"""Unit tests for ``app.domain.render``.

These tests do NOT rely on the golden files under ``tests/golden/`` — they assert
pure behavioural properties of :func:`render_svg`:

* the output contains the ``<svg`` element;
* the output is deterministic across repeated calls with the same input;
* setting :attr:`RenderOptions.highlight_net_id` changes the rendered markup (the
  per-component / per-jumper ``opacity`` attribute is added);
* the renderer scales with :attr:`RenderOptions.width_scale` (the SVG viewBox
  ``width`` attribute is a multiple of ``width_scale``).
"""

from __future__ import annotations

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
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
from app.domain.render import RenderOptions, render_svg

pytest_plugins: list[str] = []


def _empty_layout(board: BreadboardModel) -> Layout:
    return Layout(
        version=1,
        board_id=board.id,
        placements=[],
        jumpers=[],
    )


def _make_simple_layout(board: BreadboardModel, index: BoardIndex) -> Layout:
    """Build a tiny fixture: one resistor on ``a1..a4`` + one jumper on ``lower``."""
    placements = [
        ComponentPlacement(
            component_ref="R1",
            anchor_hole_id="a1",
            orientation=0,
            span=None,
            pin_holes={"1": "a1", "2": "a4"},
            occupied_hole_ids=["a1", "a2", "a3", "a4"],
            locked=False,
        )
    ]
    a1 = index.hole_point("a1")
    a4 = index.hole_point("a4")
    jumpers = [
        Jumper(
            id="J1",
            net_id="N1",
            start_hole_id="a1",
            end_hole_id="a4",
            path=JumperPath(points=[Point(x=a1[0], y=a1[1]), Point(x=a4[0], y=a4[1])], layer="lower"),
            color="#1f77b4",
            estimated_length_mm=8.0,
            locked=False,
        )
    ]
    return Layout(version=1, board_id=board.id, placements=placements, jumpers=jumpers)


def test_render_svg_contains_svg_element() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    layout = _empty_layout(board)
    svg = render_svg(board, index, FOOTPRINTS, [], [], layout)
    assert "<svg" in svg


def test_render_svg_is_deterministic_across_calls() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    components = [
        Component(ref="R1", value="470", footprint_id="AXIAL-R", pins=["1", "2"]),
    ]
    layout = _make_simple_layout(board, index)
    first = render_svg(board, index, FOOTPRINTS, components, [], layout)
    second = render_svg(board, index, FOOTPRINTS, components, [], layout)
    third = render_svg(board, index, FOOTPRINTS, components, [], layout)
    assert first == second == third
    assert len(first) > 1000


def test_render_svg_with_highlight_net_emits_opacity_attribute() -> None:
    """A highlighted net must dim non-matching components/jumpers to opacity 0.25."""
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    components = [
        Component(ref="R1", value="470", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="R2", value="1k", footprint_id="AXIAL-R", pins=["1", "2"]),
    ]
    # Place two components on disjoint hole sets and route them on different nets.
    placements = [
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
            component_ref="R2",
            anchor_hole_id="a10",
            orientation=0,
            span=None,
            pin_holes={"1": "a10", "2": "a13"},
            occupied_hole_ids=["a10", "a11", "a12", "a13"],
            locked=False,
        ),
    ]
    nets = [
        Net(id="N1", name="net1", pins=[], net_class="digital", priority=0, constraints=[]),
        Net(id="N2", name="net2", pins=[], net_class="digital", priority=0, constraints=[]),
    ]
    layout = Layout(version=1, board_id=board.id, placements=placements, jumpers=[])
    plain = render_svg(board, index, FOOTPRINTS, components, nets, layout)
    highlighted = render_svg(
        board,
        index,
        FOOTPRINTS,
        components,
        nets,
        layout,
        options=RenderOptions(highlight_net_id="N1"),
    )
    # Plain render has no opacity attributes; highlighted render has them.
    assert 'opacity="0.25"' not in plain
    assert 'opacity="0.25"' in highlighted


def test_render_svg_scales_viewport_with_width_scale() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    layout = _empty_layout(board)
    default = render_svg(board, index, FOOTPRINTS, [], [], layout)
    double = render_svg(
        board,
        index,
        FOOTPRINTS,
        [],
        [],
        layout,
        options=RenderOptions(width_scale=8.0),
    )
    # Extract the viewBox dimensions for a quick sanity check (last attribute group).
    assert default != double
    # The width in pixels must scale linearly with width_scale.
    default_w = _svg_viewbox_width(default)
    double_w = _svg_viewbox_width(double)
    assert double_w == default_w * 2


def test_render_svg_with_diagnostics_marker_emits_diagnostic_layer() -> None:
    """Passing ``diagnostics`` adds a ``<g class="diagnostics">`` layer with markers."""
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    layout = _empty_layout(board)
    from app.domain.models import Diagnostic

    diag_obj = Diagnostic(
        id="NET_OPEN:n1",
        severity="error",
        code="NET_OPEN",
        message="Net N1 is open",
        related_hole_ids=["a1"],
        related_component_refs=[],
        related_net_ids=["N1"],
        suggestion=None,
    )
    out = render_svg(
        board,
        index,
        FOOTPRINTS,
        [],
        [],
        layout,
        diagnostics=[diag_obj],
    )
    assert '<g class="diagnostics">' in out
    assert "#d92b2b" in out  # error colour appears at least once


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _svg_viewbox_width(svg: str) -> float:
    """Pull the ``width`` attribute out of the opening ``<svg ...>`` tag."""
    start = svg.find("<svg")
    end = svg.find(">", start)
    tag = svg[start:end]
    for token in tag.split():
        if token.startswith("width="):
            return float(token.split("=", 1)[1].strip('"'))
    raise AssertionError(f"no width attribute in <svg> tag: {tag!r}")
