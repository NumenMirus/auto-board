"""Greedy + hill-climbing placement for perfboards (mirrors `app.domain.place`).

Perfboards have no power rails, no center gap, and no electrical groups — every
hole is isolated until the trace router connects it (see `app.domain.boards.
perfboard`). That makes pose generation *simpler* than the breadboard case: a
pose is valid whenever its footprint's cells land inside the plain `rows x cols`
grid and satisfy the footprint's `min-clearance-holes` rule, if any. There is no
`BoardIndex` for perfboards (that type is breadboard-specific: it detects a
center gap and rail groups neither of which perfboards have), so this module
builds its own tiny flat hole index instead of importing one.

Algorithm structure mirrors `app.domain.place` exactly: order components
(locked, then clearance-constrained, then DIP, then the rest by ascending pose
count), greedily place each into its lowest-cost non-colliding pose, then
hill-climb with translate/rotate/span/swap/relocate-cluster moves accepting
only strict cost improvements. See that module's docstring for the full
rationale; this one documents only where the perfboard version differs.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from app.domain.cluster import Cluster, build_clusters
from app.domain.models import (
    Component,
    ComponentPlacement,
    FlexibleLeadSpan,
    Net,
    PerfboardModel,
    PlacementResult,
    PlacementRule,
    PlacementRuleBoardEdge,
    PlacementRuleMainArea,
    PlacementRuleMinClearance,
    PoseChoice,
    RelativeHole,
    SolverOptions,
    SolverTrace,
    ThroughHoleFootprint,
    TraceLayout,
    TraceRejection,
)

__all__ = ["place"]

_REJECTION_CAP: int = 500

# Footprint id substrings that mark a user-facing part — kept simple, mirrors
# `app.domain.cost`'s definition exactly.
_ACCESSIBLE_FAMILY_KEYWORDS: tuple[str, ...] = ("LED", "CONN", "HEADER", "TACT")


# --------------------------------------------------------------------------
# Flat hole index — perfboards have no groups/rails/center-gap, so this is
# just a `(col, row) -> flat hole number` lattice plus the matching hole ids
# and millimetre points, built directly from `PerfboardModel.rows/cols`.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PerfIndex:
    board_id: str
    rows: int
    cols: int
    pitch_mm: float
    hole_ids: tuple[str, ...]
    idx: dict[str, int]
    points: tuple[tuple[float, float], ...]
    lattice: dict[tuple[int, int], int]
    inv_lattice: dict[int, tuple[int, int]]

    @classmethod
    def build(cls, board: PerfboardModel) -> _PerfIndex:
        hole_ids: list[str] = []
        idx: dict[str, int] = {}
        points: list[tuple[float, float]] = []
        lattice: dict[tuple[int, int], int] = {}
        inv_lattice: dict[int, tuple[int, int]] = {}
        i = 0
        for row in range(1, board.rows + 1):
            for col in range(1, board.cols + 1):
                hid = f"{row}-{col}"
                hole_ids.append(hid)
                idx[hid] = i
                points.append(((col - 1) * board.pitch_mm, (row - 1) * board.pitch_mm))
                lattice[(col, row)] = i
                inv_lattice[i] = (col, row)
                i += 1
        return cls(
            board_id=board.id,
            rows=board.rows,
            cols=board.cols,
            pitch_mm=board.pitch_mm,
            hole_ids=tuple(hole_ids),
            idx=idx,
            points=tuple(points),
            lattice=lattice,
            inv_lattice=inv_lattice,
        )


# --------------------------------------------------------------------------
# Pose
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


def _rotate_offset(x: int, y: int, orientation: int) -> tuple[int, int]:
    """Rotate a lattice-step offset by `orientation` degrees around the origin.

    Duplicated from `app.domain.poses._rotate_offset` (4 lines) rather than
    imported: that module is private to the breadboard placer and importing a
    leading-underscore name across packages is the thing this codebase avoids
    (see `app.domain.validate._is_rail_backed`'s docstring for the same call).
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
    footprint: ThroughHoleFootprint, span: int
) -> tuple[dict[str, RelativeHole], list[RelativeHole]]:
    """Canonical shape for a 2-pin flexible-lead footprint at `span` holes apart.

    Identical to `app.domain.poses._flexible_local_offsets`.
    """
    pin_offsets: dict[str, RelativeHole] = {
        "1": RelativeHole(x=0, y=0),
        "2": RelativeHole(x=span, y=0),
    }
    body_cells: list[RelativeHole] = [RelativeHole(x=dx, y=0) for dx in range(span + 1)]
    return pin_offsets, body_cells


def _mech_cost(span: int | None, flex: FlexibleLeadSpan | None, orientation: int) -> float:
    """Span deviation from preferred + vertical-orientation bump. Identical to
    `app.domain.poses._mech_cost`.
    """
    cost = 0.0
    if span is not None and flex is not None:
        cost += abs(span - flex.preferred_holes) * 1.0
    if orientation in (90, 270):
        cost += 0.5
    return cost


# --------------------------------------------------------------------------
# Rule predicates
# --------------------------------------------------------------------------


