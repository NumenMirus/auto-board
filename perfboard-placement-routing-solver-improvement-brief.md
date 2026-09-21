# Implementation Brief: Improve Perfboard Placement, Routing, and Solving

## Mission

Improve the perfboard autorouter so it returns layouts that are not merely electrically valid, but are consistently compact, routable, understandable, and practical to build by hand.

The repository now has two placement engines:

- Legacy greedy perfboard placer.
- Experimental OR-Tools CP-SAT global candidate-pose placer.

The CP-SAT placer is the correct architectural foundation, but placement quality will remain inconsistent until actual routing results are used to evaluate and improve placement. The target architecture is a bounded closed loop:

```text
project netlist + board + locked placements
  -> CP-SAT produces several diverse legal placements
  -> router routes and validates every promising placement
  -> solve pipeline ranks candidates using actual route quality
  -> routing failures/congestion create targeted placement feedback
  -> best fully routed, buildable layout is returned
```

Do not rewrite the domain model, pose generator, footprint registry, board model, or exporter. Extend the existing architecture incrementally and preserve backward compatibility.

## Current Repository Context

Relevant implementation locations:

```text
backend/app/domain/traces/place.py         Legacy greedy perfboard placer
backend/app/domain/traces/place_cpsat.py   Experimental global CP-SAT placer
backend/app/domain/traces/route.py         Perfboard trace router
backend/app/domain/traces/solve.py         Placement/routing orchestration
backend/app/domain/traces/validate.py      Perfboard validation
backend/app/domain/traces/score.py         Trace layout scoring
backend/app/domain/poses.py                Canonical legal-pose generation
backend/app/domain/models.py               Solver options and project models
backend/tests/domain/test_traces_place.py
backend/tests/domain/test_traces_place_cpsat.py
backend/tests/domain/test_traces_place_quality.py
backend/scripts/benchmark_placement.py
backend/tests/fixtures/
```

Existing constraints and compatibility expectations:

- CP-SAT remains opt-in through `SolverOptions.placement_engine == "cpsat"` until benchmarks establish it is safe to make default.
- Existing projects must continue to use the legacy greedy engine by default unless explicitly configured otherwise.
- Existing pose generation is the canonical source for legal placement geometry, rotation, body occupancy, and pin-hole mapping.
- Existing trace validation is the canonical postcondition check.
- Locked placements and any locked/manual routing semantics must remain authoritative.
- All solver work must respect worker cancellation and bounded time budgets.

## Non-Negotiable Success Criteria

Do not treat a lower placement proxy score as success. A solution is better only if it improves actual deliverable layouts.

Rank outcomes in this strict priority order:

1. Fewer placement/validation errors.
2. Fewer unrouted nets.
3. Fewer routing failures and disconnected terminals.
4. Lower actual routed trace length.
5. Fewer vias/layer changes.
6. Fewer trace segments and unnecessary turns.
7. Better component compactness and functional grouping.
8. Better hand-buildability: connectors at useful edges, room to solder, sensible part orientation, visible routing corridors.
9. Bounded and acceptable solve time.

The system must never claim a high-quality success when a placement only has a good proxy score but routes poorly.

## Required Workstream 1: Benchmark Corpus and Regression Gates

### Goal

Create reliable evidence that each placement/routing change helps real perfboard projects rather than a synthetic internal objective.

### Fixtures

Create at least 10 schema-valid `autobreadboard-project` JSON fixtures for perfboard. Every document must meet the actual `ProjectDocument` schema:

```json
{
  "format": "autobreadboard-project",
  "version": 1,
  "name": "Example",
  "board": { "modelId": "..." },
  "components": [
    {
      "ref": "R1",
      "footprintId": "...",
      "value": "...",
      "pins": [
        { "id": "1", "name": "1" },
        { "id": "2", "name": "2" }
      ]
    }
  ],
  "nets": [
    {
      "id": "NET1",
      "name": "NET1",
      "netClass": "digital",
      "priority": 50,
      "pins": [
        { "componentRef": "R1", "pin": "1" }
      ]
    }
  ],
  "layout": {
    "version": 1,
    "boardId": "...",
    "placements": [],
    "jumpers": []
  },
  "settings": {
    "seed": 7,
    "solverPreset": "balanced",
    "placementWeights": {},
    "routingWeights": {}
  }
}
```

