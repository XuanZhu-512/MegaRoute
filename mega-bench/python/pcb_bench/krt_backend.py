"""Launch the pinned PCBWorld KRT checkout. This repo does not vendor KRT."""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from .netclass import resolve_net_classes


# Paper hyperparameters from PCBWorld methods/baselines/rule_based/run_rule_based_routers.py.
KRT_PAPER_ARGS = (
    "--grid-step", "0.1",
    "--max-iterations", "200000",
    "--max-probe-iterations", "5000",
    "--max-ripup", "3",
    "--heuristic-weight", "1.9",
    "--ordering", "mps",
    "--via-cost", "50",
    "--via-proximity-cost", "10",
    "--turn-cost", "1000",
    "--direction-preference-cost", "50",
    "--hole-to-hole-clearance", "0.2",
    "--board-edge-clearance", "0.0",
)

DEFAULT_KRT_ROOT = Path(__file__).resolve().parents[3] / "external/KiCadRoutingTools"
DEFAULT_KRT_RUNNER = Path(
    Path(__file__).resolve().parents[3] / "external/krt_runner/src")


def krt_arguments(board_in, board_out, geometry, rules) -> list[str]:
    net_settings = rules.get("net_settings") or {}
    classes = {item["name"]: item for item in net_settings.get("classes") or []}
    if "Default" not in classes:
        raise ValueError("project rules have no Default net class")
    default = classes["Default"]
    layers = [layer["name"] for layer in sorted(geometry["layers"], key=lambda item: item["index"])]
    if not layers:
        raise ValueError("board has no copper layers")
    resolved = resolve_net_classes(net_settings, [n["name"] for n in geometry.get("nets", []) if n.get("code")])
    for name in resolved.values():
        if name not in classes:
            raise ValueError(f"unknown net class: {name}")
    # The upstream CLI has one clearance, not per-net clearance arguments.
    # Use a conservative upper bound instead of silently dropping class rules.
    clearance = max([default["clearance"],
                     rules.get("board", {}).get("design_settings", {}).get("rules", {}).get("min_clearance", 0)]
                    + [classes[name]["clearance"] for name in resolved.values()]
                    + [item.get("local_clearance_mm") or 0 for item in geometry.get("pads", [])])
    args = [str(board_in), str(board_out), "--layers", *layers,
            "--track-width", str(default["track_width"]),
            "--clearance", str(clearance),
            "--via-size", str(default["via_diameter"]),
            "--via-drill", str(default["via_drill"]),
            *KRT_PAPER_ARGS]
    net_names = [net["name"] for net in geometry.get("nets", []) if net.get("code")]
    resolved = resolve_net_classes(net_settings, net_names)
    names = []
    widths = []
    for name, class_name in sorted(resolved.items()):
        if class_name == "Default":
            continue
        if class_name not in classes:
            raise ValueError(f"unknown net class for {name}: {class_name}")
        names.append(name)
        widths.append(str(classes[class_name]["track_width"]))
    if names:
        args += ["--power-nets", *names, "--power-nets-widths", *widths]
    return args


def run_krt(python, runner_src, krt_root, args, timeout):
    if not Path(krt_root, "route.py").is_file():
        raise FileNotFoundError(f"KRT route.py not found under {krt_root}")
    if not Path(runner_src, "krt_runner", "__init__.py").is_file():
        raise FileNotFoundError(f"krt_runner is not at {runner_src}")
    code = """
import json, os, sys
sys.path.insert(0, os.environ["KRT_RUNNER_SRC"])
from krt_runner import run_route
proc = run_route(json.loads(os.environ["KRT_ROUTE_ARGS"]), capture_output=True, text=True)
sys.stdout.write(json.dumps({"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}))
"""
    env = dict(os.environ)
    env.setdefault("KRT_RUST_SO_DIR", str(Path(__file__).resolve().parents[3] / "external/krt-runtime"))
    env["KRT_RUNNER_SRC"] = str(runner_src)
    env["KRT_ROOT"] = str(krt_root)
    env["KRT_ROUTE_ARGS"] = json.dumps(args)
    started = time.perf_counter()
    proc = subprocess.run([str(python), "-c", code], capture_output=True, text=True,
                          timeout=timeout, env=env, check=False)
    elapsed = time.perf_counter() - started
    if proc.returncode:
        raise RuntimeError(f"KRT launcher failed ({proc.returncode}): {proc.stderr.strip()}")
    payload = json.loads(proc.stdout)
    payload["wall_s"] = elapsed
    return payload


def restore_krt_board(source, destination):
    """Keep source objects intact and append new KRT copper with canonical layers."""
    from .tracemaker_backend import board_blocks
    original = board_blocks(source)
    routed = board_blocks(destination)
    layer_table = next(block for kind, block in original if kind == "layers")
    aliases = {}
    for canonical, alias in re.findall(r'\(\d+\s+"([^"]+)"\s+\w+(?:\s+"([^"]+)")?\s*\)', layer_table):
        aliases[canonical] = canonical
        if alias:
            if alias in aliases and aliases[alias] != canonical:
                raise ValueError(f"ambiguous KiCad layer alias: {alias}")
            aliases[alias] = canonical
    def identity(block):
        match = re.search(r'\((?:uuid|tstamp)\s+"?([^\s)"\n]+)', block)
        return match[1] if match else None
    old_ids = {identity(block) for _, block in original} - {None}
    added = []
    for kind, block in routed:
        if kind not in ("segment", "via", "arc") or identity(block) in old_ids:
            continue
        def canonical(match):
            names = re.findall(r'"([^"]+)"', match[2])
            if not names or any(name not in aliases for name in names):
                raise ValueError(f"unknown KRT copper layer: {match[0]}")
            return '(' + match[1] + ' ' + ' '.join(json.dumps(aliases[name]) for name in names) + ')'
        block = re.sub(r'\((layer|layers)\s+((?:"[^"\n]+"\s*)+)\)', canonical, block)
        added.append(block)
    text = Path(source).read_text(encoding="utf-8")
    closing = text.rfind(')')
    Path(destination).write_text(text[:closing] + '\n' + '\n'.join(added) + '\n' + text[closing:], encoding="utf-8")
    return {"source_objects_preserved": len(original), "added_copper": len(added)}
