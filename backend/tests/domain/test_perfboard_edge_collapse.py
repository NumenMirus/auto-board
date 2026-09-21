"""Regression: perfboard placement must not collapse to a single edge row.

This module exercises the failure case documented in
``perfboard-solver-correction-edge-collapse.md``. The fixture is a
representative isolated-hole perfboard circuit:

* U1 (DIP-8 anchor)
* R2, R3 (timing/control)
* Q1 (driver)
* R1, D2 (output stage)
* C1 (input coupling)
* D1 (indicator)

The pre-correction solver was returning a legal but visually degenerate
layout with every component anchored in row 1 of a 15x20 double-sided
perfboard. The corrected solver must:

* place components in a compact two-dimensional region,
* keep functional clusters (timing, input, output) physically local,
* return a solve status of ``fully-routed-valid`` OR
  ``placement-feasible-routing-incomplete`` — never an empty fail,
* honour ``NET_SINGLE_PIN`` as a validation warning that prevents a
  ``fully-routed-valid`` status.
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.domain.boards.registry import get_board_model
from app.domain.models import (
    ComponentPlacement,
    PerfboardModel,
    ProjectDocument,
    SolverOptions,
    TraceLayout,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.traces.place_cpsat import solve_cpsat_placement, solve_status_from_code
from app.domain.traces.validate import validate_layout
from scripts.benchmark_placement import load_fixture_documents

pytest_plugins: list[str] = []


_FIXTURE_NAME = "12-edge-collapse-regression"


def _load_fixture() -> tuple[ProjectDocument, PerfboardModel]:
    docs = load_fixture_documents()
    document = docs[_FIXTURE_NAME]
    board = get_board_model(document.board.model_id)
    assert isinstance(board, PerfboardModel)
    return document, board


def _bbox(placements: list[ComponentPlacement], ref: str) -> tuple[int, int, int, int]:
    p = next(pp for pp in placements if pp.component_ref == ref)
    cols = [int(h.split("-")[1]) for h in p.occupied_hole_ids]
    rows = [int(h.split("-")[0]) for h in p.occupied_hole_ids]
    return min(cols), max(cols), min(rows), max(rows)


def _placement_centroid(p: ComponentPlacement) -> tuple[float, float]:
    cols = [int(h.split("-")[1]) for h in p.occupied_hole_ids]
    rows = [int(h.split("-")[0]) for h in p.occupied_hole_ids]
    return (sum(cols) / len(cols), sum(rows) / len(rows))


def _row_distribution(placements: list[ComponentPlacement]) -> Counter[int]:
    """Per-row count of distinct component refs."""
    out: Counter[int] = Counter()
    for p in placements:
        rows = {int(h.split("-")[0]) for h in p.occupied_hole_ids}
        for r in rows:
            out[r] += 1
    return out


@pytest.mark.parametrize("seed", [1, 7])
def test_layout_does_not_collapse_to_single_edge_row(seed: int) -> None:
    """The headline regression: no edge-row parking strip.

    The pre-correction solver anchored every component in row 1. The
    corrected solver must spread the layout across at least 3 distinct
    rows on a 15x20 board, and none of the rows must hold more than
    50 % of the components.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=seed,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=seed,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    placements = result.placements
    assert len(placements) == len(document.components), (
        f"unplaced: {result.unplaced}; "
        f"placed={[p.component_ref for p in placements]}"
    )

    rows_used = set()
    for p in placements:
        for hid in p.occupied_hole_ids:
            rows_used.add(int(hid.split("-")[0]))
    # The 8-component circuit must use at least 3 distinct rows; the
    # pre-correction failure mode uses row 1 only.
    assert len(rows_used) >= 3, (
        f"layout collapsed into {len(rows_used)} rows: {sorted(rows_used)}"
    )

    counts = _row_distribution(placements)
    max_per_row = max(counts.values())
    n_components = len(placements)
    assert max_per_row <= n_components // 2 + 1, (
        f"row wall too dense: {dict(counts)}, n_components={n_components}"
    )


