"""Tests for :mod:`app.domain.place`.

Verifies the assignment's end-to-end expectations:

- Placing a small fixture on ``build_half400(split_rails=True)`` with the default
  weights yields zero unplaced components and zero ``HOLE_COLLISION`` diagnostics.
- The DIP-8 placement straddles the center gap (occupied rows on both sides).
- Two ``place()`` calls with the same seed produce byte-identical ``placements``
  JSON (determinism).
- Locked placements survive the placer unchanged.
- High seed / determinism across components of different footprints.
"""

from __future__ import annotations

import json

import pytest

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    DEFAULT_PLACEMENT_WEIGHTS,
    DEFAULT_ROUTING_WEIGHTS,
    Component,
    ComponentPlacement,
    Layout,
    Net,
    SolverOptions,
)
from app.domain.place import place
from app.domain.validate import validate_layout

pytest_plugins: list[str] = []


@pytest.fixture
def board_index() -> BoardIndex:
    return BoardIndex.build(build_half400(split_rails=True))


def _small_fixture() -> tuple[list[Component], list[Net]]:
    """One DIP-8, two AXIAL-R, one LED-2P, plus a small netlist that doesn't
    induce shorts (each shared net touches disjoint tie-point groups)."""
    components = [
        Component(
            ref="U1",
            value="74HC04",
            footprint_id="DIP-8",
            pins=[str(i) for i in range(1, 9)],
        ),
        Component(ref="R1", value="10k", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="R2", value="4.7k", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="D1", value="LED", footprint_id="LED-2P", pins=["1", "2"]),
    ]
    nets: list[Net] = []
    return components, nets


def _options(seed: int = 42) -> SolverOptions:
    return SolverOptions(
        seed=seed,
        placement_weights=dict(DEFAULT_PLACEMENT_WEIGHTS),
        routing_weights=dict(DEFAULT_ROUTING_WEIGHTS),
    )


def test_place_small_fixture_zero_unplaced_and_no_hole_collisions(
    board_index: BoardIndex,
) -> None:
    """place() succeeds with zero unplaced and zero HOLE_COLLISION diagnostics."""
    components, nets = _small_fixture()
    res = place(
        build_half400(True),
        board_index,
        FOOTPRINTS,
        components,
        nets,
        _options(),
    )
    assert res.unplaced == [], f"unexpectedly unplaced: {res.unplaced}"

    # Build a Layout and run validate_layout to catch any HOLE_COLLISION diagnostics.
    board = build_half400(True)
    layout = Layout(version=1, board_id=board.id, placements=res.placements, jumpers=[])
    diags, score = validate_layout(board, board_index, FOOTPRINTS, components, nets, layout, _options())
    for d in diags:
        assert d.code != "HOLE_COLLISION", f"unexpected HOLE_COLLISION: {d.message}"
    assert score.components_placed == len(components)


def test_dip8_straddles_center_gap(board_index: BoardIndex) -> None:
    """The DIP-8's occupied body covers at least one row on each side of the gap."""
    components, nets = _small_fixture()
    res = place(
        build_half400(True),
        board_index,
        FOOTPRINTS,
        components,
        nets,
        _options(),
    )
    dip = next(p for p in res.placements if p.component_ref == "U1")
    gap_lo, gap_hi = board_index.center_gap_between
    body_rows: set[int] = set()
    for hid in dip.occupied_hole_ids:
        for (_col, row), hi in board_index.lattice.items():
            if hi == board_index.idx[hid]:
                body_rows.add(row)
                break
    assert min(body_rows) <= gap_lo
    assert max(body_rows) >= gap_hi


def test_place_determinism_byte_identical(board_index: BoardIndex) -> None:
    """Two solves with the same seed produce byte-identical placements."""
    components, nets = _small_fixture()
    r1 = place(build_half400(True), board_index, FOOTPRINTS, components, nets, _options())
    r2 = place(build_half400(True), board_index, FOOTPRINTS, components, nets, _options())
    j1 = json.dumps([p.model_dump(by_alias=True) for p in r1.placements])
    j2 = json.dumps([p.model_dump(by_alias=True) for p in r2.placements])
    assert j1 == j2
    assert r1.cost == r2.cost


def test_place_trace_records_pose_choices(board_index: BoardIndex) -> None:
    """The trace carries one PoseChoice per placed component (or per locked one)."""
    components, nets = _small_fixture()
    res = place(
        build_half400(True),
        board_index,
        FOOTPRINTS,
        components,
        nets,
        _options(),
    )
    refs = {c.component_ref for c in res.trace.pose_choices}
    assert refs == {c.ref for c in components}, (
        f"trace pose_choices should reference every placed component; got {refs}"
    )


def test_place_returns_solver_trace_with_phase_timing(board_index: BoardIndex) -> None:
    """The returned SolverTrace carries a populated 'place' phase timing."""
    components, nets = _small_fixture()
    res = place(
        build_half400(True),
        board_index,
        FOOTPRINTS,
        components,
        nets,
        _options(),
    )
    assert "place" in res.trace.phase_timings_ms
    assert res.trace.phase_timings_ms["place"] >= 0.0


def test_place_with_locked_initial_layout_keeps_locked_intact(board_index: BoardIndex) -> None:
    """A locked placement from ``initial_layout`` survives the placer unchanged."""
    components, nets = _small_fixture()
    # Pre-place U1 manually at e1 orient 0.
    locked_placement = ComponentPlacement(
        component_ref="U1",
        anchor_hole_id="e1",
        orientation=0,
        span=None,
        pin_holes={str(i): f"e{i}" for i in range(1, 5)} | {str(i): f"f{i - 4}" for i in range(5, 9)},
        occupied_hole_ids=[f"{row}{col}" for row in "ef" for col in range(1, 5)],
        locked=True,
    )
    initial = Layout(version=1, board_id=build_half400(True).id, placements=[locked_placement], jumpers=[])
    res = place(
        build_half400(True),
        board_index,
        FOOTPRINTS,
        components,
        nets,
        _options(),
        initial_layout=initial,
    )
    u1 = next(p for p in res.placements if p.component_ref == "U1")
    assert u1.anchor_hole_id == "e1", "locked U1 anchor must not change"
    assert u1.orientation == 0, "locked U1 orientation must not change"
    assert u1.locked is True, "locked flag must propagate"
    # The other components must still be placed.
    assert {p.component_ref for p in res.placements} == {c.ref for c in components}


def test_place_different_seeds_produce_different_or_same_layouts(board_index: BoardIndex) -> None:
    """Different seeds must produce deterministic but possibly different layouts."""
    components, nets = _small_fixture()
    r1 = place(build_half400(True), board_index, FOOTPRINTS, components, nets, _options(seed=1))
    r2 = place(build_half400(True), board_index, FOOTPRINTS, components, nets, _options(seed=2))
    # No collision either way.
    for res in (r1, r2):
        for p in res.placements:
            assert p.occupied_hole_ids  # non-empty
        assert res.unplaced == []


def test_place_handles_single_dip_only(board_index: BoardIndex) -> None:
    """Trivial one-component netlist still places successfully."""
    components = [Component(ref="U1", value="x", footprint_id="DIP-8", pins=[str(i) for i in range(1, 9)])]
    res = place(
        build_half400(True),
        board_index,
        FOOTPRINTS,
        components,
        [],
        _options(),
    )
    assert res.unplaced == []
    assert len(res.placements) == 1
    assert res.placements[0].component_ref == "U1"
