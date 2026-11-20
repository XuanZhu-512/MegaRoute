"""KiCad external evaluation. Scores come from kicad-cli DRC and pcbnew, never from mr::evaluate."""
import csv
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from .cases import sha256
from .contracts import ExternalEvaluation, RunBudget, KiCadCase, RoutedKiCadCase


@dataclass(frozen=True)
class KiCadToolchain:
    executable: str
    exact_version: str

    @classmethod
    def load(cls, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        if set(data) != {"schema_version", "kicad_cli", "exact_version"} or data["schema_version"] != "1.0":
            raise ValueError("invalid toolchain lock")
        if not isinstance(data["exact_version"], str) or not re.fullmatch(r"\d+\.\d+\.\d+", data["exact_version"]):
            raise ValueError("exact KiCad major.minor.patch version required")
        executable = data["kicad_cli"]
        if not isinstance(executable, str) or not executable:
            raise ValueError("kicad_cli is required")
        if not Path(executable).is_absolute() and ("/" in executable or "\\" in executable):
            executable = str((path.resolve().parent / executable).resolve())
        return cls(executable, data["exact_version"])

    def probe(self) -> dict[str, str]:
        executable = shutil.which(self.executable)
        if executable is None:
            raise RuntimeError(f"KiCad executable unavailable: {self.executable}")
        env = dict(os.environ)
        env["KICAD_RUN_FROM_BUILD_DIR"] = "1"
        proc = subprocess.run([executable, "version"], capture_output=True, text=True,
                              timeout=15, check=True, env=env)
        actual = proc.stdout.strip()
        if actual != self.exact_version:
            raise RuntimeError(f"KiCad version mismatch: expected {self.exact_version}, got {actual!r}")
        return {"executable": str(Path(executable).resolve()), "version": actual,
                "executable_sha256": sha256(Path(executable))}


METRIC_FIELDS = (
    "case_id", "backend", "success", "routability", "connections_required", "connections_made",
    "track_count", "via_count", "wirelength_mm", "fixed_wirelength_mm", "drv_error_count",
    "drv_warning_count", "unconnected_item_count", "clean_pass", "invalid_output",
    "route_time_s", "drc_exit_code",
)


def count_drc(report: dict) -> dict:
    errors = warnings = 0
    for item in report.get("violations") or []:
        if item.get("excluded"):
            continue
        if item.get("severity") == "error":
            errors += 1
        elif item.get("severity") == "warning":
            warnings += 1
    return {"drv_error_count": errors, "drv_warning_count": warnings,
            "unconnected_item_count": len(report.get("unconnected_items") or [])}


def connection_score(initial: dict, final: dict) -> dict:
    """PCBWorld routability: sum(G0-Gt) / sum(G0-1). Success means every net is one pad group."""
    required = made = 0
    success = set(initial) == set(final)
    for net, groups in initial.items():
        remaining = final.get(net)
        if not isinstance(groups, int) or groups < 1 or not isinstance(remaining, int) or remaining < 1:
            success = False
            continue
        required += groups - 1
        made += groups - remaining
        if remaining != 1:
            success = False
    return {"success": success, "routability": 1.0 if required == 0 else made / required,
            "connections_required": required, "connections_made": made}


def pads_preserved(original_pads, routed_pads, original_keys=None, routed_keys=None) -> bool:
    """Pads remain when their uuids do. Legacy boards get a new uuid on every load."""
    original_ids = set(original_pads)
    routed_ids = set(routed_pads)
    if original_ids <= routed_ids:
        return True
    if original_keys is None or routed_keys is None or not original_ids.isdisjoint(routed_ids):
        return False
    return not (Counter(original_keys) - Counter(routed_keys))


def build_metrics(case_id, backend, initial_groups, final_groups, original_copper, routed_copper,
                  original_pads, routed_pads, drc_counts, route_time_s, drc_exit_code,
                  original_pad_keys=None, routed_pad_keys=None) -> dict:
    score = connection_score(initial_groups, final_groups)
    original_ids = {item["uuid"] for item in original_copper}
    added = [item for item in routed_copper if item["uuid"] not in original_ids]
    fixed = [item for item in routed_copper if item["uuid"] in original_ids]

    def length(items):
        return sum(item["length_mm"] for item in items if item["kind"] != "via")

    invalid = not pads_preserved(original_pads, routed_pads, original_pad_keys, routed_pad_keys)
    success = score["success"] and not invalid
    metrics = {
        "case_id": case_id,
        "backend": backend,
        "success": success,
        "routability": score["routability"],
        "connections_required": score["connections_required"],
        "connections_made": score["connections_made"],
        "track_count": sum(item["kind"] != "via" for item in added),
        "via_count": sum(item["kind"] == "via" for item in added),
        "wirelength_mm": length(added),
        "fixed_wirelength_mm": length(fixed),
        "drv_error_count": drc_counts["drv_error_count"],
        "drv_warning_count": drc_counts["drv_warning_count"],
        "unconnected_item_count": drc_counts["unconnected_item_count"],
        "clean_pass": success and drc_counts["drv_error_count"] == 0,
        "invalid_output": invalid,
        "route_time_s": route_time_s,
        "drc_exit_code": drc_exit_code,
    }
    missing = [field for field in METRIC_FIELDS if field not in metrics]
    if missing:
        raise RuntimeError(f"metrics missing fields: {missing}")
    return metrics


def kicad_env(pcbnew_path: Path) -> dict:
    env = dict(os.environ)
    env["KICAD_RUN_FROM_BUILD_DIR"] = "1"
    prefix = str(pcbnew_path)
    current = env.get("PYTHONPATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    if prefix not in parts:
        env["PYTHONPATH"] = os.pathsep.join([prefix, *parts]) if parts else prefix
    return env


class ExternalKiCadEvaluator:
    def __init__(self, toolchain: KiCadToolchain, kicad_python=None, pcbnew_path=None):
        self.toolchain = toolchain
        self.kicad_python = kicad_python
        self.pcbnew_path = Path(pcbnew_path) if pcbnew_path else None
        self.route_time_s = None
        self.case_id = None
        self.backend = None

    def drc_command(self, board: Path, report: Path) -> list[str]:
        # Verified against KiCad 9 CLI documentation. Run after version preflight.
        return [self.toolchain.executable, "pcb", "drc", "--format", "json",
                "--units", "mm", "--severity-all", "--all-track-errors",
                "--exit-code-violations", "--output", str(report), str(board)]

    def preflight(self) -> dict[str, str]:
        return self.toolchain.probe()

    def _board_stats(self, board: Path, budget: RunBudget) -> dict:
        if not self.kicad_python or self.pcbnew_path is None:
            raise RuntimeError("KiCad Python and pcbnew path are required to score a board")
        worker = Path(__file__).with_name("kicad_metrics_worker.py")
        proc = subprocess.run([str(self.kicad_python), str(worker), "--board", str(board),
                               "--expected-version", self.toolchain.exact_version],
                              capture_output=True, text=True, timeout=budget.evaluation_seconds,
                              env=kicad_env(self.pcbnew_path), check=False)
        if proc.returncode:
            raise RuntimeError(f"pcbnew metrics failed for {board.name}: {proc.stderr.strip()}")
        return json.loads(proc.stdout)

    def evaluate(self, original: KiCadCase, routed: RoutedKiCadCase, workdir: Path,
                 budget: RunBudget) -> ExternalEvaluation:
        if self.route_time_s is None or self.case_id is None or self.backend is None:
            raise RuntimeError("case_id, backend, and route_time_s are required")
        fingerprint = self.preflight()
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        report_path = workdir / "drc.json"
        env = kicad_env(self.pcbnew_path) if self.pcbnew_path else dict(os.environ)
        env["KICAD_RUN_FROM_BUILD_DIR"] = "1"
        proc = subprocess.run(self.drc_command(routed.case.board, report_path),
                              capture_output=True, text=True, timeout=budget.evaluation_seconds,
                              env=env, check=False)
        if proc.returncode not in (0, 5) or not report_path.is_file():
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"KiCad DRC failed ({proc.returncode}): {detail}")
        drc_counts = count_drc(json.loads(report_path.read_text(encoding="utf-8")))
        before = self._board_stats(original.board, budget)
        after = self._board_stats(routed.case.board, budget)
        metrics = build_metrics(self.case_id, self.backend, before["pad_groups"], after["pad_groups"],
                                before["copper"], after["copper"], before["pad_uuids"], after["pad_uuids"],
                                drc_counts, self.route_time_s, proc.returncode,
                                before.get("pad_keys"), after.get("pad_keys"))
        metadata = {"schema_version": "1.0", "connectivity_policy": "direct_pad_contacts_v2",
                    "metrics_worker_sha256": sha256(Path(__file__).with_name("kicad_metrics_worker.py")),
                    "toolchain": fingerprint}
        (workdir / "evaluator.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        (workdir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        with (workdir / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, METRIC_FIELDS)
            writer.writeheader()
            writer.writerow({field: metrics[field] for field in METRIC_FIELDS})
        return ExternalEvaluation("external_kicad", fingerprint, report_path, metrics)
