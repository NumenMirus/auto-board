"""Final-layout scoring.

`score_layout` consumes the diagnostics from `validate_layout` plus the two cost numbers
the solver computed elsewhere (`placement_cost` from `app.domain.cost.placement_cost` and
`routing_cost` from `app.domain.route._compute_routing_cost`) and produces the single
`LayoutScore` returned by the solve pipeline. The two cost fields are passed straight
through; this module is responsible for the count-based fields (`components_placed`,
`nets_completed`, `jumper_count`, `total_jumper_length_mm`, `crossings`,
`error_count`, `warning_count`) and for wiring `total = placement_cost + routing_cost`.

The signature mirrors `validate_layout` and `route`: individual typed arguments rather
than a wrapped `ScoreRequest` Pydantic model.
"""

from __future__ import annotations

from itertools import pairwise

from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Diagnostic,
    Jumper,
    Layout,
    LayoutScore,
    Net,
    Point,
)

__all__ = ["score_layout"]


def score_layout(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    layout: Layout,
    diagnostics: list[Diagnostic],
    placement_cost: float,
    routing_cost: float,
) -> LayoutScore:
    """Produce the final `LayoutScore` for `layout`."""

    components_placed = _count_components_placed(layout.placements, components)
    components_total = len(components)
    nets_completed = _count_nets_completed(nets, diagnostics)
    nets_total = len(nets)
    jumper_count = len(layout.jumpers)
    total_jumper_length_mm = round(sum(j.estimated_length_mm for j in layout.jumpers), 1)
    crossings = _count_layout_crossings(layout.jumpers)
    error_count = sum(1 for d in diagnostics if d.severity == "error")
    warning_count = sum(1 for d in diagnostics if d.severity == "warning")

    return LayoutScore(
        total=placement_cost + routing_cost,
        placement_cost=placement_cost,
        routing_cost=routing_cost,
        components_placed=components_placed,
        components_total=components_total,
        nets_completed=nets_completed,
        nets_total=nets_total,
        jumper_count=jumper_count,
        total_jumper_length_mm=total_jumper_length_mm,
        crossings=crossings,
        error_count=error_count,
        warning_count=warning_count,
    )


def _count_components_placed(
    placements: list[ComponentPlacement],
    components: list[Component],
) -> int:
    valid_refs = {c.ref for c in components}
    placed_refs = {p.component_ref for p in placements if p.component_ref in valid_refs}
    return len(placed_refs)


def _count_nets_completed(nets: list[Net], diagnostics: list[Diagnostic]) -> int:
    """A net is completed when no `NET_OPEN` / `SHORT_BETWEEN_NETS` references it.

    Diagnostics reference nets via `related_net_ids`. `NET_OPEN` diagnostics emit one id
    per pin unreachable, so the first entry is the failing net; `SHORT_BETWEEN_NETS`
    emits every net id that shares a physical node, so any id referencing it is a
    short. Nets with fewer than two placed pins do not appear as a NET_OPEN/SHORT and
    are not counted as completed here (the validator would have emitted
    `NET_SINGLE_PIN` for them, which is a warning, not an error).
    """

    failed: set[str] = set()
    for d in diagnostics:
        if d.code in ("NET_OPEN", "SHORT_BETWEEN_NETS"):
            failed.update(d.related_net_ids)

    return sum(1 for n in nets if n.id not in failed)


def _count_layout_crossings(jumpers: list[Jumper]) -> int:
    """Count strict segment intersections between jumper-path segments (O(n^2))."""

    segments: list[tuple[Point, Point]] = []
    for j in jumpers:
        for a, b in pairwise(j.path.points):
            segments.append((a, b))

    crossings = 0
    for i in range(len(segments)):
        for k in range(i + 1, len(segments)):
            if _segments_cross(segments[i][0], segments[i][1], segments[k][0], segments[k][1]):
                crossings += 1
    return crossings


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Strict segment-segment intersection test (collinear overlaps don't count)."""

    def _orient(p: Point, q: Point, r: Point) -> float:
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)

    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    s1 = (o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)
    s2 = (o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)
    return s1 and s2
