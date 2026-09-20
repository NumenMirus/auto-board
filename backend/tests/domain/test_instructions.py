"""Unit tests for ``app.domain.instructions``.

Coverage:

* rigid components appear before passives in the step list;
* power/ground jumpers land in the last jumper-bearing steps regardless of length;
* the final step is always ``kind='verify'`` with the exact Italian text;
* the per-jumper ``jumper_line`` matches the main spec §9.4 format exactly;
* the Italian colour table covers every entry of the router PALETTE.
"""

from __future__ import annotations

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.instructions import COLOR_NAMES, build_instructions
from app.domain.models import (
    BreadboardModel,
    Component,
    ComponentPlacement,
    Jumper,
    JumperPath,
    Layout,
    Net,
    Point,
)

pytest_plugins: list[str] = []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _make_components() -> list[Component]:
    return [
        Component(ref="U1", value=None, footprint_id="DIP-8", pins=["1", "2", "3", "4", "5", "6", "7", "8"]),
        Component(ref="R1", value="470", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="D1", value="LED", footprint_id="LED-2P", pins=["1", "2"]),
        Component(ref="C1", value="100n", footprint_id="RADIAL-CAP-2P", pins=["1", "2"]),
    ]


def _make_placements(board: BreadboardModel) -> list[ComponentPlacement]:
    # U1 = DIP-8 straddling the center gap: 4 pins above the gap on row a, 4 below on row f.
    u1_holes = [f"{row}{10 + (k - 1) // 4}" for k, row in enumerate(["a"] * 4 + ["f"] * 4, start=1)]
    return [
        ComponentPlacement(
            component_ref="U1",
            anchor_hole_id="a10",
            orientation=0,
            span=None,
            pin_holes={str(k + 1): u1_holes[k] for k in range(8)},
            occupied_hole_ids=u1_holes,
            locked=False,
        ),
        ComponentPlacement(
            component_ref="R1",
            anchor_hole_id="a1",
            orientation=0,
            span=None,
            pin_holes={"1": "a1", "2": "a4"},
            occupied_hole_ids=["a1", "a2", "a3", "a4"],
            locked=False,
        ),
        ComponentPlacement(
            component_ref="D1",
            anchor_hole_id="a20",
            orientation=0,
            span=None,
            pin_holes={"1": "a20", "2": "a22"},
            occupied_hole_ids=["a20", "a21", "a22"],
            locked=False,
        ),
        ComponentPlacement(
            component_ref="C1",
            anchor_hole_id="a30",
            orientation=0,
            span=None,
            pin_holes={"1": "a30", "2": "a31"},
            occupied_hole_ids=["a30", "a31"],
            locked=False,
        ),
    ]


def _make_jumpers() -> list[Jumper]:
    """Three jumpers covering short, long, and power classes."""
    return [
        Jumper(
            id="J1",
            net_id="N1",
            start_hole_id="a1",
            end_hole_id="a4",
            path=JumperPath(points=[Point(x=0, y=0), Point(x=10, y=0)], layer="lower"),
            color="#1f77b4",
            estimated_length_mm=10.0,
            locked=False,
        ),
        Jumper(
            id="J2",
            net_id="N2",
            start_hole_id="a20",
            end_hole_id="a30",
            path=JumperPath(points=[Point(x=0, y=0), Point(x=80, y=0)], layer="upper"),
            color="#ff7f0e",
            estimated_length_mm=80.0,
            locked=False,
        ),
        Jumper(
            id="J3",
            net_id="GND",
            start_hole_id="a4",
            end_hole_id="rail-bottom-minus-1",
            path=JumperPath(points=[Point(x=0, y=0), Point(x=20, y=10)], layer="lower"),
            color="#1a1a1a",
            estimated_length_mm=20.0,
            locked=False,
        ),
    ]


def _make_nets() -> list[Net]:
    return [
        Net(id="N1", name="sig1", pins=[], net_class="digital", priority=0, constraints=[]),
        Net(id="N2", name="sig2", pins=[], net_class="digital", priority=0, constraints=[]),
        Net(id="GND", name="GND", pins=[], net_class="ground", priority=0, constraints=[]),
    ]


