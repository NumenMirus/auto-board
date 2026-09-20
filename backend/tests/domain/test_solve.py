"""Tests for `app.domain.solve.solve` (and the deterministic-pipeline invariant)."""

from __future__ import annotations

import pytest

from app.domain.boards.half400 import build_half400
from app.domain.errors import SolverCancelled
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    DEFAULT_PLACEMENT_WEIGHTS,
    DEFAULT_ROUTING_WEIGHTS,
    Component,
    Layout,
    Net,
    PinRef,
    SolverOptions,
)
from app.domain.solve import solve

pytest_plugins: list[str] = []


def _board_and_index() -> tuple:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    return board, index


def _make_mini_netlist() -> tuple[list[Component], list[Net], Layout]:
    """Build a tiny netlist + a locked initial layout so solve() succeeds end-to-end.

    Layout has 3 axial resistors placed at well-separated columns so every net spans
    two distinct tie-point groups and no two nets share a column. This avoids the
    router accidentally shorting via overlapping column groups.
    """

    from app.domain.boards.half400 import build_half400
    from app.domain.models import ComponentPlacement, Layout

    board = build_half400(split_rails=True)

    components = [
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="R2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="R3", value="10k", footprint_id="AXIAL-R", pins=["1", "2"]),
    ]
    nets = [
        Net(
            id="N1",
            name="N1",
            pins=[
                PinRef(component_ref="R1", pin="2"),
                PinRef(component_ref="R2", pin="1"),
            ],
            net_class="digital",
            priority=1,
        ),
        Net(
            id="N2",
            name="N2",
            pins=[
                PinRef(component_ref="R2", pin="2"),
                PinRef(component_ref="R3", pin="1"),
            ],
            net_class="digital",
            priority=1,
        ),
    ]
    initial_layout = Layout(
        version=1,
        board_id=board.id,
        placements=[
            ComponentPlacement(
                component_ref="R1",
                anchor_hole_id="a1",
                orientation=0,
                span=3,
                pin_holes={"1": "a1", "2": "a4"},
                occupied_hole_ids=["a1", "a2", "a3", "a4"],
                locked=True,
            ),
            ComponentPlacement(
                component_ref="R2",
                anchor_hole_id="a10",
                orientation=0,
                span=3,
                pin_holes={"1": "a10", "2": "a13"},
                occupied_hole_ids=["a10", "a11", "a12", "a13"],
                locked=True,
            ),
            ComponentPlacement(
                component_ref="R3",
                anchor_hole_id="a20",
                orientation=0,
                span=3,
                pin_holes={"1": "a20", "2": "a23"},
                occupied_hole_ids=["a20", "a21", "a22", "a23"],
                locked=True,
            ),
        ],
        jumpers=[],
        manual_electrical_links=[],
    )
    return components, nets, initial_layout


def test_solve_mini_netlist_completes_all_nets() -> None:
    board, index = _board_and_index()
    components, nets, initial_layout = _make_mini_netlist()
    options = SolverOptions(
        seed=7,
        placement_weights=dict(DEFAULT_PLACEMENT_WEIGHTS),
        routing_weights=dict(DEFAULT_ROUTING_WEIGHTS),
        preset="fast",
        max_placement_restarts=1,
        max_local_search_iterations=50,
        max_ripup_iterations=3,
    )

    result = solve(
        board=board,
        index=index,
        footprints=FOOTPRINTS,
        components=components,
        nets=nets,
        options=options,
        initial_layout=initial_layout,
    )

    assert result.score.error_count == 0, [d.message for d in result.diagnostics if d.severity == "error"]
    assert result.score.nets_completed == result.score.nets_total


def test_solve_is_byte_deterministic() -> None:
    board, index = _board_and_index()
    components, nets, initial_layout = _make_mini_netlist()
    options = SolverOptions(
        seed=42,
        placement_weights=dict(DEFAULT_PLACEMENT_WEIGHTS),
        routing_weights=dict(DEFAULT_ROUTING_WEIGHTS),
        preset="fast",
        max_placement_restarts=1,
        max_local_search_iterations=50,
        max_ripup_iterations=3,
    )

    a = solve(board, index, FOOTPRINTS, components, nets, options, initial_layout=initial_layout)
    b = solve(board, index, FOOTPRINTS, components, nets, options, initial_layout=initial_layout)
    assert a.layout.model_dump_json() == b.layout.model_dump_json()


def test_solve_raises_solver_cancelled_when_cancel_returns_true() -> None:
    board, index = _board_and_index()
    components, nets, initial_layout = _make_mini_netlist()
    options = SolverOptions(
        seed=7,
        placement_weights=dict(DEFAULT_PLACEMENT_WEIGHTS),
        routing_weights=dict(DEFAULT_ROUTING_WEIGHTS),
        preset="fast",
        max_placement_restarts=1,
        max_local_search_iterations=50,
        max_ripup_iterations=3,
    )

    def _always_cancel() -> bool:
        return True

    with pytest.raises(SolverCancelled):
        solve(
            board=board,
            index=index,
            footprints=FOOTPRINTS,
            components=components,
            nets=nets,
            options=options,
            initial_layout=initial_layout,
            cancel=_always_cancel,
        )
