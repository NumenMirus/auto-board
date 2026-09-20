"""Electrical connectivity built from a board model and a layout.

`build_connectivity` returns a small frozen view of the electrical equipotentials defined
by the board's intrinsic groups (`ElectricalGroup`s), the components' internal pin pairs,
the jumpers in the layout, and any explicit `ManualLink`s. The result wraps a
`DisjointSetUnion` over hole indices and exposes `root_of_hole` / `groups` for downstream
checks (the validator, the renderer, the future Steiner router).

Per the main spec (§16.4), components are **not** conductors beyond their declared
`internal_connections`. A resistor on two distinct nets therefore does not short them;
a tact switch *does* because it declares `[["1","2"],["3","4"]]` as internal pairs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.dsu import DisjointSetUnion

if TYPE_CHECKING:
    from app.domain.index import BoardIndex
    from app.domain.models import BreadboardFootprint, Component, Layout


__all__ = ["Connectivity", "build_connectivity"]


@dataclass(frozen=True)
class Connectivity:
    """Electrical equipotentials over the board's holes.

    `dsu` is indexed by hole index (the same index used by `BoardIndex.hole_ids` /
    `BoardIndex.idx`). `root_of_hole` and `groups` are the two convenient lookups used by
    validators and routers.

    The private `_index` and `_hole_ids` carry the `BoardIndex` view used to translate
    between hole ids and integer indices; they are set once at construction by
    `build_connectivity` and never mutated.
    """

    board_id: str
    dsu: DisjointSetUnion
    _index: BoardIndex = field(repr=False, compare=False)
    _hole_ids: tuple[str, ...] = field(repr=False, compare=False)

    def root_of_hole(self, hole_id: str) -> int:
        """Return the DSU root of the hole, or `-1` if the id is unknown.

        The sentinel lets validation paths probe arbitrary ids (a bad jumper endpoint, a
        stale pin mapping) without raising `KeyError`; callers that need to distinguish
        "unknown" from "known but alone" can compare against `BoardIndex.idx` directly.
        """
        idx = self._index.idx.get(hole_id)
        if idx is None:
            return -1
        return self.dsu.find(idx)

    def root_of_idx(self, hole_idx: int) -> int:
        """Return the DSU root of the hole at the given index."""
        return self.dsu.find(hole_idx)

    def groups(self) -> dict[int, list[str]]:
        """Return a `root -> list[hole_id]` map, in ascending hole-id order per group.

        The dict's iteration order is sorted by root ascending; member order within each
        group is sorted by hole id ascending. Output is therefore deterministic and safe
        to compare across runs.
        """
        result: dict[int, list[str]] = {}
        for hole_idx, hole_id in enumerate(self._hole_ids):
            root = self.dsu.find(hole_idx)
            result.setdefault(root, []).append(hole_id)
        for member_ids in result.values():
            member_ids.sort()
        return dict(sorted(result.items()))


def build_connectivity(
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    layout: Layout,
) -> Connectivity:
    """Build the connectivity DSU from a board index, footprints, components, and a layout.

    `footprints` is keyed by `footprint_id` (the same convention as the global footprint
    registry, `app.domain.footprints.registry.FOOTPRINTS`) — callers pass the registry, or a
    subset of it, unmodified. `components` resolves each placement's `component_ref` to its
    `footprint_id` so this function can look up the right `BreadboardFootprint` itself; no
    caller needs to pre-translate the registry into a by-ref mapping.

    Steps, in order:

    1. Seed the DSU with one element per hole in `index.hole_ids`.
    2. Union every hole within each `ElectricalGroup` already recorded in the board
       (the tie-point columns and the rail groups).
    3. For each `ComponentPlacement` in the layout, union the pin holes connected by the
       placement's footprint `internal_connections` (list of pin-id pairs) via the
       placement's `pin_holes` mapping.
    4. Union both endpoints of every `Jumper` in `layout.jumpers`.
    5. Union both holes of every `ManualLink` in `layout.manual_electrical_links`.
    """

    hole_ids = index.hole_ids
    dsu = DisjointSetUnion(len(hole_ids))

    footprint_id_by_ref: dict[str, str] = {c.ref: c.footprint_id for c in components}

    # (a) groups: union every member of each electrical group.
    for member_idxs in index.group_holes:
        _union_chain(dsu, member_idxs)

    # (b) placements: only declared `internal_connections` are conductors.
    for placement in layout.placements:
        footprint_id = footprint_id_by_ref.get(placement.component_ref)
        footprint = footprints.get(footprint_id) if footprint_id is not None else None
        # Missing component/footprint is silently skipped here — the validator surfaces
        # `UNKNOWN_FOOTPRINT` / `UNPLACED_COMPONENT` separately for that condition.
        if footprint is None:
            continue
        pin_holes = placement.pin_holes
        for pair in footprint.internal_connections:
            if len(pair) != 2:
                continue
            a_pin, b_pin = pair
            a_hole = pin_holes.get(a_pin)
            b_hole = pin_holes.get(b_pin)
            if a_hole is None or b_hole is None:
                continue
            _union_pair(dsu, index, a_hole, b_hole)

    # (c) jumpers.
    for jumper in layout.jumpers:
        _union_pair(dsu, index, jumper.start_hole_id, jumper.end_hole_id)

    # (d) manual links.
    for link in layout.manual_electrical_links:
        _union_pair(dsu, index, link.hole_a, link.hole_b)

    return Connectivity(
        board_id=index.board_id,
        dsu=dsu,
        _index=index,
        _hole_ids=hole_ids,
    )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _union_pair(dsu: DisjointSetUnion, index: BoardIndex, a: str, b: str) -> None:
    """Union the two hole ids, tolerating unknown or duplicate ids as no-ops."""
    if a == b:
        return
    ai = index.idx.get(a)
    bi = index.idx.get(b)
    if ai is None or bi is None:
        return
    dsu.union(ai, bi)


def _union_chain(dsu: DisjointSetUnion, idxs: tuple[int, ...] | list[int]) -> None:
    """Union the first element with every other element in `idxs`."""
    if len(idxs) < 2:
        return
    head = idxs[0]
    for other in idxs[1:]:
        dsu.union(head, other)
