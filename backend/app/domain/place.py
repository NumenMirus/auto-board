"""Greedy + hill-climbing placement (main spec §6.4).

The placer builds a placement for every component on the board, recording the
``ComponentPlacement`` chosen for each ref, the union of holes it covers, and the
already-placed pin coordinates used by the cost function.

Pipeline:

1. Build a ``net_of_pin`` lookup from the netlist.
2. Build placement clusters for ordering.
3. Order components: locked first, then board-edge / clearance-constrained (CONN by
   convention), then DIP, then the rest sorted by pose-count ascending (approximate;
   see step-3 comment).
4. Greedy pass: for each component, evaluate every valid (non-colliding) pose, score
   with :func:`app.domain.cost.placement_cost`, pick the minimum. Locked components
   copy through from ``initial_layout`` verbatim.
5. Local search: hill-climbing on the random move set of main spec §6.4, accepting
   only strict improvements, recording ``iteration_scores`` every 50 iterations.
6. Restart loop: the greedy + local-search pair is repeated
   ``options.max_placement_restarts`` times; the attempt with the fewest unplaced and
   the lowest cost wins.

The result is a :class:`app.domain.models.PlacementResult` with a :class:`SolverTrace`
suitable for inspection in the editor / smoke test.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from app.domain.cluster import Cluster, build_clusters
from app.domain.cost import placement_cost
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Layout,
    Net,
    PlacementResult,
    PoseChoice,
    SolverOptions,
    SolverTrace,
    TraceRejection,
)
from app.domain.poses import Pose, generate_poses

__all__ = ["place"]


# Cap on rejection entries recorded in the trace; main spec says 500.
_REJECTION_CAP: int = 500


# --------------------------------------------------------------------------
# Internal placer state (a small bundle that mutates as components are placed).
# --------------------------------------------------------------------------


@dataclass
class _PlacerState:
    board: BreadboardModel
    index: BoardIndex
    footprints: dict[str, BreadboardFootprint]
    components: list[Component]
    options: SolverOptions

    placements: dict[str, ComponentPlacement] = field(default_factory=dict)
    occupied_mask: int = 0
    placed_pin_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    pose_by_ref: dict[str, Pose] = field(default_factory=dict)
    centroid_by_ref: dict[str, tuple[float, float]] = field(default_factory=dict)
    # ref -> anchor ref; populated by _attach_cluster.
    cluster_anchor_of: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Pose -> ComponentPlacement
# --------------------------------------------------------------------------


def _pose_to_placement(
    pose: Pose,
    component: Component,
    index: BoardIndex,
    locked: bool,
) -> ComponentPlacement:
    pin_holes = {pin_id: index.hole_ids[hole_idx] for pin_id, hole_idx in pose.pin_idx}
    occupied_set: set[str] = {index.hole_ids[i] for i in pose.body_cells_idx}
    occupied_set.update(index.hole_ids[i] for _, i in pose.pin_idx)
    return ComponentPlacement(
        component_ref=component.ref,
        anchor_hole_id=index.hole_ids[pose.anchor_idx],
        orientation=pose.orientation,
        span=pose.span,
        pin_holes=pin_holes,
        occupied_hole_ids=sorted(occupied_set),
        locked=locked,
    )


def _centroid(pose: Pose, index: BoardIndex) -> tuple[float, float]:
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


def _apply_pose_to_state(
    state: _PlacerState, ref: str, pose: Pose, component: Component, locked: bool
) -> None:
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
# Lattice helpers (cached by BoardIndex identity)
# --------------------------------------------------------------------------


# id(index) -> {(col, row): hole_idx}
_LATTICE_INV: dict[int, dict[tuple[int, int], int]] = {}
# id(index) -> {hole_idx: (col, row)}
_HOLE_TO_LATTICE: dict[int, dict[int, tuple[int, int]]] = {}


def _lattice_inv(index: BoardIndex) -> dict[tuple[int, int], int]:
    inv = _LATTICE_INV.get(id(index))
    if inv is None:
        inv = {(c, r): hi for (c, r), hi in index.lattice.items()}
        _LATTICE_INV[id(index)] = inv
    return inv


def _hole_to_lattice(index: BoardIndex) -> dict[int, tuple[int, int]]:
    cache_key = id(index)
    hole_map = _HOLE_TO_LATTICE.get(cache_key)
    if hole_map is None:
        hole_map = {hi: (c, r) for (c, r), hi in index.lattice.items()}
        _HOLE_TO_LATTICE[cache_key] = hole_map
    return hole_map


def _col_row(index: BoardIndex, hole_idx: int) -> tuple[int, int]:
    for (col, row), hi in _lattice_inv(index).items():
        if hi == hole_idx:
            return (col, row)
    raise KeyError(f"hole {hole_idx} not in lattice")


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def _edge_or_clearance(footprint: BreadboardFootprint | None) -> bool:
    if footprint is None:
        return False
    return any(r.type in ("must-be-on-board-edge", "min-clearance-holes") for r in footprint.placement_rules)


def _is_dip(footprint: BreadboardFootprint | None) -> bool:
    return footprint is not None and footprint.id.startswith("DIP-")


def _approx_pose_count(footprint: BreadboardFootprint | None) -> int:
    """Approximate pose count used only for ordering. Building the real pose list
    requires a ``BoardIndex``; we don't have one here. Stable proxy: orientations x
    spans. Components with more flexible spans sort first so they're placed last
    (the spec's heuristic is "fewest options first", but we don't have the index).

    An unknown footprint (``None``) sorts first (proxy count 0) — it has no valid
    poses at all, so ordering among these components is moot; `_greedy_pass`
    rejects them with `UNKNOWN_FOOTPRINT`-equivalent handling regardless of order.
    """
    if footprint is None:
        return 0
    orientations = len(footprint.supported_orientations)
    flex = footprint.geometry.flexible_lead_span
    spans = 1 if flex is None else (flex.max_holes - flex.min_holes + 1)
    return orientations * spans


def _build_order(
    components: list[Component],
    footprints: dict[str, BreadboardFootprint],
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
            if c.ref not in locked_refs
            and c.ref not in edge_order
            and _is_dip(footprints.get(c.footprint_id))
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
    """Move each non-anchor cluster member to immediately follow its anchor in
    ``order``. Stable: existing relative order of unaffected refs is preserved.
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


