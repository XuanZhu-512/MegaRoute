"""TraceMaker process contracts; fake CLIs never stand in for KiCad scores."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
from pcb_bench.cases import fingerprints
from pcb_bench.cli import main
from pcb_bench.contracts import KiCadCase, RunBudget
from pcb_bench.runner import recorded_algorithm
from pcb_bench.tracemaker_backend import (probe_tracemaker, route_tracemaker, sha256,
                                         tracemaker_command, verify_preserved_input)

FAKE = '''#!PYTHON
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
if args == ['version']:
    print('tracemaker ' + os.environ.get('FAKE_TM_VERSION', '0.12.1'))
    raise SystemExit(0)
mode = os.environ.get('FAKE_TM_MODE', 'partial')
if mode == 'timeout':
    print('routing started', flush=True)
    time.sleep(10)
if mode == 'missing':
    raise SystemExit(3)
source = Path(args[1])
text = source.read_text()
if mode == 'mutate_input':
    source.write_text(text + '\\n')
if mode == 'move':
    text = text.replace('(at 1 2)', '(at 9 9)')
if mode == 'remove_copper':
    text = text.replace('(segment (start 0 0) (end 1 1))', '')
output = Path(args[args.index('-o') + 1])
output.write_text(text.rstrip()[:-1] + '\\n(segment (start 1 1) (end 2 2))\\n)\\n')
if mode == 'change_rules':
    output.with_suffix('.kicad_pro').write_text('{"changed": true}')
summary = Path(args[args.index('--json') + 1])
summary.write_text(json.dumps({'completion_pct': 50}))
raise SystemExit(1 if mode == 'error' else 0 if mode == 'complete' else 3)
'''


class TraceMakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='TraceMaker tests ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exe = self.root / 'router'
        self.exe.write_text(FAKE.replace('PYTHON', sys.executable, 1))
        self.exe.chmod(0o755)
        self.board = self.root / 'board.kicad_pcb'
        self.board.write_text('(kicad_pcb (version 20241229) '
                              '(footprint "part (A)" (at 1 2) (pad "1" smd rect (net 1 "A"))) '
                              '(segment (start 0 0) (end 1 1)))\n')
        self.project = self.board.with_suffix('.kicad_pro')
        self.project.write_text('{}')
        self.rules = self.board.with_suffix('.kicad_dru')
        self.rules.write_text('(version 1)')
        self.case = KiCadCase('case1', self.board, self.project, self.rules)
        self.lock = self.root / 'toolchain.json'
        self.lock.write_text(json.dumps({'schema_version': '1.0', 'executable': 'router',
                                        'exact_version': '0.12.1', 'source_commit': 'abc',
                                        'sha256': sha256(self.exe)}))
        self.out = self.root / 'results'

    def run_router(self, mode='partial', seconds=5):
        with patch.dict('os.environ', {'FAKE_TM_MODE': mode}):
            return route_tracemaker(self.case, self.out, RunBudget(seconds, 1), toolchain=self.lock)

    def test_partial_output_is_evaluatable_and_sidecars_are_unchanged(self):
        original = fingerprints(self.case)
        result = self.run_router()
        self.assertEqual(result['returncode'], 3)
        self.assertTrue(result['partial_result'])
        self.assertEqual(result['preservation']['added_copper_blocks'], 1)
        self.assertEqual(fingerprints(self.case), original)
        self.assertEqual((self.out / 'routed/board.kicad_pro').read_bytes(), self.project.read_bytes())
        self.assertEqual((self.out / 'routed/board.kicad_dru').read_bytes(), self.rules.read_bytes())
        self.assertTrue((self.out / 'work/tracemaker/summary.json').is_file())

    def test_complete_exit_is_accepted(self):
        result = self.run_router('complete')
        self.assertFalse(result['partial_result'])
        self.assertEqual(result['status'], 'output_verified')

    def test_missing_output_and_failure_are_not_successful_passthroughs(self):
        for mode, pattern in [('missing', 'no board'), ('error', 'failed')]:
            with self.subTest(mode=mode):
                self.out = self.root / mode
                with self.assertRaisesRegex(RuntimeError, pattern):
                    self.run_router(mode)
                record = json.loads((self.out / 'work/tracemaker/tracemaker_run.json').read_text())
                self.assertEqual(record['status'], 'error')

    def test_moved_footprint_changed_input_and_removed_fixed_copper_rejected(self):
        for mode, pattern in [('move', 'immutable'), ('remove_copper', 'fixed copper'),
                              ('change_rules', 'output project/rules'),
                              ('mutate_input', 'modified its input')]:
            with self.subTest(mode=mode):
                self.out = self.root / mode
                with self.assertRaisesRegex(RuntimeError, pattern):
                    self.run_router(mode)

    def test_timeout_logs_diagnostics_and_does_not_copy_input_as_output(self):
        with self.assertRaisesRegex(RuntimeError, 'timed out'):
            self.run_router('timeout', seconds=.2)
        record = json.loads((self.out / 'work/tracemaker/tracemaker_run.json').read_text())
        self.assertTrue(record['timed_out'])
        self.assertIn('routing started', (self.out / 'work/tracemaker/stdout.log').read_text())
        self.assertFalse((self.out / 'routed/board.kicad_pcb').exists())

    def test_hash_version_and_missing_executable_are_checked(self):
        with patch.dict('os.environ', {'FAKE_TM_VERSION': '0.12.2'}):
            with self.assertRaisesRegex(RuntimeError, 'version mismatch'):
                probe_tracemaker(toolchain=self.lock)
        self.exe.write_text(self.exe.read_text() + '\n')
        with self.assertRaisesRegex(RuntimeError, 'hash'):
            probe_tracemaker(toolchain=self.lock)
        self.exe.unlink()
        with self.assertRaises(FileNotFoundError):
            probe_tracemaker(toolchain=self.lock)

    def test_unknown_override_does_not_claim_pinned_source_commit(self):
        alternate = self.root / 'alternate'
        alternate.write_bytes(self.exe.read_bytes())
        alternate.chmod(0o755)
        result = probe_tracemaker(alternate, self.lock)
        self.assertIsNone(result['source_commit'])
        self.assertFalse(result['matches_toolchain_binary'])

    def test_wallclock_accounts_for_variant_waves_and_rejects_invalid_options(self):
        command = tracemaker_command(self.exe, self.board, self.out, self.root / 'summary',
                                      100, threads=1, variants=2)
        self.assertEqual(float(command[command.index('--time') + 1]), 45)
        self.assertIn('--no-kb', command)
        self.assertIn('--no-gpu', command)
        self.assertNotIn('--reroute', command)
        for kwargs in [{'threads': 0}, {'variants': 9}, {'seed': -1}, {'seed': True}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                tracemaker_command(self.exe, self.board, self.out, self.root / 'summary', 100, **kwargs)

    def test_invalid_or_extra_board_roots_rejected(self):
        invalid = self.root / 'invalid.kicad_pcb'
        for text in ['(kicad_pcb', '(kicad_pcb) (kicad_pcb)', '(other)', '(kicad_pcb) junk']:
            invalid.write_text(text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                verify_preserved_input(self.board, invalid)

    def test_cli_uses_tracemaker_dispatch_and_identity(self):
        self.assertEqual(recorded_algorithm('tracemaker'), 'tracemaker')
        self.assertEqual(recorded_algorithm('krt'), 'krt')
        with patch('pcb_bench.cli.execute_run', return_value={'backend': 'tracemaker'}) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(['run', '--case', 'case.json', '--backend', 'tracemaker',
                               '--out', 'output', '--toolchain', 'lock.json',
                               '--kicad-python', sys.executable, '--expected-version', '9.0.8',
                               '--tracemaker-threads', '2', '--tracemaker-variants', '4',
                               '--tracemaker-seed', '12'])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_args.args[1], 'tracemaker')
        self.assertEqual(run.call_args.kwargs['tracemaker_variants'], 4)
        self.assertEqual(run.call_args.kwargs['tracemaker_seed'], 12)

    def test_aggregation_includes_fourth_backend(self):
        spec = importlib.util.spec_from_file_location('aggregate', ROOT / 'tools/aggregate_results.py')
        aggregate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(aggregate)
        run = self.root / 'batch/case1/tracemaker'
        (run / 'evaluation').mkdir(parents=True)
        (run / 'manifest.json').write_text(json.dumps({'case_id': 'case1', 'status': 'complete'}))
        (run / 'evaluation/metrics.json').write_text(json.dumps({'case_id': 'case1', 'backend': 'tracemaker',
                                                               'routability': .5, 'success': False}))
        result = aggregate.aggregate(self.root / 'batch')
        self.assertEqual(result['algorithms']['tracemaker']['evaluated_count'], 1)
        self.assertEqual(result['algorithms']['tracemaker']['averages']['routability'], .5)


if __name__ == '__main__':
    unittest.main()
