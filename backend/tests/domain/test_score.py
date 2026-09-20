"""Tests for `app.domain.score.score_layout`."""

from __future__ import annotations

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    Component,
    ComponentPlacement,
    Diagnostic,
    Jumper,
    JumperPath,
    Layout,
    Net,
    PinRef,
    Point,
)
from app.domain.score import score_layout

pytest_plugins: list[str] = []


def _board_and_index() -> tuple:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    return board, index


def _make_layout() -> Layout:
    board, _ = _board_and_index()
    placement = ComponentPlacement(
        component_ref="R1",
        anchor_hole_id="a5",
        orientation=0,
        span=3,
        pin_holes={"1": "a5", "2": "a8"},
        occupied_hole_ids=["a5", "a6", "a7", "a8"],
        locked=False,
    )
    return Layout(
        version=1,
        board_id=board.id,
        placements=[placement],
        jumpers=[],
        manual_electrical_links=[],
    )


def _make_jumper(
    jumper_id: str,
    net_id: str,
    a: str,
    b: str,
    length_mm: float = 12.7,
) -> Jumper:
    return Jumper(
        id=jumper_id,
        net_id=net_id,
        start_hole_id=a,
        end_hole_id=b,
        path=JumperPath(points=[Point(x=0, y=0), Point(x=length_mm, y=0)], layer="lower"),
        color=None,
        estimated_length_mm=length_mm,
        locked=False,
    )


def test_score_zero_diagnostics_yields_zero_errors() -> None:
    board, index = _board_and_index()
    components = [Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"])]
    nets = [
        Net(
            id="N1",
            name="N1",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R1", pin="2"),
            ],
            net_class="digital",
            priority=0,
        )
    ]
    layout = _make_layout()
    score = score_layout(
        board=board,
        index=index,
        footprints=FOOTPRINTS,
        components=components,
        nets=nets,
        layout=layout,
        diagnostics=[],
        placement_cost=42.0,
        routing_cost=13.0,
    )
    assert score.error_count == 0
    assert score.warning_count == 0
    assert score.placement_cost == 42.0
    assert score.routing_cost == 13.0
    assert score.total == 55.0


def test_score_net_open_diagnostic_drops_net_from_completed() -> None:
    board, index = _board_and_index()
    components = [Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"])]
    nets = [
        Net(
            id="N1",
            name="N1",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R1", pin="2"),
            ],
            net_class="digital",
            priority=0,
        ),
        Net(
            id="N2",
            name="N2",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R1", pin="2"),
            ],
            net_class="digital",
            priority=0,
        ),
    ]
    layout = _make_layout()
    diagnostics = [
        Diagnostic(
            id="NET_OPEN:N1",
            severity="error",
            code="NET_OPEN",
            message="Net N1 is not fully connected",
            related_net_ids=["N1"],
        )
    ]
    score = score_layout(
        board=board,
        index=index,
        footprints=FOOTPRINTS,
        components=components,
        nets=nets,
        layout=layout,
        diagnostics=diagnostics,
        placement_cost=0.0,
        routing_cost=0.0,
    )
    assert score.nets_total == 2
    assert score.nets_completed == 1  # only N2 is completed
    assert score.error_count == 1


def test_score_counts_jumper_length_and_crossings() -> None:
    board, index = _board_and_index()
    components = [Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"])]
    nets = [
        Net(
            id="N1",
            name="N1",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R1", pin="2"),
            ],
            net_class="digital",
            priority=0,
        )
    ]
    layout = _make_layout()
    # Two jumpers whose paths cross at the origin (one horizontal, one vertical).
    layout.jumpers = [
        _make_jumper("j1", "N1", "a1", "b1", length_mm=12.7),
        _make_jumper("j2", "N1", "a5", "a10", length_mm=12.7),
    ]
    # Override the paths to actually cross at (x=12.7, y=0).
    layout.jumpers[0].path = JumperPath(points=[Point(x=0, y=0), Point(x=20, y=0)], layer="lower")
    layout.jumpers[1].path = JumperPath(points=[Point(x=10, y=-5), Point(x=10, y=5)], layer="lower")

    score = score_layout(
        board=board,
        index=index,
        footprints=FOOTPRINTS,
        components=components,
        nets=nets,
        layout=layout,
        diagnostics=[],
        placement_cost=0.0,
        routing_cost=0.0,
    )
    assert score.jumper_count == 2
    assert score.crossings == 1
    assert score.total_jumper_length_mm == round(12.7 + 12.7, 1)