Do not invent the shape from memory. Before adding fixtures, read:

```text
docs/PROJECT_JSON.md
backend/app/domain/models.py
backend/tests/fixtures/*.json
```

Use only registered board-model and perfboard-footprint IDs. Add a fixture-schema test that loads every new fixture with `ProjectDocument.model_validate` before testing solve behavior.

Required fixture families:

- 555 timer / astable with DIP-8, bypass capacitor, timing RC network, LED, power connector, and output connector.
- 74HC14 or similar logic DIP with bypass capacitor, LEDs, and headers.
- DIP/microcontroller-style header breakout.
- Transistor plus LED/load and base resistor.
- Connector-heavy input/output circuit where edge placement matters.
- Circuit with a multi-terminal power net.
- Circuit with a multi-terminal analog-sensitive net.
- Circuit requiring double-sided routing or at least strongly benefiting from it.
- Circuit with locked component placement(s).
- Deliberately impossible circuit that must fail gracefully.

### Benchmark output

Extend or use `backend/scripts/benchmark_placement.py` to emit a machine-readable JSON/CSV result and a concise human table. For every fixture, engine, and seed, record:

```text
fixture
engine
seed
preset
placement_status
placement_wall_time_ms
routing_wall_time_ms
total_wall_time_ms
components_placed
components_total
unrouted_net_count
unrouted_net_ids
validation_error_count
trace_length_mm
routing_cost
via_count
trace_count
segment_count
board_span_x
board_span_y
candidate_pose_count
candidate_layout_count
routed_candidate_count
selected_candidate_index
placement_proxy_score
```

Run both engines over fixed seeds:

```text
greedy: seed 1, 7, 42
cpsat:  seed 1, 7, 42
```

### Regression tests

Add stable assertions that CP-SAT:

- Never creates more placement errors than greedy on feasible benchmark fixtures.
- Never routes fewer nets than greedy on the flagship fixtures.
- Improves either actual routing cost, routed trace length, via count, or segment count on documented flagship fixtures.
- Completes within agreed preset-specific time limits.

Avoid byte-identical placement assertions across OR-Tools versions unless deterministic mode is explicitly enabled. Prefer invariants and measurable score ceilings.

## Required Workstream 2: Route-Aware Candidate Selection

### Goal

Make the solve pipeline select by actual routed quality, not only by the CP-SAT placement proxy.

### Required flow

Implement this pipeline in `backend/app/domain/traces/solve.py` or a clearly named orchestration helper:

```text
1. Build legal CP-SAT placement candidates.
2. Produce a bounded set of diverse feasible placement solutions.
3. Convert each selected pose set into canonical ComponentPlacement objects.
4. Route each candidate using the existing perfboard router.
5. Validate each routed result using the existing perfboard validator.
6. Compute actual route metrics.
7. Return the best candidate by lexicographic route-first ranking.
```

The candidate rank must not allow an attractive placement proxy to beat a fully routed solution. Implement an explicit ranking structure similar to:

```python
@dataclass(frozen=True)
class RoutedCandidateRank:
    unrouted_net_count: int
    validation_error_count: int
    via_count: int
    trace_length_units: int
    segment_count: int
    routing_cost_units: int
    placement_proxy_score: int
    candidate_index: int
```

Then select with:

```python
best = min(candidates, key=lambda candidate: candidate.rank)
```

The exact ordering may evolve, but it must be documented and tested.

### Required test

Create a test where:

- Candidate A has a lower CP-SAT proxy score.
- Candidate A has an unroutable net, higher via count, or higher actual trace cost.
- Candidate B has a higher placement proxy score.
- Candidate B routes fully and has better actual route outcome.

