"""Lee-style BFS maze router on the perfboard hole graph.

Each hole is a node; nodes are 4-connected (cardinal neighbours in the lattice).
For single-sided boards the router operates on a single layer; for double-sided
it can switch layers by inserting a via at any visited hole at a fixed cost.

Cost model: every edge has a base length cost of 1 (one lattice step); congestion
penalties from already-placed traces are added on top via a per-edge ``usage``
count. The maze returns the lowest-cost path between any two nodes on the
requested layer.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from app.domain.models import Point, Via

CopperLayerStr = str  # "top" or "bottom"

# Cardinally-adjacent neighbour offsets (in hole-lattice coordinates).
_OFFSETS: tuple[tuple[int, int], ...] = ((-1, 0), (1, 0), (0, -1), (0, 1))


@dataclass(slots=True)
class HoleNode:
    """A single lattice hole mapped into router-space."""

    id: str
    row: int
    col: int
    point: Point


@dataclass(slots=True)
class MazeEdge:
    """One step in the lattice; ``usage`` is incremented by every trace that
    uses it (for congestion-driven cost penalty).
    """

    a: str  # hole id
    b: str  # hole id
    layer: CopperLayerStr
    length_mm: float
    usage: int = 0


@dataclass(slots=True)
class MazeGraph:
    """Hole graph built from a :class:`PerfboardModel`.

    Edges are 4-connected between adjacent holes on the same layer. For
    double-sided boards a virtual via edge connects (node, "top") ↔ (node, "bottom")
    at a fixed cost.
    """

    nodes: dict[str, HoleNode]
    edges_top: dict[str, list[MazeEdge]]
    edges_bottom: dict[str, list[MazeEdge]]
    double_sided: bool
    via_cost: float = 5.0

    def neighbour_edges(self, hole_id: str, layer: CopperLayerStr) -> list[MazeEdge]:
        if layer == "top":
            return self.edges_top.get(hole_id, [])
        return self.edges_bottom.get(hole_id, [])

    def has_node(self, hole_id: str) -> bool:
        return hole_id in self.nodes


def build_maze(rows: int, cols: int, pitch_mm: float, double_sided: bool) -> MazeGraph:
    """Construct a regular ``rows × cols`` hole maze at the given pitch.

    Hole ids are ``"{r}-{c}"`` (matching :func:`app.domain.boards.perfboard.build_perfboard`).
    Each cardinal pair of adjacent holes on the same row/column is joined by an edge
    of length ``pitch_mm``.
    """
    nodes: dict[str, HoleNode] = {}
    edges_top: dict[str, list[MazeEdge]] = {}
    edges_bottom: dict[str, list[MazeEdge]] = {}

    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            hid = f"{r}-{c}"
            nodes[hid] = HoleNode(
                id=hid,
                row=r,
                col=c,
                point=Point(x=float(c - 1) * pitch_mm, y=float(r - 1) * pitch_mm),
            )
            edges_top[hid] = []
            edges_bottom[hid] = []

    for hid, node in nodes.items():
        for dr, dc in _OFFSETS:
            nr, nc = node.row + dr, node.col + dc
            if not (1 <= nr <= rows and 1 <= nc <= cols):
                continue
            other_id = f"{nr}-{nc}"
            edges_top[hid].append(MazeEdge(a=hid, b=other_id, layer="top", length_mm=pitch_mm))
            edges_bottom[hid].append(MazeEdge(a=hid, b=other_id, layer="bottom", length_mm=pitch_mm))

    return MazeGraph(
        nodes=nodes,
        edges_top=edges_top,
        edges_bottom=edges_bottom,
        double_sided=double_sided,
    )


def _edge_cost(edge: MazeEdge, congestion_weight: float) -> float:
    """Base cost = edge length, plus a penalty proportional to ``usage``."""
    return edge.length_mm + congestion_weight * float(edge.usage)


@dataclass(slots=True)
class MazeResult:
    """Result of one maze route attempt.

    ``path`` is the ordered list of hole ids to traverse, ``layers`` is the
    layer for each consecutive pair (path[i] → path[i+1] runs on ``layers[i]``).
    The lengths of the two lists therefore differ by one: len(layers) == len(path) - 1.
    """

    path: list[str] = field(default_factory=list)
    layers: list[CopperLayerStr] = field(default_factory=list)
    cost: float = 0.0
    vias: list[Via] = field(default_factory=list)


def maze_route(
    graph: MazeGraph,
    start: str,
    end: str,
    *,
    start_layer: CopperLayerStr = "top",
    forbidden_edges: Iterable[tuple[str, str, CopperLayerStr]] = (),
    congestion_weight: float = 0.5,
) -> MazeResult | None:
    """Find the cheapest path from ``start`` to ``end`` on the given graph.

    A* with Manhattan heuristic on (row, col). For single-sided boards the
    router restricts itself to ``start_layer`` and never emits vias. For
    double-sided boards it may switch layers at any visited hole at
    ``graph.via_cost`` per switch.

    ``forbidden_edges`` is a set of (hole_a, hole_b, layer) triples the
    router must avoid — used by rip-up to keep already-failed traces from
    being immediately re-routed into the same dead-end region.
    """
    if not graph.has_node(start) or not graph.has_node(end):
        return None

    forbidden = {(a, b, l) for a, b, l in forbidden_edges}

    def heuristic(hid: str) -> float:
        node = graph.nodes[hid]
        target = graph.nodes[end]
        return (abs(node.row - target.row) + abs(node.col - target.col)) * (graph.nodes[start].point.x - target.point.x or 1.0) / 1.0

    # State: (hole_id, layer)
    start_state = (start, start_layer)
    came_from: dict[tuple[str, str], tuple[tuple[str, str], MazeEdge | None, bool]] = {}
    g_score: dict[tuple[str, str], float] = {start_state: 0.0}

    counter = 0
    queue: list[tuple[float, int, tuple[str, str]]] = []
    heapq.heappush(queue, (heuristic(start), counter, start_state))

    target_node = graph.nodes[end]
    target_row = target_node.row
    target_col = target_node.col

    def h(hid: str) -> float:
        n = graph.nodes[hid]
        return float(abs(n.row - target_row) + abs(n.col - target_col))

    while queue:
        _, _, current = heapq.heappop(queue)
        cur_hole, cur_layer = current

        if cur_hole == end:
            return _reconstruct(came_from, current, graph)

        # 4-neighbour edges on the current layer
        for edge in graph.neighbour_edges(cur_hole, cur_layer):
            if (edge.a, edge.b, edge.layer) in forbidden or (edge.b, edge.a, edge.layer) in forbidden:
                continue
            other = edge.b if edge.a == cur_hole else edge.a
            tentative = g_score[current] + _edge_cost(edge, congestion_weight)
            next_state = (other, cur_layer)
            if tentative < g_score.get(next_state, float("inf")):
                g_score[next_state] = tentative
                came_from[next_state] = (current, edge, False)
                counter += 1
                heapq.heappush(queue, (tentative + h(other), counter, next_state))

        # Optional layer switch via a via at the current hole
        if graph.double_sided and cur_layer == "top":
            other_layer = "bottom"
        elif graph.double_sided and cur_layer == "bottom":
            other_layer = "top"
        else:
            other_layer = None
        if other_layer is not None:
            tentative = g_score[current] + graph.via_cost
            next_state = (cur_hole, other_layer)
            if tentative < g_score.get(next_state, float("inf")):
                g_score[next_state] = tentative
                came_from[next_state] = (current, None, True)
                counter += 1
                heapq.heappush(queue, (tentative + h(cur_hole), counter, next_state))

    return None


def _reconstruct(
    came_from: dict[tuple[str, str], tuple[tuple[str, str], MazeEdge | None, bool]],
    end_state: tuple[str, str],
    graph: MazeGraph,
) -> MazeResult:
    """Walk the came_from map from end back to start and collect path + vias."""
    path: list[str] = []
    vias: list[Via] = []
    cur = end_state
    while True:
        path.append(cur[0])
        prev = came_from.get(cur)
        if prev is None:
            break
        prev_state, edge, is_via = prev
        if is_via:
            vias.append(Via(point=graph.nodes[cur[0]].point))
        cur = prev_state

    path.reverse()
    vias.reverse()

    # ``layers[i]`` is the layer used for the edge path[i] → path[i+1].
    # Layer at each step = layer of the destination state, except for the
    # very last step which has no outgoing edge — set it to match the prior.
    layers: list[CopperLayerStr] = []
    if len(path) >= 2:
        # Walk forward and recover the layer at each step from the came_from map.
        # Each entry ``came_from[(next_hole, layer)] = (prev_state, ...)`` tells us
        # the layer of the destination state; layer of the edge = that layer.
        # We need to invert: start at end_state and read the layer of each step
        # walking backwards via the state tuple. Simpler: use the layer at end
        # for the last edge; otherwise look at the destination state at each step.
        # For correctness we rebuild forward.
        states_by_hole: list[tuple[str, str]] = []
        # Recover the actual states used by walking back, then reversing.
        state_path: list[tuple[str, str]] = []
        c = end_state
        while True:
            state_path.append(c)
            p = came_from.get(c)
            if p is None:
                break
            c = p[0]
        state_path.reverse()
        # state_path[i] is the state before the i-th edge; state_path[i+1] is after.
        for i in range(len(state_path) - 1):
            layers.append(state_path[i + 1][1])

    cost = float(len(layers))
    return MazeResult(path=path, layers=layers, cost=cost, vias=vias)


def record_usage(graph: MazeGraph, result: MazeResult) -> None:
    """Increment ``usage`` on every edge the route used, for congestion cost."""
    for i in range(len(result.layers)):
        a = result.path[i]
        b = result.path[i + 1]
        layer = result.layers[i]
        bucket = graph.edges_top if layer == "top" else graph.edges_bottom
        for edge in bucket.get(a, []):
            if edge.b == b or edge.a == b:
                edge.usage += 1
