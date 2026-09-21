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
    # placement_engine="cpsat" is the default. Pass "greedy" explicitly
    # to opt out (legacy single-pass placer).
    preset="balanced",
    solver_seed=7,
)
```

- The default `placement_engine` is `"cpsat"`. Set it to `"greedy"` to
  use the legacy single-pass placer from `app.domain.traces.place`.
- The dispatcher in `app.domain.traces.solve.solve(...)` and `place_only(...)`
  routes between the two engines. CP-SAT falls back to greedy when it
  cannot find a feasible placement in the budget, so the user is never
  given a worse result than greedy alone — see
  [Fallback behaviour](#fallback-behaviour) below.
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
| `cluster_spread`    |      3 | Centroid-to-centroid distance from each cluster member to anchor |
| `pin_proximity`     |      8 | Pin-to-pin Manhattan distance between the closest pair per net |
| `decoupler`         |     24 | 8× cluster for bypass caps joined by power/ground to a DIP   |
| `compactness`       |      1 | Centroid distance from locked anchor (or board centre)       |
| `bbox_span`         |     12 | Origin-neutral `(x_span + y_span)` over the placed region    |
| `bbox_area`         |      1 | Looser area tie-breaker; (x_span+1) × (y_span+1)             |
| `anti_line`         |     60 | Soft penalty when `min(x_span, y_span)` collapses below threshold |
| `row_wall`          |     30 | Quadratic penalty when many components share a single row   |
| `dip_escape`        |      4 | Each non-DIP cell inside the 1-hole corridor around a DIP pin |
| `edge`              |     10 | Connector/header on an edge pose; +5 if mating side outwards |
| `orientation`       |      1 | DIP notch convention (orientation == 0)                       |
| `congestion`        |      2 | 3×3 hole-bin overlap (bin "hot" once ≥ 3 components touch it)|
| `mechanical`        |      1 | `pose.mech_cost` (span deviation + vertical penalty)         |

The CP-SAT model carries the `net_length`, `cluster_spread`, pin-level
cluster proximity (centroid + nearest pin), `compactness`, `edge`,
`orientation`, `congestion`, and `mechanical` terms. The
`bbox_span`, `bbox_area`, `anti_line`, `row_wall`, and `dip_escape`
terms are *post-solve deterministic* costs — modelling `min(x_span, y_span)`
or row distribution cleanly requires cross-candidate pair products that
explode the model. They participate in the candidate ranker so that
between two candidates that both route successfully, the one with the
better physical layout wins.

Net length is hub-based: a deterministic hub pin (lexicographic first
pin) plus one Boolean-linearized term per `(hub pose, other pose)` pair.
Multi-pin nets (>6 pins) fall back to a hub-only approximation so the
linear-product count stays bounded.

The breakdown is computed twice — once during `Minimize(...)` and again
deterministically from the chosen assignment — so the diagnostic matches
the actual cost the solver minimized. Both end up in the solver trace
under `cpsat_term_*` keys.

### Candidate ranking

The route-first selection ranks every routed candidate with the
lexicographic key:

1. `validation_error_count` (lower wins; must be 0 for "fully routed")
2. `single_pin_net_count` (lower wins; `NET_SINGLE_PIN` warnings gate success)
3. `unrouted_net_count` (lower wins)
4. `min_span` — penalty asc; a tiny `min(x_span, y_span)` is a line collapse
5. `max_components_per_row` — penalty asc; many components in one row = row wall
6. `dip_escape_violations` — penalty asc; a component blocking DIP pin escape
7. `via_count`
8. `trace_length_units`
9. `segment_count`
10. `routing_cost_units`
11. `placement_proxy_score` (final tie-breaker)
12. `candidate_index` (deterministic final tie-breaker)

`min_span`, `max_components_per_row`, and `dip_escape_violations` are the
"hand-built perfboard" terms that prevent the regression where the solver
collapsed eight components onto row 1 of a 15×20 board.

### Solve status

The solver reports a final solve status in the trace metadata under
`cpsat_solve_status` (numeric) which decodes to one of:

| Code | Status                                | Meaning |
|-----:|---------------------------------------|---------|
| 0    | `invalid-netlist`                     | At least one `NET_SINGLE_PIN` net, or a hard validation error |
| 1    | `placement-feasible-routing-incomplete` | All components placed, some required nets did not route |
| 2    | `fully-routed-valid`                  | All nets routed, zero validation errors, zero single-pin warnings |

The previous pipeline could not distinguish these states; the corrected
pipeline emits `cpsat_solve_status` so callers (UI, benchmark harness,
export job) can detect an invalid-netlist result and avoid presenting it
as a finished board.

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

CP-SAT is the default but it must never produce a worse result than
greedy. Two layers of fallback keep the user from seeing a regression:

1. **Routing-aware selection.** Every CP-SAT candidate is routed with the
   existing maze router, and greedy is *also* routed. The best-routed
   candidate wins, so if a CP-SAT candidate has more unrouted nets than
   greedy's output, the ranking picks greedy automatically. This is the
   primary safety net and triggers for any CP-SAT placement that the
   router can't complete.
2. **No-candidate fallback.** If CP-SAT returns zero usable candidates
   (e.g. model UNKNOWN/INFEASIBLE within the wall-time budget), the
   pipeline calls `place_greedy(...)` with the same options and returns
   that result if it places anything. The fallback is recorded in
   `SolverTrace.phase_timings_ms["cpsat_fallback_greedy"] = 1`.

`placement_engine="greedy"` is preserved indefinitely. The legacy placer
is `app.domain.traces.place.place_greedy` (also reachable as the historic
name `place`). The dispatcher in `app.domain.traces.solve.solve(...)`
and `place_only(...)` switches by `options.placement_engine` value.

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