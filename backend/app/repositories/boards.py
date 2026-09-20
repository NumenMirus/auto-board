"""Repository for the ``board_models`` table.

Holds the canonical board definitions used by the API: built-in boards are
seeded by :func:`app.db.seed.seed_board_models` at deployment time; users can
import additional boards which are stored here with ``builtin=false``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BoardModelRow

__all__ = ["get_board_model", "list_board_models", "upsert_board_model"]


async def get_board_model(session: AsyncSession, board_id: str) -> BoardModelRow | None:
    """Return the board row by id, or ``None`` when unknown."""
    return await session.get(BoardModelRow, board_id)


async def upsert_board_model(
    session: AsyncSession,
    id: str,
    version: int,
    definition: dict[str, Any],
    builtin: bool,
    *,
    kind: str = "breadboard",
) -> BoardModelRow:
    """Insert-or-update a board row keyed by ``id``.

    On conflict, ``version``, ``definition`` and ``kind`` are refreshed and
    ``builtin`` is set to the new value so a previously user-imported board
    can be re-promoted to builtin when the seed script picks it up.
    """
    stmt = pg_insert(BoardModelRow).values(
        id=id,
        version=version,
        definition=definition,
        kind=kind,
        builtin=builtin,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[BoardModelRow.id],
        set_={
            "version": stmt.excluded.version,
            "definition": stmt.excluded.definition,
            "kind": stmt.excluded.kind,
            "builtin": stmt.excluded.builtin,
        },
    )
    await session.execute(stmt)
    row = await session.get(BoardModelRow, id)
    if row is None:
        raise RuntimeError(f"upsert of board model {id!r} did not return a row")
    return row


async def list_board_models(session: AsyncSession) -> list[BoardModelRow]:
    """Return every board model, alphabetically by id."""
    stmt = select(BoardModelRow).order_by(BoardModelRow.id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
