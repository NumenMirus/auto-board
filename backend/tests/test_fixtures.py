"""End-to-end fixtures for AutoBreadboard.

Parametrised test that loads each ``NN-name.json`` / ``NN-name.expected.json``
pair from ``tests/fixtures/``, validates the schema, asserts round-trip
serialisation stability, runs the solver (or the validator for the induced-short
case), and checks the result against the expected values.

Fixture 4 is solved twice with ``seed=12345`` to verify determinism; the two
dumps must be byte-identical.

Fixture 9 is the validator-only "induced short" probe — its pre-populated locked
placements deliberately share a tie-point group across two distinct nets, and
the test asserts that ``validate_layout`` flags it.

Fixture 10 is the locked-placement + locked-jumper preservation probe; the test
calls ``solve(initial_layout=…)`` and asserts that the locked R1 placement and
the locked jumper survive the round-trip byte-identical.

Fixture 8 (20x DIP-28) is the "impossible" case — the solver must return a
``SolveResult`` with a partial layout without raising; the test additionally
asserts ``components_placed < components_total`` so we know the partial layout
actually happened.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import ProjectDocument, SolverOptions
from app.domain.solve import solve
from app.domain.validate import validate_layout

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
BOARD = build_half400(split_rails=True)
INDEX = BoardIndex.build(BOARD)


def _fixture_pairs() -> list[tuple[str, Path, Path]]:
    """Return [(name, fixture_path, expected_path), ...] sorted by name."""
    pairs: list[tuple[str, Path, Path]] = []
    for fixture_path in sorted(FIXTURES_DIR.glob("[0-9][0-9]-*.json")):
        if "expected" in fixture_path.name:
            continue
        name = fixture_path.stem
        expected_path = fixture_path.with_name(f"{name}.expected.json")
        if not expected_path.exists():
            msg = f"missing expected file for {name}"
            raise FileNotFoundError(msg)
        pairs.append((name, fixture_path, expected_path))
    return pairs


PAIR_IDS = [name for name, _, _ in _fixture_pairs()]


@pytest.fixture(params=_fixture_pairs(), ids=PAIR_IDS)
def fixture_pair(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Parametrised fixture that yields (name, raw_dict, expected_dict)."""
    name, fixture_path, expected_path = request.param
    raw = json.loads(fixture_path.read_text())
    expected = json.loads(expected_path.read_text())
    return name, raw, expected


def test_schema_validates(fixture_pair: tuple[str, dict[str, Any], dict[str, Any]]) -> None:
    """Every fixture's JSON must parse as a `ProjectDocument`."""
    name, raw, _expected = fixture_pair
    document = ProjectDocument.model_validate(raw)
    assert document.format == "autobreadboard-project"
    assert document.version == 1
    assert document.board.model_id == "half-400-standard-split-rails"
    # Sanity: at least one component, at least one net.
    assert document.components, f"{name} has no components"
    assert document.nets, f"{name} has no nets"


def test_roundtrip(fixture_pair: tuple[str, dict[str, Any], dict[str, Any]]) -> None:
    """``ProjectDocument.model_validate(raw).model_dump(by_alias=True) == raw`` for every fixture."""
    _name, raw, _expected = fixture_pair
    document = ProjectDocument.model_validate(raw)
    assert document.model_dump(by_alias=True) == raw


