"""Reviewable execution plan. A backend runs only when it has no remaining blockers."""
from dataclasses import asdict
from .backends import backend_spec
from .cases import fingerprints
from .contracts import KiCadCase
from .evaluation import KiCadToolchain


def make_plan(case: KiCadCase, backend: str, toolchain: KiCadToolchain) -> dict:
    spec = backend_spec(backend)
    return {
        "schema_version": "1.0", "case_id": case.case_id,
        "input_format": "kicad_pcb", "input_hashes": fingerprints(case),
        "copper_policy": case.copper_policy, "backend": asdict(spec),
        "pipeline": ["snapshot_kicad_project", *spec.stages,
                     "verify_preserved_objects_and_rules", "external_kicad_evaluation"],
        "output_format": "kicad_pcb",
        "evaluator": {"id": "external_kicad", "toolchain": asdict(toolchain)},
        "geometry_ir_role": "backend_private_not_benchmark_input",
        "internal_drc_role": "search_and_debug_only",
        "executable": not spec.blockers,
        "evaluation_blockers": [],
    }