Assert that the complete solve pipeline returns B.

This is the key regression that proves the system solves the user-visible problem.

### Candidate count and time budgets

Respect presets and wall-time budgets. Suggested initial limits:

| Preset | CP-SAT budget | Candidate placements | Routing budget per candidate |
|---|---:|---:|---:|
| fast | 1–2 seconds | 2–3 | tightly bounded |
| balanced | 3–6 seconds | 4–6 | bounded |
| quality | 8–15 seconds | 8–12 | bounded |

Do not run all routing attempts blindly if time is exhausted. Check cancellation between candidate placements and between routing passes.

### Candidate diversity

Do not repeatedly route identical or near-identical CP-SAT placements. Generate diversity by one or more of:

- Deterministic seed variation.
- Small, controlled objective perturbations.
- No-good constraint for an exact previously selected pose assignment.
- Local diversity constraints for high-impact component pose choices.

For an exact duplicate selected assignment, add a constraint that requires at least one selected literal to differ:

```text
sum(selected_literals_from_previous_solution) <= selected_literal_count - 1
```

Do not require broad diversity at the cost of feasibility; retain the best known feasible candidate.

## Required Workstream 3: Smarter Routing and Rip-Up/Reroute

### Goal

Prevent easy early routes from consuming the only available corridor for hard nets.

### Net ordering

Replace input/declaration-order routing with a deterministic difficulty/priority ordering. Define a score that considers:

```text
net priority
net class
terminal count
estimated terminal span
number of available escape paths
whether endpoints include connectors or constrained/locked parts
```

Suggested ordering intent:

1. Ground, power, and high-current trunks.
2. Clock, switching, and analog-sensitive nets.
3. High-terminal-count nets.
4. Long difficult digital nets.
5. Short local digital links.
6. Low-priority nets.

Use the project’s actual allowed net classes:

```text
ground
power
high-current
analog-sensitive
clock
switching
digital
low-priority
custom
```

Do not use undocumented literals such as `analog` in fixtures or code.

### Multi-terminal nets

Treat a multi-pin net as an incremental routing tree, not unrelated point-to-point paths:

1. Choose a deterministic root terminal.
2. Route to one remaining terminal.
3. Add the path to that net’s tree.
4. Route each remaining terminal to the nearest valid point on the same-net tree.
5. Permit same-net trace reuse but never reuse a different-net trace.

For power and ground, preserve a clear topology preference. Start with trunk-and-branch for ordinary supply distribution; make star topology an explicit policy for sensitive nets rather than a universal default.

### Path cost

Extend maze-router path cost to include more than geometric length:

```text
step cost =
  length_cost
+ turn_penalty
+ via_penalty
+ congestion_penalty
+ proximity_to_component_body_penalty
+ history_penalty
+ optional edge/clearance penalty
```

Required behavior:

- Penalize unnecessary turns to avoid zig-zags.
- Penalize vias/layer transitions strongly but do not prohibit them when required.
- Penalize routing too close to dense component bodies to preserve solder access.
- Penalize already congested corridors.
- Allow same-net trace reuse only where electrically valid.
- Keep all existing collision/clearance rules hard.

### Rip-up and reroute

Implement a bounded rip-up-and-reroute loop:

```text
route all nets in difficulty order
if all route: finish
otherwise select the hardest failed net
identify a small set of lower-priority conflicting routed nets
rip up selected victim traces
increase history/congestion cost in failed region
route failed net
reroute victims
repeat until success, cancellation, or pass/time limit
```

Initial safe bounds:

```text
max rip-up passes: 3–10
max victim nets: 1–3
no rip-up of locked/manual traces
strict solve deadline
```

The router must record why a net failed where practical:

```text
no reachable target
component-body blockage
all corridors occupied by other nets
via/layer restriction
board boundary
cancelled/timed out
```

### Required tests

Add tests where:

- A low-priority early route blocks a high-priority later net.
- Routing without rip-up fails.
- Routing with bounded rip-up completes.
- A locked/manual trace is never ripped up.
- Repeated attempts do not repeatedly choose the identical blocked corridor.

