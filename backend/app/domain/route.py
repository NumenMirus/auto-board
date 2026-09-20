"""Auto-router: turns a placed layout into a fully wired `RouteResult`.

The router follows main spec §7: it consumes a `Layout` whose `placements` are already
populated (by `app.domain.place.place`), decides the order in which nets get wired, builds
a minimal Steiner tree per net, lays out two-segment Manhattan jumper paths, computes the
routing cost, and runs a bounded rip-up/reroute pass for any net left open after the main
phase. Locked jumpers and pre-existing manual electrical links are preserved untouched.

The function is pure: no I/O, no logging, no global state. It uses only the `random`
RNG instance it creates from `options.seed` (no `random.*` module-level calls) and never
calls Python's builtin `hash()` (per-process randomised). Net and column iteration is
always sorted to keep the output deterministic across runs.

Signature mirrors `validate_layout`: individual typed arguments rather than a wrapped
request object — the `RouteRequest` Pydantic model exists for the API layer to unpack
into.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from itertools import pairwise

from app.domain.connectivity import Connectivity, build_connectivity
from app.domain.errors import SolverTimeout
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Jumper,
    JumperPath,
    Layout,
    ManualLink,
    Net,
    NetClass,
    Point,
    RouteResult,
    SolverOptions,
    SolverTrace,
    TraceRipup,
)

__all__ = ["route"]

_CRITICAL_NET_CLASSES: frozenset[str] = frozenset({"switching", "clock", "analog-sensitive", "high-current"})

_PALETTE: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
    "#bcbd22",
    "#7f7f7f",
    "#3b7dd8",
    "#c44e52",
    "#55a868",
)


def route(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    layout: Layout,
    options: SolverOptions,
    *,
    deadline_monotonic: float | None = None,
) -> RouteResult:
    """Route the jumpers for `layout` and return a `RouteResult`.

    `layout` arrives with `placements` already set and may carry pre-existing locked or
    manual jumpers in `layout.jumpers` — those are preserved verbatim in the output.
    `deadline_monotonic` is an optional `time.monotonic()` value past which the function
    raises `SolverTimeout` (callers in `solve.py` pass it; the free-standing API path
    may leave it `None`).
    """

    start = time.monotonic()

    # Snapshot the preserved jumpers. Only `Jumper.locked=True` items are preserved
    # verbatim: manual electrical links live in `layout.manual_electrical_links` (not
    # in `layout.jumpers`) and so cannot reach this list. Preserved jumpers are not
    # touched by the rip-up/reroute loop and contribute to the cost as-is.
    preserved_jumpers: list[Jumper] = [j for j in layout.jumpers if j.locked]

    occupied_holes: set[str] = _collect_occupied_holes(layout)
    jumper_endpoint_holes: set[str] = {j.start_hole_id for j in preserved_jumpers} | {
        j.end_hole_id for j in preserved_jumpers
    }

    # Seed connectivity so a second route() call on a layout that already contains
    # jumpers (locked or otherwise) starts from the right equipotentials.
    base_connectivity = build_connectivity(index, footprints, components, layout)

    # Rail-segment ownership for the prefer-rail pass: local to this route() call.
    rail_assignment: dict[int, str] = {}

    new_jumpers: list[Jumper] = []
    unrouted_nets: list[str] = []
    ripups: list[TraceRipup] = []

    # Nets that should be skipped because their class is critical but the caller has
    # forbidden routing critical classes.
    skip_critical: list[str] = []

    # (1) Order nets per main spec §7.4.
    ordered_nets = _order_nets(nets, index)

    # (2) First pass: route every routable net.
    for net in ordered_nets:
        _check_deadline(start, deadline_monotonic)

        if net.net_class in _CRITICAL_NET_CLASSES and not options.allow_critical_net_classes:
            # Skipped entirely; track for cost and unrouted list.
            skip_critical.append(net.id)
            unrouted_nets.append(net.id)
            continue

        # Resolve per-pin endpoints. Returns either pin hole ids (normal) or pin hole ids
        # plus zero-or-more extra rail hole ids (prefer-rail net).
        endpoint_holes, skip_reason = _resolve_net_endpoints(
            net=net,
            index=index,
            components=components,
            layout=layout,
            occupied_holes=occupied_holes,
            jumper_endpoint_holes=jumper_endpoint_holes,
            rail_assignment=rail_assignment,
            connectivity=base_connectivity,
            new_jumpers=new_jumpers,
        )

        if endpoint_holes is None or len(endpoint_holes) < 2:
            # Could not find a valid set of endpoints (e.g. no rail free for a power net).
            unrouted_nets.append(net.id)
            continue
        if skip_reason is not None:
            # Net reduced to fewer than two endpoints (e.g. all pins share one group
            # already); record as completed but skip jumper creation.
            # This branch is hit only when the net has fewer than 2 pins or all pins
            # already share a root in the existing connectivity.
            continue

        jumpers = _route_single_net(
            net=net,
            endpoint_holes=endpoint_holes,
            index=index,
            occupied_holes=occupied_holes,
            jumper_endpoint_holes=jumper_endpoint_holes,
            existing_jumpers=new_jumpers,
            seed=options.seed,
        )
        if not jumpers:
            unrouted_nets.append(net.id)
            continue

        new_jumpers.extend(jumpers)
        for j in jumpers:
            jumper_endpoint_holes.add(j.start_hole_id)
            jumper_endpoint_holes.add(j.end_hole_id)

    # (3) Rip-up / reroute (main spec §7.6). Use the connectivity built after the first
    # pass to detect nets whose terminals do not share a root.
    if not unrouted_nets or options.max_ripup_iterations <= 0:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        final_jumpers = preserved_jumpers + new_jumpers
        cost = _compute_routing_cost(
            board=board,
            nets=nets,
            layout_with_jumpers=Layout(
                version=1,
                board_id=board.id,
                placements=list(layout.placements),
                jumpers=final_jumpers,
                manual_electrical_links=list(layout.manual_electrical_links),
            ),
            unrouted_nets=unrouted_nets,
            skip_critical=skip_critical,
            options=options,
        )
        trace = SolverTrace(
            seed=options.seed,
            placement_order=[],
            failed_nets=list(unrouted_nets),
            ripups=ripups,
            phase_timings_ms={"route": elapsed_ms},
        )
        return RouteResult(
            jumpers=final_jumpers,
            unrouted_nets=unrouted_nets,
            trace=trace,
            cost=cost,
        )

    connectivity_after = _build_layout_connectivity(
        index=index,
        footprints=footprints,
        components=components,
        placements=layout.placements,
        preserved_jumpers=preserved_jumpers,
        new_jumpers=new_jumpers,
        manual_links=layout.manual_electrical_links,
    )

    failed_nets = _open_nets(nets, layout.placements, index, connectivity_after)
    # Keep order of `unrouted_nets` deterministic: failed_nets ∩ unrouted_nets in order.
    failed_nets_in_order = [nid for nid in unrouted_nets if nid in failed_nets]

    rng = random.Random(options.seed)
    rounds_left = options.max_ripup_iterations
    progress_round = 0
    while failed_nets_in_order and rounds_left > 0:
        _check_deadline(start, deadline_monotonic)
        rounds_left -= 1
        progress_round += 1
        target_net_id = failed_nets_in_order[0]

        # Identify up to 3 non-locked jumpers in the congested region of the failed net
        # (within 3 columns of any pin hole of the failing net, sorted by length desc).
        removed = _rip_up(
            target_net_id=target_net_id,
            nets=nets,
            placements=layout.placements,
            index=index,
            preserved_jumpers=preserved_jumpers,
            new_jumpers=new_jumpers,
            connectivity=connectivity_after,
            max_remove=3,
            rng=rng,
        )
        if not removed:
            break
        # Drop them from the working set.
        removed_ids = {r.id for r in removed}
        new_jumpers = [j for j in new_jumpers if j.id not in removed_ids]
        for r in removed:
            jumper_endpoint_holes.discard(r.start_hole_id)
            jumper_endpoint_holes.discard(r.end_hole_id)
        ripups.append(
            TraceRipup(
                net_id=target_net_id,
                removed_jumper_ids=[r.id for r in removed],
                reason="congestion_retry",
            )
        )

        # Rebuild a synthetic net list containing only the failing net and the nets
        # of the removed jumpers (so we re-route them first).
        affected_net_ids = {target_net_id} | {j.net_id for j in removed}
        affected = [n for n in ordered_nets if n.id in affected_net_ids]
        other = [n for n in ordered_nets if n.id not in affected_net_ids]

        # Free the occupied-set entries for the removed jumpers.
        affected_new = _reroute_subset(
            affected_nets=affected,
            other_nets=other,
            nets=nets,
            index=index,
            footprints=footprints,
            components=components,
            layout=layout,
            preserved_jumpers=preserved_jumpers,
            occupied_holes=occupied_holes,
            jumper_endpoint_holes=jumper_endpoint_holes,
            existing_new_jumpers=new_jumpers,
            options=options,
            deadline_monotonic=deadline_monotonic,
            start_monotonic=start,
            skip_critical=skip_critical,
        )

        new_jumpers = affected_new
        connectivity_after = _build_layout_connectivity(
            index=index,
            footprints=footprints,
            components=components,
            placements=layout.placements,
            preserved_jumpers=preserved_jumpers,
            new_jumpers=new_jumpers,
            manual_links=layout.manual_electrical_links,
        )
        failed_nets = _open_nets(nets, layout.placements, index, connectivity_after)
        failed_nets_in_order = [nid for nid in unrouted_nets if nid in failed_nets]

    # Recompute unrouted_nets as the set of nets still open (or skipped).
    final_connectivity = _build_layout_connectivity(
        index=index,
        footprints=footprints,
        components=components,
        placements=layout.placements,
        preserved_jumpers=preserved_jumpers,
        new_jumpers=new_jumpers,
        manual_links=layout.manual_electrical_links,
    )
    final_open = set(_open_nets(nets, layout.placements, index, final_connectivity))
    final_unrouted = list(final_open | set(skip_critical))

    elapsed_ms = (time.monotonic() - start) * 1000.0
    final_jumpers = preserved_jumpers + new_jumpers
    cost = _compute_routing_cost(
        board=board,
        nets=nets,
        layout_with_jumpers=Layout(
            version=1,
            board_id=board.id,
            placements=list(layout.placements),
            jumpers=final_jumpers,
            manual_electrical_links=list(layout.manual_electrical_links),
        ),
        unrouted_nets=final_unrouted,
        skip_critical=skip_critical,
        options=options,
    )
    trace = SolverTrace(
        seed=options.seed,
        placement_order=[],
        failed_nets=final_unrouted,
        ripups=ripups,
        phase_timings_ms={"route": elapsed_ms},
    )
    return RouteResult(
        jumpers=final_jumpers,
        unrouted_nets=final_unrouted,
        trace=trace,
        cost=cost,
    )


# --------------------------------------------------------------------------
# Net ordering (main spec §7.4)
# --------------------------------------------------------------------------


def _order_nets(
    nets: list[Net],
    index: BoardIndex,
) -> list[Net]:
    """Sort nets for routing in priority order.

    Order: critical classes first (only if allowed at the caller), then power/ground,
    then multi-terminal nets (>2 pins), then long-span nets (pin-to-pin Manhattan span
    exceeds half the board width), then digital, then everything else. Within each
    bucket: priority descending, id ascending.
    """

    if not nets:
        return []

    half_width_mm = max((p[0] for p in index.points), default=0.0) / 2.0

    def _span(net: Net) -> float:
        if len(net.pins) < 2:
            return 0.0
        xs: list[float] = []
        ys: list[float] = []
        # Only pin-to-pin span is computable without placements; use the board's full
        # bounding box for nets without placements (the routing-pass will discard them).
        for p in index.points:
            xs.append(p[0])
            ys.append(p[1])
        return max(xs) - min(xs) + max(ys) - min(ys)

    def _bucket(net: Net) -> tuple[int, int, int, int, int]:
        critical = 1 if net.net_class in _CRITICAL_NET_CLASSES else 0
        pg = 1 if net.net_class in ("power", "ground") else 0
        multi = 1 if len(net.pins) > 2 else 0
        long_ = 1 if _span(net) > half_width_mm else 0
        digital = 1 if net.net_class == "digital" else 0
        return (critical, pg, multi, long_, digital)

    keyed = [(_bucket(n), -n.priority, n.id, n) for n in nets]
    keyed.sort(key=lambda k: (k[0], k[1], k[2]))
    return [n for _b, _p, _i, n in keyed]


# --------------------------------------------------------------------------
# Endpoint resolution
# --------------------------------------------------------------------------


def _collect_occupied_holes(layout: Layout) -> set[str]:
    occupied: set[str] = set()
    for placement in layout.placements:
        occupied.update(placement.occupied_hole_ids)
        occupied.update(placement.pin_holes.values())
    return occupied


def _has_prefer_rail(net: Net) -> bool:
    return any(getattr(c, "type", None) == "prefer-rail" for c in net.constraints)


def _net_pin_holes(net: Net, components: list[Component], layout: Layout) -> dict[str, str]:
    """Return `PinRef -> pin_hole_id` for every pin of `net` that has a placement.

    Pins whose component is not placed are skipped (the validator will surface
    `UNPLACED_PIN`/`UNPLACED_COMPONENT` for those later).
    """

    placements_by_ref = {p.component_ref: p for p in layout.placements}
    components_by_ref = {c.ref: c for c in components}
    out: dict[str, str] = {}
    for pin_ref in net.pins:
        placement = placements_by_ref.get(pin_ref.component_ref)
        if placement is None:
            continue
        comp = components_by_ref.get(pin_ref.component_ref)
        if comp is None or pin_ref.pin not in comp.pins:
            continue
        hole_id = placement.pin_holes.get(pin_ref.pin)
        if hole_id is not None:
            out[f"{pin_ref.component_ref}.{pin_ref.pin}"] = hole_id
    return out


def _resolve_net_endpoints(
    *,
    net: Net,
    index: BoardIndex,
    components: list[Component],
    layout: Layout,
    occupied_holes: set[str],
    jumper_endpoint_holes: set[str],
    rail_assignment: dict[int, str],
    connectivity: Connectivity,
    new_jumpers: list[Jumper],
) -> tuple[list[str] | None, str | None]:
    """Return `(endpoint_holes, skip_reason)` for `net`.

    `endpoint_holes` is a list of hole ids that the Steiner tree must connect. For
    rail-preferred nets (`prefer-rail` or power/ground) the list contains the pin holes
    PLUS one chosen free rail hole per pin cluster, so the tree also touches the rail.
    `skip_reason` is non-None when the net is short-circuited (no jumper needed).
    """

    pin_holes = _net_pin_holes(net, components, layout)
    if len(pin_holes) < 2:
        return None, "fewer-than-two-pins"

    # If every pin already shares one DSU root via the existing connectivity (placements
    # + preserved jumpers + manual links), no jumper is needed.
    roots = {
        connectivity.root_of_hole(h_id) for h_id in pin_holes.values() if connectivity.root_of_hole(h_id) >= 0
    }
    if len(roots) <= 1 and roots and next(iter(roots)) >= 0:
        return list(pin_holes.values()), "already-connected"

    use_rail = net.net_class in ("power", "ground") or _has_prefer_rail(net)

    # Determine the group idx that owns each pin's electrical group. We need at least
    # one pin to be reachable from a rail segment group, otherwise the rail pass would
    # not help.
    pin_group_indices: set[int] = set()
    for h_id in pin_holes.values():
        g_idx = index.group_of_hole(h_id)
        if g_idx >= 0:
            pin_group_indices.add(g_idx)

    rail_segments: list[int] = _candidate_rail_segments(index, pin_group_indices)

    if use_rail and rail_segments:
        chosen_segment = _pick_rail_segment(
            rail_segments=rail_segments,
            rail_assignment=rail_assignment,
            net_id=net.id,
            index=index,
        )
        if chosen_segment is not None:
            rail_hole = _pick_free_rail_hole(
                group_idx=chosen_segment,
                index=index,
                occupied_holes=occupied_holes,
                jumper_endpoint_holes=jumper_endpoint_holes,
            )
            if rail_hole is not None:
                rail_assignment[chosen_segment] = net.id
                # The Steiner tree connects every pin hole plus this one rail hole.
                return [*list(pin_holes.values()), rail_hole], None

    # Fallback: direct pin-to-pin routing.
    return list(pin_holes.values()), None


def _candidate_rail_segments(
    index: BoardIndex,
    pin_group_indices: set[int],
) -> list[int]:
    """Return rail-segment group indices that touch at least one of the pin groups.

    Two tie-point groups are "touches" via a shared column — a pin at column N in
    tie-point group `tp-l-N` is physically adjacent to rail holes whose X is nearest
    column N. For our purposes, any rail segment whose X range overlaps the pin's X
    counts. Implemented here as "any rail segment whose X range overlaps the pin
    group's column range", approximated by: a rail segment is a candidate if any of its
    member holes has the closest column to at least one pin hole.
    """

    if not pin_group_indices:
        return []

    # Collect candidate X coords from pin holes.
    pin_xs: set[int] = set()
    for g_idx in pin_group_indices:
        for h_idx in index.group_holes[g_idx]:
            hx, _hy = index.points[h_idx]
            # Convert mm X to column index, rounded.
            pin_xs.add(round(hx / 2.54) + 1)

    out: list[int] = []
    for group_idx, member_idxs in enumerate(index.group_holes):
        if not index.group_ids[group_idx].startswith("rail-"):
            continue
        if not member_idxs:
            continue
        # Check whether any rail hole's column falls within the pin column set +/- 1
        # (rails cluster at 5-hole boundaries, so adjacency is by X coord).
        for h_idx in member_idxs:
            hx, _hy = index.points[h_idx]
            col = round(hx / 2.54) + 1
            if col in pin_xs or any(abs(col - px) <= 1 for px in pin_xs):
                out.append(group_idx)
                break
    return out


def _pick_rail_segment(
    *,
    rail_segments: list[int],
    rail_assignment: dict[int, str],
    net_id: str,
    index: BoardIndex,
) -> int | None:
    """Pick the cheapest (most-recently-failed-net-aware) usable rail segment.

    Cost ordering: unassigned segments first, then segments already assigned to this
    same net, then by free-hole count descending (more free holes == better connectivity
    potential). Returns `None` when every segment is owned by another net and has no free
    holes.
    """

    best: int | None = None
    best_rank: tuple[int, int, int] = (-1, -1, -1)
    for seg in rail_segments:
        owner = rail_assignment.get(seg)
        if owner is not None and owner != net_id:
            continue
        free_count = _count_free_holes(seg, index)
        if free_count <= 0:
            continue
        rank: tuple[int, int, int] = (
            1 if owner is None else 0,  # unassigned beats same-net
            1 if owner == net_id else 0,
            free_count,
        )
        if rank > best_rank:
            best = seg
            best_rank = rank
    return best


def _count_free_holes(group_idx: int, index: BoardIndex) -> int:
    return len(index.group_holes[group_idx])


def _pick_free_rail_hole(
    *,
    group_idx: int,
    index: BoardIndex,
    occupied_holes: set[str],
    jumper_endpoint_holes: set[str],
) -> str | None:
    """Return the first hole of `group_idx` that is neither occupied nor an existing
    jumper endpoint, or `None` when the segment is full.
    """

    for h_idx in index.group_holes[group_idx]:
        h_id = index.hole_ids[h_idx]
        if h_id in occupied_holes or h_id in jumper_endpoint_holes:
            continue
        return h_id
    return None


# --------------------------------------------------------------------------
# Per-net routing
# --------------------------------------------------------------------------


def _route_single_net(
    *,
    net: Net,
    endpoint_holes: list[str],
    index: BoardIndex,
    occupied_holes: set[str],
    jumper_endpoint_holes: set[str],
    existing_jumpers: list[Jumper],
    seed: int,
) -> list[Jumper]:
    """Build the jumper list for one net given its resolved endpoints.

    Uses `steiner.greedy_steiner` to build the minimal connecting tree, then constructs
    a `Jumper` for each edge with a two-segment Manhattan path. The path layer flips to
    "upper" when either candidate path crosses at least one existing jumper segment.
    """

    from app.domain.steiner import greedy_steiner

    # De-duplicate endpoints (the prefer-rail pass can hand us two holes that happen to
    # be the same). With <2 unique endpoints, return no jumpers.
    unique_holes: list[str] = []
    seen: set[str] = set()
    for h in endpoint_holes:
        if h in seen:
            continue
        seen.add(h)
        unique_holes.append(h)
    if len(unique_holes) < 2:
        return []

    terminals = [(h_id, index.hole_point(h_id)) for h_id in unique_holes]
    edges = greedy_steiner(terminals, try_all_roots=True)

    color = _net_color(net.net_class, net.id)
    jumpers: list[Jumper] = []
    for i, (a, b) in enumerate(edges):
        # Endpoints must be enabled. Skip if either is not in the index.
        if a not in index.idx or b not in index.idx:
            continue
        if not index.enabled[index.idx[a]] or not index.enabled[index.idx[b]]:
            continue
        path_points, layer = _build_jumper_path(
            a_id=a,
            b_id=b,
            index=index,
            existing_jumpers=existing_jumpers,
            seed=seed,
        )
        estimated_length_mm = round(_polyline_length(path_points) * 1.1 + 10.0, 1)
        jumpers.append(
            Jumper(
                id=f"j-{net.id}-{i}",
                net_id=net.id,
                start_hole_id=a,
                end_hole_id=b,
                path=JumperPath(points=path_points, layer=layer),
                color=color,
                estimated_length_mm=estimated_length_mm,
                locked=False,
            )
        )
    return jumpers


def _build_jumper_path(
    *,
    a_id: str,
    b_id: str,
    index: BoardIndex,
    existing_jumpers: list[Jumper],
    seed: int,
) -> tuple[list[Point], str]:
    """Build a two-segment Manhattan path from `a_id` to `b_id`.

    Returns the path's `Point`s and `"upper"` when either candidate crosses at least one
    existing jumper segment, `"lower"` otherwise. Ties on crossing count go horizontal
    first per main spec §7.4.
    """

    ax, ay = index.hole_point(a_id)
    bx, by = index.hole_point(b_id)
    h_first = [Point(x=ax, y=ay), Point(x=bx, y=ay), Point(x=bx, y=by)]
    v_first = [Point(x=ax, y=ay), Point(x=ax, y=by), Point(x=bx, y=by)]

    existing_segments = _jumper_segments(existing_jumpers)
    h_crossings = _count_segment_crossings(h_first, existing_segments)
    v_crossings = _count_segment_crossings(v_first, existing_segments)

    if h_crossings < v_crossings:
        chosen = h_first
        layer = "upper" if h_crossings >= 1 else "lower"
    elif v_crossings < h_crossings:
        chosen = v_first
        layer = "upper" if v_crossings >= 1 else "lower"
    else:
        # Tie: horizontal first per the spec.
        chosen = h_first
        layer = "upper" if h_crossings >= 1 else "lower"
    return chosen, layer


def _jumper_segments(jumpers: list[Jumper]) -> list[tuple[Point, Point]]:
    """Extract the straight segments of every jumper's path."""

    out: list[tuple[Point, Point]] = []
    for j in jumpers:
        for a, b in pairwise(j.path.points):
            out.append((a, b))
    return out


