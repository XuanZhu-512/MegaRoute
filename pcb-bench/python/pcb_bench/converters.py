"""Reserved bidirectional bridge. No synthetic KiCad output or lossy fallback."""
from pathlib import Path
from .contracts import (GeometryIRBundle, GeometryRoutingResult, KiCadCase,
                        RoutedKiCadCase, UnsupportedCapability)


class KiCadGeometryConverter:
    def preflight(self) -> None:
        raise UnsupportedCapability("kicad_geometry_bridge_not_implemented")

    def import_board(self, case: KiCadCase, workdir: Path) -> GeometryIRBundle:
        self.preflight()
        raise AssertionError("unreachable")

    def export_routes(self, bundle: GeometryIRBundle, routes: GeometryRoutingResult,
                      workdir: Path) -> RoutedKiCadCase:
        self.preflight()
        raise AssertionError("unreachable")
