"""Guard the narrow EPRO sentinel repair against changing genuine PTH pads."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair_smd', ROOT / 'tools/repair_easyeda_smd.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class RepairTests(unittest.TestCase):
    def archive(self, directory, hole=.03937, layer=1):
        path = Path(directory) / 'input.epro'
        pad = ['PAD', 'pad1', 0, '', layer, '1', 0, 0, 0, ['ROUND', hole, hole], ['RECT', 20, 20]]
        footprint = [['DOCTYPE', 'FOOTPRINT', '1.8'], ['HEAD', {'uuid': 'fp'}], pad]
        pcb = [['DOCTYPE', 'PCB', '1.8'], ['COMPONENT', 'comp', 0, 2, 10, 10, 0, {}],
               ['ATTR', 'ref', 0, 'comp', 0, 0, 0, 'Designator', 'R1'],
               ['ATTR', 'fp', 0, 'comp', 0, 0, 0, 'Footprint', 'fp'],
               ['PAD_NET', 'comp', '1', 'GND']]
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('project.json', json.dumps({'devices': {}}))
            z.writestr('FOOTPRINT/fp.efoo', '\n'.join(map(json.dumps, footprint)))
            z.writestr('PCB/board.epcb', '\n'.join(map(json.dumps, pcb)))
        return path

    def test_verified_sentinel_uses_component_side_and_net(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = repair.source_components(self.archive(tmp))
        self.assertEqual(data['R1']['side'], 2)
        self.assertEqual(data['R1']['nets'], {'1': 'GND'})

    def test_real_drill_or_multilayer_pad_is_rejected(self):
        for kwargs in ({'hole': 20}, {'layer': 12}, {'hole': 0}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError, 'sentinel pattern'):
                    repair.source_components(self.archive(tmp, **kwargs))

    def test_conversion_preserves_quoted_parentheses_and_pad_net(self):
        text = '''(kicad_pcb (version 20260206) (generator_version "10.0")
        (footprint "part (one)" (pad "1" thru_hole rect (net "A(1)")))
        (segment (start 0 0) (end 1 1) (net "A(1)"))
        (zone (net "A(1)")) (embedded_fonts no))'''
        result, removed = repair.to_unrouted_v9(text)
        self.assertEqual(removed, {'segment': 1, 'zone': 1})
        self.assertIn('(version 20241229)', result)
        self.assertIn('(net 1 "A(1)")', result)
        self.assertIn('(footprint "part (one)" (pad "1" thru_hole rect (net 1 "A(1)")))', result)
        self.assertNotIn('(segment', result)
        list(repair.expressions(result))

    def test_unbalanced_input_is_rejected(self):
        with self.assertRaises(ValueError):
            list(repair.expressions('(kicad_pcb (footprint "x")'))


if __name__ == '__main__':
    unittest.main()
