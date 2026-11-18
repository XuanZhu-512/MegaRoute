"""Native integration tests; set KICAD_PYTHON and KICAD_VERSION explicitly."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'python'))
from pcb_bench.cases import load_case, fingerprints
from pcb_bench.converters import KiCadGeometryConverter


@unittest.skipUnless(os.getenv('KICAD_PYTHON') and os.getenv('KICAD_VERSION'),
                     'native KiCad Python/version not configured')
class NativeExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)/'export'
        self.case = load_case(ROOT.parent/'dataset/test/case.json')
        self.before = fingerprints(self.case)
        self.converter = KiCadGeometryConverter(os.environ['KICAD_PYTHON'], os.environ['KICAD_VERSION'])

    def test_real_pcb_geometry_and_provenance(self):
        bundle = self.converter.import_board(self.case, self.out)
        geometry = json.loads(bundle.board_ir.read_text())
        report = json.loads(bundle.conversion_report.read_text())
        mapping = json.loads(bundle.source_map.read_text())
        self.assertEqual([x['name'] for x in geometry['layers']], ['F.Cu','B.Cu'])
        self.assertEqual(len(geometry['pads']), 9)
        self.assertEqual(sum(p['plated'] for p in geometry['pads']), 2)
        self.assertEqual(len([n for n in geometry['nets'] if n['code']]), 4)
        self.assertEqual(report['kicad_version'], os.environ['KICAD_VERSION'])
        self.assertFalse(report['cpp_geometry_v1_compatible'])
        self.assertEqual(self.before, fingerprints(self.case))
        self.assertEqual(self.before, fingerprints(bundle.source_case))
        outline = geometry['outline'][0]['outer']
        self.assertAlmostEqual(max(p[0] for p in outline), 101.4)
        self.assertAlmostEqual(max(p[1] for p in outline), 110.4)
        for pad in geometry['pads']:
            self.assertIn(pad['id'], mapping['objects'])
            self.assertEqual(len(pad['copper']), 2 if pad['plated'] else 1)
            x,y = pad['position_mm']
            for layer in pad['copper']:
                points = layer['polygons'][0]['outer']
                # Center is transformed to global board coordinates exactly once.
                self.assertLess(abs((max(p[0] for p in points)+min(p[0] for p in points))/2-x), .01)
                self.assertLess(abs((max(p[1] for p in points)+min(p[1] for p in points))/2-y), .01)
                self.assertGreater(len(points), 4)
        other = self.converter.import_board(self.case, self.out.with_name('repeat'))
        self.assertEqual(bundle.board_ir.read_bytes(), other.board_ir.read_bytes())

    def test_version_mismatch_is_atomic(self):
        converter = KiCadGeometryConverter(os.environ['KICAD_PYTHON'], '0.0.0')
        with self.assertRaisesRegex(RuntimeError, 'version mismatch'):
            converter.import_board(self.case, self.out)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.before, fingerprints(self.case))

    def test_existing_destination_and_invalid_tolerance(self):
        self.out.mkdir()
        marker = self.out/'keep.txt'; marker.write_text('keep')
        with self.assertRaises(ValueError):
            self.converter.import_board(self.case, self.out)
        self.assertEqual(marker.read_text(), 'keep')
        converter = KiCadGeometryConverter(os.environ['KICAD_PYTHON'], os.environ['KICAD_VERSION'], float('nan'))
        with self.assertRaises(ValueError):
            converter.preflight()


    def test_native_tracks_arcs_and_vias(self):
        board_path = Path(self.tmp.name)/'with_tracks.kicad_pcb'
        script = '''
import pcbnew as p, sys
b=p.LoadBoard(sys.argv[1])
v=lambda x,y: p.VECTOR2I(p.FromMM(x),p.FromMM(y))
t=p.PCB_TRACK(b);t.SetStart(v(20,20));t.SetEnd(v(25,20));t.SetWidth(p.FromMM(.3));t.SetLayer(p.F_Cu);t.SetNetCode(1);b.Add(t)
a=p.PCB_ARC(b);a.SetStart(v(25,20));a.SetMid(v(27,22));a.SetEnd(v(25,24));a.SetWidth(p.FromMM(.3));a.SetLayer(p.F_Cu);a.SetNetCode(1);b.Add(a)
h=p.PCB_VIA(b);h.SetPosition(v(20,20));h.SetWidth(p.FromMM(1.2));h.SetDrill(p.FromMM(.6));h.SetLayerPair(p.F_Cu,p.B_Cu);h.SetNetCode(1);b.Add(h)
p.SaveBoard(sys.argv[2],b)
'''
        subprocess.run([os.environ['KICAD_PYTHON'],'-c',script,str(self.case.board),str(board_path)],
                       check=True,capture_output=True,text=True,timeout=30)
        shutil.copy2(self.case.project,board_path.with_suffix('.kicad_pro'))
        manifest = Path(self.tmp.name)/'case.json'
        manifest.write_text(json.dumps(dict(schema_version='1.0',case_id='tracks',
                                            board=board_path.name,project='with_tracks.kicad_pro',
                                            copper_policy='preserve_input')))
        bundle = self.converter.import_board(load_case(manifest),self.out)
        geometry=json.loads(bundle.board_ir.read_text())
        tracks=geometry['tracks_and_vias']
        self.assertEqual(len(tracks),3)
        self.assertEqual(len([t for t in tracks if 'mid_mm' in t]),1)
        via=next(t for t in tracks if 'drill_mm' in t)
        self.assertAlmostEqual(via['drill_mm'],.6)
        self.assertEqual(len(via['copper']),2)


@unittest.skipUnless(os.getenv('KICAD_PYTHON') and os.getenv('KICAD_VERSION'),
                     'native KiCad Python/version not configured')
class NativeLayerNameTests(unittest.TestCase):
    def test_custom_layer_aliases_export_standard_identifiers(self):
        code = '''
import json, sys
from pathlib import Path
import pcbnew as p
from pcb_bench.kicad_export_worker import export_geometry
board = p.BOARD()
board.SetCopperLayerCount(6)
layers = list(board.GetEnabledLayers().CuStack())
for layer, alias in zip(layers, ['Top Layer', 'S1', 'S2', 'S3', 'S4', 'Bottom Layer']):
    board.SetLayerName(layer, alias)
points = [(0, 0), (10, 0), (10, 10), (0, 10)]
for start, end in zip(points, points[1:] + points[:1]):
    edge = p.PCB_SHAPE(board)
    edge.SetShape(p.SHAPE_T_SEGMENT)
    edge.SetLayer(p.Edge_Cuts)
    edge.SetStart(p.VECTOR2I(*(p.FromMM(v) for v in start)))
    edge.SetEnd(p.VECTOR2I(*(p.FromMM(v) for v in end)))
    edge.SetWidth(p.FromMM(.05))
    board.Add(edge)
path = Path(sys.argv[1])
p.SaveBoard(str(path), board)
geometry, _, _ = export_geometry(p, path, sys.argv[2], .005)
print(json.dumps([layer['name'] for layer in geometry['layers']]))
'''
        env = dict(os.environ)
        env['PYTHONPATH'] = str(ROOT / 'python') + os.pathsep + env.get('PYTHONPATH', '')
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([os.environ['KICAD_PYTHON'], '-c', code,
                                   str(Path(tmp) / 'aliases.kicad_pcb'), os.environ['KICAD_VERSION']],
                                  env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), ['F.Cu', 'In1.Cu', 'In2.Cu', 'In3.Cu', 'In4.Cu', 'B.Cu'])


@unittest.skipUnless(os.getenv('KICAD_PYTHON') and os.getenv('KICAD_VERSION'),
                     'native KiCad Python/version not configured')
class NativeRuleSemanticsTests(unittest.TestCase):
    def test_local_overrides_and_copper_text_use_native_geometry(self):
        # Entirely synthetic; no dataset boards or routing experiments are involved.
        code = '''
import json, sys
from pathlib import Path
import pcbnew as p
from pcb_bench.kicad_export_worker import export_geometry
from pcb_bench.adapt import adapt_geometry
v = lambda x, y: p.VECTOR2I(p.FromMM(x), p.FromMM(y))
board = p.BOARD()
for start, end in [((0,0),(20,0)), ((20,0),(20,20)), ((20,20),(0,20)), ((0,20),(0,0))]:
    edge = p.PCB_SHAPE(board); edge.SetShape(p.SHAPE_T_SEGMENT); edge.SetLayer(p.Edge_Cuts)
    edge.SetStart(v(*start)); edge.SetEnd(v(*end)); edge.SetWidth(p.FromMM(.05)); board.Add(edge)
fp = p.FOOTPRINT(board); fp.SetReference('U1'); board.Add(fp)
fp.SetLocalClearance(p.FromMM(.1))
for number, override in [('1', None), ('2', .05), ('3', 0)]:
    pad = p.PAD(fp); pad.SetNumber(number); pad.SetAttribute(p.PAD_ATTRIB_SMD)
    pad.SetShape(p.PAD_SHAPE_CIRCLE); pad.SetSize(v(1,1)); pad.SetPosition(v(5+int(number)*2,5))
    layer_set = p.LSET(); layer_set.AddLayer(p.F_Cu); pad.SetLayerSet(layer_set)
    if override is not None: pad.SetLocalClearance(p.FromMM(override))
    fp.Add(pad)
field = fp.Reference(); field.SetLayer(p.F_Cu); field.SetVisible(True); field.SetPosition(v(5,10))
hidden = fp.Value(); hidden.SetLayer(p.F_Cu); hidden.SetVisible(False)
for visible in (True,):
    text = p.PCB_TEXT(board); text.SetText('AO'); text.SetTextSize(v(1,1))
    text.SetTextThickness(p.FromMM(.1)); text.SetPosition(v(10,10)); text.SetLayer(p.B_Cu)
    text.SetVisible(visible); board.Add(text)
path = Path(sys.argv[1]); p.SaveBoard(str(path), board)
geometry, _, report = export_geometry(p, path, sys.argv[2], .005)
print(json.dumps({'pads': {x['number']: [x['local_clearance_mm'], x['local_clearance_source']]
                          for x in geometry['pads']},
                  'graphics': geometry['copper_graphics'], 'ignored': report['ignored_non_copper_graphics']}))
'''
        env = dict(os.environ)
        env['PYTHONPATH'] = str(ROOT / 'python') + os.pathsep + env.get('PYTHONPATH', '')
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([os.environ['KICAD_PYTHON'], '-c', code,
                                   str(Path(tmp) / 'rules.kicad_pcb'), os.environ['KICAD_VERSION']],
                                  env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['pads']['1'], [.1, 'footprint'])
        self.assertEqual(result['pads']['2'], [.05, 'pad'])
        self.assertEqual(result['pads']['3'], [0, 'pad'])
        self.assertEqual({g['type'] for g in result['graphics']}, {'PCB_TEXT', 'PCB_FIELD'})
        self.assertEqual(len(result['graphics']), 2)
        for graphic in result['graphics']:
            part = graphic['copper'][0]
            self.assertEqual(part['polygons'], [])
            self.assertGreater(len(part['primitives']), 1)
            self.assertTrue(all(x['kind'] == 'segment' for x in part['primitives']))
        self.assertEqual(sum(x['reason'] == 'invisible_copper_text' for x in result['ignored']), 1)


if __name__ == '__main__':
    unittest.main()