def _count_segment_crossings(
    path_points: list[Point],
    segments: list[tuple[Point, Point]],
) -> int:
    """Count how many of the `segments` are crossed by any of `path_points`' segments."""

    if len(path_points) < 2:
        return 0
    total = 0
    for a, b in pairwise(path_points):
        for s, t in segments:
            if _segments_cross(a, b, s, t):
                total += 1
    return total


def _segments_cross(
    a: Point,
    b: Point,
    c: Point,
    d: Point,
) -> bool:
    """Strict segment-segment intersection test (collinear overlaps don't count)."""

    def _orient(p: Point, q: Point, r: Point) -> float:
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)

    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)

    s1 = (o1 > 0 and o2 < 0) or (o1 < 0 and o2 > 0)
    s2 = (o3 > 0 and o4 < 0) or (o3 < 0 and o4 > 0)
    return s1 and s2


def _polyline_length(points: list[Point]) -> float:
    total = 0.0
    for a, b in pairwise(points):
        total += math.hypot(b.x - a.x, b.y - a.y)
    return total


def _net_color(net_class: NetClass, net_id: str) -> str:
    if net_class == "ground":
        return "#1a1a1a"
    if net_class == "power":
        return "#d92b2b"
    return _PALETTE[_stable_hash(net_id) % len(_PALETTE)]


