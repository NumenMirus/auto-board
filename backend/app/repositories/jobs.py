"""Repository for the ``solver_jobs`` and ``solver_job_events`` tables.

The jobs table carries lifecycle metadata; the events table is an append-only
log of progress messages emitted by the worker. ``update_job_status`` is the
single chokepoint that records ``started_at`` / ``finished_at`` so those
timestamps are written exactly once and only at the right transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverJob, SolverJobEvent

__all__ = [
    "append_job_event",
    "create_job",
    "get_job",
    "get_job_by_idempotency_key",
    "list_job_events",
    "update_job_status",
]

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})


async def create_job(
    session: AsyncSession,
    project_id: UUID,
    revision_id: UUID | None,
    operation: str,
    seed: int | None,
    options: dict[str, Any],
    idempotency_key: str | None,
    requested_by: UUID | None,
) -> SolverJob:
    """Insert a new ``solver_jobs`` row in status ``'queued'``.

    The unique partial index on ``(project_id, idempotency_key)`` will reject
    duplicate keys with an ``IntegrityError``; callers that want idempotent
    enqueue must probe with :func:`get_job_by_idempotency_key` first.
    """
    job = SolverJob(
        project_id=project_id,
        revision_id=revision_id,
        operation=operation,
        status="queued",
        seed=seed,
        options=options,
        idempotency_key=idempotency_key,
        requested_by=requested_by,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: UUID) -> SolverJob | None:
    """Return a job by id."""
    return await session.get(SolverJob, job_id)


async def get_job_by_idempotency_key(
    session: AsyncSession, project_id: UUID, idempotency_key: str
) -> SolverJob | None:
    """Return the job for ``(project_id, idempotency_key)`` or ``None``."""
    stmt = select(SolverJob).where(
        SolverJob.project_id == project_id,
        SolverJob.idempotency_key == idempotency_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_job_status(
    session: AsyncSession,
    job_id: UUID,
    status: str,
    **fields: Any,
) -> SolverJob:
    """Update ``status`` and any additional keyword fields, then return the job.

    Side effects: records ``started_at`` when transitioning into ``'running'``
    and ``finished_at`` when transitioning into a terminal status
    (``succeeded``, ``failed``, ``cancelled``) — but only when the timestamp is
    not already set, so rerunning the same transition is a no-op.
    """
    values: dict[str, Any] = {"status": status, **fields}
    if status == "running" and "started_at" not in fields:
        values["started_at"] = datetime.now(tz=UTC)
    if status in _TERMINAL_STATUSES and "finished_at" not in fields:
        values["finished_at"] = datetime.now(tz=UTC)
    stmt = update(SolverJob).where(SolverJob.id == job_id).values(**values).returning(SolverJob)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise LookupError(f"solver job {job_id} not found")
    return row


async def append_job_event(
    session: AsyncSession,
    job_id: UUID,
    phase: str | None,
    percent: int | None,
    level: str,
    code: str | None,
    message: str,
) -> SolverJobEvent:
    """Insert a single progress event row."""
    event = SolverJobEvent(
        job_id=job_id,
        phase=phase,
        percent=percent,
        level=level,
        code=code,
        message=message,
    )
    session.add(event)
    await session.flush()
    return event


async def list_job_events(session: AsyncSession, job_id: UUID, after_id: int | None) -> list[SolverJobEvent]:
    """Return events for ``job_id`` with ``id > after_id`` (or all when ``None``)."""
    stmt = select(SolverJobEvent).where(SolverJobEvent.job_id == job_id)
    if after_id is not None:
        stmt = stmt.where(SolverJobEvent.id > after_id)
    stmt = stmt.order_by(SolverJobEvent.id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)
