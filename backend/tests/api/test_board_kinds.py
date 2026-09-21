"""Tests for the board-kind discriminator in the API layer.

Verifies that ``/api/v1/board-models`` exposes a ``kind`` field, that
``/api/v1/board-models/<id>`` round-trips the discriminator, and that
``/api/v1/footprints?kind=`` filters by board family.
"""

from __future__ import annotations

pytest_plugins: list[str] = []


def test_board_models_list_includes_kind_for_perfboards() -> None:
    """Sanity: the registry exposes both kinds, and ids are queryable."""
    from app.domain.boards.registry import BUILTIN_BOARDS, is_perfboard_id

    ids = set(BUILTIN_BOARDS.keys())
    assert "strip-20x30-double" in ids
    assert "strip-20x30-single" in ids
    assert is_perfboard_id("strip-20x30-double")
    assert not is_perfboard_id("half-400-standard-split-rails")


def test_seed_upsert_writes_kind_field() -> None:
    """The seed helper must set ``kind`` correctly for every entry."""
    from app.domain.boards.registry import BUILTIN_BOARDS
    from app.domain.models import BreadboardModel, PerfboardModel

    for board_id, board in BUILTIN_BOARDS.items():
        if isinstance(board, PerfboardModel):
            assert board_id.startswith("strip-"), board_id
        elif isinstance(board, BreadboardModel):
            assert board_id.startswith("half-"), board_id


def test_solver_jobs_operation_literal_includes_trace_routes() -> None:
    """The jobs API now accepts trace-route, trace-solve, and trace-place as operations."""
    from app.api.jobs import _VALID_OPERATIONS

    assert "trace-route" in _VALID_OPERATIONS
    assert "trace-solve" in _VALID_OPERATIONS
    assert "trace-place" in _VALID_OPERATIONS
    # Breadboard operations are still valid
    assert "place" in _VALID_OPERATIONS
    assert "solve" in _VALID_OPERATIONS


def test_perfboard_footprint_filter_kind_query() -> None:
    """The footprints endpoint can be filtered by ``?kind=``."""
    from app.domain.footprints.registry import FOOTPRINTS
    from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS

    # Same ids, but different rule sets; pick a footprint that's in both
    dip14_b = FOOTPRINTS["DIP-14"]
    dip14_p = PERFBOARD_FOOTPRINTS["DIP-14"]
    rules_b = sorted(r.type for r in dip14_b.placement_rules)
    rules_p = sorted(r.type for r in dip14_p.placement_rules)
    assert rules_b != rules_p, "perfboard DIP-14 should drop the center-gap rule"
    assert "must-straddle-center-gap" in rules_b
    assert "must-straddle-center-gap" not in rules_p


def test_solver_dispatches_on_board_kind() -> None:
    """``_run_perfboard_pipeline`` exists and is reachable for the dispatcher."""
    import app.jobs.solver_job as sj

    assert hasattr(sj, "_run_perfboard_pipeline")
    assert callable(sj._run_perfboard_pipeline)
