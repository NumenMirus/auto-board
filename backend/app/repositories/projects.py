"""Repository for the ``projects`` table.

All functions are plain ``async`` callables taking an :class:`AsyncSession`
first; transaction boundaries are the caller's responsibility (typically the
API endpoint wraps the call in ``async with get_session()``).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project
from app.repositories.errors import ConflictError

__all__ = [
    "create_project",
    "delete_project",
    "get_project",
    "list_projects",
    "update_project_document",
]


async def create_project(
    session: AsyncSession,
    name: str,
    board_model_id: str,
    document: dict[str, Any],
) -> Project:
    """Insert a new project row and return it hydrated."""
    project = Project(
        name=name,
        board_model_id=board_model_id,
        document=document,
    )
    session.add(project)
    await session.flush()
    return project


async def get_project(session: AsyncSession, project_id: UUID) -> Project | None:
    """Return the project by id, or ``None`` when it does not exist."""
    return await session.get(Project, project_id)


async def list_projects(session: AsyncSession, limit: int, offset: int) -> tuple[list[Project], int]:
    """Return ``(items, total)`` for a paginated project listing.

    Items are ordered newest-first by ``created_at`` then ``id`` so the page
    boundary is deterministic across equal timestamps.
    """
    total_stmt = select(func.count()).select_from(Project)
    items_stmt = select(Project).order_by(Project.created_at.desc(), Project.id).limit(limit).offset(offset)
    total = (await session.execute(total_stmt)).scalar_one()
    rows = (await session.execute(items_stmt)).scalars().all()
    return list(rows), int(total)


async def update_project_document(
    session: AsyncSession,
    project_id: UUID,
    document: dict[str, Any],
    expected_version: int,
) -> Project:
    """Apply an optimistic-locked document update.

    Increments ``draft_version`` and updates ``updated_at`` only when the row's
    current ``draft_version`` matches ``expected_version``. Raises
    :class:`ConflictError` when no row matches (stale read) or when the row
    was deleted concurrently.
    """
    next_version = expected_version + 1
    stmt = (
        update(Project)
        .where(Project.id == project_id, Project.draft_version == expected_version)
        .values(document=document, draft_version=next_version, updated_at=func.now())
        .returning(Project)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        existing = await session.get(Project, project_id)
        if existing is None:
            raise ConflictError(f"project {project_id} not found")
        raise ConflictError(
            f"project {project_id} draft_version mismatch: expected {expected_version}, "
            f"actual {existing.draft_version}"
        )
    return row


async def delete_project(session: AsyncSession, project_id: UUID) -> bool:
    """Delete a project; returns ``True`` when a row was removed."""
    stmt = delete(Project).where(Project.id == project_id)
    result = await session.execute(stmt)
    rowcount: int = result.rowcount  # type: ignore[attr-defined]
    return bool(rowcount)