## Required Workstream 4: Routing Feedback Into Placement

### Goal

Use actual routing failures and congestion to make the next placement candidate better.

Do not immediately formulate full detailed routing in CP-SAT. That will create an unnecessarily large and difficult model. Instead add targeted, bounded feedback.

### Failure classification

For each poor routed candidate, derive structured observations such as:

```text
unroutable net and terminal set
congested board cells/corridors
component bodies adjacent to the blocked corridor
selected candidate poses near the failure
excessive-via net
excessive-detour net
connector stranded from its associated subcircuit
```

### Feedback mechanisms

Use one or more of:

- Add local no-good constraints involving the small set of pose selections responsible for a blocked corridor.
- Increase coarse congestion penalties for occupied cells near recurrent blockage.
- Increase pin-level proximity weight for long local relationships, especially bypass capacitors and timing networks.
- Penalize connector poses that force long/crossing routes to their attached functional group.
- Penalize orientation choices that repeatedly block IC pin escape directions.

A targeted no-good constraint should require at least one local choice to change. For literals `a`, `b`, and `c` that form a bad local arrangement:

```text
a + b + c <= 2
```

Do not forbid every placement containing a particular component pose unless repeated evidence shows the pose itself is intrinsically bad.

### Required regression

Create a fixture where the first compact legal placement leaves no routing corridor and a nearby variation routes. Assert that feedback causes a changed placement and improves routing outcome within the configured solve budget.

## Required Workstream 5: Better Placement Objective for Hand-Built Perfboard

### Goal

Teach CP-SAT what a good hand-buildable perfboard looks like.

Do not reduce this to generic component-centre Manhattan distance. Use candidate-pose pin coordinates and functional relationships.

### High-value soft terms

Implement or strengthen these terms in `place_cpsat.py`:

1. **Pin-level local connectivity**
   - IC supply pins to bypass capacitor pins.
   - Timing/control IC pins to RC components.
   - LED to its current-limiting resistor.
   - Transistor to base resistor and load.
   - Connector pins to the functional block they serve.

2. **Functional cluster compactness**
   - Place passives belonging to an IC/function near their anchor.
   - Avoid spreading one cluster across the board merely because isolated local costs are equal.

3. **Connector and mechanical edge placement**
   - Prefer board-edge candidates for headers/connectors.
   - Prefer outward-facing connector orientation where footprint metadata supports it.
   - Preserve user locks as authoritative.

4. **Routing corridor preservation**
   - Divide board into coarse capacity bins.
   - Penalize excessive bodies/pins in a bin.
   - Reserve escape space around IC pins and connectors.
   - Penalize blocking a board-spanning row/column if that row/column is a likely routing corridor.

5. **Orientation consistency and assembly quality**
   - Modestly prefer consistent IC notch direction.
   - Prefer a coherent polarity direction for polarized components.
   - Avoid placing a component so close to an edge that it is mechanically impractical.

6. **Existing mechanical pose cost**
   - Include canonical pose mechanical cost as a low-weight term where meaningful.

### Candidate pruning

Never reintroduce greedy behavior through aggressive candidate pruning.

When limiting candidates per component:

- Keep multiple legal rotations.
- Keep candidates in several board regions.
- Keep edge-compatible candidates for connectors.
- Keep candidates near and away from cluster anchors when useful for topological alternatives.
- Log how many candidates were generated and retained for every component.

If a model-size guard reduces candidate counts, expose that fact in solve metadata.

## Required Workstream 6: Local Post-Route Repair

### Goal

Use inexpensive local moves to polish an otherwise good routed layout.

After a CP-SAT placement and route result, attempt bounded moves for non-locked components:

- Shift one or two holes.
- Rotate a passive.
- Swap nearby like-footprint passives where electrically legal.
- Move a noncritical component out of a congested corridor.
- Mirror/flip a local cluster around an IC when legal.

