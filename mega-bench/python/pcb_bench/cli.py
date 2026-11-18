import argparse
import json
import sys
import subprocess
from pathlib import Path
from .backends import BACKENDS
from .cases import load_case, snapshot
from .evaluation import KiCadToolchain
from .pipeline import make_plan
from .adapt import adapt_files
from .contracts import GeometryIRBundle, GeometryRoutingResult, KiCadCase
from .converters import KiCadGeometryConverter
from .runner import execute_run


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
    export = sub.add_parser("export-geometry", help="extract copper polygons using KiCad pcbnew")
    export.add_argument("--case", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--kicad-python", required=True)
    export.add_argument("--expected-version", required=True)
    export.add_argument("--max-error-mm", type=float, default=.005)
    adapt = sub.add_parser("adapt-geometry", help="convert kicad-geometry JSON into a routing board")
    adapt.add_argument("--geometry", type=Path, required=True)
    adapt.add_argument("--rules", type=Path, required=True)
    adapt.add_argument("--out", type=Path, required=True)
    write = sub.add_parser("write-routes", help="append routes.json copper onto a copy of a KiCad board")
    write.add_argument("--board", type=Path, required=True)
    write.add_argument("--project", type=Path, required=True)
    write.add_argument("--routes", type=Path, required=True)
    write.add_argument("--geometry", type=Path, required=True)
    write.add_argument("--out", type=Path, required=True)
    write.add_argument("--kicad-python", required=True)
    write.add_argument("--expected-version", required=True)
    run = sub.add_parser("run", help="route one case with a registered backend and write HTML plus evaluation")
    run.add_argument("--case", type=Path, required=True)
    run.add_argument("--backend", choices=list(BACKENDS), required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--toolchain", type=Path, required=True)
    run.add_argument("--kicad-python", type=Path, required=True)
    run.add_argument("--expected-version", required=True)
    run.add_argument("--router", type=Path)
    run.add_argument("--config", type=Path)
    run.add_argument("--krt-root", type=Path)
    run.add_argument("--freerouting-jar", type=Path)
    run.add_argument("--tracemaker-exe", type=Path)
    run.add_argument("--tracemaker-threads", type=int, default=1)
    run.add_argument("--tracemaker-variants", type=int, default=1)
    run.add_argument("--tracemaker-seed", type=int, default=1)
    run.add_argument("--max-passes", type=int, default=10)
    run.add_argument("--routing-seconds", type=float, default=300)
    run.add_argument("--evaluation-seconds", type=float, default=120)
    args = parser.parse_args(argv)
    try:
        if args.command == "export-geometry":
            converter = KiCadGeometryConverter(args.kicad_python, args.expected_version, args.max_error_mm)
            bundle = converter.import_board(load_case(args.case), args.out)
            result = {"geometry": str(bundle.board_ir), "report": str(bundle.conversion_report),
                      "status": "geometry_exported", "cpp_geometry_v1_compatible": False}
        elif args.command == "write-routes":
            board = args.board.resolve()
            project = args.project.resolve()
            case = KiCadCase(board.stem, board, project)
            bundle = GeometryIRBundle(args.geometry.resolve(), args.geometry.resolve(),
                                      args.geometry.resolve(), case, {})
            routed = KiCadGeometryConverter(args.kicad_python, args.expected_version).export_routes(
                bundle, GeometryRoutingResult(args.routes.resolve()), args.out)
            result = {"board": str(routed.case.board), "status": "routes_written",
                      **routed.diagnostics}
        elif args.command == "adapt-geometry":
            board = adapt_files(args.geometry, args.rules, args.out)
            result = {"board": str(args.out), "status": "routing_board", "pads": len(board["pads"]),
                      "nets": len(board["nets"]), "fixed_copper": len(board["fixed_copper"])}
        elif args.command == "run":
            result = execute_run(args.case, args.backend, args.out, args.toolchain, args.kicad_python,
                                 args.expected_version, router=args.router, config=args.config,
                                 krt_root=args.krt_root, freerouting_jar=args.freerouting_jar,
                                 max_passes=args.max_passes, routing_seconds=args.routing_seconds,
                                 evaluation_seconds=args.evaluation_seconds,
                                 tracemaker_exe=args.tracemaker_exe,
                                 tracemaker_threads=args.tracemaker_threads,
                                 tracemaker_variants=args.tracemaker_variants,
                                 tracemaker_seed=args.tracemaker_seed)
        elif args.command == "doctor":
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
