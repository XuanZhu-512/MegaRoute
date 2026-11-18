"""One case, one backend, one result directory shared by MegaRoute and KRT."""
import json
import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from .adapt import adapt_files
from .backends import backend_spec
from .cases import fingerprints, load_case, snapshot, sha256
from .contracts import GeometryIRBundle, GeometryRoutingResult, KiCadCase, RoutedKiCadCase, RunBudget
from .converters import KiCadGeometryConverter
from .evaluation import ExternalKiCadEvaluator, KiCadToolchain, kicad_env
from .freerouting_backend import DEFAULT_FREEROUTING_JAR, run_freerouting
from .krt_backend import DEFAULT_KRT_ROOT, DEFAULT_KRT_RUNNER, krt_arguments, run_krt
from .tracemaker_backend import route_tracemaker

BENCH = Path(__file__).resolve().parents[2]
REPORT = BENCH / "tools" / "route_report.py"
GEOMETRY_VIEW = BENCH / "tools" / "visualize_geometry.py"
DEFAULT_MEGAROUTE_CONFIG = BENCH / "configs" / "megaroute.json"


def router_config(config) -> Path:
    return Path(config) if config else DEFAULT_MEGAROUTE_CONFIG


def recorded_algorithm(backend, config=None) -> str:
    if backend != "megaroute":
        return backend_spec(backend).backend_id
    path = router_config(config)
    if not path.is_file():
        raise FileNotFoundError(f"router config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["algorithm"]


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
                freerouting_jar=None, max_passes=10,
                routing_seconds=300, evaluation_seconds=120,
                tracemaker_exe=None, tracemaker_threads=1, tracemaker_variants=1, tracemaker_seed=1):
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
    algorithm = recorded_algorithm(backend, config)
    out.mkdir(parents=True, exist_ok=True)
    pcbnew = _pcbnew_path(toolchain)
    env = kicad_env(pcbnew)
    manifest = {"schema_version": "1.0", "case_id": case.case_id, "backend": backend,
                "status": "started", "input_hashes": fingerprints(case),
                "algorithm": algorithm,
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
            manifest["router"] = json.loads((out / "work" / "router_identity.json").read_text())
        elif backend == "krt":
            route_time = _route_krt(kicad_python, bundle, out, krt_root or DEFAULT_KRT_ROOT,
                                    krt_runner or DEFAULT_KRT_RUNNER, budget)
        elif backend == "tracemaker":
            record = route_tracemaker(bundle.source_case, out, budget, tracemaker_exe,
                                      tracemaker_threads, tracemaker_variants, tracemaker_seed)
            route_time = record["wall_s"]
            manifest["router"] = record
        elif backend == "freerouting":
            route_time = _route_freerouting(kicad_python, bundle, out, env, expected_version,
                                            freerouting_jar or DEFAULT_FREEROUTING_JAR,
                                            max_passes, budget)
        else:
            raise ValueError(f"backend has no execution adapter: {backend}")
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
    default_router = router is None
    router = Path(router) if router else BENCH / "build" / "dev" / "megaroute_cli"
    config = router_config(config)
    if not router.is_file():
        raise FileNotFoundError(f"megaroute_cli not found: {router}")
    if not config.is_file():
        raise FileNotFoundError(f"router config not found: {config}")
    probe = subprocess.run([str(router), "--build-info"], capture_output=True, text=True,
                           timeout=15, check=True)
    identity = json.loads(probe.stdout)
    sources = ("src/geometry.cpp", "src/spatial.cpp", "src/model.cpp", "src/drc.cpp", "src/router.cpp",
               "include/megaroute/core.hpp", "apps/main.cpp", "CMakeLists.txt",
               "include/megaroute/build_identity.hpp.in")
    digests = "".join(f"{name}:{sha256(BENCH / name)}\n" for name in sources)
    current = hashlib.sha256(digests.encode()).hexdigest()
    if default_router and identity["source_fingerprint"] != current:
        raise RuntimeError("MegaRoute binary is stale; run cmake --build mega-bench/build/dev")
    effective = effective_router_config(json.loads(config.read_text()), budget)
    effective_path = out / "work" / "effective_config.json"
    _write(effective_path, effective)
    identity.update(executable=str(router.resolve()), executable_sha256=sha256(router),
                    config_sha256=sha256(config), effective_config=effective,
                    current_source_fingerprint=current)
    _write(out / "work" / "router_identity.json", identity)
    board_json = out / "work" / "board.json"
    adapt_files(bundle.board_ir, bundle.conversion_report.parent / "project_rules.json", board_json)
    route_dir = out / "work" / "route"
    started = time.perf_counter()
    try:
        proc = subprocess.run([str(router), "route", "--board", str(board_json), "--config", str(effective_path),
                               "--out", str(route_dir), "--events"],
                              capture_output=True, text=True, timeout=budget.routing_seconds, check=False)
    except subprocess.TimeoutExpired as exc:
        # Only recover an atomically published, structurally valid legal checkpoint.
        checkpoint = route_dir / "routes.json"
        if not checkpoint.is_file():
            raise
        data = json.loads(checkpoint.read_text())
        if data.get("schema_version") != "1.0" or not isinstance(data.get("copper"), list):
            raise RuntimeError("invalid MegaRoute timeout checkpoint") from exc
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        proc = subprocess.CompletedProcess(exc.cmd, 2, decoded(exc.stdout), decoded(exc.stderr))
        identity["watchdog_terminated"] = True
        _write(out / "work" / "router_identity.json", identity)
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


def effective_router_config(config, budget):
    """Leave time for checkpoint/final serialization within the process watchdog."""
    effective = dict(config)
    internal_limit = config.get("time_limit_s", 60)
    allowance = budget.routing_seconds - min(10, budget.routing_seconds * .1)
    effective["time_limit_s"] = min(internal_limit, allowance)
    return effective


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
    if (not destination.is_file() or destination.stat().st_size == 0) and payload["returncode"] == 0:
        shutil.copy2(source.board, destination)
        record["copied_input"] = True
        _write(out / "work" / "krt_run.json", record)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"KRT produced no board (exit {payload['returncode']})")
    return payload["wall_s"]