def _stable_hash(s: str) -> int:
    """Deterministic 32-bit hash independent of `PYTHONHASHSEED`."""

    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=4).digest(), "big")


# --------------------------------------------------------------------------
# Cost (main spec §7.5)
# --------------------------------------------------------------------------


def _compute_routing_cost(
    *,
    board: BreadboardModel,
    nets: list[Net],
    layout_with_jumpers: Layout,
    unrouted_nets: list[str],
    skip_critical: list[str],
    options: SolverOptions,
) -> float:
    w = options.routing_weights

    total_length_mm = sum(j.estimated_length_mm for j in layout_with_jumpers.jumpers)
    jumper_count = len(layout_with_jumpers.jumpers)
    crossings = _count_layout_crossings(layout_with_jumpers)
    congestion = _layout_congestion_score(layout_with_jumpers)
    avoid_zone_violations = _avoid_zone_violations(board, nets, layout_with_jumpers)

    # Critical violations: count of routed nets whose class is critical AND the caller
    # chose to allow them — the UI still surfaces them per main spec §9.3.
    critical_violations = sum(
        1
        for n in nets
        if n.net_class in _CRITICAL_NET_CLASSES and n.id not in skip_critical and n.id not in unrouted_nets
    )

    unrouted_terminal = len(unrouted_nets)

    return (
        w.get("lengthMm", 0.0) * total_length_mm
        + w.get("jumperCount", 0.0) * jumper_count
        + w.get("crossing", 0.0) * crossings
        + w.get("congestion", 0.0) * congestion
        + w.get("avoidZone", 0.0) * avoid_zone_violations
        + w.get("criticalViolation", 0.0) * critical_violations
        + w.get("unroutedTerminal", 0.0) * unrouted_terminal
    )


