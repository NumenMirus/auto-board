"""Tests for `app.domain.validate.validate_layout`.

All cases build either a tiny synthetic board (when a 30x10 grid is overkill) or the real
half-size 400-tie-point board from `app.domain.boards.half400`. They share helpers for
placing a 1-pin "header" style component and wiring nets to its pin, since that's the
smallest unit of work the validator needs to evaluate a placed pin.
"""

from __future__ import annotations

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Diagnostic,
    FootprintGeometry,
    Jumper,
    JumperPath,
    Layout,
    LayoutScore,
    Net,
    PinRef,
    PlacementRuleMainArea,
    Point,
    RelativeHole,
    SolverOptions,
)
from app.domain.validate import validate_layout

pytest_plugins: list[str] = []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _board_and_index() -> tuple[BreadboardModel, BoardIndex]:
    board = build_half400(split_rails=True)
    return board, BoardIndex.build(board)


def _make_header_component(ref: str, anchor: str, span: int = 1) -> tuple[Component, ComponentPlacement]:
    """Return a 2-pin HEADER component + its placement, anchor at `anchor`, span=1."""
    footprint_id = "HEADER-1x2"
    component = Component(ref=ref, value=None, footprint_id=footprint_id, pins=["1", "2"])
    # Anchor at column `anchor` (e.g. "a5"); pin 2 is `span` columns over.
    row = anchor[0]
    col_a = int(anchor[1:])
    col_b = col_a + span
    placement = ComponentPlacement(
        component_ref=ref,
        anchor_hole_id=anchor,
        orientation=0,
        span=span,
        pin_holes={"1": anchor, "2": f"{row}{col_b}"},
        occupied_hole_ids=[anchor, f"{row}{col_b}"],
    )
    return component, placement


def _make_jumper(
    jumper_id: str,
    net_id: str,
    start: str,
    end: str,
    *,
    length_mm: float = 12.7,
) -> Jumper:
    return Jumper(
        id=jumper_id,
        net_id=net_id,
        start_hole_id=start,
        end_hole_id=end,
        path=JumperPath(points=[Point(x=0, y=0), Point(x=length_mm, y=0)], layer="lower"),
        color=None,
        estimated_length_mm=length_mm,
        locked=False,
    )


def _make_two_pin_net(
    net_id: str,
    ref_a: str,
    ref_b: str,
    net_class: str = "digital",
) -> Net:
    return Net(
        id=net_id,
        name=net_id,
        pins=[PinRef(component_ref=ref_a, pin="1"), PinRef(component_ref=ref_b, pin="1")],
        net_class=net_class,
        priority=0,
    )


def _run(
    components: list[Component],
    nets: list[Net],
    placements: list[ComponentPlacement],
    jumpers: list[Jumper],
) -> tuple[list[Diagnostic], LayoutScore]:
    board, index = _board_and_index()
    layout = Layout(
        version=1,
        board_id=board.id,
        placements=placements,
        jumpers=jumpers,
        manual_electrical_links=[],
    )
    options = SolverOptions()
    return validate_layout(board, index, FOOTPRINTS, components, nets, layout, options)


def _diag_codes(diags: list[Diagnostic]) -> list[str]:
    return [d.code for d in diags]


# --------------------------------------------------------------------------
# (a) 2-pin net across two groups + one bridging jumper → zero errors, net completed.
# --------------------------------------------------------------------------


def test_two_pin_net_across_two_groups_with_bridging_jumper_has_zero_errors() -> None:
    c1, p1 = _make_header_component("J1", "a5")
    c2, p2 = _make_header_component("J2", "a10")
    net = _make_two_pin_net("N1", "J1", "J2")
    # Jumper directly bridges the two pin holes.
    jumper = _make_jumper("W1", "N1", "a5", "a10")

    diags, score = _run([c1, c2], [net], [p1, p2], [jumper])

    errors = [d for d in diags if d.severity == "error"]
    assert errors == [], f"expected zero errors, got {[d.message for d in errors]}"
    assert score.error_count == 0
    assert score.nets_completed == 1
    assert score.nets_total == 1


# --------------------------------------------------------------------------
# (b) Same scenario minus the jumper → exactly one NET_OPEN.
# --------------------------------------------------------------------------


def test_two_pin_net_across_two_groups_without_jumper_has_one_net_open() -> None:
    c1, p1 = _make_header_component("J1", "a5")
    c2, p2 = _make_header_component("J2", "a10")
    net = _make_two_pin_net("N1", "J1", "J2")

    diags, _ = _run([c1, c2], [net], [p1, p2], [])

    assert _diag_codes(diags) == ["NET_OPEN"]
    assert diags[0].related_net_ids == ["N1"]
    # Minority = J1.1 (a5) since a10 is the bridge target… no jumper exists, so we just
    # check the diagnostic reports *some* minority hole id.
    assert len(diags[0].related_net_ids) == 1


