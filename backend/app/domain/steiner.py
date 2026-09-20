"""Greedy Steiner tree over a set of pin terminals.

`route.py` resolves each net pin to a specific board hole (either the pin's own hole for a
direct net or a free rail hole for a `prefer-rail` net); it then asks this module for the
minimum-cost tree that connects all those endpoints with simple (a, b) jumper edges.

The algorithm follows main spec §7.3: starting from a chosen root terminal, repeatedly
find the unconnected terminal with the smallest Manhattan distance to any already-connected
terminal and add that edge. When `try_all_roots` is True and the net is small enough
(`len(terminals) <= 6`), each terminal is tried as the root and the tree with the lowest
total Manhattan length wins. Ties on the "closest unconnected terminal" step are broken
by hole-id ascending, which gives byte-deterministic output across runs.

This module is pure: no I/O, no globals, no randomness. The output is a list of
`(hole_id_a, hole_id_b)` pairs. Empty for 0- or 1-terminal inputs.
"""

from __future__ import annotations

import math

__all__ = ["greedy_steiner"]


def greedy_steiner(
    terminals: list[tuple[str, tuple[float, float]]],
    try_all_roots: bool = True,
) -> list[tuple[str, str]]:
    """Build a greedy Steiner tree connecting `terminals`.

    Each terminal is `(hole_id, (x_mm, y_mm))`. The return value is the list of
    `(hole_id_a, hole_id_b)` edges forming the tree. Manhattan distance is used as the
    edge-cost metric, matching the wiring-cost basis in main spec §7.5.

    With `try_all_roots=True` and at most six terminals, every terminal is tried as the
    root and the tree with the lowest total length wins; otherwise `terminals[0]` is the
    fixed root. Holes are deduplicated by id before processing so duplicate terminals
    (two pins of the same net landing on the same tie-point column) collapse cleanly.
    """

    # Deduplicate by hole id, keeping the first-seen coordinate for stability.
    seen: dict[str, tuple[float, float]] = {}
    for hole_id, point in terminals:
        seen.setdefault(hole_id, point)
    unique = sorted(seen.items())  # sorted by hole id ascending for determinism

    if len(unique) <= 1:
        return []

    # Build the tree for every candidate root when cheap, else just the first id.
    candidates: list[str] = (
        [hole_id for hole_id, _ in unique] if try_all_roots and len(unique) <= 6 else [unique[0][0]]
    )

    best_edges: list[tuple[str, str]] = []
    best_length = math.inf

    for root in candidates:
        edges, total = _grow_tree(unique, root)
        if total < best_length:
            best_length = total
            best_edges = edges

    return best_edges


def _grow_tree(
    unique: list[tuple[str, tuple[float, float]]],
    root: str,
) -> tuple[list[tuple[str, str]], float]:
    """Grow a Steiner tree from `root` and return `(edges, total_manhattan_length)`."""

    point_of: dict[str, tuple[float, float]] = {hole_id: point for hole_id, point in unique}
    connected: set[str] = {root}
    edges: list[tuple[str, str]] = []
    total_length = 0.0

    # The greedy loop runs at most `len(unique) - 1` times because each iteration adds
    # exactly one previously-unconnected terminal.
    while len(connected) < len(unique):
        # Find the unconnected terminal closest (by Manhattan distance) to any connected
        # terminal. Tie-break by hole id ascending so the output is deterministic.
        best_target: str | None = None
        best_source: str | None = None
        best_dist = math.inf
        for hole_id, point in unique:
            if hole_id in connected:
                continue
            for c_id in connected:
                c_point = point_of[c_id]
                d = abs(point[0] - c_point[0]) + abs(point[1] - c_point[1])
                if d < best_dist or (d == best_dist and (best_target is None or hole_id < best_target)):
                    best_dist = d
                    best_target = hole_id
                    best_source = c_id
        assert best_target is not None and best_source is not None  # loop invariant
        edges.append((best_source, best_target))
        connected.add(best_target)
        total_length += best_dist

    return edges, total_length
