"""Tests for `app.domain.boards`.

Validates the half-size 400-tie-point breadboard generator: hole count, electrical group
structure (tie-point split, rail-segment split), zone coverage, and registry behaviour.
"""

from __future__ import annotations

from app.domain.boards import BUILTIN_BOARDS, build_half400, get_board_model
from app.domain.errors import InvalidInput
from app.domain.index import BoardIndex

pytest_plugins: list[str] = []


def _groups_by_id(board) -> dict[str, set[str]]:
    return {group.id: set(group.hole_ids) for group in board.electrical_groups}


def test_split_board_has_400_holes_and_68_groups() -> None:
    board = build_half400(split_rails=True)
    assert len(board.holes) == 400
    assert len(board.electrical_groups) == 68
    # 60 tie-point groups + 8 rail segment groups (4 lines x 2 segments)
    assert sum(1 for g in board.electrical_groups if g.kind == "tie-point") == 60
    assert sum(1 for g in board.electrical_groups if g.kind == "rail") == 8


def test_continuous_board_has_400_holes_and_64_groups() -> None:
    board = build_half400(split_rails=False)
    assert len(board.holes) == 400
    assert len(board.electrical_groups) == 64
    assert sum(1 for g in board.electrical_groups if g.kind == "tie-point") == 60
    assert sum(1 for g in board.electrical_groups if g.kind == "rail") == 4


def test_tie_point_groups_split_at_center_gap_column_17() -> None:
    board = build_half400(split_rails=True)
    groups = _groups_by_id(board)

    assert "tp-l-17" in groups
    assert "tp-r-17" in groups
    assert groups["tp-l-17"] == {f"{row}17" for row in "abcde"}
    assert groups["tp-r-17"] == {f"{row}17" for row in "fghij"}

    # No hole shared between the two halves of any column.
    assert groups["tp-l-17"].isdisjoint(groups["tp-r-17"])

    # The two halves are not transitively connected via any other tie-point group.
    for col in range(1, 31):
        assert groups[f"tp-l-{col}"].isdisjoint(groups[f"tp-r-{col}"])


def test_rail_segments_split_at_hole_15() -> None:
    board = build_half400(split_rails=True)
    groups = _groups_by_id(board)
    for line in ("top-plus", "top-minus", "bottom-minus", "bottom-plus"):
        assert f"rail-{line}-seg-a" in groups
        assert f"rail-{line}-seg-b" in groups
        assert f"rail-{line}-15" in groups[f"rail-{line}-seg-a"]
        assert f"rail-{line}-16" in groups[f"rail-{line}-seg-b"]
        assert groups[f"rail-{line}-seg-a"].isdisjoint(groups[f"rail-{line}-seg-b"])


def test_continuous_rail_groups_contain_all_25_holes_per_line() -> None:
    board = build_half400(split_rails=False)
    groups = _groups_by_id(board)
    for line in ("top-plus", "top-minus", "bottom-minus", "bottom-plus"):
        assert f"rail-{line}-seg-a" in groups
        assert f"rail-{line}-seg-b" not in groups
        assert len(groups[f"rail-{line}-seg-a"]) == 25
        assert {f"rail-{line}-{i}" for i in range(1, 26)} == groups[f"rail-{line}-seg-a"]


def test_metadata_reflects_split_or_continuous() -> None:
    split = build_half400(split_rails=True)
    assert split.metadata.rail_configuration == "split-1-15/16-25"
    assert split.metadata.columns == 30
    assert split.metadata.rows == list("abcdefghij")
    assert split.metadata.rail_lines == ["top-plus", "top-minus", "bottom-minus", "bottom-plus"]

    continuous = build_half400(split_rails=False)
    assert continuous.metadata.rail_configuration == "continuous"