def _specctra(python, env, expected_version, args):
    worker = Path(__file__).with_name("kicad_specctra_worker.py")
    proc = subprocess.run([str(python), str(worker), *args, "--expected-version", expected_version],
                          capture_output=True, text=True, env=env, timeout=120, check=False)
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"KiCad Specctra bridge failed: {detail}")


def _route_freerouting(python, bundle, out, env, expected_version, jar, max_passes, budget):
    source = bundle.source_case
    work = out / "work" / "freerouting"
    work.mkdir(parents=True, exist_ok=True)
    dsn = (work / "board.dsn").resolve()
    ses = (work / "board.ses").resolve()
    log_path = work / "routing.log"
    _specctra(python, env, expected_version,
              ["--action", "export-dsn", "--board", str(source.board.resolve()), "--dsn", str(dsn)])
    payload = run_freerouting(jar, dsn, ses, (work / "tmp").resolve(), max_passes,
                              budget.routing_seconds, log_path)
    _write(work / "freerouting_run.json",
           {"jar": str(jar), "max_passes": max_passes, "returncode": payload["returncode"],
            "wall_s": payload["wall_s"], "command": payload["command"]})
    if not ses.is_file() or ses.stat().st_size == 0:
        raise RuntimeError(f"FreeRouting produced no SES (exit {payload['returncode']})")
    routed_dir = out / "routed"
    routed_dir.mkdir(parents=True, exist_ok=True)
    destination = (routed_dir / source.board.name).resolve()
    shutil.copy2(source.project, routed_dir / source.project.name)
    if source.custom_rules:
        shutil.copy2(source.custom_rules, routed_dir / source.custom_rules.name)
    _specctra(python, env, expected_version,
              ["--action", "import-ses", "--board", str(source.board.resolve()),
               "--ses", str(ses), "--out", str(destination)])
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("FreeRouting SES import produced no board")
    return payload["wall_s"]
