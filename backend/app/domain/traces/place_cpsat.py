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
    "solve_status_from_code",
]


# --------------------------------------------------------------------------
# Scaling, weights, presets
# --------------------------------------------------------------------------


_MILLIMETRE_SCALE: int = 100  # 1 mm == 100 integer units (objective is in 1/100 mm)
_BIN_ROWS: int = 3
_BIN_COLS: int = 3
_HOT_BIN_THRESHOLD: int = 3  # bin becomes "hot" once >= N components touch it
# Cap on (DIP candidate × corridor cell) products in the in-model DIP
# pin-escape term. Past this count the linearization cost outweighs the
# benefit, so the term is skipped deterministically. 20 k keeps the
# flagship fixture under the per-solve budget while leaving the term
# active for realistic DIP placements.
_DIP_ESCAPE_PRODUCT_CAP: int = 20000


@dataclass(frozen=True, slots=True)
class CpsatWeights:
    """Integer coefficients for the soft objective terms.

    The objective scales lattice-step quantities by ``_step_q(board)`` so
    every term lives in the same 1/100 mm unit. Because ``net=16``, a
    weight ``W`` costs ``W/16`` hole-steps of net length per unit —
    ``anti_line=400`` therefore pays for ~25 hole-steps of net length
    per hole of span deficit, and ``row_wall=200`` ~12 hole-steps per
    extra component parked in one row/column. ``net`` was raised 4x from
    the original ``4`` so pin-level HPWL competes more strongly for
    clustering quality within a finite per-solve budget (CP-SAT rarely
    proves optimality on the flagship fixture, so the *rate* at which
    the first-found feasible solution improves matters). Tweak in
    ``DEFAULT_CPSAT_WEIGHTS``; presets keep these values fixed because
    only wall-time / candidate caps vary between presets.
    """

    net: int = 16
    decoupler: int = 96  # applied per-net to power/ground nets touching bypass caps
    compactness: int = 1  # bbox-centre offset
    bbox_span: int = 12  # (x_span + y_span) over the global bbox
    bbox_area: int = 1  # post-solve only — avoids a quadratic in the model
    anti_line: int = 400  # penalty per hole of min(x_span, y_span) deficit
    pin_proximity: int = 8  # post-solve breakdown only — no model term
    row_wall: int = 200  # penalty per extra component over the row/col cap
    dip_escape: int = 4  # ~1 hole-step per intruding DIP-pin-corridor cell
    edge: int = 40  # scaled with ``net``'s 4x bump so a connector's edge
    # bonus still outweighs the HPWL saving from drifting off the edge
    # toward a net-connected interior part (e.g. a single flexible
    # passive on the connector's only net)
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
    "fast": PresetBudget(1500, 80, 3),
    "balanced": PresetBudget(3000, 200, 5),
    "quality": PresetBudget(10000, 350, 8),
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


def _is_connector_or_header(footprint_id: str) -> bool:
    return footprint_id.startswith("CONN-") or footprint_id.startswith("HEADER-1x")


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


def _stratum(cand: CandidatePose, board: PerfboardModel) -> tuple[int, int, int]:
    """4x4 board-region band plus orientation — the diversity key."""
    min_col, min_row, _max_col, _max_row = cand.bbox
    row_band = (min_row - 1) * 4 // max(1, board.rows)
    col_band = (min_col - 1) * 4 // max(1, board.cols)
    return (row_band, col_band, cand.orientation)


def _stratified_round_robin(
    cands: list[CandidatePose], *, limit: int, board: PerfboardModel
) -> list[CandidatePose]:
    """Round-robin one pose per board-region/orientation stratum until
    ``limit`` is reached, so the kept pool covers the whole board instead
    of clustering around one target point. Each stratum's poses are
    pre-sorted by ``(mech_cost_q, anchor_idx, orientation, span)``."""
    buckets: dict[tuple[int, int, int], list[CandidatePose]] = {}
    for c in cands:
        buckets.setdefault(_stratum(c, board), []).append(c)
    for buf in buckets.values():
        buf.sort(
            key=lambda c: (
                c.mech_cost_q,
                c.anchor_idx,
                c.orientation,
                -1 if c.span is None else c.span,
            )
        )
    kept: list[CandidatePose] = []
    bucket_lists = [list(buckets[s]) for s in sorted(buckets)]
    while len(kept) < limit:
        advanced = False
        for buf in bucket_lists:
            if not buf:
                continue
            kept.append(buf.pop(0))
            advanced = True
            if len(kept) >= limit:
                break
        if not advanced:
            break
    return kept


def _select_candidates(
    all_cands: tuple[CandidatePose, ...],
    *,
    limit: int,
    board: PerfboardModel,
    edge_class: bool,
) -> list[CandidatePose]:
    """Deterministic stratified sampling so the kept pool covers the whole
    board instead of clustering around one target point.

    For connector/header footprints (``edge_class``), candidates are
    sorted globally by distance to the nearest board boundary instead of
    region-diverse round-robin — a plain round-robin only guarantees one
    pose per edge-touching stratum, which a small ``candidate_limit``
    (few edge strata among many interior ones) can starve out entirely.
    Distance-to-edge (not literal touch) is the right metric because a
    footprint carrying a ``min-clearance-holes`` rule can never legally
    touch row/col 1 or the far row/col — clearance is checked against the
    board boundary the same as an occupied neighbour, so the closest
    legal pose always sits exactly ``clearance`` cells in. Connectors
    genuinely need to hug the board's mounting edge, not spread across
    its interior like a passive, so global (not stratified) priority is
    correct here.
    """
    if not edge_class:
        return _stratified_round_robin(list(all_cands), limit=limit, board=board)

    def _edge_dist(c: CandidatePose) -> int:
        min_col, min_row, max_col, max_row = c.bbox
        return min(min_col - 1, board.cols - max_col, min_row - 1, board.rows - max_row)

    ordered = sorted(
        all_cands,
        key=lambda c: (
            _edge_dist(c),
            c.mech_cost_q,
            c.anchor_idx,
            c.orientation,
            -1 if c.span is None else c.span,
        ),
    )
    return ordered[:limit]


