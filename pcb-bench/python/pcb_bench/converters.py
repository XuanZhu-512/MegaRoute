"""KiCad-native geometry extraction in an isolated, version-checked worker."""
import json
import math
import subprocess
import tempfile
from pathlib import Path
from .cases import fingerprints, snapshot
from .contracts import (GeometryIRBundle, GeometryRoutingResult, KiCadCase,
                        RoutedKiCadCase, UnsupportedCapability)


class KiCadGeometryConverter:
    def __init__(self, python_executable=None, expected_version=None, max_error_mm=.005, env=None):
        self.python_executable = python_executable
        self.expected_version = expected_version
        self.max_error_mm = max_error_mm
        self.env = env

    def preflight(self) -> None:
        if not self.python_executable or not self.expected_version:
            raise UnsupportedCapability("KiCad Python executable and exact expected version are required")
        if not math.isfinite(self.max_error_mm) or not .000001 <= self.max_error_mm <= .1:
            raise ValueError("max_error_mm must be between 0.000001 and 0.1")

    def import_board(self, case: KiCadCase, workdir: Path) -> GeometryIRBundle:
        self.preflight()
        workdir = workdir.resolve()
        if workdir.exists():
            raise ValueError("export destination must not exist")
        initial = fingerprints(case)
        workdir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.geometry-export-', dir=workdir.parent) as tmp:
            staging = Path(tmp)
            source = snapshot(case, staging/'source')
            worker = Path(__file__).with_name('kicad_export_worker.py')
            proc = subprocess.run([str(self.python_executable), str(worker), '--board', str(source.board),
                                   '--out', str(staging), '--expected-version', self.expected_version,
                                   '--max-error-mm', str(self.max_error_mm)],
                                  capture_output=True, text=True, timeout=120, env=self.env)
            if proc.returncode:
                raise RuntimeError(f"KiCad geometry export failed: {proc.stderr.strip()}")
            if fingerprints(case) != initial or fingerprints(source) != initial:
                raise RuntimeError("source files changed during export")
            project = json.loads(source.project.read_text(encoding='utf-8'))
            (staging/'project_rules.json').write_text(json.dumps(project, indent=2), encoding='utf-8')
            report_path = staging/'conversion_report.json'
            report = json.loads(report_path.read_text(encoding='utf-8'))
            report.update(source_hashes=initial, case_id=case.case_id,
                          worker_stderr=proc.stderr.strip(), python_executable=str(self.python_executable))
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            # Only publish the directory after every extraction/check has succeeded.
            staging.rename(workdir)
        copied = KiCadCase(case.case_id, workdir/'source'/case.board.name,
                           workdir/'source'/case.project.name,
                           workdir/'source'/case.custom_rules.name if case.custom_rules else None)
        return GeometryIRBundle(workdir/'geometry.json', workdir/'source_map.json',
                                workdir/'conversion_report.json', copied, initial)

    def export_routes(self, bundle: GeometryIRBundle, routes: GeometryRoutingResult,
                      workdir: Path) -> RoutedKiCadCase:
        self.preflight()
        workdir = workdir.resolve()
        if workdir.exists():
            raise ValueError("writeback destination must not exist")
        initial = fingerprints(bundle.source_case)
        workdir.parent.mkdir(parents=True, exist_ok=True)
        copied = snapshot(bundle.source_case, workdir)
        route_data = json.loads(routes.added_copper.read_text(encoding="utf-8"))
        copper = route_data.get("copper", [])
        report = {"added": 0, "uuids": [], "preserved_without_routes": not copper}
        if copper:
            worker = Path(__file__).with_name("kicad_write_worker.py")
            proc = subprocess.run([str(self.python_executable), str(worker), "--board", str(copied.board),
                                   "--out", str(copied.board), "--routes", str(routes.added_copper),
                                   "--geometry", str(bundle.board_ir),
                                   "--expected-version", self.expected_version],
                                  capture_output=True, text=True, timeout=120, env=self.env)
            if proc.returncode:
                raise RuntimeError(f"KiCad route writeback failed: {proc.stderr.strip()}")
            report = json.loads(proc.stdout)
        if fingerprints(bundle.source_case) != initial:
            raise RuntimeError("original source changed during writeback")
        (workdir / "writeback_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return RoutedKiCadCase(copied, raw_artifacts=(copied.board,), diagnostics=report)
