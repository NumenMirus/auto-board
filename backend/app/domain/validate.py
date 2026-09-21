"""Layout validator.

Pure, allocation-light validator that turns a `BreadboardModel`, its `BoardIndex`, the
component netlist, and a `Layout` into a list of `Diagnostic`s plus a `LayoutScore`. The
API serves this synchronously on every editor mutation, so the hot path is benchmarked at
under 20 ms for ~20 components / ~30 nets.

This module does not import Sanic, SQLAlchemy, redis, boto3, or `app.settings`. It is the
only validator used by `app.services.solver_job`, by the `/api/v1/validate` route, and by
the editor's debounced validation call.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from app.domain.connectivity import build_connectivity
from app.domain.diagnostics import make_diagnostic
from app.domain.models import LayoutScore

if TYPE_CHECKING:
    from app.domain.connectivity import Connectivity
    from app.domain.index import BoardIndex
    from app.domain.models import (
        BreadboardFootprint,
        BreadboardModel,
        Component,
        ComponentPlacement,
        Diagnostic,
        Layout,
        Net,
        PinRef,
        SolverOptions,
    )


__all__ = ["validate_layout"]

_CRITICAL_NET_CLASSES: frozenset[str] = frozenset({"switching", "clock", "analog-sensitive", "high-current"})

# Hole-id regexes for column extraction when computing congestion.
_TIE_HOLE_RE = re.compile(r"^([a-j])(\d+)$")
_RAIL_HOLE_RE = re.compile(r"^rail-(?P<line>.+)-(?P<seq>\d+)$")

# Threshold from the spec: more than six jumper endpoints in a single column is
# congestion. The warning fires once per offending column.
_HIGH_CONGESTION_THRESHOLD: int = 6


def _is_rail_backed(net: Net) -> bool:
    """Mirror the router's rail-preference test (`app.domain.route._resolve_net_endpoints`).

    Power/ground nets and explicit `prefer-rail` nets get one endpoint placed on a rail
    hole, so a single component pin on such a net is a real connection to the rail, not a
    dangling net.
    """
    if net.net_class in ("power", "ground"):
        return True
    return any(getattr(c, "type", None) == "prefer-rail" for c in net.constraints)


def validate_layout(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    layout: Layout,
    options: SolverOptions,
) -> tuple[list[Diagnostic], LayoutScore]:
    """Validate `layout` against the netlist and the board, returning diagnostics and a score.

    Pure function — no I/O, no logging, no global state. Two consecutive calls with the
    same inputs produce identical diagnostic lists and score objects.
    """

    diagnostics: list[Diagnostic] = []

    # ------------------------------------------------------------------
    # (a) input checks
    # ------------------------------------------------------------------

    # Duplicate component refs.
    ref_counts: dict[str, int] = defaultdict(int)
    for comp in components:
        ref_counts[comp.ref] += 1
    for ref in sorted(ref_counts):
        if ref_counts[ref] > 1:
            diagnostics.append(make_diagnostic("DUPLICATE_COMPONENT_REF", ref=ref))

    # Build a ref -> Component lookup, validate footprint ids, validate pin references
    # and detect pins claimed by multiple nets.
    components_by_ref: dict[str, Component] = {}
    for comp in components:
        # First ref wins; duplicates are surfaced by `DUPLICATE_COMPONENT_REF`.
        if comp.ref not in components_by_ref:
            components_by_ref[comp.ref] = comp

    seen_unknown_footprints: set[str] = set()
    for comp in components:
        if comp.footprint_id in footprints:
            continue
        if comp.footprint_id in seen_unknown_footprints:
            continue
        seen_unknown_footprints.add(comp.footprint_id)
        diagnostics.append(
            make_diagnostic(
                "UNKNOWN_FOOTPRINT",
                ref=comp.ref,
                footprint=comp.footprint_id,
            )
        )

    # Track every (ref, pin) -> set of net ids seen.
    pin_to_nets: dict[tuple[str, str], set[str]] = defaultdict(set)
    seen_pin_errors: set[tuple[str, str, str]] = set()  # (net, ref, pin) already emitted
    board_has_rails = any(gid.startswith("rail-") for gid in index.group_ids)
    for net in nets:
        if len(net.pins) < 2 and not (
            len(net.pins) == 1 and board_has_rails and _is_rail_backed(net)
        ):
            diagnostics.append(make_diagnostic("NET_SINGLE_PIN", net=net.id))
        for pin_ref in net.pins:
            ref_comp = components_by_ref.get(pin_ref.component_ref)
            if ref_comp is None or pin_ref.pin not in ref_comp.pins:
                key = (net.id, pin_ref.component_ref, pin_ref.pin)
                if key not in seen_pin_errors:
                    seen_pin_errors.add(key)
                    diagnostics.append(
                        make_diagnostic(
                            "UNKNOWN_PIN_REFERENCE",
                            net=net.id,
                            ref=pin_ref.component_ref,
                            pin=pin_ref.pin,
                        )
                    )
                continue
            pin_to_nets[(pin_ref.component_ref, pin_ref.pin)].add(net.id)

    seen_multi_pin: set[tuple[str, str]] = set()
    for (ref, pin), attached in pin_to_nets.items():
        if len(attached) <= 1:
            continue
        if (ref, pin) in seen_multi_pin:
            continue
        seen_multi_pin.add((ref, pin))
        diagnostics.append(
            make_diagnostic(
                "PIN_IN_MULTIPLE_NETS",
                ref=ref,
                pin=pin,
                nets=sorted(attached),
            )
        )

    # ------------------------------------------------------------------
    # Build placement lookups
    # ------------------------------------------------------------------

    placements_by_ref: dict[str, ComponentPlacement] = {p.component_ref: p for p in layout.placements}
    # hole -> sorted list of placement refs claiming it (for HOLE_COLLISION and
    # INVALID_JUMPER_ENDPOINT checks).
    occupied_holes: dict[str, list[str]] = defaultdict(list)
    for placement in layout.placements:
        for hole_id in placement.occupied_hole_ids:
            occupied_holes[hole_id].append(placement.component_ref)
        # Pin holes count as claimed (a jumper ending on the placement's pin is invalid).
        for hole_id in placement.pin_holes.values():
            if placement.component_ref not in occupied_holes[hole_id]:
                occupied_holes[hole_id].append(placement.component_ref)

    # ------------------------------------------------------------------
    # (b) placement checks
    # ------------------------------------------------------------------

    for placement in layout.placements:
        ref_comp = components_by_ref.get(placement.component_ref)
        if ref_comp is None:
            continue
        # Pin-hole existence and enabled-ness.
        for pin_id, hole_id in placement.pin_holes.items():
            hole_idx = index.idx.get(hole_id)
            if hole_idx is None or not index.enabled[hole_idx]:
                diagnostics.append(
                    make_diagnostic(
                        "PIN_OUT_OF_BOARD",
                        ref=placement.component_ref,
                        pin=pin_id,
                    )
                )
        # Placement rules.
        footprint = footprints.get(ref_comp.footprint_id)
        if footprint is None:
            continue
        for rule in footprint.placement_rules:
            rule_type = getattr(rule, "type", None)
            if rule_type == "must-straddle-center-gap" and not _placement_straddles_center_gap(
                index, placement
            ):
                diagnostics.append(
                    make_diagnostic(
                        "PLACEMENT_RULE_VIOLATION",
                        ref=placement.component_ref,
                        rule="must-straddle-center-gap",
                    )
                )

    for hole_id, claimants in sorted(occupied_holes.items()):
        unique_claimants = sorted(set(claimants))
        if len(unique_claimants) > 1:
            diagnostics.append(
                make_diagnostic(
                    "HOLE_COLLISION",
                    hole=hole_id,
                    claimants=unique_claimants,
                )
            )

    # ------------------------------------------------------------------
    # (c) jumper checks
    # ------------------------------------------------------------------

    # Build the set of body-only holes: occupied holes that aren't pin holes of their
    # owner placement. A jumper endpoint coinciding with such a hole is an
    # `INVALID_JUMPER_ENDPOINT` — physically a wire cannot share a body-only cell. A
    # jumper endpoint coinciding with a pin hole of some placement is allowed (a real
    # breadboard can stack a wire and a component lead in the same tie-point hole).
    body_only_holes: set[str] = set()
    for hole_id, claimants in occupied_holes.items():
        for placement in layout.placements:
            if placement.component_ref not in claimants:
                continue
            if hole_id in placement.pin_holes.values():
                break
        else:
            body_only_holes.add(hole_id)

    for jumper in layout.jumpers:
        for endpoint in (jumper.start_hole_id, jumper.end_hole_id):
            hole_idx = index.idx.get(endpoint)
            if hole_idx is None or not index.enabled[hole_idx]:
                diagnostics.append(
                    make_diagnostic(
                        "INVALID_JUMPER_ENDPOINT",
                        jumper=jumper.id,
                        hole=endpoint,
                    )
                )
                continue
            if endpoint in body_only_holes:
                diagnostics.append(
                    make_diagnostic(
                        "INVALID_JUMPER_ENDPOINT",
                        jumper=jumper.id,
                        hole=endpoint,
                    )
                )

    # ------------------------------------------------------------------
    # (d) connectivity → shorts / opens
    # ------------------------------------------------------------------

    connectivity = build_connectivity(index, footprints, components, layout)

    net_to_pins: dict[str, list[tuple[PinRef, int, str]]] = defaultdict(list)
    for net in nets:
        for pin_ref in net.pins:
            pin_placement = placements_by_ref.get(pin_ref.component_ref)
            if pin_placement is None:
                continue
            pin_hole = pin_placement.pin_holes.get(pin_ref.pin)
            if pin_hole is None:
                continue
            hole_idx = index.idx.get(pin_hole)
            if hole_idx is None:
                continue
            root = connectivity.root_of_idx(hole_idx)
            net_to_pins[net.id].append((pin_ref, root, pin_hole))

    # root -> set of net ids attached.
    root_to_nets: dict[int, set[str]] = defaultdict(set)
    for net_id, entries in net_to_pins.items():
        for _pinref, root, _hole in entries:
            root_to_nets[root].add(net_id)

    for root in sorted(root_to_nets):
        attached = root_to_nets[root]
        if len(attached) <= 1:
            continue
        sorted_nets = sorted(attached)
        node = _lex_smallest_hole_in_root(connectivity, root)
        diagnostics.append(
            make_diagnostic(
                "SHORT_BETWEEN_NETS",
                nets=sorted_nets,
                node=node,
            )
        )

    # Open nets: any net whose placed pins do not all share one root.
    short_nets: set[str] = set()
    for d in diagnostics:
        if d.code == "SHORT_BETWEEN_NETS":
            short_nets.update(d.related_net_ids)

    for net_id, entries in net_to_pins.items():
        if len(entries) < 2:
            continue
        roots = {root for _pinref, root, _hole in entries}
        if len(roots) <= 1:
            continue
        # Minority = pins whose root is not the most-popular root.
        root_counts: dict[int, int] = defaultdict(int)
        for _pinref, root, _hole in entries:
            root_counts[root] += 1
        majority_root = max(
            sorted(root_counts, key=lambda r: (-root_counts[r], r)),
        )
        minority = sorted(
            f"{pin.component_ref}.{pin.pin}" for pin, root, _hole in entries if root != majority_root
        )
        diagnostics.append(
            make_diagnostic(
                "NET_OPEN",
                net=net_id,
                pins=minority,
            )
        )

    # ------------------------------------------------------------------
    # (e) rail-segment sanity
    # ------------------------------------------------------------------

    diagnostics.extend(_check_rail_segments(nets, layout, index))

    # ------------------------------------------------------------------
    # (f) class warnings
    # ------------------------------------------------------------------

    diagnostics.extend(_check_class_warnings(nets, net_to_pins, index, layout, options))

    # ------------------------------------------------------------------
    # (g) congestion
    # ------------------------------------------------------------------

    diagnostics.extend(_check_congestion(layout))

    # ------------------------------------------------------------------
    # Score
    # ------------------------------------------------------------------

    score = _build_score(components, nets, layout, diagnostics, net_to_pins, options)

    return diagnostics, score


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _placement_straddles_center_gap(index: BoardIndex, placement: ComponentPlacement) -> bool:
    """True iff the placement's pin holes occupy both row indices of `center_gap_between`."""
    a_row, b_row = index.center_gap_between
    has_a = False
    has_b = False
    for hole_id in placement.pin_holes.values():
        m = _TIE_HOLE_RE.match(hole_id)
        if m is None:
            continue
        row_idx = index.row_index_of.get(m.group(1))
        if row_idx == a_row:
            has_a = True
        elif row_idx == b_row:
            has_b = True
        if has_a and has_b:
            return True
    return False


