"""extend solver_jobs.operation check constraint to include trace-route / trace-solve

Revision ID: 0003_trace_operations
Revises: 0002_perfboard_kind
Create Date: 2026-09-20 17:45:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_trace_operations"
down_revision: str | None = "0002_perfboard_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_solver_jobs_operation_allowed", "solver_jobs", type_="check"
    )
    op.create_check_constraint(
        "ck_solver_jobs_operation_allowed",
        "solver_jobs",
        "operation IN ('place','route','solve','optimize','validate','export','trace-route','trace-solve')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_solver_jobs_operation_allowed", "solver_jobs", type_="check"
    )
    op.create_check_constraint(
        "ck_solver_jobs_operation_allowed",
        "solver_jobs",
        "operation IN ('place','route','solve','optimize','validate','export')",
    )
