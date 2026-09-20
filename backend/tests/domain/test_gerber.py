"""Tests for `app.domain.gerber`, `app.domain.excellon`, `app.domain.render_traces`,
and `app.domain.instructions_perfboard`.
"""

from __future__ import annotations

import pytest

from app.domain.boards.registry import get_board_model
from app.domain.excellon import render_excellon
from app.domain.gerber import render_gerber
from app.domain.instructions_perfboard import build_instructions
from app.domain.models import (
    Component,
    ComponentPlacement,
    Net,
    PerfboardModel,
    PinRef,
    Point,
    Trace,
    TraceLayout,
    TraceSegment,
    Via,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.render_traces import RenderOptions, render_traces

pytest_plugins: list[str] = []


def _sample_layout(board: PerfboardModel) -> tuple[list[Component], list[Net], TraceLayout]:
    placements = [
        ComponentPlacement(
            component_ref="R1",
            anchor_hole_id="2-2",
            orientation=0,
            span=None,
            pin_holes={"1": "2-2", "2": "2-5"},
            occupied_hole_ids=["2-2", "2-3", "2-4", "2-5"],
            locked=False,
        ),
    ]
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
                estimated_length_mm=5.08,
            ),
        ],
    )
    return components, nets, layout


def test_gerber_bundle_has_three_valid_files() -> None:
    board = get_board_model("strip-20x30-double")
    assert isinstance(board, PerfboardModel)
    components, _nets, layout = _sample_layout(board)
    bundle = render_gerber(board, components, PERFBOARD_FOOTPRINTS, layout)
    for gerber_str in (bundle.top_copper, bundle.bottom_copper, bundle.board_outline):
        assert gerber_str.startswith("%FSLAX46Y46*%")
        assert gerber_str.rstrip().endswith("M02*")
        assert "%MOMM*%" in gerber_str


def test_gerber_top_layer_includes_trace_and_pads() -> None:
    board = get_board_model("strip-20x30-double")
    components, _nets, layout = _sample_layout(board)
    bundle = render_gerber(board, components, PERFBOARD_FOOTPRINTS, layout)
    # Pad aperture D10 is distinct from the trace aperture (D100+)
    assert "%ADD10C,1.7*%" in bundle.top_copper
    assert "%ADD100C,0.4*%" in bundle.top_copper
    assert "D10*" in bundle.top_copper  # pad flash select
    assert "D100*" in bundle.top_copper  # trace draw select
    # No trace on the bottom layer for this fixture
    assert "D100*" not in bundle.bottom_copper


def test_gerber_outline_is_a_closed_rectangle() -> None:
    board = get_board_model("strip-15x20-double")
    components, _nets, layout = _sample_layout(board)
    bundle = render_gerber(board, components, PERFBOARD_FOOTPRINTS, layout)
    # 5 D01 moves: 4 corners + close back to start
    d01_count = bundle.board_outline.count("D01*X")
    assert d01_count == 5


def test_excellon_drill_file_lists_pin_holes_and_vias() -> None:
    board = get_board_model("strip-20x30-double")
    components, _nets, layout = _sample_layout(board)
    # Add a via to exercise the second tool code
    layout.traces[0].vias.append(Via(point=Point(x=5.0, y=5.0), drill_mm=0.3))
    drl = render_excellon(board, components, PERFBOARD_FOOTPRINTS, layout)
    assert drl.startswith("M48")
    assert drl.rstrip().endswith("M30")
    assert "T1C0.3" in drl  # via drill (sorted first, smaller diameter)
    assert "T2C0.5" in drl  # pad drill


def test_render_traces_svg_contains_hole_grid_and_trace() -> None:
    board = get_board_model("strip-20x30-double")
    components, _nets, layout = _sample_layout(board)
    svg = render_traces(board, components, PERFBOARD_FOOTPRINTS, layout)
    assert svg.startswith("<?xml")
    assert "<svg" in svg
    assert svg.rstrip().endswith("</svg>")
    assert "polyline" in svg  # the trace
    assert svg.count("<circle") >= len(board.holes)  # at least one circle per hole


def test_render_traces_respects_width_scale() -> None:
    board = get_board_model("strip-15x20-double")
    components, _nets, layout = _sample_layout(board)
    svg_1x = render_traces(board, components, PERFBOARD_FOOTPRINTS, layout, RenderOptions(width_scale=1.0))
    svg_2x = render_traces(board, components, PERFBOARD_FOOTPRINTS, layout, RenderOptions(width_scale=2.0))
    # width attribute should differ by 2x
    import re

    w1 = int(re.search(r'width="(\d+)"', svg_1x).group(1))
    w2 = int(re.search(r'width="(\d+)"', svg_2x).group(1))
    assert w2 == pytest.approx(w1 * 2, abs=1)


def test_build_perfboard_instructions_has_bom_and_steps() -> None:
    board = get_board_model("strip-20x30-double")
    components, nets, layout = _sample_layout(board)
    instructions = build_instructions(board, components, nets, layout)
    assert instructions.bom_lines  # at least one BOM line
    assert instructions.steps  # at least one step
    assert any("verifica" in s.lower() or "continuit" in s.lower() for s in instructions.steps)


def test_perfboard_instructions_orders_components_before_traces() -> None:
    board = get_board_model("strip-20x30-double")
    components, nets, layout = _sample_layout(board)
    instructions = build_instructions(board, components, nets, layout)
    component_step_idx = next(i for i, s in enumerate(instructions.steps) if "Inserisci" in s)
    trace_step_idx = next(i for i, s in enumerate(instructions.steps) if "Traccia" in s)
    assert component_step_idx < trace_step_idx
