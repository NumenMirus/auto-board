"""Integration tests for the persistence repositories.

Each test needs a live PostgreSQL: when ``DATABASE_URL`` is unset the whole
module is skipped so the test runner stays green on machines without one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Layout, ProjectRevision, SolverJob
from app.db.session import reset_engine
from app.repositories.errors import ConflictError
from app.repositories.jobs import create_job, get_job_by_idempotency_key
from app.repositories.layouts import create_layout
from app.repositories.projects import create_project, delete_project, update_project_document
from app.repositories.revisions import create_revision, list_revisions

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires database",
)


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a clean session against a freshly-recreated schema.

    The fixture wipes the public schema so individual tests stay independent;
    it uses the DDL emitted by ``Base.metadata.create_all`` rather than
    invoking Alembic so it doesn't depend on the migration having been run.
    """
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with factory() as session:
            yield session
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()
        reset_engine()


async def test_optimistic_lock_conflict_raises_conflict_error(
    db_session: AsyncSession,
) -> None:
    """A stale ``expected_version`` is rejected with :class:`ConflictError`."""
    project = await create_project(
        db_session,
        name="p",
        board_model_id="half-400-standard-split-rails",
        document={"x": 1},
    )
    await db_session.commit()
    project_id: UUID = project.id
    assert project.draft_version == 1

    # First writer bumps the version from 1 -> 2.
    updated = await update_project_document(db_session, project_id, {"x": 2}, expected_version=1)
    await db_session.commit()
    assert updated.draft_version == 2

    # Second writer still thinks it's at 1: must be rejected.
    with pytest.raises(ConflictError):
        await update_project_document(db_session, project_id, {"x": 3}, expected_version=1)
    await db_session.rollback()


async def test_revision_numbering_contiguous_per_project(
    db_session: AsyncSession,
) -> None:
    """Three revisions for one project number exactly 1, 2, 3."""
    project = await create_project(
        db_session,
        name="p",
        board_model_id="half-400-standard-split-rails",
        document={"x": 0},
    )
    await db_session.commit()
    project_id = project.id

    revs = []
    for i in range(3):
        rev = await create_revision(db_session, project_id, {"x": i})
        revs.append(rev)
    await db_session.commit()

    numbers = sorted(r.revision_number for r in revs)
    assert numbers == [1, 2, 3]

    # Same project, second revision must pick up after the third.
    extra = await create_revision(db_session, project_id, {"x": 99})
    await db_session.commit()
    assert extra.revision_number == 4

    listed = await list_revisions(db_session, project_id)
    listed_numbers = sorted(r.revision_number for r in listed)
    assert listed_numbers == [1, 2, 3, 4]


async def test_solver_jobs_idempotency_unique_constraint_rejects_duplicate(
    db_session: AsyncSession,
) -> None:
    """A second ``solver_jobs`` row with the same ``(project_id, idempotency_key)``
    raises ``IntegrityError`` (the underlying driver wraps the partial unique
    index violation).

    ``get_job_by_idempotency_key`` then returns the first row.
    """
    project = await create_project(
        db_session,
        name="p",
        board_model_id="half-400-standard-split-rails",
        document={"x": 0},
    )
    await db_session.commit()
    project_id = project.id

    idem = "key-" + uuid4().hex
    first = await create_job(
        db_session,
        project_id=project_id,
        revision_id=None,
        operation="solve",
        seed=12345,
        options={"preset": "balanced"},
        idempotency_key=idem,
        requested_by=None,
    )
    await db_session.commit()
    assert first.idempotency_key == idem

    # Same key, second insert: must violate the partial unique index.
    with pytest.raises(IntegrityError):
        await create_job(
            db_session,
            project_id=project_id,
            revision_id=None,
            operation="solve",
            seed=67890,
            options={"preset": "fast"},
            idempotency_key=idem,
            requested_by=None,
        )
    await db_session.rollback()

    # Idempotency probe returns the first row.
    found = await get_job_by_idempotency_key(db_session, project_id, idem)
    assert found is not None
    assert found.id == first.id
    assert found.seed == 12345


async def test_delete_project_cascades_dependent_rows(
    db_session: AsyncSession,
) -> None:
    """Deleting a project also removes its revisions, solver jobs, and layouts —
    the FKs on those tables carry ``ON DELETE CASCADE`` (see
    `alembic/versions/0005_project_delete_cascade.py`)."""
    project = await create_project(
        db_session,
        name="p",
        board_model_id="half-400-standard-split-rails",
        document={"x": 0},
    )
    await db_session.commit()
    project_id = project.id

    revision = await create_revision(db_session, project_id, {"x": 1})
    await db_session.commit()

    job = await create_job(
        db_session,
        project_id=project_id,
        revision_id=revision.id,
        operation="solve",
        seed=1,
        options={"preset": "balanced"},
        idempotency_key=None,
        requested_by=None,
    )
    await db_session.commit()

    await create_layout(
        db_session,
        project_id=project_id,
        revision_id=revision.id,
        source="solver",
        solver_job_id=job.id,
        layout={},
        score=None,
        diagnostics=None,
    )
    await db_session.commit()

    assert await delete_project(db_session, project_id) is True
    await db_session.commit()

    remaining_jobs = (
        await db_session.execute(select(SolverJob).where(SolverJob.project_id == project_id))
    ).scalars().all()
    remaining_layouts = (
        await db_session.execute(select(Layout).where(Layout.project_id == project_id))
    ).scalars().all()
    remaining_revisions = (
        await db_session.execute(select(ProjectRevision).where(ProjectRevision.project_id == project_id))
    ).scalars().all()
    assert remaining_jobs == []
    assert remaining_layouts == []
    assert remaining_revisions == []

    # A second delete of the same (now-gone) project must report no row removed.
    assert await delete_project(db_session, project_id) is False


# ---------------------------------------------------------------------------
# Helpers shared by future tests in this module.
# ---------------------------------------------------------------------------


def _empty_doc() -> dict[str, Any]:
    return {"format": "autobreadboard-project", "version": 1}
