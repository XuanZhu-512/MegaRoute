"""Pinned, CPU-only TraceMaker CLI backend; KiCad remains the evaluator."""
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .cases import fingerprints, sha256


BENCH = Path(__file__).resolve().parents[2]
DEFAULT_TOOLCHAIN = BENCH / 'configs/tracemaker-toolchain.json'
ROUTING_BLOCKS = {'segment', 'arc', 'via'}


def probe_tracemaker(executable=None, toolchain=DEFAULT_TOOLCHAIN):
    lock_path = Path(toolchain)
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    if lock.get('schema_version') != '1.0':
        raise ValueError('invalid TraceMaker toolchain schema')
    configured = Path(lock['executable'])
    if not configured.is_absolute():
        configured = lock_path.resolve().parent / configured
    path = Path(executable).resolve() if executable is not None else configured.resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f'TraceMaker executable unavailable: {path}; see docs/TRACEMAKER.md')
    digest = sha256(path)
    pinned = path == configured.resolve()
    if pinned and digest != lock.get('sha256'):
        raise RuntimeError('TraceMaker executable hash does not match the toolchain lock')
    proc = subprocess.run([str(path), 'version'], capture_output=True, text=True, timeout=15, check=False)
    match = re.search(r'\b(\d+\.\d+\.\d+)\b', proc.stdout)
    if proc.returncode or not match or match[1] != lock['exact_version']:
        raise RuntimeError(f'TraceMaker version mismatch: expected {lock["exact_version"]}, '
                           f'got {proc.stdout.strip()!r}; {proc.stderr.strip()}')
    return {'executable': str(path), 'version': match[1], 'executable_sha256': digest,
            'source_commit': lock['source_commit'] if pinned else None,
            'matches_toolchain_binary': pinned, 'toolchain': str(lock_path.resolve())}


def board_blocks(path):
    """File-preservation check only; geometry and scoring come from pcbnew.

    TraceMaker's native editor preserves input expressions and appends copper.
    Requiring the same opaque blocks guards placement, net assignments, rules,
    outlines, and existing copper, including fields the adapter does not know.
    """
    text = Path(path).read_text(encoding='utf-8')
    stack, blocks = [], []
    root = None
    roots = 0
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        token = match.group()
        if token == '(':
            if not stack:
                roots += 1
            stack.append([match.start(), None])
        elif token == ')':
            if not stack:
                raise ValueError('unbalanced TraceMaker PCB output')
            start, kind = stack.pop()
            if len(stack) == 1:
                blocks.append((kind, text[start:match.end()]))
        else:
            if not stack:
                raise ValueError('data outside the KiCad board expression')
            if stack[-1][1] is None:
                stack[-1][1] = token
                if len(stack) == 1:
                    root = token
    if stack or roots != 1 or root != 'kicad_pcb':
        raise ValueError('invalid TraceMaker PCB root')
    return blocks


def verify_preserved_input(original, routed):
    before, after = board_blocks(original), board_blocks(routed)
    immutable_before = Counter(block for block in before if block[0] not in ROUTING_BLOCKS)
    immutable_after = Counter(block for block in after if block[0] not in ROUTING_BLOCKS)
    if immutable_before != immutable_after:
        changed = sorted({kind for kind, _ in (immutable_before - immutable_after)} |
                         {kind for kind, _ in (immutable_after - immutable_before)})
        raise RuntimeError(f'TraceMaker changed immutable board objects: {", ".join(changed)}')
    copper_before = Counter(block for block in before if block[0] in ROUTING_BLOCKS)
    copper_after = Counter(block for block in after if block[0] in ROUTING_BLOCKS)
    if copper_before - copper_after:
        raise RuntimeError('TraceMaker removed or changed existing fixed copper')
    return {'immutable_blocks_preserved': sum(immutable_before.values()),
            'fixed_copper_blocks_preserved': sum(copper_before.values()),
            'added_copper_blocks': sum((copper_after - copper_before).values())}


def tracemaker_command(executable, board, output, summary, timeout, threads=1, variants=1, seed=1):
    for name, value in [('threads', threads), ('variants', variants)]:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
            raise ValueError(f'TraceMaker {name} must be an integer in [1, 8]')
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ValueError('TraceMaker seed must be a uint64')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('TraceMaker routing timeout must be positive and finite')
    # --time is per variant. Account for sequential waves and leave time for
    # input loading, legalisation, optimisation and saving within the watchdog.
    internal = (timeout - min(10., timeout * .2)) / math.ceil(variants / threads)
    return [str(executable), 'route', str(board), '-o', str(output), '--json', str(summary),
            '--time', format(internal, '.12g'), '--threads', str(threads),
            '--variants', str(variants), '--seed', str(seed), '--no-gpu', '--no-kb',
            '--component-rules', 'off']


def route_tracemaker(case, out, budget, executable=None, threads=1, variants=1, seed=1,
                     toolchain=DEFAULT_TOOLCHAIN):
    identity = probe_tracemaker(executable, toolchain)
    out = Path(out).resolve()
    work = out / 'work' / 'tracemaker'
    routed = out / 'routed'
    work.mkdir(parents=True, exist_ok=True)
    routed.mkdir(parents=True, exist_ok=True)
    destination = routed / case.board.name
    if destination.exists():
        raise ValueError('TraceMaker output must not already exist')
    # Preserve project/rule basenames for the subsequent external KiCad judge.
    shutil.copy2(case.project, routed / case.project.name)
    if case.custom_rules:
        shutil.copy2(case.custom_rules, routed / case.custom_rules.name)
    command = tracemaker_command(identity['executable'], case.board.resolve(), destination,
                                work / 'summary.json', budget.routing_seconds, threads, variants, seed)
    initial = fingerprints(case)
    record = {**identity, 'command': command, 'threads': threads, 'variants': variants,
              'seed': seed, 'gpu': False, 'knowledge_base': False,
              'routing_seconds': budget.routing_seconds, 'input_hashes': initial}
    started = time.perf_counter()
    stdout = stderr = ''
    try:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, cwd=work,
                                  timeout=budget.routing_seconds, check=False)
            stdout, stderr = proc.stdout, proc.stderr
            record['returncode'] = proc.returncode
        except subprocess.TimeoutExpired as exc:
            def decoded(value):
                return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
            stdout, stderr = decoded(exc.stdout), decoded(exc.stderr)
            record.update(timed_out=True, returncode=None)
            raise RuntimeError(f'TraceMaker timed out after {budget.routing_seconds}s; '
                               'incomplete output is not accepted') from exc
        if fingerprints(case) != initial:
            raise RuntimeError('TraceMaker modified its input snapshot or rules')
        if proc.returncode not in (0, 3):
            raise RuntimeError(f'TraceMaker failed ({proc.returncode}): {stderr.strip()}')
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError(f'TraceMaker produced no board (exit {proc.returncode})')
        sidecars = [case.project] + ([case.custom_rules] if case.custom_rules else [])
        if any((routed / path.name).read_bytes() != path.read_bytes() for path in sidecars):
            raise RuntimeError('TraceMaker changed output project/rules')
        record['preservation'] = verify_preserved_input(case.board, destination)
        # The CLI's route summary is diagnostic. Final success comes from KiCad.
        record['partial_result'] = proc.returncode == 3
        record['status'] = 'output_verified'
    except Exception as exc:
        record.update(status='error', error=str(exc))
        raise
    finally:
        record['wall_s'] = time.perf_counter() - started
        (work / 'stdout.log').write_text(stdout, encoding='utf-8')
        (work / 'stderr.log').write_text(stderr, encoding='utf-8')
        (work / 'tracemaker_run.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record
