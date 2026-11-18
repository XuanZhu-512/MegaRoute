"""HTML report shared by MegaRoute and KRT.

The top image is the unrouted geometry export. The bottom image is a geometry
export of the routed KiCad board. A page is written only when that board exists.
"""
import argparse
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape


def render_report(title, unrouted_href, routed_href):
    safe_title = escape(title)
    unrouted = escape(unrouted_href, {'"': "&quot;"})
    routed = escape(routed_href, {'"': "&quot;"})
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
  body {{ margin: 0; background: #f4f5f6; color: #222; font-family: sans-serif; }}
  main {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 20px; font-weight: 600; }}
  section {{ background: #fff; border: 1px solid #ddd; margin: 16px 0 0; padding: 16px; }}
  h2 {{ margin: 0 0 12px; font-size: 16px; font-weight: 600; }}
  img {{ width: 100%; height: auto; display: block; background: #fff; }}
</style>
</head>
<body>
<main>
  <h1>{safe_title}</h1>
  <section>
    <h2>未布线（几何导出）</h2>
    <img src="{unrouted}" alt="未布线几何导出">
  </section>
  <section>
    <h2>布线完毕</h2>
    <img src="{routed}" alt="布线完毕">
  </section>
</main>
</body>
</html>
"""


def routed_board(run_dir: Path):
    routed = run_dir / "routed"
    if not routed.is_dir():
        return None
    boards = sorted(routed.glob("*.kicad_pcb"))
    if len(boards) != 1:
        return None
    return boards[0]


def write_task_report(run_dir, html_path=None):
    run_dir = Path(run_dir)
    if routed_board(run_dir) is None:
        return None
    preview = run_dir / "preview" / "board.svg"
    routed_svg = run_dir / "routed_view" / "board.svg"
    if not preview.is_file() or not routed_svg.is_file():
        raise FileNotFoundError("preview/board.svg and routed_view/board.svg are required")
    report_path = Path(html_path) if html_path else run_dir / "report.html"
    manifest_path = run_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        title = f"{manifest.get('case_id', run_dir.name)} · {manifest.get('backend', '')}".strip(" ·")
    else:
        title = run_dir.name
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.parent.resolve() == run_dir.resolve():
        unrouted_href = "preview/board.svg"
        routed_href = "routed_view/board.svg"
    else:
        unrouted_href = preview.resolve().as_uri()
        routed_href = routed_svg.resolve().as_uri()
    report_path.write_text(render_report(title, unrouted_href, routed_href), encoding="utf-8")
    return report_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write the shared before/after HTML when a routed board exists")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--html", type=Path)
    args = parser.parse_args(argv)
    try:
        report = write_task_report(args.run, args.html)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    if report is None:
        print(json.dumps({"status": "skipped", "reason": "no_routed_board"}, indent=2))
        return 0
    print(json.dumps({"status": "report", "html": str(report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
