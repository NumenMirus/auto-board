"""extend solver_jobs.operation check constraint to include trace-place

Revision ID: 0004_trace_place
Revises: 0003_trace_operations
Create Date: 2026-09-21 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_trace_place"
down_revision: str | None = "0003_trace_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_solver_jobs_operation_allowed", "solver_jobs", type_="check"
    )
    op.create_check_constraint(
        "ck_solver_jobs_operation_allowed",
        "solver_jobs",
        "operation IN ('place','route','solve','optimize','validate','export','trace-route','trace-solve','trace-place')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_solver_jobs_operation_allowed", "solver_jobs", type_="check"
    )
    op.create_check_constraint(
        "ck_solver_jobs_operation_allowed",
        "solver_jobs",
        "operation IN ('place','route','solve','optimize','validate','export','trace-route','trace-solve')",
    )
