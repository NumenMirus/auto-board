"""Property tests for AutoBreadboard.

Five Hypothesis properties, each pinning down a behavioral invariant:

(a) Two placements that claim the same hole are ALWAYS flagged with
    `HOLE_COLLISION` by the validator (no silent overlap).

(b) The internal lattice rotation helper `_rotate` is its own inverse: rotating
    by ``o`` and then by ``360 - o`` recovers the original lattice offset.

(c) A `Layout` round-trips losslessly through `model_dump(by_alias=True)` /
    `model_validate` — no silent field loss when crossing the wire boundary.

(d) The validator never returns ``error_count == 0`` when two distinct nets'
    pins resolve to the same physical DSU root (induced short).

(e) `solve()` either returns a `SolveResult` or raises a `DomainError`
    subclass; it must never propagate `KeyError` / `AttributeError` /
    `TypeError` / `IndexError` from malformed or partially-valid input.
"""

from __future__ import annotations

from typing import cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.domain.boards.half400 import build_half400
from app.domain.errors import DomainError
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    Component,
    ComponentPlacement,
    Jumper,
    JumperPath,
    Layout,
    Net,
    NetClass,
    PinRef,
    Point,
    SolverOptions,
)
from app.domain.poses import Pose, generate_poses
from app.domain.solve import _rotate, solve
from app.domain.validate import validate_layout

# --------------------------------------------------------------------------
# Shared board fixtures
# --------------------------------------------------------------------------

#: Board model used by every property that needs an index. Built once per
#: session — `build_half400` is cheap but rglobs the spec, so caching matters
#: when Hypothesis runs hundreds of examples.
_SPLIT_BOARD = build_half400(split_rails=True)
_BOARD_INDEX = BoardIndex.build(_SPLIT_BOARD)

#: A handful of small, common footprints pose generation produces sensible
#: non-empty layouts for. AXIAL-R is an axial resistor, LED-2P a two-pin LED,
#: RADIAL-CAP-2P a 2-pin radial capacitor.
_PROBE_FOOTPRINT_IDS: tuple[str, ...] = ("AXIAL-R", "LED-2P", "RADIAL-CAP-2P")

#: Pre-generated pose tuples per footprint id, cached so we don't pay the
#: ``@lru_cache`` lookup cost on every Hypothesis example.
_PROBE_POSES: dict[str, tuple[Pose, ...]] = {
    fp_id: generate_poses(_BOARD_INDEX, FOOTPRINTS[fp_id]) for fp_id in _PROBE_FOOTPRINT_IDS
}

# --------------------------------------------------------------------------
# Helpers shared across properties
# --------------------------------------------------------------------------


def _pose_to_placement(pose: Pose, ref: str, index: BoardIndex = _BOARD_INDEX) -> ComponentPlacement:
    """Build a `ComponentPlacement` from a `Pose` using the canonical index."""
    pin_holes = {pid: index.hole_ids[hi] for pid, hi in pose.pin_idx}
    occupied = [index.hole_ids[hi] for hi in pose.body_cells_idx]
    return ComponentPlacement(
        component_ref=ref,
        anchor_hole_id=index.hole_ids[pose.anchor_idx],
        orientation=pose.orientation,
        span=pose.span,
        pin_holes=pin_holes,
        occupied_hole_ids=occupied,
        locked=False,
    )


# --------------------------------------------------------------------------
# (a) No hole occupied by two pins without a diagnostic
# --------------------------------------------------------------------------


def _placement_for_footprint(fp_id: str, pose_idx: int, ref: str) -> ComponentPlacement:
    poses = _PROBE_POSES[fp_id]
    # Modulo into the available pose range so Hypothesis indices always land.
    return _pose_to_placement(poses[pose_idx % len(poses)], ref=ref)


@st.composite
def _colliding_placements(draw: st.DrawFn) -> tuple[list[str], list[ComponentPlacement], list[Component]]:
    """Generate a small ``(refs, placements, components)`` triple where collisions
    are deliberately possible by construction.

    The strategy picks 2-4 footprints (each from the small probe set) and a
    pose index per footprint, then constructs placements. The validator
    interprets the result as a flat list.
    """
    count = draw(st.integers(min_value=2, max_value=4))
    refs: list[str] = []
    placements: list[ComponentPlacement] = []
    components: list[Component] = []
    for i in range(count):
        fp_id = draw(st.sampled_from(_PROBE_FOOTPRINT_IDS))
        pose_idx = draw(st.integers(min_value=0, max_value=20))
        ref = f"R{i + 1}"
        refs.append(ref)
        placements.append(_placement_for_footprint(fp_id, pose_idx, ref=ref))
        components.append(Component(ref=ref, value="1k", footprint_id=fp_id, pins=["1", "2"]))
    return refs, placements, components