def _count_layout_crossings(layout: Layout) -> int:
    """Count geometric crossings between jumper-path segments (O(n^2) over segments)."""

    segs: list[tuple[Point, Point]] = []
    for j in layout.jumpers:
        for a, b in pairwise(j.path.points):
            segs.append((a, b))

    crossings = 0
    for i in range(len(segs)):
        for k in range(i + 1, len(segs)):
            if _segments_cross(segs[i][0], segs[i][1], segs[k][0], segs[k][1]):
                crossings += 1
    return crossings


def _layout_congestion_score(layout: Layout) -> float:
    """Sum of `max(0, jumper_count_per_column - 4) ** 2` across all columns.

    Squared penalty matches the spirit of main spec §7.5 ("per column bucket > 6 → cost
    spike"). Returns a float score.
    """

    counts: dict[int, int] = {}
    for j in layout.jumpers:
        for ep in (j.start_hole_id, j.end_hole_id):
            col = _column_of_hole(ep)
            if col is not None:
                counts[col] = counts.get(col, 0) + 1
    return float(sum(max(0, c - 4) ** 2 for c in counts.values()))


def _column_of_hole(hole_id: str) -> int | None:
    import re

    m = re.match(r"^([a-j])(\d+)$", hole_id)
    if m is not None:
        return int(m.group(2))
    m = re.match(r"^rail-(?P<line>.+)-(?P<seq>\d+)$", hole_id)
    if m is not None:
        return int(m.group("seq"))
    return None


