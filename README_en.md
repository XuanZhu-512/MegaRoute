# MegaRoute

<p>
  <a href="./README_en.md"><img alt="English" src="https://img.shields.io/badge/English-1f6feb?style=for-the-badge"></a>
  <a href="./README_zh.md"><img alt="中文" src="https://img.shields.io/badge/中文-555?style=for-the-badge"></a>
</p>

PCB routing benchmark and a reimplementation of MegaRoute. Every router reads the same KiCad board, writes a routed `.kicad_pcb`, and is scored by one pinned KiCad evaluator.

## 1. Introduction

This repository compares automatic PCB routers on unrouted KiCad boards. A case is a `.kicad_pcb` plus the matching `.kicad_pro` (and `.kicad_dru` when the case declares one). Original copper stays fixed. Metrics come from KiCad 9.0.8, not from a router’s own summary.

**Datasets**

| Split | Boards | Role |
| --- | ---: | --- |
| D3-A | 99 | PCBWorld `easy.test` |
| D3-B | 10 | PCBWorld `medium.test` |
| D3-C | 1 | Repaired EasyEDA import, used to check the pipeline |

**Routers**

- **MegaRoute** — in-tree C++ router (adaptive step size, negotiation, strict repair).
- **FreeRouting** 2.1.0 — external Java router via Specctra DSN/SES.
- **KRT** — [KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools).
- **TraceMaker** 0.12.1 — external CPU router. It is wired in; the D3-A / D3-B averages below were taken before it was run on those splits.

**Supporting tools**

- KiCad 9.0.8 `kicad-cli` and `pcbnew`: geometry export, route write-back, DRC, connectivity, wire length, and via counts. Runtime copy: `external/kicad-9.0.8/`.
- Java 21+ for FreeRouting (`external/freerouting/`).
- NumPy, SciPy, and Shapely for KRT (`external/KiCadRoutingTools/`).

## 2. MegaRoute

MegaRoute searches each two-terminal connection in `(x, y, layer)` and keeps only candidates that pass a shape-based clearance check.

- Step length is two-level: `delta = w` when the nearest obstacle is within `beta * w`, otherwise `delta = beta * w` (`beta = 5`).
- From the current node it tries eight planar steps, axis alignment, 45° alignment, a via to another copper layer, and a direct end connection.
- Cost is routed length, an octile distance heuristic, via cost, and a logistic penalty on spacing violations. The penalty rises over at most 20 passes.
- Conflict bundles are ripped up and rerouted. History congestion and finer sampling are used when progress stalls. A final pass rejects remaining violations.
- Fixed pads, board outline, and keepouts are hard constraints. Reported wire length and via count include only copper added by the run.

## 3. Layout

```text
MegaRoute/
├── README_en.md
├── README_zh.md
├── dataset/
│   ├── D3-A/                 # 99 cases: case.json + .kicad_pcb + .kicad_pro
│   ├── D3-B/                 # 10 cases
│   └── D3-C/                 # one repaired board
├── mega-bench/
│   ├── apps/main.cpp         # megaroute_cli: validate / route / check
│   ├── include/megaroute/
│   ├── src/                  # model, geometry, spatial index, DRC, router
│   ├── python/pcb_bench/     # case I/O, four backends, KiCad evaluation
│   ├── tools/                # bench.py, aggregation, visualization
│   ├── configs/              # megaroute.json, KiCad and TraceMaker locks
│   ├── schemas/
│   ├── tests/
│   ├── adapters/easyeda/     # contract only; import is unsupported
│   └── third_party/nlohmann/
├── external/                 # KiCad, FreeRouting, KRT, TraceMaker (not in git)
└── results/                  # routed boards, reports, evaluation/metrics.json
```

`mega-bench/build/` and `results/` are generated. `external/` is a local toolchain and is gitignored.

## 4. CLI

From the repository root. `BACKEND` is `megaroute`, `freerouting`, `krt`, `tracemaker`, or `all`. A nonempty result directory is skipped.

```bash
bash dataset/D3-A/run_batch.sh megaroute
bash dataset/D3-B/run_batch.sh freerouting
bash dataset/D3-A/run_batch.sh all
```

One board:

```bash
python mega-bench/tools/bench.py run \
  --case dataset/D3-B/d3b_0113_maytal_Maytal/case.json \
  --backend megaroute \
  --out results/D3-B/d3b_0113_maytal_Maytal/megaroute \
  --toolchain mega-bench/configs/kicad-toolchain.json \
  --kicad-python "${KICAD_PYTHON:-python3}" \
  --expected-version 9.0.8 \
  --routing-seconds 600 \
  --evaluation-seconds 120
```

The output directory must be empty. Scores are in `evaluation/metrics.json`. `KICAD_PYTHON` must be able to import the pinned `pcbnew` 9.0.8. KRT also needs NumPy, SciPy, and Shapely; FreeRouting needs `java` on `PATH`.

Build the MegaRoute binary (the D3 batch scripts do this when the backend is `megaroute` or `all`):

```bash
cmake -S mega-bench -B mega-bench/build/dev -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build mega-bench/build/dev -j 2
```

## 5. Comparison

Averages are the unweighted mean of per-board KiCad metrics in `results/D3-A/eval.json` and `results/D3-B/eval.json` (2026-11-16). Boards without a finished evaluation are left out and are not treated as zero. `n` is finished evaluations / boards in the split.

Success means every net is one pad group and the original pads are still present. Routability is routed connections divided by required connections, then averaged across boards. Clean pass means success and zero KiCad DRC errors; warnings are allowed. Wire length and via count include only added copper. A shorter wire length with a lower routability is not a better route.

### D3-A (99 boards)

| Algorithm | n | Success | Routability | Clean pass | WL (mm) | Vias | DRC errors | Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 97/99 | 0.9381 | 0.9381 | 0.9175 | 139.15 | 3.66 | 0.04 | 0.71 |
| FreeRouting | 98/99 | 0.8776 | 0.9756 | 0.8469 | 152.61 | 0.95 | 0.06 | 8.76 |
| KRT | 89/99 | 0.8315 | 0.9343 | 0.7079 | 146.56 | 3.91 | 0.62 | 1.10 |

### D3-B (10 boards)

| Algorithm | n | Success | Routability | Clean pass | WL (mm) | Vias | DRC errors | Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 10/10 | 1.0000 | 1.0000 | 1.0000 | 497.04 | 20.10 | 0.00 | 5.41 |
| FreeRouting | 10/10 | 0.8000 | 0.9895 | 0.8000 | 531.64 | 3.50 | 0.00 | 15.17 |
| KRT | 10/10 | 0.4000 | 0.7490 | 0.1000 | 398.78 | 10.00 | 2.20 | 2.71 |

## 6. References

1. Haiyun Li and Jixin Zhang. *MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search*. Design, Automation & Test in Europe (DATE), 2025. [doi:10.23919/DATE64628.2025.10993225](https://doi.org/10.23919/DATE64628.2025.10993225).
2. KiCad. <https://www.kicad.org/>.
3. FreeRouting. <https://github.com/freerouting/freerouting>.
4. Andrew Haas. KiCadRoutingTools. <https://github.com/drandyhaas/KiCadRoutingTools>.
5. TraceMaker. <https://github.com/DingoOz/TraceMaker>.
