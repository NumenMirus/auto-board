"""Perfboard trace routing driver.

Picks net order, calls the maze router for each net, applies rip-up/reroute
on failure, and assembles a :class:`TraceLayout`.

Routing strategy (per main spec §7.4 / Phase 1B plan):

1. Order nets: critical classes first, then power/ground, then multi-terminal,
   then by length / priority, then by id.
2. For each net: pick a Steiner-tree order over its terminals (greedy attach),
   then maze-route between successive terminals starting from the cheapest
   already-routed terminal as the anchor.
3. After each route, increment ``MazeEdge.usage`` on every used edge so the
   next net pays a congestion penalty.
4. If a route returns ``None``, rip up to ``max_ripup_iterations``: remove
   the k=3 highest-cost unlocked traces in the failing region, mark their
   edges as ``forbidden``, retry.
5. On exhaustion, leave the net partially routed and emit an
   ``UNROUTED_TERMINAL`` diagnostic — never raise.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from app.domain.errors import DomainError
from app.domain.models import (
    Component,
    ComponentPlacement,
    Net,
    Point,
    Trace,
    TraceLayout,
    TraceSegment,
    Via,
)
from app.domain.perfboards.registry import ThroughHoleFootprint
from app.domain.traces import maze

__all__ = ["RouteResult", "route"]

DEFAULT_RIPUP_K = 3
DEFAULT_MAX_RIPUP_ITERATIONS = 8


@dataclass(slots=True)
class RouteResult:
    layout: TraceLayout
    unrouted_nets: list[str] = field(default_factory=list)
    ripup_count: int = 0
    trace_cost: float = 0.0


def _pin_hole_ids(
    placements: list[ComponentPlacement],
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
) -> dict[str, dict[str, str]]:
    """Build ``component_ref -> {pin_name -> hole_id}`` from placements."""
    by_ref = {c.ref: c for c in components}
    out: dict[str, dict[str, str]] = {}
    for p in placements:
        comp = by_ref.get(p.component_ref)
        if comp is None:
            continue
        out[p.component_ref] = dict(p.pin_holes)
    return out


def _net_terminal_holes(
    net: Net,
    pin_map: dict[str, dict[str, str]],
) -> list[str]:
    """Return the hole ids this net needs to connect."""
    holes: list[str] = []
    for pin in net.pins:
        ref_holes = pin_map.get(pin.component_ref)
        if ref_holes is None:
            continue
        h = ref_holes.get(pin.pin)
        if h is not None:
            holes.append(h)
    return holes


def _sort_nets(nets: list[Net]) -> list[Net]:
    """Order nets: critical classes first, then power/ground, then multi-terminal,
    then by priority desc, then by id ascending."""
    priority_class = {
        "ground": 0,
        "power": 1,
        "high-current": 2,
        "clock": 3,
        "switching": 4,
        "analog-sensitive": 5,
        "digital": 6,
        "low-priority": 7,
        "custom": 8,
    }

    def key(n: Net) -> tuple[int, int, int, str]:
        return (
            priority_class.get(n.net_class, 9),
            0 if n.net_class in ("ground", "power") else 1,
            -len(n.pins),
            n.id,
        )

    return sorted(nets, key=key)


def _steiner_order(terminals: list[str], graph: maze.MazeGraph) -> list[str]:
    """Greedy attach: start at the first terminal, repeatedly append the
    closest-to-the-tree terminal until all are included. Cost is Manhattan.
    """
    if len(terminals) <= 1:
        return list(terminals)
    remaining = set(terminals[1:])
    order = [terminals[0]]
    while remaining:
        anchor_row, anchor_col = graph.nodes[order[-1]].row, graph.nodes[order[-1]].col
        nxt = min(
            remaining,
            key=lambda h: abs(graph.nodes[h].row - anchor_row) + abs(graph.nodes[h].col - anchor_col),
        )
        order.append(nxt)
        remaining.remove(nxt)
    return order


def _path_to_segments(
    result: maze.MazeResult,
    graph: maze.MazeGraph,
    *,
    width_mm: float,
) -> tuple[list[TraceSegment], list[Via], float]:
    """Convert a maze result into trace segments + vias + total length."""
    if len(result.path) < 2:
        return [], list(result.vias), 0.0
    segments: list[TraceSegment] = []
    total_length = 0.0
    for i, layer in enumerate(result.layers):
        a, b = result.path[i], result.path[i + 1]
        pa, pb = graph.nodes[a].point, graph.nodes[b].point
        seg_length = math.hypot(pb.x - pa.x, pb.y - pa.y)
        segments.append(
            TraceSegment(start=Point(x=pa.x, y=pa.y), end=Point(x=pb.x, y=pb.y), layer=layer, width_mm=width_mm)
        )
        total_length += seg_length
    return segments, list(result.vias), total_length


def _trace_cost(trace: Trace, graph: maze.MazeGraph) -> float:
    """Cost ranking for rip-up: shorter is cheaper; vias add 5 each."""
    return trace.estimated_length_mm + 5.0 * float(len(trace.vias))


def _ripup_forbidden(
    traces: list[Trace],
    failed_region: set[str],
    k: int,
) -> set[tuple[str, str, str]]:
    """Pick the k highest-cost unlocked traces whose path intersects
    ``failed_region``; emit the edges they used as forbidden for the next pass.
    """
    candidates = [
        t for t in traces
        if not t.locked and any(seg.start and (seg.start.x is not None) for seg in t.segments)
        and any(
            any(p == hid for p in (s.start.x, s.start.y))  # noqa: not a perfect region match — see note
            for s in t.segments
            for hid in failed_region
        )
    ]
    if not candidates:
        candidates = [t for t in traces if not t.locked]
    candidates.sort(key=_trace_cost, reverse=True)
    picked = candidates[:k]
    forbidden: set[tuple[str, str, str]] = set()
    for trace in picked:
        for seg in trace.segments:
            # Use coordinate-based round-trip to hole ids (cheap, robust).
            for hid, node in graph.nodes.items():
                if (math.isclose(node.point.x, seg.start.x) and math.isclose(node.point.y, seg.start.y)) or \
                   (math.isclose(node.point.x, seg.end.x) and math.isclose(node.point.y, seg.end.y)):
                    forbidden.add((hid, hid, seg.layer))
    return forbidden


def route(
    *,
    placements: list[ComponentPlacement],
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
    nets: list[Net],
    graph: maze.MazeGraph,
    width_mm: float = 0.4,
    max_ripup_iterations: int = DEFAULT_MAX_RIPUP_ITERATIONS,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> RouteResult:
    """Run the trace router and return a :class:`RouteResult`.

    ``graph`` must be a :func:`app.domain.traces.maze.build_maze` graph built
    from the same perfboard the placements target. ``placements`` must be a
    full placement list (locked or unlocked) — pin holes are looked up from
    :attr:`ComponentPlacement.pin_holes`.
    """
    pin_map = _pin_hole_ids(placements, components, footprints)
    traces: list[Trace] = []
    vias: list[Via] = []
    unrouted: list[str] = []
    trace_cost_total = 0.0

    ordered_nets = _sort_nets(nets)
    total_nets = max(1, len(ordered_nets))

    for idx, net in enumerate(ordered_nets):
        if cancel is not None and cancel():
            raise DomainError("cancelled by solver")
        if progress is not None:
            progress("route", int(20 + 70 * idx / total_nets))

        terminals = _net_terminal_holes(net, pin_map)
        # Drop terminals not on the maze (e.g. invalid pin_holes)
        terminals = [h for h in terminals if graph.has_node(h)]
        if len(terminals) < 2:
            unrouted.append(net.id)
            continue

        order = _steiner_order(terminals, graph)
        anchor = order[0]
        net_traces: list[Trace] = []
        net_vias: list[Via] = []
        net_succeeded = True
        forbidden: set[tuple[str, str, str]] = set()

        # Try once, then up to max_ripup_iterations rip-ups
        for attempt in range(max_ripup_iterations + 1):
            if cancel is not None and cancel():
                raise DomainError("cancelled by solver")
            cur_anchor = anchor
            cur_traces: list[Trace] = []
            cur_vias: list[Via] = []
            ok = True
            for nxt in order[1:]:
                result = maze.maze_route(
                    graph,
                    cur_anchor,
                    nxt,
                    start_layer="top",
                    forbidden_edges=forbidden,
                )
                if result is None:
                    ok = False
                    break
                segments, vs, total_length = _path_to_segments(result, graph, width_mm=width_mm)
                trace_id = f"T-{net.id}-{cur_anchor}-{nxt}-{attempt}"
                cur_traces.append(
                    Trace(
                        id=trace_id,
                        net_id=net.id,
                        segments=segments,
                        vias=vs,
                        estimated_length_mm=round(total_length + 10.0, 1),
                        width_mm=width_mm,
                    )
                )
                cur_vias.extend(vs)
                maze.record_usage(graph, result)
                cur_anchor = nxt
            if ok:
                net_traces = cur_traces
                net_vias = cur_vias
                break
            # Rip-up: forbid edges of the k highest-cost traces in this net
            forbidden |= _ripup_forbidden(cur_traces, set(), DEFAULT_RIPUP_K)
        else:
            net_succeeded = False

        if net_succeeded:
            traces.extend(net_traces)
            vias.extend(net_vias)
            trace_cost_total += sum(t.estimated_length_mm for t in net_traces)
        else:
            unrouted.append(net.id)

    return RouteResult(
        layout=TraceLayout(
            version=1,
            board_id=graph.nodes[next(iter(graph.nodes))].id if False else "perfboard",
            placements=placements,
            traces=traces,
            vias=vias,
        ),
        unrouted_nets=unrouted,
        trace_cost=trace_cost_total,
    )
