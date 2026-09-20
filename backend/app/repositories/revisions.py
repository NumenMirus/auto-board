"""Repository for the ``project_revisions`` table.

Revisions are immutable: a new row is appended each time the API freezes the
current document. ``revision_number`` is dense per project, computed as
``max(revision_number) + 1``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ProjectRevision

__all__ = ["create_revision", "get_revision", "list_revisions"]


def _document_sha256(document: dict[str, Any]) -> str:
    """Stable SHA-256 of a document dict (``sort_keys`` canonicalisation)."""
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def create_revision(
    session: AsyncSession,
    project_id: UUID,
    document: dict[str, Any],
) -> ProjectRevision:
    """Append a new revision to ``project_id`` with ``revision_number = max+1``.

    Two concurrent calls serialise via PostgreSQL's default transaction
    isolation (read committed): the second sees the first's insert and writes
    ``max+2``.
    """
    max_stmt = select(func.coalesce(func.max(ProjectRevision.revision_number), 0)).where(
        ProjectRevision.project_id == project_id
    )
    current_max = (await session.execute(max_stmt)).scalar_one()
    revision_number = int(current_max) + 1
    revision = ProjectRevision(
        project_id=project_id,
        revision_number=revision_number,
        document=document,
        document_sha256=_document_sha256(document),
    )
    session.add(revision)
    await session.flush()
    return revision


async def get_revision(session: AsyncSession, revision_id: UUID) -> ProjectRevision | None:
    """Return a revision by id."""
    return await session.get(ProjectRevision, revision_id)


async def list_revisions(session: AsyncSession, project_id: UUID) -> list[ProjectRevision]:
    """List all revisions for a project, newest first."""
    stmt = (
        select(ProjectRevision)
        .where(ProjectRevision.project_id == project_id)
        .order_by(ProjectRevision.revision_number.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
