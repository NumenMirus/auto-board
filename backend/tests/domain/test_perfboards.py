"""Tests for `app.domain.boards.perfboard` and `app.domain.perfboards.registry`.

Validates the perfboard generator (uniform hole grid, layer count, no electrical groups)
and the perfboard footprint registry (24 footprints, no center-gap rules, internal
connections preserved on TACT-SW-4P).
"""

from __future__ import annotations

import pytest

from app.domain.boards.perfboard import build_perfboard
from app.domain.boards.registry import BUILTIN_BOARDS, get_board_model, is_perfboard_id
from app.domain.errors import InvalidInput
from app.domain.models import PerfboardModel
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS, get_perfboard_footprint


pytest_plugins: list[str] = []


def test_build_perfboard_default_double_layered_20x30() -> None:
    board = build_perfboard(rows=20, cols=30, layers=2)
    assert isinstance(board, PerfboardModel)
    assert len(board.holes) == 600
    assert board.rows == 20
    assert board.cols == 30
    assert board.layers == 2
    assert board.pitch_mm == 2.54
    # 20 rows × 30 cols = 600 — every id is unique and deterministic
    ids = [h.id for h in board.holes]
    assert len(set(ids)) == 600
    assert ids[0] == "1-1" and ids[-1] == "20-30"
    # Hole geometry: row r col c → x = (c-1)*2.54, y = (r-1)*2.54
    h = board.holes[0]
    assert h.point.x == pytest.approx(0.0)
    assert h.point.y == pytest.approx(0.0)
    assert h.grid.col == 1 and h.grid.row == "1"
    last = board.holes[-1]
    assert last.point.x == pytest.approx((30 - 1) * 2.54)
    assert last.point.y == pytest.approx((20 - 1) * 2.54)


def test_perfboard_has_no_electrical_groups_and_one_zone() -> None:
    board = build_perfboard(rows=10, cols=15, layers=1)
    # Perfboards are uniform isolated-hole grids; the schema doesn't even
    # carry an electrical_groups field on PerfboardModel.
    assert not hasattr(board, "electrical_groups")
    # One 'main' zone covering the whole board
    assert len(board.zones) == 1
    assert board.zones[0].kind == "main"
    assert len(board.zones[0].polygon) == 4


def test_perfboard_single_and_double_layer_ids() -> None:
    single = build_perfboard(rows=5, cols=5, layers=1)
    double = build_perfboard(rows=5, cols=5, layers=2)
    assert single.layers == 1
    assert double.layers == 2
    assert single.id != double.id


def test_perfboard_rejects_invalid_dims() -> None:
    with pytest.raises(ValueError):
        build_perfboard(rows=0, cols=10, layers=1)
    with pytest.raises(ValueError):
        build_perfboard(rows=10, cols=0, layers=1)
    with pytest.raises(ValueError):
        build_perfboard(rows=10, cols=10, layers=3)


def test_builtin_registry_has_all_three_perfboard_entries() -> None:
    for bid in ("strip-20x30-single", "strip-20x30-double", "strip-15x20-double"):
        model = get_board_model(bid)
        assert isinstance(model, PerfboardModel), bid
        assert is_perfboard_id(bid)


def test_builtin_registry_keeps_breadboard_entries() -> None:
    board = get_board_model("half-400-standard-split-rails")
    assert len(board.holes) == 400
    assert not is_perfboard_id("half-400-standard-split-rails")


def test_builtin_registry_unknown_id_raises() -> None:
    with pytest.raises(InvalidInput):
        get_board_model("nope-board")


def test_perfboard_footprint_registry_has_24_entries() -> None:
    assert len(PERFBOARD_FOOTPRINTS) == 24
    # Spot-check expected footprint ids
    for fid in ("DIP-8", "DIP-14", "DIP-16", "DIP-20", "DIP-28",
                "AXIAL-R", "AXIAL-DIODE", "RADIAL-CAP-2P",
                "ELECTROLYTIC-CAP-2P", "LED-2P", "TO-92", "TACT-SW-4P",
                "HEADER-1x2", "HEADER-1x10", "CONN-1x2", "CONN-1x4"):
        assert fid in PERFBOARD_FOOTPRINTS, fid


def test_dip_pins_in_two_rows_with_known_count() -> None:
    for n in (8, 14, 16, 20, 28):
        f = get_perfboard_footprint(f"DIP-{n}")
        assert len(f.pin_offsets) == n
        # Pins 1..half on row 0, pins half+1..n on row 1
        half = n // 2
        for k in range(half):
            assert f.pin_offsets[str(k + 1)].y == 0
            assert f.pin_offsets[str(k + 1)].x == k
        for k in range(half):
            assert f.pin_offsets[str(half + 1 + k)].y == 1
            assert f.pin_offsets[str(half + 1 + k)].x == half - 1 - k


def test_perfboard_footprints_have_no_center_gap_rule() -> None:
    """Perfboard DIPs and tact switches must NOT require a center gap — that
    rule belongs only to breadboard placement. Here every rule is either
    ``must-be-on-main-area`` or ``min-clearance-holes``.
    """
    for fid, f in PERFBOARD_FOOTPRINTS.items():
        for rule in f.placement_rules:
            assert rule.type != "must-straddle-center-gap", f"{fid} has a center-gap rule"


def test_tact_switch_internal_connections_preserved() -> None:
    f = get_perfboard_footprint("TACT-SW-4P")
    assert sorted([sorted(pair) for pair in f.internal_connections]) == [["1", "2"], ["3", "4"]]


def test_connector_keeps_clearance_rule() -> None:
    f = get_perfboard_footprint("CONN-1x3")
    rule_types = {r.type for r in f.placement_rules}
    assert "min-clearance-holes" in rule_types
    # And the value is 1
    for r in f.placement_rules:
        if r.type == "min-clearance-holes":
            assert r.value == 1


def test_led_and_electrolytic_polarity_preserved() -> None:
    led = get_perfboard_footprint("LED-2P")
    assert led.polarity == {"1": "anode", "2": "cathode"}
    cap = get_perfboard_footprint("ELECTROLYTIC-CAP-2P")
    assert cap.polarity == {"1": "anode", "2": "cathode"}


def test_axial_diode_cathode_marker() -> None:
    f = get_perfboard_footprint("AXIAL-DIODE")
    assert f.polarity == {"2": "cathode"}


def test_unknown_perfboard_footprint_raises() -> None:
    with pytest.raises(InvalidInput):
        get_perfboard_footprint("DOES-NOT-EXIST")


def test_builtin_boards_dict_includes_all_families() -> None:
    """The single registry exposes breadboard + perfboard entries."""
    ids = set(BUILTIN_BOARDS.keys())
    assert "half-400-standard-split-rails" in ids
    assert "half-400-standard-continuous-rails" in ids
    assert "strip-20x30-single" in ids
    assert "strip-20x30-double" in ids
    assert "strip-15x20-double" in ids
