"""Repair this EasyEDA project's sentinel-hole SMD pads without moving copper.

Run with the matching KiCad 9 pcbnew Python. Original files are archived under
OUT/original; the generated board is unrouted and uses KiCad's native writer.
Only the observed ROUND 0.03937 mil, top-layer library pads are accepted.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


def expressions(text):
    """Yield balanced top-level expression spans, respecting quoted strings."""
    stack = []
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+', text):
        token = match.group()
        if token == '(':
            stack.append([match.start(), None])
        elif token == ')':
            if not stack:
                raise ValueError('Unmatched closing parenthesis')
            start, kind = stack.pop()
            if len(stack) == 1:
                yield kind, start, match.end()
        elif stack and stack[-1][1] is None:
            stack[-1][1] = token
    if stack:
        raise ValueError('Unclosed expression')


def documents(text):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row[0] == 'DOCTYPE':
            result.append([])
        result[-1].append(row)
    return result


def source_components(path):
    libraries = {}
    with zipfile.ZipFile(path) as archive:
        project = json.loads(archive.read('project.json'))
        pcb_files = [n for n in archive.namelist() if n.endswith('.epcb')]
        if len(pcb_files) != 1:
            raise ValueError('Expected exactly one PCB in EPRO')
        pcb = None
        for name in [n for n in archive.namelist() if n.endswith('.efoo')] + pcb_files:
            for doc in documents(archive.read(name).decode('utf-8')):
                if doc[0][1] == 'FOOTPRINT':
                    head = next(r[1] for r in doc if r[0] == 'HEAD')
                    libraries[head['uuid']] = [r for r in doc if r[0] == 'PAD']
                elif doc[0][1] == 'PCB':
                    pcb = doc
        if pcb is None:
            raise ValueError('No PCB document found')
        attrs = defaultdict(dict)
        nets = defaultdict(dict)
        for row in pcb:
            if row[0] == 'ATTR' and row[3]:
                attrs[row[3]][row[7]] = row[8]
            elif row[0] == 'PAD_NET':
                nets[row[1]][row[2]] = row[3]
        result = {}
        for row in pcb:
            if row[0] != 'COMPONENT':
                continue
            data = attrs[row[1]]
            reference = data['Designator']
            footprint = data.get('Footprint') or project['devices'][data['Device']]['attributes']['Footprint']
            pads = libraries[footprint]
            if reference in result or row[3] not in (1, 2):
                raise ValueError('Duplicate reference or unsupported component layer')
            for pad in pads:
                hole = pad[9]
                if (pad[4] != 1 or not isinstance(hole, list) or len(hole) != 3
                        or hole[0] != 'ROUND' or any(abs(v - .03937) > 1e-9 for v in hole[1:])):
                    raise ValueError(f'{reference}: pad does not match the verified SMD sentinel pattern')
            result[reference] = {'side': row[3], 'pads': pads, 'nets': nets[row[1]]}
        return result


def to_unrouted_v9(text):
    if '(version 20260206)' not in text:
        raise ValueError('Expected the inspected KiCad 10 format (20260206)')
    spans = list(expressions(text))
    removed = Counter()
    parts, last = [], 0
    for kind, start, end in spans:
        if kind in {'segment', 'arc', 'via', 'zone'}:
            parts.append(text[last:start])
            last = end
            removed[kind] += 1
    parts.append(text[last:])
    unrouted = ''.join(parts)
    assert [text[a:b] for k, a, b in spans if k not in removed] == [
        unrouted[a:b] for _, a, b in expressions(unrouted)]
    names = list(dict.fromkeys(re.findall(r'\(net ("(?:\\.|[^"\\])*")\)', unrouted)))
    codes = {name: i + 1 for i, name in enumerate(n for n in names if n != '""')}
    candidate = re.sub(r'\(net ("(?:\\.|[^"\\])*")\)',
                       lambda m: f'(net {codes.get(m[1], 0)} {m[1]})', unrouted)
    candidate = candidate.replace('(version 20260206)', '(version 20241229)', 1)
    candidate = candidate.replace('(generator_version "10.0")', '(generator_version "9.0")', 1)
    for kind in ('covering', 'plugging'):
        candidate = re.sub(r'\(' + kind + r'\s+\(front no\)\s+\(back no\)\s*\)', '', candidate)
    for field in ('(capping no)', '(filling no)', '(duplicate_pad_numbers_are_jumpers no)'):
        candidate = candidate.replace(field, '')
    candidate = re.sub(r'\(tenting\s+\(front yes\)\s+\(back yes\)\s*\)',
                       '(tenting front back)', candidate)
    pos = next(a for k, a, _ in expressions(candidate) if k == 'footprint')
    declarations = '\n'.join(f'(net {code} {name})' for name, code in codes.items())
    return candidate[:pos] + declarations + '\n' + candidate[pos:], dict(removed)


def pad_signature(pad):
    # Deliberately exclude the three repaired fields: attribute, drill, layers.
    return (pad.m_Uuid.AsString(), pad.GetParentFootprint().GetReference(),
            pad.GetNumber(), pad.GetNetname(), pad.GetPosition().x, pad.GetPosition().y,
            pad.GetOrientationDegrees(), pad.GetSize().x, pad.GetSize().y, pad.GetShape())


def repair(pcb, project, epro, out):
    import pcbnew as p
    if p.Version() != '9.0.8':
        raise ValueError('This conversion is validated with KiCad 9.0.8 only')
    expected = source_components(epro)
    raw = pcb.read_bytes()
    candidate, removed = to_unrouted_v9(raw.decode('utf-8'))
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='d3c-repair-') as tmp:
        tmp = Path(tmp)
        board_path = tmp / 'data.kicad_pcb'
        project_path = tmp / 'data.kicad_pro'
        board_path.write_text(candidate)
        shutil.copy2(project, project_path)
        board = p.LoadBoard(str(board_path))
        if board is None:
            raise ValueError('KiCad could not load the converted candidate')
        footprints = list(board.GetFootprints())
        if set(expected) != {f.GetReference() for f in footprints}:
            raise ValueError('EPRO and KiCad component references differ')
        before = sorted(pad_signature(pad) for pad in board.GetPads())
        placements = [(f.m_Uuid.AsString(), f.GetPosition().x, f.GetPosition().y,
                       f.GetOrientationDegrees(), f.GetLayer()) for f in footprints]
        for footprint in footprints:
            ref = footprint.GetReference()
            source = expected[ref]
            side = p.F_Cu if source['side'] == 1 else p.B_Cu
            if footprint.GetLayer() != side:
                raise ValueError(f'{ref}: component side differs from EPRO')
            pads = list(footprint.Pads())
            if Counter(x.GetNumber() for x in pads) != Counter(x[5] for x in source['pads']):
                raise ValueError(f'{ref}: pad numbers differ from EPRO')
            for pad in pads:
                if pad.GetNetname() != source['nets'].get(pad.GetNumber(), ''):
                    raise ValueError(f'{ref}.{pad.GetNumber()}: net differs from EPRO')
                if (pad.GetAttribute() != p.PAD_ATTRIB_PTH
                        or pad.GetDrillSize().x != p.FromMM(.001)
                        or pad.GetDrillSize().y != p.FromMM(.001)):
                    raise ValueError(f'{ref}: unexpected imported pad definition')
                mask = p.LSET()
                for layer in (side, p.F_Mask if side == p.F_Cu else p.B_Mask,
                              p.F_Paste if side == p.F_Cu else p.B_Paste):
                    mask.AddLayer(layer)
                pad.SetAttribute(p.PAD_ATTRIB_SMD)
                pad.SetDrillSize(p.VECTOR2I(0, 0))
                pad.SetLayerSet(mask)
        assert sorted(pad_signature(pad) for pad in board.GetPads()) == before
        assert placements == [(f.m_Uuid.AsString(), f.GetPosition().x, f.GetPosition().y,
                               f.GetOrientationDegrees(), f.GetLayer()) for f in footprints]
        p.SaveBoard(str(board_path), board)
        reload = p.LoadBoard(str(board_path))
        assert sorted(pad_signature(pad) for pad in reload.GetPads()) == before
        assert len(list(reload.GetTracks())) == 0 and len(list(reload.Zones())) == 0
        assert all(pad.GetAttribute() == p.PAD_ATTRIB_SMD and pad.GetDrillSize().x == 0
                   for pad in reload.GetPads())
        original = out / 'original'
        original.mkdir(exist_ok=True)
        sources = {'data.kicad_pcb': pcb, 'data.kicad_pro': project, 'data.epro': epro}
        hashes = {}
        for name, source in sources.items():
            destination = original / name
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if destination.exists() and destination.read_bytes() != source.read_bytes():
                raise ValueError(f'Original archive differs; refusing overwrite: {destination}')
            shutil.copy2(source, destination)
            hashes[name] = digest
        shutil.copy2(board_path, out / 'data.kicad_pcb')
        shutil.copy2(project_path, out / 'data.kicad_pro')
        manifest = {'schema_version': '1.0', 'case_id': 'D3-C', 'board': 'data.kicad_pcb',
                    'project': 'data.kicad_pro', 'copper_policy': 'preserve_input'}
        (out / 'case.json').write_text(json.dumps(manifest, indent=2) + '\n')
        report = {'original_sha256': hashes, 'kicad_version': p.Version(),
                  'footprints': len(footprints), 'pads_repaired': len(before),
                  'nets': reload.GetNetCount() - 1, 'copper_layers': reload.GetCopperLayerCount(),
                  'removed_reference_copper': removed,
                  'repair': 'EPRO-verified top-layer library SMD pads mapped to each component side; sentinel drills removed',
                  'preserved': ['component placement/side/rotation', 'pad geometry/position/rotation/UUID', 'pad numbers and nets'],
                  'routing_tested': False}
        (out / 'repair_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('pcb', 'project', 'epro', 'out'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.pcb, args.project, args.epro, args.out), ensure_ascii=False, indent=2))
