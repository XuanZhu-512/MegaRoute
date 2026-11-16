"""KiCad external evaluation boundary, with exact version enforcement.

DRC command construction and version probing are available. Full metric extraction
and structural invariance checking remain unimplemented; no internal-score fallback.
"""
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from .cases import sha256
from .contracts import UnsupportedCapability


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
        proc = subprocess.run([executable, "version"], capture_output=True, text=True,
                              timeout=15, check=True)
        actual = proc.stdout.strip()
        if actual != self.exact_version:
            raise RuntimeError(f"KiCad version mismatch: expected {self.exact_version}, got {actual!r}")
        return {"executable": str(Path(executable).resolve()), "version": actual,
                "executable_sha256": sha256(Path(executable))}


class ExternalKiCadEvaluator:
    def __init__(self, toolchain: KiCadToolchain):
        self.toolchain = toolchain

    def drc_command(self, board: Path, report: Path) -> list[str]:
        # Verified against KiCad 9 CLI documentation. Run after version preflight.
        return [self.toolchain.executable, "pcb", "drc", "--format", "json",
                "--units", "mm", "--severity-all", "--all-track-errors",
                "--exit-code-violations", "--output", str(report), str(board)]

    def preflight(self) -> dict[str, str]:
        self.toolchain.probe()
        raise UnsupportedCapability("external_kicad_metrics_and_invariant_checks_not_implemented")

    def evaluate(self, original, routed, workdir, budget):
        self.preflight()
        raise AssertionError("unreachable")
