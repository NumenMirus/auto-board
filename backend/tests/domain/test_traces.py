"""Tests for `app.domain.traces` — maze router, route driver, validator, score."""

from __future__ import annotations

import pytest

from app.domain.boards.registry import get_board_model
from app.domain.diagnostics import DIAGNOSTIC_CATALOG
from app.domain.models import (
    Component,
    ComponentPlacement,
    Net,
    PerfboardModel,
    PinRef,
    Point,
    SolverOptions,
    Trace,
    TraceLayout,
    TraceSegment,
    Via,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.traces import maze
from app.domain.traces.cost import trace_cost
from app.domain.traces.route import route as route_traces
from app.domain.traces.score import score_layout
from app.domain.traces.solve import place_only as place_only_traces
from app.domain.traces.solve import route_only as route_only_traces
from app.domain.traces.solve import solve as solve_traces
from app.domain.traces.validate import validate_layout

pytest_plugins: list[str] = []


def _placement(ref: str, anchor: str, pin_holes: dict[str, str]) -> ComponentPlacement:
    return ComponentPlacement(
        component_ref=ref,
        anchor_hole_id=anchor,
        orientation=0,
        span=None,
        pin_holes=pin_holes,
        occupied_hole_ids=list(pin_holes.values()),
        locked=False,
    )


def test_maze_graph_node_and_edge_counts() -> None:
    g = maze.build_maze(rows=3, cols=3, pitch_mm=2.54, double_sided=False)
    assert len(g.nodes) == 9
    # corner 1-1 has 2 neighbours; edge 1-2 has 3 neighbours; centre 2-2 has 4
    assert len(g.edges_top["1-1"]) == 2
    assert len(g.edges_top["1-2"]) == 3
    assert len(g.edges_top["2-2"]) == 4
    # Single-sided boards must not let the router switch layers
    assert not g.double_sided


def test_maze_route_straight_line_single_sided() -> None:
    g = maze.build_maze(rows=5, cols=5, pitch_mm=2.54, double_sided=False)
    r = maze.maze_route(g, "1-1", "1-5")
    assert r is not None
    assert r.path[0] == "1-1" and r.path[-1] == "1-5"
    assert len(r.path) == 5  # 1-1, 1-2, 1-3, 1-4, 1-5
    assert r.vias == []


def test_maze_route_double_sided_avoids_unnecessary_vias() -> None:
    g = maze.build_maze(rows=5, cols=5, pitch_mm=2.54, double_sided=True)
    r = maze.maze_route(g, "1-1", "1-5")
    # A direct horizontal run is cheaper than going around and through a via
    assert r is not None
    assert r.vias == []


def test_maze_route_double_sided_with_blocked_edges_uses_via() -> None:
    g = maze.build_maze(rows=3, cols=3, pitch_mm=2.54, double_sided=True)
    # Block the direct top neighbours of 1-1 so the maze must drop to bottom via
    # a via at 1-1 itself, traverse bottom to a node that still has a top edge,
    # then come back up — net effect: at least one via on the route.
    forbidden = {
        ("1-1", "1-2", "top"),
        ("1-1", "2-1", "top"),
    }
    r = maze.maze_route(g, "1-1", "1-3", forbidden_edges=forbidden)
    assert r is not None
    assert len(r.vias) >= 1


def test_maze_route_unknown_node_returns_none() -> None:
    g = maze.build_maze(rows=3, cols=3, pitch_mm=2.54, double_sided=False)
    assert maze.maze_route(g, "1-1", "99-99") is None
    assert maze.maze_route(g, "99-99", "1-1") is None


def test_route_driver_produces_trace_for_two_terminal_net() -> None:
    g = maze.build_maze(rows=10, cols=10, pitch_mm=2.54, double_sided=True)
    placements = [_placement("R1", "2-2", {"1": "2-2", "2": "2-5"})]
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[])
    ]
    nets = [
        Net(
            id="N1",
            name="SIG",
            pins=[PinRef(component_ref="R1", pin="1"), PinRef(component_ref="R1", pin="2")],
            net_class="digital",
            priority=5,
            constraints=[],
        )
    ]
    res = route_traces(
        board_id="test-board",
        placements=placements,
        components=components,
        footprints=PERFBOARD_FOOTPRINTS,
        nets=nets,
        graph=g,
    )
    assert res.unrouted_nets == []
    assert len(res.layout.traces) == 1
    assert res.layout.traces[0].net_id == "N1"
    # 3 segments (2-2 → 2-3 → 2-4 → 2-5)
    assert len(res.layout.traces[0].segments) == 3


