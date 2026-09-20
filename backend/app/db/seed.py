"""Seed built-in board models into the ``board_models`` table.

Called from the Helm migration Job (``alembic upgrade head && python -m app.db.seed``)
and from the dev ``make seed`` target. The function is idempotent: re-running
it after a code update refreshes ``version`` and ``definition`` for every
built-in board without touching user-imported ones (those keep ``builtin=false``
and a different id namespace in practice).

Perfboard vs breadboard discrimination is via the ``kind`` column on
``board_models``: ``"breadboard"`` for entries in
:data:`app.domain.boards.registry.BUILTIN_BOARDS` whose id starts with
``half-`` and ``"perfboard"`` for entries whose id starts with ``strip-``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.boards.registry import BUILTIN_BOARDS
from app.domain.models import BreadboardModel, PerfboardModel
from app.repositories.boards import upsert_board_model

__all__ = ["seed_board_models"]


def _kind_of(board: object) -> str:
    if isinstance(board, PerfboardModel):
        return "perfboard"
    if isinstance(board, BreadboardModel):
        return "breadboard"
    # Defensive fallback — id-based dispatch.
    bid = getattr(board, "id", "")
    if bid.startswith("strip-"):
        return "perfboard"
    return "breadboard"


async def seed_board_models(session: AsyncSession) -> None:
    """Upsert every entry in :data:`BUILTIN_BOARDS` and commit."""
    for _board_id, board in BUILTIN_BOARDS.items():
        await upsert_board_model(
            session,
            id=board.id,
            version=board.version,
            definition=board.model_dump(by_alias=True),
            builtin=True,
            kind=_kind_of(board),
        )
    await session.commit()


async def _main() -> None:
    from app.db.session import get_session

    async with get_session() as session:
        await seed_board_models(session)


if __name__ == "__main__":
    asyncio.run(_main())
