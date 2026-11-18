"""A routed board gets a stacked HTML report; a run without one does not."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("route_report", ROOT / "tools" / "route_report.py")
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


class RouteReportTests(unittest.TestCase):
    def test_page_stacks_unrouted_geometry_above_routed_image(self):
        html = report.render_report("test_board_00000 · krt", "preview/board.svg", "routed_view/board.svg")
        unrouted = html.index("未布线（几何导出）")
        routed = html.index("布线完毕")
        self.assertLess(unrouted, routed)
        self.assertLess(html.index('src="preview/board.svg"'), html.index('src="routed_view/board.svg"'))
        self.assertIn("<title>test_board_00000 · krt</title>", html)

    def test_missing_board_writes_no_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "preview").mkdir()
            (run / "preview" / "board.svg").write_text("<svg/>", encoding="utf-8")
            self.assertIsNone(report.write_task_report(run))
            self.assertFalse((run / "report.html").exists())

    def test_routed_board_writes_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            for folder in ("preview", "routed_view", "routed"):
                (run / folder).mkdir()
            (run / "preview" / "board.svg").write_text("<svg/>", encoding="utf-8")
            (run / "routed_view" / "board.svg").write_text("<svg/>", encoding="utf-8")
            (run / "routed" / "board.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
            (run / "manifest.json").write_text(json.dumps({"case_id": "case1", "backend": "krt"}),
                                               encoding="utf-8")
            html = report.write_task_report(run)
            text = html.read_text(encoding="utf-8")
            self.assertIn("case1 · krt", text)
            self.assertIn("preview/board.svg", text)
            self.assertIn("routed_view/board.svg", text)


if __name__ == "__main__":
    unittest.main()