@given(data=_colliding_placements())
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_collision_detection_when_holes_shared(
    data: tuple[list[str], list[ComponentPlacement], list[Component]],
) -> None:
    """Whenever two placements claim the same hole, the validator must emit `HOLE_COLLISION`."""
    refs, placements, components = data
    # Collect pairwise shared holes.
    occupied = [set(p.occupied_hole_ids) for p in placements]
    shared_pairs: list[tuple[str, str, str]] = []
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            shared = occupied[i] & occupied[j]
            for hole in shared:
                shared_pairs.append((refs[i], refs[j], hole))

    layout = Layout(
        version=1,
        board_id=_SPLIT_BOARD.id,
        placements=placements,
        jumpers=[],
    )

    # Use a netlist that puts each pair of pins in their own net so the
    # validator doesn't reject the layout for *other* reasons first.
    nets: list[Net] = []
    for i, comp in enumerate(components):
        # Self-loop net: pin 1 -> pin 2 of the same component.
        nets.append(
            Net(
                id=f"N{i + 1}",
                name=f"n{i + 1}",
                pins=[
                    PinRef(component_ref=comp.ref, pin="1"),
                    PinRef(component_ref=comp.ref, pin="2"),
                ],
                net_class="digital",
                priority=0,
            )
        )

    diagnostics, _score = validate_layout(
        _SPLIT_BOARD,
        _BOARD_INDEX,
        FOOTPRINTS,
        components,
        nets,
        layout,
        SolverOptions(seed=12345),
    )

    # The implication: every detected shared hole must surface a
    # `HOLE_COLLISION` diagnostic mentioning both component refs.
    collision_codes = {d.code for d in diagnostics}
    if shared_pairs:
        assert "HOLE_COLLISION" in collision_codes, (
            f"validator missed collision(s): shared pairs={shared_pairs!r}, "
            f"got codes={[d.code for d in diagnostics]!r}"
        )
        for ref_a, ref_b, hole in shared_pairs:
            matching = [
                d
                for d in diagnostics
                if d.code == "HOLE_COLLISION"
                and hole in d.message
                and ref_a in d.message
                and ref_b in d.message
            ]
            assert matching, (
                f"no HOLE_COLLISION diagnostic covers hole={hole!r} refs=({ref_a!r},{ref_b!r}); "
                f"got {[d.message for d in diagnostics if d.code == 'HOLE_COLLISION']!r}"
            )


# --------------------------------------------------------------------------
# (b) Rotation round-trip
# --------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    x=st.integers(min_value=-20, max_value=20),
    y=st.integers(min_value=-20, max_value=20),
    orientation=st.sampled_from([90, 180, 270]),
)
def test_rotate_round_trip(x: int, y: int, orientation: int) -> None:
    """Rotating by ``o`` and then by ``360 - o`` recovers the original offset."""
    once = _rotate(x, y, orientation)
    twice = _rotate(once[0], once[1], 360 - orientation)
    assert twice == (x, y), (
        f"rotation round-trip failed: ({x!r}, {y!r}) @ {orientation} -> {once!r} -> {twice!r}"
    )


# --------------------------------------------------------------------------
# (c) Layout export/import round-trip preserves data
# --------------------------------------------------------------------------


#: Concrete placement and jumper templates used to construct realistic,
#: non-empty Layouts without dragging the full Strategy machinery into nested
#: Pydantic models.
_PLACEMENT_TEMPLATES: tuple[ComponentPlacement, ...] = (
    ComponentPlacement(
        component_ref="R1",
        anchor_hole_id="a1",
        orientation=0,
        span=2,
        pin_holes={"1": "a1", "2": "a3"},
        occupied_hole_ids=["a1", "a2", "a3"],
        locked=False,
    ),
    ComponentPlacement(
        component_ref="U1",
        anchor_hole_id="f5",
        orientation=180,
        span=None,
        pin_holes={"1": "f5", "2": "j5"},
        occupied_hole_ids=["f5", "g5", "h5", "i5", "j5", "j4", "i4", "h4", "g4", "f4"],
        locked=True,
    ),
    ComponentPlacement(
        component_ref="LED1",
        anchor_hole_id="a10",
        orientation=90,
        span=1,
        pin_holes={"1": "a10", "2": "j10"},
        occupied_hole_ids=["a10", "b10", "j10", "i10"],
        locked=False,
    ),
)

