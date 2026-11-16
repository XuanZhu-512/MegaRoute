"""Legacy geometry-IR diagnostics only; NOT the KiCad external benchmark pipeline."""
import argparse
import hashlib
import json
import platform
import subprocess
import time
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    print('Internal geometry diagnostics only; no KiCad external scoring. '
          'Use tools/bench.py for the new benchmark architecture.', file=sys.stderr)
    p = argparse.ArgumentParser()
    p.add_argument('--exe', type=Path, required=True)
    p.add_argument('--boards', type=Path, nargs='+', required=True)
    p.add_argument('--configs', type=Path, nargs='+', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--repeats', type=int, default=3)
    a = p.parse_args()
    if a.repeats < 1:
        p.error('repeats must be positive')
    if a.out.exists() and any(a.out.iterdir()):
        p.error('output directory must be empty')
    a.out.mkdir(parents=True, exist_ok=True)
    environment = dict(metrics_scope='internal_geometry_diagnostics',
                       platform=platform.platform(), cpu=platform.processor(),
                       python=platform.python_version(), executable_sha256=digest(a.exe))
    repo = Path(__file__).resolve().parents[2]
    for key, command in [('commit', ['git', 'rev-parse', 'HEAD']), ('working_tree', ['git', 'status', '--porcelain'])]:
        try:
            environment[key] = subprocess.check_output(command, cwd=repo, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            environment[key] = 'unavailable'
    (a.out/'environment.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    with (a.out/'runs.jsonl').open('w', encoding='utf-8') as summary:
        index = 0
        for board in a.boards:
            for config in a.configs:
                cfg = json.loads(config.read_text(encoding='utf-8'))
                for repeat in range(a.repeats):
                    run_dir = a.out/f'{index:05d}'
                    index += 1
                    record = dict(metrics_scope='internal_geometry_diagnostics',
                                  board=str(board), config=str(config), repeat=repeat,
                                  board_sha256=digest(board), config_sha256=digest(config), run=str(run_dir))
                    begin = time.monotonic()
                    try:
                        proc = subprocess.run([str(a.exe.resolve()), 'route', '--board', str(board.resolve()),
                                               '--config', str(config.resolve()), '--out', str(run_dir.resolve())],
                                              capture_output=True, text=True, timeout=cfg.get('time_limit_s',60)+60)
                        record.update(returncode=proc.returncode, stderr=proc.stderr)
                        if (run_dir/'metrics.json').exists():
                            record['metrics'] = json.loads((run_dir/'metrics.json').read_text())
                            record['routes_sha256'] = digest(run_dir/'routes.json')
                        else:
                            record['failure'] = 'no_verified_metrics'
                    except subprocess.TimeoutExpired:
                        record['failure'] = 'process_timeout_including_validation'
                    except OSError as error:
                        record['failure'] = str(error)
                    record['process_wall_s'] = time.monotonic()-begin
                    summary.write(json.dumps(record)+'\n')
                    summary.flush()


if __name__ == '__main__':
    main()
