"""Budgets plus native pad connectivity and copper writeback regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.contracts import RunBudget, KiCadCase
from pcb_bench.runner import effective_router_config, _route_megaroute


class BudgetTests(unittest.TestCase):
    def test_internal_deadline_leaves_watchdog_margin(self):
        for seconds in (.01, 1, 60, 300):
            result = effective_router_config({"time_limit_s": 300}, RunBudget(seconds, 60))
            self.assertGreater(result["time_limit_s"], 0)
            self.assertLess(result["time_limit_s"], seconds)
        self.assertEqual(effective_router_config({"time_limit_s": 20}, RunBudget(300, 60))["time_limit_s"], 20)


class WatchdogTests(unittest.TestCase):
    def test_watchdog_recovers_only_a_published_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            router = root / "router"
            router.write_bytes(b"test binary")
            config = root / "config.json"
            config.write_text('{"schema_version":"1.0","time_limit_s":300}')
            board = root / "board.kicad_pcb"
            board.write_text("board fixture")
            case = KiCadCase("fixture", board, root / "board.kicad_pro")
            bundle = SimpleNamespace(board_ir=root / "geometry.json", source_map=root / "map.json",
                                     conversion_report=root / "conversion.json", source_case=case, source_hashes={})
            converter = Mock()
            converter.export_routes.return_value = SimpleNamespace(case=case)
            for published in (True, False):
                out = root / str(published)

                def process(args, **kwargs):
                    if "--build-info" in args:
                        return subprocess.CompletedProcess(args, 0, '{"source_fingerprint":"custom"}', "")
                    if published:
                        route_dir = Path(args[args.index("--out") + 1])
                        route_dir.mkdir()
                        (route_dir / "routes.json").write_text('{"schema_version":"1.0","copper":[]}')
                    raise subprocess.TimeoutExpired(args, 1, output=b"partial stdout", stderr=b"timeout")

                with patch("pcb_bench.runner.subprocess.run", side_effect=process), \
                     patch("pcb_bench.runner.adapt_files"):
                    if published:
                        _route_megaroute(converter, bundle, out, router, config, RunBudget(1, 60))
                        identity = json.loads((out / "work/router_identity.json").read_text())
                        self.assertTrue(identity["watchdog_terminated"])
                        self.assertTrue((out / "work/router.log").read_text().endswith("timeout"))
                    else:
                        with self.assertRaises(subprocess.TimeoutExpired):
                            _route_megaroute(converter, bundle, out, router, config, RunBudget(1, 60))


@unittest.skipUnless(os.getenv("KICAD_PYTHON") and os.getenv("KICAD_VERSION"),
                     "native KiCad Python/version not configured")
class NativeWorkerTests(unittest.TestCase):
    def test_pad_region_contact_does_not_require_pad_centers(self):
        script = r'''
import pathlib, sys
import pcbnew as p
sys.path.insert(0, sys.argv[1])
from pcb_bench.kicad_metrics_worker import board_stats
from pcb_bench.kicad_write_worker import append_routes
root = pathlib.Path(sys.argv[2])
board = p.BOARD()
net = p.NETINFO_ITEM(board, "A", 1)
board.Add(net)
for i, (x, width) in enumerate(((2, 2), (12, 6))):
    footprint = p.FOOTPRINT(board)
    footprint.SetReference("J" + str(i))
    board.Add(footprint)
    pad = p.PAD(footprint)
    pad.SetNumber("1")
    pad.SetAttribute(p.PAD_ATTRIB_SMD)
    pad.SetShape(p.PAD_SHAPE_RECT)
    layers = p.LSET()
    layers.AddLayer(p.F_Cu)
    pad.SetLayerSet(layers)
    pad.SetSize(p.VECTOR2I(p.FromMM(width), p.FromMM(2)))
    pad.SetPosition(p.VECTOR2I(p.FromMM(x), p.FromMM(5)))
    pad.SetNet(net)
    footprint.Add(pad)
source = root / "source.kicad_pcb"
p.SaveBoard(str(source), board)
assert board_stats(p, source, sys.argv[3])["pad_groups"] == {"A": 2}
layers = [{"index": 0, "kicad_id": p.F_Cu}, {"index": 1, "kicad_id": p.B_Cu}]
for name, end_x, layer, groups in (("edge", 9, 0, 1), ("inside", 9.1, 0, 1),
                                   ("gap", 8.5, 0, 2), ("wrong_layer", 9, 1, 2)):
    trace = {"id": "trace", "kind": "segment", "net": "A", "a": [3,5],
             "b": [end_x,5], "width": .4, "layers": [layer]}
    output = root / (name + ".kicad_pcb")
    append_routes(p, source, output, {"copper": [trace]}, layers, sys.argv[3])
    stats = board_stats(p, output, sys.argv[3])
    assert stats["pad_groups"] == {"A": groups}, (name, stats)
'''
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([os.environ["KICAD_PYTHON"], "-c", script,
                                   str(ROOT / "python"), tmp, os.environ["KICAD_VERSION"]],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_direct_pad_contacts_and_duplicate_via_writeback(self):
        script = r'''
import json, pathlib, sys
import pcbnew as p
sys.path.insert(0, sys.argv[1])
from pcb_bench.kicad_metrics_worker import board_stats
from pcb_bench.kicad_write_worker import append_routes
root = pathlib.Path(sys.argv[2])
version = sys.argv[3]
board = p.BOARD()
net = p.NETINFO_ITEM(board, "A", 1)
board.Add(net)
for i, x in enumerate((10, 11, 16)):
    footprint = p.FOOTPRINT(board)
    footprint.SetReference("J" + str(i))
    board.Add(footprint)
    pad = p.PAD(footprint)
    pad.SetNumber("1")
    pad.SetAttribute(p.PAD_ATTRIB_SMD)
    pad.SetShape(p.PAD_SHAPE_RECT)
    layers = p.LSET()
    layers.AddLayer(p.F_Cu)
    pad.SetLayerSet(layers)
    pad.SetSize(p.VECTOR2I(p.FromMM(2), p.FromMM(2)))
    pad.SetPosition(p.VECTOR2I(p.FromMM(x), p.FromMM(10)))
    pad.SetNet(net)
    footprint.Add(pad)
source = root / "input.kicad_pcb"
p.SaveBoard(str(source), board)
stats = board_stats(p, source, version)
assert stats["pad_groups"] == {"A": 2}, stats
via = {"id": "v1", "net": "A", "kind": "via", "center": [10, 10],
       "radius": .3, "drill": .3, "layers": [0, 1]}
layers = [{"index": 0, "kicad_id": p.F_Cu}, {"index": 1, "kicad_id": p.B_Cu}]
first = root / "first.kicad_pcb"
report = append_routes(p, source, first, {"copper": [via, dict(via, id="v2")]}, layers, version)
assert report["added"] == 1 and report["duplicate_vias_skipped"] == 1, report
second = root / "second.kicad_pcb"
report = append_routes(p, first, second, {"copper": [via, dict(via, id="larger", radius=.4)]}, layers, version)
assert report["added"] == 1 and report["duplicate_vias_skipped"] == 1, report
assert len(board_stats(p, second, version)["copper"]) == 2
print(json.dumps({"pad_groups": stats["pad_groups"], "report": report}))
'''
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([os.environ["KICAD_PYTHON"], "-c", script,
                                   str(ROOT / "python"), tmp, os.environ["KICAD_VERSION"]],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            self.assertEqual(json.loads(proc.stdout)["pad_groups"], {"A": 2})


if __name__ == "__main__":
    unittest.main()