def _has_rule(rules: list[PlacementRule], rule_type: type[PlacementRule]) -> bool:
    return any(isinstance(r, rule_type) for r in rules)


def _min_clearance_value(rules: list[PlacementRule]) -> int:
    for r in rules:
        if isinstance(r, PlacementRuleMinClearance):
            return r.value
    return 0


def _check_main_area(cols: list[int], rows: list[int], index: _PerfIndex) -> bool:
    return all(1 <= c <= index.cols for c in cols) and all(1 <= r <= index.rows for r in rows)


def _check_min_clearance(cols: list[int], rows: list[int], value: int, index: _PerfIndex) -> bool:
    """Every occupied cell needs `value` empty neighbours in each cardinal direction
    (or the board edge, which is exempt). Identical logic to `app.domain.poses.
    _check_min_clearance`, bounded by `index.rows`/`index.cols` instead of the
    breadboard's hardcoded 30x10 main area. Only ever called at pose-generation
    time (no other component is placed yet), so it is a pure board-geometry
    check, not a runtime occupancy check — the greedy/local-search collision
    filter handles actual occupancy separately.
    """
    cell_set = set(zip(cols, rows, strict=False))
    for c, r in zip(cols, rows, strict=False):
        for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            empty = 0
            step = 1
            while empty < value:
                nc, nr = c + dc * step, r + dr * step
                if not (1 <= nc <= index.cols and 1 <= nr <= index.rows):
                    break
                if index.lattice.get((nc, nr)) is None:
                    break
                if (nc, nr) in cell_set:
                    step += 1
                    continue
                empty += 1
                step += 1
            if empty < value:
                return False
    return True


def _resolve_cells(
    pin_offsets: dict[str, RelativeHole],
    body_cells: list[RelativeHole],
    orientation: int,
    anchor_col: int,
    anchor_row: int,
    index: _PerfIndex,
) -> tuple[list[tuple[str, int]], list[int], list[int], list[int]] | None:
    """Translate + rotate local offsets onto the lattice; `None` if any cell falls
    off the grid. Mirrors `app.domain.poses._resolve_pin_holes` minus the
    "disabled hole" check (perfboards have none).
    """
    pins: list[tuple[str, int]] = []
    body_idxs: list[int] = []
    cols: list[int] = []
    rows: list[int] = []

    for pin_id, off in pin_offsets.items():
        dx, dy = _rotate_offset(off.x, off.y, orientation)
        col, row = anchor_col + dx, anchor_row + dy
        hole_idx = index.lattice.get((col, row))
        if hole_idx is None:
            return None
        pins.append((pin_id, hole_idx))
        cols.append(col)
        rows.append(row)

    for off in body_cells:
        dx, dy = _rotate_offset(off.x, off.y, orientation)
        col, row = anchor_col + dx, anchor_row + dy
        hole_idx = index.lattice.get((col, row))
        if hole_idx is None:
            return None
        body_idxs.append(hole_idx)
        cols.append(col)
        rows.append(row)

    return pins, body_idxs, cols, rows


# --------------------------------------------------------------------------
# Pose generation (cached per board + footprint)
# --------------------------------------------------------------------------

_POSE_CACHE: dict[tuple[str, str], tuple[Pose, ...]] = {}


def generate_poses(index: _PerfIndex, footprint: ThroughHoleFootprint) -> tuple[Pose, ...]:
    cache_key = (index.board_id, footprint.id)
    cached = _POSE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    rules = list(footprint.placement_rules)
    min_clearance = _min_clearance_value(rules)
    main_area_required = _has_rule(rules, PlacementRuleMainArea)
    # `must-be-on-board-edge` is unused by every registered perfboard footprint
    # today (see `app.domain.perfboards.registry`) — flagged for forward
    # compatibility only, matching `app.domain.poses.generate_poses`.
    _ = _has_rule(rules, PlacementRuleBoardEdge)

    flex = footprint.geometry.flexible_lead_span

    poses: list[Pose] = []
    for (col, row), anchor_idx in index.lattice.items():
        for orientation in footprint.supported_orientations:
            span_list: list[int | None] = (
                [None] if flex is None else list(range(flex.min_holes, flex.max_holes + 1))
            )
            for span in span_list:
                if span is None:
                    pin_offsets_iter = footprint.pin_offsets
                    body_cells_iter = footprint.body_cells
                else:
                    pin_offsets_iter, body_cells_iter = _flexible_local_offsets(footprint, span)

                resolved = _resolve_cells(pin_offsets_iter, body_cells_iter, orientation, col, row, index)
                if resolved is None:
                    continue
                pins, body_idxs, cols, rows = resolved

                if main_area_required and not _check_main_area(cols, rows, index):
                    continue
                if min_clearance > 0 and not _check_min_clearance(cols, rows, min_clearance, index):
                    continue

                occupied_mask = 0
                for hi in body_idxs:
                    occupied_mask |= 1 << hi
                for _pin_id, hi in pins:
                    occupied_mask |= 1 << hi

                mech = _mech_cost(span, flex, orientation)
                sorted_pins = tuple(sorted(pins, key=lambda kv: kv[0]))

                poses.append(
                    Pose(
                        anchor_idx=anchor_idx,
                        orientation=orientation,
                        span=span,
                        pin_idx=sorted_pins,
                        occupied_mask=occupied_mask,
                        body_cells_idx=tuple(body_idxs),
                        mech_cost=mech,
                    )
                )

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


