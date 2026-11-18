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
    def test_default_config_is_megaroute(self):
        data = json.loads(DEFAULT_MEGAROUTE_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(data["algorithm"], "megaroute")
        self.assertEqual(data["max_iterations"], 20)
        self.assertEqual(recorded_algorithm("megaroute"), "megaroute")
        self.assertEqual(recorded_algorithm("krt"), "krt")
        self.assertEqual(recorded_algorithm("freerouting"), "freerouting")
        self.assertEqual(BACKENDS["megaroute"].blockers, ())


if __name__ == "__main__":
    unittest.main()
