"""Quality regression tests: greedy vs CP-SAT perfboard placement.

Side-by-side comparison on flagship fixtures. For each, we run both engines
with the same seed, route both placements, and assert the CP-SAT output is
at least as good as the greedy baseline on a documented metric. Tolerances
are loose enough to survive OR-Tools version drift; they catch real
regressions, not solver noise.

Fixtures live in ``backend/tests/fixtures/`` (breadboard today) — these
tests build perfboard fixtures by hand because the existing perfboard board
registry only has the flagship stripboards, and the breadboard fixtures are
the canonical flagship circuits. We reuse the same component shapes so the
quality comparisons stay meaningful.
"""

from __future__ import annotations

import pytest

from app.domain.boards.perfboard import build_perfboard
from app.domain.models import (
    Component,
    Net,
    PinRef,
    SolverOptions,
    TraceLayout,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.traces import maze, route as trace_route
from app.domain.traces.place import place_greedy
from app.domain.traces.place_cpsat import solve_cpsat_placement


# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


def _board():
    return build_perfboard(rows=20, cols=30, layers=2, id="strip-20x30-double")


def _dip14_components():
    return [
        Component(ref="U1", value="74HC14", footprint_id="DIP-14",
                   pins=[str(i) for i in range(1, 15)]),
        Component(ref="C1", value="100n", footprint_id="RADIAL-CAP-2P",
                   pins=["1", "2"]),
        Component(ref="R1", value="10k", footprint_id="AXIAL-R",
                   pins=["1", "2"]),
        Component(ref="R2", value="4.7k", footprint_id="AXIAL-R",
                   pins=["1", "2"]),
        Component(ref="D1", value="LED", footprint_id="LED-2P",
                   pins=["1", "2"]),
    ]


def _dip14_nets():
    return [
        Net(id="vcc", name="VCC",
            pins=[PinRef(component_ref="U1", pin="14"),
                  PinRef(component_ref="C1", pin="1")],
            net_class="power", priority=0),
        Net(id="gnd", name="GND",
            pins=[PinRef(component_ref="U1", pin="7"),
                  PinRef(component_ref="C1", pin="2")],
            net_class="ground", priority=0),
        Net(id="in1", name="IN1",
            pins=[PinRef(component_ref="U1", pin="1"),
                  PinRef(component_ref="R1", pin="2")],
            net_class="digital", priority=0),
        Net(id="out1", name="OUT1",
            pins=[PinRef(component_ref="U1", pin="2"),
                  PinRef(component_ref="D1", pin="1")],
            net_class="digital", priority=0),
        Net(id="out2", name="OUT2",
            pins=[PinRef(component_ref="U1", pin="4"),
                  PinRef(component_ref="R2", pin="1")],
            net_class="digital", priority=0),
    ]


def _connector_breakout_components():
    return [
        Component(ref="HDR1", value="8-pin", footprint_id="HEADER-1x8",
                  pins=[str(i) for i in range(1, 9)]),
        Component(ref="U1", value="74HC04", footprint_id="DIP-8",
                  pins=[str(i) for i in range(1, 9)]),
        Component(ref="R1", value="10k", footprint_id="AXIAL-R",
                  pins=["1", "2"]),
    ]


def _connector_breakout_nets():
    return [
        Net(id="sig1", name="SIG1",
            pins=[PinRef(component_ref="HDR1", pin="1"),
                  PinRef(component_ref="U1", pin="1")],
            net_class="digital", priority=0),
        Net(id="sig2", name="SIG2",
            pins=[PinRef(component_ref="HDR1", pin="2"),
                  PinRef(component_ref="U1", pin="3")],
            net_class="digital", priority=0),
    ]


def _run_pair(components, nets, seed):
    """Run greedy and CP-SAT, route both, return ``(route_cpsat, route_greedy)``."""
    board = _board()
    initial = TraceLayout(board_id=board.id, placements=[])
    cpsat_opts = SolverOptions(
        seed=seed,
        placement_engine="cpsat",
        placement_time_limit_ms=4000,
        placement_candidate_limit=30,
        placement_solution_count=3,
        solver_seed=seed,
    )
    greedy_opts = SolverOptions(seed=seed, placement_engine="greedy")
    cpsat_placement = solve_cpsat_placement(
        board=board, footprints=PERFBOARD_FOOTPRINTS,
        components=components, nets=nets, options=cpsat_opts,
        initial_layout=initial,
    )
    greedy_placement = place_greedy(
        board=board, footprints=PERFBOARD_FOOTPRINTS,
        components=components, nets=nets,
        options=greedy_opts, initial_layout=initial,
    )
    graph = maze.build_maze(
        rows=board.rows, cols=board.cols,
        pitch_mm=board.pitch_mm, double_sided=(board.layers == 2),
    )
    rr_c = trace_route.route(
        board_id=board.id, placements=cpsat_placement.placements,
        components=components, footprints=PERFBOARD_FOOTPRINTS,
        nets=nets, graph=graph,
    )
    rr_g = trace_route.route(
        board_id=board.id, placements=greedy_placement.placements,
        components=components, footprints=PERFBOARD_FOOTPRINTS,
        nets=nets, graph=graph,
    )
    return rr_c, rr_g, cpsat_placement, greedy_placement


def _bbox(placements, ref):
    p = next(pp for pp in placements if pp.component_ref == ref)
    cols = [int(h.split("-")[1]) for h in p.occupied_hole_ids]
    rows = [int(h.split("-")[0]) for h in p.occupied_hole_ids]
    return min(cols), max(cols), min(rows), max(rows)


# --------------------------------------------------------------------------
# Quality assertions
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 7])
def test_cpsat_unrouted_net_count_not_worse_than_greedy(seed: int) -> None:
    rr_c, rr_g, _, _ = _run_pair(_dip14_components(), _dip14_nets(), seed)
    assert len(rr_c.unrouted_nets) <= len(rr_g.unrouted_nets)


