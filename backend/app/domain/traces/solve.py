"""Top-level perfboard solve pipeline.

Wraps placement + trace routing + validation + scoring into a single
callable that mirrors :func:`app.domain.solve.solve` for the breadboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.domain.models import (
    Component,
    ComponentPlacement,
    Net,
    PerfboardModel,
    ProjectDocument,
    SolverOptions,
    SolverTrace,
    TraceLayout,
)
from app.domain.perfboards.registry import ThroughHoleFootprint
from app.domain.traces import maze
from app.domain.traces import route as trace_route
from app.domain.traces.score import score_layout
from app.domain.traces.validate import validate_layout

__all__ = ["SolveResult", "solve"]


@dataclass(slots=True)
class SolveResult:
    layout: TraceLayout
    score: object  # LayoutScore — kept untyped to avoid an import cycle
    diagnostics: list = field(default_factory=list)
    trace: SolverTrace | None = None


def _initial_layout_from_document(
    doc: ProjectDocument,
) -> TraceLayout:
    placements = [
        ComponentPlacement.model_validate(p.model_dump(by_alias=True))
        for p in doc.layout.placements
    ]
    return TraceLayout(board_id=doc.board.model_id, placements=placements)


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
    """Run the perfboard pipeline: layout (passthrough) → trace-route → validate → score.

    The perfboard pipeline does not run a placement solver of its own — the
    component positions come from the input layout (which the API layer or
    the user provides). This keeps Phase 1B focused on the new piece
    (trace routing) and means the editor can place components freely before
    requesting a trace-route pass.
    """
    if progress is not None:
        progress("validate", 0)
    layout = initial_layout or TraceLayout(board_id=board.id, placements=[])

    if progress is not None:
        progress("trace-route", 20)

    graph = maze.build_maze(
        rows=board.rows,
        cols=board.cols,
        pitch_mm=board.pitch_mm,
        double_sided=board.layers == 2,
    )
    route_result = trace_route.route(
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
    )

    trace = SolverTrace(
        seed=options.seed,
        placement_order=[c.ref for c in components],
        pose_choices=[],
        rejections=[],
        failed_nets=list(route_result.unrouted_nets),
        ripups=[],
        iteration_scores=[],
        phase_timings_ms={"trace-route": 0.0},
    )

    if progress is not None:
        progress("done", 100)

    return SolveResult(
        layout=route_result.layout,
        score=score,
        diagnostics=validation.diagnostics,
        trace=trace,
    )
