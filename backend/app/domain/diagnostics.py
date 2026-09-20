"""Closed diagnostic catalog.

Every diagnostic code the solver, validator, and API can emit is registered here with its
severity and message template. Codes are load-bearing strings: the UI keys interaction off
them, the fixtures assert on them, and the smoke test checks for their absence/presence.
Never invent a code outside this catalog; extend the catalog instead.
"""

from __future__ import annotations

from app.domain.models import Diagnostic, DiagnosticSeverity

__all__ = ["DIAGNOSTIC_CATALOG", "make_diagnostic"]

DIAGNOSTIC_CATALOG: dict[str, tuple[DiagnosticSeverity, str]] = {
    # --- errors --------------------------------------------------------
    "SHORT_BETWEEN_NETS": ("error", "Nets {nets} share physical node {node}"),
    "NET_OPEN": ("error", "Net {net} is not fully connected: {pins} unreachable"),
    "UNPLACED_COMPONENT": ("error", "Component {ref} has no placement"),
    "UNPLACED_PIN": ("error", "Pin {ref}.{pin} has no hole assignment"),
    "INVALID_JUMPER_ENDPOINT": ("error", "Jumper {jumper} references unknown or disabled hole {hole}"),
    "HOLE_COLLISION": ("error", "Hole {hole} is claimed by {claimants}"),
    "BODY_COLLISION": ("error", "Bodies of {refs} overlap"),
    "PIN_OUT_OF_BOARD": ("error", "Pin {ref}.{pin} falls outside the board lattice"),
    "UNKNOWN_FOOTPRINT": ("error", "Component {ref} uses unknown footprint {footprint}"),
    "DUPLICATE_COMPONENT_REF": ("error", "Duplicate component ref {ref}"),
    "PIN_IN_MULTIPLE_NETS": ("error", "Pin {ref}.{pin} belongs to nets {nets}"),
    "UNKNOWN_PIN_REFERENCE": ("error", "Net {net} references unknown pin {ref}.{pin}"),
    "UNKNOWN_BOARD_MODEL": ("error", "Unknown board model {board}"),
    "PLACEMENT_RULE_VIOLATION": ("error", "Placement of {ref} violates rule {rule}"),
    # --- warnings --------------------------------------------------------
    "NET_SINGLE_PIN": ("warning", "Net {net} has fewer than two pins"),
    "RAIL_SEGMENT_ASSUMED_CONTINUOUS": (
        "warning",
        "Net {net} spans rail segments {segments}; this rail is split",
    ),
    "CRITICAL_NET_CLASS_ROUTED": (
        "warning",
        "Net {net} is class {net_class}; breadboard routing is not qualified for it",
    ),
    "LONG_CRITICAL_NET": ("warning", "Critical net {net} routed with {length_mm} mm of wire"),
    "HIGH_CONGESTION": ("warning", "Region around column {column} carries {count} jumpers"),
    "HIGH_CURRENT_ON_RAIL": ("warning", "Net {net} is high-current on a standard breadboard rail"),
    "INSUFFICIENT_BODY_CLEARANCE": (
        "warning",
        "Component {ref} has less than {value} hole(s) clearance",
    ),
    "APPROXIMATE_FOOTPRINT": ("warning", "Footprint {footprint} is an approximation of the real package"),
    # --- info --------------------------------------------------------
    "NET_CLASS_INFERRED": ("info", "Net {net} classified as {net_class} from its name"),
    "CLUSTER_ASSIGNED": ("info", "Component {ref} grouped with cluster anchor {anchor}"),
    # --- perfboard-specific -------------------------------------------
    "UNROUTED_TERMINAL": (
        "error",
        "Perfboard net {net} is missing one or more terminal connections: {pins}",
    ),
    "TRACE_CROSSING_UNAVOIDABLE": (
        "warning",
        "Perfboard trace layout has {count} unavoidable trace crossings",
    ),
}


def make_diagnostic(code: str, **fields: object) -> Diagnostic:
    """Build a `Diagnostic` from the catalog.

    `id` is stable across runs: `f"{code}:{'|'.join(sorted(key_parts))}"` where `key_parts`
    are the string-rendered field values. This lets callers diff diagnostics between solver
    runs without relying on insertion order.

    Raises `KeyError` for an unregistered code (fail loud rather than emit a free-text
    diagnostic).
    """

    severity, template = DIAGNOSTIC_CATALOG[code]
    message = template.format(**fields)

    key_parts = [str(v) for v in fields.values()]
    diagnostic_id = f"{code}:{'|'.join(sorted(key_parts))}" if key_parts else code

    related_hole_ids = _as_str_list(fields.get("hole")) + _as_str_list(fields.get("holes"))
    related_component_refs = _as_str_list(fields.get("ref")) + _as_str_list(fields.get("refs"))
    related_net_ids = _as_str_list(fields.get("net")) + _as_str_list(fields.get("nets"))

    suggestion = fields.get("suggestion")

    return Diagnostic(
        id=diagnostic_id,
        severity=severity,
        code=code,
        message=message,
        related_hole_ids=related_hole_ids,
        related_component_refs=related_component_refs,
        related_net_ids=related_net_ids,
        suggestion=str(suggestion) if suggestion is not None else None,
    )


def _as_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(v) for v in value]
    return [str(value)]
