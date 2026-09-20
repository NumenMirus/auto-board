"""Gerber X2 writer for perfboard trace layouts.

Emits three Gerber files (one per copper layer + a board outline) plus a
matching Excellon drill file (see :mod:`app.domain.excellon`). The output is
deterministic and follows the Gerber X2 attribute grammar so modern CAM tools
(JLCPCB, PCBWay, KiCad) accept it without manual fixups.

Apertures:
- D10 = circular pad for a single hole (1.7 mm diameter, 1.0 mm drill)
- D11 = trace draw aperture (0.4 mm round — overridden per-segment by width)
- D12 = board outline (0.15 mm round)

Coordinate format: ``%FSLAX46Y46*%`` — 6 integer + 6 decimal digits, mm,
absolute. Origin at the lower-left corner of the board outline.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import (
    Component,
    PerfboardModel,
    Point,
    ThroughHoleFootprint,
    Trace,
    TraceLayout,
)

__all__ = ["GerberBundle", "render_gerber"]


@dataclass(slots=True)
class GerberBundle:
    top_copper: str
    bottom_copper: str
    board_outline: str


# Coordinate format header (X2 / mm / absolute / 6.6)
_FS = "%FSLAX46Y46*%"
_MO = "%MOMM*%"
# X2 attributes (header — the per-file FileFunction is appended below)
_ATTR_PREFIX = "%TF.GenerationSoftware,AutoBoard,1.0*%%TF.Part,Single*%"


def _xy(p: Point) -> str:
    """Format a Point as a Gerber X,Y pair (in mm)."""
    return f"X{p.x * 1_000_000:.0f}Y{p.y * 1_000_000:.0f}"


def _board_origin_offset(board: PerfboardModel) -> tuple[float, float]:
    """Pad origin so the outline sits at >= 2 mm from the file origin."""
    return (-2.0, -2.0)


def _outline_polygon(board: PerfboardModel) -> list[Point]:
    """Return a 4-corner polygon for the board outline (rectangle)."""
    ox, oy = _board_origin_offset(board)
    w = (board.cols - 1) * board.pitch_mm
    h = (board.rows - 1) * board.pitch_mm
    return [
        Point(x=ox, y=oy),
        Point(x=ox + w, y=oy),
        Point(x=ox + w, y=oy + h),
        Point(x=ox, y=oy + h),
        Point(x=ox, y=oy),
    ]


def _board_outline(board: PerfboardModel) -> str:
    poly = _outline_polygon(board)
    lines = [
        _FS,
        _MO,
        _ATTR_PREFIX,
        "%TF.FileFunction,Profile*%",
        "%ADD12C,0.15*%",
        "G75*",
        "D12*",
    ]
    for p in poly[:-1]:
        lines.append(f"D01*{_xy(p)}D01*")
    lines.append(f"D01*{_xy(poly[-1])}D01*")
    lines.append("M02*")
    return "\n".join(lines) + "\n"


def _aperture_for_trace(trace: Trace, segment_index: int) -> tuple[int, float]:
    """Return ``(aperture_code, diameter_mm)`` for a trace segment.

    Trace apertures live in the D100+ namespace so they don't collide with
    the through-hole pad apertures in D10..D99.
    """
    width = trace.segments[segment_index].width_mm
    return (100 + segment_index, width)


def _layer_gerber(
    board: PerfboardModel,
    layout: TraceLayout,
    *,
    layer: str,
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
) -> str:
    """Render a single copper layer."""
    function_attr = (
        "%TF.FileFunction,Copper,L1,Top*%" if layer == "top" else "%TF.FileFunction,Copper,L2,Bot*%"
    )
    lines: list[str] = [
        _FS,
        _MO,
        _ATTR_PREFIX,
        function_attr,
    ]
    # Define a single pad aperture (D10) — used for every through-hole pad
    lines.append("%ADD10C,1.7*%")
    # Define per-segment trace apertures (D11..Dnn)
    used_apertures: set[int] = set()
    trace_aperture_map: dict[int, int] = {}
    for trace in layout.traces:
        for i, seg in enumerate(trace.segments):
            if seg.layer != layer:
                continue
            code, _width = _aperture_for_trace(trace, i)
            trace_aperture_map[id(seg)] = code
            if code not in used_apertures:
                lines.append(f"%ADD{code}C,{seg.width_mm}*%")
                used_apertures.add(code)

    # Pads at every hole used by a placement pin
    comp_by_ref = {c.ref: c for c in components}
    for placement in layout.placements:
        comp = comp_by_ref.get(placement.component_ref)
        if comp is None:
            continue
        fp = footprints.get(comp.footprint_id)
        if fp is None:
            continue
        for _pin, hole_id in placement.pin_holes.items():
            hole = next((h for h in board.holes if h.id == hole_id), None)
            if hole is None:
                continue
            lines.append(f"D10*{_xy(hole.point)}D03*")

    # Trace draws (D01 = linear interpolation between current and target point)
    for trace in layout.traces:
        for seg in trace.segments:
            if seg.layer != layer:
                continue
            code = trace_aperture_map[id(seg)]
            lines.append(f"D{code}*")
            lines.append(f"D01*{_xy(seg.start)}D01*")
            lines.append(f"D01*{_xy(seg.end)}D01*")

    lines.append("M02*")
    return "\n".join(lines) + "\n"


def render_gerber(
    board: PerfboardModel,
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
    layout: TraceLayout,
) -> GerberBundle:
    """Produce a 3-file Gerber bundle for a perfboard trace layout."""
    return GerberBundle(
        top_copper=_layer_gerber(board, layout, layer="top", components=components, footprints=footprints),
        bottom_copper=_layer_gerber(
            board, layout, layer="bottom", components=components, footprints=footprints
        ),
        board_outline=_board_outline(board),
    )
