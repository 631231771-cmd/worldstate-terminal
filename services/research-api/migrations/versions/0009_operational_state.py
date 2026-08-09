"""Persist daily world-state snapshots and user watchlist entries."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_operational_state"
down_revision: str | None = "0008_thesis_book"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("world_state_snapshots"):
        op.create_table(
        "world_state_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("methodology_version", sa.String(length=64), nullable=False),
        sa.Column("data_mode", sa.String(length=16), nullable=False, server_default="observed"),
        sa.Column("dimensions_json", sa.JSON(), nullable=False),
        sa.Column("regime_json", sa.JSON(), nullable=False),
        sa.Column("top_changes_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("data_gaps_json", sa.JSON(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date", "data_mode", name="uq_world_state_snapshot_day_mode"),
        )
    if not any(
        item.get("name") == "ix_world_state_snapshots_date"
        for item in inspector.get_indexes("world_state_snapshots")
    ):
        op.create_index("ix_world_state_snapshots_date", "world_state_snapshots", ["snapshot_date"])
    if not inspector.has_table("watchlist_items"):
        op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("item_key", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("data_mode", sa.String(length=16), nullable=False, server_default="observed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_type", "item_key", name="uq_watchlist_item_type_key"),
        )
    if not any(
        item.get("name") == "ix_watchlist_items_updated"
        for item in inspector.get_indexes("watchlist_items")
    ):
        op.create_index("ix_watchlist_items_updated", "watchlist_items", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_updated", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_index("ix_world_state_snapshots_date", table_name="world_state_snapshots")
    op.drop_table("world_state_snapshots")
