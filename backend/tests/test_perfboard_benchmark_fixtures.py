from __future__ import annotations

from app.domain.boards.registry import get_board_model
from app.domain.models import PerfboardModel, ProjectDocument
from scripts.benchmark_placement import load_fixture_documents


def test_perfboard_benchmark_fixture_corpus_is_schema_valid() -> None:
    docs = load_fixture_documents()
    assert len(docs) >= 10
    for name, document in docs.items():
        raw = document.model_dump(by_alias=True)
        reparsed = ProjectDocument.model_validate(raw)
        assert reparsed.format == "autobreadboard-project"
        assert reparsed.components, f"{name} has no components"
        assert reparsed.nets, f"{name} has no nets"


def test_perfboard_benchmark_fixture_corpus_uses_perfboards() -> None:
    docs = load_fixture_documents()
    for name, document in docs.items():
        board = get_board_model(document.board.model_id)
        assert isinstance(board, PerfboardModel), f"{name} is not a perfboard fixture"
        assert document.layout.board_id == document.board.model_id
