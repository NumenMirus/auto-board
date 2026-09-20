"""Cron-style retention purge for expired exports.

Walks the ``exports`` table for rows whose ``retention_until`` is in the past,
deletes the underlying S3 object, and removes the row. Runs hourly at minute
``7`` via :func:`arq.cron.cron`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db.session import get_session
from app.repositories import exports as exports_repo
from app.services import storage

__all__ = ["purge_expired_exports"]


async def purge_expired_exports(ctx: dict[str, Any]) -> None:
    """Delete S3 objects and rows for every export past its retention deadline."""
    now = datetime.now(tz=UTC)
    async with get_session() as session:
        rows = await exports_repo.list_expired_exports(session, now)
    if not rows:
        return

    for row in rows:
        key = row.storage_key
        row_id = row.id
        if key is not None:
            try:
                await storage.delete(key)
            except Exception as exc:
                get_logger().warning(
                    "export delete failed",
                    export_id=str(row_id),
                    key=key,
                    error=str(exc),
                )
        async with get_session() as session:
            current = await exports_repo.get_export(session, row_id)
            if current is None:
                continue
            await session.delete(current)
