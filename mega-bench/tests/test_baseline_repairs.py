"""Adapter regressions with synthetic files; no router/JVM is started."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.krt_backend import restore_krt_board, krt_arguments
from pcb_bench.freerouting_backend import protect_copper_graphics
from pcb_bench.tracemaker_backend import board_blocks


class BaselineRepairTests(unittest.TestCase):
    def test_krt_restores_source_and_maps_only_new_copper_layers(self):
        source = '''(kicad_pcb (version 20241229)
          (layers (0 "F.Cu" signal "Top") (2 "B.Cu" signal "Bottom"))
          (gr_text "Top" (layer "F.Cu") (uuid "text"))
          (segment (layer "F.Cu") (uuid "fixed")))'''
        output = '''(kicad_pcb (layers (0 "F.Cu" signal "Top") (2 "B.Cu" signal "Bottom"))
          (gr_text "Top" (layer "F.SilkS") (uuid "text"))
          (segment (layer "Top") (uuid "fixed"))
          (segment (layer "Bottom") (uuid "new"))
          (via (layers "Top" "Bottom") (uuid "v")))'''
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'in.pcb', Path(tmp)/'out.pcb'
            a.write_text(source); b.write_text(output)
            report = restore_krt_board(a, b)
            blocks = board_blocks(b)
            for block in board_blocks(a):
                self.assertIn(block, blocks)
            self.assertEqual(report['added_copper'], 2)
            self.assertIn('(layer "B.Cu")', b.read_text())
            self.assertIn('(layers "F.Cu" "B.Cu")', b.read_text())
            self.assertEqual(b.read_text().count('(uuid "fixed")'), 1)
            b.write_text(output.replace('(layer "Bottom")', '(layer "Missing")'))
            with self.assertRaisesRegex(ValueError, 'unknown KRT copper layer'):
                restore_krt_board(a, b)

    def test_krt_clearance_includes_assigned_class_board_and_local_rules(self):
        geometry = {'layers': [{'index': 0, 'name': 'F.Cu'}],
                    'nets': [{'code': 1, 'name': 'VCC'}]}
        rules = {'net_settings': {'classes': [
            {'name': 'Default', 'track_width': .2, 'clearance': .2, 'via_diameter': .6, 'via_drill': .3},
            {'name': 'Power', 'nets': ['VCC'], 'track_width': .5, 'clearance': .5}]}}
        args = krt_arguments('in', 'out', geometry, rules)
        self.assertEqual(float(args[args.index('--clearance')+1]), .5)
        geometry['pads'] = [{'local_clearance_mm': .7}]
        rules['board'] = {'design_settings': {'rules': {'min_clearance': .8}}}
        args = krt_arguments('in', 'out', geometry, rules)
        self.assertEqual(float(args[args.index('--clearance')+1]), .8)

    def test_dsn_graphics_preserve_layers_windows_and_invert_y(self):
        geometry = {'layers': [{'index': 0, 'name': 'F.Cu'}], 'copper_graphics': [
            {'copper': [{'layer': 0, 'polygons': [
                {'outer': [[1,2],[5,2],[5,6],[1,6]],
                 'holes': [[[2,3],[3,3],[3,4],[2,4]]]}], 'primitives': [
                {'kind': 'segment', 'a': [7,2], 'b': [8,2], 'width': .2}]}]}]}
        rules = {'net_settings': {'classes': [{'clearance': .2}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'board.dsn'
            # A quoted close parenthesis must not terminate the structure.
            path.write_text('(pcb "x" (unit um) (structure (layer "F.Cu") (name ")")) (placement))')
            self.assertEqual(protect_copper_graphics(path, geometry, rules), 2)
            text = path.read_text()
            self.assertIn('1000.000000000 -2000.000000000', text)
            self.assertIn('(window (polygon "F.Cu"', text)
            self.assertLess(text.index('mr_fixed_graphic_0'), text.index('(placement'))
            self.assertIn('(placement)', text)
            self.assertIn('mr_fixed_graphic_1', text)
            self.assertIn('(clearance_class mrgraphics)', text)
            self.assertIn('(type mrgraphics_wire)', text)
            path.write_text('(pcb (unit mil) (structure))')
            with self.assertRaisesRegex(ValueError, 'unsupported DSN unit'):
                protect_copper_graphics(path, geometry, rules)


if __name__ == '__main__':
    unittest.main()
