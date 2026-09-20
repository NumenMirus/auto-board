"""`BoardIndex`: the hot-path lookup structure built once per board.

Placement pose generation, routing, and validation all index into this structure instead of
walking `BreadboardModel` lists repeatedly. Building it is O(holes + groups); every other
domain module treats it as read-only.

Construction is pure (`BoardIndex.build`); caching by `board.id` is the caller's
responsibility (API/worker layer), not this module's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

from app.domain.models import BreadboardModel

__all__ = ["BoardIndex"]

_RAIL_HOLE_RE = re.compile(r"^rail-(?P<line>.+)-(?P<seq>\d+)$")


@dataclass(frozen=True, slots=True)
class BoardIndex:
    board_id: str
    hole_ids: tuple[str, ...]
    idx: dict[str, int]
    points: tuple[tuple[float, float], ...]
    enabled: tuple[bool, ...]
    group_of: tuple[int, ...]
    group_ids: tuple[str, ...]
    group_holes: tuple[tuple[int, ...], ...]
    lattice: dict[tuple[int, int], int]
    rail_lattice: dict[str, tuple[int, ...]]
    row_index_of: dict[str, int]
    center_gap_between: tuple[int, int]

    @classmethod
    def build(cls, board: BreadboardModel) -> BoardIndex:
        hole_ids = tuple(h.id for h in board.holes)
        idx = {hole_id: i for i, hole_id in enumerate(hole_ids)}
        points = tuple((h.point.x, h.point.y) for h in board.holes)
        enabled = tuple(h.enabled for h in board.holes)

        group_ids = tuple(g.id for g in board.electrical_groups)
        group_of: list[int] = [-1] * len(hole_ids)
        group_holes: list[tuple[int, ...]] = []
        for group_idx, group in enumerate(board.electrical_groups):
            member_idxs: list[int] = []
            for hole_id in group.hole_ids:
                hole_idx = idx[hole_id]
                group_of[hole_idx] = group_idx
                member_idxs.append(hole_idx)
            group_holes.append(tuple(member_idxs))

        row_index_of = {row: i for i, row in enumerate(board.metadata.rows)}

        lattice: dict[tuple[int, int], int] = {}
        rail_members: dict[str, list[tuple[int, int]]] = {}
        for hole_idx, hole in enumerate(board.holes):
            rail_match = _RAIL_HOLE_RE.match(hole.id)
            if rail_match is not None:
                line = rail_match.group("line")
                seq = int(rail_match.group("seq"))
                rail_members.setdefault(line, []).append((seq, hole_idx))
            else:
                row_idx = row_index_of.get(hole.grid.row)
                if row_idx is not None:
                    lattice[(hole.grid.col, row_idx)] = hole_idx

        rail_lattice = {
            line: tuple(hole_idx for _seq, hole_idx in sorted(members))
            for line, members in rail_members.items()
        }

        center_gap_between = _detect_center_gap(board, lattice)

        return cls(
            board_id=board.id,
            hole_ids=hole_ids,
            idx=idx,
            points=points,
            enabled=enabled,
            group_of=tuple(group_of),
            group_ids=group_ids,
            group_holes=tuple(group_holes),
            lattice=lattice,
            rail_lattice=rail_lattice,
            row_index_of=row_index_of,
            center_gap_between=center_gap_between,
        )

    def hole_point(self, hole_id: str) -> tuple[float, float]:
        return self.points[self.idx[hole_id]]

    def group_of_hole(self, hole_id: str) -> int:
        return self.group_of[self.idx[hole_id]]


def _detect_center_gap(
    board: BreadboardModel,
    lattice: dict[tuple[int, int], int],
) -> tuple[int, int]:
    """Find the pair of adjacent row indices separated by a wider-than-pitch gap.

    Uses the median y of each row (over all columns present in the main lattice) and flags
    the first consecutive pair whose y-delta exceeds 1.5x the board pitch. Raises
    `ValueError` if no such gap exists (every board this codebase supports has one).
    """

    row_ys: dict[int, list[float]] = {}
    for (_col, row_idx), hole_idx in lattice.items():
        row_ys.setdefault(row_idx, []).append(board.holes[hole_idx].point.y)

    medians: dict[int, float] = {}
    for row_idx, ys in row_ys.items():
        ys_sorted = sorted(ys)
        medians[row_idx] = ys_sorted[len(ys_sorted) // 2]

    ordered_rows = sorted(medians)
    pitch = board.pitch_mm
    for a, b in pairwise(ordered_rows):
        if medians[b] - medians[a] > pitch * 1.5:
            return (a, b)

    raise ValueError(f"board {board.id!r} has no detectable center gap")
