"""Launch the pinned PCBWorld KRT checkout. This repo does not vendor KRT."""
import json
import os
import subprocess
import time
from pathlib import Path


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

DEFAULT_KRT_ROOT = Path("/home/xuanzhu/projects/PCBWorld/external/KiCadRoutingTools")
DEFAULT_KRT_RUNNER = Path(
    "/home/xuanzhu/projects/PCBWorld/methods/baselines/rule_based/krt/src")


def krt_arguments(board_in, board_out, geometry, rules) -> list[str]:
    patterns = rules.get("net_settings", {}).get("netclass_patterns") or []
    if patterns:
        raise ValueError("unsupported_feature: netclass_patterns")
    classes = {item["name"]: item for item in rules["net_settings"]["classes"]}
    if "Default" not in classes:
        raise ValueError("project rules have no Default net class")
    default = classes["Default"]
    layers = [layer["name"] for layer in sorted(geometry["layers"], key=lambda item: item["index"])]
    if not layers:
        raise ValueError("board has no copper layers")
    args = [str(board_in), str(board_out), "--layers", *layers,
            "--track-width", str(default["track_width"]),
            "--clearance", str(default["clearance"]),
            "--via-size", str(default["via_diameter"]),
            "--via-drill", str(default["via_drill"]),
            *KRT_PAPER_ARGS]
    assignments = rules.get("net_settings", {}).get("netclass_assignments") or {}
    names = []
    widths = []
    for name, class_name in sorted(assignments.items()):
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
