"""Launch the pinned FreeRouting 2.1.0 jar. This repo does not vendor the jar."""
import re
import shutil
import subprocess
import time
from pathlib import Path


DEFAULT_FREEROUTING_JAR = Path(
    "/home/xuanzhu/projects/PCBWorld/external/freerouting/freerouting-2.1.0.jar")
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
    return ["java", "-Djava.awt.headless=true", f"-Djava.io.tmpdir={tmp_dir}", "-Xmx4g",
            "-jar", str(jar), "-de", str(dsn), "-do", str(ses), "-mp", str(passes)]


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
