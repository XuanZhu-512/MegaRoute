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
| D3-C | 10 | PCBWorld `hard.test` |
| Tier-D | 22 | A harder PCBench split |

**Routers**

- **MegaRoute** — in-tree C++ research reimplementation (adaptive steps, shape checks, iterative DRC minimization).
- **FreeRouting** 2.1.0 — external Java router via Specctra DSN/SES.
- **KRT** — [KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools).
- **TraceMaker** 0.12.1 — external CPU router. D3-A, D3-B, and D3-C are complete. All 22 Tier-D boards are in Section 5; two produced no routed board and are counted as failures.

**Supporting tools**

- KiCad 9.0.8 `kicad-cli` and `pcbnew`: geometry export, route write-back, DRC, connectivity, wire length, and via counts. Runtime copy: `external/kicad-9.0.8/`.
- Java 21+ for FreeRouting (`external/freerouting/`).
- NumPy, SciPy, and Shapely for KRT (`external/KiCadRoutingTools/`).

## 2. MegaRoute

MegaRoute preserves the adaptive step-size search, five exploration operations, shape-based obstacles, cost guidance, and iterative DRC minimization described in Section IV of the paper.

- Near-obstacle steps are `w`; distant steps are `beta*w`, with `beta=5`. The node density threshold stays at `d_min=1 mil`.
- Candidates include eight planar directions, axis alignment, 45-degree alignment, layer changes, and direct end connections.
- The heuristic uses the paper's octile distance. Costs include length, DRC, and vias, without an additional history congestion term.
- Logistic defaults are `L=200,k=0.4,mu=10`, with at most 20 iterations. Stagnation refinement and extra strict repair searches have been removed.
- Valid nominal pad centers are preferred. Otherwise, one fixed legal copper access point per layer is selected before point-to-point search.
- Copper holes, copper text, board boundaries, and clearance adaptation remain supported. Only legal copper is exported; length and via counts cover additions.

See [paper fidelity, implementation boundaries, tests, and retest commands](mega-bench/docs/PAPER_FIDELITY.md).

## 3. Layout

```text
MegaRoute/
├── README_en.md
├── README_zh.md
├── dataset/
│   ├── D3-A/                 # 99 cases: case.json + .kicad_pcb + .kicad_pro
│   ├── D3-B/                 # 10 cases
│   ├── D3-C/                 # 10 cases
│   └── Tier-D/               # 22 cases
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

MegaRoute parameters can be set directly on `bench.py run`, after the required arguments in the one-board example above. D3-A/B/C batch scripts also accept these options after `megaroute` or `all`; with `all`, extra options apply only to MegaRoute. Existing nonempty result directories are skipped; `RESULTS_ROOT` selects a separate output root (default: `results/`).

```bash
# D3-C: write a separate set of results
RESULTS_ROOT="$PWD/results/tuning-beta2" bash dataset/D3-C/run_batch.sh megaroute \
  --megaroute-beta 2 \
  --megaroute-penalty-l 1000 \
  --megaroute-max-iterations 100 \
  --megaroute-time-limit-s 3600 \
  --routing-seconds 3630