def _avoid_zone_violations(
    board: BreadboardModel,
    nets: list[Net],
    layout: Layout,
) -> int:
    """Count of jumper-path vertices that fall inside an avoid-zone of the jumper's net.

    We use a simple bounding-box test on the zone polygon (`min/max x and y`) as the
    cheaper alternative to a full ray-cast point-in-polygon — the zones are rectangular
    on the canonical 400-tie-point board and the spec only needs an upper-bound cost.
    Documented choice: bounding-box intersection, not exact point-in-polygon.
    """

    zones_by_id: dict[str, list[Point]] = {z.id: z.polygon for z in board.zones}
    avoid_zones_by_net: dict[str, list[str]] = {}
    for n in nets:
        for c in n.constraints:
            if getattr(c, "type", None) == "avoid-zone":
                zid = getattr(c, "zone_id", None)
                if zid is not None:
                    avoid_zones_by_net.setdefault(n.id, []).append(zid)

    if not avoid_zones_by_net:
        return 0

    violations = 0
    for j in layout.jumpers:
        zones = avoid_zones_by_net.get(j.net_id, [])
        if not zones:
            continue
        for zid in zones:
            polygon = zones_by_id.get(zid, [])
            if len(polygon) < 3:
                continue
            min_x = min(p.x for p in polygon)
            max_x = max(p.x for p in polygon)
            min_y = min(p.y for p in polygon)
            max_y = max(p.y for p in polygon)
            for pt in j.path.points:
                if min_x <= pt.x <= max_x and min_y <= pt.y <= max_y:
                    violations += 1
                    break  # one violation per (jumper, zone) pair is enough
    return violations


