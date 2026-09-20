"""SVG renderer for perfboard trace layouts.

Pure-string rendering (no I/O, no cairosvg): produces an assembly-style SVG
that shows the hole grid, the components placed on it, the copper traces on
each layer (top in solid colour, bottom in dashed), and any vias. Output is
deterministic byte-for-byte so golden files compare exactly.

Coordinate system matches :class:`app.domain.models.Point` — board origin
(0, 0) is at the top-left of the perfboard; ``x`` grows right and ``y`` grows
down. All holes are on a 2.54 mm pitch; the renderer also scales the output
``width``/``height`` attributes by ``RenderOptions.width_scale`` while keeping
the ``viewBox`` in native millimetres (matching the breadboard renderer).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import (
    Component,
    PerfboardModel,
    ThroughHoleFootprint,
    TraceLayout,
)

__all__ = ["RenderOptions", "render_traces"]


@dataclass(slots=True)
class RenderOptions:
    show_labels: bool = True
    highlight_net_id: str | None = None
    show_traces: bool = True
    width_scale: float = 4.0
    top_trace_colour: str = "#cc4125"
    bottom_trace_colour: str = "#1f77b4"


_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#bcbd22",
    "#17becf",
)


def _net_colour(net_id: str) -> str:
    h = abs(hash(net_id))
    return _PALETTE[h % len(_PALETTE)]


def render_traces(
    board: PerfboardModel,
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
    layout: TraceLayout,
    options: RenderOptions | None = None,
) -> str:
    """Render ``layout`` as an SVG string."""
    options = options or RenderOptions()
    comp_by_ref = {c.ref: c for c in components}

    # Header + background. The viewBox is in mm; width/height are scaled.
    width_mm = (board.cols - 1) * board.pitch_mm + 4.0
    height_mm = (board.rows - 1) * board.pitch_mm + 4.0
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="-2 -2 {width_mm:.3f} {height_mm:.3f}" '
        f'width="{width_mm * options.width_scale:.0f}" '
        f'height="{height_mm * options.width_scale:.0f}">',
        f'  <rect x="-2" y="-2" width="{width_mm:.3f}" height="{height_mm:.3f}" '
        f'fill="#fafafa" stroke="#333" stroke-width="0.15"/>',
    ]

    # Hole grid
    parts.append('  <g id="holes" fill="#222">')
    for hole in board.holes:
        cx, cy = hole.point.x, hole.point.y
        parts.append(f'    <circle cx="{cx:.2f}" cy="{cy:.2f}" r="0.35" stroke="#000" stroke-width="0.05"/>')
    parts.append("  </g>")

    # Hole labels
    if options.show_labels:
        parts.append('  <g id="labels" font-family="DejaVu Sans, sans-serif" font-size="0.9" fill="#666">')
        for r in range(1, board.rows + 1):
            for c in range(1, board.cols + 1):
                if c in (1, 5, 10, 15, 20, 25, 30) and r in (1, board.rows):
                    x = (c - 1) * board.pitch_mm
                    y = (r - 1) * board.pitch_mm
                    parts.append(f'    <text x="{x:.2f}" y="{y - 1.0:.2f}" text-anchor="middle">{c}</text>')
                if r in (1, 5, 10, 15, 20) and c == 1:
                    x = (c - 1) * board.pitch_mm - 1.5
                    y = (r - 1) * board.pitch_mm
                    parts.append(f'    <text x="{x:.2f}" y="{y + 0.4:.2f}" text-anchor="end">{r}</text>')
        parts.append("  </g>")

    # Components: draw a translucent rect for the body and a centred ref label
    parts.append('  <g id="components" font-family="DejaVu Sans, sans-serif" font-size="0.9">')
    for placement in layout.placements:
        comp = comp_by_ref.get(placement.component_ref)
        if comp is None:
            continue
        fp = footprints.get(comp.footprint_id)
        if fp is None:
            continue
        anchor_hole = next((h for h in board.holes if h.id == placement.anchor_hole_id), None)
        if anchor_hole is None:
            continue
        body_x = anchor_hole.point.x
        body_y = anchor_hole.point.y
        body_w = max((c.x for c in fp.body_cells), default=0) * board.pitch_mm + 1.0
        body_h = max((c.y for c in fp.body_cells), default=0) * board.pitch_mm + 1.0
        parts.append(
            f'    <rect x="{body_x:.2f}" y="{body_y:.2f}" width="{body_w:.2f}" '
            f'height="{body_h:.2f}" fill="#fffae0" stroke="#aa6" stroke-width="0.1" opacity="0.85"/>'
        )
        # Component ref centred over the body
        cx = body_x + body_w / 2.0
        cy = body_y + body_h / 2.0
        parts.append(
            f'    <text x="{cx:.2f}" y="{cy + 0.3:.2f}" text-anchor="middle" fill="#222">{comp.ref}</text>'
        )
        # Pin markers
        for _pin_name, hole_id in placement.pin_holes.items():
            pin_hole = next((h for h in board.holes if h.id == hole_id), None)
            if pin_hole is None:
                continue
            parts.append(
                f'    <circle cx="{pin_hole.point.x:.2f}" cy="{pin_hole.point.y:.2f}" '
                f'r="0.55" fill="#cc4125" opacity="0.85"/>'
            )
    parts.append("  </g>")

    # Traces
    if options.show_traces and layout.traces:
        parts.append('  <g id="traces" fill="none" stroke-linecap="round" stroke-linejoin="round">')
        for trace in layout.traces:
            colour = (
                options.top_trace_colour
                if options.highlight_net_id is None
                else (options.top_trace_colour if trace.net_id == options.highlight_net_id else "#cccccc")
            )
            for seg in trace.segments:
                dasharray = "" if seg.layer == "top" else ' stroke-dasharray="0.6 0.4"'
                width = seg.width_mm * 2.0
                parts.append(
                    f'    <polyline points="{seg.start.x:.2f},{seg.start.y:.2f} '
                    f'{seg.end.x:.2f},{seg.end.y:.2f}" stroke="{colour}" '
                    f'stroke-width="{width:.2f}"{dasharray}/>'
                )
        parts.append("  </g>")

        # Vias: concentric circles
        for trace in layout.traces:
            for via in trace.vias:
                parts.append(
                    f'  <circle cx="{via.point.x:.2f}" cy="{via.point.y:.2f}" '
                    f'r="{via.diameter_mm / 2.0:.2f}" fill="#fff" stroke="#000" stroke-width="0.1"/>'
                )
                parts.append(
                    f'  <circle cx="{via.point.x:.2f}" cy="{via.point.y:.2f}" r="0.18" fill="#000"/>'
                )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
