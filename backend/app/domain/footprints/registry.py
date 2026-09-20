"""Builtin breadboard footprint registry.

Footprints describe the lattice-step geometry of a component relative to its anchor hole
(the hole pin `'1'` is placed on). Pin offsets and body cells are integer lattice steps
(`RelativeHole`), never millimetres. Every footprint here is implicitly restricted to the
main lattice; rails are jumper endpoints only and never placement targets.

Flexible footprints (axial resistors, radial caps, electrolytic caps, LEDs) carry a
`FlexibleLeadSpan`. The registry stores their canonical `pin_offsets`/`body_cells` at the
**preferred** span so the entry is self-contained; the pose generator (a later wave)
regenerates offsets for any chosen span.
"""

from __future__ import annotations

from app.domain.errors import InvalidInput
from app.domain.models import (
    BreadboardFootprint,
    FlexibleLeadSpan,
    FootprintGeometry,
    PlacementRuleMainArea,
    PlacementRuleMinClearance,
    PlacementRuleStraddleCenterGap,
    RelativeHole,
)

__all__ = ["FOOTPRINTS", "get_footprint"]


def _rh(x: int, y: int) -> RelativeHole:
    return RelativeHole(x=x, y=y)


# --------------------------------------------------------------------------
# DIP packages: 8 / 14 / 16 / 20 / 28 pins, straddle the center gap.
# --------------------------------------------------------------------------

_SUPPORTED_DIP_PIN_COUNTS: tuple[int, ...] = (8, 14, 16, 20, 28)


def _make_dip(pin_count: int) -> BreadboardFootprint:
    half = pin_count // 2
    pin_offsets: dict[str, RelativeHole] = {}
    for k in range(half):
        pin_offsets[str(k + 1)] = _rh(k, 0)
    for k in range(half):
        pin_offsets[str(half + 1 + k)] = _rh(half - 1 - k, 1)
    body_cells = [_rh(dx, dy) for dx in range(half) for dy in range(2)]
    return BreadboardFootprint(
        id=f"DIP-{pin_count}",
        display_name=f"DIP-{pin_count} (through-hole)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 180],
        placement_rules=[
            PlacementRuleStraddleCenterGap(type="must-straddle-center-gap"),
            PlacementRuleMainArea(type="must-be-on-main-area"),
        ],
        geometry=FootprintGeometry(
            pins_per_side=half,
            nominal_body_width_mm=7.62,
        ),
    )


# --------------------------------------------------------------------------
# Two-pin flexible footprints.
# --------------------------------------------------------------------------

_AXIAL_FLEXIBLE_SPAN = FlexibleLeadSpan(
    min_holes=2,
    max_holes=8,
    preferred_holes=3,
    orientations=["horizontal", "vertical"],
)

_RADIAL_FLEXIBLE_SPAN = FlexibleLeadSpan(
    min_holes=1,
    max_holes=3,
    preferred_holes=2,
    orientations=["horizontal", "vertical"],
)


def _make_axial_resistor() -> BreadboardFootprint:
    preferred = _AXIAL_FLEXIBLE_SPAN.preferred_holes
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(preferred, 0),
    }
    body_cells = [_rh(dx, 0) for dx in range(preferred + 1)]
    return BreadboardFootprint(
        id="AXIAL-R",
        display_name="Axial resistor (2-pin, flexible span)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(flexible_lead_span=_AXIAL_FLEXIBLE_SPAN),
    )


def _make_axial_diode() -> BreadboardFootprint:
    preferred = _AXIAL_FLEXIBLE_SPAN.preferred_holes
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(preferred, 0),
    }
    body_cells = [_rh(dx, 0) for dx in range(preferred + 1)]
    return BreadboardFootprint(
        id="AXIAL-DIODE",
        display_name="Axial diode (cathode marked)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(flexible_lead_span=_AXIAL_FLEXIBLE_SPAN),
        polarity={"2": "cathode"},
    )


def _make_radial_cap() -> BreadboardFootprint:
    preferred = _RADIAL_FLEXIBLE_SPAN.preferred_holes
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(preferred, 0),
    }
    body_cells = [_rh(0, 0), _rh(1, 0), _rh(2, 0)]
    return BreadboardFootprint(
        id="RADIAL-CAP-2P",
        display_name="Radial capacitor (2-pin, flexible span)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(flexible_lead_span=_RADIAL_FLEXIBLE_SPAN),
    )


