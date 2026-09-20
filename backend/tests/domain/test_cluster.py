"""Tests for :mod:`app.domain.cluster`.

Verifies the assignment's rule list on hand-crafted fixtures:

- A DIP-14 U1 plus a 2-pin cap C1 sharing power+ground nets with U1 lands C1 in U1's
  cluster.
- An unrelated resistor R5 (no shared net with U1) becomes its own singleton cluster.
- TO-92 transistors become anchors when joined by an axial resistor/diode.
- Singletons sort by cluster id ascending.
"""

from __future__ import annotations

import pytest

from app.domain.cluster import Cluster, build_clusters
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.models import Component, Net, PinRef

pytest_plugins: list[str] = []


def _comps(*items: tuple[str, str, list[str]]) -> list[Component]:
    return [Component(ref=r, footprint_id=fp, pins=pins, value=None) for r, fp, pins in items]


def test_dip14_with_bypass_cap_joins_u1_cluster() -> None:
    """Cap C1 shares VCC and GND with U1's pins → C1 in U1's cluster."""
    components = _comps(
        ("U1", "DIP-14", [str(i) for i in range(1, 15)]),
        ("C1", "RADIAL-CAP-2P", ["1", "2"]),
        ("R5", "AXIAL-R", ["1", "2"]),
    )
    nets = [
        Net(
            id="N_PWR",
            name="VCC",
            pins=[PinRef(component_ref="U1", pin="14"), PinRef(component_ref="C1", pin="1")],
            net_class="power",
            priority=1,
        ),
        Net(
            id="N_GND",
            name="GND",
            pins=[PinRef(component_ref="U1", pin="7"), PinRef(component_ref="C1", pin="2")],
            net_class="ground",
            priority=1,
        ),
        Net(
            id="N_R5A",
            name="R5A",
            pins=[PinRef(component_ref="R5", pin="1")],
            net_class="digital",
            priority=1,
        ),
        Net(
            id="N_R5B",
            name="R5B",
            pins=[PinRef(component_ref="R5", pin="2")],
            net_class="digital",
            priority=1,
        ),
    ]
    clusters = build_clusters(components, nets, FOOTPRINTS)
    by_id = {c.id: c for c in clusters}

    assert "U1" in by_id, "U1 cluster must exist"
    assert "C1" in {m for m in by_id["U1"].member_refs}, (
        "C1 must be a member of U1's cluster because it shares VCC and GND with U1"
    )

    assert "R5" in by_id
    assert by_id["R5"].member_refs == ("R5",), "R5 must be a singleton (no shared nets with U1)"


def test_singletons_get_their_own_cluster() -> None:
    """Components with no shared net each become their own singleton cluster."""
    components = _comps(
        ("R1", "AXIAL-R", ["1", "2"]),
        ("R2", "AXIAL-R", ["1", "2"]),
    )
    nets: list[Net] = []
    clusters = build_clusters(components, nets, FOOTPRINTS)
    assert {c.id for c in clusters} == {"R1", "R2"}
    for c in clusters:
        assert c.member_refs == (c.id,)


def test_clusters_sorted_by_id() -> None:
    """Returned cluster list is sorted ascending by cluster id."""
    components = _comps(
        ("Z1", "AXIAL-R", ["1", "2"]),
        ("A1", "AXIAL-R", ["1", "2"]),
        ("M1", "AXIAL-R", ["1", "2"]),
    )
    clusters = build_clusters(components, [], FOOTPRINTS)
    ids = [c.id for c in clusters]
    assert ids == sorted(ids)


def test_resistor_on_to92_net_joins_to92_cluster() -> None:
    """An AXIAL-R sharing a net with a TO-92 joins the TO-92's singleton cluster."""
    components = _comps(
        ("Q1", "TO-92", ["1", "2", "3"]),
        ("R1", "AXIAL-R", ["1", "2"]),
    )
    nets = [
        Net(
            id="N_BASE",
            name="BASE",
            pins=[PinRef(component_ref="Q1", pin="2"), PinRef(component_ref="R1", pin="1")],
            net_class="analog-sensitive",
            priority=1,
        ),
        Net(
            id="N_R1B",
            name="R1B",
            pins=[PinRef(component_ref="R1", pin="2")],
            net_class="analog-sensitive",
            priority=1,
        ),
    ]
    clusters = build_clusters(components, nets, FOOTPRINTS)
    by_id = {c.id: c for c in clusters}
    assert "Q1" in by_id
    assert "R1" in set(by_id["Q1"].member_refs), "R1 should join Q1's TO-92 cluster"


def test_cluster_dataclass_is_frozen() -> None:
    """Cluster must be a frozen dataclass (per the spec)."""
    c = Cluster(id="U1", anchor_ref="U1", member_refs=("U1",))
    with pytest.raises((AttributeError, TypeError)):
        c.id = "X"  # type: ignore[misc]


def test_clock_net_pulls_member_into_dip_cluster() -> None:
    """A component on a 'clock' net that shares it with a DIP anchor joins that anchor."""
    components = _comps(
        ("U1", "DIP-8", [str(i) for i in range(1, 9)]),
        ("R7", "AXIAL-R", ["1", "2"]),
    )
    nets = [
        Net(
            id="N_CLK",
            name="CLK",
            pins=[PinRef(component_ref="U1", pin="1"), PinRef(component_ref="R7", pin="1")],
            net_class="clock",
            priority=1,
        ),
        Net(
            id="N_R7B",
            name="R7B",
            pins=[PinRef(component_ref="R7", pin="2")],
            net_class="clock",
            priority=1,
        ),
    ]
    clusters = build_clusters(components, nets, FOOTPRINTS)
    by_id = {c.id: c for c in clusters}
    assert "U1" in by_id
    assert "R7" in set(by_id["U1"].member_refs), "R7 shares a clock net with U1 → should join U1's cluster"


def test_dip_anchor_ref_is_itself() -> None:
    """The DIP's own anchor_ref must be itself."""
    components = _comps(("U1", "DIP-14", [str(i) for i in range(1, 15)]))
    clusters = build_clusters(components, [], FOOTPRINTS)
    assert clusters[0].anchor_ref == "U1"
    assert clusters[0].id == "U1"