# --------------------------------------------------------------------------
# Rip-up / reroute (main spec §7.6)
# --------------------------------------------------------------------------


def _rip_up(
    *,
    target_net_id: str,
    nets: list[Net],
    placements: list[ComponentPlacement],
    index: BoardIndex,
    preserved_jumpers: list[Jumper],
    new_jumpers: list[Jumper],
    connectivity: Connectivity,
    max_remove: int,
    rng: random.Random,
) -> list[Jumper]:
    """Return up to `max_remove` non-locked jumpers to remove before re-routing `target_net_id`.

    Selection rule: non-locked jumpers in the working set whose endpoints sit within 3
    columns of any pin hole of the failing net, sorted by `estimated_length_mm`
    descending so longer (less essential) jumpers are removed first. Skips the target
    net's own jumpers — those get re-created by `_reroute_subset`.
    """

    placements_by_ref = {p.component_ref: p for p in placements}
    pin_cols: set[int] = set()
    target = next((n for n in nets if n.id == target_net_id), None)
    if target is not None:
        for pin_ref in target.pins:
            placement = placements_by_ref.get(pin_ref.component_ref)
            if placement is None:
                continue
            hole_id = placement.pin_holes.get(pin_ref.pin)
            if hole_id is None:
                continue
            col = _column_of_hole(hole_id)
            if col is not None:
                pin_cols.add(col)

    candidates: list[Jumper] = []
    for j in new_jumpers:
        if j.locked:
            continue
        if j.net_id == target_net_id:
            continue
        ok = False
        for ep in (j.start_hole_id, j.end_hole_id):
            col = _column_of_hole(ep)
            if col is not None and pin_cols and any(abs(col - pc) <= 3 for pc in pin_cols):
                ok = True
                break
        if ok:
            candidates.append(j)

    candidates.sort(key=lambda j: -j.estimated_length_mm)
    # If no column-overlap candidates, fall back to most-recently-added (preserved order
    # is by creation, so taking the tail gives "most recent").
    if not candidates:
        candidates = [j for j in new_jumpers if not j.locked and j.net_id != target_net_id]
        candidates = candidates[-max_remove:] if len(candidates) > max_remove else candidates
    return candidates[:max_remove]