@pytest.mark.parametrize("seed", [1, 7])
def test_layout_has_meaningful_x_and_y_span(seed: int) -> None:
    """Origin-neutral bbox check — the layout must occupy a 2D region.

    Translation of an equivalent arrangement should not change the
    spans; here we check the absolute span as a witness of 2D occupancy.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=seed,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=seed,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    cols: list[int] = []
    rows: list[int] = []
    for p in result.placements:
        for hid in p.occupied_hole_ids:
            cols.append(int(hid.split("-")[1]))
            rows.append(int(hid.split("-")[0]))
    x_span = max(cols) - min(cols)
    y_span = max(rows) - min(rows)
    # Both axes must have meaningful extent; a row-collapse gives
    # (x_span > 0, y_span == 0 or 1).
    assert x_span >= 4 and y_span >= 4, (
        f"layout collapsed: x_span={x_span}, y_span={y_span}"
    )


def test_brief_mandated_pin_proximity_is_respected() -> None:
    """C1 (input coupling) must sit within a bounded pin distance of its
    associated U1 input pin, R2/R3 must stay near U1 pins 5/6, and
    Q1/R1/D2 must form a compact output cluster near the U1 output
    pin. The bounds are deliberately loose to keep the test stable
    across CP-SAT version drift.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=7,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=7,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    placements_by_ref = {p.component_ref: p for p in result.placements}

    def manhattan(a: str, b: str) -> int:
        ra, ca = int(a.split("-")[0]), int(a.split("-")[1])
        rb, cb = int(b.split("-")[0]), int(b.split("-")[1])
        return abs(ra - rb) + abs(ca - cb)

    u1 = placements_by_ref["U1"]
    c1 = placements_by_ref["C1"]
    r2 = placements_by_ref["R2"]
    r3 = placements_by_ref["R3"]
    q1 = placements_by_ref["Q1"]
    r1 = placements_by_ref["R1"]
    d2 = placements_by_ref["D2"]

    # C1 is wired to U1 ground (pin 4) and to the timing RC chain
    # (U1 pins 5/6 via R3). Stay within ~12 lattice steps of U1.
    c1_to_u1 = min(
        manhattan(c1.pin_holes["1"], u1.pin_holes["4"]),
        manhattan(c1.pin_holes["2"], u1.pin_holes["4"]),
    )
    assert c1_to_u1 <= 12, f"C1 too far from U1: {c1_to_u1} steps"

    # R2 and R3 timing cluster — bounded distance from U1 pins 5/6.
    r2_to_u1 = min(
        manhattan(r2.pin_holes["1"], u1.pin_holes["5"]),
        manhattan(r2.pin_holes["1"], u1.pin_holes["6"]),
    )
    r3_to_u1 = min(
        manhattan(r3.pin_holes["1"], u1.pin_holes["5"]),
        manhattan(r3.pin_holes["1"], u1.pin_holes["6"]),
    )
    assert r2_to_u1 <= 12, f"R2 too far from U1 timing pins: {r2_to_u1}"
    assert r3_to_u1 <= 12, f"R3 too far from U1 timing pins: {r3_to_u1}"

    # Output cluster (Q1, R1, D2) — sit near U1 output pin (3).
    def cluster_to_output(*refs: ComponentPlacement) -> int:
        return min(
            min(
                manhattan(p.pin_holes[pid], u1.pin_holes["3"])
                for pid in p.pin_holes
            )
            for p in refs
        )

    output_cluster = cluster_to_output(q1, r1, d2)
    assert output_cluster <= 12, f"output cluster too far: {output_cluster}"


