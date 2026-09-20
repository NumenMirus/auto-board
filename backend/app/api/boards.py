"""Board-model and footprint registry endpoints.

Read-only: the data is sourced from the built-in registries plus the seeded
``board_models`` rows in the database. No writes are exposed here.
"""

from __future__ import annotations

from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json

from app.core.errors import AppError
from app.db.session import get_session
from app.domain.boards.registry import BUILTIN_BOARDS, get_board_model
from app.domain.errors import InvalidInput
from app.domain.footprints.registry import FOOTPRINTS
from app.repositories import boards as boards_repo

__all__ = ["bp"]


bp = Blueprint("boards", url_prefix="/api/v1")


def _board_summary(board_id: str) -> dict[str, object]:
    board = BUILTIN_BOARDS[board_id]
    dumped = board.model_dump(by_alias=True)
    return {
        "id": dumped["id"],
        "version": dumped["version"],
        "metadata": dumped["metadata"],
    }


@bp.get("/board-models")
async def list_board_models(_: Request) -> HTTPResponse:
    """List every known board model with its id, version and metadata."""
    async with get_session() as session:
        rows = await boards_repo.list_board_models(session)
    # Prefer the database view when seeded; fall back to the built-in registry.
    if rows:
        items: list[dict[str, object]] = []
        for row in rows:
            definition = row.definition
            items.append(
                {
                    "id": row.id,
                    "version": row.version,
                    "metadata": definition.get("metadata", {}),
                }
            )
    else:
        items = [_board_summary(bid) for bid in sorted(BUILTIN_BOARDS)]
    return json(items, status=200)


@bp.get("/board-models/<board_id>")
async def get_board(_: Request, board_id: str) -> HTTPResponse:
    """Return a single board model by id, full definition."""
    try:
        board = get_board_model(board_id)
    except InvalidInput as exc:
        raise AppError("UNKNOWN_BOARD_MODEL", str(exc), status=404) from exc
    # The DB row, when present, is the canonical definition; else return the built-in.
    async with get_session() as session:
        row = await boards_repo.get_board_model(session, board_id)
    if row is not None:
        return json(row.definition, status=200)
    return json(board.model_dump(by_alias=True), status=200)


@bp.get("/footprints")
async def list_footprints(_: Request) -> HTTPResponse:
    """List every registered footprint."""
    return json([fp.model_dump(by_alias=True) for fp in FOOTPRINTS.values()], status=200)
