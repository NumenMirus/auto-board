"""Array-based disjoint-set union (union-find) over integer indices.

Used by the connectivity and validation layers to model the breadboard's electrical
equipotentials. The implementation is intentionally minimal — no per-element objects, just
two flat arrays sized to the element count — so it stays cheap on a 400-hole board and
behaves well as the element count grows into the thousands.

Operations:
* `find(i)` — return the root of `i`, with path halving.
* `union(i, j)` — merge the sets of `i` and `j` using union by size (smaller tree root
  attached to the larger one).
* `roots()` — return one representative id per set, in ascending order.

The class is not frozen; callers are expected to treat instances as ephemeral.
"""

from __future__ import annotations

__all__ = ["DisjointSetUnion"]


class DisjointSetUnion:
    """Union-find over a fixed population of integer indices `[0, n)`."""

    __slots__ = ("_count", "_parent", "_size")

    def __init__(self, n: int) -> None:
        if n < 0:
            raise ValueError(f"DSU size must be non-negative, got {n}")
        self._parent: list[int] = list(range(n))
        # `_size[root]` holds the size of the tree rooted at `root`; non-root entries
        # are unused.
        self._size: list[int] = [1] * n
        self._count: int = n

    def __len__(self) -> int:
        return len(self._parent)

    @property
    def n_sets(self) -> int:
        """Number of distinct sets currently in the structure."""
        return self._count

    def find(self, i: int) -> int:
        """Return the root of element `i`, applying path halving on the way."""
        parent = self._parent
        # Iterative path halving: every other node on the path gets its grandparent as
        # its parent, flattening the tree without recursion.
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        """Merge the sets containing `i` and `j`. No-op when already in the same set."""
        ri = self.find(i)
        rj = self.find(j)
        if ri == rj:
            return
        # Union by size: attach the smaller tree under the larger root.
        if self._size[ri] < self._size[rj]:
            ri, rj = rj, ri
        self._parent[rj] = ri
        self._size[ri] += self._size[rj]
        self._count -= 1

    def connected(self, i: int, j: int) -> bool:
        """True iff `i` and `j` are in the same set."""
        return self.find(i) == self.find(j)

    def roots(self) -> list[int]:
        """Return one representative id per set, sorted ascending.

        Distinct roots are unique by construction (each root is its own parent), so the
        result is a deterministic ascending list rather than insertion-order dependent.
        """
        parent = self._parent
        return sorted(i for i in range(len(parent)) if parent[i] == i)
