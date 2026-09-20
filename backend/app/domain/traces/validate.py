"""Pure validator for perfboard trace layouts.

Mirrors the breadboard validator's structure but operates on the trace /
placement semantics of a perfboard: no electrical groups, no rails, no
jumpers, every hole is isolated by default. Errors are emitted via the
shared :data:`app.domain.diagnostics.DIAGNOSTIC_CATALOG`.
"""

from __future__ import annotations

from collections import defaultdict

from app.domain.diagnostics import make_diagnostic
from app.domain.models import (
    Component,
    ComponentPlacement,
    Diagnostic,
    Net,
    PerfboardModel,
    ThroughHoleFootprint,
    TraceLayout,
)

__all__ = ["ValidationResult", "validate_layout"]


class ValidationResult:
    """Pure validator output for a perfboard trace layout."""

    __slots__ = ("diagnostics", "score_inputs")

    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []
        self.score_inputs: dict[str, object] = {}


def _validate_input_basics(
    components: list[Component],
    nets: list[Net],
    footprints: dict[str, ThroughHoleFootprint],
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    seen_refs: set[str] = set()
    for c in components:
        if c.ref in seen_refs:
            diags.append(make_diagnostic("DUPLICATE_COMPONENT_REF", ref=c.ref))
        seen_refs.add(c.ref)
        if c.footprint_id not in footprints:
            diags.append(make_diagnostic("UNKNOWN_FOOTPRINT", ref=c.ref, footprint=c.footprint_id))

    pin_to_nets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for net in nets:
        if len(net.pins) < 2:
            diags.append(make_diagnostic("NET_SINGLE_PIN", net=net.id))
        for pin_ref in net.pins:
            pin_to_nets[(pin_ref.component_ref, pin_ref.pin)].append(net.id)
    for (ref, pin_name), net_ids in pin_to_nets.items():
        if len(net_ids) > 1:
            diags.append(
                make_diagnostic("PIN_IN_MULTIPLE_NETS", ref=ref, pin=pin_name, nets=",".join(sorted(net_ids)))
            )
    return diags


def _validate_placements(
    board: PerfboardModel,
    placements: list[ComponentPlacement],
    components: list[Component],
    footprints: dict[str, ThroughHoleFootprint],
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    by_ref = {c.ref: c for c in components}
    hole_owners: dict[str, list[str]] = defaultdict(list)
    valid_hole_ids = {h.id for h in board.holes}
    for p in placements:
        comp = by_ref.get(p.component_ref)
        if comp is None:
            diags.append(make_diagnostic("UNPLACED_COMPONENT", ref=p.component_ref))
            continue
        for hole_id in p.occupied_hole_ids:
            hole_owners[hole_id].append(p.component_ref)
        for pin_name, hole_id in p.pin_holes.items():
            if hole_id not in valid_hole_ids:
                diags.append(make_diagnostic("PIN_OUT_OF_BOARD", ref=p.component_ref, pin=pin_name))
    for hole_id, claimants in hole_owners.items():
        if len(claimants) > 1:
            diags.append(
                make_diagnostic(
                    "HOLE_COLLISION",
                    hole=hole_id,
                    claimants=",".join(sorted(claimants)),
                )
            )
    return diags


def _validate_traces(
    layout: TraceLayout,
    components: list[Component],
    nets: list[Net],
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    routed_nets = {t.net_id for t in layout.traces}
    placed_refs = {p.component_ref for p in layout.placements}

    # UNROUTED_TERMINAL for any net whose pin refs include a placed component
    # but the net never got a trace.
    for net in nets:
        if net.id in routed_nets:
            continue
        missing = [f"{p.component_ref}.{p.pin}" for p in net.pins if p.component_ref in placed_refs]
        if missing:
            diags.append(make_diagnostic("UNROUTED_TERMINAL", net=net.id, pins=",".join(sorted(missing))))
    return diags


def validate_layout(
    board: PerfboardModel,
    footprints: dict[str, ThroughHoleFootprint],
    components: list[Component],
    nets: list[Net],
    layout: TraceLayout,
) -> ValidationResult:
    """Validate a perfboard trace layout; pure, fast, no I/O."""
    result = ValidationResult()
    result.diagnostics.extend(_validate_input_basics(components, nets, footprints))
    result.diagnostics.extend(_validate_placements(board, layout.placements, components, footprints))
    result.diagnostics.extend(_validate_traces(layout, components, nets))
    return result
