"""add kind column to board_models for breadboard/perfboard discrimination

Revision ID: 0002_perfboard_kind
Revises: 0001_initial
Create Date: 2026-09-20 17:30:00

Adds a ``kind`` column to ``board_models`` discriminating the two board
families (``"breadboard"`` or ``"perfboard"``). Existing rows are back-filled
to ``"breadboard"`` since perfboards are new and the only ones in the seed
table are explicitly written with the right value on upsert.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_perfboard_kind"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "board_models",
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'breadboard'"),
        ),
    )
    # Backfill: every existing row was a breadboard (perfboards are new)
    op.execute("UPDATE board_models SET kind = 'breadboard' WHERE kind IS NULL")
    # A CHECK constraint keeps future inserts honest.
    op.create_check_constraint(
        "board_models_kind_check",
        "board_models",
        "kind IN ('breadboard', 'perfboard')",
    )


def downgrade() -> None:
    op.drop_constraint("board_models_kind_check", "board_models", type_="check")
    op.drop_column("board_models", "kind")
