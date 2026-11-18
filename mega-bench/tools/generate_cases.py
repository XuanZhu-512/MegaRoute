"""Generate neutral JSON fixtures or reproducible synthetic boards. No EDA parser."""
import argparse
import hashlib
import json
from pathlib import Path


def base(layers=2, size=10):
    return dict(schema_version="1.0", units="mm", layers=layers,
                outline=[[0, 0], [size, 0], [size, size], [0, size]], holes=[],
                rules=dict(min_width=.2, clearance=.2, edge_clearance=.2,
                           via_diameter=.6, via_drill=.3, min_annular=.1),
                nets=[], pads=[], fixed_copper=[], keepouts=[])


def pad(id_, net, x, y, layer=0):
    return dict(id=id_, net=net, kind="circle", center=[x, y], radius=.3, layers=[layer])


def fixture(name):
    b = base()
    b['nets'] = [dict(id='A')]
    b['pads'] = [pad('a', 'A', 1, 5), pad('b', 'A', 9, 5)]
    if name == 'two_net':
        b['pads'] = [pad('a', 'A', 1, 2), pad('b', 'A', 9, 2),
                     pad('c', 'B', 1, 8), pad('d', 'B', 9, 8)]
        b['nets'].append(dict(id='B'))
    elif name in ('obstacle', 'blocked', 'multilayer'):
        ys = (3, 7) if name == 'obstacle' else (0, 10)
        b['keepouts'] = [dict(id='wall', points=[[4, ys[0]], [6, ys[0]],
                                                   [6, ys[1]], [4, ys[1]]],
                              layers=[0] if name == 'multilayer' else [0, 1])]
    elif name == 'multi_terminal':
        b['pads'].append(pad('c', 'A', 5, 8))
    elif name == 'fixed':
        b['fixed_copper'] = [dict(id='existing', net='A', kind='segment',
                                  a=[1, 5], b=[9, 5], width=.2, layers=[0])]
    elif name != 'straight':
        raise ValueError(f'unknown fixture {name}')
    return b


def synthetic(n, layers, size, rho, seed):
    import numpy as np
    if n <= 0 or layers not in (2, 4, 6) or size < 4 or rho not in (0., .1):
        raise ValueError('invalid generation parameters')
    rng = np.random.Generator(np.random.PCG64(seed))
    b = base(layers, size)
    half = size * rho**.5 / 2
    lo, hi = size/2-half, size/2+half
    if rho:
        b['keepouts'] = [dict(id='central_keepout', points=[[lo, lo], [hi, lo], [hi, hi], [lo, hi]], layers=list(range(layers)))]
    positions = []
    attempts = 0
    while len(positions) < 2*n and attempts < 10000*n:
        attempts += 1
        x, y = float(rng.uniform(1, size-1)), float(rng.uniform(1, size-1))
        z = int(rng.choice([0, layers-1]))
        # Expanded rectangle conservatively reserves the entire pad, not its center.
        if rho and lo-.3 <= x <= hi+.3 and lo-.3 <= y <= hi+.3:
            continue
        if any((x-px)**2+(y-py)**2 < .8**2 for px, py, _ in positions):
            continue
        positions.append((x, y, z))
    if len(positions) != 2*n:
        raise RuntimeError(f'generation_failed: seed={seed}, attempts={attempts}')
    indices = rng.permutation(2*n).tolist()
    for i in range(n):
        net = f'N{i}'
        b['nets'].append(dict(id=net))
        for p in indices[2*i:2*i+2]:
            b['pads'].append(pad(f'P{p}', net, *positions[p]))
    b['metadata'] = dict(generator='pcg64-v1', numpy_version=np.__version__, seed=seed,
                         n=n, size=size, rho=rho, attempts=attempts,
                         split='development' if seed < 5 else 'evaluation')
    return b


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--fixture', choices=['straight', 'two_net', 'obstacle', 'blocked', 'multilayer', 'multi_terminal', 'fixed'])
    p.add_argument('--nets', type=int, default=20)
    p.add_argument('--layers', type=int, default=2)
    p.add_argument('--size', type=float, default=50)
    p.add_argument('--rho', type=float, default=0)
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args()
    b = fixture(args.fixture) if args.fixture else synthetic(args.nets, args.layers, args.size, args.rho, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(b, indent=2) + '\n'
    args.out.write_text(payload, encoding='utf-8')
    print(json.dumps(dict(path=str(args.out), sha256=hashlib.sha256(payload.encode()).hexdigest())))


if __name__ == '__main__':
    main()
