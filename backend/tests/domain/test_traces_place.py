"""Tests for :mod:`app.domain.traces.place` — the perfboard placer.

Mirrors `backend/tests/domain/test_place.py`'s coverage for the breadboard
placer: zero unplaced + zero hole overlaps on a small fixture, determinism,
locked placements surviving untouched, and single-component placement. Also
covers the perfboard-specific bit: pose generation stays inside the plain
`rows x cols` grid (no center gap / rails to straddle).
"""

from __future__ import annotations

import pytest

from app.domain.boards.perfboard import build_perfboard
from app.domain.models import (
    DEFAULT_PLACEMENT_WEIGHTS,
    Component,
    ComponentPlacement,
    Net,
    PinRef,
    SolverOptions,
    TraceLayout,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.traces.place import place

pytest_plugins: list[str] = []

_ROWS = 12
_COLS = 16


def _board():
    return build_perfboard(rows=_ROWS, cols=_COLS, layers=2, id="test-strip")


def _small_fixture() -> tuple[list[Component], list[Net]]:
    """One DIP-8, two AXIAL-R, one LED-2P — same shape as the breadboard
    placer's small fixture, sized to fit a 12x16 perfboard comfortably."""
    components = [
        Component(ref="U1", value="74HC04", footprint_id="DIP-8", pins=[str(i) for i in range(1, 9)]),
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="R2", value="4.7k", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="D1", value="LED", footprint_id="LED-2P", pins=["1", "2"]),
    ]
    nets = [
        Net(
            id="net-a",
            name="A",
            pins=[PinRef(component_ref="U1", pin="1"), PinRef(component_ref="R1", pin="1")],
            net_class="digital",
            priority=0,
        ),
        Net(
            id="net-b",
            name="B",
            pins=[PinRef(component_ref="R2", pin="2"), PinRef(component_ref="D1", pin="1")],
            net_class="digital",
            priority=0,
        ),
    ]
    return components, nets


def _options(seed: int = 42) -> SolverOptions:
    return SolverOptions(seed=seed, placement_weights=dict(DEFAULT_PLACEMENT_WEIGHTS))


def test_place_small_fixture_zero_unplaced_and_no_hole_overlap() -> None:
    components, nets = _small_fixture()
    res = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options())
    assert res.unplaced == [], f"unexpectedly unplaced: {res.unplaced}"
    assert {p.component_ref for p in res.placements} == {c.ref for c in components}

    seen: set[str] = set()
    for placement in res.placements:
        for hole_id in placement.occupied_hole_ids:
            assert hole_id not in seen, f"hole {hole_id} occupied by two placements"
            seen.add(hole_id)


def test_place_keeps_every_cell_inside_board_bounds() -> None:
    components, nets = _small_fixture()
    res = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options())
    for placement in res.placements:
        for hole_id in placement.occupied_hole_ids:
            row_str, col_str = hole_id.split("-", 1)
            row, col = int(row_str), int(col_str)
            assert 1 <= row <= _ROWS
            assert 1 <= col <= _COLS


def test_place_determinism_byte_identical() -> None:
    components, nets = _small_fixture()
    r1 = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options(seed=7))
    r2 = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options(seed=7))
    j1 = [p.model_dump(by_alias=True) for p in r1.placements]
    j2 = [p.model_dump(by_alias=True) for p in r2.placements]
    assert j1 == j2
    assert r1.cost == r2.cost


def test_place_trace_records_one_pose_choice_per_component() -> None:
    components, nets = _small_fixture()
    res = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options())
    assert len(res.trace.pose_choices) == len(components)
    assert {pc.component_ref for pc in res.trace.pose_choices} == {c.ref for c in components}


def test_place_with_locked_initial_layout_keeps_locked_intact() -> None:
    components, nets = _small_fixture()
    locked = ComponentPlacement(
        component_ref="U1",
        anchor_hole_id="2-2",
        orientation=0,
        span=None,
        pin_holes={str(i): f"{2 + (i - 1) // 4}-{2 + (i - 1) % 4}" for i in range(1, 9)},
        occupied_hole_ids=[f"{2 + (i - 1) // 4}-{2 + (i - 1) % 4}" for i in range(1, 9)],
        locked=True,
    )
    initial = TraceLayout(board_id="test-strip", placements=[locked])
    res = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options(), initial_layout=initial)
    u1 = next(p for p in res.placements if p.component_ref == "U1")
    assert u1.anchor_hole_id == "2-2"
    assert u1.locked is True
    assert {p.component_ref for p in res.placements} == {c.ref for c in components}


def test_place_handles_single_component() -> None:
    components = [Component(ref="U1", value="74HC04", footprint_id="DIP-8", pins=[str(i) for i in range(1, 9)])]
    res = place(_board(), PERFBOARD_FOOTPRINTS, components, [], _options())
    assert res.unplaced == []
    assert res.placements[0].component_ref == "U1"


def test_place_rejects_component_too_big_for_the_board() -> None:
    """A footprint that cannot fit anywhere on a tiny board ends up unplaced,
    not silently dropped or crashing the solver."""
    tiny = build_perfboard(rows=2, cols=2, layers=1, id="tiny-strip")
    components = [Component(ref="U1", value="74HC04", footprint_id="DIP-14", pins=[str(i) for i in range(1, 15)])]
    res = place(tiny, PERFBOARD_FOOTPRINTS, components, [], _options())
    assert res.unplaced == ["U1"]
    assert res.placements == []


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_place_different_seeds_all_place_everything(seed: int) -> None:
    components, nets = _small_fixture()
    res = place(_board(), PERFBOARD_FOOTPRINTS, components, nets, _options(seed=seed))
    assert res.unplaced == []
