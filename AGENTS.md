# Agent Instructions — MegaRoute

This file contains rules for all agents trying to contribute to the MegaRoute project. Please follow the steps below to ensure proper setup and usage.

## 1. General Rules

1. Check `README.md` first.
2. Don't run any experiments without asking for permission. Instead, output the command for the user to run.
3. When modifying `README_en.md`, please modify `README_zh.md` as well.
4. When finishing a task:
   - Output a summary of the task in the chatting zone.
   - Delete unnecessary files generated during the task.
5. `MegaRoute` routing algorithm is reconstructed from the paper:
   `MegaRoute_Universal_Automated_Large-Scale_PCB_Routing_Algorithm.pdf`.
6. Don't modify external routing tools including `freerouting`, `KiCadRoutingTools` and `TraceMaker`.

---

## 2. Algorithm Fidelity

The implementation of `MegaRoute` is a research reimplementation of the MegaRoute paper. The following algorithmic mechanisms should be preserved unless the user explicitly requests an experimental modification.

### 2.1 Core mechanisms that must be faithfully reproduced

The following are considered core parts of MegaRoute:

- Adaptive step-size search.
- Node representation as `(x, y, z)`, where `z` denotes the PCB layer.
- The five exploration operations:
  1. Obstacle-aware exploration.
  2. Axis alignment.
  3. Diagonal alignment.
  4. Layer change.
  5. End connection.
- Shape-based obstacle detection.
- Geometric clearance checking.
- The distinction between obstacles based on net and layer.
- A*-like cost guidance.
- The paper-defined 135-degree constraint distance heuristic.
- DRC minimization through iterative routing optimization.
- The paper-defined DRC penalty schedule.
- The final objective of obtaining highly routable and DRC-compliant routing while considering wire length and via usage.

Do not replace these mechanisms with conventional grid-based routing, a generic A* implementation, or another routing algorithm while claiming that the result is a faithful MegaRoute implementation.

---

## 3. What May Be Implemented Differently

The following implementation details may differ from the original implementation when the paper does not specify them:

- Programming language details beyond the reported implementation language.
- C++ standard.

The default parameters can be modified as needed, including:

- `beta = 5`
- `d_min = 1 mil`
- `L = 200`
- `k = 0.4`
- `mu = 10`
- Maximum optimization iterations = `20`

Other parts that paper doesn't specify can be implemented with real-world engineering considerations.