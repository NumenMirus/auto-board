"""Half-size 400-tie-point breadboard generator.

Generates the canonical breadboard geometry used by every fixture and smoke test:

- Main area: 30 columns x 10 rows (`a..j`) = 300 holes, with a real 7.62 mm DIP channel
  between rows `e` (index 4) and `f` (index 5).
- Rails: four lines (`top-plus`, `top-minus`, `bottom-minus`, `bottom-plus`) of 25 holes
  each = 100 holes. Rails are jumper endpoints only — placement is restricted to the main
  lattice.

The split variant breaks each rail into two electrical groups at the cluster boundary
between holes 15 and 16, matching the physical break in real breadboard power rails.
The continuous variant treats each rail as a single electrical group.
"""

from __future__ import annotations

from app.domain.models import (
    BoardMetadata,
    BoardZone,
    BreadboardModel,
    ElectricalGroup,
    GridPoint,
    Hole,
    Point,
)

__all__ = ["build_half400"]

_ROWS: tuple[str, ...] = ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j")
_RAIL_LINES: tuple[str, ...] = ("top-plus", "top-minus", "bottom-minus", "bottom-plus")

# Rail Y positions in millimetres (top-plus topmost, bottom-plus bottom-most).
_RAIL_Y: dict[str, float] = {
    "top-plus": -12.70,
    "top-minus": -10.16,
    "bottom-minus": 38.10,
    "bottom-plus": 40.64,
}

_PITCH_MM: float = 2.54
_DIP_CHANNEL_MM: float = 7.62
_CENTER_GAP_CHANNEL_OFFSET_MM: float = 10.16  # y(row 4) + one extra pitch of slack above the DIP channel
_TIE_POINT_GROUP_ROWS_ABOVE_GAP: tuple[str, ...] = ("a", "b", "c", "d", "e")
_TIE_POINT_GROUP_ROWS_BELOW_GAP: tuple[str, ...] = ("f", "g", "h", "i", "j")
_SPLIT_BOUNDARY_SEQ: int = 15  # 1..15 in seg-a, 16..25 in seg-b


def _main_y(row_index: int) -> float:
    """Y coordinate in millimetres for a main-area row index (0..9).

    Rows 0..4 sit at the standard pitch; rows 5..9 are offset by the DIP channel so the
    physical 7.62 mm gap between rows `e` and `f` is preserved.
    """
    if row_index < 5:
        return float(row_index) * _PITCH_MM
    return _CENTER_GAP_CHANNEL_OFFSET_MM + _DIP_CHANNEL_MM + float(row_index - 5) * _PITCH_MM


def _main_x(col: int) -> float:
    """X coordinate in millimetres for a main-area column (1..30)."""
    return float(col - 1) * _PITCH_MM


