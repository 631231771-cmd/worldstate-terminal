"""Repair timestamp defaults for operational state tables created by 0009."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_operational_state_defaults"
down_revision: str | None = "0009_operational_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("world_state_snapshots"):
        with op.batch_alter_table("world_state_snapshots", recreate="always") as batch:
            batch.alter_column(
                "created_at", existing_type=sa.DateTime(timezone=True),
                server_default=sa.func.now(), existing_nullable=False,
            )
    if inspector.has_table("watchlist_items"):
        with op.batch_alter_table("watchlist_items", recreate="always") as batch:
            batch.alter_column(
                "created_at", existing_type=sa.DateTime(timezone=True),
                server_default=sa.func.now(), existing_nullable=False,
            )
            batch.alter_column(
                "updated_at", existing_type=sa.DateTime(timezone=True),
                server_default=sa.func.now(), existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("world_state_snapshots"):
        with op.batch_alter_table("world_state_snapshots", recreate="always") as batch:
            batch.alter_column(
                "created_at", existing_type=sa.DateTime(timezone=True),
                server_default=None, existing_nullable=False,
            )
    if inspector.has_table("watchlist_items"):
        with op.batch_alter_table("watchlist_items", recreate="always") as batch:
            batch.alter_column(
                "created_at", existing_type=sa.DateTime(timezone=True),
                server_default=None, existing_nullable=False,
            )
            batch.alter_column(
                "updated_at", existing_type=sa.DateTime(timezone=True),
                server_default=None, existing_nullable=False,
            )
