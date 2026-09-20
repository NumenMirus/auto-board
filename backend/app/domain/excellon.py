"""Excellon drill file writer for perfboards.

Emits an NC drill file (``*.drl``) listing every hole that needs a drill —
through-hole pads used by components, plus vias. The output follows the
Excellon format used by JLCPCB / PCBWay / KiCad's ``Drill.nc`` import.

Coordinates are in millimetres, absolute mode, 6.6 decimal format (matches
the Gerber X2 writer in :mod:`app.domain.gerber`). One tool definition
``T1`` is used for the canonical 0.5 mm drill; per-design larger drills are
added as ``T2``, ``T3`` etc. as encountered.
"""

from __future__ import annotations

from app.domain.models import (
    Component,
    PerfboardModel,
    ThroughHoleFootprint,
    TraceLayout,
)

__all__ = ["render_excellon"]


def _collect_drills(
    board: PerfboardModel,
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
    layout: TraceLayout,
) -> dict[float, list[tuple[float, float]]]:
    """Return ``{drill_diameter_mm: [(x, y), ...]}`` for every drilled hole."""
    drills: dict[float, list[tuple[float, float]]] = {}
    comp_by_ref = {c.ref: c for c in components}
    for placement in layout.placements:
        comp = comp_by_ref.get(placement.component_ref)
        if comp is None:
            continue
        fp = footprints.get(comp.footprint_id)
        if fp is None:
            continue
        for _pin_name, hole_id in placement.pin_holes.items():
            hole = next((h for h in board.holes if h.id == hole_id), None)
            if hole is None:
                continue
            # All through-hole pads share the canonical 0.5 mm drill by default
            drills.setdefault(0.5, []).append((hole.point.x, hole.point.y))
    for trace in layout.traces:
        for via in trace.vias:
            drills.setdefault(via.drill_mm, []).append((via.point.x, via.point.y))
    return drills


def render_excellon(
    board: PerfboardModel,
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
    layout: TraceLayout,
) -> str:
    """Return an Excellon ``.drl`` string for the given layout."""
    drills = _collect_drills(board, components, footprints, layout)
    lines: list[str] = [
        "M48",
        "; AutoBoard Excellon drill file",
        "FMAT,2",
        "INCH,LZ",
        "METRIC,TZ",
    ]
    # Tool table — T1, T2, ... assigned in sorted order by diameter
    tool_codes: dict[float, str] = {}
    for i, diameter in enumerate(sorted(drills), start=1):
        code = f"T{i}"
        tool_codes[diameter] = code
        lines.append(f"{code}C{format(diameter, '.4f').rstrip('0').rstrip('.')}")
    lines.append("%")
    lines.append("G05")
    lines.append("T01")
    lines.append("X0Y0")

    # Drill cycles — group by tool
    for diameter, coords in sorted(drills.items()):
        code = tool_codes[diameter]
        lines.append(f"{code}")
        for x, y in coords:
            lines.append(f"X{x * 1_000_000:.0f}Y{y * 1_000_000:.0f}")
    lines.append("M30")
    return "\n".join(lines) + "\n"
