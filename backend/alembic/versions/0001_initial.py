"""initial schema: projects, revisions, layouts, jobs, exports, board models

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-20 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # gen_random_uuid() lives in pgcrypto; create it before any table that
    # references it as a server default.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("board_model_id", sa.String(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column(
            "draft_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "project_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("document_sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "project_id",
            "revision_number",
            name="uq_project_revisions_project_revision",
        ),
    )
    op.create_index(
        "ix_project_revisions_project_revision_desc",
        "project_revisions",
        ["project_id", sa.text("revision_number DESC")],
    )

    op.create_table(
        "layouts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_revisions.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("solver_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("layout", postgresql.JSONB(), nullable=False),
        sa.Column("score", postgresql.JSONB(), nullable=True),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("source IN ('manual','solver')", name="ck_layouts_source_allowed"),
    )
    op.create_index(
        "ix_layouts_project_created_desc",
        "layouts",
        ["project_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "solver_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_revisions.id"),
            nullable=True,
        ),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("queue_job_id", sa.Text(), nullable=True),
        sa.Column(
            "progress_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("progress_phase", sa.Text(), nullable=True),
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("result_layout_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("trace", postgresql.JSONB(), nullable=True),
        sa.Column("timings", postgresql.JSONB(), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation IN ('place','route','solve','optimize','validate','export')",
            name="ck_solver_jobs_operation_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_solver_jobs_status_allowed",
        ),
    )
    op.create_index(
        "ix_solver_jobs_project_created_desc",
        "solver_jobs",
        ["project_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_solver_jobs_status", "solver_jobs", ["status"])
    op.create_index(
        "uq_solver_jobs_project_idempotency_key",
        "solver_jobs",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "solver_job_events",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("solver_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("percent", sa.Integer(), nullable=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_solver_job_events_job_id_id",
        "solver_job_events",
        ["job_id", "id"],
    )

    op.create_table(
        "exports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "layout_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("layouts.id"),
            nullable=True,
        ),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.Text(), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_exports_status_allowed",
        ),
    )
    op.create_index(
        "ix_exports_project_created_desc",
        "exports",
        ["project_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_exports_retention_until", "exports", ["retention_until"])

    op.create_table(
        "board_models",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "footprint_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("component_ref", sa.Text(), nullable=False),
        sa.Column("footprint_id", sa.Text(), nullable=False),
        sa.Column("pin_map", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "project_id",
            "component_ref",
            name="uq_footprint_overrides_project_component",
        ),
    )


def downgrade() -> None:
    # Drop in reverse dependency order: child tables first, then parents.
    op.drop_table("footprint_overrides")
    op.drop_table("board_models")
    op.drop_index("ix_exports_retention_until", table_name="exports")
    op.drop_index("ix_exports_project_created_desc", table_name="exports")
    op.drop_table("exports")
    op.drop_index("ix_solver_job_events_job_id_id", table_name="solver_job_events")
    op.drop_table("solver_job_events")
    op.drop_index("uq_solver_jobs_project_idempotency_key", table_name="solver_jobs")
    op.drop_index("ix_solver_jobs_status", table_name="solver_jobs")
    op.drop_index("ix_solver_jobs_project_created_desc", table_name="solver_jobs")
    op.drop_table("solver_jobs")
    op.drop_index("ix_layouts_project_created_desc", table_name="layouts")
    op.drop_table("layouts")
    op.drop_index(
        "ix_project_revisions_project_revision_desc",
        table_name="project_revisions",
    )
    op.drop_table("project_revisions")
    op.drop_table("projects")
    # pgcrypto is intentionally left in place; other tooling may depend on it.
