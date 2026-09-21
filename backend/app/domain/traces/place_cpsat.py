"""Global CP-SAT placer for perfboards.

Reuses the canonical pose enumeration from :mod:`app.domain.traces.place`
(``generate_poses`` + the ``_POSE_CACHE``) and the existing trace router
(:mod:`app.domain.traces.route`). Picks one pose per component subject to
exact hole-occupancy constraints and a routing-aware proxy objective, routes
a small set of diverse candidates, and returns the best fully routed one.

Activation: ``SolverOptions.placement_engine == "cpsat"``.

The legacy single-pass placer is preserved as
:func:`app.domain.traces.place.place_greedy` (also reachable as ``place``);
the dispatcher in :mod:`app.domain.traces.solve` routes between the two
engines based on the option value.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from app.domain.cluster import build_clusters
from app.domain.errors import SolverCancelled, SolverTimeout
from app.domain.models import (
    Component,
    ComponentPlacement,
    Diagnostic,
    FootprintGeometry,
    Net,
    Orientation,
    PerfboardModel,
    PlacementResult,
    PoseChoice,
    SolverOptions,
    SolverTrace,
    ThroughHoleFootprint,
    TraceLayout,
    TraceRejection,
)
from app.domain.traces import maze, route as trace_route
from app.domain.traces.place import (
    Pose,
    _PerfIndex,
    _flexible_local_offsets,
    _mech_cost,
    _resolve_cells,
    _rotate_offset,
    generate_poses,
)
from app.domain.traces.place import place_greedy
from app.domain.traces.validate import validate_layout

__all__ = [
    "CandidatePose",
    "CpsatWeights",
    "PlacementObjectiveBreakdown",
    "PresetBudget",
    "build_candidate_poses",
    "build_cpsat_model",
    "add_objective_terms",
    "solve_cpsat_placement",
]


# --------------------------------------------------------------------------
# Scaling, weights, presets
# --------------------------------------------------------------------------


_MILLIMETRE_SCALE: int = 100  # 1 mm == 100 integer units (objective is in 1/100 mm)
_BIN_ROWS: int = 3
_BIN_COLS: int = 3
_HOT_BIN_THRESHOLD: int = 3  # bin becomes "hot" once >= N components touch it


@dataclass(frozen=True, slots=True)
class CpsatWeights:
    """Integer coefficients for the soft objective terms.

    All terms share the millimetre-scaled unit (``_MILLIMETRE_SCALE``), so
    ``net=4`` means 0.04 mm of Manhattan distance per unit of net length.
    Tweak in ``DEFAULT_CPSAT_WEIGHTS``; presets keep these values fixed
    because only wall-time / candidate caps vary between presets.
    """

    net: int = 4
    cluster: int = 3
    decoupler: int = 24  # 8x cluster, applied only to bypass caps
    compactness: int = 1
    edge: int = 10
    orientation: int = 1
    congestion: int = 2
    mechanical: int = 1


DEFAULT_CPSAT_WEIGHTS: CpsatWeights = CpsatWeights()


@dataclass(frozen=True, slots=True)
class PresetBudget:
    """Wall-time budget + candidate caps for a solver preset."""

    time_limit_ms: int
    candidate_limit: int
    solution_count: int


_PRESET_BUDGET: Mapping[str, PresetBudget] = {
    "fast": PresetBudget(1500, 50, 3),
    "balanced": PresetBudget(3000, 100, 5),
    "quality": PresetBudget(10000, 150, 8),
}


# --------------------------------------------------------------------------
# Candidate pose
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidatePose:
    """One legal pose for one component.

    Holds absolute board-relative geometry in lattice-step units except
    where noted, plus pre-computed integer coefficients the CP-SAT
    objective consumes. Keeping coefficients integer at construction
    time means the objective is a sum of ``IntVar * int`` products — the
    safest way to drive CP-SAT deterministically.
    """

    component_ref: str
    pose_id: int
    anchor_idx: int
    orientation: Orientation
    span: int | None
    pin_holes: tuple[tuple[str, str], ...]  # (pin_id, "row-col")
    body_hole_ids: tuple[str, ...]
    occupied_hole_ids: frozenset[str]  # pin ∪ body, absolute ids
    centroid_q: tuple[int, int]  # (col_q, row_q), each mm * 100
    mech_cost_q: int
    bbox: tuple[int, int, int, int]  # (min_col, min_row, max_col, max_row)
    pin_centroid_q: tuple[int, int]
    footprint_id: str


# --------------------------------------------------------------------------
# Pre-filter helpers
# --------------------------------------------------------------------------


_TWO_PIN_FLEXIBLE_FOOTPRINTS: frozenset[str] = frozenset(
    {
        "AXIAL-R",
        "AXIAL-DIODE",
        "RADIAL-CAP-2P",
        "ELECTROLYTIC-CAP-2P",
        "LED-2P",
    }
)


def _is_two_pin_flexible(footprint_id: str) -> bool:
    return footprint_id in _TWO_PIN_FLEXIBLE_FOOTPRINTS


def _is_connector_or_header(footprint_id: str) -> bool:
    return footprint_id.startswith("CONN-") or footprint_id.startswith("HEADER-1x")


def _has_clearance_rule(footprint_id: str, footprints: Mapping[str, ThroughHoleFootprint]) -> bool:
    fp = footprints.get(footprint_id)
    return bool(fp and any(r.type == "min-clearance-holes" for r in fp.placement_rules))


def _centroid_q_for_holes(hole_ids: Iterable[str], pitch_mm: float) -> tuple[int, int]:
    """Return the centroid of a set of absolute ``"row-col"`` hole ids as
    ``(col_q, row_q)`` in ``_MILLIMETRE_SCALE`` units."""
    cols: list[int] = []
    rows: list[int] = []
    for hid in hole_ids:
        row_str, col_str = hid.split("-", 1)
        row = int(row_str) - 1
        col = int(col_str) - 1
        cols.append(int(round(col * pitch_mm * _MILLIMETRE_SCALE)))
        rows.append(int(round(row * pitch_mm * _MILLIMETRE_SCALE)))
    if not cols:
        return (0, 0)
    return (sum(cols) // len(cols), sum(rows) // len(rows))


def _bbox_for_holes(hole_ids: Iterable[str]) -> tuple[int, int, int, int]:
    cols: list[int] = []
    rows: list[int] = []
    for hid in hole_ids:
        row_str, col_str = hid.split("-", 1)
        cols.append(int(col_str))
        rows.append(int(row_str))
    if not cols:
        return (1, 1, 1, 1)
    return (min(cols), min(rows), max(cols), max(rows))


def _pin_centroid_q(pin_holes: tuple[tuple[str, str], ...], pitch_mm: float) -> tuple[int, int]:
    return _centroid_q_for_holes((hid for _, hid in pin_holes), pitch_mm)


def _pose_to_candidate(
    pose: Pose,
    component_ref: str,
    footprint_id: str,
    index: _PerfIndex,
) -> CandidatePose:
    pin_holes: list[tuple[str, str]] = []
    occupied: set[str] = set()
    for pin_id, hole_idx in pose.pin_idx:
        hid = index.hole_ids[hole_idx]
        pin_holes.append((pin_id, hid))
        occupied.add(hid)
    body_hole_ids: list[str] = []
    for hole_idx in pose.body_cells_idx:
        hid = index.hole_ids[hole_idx]
        body_hole_ids.append(hid)
        occupied.add(hid)
    all_holes = body_hole_ids + [h for _, h in pin_holes]
    return CandidatePose(
        component_ref=component_ref,
        pose_id=-1,  # assigned by build_candidate_poses
        anchor_idx=pose.anchor_idx,
        orientation=pose.orientation,
        span=pose.span,
        pin_holes=tuple(sorted(pin_holes, key=lambda kv: kv[0])),
        body_hole_ids=tuple(body_hole_ids),
        occupied_hole_ids=frozenset(occupied),
        centroid_q=_centroid_q_for_holes(all_holes, index.pitch_mm),
        mech_cost_q=int(round(pose.mech_cost * _MILLIMETRE_SCALE)),
        bbox=_bbox_for_holes(all_holes),
        pin_centroid_q=_pin_centroid_q(tuple(pin_holes), index.pitch_mm),
        footprint_id=footprint_id,
    )


# --------------------------------------------------------------------------
# build_candidate_poses
# --------------------------------------------------------------------------


def _cheap_pose_score(
    cand: CandidatePose,
    board: PerfboardModel,
    initial_layout: TraceLayout | None,
) -> float:
    """Deterministic cheap score for pre-filter ranking.

    Lower is better. Components of interest (no global minimum):
    centroid distance to first placed/locked position, span deviation,
    vertical-orientation bump. Used only for ranking when a component's
    candidate count exceeds ``placement_candidate_limit``; never rejects a
    hard-rule-feasible pose.
    """
    # Anchor centroid: locked placement centroid, else board centre.
    bx = (board.cols - 1) * board.pitch_mm
    by = (board.rows - 1) * board.pitch_mm
    target_qx = int(round((bx / 2.0) * _MILLIMETRE_SCALE))
    target_qy = int(round((by / 2.0) * _MILLIMETRE_SCALE))
    if initial_layout is not None and initial_layout.placements:
        xs: list[int] = []
        ys: list[int] = []
        for p in initial_layout.placements:
            for hid in p.occupied_hole_ids:
                row_str, col_str = hid.split("-", 1)
                row = int(row_str) - 1
                col = int(col_str) - 1
                xs.append(int(round(col * board.pitch_mm * _MILLIMETRE_SCALE)))
                ys.append(int(round(row * board.pitch_mm * _MILLIMETRE_SCALE)))
        if xs:
            target_qx = sum(xs) // len(xs)
            target_qy = sum(ys) // len(ys)

    dx = abs(cand.centroid_q[0] - target_qx)
    dy = abs(cand.centroid_q[1] - target_qy)
    distance_score = (dx + dy) / (2.0 * _MILLIMETRE_SCALE)

    vertical = 0.05 if cand.orientation in (90, 270) else 0.0
    return float(distance_score + vertical)


def _enumerated_candidates_for_component(
    *,
    component_ref: str,
    footprint: ThroughHoleFootprint,
    index: _PerfIndex,
    locked_occupied: set[str],
) -> tuple[CandidatePose, ...]:
    """Enumerate every legal pose for one footprint, then drop any pose
    whose occupied holes collide with locked placements. Pose geometry
    (anchors, orientation, span, mech_cost) is computed by the existing
    ``generate_poses`` cache, so we reuse it rather than reimplementing
    footprint transforms here."""
    raw = generate_poses(index, footprint)
    cands: list[CandidatePose] = []
    for pose in raw:
        # Convert to CandidatePose then filter on locked holes (absolute ids).
        cand = _pose_to_candidate(pose, component_ref, footprint.id, index)
        if any(hid in locked_occupied for hid in cand.occupied_hole_ids):
            continue
        cands.append(cand)
    return tuple(cands)


def _assign_pose_ids(candidates: Iterable[CandidatePose]) -> list[CandidatePose]:
    out = sorted(candidates, key=lambda c: (c.anchor_idx, c.orientation, -1 if c.span is None else c.span))
    return [dataclasses.replace(c, pose_id=i) for i, c in enumerate(out)]


def build_candidate_poses(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    locked_placements: list[ComponentPlacement],
    candidate_limit: int,
    initial_layout: TraceLayout | None = None,
) -> tuple[
    Mapping[str, tuple[CandidatePose, ...]],
    Mapping[str, tuple[tuple[str, int], ...]],
    set[str],
]:
    """Enumerate per-component candidate poses, apply pre-filters, return
    candidates by component ref, the inverse index by hole id, and the set
    of locked-occupied holes.

    Pre-filter rules:

    * drop any pose that collides with a locked placement;
    * for 2-pin flexible footprints (AXIAL-R, AXIAL-DIODE, RADIAL-CAP-2P,
      ELECTROLYTIC-CAP-2P, LED-2P) cap to ``candidate_limit`` by a cheap
      heuristic score (centroid distance + vertical penalty), preserving at
      least 4 poses per orientation;
    * keep every pose for DIP, TO-92, TACT-SW-4P, HEADER-1x*, CONN-1x* and
      any footprint carrying a ``min-clearance-holes`` rule.
    """
    index = _PerfIndex.build(board)
    locked_occupied: set[str] = set()
    for p in locked_placements:
        locked_occupied.update(p.occupied_hole_ids)

    out: dict[str, tuple[CandidatePose, ...]] = {}
    hole_to_candidates: dict[str, list[tuple[str, int]]] = {}

    for component in components:
        footprint = footprints.get(component.footprint_id)
        if footprint is None:
            out[component.ref] = ()
            continue

        all_cands = _enumerated_candidates_for_component(
            component_ref=component.ref,
            footprint=footprint,
            index=index,
            locked_occupied=locked_occupied,
        )

        if (
            not _is_two_pin_flexible(footprint.id)
            and not _is_connector_or_header(footprint.id)
            and not _has_clearance_rule(footprint.id, footprints)
            and len(all_cands) <= candidate_limit
        ):
            kept = _assign_pose_ids(all_cands)
        elif len(all_cands) <= candidate_limit:
            kept = _assign_pose_ids(all_cands)
        else:
            # Cheap-score sort: connectors/headers get an edge-bias so the
            # cap doesn't strip every edge pose; everything else uses the
            # plain centroid distance heuristic.
            is_edge_class = _is_connector_or_header(footprint.id)

            def _cheap(c: CandidatePose) -> tuple[float, int]:
                base = _cheap_pose_score(c, board, initial_layout)
                if is_edge_class:
                    min_col, min_row, max_col, max_row = c.bbox
                    on_edge = (
                        min_col == 1 or max_col == board.cols
                        or min_row == 1 or max_row == board.rows
                    )
                    # Make on-edge poses sort first.
                    return (0.0 if on_edge else 1.0, base)
                return (base, 0)

            scored = sorted(
                all_cands,
                key=lambda c: (
                    _cheap(c),
                    c.anchor_idx,
                    c.orientation,
                    -1 if c.span is None else c.span,
                ),
            )
            head = scored[:candidate_limit]
            head_keys = {(c.anchor_idx, c.orientation) for c in head}
            by_orient: dict[int, list[CandidatePose]] = {0: [], 90: [], 180: [], 270: []}
            for c in scored[candidate_limit:]:
                if (c.anchor_idx, c.orientation) in head_keys:
                    continue
                if len(by_orient[c.orientation]) < 4:
                    by_orient[c.orientation].append(c)
            kept = _assign_pose_ids(list(head) + [c for cs in by_orient.values() for c in cs])

        out[component.ref] = tuple(kept)
        for c in kept:
            for hid in c.occupied_hole_ids:
                hole_to_candidates.setdefault(hid, []).append((c.component_ref, c.pose_id))

    hole_to_candidates_final: dict[str, tuple[tuple[str, int], ...]] = {
        hid: tuple(pairs) for hid, pairs in hole_to_candidates.items()
    }
    return out, hole_to_candidates_final, locked_occupied


# --------------------------------------------------------------------------
# CP-SAT feasibility model
# --------------------------------------------------------------------------


def build_cpsat_model(
    *,
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    hole_to_candidates: Mapping[str, tuple[tuple[str, int], ...]],
    locked_occupied: set[str],
) -> tuple[
    cp_model.CpModel,
    dict[str, dict[int, cp_model.IntVar]],
]:
    """Build the feasibility model. Returns the model and the per-component
    selection variables (indexed by ``pose_id``). Soft objective terms are
    layered on by :func:`add_objective_terms` — keep them decoupled so the
    feasibility model can be unit-tested in isolation.
    """
    model = cp_model.CpModel()
    sel_vars: dict[str, dict[int, cp_model.IntVar]] = {}

    # Exactly one pose per movable component.
    for ref, cands in candidates.items():
        if not cands:
            continue
        sel_vars[ref] = {}
        for c in cands:
            sel_vars[ref][c.pose_id] = model.NewBoolVar(f"sel_{ref}_{c.pose_id}")
        model.Add(sum(sel_vars[ref][c.pose_id] for c in cands) == 1)

    # Exact hole occupancy: at most one selected candidate touches any hole.
    for hole_id, pairs in hole_to_candidates.items():
        if hole_id in locked_occupied or not pairs:
            continue
        model.Add(
            sum(sel_vars[ref][pose_id] for ref, pose_id in pairs) <= 1
        )

    return model, sel_vars


# --------------------------------------------------------------------------
# Objective terms
# --------------------------------------------------------------------------


@dataclass(slots=True)
class PlacementObjectiveBreakdown:
    """Per-term integer costs of the final CP-SAT solution. Units are
    ``_MILLIMETRE_SCALE``-scaled Manhattan (so ``net_length`` is in 1/100 mm).
    Always non-negative."""

    net_length: int = 0
    cluster_spread: int = 0
    compactness: int = 0
    edge: int = 0
    orientation: int = 0
    congestion: int = 0
    mechanical: int = 0
    total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "netLength": self.net_length,
            "clusterSpread": self.cluster_spread,
            "compactness": self.compactness,
            "edge": self.edge,
            "orientation": self.orientation,
            "congestion": self.congestion,
            "mechanical": self.mechanical,
            "total": self.total,
        }


_DECOUPLER_FOOTPRINTS: frozenset[str] = frozenset(
    {
        "RADIAL-CAP-2P",
        "ELECTROLYTIC-CAP-2P",
        "AXIAL-R",
        "AXIAL-DIODE",
    }
)


def _manhattan_q(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _pin_hole_for_ref_pin(
    ref: str,
    pin: str,
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    locked_pin_holes: Mapping[str, Mapping[str, str]],
    selected_pose: Mapping[str, CandidatePose] | None,
) -> tuple[int, int] | None:
    """Return the (col_q, row_q) of ``ref.pin`` in the chosen pose, or None
    if the pin doesn't exist. ``locked_pin_holes`` wins for locked refs."""
    if ref in locked_pin_holes and pin in locked_pin_holes[ref]:
        hid = locked_pin_holes[ref][pin]
        row_str, col_str = hid.split("-", 1)
        return (
            int(round((int(col_str) - 1) * 2.54 * _MILLIMETRE_SCALE)),
            int(round((int(row_str) - 1) * 2.54 * _MILLIMETRE_SCALE)),
        )
    if selected_pose is not None and ref in selected_pose:
        for pid, hid in selected_pose[ref].pin_holes:
            if pid == pin:
                row_str, col_str = hid.split("-", 1)
                return (
                    int(round((int(col_str) - 1) * 2.54 * _MILLIMETRE_SCALE)),
                    int(round((int(row_str) - 1) * 2.54 * _MILLIMETRE_SCALE)),
                )
    return None


