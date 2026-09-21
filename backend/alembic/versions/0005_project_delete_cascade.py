"""add ON DELETE CASCADE to every foreign key that references projects/layouts, so
deleting a project also removes its layouts, solver jobs, exports, and footprint
overrides

Revision ID: 0005_project_delete_cascade
Revises: 0004_trace_place
Create Date: 2026-09-21 00:05:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_project_delete_cascade"
down_revision: str | None = "0004_trace_place"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (constraint_name, table, column, referenced_table)
_CASCADES: list[tuple[str, str, str, str]] = [
    ("layouts_project_id_fkey", "layouts", "project_id", "projects"),
    ("layouts_revision_id_fkey", "layouts", "revision_id", "project_revisions"),
    ("solver_jobs_project_id_fkey", "solver_jobs", "project_id", "projects"),
    ("solver_jobs_revision_id_fkey", "solver_jobs", "revision_id", "project_revisions"),
    ("exports_project_id_fkey", "exports", "project_id", "projects"),
    ("exports_layout_id_fkey", "exports", "layout_id", "layouts"),
    ("footprint_overrides_project_id_fkey", "footprint_overrides", "project_id", "projects"),
]


def upgrade() -> None:
    for name, table, column, ref_table in _CASCADES:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref_table, [column], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    for name, table, column, ref_table in _CASCADES:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, ref_table, [column], ["id"])
