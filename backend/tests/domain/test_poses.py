"""Tests for :mod:`app.domain.poses`.

Verifies the canonical constraints enumerated in the assignment:

- DIP-14 poses all straddle the center gap (every pose has occupied rows on both
  sides of ``index.center_gap_between``).
- AXIAL-R poses cover the full span range and both horizontal/vertical orientations.
- Poses that would fall off the board edge are correctly excluded.
"""

from __future__ import annotations

import pytest

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import get_footprint
from app.domain.index import BoardIndex
from app.domain.poses import Pose, generate_poses

pytest_plugins: list[str] = []


@pytest.fixture
def board_index() -> BoardIndex:
    return BoardIndex.build(build_half400(split_rails=True))


def _pose_occupied_rows(pose: Pose, index: BoardIndex) -> set[int]:
    """Return the set of row indices touched by the pose's body cells."""
    rows: set[int] = set()
    body_set = set(pose.body_cells_idx)
    for (_col, row), hi in index.lattice.items():
        if hi in body_set:
            rows.add(row)
    return rows


def test_dip14_only_straddles_center_gap(board_index: BoardIndex) -> None:
    """Every DIP-14 pose must have occupied rows on both sides of the gap."""
    fp = get_footprint("DIP-14")
    poses = generate_poses(board_index, fp)
    gap_lo, gap_hi = board_index.center_gap_between
    assert poses, "expected DIP-14 to generate at least one pose"
    for pose in poses:
        rows = _pose_occupied_rows(pose, board_index)
        assert min(rows) <= gap_lo, (
            f"DIP-14 pose anchor {board_index.hole_ids[pose.anchor_idx]} "
            f"rows {sorted(rows)} has no row <= gap_lo={gap_lo}"
        )
        assert max(rows) >= gap_hi, (
            f"DIP-14 pose anchor {board_index.hole_ids[pose.anchor_idx]} "
            f"rows {sorted(rows)} has no row >= gap_hi={gap_hi}"
        )


def test_axial_r_full_span_and_orientation_coverage(board_index: BoardIndex) -> None:
    """AXIAL-R must enumerate spans 2..8 and orientations 0/90/180/270."""
    fp = get_footprint("AXIAL-R")
    poses = generate_poses(board_index, fp)
    assert poses
    spans_seen: set[int] = {pose.span for pose in poses if pose.span is not None}
    orientations_seen = {pose.orientation for pose in poses}
    assert spans_seen == set(range(2, 9)), f"expected spans 2..8, got {sorted(spans_seen)}"
    assert orientations_seen == {0, 90, 180, 270}, (
        f"expected orientations 0/90/180/270, got {sorted(orientations_seen)}"
    )


def test_pose_off_board_edge_excluded(board_index: BoardIndex) -> None:
    """An AXIAL-R with anchor at col 30 orientation 0 has no valid pose."""
    fp = get_footprint("AXIAL-R")
    poses = generate_poses(board_index, fp)
    # Find the hole idx for "a30".
    a30_idx = board_index.idx["a30"]
    # orient 0 means pin 2 at (col+span, row); with col=30 and span >= 1 the pin
    # leaves the lattice. Expect NO pose with anchor at a30 and orientation 0.
    off_edge = [p for p in poses if p.anchor_idx == a30_idx and p.orientation == 0]
    assert off_edge == [], f"expected no AXIAL-R pose at a30 orientation 0, got {len(off_edge)}"


def test_pose_occupancy_bitmask_matches_body(board_index: BoardIndex) -> None:
    """The pose's occupied_mask must cover exactly its body cells + pin holes."""
    fp = get_footprint("DIP-14")
    pose = generate_poses(board_index, fp)[0]
    expected = 0
    for hi in pose.body_cells_idx:
        expected |= 1 << hi
    for _, hi in pose.pin_idx:
        expected |= 1 << hi
    assert pose.occupied_mask == expected


def test_dip8_strictly_uses_straddle_orientation_set(board_index: BoardIndex) -> None:
    """DIP-8 only supports orientations 0 and 180, not 90/270."""
    fp = get_footprint("DIP-8")
    poses = generate_poses(board_index, fp)
    orientations = {p.orientation for p in poses}
    assert orientations == {0, 180}


def test_generate_poses_is_deterministic(board_index: BoardIndex) -> None:
    """Two calls with the same inputs return equal pose tuples in the same order."""
    fp = get_footprint("DIP-8")
    a = generate_poses(board_index, fp)
    b = generate_poses(board_index, fp)
    assert a == b


def test_to92_supports_all_four_orientations(board_index: BoardIndex) -> None:
    """TO-92 supports orientations 0/90/180/270 (approximate 3-pin footprint)."""
    fp = get_footprint("TO-92")
    poses = generate_poses(board_index, fp)
    orientations = {p.orientation for p in poses}
    assert orientations == {0, 90, 180, 270}


def test_mech_cost_includes_vertical_bump(board_index: BoardIndex) -> None:
    """Vertical orientations carry a +0.5 mech cost over horizontal at the same anchor/span."""
    fp = get_footprint("AXIAL-R")
    poses = generate_poses(board_index, fp)
    by_anchor: dict[int, list[Pose]] = {}
    for p in poses:
        by_anchor.setdefault(p.anchor_idx, []).append(p)
    sample_anchor = next(iter(by_anchor))
    same = by_anchor[sample_anchor]
    horizontals = [p for p in same if p.orientation in (0, 180)]
    verticals = [p for p in same if p.orientation in (90, 270)]
    assert horizontals and verticals, "expected both orientations at first anchor"
    for h in horizontals:
        for v in verticals:
            if h.span == v.span:
                assert v.mech_cost == pytest.approx(h.mech_cost + 0.5), (
                    "vertical mech_cost should be +0.5 over horizontal at same span"
                )
