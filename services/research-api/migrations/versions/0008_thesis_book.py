"""Add the personal research thesis book."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_thesis_book"
down_revision: str | None = "0007_truthfulness_stabilization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "theses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("horizon", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("entities_json", sa.JSON(), nullable=False),
        sa.Column("related_states_json", sa.JSON(), nullable=False),
        sa.Column("supporting_evidence_json", sa.JSON(), nullable=False),
        sa.Column("contradicting_evidence_json", sa.JSON(), nullable=False),
        sa.Column("confirmation_conditions_json", sa.JSON(), nullable=False),
        sa.Column("falsification_conditions_json", sa.JSON(), nullable=False),
        sa.Column("watch_variables_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("history_json", sa.JSON(), nullable=False),
        sa.Column("data_mode", sa.String(length=16), nullable=False, server_default="observed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active','paused','falsified','confirmed','archived')",
            name="ck_theses_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_theses_status_updated", "theses", ["status", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_theses_status_updated", table_name="theses")
    op.drop_table("theses")

