"""Tests for `app.domain.footprints`.

Validates the builtin footprint registry: pin offsets, body cells, geometry constraints,
rotation lattice consistency, and registry lookup behaviour.
"""

from __future__ import annotations

from app.domain.errors import InvalidInput
from app.domain.footprints import FOOTPRINTS, get_footprint
from app.domain.models import RelativeHole

pytest_plugins: list[str] = []


def _rotate_relative(offsets: set[tuple[int, int]], angle_deg: int) -> set[tuple[int, int]]:
    """Rotate a set of lattice offsets by `angle_deg` around the origin (pin '1').

    Only `0`, `90`, `180`, `270` are supported. The anchor is always at `(0, 0)`, so no
    translation is needed before/after rotation.
    """
    if angle_deg == 0:
        return set(offsets)
    if angle_deg == 90:
        return {(y, -x) for x, y in offsets}
    if angle_deg == 180:
        return {(-x, -y) for x, y in offsets}
    if angle_deg == 270:
        return {(-y, x) for x, y in offsets}
    raise ValueError(f"Unsupported rotation: {angle_deg}")


def _normalize(offsets: set[tuple[int, int]]) -> frozenset[tuple[int, int]]:
    """Translate the offsets so their minimum x and y are at the origin.

    Footprints anchor on pin `'1'` which sits at `(0, 0)`; this normalises arbitrary
    translated offset sets for set-equality checks.
    """
    if not offsets:
        return frozenset()
    min_x = min(x for x, _ in offsets)
    min_y = min(y for _, y in offsets)
    return frozenset((x - min_x, y - min_y) for x, y in offsets)


def test_registry_has_expected_footprints() -> None:
    expected = {
        "DIP-8",
        "DIP-14",
        "DIP-16",
        "DIP-20",
        "DIP-28",
        "AXIAL-R",
        "AXIAL-DIODE",
        "RADIAL-CAP-2P",
        "ELECTROLYTIC-CAP-2P",
        "LED-2P",
        "TO-92",
        "TACT-SW-4P",
    }
    expected |= {f"HEADER-1x{n}" for n in range(2, 11)}
    expected |= {f"CONN-1x{n}" for n in range(2, 5)}
    assert expected.issubset(FOOTPRINTS.keys())


def test_get_footprint_unknown_id_raises() -> None:
    import pytest

    with pytest.raises(InvalidInput):
        get_footprint("does-not-exist")


def test_dip_pin_counts() -> None:
    for pin_count in (8, 14, 16, 20, 28):
        fp = get_footprint(f"DIP-{pin_count}")
        assert len(fp.pin_offsets) == pin_count
        half = pin_count // 2
        assert fp.geometry.pins_per_side == half
        # Orientations restricted to horizontal/vertical (DIPs straddle the gap).
        assert fp.supported_orientations == [0, 180]


def test_dip_pin_1_and_pin_n_are_one_row_apart() -> None:
    fp = get_footprint("DIP-14")
    p1 = fp.pin_offsets["1"]
    p14 = fp.pin_offsets["14"]
    # Pin 1 sits at (0, 0) on the top row; pin 14 sits "directly across" at (0, 1)
    # on the bottom row of the DIP — same column, one lattice step below.
    assert p1.y == 0
    assert p14.y == 1
    assert p1.x == p14.x == 0
    assert abs(p1.y - p14.y) == 1


def test_dip_pin_pairs_are_symmetric() -> None:
    fp = get_footprint("DIP-14")
    half = 7
    # Pins 1..7 sit on row 0; pins 8..14 sit on row 1 in reverse x order.
    for k in range(half):
        upper = fp.pin_offsets[str(k + 1)]
        lower = fp.pin_offsets[str(half + 1 + k)]
        assert upper.y == 0
        assert lower.y == 1
        assert upper.x == k
        assert lower.x == half - 1 - k


def test_dip_rules_straddle_and_main_area() -> None:
    fp = get_footprint("DIP-14")
    rule_types = {rule.type for rule in fp.placement_rules}
    assert "must-straddle-center-gap" in rule_types
    assert "must-be-on-main-area" in rule_types


def test_axial_resistor_pins_and_flexible_span() -> None:
    fp = get_footprint("AXIAL-R")
    assert fp.pin_offsets["1"] == RelativeHole(x=0, y=0)
    span = fp.geometry.flexible_lead_span
    assert span is not None
    assert span.preferred_holes == 3
    # Pin 2 is stored at the preferred span: x = 3.
    assert fp.pin_offsets["2"] == RelativeHole(x=3, y=0)
    assert fp.supported_orientations == [0, 90, 180, 270]
    assert fp.polarity == {}


def test_axial_diode_polarity() -> None:
    fp = get_footprint("AXIAL-DIODE")
    assert fp.polarity == {"2": "cathode"}
    assert fp.geometry.flexible_lead_span is not None


