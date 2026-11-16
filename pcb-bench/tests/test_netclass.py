"""KiCad net class resolution matches PCBWorld pcbench_prep."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.netclass import kicad_pattern_match, resolve_net_classes


class NetclassTests(unittest.TestCase):
    def test_wildcard_case_sensitive(self):
        self.assertTrue(kicad_pattern_match("NET*", "NET1"))
        self.assertFalse(kicad_pattern_match("net*", "NET1"))

    def test_priority_explicit_over_pattern(self):
        settings = {
            "classes": [
                {"name": "Default", "nets": []},
                {"name": "Power", "nets": ["VCC"], "track_width": 0.5, "clearance": 0.3},
            ],
            "netclass_patterns": [{"pattern": "V*", "netclass": "Default"}],
        }
        resolved = resolve_net_classes(settings, ["VCC", "GND"])
        self.assertEqual(resolved["VCC"], "Power")
        self.assertEqual(resolved["GND"], "Default")


if __name__ == "__main__":
    unittest.main()