"""Average per-board external metrics, including evaluated unsuccessful routes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics

ALGORITHMS = ('megaroute', 'freerouting', 'krt')


def aggregate(root):
    cases = sorted(p for p in root.iterdir() if p.is_dir() and any((p / a).is_dir() for a in ALGORITHMS))
    output = {
        'schema_version': '1.0',
        'dataset': root.name,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'board_count': len(cases),
        'policy': {
            'source': '<case>/<algorithm>/evaluation/metrics.json',
            'included': 'All completed external evaluations, including unsuccessful routes',
            'average': 'Unweighted arithmetic mean over boards with a finite value for each metric',
            'boolean_metrics': 'Mean of 0/1 values; success and clean_pass are rates among evaluated boards',
            'missing_metrics': 'Excluded, never replaced with zero; see metric_sample_counts',
            'drc_exit_code': 'Included as requested, but its mean is a process-status statistic, not route quality',
        },
        'algorithms': {},
    }
    for algorithm in ALGORITHMS:
        statuses = Counter()
        rows = []
        missing = []
        invalid = []
        for case in cases:
            manifest = case / algorithm / 'manifest.json'
            if not manifest.is_file():
                statuses['not_run'] += 1
                missing.append(case.name)
                continue
            try:
                state = json.loads(manifest.read_text())
                status = state.get('status', 'unknown')
                statuses[status] += 1
                path = case / algorithm / 'evaluation/metrics.json'
                if status != 'complete' or not path.is_file():
                    missing.append(case.name)
                    continue
                metrics = json.loads(path.read_text())
                if metrics.get('backend') != algorithm or metrics.get('case_id') != state.get('case_id'):
                    raise ValueError('metric identity does not match manifest')
                rows.append(metrics)
            except (OSError, ValueError) as exc:
                invalid.append({'case_id': case.name, 'error': str(exc)})
        fields = sorted({k for row in rows for k, v in row.items() if isinstance(v, (int, float))})
        values = {k: [float(row[k]) for row in rows if isinstance(row.get(k), (int, float))
                       and math.isfinite(row[k])] for k in fields}
        output['algorithms'][algorithm] = {
            'status_counts': dict(statuses),
            'evaluated_count': len(rows),
            'unevaluated_count': len(cases) - len(rows),
            'clean_pass_count': sum(row.get('clean_pass') is True for row in rows),
            'success_count': sum(row.get('success') is True for row in rows),
            'averages': {k: statistics.fmean(v) if v else None for k, v in values.items()},
            'metric_sample_counts': {k: len(v) for k, v in values.items()},
            'unevaluated_cases': missing,
            'invalid_metric_files': invalid,
        }
    target = root / 'eval.json'
    temporary = root / 'eval.json.tmp'
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(target)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', nargs='*', type=Path, default=[Path('results/D3-A'), Path('results/D3-B')])
    for root in parser.parse_args().roots:
        result = aggregate(root)
        print(root / 'eval.json')
        for name, metrics in result['algorithms'].items():
            print(f"  {name}: {metrics['evaluated_count']}/{result['board_count']} evaluated")
