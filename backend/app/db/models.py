"""SQLAlchemy 2.0 ORM models for AutoBreadboard persistence.

These models are the schema of record. The Alembic migration
``alembic/versions/0001_initial.py`` mirrors the tables, indexes, and
constraints defined here; when adding or changing columns, update both files in
the same change.

Conventions:

* Primary keys are server-generated UUIDs (``gen_random_uuid()`` from
  ``pgcrypto``) except the ``solver_job_events`` bigserial log table.
* Timestamps are stored as ``TIMESTAMP WITH TIME ZONE`` with a ``now()`` server
  default.
* JSON columns use PostgreSQL ``JSONB``.
* Check constraints are listed in the assignment verbatim so the database
  enforces the same domain invariants the API does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

__all__ = [
    "BoardModelRow",
    "Export",
    "FootprintOverrideRow",
    "Layout",
    "Project",
    "ProjectRevision",
    "SolverJob",
    "SolverJobEvent",
]


class Project(Base):
    """A user-owned AutoBreadboard project.

    The mutable document (netlist + layout + settings) lives in the ``document``
    JSONB column. Concurrency is controlled by ``draft_version``; the
    repository layer increments it atomically and rejects updates that target a
    stale version.
    """

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    board_model_id: Mapped[str] = mapped_column(String, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProjectRevision(Base):
    """An immutable snapshot of a project's document at a point in time.

    The SHA-256 hash is stored alongside the JSON payload so the API can detect
    drift between the revision document and the canonical document on disk
    without recomputing.
    """

    __tablename__ = "project_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision_number", name="uq_project_revisions_project_revision"),
        Index(
            "ix_project_revisions_project_revision_desc",
            "project_id",
            text("revision_number DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    document_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Layout(Base):
    """A computed or manual layout attached to a (project, revision) pair.

    Layouts are never mutated; the solver always writes a fresh row when it
    improves on a previous result, and the editor writes a new row for each
    user-saved snapshot.
    """

    __tablename__ = "layouts"
    __table_args__ = (
        CheckConstraint("source IN ('manual','solver')", name="ck_layouts_source_allowed"),
        Index(
            "ix_layouts_project_created_desc",
            "project_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    revision_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project_revisions.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    solver_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    score: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    diagnostics: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SolverJob(Base):
    """A solver/worker job.

    ``idempotency_key`` is optional; when present, the partial unique index on
    ``(project_id, idempotency_key)`` guarantees that two retries with the same
    key collapse to a single job row. The check constraints lock the
    ``operation`` and ``status`` value sets to the closed enums the worker
    speaks.
    """

    __tablename__ = "solver_jobs"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('place','route','solve','optimize','validate','export',"
            "'trace-route','trace-solve')",
            name="ck_solver_jobs_operation_allowed",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_solver_jobs_status_allowed",
        ),
        Index(
            "ix_solver_jobs_project_created_desc",
            "project_id",
            text("created_at DESC"),
        ),
        Index("ix_solver_jobs_status", "status"),
        Index(
            "uq_solver_jobs_project_idempotency_key",
            "project_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    revision_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("project_revisions.id"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    queue_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    progress_phase: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    result_layout_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    requested_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SolverJobEvent(Base):
    """Append-only event log emitted by the worker while a job runs.

    The primary key is a bigserial so events are ordered naturally and can be
    paginated with ``id > after_id`` without timestamp races.
    """

    __tablename__ = "solver_job_events"
    __table_args__ = (Index("ix_solver_job_events_job_id_id", "job_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("solver_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    phase: Mapped[str | None] = mapped_column(Text, nullable=True)
    percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class Export(Base):
    """A rendered export artefact (SVG, PNG, PDF, JSON, BOM CSV, etc.).

    The actual file is stored in S3/MinIO; this row holds metadata, retention,
    and the lifecycle status. ``retention_until`` powers the cron purge job.
    """

    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_exports_status_allowed",
        ),
        Index(
            "ix_exports_project_created_desc",
            "project_id",
            text("created_at DESC"),
        ),
        Index("ix_exports_retention_until", "retention_until"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    revision_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    layout_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("layouts.id"), nullable=True
    )
    format: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BoardModelRow(Base):
    """Persisted record of a known board model.

    Built-in boards are upserted by the seed script at every deployment; the
    ``builtin`` flag lets the application distinguish seeded rows from
    user-imported ones. ``kind`` discriminates the board family
    (``"breadboard"`` or ``"perfboard"``) so the API can return the right
    schema and the solver can dispatch on it.
    """

    __tablename__ = "board_models"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="breadboard", server_default=text("'breadboard'")
    )
    builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FootprintOverrideRow(Base):
    """A per-project footprint override for one component.

    ``pin_map`` (when present) renames pins; otherwise the override only swaps
    the footprint id while keeping the existing pin names.
    """

    __tablename__ = "footprint_overrides"
    __table_args__ = (
        UniqueConstraint("project_id", "component_ref", name="uq_footprint_overrides_project_component"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    component_ref: Mapped[str] = mapped_column(Text, nullable=False)
    footprint_id: Mapped[str] = mapped_column(Text, nullable=False)
    pin_map: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