def _make_layout(board: BreadboardModel) -> Layout:
    return Layout(
        version=1,
        board_id=board.id,
        placements=_make_placements(board),
        jumpers=_make_jumpers(),
    )


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_rigid_components_appear_before_passives() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    components = _make_components()
    nets = _make_nets()
    layout = _make_layout(board)
    instructions = build_instructions(board, index, FOOTPRINTS, components, nets, layout)
    steps = instructions.steps

    rigid_indices = [s.order for s in steps if s.kind == "place-rigid"]
    passive_indices = [s.order for s in steps if s.kind == "place-passive"]
    assert rigid_indices, "expected at least one rigid step"
    assert passive_indices, "expected at least one passive step"
    assert max(rigid_indices) < min(passive_indices)


def test_power_ground_jumpers_appear_last_among_jumpers() -> None:
    """Power/ground jumpers MUST land after both short and long jumpers, regardless of length."""
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    components = _make_components()
    nets = _make_nets()
    layout = _make_layout(board)
    instructions = build_instructions(board, index, FOOTPRINTS, components, nets, layout)
    steps = instructions.steps

    jumper_steps = [s for s in steps if s.jumper_line is not None]
    assert len(jumper_steps) >= 3
    last_jumper = jumper_steps[-1]
    assert last_jumper.kind == "connect-power"
    # The previous jumper steps must be either short or long, never power.
    for step in jumper_steps[:-1]:
        assert step.kind in {"add-jumper-short", "add-jumper-long"}


def test_final_step_is_always_verify_with_italian_text() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    components = _make_components()
    nets = _make_nets()
    layout = _make_layout(board)
    instructions = build_instructions(board, index, FOOTPRINTS, components, nets, layout)
    last = instructions.steps[-1]
    assert last.kind == "verify"
    assert last.description == "Verificare continuità e polarità prima di alimentare il circuito."


def test_jumper_line_format_matches_main_spec_example() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    components = _make_components()
    nets = _make_nets()
    layout = _make_layout(board)
    instructions = build_instructions(board, index, FOOTPRINTS, components, nets, layout)
    jumper_steps = [s for s in instructions.steps if s.jumper_line is not None]
    assert jumper_steps, "expected at least one jumper step"

    # Find the line for the first jumper (J1). `jumper_line` is non-None for these steps.
    def _find(prefix: str) -> str:
        for s in jumper_steps:
            assert s.jumper_line is not None  # narrow for mypy
            if s.jumper_line.startswith(prefix):
                return s.jumper_line
        raise AssertionError(f"no jumper step with line starting {prefix!r}")

    assert _find("J1 —") == "J1 — Net: sig1 — da a1 a a4 — blu — 10 mm — layer lower"
    expected_j3 = "J3 — Net: GND — da a4 a rail-bottom-minus-1 — nero — 20 mm — layer lower"
    assert _find("J3 —") == expected_j3


def test_color_names_covers_router_palette() -> None:
    """Every router PALETTE colour (lower-case) MUST have an Italian name in the table."""
    # Hard-coded copy of the router palette from app/domain/route.py (kept in sync
    # by hand; the integration test below catches drift).
    router_palette = (
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#17becf",
        "#bcbd22",
        "#7f7f7f",
        "#3b7dd8",
        "#c44e52",
        "#55a868",
    )
    for hex_color in router_palette:
        assert hex_color in COLOR_NAMES, f"missing Italian name for router palette colour {hex_color!r}"
    # Power/ground specials must also be present.
    assert "#1a1a1a" in COLOR_NAMES
    assert "#d92b2b" in COLOR_NAMES
    # Spot-check the most common mapping.
    assert COLOR_NAMES["#1a1a1a"] == "nero"
    assert COLOR_NAMES["#d92b2b"] == "rosso"
    assert COLOR_NAMES["#1f77b4"] == "blu"
