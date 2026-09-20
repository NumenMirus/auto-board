"""Perfboard / stripboard generator.

A perfboard is a uniform grid of isolated through-holes on a single (or double)
copper-clad substrate. There are no power rails, no center gap, and no
electrical groups — every hole is isolated by default. Connections are made
later by the trace router (maze router over the hole graph + rip-up/reroute).

The hole grid is ``cols`` columns wide and ``rows`` rows tall, on a 2.54 mm
(0.1″) pitch. Hole id convention: ``f"{row}{col}"`` (row 1..N, col 1..N),
matching the breadboard's ``{row}{col}`` style.
"""

from __future__ import annotations

from app.domain.models import (
    BoardZone,
    GridPoint,
    Hole,
    PerfboardMetadata,
    PerfboardModel,
    Point,
)

__all__ = ["build_perfboard"]

_PITCH_MM: float = 2.54


def build_perfboard(
    rows: int,
    cols: int,
    layers: int = 2,
    *,
    id: str | None = None,
) -> PerfboardModel:
    """Construct a ``rows × cols`` perfboard with the requested copper layer count.

    The hole grid is laid out so row 1 is at the top (y = 0) and col 1 is at
    the left. ``layers`` is 1 (single-sided) or 2 (double-sided with plated
    through-holes / vias allowed).
    """
    if rows <= 0 or cols <= 0:
        raise ValueError(f"rows and cols must be positive, got rows={rows} cols={cols}")
    if layers not in (1, 2):
        raise ValueError(f"layers must be 1 or 2, got {layers}")

    holes: list[Hole] = []
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            point = Point(x=float(c - 1) * _PITCH_MM, y=float(r - 1) * _PITCH_MM)
            grid = GridPoint(col=c, row=str(r))
            # Pad column with leading zeros so multi-digit rows/cols produce
            # unique ids. e.g. row 10 col 1 → "10-01", row 1 col 10 → "01-10".
            label = f"{r}-{c}"
            holes.append(
                Hole(
                    id=label,
                    point=point,
                    grid=grid,
                    enabled=True,
                    label=label,
                )
            )

    width_mm = float(cols - 1) * _PITCH_MM
    height_mm = float(rows - 1) * _PITCH_MM
    main_zone = BoardZone(
        id="main",
        kind="main",
        polygon=[
            Point(x=-1.27, y=-1.27),
            Point(x=width_mm + 1.27, y=-1.27),
            Point(x=width_mm + 1.27, y=height_mm + 1.27),
            Point(x=-1.27, y=height_mm + 1.27),
        ],
    )

    board_id = id or f"strip-{rows}x{cols}-{'double' if layers == 2 else 'single'}"
    return PerfboardModel(
        id=board_id,
        version=1,
        pitch_mm=_PITCH_MM,
        rows=rows,
        cols=cols,
        layers=layers,
        holes=holes,
        zones=[main_zone],
        metadata=PerfboardMetadata(rows=rows, cols=cols, layers=layers),
    )
