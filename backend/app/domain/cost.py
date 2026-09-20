"""Placement cost function (main spec §6.3).

The cost of placing a component at a candidate pose is a weighted sum of seven terms.
All terms are pure, deterministic, and operate on the inputs supplied by the caller — no
global state, no I/O, no ``random`` calls.

Terms, in evaluation order:

- ``weighted_manhattan`` — distance from each pin to the nearest already-placed same-net
  pin (in mm). This is the primary "keep related components close" signal.
- ``congestion`` — local density of occupied holes around the candidate body.
- ``mechanical`` — driven by the pose's ``mech_cost`` (span deviation + vertical bump).
- ``critical_rule`` — always 0 here; placement rules are hard-rejected during pose
  generation, so this term exists for future extensibility but contributes nothing.
- ``accessibility`` — bump for user-facing parts (LED/CONN/HEADER/TACT) that the
  placer would otherwise shove into the interior.
- ``overlap`` — big penalty if the pose collides with anything already placed.
- ``cluster`` — Manhattan distance from the pose's centroid to the cluster anchor's
  centroid, weighted by the ``cluster`` weight, only when ``cluster_anchor_point`` is
  set.

The signature matches main spec §6.3 exactly plus two optional knobs: a
``component_ref`` (so the function can build ``"ref.pin"`` keys for its lookup tables
without the spec'd dict carrying them) and ``cluster_anchor_point`` (the anchor's
centroid in mm). Both default to safe values.
"""

from __future__ import annotations

from app.domain.index import BoardIndex
from app.domain.models import BreadboardFootprint
from app.domain.poses import Pose

__all__ = ["placement_cost"]


# Footprint id substrings that mark a user-facing part — kept simple, documented.
_ACCESSIBLE_FAMILY_KEYWORDS: tuple[str, ...] = ("LED", "CONN", "HEADER", "TACT")

# Half-size board pitch (mm). Used for the bounding-box padding in the congestion term.
_PITCH_MM: float = 2.54


def _user_facing(footprint: BreadboardFootprint) -> bool:
    fid = footprint.id
    return any(keyword in fid for keyword in _ACCESSIBLE_FAMILY_KEYWORDS)