For each proposed move:

1. Preserve hard placement constraints.
2. Route only affected nets when safe, otherwise route the candidate under a strict small budget.
3. Accept only if the lexicographic actual-layout rank improves.
4. Stop after a bounded move budget or deadline.

Start with deterministic hill climbing. Do not add simulated annealing unless benchmark data proves it is necessary.

## Solver Reliability and Observability

### Required metadata

Record or return structured solver metadata; keep API additions backwards compatible:

```json
{
  "placementEngine": "cpsat",
  "placementStatus": "OPTIMAL | FEASIBLE | UNKNOWN | INFEASIBLE",
  "placementWallTimeMs": 0,
  "routeWallTimeMs": 0,
  "totalWallTimeMs": 0,
  "candidatePoseCount": 0,
  "candidateLayoutCount": 0,
  "routedCandidateCount": 0,
  "selectedCandidateIndex": 0,
  "unroutedNets": [],
  "traceLengthMm": 0,
  "viaCount": 0,
  "segmentCount": 0,
  "objective": {
    "netLengthProxy": 0,
    "clusterSpread": 0,
    "compactness": 0,
    "connectorEdge": 0,
    "orientation": 0,
    "congestion": 0,
    "actualRoutingCost": 0
  }
}
```

At minimum, emit this internally to test logs and benchmark output. Prefer exposing it in solver trace/result data if the existing API model permits it cleanly.

### CP-SAT status handling

Handle each result explicitly:

| Status | Required behavior |
|---|---|
| `OPTIMAL` | Evaluate selected solution(s), route candidates, return best actual layout |
| `FEASIBLE` | Treat incumbent as valid, route/evaluate it, retain metadata that optimality was not proven |
| `UNKNOWN` with incumbent | Evaluate available incumbent(s) under remaining budget |
| `UNKNOWN` without incumbent | Return explicit timeout/no-incumbent diagnostic; only fallback if documented |
| `INFEASIBLE` | Return clear infeasibility diagnostics; do not silently pretend greedy solved the equivalent constrained request |
| exception/model error | Log structured error and apply documented fallback policy |

Do not silently fall back to greedy without exposing that fallback. Otherwise users will believe CP-SAT was used while receiving the old weak result.

### Determinism

For deterministic test mode:

```python
solver.parameters.random_seed = options.seed
solver.parameters.num_search_workers = 1
```

Use one worker in CI/regression tests. Parallel search may be allowed in quality mode, but document that exact layout identity may vary.

### Model-size limits

Log:

```text
component count
candidate count total
candidates/component
selection variable count
pairwise auxiliary variable count
hole-occupancy constraint count
objective term count
CP-SAT status
wall time
best bound
objective value
```

Add safeguards against uncontrolled pairwise candidate interactions. Prefer retaining high-value relationships and dropping lower-value pair terms over allowing memory/runtime blowups.

## Product/UI Follow-Up (Not Required for First Backend PR)

Once the backend is measured and reliable, expose an advanced experimental interface:

- Placement engine: `Greedy` / `CP-SAT`
- Preset: `Fast` / `Balanced` / `Quality`
- Seed
- Number of alternatives
- Single-sided / double-sided policy
- Prefer shorter routes / fewer vias / more open layout / compact layout
- Lock component position and orientation
- Define keep-in / keep-out areas

Return several routed alternatives, not one opaque result. Each should show:

```text
routed nets
unrouted nets
trace length
vias
segment count
board span
solve time
brief routing/placement notes
```

## Suggested Delivery Plan

### PR 1 — Fixtures, benchmark, and determinism

- Add schema-valid perfboard fixture corpus.
- Add fixture validation test.
- Extend benchmark output with real routing metrics.
- Run greedy and CP-SAT comparison across fixed seeds.
- Add deterministic CP-SAT test configuration.
- Do not change default placement engine.

### PR 2 — Route-aware candidate ranking

- Route and validate each CP-SAT candidate.
- Add route-first lexicographic rank.
- Add explicit candidate-result metadata.
- Add regression where a worse proxy but better actual route wins.

