"""Default MegaRoute run records the algorithm stored in its config."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.backends import BACKENDS
from pcb_bench.runner import DEFAULT_MEGAROUTE_CONFIG, recorded_algorithm


class MegaRouteDefaultTests(unittest.TestCase):
    def test_drc_preset_changes_only_permitted_parameters(self):
        base = json.loads(DEFAULT_MEGAROUTE_CONFIG.read_text())
        preset = json.loads((ROOT / "configs/megaroute-drc.json").read_text())
        changed = {key for key in base if base[key] != preset[key]}
        self.assertEqual(changed, {"penalty_L", "penalty_mu", "max_iterations"})
        self.assertEqual(preset["max_iterations"], 2*preset["penalty_mu"])
        self.assertEqual(preset["routing_order"], "rotate_conflicts")

    def test_default_config_is_megaroute(self):
        data = json.loads(DEFAULT_MEGAROUTE_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(data["algorithm"], "megaroute")
        self.assertEqual(data["max_iterations"], 20)
        for key, value in {"beta": 5, "d_min_mm": .0254, "penalty_L": 200,
                           "penalty_k": .4, "penalty_mu": 10}.items():
            self.assertEqual(data[key], value)
        for key in ("history_weight", "refinement_levels", "stagnation_rounds"):
            self.assertNotIn(key, data)
        self.assertEqual(recorded_algorithm("megaroute"), "megaroute")
        self.assertEqual(recorded_algorithm("krt"), "krt")
        self.assertEqual(recorded_algorithm("freerouting"), "freerouting")
        self.assertEqual(BACKENDS["megaroute"].blockers, ())


if __name__ == "__main__":
    unittest.main()