_JUMPER_TEMPLATES: tuple[Jumper, ...] = (
    Jumper(
        id="J1",
        net_id="N1",
        start_hole_id="a1",
        end_hole_id="a3",
        path=JumperPath(points=[Point(x=0.0, y=0.0), Point(x=5.08, y=0.0)], layer="lower"),
        estimated_length_mm=7.0,
        locked=False,
        color="#1a1a1a",
    ),
    Jumper(
        id="J2",
        net_id="N2",
        start_hole_id="f5",
        end_hole_id="j5",
        path=JumperPath(
            points=[Point(x=10.16, y=12.7), Point(x=10.16, y=25.4), Point(x=25.4, y=25.4)],
            layer="upper",
        ),
        estimated_length_mm=20.0,
        locked=True,
        color="#d92b2b",
    ),
    Jumper(
        id="J3",
        net_id="N3",
        start_hole_id="a10",
        end_hole_id="j10",
        path=JumperPath(points=[Point(x=22.86, y=0.0), Point(x=22.86, y=12.7)], layer="lower"),
        estimated_length_mm=15.0,
        locked=False,
        color="#1f77b4",
    ),
)


@st.composite
def _layouts(draw: st.DrawFn) -> Layout:
    """Build a ``Layout`` with 0-3 placements and 0-3 jumpers.

    Uses fixed templates for placement and jumper content rather than a fully
    generative strategy over nested models: each template exercises a different
    orientation, lock state, layer, and color, which is plenty for proving the
    round-trip is lossless. ``unique=True`` is not used because Pydantic models
    with mutable defaults are not hashable; allowing duplicates is harmless
    for the round-trip property.
    """
    placements = draw(
        st.lists(
            st.sampled_from(_PLACEMENT_TEMPLATES),
            min_size=0,
            max_size=len(_PLACEMENT_TEMPLATES),
        )
    )
    jumpers = draw(
        st.lists(
            st.sampled_from(_JUMPER_TEMPLATES),
            min_size=0,
            max_size=len(_JUMPER_TEMPLATES),
        )
    )
    return Layout(
        version=1,
        board_id="half-400-standard-split-rails",
        placements=placements,
        jumpers=jumpers,
        manual_electrical_links=[],
    )


@given(layout=_layouts())
@settings(max_examples=30, deadline=None)
def test_layout_roundtrip(layout: Layout) -> None:
    """`Layout.model_validate(layout.model_dump(by_alias=True))` equals the original."""
    dumped = layout.model_dump(by_alias=True)
    restored = Layout.model_validate(dumped)
    assert restored == layout, (
        f"round-trip mismatch: original={layout.model_dump(by_alias=True)!r}, "
        f"restored={restored.model_dump(by_alias=True)!r}"
    )


# --------------------------------------------------------------------------
# (d) Validator never marks a layout valid with two target nets in the same
#     physical group
# --------------------------------------------------------------------------


@st.composite
def _short_scenario(draw: st.DrawFn) -> tuple[list[Component], list[Net], Layout]:
    """Build a scenario where two different nets' pins end up in the same
    physical DSU root.

    Strategy: pick a column whose tie-point group has at least two members we
    can use, place one 2-pin component spanning two of them, and wire two
    distinct nets through the same physical node. The two nets share the same
    electrical equipotential -> ``SHORT_BETWEEN_NETS``.
    """
    # Pick a column whose tie-point group has at least two members we can use.
    column = draw(st.integers(min_value=1, max_value=30))
    hole_a = f"a{column}"
    hole_b = f"b{column}"

    # Place a single 2-pin footprint spanning both holes (anchor at hole_a,
    # span 1 -> pin 2 at hole_b).
    placement = ComponentPlacement(
        component_ref="R1",
        anchor_hole_id=hole_a,
        orientation=0,
        span=1,
        pin_holes={"1": hole_a, "2": hole_b},
        occupied_hole_ids=[hole_a, hole_b],
        locked=False,
    )
    layout = Layout(
        version=1,
        board_id=_SPLIT_BOARD.id,
        placements=[placement],
        jumpers=[],
    )
    components: list[Component] = [
        Component(ref="R1", value="1k", footprint_id="AXIAL-R", pins=["1", "2"]),
    ]

    # Two nets: each "touches" both pins via separate PinRefs on the same
    # physical node -> SHORT between them.
    nets: list[Net] = [
        Net(
            id="N1",
            name="n1",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R1", pin="2"),
            ],
            net_class="digital",
            priority=0,
        ),
        Net(
            id="N2",
            name="n2",
            pins=[
                PinRef(component_ref="R1", pin="1"),
                PinRef(component_ref="R1", pin="2"),
            ],
            net_class="digital",
            priority=0,
        ),
    ]
    return components, nets, layout