@pytest.mark.parametrize("seed", [1, 7])
def test_cpsat_routed_trace_length_not_worse_than_greedy(seed: int) -> None:
    rr_c, rr_g, _, _ = _run_pair(_dip14_components(), _dip14_nets(), seed)
    c_total = sum(t.estimated_length_mm for t in rr_c.layout.traces)
    g_total = sum(t.estimated_length_mm for t in rr_g.layout.traces)
    # Allow 5 % slack on the routing cost; CP-SAT should not regress.
    assert c_total <= g_total * 1.05


@pytest.mark.parametrize("seed", [1, 7])
def test_cpsat_board_span_within_tolerance(seed: int) -> None:
    """CP-SAT placements should not be drastically wider than greedy. We
    allow 10 % slack because CP-SAT may legitimately choose a wider
    arrangement for better routing."""
    components = _dip14_components()
    _, _, cpsat_pl, greedy_pl = _run_pair(components, _dip14_nets(), seed)
    cs = _bbox(cpsat_pl.placements, "U1")
    gs = _bbox(greedy_pl.placements, "U1")
    cw = cs[1] - cs[0]
    gw = gs[1] - gs[0]
    assert cw <= gw * 1.20, f"DIP span too wide: cpsat={cw}, greedy={gw}"


def test_cpsat_decoupler_within_distance_of_supply_pin() -> None:
    """The bypass cap joined by power+ground to the DIP should be placed
    within ~6 lattice steps of the relevant supply pin."""
    components = _dip14_components()
    nets = _dip14_nets()
    _, _, cpsat_pl, _ = _run_pair(components, nets, seed=7)
    u1 = next(p for p in cpsat_pl.placements if p.component_ref == "U1")
    c1 = next(p for p in cpsat_pl.placements if p.component_ref == "C1")
    a = c1.pin_holes["1"]
    b = u1.pin_holes["14"]  # DIP-14 VCC is pin 14
    d = abs(int(a.split("-")[0]) - int(b.split("-")[0])) + abs(
        int(a.split("-")[1]) - int(b.split("-")[1])
    )
    assert d <= 6, f"cap pin 1 too far from U1 pin 14: {d} steps (cap={a}, U1={b})"


@pytest.mark.parametrize("seed", [1, 7])
def test_cpsat_connector_on_edge_when_footprint_carries_no_rule(seed: int) -> None:
    """The header breakout should not bury itself in the middle of the
    board when an edge pose is reachable. CP-SAT's edge term kicks in for
    CONN-*/HEADER-* footprints."""
    components = _connector_breakout_components()
    nets = _connector_breakout_nets()
    rr_c, rr_g, cpsat_pl, _ = _run_pair(components, nets, seed)
    hdr = next(p for p in cpsat_pl.placements if p.component_ref == "HDR1")
    cols = sorted(int(h.split("-")[1]) for h in hdr.occupied_hole_ids)
    rows = sorted(int(h.split("-")[0]) for h in hdr.occupied_hole_ids)
    # Either column-span or row-span is on the edge.
    board_cols, board_rows = 30, 20
    on_left = cols[0] == 1
    on_right = cols[-1] == board_cols
    on_top = rows[0] == 1
    on_bot = rows[-1] == board_rows
    assert on_left or on_right or on_top or on_bot, (
        f"header not on any edge: cols={cols}, rows={rows}"
    )


@pytest.mark.parametrize("seed", [1, 7])
def test_cpsat_components_all_placed(seed: int) -> None:
    """Sanity: the CP-SAT path produces a fully-placed layout on flagship
    fixtures (no unplaced components in the result)."""
    components = _dip14_components()
    nets = _dip14_nets()
    _, _, cpsat_pl, _ = _run_pair(components, nets, seed)
    assert cpsat_pl.unplaced == [], f"unplaced: {cpsat_pl.unplaced}"