"""Launch the pinned FreeRouting 2.1.0 jar. This repo does not vendor the jar."""
import re
import json
import math
import shutil
import subprocess
import time
from pathlib import Path


DEFAULT_FREEROUTING_JAR = Path(
    Path(__file__).resolve().parents[3] / "external/freerouting/freerouting-2.1.0.jar")
FREEROUTING_JAVA = 21
DEFAULT_MAX_PASSES = 10


def parse_java_major(text: str) -> int:
    match = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not match:
        raise RuntimeError(f"cannot read the Java version: {text[:200]}")
    major = int(match.group(1))
    # Java 8 reports itself as "1.8".
    return int(match.group(2) or 0) if major == 1 else major


def require_java_major(text: str) -> int:
    major = parse_java_major(text)
    if major < FREEROUTING_JAVA:
        raise RuntimeError(
            f"FreeRouting needs Java {FREEROUTING_JAVA}, the java on PATH is Java {major}")
    return major


def require_freerouting(jar: Path) -> None:
    if not Path(jar).is_file():
        raise FileNotFoundError(f"FreeRouting jar not found: {jar}")
    java = shutil.which("java")
    if java is None:
        raise RuntimeError(f"no java on PATH — FreeRouting needs Java {FREEROUTING_JAVA}")
    proc = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=60, check=False)
    require_java_major((proc.stderr or "") + (proc.stdout or ""))


def freerouting_command(jar, dsn, ses, tmp_dir, passes) -> list[str]:
    if passes < 1:
        raise ValueError("max-passes must be at least 1")
    # In pinned 2.1.0, -mp sets maxPasses, but BatchAutorouter checks the
    # separate stop_pass_no field. Set both so incomplete boards can finish
    # and publish their SES instead of running until the process watchdog.
    return ["java", "-Djava.awt.headless=true", f"-Djava.io.tmpdir={tmp_dir}", "-Xmx4g",
            "-jar", str(jar), "-de", str(dsn), "-do", str(ses), "-mp", str(passes),
            f"--router.stop_pass_no={passes}"]


def run_freerouting(jar, dsn, ses, tmp_dir, passes, timeout, log_path) -> dict:
    require_freerouting(Path(jar))
    tmp = Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    command = freerouting_command(jar, dsn, ses, tmp, passes)
    started = time.perf_counter()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        log = (proc.stdout or "") + (proc.stderr or "") + f"\n[runner] freerouting exit code {proc.returncode}\n"
        returncode = proc.returncode
    except subprocess.TimeoutExpired as exc:
        log = f"TIMEOUT after {timeout}s\n"
        if exc.stdout:
            log += exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", errors="replace")
        if exc.stderr:
            log += exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(log, encoding="utf-8")
        raise RuntimeError(f"FreeRouting timed out after {timeout}s") from exc
    elapsed = time.perf_counter() - started
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).write_text(log, encoding="utf-8")
    return {"command": command, "returncode": returncode, "log": log, "wall_s": elapsed}


def protect_copper_graphics(dsn_path, geometry, rules):
    """Add fixed netless copper graphics omitted by KiCad's DSN exporter.

    Native contours and stroke capsules become layer keepouts, including windows.
    The source PCB is untouched. DSN Y is inverted relative to KiCad board XY.
    """
    text = Path(dsn_path).read_text(encoding="utf-8")
    unit = re.search(r'\(unit\s+(um|mm)\)', text)
    if not unit:
        raise ValueError("unsupported DSN unit for copper keepouts")
    scale = 1000 if unit[1] == 'um' else 1
    layers = {layer["index"]: layer["name"] for layer in geometry["layers"]}
    classes = rules.get("net_settings", {}).get("classes", [])
    clearance = max([rules.get("board", {}).get("design_settings", {}).get("rules", {}).get("min_clearance", 0)]
                    + [c["clearance"] for c in classes])
    def polygon(ring, layer):
        if len(ring) < 3:
            raise ValueError("degenerate DSN copper keepout")
        coords = ' '.join(f'{x*scale:.9f} {-y*scale:.9f}' for x, y in ring)
        return f'(polygon {json.dumps(layer)} 0 {coords})'
    def capsule(primitive):
        radius = primitive['width'] / 2 / math.cos(math.pi / 16)
        points = sorted(set((x + radius*math.cos(i*math.pi/8), y + radius*math.sin(i*math.pi/8))
                            for x, y in [primitive['a'], primitive['b']] for i in range(16)))
        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
        def half(points):
            hull = []
            for point in points:
                while len(hull) > 1 and cross(hull[-2], hull[-1], point) <= 0:
                    hull.pop()
                hull.append(point)
            return hull[:-1]
        return half(points) + half(list(reversed(points)))
    keepouts = []
    for graphic in geometry.get('copper_graphics', []):
        for part in graphic['copper']:
            layer = layers[part['layer']]
            polygons = list(part.get('polygons', []))
            for primitive in part.get('primitives', []):
                if primitive['kind'] == 'segment':
                    polygons.append({'outer': capsule(primitive)})
                elif primitive['kind'] == 'polygon':
                    polygons.append({'outer': primitive['points'], 'holes': primitive.get('holes', [])})
                else:
                    raise ValueError("unsupported DSN copper primitive")
            for poly in polygons:
                windows = ''.join('(window ' + polygon(hole, layer) + ')' for hole in poly.get('holes', []))
                keepouts.append(f'(keepout mr_fixed_graphic_{len(keepouts)} '
                                + polygon(poly['outer'], layer) + windows
                                + ' (clearance_class mrgraphics))')
    if not keepouts:
        return 0
    start = re.search(r'\(structure\s', text)
    if not start:
        raise ValueError("DSN has no structure")
    depth = 0
    end = None
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|[()]', text[start.start():]):
        if token[0] == '(':
            depth += 1
        elif token[0] == ')':
            depth -= 1
            if depth == 0:
                end = start.start() + token.start()
                break
    if end is None:
        raise ValueError("unbalanced DSN structure")
    # Pinned 2.1.0 reads clearance_class on an area, but skips nested rule
    # scopes there. Define the pair rules at structure level instead.
    pairs = ('wire', 'via', 'smd', 'pin', 'area', 'mrgraphics')
    pair_rules = '(rule ' + ' '.join(
        f'(clearance {clearance*scale:.9f} (type mrgraphics_{other}))' for other in pairs) + ')'
    keepouts.insert(0, pair_rules)
    Path(dsn_path).write_text(text[:end] + '\n' + '\n'.join(keepouts) + '\n' + text[end:], encoding="utf-8")
    return len(keepouts) - 1