def _reroute_subset(
    *,
    affected_nets: list[Net],
    other_nets: list[Net],
    nets: list[Net],
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    layout: Layout,
    preserved_jumpers: list[Jumper],
    occupied_holes: set[str],
    jumper_endpoint_holes: set[str],
    existing_new_jumpers: list[Jumper],
    options: SolverOptions,
    deadline_monotonic: float | None,
    start_monotonic: float,
    skip_critical: list[str],
) -> list[Jumper]:
    """Re-route the affected nets on top of the existing (non-removed) jumper set.

    Returns the new working set of new jumpers (preserved + newly re-routed + the
    non-affected survivors).
    """

    # Start by keeping the jumpers that belong to no affected net.
    affected_net_ids = {n.id for n in affected_nets}
    survivors = [j for j in existing_new_jumpers if j.net_id not in affected_net_ids]

    # Build a fresh occupancy view from survivors + placements.
    occupied = set(occupied_holes)
    for j in survivors:
        occupied.discard(j.start_hole_id)
        occupied.discard(j.end_hole_id)
    endpoints_used = {j.start_hole_id for j in survivors} | {j.end_hole_id for j in survivors}

    # Reconnect preserved jumpers' endpoints to the occupied set (so rail pass doesn't
    # land a new jumper on a locked manual endpoint).
    for j in preserved_jumpers:
        endpoints_used.add(j.start_hole_id)
        endpoints_used.add(j.end_hole_id)

    fresh_connectivity = _build_layout_connectivity(
        index=index,
        footprints=footprints,
        components=components,
        placements=layout.placements,
        preserved_jumpers=preserved_jumpers,
        new_jumpers=survivors,
        manual_links=layout.manual_electrical_links,
    )

    rail_assignment: dict[int, str] = {}

    re_routed: list[Jumper] = []
    for net in affected_nets:
        _check_deadline(start_monotonic, deadline_monotonic)
        if net.net_class in _CRITICAL_NET_CLASSES and not options.allow_critical_net_classes:
            continue
        endpoint_holes, skip_reason = _resolve_net_endpoints(
            net=net,
            index=index,
            components=components,
            layout=layout,
            occupied_holes=occupied,
            jumper_endpoint_holes=endpoints_used,
            rail_assignment=rail_assignment,
            connectivity=fresh_connectivity,
            new_jumpers=survivors + re_routed,
        )
        if endpoint_holes is None or len(endpoint_holes) < 2:
            continue
        if skip_reason is not None:
            continue
        jumpers = _route_single_net(
            net=net,
            endpoint_holes=endpoint_holes,
            index=index,
            occupied_holes=occupied,
            jumper_endpoint_holes=endpoints_used,
            existing_jumpers=survivors + re_routed,
            seed=options.seed,
        )
        for j in jumpers:
            endpoints_used.add(j.start_hole_id)
            endpoints_used.add(j.end_hole_id)
        re_routed.extend(jumpers)

    return survivors + re_routed


