"""FreeRouting command construction. These tests do not start a JVM."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from pcb_bench.backends import BACKENDS
from pcb_bench.freerouting_backend import (DEFAULT_MAX_PASSES, freerouting_command,
                                           parse_java_major, require_java_major)


class FreeRoutingCommandTests(unittest.TestCase):
    def test_command_matches_the_pinned_launcher(self):
        jar = Path("/opt/freerouting-2.1.0.jar")
        dsn = Path("/work/board.dsn")
        ses = Path("/work/board.ses")
        tmp = Path("/work/tmp")
        command = freerouting_command(jar, dsn, ses, tmp, DEFAULT_MAX_PASSES)
        self.assertEqual(command[0], "java")
        self.assertIn("-Djava.awt.headless=true", command)
        self.assertIn("-Djava.io.tmpdir=/work/tmp", command)
        self.assertEqual(command[command.index("-jar") + 1], str(jar))
        self.assertEqual(command[command.index("-de") + 1], str(dsn))
        self.assertEqual(command[command.index("-do") + 1], str(ses))
        self.assertEqual(command[command.index("-mp") + 1], "10")
        self.assertEqual(BACKENDS["freerouting"].blockers, ())

    def test_java_21_is_accepted_and_17_is_rejected(self):
        self.assertEqual(require_java_major('openjdk version "21.0.2" 2024-01-16'), 21)
        with self.assertRaises(RuntimeError):
            require_java_major('openjdk version "17.0.9"')
        self.assertEqual(parse_java_major('java version "1.8.0_392"'), 8)


if __name__ == "__main__":
    unittest.main()