def _check_rail_segments(nets: list[Net], layout: Layout, index: BoardIndex) -> list[Diagnostic]:
    """Emit `RAIL_SEGMENT_ASSUMED_CONTINUOUS` for any net touching two rail segments."""
    diagnostics: list[Diagnostic] = []

    # Map each rail group id to its rail line (e.g. "top-plus").
    rail_line_of: dict[str, str] = {}
    for group_idx, _group in enumerate(index.group_holes):
        rgid = index.group_ids[group_idx]
        if not rgid.startswith("rail-"):
            continue
        m = re.match(r"^rail-(?P<line>.+)-seg-[ab]$", rgid)
        if m is not None:
            rail_line_of[rgid] = m.group("line")

    hole_to_group: dict[str, str] = {}
    for group_idx, member_idxs in enumerate(index.group_holes):
        rgid = index.group_ids[group_idx]
        for hole_idx in member_idxs:
            hole_to_group[index.hole_ids[hole_idx]] = rgid

    placements_by_ref = {p.component_ref: p for p in layout.placements}

    net_rail_groups: dict[str, set[str]] = defaultdict(set)
    for net in nets:
        for pin_ref in net.pins:
            pin_placement = placements_by_ref.get(pin_ref.component_ref)
            if pin_placement is None:
                continue
            pin_hole = pin_placement.pin_holes.get(pin_ref.pin)
            if pin_hole is None:
                continue
            hole_gid = hole_to_group.get(pin_hole)
            if hole_gid is None or hole_gid not in rail_line_of:
                continue
            net_rail_groups[net.id].add(hole_gid)
        for jumper in layout.jumpers:
            if jumper.net_id != net.id:
                continue
            for rail_endpoint in (jumper.start_hole_id, jumper.end_hole_id):
                ep_gid = hole_to_group.get(rail_endpoint)
                if ep_gid is None or ep_gid not in rail_line_of:
                    continue
                net_rail_groups[net.id].add(ep_gid)

    for net_id, group_ids in net_rail_groups.items():
        per_line: dict[str, set[str]] = defaultdict(set)
        for rgid in group_ids:
            per_line[rail_line_of[rgid]].add(rgid)
        differing: list[str] = []
        for _line, groups in sorted(per_line.items()):
            if len(groups) > 1:
                differing.extend(sorted(groups))
        if differing:
            diagnostics.append(
                make_diagnostic(
                    "RAIL_SEGMENT_ASSUMED_CONTINUOUS",
                    net=net_id,
                    segments=sorted(set(differing)),
                )
            )
    return diagnostics