@given(scenario=_short_scenario())
@settings(max_examples=30, deadline=None)
def test_validator_rejects_induced_short(
    scenario: tuple[list[Component], list[Net], Layout],
) -> None:
    """When two distinct nets share a physical DSU root, the validator must report an error."""
    components, nets, layout = scenario
    diagnostics, score = validate_layout(
        _SPLIT_BOARD,
        _BOARD_INDEX,
        FOOTPRINTS,
        components,
        nets,
        layout,
        SolverOptions(seed=12345),
    )
    short_diags = [d for d in diagnostics if d.code == "SHORT_BETWEEN_NETS"]
    assert short_diags, (
        f"expected SHORT_BETWEEN_NETS for nets sharing a physical group; got "
        f"codes={[d.code for d in diagnostics]!r}"
    )
    assert score.error_count > 0, f"layout with induced short must not validate cleanly; score={score!r}"


# --------------------------------------------------------------------------
# (e) Solver never crashes on partially-valid netlists
# --------------------------------------------------------------------------


_NetClassValues: tuple[str, ...] = ("ground", "power", "digital", "low-priority")


@st.composite
def _partially_valid_netlist(draw: st.DrawFn) -> tuple[list[Component], list[Net]]:
    """Generate a small netlist with deliberately invalid references.

    Possible bad shapes:
    * A ``Component`` with a ``footprint_id`` that is not in ``FOOTPRINTS``.
    * A ``Net`` with an empty ``pins`` list.
    * A ``PinRef`` whose ``component_ref`` points to nothing in the component
      list (a "ghost" reference).

    A Hypothesis example can include 0, 1 or all 3 of these bad shapes.
    """
    # Pick how many bad shapes to inject. 0 = valid baseline (rare but useful
    # to confirm the property holds on clean inputs too).
    bad_count = draw(st.integers(min_value=0, max_value=3))
    bad_choices = draw(
        st.lists(
            st.sampled_from(["unknown_footprint", "empty_net", "ghost_ref"]),
            min_size=bad_count,
            max_size=bad_count,
            unique=True,
        )
    )

    components: list[Component] = []
    nets: list[Net] = []

    if "unknown_footprint" in bad_choices:
        components.append(
            Component(
                ref="R_BROKEN",
                value="1k",
                footprint_id="NOT-EXIST-FOOTPRINT",
                pins=["1", "2"],
            )
        )

    # Always include at least one *valid* component so the solver has
    # *something* it can attempt to place, which makes the test more
    # representative of real-world partially-valid inputs.
    components.append(
        Component(
            ref="R_OK",
            value="1k",
            footprint_id="AXIAL-R",
            pins=["1", "2"],
        )
    )

    # The valid net (a self-loop on R_OK).
    nets.append(
        Net(
            id="N_OK",
            name="ok",
            pins=[
                PinRef(component_ref="R_OK", pin="1"),
                PinRef(component_ref="R_OK", pin="2"),
            ],
            net_class=cast(NetClass, draw(st.sampled_from(_NetClassValues))),
            priority=0,
        )
    )

    if "empty_net" in bad_choices:
        nets.append(Net(id="N_EMPTY", name="empty", pins=[], net_class="digital", priority=0))

    if "ghost_ref" in bad_choices:
        nets.append(
            Net(
                id="N_GHOST",
                name="ghost",
                pins=[PinRef(component_ref="R_DOES_NOT_EXIST", pin="1")],
                net_class="digital",
                priority=0,
            )
        )

    return components, nets


@given(netlist=_partially_valid_netlist())
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_solver_handles_partially_valid_netlists(
    netlist: tuple[list[Component], list[Net]],
) -> None:
    """`solve()` must return a `SolveResult` or raise `DomainError`; never `KeyError` etc."""
    components, nets = netlist
    try:
        result = solve(
            _SPLIT_BOARD,
            _BOARD_INDEX,
            FOOTPRINTS,
            components,
            nets,
            SolverOptions(seed=12345),
        )
    except DomainError:
        # Acceptable: deterministic-domain failure surfaced as a typed error.
        return
    except (KeyError, AttributeError, TypeError, IndexError, ValueError) as exc:
        pytest.fail(
            f"solve() leaked {type(exc).__name__} on partially-valid netlist: "
            f"components={components!r}, nets={nets!r}: {exc!r}"
        )
    except Exception as exc:  # pragma: no cover - defensive
        pytest.fail(
            f"solve() raised unexpected {type(exc).__name__} on partially-valid netlist: "
            f"components={components!r}, nets={nets!r}: {exc!r}"
        )
    # Returned a SolveResult -> property holds.
    assert result is not None