def test_main_zones_cover_main_and_center_gap() -> None:
    board = build_half400(split_rails=True)
    zone_ids = [zone.id for zone in board.zones]
    assert "main" in zone_ids
    assert "center-gap" in zone_ids
    for line in ("top-plus", "top-minus", "bottom-minus", "bottom-plus"):
        assert f"rail-{line}" in zone_ids

    main_zone = next(z for z in board.zones if z.id == "main")
    assert main_zone.kind == "main"
    xs = {p.x for p in main_zone.polygon}
    ys = {p.y for p in main_zone.polygon}
    assert min(xs) == -1.27 and max(xs) == 75.0
    assert min(ys) == -1.27 and max(ys) == 29.21

    gap_zone = next(z for z in board.zones if z.id == "center-gap")
    assert gap_zone.kind == "center-gap"
    gxs = {p.x for p in gap_zone.polygon}
    gys = {p.y for p in gap_zone.polygon}
    assert min(gxs) == -1.27 and max(gxs) == 75.0
    assert min(gys) == 11.43 and max(gys) == 16.51


def test_main_hole_count_and_pitch() -> None:
    board = build_half400(split_rails=True)
    main_holes = [h for h in board.holes if not h.id.startswith("rail-")]
    assert len(main_holes) == 300

    # Row e (index 4) is the last row above the gap; row f (index 5) is the first below.
    e17 = next(h for h in main_holes if h.id == "e17")
    f17 = next(h for h in main_holes if h.id == "f17")
    assert e17.point.y == 4 * 2.54  # 10.16 mm
    assert f17.point.y == 10.16 + 7.62  # 17.78 mm
    assert round(f17.point.y - e17.point.y, 3) == 7.62  # the real DIP channel

    # x for column 1 is 0.0, column 30 is 29 * 2.54 = 73.66
    a1 = next(h for h in main_holes if h.id == "a1")
    a30 = next(h for h in main_holes if h.id == "a30")
    assert a1.point.x == 0.0
    assert round(a30.point.x, 3) == round(29 * 2.54, 3)


def test_rail_hole_x_has_five_hole_cluster_gap() -> None:
    board = build_half400(split_rails=True)
    rail5 = next(h for h in board.holes if h.id == "rail-top-plus-5")
    rail6 = next(h for h in board.holes if h.id == "rail-top-plus-6")
    # The cluster boundary between holes 5 and 6 introduces an extra pitch (2 pitches
    # total between them instead of the standard 1 pitch).
    assert round(rail6.point.x - rail5.point.x, 3) == round(2 * 2.54, 3)
    # Within the same cluster (holes 1 and 2) the spacing is exactly one pitch.
    rail1 = next(h for h in board.holes if h.id == "rail-top-plus-1")
    rail2 = next(h for h in board.holes if h.id == "rail-top-plus-2")
    assert round(rail2.point.x - rail1.point.x, 3) == round(2.54, 3)


def test_rail_y_positions_match_spec() -> None:
    board = build_half400(split_rails=True)
    expected = {
        "top-plus": -12.70,
        "top-minus": -10.16,
        "bottom-minus": 38.10,
        "bottom-plus": 40.64,
    }
    for line, y in expected.items():
        hole = next(h for h in board.holes if h.id == f"rail-{line}-1")
        assert hole.point.y == y


def test_board_index_builds_cleanly_for_split_board() -> None:
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    assert len(index.hole_ids) == 400
    # main lattice covers 30 columns x 5 rows above and 5 rows below the gap
    assert len(index.lattice) == 30 * 10
    assert index.center_gap_between == (4, 5)
    # each rail line has 25 holes
    assert all(len(v) == 25 for v in index.rail_lattice.values())


def test_registry_lazy_loading() -> None:
    boards = BUILTIN_BOARDS
    assert set(boards.keys()) == {
        "half-400-standard-split-rails",
        "half-400-standard-continuous-rails",
    }
    a = get_board_model("half-400-standard-split-rails")
    b = get_board_model("half-400-standard-split-rails")
    # Lazy + cached: identity-equal across calls.
    assert a is b


def test_get_board_model_unknown_id_raises() -> None:
    import pytest

    with pytest.raises(InvalidInput):
        get_board_model("does-not-exist")