def test_route_driver_unrouted_terminal_for_single_pin_net() -> None:
    """A net with only one valid terminal cannot be routed — it has fewer
    than 2 holes in the maze, so it shows up in ``unrouted_nets``.
    """
    g = maze.build_maze(rows=4, cols=4, pitch_mm=2.54, double_sided=False)
    placements = [_placement("R1", "1-1", {"1": "1-1"})]  # only one pin placed
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[])
    ]
    nets = [
        Net(
            id="N1",
            name="SIG",
            pins=[PinRef(component_ref="R1", pin="1"), PinRef(component_ref="R1", pin="2")],
            net_class="digital",
            priority=5,
            constraints=[],
        )
    ]
    res = route_traces(
        board_id="test-board",
        placements=placements,
        components=components,
        footprints=PERFBOARD_FOOTPRINTS,
        nets=nets,
        graph=g,
    )
    assert "N1" in res.unrouted_nets


def test_route_driver_orders_harder_higher_priority_nets_first() -> None:
    g = maze.build_maze(rows=8, cols=8, pitch_mm=2.54, double_sided=True)
    placements = [
        _placement("A1", "1-1", {"1": "1-1", "2": "1-2"}),
        _placement("A2", "1-7", {"1": "1-7", "2": "1-8"}),
        _placement("B1", "6-1", {"1": "6-1", "2": "6-2"}),
        _placement("B2", "6-7", {"1": "6-7", "2": "6-8"}),
    ]
    components = [
        Component(ref="A1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="A2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="B1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="B2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
    ]
    nets = [
        Net(
            id="LOW",
            name="LOW",
            pins=[PinRef(component_ref="A1", pin="1"), PinRef(component_ref="A2", pin="1")],
            net_class="low-priority",
            priority=1,
        ),
        Net(
            id="HIGH",
            name="HIGH",
            pins=[PinRef(component_ref="B1", pin="1"), PinRef(component_ref="B2", pin="1")],
            net_class="ground",
            priority=100,
        ),
    ]
    res = route_traces(
        board_id="test-board",
        placements=placements,
        components=components,
        footprints=PERFBOARD_FOOTPRINTS,
        nets=nets,
        graph=g,
    )
    assert res.layout.traces[0].net_id == "HIGH"


def test_route_driver_reuses_existing_tree_for_multi_terminal_net() -> None:
    g = maze.build_maze(rows=6, cols=6, pitch_mm=2.54, double_sided=True)
    placements = [
        _placement("R1", "1-1", {"1": "1-1", "2": "1-2"}),
        _placement("R2", "1-5", {"1": "1-5", "2": "1-6"}),
        _placement("R3", "3-3", {"1": "3-3", "2": "3-4"}),
    ]
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="R2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="R3", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
    ]
    nets = [
        Net(
            id="BUS",
            name="BUS",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R2", pin="1"),
                PinRef(component_ref="R3", pin="1"),
            ],
            net_class="digital",
            priority=50,
        )
    ]
    res = route_traces(
        board_id="test-board",
        placements=placements,
        components=components,
        footprints=PERFBOARD_FOOTPRINTS,
        nets=nets,
        graph=g,
    )
    total_length = sum(t.estimated_length_mm for t in res.layout.traces)
    assert len(res.layout.traces) == 2
    assert total_length < 40.0