def _hub_pin_for_net(
    net: Net,
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    locked_pin_holes: Mapping[str, Mapping[str, str]],
    selected_pose: Mapping[str, CandidatePose] | None,
) -> tuple[PinRefLike, tuple[int, int]] | None:
    """Pick a deterministic hub for the net: highest-degree pin, falling
    back to lexicographic-first. Returns ``None`` if no pin has a known
    hole (e.g. all pins are on movable components and we have no selection
    yet — caller should pre-resolve)."""

    best: tuple[PinRefLike, tuple[int, int], int] | None = None
    for pin in net.pins:
        hole = _pin_hole_for_ref_pin(
            pin.component_ref, pin.pin, candidates, locked_pin_holes, selected_pose
        )
        if hole is None:
            continue
        deg = sum(1 for p in net.pins if p.component_ref == pin.component_ref)
        key = (deg, pin.component_ref, pin.pin)
        if best is None or key > best[2:]:
            best = (PinRefLike(component_ref=pin.component_ref, pin=pin.pin), hole, key)
    if best is None:
        return None
    return best[0], best[1]


@dataclass(frozen=True, slots=True)
class PinRefLike:
    component_ref: str
    pin: str


def _build_bin_to_components(
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    board: PerfboardModel,
) -> dict[tuple[int, int], set[str]]:
    """Return ``(row_bin, col_bin) -> {ref}`` mapping every candidate cell
    to its bin. Bins are 3-row × 3-col blocks of the board."""
    bin_to_components: dict[tuple[int, int], set[str]] = {}
    for ref, cands in candidates.items():
        for c in cands:
            for cell in c.occupied_hole_ids:
                row_str, col_str = cell.split("-", 1)
                row = int(row_str)
                col = int(col_str)
                rb = (row - 1) // _BIN_ROWS
                cb = (col - 1) // _BIN_COLS
                bin_to_components.setdefault((rb, cb), set()).add(ref)
    return bin_to_components