# --------------------------------------------------------------------------
# (c) Wrong jumper bridging two different nets' groups → exactly one SHORT_BETWEEN_NETS.
# --------------------------------------------------------------------------


def test_extra_jumper_bridging_two_nets_produces_one_short() -> None:
    # Two components on column 5: pins at a5/c5 (same group tp-l-5) and a6/c6 (group tp-l-6).
    c1, p1 = _make_header_component("J1", "a5")
    c2, p2 = _make_header_component("J2", "c5")
    # Net A = J1.1 (a5) + J2.1 (c5): both in tp-l-5.
    net_a = _make_two_pin_net("NA", "J1", "J2")
    # Net B = J1.2 (a6) + J2.2 (c6): both in tp-l-6.
    net_b = Net(
        id="NB",
        name="NB",
        pins=[PinRef(component_ref="J1", pin="2"), PinRef(component_ref="J2", pin="2")],
        net_class="digital",
        priority=0,
    )
    # Stray jumper a5 -> a6 bridges net A and net B → SHORT_BETWEEN_NETS.
    stray = _make_jumper("W_BAD", "NA", "a5", "a6", length_mm=2.54)

    diags, _ = _run([c1, c2], [net_a, net_b], [p1, p2], [stray])

    shorts = [d for d in diags if d.code == "SHORT_BETWEEN_NETS"]
    assert len(shorts) == 1, f"expected one SHORT_BETWEEN_NETS, got {len(shorts)}"
    assert set(shorts[0].related_net_ids) == {"NA", "NB"}


# --------------------------------------------------------------------------
# (d) 2-pin footprint with no internal_connections: its two pins on two different
# nets → no short.
# --------------------------------------------------------------------------


def test_two_pin_resistor_on_two_nets_does_not_short() -> None:
    # AXIAL-R has internal_connections=[] (no internal pairs).
    resistor = Component(ref="R1", value="1k", footprint_id="AXIAL-R", pins=["1", "2"])
    # Place at a5, span=5 → pin 1 at a5, pin 2 at a10 (different groups).
    placement = ComponentPlacement(
        component_ref="R1",
        anchor_hole_id="a5",
        orientation=0,
        span=5,
        pin_holes={"1": "a5", "2": "a10"},
        occupied_hole_ids=["a5", "a10"],
    )
    net_left = Net(
        id="NL",
        name="NL",
        pins=[PinRef(component_ref="R1", pin="1")],
        net_class="digital",
        priority=0,
    )
    net_right = Net(
        id="NR",
        name="NR",
        pins=[PinRef(component_ref="R1", pin="2")],
        net_class="digital",
        priority=0,
    )

    diags, _ = _run([resistor], [net_left, net_right], [placement], [])

    assert all(d.code != "SHORT_BETWEEN_NETS" for d in diags), (
        f"unexpected short: {[d.message for d in diags if d.code == 'SHORT_BETWEEN_NETS']}"
    )


# --------------------------------------------------------------------------
# (e) Footprint WITH internal_connections=[['1','2']] whose pins 1/2 are wired to two
# different nets → exactly one SHORT_BETWEEN_NETS.
# --------------------------------------------------------------------------


def test_footprint_with_internal_pair_on_two_nets_short_circuits() -> None:
    # Build a one-off footprint that bridges pin 1 and pin 2 internally.
    custom = BreadboardFootprint(
        id="TEST-BRIDGE",
        display_name="Test bridge",
        pin_offsets={"1": RelativeHole(x=0, y=0), "2": RelativeHole(x=5, y=0)},
        body_cells=[RelativeHole(x=0, y=0), RelativeHole(x=5, y=0)],
        supported_orientations=[0],
        placement_rules=[PlacementRuleMainArea(type="must-be-on-main-area")],
        geometry=FootprintGeometry(),
        internal_connections=[["1", "2"]],
    )
    fps = dict(FOOTPRINTS)
    fps["TEST-BRIDGE"] = custom

    bridge = Component(ref="X1", value=None, footprint_id="TEST-BRIDGE", pins=["1", "2"])
    placement = ComponentPlacement(
        component_ref="X1",
        anchor_hole_id="a5",
        orientation=0,
        span=5,
        pin_holes={"1": "a5", "2": "a10"},
        occupied_hole_ids=["a5", "a10"],
    )
    net_left = Net(
        id="NL",
        name="NL",
        pins=[PinRef(component_ref="X1", pin="1")],
        net_class="digital",
        priority=0,
    )
    net_right = Net(
        id="NR",
        name="NR",
        pins=[PinRef(component_ref="X1", pin="2")],
        net_class="digital",
        priority=0,
    )

    board, index = _board_and_index()
    layout = Layout(
        version=1,
        board_id=board.id,
        placements=[placement],
        jumpers=[],
        manual_electrical_links=[],
    )
    diags, _ = validate_layout(board, index, fps, [bridge], [net_left, net_right], layout, SolverOptions())

    shorts = [d for d in diags if d.code == "SHORT_BETWEEN_NETS"]
    assert len(shorts) == 1, f"expected one SHORT_BETWEEN_NETS, got {len(shorts)}"
    assert set(shorts[0].related_net_ids) == {"NL", "NR"}