def _manhattan(a: tuple[float, float], b: tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _nearest_placed_same_net(
    own_ref_pin: str,
    own_point: tuple[float, float],
    net_id: str,
    net_of_pin: dict[tuple[str, str], str],
    placed_pin_points: dict[str, tuple[float, float]],
) -> float:
    """Find the nearest already-placed pin sharing ``net_id`` (mm, Manhattan)."""
    best = float("inf")
    for placed_ref_pin, point in placed_pin_points.items():
        if placed_ref_pin == own_ref_pin:
            continue
        placed_ref, placed_pin = placed_ref_pin.split(".", 1)
        if net_of_pin.get((placed_ref, placed_pin)) != net_id:
            continue
        best = min(best, _manhattan(own_point, point))
    return best


def _weighted_manhattan_term(
    pose: Pose,
    component_ref: str,
    index: BoardIndex,
    net_of_pin: dict[tuple[str, str], str],
    placed_pin_points: dict[str, tuple[float, float]],
) -> float:
    """Sum of nearest-placed-same-net Manhattan distances for every pin of ``pose``."""
    points = index.points
    total = 0.0
    for pin_id, hole_idx in pose.pin_idx:
        ref_pin = f"{component_ref}.{pin_id}"
        net_id = net_of_pin.get((component_ref, pin_id))
        if net_id is None:
            continue
        nearest = _nearest_placed_same_net(ref_pin, points[hole_idx], net_id, net_of_pin, placed_pin_points)
        if nearest != float("inf"):
            total += nearest
    return total


def _congestion_term(
    pose: Pose,
    occupied_mask: int,
    index: BoardIndex,
) -> float:
    """Number of occupied holes in the pose's body bounding box (±2 cols, ±1 row).

    Kept O(board size) but the bounding-box pre-filter makes the constant small. For
    a typical 30x10 board the inner loop iterates the pose's body only.
    """
    if not pose.body_cells_idx:
        return 0.0
    points = index.points
    body_points = [points[i] for i in pose.body_cells_idx]
    min_x = min(p[0] for p in body_points)
    max_x = max(p[0] for p in body_points)
    min_y = min(p[1] for p in body_points)
    max_y = max(p[1] for p in body_points)
    # ±2 columns / ±1 row, in mm (pitch is 2.54).
    pad_x = 2.0 * _PITCH_MM
    pad_y = 1.0 * _PITCH_MM
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


def _accessibility_term(pose: Pose, footprint: BreadboardFootprint, index: BoardIndex) -> float:
    """1.0 if a user-facing part is wedged into the interior (not the edge columns)."""
    if not _user_facing(footprint):
        return 0.0
    if not pose.body_cells_idx:
        return 0.0
    points = index.points
    body_xs = [points[i][0] for i in pose.body_cells_idx]
    min_x = min(body_xs)
    max_x = max(body_xs)
    # 30 columns: cols 1-3 = left 20% edge, cols 28-30 = right 20% edge; x ranges in mm.
    edge_low_max_x = 3 * _PITCH_MM  # last column of the left edge band (col 3 at x=5.08)
    edge_high_min_x = 27 * _PITCH_MM  # first column of the right edge band (col 28 at x=68.58)
    in_left_edge = max_x <= edge_low_max_x
    in_right_edge = min_x >= edge_high_min_x
    return 0.0 if (in_left_edge or in_right_edge) else 1.0


def _pose_centroid(pose: Pose, index: BoardIndex) -> tuple[float, float]:
    if not pose.body_cells_idx:
        return (0.0, 0.0)
    xs = [index.points[i][0] for i in pose.body_cells_idx]
    ys = [index.points[i][1] for i in pose.body_cells_idx]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def placement_cost(
    pose: Pose,
    footprint: BreadboardFootprint,
    index: BoardIndex,
    placed_pin_points: dict[str, tuple[float, float]],
    net_of_pin: dict[tuple[str, str], str],
    occupied_mask: int,
    weights: dict[str, float],
    cluster_anchor_point: tuple[float, float] | None = None,
    component_ref: str = "",
) -> float:
    """Compute the weighted placement cost of ``pose``.

    Parameters mirror main spec §6.3 plus two optional knobs documented above. The
    ``component_ref`` parameter is only needed when ``weights['weightedDistance']`` is
    nonzero (so the cost can build ``"ref.pin"`` keys); the default empty string keeps
    the function callable in tests that exercise other terms.
    """
    # weightedManhattan
    w_dist = weights.get("weightedDistance", 0.0)
    if w_dist:
        weighted_manhattan = w_dist * _weighted_manhattan_term(
            pose, component_ref, index, net_of_pin, placed_pin_points
        )
    else:
        weighted_manhattan = 0.0

    # congestion
    w_cong = weights.get("congestion", 0.0)
    congestion = w_cong * _congestion_term(pose, occupied_mask, index) if w_cong else 0.0

    # mechanical
    w_mech = weights.get("mechanical", 0.0)
    mech = w_mech * pose.mech_cost if w_mech else 0.0

    # criticalRule: always 0 here; placement rules are hard-rejected during pose generation.
    critical_rule = 0.0

    # accessibility
    w_acc = weights.get("accessibility", 0.0)
    accessibility = w_acc * _accessibility_term(pose, footprint, index) if w_acc else 0.0

    # overlap
    w_overlap = weights.get("overlap", 0.0)
    overlap = w_overlap * (1.0 if (occupied_mask & pose.occupied_mask) else 0.0)

    # cluster
    w_cluster = weights.get("cluster", 0.0)
    cluster_pull = 0.0
    if w_cluster and cluster_anchor_point is not None:
        cluster_pull = w_cluster * _manhattan(_pose_centroid(pose, index), cluster_anchor_point)

    return weighted_manhattan + congestion + mech + critical_rule + accessibility + overlap + cluster_pull
