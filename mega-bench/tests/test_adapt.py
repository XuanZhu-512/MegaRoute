"""Routing-board adapter preserves KiCad geometry and resolved net rules."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.adapt import adapt_geometry


def rules():
    return {"board": {"design_settings": {"rules": {
        "min_track_width": 0.3, "min_clearance": 0.3, "min_copper_edge_clearance": 0.3,
        "min_via_diameter": 1.2, "min_through_hole_diameter": 0.6, "min_via_annular_width": 0.0}}},
            "net_settings": {"classes": [{"name": "Default", "track_width": 0.3, "clearance": 0.3}],
                             "netclass_assignments": {}, "netclass_patterns": []}}


def geometry():
    return {"schema_version": "kicad-geometry-1.0", "units": "mm",
            "layers": [{"index": 0, "name": "F.Cu"}, {"index": 1, "name": "B.Cu"}],
            "outline": [{"outer": [[0, 0], [10, 0], [10, 10], [0, 10]], "holes": [[[1, 1], [2, 1], [2, 2]]]}],
            "nets": [{"code": 0, "name": ""}, {"code": 1, "name": "NET1"}],
            "pads": [
                {"id": "pth", "net_name": "NET1", "attribute": "plated_through_hole",
                 "position_mm": [3, 3],
                 "copper": [
                     {"layer": 0, "shape_code": 0, "size_mm": [1.2, 1.2],
                      "polygons": [{"outer": [[2.4, 3], [3, 2.4], [3.6, 3]], "holes": []}]},
                     {"layer": 1, "shape_code": 0, "size_mm": [1.2, 1.2],
                      "polygons": [{"outer": [[2.4, 3], [3, 2.4], [3.6, 3]], "holes": []}]}]},
                {"id": "smd", "net_name": "NET1", "attribute": "smd", "position_mm": [7, 7],
                 "copper": [{"layer": 1, "shape_code": 4, "size_mm": [2, 2],
                             "polygons": [{"outer": [[6, 6], [8, 6], [8, 8], [6, 8]], "holes": []}]}]}],
            "tracks_and_vias": [], "copper_graphics": []}


class AdaptTests(unittest.TestCase):
    def test_local_clearance_including_zero_and_netless_obstacle(self):
        data = geometry()
        data["pads"][0]["local_clearance_mm"] = .05
        data["pads"][1]["local_clearance_mm"] = 0
        board = adapt_geometry(data, rules())
        self.assertEqual([p["clearance_override"] for p in board["pads"]], [.05, 0])
        self.assertEqual(board["rules"]["fixed_boundary_policy"], "kicad_edges")
        data["pads"][1]["net_name"] = ""
        board = adapt_geometry(data, rules())
        self.assertEqual(board["fixed_copper"][0]["clearance_override"], 0)

    def test_copper_text_strokes_keep_real_glyph_gaps(self):
        data = geometry()
        primitives = [{"kind": "segment", "a": [3, 4], "b": [4, 4], "width": .1},
                      {"kind": "polygon", "center": [5, 4], "points": [[5, 4], [6, 4], [5, 5]]}]
        data["copper_graphics"] = [{"id": "text", "type": "PCB_TEXT", "copper": [
            {"layer": 0, "polygons": [], "primitives": primitives}]}]
        fixed = adapt_geometry(data, rules())["fixed_copper"]
        self.assertEqual(len(fixed), 2)
        self.assertEqual(fixed[0]["a"], [3, 4])
        self.assertEqual(fixed[1]["points"], primitives[1]["points"])
        self.assertEqual([x["copper_group"] for x in fixed], ["text", "text"])
        self.assertEqual(len({x["id"] for x in fixed}), 2)

    def test_plated_circle_polygon_and_rules(self):
        board = adapt_geometry(geometry(), rules())
        self.assertEqual(board["rules"]["min_width"], 0.3)
        self.assertEqual(board["rules"]["via_diameter"], 1.2)
        self.assertEqual(board["rules"]["via_drill"], 0.6)
        self.assertEqual(board["nets"], [{"id": "NET1", "width": 0.3, "clearance": 0.3}])
        self.assertEqual(board["holes"], [[[1, 1], [2, 1], [2, 2]]])
        plated = next(pad for pad in board["pads"] if pad["id"] == "pth")
        self.assertEqual(plated["kind"], "circle")
        self.assertEqual(plated["radius"], 0.6)
        self.assertEqual(plated["layers"], [0, 1])
        self.assertTrue(plated["plated"])
        smd = next(pad for pad in board["pads"] if pad["id"] == "smd")
        self.assertEqual(smd["kind"], "polygon")
        self.assertFalse(smd["plated"])
        self.assertEqual(smd["points"][0], [6, 6])

    def test_rect_plated_pad_and_unconnected_copper(self):
        data = geometry()
        data["pads"][0]["copper"][0]["shape_code"] = 1
        data["pads"][0]["copper"][1]["shape_code"] = 1
        data["pads"].append({
            "id": "mount", "net_name": "", "attribute": "plated_through_hole",
            "position_mm": [1.5, 1.5],
            "copper": [
                {"layer": 0, "shape_code": 0, "size_mm": [1, 1],
                 "polygons": [{"outer": [[1, 1], [2, 1], [2, 2], [1, 2]], "holes": []}]},
                {"layer": 1, "shape_code": 0, "size_mm": [1, 1],
                 "polygons": [{"outer": [[1, 1], [2, 1], [2, 2], [1, 2]], "holes": []}]}]})
        board = adapt_geometry(data, rules())
        plated = next(pad for pad in board["pads"] if pad["id"] == "pth")
        self.assertEqual(plated["kind"], "polygon")
        self.assertTrue(plated["plated"])
        self.assertEqual(plated["layers"], [0, 1])
        mount = next(item for item in board["fixed_copper"] if item["id"] == "mount")
        self.assertEqual(mount["kind"], "polygon")
        self.assertTrue(mount["plated"])
        self.assertNotIn("net", mount)

    def test_polygon_holes_preserved_for_graphics_and_pad_access(self):
        data = geometry()
        hole = [[6.5, 6.5], [7.5, 6.5], [7.5, 7.5], [6.5, 7.5]]
        poly = data["pads"][1]["copper"][0]["polygons"][0]
        poly["holes"] = [hole]
        data["copper_graphics"] = [{"id": "ring", "type": "PCB_SHAPE", "copper": [
            {"layer": 0, "polygons": [poly]}]}]
        board = adapt_geometry(data, rules())
        self.assertEqual(board["fixed_copper"][0]["holes"], [hole])
        self.assertEqual(board["pads"][1]["holes"], [hole])
        self.assertEqual(board["pads"][1]["center"], poly["outer"][0])
        self.assertEqual(data["pads"][1]["position_mm"], [7, 7])
        poly["holes"] = [[[7, 7], [8, 7]]]
        with self.assertRaisesRegex(ValueError, "degenerate copper hole"):
            adapt_geometry(data, rules())

    def test_circle_fast_path_does_not_discard_explicit_holes(self):
        data = geometry()
        for part in data["pads"][0]["copper"]:
            part["polygons"][0]["holes"] = [[[2.95, 2.9], [3.05, 2.9], [3, 2.8]]]
        pad = adapt_geometry(data, rules())["pads"][0]
        self.assertEqual(pad["kind"], "polygon")
        self.assertEqual(len(pad["holes"]), 1)

    def test_arc_rejected_and_patterns_resolved(self):
        data = geometry()
        data["tracks_and_vias"] = [{"id": "arc", "type": "PCB_ARC", "copper": []}]
        with self.assertRaises(ValueError):
            adapt_geometry(data, rules())
        patterned = rules()
        patterned["net_settings"]["netclass_patterns"] = [
            {"pattern": "NET*", "netclass": "Default"},
        ]
        patterned["net_settings"]["classes"].append(
            {"name": "Wide", "track_width": 0.5, "clearance": 0.4})
        patterned["net_settings"]["netclass_patterns"].insert(
            0, {"pattern": "NET1", "netclass": "Wide"})
        board = adapt_geometry(geometry(), patterned)
        self.assertEqual(board["nets"], [{"id": "NET1", "width": 0.5, "clearance": 0.4}])


if __name__ == "__main__":
    unittest.main()
