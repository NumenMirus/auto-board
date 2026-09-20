"""Component clustering for placement ordering.

Clusters group components that should sit close together physically — a decoupling cap
next to its DIP, a base resistor next to its transistor. The router benefits because
shorter same-net wires mean fewer crossings; the placer benefits because cluster
members can be placed immediately after their anchor.

The rules are intentionally rule-based (not graph-based) per the spec. A component
joins the first cluster that matches; clusters are returned sorted by id.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import BreadboardFootprint, Component, Net

__all__ = ["Cluster", "build_clusters"]


@dataclass(frozen=True, slots=True)
class Cluster:
    """A placement cluster: an anchor (DIP, TO-92 acting as anchor) plus zero or more members."""

    id: str
    anchor_ref: str | None
    member_refs: tuple[str, ...]


# Footprints considered "2-pin passives that may act as bypass caps" for rule (b).
_TWO_PIN_CAP_FOOTPRINTS: frozenset[str] = frozenset(
    {
        "RADIAL-CAP-2P",
        "ELECTROLYTIC-CAP-2P",
        "LED-2P",
        "AXIAL-R",
        "AXIAL-DIODE",
    }
)

# Footprints that count as "resistor/diode" for rule (c).
_RESISTOR_DIODE_FOOTPRINTS: frozenset[str] = frozenset({"AXIAL-R", "AXIAL-DIODE"})


def _is_two_pin(footprint: BreadboardFootprint) -> bool:
    return footprint.id in _TWO_PIN_CAP_FOOTPRINTS and len(footprint.pin_offsets) == 2


def _power_or_ground(net: Net) -> bool:
    return net.net_class in ("power", "ground")


def _pins_by_net(nets: list[Net]) -> dict[str, set[tuple[str, str]]]:
    """Map ``net_id -> set[(component_ref, pin_id)]`` so the rules can answer
    "what's on this net?" in O(1).
    """
    out: dict[str, set[tuple[str, str]]] = {}
    for net in nets:
        bucket = out.setdefault(net.id, set())
        for pin in net.pins:
            bucket.add((pin.component_ref, pin.pin))
    return out


def _clusters_from_membership(
    anchor_for: dict[str, str],
    cluster_members: dict[str, list[str]],
) -> list[Cluster]:
    """Materialise :class:`Cluster` records from the membership dictionaries.

    Split out from :func:`build_clusters` so the dict-iteration here doesn't share
    scope with ``pins_by_net`` — mypy otherwise infers the wrong value-type when two
    distinct dicts are in scope.
    """
    clusters: list[Cluster] = []
    for anchor_ref, members in cluster_members.items():
        # Anchor first, then members in deterministic ref order.
        sorted_members = (anchor_ref, *sorted(m for m in members if m != anchor_ref))
        clusters.append(Cluster(id=anchor_ref, anchor_ref=anchor_ref, member_refs=sorted_members))
    # Silence "unused" warnings on debug-only state we keep for downstream callers.
    del anchor_for
    clusters.sort(key=lambda c: c.id)
    return clusters


def build_clusters(
    components: list[Component],
    nets: list[Net],
    footprints: dict[str, BreadboardFootprint],
) -> list[Cluster]:
    """Group components into placement clusters per the rule list.

    Rule order — first match wins:

    (a) every component whose footprint_id starts with ``DIP-`` is its own anchor;
    (b) a 2-pin passive sharing a power/ground net *and* another net with a DIP anchor's
        pin joins that anchor (bypass-cap heuristic);
    (c) a resistor/diode sharing any net with a TO-92 joins that TO-92's cluster (the
        TO-92 becomes an anchor singleton if it wasn't already one);
    (d) a component on a ``clock``-class net that shares that net with an established
        DIP anchor joins that anchor's cluster;
    (e) everything else is its own singleton cluster.

    Diagnostics for cluster assignment live in the validator, not here: the placer only
    consumes the cluster list to order placements.
    """
    by_ref: dict[str, Component] = {c.ref: c for c in components}

    # Each ref maps to the anchor ref of its cluster; ``anchor_for[anchor_ref] == anchor_ref``.
    anchor_for: dict[str, str] = {}
    # Anchor ref -> ordered list of member refs (anchor included).
    cluster_members: dict[str, list[str]] = {}

    def _ensure_anchor(ref: str) -> None:
        if ref in anchor_for:
            return
        anchor_for[ref] = ref
        cluster_members[ref] = [ref]

    # Pre-pass: DIP components are anchors.
    for comp in sorted(components, key=lambda c: c.ref):
        if comp.footprint_id.startswith("DIP-"):
            _ensure_anchor(comp.ref)

    # Index nets for O(1) lookup. Each entry: net_id -> set[(ref, pin)]
    pins_by_net = _pins_by_net(nets)
    # Invert: ref -> set[net_id] (only refs present in the netlist).
    nets_of_ref: dict[str, set[str]] = {}
    for net_id, members in pins_by_net.items():
        for ref, _pin in members:
            if ref in by_ref:
                nets_of_ref.setdefault(ref, set()).add(net_id)

    to92_refs: set[str] = {c.ref for c in components if c.footprint_id == "TO-92"}
    pg_classes: dict[str, bool] = {n.id: _power_or_ground(n) for n in nets}

    def _join(anchor_ref: str, member_ref: str) -> bool:
        if anchor_ref == member_ref:
            return True
        if member_ref in anchor_for:
            return False
        anchor_for[member_ref] = anchor_ref
        cluster_members.setdefault(anchor_ref, [anchor_ref]).append(member_ref)
        return True

    for comp in sorted(components, key=lambda c: c.ref):
        # Anchors already established by (a) don't need a cluster lookup.
        if comp.ref in anchor_for and anchor_for[comp.ref] == comp.ref:
            continue

        ref = comp.ref
        comp_nets = nets_of_ref.get(ref, set())
        comp_fp = footprints.get(comp.footprint_id)
        joined = False

        # (b) bypass-cap heuristic.
        if comp_fp is not None and _is_two_pin(comp_fp) and comp_nets:
            for anchor_ref, anchor_comp in by_ref.items():
                if anchor_ref == ref:
                    continue
                if not anchor_comp.footprint_id.startswith("DIP-"):
                    continue
                shared = comp_nets & nets_of_ref.get(anchor_ref, set())
                if len(shared) < 2:
                    continue
                if not any(pg_classes.get(nid, False) for nid in shared):
                    continue
                if _join(anchor_ref, ref):
                    joined = True
                    break

        # (c) resistor/diode sharing a net with a TO-92.
        if not joined and comp_fp is not None and comp_fp.id in _RESISTOR_DIODE_FOOTPRINTS:
            for to92_ref in to92_refs:
                if to92_ref == ref:
                    continue
                shared = comp_nets & nets_of_ref.get(to92_ref, set())
                if not shared:
                    continue
                _ensure_anchor(to92_ref)
                if _join(to92_ref, ref):
                    joined = True
                    break

        # (d) clock-net adjacency to a DIP anchor.
        if not joined:
            clock_nets: set[str] = {
                nid for nid in comp_nets for net in nets if net.id == nid and net.net_class == "clock"
            }
            for anchor_ref, anchor_comp in by_ref.items():
                if anchor_ref == ref:
                    continue
                if not anchor_comp.footprint_id.startswith("DIP-"):
                    continue
                anchor_clock_nets = clock_nets & nets_of_ref.get(anchor_ref, set())
                if anchor_clock_nets and _join(anchor_ref, ref):
                    joined = True
                    break

        # (e) singleton fallback.
        if not joined:
            _ensure_anchor(ref)

    return _clusters_from_membership(anchor_for, cluster_members)