def _make_electrolytic_cap() -> BreadboardFootprint:
    preferred = _RADIAL_FLEXIBLE_SPAN.preferred_holes
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(preferred, 0),
    }
    body_cells = [_rh(dx, dy) for dx in range(preferred + 1) for dy in range(2)]
    return BreadboardFootprint(
        id="ELECTROLYTIC-CAP-2P",
        display_name="Electrolytic capacitor (polarised)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(flexible_lead_span=_RADIAL_FLEXIBLE_SPAN),
        polarity={"1": "anode", "2": "cathode"},
    )


def _make_led() -> BreadboardFootprint:
    preferred = _RADIAL_FLEXIBLE_SPAN.preferred_holes
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(preferred, 0),
    }
    body_cells = [_rh(dx, dy) for dx in range(preferred + 1) for dy in range(2)]
    return BreadboardFootprint(
        id="LED-2P",
        display_name="LED (polarised)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(flexible_lead_span=_RADIAL_FLEXIBLE_SPAN),
        polarity={"1": "anode", "2": "cathode"},
    )


# --------------------------------------------------------------------------
# TO-92 transistor: 3 inline pins, body approximated as 3 holes.
# --------------------------------------------------------------------------


def _make_to92() -> BreadboardFootprint:
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(1, 0),
        "3": _rh(2, 0),
    }
    return BreadboardFootprint(
        id="TO-92",
        display_name="TO-92 transistor (3 inline pins, approximate)",
        pin_offsets=pin_offsets,
        body_cells=[_rh(0, 0), _rh(1, 0), _rh(2, 0)],
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(pins_per_side=3),
    )


# --------------------------------------------------------------------------
# TACT switch: 4 pins straddling the center gap, two internal pairs.
# --------------------------------------------------------------------------


def _make_tact_switch() -> BreadboardFootprint:
    pin_offsets = {
        "1": _rh(0, 0),
        "2": _rh(2, 0),
        "3": _rh(0, 1),
        "4": _rh(2, 1),
    }
    body_cells = [_rh(dx, dy) for dx in range(3) for dy in range(2)]
    return BreadboardFootprint(
        id="TACT-SW-4P",
        display_name="Tactile switch (4-pin, internal pairs)",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 180],
        placement_rules=[PlacementRuleStraddleCenterGap(type="must-straddle-center-gap")],
        geometry=FootprintGeometry(pins_per_side=2),
        internal_connections=[["1", "2"], ["3", "4"]],
    )


# --------------------------------------------------------------------------
# Pin headers and connectors.
# --------------------------------------------------------------------------


def _make_header(pin_count: int) -> BreadboardFootprint:
    pin_offsets = {str(k + 1): _rh(k, 0) for k in range(pin_count)}
    body_cells = [_rh(k, 0) for k in range(pin_count)]
    return BreadboardFootprint(
        id=f"HEADER-1x{pin_count}",
        display_name=f"{pin_count}-pin single-row header",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(pins_per_side=pin_count),
    )


def _make_connector(pin_count: int) -> BreadboardFootprint:
    pin_offsets = {str(k + 1): _rh(k, 0) for k in range(pin_count)}
    body_cells = [_rh(k, 0) for k in range(pin_count)]
    return BreadboardFootprint(
        id=f"CONN-1x{pin_count}",
        display_name=f"{pin_count}-pin single-row connector",
        pin_offsets=pin_offsets,
        body_cells=body_cells,
        supported_orientations=[0, 90, 180, 270],
        placement_rules=[
            PlacementRuleMainArea(type="must-be-on-main-area"),
            PlacementRuleMinClearance(type="min-clearance-holes", value=1),
        ],
        geometry=FootprintGeometry(pins_per_side=pin_count),
    )


FOOTPRINTS: dict[str, BreadboardFootprint] = {
    **{f"DIP-{n}": _make_dip(n) for n in _SUPPORTED_DIP_PIN_COUNTS},
    "AXIAL-R": _make_axial_resistor(),
    "AXIAL-DIODE": _make_axial_diode(),
    "RADIAL-CAP-2P": _make_radial_cap(),
    "ELECTROLYTIC-CAP-2P": _make_electrolytic_cap(),
    "LED-2P": _make_led(),
    "TO-92": _make_to92(),
    "TACT-SW-4P": _make_tact_switch(),
    **{f"HEADER-1x{n}": _make_header(n) for n in range(2, 11)},
    **{f"CONN-1x{n}": _make_connector(n) for n in range(2, 5)},
}


def get_footprint(footprint_id: str) -> BreadboardFootprint:
    """Return the registered `BreadboardFootprint` for `footprint_id`.

    Raises `InvalidInput` when the id is unknown.
    """
    if footprint_id not in FOOTPRINTS:
        raise InvalidInput(f"Unknown footprint {footprint_id!r}")
    return FOOTPRINTS[footprint_id]