def _seed_locked_placements(state: _PlacerState, initial_layout: Layout | None) -> set[str]:
    """Copy locked placements from ``initial_layout`` into ``state``.

    Reconstructs a minimal :class:`Pose` from the recorded anchor/orientation/span so
    local search and the cost function see the locked footprint's body.
    Returns the set of locked refs.
    """
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
        anchor_col_row: tuple[int, int] | None = None
        for (col, row), hidx in state.index.lattice.items():
            if hidx == anchor_idx:
                anchor_col_row = (col, row)
                break
        if anchor_col_row is None:
            continue
        col, row = anchor_col_row
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
            # Fall back to the recorded occupied holes.
            body_idx = [state.index.idx[h] for h in placement.occupied_hole_ids if h in state.index.idx]
        occupied_mask = 0
        for hi in body_idx:
            occupied_mask |= 1 << hi
        for _, hi in pin_idx:
            occupied_mask |= 1 << hi
        pos = Pose(
            anchor_idx=anchor_idx,
            orientation=placement.orientation,
            span=placement.span,
            pin_idx=tuple(sorted(pin_idx, key=lambda kv: kv[0])),
            occupied_mask=occupied_mask,
            body_cells_idx=tuple(body_idx),
            mech_cost=0.0,
        )
        state.placements[placement.component_ref] = placement
        state.pose_by_ref[placement.component_ref] = pos
        for i in body_idx:
            state.occupied_mask |= 1 << i
        for pid, hi in pin_idx:
            state.placed_pin_points[f"{placement.component_ref}.{pid}"] = state.index.points[hi]
        state.centroid_by_ref[placement.component_ref] = _centroid(pos, state.index)
        locked.add(placement.component_ref)
    return locked


# --------------------------------------------------------------------------
# Greedy placement
# --------------------------------------------------------------------------


def _greedy_pass(
    state: _PlacerState,
    order: list[str],
    locked_refs: set[str],
    net_of_pin: dict[tuple[str, str], str],
    trace: SolverTrace,
) -> list[str]:
    """Run the greedy placement pass in the given order. Returns the unplaced list."""
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
                    orientation=placed_pose.orientation,
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
                orientation=chosen_pose.orientation,
                span=chosen_pose.span,
                cost=best_cost,
            )
        )

    return unplaced


