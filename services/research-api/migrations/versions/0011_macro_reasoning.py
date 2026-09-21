"""Add source, author-claim, and mechanism-assessment persistence."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_macro_reasoning"
down_revision: str | None = "0010_operational_state_defaults"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("research_sources"):
        op.create_table(
            "research_sources",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("title", sa.String(length=512), nullable=False),
            sa.Column("author", sa.String(length=255), nullable=False),
            sa.Column("source_type", sa.String(length=64), nullable=False),
            sa.Column("source_url", sa.String(length=2048), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column("data_mode", sa.String(length=16), nullable=False, server_default="observed"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "data_mode IN ('observed','fixture')", name="ck_research_sources_data_mode"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_research_sources_retrieved", "research_sources", ["retrieved_at"])
    if not inspector.has_table("author_claims"):
        op.create_table(
            "author_claims",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("source_id", sa.Uuid(), nullable=False),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("exact_quote", sa.Text(), nullable=False),
            sa.Column("extraction_method", sa.String(length=32), nullable=False),
            sa.Column("extractor_model", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("mechanism_key", sa.String(length=128), nullable=True),
            sa.Column("mechanism_version", sa.String(length=32), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_by", sa.String(length=128), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("data_mode", sa.String(length=16), nullable=False, server_default="observed"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.CheckConstraint(
                "status IN ('draft','confirmed','rejected')", name="ck_author_claims_status"
            ),
            sa.CheckConstraint(
                "extraction_method IN ('manual','ai')",
                name="ck_author_claims_extraction_method",
            ),
            sa.ForeignKeyConstraint(["source_id"], ["research_sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_author_claims_source_status", "author_claims", ["source_id", "status"])
    if not inspector.has_table("mechanism_assessments"):
        op.create_table(
            "mechanism_assessments",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("claim_id", sa.Uuid(), nullable=False),
            sa.Column("playbook_key", sa.String(length=128), nullable=False),
            sa.Column("playbook_version", sa.String(length=32), nullable=False),
            sa.Column("playbook_hash", sa.String(length=64), nullable=False),
            sa.Column("primary_mechanism_key", sa.String(length=128), nullable=False),
            sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("data_mode", sa.String(length=16), nullable=False),
            sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
            sa.Column("input_snapshot_hash", sa.String(length=64), nullable=False),
            sa.Column("result_json", sa.JSON(), nullable=False),
            sa.Column("output_hash", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(["claim_id"], ["author_claims.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_mechanism_assessments_claim_time",
            "mechanism_assessments",
            ["claim_id", "evaluated_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_mechanism_assessments_claim_time", table_name="mechanism_assessments")
    op.drop_table("mechanism_assessments")
    op.drop_index("ix_author_claims_source_status", table_name="author_claims")
    op.drop_table("author_claims")
    op.drop_index("ix_research_sources_retrieved", table_name="research_sources")
    op.drop_table("research_sources")
