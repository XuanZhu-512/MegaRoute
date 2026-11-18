import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

exe, root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(root / 'tools'))
from generate_cases import fixture


def run(*args, expected=0):
    p = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, timeout=90)
    assert p.returncode == expected, (args, p.returncode, p.stdout, p.stderr)
    return json.loads(p.stdout if p.stdout.strip() else p.stderr)


with tempfile.TemporaryDirectory(prefix='pcb-bench-test-') as tmp:
    tmp = Path(tmp)
    board, config = tmp/'board.json', tmp/'config.json'
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='adaptive_strict', time_limit_s=20, max_expanded_nodes=100000)))
    for name in ('straight', 'two_net', 'obstacle', 'multilayer', 'multi_terminal', 'fixed'):
        board.write_text(json.dumps(fixture(name)))
        run('validate', '--board', board)
        out = tmp/name
        m = run('route', '--board', board, '--config', config, '--out', out, '--events')
        assert m['DRC'] == 0 and m['C_routed'] == m['C_total'], (name, m)
        checked = run('check', '--board', out/'board.json', '--routes', out/'routes.json')
        assert checked['C_routed'] == m['C_routed']
        if name == 'multilayer':
            assert m['VC'] >= 2
        if name == 'fixed':
            assert m['C_total'] == 0 and m['WL_mm'] == 0 and m['R'] is None
    # Determinism and the required 1 mil baseline.
    board.write_text(json.dumps(fixture('two_net')))
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='baseline_fixed_strict')))
    for name in ('baseline1', 'baseline2'):
        run('route', '--board', board, '--config', config, '--out', tmp/name)
    assert (tmp/'baseline1/routes.json').read_bytes() == (tmp/'baseline2/routes.json').read_bytes()
    # Whole-segment DRC must detect crossing a keepout, even with legal endpoints.
    board.write_text(json.dumps(fixture('obstacle')))
    routes = tmp/'bad_routes.json'
    routes.write_text(json.dumps(dict(schema_version='1.0', copper=[dict(id='bad', net='A', kind='segment', a=[1,5], b=[9,5], width=.2, layers=[0])])))
    m = run('check', '--board', board, '--routes', routes, expected=2)
    assert any(v['rule'] == 'keepout' for v in m['violations'])
    # Reject bad schema, unknown fields and silently unsupported algorithm modes.
    bad = fixture('straight'); bad['schema_version'] = '9'; board.write_text(json.dumps(bad))
    run('validate', '--board', board, expected=1)
    bad = fixture('straight'); bad['pads'][0]['net'] = 'missing'; board.write_text(json.dumps(bad))
    run('validate', '--board', board, expected=1)
    bad = fixture('straight'); bad['rules']['differential_pair'] = True; board.write_text(json.dumps(bad))
    run('validate', '--board', board, expected=1)
    board.write_text(json.dumps(fixture('straight')))
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='megaroute_full')))
    run('route', '--board', board, '--config', config, '--out', tmp/'unsupported', expected=1)
    # A resource cap is a diagnosed partial result, never a false success.
    board.write_text(json.dumps(fixture('blocked')))
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='adaptive_strict', max_expanded_nodes=1)))
    m = run('route', '--board', board, '--config', config, '--out', tmp/'limited', expected=2)
    assert m['C_routed'] == 0 and m['search_failures'][0]['reason'] == 'node_limit'
    # Exhausted finite search and elapsed-time exhaustion have distinct diagnoses.
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='adaptive_strict', time_limit_s=20)))
    m = run('route', '--board', board, '--config', config, '--out', tmp/'exhausted', expected=2)
    assert m['search_failures'][0]['reason'] == 'search_exhausted'
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='adaptive_strict', time_limit_s=1e-9)))
    m = run('route', '--board', board, '--config', config, '--out', tmp/'timed', expected=2)
    assert m['termination_reason'] == 'timeout'
    # An obstacle whose ID resembles an internal search label is still checked.
    b = fixture('straight')
    b['nets'].append(dict(id='B'))
    b['pads'].append(dict(id='__candidate__', net='B', kind='polygon',
                         center=[5,5], points=[[4,4],[6,4],[6,6],[4,6]], layers=[0]))
    b['holes'] = [[[7,7],[8,7],[8,8],[7,8]]]
    board.write_text(json.dumps(b))
    config.write_text(json.dumps(dict(schema_version='1.0', algorithm='adaptive_strict')))
    m = run('route', '--board', board, '--config', config, '--out', tmp/'polygon')
    assert m['DRC'] == 0
    # Fixed-input violations must not be presented as a clean routed board.
    b = fixture('straight'); b['pads'][0]['center'] = [.1,5]
    board.write_text(json.dumps(b))
    run('validate', '--board', board, expected=2)
    m = run('route', '--board', board, '--config', config, '--out', tmp/'bad_input', expected=2)
    assert m['termination_reason'] == 'input_drc_violations' and m['fixed_input_DRC'] > 0
print('CLI integration checks passed')