def _along_edge(cand: CandidatePose, board: PerfboardModel) -> bool:
    """True if the candidate's body sits on an edge AND its long axis is
    parallel to that edge (so a connector's mating side faces outwards)."""
    min_col, min_row, max_col, max_row = cand.bbox
    horizontal = (max_col - min_col) >= (max_row - min_row)
    if min_col == 1 or max_col == board.cols:
        if horizontal:
            return True
    if min_row == 1 or max_row == board.rows:
        if not horizontal:
            return True
    return False


def _anchor_centroid_q(
    locked_placements: list[ComponentPlacement], board: PerfboardModel
) -> tuple[int, int]:
    """Average centroid of locked placements, or board centre if none."""
    if not locked_placements:
        bx = (board.cols - 1) * board.pitch_mm
        by = (board.rows - 1) * board.pitch_mm
        return (
            int(round((bx / 2.0) * _MILLIMETRE_SCALE)),
            int(round((by / 2.0) * _MILLIMETRE_SCALE)),
        )
    xs: list[int] = []
    ys: list[int] = []
    for p in locked_placements:
        for hid in p.occupied_hole_ids:
            row_str, col_str = hid.split("-", 1)
            row = int(row_str) - 1
            col = int(col_str) - 1
            xs.append(int(round(col * board.pitch_mm * _MILLIMETRE_SCALE)))
            ys.append(int(round(row * board.pitch_mm * _MILLIMETRE_SCALE)))
    return (sum(xs) // len(xs), sum(ys) // len(ys)) if xs else (0, 0)


def add_objective_terms(
    model: cp_model.CpModel,
    *,
    sel_vars: dict[str, dict[int, cp_model.IntVar]],
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    components: list[Component],
    nets: list[Net],
    board: PerfboardModel,
    locked_placements: list[ComponentPlacement],
    footprints: dict[str, ThroughHoleFootprint] | None = None,
    weights: CpsatWeights = DEFAULT_CPSAT_WEIGHTS,
) -> tuple[list[cp_model.LinearExpr], PlacementObjectiveBreakdown]:
    """Add every soft objective term to ``model``. Returns the list of
    linear expressions (for ``model.Minimize(sum(...))``) plus a zero
    breakdown the caller updates after solving."""
    terms: list[cp_model.LinearExpr] = []
    breakdown = PlacementObjectiveBreakdown()

    # Build cluster anchors. ``build_clusters`` only uses footprints to
    # decide which 2-pin caps count as bypass / which DIPs can be anchors;
    # the dict can be sparse as long as it covers the components' ids.
    fp_lookup: dict[str, ThroughHoleFootprint] = dict(footprints or {})
    for c in components:
        fp_lookup.setdefault(
            c.footprint_id,
            ThroughHoleFootprint(
                id=c.footprint_id,
                display_name="stub",
                pin_offsets={},
                body_cells=[],
                supported_orientations=[0],
                placement_rules=[],
                geometry=FootprintGeometry(),
            ),
        )
    clusters = build_clusters(components, nets, fp_lookup)
    cluster_anchor_of: dict[str, str] = {}
    for cluster in clusters:
        anchor_ref = cluster.anchor_ref or cluster.id
        for member in cluster.member_refs:
            cluster_anchor_of[member] = anchor_ref
    is_decoupler: dict[str, bool] = {
        ref: bool(
            cluster_anchor_of.get(ref, ref) != ref
            and _footprint_of(ref, components) in _DECOUPLER_FOOTPRINTS
        )
        for ref in candidates
    }

    # Locked pin holes for hub resolution.
    locked_pin_holes: dict[str, dict[str, str]] = {}
    for p in locked_placements:
        locked_pin_holes[p.component_ref] = dict(p.pin_holes)

    # ---- 1. Estimated net length (hub-based, bounded) ----
    for net in nets:
        # Hub: first pin (lexicographic) for determinism.
        sorted_pins = sorted(
            net.pins, key=lambda p: (p.component_ref, p.pin)
        )
        # Resolve hub hole from candidates directly (one of the candidate
        # poses is selected — we model the hub as the candidate hole of the
        # component, averaged across selected pose's pin_holes).
        # Simpler: hub = pin_centroid of the *first* pin's selected pose.
        hub_ref = sorted_pins[0].component_ref
        hub_pin = sorted_pins[0].pin
        hub_cands = candidates.get(hub_ref)
        if hub_cands:
            for other in sorted_pins[1:]:
                if len(net.pins) > 6:
                    # Hub-only approximation: each pin contributes distance
                    # to the hub (no inter-pin product).
                    for c_hub in hub_cands:
                        for c_other in candidates.get(other.component_ref, ()):  # type: ignore[arg-type]
                            z = model.NewBoolVar(
                                f"net_hub_{net.id}_{c_hub.pose_id}_{other.component_ref}_{c_other.pose_id}"
                            )
                            model.Add(z <= sel_vars[hub_ref][c_hub.pose_id])
                            model.Add(z <= sel_vars[other.component_ref][c_other.pose_id])
                            model.Add(
                                z
                                >= sel_vars[hub_ref][c_hub.pose_id]
                                + sel_vars[other.component_ref][c_other.pose_id]
                                - 1
                            )
                            d = _manhattan_q(c_hub.pin_centroid_q, c_other.pin_centroid_q)
                            terms.append(weights.net * d * z)
                    continue
                # Bounded pairwise: each other pin → hub.
                for c_hub in hub_cands:
                    for c_other in candidates.get(other.component_ref, ()):  # type: ignore[arg-type]
                        z = model.NewBoolVar(
                            f"net_pair_{net.id}_{c_hub.pose_id}_{other.component_ref}_{c_other.pose_id}"
                        )
                        model.Add(z <= sel_vars[hub_ref][c_hub.pose_id])
                        model.Add(z <= sel_vars[other.component_ref][c_other.pose_id])
                        model.Add(
                            z
                            >= sel_vars[hub_ref][c_hub.pose_id]
                            + sel_vars[other.component_ref][c_other.pose_id]
                            - 1
                        )
                        d = _manhattan_q(c_hub.pin_centroid_q, c_other.pin_centroid_q)
                        terms.append(weights.net * d * z)

    # ---- 2. Cluster proximity ----
    for member_ref, anchor_ref in cluster_anchor_of.items():
        if member_ref == anchor_ref:
            continue
        if member_ref not in candidates or anchor_ref not in candidates:
            continue
        w = weights.decoupler if is_decoupler.get(member_ref, False) else weights.cluster
        for ca in candidates[anchor_ref]:
            for cm in candidates[member_ref]:
                z = model.NewBoolVar(
                    f"cl_{anchor_ref}_{ca.pose_id}_{member_ref}_{cm.pose_id}"
                )
                model.Add(z <= sel_vars[anchor_ref][ca.pose_id])
                model.Add(z <= sel_vars[member_ref][cm.pose_id])
                model.Add(
                    z
                    >= sel_vars[anchor_ref][ca.pose_id]
                    + sel_vars[member_ref][cm.pose_id]
                    - 1
                )
                d = _manhattan_q(ca.centroid_q, cm.centroid_q)
                terms.append(w * d * z)

    # ---- 3. Compactness ----
    anchor_centroid = _anchor_centroid_q(locked_placements, board)
    for ref, cands in candidates.items():
        for c in cands:
            d = _manhattan_q(c.centroid_q, anchor_centroid)
            terms.append(weights.compactness * d * sel_vars[ref][c.pose_id])

    # ---- 4. Connector edge preference ----
    for ref, cands in candidates.items():
        if not cands or not _is_connector_or_header(cands[0].footprint_id):
            continue
        for c in cands:
            min_col, min_row, max_col, max_row = c.bbox
            edge_score = 0
            if min_col == 1 or max_col == board.cols:
                edge_score += weights.edge
            if min_row == 1 or max_row == board.rows:
                edge_score += weights.edge
            if _along_edge(c, board):
                edge_score += weights.edge // 2
            terms.append(edge_score * sel_vars[ref][c.pose_id])

    # ---- 5. Orientation preference ----
    for ref, cands in candidates.items():
        if not cands:
            continue
        fp_id = cands[0].footprint_id
        for c in cands:
            if fp_id.startswith("DIP-"):
                cost = 0 if c.orientation == 0 else weights.orientation
            else:
                cost = 0
            terms.append(cost * sel_vars[ref][c.pose_id])

    # ---- 6. Congestion (3x3 bins) ----
    bin_to_components = _build_bin_to_components(candidates, board)
    for bin_key, comp_set in bin_to_components.items():
        if len(comp_set) < _HOT_BIN_THRESHOLD:
            continue
        rb, cb = bin_key
        for ref in comp_set:
            for c in candidates[ref]:
                n = sum(
                    1
                    for cell in c.occupied_hole_ids
                    if int(cell.split("-")[0]) // _BIN_ROWS == rb
                    and int(cell.split("-")[1]) // _BIN_COLS == cb
                )
                if n:
                    terms.append(weights.congestion * n * sel_vars[ref][c.pose_id])

    # ---- 7. Mechanical cost ----
    for ref, cands in candidates.items():
        for c in cands:
            terms.append(weights.mechanical * c.mech_cost_q * sel_vars[ref][c.pose_id])

    return terms, breakdown


def _footprint_of(ref: str, components: list[Component]) -> str:
    for c in components:
        if c.ref == ref:
            return c.footprint_id
    return ""


# --------------------------------------------------------------------------
# No-good (diversity) constraint
# --------------------------------------------------------------------------


def _add_no_good_constraint(
    model: cp_model.CpModel,
    *,
    sel_vars: dict[str, dict[int, cp_model.IntVar]],
    previous_assignment: Mapping[str, int],
) -> None:
    """Forbid the literal assignment ``previous_assignment`` from reappearing.

    Implementation: at least one component must pick a different pose:

        sum(1 - sel_vars[ref][previous_assignment[ref]]) >= 1

    Equivalent to the brief's ``sum(s_i for selected) <= n - 1`` form.
    """
    clauses: list[cp_model.IntVar] = []
    for ref, prev_pose_id in previous_assignment.items():
        var = sel_vars.get(ref, {}).get(prev_pose_id)
        if var is None:
            continue
        clauses.append(var)
    if not clauses:
        return
    # At least one of the previously selected poses must be unselected.
    # Equivalently: sum(1 - var) >= 1 ⇔ len - sum(var) >= 1 ⇔ sum(var) <= len-1
    model.Add(sum(clauses) <= len(clauses) - 1)


# --------------------------------------------------------------------------
# Routing-aware candidate evaluation
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _CandidateOutcome:
    candidate_index: int
    placements: list[ComponentPlacement]
    proxy_breakdown: PlacementObjectiveBreakdown
    trace_cost: float
    trace_length_mm: float
    via_count: int
    trace_count: int
    segment_count: int
    unrouted_nets: tuple[str, ...]
    validation_diagnostics: list[Diagnostic]
    placement_status: str  # "FEASIBLE" | "INVALID" | "INFEASIBLE"
    placement_engine_ms: float


@dataclass(frozen=True, slots=True, order=True)
class RoutedCandidateRank:
    validation_error_count: int
    unrouted_net_count: int
    trace_length_units: float
    via_count: int
    segment_count: int
    routing_cost_units: float
    placement_proxy_score: int
    candidate_index: int


def _evaluate_candidate(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    candidate: list[ComponentPlacement],
    cancel: Callable[[], bool] | None,
    progress: Callable[[str, int], None] | None,
    proxy_breakdown: PlacementObjectiveBreakdown,
    placement_engine_ms: float,
    candidate_index: int,
) -> _CandidateOutcome | None:
    """Route + validate + score one candidate. Returns None if cancelled."""
    if cancel is not None and cancel():
        return None
    graph = maze.build_maze(
        rows=board.rows,
        cols=board.cols,
        pitch_mm=board.pitch_mm,
        double_sided=(board.layers == 2),
    )
    route_result = trace_route.route(
        board_id=board.id,
        placements=candidate,
        components=components,
        footprints=footprints,
        nets=nets,
        graph=graph,
        cancel=cancel,
        progress=None,
    )
    validation = validate_layout(board, footprints, components, nets, route_result.layout)
    if progress is not None:
        progress("trace-route", progress_marker(route_result.layout))
    placement_errors = [d for d in validation.diagnostics if d.severity == "error"]
    via_count = sum(len(t.vias) for t in route_result.layout.traces)
    trace_length_mm = sum(t.estimated_length_mm for t in route_result.layout.traces)
    segment_count = sum(len(t.segments) for t in route_result.layout.traces)
    return _CandidateOutcome(
        candidate_index=candidate_index,
        placements=candidate,
        proxy_breakdown=proxy_breakdown,
        trace_cost=route_result.trace_cost,
        trace_length_mm=trace_length_mm,
        via_count=via_count,
        trace_count=len(route_result.layout.traces),
        segment_count=segment_count,
        unrouted_nets=tuple(route_result.unrouted_nets),
        validation_diagnostics=validation.diagnostics,
        placement_status="INVALID" if placement_errors else "FEASIBLE",
        placement_engine_ms=placement_engine_ms,
    )


def progress_marker(layout: TraceLayout) -> int:
    """Best-effort progress marker for ``progress("trace-route", pct)``."""
    return min(99, 90 + (5 if layout.traces else 0))


def _rank_outcomes(outcomes: list[_CandidateOutcome]) -> _CandidateOutcome:
    """Rank candidates by actual routed quality before proxy quality."""

    def validation_error_count(outcome: _CandidateOutcome) -> int:
        return sum(1 for d in outcome.validation_diagnostics if d.severity == "error")

    def rank(outcome: _CandidateOutcome) -> RoutedCandidateRank:
        return RoutedCandidateRank(
            validation_error_count=validation_error_count(outcome),
            unrouted_net_count=len(outcome.unrouted_nets),
            trace_length_units=outcome.trace_length_mm,
            via_count=outcome.via_count,
            segment_count=outcome.segment_count,
            routing_cost_units=outcome.trace_cost,
            placement_proxy_score=outcome.proxy_breakdown.total,
            candidate_index=outcome.candidate_index,
        )

    return min(outcomes, key=rank)


# --------------------------------------------------------------------------
# Top-level entrypoint
# --------------------------------------------------------------------------


def _selected_pose_for(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    sel_vars: dict[str, dict[int, cp_model.IntVar]],
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    components: list[Component],
    nets: list[Net],
    board: PerfboardModel,
    locked_placements: list[ComponentPlacement],
    weights: CpsatWeights,
    unplaced: list[str],
    footprints: dict[str, ThroughHoleFootprint],
) -> tuple[list[ComponentPlacement], PlacementObjectiveBreakdown] | None:
    """After a successful Solve, extract the chosen literal per component,
    build canonical ComponentPlacements, and recompute the objective
    breakdown exactly from those poses (so the diagnostic matches what the
    solver actually evaluated)."""
    chosen: dict[str, CandidatePose] = {}
    for ref, vars_by_pose in sel_vars.items():
        selected = None
        for pose_id, var in vars_by_pose.items():
            if solver.Value(var):
                selected = pose_id
                break
        if selected is None:
            unplaced.append(ref)
            continue
        chosen[ref] = next(c for c in candidates[ref] if c.pose_id == selected)

    placements: list[ComponentPlacement] = list(locked_placements)
    footprint_by_ref = {c.ref: c for c in components}
    for ref, cand in chosen.items():
        comp = footprint_by_ref[ref]
        placements.append(_candidate_to_placement(cand, comp))

    # Recompute breakdown directly (deterministic, no CP-SAT round-trip).
    breakdown = _recompute_breakdown(
        chosen, locked_placements, components, nets, board, weights, footprints
    )
    return placements, breakdown


def _candidate_to_placement(cand: CandidatePose, component: Component) -> ComponentPlacement:
    pin_holes = {pid: hid for pid, hid in cand.pin_holes}
    occupied = sorted(cand.occupied_hole_ids)
    return ComponentPlacement(
        component_ref=component.ref,
        anchor_hole_id=_hole_id_for_anchor(cand),
        orientation=cand.orientation,
        span=cand.span,
        pin_holes=pin_holes,
        occupied_hole_ids=occupied,
        locked=False,
    )


def _hole_id_for_anchor(cand: CandidatePose) -> str:
    """The candidate encodes ``anchor_idx`` as a lattice index; reconstruct
    ``"row-col"`` from ``pin_holes[0][1]`` (always present because every
    footprint has pin '1'). If the candidate happens to have no pins
    (today no such footprint), fall back to the first body cell."""
    if cand.pin_holes:
        return cand.pin_holes[0][1]
    if cand.body_hole_ids:
        return cand.body_hole_ids[0]
    return "1-1"


def index_hole_id(cand: CandidatePose) -> str:
    """Alias for :func:`_hole_id_for_anchor` used outside the module."""
    return _hole_id_for_anchor(cand)


def _recompute_breakdown(
    chosen: Mapping[str, CandidatePose],
    locked_placements: list[ComponentPlacement],
    components: list[Component],
    nets: list[Net],
    board: PerfboardModel,
    weights: CpsatWeights,
    footprints: dict[str, ThroughHoleFootprint] | None = None,
) -> PlacementObjectiveBreakdown:
    """Recompute the objective breakdown deterministically from a chosen
    pose assignment. Units are integer (1/100 mm)."""
    breakdown = PlacementObjectiveBreakdown()

    fp_lookup: dict[str, ThroughHoleFootprint] = dict(footprints or {})
    for c in components:
        fp_lookup.setdefault(
            c.footprint_id,
            ThroughHoleFootprint(
                id=c.footprint_id, display_name="stub", pin_offsets={},
                body_cells=[], supported_orientations=[0], placement_rules=[],
                geometry=FootprintGeometry(),
            ),
        )

    # 1. Net length (hub-based, same rule as add_objective_terms).
    for net in nets:
        sorted_pins = sorted(net.pins, key=lambda p: (p.component_ref, p.pin))
        if not sorted_pins:
            continue
        hub_pin = sorted_pins[0]
        hub_cand = chosen.get(hub_pin.component_ref) or _locked_cand(
            hub_pin.component_ref, hub_pin.pin, locked_placements
        )
        if hub_cand is None:
            continue
        for other in sorted_pins[1:]:
            other_cand = chosen.get(other.component_ref) or _locked_cand(
                other.component_ref, other.pin, locked_placements
            )
            if other_cand is None:
                continue
            d = _manhattan_q(hub_cand.pin_centroid_q, other_cand.pin_centroid_q)
            breakdown.net_length += weights.net * d

    # 2. Cluster proximity.
    clusters = build_clusters(components, nets, fp_lookup)
    cluster_anchor_of: dict[str, str] = {}
    for cluster in clusters:
        anchor_ref = cluster.anchor_ref or cluster.id
        for member in cluster.member_refs:
            cluster_anchor_of[member] = anchor_ref
    for member_ref, anchor_ref in cluster_anchor_of.items():
        if member_ref == anchor_ref:
            continue
        ca = chosen.get(anchor_ref)
        cm = chosen.get(member_ref)
        if ca is None or cm is None:
            continue
        w = weights.decoupler if _footprint_of(member_ref, components) in _DECOUPLER_FOOTPRINTS else weights.cluster
        breakdown.cluster_spread += w * _manhattan_q(ca.centroid_q, cm.centroid_q)

    # 3. Compactness.
    anchor_centroid = _anchor_centroid_q(locked_placements, board)
    for ref, cand in chosen.items():
        d = _manhattan_q(cand.centroid_q, anchor_centroid)
        breakdown.compactness += weights.compactness * d

    # 4. Edge.
    for ref, cand in chosen.items():
        if not _is_connector_or_header(cand.footprint_id):
            continue
        min_col, min_row, max_col, max_row = cand.bbox
        edge_score = 0
        if min_col == 1 or max_col == board.cols:
            edge_score += weights.edge
        if min_row == 1 or max_row == board.rows:
            edge_score += weights.edge
        if _along_edge(cand, board):
            edge_score += weights.edge // 2
        breakdown.edge += edge_score

    # 5. Orientation.
    for ref, cand in chosen.items():
        if cand.footprint_id.startswith("DIP-"):
            breakdown.orientation += 0 if cand.orientation == 0 else weights.orientation

    # 6. Congestion.
    bin_to_components: dict[tuple[int, int], set[str]] = {}
    for ref, cand in chosen.items():
        for cell in cand.occupied_hole_ids:
            row_str, col_str = cell.split("-", 1)
            row = int(row_str)
            col = int(col_str)
            rb = (row - 1) // _BIN_ROWS
            cb = (col - 1) // _BIN_COLS
            bin_to_components.setdefault((rb, cb), set()).add(ref)
    for (rb, cb), comp_set in bin_to_components.items():
        if len(comp_set) < _HOT_BIN_THRESHOLD:
            continue
        for ref, cand in chosen.items():
            if ref not in comp_set:
                continue
            n = sum(
                1
                for cell in cand.occupied_hole_ids
                if int(cell.split("-")[0]) // _BIN_ROWS == rb
                and int(cell.split("-")[1]) // _BIN_COLS == cb
            )
            breakdown.congestion += weights.congestion * n

    # 7. Mechanical.
    for ref, cand in chosen.items():
        breakdown.mechanical += weights.mechanical * cand.mech_cost_q

    breakdown.total = (
        breakdown.net_length
        + breakdown.cluster_spread
        + breakdown.compactness
        + breakdown.edge
        + breakdown.orientation
        + breakdown.congestion
        + breakdown.mechanical
    )
    return breakdown


def _locked_cand(
    ref: str, pin: str, locked_placements: list[ComponentPlacement]
) -> CandidatePose | None:
    """Synthesise a minimal CandidatePose for a locked component so
    ``_manhattan_q`` works on its pins. ``pin_centroid_q`` is the locked
    pin's coordinates; ``centroid_q`` is the average of occupied holes."""
    for p in locked_placements:
        if p.component_ref != ref:
            continue
        if pin not in p.pin_holes:
            continue
        xs: list[int] = []
        ys: list[int] = []
        for hid in p.occupied_hole_ids:
            row_str, col_str = hid.split("-", 1)
            xs.append(int(col_str))
            ys.append(int(row_str))
        if not xs:
            return None
        cx = int(round((sum(xs) / len(xs) - 1) * 2.54 * _MILLIMETRE_SCALE))
        cy = int(round((sum(ys) / len(ys) - 1) * 2.54 * _MILLIMETRE_SCALE))
        row_str, col_str = p.pin_holes[pin].split("-", 1)
        px = int(round((int(col_str) - 1) * 2.54 * _MILLIMETRE_SCALE))
        py = int(round((int(row_str) - 1) * 2.54 * _MILLIMETRE_SCALE))
        return CandidatePose(
            component_ref=ref,
            pose_id=-1,
            anchor_idx=-1,
            orientation=p.orientation,
            span=p.span,
            pin_holes=tuple(sorted(p.pin_holes.items(), key=lambda kv: kv[0])),
            body_hole_ids=tuple(p.occupied_hole_ids),
            occupied_hole_ids=frozenset(p.occupied_hole_ids),
            centroid_q=(cx, cy),
            mech_cost_q=0,
            bbox=_bbox_for_holes(p.occupied_hole_ids),
            pin_centroid_q=(px, py),
            footprint_id="LOCKED",
        )
    return None


def _resolve_budget(options: SolverOptions) -> tuple[int, int, int, bool]:
    """Pick (time_limit_ms, candidate_limit, solution_count, preset_used).

    Per-call fields win when they differ from their Pydantic default. The
    preset only applies when the caller did not override the individual
    fields. Returns ``preset_used=True`` when the preset contributed.
    """
    fields = SolverOptions.model_fields
    default_time = fields["placement_time_limit_ms"].default
    default_cand = fields["placement_candidate_limit"].default
    default_count = fields["placement_solution_count"].default

    preset_budget = _PRESET_BUDGET.get(options.preset, _PRESET_BUDGET["balanced"])
    time_used = options.placement_time_limit_ms
    cand_used = options.placement_candidate_limit
    count_used = options.placement_solution_count
    preset_used = False
    if time_used == default_time:
        time_used = preset_budget.time_limit_ms
        preset_used = True
    if cand_used == default_cand:
        cand_used = preset_budget.candidate_limit
        preset_used = True
    if count_used == default_count:
        count_used = preset_budget.solution_count
        preset_used = True
    return time_used, cand_used, count_used, preset_used


def solve_cpsat_placement(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    options: SolverOptions,
    initial_layout: TraceLayout | None = None,
    cancel: Callable[[], bool] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> PlacementResult:
    """Build the CP-SAT model, solve for K diverse candidates, route each,
    pick the best fully routed one."""
    t_start = time.perf_counter()
    if cancel is not None and cancel():
        raise SolverCancelled("cpsat placement cancelled before build")
    if progress is not None:
        progress("place", 0)

    # Locked placements (mirrors place._seed_locked_placements semantics).
    initial_layout = initial_layout or TraceLayout(board_id=board.id, placements=[])
    locked_placements = [p for p in initial_layout.placements if p.locked]
    locked_refs = {p.component_ref for p in locked_placements}

    # Components actually movable.
    movable_refs = [c.ref for c in components if c.ref not in locked_refs]

    time_limit_ms, candidate_limit, solution_count, preset_used = _resolve_budget(options)

    if not movable_refs:
        # Nothing to place: defer to greedy for the empty case so the
        # downstream solver pipeline sees a uniform PlacementResult.
        return place_greedy(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            options=options,
            initial_layout=initial_layout,
        )

    if progress is not None:
        progress("place", 5)

    candidates, hole_to_candidates, _locked_occ = build_candidate_poses(
        board=board,
        footprints=footprints,
        components=[c for c in components if c.ref not in locked_refs],
        locked_placements=locked_placements,
        candidate_limit=candidate_limit,
        initial_layout=initial_layout,
    )

    if progress is not None:
        progress("place", 10)

    if not candidates or all(len(c) == 0 for c in candidates.values()):
        # Nothing feasible: return unplaced for every movable component.
        trace = SolverTrace(
            seed=options.solver_seed,
            placement_order=[],
            pose_choices=[],
            rejections=[
                TraceRejection(component_ref=ref, reason="no_valid_pose", detail="cpsat: no candidates")
                for ref in movable_refs
            ],
            failed_nets=[],
            ripups=[],
            iteration_scores=[],
            phase_timings_ms={"place": round((time.perf_counter() - t_start) * 1000.0, 3)},
        )
        if progress is not None:
            progress("done", 100)
        return PlacementResult(placements=list(locked_placements), unplaced=movable_refs, trace=trace, cost=0.0)

    model, sel_vars = build_cpsat_model(
        candidates=candidates,
        hole_to_candidates=hole_to_candidates,
        locked_occupied={hid for p in locked_placements for hid in p.occupied_hole_ids},
    )

    if progress is not None:
        progress("place", 15)

    terms, _ = add_objective_terms(
        model,
        sel_vars=sel_vars,
        candidates=candidates,
        components=[c for c in components if c.ref not in locked_refs],
        nets=nets,
        board=board,
        locked_placements=locked_placements,
    )
    if terms:
        model.Minimize(sum(terms))

    if progress is not None:
        progress("place", 20)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.1, time_limit_ms / 1000.0)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = options.solver_seed
    solver.parameters.log_search_progress = False

    # Loop: solve, extract, no-good, solve again, up to solution_count.
    routing_budget_ms = max(200, int(0.4 * time_limit_ms))
    solving_budget_ms = time_limit_ms - routing_budget_ms
    per_solve_ms = max(50, solving_budget_ms // max(1, solution_count))

    collected: list[tuple[list[ComponentPlacement], PlacementObjectiveBreakdown]] = []
    previous_assignment: dict[str, int] = {}
    last_status = cp_model.OPTIMAL  # any non-INFEASIBLE

    for k in range(solution_count):
        if cancel is not None and cancel():
            raise SolverCancelled("cpsat placement cancelled during search")
        solver.parameters.max_time_in_seconds = max(0.1, per_solve_ms / 1000.0)
        status = solver.Solve(model)
        last_status = status
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            unplaced: list[str] = []
            extracted = _selected_pose_for(
                model, solver, sel_vars, candidates,
                [c for c in components if c.ref not in locked_refs],
                nets, board, locked_placements,
                DEFAULT_CPSAT_WEIGHTS, unplaced, footprints,
            )
            if extracted is not None:
                placements, breakdown = extracted
                collected.append((placements, breakdown))
                # Build previous_assignment for the no-good by matching
                # every movable placement back to its source CandidatePose.
                previous_assignment = {}
                for p in placements:
                    if p.component_ref not in candidates:
                        continue
                    for c in candidates[p.component_ref]:
                        if (
                            c.anchor_idx >= 0
                            and index_hole_id(c) == p.anchor_hole_id
                            and c.span == p.span
                            and c.orientation == p.orientation
                        ):
                            previous_assignment[p.component_ref] = c.pose_id
                            break
        elif status == cp_model.INFEASIBLE:
            break
        # UNKNOWN / MODEL_INVALID: skip and continue.
        if progress is not None:
            progress("place", 25 + int(60 * (k + 1) / solution_count))
        if k < solution_count - 1:
            _add_no_good_constraint(
                model, sel_vars=sel_vars, previous_assignment=previous_assignment
            )

    if progress is not None:
        progress("trace-route", 85)

    # Routing-aware selection.
    outcomes: list[_CandidateOutcome] = []
    for candidate_index, (placements, breakdown) in enumerate(collected):
        if cancel is not None and cancel():
            raise SolverCancelled("cpsat placement cancelled during routing")
        outcome = _evaluate_candidate(
            board=board,
            footprints=footprints,
            components=[c for c in components if c.ref not in locked_refs]
            + [c for c in components if c.ref in locked_refs],
            nets=nets,
            candidate=placements,
            cancel=cancel,
            progress=progress,
            proxy_breakdown=breakdown,
            placement_engine_ms=round((time.perf_counter() - t_start) * 1000.0, 3),
            candidate_index=candidate_index,
        )
        if outcome is not None:
            outcomes.append(outcome)

    if progress is not None:
        progress("trace-route", 95)

    if not outcomes:
        # Solver produced no usable candidate — return empty placements +
        # all movable as unplaced so the pipeline can still complete.
        trace = SolverTrace(
            seed=options.solver_seed,
            placement_order=[],
            pose_choices=[],
            rejections=[
                TraceRejection(
                    component_ref=ref,
                    reason="no_cpsat_solution",
                    detail=f"cp_model status: {solver.StatusName(last_status)}",
                )
                for ref in movable_refs
            ],
            failed_nets=[],
            ripups=[],
            iteration_scores=[],
            phase_timings_ms={
                "place": round((time.perf_counter() - t_start) * 1000.0, 3),
                "cpsat_preset_used": 1 if preset_used else 0,
            },
        )
        if progress is not None:
            progress("done", 100)
        return PlacementResult(
            placements=list(locked_placements),
            unplaced=movable_refs,
            trace=trace,
            cost=0.0,
        )

    best = _rank_outcomes(outcomes)
    final_placements = best.placements
    proxy_total = best.proxy_breakdown.total

    # Build trace: pose_choices + phase_timings_ms + status.
    pose_choices = [
        PoseChoice(
            component_ref=p.component_ref,
            anchor_hole_id=p.anchor_hole_id,
            orientation=p.orientation,
            span=p.span,
            cost=0.0,
        )
        for p in final_placements
        if p.component_ref not in locked_refs
    ]
    phase_timings = {
        "place": round((time.perf_counter() - t_start) * 1000.0, 3),
        "cpsat_solution_count": len(collected),
        "cpsat_routed_count": len(outcomes),
        "cpsat_preset_used": 1 if preset_used else 0,
        "cpsat_selected_candidate_index": best.candidate_index,
        "cpsat_proxy_total": proxy_total,
        "cpsat_trace_length_mm": round(best.trace_length_mm, 3),
        "cpsat_via_count": best.via_count,
        "cpsat_trace_count": best.trace_count,
        "cpsat_segment_count": best.segment_count,
        "cpsat_unrouted_count": len(best.unrouted_nets),
    }
    # Stash per-term breakdown into phase_timings_ms under prefixed keys.
    bd = best.proxy_breakdown.as_dict()
    for key, value in bd.items():
        phase_timings[f"cpsat_term_{key}"] = value

    trace = SolverTrace(
        seed=options.solver_seed,
        placement_order=[p.component_ref for p in final_placements if p.component_ref not in locked_refs],
        pose_choices=pose_choices,
        rejections=[],
        failed_nets=list(best.unrouted_nets),
        ripups=[],
        iteration_scores=[proxy_total],
        phase_timings_ms=phase_timings,
    )

    if progress is not None:
        progress("done", 100)

    return PlacementResult(
        placements=final_placements,
        unplaced=[],
        trace=trace,
        cost=float(proxy_total) / _MILLIMETRE_SCALE,
    )