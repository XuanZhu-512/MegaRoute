"""Backend identity and IO plans; native adapters are deliberately not fabricated."""
from dataclasses import dataclass
from .contracts import UnsupportedCapability


@dataclass(frozen=True)
class BackendSpec:
    backend_id: str
    stages: tuple[str, ...]
    blockers: tuple[str, ...]

    def preflight(self) -> None:
        if self.blockers:
            raise UnsupportedCapability(f"{self.backend_id}: " + ", ".join(self.blockers))


BACKENDS = {
    "megaroute": BackendSpec("megaroute", (
        "kicad_to_geometry_ir", "cpp_geometry_router", "geometry_ir_to_kicad"), (
        "bidirectional KiCad/IR bridge", "full MegaRoute negotiated rerouting")),
    "freerouting": BackendSpec("freerouting", (
        "kicad_to_dsn", "freerouting_process", "ses_to_kicad"), (
        "KiCad DSN/SES bridge", "pinned Freerouting launcher")),
    "krt": BackendSpec("krt", ("krt_process", "verify_kicad_output"), (
        "pinned KiCadRoutingTools launcher and rule mapping",)),
}


def backend_spec(name: str) -> BackendSpec:
    if name not in BACKENDS:
        raise ValueError(f"unknown backend: {name}; choose {', '.join(BACKENDS)}")
    return BACKENDS[name]