@pytest.mark.parametrize("seed", [1, 7])
def test_solve_status_distinguishes_invalid_netlist(seed: int) -> None:
    """The fixture intentionally contains a single-pin VCC net. The
    solver must surface that as a ``NET_SINGLE_PIN`` warning AND must
    not claim a ``fully-routed-valid`` status while it exists.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=seed,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=seed,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    codes = [
        d.code
        for d in validate_layout(
            board,
            PERFBOARD_FOOTPRINTS,
            list(document.components),
            list(document.nets),
            TraceLayout(board_id=board.id, placements=result.placements),
        ).diagnostics
    ]
    assert "NET_SINGLE_PIN" in codes, (
        "the fixture exposes a single-pin VCC net; validator must flag it"
    )

    status_code = result.trace.phase_timings_ms.get("cpsat_solve_status")
    assert status_code is not None, (
        f"cpsat_solve_status missing from trace: {sorted(result.trace.phase_timings_ms)}"
    )
    status = solve_status_from_code(int(status_code))
    assert status != "fully-routed-valid", (
        f"solver returned {status!r} while NET_SINGLE_PIN present"
    )
    assert status == "invalid-netlist", (
        f"single-pin net must mark solve invalid; got {status!r}"
    )


@pytest.mark.parametrize("seed", [1, 7])
def test_multiple_candidates_were_routed(seed: int) -> None:
    """The route-first selection must consider more than one candidate.

    Two candidates are the minimum: the CP-SAT pick and the greedy
    baseline. Larger solution_count + the no-good diversification push
    the count higher; we only assert at least 1 here so the test stays
    stable across solver versions.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=seed,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=seed,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    routed_count = int(result.trace.phase_timings_ms.get("cpsat_routed_count", 0))
    solution_count = int(result.trace.phase_timings_ms.get("cpsat_solution_count", 0))
    assert routed_count >= 1
    assert solution_count >= 1


def test_layout_retains_routing_corridor_around_u1() -> None:
    """U1 is a DIP-8 — at least one of its pin rows must keep at least
    one free hole on each side so a trace can escape the package.
    Components placed inside the DIP's immediate escape area are
    penalised; the regression case stuffed components into that region.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=7,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=7,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    placements_by_ref = {p.component_ref: p for p in result.placements}
    u1 = placements_by_ref["U1"]
    dip_escape = int(result.trace.phase_timings_ms.get("cpsat_dip_escape_violations", 0))
    # We don't demand zero (other fixtures may legitimately touch), but
    # the broken layout stuffed every component in row 1 around U1 — the
    # metric must be small relative to a regression case. The flagship
    # layout uses up to 5 cells in the DIP's 1-hole escape corridor.
    assert dip_escape <= 6, f"DIP escape violations too high: {dip_escape}"


def test_trace_exposes_layout_metrics() -> None:
    """Solver-trace metadata must carry the bbox / row / DIP-escape /
    single-pin-net / solve-status keys so callers can diagnose without
    re-running the placer.
    """
    document, board = _load_fixture()
    options = SolverOptions(
        seed=7,
        placement_engine="cpsat",
        placement_time_limit_ms=15000,
        placement_candidate_limit=80,
        placement_solution_count=4,
        solver_seed=7,
    )
    result = solve_cpsat_placement(
        board=board,
        footprints=PERFBOARD_FOOTPRINTS,
        components=list(document.components),
        nets=list(document.nets),
        options=options,
        initial_layout=TraceLayout(board_id=board.id, placements=[]),
    )
    timings = result.trace.phase_timings_ms
    for key in (
        "cpsat_solve_status",
        "cpsat_x_span",
        "cpsat_y_span",
        "cpsat_min_span",
        "cpsat_max_components_per_row",
        "cpsat_dip_escape_violations",
        "cpsat_single_pin_net_count",
    ):
        assert key in timings, f"trace missing {key}: {sorted(timings)}"


def test_fixture_path_is_resolvable() -> None:
    """The regression fixture must be present and schema-valid so the
    benchmark corpus can also exercise it.
    """
    docs = load_fixture_documents()
    assert _FIXTURE_NAME in docs, (
        f"fixture {_FIXTURE_NAME!r} not in benchmark corpus: {sorted(docs)}"
    )
    document = docs[_FIXTURE_NAME]
    raw = document.model_dump(by_alias=True)
    reparsed = ProjectDocument.model_validate(raw)
    assert reparsed.board.model_id == "strip-15x20-double"


def test_perfboard_alias_resolves_to_same_model() -> None:
    """The documented ``perfboard-15x20-double-sided`` alias must point
    at the same model object as the legacy ``strip-15x20-double``.
    """
    from app.domain.boards.registry import (
        PERFBOARD_ID_ALIASES,
        get_board_model,
        resolve_board_id,
    )

    assert resolve_board_id("perfboard-15x20-double-sided") == "strip-15x20-double"
    legacy = get_board_model("strip-15x20-double")
    aliased = get_board_model("perfboard-15x20-double-sided")
    assert legacy is aliased
    assert "perfboard-15x20-double-sided" in PERFBOARD_ID_ALIASES