# --------------------------------------------------------------------------
# Bonus coverage: the validator handles a clean 20-component / 30-net layout in well
# under 20 ms; duplicate refs and unknown footprints surface the right codes.
# --------------------------------------------------------------------------


def test_duplicate_component_ref_is_reported() -> None:
    _c1, _p1 = _make_header_component("DUP", "a5")
    c2, _ = _make_header_component("DUP", "a10")
    net = _make_two_pin_net("N", "DUP", "DUP")
    # Two DUP components with two distinct placements cannot both occupy a5 / a10
    # simultaneously (the second placement's pin_holes would collide). Use distinct
    # anchors so the collision detector stays quiet.
    c1b = Component(ref="DUP", value=None, footprint_id="HEADER-1x2", pins=["1", "2"])
    p1b = ComponentPlacement(
        component_ref="DUP",
        anchor_hole_id="a5",
        orientation=0,
        span=1,
        pin_holes={"1": "a5", "2": "a6"},
        occupied_hole_ids=["a5", "a6"],
    )
    p2b = ComponentPlacement(
        component_ref="DUP",
        anchor_hole_id="c10",
        orientation=0,
        span=1,
        pin_holes={"1": "c10", "2": "c11"},
        occupied_hole_ids=["c10", "c11"],
    )
    diags, _ = _run([c1b, c2], [net], [p1b, p2b], [])
    assert "DUPLICATE_COMPONENT_REF" in _diag_codes(diags)


def test_unknown_footprint_is_reported() -> None:
    bad = Component(ref="Z1", value=None, footprint_id="NOPE", pins=["1"])
    placement = ComponentPlacement(
        component_ref="Z1",
        anchor_hole_id="a5",
        orientation=0,
        span=None,
        pin_holes={"1": "a5"},
        occupied_hole_ids=["a5"],
    )
    net = Net(
        id="N",
        name="N",
        pins=[PinRef(component_ref="Z1", pin="1")],
        net_class="digital",
        priority=0,
    )
    diags, _ = _run([bad], [net], [placement], [])
    assert "UNKNOWN_FOOTPRINT" in _diag_codes(diags)


def test_validator_runs_under_20ms_for_20_components() -> None:
    """Hot-path budget: well under 20 ms on a 20-component / 30-net synthetic layout."""
    import random
    import time

    rng = random.Random(0)
    components: list[Component] = []
    placements: list[ComponentPlacement] = []
    nets: list[Net] = []
    for i in range(20):
        components.append(Component(ref=f"U{i}", value=None, footprint_id="AXIAL-R", pins=["1", "2"]))
        col_a = rng.randint(1, 22)
        col_b = col_a + 3
        placements.append(
            ComponentPlacement(
                component_ref=f"U{i}",
                anchor_hole_id=f"a{col_a}",
                orientation=0,
                span=3,
                pin_holes={"1": f"a{col_a}", "2": f"a{col_b}"},
                occupied_hole_ids=[f"a{col_a}", f"a{col_b}"],
            )
        )
    for i in range(30):
        a, b = rng.sample(range(20), 2)
        nets.append(
            Net(
                id=f"N{i}",
                name=f"N{i}",
                pins=[PinRef(component_ref=f"U{a}", pin="1"), PinRef(component_ref=f"U{b}", pin="1")],
                net_class="digital",
                priority=0,
            )
        )

    board, index = _board_and_index()
    layout = Layout(
        version=1,
        board_id=board.id,
        placements=placements,
        jumpers=[],
        manual_electrical_links=[],
    )
    options = SolverOptions()

    # Warm up the path (JIT / cache effects).
    validate_layout(board, index, FOOTPRINTS, components, nets, layout, options)

    samples: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        validate_layout(board, index, FOOTPRINTS, components, nets, layout, options)
        samples.append((time.perf_counter() - t0) * 1000)

    assert min(samples) < 20.0, f"validator too slow: {samples}"