def _record_rejection(trace: SolverTrace, ref: str, reason: str, detail: str) -> None:
    if len(trace.rejections) >= _REJECTION_CAP:
        return
    trace.rejections.append(TraceRejection(component_ref=ref, reason=reason, detail=detail or None))


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


def _translate_pose(index: BoardIndex, pose: Pose, dc: int, dr: int) -> Pose | None:
    """Return ``pose`` translated by ``(dc, dr)`` lattice steps, or None if invalid."""
    inv = _lattice_inv(index)
    hole_map = _hole_to_lattice(index)
    col, row = hole_map[pose.anchor_idx]
    new_col, new_row = col + dc, row + dr
    new_anchor = inv.get((new_col, new_row))
    if new_anchor is None:
        return None
    new_pin_idx: list[tuple[str, int]] = []
    for pin_id, hi in pose.pin_idx:
        cc, rr = hole_map[hi]
        nh = inv.get((cc + dc, rr + dr))
        if nh is None or not index.enabled[nh]:
            return None
        new_pin_idx.append((pin_id, nh))
    new_body_idx: list[int] = []
    for hi in pose.body_cells_idx:
        cc, rr = hole_map[hi]
        nh = inv.get((cc + dc, rr + dr))
        if nh is None or not index.enabled[nh]:
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
    """Move a whole non-anchor cluster together by the same translation delta."""
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
    old_col, old_row = _col_row(state.index, anchor_pose.anchor_idx)
    new_col, new_row = _col_row(state.index, new_anchor_pose.anchor_idx)
    dc, dr = new_col - old_col, new_row - old_row

    # Translate each cluster member; reject the whole move if any leaves the board.
    translated: list[tuple[str, Pose, Component]] = []
    for member_ref in members:
        member_pose = state.pose_by_ref[member_ref]
        new_member = _translate_pose(state.index, member_pose, dc, dr)
        if new_member is None:
            return False
        comp = next(c for c in state.components if c.ref == member_ref)
        translated.append((member_ref, new_member, comp))
    # Reject if any translated member collides with another placed pose.
    rest_mask = state.occupied_mask
    for _, p, _ in translated:
        rest_mask &= ~p.occupied_mask
    for _, p, _ in translated:
        if p.occupied_mask & rest_mask:
            return False
    # Apply.
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
    """Hill-climb for ``options.max_local_search_iterations``. Accepts strict improvements only."""
    current_cost = initial_cost
    placed_refs = [r for r in state.pose_by_ref if r not in locked_refs]
    if not placed_refs:
        return current_cost

    iter_scores: list[float] = [current_cost]
    max_iter = max(1, state.options.max_local_search_iterations)

    for i in range(max_iter):
        ref = rng.choice(placed_refs)
        move_name = rng.choice(_MOVE_NAMES)
        affected = {ref}
        if move_name == "swap":
            component = next(c for c in state.components if c.ref == ref)
            partner_pool = [
                r
                for r in state.pose_by_ref
                if r != ref
                and next(c for c in state.components if c.ref == r).footprint_id == component.footprint_id
            ]
            if partner_pool:
                affected.add(rng.choice(partner_pool))
            else:
                continue
        elif move_name == "relocate_cluster":
            anchor_ref = state.cluster_anchor_of.get(ref, "")
            if anchor_ref and anchor_ref != ref:
                affected.update(
                    r for r in state.pose_by_ref if state.cluster_anchor_of.get(r, "") == anchor_ref
                )

        # Snapshot the state we may mutate.
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
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: Layout | None = None,
) -> PlacementResult:
    """Place every component of the netlist onto the board.

    Runs the greedy pass followed by local search, repeated up to
    ``options.max_placement_restarts`` times; returns the best attempt (fewest
    unplaced components, then lowest cost).
    """
    start = time.perf_counter()

    net_of_pin: dict[tuple[str, str], str] = {}
    for net in nets:
        for pin in net.pins:
            key = (pin.component_ref, pin.pin)
            net_of_pin.setdefault(key, net.id)

    clusters = build_clusters(components, nets, footprints)
    cluster_anchor_of: dict[str, str] = {}
    cluster_by_ref: dict[str, Cluster] = {}
    for cluster in clusters:
        # `cluster.anchor_ref` is typed Optional for forward compatibility, but every
        # cluster built by build_clusters today has an anchor (rule (e) makes singleton
        # anchors out of every component).
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