def _check_class_warnings(
    nets: list[Net],
    net_to_pins: dict[str, list[tuple[PinRef, int, str]]],
    index: BoardIndex,
    layout: Layout,
    options: SolverOptions,
) -> list[Diagnostic]:
    """Emit `CRITICAL_NET_CLASS_ROUTED` and `HIGH_CURRENT_ON_RAIL`."""
    diagnostics: list[Diagnostic] = []

    for net in nets:
        entries = net_to_pins.get(net.id, [])
        distinct_roots = {root for _pinref, root, _hole in entries}
        is_routed = len(entries) >= 2 and len(distinct_roots) <= 1

        if net.net_class in _CRITICAL_NET_CLASSES and is_routed:
            diagnostics.append(
                make_diagnostic(
                    "CRITICAL_NET_CLASS_ROUTED",
                    net=net.id,
                    net_class=net.net_class,
                )
            )

        if net.net_class == "high-current":
            touches_rail = False
            for _pinref, _root, hole_id in entries:
                hole_idx = index.idx.get(hole_id)
                if hole_idx is None:
                    continue
                gid = index.group_ids[index.group_of[hole_idx]]
                if gid.startswith("rail-"):
                    touches_rail = True
                    break
            if not touches_rail:
                for jumper in layout.jumpers:
                    if jumper.net_id != net.id:
                        continue
                    for hc_endpoint in (jumper.start_hole_id, jumper.end_hole_id):
                        hole_idx = index.idx.get(hc_endpoint)
                        if hole_idx is None:
                            continue
                        gid = index.group_ids[index.group_of[hole_idx]]
                        if gid.startswith("rail-"):
                            touches_rail = True
                            break
                    if touches_rail:
                        break
            if touches_rail:
                diagnostics.append(
                    make_diagnostic(
                        "HIGH_CURRENT_ON_RAIL",
                        net=net.id,
                    )
                )

    return diagnostics


