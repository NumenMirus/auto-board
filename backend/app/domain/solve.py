"""Top-level solve pipeline.

Composes the placement, routing, validation and scoring phases into a single
`solve()` call and exposes the M4 routing-feedback `optimize()` local search. Both
functions accept the same individual-typed-argument style as `validate_layout` and
`route` so the API layer can unpack a `SolveRequest` once and call straight through.

Cancellation and timeout are checked between phases and (where cheap) inside the inner
local-search / rip-up loops of the placement and routing phases. The deadline is the
`time.monotonic()` instant past which work must stop; when the caller doesn't supply
`options.timeout_seconds` we fall back to a 60-second default — long enough for the
fixtures, short enough to keep the smoke test bounded.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from app.domain.errors import SolverCancelled, SolverTimeout
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Layout,
    Net,
    PoseChoice,
    SolveResult,
    SolverOptions,
    SolverTrace,
    TraceRejection,
    TraceRipup,
)
from app.domain.place import place
from app.domain.route import route
from app.domain.score import score_layout
from app.domain.validate import validate_layout

__all__ = ["optimize", "solve"]

_DEFAULT_TIMEOUT_SECONDS: int = 60
_CRITICAL_NET_CLASSES: frozenset[str] = frozenset({"switching", "clock", "analog-sensitive", "high-current"})


def solve(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: Layout | None = None,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> SolveResult:
    """Run the full place-route-validate-score pipeline.

    Cancellation and timeout are checked between phases; if `cancel()` returns `True` we
    raise `SolverCancelled`; if the monotonic deadline passes we raise `SolverTimeout`.
    Both exceptions are deterministic-domain errors, never retried.

    Validation strategy: rather than run a separate early `validate_layout` call (which
    would cost an extra ~20 ms and double the input-check work), we let the final
    `validate_layout` pass after routing surface every input, placement and connectivity
    issue at once. The placement/route phases are forgiving of unplaceable components
    (they appear in `placement.unplaced` / `route.unrouted_nets`) and the validator
    emits the proper `UNPLACED_COMPONENT` / `NET_OPEN` diagnostics in the final pass.
    """

    start_monotonic = time.monotonic()
    timeout_s = options.timeout_seconds if options.timeout_seconds is not None else _DEFAULT_TIMEOUT_SECONDS
    deadline = start_monotonic + timeout_s

    timings: dict[str, float] = {}

    _maybe_progress(progress, "validate", 0)
    _check_cancel(cancel)
    t0 = time.monotonic()
    timings["validate"] = (time.monotonic() - t0) * 1000.0

    # ------------------------------------------------------------------
    # place
    # ------------------------------------------------------------------
    _maybe_progress(progress, "place", 10)
    _check_cancel(cancel)
    _check_deadline(deadline)
    t0 = time.monotonic()
    placement_result = place(board, index, footprints, components, nets, options, initial_layout)
    timings["place"] = (time.monotonic() - t0) * 1000.0
    _check_cancel(cancel)
    _check_deadline(deadline)

    # ------------------------------------------------------------------
    # route
    # ------------------------------------------------------------------
    _maybe_progress(progress, "route", 50)
    t0 = time.monotonic()
    seed_layout = Layout(
        version=1,
        board_id=board.id,
        placements=list(placement_result.placements),
        jumpers=list(initial_layout.jumpers) if initial_layout is not None else [],
        manual_electrical_links=(
            list(initial_layout.manual_electrical_links) if initial_layout is not None else []
        ),
    )
    route_result = route(
        board=board,
        index=index,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=seed_layout,
        options=options,
        deadline_monotonic=deadline,
    )
    timings["route"] = (time.monotonic() - t0) * 1000.0
    _check_cancel(cancel)
    _check_deadline(deadline)

    # ------------------------------------------------------------------
    # verify
    # ------------------------------------------------------------------
    _maybe_progress(progress, "verify", 80)
    t0 = time.monotonic()
    final_layout = Layout(
        version=1,
        board_id=board.id,
        placements=list(placement_result.placements),
        jumpers=list(route_result.jumpers),
        manual_electrical_links=list(seed_layout.manual_electrical_links),
    )
    diagnostics, _base_score = validate_layout(
        board=board,
        index=index,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=final_layout,
        options=options,
    )
    timings["verify"] = (time.monotonic() - t0) * 1000.0

    # ------------------------------------------------------------------
    # score (combine the two cost numbers from placement/route with the count fields)
    # ------------------------------------------------------------------
    _maybe_progress(progress, "export", 95)
    t0 = time.monotonic()
    final_score = score_layout(
        board=board,
        index=index,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=final_layout,
        diagnostics=diagnostics,
        placement_cost=placement_result.cost,
        routing_cost=route_result.cost,
    )
    timings["export"] = (time.monotonic() - t0) * 1000.0

    # ------------------------------------------------------------------
    # trace merge
    # ------------------------------------------------------------------
    merged_trace = _merge_traces(
        seed=options.seed,
        placement_trace=placement_result.trace,
        route_trace=route_result.trace,
        timings=timings,
    )

    _maybe_progress(progress, "export", 100)
    return SolveResult(
        layout=final_layout,
        score=final_score,
        diagnostics=diagnostics,
        trace=merged_trace,
    )


def optimize(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    base_layout: Layout,
    options: SolverOptions,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> SolveResult:
    """M4 routing-feedback local search.

    For up to `max(1, options.max_local_search_iterations // 4)` iterations: pick a
    random non-locked placed component, propose one placement move (translate / rotate
    / span change), compute the full energy as `placement_cost_delta + (new routing
    cost) - (current routing cost)`, accept ONLY on strict improvement (no simulated
    annealing — main spec §6.5 forbids it before metrics exist). Cancellation and
    timeout are checked between iterations.

    Returns a `SolveResult` built the same way `solve()` does.
    """

    start_monotonic = time.monotonic()
    timeout_s = options.timeout_seconds if options.timeout_seconds is not None else _DEFAULT_TIMEOUT_SECONDS
    deadline = start_monotonic + timeout_s

    timings: dict[str, float] = {}
    _maybe_progress(progress, "validate", 0)
    t0 = time.monotonic()
    timings["validate"] = (time.monotonic() - t0) * 1000.0

    best_layout = base_layout.model_copy(deep=True)
    # Compute the baseline routing cost for the starting layout.
    _check_cancel(cancel)
    _check_deadline(deadline)

    _maybe_progress(progress, "route", 50)
    t0 = time.monotonic()
    best_route = route(
        board=board,
        index=index,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=Layout(
            version=1,
            board_id=board.id,
            placements=list(best_layout.placements),
            jumpers=list(best_layout.jumpers),
            manual_electrical_links=list(best_layout.manual_electrical_links),
        ),
        options=options,
        deadline_monotonic=deadline,
    )
    best_routing_cost = best_route.cost
    timings["route"] = (time.monotonic() - t0) * 1000.0
    _check_deadline(deadline)

    # Estimate the placement cost using validate_layout's count-based score; we don't
    # have a separate placement_cost for the baseline, so we fall back to 0.0.
    best_placement_cost = 0.0

    rng = random.Random(options.seed)
    max_iters = max(1, options.max_local_search_iterations // 4)
    locked_refs = {p.component_ref for p in best_layout.placements if p.locked}

    for _iteration in range(max_iters):
        _check_cancel(cancel)
        _check_deadline(deadline)

        candidate_refs = [
            p.component_ref for p in best_layout.placements if p.component_ref not in locked_refs
        ]
        if not candidate_refs:
            break
        target_ref = candidate_refs[rng.randrange(len(candidate_refs))]
        perturbed_placements, perturb_cost = _propose_perturbation(
            placements=best_layout.placements,
            target_ref=target_ref,
            components=components,
            index=index,
            footprints=footprints,
            nets=nets,
            rng=rng,
        )
        if perturbed_placements is None:
            continue

        perturbed_layout = Layout(
            version=1,
            board_id=board.id,
            placements=perturbed_placements,
            jumpers=list(best_layout.jumpers),
            manual_electrical_links=list(best_layout.manual_electrical_links),
        )

        _check_deadline(deadline)
        new_route = route(
            board=board,
            index=index,
            footprints=footprints,
            components=components,
            nets=nets,
            layout=perturbed_layout,
            options=options,
            deadline_monotonic=deadline,
        )
        new_routing_cost = new_route.cost
        energy_delta = (perturb_cost - best_placement_cost) + (new_routing_cost - best_routing_cost)
        if energy_delta >= 0:
            continue  # not an improvement; main spec §6.5 forbids annealing

        best_layout = perturbed_layout.model_copy(deep=True)
        best_layout.jumpers = list(new_route.jumpers)
        best_routing_cost = new_routing_cost
        best_placement_cost = perturb_cost

    # ------------------------------------------------------------------
    # verify + score on the best layout
    # ------------------------------------------------------------------
    _maybe_progress(progress, "verify", 80)
    t0 = time.monotonic()
    diagnostics, _ = validate_layout(
        board=board,
        index=index,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=best_layout,
        options=options,
    )
    timings["verify"] = (time.monotonic() - t0) * 1000.0

    _maybe_progress(progress, "export", 95)
    t0 = time.monotonic()
    final_score = score_layout(
        board=board,
        index=index,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=best_layout,
        diagnostics=diagnostics,
        placement_cost=best_placement_cost,
        routing_cost=best_routing_cost,
    )
    timings["export"] = (time.monotonic() - t0) * 1000.0

    trace = SolverTrace(
        seed=options.seed,
        placement_order=[],
        pose_choices=[],
        rejections=[],
        failed_nets=[],
        ripups=[],
        iteration_scores=[],
        phase_timings_ms=timings,
    )

    _maybe_progress(progress, "export", 100)
    return SolveResult(
        layout=best_layout,
        score=final_score,
        diagnostics=diagnostics,
        trace=trace,
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _maybe_progress(
    progress: Callable[[str, int], None] | None,
    phase: str,
    percent: int,
) -> None:
    if progress is not None:
        progress(phase, percent)


def _check_cancel(cancel: Callable[[], bool] | None) -> None:
    if cancel is not None and cancel():
        raise SolverCancelled("solver cancelled")


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise SolverTimeout("solver deadline exceeded")


def _merge_traces(
    *,
    seed: int,
    placement_trace: SolverTrace,
    route_trace: SolverTrace,
    timings: dict[str, float],
) -> SolverTrace:
    """Concatenate the per-phase traces into one `SolverTrace`."""

    pose_choices: list[PoseChoice] = list(placement_trace.pose_choices)
    rejections: list[TraceRejection] = list(placement_trace.rejections)
    failed_nets: list[str] = list(placement_trace.failed_nets) + list(route_trace.failed_nets)
    ripups: list[TraceRipup] = list(placement_trace.ripups) + list(route_trace.ripups)
    iteration_scores: list[float] = list(placement_trace.iteration_scores) + list(
        route_trace.iteration_scores
    )

    merged_timings: dict[str, float] = {}
    merged_timings.update(placement_trace.phase_timings_ms)
    merged_timings.update(route_trace.phase_timings_ms)
    merged_timings.update(timings)

    return SolverTrace(
        seed=seed,
        placement_order=list(placement_trace.placement_order),
        pose_choices=pose_choices,
        rejections=rejections,
        failed_nets=failed_nets,
        ripups=ripups,
        iteration_scores=iteration_scores,
        phase_timings_ms=merged_timings,
    )


def _propose_perturbation(
    *,
    placements: list[ComponentPlacement],
    target_ref: str,
    components: list[Component],
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    nets: list[Net],
    rng: random.Random,
) -> tuple[list[ComponentPlacement] | None, float]:
    """Perturb one non-locked placement's anchor/orientation/span.

    Picks a new anchor that doesn't collide with any other placement's occupied holes,
    a new orientation from the footprint's supported set, and (for flexible footprints)
    a new span. Returns `(new_placements, placement_cost)`. Returns `(None, inf)` when
    the perturbation is infeasible (caller skips).
    """

    target_idx = next((i for i, p in enumerate(placements) if p.component_ref == target_ref), None)
    if target_idx is None:
        return None, float("inf")

    target_placement = placements[target_idx]
    components_by_ref = {c.ref: c for c in components}
    target_component = components_by_ref.get(target_ref)
    if target_component is None:
        return None, float("inf")

    footprint = footprints.get(target_component.footprint_id)
    if footprint is None:
        return None, float("inf")

    other_occupied: set[str] = set()
    for p in placements:
        if p.component_ref == target_ref:
            continue
        other_occupied.update(p.occupied_hole_ids)
        other_occupied.update(p.pin_holes.values())

    # Pick a new orientation and (if flexible) span.
    if footprint.supported_orientations:
        new_orientation = footprint.supported_orientations[
            rng.randrange(len(footprint.supported_orientations))
        ]
    else:
        new_orientation = target_placement.orientation
    new_span = target_placement.span
    if footprint.geometry.flexible_lead_span is not None:
        span_min = footprint.geometry.flexible_lead_span.min_holes
        span_max = footprint.geometry.flexible_lead_span.max_holes
        new_span = rng.randint(span_min, span_max)

    # Compute the rotated footprint cells.
    rotated = _rotated_offsets(footprint, new_orientation, new_span)
    if not rotated:
        return None, float("inf")

    # Anchor candidates: any lattice hole whose rotated cells are all enabled and
    # disjoint from `other_occupied`. Iterate sorted for determinism.
    candidates: list[tuple[float, float]] = []
    for anchor_hole_id in sorted(index.idx):
        anchor_idx = index.idx[anchor_hole_id]
        if not index.enabled[anchor_idx]:
            continue
        ax, ay = index.points[anchor_idx]
        ok = True
        for ox, oy in rotated:
            tx = ax + float(ox) * 2.54
            ty = ay + float(oy) * 2.54
            # Find the nearest lattice hole to (tx, ty) within a small tolerance.
            col = round(tx / 2.54)
            row_y = ty
            # Resolve a hole id: only main lattice holes (tie-point) are placement
            # targets, so look up (col, row) in the lattice.
            row_idx = None
            for ri, ry in enumerate(_row_y(index)):
                if abs(ry - row_y) < 1e-6:
                    row_idx = ri
                    break
            if row_idx is None:
                ok = False
                break
            target_hole_idx = index.lattice.get((col, row_idx))
            if target_hole_idx is None:
                ok = False
                break
            th_id = index.hole_ids[target_hole_idx]
            if th_id in other_occupied:
                ok = False
                break
        if ok:
            candidates.append((ax, ay))
    if not candidates:
        return None, float("inf")

    new_anchor_idx = rng.randrange(len(candidates))
    new_anchor_x, new_anchor_y = candidates[new_anchor_idx]
    # Find the nearest lattice hole for that anchor.
    col = round(new_anchor_x / 2.54)
    row_idx = None
    for ri, ry in enumerate(_row_y(index)):
        if abs(ry - new_anchor_y) < 1e-6:
            row_idx = ri
            break
    if row_idx is None:
        return None, float("inf")
    anchor_hole_idx = index.lattice.get((col, row_idx))
    if anchor_hole_idx is None:
        return None, float("inf")
    anchor_hole_id = index.hole_ids[anchor_hole_idx]

    # Build the new pin_holes mapping.
    new_pin_holes: dict[str, str] = {}
    new_occupied: list[str] = []
    for pin_id, ox, oy in _pin_offset_triples(footprint, new_span):
        target_x = new_anchor_x + float(ox) * 2.54
        target_y = new_anchor_y + float(oy) * 2.54
        col_p = round(target_x / 2.54)
        row_p = None
        for ri, ry in enumerate(_row_y(index)):
            if abs(ry - target_y) < 1e-6:
                row_p = ri
                break
        if row_p is None:
            return None, float("inf")
        hole_idx = index.lattice.get((col_p, row_p))
        if hole_idx is None:
            return None, float("inf")
        h_id = index.hole_ids[hole_idx]
        new_pin_holes[pin_id] = h_id
        if h_id not in new_occupied:
            new_occupied.append(h_id)
    for ox, oy in rotated:
        target_x = new_anchor_x + float(ox) * 2.54
        target_y = new_anchor_y + float(oy) * 2.54
        col_p = round(target_x / 2.54)
        row_p = None
        for ri, ry in enumerate(_row_y(index)):
            if abs(ry - target_y) < 1e-6:
                row_p = ri
                break
        if row_p is None:
            continue
        hole_idx = index.lattice.get((col_p, row_p))
        if hole_idx is None:
            continue
        h_id = index.hole_ids[hole_idx]
        if h_id not in new_occupied:
            new_occupied.append(h_id)

    new_placement = ComponentPlacement(
        component_ref=target_ref,
        anchor_hole_id=anchor_hole_id,
        orientation=new_orientation,
        span=new_span,
        pin_holes=new_pin_holes,
        occupied_hole_ids=new_occupied,
        locked=False,
    )

    new_placements = list(placements)
    new_placements[target_idx] = new_placement
    # Approximation: each occupied lattice hole contributes one pitch of distance to
    # the placement-cost energy. Cheap but monotonic in the perturbation size.
    placement_cost = float(len(new_occupied)) * 2.54
    return new_placements, placement_cost


def _rotated_offsets(
    footprint: BreadboardFootprint,
    orientation: int,
    span: int | None,
) -> list[tuple[int, int]]:
    """Return the rotated pin offsets for a footprint at the chosen orientation/span."""

    out: list[tuple[int, int]] = []
    for _pin_id, ox, oy in _pin_offset_triples(footprint, span):
        out.append(_rotate(ox, oy, orientation))
    return out


def _pin_offset_triples(
    footprint: BreadboardFootprint,
    span: int | None,
) -> list[tuple[str, int, int]]:
    """Return `(pin_id, offset_x, offset_y)` triples with the footprint's pin offsets.

    Flexible footprints regenerate pin offsets for the chosen `span`; rigid footprints
    use their registry offsets as-is.
    """

    flex = footprint.geometry.flexible_lead_span
    if flex is None or span is None:
        return [(pin_id, rh.x, rh.y) for pin_id, rh in footprint.pin_offsets.items()]

    # Two-pin flexible: pin 1 at (0, 0), pin 2 at (span-1, 0).
    if "1" in footprint.pin_offsets and "2" in footprint.pin_offsets and len(footprint.pin_offsets) == 2:
        return [
            ("1", 0, 0),
            ("2", max(span - 1, 0), 0),
        ]
    return [(pin_id, rh.x, rh.y) for pin_id, rh in footprint.pin_offsets.items()]


def _rotate(x: int, y: int, orientation: int) -> tuple[int, int]:
    """Rotate a lattice offset by `orientation` (in degrees) about the anchor."""

    o = orientation % 360
    if o == 0:
        return (x, y)
    if o == 90:
        return (-y, x)
    if o == 180:
        return (-x, -y)
    if o == 270:
        return (y, -x)
    return (x, y)


def _row_y(index: BoardIndex) -> list[float]:
    """Return the Y coordinate of every row in main-area order.

    Walks the lattice once; ordering by row index ascending.
    """

    rows: dict[int, float] = {}
    for (_col, row_idx), hole_idx in index.lattice.items():
        if row_idx in rows:
            continue
        rows[row_idx] = index.points[hole_idx][1]
    return [rows[i] for i in sorted(rows)]