def test_failed_partial_attempt_does_not_leave_congestion_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    g = maze.build_maze(rows=4, cols=4, pitch_mm=2.54, double_sided=False)
    placements = [
        _placement("R1", "1-1", {"1": "1-1", "2": "1-2"}),
        _placement("R2", "1-4", {"1": "1-4", "2": "1-3"}),
        _placement("R3", "4-4", {"1": "4-4", "2": "4-3"}),
    ]
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="R2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="R3", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
    ]
    nets = [
        Net(
            id="BUS",
            name="BUS",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R2", pin="1"),
                PinRef(component_ref="R3", pin="1"),
            ],
            net_class="digital",
            priority=10,
        )
    ]
    calls = {"count": 0}

    def fake_maze_route(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] % 2 == 1:
            return maze.MazeResult(path=["1-1", "1-4"], layers=["top"], cost=1.0, vias=[])
        return None

    monkeypatch.setattr(maze, "maze_route", fake_maze_route)
    res = route_traces(
        board_id="test-board",
        placements=placements,
        components=components,
        footprints=PERFBOARD_FOOTPRINTS,
        nets=nets,
        graph=g,
        max_ripup_iterations=1,
    )
    assert res.unrouted_nets == ["BUS"]
    assert all(edge.usage == 0 for edges in g.edges_top.values() for edge in edges)
    assert all(edge.usage == 0 for edges in g.edges_bottom.values() for edge in edges)


def test_trace_cost_length_only_with_default_weights() -> None:
    t = Trace(
        id="T1",
        net_id="N1",
        segments=[],
        estimated_length_mm=12.5,
        width_mm=0.4,
        vias=[Via(point=Point(x=0.0, y=0.0))],
    )
    assert trace_cost(t) == pytest.approx(12.5 + 5.0)


def test_score_layout_computes_jumper_count_and_total_length() -> None:
    placements = [_placement("R1", "2-2", {"1": "2-2", "2": "2-5"})]
    layout = TraceLayout(
        board_id="strip-20x30-double",
        placements=placements,
        traces=[
            Trace(
                id="T1",
                net_id="N1",
                segments=[TraceSegment(start=Point(x=2.54, y=2.54), end=Point(x=7.62, y=2.54), layer="top")],
                estimated_length_mm=10.0,
            ),
        ],
    )
    score = score_layout(placements=placements, components_placed=1, components_total=1, layout=layout)
    assert score.jumper_count == 1
    assert score.total_jumper_length_mm == pytest.approx(10.0)
    assert score.routing_cost == pytest.approx(10.0)


def test_validate_layout_emits_unrouted_terminal() -> None:
    board = get_board_model("strip-20x30-double")
    assert isinstance(board, PerfboardModel)
    placements = [_placement("R1", "2-2", {"1": "2-2", "2": "2-5"})]
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[])
    ]
    nets = [
        Net(
            id="N1",
            name="SIG",
            pins=[PinRef(component_ref="R1", pin="1"), PinRef(component_ref="R1", pin="2")],
            net_class="digital",
            priority=5,
            constraints=[],
        )
    ]
    # No traces routed → validator must emit UNROUTED_TERMINAL
    layout = TraceLayout(board_id=board.id, placements=placements)
    result = validate_layout(board, PERFBOARD_FOOTPRINTS, components, nets, layout)
    codes = {d.code for d in result.diagnostics}
    assert "UNROUTED_TERMINAL" in codes


def test_validate_layout_no_diagnostics_on_clean_layout() -> None:
    board = get_board_model("strip-20x30-double")
    placements = [_placement("R1", "2-2", {"1": "2-2", "2": "2-5"})]
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[])
    ]
    nets = [
        Net(
            id="N1",
            name="SIG",
            pins=[PinRef(component_ref="R1", pin="1"), PinRef(component_ref="R1", pin="2")],
            net_class="digital",
            priority=5,
            constraints=[],
        )
    ]
    layout = TraceLayout(
        board_id=board.id,
        placements=placements,
        traces=[
            Trace(
                id="T1",
                net_id="N1",
                segments=[TraceSegment(start=Point(x=2.54, y=2.54), end=Point(x=7.62, y=2.54), layer="top")],
                estimated_length_mm=10.0,
            ),
        ],
    )
    result = validate_layout(board, PERFBOARD_FOOTPRINTS, components, nets, layout)
    assert result.diagnostics == []


def test_diagnostic_catalog_has_new_codes() -> None:
    assert "UNROUTED_TERMINAL" in DIAGNOSTIC_CATALOG
    assert "TRACE_CROSSING_UNAVOIDABLE" in DIAGNOSTIC_CATALOG


