"""Source-tree entry point; equivalent to installed `pcb-bench` command."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from pcb_bench.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
