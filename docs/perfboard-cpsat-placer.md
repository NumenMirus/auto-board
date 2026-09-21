# Perfboard CP-SAT Placer

The perfboard placer is responsible for choosing **where** every movable
component goes on a perfboard. The legacy placer in
`backend/app/domain/traces/place.py` is a single-pass greedy + hill-climbing
loop that accepts only strict improvements against a weighted heuristic, so
it can never undo a bad first placement. Real flagship fixtures show the
symptom: legal but visibly broken layouts — components scattered, functional
groups split, the router forced to compensate.

This document describes the new global placer in
`backend/app/domain/traces/place_cpsat.py`, which replaces the greedy path
behind a flag and is opt-in via `SolverOptions.placement_engine == "cpsat"`.

---

## Activation

```python
from app.domain.models import SolverOptions

opts = SolverOptions(
    placement_engine="cpsat",
    preset="balanced",
    solver_seed=7,
)
```

- The default `placement_engine` is `"greedy"` — existing project documents
  keep loading and the legacy placer keeps running until benchmarks prove
  the flip.
- Existing `placement_weights` and `routing_weights` are ignored by the
  CP-SAT path; the new objective is described below.
- The CP-SAT engine is orthogonal to `SolverOptions.preset`. The preset
  maps to wall-time / candidate-cap / candidate-count budgets (see
  [Presets](#presets)) unless individual limits are overridden.

---

## Model

```
for each movable component c:
    sum(select[c][p] for p in candidates[c]) == 1

for each board hole h touched by at least one candidate:
    sum(select[c][p] for (c, p) in hole_to_candidates[h]) <= 1
```

Two constraints, no more:

- **Exactly one pose per component** — `select[c][p]` is a Boolean variable
  for every candidate pose `p` of component `c`; the sum is forced to 1.
- **Exact hole occupancy** — for every board hole `h`, the sum of the
  candidates that touch `h` is ≤ 1. This is the brief's "use canonical
  hole IDs, not bounding boxes" constraint.

Locked placements emit no variables; their occupied holes are filtered out
of every movable candidate list at pre-filter time, and the locked placements
themselves are emitted verbatim into the result.

### Objective

All terms are integer (millimetre × 100). Weights and term definitions:

| Term                | Weight | Source                                                       |
|---------------------|-------:|--------------------------------------------------------------|
| `net_length`        |      4 | Per-net Manhattan distance, hub-based; bounded pair count    |
| `cluster_spread`    |      3 | Manhattan distance from each cluster member to its anchor    |
| `decoupler`         |     24 | 8× cluster for bypass caps joined by power/ground to a DIP   |
| `compactness`       |      1 | Centroid distance from locked anchor (or board centre)        |
| `edge`              |     10 | Connector/header on an edge pose; +5 if mating side outwards |
| `orientation`       |      1 | DIP notch convention (orientation == 0)                       |
| `congestion`        |      2 | 3×3 hole-bin overlap (bin "hot" once ≥ 3 components touch it)|
| `mechanical`        |      1 | `pose.mech_cost` (span deviation + vertical penalty)         |

Net length is hub-based: a deterministic hub pin (lexicographic first
pin) plus one Boolean-linearized term per `(hub pose, other pose)` pair.
Multi-pin nets (>6 pins) fall back to a hub-only approximation so the
linear-product count stays bounded.

The breakdown is computed twice — once during `Minimize(...)` and again
deterministically from the chosen assignment — so the diagnostic matches
the actual cost the solver minimized. Both end up in the solver trace
under `cpsat_term_*` keys.

---

## Presets

| Preset     | `placement_time_limit_ms` | `placement_candidate_limit` | `placement_solution_count` |
|------------|--------------------------:|----------------------------:|---------------------------:|
| `fast`     | 1500                      | 50                          | 3                          |
| `balanced` | 3000                      | 100                         | 5                          |
| `quality`  | 10000                     | 150                         | 8                          |

Per-call `placement_time_limit_ms`, `placement_candidate_limit`, and
`placement_solution_count` always win over the preset (detected by
comparison with the `SolverOptions.model_fields[...].default`).

Wall time is split: 60% to solving, 40% to routing the produced
candidates. Each diversified solve gets an equal share of the solving
budget.

---

## Candidate pre-filtering

Pose enumeration reuses `app.domain.traces.place.generate_poses(...)` plus
its `_POSE_CACHE`; no new geometry logic. Pre-filter rules:

1. Drop any candidate whose occupied holes collide with locked placements.
2. For footprints whose candidate set fits in `placement_candidate_limit`,
   keep them all.
3. Otherwise cap to the top `placement_candidate_limit` poses by a cheap
   deterministic score, preserving at least 4 poses per orientation
   (0/90/180/270).
4. Connectors and headers (`CONN-*`, `HEADER-1x*`) get an edge-bias in
   the cheap score so the cap doesn't strip every edge pose.
5. Footprints with `min-clearance-holes` rules (today only `CONN-*`) are
   treated like connectors for candidate preservation.

Hard-rule-feasibility is never dropped — a pose is removed only because it
collides with a locked placement, never because the heuristic dislikes it.

---

## Diversified candidate generation

For each of `placement_solution_count` rounds:

1. Solve the model with `max_time_in_seconds = per_solve_budget`.
2. Extract the chosen literal per component.
3. Add a no-good constraint: `sum(1 - select[c][prev_pose[c]]) >= 1`,
   i.e. at least one component must pick a different pose.
4. Repeat.

The `_CandidateOutcome` ranking uses the brief's priority list:

1. Placement validity (zero errors from `validate_layout`).
2. Zero unrouted nets from `trace_route.route`.
3. Lowest `trace_cost` (sum of `Trace.estimated_length_mm`).
4. Fewest vias.
5. Fewest traces.
6. Lowest `PlacementObjectiveBreakdown.total` as final tiebreaker.

The best fully-routed candidate wins. If none route fully, the best
placement-valid candidate is returned with diagnostics describing every
unrouted status. The worker never crashes on infeasibility.

---

## Cancellation + worker safety

- Cancellation is checked before model build, before each diversified
  solve, and before each candidate evaluation. The router already honours
  `cancel()` via `DomainError("cancelled by solver")`; we propagate it as
  `SolverCancelled`.
- Per-solve wall-time is bounded by `placement_time_limit_ms / solution_count - 200ms`.
- Routing budget is at least 200ms total for all candidates.
- The solver runs with `num_search_workers=1` and the user-supplied
  `solver_seed` so output is deterministic across runs.

---

## Fallback behaviour

`placement_engine="greedy"` is preserved for one release minimum. The
legacy placer is `app.domain.traces.place.place_greedy` (also reachable
as the historic name `place`). The dispatcher in
`app.domain.traces.solve.solve(...)` and `place_only(...)` switches by
`options.placement_engine` value.

If the CP-SAT path produces no usable candidate, the pipeline falls back
to the greedy placer's same-named entry point with the same options (so
the trace/route/validate tail sees a uniform `PlacementResult` shape).
The fallback is recorded as a `TraceRejection(reason="no_cpsat_solution")`
in the trace.

---

## Tuning guide

1. **Most regressions show up as the CP-SAT path producing wider
   placements than greedy.** Raise `placement_candidate_limit` first.
2. **CP-SAT times out without finding a feasible assignment.** Raise
   `placement_time_limit_ms` next.
3. **CP-SAT finds a feasible assignment but routes worse than greedy.**
   That's a routing-quality regression — file a benchmark CSV diff. The
   soft objective terms and their weights are the place to investigate,
   but in practice the routing is dominated by the maze router and
   pin-density terms.
4. **Two solutions look identical.** The no-good constraint is too
   narrow; raise `placement_solution_count` and rerun.

---

## Known limitations

- Joint placement-and-routing (a single CP-SAT model that also decides
  trace paths) is **out of scope**.
- Analog / RF / thermal / current / EMI-aware placement is **out of
  scope**. The routing proxy is purely topological.
- Pin density is not modelled beyond the 3×3 bin congestion term.
- Per-pose mechanical cost uses `mech_cost` from the greedy placer; no
  new mechanical heuristic is introduced.

---

## Benchmark results

Run on demand with `make benchmark`. Latest committed CSV is
`backend/scripts/benchmark-results.csv`. Median summary on the bundled
fixtures (20×30 double-sided perfboard, default 1500 ms / 3000 ms /
10000 ms preset budgets):

| Fixture          | Engine | Preset    | Trace length (mm) | Vias | Placed | Unrouted |
|------------------|--------|-----------|------------------:|-----:|-------:|---------:|
| dip14-flagship   | greedy | balanced  | 93.40             | 0    | 5      | 0        |
| dip14-flagship   | cpsat  | balanced  | 73.00             | 0    | 5      | 0        |

Reproduce locally:

```bash
make benchmark
```

---

## Test coverage

- `backend/tests/domain/test_traces_place_cpsat.py` — 9 unit tests
  covering feasibility, locked handling, Boolean linearization, edge
  preference, decoupler proximity, no-good diversity, timeout fallback,
  and infeasibility.
- `backend/tests/domain/test_traces_place_quality.py` — 11 quality
  regression tests parametrized over seeds `[1, 7]`, comparing CP-SAT to
  greedy on routed trace length, unrouted net count, board span,
  decoupler proximity, and connector edge placement.
- `backend/tests/test_architecture.py` — `test_place_cpsat_has_no_io_imports`
  pins the module's purity.