```

CLI values override `--config`, which defaults to `mega-bench/configs/megaroute.json`. Omitted options keep the configured values; source config files are never rewritten. The effective values are saved in `work/effective_config.json` and the run manifest's router identity. The internal time limit is still capped by `--routing-seconds` minus a saving margin of up to 10 seconds, so increase both limits for longer runs.

| CLI option | JSON key | Allowed values |
| --- | --- | --- |
| `--megaroute-beta` | `beta` | ≥ 1 |
| `--megaroute-d-min-mm` | `d_min_mm` | ≥ 0, mm |
| `--megaroute-lambda-v` | `lambda_v` | ≥ 0 |
| `--megaroute-time-limit-s` | `time_limit_s` | > 0, seconds |
| `--megaroute-max-iterations` | `max_iterations` | integer 1–100 |
| `--megaroute-max-expanded-nodes` | `max_expanded_nodes` | integer 1–10000000 |
| `--megaroute-max-records` | `max_records` | integer 1–10000000 |
| `--megaroute-penalty-l` | `penalty_L` | > 0 |
| `--megaroute-penalty-k` | `penalty_k` | > 0 |
| `--megaroute-penalty-mu` | `penalty_mu` | > 0 |
| `--megaroute-routing-order` | `routing_order` | `fixed`, `rotate_conflicts` |

For longer Tier-D MegaRoute reruns, use `--config mega-bench/configs/megaroute-tier-d.json --routing-seconds 1210`: the internal routing limit is 1200 seconds (20 minutes), with at most 100 iterations and an extra 10 seconds in the outer watchdog for final checks and serialization. Other search parameters match the default configuration; the DRC penalty formula and parameters are unchanged. Increasing these budgets does not bypass `input_drc_violations` or increase the per-search node/record limits. The default `megaroute.json` is unchanged.

Build the MegaRoute binary (the D3 batch scripts do this when the backend is `megaroute` or `all`):

```bash
cmake -S mega-bench -B mega-bench/build/dev -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build mega-bench/build/dev -j 2
```

## 5. Comparison

Averages are the unweighted mean of each board’s `evaluation/metrics.json`. Boards without a finished evaluation are left out and are not treated as zero. `n` is boards included in the row / boards in the split. All four routers have a finished evaluation on every current D3-A, D3-B, and D3-C board. Tier-D cells stay empty until that router has a finished evaluation. Eight Tier-D MegaRoute boards stopped on input DRC before routing and are left out of that row. Two Tier-D TraceMaker runs produced no routed board and are counted as failures: routability, added copper, vias, and DRC are 0, and the time is the recorded process time.

Success means every net is one pad group and the original pads are still present. Routability is routed connections divided by required connections, then averaged across boards. Clean pass means success and zero KiCad DRC errors; warnings are allowed. Wire length and via count include only added copper. A shorter wire length with a lower routability is not a better route.

### D3-A (99 boards)

| Algorithm | n | Success | Routability | Clean pass | WL (mm) | Vias | DRC errors | Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 99/99 | 0.9899 | 0.9990 | 0.9899 | 142.41 | 3.22 | 0.00 | 0.20 |
| FreeRouting | 99/99 | 0.8788 | 0.9759 | 0.8485 | 152.23 | 0.94 | 0.06 | 8.71 |
| KRT | 99/99 | 0.7980 | 0.9192 | 0.6768 | 141.55 | 3.84 | 0.58 | 1.10 |
| TraceMaker | 99/99 | 0.9899 | 0.9949 | 0.9899 | 144.53 | 1.89 | 0.00 | 0.59 |

### D3-B (10 boards)

| Algorithm | n | Success | Routability | Clean pass | WL (mm) | Vias | DRC errors | Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 10/10 | 1.0000 | 1.0000 | 1.0000 | 495.08 | 17.30 | 0.00 | 1.31 |
| FreeRouting | 10/10 | 0.8000 | 0.9895 | 0.8000 | 531.64 | 3.50 | 0.00 | 15.17 |
| KRT | 10/10 | 0.4000 | 0.7490 | 0.1000 | 398.78 | 10.00 | 2.20 | 2.71 |
| TraceMaker | 10/10 | 1.0000 | 1.0000 | 1.0000 | 503.43 | 11.10 | 0.00 | 8.75 |

### D3-C (10 boards)

| Algorithm | n | Success | Routability | Clean pass | WL (mm) | Vias | DRC errors | Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 10/10 | 0.8000 | 0.9776 | 0.8000 | 1214.91 | 71.20 | 0.00 | 142.03 |
| FreeRouting | 10/10 | 0.2000 | 0.8789 | 0.2000 | 1243.01 | 21.20 | 0.00 | 18.11 |
| KRT | 10/10 | 0.0000 | 0.5419 | 0.0000 | 753.88 | 38.20 | 1.50 | 4.64 |
| TraceMaker | 10/10 | 0.9000 | 0.9940 | 0.9000 | 1268.48 | 55.40 | 0.00 | 249.82 |

### Tier-D (22 boards)

| Algorithm | n | Success | Routability | Clean pass | WL (mm) | Vias | DRC errors | Time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MegaRoute | 14/22 | 0.3571 | 0.9341 | 0.0000 | 7139.26 | 247.71 | 524.14 | 706.27 |
| FreeRouting | 12/22 | 0.0833 | 0.9473 | 0.0000 | 6149.66 | 90.42 | 338.08 | 209.30 |
| KRT |  |  |  |  |  |  |  |  |
| TraceMaker | 22/22 | 0.3636 | 0.8870 | 0.0455 | 6546.58 | 205.27 | 1477.68 | 379.51 |

## 6. References

1. Haiyun Li and Jixin Zhang. *MegaRoute: Universal Automated Large-Scale PCB Routing Method with Adaptive Step-Size Search*. Design, Automation & Test in Europe (DATE), 2025. [doi:10.23919/DATE64628.2025.10993225](https://doi.org/10.23919/DATE64628.2025.10993225).
2. KiCad. <https://www.kicad.org/>.
3. FreeRouting. <https://github.com/freerouting/freerouting>.
4. Andrew Haas. KiCadRoutingTools. <https://github.com/drandyhaas/KiCadRoutingTools>.
5. TraceMaker. <https://github.com/DingoOz/TraceMaker>.
