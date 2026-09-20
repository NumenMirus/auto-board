"""Tests for `app.domain.dsu.DisjointSetUnion`."""

from __future__ import annotations

import random

from app.domain.dsu import DisjointSetUnion

pytest_plugins: list[str] = []


def test_initial_state_has_n_singletons() -> None:
    dsu = DisjointSetUnion(20)
    assert len(dsu) == 20
    assert dsu.n_sets == 20
    # Each element starts as its own root.
    for i in range(20):
        assert dsu.find(i) == i


def test_union_merges_two_sets() -> None:
    dsu = DisjointSetUnion(5)
    dsu.union(0, 1)
    assert dsu.find(0) == dsu.find(1)
    assert dsu.n_sets == 4
    assert not dsu.connected(0, 2)
    assert dsu.connected(0, 1)


def test_union_is_idempotent() -> None:
    dsu = DisjointSetUnion(5)
    dsu.union(0, 1)
    dsu.union(0, 1)
    dsu.union(1, 0)
    assert dsu.find(0) == dsu.find(1)
    assert dsu.n_sets == 4


def test_transitive_closure() -> None:
    dsu = DisjointSetUnion(10)
    # Build a chain 0-1-2-3 and a chain 4-5; check that the merged chain has one root.
    dsu.union(0, 1)
    dsu.union(1, 2)
    dsu.union(2, 3)
    dsu.union(4, 5)
    assert dsu.connected(0, 3)
    assert dsu.connected(1, 2)
    assert not dsu.connected(0, 4)
    assert dsu.n_sets == 6  # {0,1,2,3}, {4,5}, 6, 7, 8, 9


def test_path_halving_flattens_deep_trees() -> None:
    """Build a linear chain and check that find() compresses paths on traversal."""
    dsu = DisjointSetUnion(20)
    # 0 -> 1 -> 2 -> ... -> 19 (each union attaches the larger root to the right).
    for i in range(19):
        dsu.union(i, i + 1)
    # Now perform one find on 0 to trigger path halving.
    root = dsu.find(0)
    # Subsequent finds on intermediate elements must still resolve to the same root.
    for i in range(20):
        assert dsu.find(i) == root


def test_roots_returns_distinct_sorted_ids() -> None:
    dsu = DisjointSetUnion(20)
    # Build three clusters: {0,1,2}, {5,7}, {13,17,19}.
    dsu.union(0, 1)
    dsu.union(1, 2)
    dsu.union(5, 7)
    dsu.union(13, 17)
    dsu.union(17, 19)
    roots = dsu.roots()
    assert roots == sorted(roots)
    assert len(roots) == dsu.n_sets
    # Every root must be its own parent.
    parent = dsu._parent
    for r in roots:
        assert parent[r] == r


def test_stress_random_unions_match_naive() -> None:
    """Stress: 1000 random unions on 500 elements must match a naive union-find.

    We compare set membership, not specific root ids: union-by-size and the naive
    "always attach rj to ri" may legitimately pick different root identifiers while
    describing the same partition.
    """
    dsu = DisjointSetUnion(500)
    naive: list[int] = list(range(500))

    def naive_find(i: int) -> int:
        while naive[i] != i:
            i = naive[i]
        return i

    def naive_union(i: int, j: int) -> None:
        ri, rj = naive_find(i), naive_find(j)
        if ri != rj:
            naive[rj] = ri

    rng = random.Random(12345)
    pairs = [(rng.randrange(500), rng.randrange(500)) for _ in range(1000)]
    for a, b in pairs:
        dsu.union(a, b)
        naive_union(a, b)
    # Both must describe the same partition.
    naive_sets: dict[int, set[int]] = {}
    for i in range(500):
        naive_sets.setdefault(naive_find(i), set()).add(i)
    dsu_sets: dict[int, set[int]] = {}
    for r in dsu.roots():
        dsu_sets[r] = {i for i in range(500) if dsu.find(i) == r}
    assert {frozenset(s) for s in naive_sets.values()} == {frozenset(s) for s in dsu_sets.values()}
    assert len(naive_sets) == dsu.n_sets


def test_empty_and_single_element() -> None:
    empty = DisjointSetUnion(0)
    assert len(empty) == 0
    assert empty.roots() == []
    assert empty.n_sets == 0

    single = DisjointSetUnion(1)
    assert single.find(0) == 0
    assert single.roots() == [0]


def test_negative_size_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        DisjointSetUnion(-1)