def _check_congestion(layout: Layout) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    column_counts: dict[int, int] = defaultdict(int)
    for jumper in layout.jumpers:
        for endpoint in (jumper.start_hole_id, jumper.end_hole_id):
            col = _column_of_hole(endpoint)
            if col is not None:
                column_counts[col] += 1
    for column, count in sorted(column_counts.items()):
        if count > _HIGH_CONGESTION_THRESHOLD:
            diagnostics.append(
                make_diagnostic(
                    "HIGH_CONGESTION",
                    column=column,
                    count=count,
                )
            )
    return diagnostics


def _column_of_hole(hole_id: str) -> int | None:
    m = _TIE_HOLE_RE.match(hole_id)
    if m is not None:
        return int(m.group(2))
    m = _RAIL_HOLE_RE.match(hole_id)
    if m is not None:
        return int(m.group("seq"))
    return None


def _lex_smallest_hole_in_root(connectivity: Connectivity, root: int) -> str:
    """Return the lex-smallest hole id in the DSU root, or empty string when none."""
    for root_id, hole_ids in connectivity.groups().items():
        if root_id == root and hole_ids:
            return hole_ids[0]  # `groups()` returns members sorted ascending.
    return ""


def _build_score(
    components: list[Component],
    nets: list[Net],
    layout: Layout,
    diagnostics: list[Diagnostic],
    net_to_pins: dict[str, list[tuple[PinRef, int, str]]],
    options: SolverOptions,
) -> LayoutScore:
    placed_refs = {p.component_ref for p in layout.placements}
    component_refs = {c.ref for c in components}
    components_placed = len(placed_refs & component_refs)
    components_total = len(components)

    open_nets = {d.related_net_ids[0] for d in diagnostics if d.code == "NET_OPEN"}
    short_nets: set[str] = set()
    for d in diagnostics:
        if d.code == "SHORT_BETWEEN_NETS":
            short_nets.update(d.related_net_ids)

    nets_completed = 0
    for net in nets:
        if net.id in open_nets or net.id in short_nets:
            continue
        if not net_to_pins.get(net.id):
            continue
        if not options.allow_critical_net_classes and net.net_class in _CRITICAL_NET_CLASSES:
            continue
        nets_completed += 1

    jumper_count = len(layout.jumpers)
    total_jumper_length_mm = round(sum(j.estimated_length_mm for j in layout.jumpers), 2)
    error_count = sum(1 for d in diagnostics if d.severity == "error")
    warning_count = sum(1 for d in diagnostics if d.severity == "warning")

    return LayoutScore(
        total=0.0,
        placement_cost=0.0,
        routing_cost=0.0,
        components_placed=components_placed,
        components_total=components_total,
        nets_completed=nets_completed,
        nets_total=len(nets),
        jumper_count=jumper_count,
        total_jumper_length_mm=total_jumper_length_mm,
        crossings=0,
        error_count=error_count,
        warning_count=warning_count,
    )
