"""Assembly instruction builder (main spec §9.4).

The output is a deterministic list of `InstructionStep`s ordered rigid → passives →
short jumpers → long jumpers → power/ground jumpers → mandatory verify step. Power
and ground jumpers are pulled out of the short/long buckets regardless of length so
the final assembly action is always the same: hook up the rails last.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Jumper,
    Layout,
    Net,
)

__all__ = [
    "COLOR_NAMES",
    "AssemblyInstructions",
    "InstructionStep",
    "build_instructions",
]


# --------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstructionStep:
    """One ordered step of the assembly guide.

    ``order`` is the 0-based position in the assembly sequence (matches the index of the
    step in :attr:`AssemblyInstructions.steps`). ``kind`` is one of
    ``'place-rigid' | 'place-passive' | 'add-jumper-short' | 'add-jumper-long' |
    'connect-power' | 'verify'``.
    """

    order: int
    kind: str
    description: str
    jumper_line: str | None = None


@dataclass(frozen=True, slots=True)
class AssemblyInstructions:
    """The full ordered assembly guide."""

    steps: tuple[InstructionStep, ...]


# --------------------------------------------------------------------------
# Italian colour names — covers every colour the router can produce plus the two
# power/ground specials. Case-insensitive hex match (lower-case keys). Fallback
# for any unmapped colour is ``'colore sconosciuto'``.
# --------------------------------------------------------------------------


# Ground/power specials + every entry of the router's PALETTE (see app/domain/route.py).
COLOR_NAMES: dict[str, str] = {
    "#1a1a1a": "nero",
    "#d92b2b": "rosso",
    "#1f77b4": "blu",
    "#ff7f0e": "arancione",
    "#2ca02c": "verde",
    "#9467bd": "viola",
    "#8c564b": "marrone",
    "#e377c2": "rosa",
    "#17becf": "ciano",
    "#bcbd22": "giallo-verde",
    "#7f7f7f": "grigio",
    "#3b7dd8": "azzurro",
    "#c44e52": "rosso scuro",
    "#55a868": "verde scuro",
}

_UNKNOWN_COLOUR: str = "colore sconosciuto"


# --------------------------------------------------------------------------
# Footprint classification — defines which components count as "rigid" (must be
# placed first) and which as "passive" (placed second).
# --------------------------------------------------------------------------


_RIGID_FOOTPRINT_PREFIXES: tuple[str, ...] = ("DIP-",)
_RIGID_FOOTPRINT_EXACT: frozenset[str] = frozenset(
    {"TACT-SW-4P"} | {f"HEADER-1x{n}" for n in range(2, 11)} | {f"CONN-1x{n}" for n in range(2, 5)}
)
_PASSIVE_FOOTPRINT_IDS: frozenset[str] = frozenset(
    {"AXIAL-R", "AXIAL-DIODE", "RADIAL-CAP-2P", "ELECTROLYTIC-CAP-2P", "LED-2P", "TO-92"}
)

# Short/long jumper threshold (mm). Anything shorter than this counts as a "short
# jumper" in the assembly sequence; the rest are "long jumpers". Picked empirically
# to match main spec §9.4's "short jumpers first, long jumpers after" guidance for
# half-size breadboards.
_SHORT_JUMPER_THRESHOLD_MM: float = 30.0


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def build_instructions(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    layout: Layout,
) -> AssemblyInstructions:
    """Build the assembly guide for ``layout``.

    Parameters are accepted for interface parity with :func:`render_svg` and future
    board-aware enrichment (e.g. mentioning specific tie-point groups in the step
    text). Only ``layout``, ``components`` and ``nets`` are used by the current
    implementation; the rest are accepted and ignored.
    """
    _ = (board, index, footprints)

    component_by_ref: dict[str, Component] = {c.ref: c for c in components}
    net_by_id: dict[str, Net] = {n.id: n for n in nets}

    # Classify every placement as rigid or passive.
    rigid_placements: list[ComponentPlacement] = []
    passive_placements: list[ComponentPlacement] = []
    for placement in layout.placements:
        component = component_by_ref.get(placement.component_ref)
        if component is None:
            # Unknown component — fall through to passive bucket so it still appears.
            passive_placements.append(placement)
            continue
        fid = component.footprint_id
        if fid in _RIGID_FOOTPRINT_EXACT or fid.startswith(_RIGID_FOOTPRINT_PREFIXES):
            rigid_placements.append(placement)
        elif fid in _PASSIVE_FOOTPRINT_IDS:
            passive_placements.append(placement)
        else:
            # Treat any unrecognised multi-pin footprint as rigid so it lands before
            # the passives. Single-pin-only footprints cannot exist in the registry
            # so we never produce empty groups here.
            rigid_placements.append(placement)

    rigid_placements.sort(key=lambda p: p.component_ref)
    passive_placements.sort(key=lambda p: p.component_ref)

    # Classify jumpers into short / long / power buckets.
    short_jumpers: list[tuple[int, Jumper]] = []
    long_jumpers: list[tuple[int, Jumper]] = []
    power_jumpers: list[tuple[int, Jumper]] = []
    for idx, jumper in enumerate(layout.jumpers, start=1):
        net = net_by_id.get(jumper.net_id)
        net_class = net.net_class if net is not None else ""
        if net_class in ("power", "ground"):
            power_jumpers.append((idx, jumper))
        elif jumper.estimated_length_mm < _SHORT_JUMPER_THRESHOLD_MM:
            short_jumpers.append((idx, jumper))
        else:
            long_jumpers.append((idx, jumper))
    short_jumpers.sort(key=lambda pair: pair[1].estimated_length_mm)
    long_jumpers.sort(key=lambda pair: pair[1].estimated_length_mm)
    # Power/ground jumpers keep their natural index ordering (they are last regardless).

    steps: list[InstructionStep] = []
    order = 0

    # 1) rigid components, sorted by ref
    for placement in rigid_placements:
        component = component_by_ref.get(placement.component_ref)
        value_suffix = f" ({component.value})" if component is not None and component.value else ""
        steps.append(
            InstructionStep(
                order=order,
                kind="place-rigid",
                description=(
                    f"Posiziona {placement.component_ref}{value_suffix} sul lato principale "
                    "della breadboard (orientamento 0° o 180°)."
                ),
            )
        )
        order += 1

    # 2) passive components, sorted by ref
    for placement in passive_placements:
        component = component_by_ref.get(placement.component_ref)
        value_suffix = f" ({component.value})" if component is not None and component.value else ""
        steps.append(
            InstructionStep(
                order=order,
                kind="place-passive",
                description=(f"Posiziona {placement.component_ref}{value_suffix} verificando la polarità."),
            )
        )
        order += 1

    # 3) short jumpers (sorted by length ascending)
    for idx, jumper in short_jumpers:
        steps.append(
            InstructionStep(
                order=order,
                kind="add-jumper-short",
                description=f"Cablaggio jumper corto {idx}.",
                jumper_line=_format_jumper_line(jumper, idx, net_by_id),
            )
        )
        order += 1

    # 4) long jumpers (sorted by length ascending)
    for idx, jumper in long_jumpers:
        steps.append(
            InstructionStep(
                order=order,
                kind="add-jumper-long",
                description=f"Cablaggio jumper lungo {idx}.",
                jumper_line=_format_jumper_line(jumper, idx, net_by_id),
            )
        )
        order += 1

    # 5) power/ground jumpers LAST regardless of length
    for idx, jumper in power_jumpers:
        steps.append(
            InstructionStep(
                order=order,
                kind="connect-power",
                description=f"Collega alimentazione/massa: jumper {idx}.",
                jumper_line=_format_jumper_line(jumper, idx, net_by_id),
            )
        )
        order += 1

    # 6) mandatory final verify step
    steps.append(
        InstructionStep(
            order=order,
            kind="verify",
            description="Verificare continuità e polarità prima di alimentare il circuito.",
        )
    )

    return AssemblyInstructions(steps=tuple(steps))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _format_jumper_line(jumper: Jumper, index: int, net_by_id: dict[str, Net]) -> str:
    """Format one jumper line exactly per main spec §9.4's example."""
    net = net_by_id.get(jumper.net_id)
    net_name = net.name if net is not None else ""
    colour = _italian_colour(jumper.color)
    length_mm = jumper.estimated_length_mm
    layer = jumper.path.layer
    return (
        f"J{index} — Net: {net_name} — "
        f"da {jumper.start_hole_id} a {jumper.end_hole_id} — "
        f"{colour} — {length_mm:.0f} mm — layer {layer}"
    )


def _italian_colour(hex_color: str | None) -> str:
    """Look up an Italian colour name for ``hex_color`` (case-insensitive)."""
    if hex_color is None:
        return _UNKNOWN_COLOUR
    key = hex_color.lower()
    return COLOR_NAMES.get(key, _UNKNOWN_COLOUR)
