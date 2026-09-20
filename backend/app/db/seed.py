"""Seed built-in board models into the ``board_models`` table.

Called from the Helm migration Job (``alembic upgrade head && python -m app.db.seed``)
and from the dev ``make seed`` target. The function is idempotent: re-running
it after a code update refreshes ``version`` and ``definition`` for every
built-in board without touching user-imported ones (those keep ``builtin=false``
and a different id namespace in practice).
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.boards.registry import BUILTIN_BOARDS
from app.repositories.boards import upsert_board_model

__all__ = ["seed_board_models"]


async def seed_board_models(session: AsyncSession) -> None:
    """Upsert every entry in :data:`BUILTIN_BOARDS` and commit."""
    for _board_id, board in BUILTIN_BOARDS.items():
        await upsert_board_model(
            session,
            id=board.id,
            version=board.version,
            definition=board.model_dump(by_alias=True),
            builtin=True,
        )
    await session.commit()


async def _main() -> None:
    from app.db.session import get_session

    async with get_session() as session:
        await seed_board_models(session)


if __name__ == "__main__":
    asyncio.run(_main())
