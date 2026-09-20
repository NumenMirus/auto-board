"""Pose generation for footprint placement.

A :class:`Pose` is one concrete candidate placement: an anchor hole on the main lattice,
an orientation, and (for flexible-lead footprints) a span. Pose generation enumerates
``anchor x orientation x span``, applies the footprint's placement rules, and rejects any
pose that does not fit.

Placement is restricted to the main lattice (``index.lattice``); rails are jumper
endpoints only. Every pose is therefore guaranteed by construction to satisfy
``PlacementRuleMainArea`` — but we still validate it explicitly for completeness.

The pose list for a given board + footprint pair is deterministic and cached by
``(board_id, footprint_id)`` so repeated greedy passes and local-search moves don't pay
the enumeration cost again.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    FlexibleLeadSpan,
    PlacementRule,
    PlacementRuleBoardEdge,
    PlacementRuleMainArea,
    PlacementRuleMinClearance,
    PlacementRuleStraddleCenterGap,
    RelativeHole,
)

__all__ = ["Pose", "generate_poses"]


# --------------------------------------------------------------------------
# Pose dataclass
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pose:
    anchor_idx: int
    orientation: int
    span: int | None
    pin_idx: tuple[tuple[str, int], ...]
    occupied_mask: int
    body_cells_idx: tuple[int, ...]
    mech_cost: float


# --------------------------------------------------------------------------
# Rotation helpers
# --------------------------------------------------------------------------


def _rotate_offset(x: int, y: int, orientation: int) -> tuple[int, int]:
    """Rotate the lattice-step offset ``(x, y)`` by ``orientation`` degrees around the origin.

    Only ``0``, ``90``, ``180``, ``270`` are supported. The anchor is always at the
    footprint's local origin so no translation is required before rotation.
    """
    if orientation == 0:
        return (x, y)
    if orientation == 90:
        return (y, -x)
    if orientation == 180:
        return (-x, -y)
    if orientation == 270:
        return (-y, x)
    raise ValueError(f"Unsupported orientation: {orientation}")


def _flexible_local_offsets(
    footprint: BreadboardFootprint, span: int
) -> tuple[dict[str, RelativeHole], list[RelativeHole]]:
    """Build the local pin/body offsets for a flexible-lead footprint at ``span``.

    Two-pin flexible footprints (axial, radial, LED, electrolytic) have an implicit
    canonical shape: pin ``"1"`` at ``(0, 0)``, pin ``"2"`` at ``(span, 0)``, body cells
    covering the line segment between them (inclusive of both endpoints). Orientation is
    applied to this base shape, *not* to the registry's stored offsets, so the chosen
    span always shows up in the resulting pose geometry.

    The board's main lattice is a 30 x 10 grid; we keep offsets in lattice steps so the
    rotated pose still lands on integer coordinates.
    """
    pin_offsets: dict[str, RelativeHole] = {
        "1": RelativeHole(x=0, y=0),
        "2": RelativeHole(x=span, y=0),
    }
    body_cells: list[RelativeHole] = [RelativeHole(x=dx, y=0) for dx in range(span + 1)]
    return pin_offsets, body_cells


# --------------------------------------------------------------------------
# Direct-lattice indexing helpers
# --------------------------------------------------------------------------


def _anchor_col_row(index: BoardIndex, anchor_idx: int) -> tuple[int, int]:
    """Return ``(col, row_index)`` for the lattice hole at ``anchor_idx``.

    ``anchor_idx`` is always a lattice hole for the poses we generate, so we use the
    inverted lattice as a cache. The inversion is built lazily and shared across pose
    generations on the same ``BoardIndex`` instance.
    """
    inv = _LATTICE_INV_CACHE.get(id(index))
    if inv is None:
        inv = {hole_idx: (col, row) for (col, row), hole_idx in index.lattice.items()}
        _LATTICE_INV_CACHE[id(index)] = inv
    return inv[anchor_idx]


# id(index) -> {hole_idx: (col, row_index)}
# BoardIndex is a frozen dataclass; identity is stable for the lifetime of the object.
_LATTICE_INV_CACHE: dict[int, dict[int, tuple[int, int]]] = {}


# --------------------------------------------------------------------------
# Rule predicates (each returns False to REJECT)
# --------------------------------------------------------------------------


def _resolve_pin_holes(
    pin_offsets: dict[str, RelativeHole],
    body_cells: list[RelativeHole],
    orientation: int,
    anchor_col: int,
    anchor_row: int,
    index: BoardIndex,
) -> tuple[list[tuple[str, int]], list[int], list[int], list[int]] | None:
    """Translate + rotate the local offsets onto the lattice. Return ``None`` if any cell
    falls outside the lattice or lands on a disabled hole.

    Returns ``(pins, body_idxs, cols, rows)`` where ``pins`` is a list of
    ``(pin_id, hole_idx)`` pairs and ``body_idxs`` is the body-cell hole indices in
    their original (un-sorted) order. ``cols``/``rows`` are the corresponding lattice
    coordinates.
    """
    pins: list[tuple[str, int]] = []
    body_idxs: list[int] = []
    cols: list[int] = []
    rows: list[int] = []

    for pin_id, off in pin_offsets.items():
        dx, dy = _rotate_offset(off.x, off.y, orientation)
        col = anchor_col + dx
        row = anchor_row + dy
        hole_idx = index.lattice.get((col, row))
        if hole_idx is None:
            return None
        if not index.enabled[hole_idx]:
            return None
        pins.append((pin_id, hole_idx))
        cols.append(col)
        rows.append(row)

    for off in body_cells:
        dx, dy = _rotate_offset(off.x, off.y, orientation)
        col = anchor_col + dx
        row = anchor_row + dy
        hole_idx = index.lattice.get((col, row))
        if hole_idx is None:
            return None
        if not index.enabled[hole_idx]:
            return None
        body_idxs.append(hole_idx)
        cols.append(col)
        rows.append(row)

    return pins, body_idxs, cols, rows


def _check_main_area(cols: list[int], rows: list[int]) -> bool:
    """All resolved cells must lie inside the main lattice — they already do by virtue of
    the lattice lookup, but assert the bounding box here for the explicit
    ``PlacementRuleMainArea`` check.
    """
    return all(1 <= c <= 30 for c in cols) and all(0 <= r <= 9 for r in rows)


def _check_straddle_center_gap(rows: list[int], index: BoardIndex) -> bool:
    """Occupied rows must include at least one row on each side of the center gap."""
    gap_lo, gap_hi = index.center_gap_between
    return min(rows) <= gap_lo and max(rows) >= gap_hi


def _check_min_clearance(
    cols: list[int], rows: list[int], value: int, occupied_mask: int, index: BoardIndex
) -> bool:
    """Each occupied cell must have at least ``value`` empty main-lattice neighbours in
    every cardinal direction (or run off the edge, which is exempt).

    A neighbour cell that belongs to the SAME footprint's own body (e.g. a 2-pin
    connector's other pin, one column away) is transparent for this check: it is
    neither a "blocker" nor does it count toward the empty-hole tally, so the scan
    simply continues past it looking for genuine external clearance. Treating a
    footprint's own adjacent pins as a clearance violation against themselves would
    make any closely-packed footprint (e.g. ``CONN-1x2``, whose two pins are one
    lattice step apart) permanently unplaceable.
    """
    cell_set = set(zip(cols, rows, strict=False))
    for c, r in zip(cols, rows, strict=False):
        for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            empty = 0
            step = 1
            while empty < value:
                nc = c + dc * step
                nr = r + dr * step
                # Out of grid → exempt (doesn't count against clearance).
                if not (1 <= nc <= 30 and 0 <= nr <= 9):
                    break
                hole_idx = index.lattice.get((nc, nr))
                if hole_idx is None or not index.enabled[hole_idx]:
                    break
                if (nc, nr) in cell_set:
                    # Own footprint cell: skip past it, keep scanning outward.
                    step += 1
                    continue
                if (occupied_mask >> hole_idx) & 1:
                    break
                empty += 1
                step += 1
            if empty < value:
                return False
    return True


def _has_rule(rules: list[PlacementRule], rule_type: type[PlacementRule]) -> bool:
    return any(isinstance(r, rule_type) for r in rules)


def _min_clearance_value(rules: list[PlacementRule]) -> int:
    for r in rules:
        if isinstance(r, PlacementRuleMinClearance):
            return r.value
    return 0


def _is_board_edge_constrained(rules: list[PlacementRule]) -> bool:
    return _has_rule(rules, PlacementRuleBoardEdge)


# --------------------------------------------------------------------------
# Pose generation
# --------------------------------------------------------------------------


# Module-level cache: (board_id, footprint_id) -> tuple[Pose, ...]
# BoardIndex / BreadboardFootprint themselves aren't hashable (frozen dataclasses with
# dict fields), so we key by their string ids. The foot print itself is shared across
# calls so the id is sufficient.
_POSE_CACHE: dict[tuple[str, str], tuple[Pose, ...]] = {}


def generate_poses(index: BoardIndex, footprint: BreadboardFootprint) -> tuple[Pose, ...]:
    """Enumerate every valid pose for ``footprint`` on ``index``'s main lattice.

    Cached by ``(index.board_id, footprint.id)``; this cache is intentionally a plain
    dict rather than ``functools.lru_cache`` because the input objects aren't hashable.
    """
    cache_key = (index.board_id, footprint.id)
    cached = _POSE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rules = list(footprint.placement_rules)
    min_clearance = _min_clearance_value(rules)
    main_area_required = _has_rule(rules, PlacementRuleMainArea)
    straddle_required = _has_rule(rules, PlacementRuleStraddleCenterGap)
    # PlacementRuleBoardEdge is currently unused by any registered footprint but kept for
    # forward compatibility — flagged here so a future reviewer can wire the heuristic.
    _ = _is_board_edge_constrained(rules)

    flex = footprint.geometry.flexible_lead_span

    poses: list[Pose] = []
    for (col, row), anchor_idx in index.lattice.items():
        for orientation in footprint.supported_orientations:
            if flex is None:
                spans: tuple[int | None, ...] = (None,)
                span_list: list[int | None] = [None]
            else:
                span_list = list(range(flex.min_holes, flex.max_holes + 1))
                spans = tuple(span_list)

            for span in spans:
                if span is None:
                    # Fixed footprint: use the registry offsets as-is.
                    pin_offsets_iter = footprint.pin_offsets
                    body_cells_iter = footprint.body_cells
                    span_value: int | None = None
                else:
                    pin_offsets_iter, body_cells_iter = _flexible_local_offsets(footprint, span)
                    span_value = span

                resolved = _resolve_pin_holes(
                    pin_offsets_iter,
                    body_cells_iter,
                    orientation,
                    col,
                    row,
                    index,
                )
                if resolved is None:
                    continue
                pins, body_idxs, cols, rows = resolved

                if main_area_required and not _check_main_area(cols, rows):
                    continue
                if straddle_required and not _check_straddle_center_gap(rows, index):
                    continue

                # Occupancy mask over body cells. Pins are typically inside body cells;
                # union both so collision detection covers the full footprint envelope.
                occupied_mask = 0
                for hi in body_idxs:
                    occupied_mask |= 1 << hi
                for _pin_id, hi in pins:
                    occupied_mask |= 1 << hi

                if min_clearance > 0 and not _check_min_clearance(cols, rows, min_clearance, 0, index):
                    continue

                mech = _mech_cost(span_value, flex, orientation)

                sorted_pins = tuple(sorted(pins, key=lambda kv: kv[0]))

                poses.append(
                    Pose(
                        anchor_idx=anchor_idx,
                        orientation=orientation,
                        span=span_value,
                        pin_idx=sorted_pins,
                        occupied_mask=occupied_mask,
                        body_cells_idx=tuple(body_idxs),
                        mech_cost=mech,
                    )
                )

    # Deterministic ordering: anchor hole id ascending, then orientation, then span.
    poses.sort(
        key=lambda p: (
            index.hole_ids[p.anchor_idx],
            p.orientation,
            -1 if p.span is None else p.span,
        )
    )
    result = tuple(poses)
    _POSE_CACHE[cache_key] = result
    return result


def _mech_cost(
    span: int | None,
    flex: FlexibleLeadSpan | None,
    orientation: int,
) -> float:
    """Mechanical penalty: span deviation from preferred + vertical orientation bump.

    Vertical (90/270) orientations of an axial part need a wire kink, so we add a
    constant cost; the registry already pads the body slightly to discourage vertical
    placement but the cost here is the explicit term the spec requires.
    """
    cost = 0.0
    if span is not None and flex is not None:
        cost += abs(span - flex.preferred_holes) * 1.0
    if orientation in (90, 270):
        cost += 0.5
    return cost
