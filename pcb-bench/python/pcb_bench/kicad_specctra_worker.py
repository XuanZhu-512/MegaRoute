"""Export a Specctra DSN or import a SES with KiCad's pcbnew. Run with KiCad's Python."""
import argparse
import json
import sys
from pathlib import Path


def export_dsn(p, board_path, dsn_path, expected_version):
    actual = p.Version()
    if actual != expected_version:
        raise ValueError(f"KiCad version mismatch: expected {expected_version}, got {actual}")
    board = p.LoadBoard(str(board_path))
    if board is None:
        raise ValueError("KiCad could not load board")
    if not p.ExportSpecctraDSN(board, str(dsn_path)):
        raise RuntimeError("ExportSpecctraDSN failed")
    if not Path(dsn_path).is_file() or Path(dsn_path).stat().st_size == 0:
        raise RuntimeError("ExportSpecctraDSN produced no DSN")


def import_ses(p, board_path, ses_path, out_path, expected_version):
    actual = p.Version()
    if actual != expected_version:
        raise ValueError(f"KiCad version mismatch: expected {expected_version}, got {actual}")
    board = p.LoadBoard(str(board_path))
    if board is None:
        raise ValueError("KiCad could not load board")
    if not p.ImportSpecctraSES(board, str(ses_path)):
        raise RuntimeError("ImportSpecctraSES failed")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    board.Save(str(out_path))
    if not Path(out_path).is_file() or Path(out_path).stat().st_size == 0:
        raise RuntimeError("ImportSpecctraSES produced no board")


def main(argv=None):
    parser = argparse.ArgumentParser(description="KiCad Specctra DSN/SES bridge")
    parser.add_argument("--action", choices=("export-dsn", "import-ses"), required=True)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--dsn", type=Path)
    parser.add_argument("--ses", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)
    try:
        import pcbnew
        if args.action == "export-dsn":
            if args.dsn is None:
                raise ValueError("--dsn is required")
            export_dsn(pcbnew, args.board, args.dsn, args.expected_version)
        else:
            if args.ses is None or args.out is None:
                raise ValueError("--ses and --out are required")
            import_ses(pcbnew, args.board, args.ses, args.out, args.expected_version)
        print(json.dumps({"status": args.action}))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