# --------------------------------------------------------------------------
# Placement cost (mirrors `app.domain.cost.placement_cost`)
# --------------------------------------------------------------------------


def _user_facing(footprint: ThroughHoleFootprint) -> bool:
    return any(keyword in footprint.id for keyword in _ACCESSIBLE_FAMILY_KEYWORDS)


def _manhattan(a: tuple[float, float], b: tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _nearest_placed_same_net(
    pin_point: tuple[float, float],
    net_id: str,
    net_of_pin: dict[tuple[str, str], str],
    placed_pin_points: dict[str, tuple[float, float]],
) -> float:
    best = float("inf")
    for key, point in placed_pin_points.items():
        ref, pin = key.split(".", 1)
        if net_of_pin.get((ref, pin)) == net_id:
            best = min(best, _manhattan(pin_point, point))
    return 0.0 if best == float("inf") else best


def _weighted_manhattan_term(
    pose: Pose,
    component_ref: str,
    index: _PerfIndex,
    net_of_pin: dict[tuple[str, str], str],
    placed_pin_points: dict[str, tuple[float, float]],
) -> float:
    total = 0.0
    for pin_id, hole_idx in pose.pin_idx:
        net_id = net_of_pin.get((component_ref, pin_id))
        if net_id is None:
            continue
        total += _nearest_placed_same_net(index.points[hole_idx], net_id, net_of_pin, placed_pin_points)
    return total


def _congestion_term(pose: Pose, occupied_mask: int, index: _PerfIndex) -> float:
    """Occupied-hole count in the pose's body bounding box (±2 cols, ±1 row)."""
    if not pose.body_cells_idx:
        return 0.0
    points = index.points
    body_points = [points[i] for i in pose.body_cells_idx]
    min_x = min(p[0] for p in body_points)
    max_x = max(p[0] for p in body_points)
    min_y = min(p[1] for p in body_points)
    max_y = max(p[1] for p in body_points)
    pad_x = 2.0 * index.pitch_mm
    pad_y = 1.0 * index.pitch_mm
    body_set = set(pose.body_cells_idx)
    busy = 0
    for hole_idx, point in enumerate(points):
        if not (min_x - pad_x <= point[0] <= max_x + pad_x):
            continue
        if not (min_y - pad_y <= point[1] <= max_y + pad_y):
            continue
        if hole_idx in body_set:
            continue
        if (occupied_mask >> hole_idx) & 1:
            busy += 1
    return float(busy)


def _accessibility_term(pose: Pose, footprint: ThroughHoleFootprint, index: _PerfIndex) -> float:
    """1.0 if a user-facing part is wedged away from every board edge.

    Breadboards only check left/right columns (`app.domain.cost.
    _accessibility_term`) because their 10-row main area is already short
    enough that vertical position barely matters. Perfboards can be any
    rows x cols shape, so this checks all four edges, each edge band sized to
    ~15% of that axis (at least one hole).
    """
    if not _user_facing(footprint) or not pose.body_cells_idx:
        return 0.0
    points = index.points
    body_xs = [points[i][0] for i in pose.body_cells_idx]
    body_ys = [points[i][1] for i in pose.body_cells_idx]
    min_x, max_x = min(body_xs), max(body_xs)
    min_y, max_y = min(body_ys), max(body_ys)
    band_x = max(1, round(index.cols * 0.15)) * index.pitch_mm
    band_y = max(1, round(index.rows * 0.15)) * index.pitch_mm
    board_max_x = (index.cols - 1) * index.pitch_mm
    board_max_y = (index.rows - 1) * index.pitch_mm
    near_edge = (
        min_x <= band_x
        or max_x >= board_max_x - band_x
        or min_y <= band_y
        or max_y >= board_max_y - band_y
    )
    return 0.0 if near_edge else 1.0


def _pose_centroid(pose: Pose, index: _PerfIndex) -> tuple[float, float]:
    if not pose.body_cells_idx:
        return (0.0, 0.0)
    xs = [index.points[i][0] for i in pose.body_cells_idx]
    ys = [index.points[i][1] for i in pose.body_cells_idx]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def placement_cost(
    pose: Pose,
    footprint: ThroughHoleFootprint,
    index: _PerfIndex,
    placed_pin_points: dict[str, tuple[float, float]],
    net_of_pin: dict[tuple[str, str], str],
    occupied_mask: int,
    weights: dict[str, float],
    cluster_anchor_point: tuple[float, float] | None = None,
    component_ref: str = "",
) -> float:
    """Weighted placement cost. Same term set and weight keys as
    `app.domain.cost.placement_cost` so `SolverOptions.placement_weights`
    behaves identically on both board families.
    """
    w_dist = weights.get("weightedDistance", 0.0)
    weighted_manhattan = (
        w_dist * _weighted_manhattan_term(pose, component_ref, index, net_of_pin, placed_pin_points)
        if w_dist
        else 0.0
    )

    w_cong = weights.get("congestion", 0.0)
    congestion = w_cong * _congestion_term(pose, occupied_mask, index) if w_cong else 0.0

    w_mech = weights.get("mechanical", 0.0)
    mech = w_mech * pose.mech_cost if w_mech else 0.0

    # criticalRule: always 0; placement rules are hard-rejected during pose generation.
    critical_rule = 0.0

    w_acc = weights.get("accessibility", 0.0)
    accessibility = w_acc * _accessibility_term(pose, footprint, index) if w_acc else 0.0

    w_overlap = weights.get("overlap", 0.0)
    overlap = w_overlap * (1.0 if (occupied_mask & pose.occupied_mask) else 0.0)

    w_cluster = weights.get("cluster", 0.0)
    cluster_pull = 0.0
    if w_cluster and cluster_anchor_point is not None:
        cluster_pull = w_cluster * _manhattan(_pose_centroid(pose, index), cluster_anchor_point)

    return weighted_manhattan + congestion + mech + critical_rule + accessibility + overlap + cluster_pull


# --------------------------------------------------------------------------
# Placer state
# --------------------------------------------------------------------------


@dataclass
class _PlacerState:
    board: PerfboardModel
    index: _PerfIndex
    footprints: dict[str, ThroughHoleFootprint]
    components: list[Component]
    options: SolverOptions

    placements: dict[str, ComponentPlacement] = field(default_factory=dict)
    occupied_mask: int = 0
    placed_pin_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    pose_by_ref: dict[str, Pose] = field(default_factory=dict)
    centroid_by_ref: dict[str, tuple[float, float]] = field(default_factory=dict)
    cluster_anchor_of: dict[str, str] = field(default_factory=dict)


def _pose_to_placement(pose: Pose, component: Component, index: _PerfIndex, locked: bool) -> ComponentPlacement:
    pin_holes = {pin_id: index.hole_ids[hole_idx] for pin_id, hole_idx in pose.pin_idx}
    occupied_set: set[str] = {index.hole_ids[i] for i in pose.body_cells_idx}
    occupied_set.update(index.hole_ids[i] for _, i in pose.pin_idx)
    return ComponentPlacement(
        component_ref=component.ref,
        anchor_hole_id=index.hole_ids[pose.anchor_idx],
        orientation=pose.orientation,  # type: ignore[arg-type]
        span=pose.span,
        pin_holes=pin_holes,
        occupied_hole_ids=sorted(occupied_set),
        locked=locked,
    )


def _centroid(pose: Pose, index: _PerfIndex) -> tuple[float, float]:
    if not pose.body_cells_idx:
        return (0.0, 0.0)
    xs = [index.points[i][0] for i in pose.body_cells_idx]
    ys = [index.points[i][1] for i in pose.body_cells_idx]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _all_holes_for_pose(pose: Pose) -> list[int]:
    seen: set[int] = set(pose.body_cells_idx)
    seen.update(hi for _, hi in pose.pin_idx)
    return sorted(seen)


def _clear_pose_from_state(state: _PlacerState, ref: str) -> None:
    pose = state.pose_by_ref.get(ref)
    if pose is None:
        return
    for i in _all_holes_for_pose(pose):
        state.occupied_mask &= ~(1 << i)
    for k in [k for k in state.placed_pin_points if k.split(".", 1)[0] == ref]:
        del state.placed_pin_points[k]
    state.pose_by_ref.pop(ref, None)
    state.centroid_by_ref.pop(ref, None)
    state.placements.pop(ref, None)


def _apply_pose_to_state(state: _PlacerState, ref: str, pose: Pose, component: Component, locked: bool) -> None:
    state.pose_by_ref[ref] = pose
    for i in _all_holes_for_pose(pose):
        state.occupied_mask |= 1 << i
    for pin_id, hi in pose.pin_idx:
        state.placed_pin_points[f"{ref}.{pin_id}"] = state.index.points[hi]
    state.centroid_by_ref[ref] = _centroid(pose, state.index)
    state.placements[ref] = _pose_to_placement(pose, component, state.index, locked)


def _total_cost(state: _PlacerState, net_of_pin: dict[tuple[str, str], str]) -> float:
    total = 0.0
    for ref, pose in state.pose_by_ref.items():
        component = next(c for c in state.components if c.ref == ref)
        footprint = state.footprints[component.footprint_id]
        anchor_ref = state.cluster_anchor_of.get(ref, "")
        cluster_anchor_point: tuple[float, float] | None = None
        if anchor_ref != ref and anchor_ref and anchor_ref in state.centroid_by_ref:
            cluster_anchor_point = state.centroid_by_ref[anchor_ref]
        total += placement_cost(
            pose,
            footprint,
            state.index,
            state.placed_pin_points,
            net_of_pin,
            state.occupied_mask,
            state.options.placement_weights,
            cluster_anchor_point=cluster_anchor_point,
            component_ref=ref,
        )
    return total


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def _edge_or_clearance(footprint: ThroughHoleFootprint | None) -> bool:
    if footprint is None:
        return False
    return any(r.type in ("must-be-on-board-edge", "min-clearance-holes") for r in footprint.placement_rules)


def _is_dip(footprint: ThroughHoleFootprint | None) -> bool:
    return footprint is not None and footprint.id.startswith("DIP-")


def _approx_pose_count(footprint: ThroughHoleFootprint | None) -> int:
    if footprint is None:
        return 0
    orientations = len(footprint.supported_orientations)
    flex = footprint.geometry.flexible_lead_span
    spans = 1 if flex is None else (flex.max_holes - flex.min_holes + 1)
    return orientations * spans


def _build_order(
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
    locked_refs: set[str],
) -> list[str]:
    locked_order = sorted([c.ref for c in components if c.ref in locked_refs])
    edge_order = sorted(
        [
            c.ref
            for c in components
            if c.ref not in locked_refs and _edge_or_clearance(footprints.get(c.footprint_id))
        ]
    )
    dip_order = sorted(
        [
            c.ref
            for c in components
            if c.ref not in locked_refs and c.ref not in edge_order and _is_dip(footprints.get(c.footprint_id))
        ]
    )
    rest = [
        c
        for c in components
        if c.ref not in locked_refs and c.ref not in edge_order and c.ref not in dip_order
    ]
    rest.sort(key=lambda c: (_approx_pose_count(footprints.get(c.footprint_id)), c.ref))
    rest_order = [c.ref for c in rest]
    return locked_order + edge_order + dip_order + rest_order


def _stable_reorder_by_cluster(order: list[str], cluster_by_ref: dict[str, Cluster]) -> list[str]:
    """Move each non-anchor cluster member to immediately follow its anchor.

    Identical to `app.domain.place._stable_reorder_by_cluster` (generic over
    `Cluster`, not board-specific) — duplicated rather than imported since
    that name is private to the breadboard placer module.
    """
    out: list[str] = list(order)
    for ref in list(out):
        cluster = cluster_by_ref.get(ref)
        if cluster is None or cluster.anchor_ref != ref:
            continue
        tail = [m for m in cluster.member_refs if m != ref and m in out]
        if not tail:
            continue
        try:
            anchor_idx = out.index(ref)
        except ValueError:
            continue
        for m in tail:
            try:
                out.remove(m)
            except ValueError:
                continue
        insert_at = anchor_idx + 1
        for m in tail:
            out.insert(insert_at, m)
            insert_at += 1
    return out


# --------------------------------------------------------------------------
# Locked placement seeding
# --------------------------------------------------------------------------


def _seed_locked_placements(state: _PlacerState, initial_layout: TraceLayout | None) -> set[str]:
    locked: set[str] = set()
    if initial_layout is None:
        return locked
    for placement in initial_layout.placements:
        if not placement.locked:
            continue
        component = next((c for c in state.components if c.ref == placement.component_ref), None)
        if component is None:
            continue
        footprint = state.footprints.get(component.footprint_id)
        if footprint is None:
            continue
        anchor_idx = state.index.idx.get(placement.anchor_hole_id)
        if anchor_idx is None:
            continue
        col, row = state.index.inv_lattice[anchor_idx]

        pin_idx: list[tuple[str, int]] = []
        for pid in footprint.pin_offsets:
            hid = placement.pin_holes.get(pid)
            if hid is None:
                continue
            pin_idx.append((pid, state.index.idx[hid]))

        body_idx: list[int] = []
        for off in footprint.body_cells:
            hi = state.index.lattice.get((col + off.x, row + off.y))
            if hi is None:
                continue
            body_idx.append(hi)
        if not body_idx:
            body_idx = [state.index.idx[h] for h in placement.occupied_hole_ids if h in state.index.idx]

        occupied_mask = 0
        for hi in body_idx:
            occupied_mask |= 1 << hi
        for _, hi in pin_idx:
            occupied_mask |= 1 << hi

        pose = Pose(
            anchor_idx=anchor_idx,
            orientation=placement.orientation,
            span=placement.span,
            pin_idx=tuple(sorted(pin_idx, key=lambda kv: kv[0])),
            occupied_mask=occupied_mask,
            body_cells_idx=tuple(body_idx),
            mech_cost=0.0,
        )
        state.placements[placement.component_ref] = placement
        state.pose_by_ref[placement.component_ref] = pose
        for i in body_idx:
            state.occupied_mask |= 1 << i
        for pid, hi in pin_idx:
            state.placed_pin_points[f"{placement.component_ref}.{pid}"] = state.index.points[hi]
        state.centroid_by_ref[placement.component_ref] = _centroid(pose, state.index)
        locked.add(placement.component_ref)
    return locked


# --------------------------------------------------------------------------
# Greedy placement
# --------------------------------------------------------------------------


def _record_rejection(trace: SolverTrace, ref: str, reason: str, detail: str) -> None:
    if len(trace.rejections) >= _REJECTION_CAP:
        return
    trace.rejections.append(TraceRejection(component_ref=ref, reason=reason, detail=detail or None))


def _greedy_pass(
    state: _PlacerState,
    order: list[str],
    locked_refs: set[str],
    net_of_pin: dict[tuple[str, str], str],
    trace: SolverTrace,
) -> list[str]:
    unplaced: list[str] = []
    for ref in order:
        component = next((c for c in state.components if c.ref == ref), None)
        if component is None:
            continue
        footprint = state.footprints.get(component.footprint_id)
        if footprint is None:
            unplaced.append(ref)
            _record_rejection(trace, ref, "unknown_footprint", "")
            continue

        if ref in locked_refs:
            placed_pose = state.pose_by_ref.get(ref)
            if placed_pose is None:
                unplaced.append(ref)
                _record_rejection(trace, ref, "no_valid_pose", "0 candidates all rejected")
                continue
            locked_anchor_ref = state.cluster_anchor_of.get(ref, "")
            locked_cluster_point: tuple[float, float] | None = None
            if locked_anchor_ref != ref and locked_anchor_ref and locked_anchor_ref in state.centroid_by_ref:
                locked_cluster_point = state.centroid_by_ref[locked_anchor_ref]
            cost = placement_cost(
                placed_pose,
                footprint,
                state.index,
                state.placed_pin_points,
                net_of_pin,
                state.occupied_mask,
                state.options.placement_weights,
                cluster_anchor_point=locked_cluster_point,
                component_ref=ref,
            )
            trace.pose_choices.append(
                PoseChoice(
                    component_ref=ref,
                    anchor_hole_id=state.index.hole_ids[placed_pose.anchor_idx],
                    orientation=placed_pose.orientation,  # type: ignore[arg-type]
                    span=placed_pose.span,
                    cost=cost,
                )
            )
            continue

        candidates = generate_poses(state.index, footprint)
        valid = [p for p in candidates if not (p.occupied_mask & state.occupied_mask)]
        if not valid:
            unplaced.append(ref)
            _record_rejection(trace, ref, "no_valid_pose", f"{len(candidates)} candidates all rejected")
            continue

        anchor_ref_for_member = state.cluster_anchor_of.get(ref, "")
        cluster_anchor_point: tuple[float, float] | None = None
        if (
            anchor_ref_for_member != ref
            and anchor_ref_for_member
            and anchor_ref_for_member in state.centroid_by_ref
        ):
            cluster_anchor_point = state.centroid_by_ref[anchor_ref_for_member]

        best: tuple[float, str, int, int, Pose] | None = None
        for pose in valid:
            cost = placement_cost(
                pose,
                footprint,
                state.index,
                state.placed_pin_points,
                net_of_pin,
                state.occupied_mask,
                state.options.placement_weights,
                cluster_anchor_point=cluster_anchor_point,
                component_ref=ref,
            )
            key = (
                cost,
                state.index.hole_ids[pose.anchor_idx],
                pose.orientation,
                -1 if pose.span is None else pose.span,
            )
            if best is None or key < best[:4]:
                best = (key[0], key[1], key[2], key[3], pose)
        assert best is not None
        best_cost = best[0]
        chosen_pose = best[4]
        _apply_pose_to_state(state, ref, chosen_pose, component, locked=False)
        trace.pose_choices.append(
            PoseChoice(
                component_ref=ref,
                anchor_hole_id=state.index.hole_ids[chosen_pose.anchor_idx],
                orientation=chosen_pose.orientation,  # type: ignore[arg-type]
                span=chosen_pose.span,
                cost=best_cost,
            )
        )

    return unplaced


# --------------------------------------------------------------------------
# Local search moves
# --------------------------------------------------------------------------

_MOVE_NAMES: tuple[str, ...] = ("translate", "rotate", "span", "swap", "relocate_cluster")


def _try_translate(state: _PlacerState, ref: str, rng: random.Random) -> bool:
    component = next(c for c in state.components if c.ref == ref)
    footprint = state.footprints[component.footprint_id]
    candidates = generate_poses(state.index, footprint)
    current = state.pose_by_ref[ref]
    other_anchors = [
        p
        for p in candidates
        if p.anchor_idx != current.anchor_idx
        and not (p.occupied_mask & (state.occupied_mask & ~current.occupied_mask))
    ]
    if not other_anchors:
        return False
    new_pose = rng.choice(other_anchors)
    _clear_pose_from_state(state, ref)
    _apply_pose_to_state(state, ref, new_pose, component, locked=False)
    return True


def _try_rotate(state: _PlacerState, ref: str, rng: random.Random) -> bool:
    component = next(c for c in state.components if c.ref == ref)
    footprint = state.footprints[component.footprint_id]
    current = state.pose_by_ref[ref]
    candidates = generate_poses(state.index, footprint)
    same_anchor = [
        p
        for p in candidates
        if p.anchor_idx == current.anchor_idx
        and p.orientation != current.orientation
        and not (p.occupied_mask & (state.occupied_mask & ~current.occupied_mask))
    ]
    if not same_anchor:
        return False
    new_pose = rng.choice(same_anchor)
    _clear_pose_from_state(state, ref)
    _apply_pose_to_state(state, ref, new_pose, component, locked=False)
    return True


def _try_span(state: _PlacerState, ref: str, rng: random.Random) -> bool:
    component = next(c for c in state.components if c.ref == ref)
    footprint = state.footprints[component.footprint_id]
    flex = footprint.geometry.flexible_lead_span
    if flex is None:
        return False
    current = state.pose_by_ref[ref]
    if current.span is None:
        return False
    delta = rng.choice((-1, 1))
    new_span = current.span + delta
    if new_span < flex.min_holes or new_span > flex.max_holes:
        return False
    candidates = generate_poses(state.index, footprint)
    same_anchor = [
        p
        for p in candidates
        if p.anchor_idx == current.anchor_idx
        and p.orientation == current.orientation
        and p.span == new_span
        and not (p.occupied_mask & (state.occupied_mask & ~current.occupied_mask))
    ]
    if not same_anchor:
        return False
    new_pose = same_anchor[0]
    _clear_pose_from_state(state, ref)
    _apply_pose_to_state(state, ref, new_pose, component, locked=False)
    return True


def _try_swap(state: _PlacerState, ref: str, rng: random.Random) -> bool:
    component = next(c for c in state.components if c.ref == ref)
    partner_candidates = [
        r
        for r in state.pose_by_ref
        if r != ref and next(c for c in state.components if c.ref == r).footprint_id == component.footprint_id
    ]
    if not partner_candidates:
        return False
    other_ref = rng.choice(partner_candidates)
    pose_a = state.pose_by_ref[ref]
    pose_b = state.pose_by_ref[other_ref]
    rest_mask = state.occupied_mask & ~pose_a.occupied_mask & ~pose_b.occupied_mask
    if (pose_a.occupied_mask & rest_mask) or (pose_b.occupied_mask & rest_mask):
        return False
    component_b = next(c for c in state.components if c.ref == other_ref)
    _clear_pose_from_state(state, ref)
    _clear_pose_from_state(state, other_ref)
    _apply_pose_to_state(state, ref, pose_b, component, locked=False)
    _apply_pose_to_state(state, other_ref, pose_a, component_b, locked=False)
    return True


def _translate_pose(index: _PerfIndex, pose: Pose, dc: int, dr: int) -> Pose | None:
    col, row = index.inv_lattice[pose.anchor_idx]
    new_anchor = index.lattice.get((col + dc, row + dr))
    if new_anchor is None:
        return None
    new_pin_idx: list[tuple[str, int]] = []
    for pin_id, hi in pose.pin_idx:
        cc, rr = index.inv_lattice[hi]
        nh = index.lattice.get((cc + dc, rr + dr))
        if nh is None:
            return None
        new_pin_idx.append((pin_id, nh))
    new_body_idx: list[int] = []
    for hi in pose.body_cells_idx:
        cc, rr = index.inv_lattice[hi]
        nh = index.lattice.get((cc + dc, rr + dr))
        if nh is None:
            return None
        new_body_idx.append(nh)
    occupied = 0
    for nh in new_body_idx:
        occupied |= 1 << nh
    for _, nh in new_pin_idx:
        occupied |= 1 << nh
    return Pose(
        anchor_idx=new_anchor,
        orientation=pose.orientation,
        span=pose.span,
        pin_idx=tuple(sorted(new_pin_idx, key=lambda kv: kv[0])),
        occupied_mask=occupied,
        body_cells_idx=tuple(new_body_idx),
        mech_cost=pose.mech_cost,
    )


def _try_relocate_cluster(state: _PlacerState, ref: str, rng: random.Random) -> bool:
    anchor_ref = state.cluster_anchor_of.get(ref, "")
    if not anchor_ref or anchor_ref == ref or anchor_ref not in state.pose_by_ref:
        return False
    members = [r for r in state.pose_by_ref if state.cluster_anchor_of.get(r, "") == anchor_ref]
    if not members:
        return False
    anchor_pose = state.pose_by_ref[anchor_ref]
    anchor_component = next(c for c in state.components if c.ref == anchor_ref)
    candidates = generate_poses(state.index, state.footprints[anchor_component.footprint_id])
    new_anchor_candidates = [
        p
        for p in candidates
        if p.anchor_idx != anchor_pose.anchor_idx
        and not (p.occupied_mask & (state.occupied_mask & ~anchor_pose.occupied_mask))
    ]
    if not new_anchor_candidates:
        return False
    new_anchor_pose = rng.choice(new_anchor_candidates)
    old_col, old_row = state.index.inv_lattice[anchor_pose.anchor_idx]
    new_col, new_row = state.index.inv_lattice[new_anchor_pose.anchor_idx]
    dc, dr = new_col - old_col, new_row - old_row

    translated: list[tuple[str, Pose, Component]] = []
    for member_ref in members:
        member_pose = state.pose_by_ref[member_ref]
        new_member = _translate_pose(state.index, member_pose, dc, dr)
        if new_member is None:
            return False
        comp = next(c for c in state.components if c.ref == member_ref)
        translated.append((member_ref, new_member, comp))

    rest_mask = state.occupied_mask
    for _, p, _ in translated:
        rest_mask &= ~p.occupied_mask
    for _, p, _ in translated:
        if p.occupied_mask & rest_mask:
            return False

    for member_ref, new_pose, comp in translated:
        _clear_pose_from_state(state, member_ref)
        _apply_pose_to_state(state, member_ref, new_pose, comp, locked=False)
    return True


# --------------------------------------------------------------------------
# Local search
# --------------------------------------------------------------------------


def _local_search(
    state: _PlacerState,
    locked_refs: set[str],
    net_of_pin: dict[tuple[str, str], str],
    rng: random.Random,
    trace: SolverTrace,
    initial_cost: float,
) -> float:
    current_cost = initial_cost
    placed_refs = [r for r in state.pose_by_ref if r not in locked_refs]
    if not placed_refs:
        return current_cost

    iter_scores: list[float] = [current_cost]
    max_iter = max(1, state.options.max_local_search_iterations)

    for i in range(max_iter):
        ref = rng.choice(placed_refs)
        move_name = rng.choice(_MOVE_NAMES)
        if move_name == "swap":
            component = next(c for c in state.components if c.ref == ref)
            partner_pool = [
                r
                for r in state.pose_by_ref
                if r != ref
                and next(c for c in state.components if c.ref == r).footprint_id == component.footprint_id
            ]
            if not partner_pool:
                continue

        mask_before = state.occupied_mask
        placements_before = dict(state.placements)
        points_before = dict(state.placed_pin_points)
        centroids_before = dict(state.centroid_by_ref)
        poses_before = dict(state.pose_by_ref)

        if move_name == "translate":
            moved = _try_translate(state, ref, rng)
        elif move_name == "rotate":
            moved = _try_rotate(state, ref, rng)
        elif move_name == "span":
            moved = _try_span(state, ref, rng)
        elif move_name == "swap":
            moved = _try_swap(state, ref, rng)
        elif move_name == "relocate_cluster":
            moved = _try_relocate_cluster(state, ref, rng)
        else:
            moved = False

        if not moved:
            state.occupied_mask = mask_before
            state.placements = placements_before
            state.placed_pin_points = points_before
            state.centroid_by_ref = centroids_before
            state.pose_by_ref = poses_before
            continue

        new_cost = _total_cost(state, net_of_pin)
        if new_cost < current_cost:
            current_cost = new_cost
        else:
            state.occupied_mask = mask_before
            state.placements = placements_before
            state.placed_pin_points = points_before
            state.centroid_by_ref = centroids_before
            state.pose_by_ref = poses_before

        if (i + 1) % 50 == 0:
            iter_scores.append(current_cost)

    trace.iteration_scores.extend(iter_scores)
    return current_cost


# --------------------------------------------------------------------------
# Top-level entry point
# --------------------------------------------------------------------------


def place(
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: TraceLayout | None = None,
) -> PlacementResult:
    """Place every component of the netlist onto a perfboard's plain grid.

    Same greedy + local-search + restart structure as `app.domain.place.place`;
    returns the attempt with the fewest unplaced components, then lowest cost.
    """
    start = time.perf_counter()
    index = _PerfIndex.build(board)

    net_of_pin: dict[tuple[str, str], str] = {}
    for net in nets:
        for pin in net.pins:
            key = (pin.component_ref, pin.pin)
            net_of_pin.setdefault(key, net.id)

    clusters = build_clusters(components, nets, footprints)
    cluster_anchor_of: dict[str, str] = {}
    cluster_by_ref: dict[str, Cluster] = {}
    for cluster in clusters:
        anchor_ref = cluster.anchor_ref or cluster.id
        cluster_by_ref[anchor_ref] = cluster
        for m in cluster.member_refs:
            cluster_anchor_of[m] = anchor_ref

    best: tuple[float, int, _PlacerState, list[str], SolverTrace] | None = None
    restarts = max(1, options.max_placement_restarts)

    for attempt in range(restarts):
        state = _PlacerState(
            board=board,
            index=index,
            footprints=footprints,
            components=components,
            options=options,
            cluster_anchor_of=dict(cluster_anchor_of),
        )

        locked_refs = _seed_locked_placements(state, initial_layout)

        trace = SolverTrace(
            seed=options.seed,
            placement_order=[],
            pose_choices=[],
            rejections=[],
            failed_nets=[],
            ripups=[],
            iteration_scores=[],
            phase_timings_ms={},
        )

        base_order = _build_order(components, footprints, locked_refs)
        order = _stable_reorder_by_cluster(base_order, cluster_by_ref)
        trace.placement_order = list(order)

        unplaced = _greedy_pass(state, order, locked_refs, net_of_pin, trace)

        initial_cost = _total_cost(state, net_of_pin) if not unplaced else float("inf")
        rng = random.Random(options.seed * 1000 + attempt)
        _local_search(state, locked_refs, net_of_pin, rng, trace, initial_cost)

        total_cost = _total_cost(state, net_of_pin)
        n_unplaced = len(unplaced)
        rank = (n_unplaced, total_cost)
        if best is None or rank < (best[1], best[0]):
            best = (total_cost, n_unplaced, state, unplaced, trace)

    assert best is not None
    total_cost, _n_unplaced, final_state, unplaced, trace = best
    placements = [final_state.placements[r] for r in sorted(final_state.placements)]
    trace.phase_timings_ms["place"] = round((time.perf_counter() - start) * 1000.0, 3)

    return PlacementResult(
        placements=placements,
        unplaced=unplaced,
        trace=trace,
        cost=total_cost,
    )
