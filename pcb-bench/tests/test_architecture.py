"""Architecture tests use mock tool probes, not actual KiCad routing/evaluation."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.backends import BACKENDS
from pcb_bench.cases import load_case, snapshot, fingerprints
from pcb_bench.cli import main
from pcb_bench.contracts import UnsupportedCapability
from pcb_bench.converters import KiCadGeometryConverter
from pcb_bench.evaluation import KiCadToolchain, ExternalKiCadEvaluator
from pcb_bench.pipeline import make_plan


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Minimal byte fixtures for file contracts, not valid/evaluated KiCad boards.
        self.board = self.root / "board.kicad_pcb"
        self.board.write_text('(kicad_pcb (version 20241229))')
        self.project = self.root / "board.kicad_pro"
        self.project.write_text('{}')
        self.manifest = self.root / "case.json"
        self.data = dict(schema_version="1.0", case_id="case1", board=self.board.name,
                         project=self.project.name, copper_policy="preserve_input")
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.data))

    def test_case_requires_rules_and_kicad_format(self):
        self.project.unlink()
        with self.assertRaises(ValueError):
            load_case(self.manifest)
        self.project.write_text('{}')
        rules = self.root / 'board.kicad_dru'
        rules.write_text('(version 1)')
        with self.assertRaises(ValueError):
            load_case(self.manifest)
        self.data['custom_rules'] = rules.name
        self.save()
        self.assertEqual(load_case(self.manifest).custom_rules, rules)
        self.data['board'] = 'ir.json'
        (self.root/'ir.json').write_text('{}')
        self.save()
        with self.assertRaises(ValueError):
            load_case(self.manifest)

    def test_snapshot_preserves_original_and_refuses_overwrite(self):
        case = load_case(self.manifest)
        initial = fingerprints(case)
        copied = snapshot(case, self.root/'snapshot')
        self.assertEqual(initial, fingerprints(copied))
        self.assertEqual(initial, fingerprints(case))
        self.assertEqual(copied.board.stem, copied.project.stem)
        with self.assertRaises(ValueError):
            snapshot(case, self.root/'snapshot')

    def test_every_backend_has_same_external_evaluator(self):
        case = load_case(self.manifest)
        lock = KiCadToolchain('kicad-cli', '9.0.8')
        for backend in BACKENDS:
            plan = make_plan(case, backend, lock)
            self.assertEqual(plan['output_format'], 'kicad_pcb')
            self.assertEqual(plan['evaluator']['id'], 'external_kicad')
            self.assertEqual(plan['pipeline'][-1], 'external_kicad_evaluation')
            self.assertFalse(plan['executable'])
            with self.assertRaises(UnsupportedCapability):
                BACKENDS[backend].preflight()

    def test_converter_never_silently_passes_through(self):
        with self.assertRaises(UnsupportedCapability):
            KiCadGeometryConverter().import_board(load_case(self.manifest), self.root/'work')

    def test_version_exact_match_and_no_score_fallback(self):
        lock = KiCadToolchain('kicad-cli', '9.0.8')
        with patch('pcb_bench.evaluation.shutil.which', return_value=str(self.board)):
            with patch('pcb_bench.evaluation.subprocess.run', return_value=subprocess.CompletedProcess([],0,'9.0.9\n','')):
                with self.assertRaisesRegex(RuntimeError, 'version mismatch'):
                    lock.probe()
            with patch('pcb_bench.evaluation.subprocess.run', return_value=subprocess.CompletedProcess([],0,'9.0.8\n','')):
                self.assertEqual(lock.probe()['version'], '9.0.8')
                with self.assertRaises(UnsupportedCapability):
                    ExternalKiCadEvaluator(lock).preflight()
        with patch('pcb_bench.evaluation.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                lock.probe()

    def test_cli_plan_and_drc_command(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['plan','--case',str(self.manifest),'--backend','freerouting',
                         '--toolchain',str(ROOT/'configs/kicad-toolchain.json')])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['input_format'], 'kicad_pcb')
        evaluator = ExternalKiCadEvaluator(KiCadToolchain('kicad-cli','9.0.8'))
        cmd = evaluator.drc_command(self.board,self.root/'drc.json')
        self.assertIn('--severity-all',cmd)
        self.assertIn('--exit-code-violations',cmd)
        self.assertNotIn('--schematic-parity',cmd)


if __name__ == '__main__':
    unittest.main()
