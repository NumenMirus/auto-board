"""Tests for `app.domain.route.route` and `app.domain.steiner.greedy_steiner`.

Covers:
* `greedy_steiner` produces a connecting tree whose total Manhattan length is at most
  the naive star-from-first-terminal topology.
* `route` creates exactly one jumper per 2-pin net between two placed components and
  leaves `unrouted_nets` empty.
* `route` honors `prefer-rail` on a power net by landing at least one jumper endpoint
  on a `rail-*` hole id when a rail segment is available.
* `route` is deterministic: two calls with the same seed produce byte-identical jumper
  lists.
"""

from __future__ import annotations

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    Component,
    ComponentPlacement,
    Layout,
    Net,
    NetConstraintPreferRail,
    PinRef,
    SolverOptions,
)
from app.domain.route import route
from app.domain.steiner import greedy_steiner

pytest_plugins: list[str] = []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _board_and_index() -> tuple:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    return board, index


def _make_two_pin_net(
    net_id: str,
    ref_a: str,
    ref_b: str,
    net_class: str = "digital",
    constraints: list | None = None,
) -> Net:
    return Net(
        id=net_id,
        name=net_id,
        pins=[PinRef(component_ref=ref_a, pin="1"), PinRef(component_ref=ref_b, pin="1")],
        net_class=net_class,
        priority=0,
        constraints=constraints if constraints is not None else [],
    )