def _rail_x(seq: int) -> float:
    """X coordinate in millimetres for a rail hole (1..25).

    The 25 rail holes cluster in groups of 5 separated by a one-pitch gap, matching the
    visual dot clusters on real breadboards.
    """
    return 2.54 + float(seq - 1 + (seq - 1) // 5) * _PITCH_MM


def _build_main_holes() -> list[Hole]:
    holes: list[Hole] = []
    for col in range(1, 31):
        for row_index, row in enumerate(_ROWS):
            hole_id = f"{row}{col}"
            holes.append(
                Hole(
                    id=hole_id,
                    point=Point(x=_main_x(col), y=_main_y(row_index)),
                    grid=GridPoint(col=col, row=row),
                    enabled=True,
                    label=f"{row.upper()}{col}",
                )
            )
    return holes


def _build_tie_point_groups() -> list[ElectricalGroup]:
    groups: list[ElectricalGroup] = []
    for col in range(1, 31):
        above = [f"{row}{col}" for row in _TIE_POINT_GROUP_ROWS_ABOVE_GAP]
        below = [f"{row}{col}" for row in _TIE_POINT_GROUP_ROWS_BELOW_GAP]
        groups.append(ElectricalGroup(id=f"tp-l-{col}", hole_ids=above, kind="tie-point"))
        groups.append(ElectricalGroup(id=f"tp-r-{col}", hole_ids=below, kind="tie-point"))
    return groups


def _build_rail_holes() -> list[Hole]:
    holes: list[Hole] = []
    for line in _RAIL_LINES:
        y = _RAIL_Y[line]
        for seq in range(1, 26):
            hole_id = f"rail-{line}-{seq}"
            holes.append(
                Hole(
                    id=hole_id,
                    point=Point(x=_rail_x(seq), y=y),
                    grid=GridPoint(col=seq, row=line),
                    enabled=True,
                    label=hole_id,
                )
            )
    return holes


def _build_rail_groups(split_rails: bool) -> list[ElectricalGroup]:
    groups: list[ElectricalGroup] = []
    for line in _RAIL_LINES:
        all_ids = [f"rail-{line}-{seq}" for seq in range(1, 26)]
        if split_rails:
            groups.append(
                ElectricalGroup(
                    id=f"rail-{line}-seg-a",
                    hole_ids=all_ids[:_SPLIT_BOUNDARY_SEQ],
                    kind="rail",
                )
            )
            groups.append(
                ElectricalGroup(
                    id=f"rail-{line}-seg-b",
                    hole_ids=all_ids[_SPLIT_BOUNDARY_SEQ:],
                    kind="rail",
                )
            )
        else:
            groups.append(ElectricalGroup(id=f"rail-{line}-seg-a", hole_ids=all_ids, kind="rail"))
    return groups


def _build_main_zone() -> BoardZone:
    return BoardZone(
        id="main",
        kind="main",
        polygon=[
            Point(x=-1.27, y=-1.27),
            Point(x=75.0, y=-1.27),
            Point(x=75.0, y=29.21),
            Point(x=-1.27, y=29.21),
        ],
    )


def _build_center_gap_zone() -> BoardZone:
    return BoardZone(
        id="center-gap",
        kind="center-gap",
        polygon=[
            Point(x=-1.27, y=11.43),
            Point(x=75.0, y=11.43),
            Point(x=75.0, y=16.51),
            Point(x=-1.27, y=16.51),
        ],
    )


def _build_rail_zones() -> list[BoardZone]:
    zones: list[BoardZone] = []
    for line in _RAIL_LINES:
        y = _RAIL_Y[line]
        zones.append(
            BoardZone(
                id=f"rail-{line}",
                kind="rail",
                polygon=[
                    Point(x=_rail_x(1) - 1.27, y=y - 1.27),
                    Point(x=_rail_x(25) + 1.27, y=y - 1.27),
                    Point(x=_rail_x(25) + 1.27, y=y + 1.27),
                    Point(x=_rail_x(1) - 1.27, y=y + 1.27),
                ],
            )
        )
    return zones


def build_half400(split_rails: bool) -> BreadboardModel:
    """Build the canonical half-size 400-tie-point breadboard.

    Args:
        split_rails: when `True`, each rail line is split into two electrical groups at
            the cluster boundary (holes 1-15 / 16-25); when `False`, each rail is a single
            electrical group of 25 holes.
    """
    board_id = "half-400-standard-split-rails" if split_rails else "half-400-standard-continuous-rails"
    rail_configuration = "split-1-15/16-25" if split_rails else "continuous"
    metadata = BoardMetadata(
        columns=30,
        rail_configuration=rail_configuration,
        rows=list(_ROWS),
        rail_lines=list(_RAIL_LINES),
    )
    return BreadboardModel(
        id=board_id,
        version=1,
        pitch_mm=_PITCH_MM,
        holes=_build_main_holes() + _build_rail_holes(),
        electrical_groups=_build_tie_point_groups() + _build_rail_groups(split_rails),
        zones=[_build_main_zone(), _build_center_gap_zone(), *_build_rail_zones()],
        metadata=metadata,
    )
