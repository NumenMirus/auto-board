"""Repository for the ``exports`` table.

Exports track the lifecycle of a rendered artefact (SVG/PNG/PDF/JSON/BOM CSV,
etc.) from creation in ``pending`` state through ``running`` and either
``succeeded`` or ``failed``. Successful rows hold the S3 storage key, content
type, size, checksum, and a ``retention_until`` deadline the cron purge job
honours.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Export

__all__ = [
    "create_export",
    "get_export",
    "list_expired_exports",
    "update_export",
]


async def create_export(
    session: AsyncSession,
    project_id: UUID,
    revision_id: UUID | None,
    layout_id: UUID | None,
    format: str,
    content_type: str,
) -> Export:
    """Insert a new ``exports`` row in status ``'pending'``."""
    row = Export(
        project_id=project_id,
        revision_id=revision_id,
        layout_id=layout_id,
        format=format,
        content_type=content_type,
        status="pending",
    )
    session.add(row)
    await session.flush()
    return row


async def get_export(session: AsyncSession, export_id: UUID) -> Export | None:
    """Return an export by id."""
    return await session.get(Export, export_id)


async def update_export(
    session: AsyncSession,
    export_id: UUID,
    **fields: Any,
) -> Export:
    """Update arbitrary export fields and return the refreshed row.

    When ``status`` transitions into ``'succeeded'`` or ``'failed'`` and no
    ``completed_at`` was provided, the timestamp is recorded automatically so
    callers don't have to remember.
    """
    values: dict[str, Any] = dict(fields)
    status = values.get("status")
    if status in {"succeeded", "failed"} and "completed_at" not in values:
        values["completed_at"] = datetime.now(tz=UTC)
    stmt = update(Export).where(Export.id == export_id).values(**values).returning(Export)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise LookupError(f"export {export_id} not found")
    return row


async def list_expired_exports(session: AsyncSession, before: datetime) -> list[Export]:
    """Return exports whose ``retention_until`` is strictly before ``before``."""
    stmt = (
        select(Export)
        .where(Export.retention_until.is_not(None))
        .where(Export.retention_until < before)
        .order_by(Export.retention_until)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