# --------------------------------------------------------------------------
# Connectivity rebuild + open-net detection
# --------------------------------------------------------------------------


def _build_layout_connectivity(
    *,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    placements: list[ComponentPlacement],
    preserved_jumpers: list[Jumper],
    new_jumpers: list[Jumper],
    manual_links: list[ManualLink],
) -> Connectivity:
    """Build a fresh `Connectivity` for a layout that is `placements + preserved + new`."""

    layout = Layout(
        version=1,
        board_id=index.board_id,
        placements=list(placements),
        jumpers=list(preserved_jumpers) + list(new_jumpers),
        manual_electrical_links=list(manual_links),
    )
    return build_connectivity(index, footprints, components, layout)


def _open_nets(
    nets: list[Net],
    placements: list[ComponentPlacement],
    index: BoardIndex,
    connectivity: Connectivity,
) -> set[str]:
    """Return net ids whose placed pins do NOT all share one DSU root."""

    placements_by_ref = {p.component_ref: p for p in placements}
    open_nets: set[str] = set()
    for net in nets:
        roots: set[int] = set()
        count = 0
        for pin_ref in net.pins:
            placement = placements_by_ref.get(pin_ref.component_ref)
            if placement is None:
                continue
            h_id = placement.pin_holes.get(pin_ref.pin)
            if h_id is None:
                continue
            r = connectivity.root_of_hole(h_id)
            if r < 0:
                continue
            roots.add(r)
            count += 1
        if count < 2:
            continue
        if len(roots) > 1:
            open_nets.add(net.id)
    return open_nets


def _check_deadline(start: float, deadline_monotonic: float | None) -> None:
    if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
        raise SolverTimeout("routing exceeded deadline")