def test_solver_matches_expected(fixture_pair: tuple[str, dict[str, Any], dict[str, Any]]) -> None:
    """Run `solve` (or `validate_layout` for fixture 9) and check against `.expected.json`."""
    name, raw, expected = fixture_pair

    if name == "09-induced-short":
        # Validator-only: the pre-populated locked placements share tie-point
        # group tp-l-1 across two distinct nets → SHORT_BETWEEN_NETS.
        document = ProjectDocument.model_validate(raw)
        diagnostics, _score = validate_layout(
            BOARD,
            INDEX,
            FOOTPRINTS,
            document.components,
            document.nets,
            document.layout,
            SolverOptions(seed=12345),
        )
        codes = [d.code for d in diagnostics]
        for required in expected["requiredDiagnosticCodes"]:
            assert required in codes, f"missing required code {required!r}; in {codes}"
        return

    document = ProjectDocument.model_validate(raw)
    initial_layout = document.layout if document.layout.placements or document.layout.jumpers else None

    result = solve(
        BOARD,
        INDEX,
        FOOTPRINTS,
        document.components,
        document.nets,
        SolverOptions(seed=12345),
        initial_layout=initial_layout,
    )

    # Score checks
    score = result.score
    assert score.error_count <= expected["maxErrors"], (
        f"{name}: error_count={score.error_count} > expected maxErrors={expected['maxErrors']}"
    )
    codes = [d.code for d in result.diagnostics]
    for required in expected["requiredDiagnosticCodes"]:
        assert required in codes, f"{name}: missing required code {required!r}; in {codes}"
    for forbidden in expected["forbiddenDiagnosticCodes"]:
        assert forbidden not in codes, f"{name}: unexpected forbidden code {forbidden!r}; in {codes}"

    # netsCompleted: "all" means nets_completed == nets_total.
    if expected["netsCompleted"] == "all":
        assert score.nets_completed == score.nets_total, (
            f"{name}: nets_completed={score.nets_completed}/{score.nets_total} (expected all)"
        )
    else:
        assert score.nets_completed == expected["netsCompleted"], (
            f"{name}: nets_completed={score.nets_completed} (expected {expected['netsCompleted']})"
        )

    # componentsPlaced: expected count
    assert score.components_placed == expected["componentsPlaced"], (
        f"{name}: components_placed={score.components_placed} (expected {expected['componentsPlaced']})"
    )

    # Fixture 7 additionally checks: at least one jumper endpoint touches a rail hole.
    if name == "07-prefer-rail":
        rails = [
            j
            for j in result.layout.jumpers
            if j.start_hole_id.startswith("rail-") or j.end_hole_id.startswith("rail-")
        ]
        assert rails, (
            f"07-prefer-rail: expected at least one jumper to touch a rail hole; "
            f"got {len(result.layout.jumpers)} jumpers"
        )

    # Fixture 8 additionally asserts the partial-layout invariant directly.
    if name == "08-impossible-20-dip28":
        assert score.components_placed < score.components_total, (
            f"08: expected partial layout; components_placed={score.components_placed} == total"
        )

    # Fixture 10 asserts locked R1 + locked J_LCK are preserved byte-identical.
    if name == "10-locked-preserved":
        # R1 placement
        r1_after = next((p for p in result.layout.placements if p.component_ref == "R1"), None)
        assert r1_after is not None, "10: R1 placement missing"
        r1_before = next(p for p in document.layout.placements if p.component_ref == "R1")
        assert r1_after.anchor_hole_id == r1_before.anchor_hole_id, (
            f"10: R1 anchor moved {r1_before.anchor_hole_id!r} -> {r1_after.anchor_hole_id!r}"
        )
        assert r1_after.orientation == r1_before.orientation, (
            f"10: R1 orientation changed {r1_before.orientation} -> {r1_after.orientation}"
        )
        assert r1_after.pin_holes == r1_before.pin_holes, (
            f"10: R1 pin_holes changed {r1_before.pin_holes!r} -> {r1_after.pin_holes!r}"
        )
        # Locked jumper
        j_after = next((j for j in result.layout.jumpers if j.id == "J_LCK"), None)
        assert j_after is not None, "10: locked jumper J_LCK missing from solved layout"
        j_before = next(j for j in document.layout.jumpers if j.id == "J_LCK")
        assert j_after.id == j_before.id
        assert j_after.start_hole_id == j_before.start_hole_id
        assert j_after.end_hole_id == j_before.end_hole_id


def test_determinism_fixture4() -> None:
    """Solving fixture 4 twice with ``seed=12345`` produces byte-identical layout JSON."""
    raw = json.loads((FIXTURES_DIR / "04-74hc14-flagship.json").read_text())
    document = ProjectDocument.model_validate(raw)
    options = SolverOptions(seed=12345)
    first = solve(BOARD, INDEX, FOOTPRINTS, document.components, document.nets, options)
    second = solve(BOARD, INDEX, FOOTPRINTS, document.components, document.nets, options)
    assert first.layout.model_dump(by_alias=True) == second.layout.model_dump(by_alias=True), (
        "fixture 4 is not deterministic across two runs with seed=12345"
    )