def build_candidate_poses(
    *,
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    locked_placements: list[ComponentPlacement],
    candidate_limit: int,
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
    * for every component over the cap, pick ``candidate_limit`` poses via
      deterministic stratified sampling so the kept pool covers the
      whole board instead of clustering around one target point;
    * keep every pose for components at or under the cap.
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

        if len(all_cands) <= candidate_limit:
            kept = _assign_pose_ids(all_cands)
        else:
            edge_class = _is_connector_or_header(footprint.id)
            selected = _select_candidates(
                all_cands, limit=candidate_limit, board=board, edge_class=edge_class
            )
            kept = _assign_pose_ids(selected)

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
    Always non-negative.

    The ``bbox_span`` and ``anti_line`` terms are *post-solve* deterministic
    costs derived from the chosen candidate bboxes — they are not in the
    CP-SAT linearised objective because modelling ``min(x_span, y_span)``
    cleanly requires cross-candidate pair products that explode the model.
    The post-solve penalty participates in candidate ranking but does not
    influence CP-SAT's choice of pose per component.
    """

    net_length: int = 0
    cluster_spread: int = 0
    pin_proximity: int = 0
    compactness: int = 0
    bbox_span: int = 0
    bbox_area: int = 0
    anti_line: int = 0
    row_wall: int = 0
    dip_escape: int = 0
    edge: int = 0
    orientation: int = 0
    congestion: int = 0
    mechanical: int = 0
    total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "netLength": self.net_length,
            "clusterSpread": self.cluster_spread,
            "pinProximity": self.pin_proximity,
            "compactness": self.compactness,
            "bboxSpan": self.bbox_span,
            "bboxArea": self.bbox_area,
            "antiLine": self.anti_line,
            "rowWall": self.row_wall,
            "dipEscape": self.dip_escape,
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


def _hole_rc(hole_id: str) -> tuple[int, int]:
    """``"row-col"`` → ``(row, col)`` as 1-based lattice ints."""
    row_str, col_str = hole_id.split("-", 1)
    return int(row_str), int(col_str)


def _step_q(board: PerfboardModel) -> int:
    """One lattice step in the objective's 1/100 mm integer unit (254 at 2.54 mm)."""
    return int(round(board.pitch_mm * _MILLIMETRE_SCALE))


def _anti_line_threshold(n_movable: int, board: PerfboardModel) -> int:
    """Smallest acceptable value of ``min(x_span, y_span)`` in lattice steps.

    A 1-D row/column of ``n`` parts has ``min_span <= 2``; requiring
    ``(n + 1) // 2`` forces a genuinely two-dimensional region while staying
    feasible on the board (8 movable parts on any board >= 5 in both axes
    → threshold 4).
    """
    if n_movable < 2:
        return 0
    return max(1, min((n_movable + 1) // 2, min(board.rows, board.cols) - 1))


def _wall_cap(n_movable: int) -> int:
    """Max components allowed to share one row (or column) before the
    row-wall penalty starts. Same rule the post-solve breakdown already
    used: ``max(2, n * 2 // 5)`` → 3 for 8 movable parts."""
    return max(2, n_movable * 2 // 5)


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


def _anchor_centre_rc(
    locked_placements: list[ComponentPlacement], board: PerfboardModel
) -> tuple[int, int]:
    """Lattice-unit centroid of locked occupied holes, else board centre."""
    if not locked_placements:
        return ((board.cols + 1) // 2, (board.rows + 1) // 2)
    cols: list[int] = []
    rows: list[int] = []
    for p in locked_placements:
        for hid in p.occupied_hole_ids:
            row, col = _hole_rc(hid)
            cols.append(col)
            rows.append(row)
    if not cols:
        return ((board.cols + 1) // 2, (board.rows + 1) // 2)
    return (sum(cols) // len(cols), sum(rows) // len(rows))


def _is_decoupler_net(net: Net, is_decoupler: Mapping[str, bool]) -> bool:
    """True when the net is power/ground and at least one pin belongs to a
    bypass-decoupler footprint."""
    if net.net_class not in ("power", "ground"):
        return False
    return any(is_decoupler.get(p.component_ref, False) for p in net.pins)


def _pin_coord_vars(
    model: cp_model.CpModel,
    *,
    sel_vars: dict[str, dict[int, cp_model.IntVar]],
    candidates: Mapping[str, tuple[CandidatePose, ...]],
    board: PerfboardModel,
) -> dict[tuple[str, str], tuple[cp_model.IntVar, cp_model.IntVar]]:
    """``(ref, pin_id) -> (col_var, row_var)`` in 1-based lattice units.

    ``col == sum(col_of_pose * sel_pose)`` is exact because the selection
    literals are one-hot. This is what lets the objective distinguish U1
    pin 5 from U1 pin 8 — the old ``pin_centroid_q`` could not.
    """
    pin_vars: dict[tuple[str, str], tuple[cp_model.IntVar, cp_model.IntVar]] = {}
    for ref, cands in candidates.items():
        if not cands:
            continue
        pin_ids = [pid for pid, _hid in cands[0].pin_holes]
        # Precompute each candidate's own (row, col) per pin id once so the
        # sum below varies per pose — using ``cands[0]``'s hole for every
        # pose would make the variable constant regardless of the actual
        # selection, which defeats exact per-pin HPWL.
        cand_pin_rc: list[dict[str, tuple[int, int]]] = [
            {pid: _hole_rc(hid) for pid, hid in c.pin_holes} for c in cands
        ]
        for pid in pin_ids:
            col_var = model.NewIntVar(1, board.cols, f"px_{ref}_{pid}")
            row_var = model.NewIntVar(1, board.rows, f"py_{ref}_{pid}")
            model.Add(
                col_var
                == sum(
                    cand_pin_rc[i][pid][1] * sel_vars[ref][c.pose_id]
                    for i, c in enumerate(cands)
                )
            )
            model.Add(
                row_var
                == sum(
                    cand_pin_rc[i][pid][0] * sel_vars[ref][c.pose_id]
                    for i, c in enumerate(cands)
                )
            )
            pin_vars[(ref, pid)] = (col_var, row_var)
    return pin_vars


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
    """Add every soft objective term to ``model``.

    The model is exact linear over pin coordinates: each (ref, pin_id)
    has two ``NewIntVar``s bound to the selected pose, so the objective
    can see U1 pin 5 distinct from U1 pin 8. Net HPWL, global bbox span,
    row/column walls, and an in-model DIP pin-escape term are all
    expressed in that linear space; only edge/congestion/mechanical stay
    as per-pose linear terms. Returns the list of linear expressions
    (for ``model.Minimize(sum(...))``) plus a zero breakdown the caller
    updates after solving.
    """
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

    # Locked pin holes for HPWL constant injection.
    locked_pin_holes: dict[str, dict[str, str]] = {}
    for p in locked_placements:
        locked_pin_holes[p.component_ref] = dict(p.pin_holes)

    step_q = _step_q(board)

    # ---- 0. Pin coordinate variables (exact, per-pin) ----
    pin_vars = _pin_coord_vars(
        model, sel_vars=sel_vars, candidates=candidates, board=board
    )

    # ---- 1. Net HPWL (exact linear over pin coordinates) ----
    for net in nets:
        xs: list[cp_model.LinearExpr] = []
        ys: list[cp_model.LinearExpr] = []
        for pin in net.pins:
            var = pin_vars.get((pin.component_ref, pin.pin))
            if var is not None:
                xs.append(var[0])
                ys.append(var[1])
                continue
            hid = locked_pin_holes.get(pin.component_ref, {}).get(pin.pin)
            if hid is not None:
                row, col = _hole_rc(hid)
                xs.append(model.NewConstant(col))
                ys.append(model.NewConstant(row))
        if len(xs) < 2:
            continue  # single-pin net (e.g. VCC) contributes nothing
        x_lo = model.NewIntVar(1, board.cols, f"hpwl_xlo_{net.id}")
        x_hi = model.NewIntVar(1, board.cols, f"hpwl_xhi_{net.id}")
        y_lo = model.NewIntVar(1, board.rows, f"hpwl_ylo_{net.id}")
        y_hi = model.NewIntVar(1, board.rows, f"hpwl_yhi_{net.id}")
        model.AddMinEquality(x_lo, xs)
        model.AddMaxEquality(x_hi, xs)
        model.AddMinEquality(y_lo, ys)
        model.AddMaxEquality(y_hi, ys)
        hpwl = model.NewIntVar(0, board.cols + board.rows, f"hpwl_{net.id}")
        model.Add(hpwl == (x_hi - x_lo) + (y_hi - y_lo))
        net_weight = weights.decoupler if _is_decoupler_net(net, is_decoupler) else weights.net
        terms.append(net_weight * step_q * hpwl)

    # ---- 2. Global 2-D spread (bbox span + anti-line deficit) ----
    n_movable = len(candidates)
    threshold = _anti_line_threshold(n_movable, board)
    cminx: dict[str, cp_model.IntVar] = {}
    cmaxx: dict[str, cp_model.IntVar] = {}
    cminy: dict[str, cp_model.IntVar] = {}
    cmaxy: dict[str, cp_model.IntVar] = {}
    cminx_list: list[cp_model.LinearExpr] = []
    cmaxx_list: list[cp_model.LinearExpr] = []
    cminy_list: list[cp_model.LinearExpr] = []
    cmaxy_list: list[cp_model.LinearExpr] = []
    for ref, cands in candidates.items():
        if not cands:
            continue
        cminx[ref] = model.NewIntVar(1, board.cols, f"cminx_{ref}")
        cmaxx[ref] = model.NewIntVar(1, board.cols, f"cmaxx_{ref}")
        cminy[ref] = model.NewIntVar(1, board.rows, f"cminy_{ref}")
        cmaxy[ref] = model.NewIntVar(1, board.rows, f"cmaxy_{ref}")
        model.Add(
            cminx[ref]
            == sum(c.bbox[0] * sel_vars[ref][c.pose_id] for c in cands)
        )
        model.Add(
            cmaxx[ref]
            == sum(c.bbox[2] * sel_vars[ref][c.pose_id] for c in cands)
        )
        model.Add(
            cminy[ref]
            == sum(c.bbox[1] * sel_vars[ref][c.pose_id] for c in cands)
        )
        model.Add(
            cmaxy[ref]
            == sum(c.bbox[3] * sel_vars[ref][c.pose_id] for c in cands)
        )
        cminx_list.append(cminx[ref])
        cmaxx_list.append(cmaxx[ref])
        cminy_list.append(cminy[ref])
        cmaxy_list.append(cmaxy[ref])
    # Inject locked placements as constants so the spread covers all
    # board content, not just the movable pieces.
    for p in locked_placements:
        cols: list[int] = []
        rows: list[int] = []
        for hid in p.occupied_hole_ids:
            row, col = _hole_rc(hid)
            cols.append(col)
            rows.append(row)
        if cols:
            cminx_list.append(model.NewConstant(min(cols)))
            cmaxx_list.append(model.NewConstant(max(cols)))
            cminy_list.append(model.NewConstant(min(rows)))
            cmaxy_list.append(model.NewConstant(max(rows)))

    gminx = model.NewIntVar(1, board.cols, "gminx")
    gmaxx = model.NewIntVar(1, board.cols, "gmaxx")
    gminy = model.NewIntVar(1, board.rows, "gminy")
    gmaxy = model.NewIntVar(1, board.rows, "gmaxy")
    model.AddMinEquality(gminx, cminx_list)
    model.AddMaxEquality(gmaxx, cmaxx_list)
    model.AddMinEquality(gminy, cminy_list)
    model.AddMaxEquality(gmaxy, cmaxy_list)
    span_x = model.NewIntVar(0, board.cols, "span_x")
    span_y = model.NewIntVar(0, board.rows, "span_y")
    model.Add(span_x == gmaxx - gminx)
    model.Add(span_y == gmaxy - gminy)
    min_span = model.NewIntVar(0, max(board.cols, board.rows), "min_span")
    model.AddMinEquality(min_span, [span_x, span_y])
    if threshold > 0:
        deficit = model.NewIntVar(0, threshold, "anti_line_deficit")
        model.Add(deficit >= threshold - min_span)
        terms.append(weights.anti_line * step_q * deficit)
    terms.append(weights.bbox_span * step_q * (span_x + span_y))

    # ---- 3. Centring on the bbox centre (replaces per-component pull) ----
    target_col, target_row = _anchor_centre_rc(locked_placements, board)
    off_x = model.NewIntVar(0, board.cols, "off_x")
    off_y = model.NewIntVar(0, board.rows, "off_y")
    model.AddAbsEquality(off_x, gminx + gmaxx - 2 * target_col)
    model.AddAbsEquality(off_y, gminy + gmaxy - 2 * target_row)
    terms.append(weights.compactness * step_q * (off_x + off_y))

    # ---- 4. Row and column walls ----
    rows_of: dict[tuple[str, int], set[int]] = {}
    cols_of: dict[tuple[str, int], set[int]] = {}
    for ref, cands in candidates.items():
        for c in cands:
            rows_set: set[int] = set()
            cols_set: set[int] = set()
            for hid in c.occupied_hole_ids:
                row, col = _hole_rc(hid)
                rows_set.add(row)
                cols_set.add(col)
            rows_of[(ref, c.pose_id)] = rows_set
            cols_of[(ref, c.pose_id)] = cols_set
    cap = _wall_cap(n_movable)
    if n_movable >= 2 and cap >= 0:
        for r in range(1, board.rows + 1):
            users: list[cp_model.LinearExpr] = []
            for ref, cands in candidates.items():
                matching = [c for c in cands if r in rows_of[(ref, c.pose_id)]]
                if not matching:
                    continue
                users.append(
                    sum(sel_vars[ref][c.pose_id] for c in matching)
                )
            if not users or len(users) <= cap:
                continue
            total = sum(users)
            excess = model.NewIntVar(0, len(users), f"row_excess_{r}")
            model.Add(excess >= total - cap)
            terms.append(weights.row_wall * step_q * excess)
        for c_idx in range(1, board.cols + 1):
            users = []
            for ref, cands in candidates.items():
                matching = [c for c in cands if c_idx in cols_of[(ref, c.pose_id)]]
                if not matching:
                    continue
                users.append(
                    sum(sel_vars[ref][c.pose_id] for c in matching)
                )
            if not users or len(users) <= cap:
                continue
            total = sum(users)
            excess = model.NewIntVar(0, len(users), f"col_excess_{c_idx}")
            model.Add(excess >= total - cap)
            terms.append(weights.row_wall * step_q * excess)

    # ---- 5. DIP pin-escape corridor (in-model, capped) ----
    # Build occupancy booleans for every hole touched by a non-DIP
    # candidate. The feasibility model already enforces "at most one
    # candidate per hole", so a single BoolVar summing the selection
    # literals is a valid occupancy indicator.
    nondip_selectors: dict[str, list[cp_model.IntVar]] = {}
    for ref, cands in candidates.items():
        for c in cands:
            if c.footprint_id.startswith("DIP-"):
                continue
            for hid in c.occupied_hole_ids:
                nondip_selectors.setdefault(hid, []).append(sel_vars[ref][c.pose_id])
    occ_nondip: dict[str, cp_model.IntVar] = {}
    for hid, literals in nondip_selectors.items():
        if len(literals) == 1:
            occ_nondip[hid] = literals[0]
        else:
            var = model.NewBoolVar(f"occ_nondip_{hid}")
            model.Add(var <= sum(literals))
            occ_nondip[hid] = var
    dip_pairs: list[tuple[CandidatePose, str, cp_model.IntVar]] = []
    pair_count = 0
    for ref, cands in candidates.items():
        for c in cands:
            if not c.footprint_id.startswith("DIP-"):
                continue
            occupied: set[tuple[int, int]] = {
                _hole_rc(hid) for hid in c.occupied_hole_ids
            }
            for _pid, hid in c.pin_holes:
                pr, pc = _hole_rc(hid)
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if abs(dr) + abs(dc) != 1:
                            continue
                        rr = pr + dr
                        cc = pc + dc
                        if not (1 <= rr <= board.rows and 1 <= cc <= board.cols):
                            continue
                        if (rr, cc) in occupied:
                            continue
                        corridor_hid = f"{rr}-{cc}"
                        occ_var = occ_nondip.get(corridor_hid)
                        if occ_var is None:
                            continue
                        pair_count += 1
                        dip_pairs.append((c, corridor_hid, occ_var))
    if pair_count <= _DIP_ESCAPE_PRODUCT_CAP:
        for idx, (c, corridor_hid, occ_var) in enumerate(dip_pairs):
            sel = sel_vars[c.component_ref][c.pose_id]
            z = model.NewBoolVar(
                f"dipescape_{c.component_ref}_{c.pose_id}_{corridor_hid}_{idx}"
            )
            model.Add(z <= sel)
            model.Add(z <= occ_var)
            model.Add(z >= sel + occ_var - 1)
            terms.append(weights.dip_escape * step_q * z)

    # ---- 6. Connector edge preference ----
    # Graded by distance to the nearest board boundary, not literal touch:
    # a footprint carrying a ``min-clearance-holes`` rule (nearly every
    # real connector/header) can never legally touch row/col 1 or the far
    # row/col — the closest legal pose always sits exactly ``clearance``
    # cells in. Rewarding only a literal touch left the term permanently
    # inert for those footprints. Negated (subtracted from cost) because
    # this is a bonus for being near the edge, not a penalty.
    for ref, cands in candidates.items():
        if not cands or not _is_connector_or_header(cands[0].footprint_id):
            continue
        for c in cands:
            min_col, min_row, max_col, max_row = c.bbox
            edge_dist = min(min_col - 1, board.cols - max_col, min_row - 1, board.rows - max_row)
            edge_bonus = weights.edge * max(0, 2 - edge_dist)
            if _along_edge(c, board):
                edge_bonus += weights.edge // 2
            terms.append(-edge_bonus * sel_vars[ref][c.pose_id])

    # ---- 7. Orientation preference ----
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

    # ---- 8. Congestion (3x3 bins) ----
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
                    if (int(cell.split("-")[0]) - 1) // _BIN_ROWS == rb
                    and (int(cell.split("-")[1]) - 1) // _BIN_COLS == cb
                )
                if n:
                    terms.append(weights.congestion * n * sel_vars[ref][c.pose_id])

    # ---- 9. Mechanical cost ----
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
    min_changes: int = 1,
) -> None:
    """Forbid the literal assignment ``previous_assignment`` from reappearing.

    Implementation: at least ``min_changes`` components must pick a different
    pose from ``previous_assignment``.

        sum(1 - sel_vars[ref][previous_assignment[ref]]) >= min_changes

    Equivalent to the brief's ``sum(s_i for selected) <= n - min_changes``
    form. Raising ``min_changes`` past 1 makes each new candidate differ in
    many components instead of one, so the diversity pool explores the
    solution space rather than drifting one hole at a time.
    """
    clauses: list[cp_model.IntVar] = []
    for ref, prev_pose_id in previous_assignment.items():
        var = sel_vars.get(ref, {}).get(prev_pose_id)
        if var is None:
            continue
        clauses.append(var)
    if not clauses:
        return
    threshold = max(1, min(min_changes, len(clauses)))
    # At least ``threshold`` of the previously selected poses must be
    # unselected. sum(1 - var) >= threshold ⇔ len - sum(var) >= threshold
    # ⇔ sum(var) <= len - threshold.
    model.Add(sum(clauses) <= len(clauses) - threshold)


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
    # Post-solve physical metrics — populated alongside the routed outcome
    # so the candidate ranker can break ties / penalise degenerate layouts.
    x_span: int = 0
    y_span: int = 0
    min_span: int = 0
    max_components_per_row: int = 0
    line_collapse: int = 0
    dip_escape_violations: int = 0
    single_pin_net_count: int = 0
    validation_error_count: int = 0


@dataclass(frozen=True, slots=True, order=True)
class RoutedCandidateRank:
    """Lexicographic rank key for a routed candidate.

    Order (left = wins):
        1. ``validation_error_count``   (must be zero to win)
        2. ``single_pin_net_count``     (must be zero to be fully routed)
        3. ``unrouted_net_count``
        4. ``line_collapse``            (penalty asc; deficit of min_span vs
                                          ``_anti_line_threshold``)
        5. ``dip_escape_violations``    (penalty asc; block-traced cells)
        6. ``via_count``
        7. ``trace_length_units``
        8. ``segment_count``
        9. ``routing_cost_units``
       10. ``placement_proxy_score``    (final tie-breaker)
       11. ``candidate_index``          (deterministic final tie-breaker)

    ``min_span`` was the previous rank field but ordering it ascending
    preferred the *flattest* candidate — the exact defect it was added
    to prevent. ``line_collapse`` is a bounded deficit that is ``0`` for
    every acceptable layout, so it only ever discriminates against
    degenerate ones and otherwise falls through to real routing quality.
    ``max_components_per_row`` is dropped from the key because a
    legitimate dense 2-D cluster with several vertical parts can share a
    row band without being a wall; it stays as a reported metric on
    ``_CandidateOutcome`` and the ``cpsat_max_components_per_row`` trace
    key.
    """

    validation_error_count: int
    single_pin_net_count: int
    unrouted_net_count: int
    line_collapse: int
    dip_escape_violations: int
    via_count: int
    trace_length_units: float
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
    single_pin_net_count = sum(1 for d in validation.diagnostics if d.code == "NET_SINGLE_PIN")
    # Physical layout metrics. Computed from the *placement* (not the routed
    # layout) so degenerate row-collapses are visible even when routing
    # somehow succeeds.
    component_by_ref = {c.ref: c for c in components}
    chosen_for_metrics: dict[str, CandidatePose] = {}
    for p in candidate:
        comp = component_by_ref.get(p.component_ref)
        footprint_id = comp.footprint_id if comp else ""
        chosen_for_metrics[p.component_ref] = _placement_to_metric_pose(p, footprint_id)
    _min_col, _min_row, _max_col, _max_row, x_span, y_span = _placement_bbox_span(chosen_for_metrics)
    min_span = min(x_span, y_span)
    max_per_row, _ = _axis_distribution(chosen_for_metrics)
    line_collapse = max(0, _anti_line_threshold(len(candidate), board) - min_span)
    dip_escape = _dip_pin_escape_violations(chosen_for_metrics, board)
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
        x_span=x_span,
        y_span=y_span,
        min_span=min_span,
        max_components_per_row=max_per_row,
        line_collapse=line_collapse,
        dip_escape_violations=dip_escape,
        single_pin_net_count=single_pin_net_count,
        validation_error_count=len(placement_errors),
    )


def progress_marker(layout: TraceLayout) -> int:
    """Best-effort progress marker for ``progress("trace-route", pct)``."""
    return min(99, 90 + (5 if layout.traces else 0))


def _rank_outcomes(outcomes: list[_CandidateOutcome]) -> _CandidateOutcome:
    """Rank candidates by actual routed quality, with structural / pin-level
    metrics as tie-breakers and the CP-SAT proxy score as the final fallback.

    The lexicographic key is :class:`RoutedCandidateRank`; lower wins on every
    field. ``candidate_index`` is the deterministic final tie-breaker so
    two equally-routed candidates always resolve to the same choice.
    """

    def rank(outcome: _CandidateOutcome) -> RoutedCandidateRank:
        return RoutedCandidateRank(
            validation_error_count=outcome.validation_error_count,
            single_pin_net_count=outcome.single_pin_net_count,
            unrouted_net_count=len(outcome.unrouted_nets),
            line_collapse=outcome.line_collapse,
            dip_escape_violations=outcome.dip_escape_violations,
            via_count=outcome.via_count,
            trace_length_units=outcome.trace_length_mm,
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


def _placement_bbox_span(chosen: Mapping[str, CandidatePose]) -> tuple[int, int, int, int, int, int]:
    """Return ``(min_col, min_row, max_col, max_row, x_span, y_span)`` over the
    union of every chosen candidate's occupied holes, plus a min(x_span, y_span).

    Translation of an equivalent arrangement to another board region does not
    change the spans — they are origin-neutral, which is the desired
    compactness invariant per the perfboard edge-collapse brief.
    """
    if not chosen:
        return 0, 0, 0, 0, 0, 0
    cols: list[int] = []
    rows: list[int] = []
    for cand in chosen.values():
        for hid in cand.occupied_hole_ids:
            row_str, col_str = hid.split("-", 1)
            cols.append(int(col_str))
            rows.append(int(row_str))
    if not cols:
        return 0, 0, 0, 0, 0, 0
    min_col, max_col = min(cols), max(cols)
    min_row, max_row = min(rows), max(rows)
    x_span = max(0, max_col - min_col)
    y_span = max(0, max_row - min_row)
    return min_col, min_row, max_col, max_row, x_span, y_span


def _axis_distribution(chosen: Mapping[str, CandidatePose]) -> tuple[int, int]:
    """Return ``(max_components_per_row, max_components_per_col)`` for the
    chosen placements. Drives the row-wall anti-collapse penalty on both
    axes — a vertical parking strip is the same defect mirrored.
    """
    if not chosen:
        return 0, 0
    by_row: dict[int, set[str]] = {}
    by_col: dict[int, set[str]] = {}
    for ref, cand in chosen.items():
        for hid in cand.occupied_hole_ids:
            row, col = _hole_rc(hid)
            by_row.setdefault(row, set()).add(ref)
            by_col.setdefault(col, set()).add(ref)
    max_per_row = max((len(refs) for refs in by_row.values()), default=0)
    max_per_col = max((len(refs) for refs in by_col.values()), default=0)
    return max_per_row, max_per_col


def _dip_pin_escape_violations(
    chosen: Mapping[str, CandidatePose],
    board: PerfboardModel,
    *,
    escape_holes: int = 1,
) -> int:
    """Count cells a non-DIP candidate occupies within the DIP-pin escape
    corridor (default 1 hole around any DIP pin). The corridor is the
    set of cells immediately adjacent to a DIP pin on the same board —
    a trace needs at least one free hole next to each DIP pin to leave
    the package without jumping over its body.

    Returns the total count of (candidate, corridor-cell) pairs that
    intrude into the escape region. Multiple cell intrusions from one
    candidate each count once.
    """
    dip_pins: set[tuple[int, int]] = set()
    for cand in chosen.values():
        if not cand.footprint_id.startswith("DIP-"):
            continue
        for _pid, hid in cand.pin_holes:
            row_str, col_str = hid.split("-", 1)
            dip_pins.add((int(row_str), int(col_str)))
    if not dip_pins:
        return 0
    corridor: set[tuple[int, int]] = set()
    for row, col in dip_pins:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr = row + dr
                cc = col + dc
                if 1 <= rr <= board.rows and 1 <= cc <= board.cols:
                    if abs(dr) + abs(dc) <= escape_holes:
                        corridor.add((rr, cc))
    # Drop cells the DIP itself occupies — those aren't escape corridors.
    dip_occupied: set[tuple[int, int]] = set()
    for cand in chosen.values():
        if not cand.footprint_id.startswith("DIP-"):
            continue
        for hid in cand.occupied_hole_ids:
            row_str, col_str = hid.split("-", 1)
            dip_occupied.add((int(row_str), int(col_str)))
    corridor -= dip_occupied
    if not corridor:
        return 0
    violations = 0
    for cand in chosen.values():
        if cand.footprint_id.startswith("DIP-"):
            continue  # don't penalise DIP-on-DIP stacking here
        for hid in cand.occupied_hole_ids:
            row_str, col_str = hid.split("-", 1)
            if (int(row_str), int(col_str)) in corridor:
                violations += 1
    return violations


def _pin_pair_proximity(
    chosen: Mapping[str, CandidatePose],
    nets: list[Net],
    *,
    max_pairs_per_net: int = 4,
) -> int:
    """Pin-hole Manhattan distance between every net pin pair (capped).

    Distinct from ``net_length`` (hub-based) — this drives the
    pin-level proximity term that bounds how far apart two physically-
    local pins can be. Only the closest ``max_pairs_per_net`` pin pairs
    per net contribute so a 6-pin net does not blow up the model.
    """
    pairs: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
    for net in nets:
        pin_locs: list[tuple[int, int]] = []
        for pin in net.pins:
            cand = chosen.get(pin.component_ref)
            if cand is None:
                continue
            for pid, hid in cand.pin_holes:
                if pid != pin.pin:
                    continue
                row_str, col_str = hid.split("-", 1)
                pin_locs.append((int(row_str), int(col_str)))
                break
        if len(pin_locs) < 2:
            continue
        # Closest pairs only.
        local_pairs: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
        for i, a in enumerate(pin_locs):
            for b in pin_locs[i + 1 :]:
                d = abs(a[0] - b[0]) + abs(a[1] - b[1])
                local_pairs.append((d, a, b))
        local_pairs.sort()
        for d, a, b in local_pairs[:max_pairs_per_net]:
            pairs.append((d, a, b))
    total = 0
    for d, _a, _b in pairs:
        total += d
    return total


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

    step_q = _step_q(board)
    locked_pin_holes: dict[str, dict[str, str]] = {
        p.component_ref: dict(p.pin_holes) for p in locked_placements
    }
    cluster_anchor_of: dict[str, str] = {}
    clusters = build_clusters(components, nets, fp_lookup)
    for cluster in clusters:
        anchor_ref = cluster.anchor_ref or cluster.id
        for member in cluster.member_refs:
            cluster_anchor_of[member] = anchor_ref

    def _pin_rc(pin_ref) -> tuple[int, int] | None:
        cand = chosen.get(pin_ref.component_ref)
        if cand is not None:
            for pid, hid in cand.pin_holes:
                if pid == pin_ref.pin:
                    return _hole_rc(hid)
            return None
        hid = locked_pin_holes.get(pin_ref.component_ref, {}).get(pin_ref.pin)
        return _hole_rc(hid) if hid is not None else None

    is_decoupler: dict[str, bool] = {
        ref: bool(
            cluster_anchor_of.get(ref, ref) != ref
            and _footprint_of(ref, components) in _DECOUPLER_FOOTPRINTS
        )
        for ref in chosen
    }

    # 1. Net length — half-perimeter wire length over actual pin holes,
    #    mirroring the in-model HPWL term.
    pin_locs: dict[tuple[str, str], tuple[int, int]] = {}
    for ref, cand in chosen.items():
        for pid, hid in cand.pin_holes:
            pin_locs[(ref, pid)] = _hole_rc(hid)
    for ref, pins in locked_pin_holes.items():
        for pid, hid in pins.items():
            pin_locs[(ref, pid)] = _hole_rc(hid)
    for net in nets:
        locs: list[tuple[int, int]] = []
        for pin in net.pins:
            loc = _pin_rc(pin) or pin_locs.get((pin.component_ref, pin.pin))
            if loc is not None:
                locs.append(loc)
        if len(locs) < 2:
            continue
        cols = [c for _r, c in locs]
        rows = [r for r, _c in locs]
        hpwl_lattice = (max(cols) - min(cols)) + (max(rows) - min(rows))
        net_weight = (
            weights.decoupler
            if (net.net_class in ("power", "ground")
                and any(is_decoupler.get(p.component_ref, False) for p in net.pins))
            else weights.net
        )
        breakdown.net_length += net_weight * step_q * hpwl_lattice

    # 2. Cluster proximity — decoupler-only report. Other cluster
    #    members' spread is now captured by HPWL.
    for member_ref, anchor_ref in cluster_anchor_of.items():
        if member_ref == anchor_ref:
            continue
        ca = chosen.get(anchor_ref)
        cm = chosen.get(member_ref)
        if ca is None or cm is None:
            continue
        if not is_decoupler.get(member_ref, False):
            continue
        breakdown.cluster_spread += weights.decoupler * _manhattan_q(
            ca.centroid_q, cm.centroid_q
        )

    # 2b. Pin-pair proximity (the closest 4 pin pairs per net). Captures
    #     the high-priority local connections between two specific pins,
    #     independent of which is the hub.
    breakdown.pin_proximity = weights.pin_proximity * _pin_pair_proximity(chosen, nets)

    # 3. Compactness — bbox-centre offset, anchored at the locked
    #    centroid (or board centre if no locked placements).
    if chosen:
        target_col, target_row = _anchor_centre_rc(locked_placements, board)
        _min_col, _min_row, _max_col, _max_row, _, _ = _placement_bbox_span(chosen)
        breakdown.compactness = (
            weights.compactness
            * step_q
            * (abs(_min_col + _max_col - 2 * target_col)
               + abs(_min_row + _max_row - 2 * target_row))
        )

    # 3b. Origin-neutral 2D bbox penalty + anti-line-collapse penalty.
    #     Computed once per candidate (not per pair) — stays cheap.
    if chosen:
        _min_col, _min_row, _max_col, _max_row, x_span, y_span = _placement_bbox_span(chosen)
        # bbox span is in lattice steps; multiply by step_q to keep the
        # same integer-unit scale as the rest of the breakdown.
        breakdown.bbox_span = weights.bbox_span * step_q * (x_span + y_span)
        breakdown.bbox_area = weights.bbox_area * int(
            round((x_span + 1) * (y_span + 1) * (2.54 * _MILLIMETRE_SCALE) ** 2 / _MILLIMETRE_SCALE)
        )
        # Anti-line collapse: single-axis deficit against the threshold.
        threshold = _anti_line_threshold(len(chosen), board)
        if threshold > 0:
            min_span = min(x_span, y_span)
            if min_span < threshold:
                breakdown.anti_line = (
                    weights.anti_line * step_q * (threshold - min_span)
                )

    # 3c. Row-wall penalty: linear, two-axis, matching the in-model term.
    if chosen and not _is_linear_layout_allowed(chosen, fp_lookup):
        max_per_row, max_per_col = _axis_distribution(chosen)
        n_movable = len(chosen)
        cap = _wall_cap(n_movable)
        row_excess = max(0, max_per_row - cap)
        col_excess = max(0, max_per_col - cap)
        breakdown.row_wall = (
            weights.row_wall * step_q * (row_excess + col_excess)
        )

    # 3d. DIP-pin escape corridor penalty.
    breakdown.dip_escape = weights.dip_escape * _dip_pin_escape_violations(chosen, board)

    # 4. Edge — graded bonus (negative contribution), mirrors the in-model
    #    term. See ``add_objective_terms`` term 6 for the rationale.
    for ref, cand in chosen.items():
        if not _is_connector_or_header(cand.footprint_id):
            continue
        min_col, min_row, max_col, max_row = cand.bbox
        edge_dist = min(min_col - 1, board.cols - max_col, min_row - 1, board.rows - max_row)
        edge_bonus = weights.edge * max(0, 2 - edge_dist)
        if _along_edge(cand, board):
            edge_bonus += weights.edge // 2
        breakdown.edge -= edge_bonus

    # 5. Orientation.
    for ref, cand in chosen.items():
        if cand.footprint_id.startswith("DIP-"):
            breakdown.orientation += 0 if cand.orientation == 0 else weights.orientation

    # 6. Congestion.
    bin_to_components: dict[tuple[int, int], set[str]] = {}
    for ref, cand in chosen.items():
        for cell in cand.occupied_hole_ids:
            row, col = _hole_rc(cell)
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
                if (int(cell.split("-")[0]) - 1) // _BIN_ROWS == rb
                and (int(cell.split("-")[1]) - 1) // _BIN_COLS == cb
            )
            breakdown.congestion += weights.congestion * n

    # 7. Mechanical.
    for ref, cand in chosen.items():
        breakdown.mechanical += weights.mechanical * cand.mech_cost_q

    breakdown.total = (
        breakdown.net_length
        + breakdown.cluster_spread
        + breakdown.pin_proximity
        + breakdown.compactness
        + breakdown.bbox_span
        + breakdown.bbox_area
        + breakdown.anti_line
        + breakdown.row_wall
        + breakdown.dip_escape
        + breakdown.edge
        + breakdown.orientation
        + breakdown.congestion
        + breakdown.mechanical
    )
    return breakdown


def _is_linear_layout_allowed(
    chosen: Mapping[str, CandidatePose],
    footprints: Mapping[str, ThroughHoleFootprint],
) -> bool:
    """Return True when the chosen set is legitimately linear — a header,
    connector bank, or LED bar whose footprint profile is long in one axis.

    The row-wall penalty is suppressed for these because a single-row
    arrangement is the user's intent, not a solver artefact.
    """
    if not chosen:
        return True
    eligible_linear = 0
    eligible_non_linear = 0
    for ref, cand in chosen.items():
        fp = footprints.get(cand.footprint_id)
        if fp is None:
            eligible_non_linear += 1
            continue
        if _is_connector_or_header(cand.footprint_id) or cand.footprint_id.startswith("LED"):
            eligible_linear += 1
        else:
            eligible_non_linear += 1
    # All linear-eligible, no IC/passive → linear layout allowed.
    return eligible_non_linear == 0


def _placement_to_metric_pose(p: ComponentPlacement, footprint_id: str = "") -> CandidatePose:
    """Synthesise a minimal CandidatePose from a canonical ComponentPlacement
    so the bbox / row-distribution / dip-escape helpers can run on
    post-routing placement lists (which only carry ComponentPlacement).

    The synthesised pose only exposes the fields those helpers read:
    ``bbox``, ``occupied_hole_ids``, ``pin_holes``, ``footprint_id``.
    Centroid / pin-centroid stay at (0, 0) because they aren't needed.
    """
    return CandidatePose(
        component_ref=p.component_ref,
        pose_id=-1,
        anchor_idx=-1,
        orientation=p.orientation,
        span=p.span,
        pin_holes=tuple(sorted(p.pin_holes.items(), key=lambda kv: kv[0])),
        body_hole_ids=tuple(p.occupied_hole_ids),
        occupied_hole_ids=frozenset(p.occupied_hole_ids),
        centroid_q=(0, 0),
        mech_cost_q=0,
        bbox=_bbox_for_holes(p.occupied_hole_ids),
        pin_centroid_q=(0, 0),
        footprint_id=footprint_id,
    )


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
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = options.solver_seed
    solver.parameters.log_search_progress = False

    def _apply_solve_budget(this_solve_ms: int) -> None:
        """Bound the next ``Solve()`` by deterministic work, not wall-clock
        time. ``max_time_in_seconds`` alone makes CP-SAT's truncated
        (non-optimal) search machine/load-dependent — two runs with an
        identical ``time_limit_ms`` can explore different amounts of the
        search tree depending on real CPU speed at that moment, so the
        result differs even with the same ``random_seed``. Verified
        empirically: two solves with the same ``max_deterministic_time``
        return bit-identical placements; two solves with the same
        ``max_time_in_seconds`` do not. The wall-clock cap stays as a
        generous (3x), normally-non-binding safety net against a
        pathologically slow host.
        """
        this_solve_s = this_solve_ms / 1000.0
        solver.parameters.max_deterministic_time = this_solve_s
        solver.parameters.max_time_in_seconds = max(60.0, this_solve_s * 3.0)


    # Loop: solve, extract, no-good, solve again, up to solution_count.
    # Routing + validation is empirically ~5ms per candidate for perfboard
    # fixtures (maze build + trace route + diagnostics), so the budget
    # carve-out for it only needs a small fixed floor, not a fraction of
    # ``time_limit_ms`` — nearly everything should go to solving.
    routing_budget_ms = max(300, int(0.05 * time_limit_ms))
    solving_budget_ms = time_limit_ms - routing_budget_ms
    # The first solve gets the majority (70%) of the solving budget.
    # Measured on the flagship 8-component fixture at ``candidate_limit=200``:
    # CP-SAT reaches *any* feasible solution in ~2.5s, but the exact
    # pin-coordinate HPWL term only pulls related parts close together
    # (e.g. a timing resistor next to its IC pin) if the solver keeps
    # improving past that first solution — at a 3s budget target pin
    # pairs sit 7-13 lattice steps apart, at 10s they sit 2-6 apart. A
    # solve is NOT stopped early on the first solution found: CP-SAT
    # already returns as soon as it proves OPTIMAL/INFEASIBLE, so a
    # generous budget only costs time when the solver has genuine room
    # to improve. Remaining solves exist purely for ranking diversity
    # and share what's left of the budget; the floor still guarantees
    # each one a realistic chance to find something.
    #
    # Budgets are computed once, statically, from ``time_limit_ms`` —
    # NOT from wall-clock elapsed time. CP-SAT's time-limited search is
    # not bit-for-bit reproducible across different ``max_time_in_seconds``
    # values even with a fixed ``random_seed``, so deriving the per-solve
    # budget from ``time.perf_counter()`` (which jitters a few ms between
    # otherwise-identical runs) made two calls with identical options
    # return different layouts. A static split trades a little adaptivity
    # for exact determinism.
    _SOLVE_FLOOR_S = 2.0
    _FIRST_SOLVE_SHARE = 0.7
    first_solve_ms = max(int(_SOLVE_FLOOR_S * 1000), int(solving_budget_ms * _FIRST_SOLVE_SHARE))
    rest_budget_ms = max(0, solving_budget_ms - first_solve_ms)
    per_solve_ms = (
        max(int(_SOLVE_FLOOR_S * 1000), rest_budget_ms // max(1, solution_count - 1))
        if solution_count > 1
        else 0
    )

    collected: list[tuple[list[ComponentPlacement], PlacementObjectiveBreakdown]] = []
    previous_assignment: dict[str, int] = {}
    last_status = cp_model.OPTIMAL  # any non-INFEASIBLE

    for k in range(solution_count):
        if cancel is not None and cancel():
            raise SolverCancelled("cpsat placement cancelled during search")
        this_solve_ms = first_solve_ms if k == 0 else per_solve_ms
        _apply_solve_budget(this_solve_ms)
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
                model,
                sel_vars=sel_vars,
                previous_assignment=previous_assignment,
                min_changes=max(1, len(previous_assignment) // 2),
            )

    if progress is not None:
        progress("trace-route", 85)

    # Retry once with doubled candidate cap if the model was infeasible
    # OR all solves were UNKNOWN (timed out without finding). Common
    # cause: cheap-score filtering left too few non-overlapping candidate
    # pairs for the model to find a placement. Doubling the cap brings in
    # geometric-diverse candidates that restore feasibility without
    # changing the objective.
    if (
        not collected
        and last_status in (cp_model.INFEASIBLE, cp_model.UNKNOWN)
        and candidate_limit < 500
    ):
        retry_limit = min(500, candidate_limit * 2)
        if progress is not None:
            progress("place", 22)
        candidates, hole_to_candidates, _ = build_candidate_poses(
            board=board,
            footprints=footprints,
            components=[c for c in components if c.ref not in locked_refs],
            locked_placements=locked_placements,
            candidate_limit=retry_limit,
        )
        model, sel_vars = build_cpsat_model(
            candidates=candidates,
            hole_to_candidates=hole_to_candidates,
            locked_occupied={hid for p in locked_placements for hid in p.occupied_hole_ids},
        )
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
        for k in range(solution_count):
            if cancel is not None and cancel():
                raise SolverCancelled("cpsat placement cancelled during retry")
            this_solve_ms = first_solve_ms if k == 0 else per_solve_ms
            _apply_solve_budget(this_solve_ms)
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
            if progress is not None:
                progress("place", 25 + int(60 * (k + 1) / solution_count))
            if k < solution_count - 1:
                _add_no_good_constraint(
                    model,
                    sel_vars=sel_vars,
                    previous_assignment=previous_assignment,
                    min_changes=max(1, len(previous_assignment) // 2),
                )

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
        # Solver produced no usable candidate — fall back to the greedy
        # placer so the user always gets a routable layout. CP-SAT stays
        # available via the explicit ``placement_engine="cpsat"`` option
        # but defaults to a graceful fallback rather than empty placements.
        greedy_result = place_greedy(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            options=options,
            initial_layout=initial_layout,
        )
        if greedy_result.unplaced:
            # Greedy also failed: return empty placements + all movable
            # as unplaced so the pipeline can still complete with
            # diagnostics.
            trace = SolverTrace(
                seed=options.solver_seed,
                placement_order=[],
                pose_choices=[],
                rejections=[
                    TraceRejection(
                        component_ref=ref,
                        reason="no_cpsat_or_greedy_solution",
                        detail=f"cp_model status: {solver.StatusName(last_status)}",
                    )
                    for ref in greedy_result.unplaced
                ],
                failed_nets=[],
                ripups=[],
                iteration_scores=[],
                phase_timings_ms={
                    "place": round((time.perf_counter() - t_start) * 1000.0, 3),
                    "cpsat_preset_used": 1 if preset_used else 0,
                    "cpsat_fallback_greedy": 1,
                },
            )
            if progress is not None:
                progress("done", 100)
            return PlacementResult(
                placements=list(locked_placements),
                unplaced=greedy_result.unplaced,
                trace=trace,
                cost=0.0,
            )
        # Greedy produced placements: return them and tag the trace so the
        # caller can see the fallback path.
        greedy_trace = greedy_result.trace
        if greedy_trace.phase_timings_ms is None:
            greedy_trace.phase_timings_ms = {}
        greedy_trace.phase_timings_ms["cpsat_fallback_greedy"] = 1
        greedy_trace.phase_timings_ms["cpsat_preset_used"] = 1 if preset_used else 0
        if progress is not None:
            progress("done", 100)
        return greedy_result

    # Always also route greedy so the routing-aware ranking has a known-good
    # baseline. If greedy routes better than any CP-SAT candidate, the
    # ranking picks greedy automatically — that prevents the regression
    # where a CP-SAT candidate with broken routing was returned even
    # though greedy produced a fully-routable layout.
    greedy_placement = place_greedy(
        board=board,
        footprints=footprints,
        components=components,
        nets=nets,
        options=options,
        initial_layout=initial_layout,
    )
    if not greedy_placement.unplaced:
        greedy_breakdown = PlacementObjectiveBreakdown(
            total=int(round(greedy_placement.cost * _MILLIMETRE_SCALE))
        )
        greedy_outcome = _evaluate_candidate(
            board=board,
            footprints=footprints,
            components=components,
            nets=nets,
            candidate=greedy_placement.placements,
            cancel=cancel,
            progress=progress,
            proxy_breakdown=greedy_breakdown,
            placement_engine_ms=round((time.perf_counter() - t_start) * 1000.0, 3),
            candidate_index=len(outcomes),
        )
        if greedy_outcome is not None:
            outcomes.append(greedy_outcome)

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
    # Solve status — the brief distinguishes:
    #   * ``invalid-netlist`` — at least one NET_SINGLE_PIN net (or
    #     validation reported a hard error). Solver cannot claim a
    #     fully-solved status while this is the case.
    #   * ``placement-feasible-routing-incomplete`` — placement feasible
    #     but at least one required net did not route.
    #   * ``fully-routed-valid`` — all nets routed, zero validation
    #     errors, zero single-pin warnings.
    if best.validation_error_count > 0:
        solve_status = "invalid-netlist"
    elif best.single_pin_net_count > 0:
        solve_status = "invalid-netlist"
    elif len(best.unrouted_nets) > 0:
        solve_status = "placement-feasible-routing-incomplete"
    else:
        solve_status = "fully-routed-valid"

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
        "cpsat_solve_status": _SOLVE_STATUS_CODES.get(solve_status, 2),
        "cpsat_x_span": best.x_span,
        "cpsat_y_span": best.y_span,
        "cpsat_min_span": best.min_span,
        "cpsat_max_components_per_row": best.max_components_per_row,
        "cpsat_dip_escape_violations": best.dip_escape_violations,
        "cpsat_single_pin_net_count": best.single_pin_net_count,
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


# --------------------------------------------------------------------------
# Solve status encoding
# --------------------------------------------------------------------------

# Stable numeric encoding so the trace key can carry a numeric value while
# the API surface still reads ``"fully-routed-valid"`` etc. The numbers are
# arbitrary but stable; readers should consult the
# :func:`solve_status_from_code` helper to decode.
_SOLVE_STATUS_CODES: Mapping[str, int] = {
    "invalid-netlist": 0,
    "placement-feasible-routing-incomplete": 1,
    "fully-routed-valid": 2,
}


def solve_status_from_code(code: int) -> str:
    """Decode the numeric ``cpsat_solve_status`` trace key back to a string."""
    for name, value in _SOLVE_STATUS_CODES.items():
        if value == code:
            return name
    return "unknown"