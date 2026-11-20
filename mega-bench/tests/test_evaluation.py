"""External scores use KiCad DRC counts and pad groups, not the internal router."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.evaluation import METRIC_FIELDS, build_metrics, connection_score, count_drc
from pcb_bench.krt_backend import KRT_PAPER_ARGS, krt_arguments


class EvaluationTests(unittest.TestCase):
    def test_routability_matches_pad_group_formula(self):
        initial = {"NET1": 2, "NET2": 3, "NET3": 2, "NET4": 2}
        done = connection_score(initial, {net: 1 for net in initial})
        self.assertEqual(done["connections_required"], 5)
        self.assertEqual(done["connections_made"], 5)
        self.assertEqual(done["routability"], 1)
        self.assertTrue(done["success"])
        partial = connection_score(initial, {"NET1": 1, "NET2": 2, "NET3": 2, "NET4": 2})
        self.assertEqual(partial["connections_made"], 2)
        self.assertAlmostEqual(partial["routability"], 2 / 5)
        self.assertFalse(partial["success"])

    def test_drc_counts_ignore_exclusions_and_unconnected_list(self):
        counts = count_drc({"violations": [
            {"severity": "error", "excluded": False},
            {"severity": "error", "excluded": True},
            {"severity": "warning"}],
            "unconnected_items": [{}, {}]})
        self.assertEqual(counts, {"drv_error_count": 1, "drv_warning_count": 1,
                                  "unconnected_item_count": 2})

    def test_metrics_share_one_field_set_and_do_not_invent_clean_pass(self):
        metrics = build_metrics(
            "case1", "megaroute", {"NET1": 2}, {"NET1": 1},
            [], [{"uuid": "new", "kind": "segment", "length_mm": 1.5},
                 {"uuid": "via", "kind": "via", "length_mm": 0}],
            ["pad"], ["pad"],
            {"drv_error_count": 0, "drv_warning_count": 2, "unconnected_item_count": 0},
            0.25, 0)
        self.assertEqual(tuple(metrics), METRIC_FIELDS)
        self.assertEqual(metrics["track_count"], 1)
        self.assertEqual(metrics["via_count"], 1)
        self.assertEqual(metrics["wirelength_mm"], 1.5)
        self.assertTrue(metrics["clean_pass"])
        self.assertFalse(metrics["invalid_output"])
        dropped = build_metrics(
            "case1", "krt", {"NET1": 2}, {"NET1": 1}, [], [],
            ["pad"], [], {"drv_error_count": 0, "drv_warning_count": 0, "unconnected_item_count": 0},
            1, 5)
        self.assertTrue(dropped["invalid_output"])
        self.assertFalse(dropped["clean_pass"])
        self.assertFalse(dropped["success"])
        legacy = build_metrics(
            "case1", "tracemaker", {"NET1": 2}, {"NET1": 1}, [], [],
            ["generated-a", "generated-b"], ["saved-a", "saved-b"],
            {"drv_error_count": 0, "drv_warning_count": 0, "unconnected_item_count": 0},
            1, 0, ["R1:1", "R1:2"], ["R1:1", "R1:2"])
        self.assertFalse(legacy["invalid_output"])
        self.assertTrue(legacy["success"])
        removed = build_metrics(
            "case1", "tracemaker", {"NET1": 2}, {"NET1": 1}, [], [],
            ["generated-a", "generated-b"], ["saved-a"],
            {"drv_error_count": 0, "drv_warning_count": 0, "unconnected_item_count": 0},
            1, 0, ["R1:1", "R1:2"], ["R1:1"])
        self.assertTrue(removed["invalid_output"])
        self.assertFalse(removed["success"])

    def test_krt_uses_default_class_and_paper_arguments(self):
        geometry = {"layers": [{"index": 1, "name": "B.Cu"}, {"index": 0, "name": "F.Cu"}]}
        rules = {"net_settings": {"classes": [{"name": "Default", "track_width": 0.3, "clearance": 0.3,
                                               "via_diameter": 1.2, "via_drill": 0.6}],
                                  "netclass_patterns": [], "netclass_assignments": {}}}
        args = krt_arguments("in.kicad_pcb", "out.kicad_pcb", geometry, rules)
        self.assertEqual(args[:2], ["in.kicad_pcb", "out.kicad_pcb"])
        self.assertEqual(args[args.index("--layers") + 1:args.index("--track-width")], ["F.Cu", "B.Cu"])
        self.assertIn("--via-size", args)
        self.assertEqual(args[args.index("--via-size") + 1], "1.2")
        self.assertEqual(tuple(args[args.index("--grid-step"):]), KRT_PAPER_ARGS)
        geometry["nets"] = [{"code": 1, "name": "VCC"}, {"code": 2, "name": "SIG"}]
        rules["net_settings"]["classes"].append(
            {"name": "Power", "track_width": 0.5, "clearance": 0.3,
             "via_diameter": 1.2, "via_drill": 0.6})
        rules["net_settings"]["netclass_patterns"] = [{"pattern": "VCC", "netclass": "Power"}]
        args = krt_arguments("in.kicad_pcb", "out.kicad_pcb", geometry, rules)
        self.assertIn("--power-nets", args)
        self.assertEqual(args[args.index("--power-nets") + 1], "VCC")
        self.assertEqual(args[args.index("--power-nets-widths") + 1], "0.5")


if __name__ == "__main__":
    unittest.main()