def test_radial_cap_and_led_share_span() -> None:
    radial = get_footprint("RADIAL-CAP-2P")
    led = get_footprint("LED-2P")
    elco = get_footprint("ELECTROLYTIC-CAP-2P")
    assert radial.geometry.flexible_lead_span is not None
    assert led.geometry.flexible_lead_span is not None
    assert elco.geometry.flexible_lead_span is not None
    # Same span spec (min/max/preferred) across radial-style parts.
    assert radial.geometry.flexible_lead_span.model_dump() == led.geometry.flexible_lead_span.model_dump()
    assert led.polarity == {"1": "anode", "2": "cathode"}
    assert elco.polarity == {"1": "anode", "2": "cathode"}


def test_to_92_three_inline_pins() -> None:
    fp = get_footprint("TO-92")
    assert set(fp.pin_offsets.keys()) == {"1", "2", "3"}
    assert fp.pin_offsets["1"] == RelativeHole(x=0, y=0)
    assert fp.pin_offsets["2"] == RelativeHole(x=1, y=0)
    assert fp.pin_offsets["3"] == RelativeHole(x=2, y=0)
    assert fp.supported_orientations == [0, 90, 180, 270]


def test_tact_switch_internal_pairs() -> None:
    fp = get_footprint("TACT-SW-4P")
    assert set(fp.pin_offsets.keys()) == {"1", "2", "3", "4"}
    assert fp.pin_offsets["1"] == RelativeHole(x=0, y=0)
    assert fp.pin_offsets["2"] == RelativeHole(x=2, y=0)
    assert fp.pin_offsets["3"] == RelativeHole(x=0, y=1)
    assert fp.pin_offsets["4"] == RelativeHole(x=2, y=1)
    assert fp.internal_connections == [["1", "2"], ["3", "4"]]
    assert fp.supported_orientations == [0, 180]
    rule_types = {rule.type for rule in fp.placement_rules}
    assert "must-straddle-center-gap" in rule_types


def test_header_pin_count_and_offsets() -> None:
    for n in range(2, 11):
        fp = get_footprint(f"HEADER-1x{n}")
        assert len(fp.pin_offsets) == n
        for k in range(n):
            assert fp.pin_offsets[str(k + 1)] == RelativeHole(x=k, y=0)


def test_connector_extra_min_clearance_rule() -> None:
    fp = get_footprint("CONN-1x3")
    rule_types = {rule.type for rule in fp.placement_rules}
    assert "min-clearance-holes" in rule_types
    for rule in fp.placement_rules:
        if rule.type == "min-clearance-holes":
            assert rule.value == 1


def test_header_has_no_min_clearance_rule() -> None:
    fp = get_footprint("HEADER-1x3")
    rule_types = {rule.type for rule in fp.placement_rules}
    assert "min-clearance-holes" not in rule_types


def test_pin_offsets_inside_body_cells_bounding_box() -> None:
    """Every footprint's pin offsets must lie within the bounding box of its body cells.

    For axial/radial footprints the body extends one row in y; for DIP it extends 2 rows;
    for TO-92 it is a single row of 3 cells. The bounding-box check is footprint-agnostic.
    """
    for fid, fp in FOOTPRINTS.items():
        if not fp.body_cells:
            continue
        bx_min = min(c.x for c in fp.body_cells)
        bx_max = max(c.x for c in fp.body_cells)
        by_min = min(c.y for c in fp.body_cells)
        by_max = max(c.y for c in fp.body_cells)
        for pin, off in fp.pin_offsets.items():
            assert bx_min <= off.x <= bx_max, f"{fid}: pin {pin} x={off.x} outside body x range"
            assert by_min <= off.y <= by_max, f"{fid}: pin {pin} y={off.y} outside body y range"


def test_offset_set_rotates_consistently() -> None:
    """90° + 270° rotation of pin offsets (anchored at origin) returns to the original set.

    This validates that the offsets live on a consistent orthogonal lattice; it does NOT
    validate that the registry performs rotation (the pose generator in a later wave does).
    """
    for fid, fp in FOOTPRINTS.items():
        if not fp.pin_offsets:
            continue
        offsets = {(off.x, off.y) for off in fp.pin_offsets.values()}
        rotated_90 = _rotate_relative(offsets, 90)
        rotated_270 = _rotate_relative(rotated_90, 270)
        assert _normalize(offsets) == _normalize(rotated_270), (
            f"{fid}: 90°+270° rotation drifted; original={sorted(offsets)}, after={sorted(rotated_270)}"
        )


def test_offset_set_full_orbit_returns_to_origin() -> None:
    for fid, fp in FOOTPRINTS.items():
        if not fp.pin_offsets:
            continue
        offsets = {(off.x, off.y) for off in fp.pin_offsets.values()}
        # After four 90° rotations we should be back where we started (anchored at origin).
        rotated = offsets
        for _ in range(4):
            rotated = _rotate_relative(rotated, 90)
        assert _normalize(offsets) == _normalize(rotated), (
            f"{fid}: 360° rotation drifted; original={sorted(offsets)}, after={sorted(rotated)}"
        )


def test_get_footprint_returns_same_instance() -> None:
    a = get_footprint("DIP-14")
    b = get_footprint("DIP-14")
    assert a is b
