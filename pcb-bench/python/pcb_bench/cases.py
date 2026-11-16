"""Immutable KiCad input bundles. No PCB parsing or implicit rule defaults."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from .contracts import KiCadCase


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_case(manifest: Path) -> KiCadCase:
    manifest = manifest.resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    required = {"schema_version", "case_id", "board", "project", "copper_policy"}
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - {"custom_rules"}:
        raise ValueError("invalid case fields")
    if data["schema_version"] != "1.0":
        raise ValueError("unsupported case schema")
    if not isinstance(data["case_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", data["case_id"]):
        raise ValueError("invalid case_id")
    if data["copper_policy"] != "preserve_input":
        raise ValueError("unsupported copper policy; preprocess identical inputs offline")

    def resolve(key, suffix):
        value = data[key]
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid {key} path")
        path = (manifest.parent / value).resolve()
        if path.suffix != suffix or not path.is_file():
            raise ValueError(f"missing or invalid {key}: {path}")
        return path

    board = resolve("board", ".kicad_pcb")
    project = resolve("project", ".kicad_pro")
    # Renaming a project can affect text variables and references; preserve its basename.
    if project != board.with_suffix(".kicad_pro"):
        raise ValueError("board and project must be co-located with the same basename")
    rules = resolve("custom_rules", ".kicad_dru") if "custom_rules" in data else None
    sibling = board.with_suffix(".kicad_dru")
    if rules is not None and rules != sibling:
        raise ValueError("custom rules must be the board's same-basename sibling")
    if sibling.exists() and rules is None:
        raise ValueError("existing .kicad_dru must be declared; refusing to omit rules")
    return KiCadCase(data["case_id"], board, project, rules, data["copper_policy"])


def fingerprints(case: KiCadCase) -> dict[str, str]:
    paths = {"board": case.board, "project": case.project}
    if case.custom_rules:
        paths["custom_rules"] = case.custom_rules
    return {key: sha256(path) for key, path in paths.items()}


def snapshot(case: KiCadCase, destination: Path) -> KiCadCase:
    """Copy source assets byte-for-byte; never strip tracks or rewrite rules here."""
    destination = destination.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("snapshot directory must be empty")
    before = fingerprints(case)
    destination.mkdir(parents=True, exist_ok=True)
    for source in (case.board, case.project, case.custom_rules):
        if source:
            shutil.copy2(source, destination / source.name)
    copied = KiCadCase(case.case_id, destination / case.board.name,
                       destination / case.project.name,
                       destination / case.custom_rules.name if case.custom_rules else None,
                       case.copper_policy)
    if fingerprints(case) != before or fingerprints(copied) != before:
        raise RuntimeError("input changed while making snapshot")
    (destination / "input_hashes.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
    return copied