def test_solve_pipeline_end_to_end() -> None:
    board = get_board_model("strip-20x30-double")
    placements = [
        _placement("R1", "2-2", {"1": "2-2", "2": "2-5"}),
        _placement("R2", "4-2", {"1": "4-2", "2": "4-5"}),
    ]
    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
        Component(ref="R2", value="4k7", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
    ]
    nets = [
        Net(
            id="GND",
            name="GND",
            pins=[PinRef(component_ref="R1", pin="1"), PinRef(component_ref="R2", pin="2")],
            net_class="ground",
            priority=10,
            constraints=[],
        ),
        Net(
            id="SIG",
            name="SIG",
            pins=[PinRef(component_ref="R1", pin="2"), PinRef(component_ref="R2", pin="1")],
            net_class="digital",
            priority=5,
            constraints=[],
        ),
    ]
    initial_layout = TraceLayout(board_id=board.id, placements=placements)
    res = solve_traces(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=components,
        nets=nets,
        options=SolverOptions(),
        initial_layout=initial_layout,
    )
    assert res.score.error_count == 0
    assert len(res.layout.traces) == 2


def test_solve_places_components_from_empty_layout() -> None:
    """Regression: a schematic-derived perfboard project starts with zero
    placements (ports never appear in `net.pins` — see `netlist.ts`
    `buildNet`). `trace-solve` must place every component before routing,
    not just pass the (empty) input layout through to the router unchanged.
    """
    board = get_board_model("strip-20x30-double")
    components = [
        Component(ref="D1", value=None, footprint_id="LED-2P", pins=["1", "2"]),
        Component(ref="U1", value=None, footprint_id="DIP-14", pins=[str(i) for i in range(1, 15)]),
    ]
    nets = [
        # A ground port wired to one component pin: single-pin net, exactly
        # like the reported project's "net-gnd".
        Net(id="net-gnd", name="GND", pins=[PinRef(component_ref="U1", pin="1")], net_class="ground", priority=0),
        Net(
            id="net-n-1",
            name="N$1",
            pins=[PinRef(component_ref="D1", pin="2"), PinRef(component_ref="U1", pin="13")],
            net_class="digital",
            priority=0,
        ),
        Net(
            id="net-n-2",
            name="N$2",
            pins=[PinRef(component_ref="D1", pin="1"), PinRef(component_ref="U1", pin="14")],
            net_class="digital",
            priority=0,
        ),
    ]
    res = solve_traces(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=components,
        nets=nets,
        options=SolverOptions(),
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    assert res.score.components_placed == 2
    assert {p.component_ref for p in res.layout.placements} == {"D1", "U1"}
    # net-n-1 / net-n-2 are both 2-pin nets and route successfully. net-gnd has
    # only one physical pin — a perfboard has no rails to land it on (unlike a
    # breadboard), so it is genuinely unroutable and UNROUTED_TERMINAL is the
    # correct diagnostic, not a defect.
    assert len(res.layout.traces) == 2
    codes = {d.code for d in res.diagnostics}
    assert "UNROUTED_TERMINAL" in codes
    assert res.score.error_count == 1


def test_place_only_places_every_component_and_adds_no_traces() -> None:
    """`trace-place` places every unlocked component without routing — the
    perfboard counterpart of the breadboard `place` op."""
    board = get_board_model("strip-20x30-double")
    components = [
        Component(ref="D1", value=None, footprint_id="LED-2P", pins=["1", "2"]),
        Component(ref="U1", value=None, footprint_id="DIP-14", pins=[str(i) for i in range(1, 15)]),
    ]
    nets = [
        Net(id="net-gnd", name="GND", pins=[PinRef(component_ref="U1", pin="1")], net_class="ground", priority=0),
        Net(
            id="net-n-1",
            name="N$1",
            pins=[PinRef(component_ref="D1", pin="2"), PinRef(component_ref="U1", pin="13")],
            net_class="digital",
            priority=0,
        ),
    ]
    res = place_only_traces(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=components,
        nets=nets,
        options=SolverOptions(),
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    assert len(res.layout.placements) == len(components)
    assert {p.component_ref for p in res.layout.placements} == {"D1", "U1"}
    assert res.layout.traces == []


def test_route_only_does_not_place_anything() -> None:
    """`trace-route` stays route-only: an empty input layout stays empty."""
    board = get_board_model("strip-20x30-double")
    components = [Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"])]
    nets: list[Net] = []
    res = route_only_traces(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=components,
        nets=nets,
        options=SolverOptions(),
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    assert res.layout.placements == []
    assert res.score.components_placed == 0
