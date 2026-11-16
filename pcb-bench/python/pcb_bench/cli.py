import argparse
import json
import sys
import subprocess
from pathlib import Path
from .backends import BACKENDS
from .cases import load_case, snapshot
from .evaluation import KiCadToolchain
from .pipeline import make_plan


def main(argv=None):
    parser = argparse.ArgumentParser(description="KiCad-first PCB benchmark architecture tools")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="validate case files and display backend/evaluation plan")
    plan.add_argument("--case", type=Path, required=True)
    plan.add_argument("--backend", choices=list(BACKENDS), required=True)
    plan.add_argument("--toolchain", type=Path, required=True)
    prepare = sub.add_parser("snapshot", help="copy input PCB and rules without modifying them")
    prepare.add_argument("--case", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    doctor = sub.add_parser("doctor", help="verify exact installed KiCad version")
    doctor.add_argument("--toolchain", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = KiCadToolchain.load(args.toolchain).probe()
        elif args.command == "snapshot":
            case = snapshot(load_case(args.case), args.out)
            result = {"case_id": case.case_id, "board": str(case.board),
                      "status": "input_snapshot_only", "evaluation": None}
        else:
            result = make_plan(load_case(args.case), args.backend, KiCadToolchain.load(args.toolchain))
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