### PR 3 — Routing difficulty order and rip-up/reroute

- Implement deterministic net difficulty ordering.
- Add multi-terminal routing-tree behavior where practical.
- Add congestion/history cost.
- Add bounded rip-up/reroute with locked trace protection.
- Add relevant routing regression fixtures.

### PR 4 — Placement feedback and hand-buildable objective

- Add targeted no-good constraints from routing failures.
- Strengthen pin-level local-net objective terms.
- Add connector edge/orientation and corridor-preservation penalties.
- Add model-size guardrails and telemetry.

### PR 5 — Local repair and experimental UI

- Add bounded post-route local move/rotate repair.
- Expose solver diagnostics and alternative layouts.
- Keep CP-SAT experimental until benchmark gates are consistently met.

## Testing Commands

Use the repository’s real commands/package tooling. At minimum, run the relevant backend tests after every stage:

```bash
cd backend
uv sync
uv run pytest tests/domain/test_traces_place.py -q
uv run pytest tests/domain/test_traces_place_cpsat.py -q
uv run pytest tests/domain/test_traces_place_quality.py -q
uv run pytest tests/domain/test_traces.py -q
uv run pytest tests/domain/test_route.py -q
uv run pytest -q
uv run python scripts/benchmark_placement.py
```

If the project’s actual test command differs, use the documented project command, but do not omit the full suite before submitting.

## Explicit Non-Goals

- Do not implement complete detailed routing inside CP-SAT in this workstream.
- Do not remove the greedy placer yet.
- Do not change breadboard solver behavior while working on perfboard.
- Do not replace canonical pose generation or validation with duplicate geometry code.
- Do not add unbounded solver loops or unbounded candidate counts.
- Do not optimize only Manhattan placement distance and call it routing quality.
- Do not rely on byte-identical OR-Tools outcomes across versions unless deterministic mode is enabled and tested.
- Do not silently hide CP-SAT failure behind a greedy fallback.

## Acceptance Checklist

### Benchmark and quality

- [ ] At least 10 valid perfboard projects are added and schema-validated.
- [ ] Benchmark output compares greedy and CP-SAT over fixed seeds.
- [ ] CP-SAT does not regress routed-net count on flagship feasible fixtures.
- [ ] CP-SAT shows measurable actual routing improvement on documented fixtures.

### Placement and solve pipeline

- [ ] CP-SAT produces bounded, diverse legal candidates.
- [ ] Every candidate is routed and validated within configured budgets.
- [ ] Final selection is route-first, not proxy-first.
- [ ] A regression proves that a fully routed candidate wins over a prettier but unroutable/proxy-better candidate.
- [ ] Locked placements remain unchanged.
- [ ] Timeout, unknown, infeasible, cancellation, and fallback outcomes are explicit.

### Routing

- [ ] Net routing order uses priority/difficulty rather than declaration order.
- [ ] Multi-terminal routing avoids independent duplicated point-to-point paths.
- [ ] Router uses turn, via, congestion, and history penalties.
- [ ] Bounded rip-up/reroute can resolve a controlled blocking case.
- [ ] Locked/manual traces are never ripped up.

### Feedback and buildability

- [ ] Routing failure can influence subsequent placement candidates.
- [ ] Placement objective includes pin-level local connectivity, connector handling, and corridor/congestion awareness.
- [ ] Candidate pruning preserves rotation and regional diversity.
- [ ] Solver metadata exposes model size and real routed metrics.

### Safety

- [ ] Worker cancellation and hard time limits are respected.
- [ ] Full backend test suite passes.
- [ ] No breadboard behavior or project-document compatibility is unintentionally changed.

## Definition of Done

The work is complete when the solver reliably returns layouts that have fewer routing failures, shorter and simpler actual traces, fewer avoidable vias and detours, better functional grouping, useful connector positions, and enough physical routing/soldering space to be preferable to the old greedy output on a representative set of real perfboard circuits.
