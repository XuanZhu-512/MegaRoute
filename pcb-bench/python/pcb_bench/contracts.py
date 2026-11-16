"""Boundaries between case preparation, conversion, routing and external scoring."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class UnsupportedCapability(RuntimeError):
    """A declared but not yet implemented capability; never a successful empty result."""


@dataclass(frozen=True)
class KiCadCase:
    case_id: str
    board: Path
    project: Path
    custom_rules: Path | None = None
    # All input copper is immutable in the initial contract. Strip editable/reference
    # routes OFFLINE, identically for every backend, before creating this case.
    copper_policy: str = "preserve_input"


@dataclass(frozen=True)
class GeometryIRBundle:
    """IR alone is insufficient to reconstruct the entire original KiCad project."""
    board_ir: Path
    source_map: Path
    conversion_report: Path
    source_case: KiCadCase
    source_hashes: dict[str, str]


@dataclass(frozen=True)
class GeometryRoutingResult:
    # Existing v1 routes JSON is append-only. Full-board replacement is not allowed.
    added_copper: Path
    internal_diagnostics: Path | None = None


@dataclass(frozen=True)
class RunBudget:
    routing_seconds: float
    evaluation_seconds: float
    threads: int = 1

    def __post_init__(self):
        import math
        if (not math.isfinite(self.routing_seconds) or self.routing_seconds <= 0
                or not math.isfinite(self.evaluation_seconds) or self.evaluation_seconds <= 0
                or isinstance(self.threads, bool) or not isinstance(self.threads, int) or self.threads < 1):
            raise ValueError("invalid run budget")


@dataclass(frozen=True)
class RoutedKiCadCase:
    case: KiCadCase
    raw_artifacts: tuple[Path, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExternalEvaluation:
    evaluator: str
    toolchain_fingerprint: dict[str, str]
    raw_report: Path
    metrics: dict[str, Any]
    # Missing external metrics must be null/unsupported, never filled from mr::evaluate.


class KiCadGeometryBridge(Protocol):
    def preflight(self) -> None: ...
    def import_board(self, case: KiCadCase, workdir: Path) -> GeometryIRBundle: ...
    def export_routes(self, bundle: GeometryIRBundle, routes: GeometryRoutingResult,
                      workdir: Path) -> RoutedKiCadCase: ...


class RouterBackend(Protocol):
    backend_id: str
    def preflight(self) -> None: ...
    def route(self, case: KiCadCase, workdir: Path, budget: RunBudget,
              config: dict[str, Any]) -> RoutedKiCadCase: ...


class KiCadEvaluator(Protocol):
    def preflight(self) -> dict[str, str]: ...
    def evaluate(self, original: KiCadCase, routed: RoutedKiCadCase,
                 workdir: Path, budget: RunBudget) -> ExternalEvaluation: ...
