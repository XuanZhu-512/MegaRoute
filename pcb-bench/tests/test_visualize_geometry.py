"""Scene JSON and SVG keep the coordinates stored in kicad-geometry JSON."""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("visualize_geometry", ROOT / "tools" / "visualize_geometry.py")
viewer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(viewer)


def sample_geometry():
    return {
        "schema_version": "kicad-geometry-1.0",
        "units": "mm",
        "coordinate_system": "KiCad board-global XY; no Y inversion",
        "layers": [
            {"index": 0, "kicad_id": 0, "name": "F.Cu"},
            {"index": 1, "kicad_id": 31, "name": "B.Cu"},
        ],
        "outline": [{"outer": [[0.0, 0.0], [10.0, 0.0], [10.25, 4.5], [0.0, 4.5]],
                     "holes": [[[1.5, 1.5], [2.5, 1.5], [2.5, 2.25]]]}],
        "nets": [{"code": 1, "name": "NET1"}],
        "pads": [
            {"id": "pad-a", "net_code": 1, "net_name": "NET1", "plated": True,
             "drill_size_mm": [0.6, 0.6], "drill_position_mm": [1.25, 2.5],
             "copper": [
                 {"layer": 0, "polygons": [{"outer": [[1.0, 2.0], [1.2, 2.125], [1.4, 2.0]], "holes": []}]},
                 {"layer": 1, "polygons": [{"outer": [[1.0, 2.0], [1.2, 2.125], [1.4, 2.0]], "holes": []}]},
             ]},
            {"id": "pad-b", "net_code": 1, "net_name": "NET1", "plated": False,
             "drill_size_mm": [0.0, 0.0], "drill_position_mm": [3.0, 3.0],
             "copper": [{"layer": 1, "polygons": [{"outer": [[3.0, 3.0], [3.5, 3.0], [3.5, 3.5]], "holes": []}]}]},
        ],
        "tracks_and_vias": [],
        "copper_graphics": [],
    }


class GeometryPreviewTests(unittest.TestCase):
    def test_scene_and_svg_keep_source_coordinates(self):
        geometry = json.loads(json.dumps(sample_geometry()))
        scene = viewer.build_scene(geometry)
        svg = viewer.render_svg(scene)
        self.assertEqual([layer["name"] for layer in scene["layers"]], ["F.Cu", "B.Cu"])
        counts = {layer["index"]: sum(shape["role"] == "pad" for shape in layer["shapes"])
                  for layer in scene["layers"]}
        expected = {0: 0, 1: 0}
        for pad in geometry["pads"]:
            for part in pad["copper"]:
                expected[part["layer"]] += 1
        self.assertEqual(counts, expected)
        front = next(shape for shape in scene["layers"][0]["shapes"] if shape["id"] == "pad-a")
        self.assertEqual(front["polygons"], geometry["pads"][0]["copper"][0]["polygons"])
        self.assertEqual(front["drill"], {"center": [1.25, 2.5], "radius": 0.3})
        self.assertNotIn("drill", next(shape for shape in scene["layers"][1]["shapes"] if shape["id"] == "pad-b"))
        outer = geometry["pads"][0]["copper"][0]["polygons"][0]["outer"]
        self.assertIn(f"M {json.dumps(outer[0][0])} {json.dumps(outer[0][1])}", svg)
        for point in outer[1:]:
            self.assertIn(f"L {json.dumps(point[0])} {json.dumps(point[1])}", svg)
        hole = geometry["outline"][0]["holes"][0][0]
        self.assertIn(f"M {json.dumps(hole[0])} {json.dumps(hole[1])}", svg)
        self.assertIn("scale(1 -1)", svg)
        self.assertIn('r="0.3"', svg)


if __name__ == "__main__":
    unittest.main()
