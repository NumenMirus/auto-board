"""Top-level perfboard solve pipeline.

Wraps placement + trace routing + validation + scoring into a single
callable that mirrors :func:`app.domain.solve.solve` for the breadboard.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.domain.models import (
    Component,
    ComponentPlacement,
    Diagnostic,
    LayoutScore,
    Net,
    PerfboardModel,
    ProjectDocument,
    SolverOptions,
    SolverTrace,
    ThroughHoleFootprint,
    TraceLayout,
)
from app.domain.traces import maze
from app.domain.traces import route as trace_route
from app.domain.traces.place import place as place_perfboard
from app.domain.traces.score import score_layout
from app.domain.traces.validate import validate_layout

__all__ = ["SolveResult", "place_only", "route_only", "solve"]


@dataclass(slots=True)
class SolveResult:
    layout: TraceLayout
    score: LayoutScore
    diagnostics: list[Diagnostic] = field(default_factory=list)
    trace: SolverTrace | None = None


def _initial_layout_from_document(
    doc: ProjectDocument,
) -> TraceLayout:
    placements = [
        ComponentPlacement.model_validate(p.model_dump(by_alias=True)) for p in doc.layout.placements
    ]
    return TraceLayout(board_id=doc.board.model_id, placements=placements)


def _route_validate_score(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    layout: TraceLayout,
    placement_cost: float,
    cancel: Callable[[], bool] | None,
    progress: Callable[[str, int], None] | None,
) -> tuple[TraceLayout, LayoutScore, list[Diagnostic], list[str]]:
    """Route `layout.placements`, validate, and score. Shared tail for both
    `solve` (place + route) and `route_only` (route against given placements).
    """
    graph = maze.build_maze(
        rows=board.rows,
        cols=board.cols,
        pitch_mm=board.pitch_mm,
        double_sided=board.layers == 2,
    )
    route_result = trace_route.route(
        board_id=board.id,
        placements=layout.placements,
        components=components,
        footprints=footprints,
        nets=nets,
        graph=graph,
        cancel=cancel,
        progress=lambda phase, percent: progress("trace-route", percent) if progress else None,
    )

    if progress is not None:
        progress("verify", 95)
    validation = validate_layout(board, footprints, components, nets, route_result.layout)

    if progress is not None:
        progress("score", 99)
    placed = {p.component_ref for p in route_result.layout.placements}
    components_placed = sum(1 for c in components if c.ref in placed)
    score = score_layout(
        placements=route_result.layout.placements,
        components_placed=components_placed,
        components_total=len(components),
        layout=route_result.layout,
        diagnostics=validation.diagnostics,
        placement_cost=placement_cost,
    )
    return route_result.layout, score, validation.diagnostics, list(route_result.unrouted_nets)


def solve(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: TraceLayout | None = None,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> SolveResult:
    """Run the perfboard pipeline: place → trace-route → validate → score.

    Locked placements in `initial_layout` are kept as-is (mirrors the
    breadboard placer); every unlocked component is (re)placed from scratch
    onto the board's plain grid before routing. This is the perfboard
    counterpart of `app.domain.solve.solve` — the `trace-solve` job operation.

    Placer is selected by ``options.placement_engine``:

    * ``"greedy"`` (default) — legacy single-pass placer from
      :mod:`app.domain.traces.place`.
    * ``"cpsat"`` — global OR-Tools CP-SAT placer from
      :mod:`app.domain.traces.place_cpsat`. Routing-aware candidate
      selection still happens here in the shared tail.
    """
    if progress is not None:
        progress("place", 0)
    layout = initial_layout or TraceLayout(board_id=board.id, placements=[])

    if options.placement_engine == "cpsat":
        from app.domain.traces.place_cpsat import solve_cpsat_placement as _cpsat_place

        placement = _cpsat_place(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            options=options,
            initial_layout=layout,
            cancel=cancel,
            progress=lambda phase, percent: progress("place", percent) if progress else None,
        )
    else:
        placement = place_perfboard(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            options=options,
            initial_layout=layout,
        )
    placed_layout = TraceLayout(board_id=board.id, placements=placement.placements)

    if progress is not None:
        progress("trace-route", 20)
    routed_layout, score, diagnostics, unrouted = _route_validate_score(
        board=board,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=placed_layout,
        placement_cost=placement.cost,
        cancel=cancel,
        progress=progress,
    )

    trace = SolverTrace(
        seed=options.seed,
        placement_order=placement.trace.placement_order,
        pose_choices=placement.trace.pose_choices,
        rejections=placement.trace.rejections,
        failed_nets=unrouted,
        ripups=[],
        iteration_scores=placement.trace.iteration_scores,
        phase_timings_ms={**placement.trace.phase_timings_ms, "trace-route": 0.0},
    )

    if progress is not None:
        progress("done", 100)

    return SolveResult(
        layout=routed_layout,
        score=score,
        diagnostics=diagnostics,
        trace=trace,
    )


def place_only(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: TraceLayout | None = None,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> SolveResult:
    """Place every unlocked component onto the perfboard grid — no routing phase. This is
    the `trace-place` job operation: the perfboard counterpart of the breadboard `place` op
    (`app.domain.place.place`). The returned layout is placed but unrouted, so the
    diagnostics from `validate_layout` will include `UNROUTED_TERMINAL` for every net —
    that mirrors the breadboard `place` op reporting `NET_OPEN` on its unrouted layout.

    Placer is selected by ``options.placement_engine`` (``"greedy"`` or
    ``"cpsat"``) — see :func:`solve` for the full description.
    """
    if progress is not None:
        progress("place", 0)
    layout = initial_layout or TraceLayout(board_id=board.id, placements=[])

    if options.placement_engine == "cpsat":
        from app.domain.traces.place_cpsat import solve_cpsat_placement as _cpsat_place

        placement = _cpsat_place(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            options=options,
            initial_layout=layout,
            cancel=cancel,
            progress=lambda phase, percent: progress("place", percent) if progress else None,
        )
    else:
        placement = place_perfboard(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            options=options,
            initial_layout=layout,
        )
    placed_layout = TraceLayout(board_id=board.id, placements=placement.placements)

    if progress is not None:
        progress("verify", 90)
    validation = validate_layout(board, footprints, components, nets, placed_layout)

    placed = {p.component_ref for p in placed_layout.placements}
    components_placed = sum(1 for c in components if c.ref in placed)
    score = score_layout(
        placements=placed_layout.placements,
        components_placed=components_placed,
        components_total=len(components),
        layout=placed_layout,
        diagnostics=validation.diagnostics,
        placement_cost=placement.cost,
    )

    trace = SolverTrace(
        seed=options.seed,
        placement_order=placement.trace.placement_order,
        pose_choices=placement.trace.pose_choices,
        rejections=placement.trace.rejections,
        failed_nets=[],
        ripups=[],
        iteration_scores=placement.trace.iteration_scores,
        phase_timings_ms=placement.trace.phase_timings_ms,
    )

    if progress is not None:
        progress("done", 100)

    return SolveResult(
        layout=placed_layout,
        score=score,
        diagnostics=validation.diagnostics,
        trace=trace,
    )


def route_only(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: TraceLayout | None = None,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> SolveResult:
    """Route the placements already present in `initial_layout` verbatim — no
    placement phase. This is the `trace-route` job operation: "route only
    against an existing placement" per `docs/PROJECT_JSON.md`.
    """
    if progress is not None:
        progress("trace-route", 20)
    layout = initial_layout or TraceLayout(board_id=board.id, placements=[])

    routed_layout, score, diagnostics, unrouted = _route_validate_score(
        board=board,
        footprints=footprints,
        components=components,
        nets=nets,
        layout=layout,
        placement_cost=0.0,
        cancel=cancel,
        progress=progress,
    )

    trace = SolverTrace(
        seed=options.seed,
        placement_order=[c.ref for c in components],
        pose_choices=[],
        rejections=[],
        failed_nets=unrouted,
        ripups=[],
        iteration_scores=[],
        phase_timings_ms={"trace-route": 0.0},
    )

    if progress is not None:
        progress("done", 100)

    return SolveResult(
        layout=routed_layout,
        score=score,
        diagnostics=diagnostics,
        trace=trace,
    )
