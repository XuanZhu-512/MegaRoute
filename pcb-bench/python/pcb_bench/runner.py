"""One case, one backend, one result directory shared by MegaRoute and KRT."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .adapt import adapt_files
from .backends import backend_spec
from .cases import fingerprints, load_case, snapshot
from .contracts import GeometryIRBundle, GeometryRoutingResult, KiCadCase, RoutedKiCadCase, RunBudget
from .converters import KiCadGeometryConverter
from .evaluation import ExternalKiCadEvaluator, KiCadToolchain, kicad_env
from .krt_backend import DEFAULT_KRT_ROOT, DEFAULT_KRT_RUNNER, krt_arguments, run_krt

BENCH = Path(__file__).resolve().parents[2]
REPORT = BENCH / "tools" / "route_report.py"
GEOMETRY_VIEW = BENCH / "tools" / "visualize_geometry.py"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _pcbnew_path(toolchain: KiCadToolchain) -> Path:
    executable = Path(toolchain.executable)
    if executable.is_absolute():
        candidate = executable.resolve().parents[1] / "pcbnew"
        if (candidate / "pcbnew.py").is_file() or (candidate / "_pcbnew.so").is_file():
            return candidate
    found = os.environ.get("PCBNEW_PATH")
    if found:
        return Path(found)
    raise RuntimeError("cannot locate pcbnew next to kicad-cli; set PCBNEW_PATH")


def _preview(python, geometry: Path, out_dir: Path, env) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    proc = subprocess.run([str(python), str(GEOMETRY_VIEW), "--geometry", str(geometry), "--out", str(out_dir)],
                          capture_output=True, text=True, env=env, check=False)
    if proc.returncode:
        raise RuntimeError(f"geometry preview failed: {proc.stderr.strip()}")


def _routed_board(run_dir: Path) -> Path | None:
    routed = run_dir / "routed"
    if not routed.is_dir():
        return None
    boards = sorted(routed.glob("*.kicad_pcb"))
    return boards[0] if len(boards) == 1 else None


def execute_run(case_path, backend, out, toolchain_path, kicad_python, expected_version,
                router=None, config=None, krt_root=None, krt_runner=None,
                routing_seconds=300, evaluation_seconds=120):
    spec = backend_spec(backend)
    if backend != "megaroute":
        spec.preflight()
    case = load_case(Path(case_path))
    toolchain = KiCadToolchain.load(Path(toolchain_path))
    if toolchain.exact_version != expected_version:
        raise ValueError(f"expected-version {expected_version} does not match toolchain {toolchain.exact_version}")
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise ValueError("output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    pcbnew = _pcbnew_path(toolchain)
    env = kicad_env(pcbnew)
    manifest = {"schema_version": "1.0", "case_id": case.case_id, "backend": backend,
                "status": "started", "input_hashes": fingerprints(case),
                "algorithm": "adaptive_strict" if backend == "megaroute" else "krt",
                "kicad_version": expected_version}
    _write(out / "manifest.json", manifest)
    try:
        copied = snapshot(case, out / "input")
        converter = KiCadGeometryConverter(kicad_python, expected_version, env=env)
        bundle = converter.import_board(copied, out / "work" / "export")
        _preview(kicad_python, bundle.board_ir, out / "preview", env)
        budget = RunBudget(routing_seconds, evaluation_seconds)
        if backend == "megaroute":
            route_time = _route_megaroute(converter, bundle, out, router, config, budget)
        else:
            route_time = _route_krt(kicad_python, bundle, out, krt_root or DEFAULT_KRT_ROOT,
                                    krt_runner or DEFAULT_KRT_RUNNER, budget)
        board = _routed_board(out)
        if board is None:
            manifest["status"] = "no_routed_board"
            manifest["route_time_s"] = route_time
            _write(out / "manifest.json", manifest)
            return manifest
        routed_case_dir = board.parent
        routed_case = KiCadCase(copied.case_id, board, routed_case_dir / copied.project.name,
                                copied.custom_rules, copied.copper_policy)
        routed_bundle = converter.import_board(routed_case, out / "work" / "routed_export")
        _preview(kicad_python, routed_bundle.board_ir, out / "routed_view", env)
        report_proc = subprocess.run([str(kicad_python), str(REPORT), "--run", str(out)],
                                     capture_output=True, text=True, env=env, check=False)
        if report_proc.returncode:
            raise RuntimeError(f"HTML report failed: {report_proc.stderr.strip()}")
        report = json.loads(report_proc.stdout)
        evaluator = ExternalKiCadEvaluator(toolchain, kicad_python, pcbnew)
        evaluator.case_id = case.case_id
        evaluator.backend = backend
        evaluator.route_time_s = route_time
        evaluation = evaluator.evaluate(copied, RoutedKiCadCase(routed_case, (board,)),
                                        out / "evaluation", budget)
        manifest.update(status="complete", route_time_s=route_time,
                        report=report.get("html"),
                        evaluation=str(out / "evaluation" / "metrics.json"),
                        clean_pass=evaluation.metrics["clean_pass"],
                        success=evaluation.metrics["success"])
        _write(out / "manifest.json", manifest)
        return manifest
    except Exception as exc:
        manifest.update(status="error", error=str(exc))
        _write(out / "manifest.json", manifest)
        raise


def _route_megaroute(converter, bundle, out, router, config, budget):
    router = Path(router) if router else BENCH / "build" / "dev" / "megaroute_cli"
    config = Path(config) if config else BENCH / "configs" / "adaptive_strict.json"
    if not router.is_file():
        raise FileNotFoundError(f"megaroute_cli not found: {router}")
    if not config.is_file():
        raise FileNotFoundError(f"router config not found: {config}")
    board_json = out / "work" / "board.json"
    adapt_files(bundle.board_ir, bundle.conversion_report.parent / "project_rules.json", board_json)
    route_dir = out / "work" / "route"
    started = time.perf_counter()
    proc = subprocess.run([str(router), "route", "--board", str(board_json), "--config", str(config),
                           "--out", str(route_dir), "--events"],
                          capture_output=True, text=True, timeout=budget.routing_seconds, check=False)
    elapsed = time.perf_counter() - started
    (out / "work" / "router.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    routes = route_dir / "routes.json"
    if proc.returncode not in (0, 2) or not routes.is_file():
        raise RuntimeError(f"megaroute_cli failed ({proc.returncode}): {proc.stderr.strip()}")
    # Write onto the input snapshot, not the dataset original.
    source = bundle.source_case
    routed = converter.export_routes(
        GeometryIRBundle(bundle.board_ir, bundle.source_map, bundle.conversion_report, source,
                         bundle.source_hashes),
        GeometryRoutingResult(routes), out / "routed")
    if not routed.case.board.is_file():
        raise RuntimeError("writeback did not produce a KiCad board")
    return elapsed


def _route_krt(python, bundle, out, krt_root, krt_runner, budget):
    rules = json.loads((bundle.conversion_report.parent / "project_rules.json").read_text(encoding="utf-8"))
    geometry = json.loads(bundle.board_ir.read_text(encoding="utf-8"))
    routed_dir = out / "routed"
    routed_dir.mkdir(parents=True, exist_ok=True)
    source = bundle.source_case
    destination = routed_dir / source.board.name
    shutil.copy2(source.project, routed_dir / source.project.name)
    if source.custom_rules:
        shutil.copy2(source.custom_rules, routed_dir / source.custom_rules.name)
    args = krt_arguments(source.board.resolve(), destination.resolve(), geometry, rules)
    payload = run_krt(python, krt_runner, krt_root, args, budget.routing_seconds)
    record = {"args": args, "krt_root": str(krt_root), "returncode": payload["returncode"],
              "wall_s": payload["wall_s"], "hyperparameters": "KRT_PAPER_ARGS"}
    _write(out / "work" / "krt_run.json", record)
    log = out / "work" / "routing.log"
    log.write_text(payload.get("stdout", "") + "\n" + payload.get("stderr", ""), encoding="utf-8")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"KRT produced no board (exit {payload['returncode']})")
    return payload["wall_s"]
