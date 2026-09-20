"""Repository for the ``layouts`` table.

Layouts are append-only — both the solver and the editor always write a fresh
row rather than mutating an existing one — so this module exposes only
``create_layout`` and ``get_layout``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Layout

__all__ = ["create_layout", "get_layout"]


async def create_layout(
    session: AsyncSession,
    project_id: UUID,
    revision_id: UUID | None,
    source: str,
    solver_job_id: UUID | None,
    layout: dict[str, Any],
    score: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]] | None,
) -> Layout:
    """Insert a new layout row and return it hydrated.

    ``source`` is constrained at the database level to ``'manual' | 'solver'``;
    the caller is expected to pass a valid value.
    """
    row = Layout(
        project_id=project_id,
        revision_id=revision_id,
        source=source,
        solver_job_id=solver_job_id,
        layout=layout,
        score=score,
        diagnostics=diagnostics,
    )
    session.add(row)
    await session.flush()
    return row


async def get_layout(session: AsyncSession, layout_id: UUID) -> Layout | None:
    """Return a layout by id."""
    return await session.get(Layout, layout_id)