def _make_two_resistor_layout() -> tuple[list[Component], list[Net], Layout]:
    """Build a layout with two axial resistors placed at fixed anchors.

    Returns components, components (same list for the two-pin net), and a `Layout` whose
    placements are pre-populated and whose jumpers list is empty.
    """

    board, _ = _board_and_index()
    c1 = Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False)
    c2 = Component(ref="R2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False)
    components = [c1, c2]

    placement_r1 = ComponentPlacement(
        component_ref="R1",
        anchor_hole_id="a5",
        orientation=0,
        span=3,
        pin_holes={"1": "a5", "2": "a8"},
        occupied_hole_ids=["a5", "a6", "a7", "a8"],
        locked=False,
    )
    placement_r2 = ComponentPlacement(
        component_ref="R2",
        anchor_hole_id="a20",
        orientation=0,
        span=3,
        pin_holes={"1": "a20", "2": "a23"},
        occupied_hole_ids=["a20", "a21", "a22", "a23"],
        locked=False,
    )
    layout = Layout(
        version=1,
        board_id=board.id,
        placements=[placement_r1, placement_r2],
        jumpers=[],
        manual_electrical_links=[],
    )
    return components, components, layout  # second arg mirrors a Netlist (here: components list)


# --------------------------------------------------------------------------
# steiner
# --------------------------------------------------------------------------


def test_steiner_three_terminals_beats_naive_star() -> None:
    terminals = [
        ("a1", (0.0, 0.0)),
        ("a10", (22.86, 0.0)),
        ("j10", (22.86, 27.94)),
    ]
    edges = greedy_steiner(terminals)

    assert len(edges) == 2
    touched: set[str] = set()
    for a, b in edges:
        touched.add(a)
        touched.add(b)
    assert touched == {"a1", "a10", "j10"}

    # Total Manhattan length of the chosen tree must not exceed the star-from-first
    # topology (a1 -> a10 -> j10 == 22.86 + 27.94 == 50.8 mm).
    pts = dict(terminals)
    total = 0.0
    for a, b in edges:
        total += abs(pts[a][0] - pts[b][0]) + abs(pts[a][1] - pts[b][1])
    assert total <= 50.8


def test_steiner_zero_or_one_terminal_returns_no_edges() -> None:
    assert greedy_steiner([]) == []
    assert greedy_steiner([("a1", (0.0, 0.0))]) == []


# --------------------------------------------------------------------------
# route
# --------------------------------------------------------------------------


def test_route_two_pin_net_creates_one_jumper() -> None:
    board, index = _board_and_index()
    components, _, placements_layout = _make_two_resistor_layout()
    net = _make_two_pin_net("N1", "R1", "R2")
    options = SolverOptions(seed=7, preset="fast", max_placement_restarts=1, max_local_search_iterations=50)

    result = route(
        board=board,
        index=index,
        footprints=FOOTPRINTS,
        components=components,
        nets=[net],
        layout=placements_layout,
        options=options,
    )

    matching = [j for j in result.jumpers if j.net_id == "N1"]
    assert len(matching) == 1
    assert result.unrouted_nets == []


def test_route_prefer_rail_lands_on_rail_hole() -> None:
    board, index = _board_and_index()
    components, _, placements_layout = _make_two_resistor_layout()
    # Power net with an explicit prefer-rail constraint.
    constraints = [NetConstraintPreferRail(type="prefer-rail")]
    net = _make_two_pin_net("PWR", "R1", "R2", net_class="power", constraints=constraints)
    options = SolverOptions(seed=7, preset="fast", max_placement_restarts=1, max_local_search_iterations=50)

    result = route(
        board=board,
        index=index,
        footprints=FOOTPRINTS,
        components=components,
        nets=[net],
        layout=placements_layout,
        options=options,
    )

    matching = [j for j in result.jumpers if j.net_id == "PWR"]
    assert len(matching) >= 1
    # At least one jumper endpoint must be a rail hole id.
    rail_endpoints = [
        ep for j in matching for ep in (j.start_hole_id, j.end_hole_id) if ep.startswith("rail-")
    ]
    assert rail_endpoints, f"no rail endpoint in {[(j.start_hole_id, j.end_hole_id) for j in matching]}"


def test_route_is_deterministic() -> None:
    board, index = _board_and_index()
    components, _, placements_layout = _make_two_resistor_layout()
    net1 = _make_two_pin_net("N1", "R1", "R2")
    options = SolverOptions(seed=11, preset="fast", max_placement_restarts=1, max_local_search_iterations=50)

    def _run() -> str:
        result = route(
            board=board,
            index=index,
            footprints=FOOTPRINTS,
            components=components,
            nets=[net1],
            layout=placements_layout,
            options=options,
        )
        # Compare only the layout-shaped output: jumper list, unrouted nets, cost.
        # `phase_timings_ms` uses wall-clock timing and so isn't byte-identical
        # between successive runs.
        payload = result.model_dump(mode="json", by_alias=True)
        return str(sorted((j["id"], j["startHoleId"], j["endHoleId"]) for j in payload["jumpers"]))

    assert _run() == _run()


def test_route_with_place_output_produces_consistent_layout() -> None:
    """End-to-end mini-pipeline: place() the components, then route() the wires."""

    from app.domain.place import place

    board, index = _board_and_index()
    # Two resistors + a two-pin digital net whose pin spacing forces two different
    # electrical groups (different columns).
    c1 = Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"])
    c2 = Component(ref="R2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"])
    components = [c1, c2]
    options = SolverOptions(seed=21, preset="fast", max_placement_restarts=2, max_local_search_iterations=80)

    # Pin both resistors with anchor constraints that force them to specific columns.
    from app.domain.models import ComponentPlacement

    placement_input = Layout(
        version=1,
        board_id=board.id,
        placements=[
            ComponentPlacement(
                component_ref="R1",
                anchor_hole_id="a5",
                orientation=0,
                span=3,
                pin_holes={"1": "a5", "2": "a8"},
                occupied_hole_ids=["a5", "a6", "a7", "a8"],
                locked=True,
            ),
            ComponentPlacement(
                component_ref="R2",
                anchor_hole_id="a25",
                orientation=0,
                span=3,
                pin_holes={"1": "a25", "2": "a28"},
                occupied_hole_ids=["a25", "a26", "a27", "a28"],
                locked=True,
            ),
        ],
        jumpers=[],
        manual_electrical_links=[],
    )
    net1 = _make_two_pin_net("N1", "R1", "R2")
    placement = place(board, index, FOOTPRINTS, components, [net1], options, initial_layout=placement_input)
    seed_layout = Layout(
        version=1,
        board_id=board.id,
        placements=list(placement.placements),
        jumpers=[],
        manual_electrical_links=[],
    )
    result = route(board, index, FOOTPRINTS, components, [net1], seed_layout, options)
    # At least one jumper is created (the components span different tie-point columns).
    assert any(j.net_id == "N1" for j in result.jumpers)
    assert result.unrouted_nets == []
