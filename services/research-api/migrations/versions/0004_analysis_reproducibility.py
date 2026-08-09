"""Add immutable manifests and structured evidence for v0.4 research runs."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_analysis_reproducibility"
down_revision: str | None = "0003_macro_research_terminal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())

    def has_column(table: str, name: str) -> bool:
        return name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}

    if not has_column("regime_snapshots", "dimensions_json"):
        op.add_column(
            "regime_snapshots",
            sa.Column("dimensions_json", sa.JSON(), nullable=False, server_default="{}"),
        )
    columns = (
        ("input_snapshot_hash", sa.String(64)),
        ("config_hash", sa.String(64)),
        ("output_hash", sa.String(64)),
        ("release_snapshot_json", sa.JSON()),
        ("release_value_ids_json", sa.JSON()),
        ("consensus_snapshot_ids_json", sa.JSON()),
        ("release_stage_ids_json", sa.JSON()),
        ("market_dataset_manifest_json", sa.JSON()),
        ("market_dataset_hash", sa.String(64)),
        ("historical_sample_manifest_json", sa.JSON()),
        ("historical_sample_hash", sa.String(64)),
        ("provider_manifest_json", sa.JSON()),
        ("source_artifact_ids_json", sa.JSON()),
        ("algorithm_versions_json", sa.JSON()),
        ("rule_versions_json", sa.JSON()),
        ("analysis_parameters_json", sa.JSON()),
        ("reproducibility_status", sa.String(32)),
        ("idempotency_key", sa.String(128)),
        ("failure_stage", sa.String(64)),
        ("error_type", sa.String(128)),
        ("error_message", sa.Text()),
    )
    for name, column_type in columns:
        default = "'legacy_incomplete'" if name == "reproducibility_status" else None
        if not has_column("analysis_runs", name):
            op.add_column(
                "analysis_runs",
                sa.Column(
                    name,
                    column_type,
                    nullable=True,
                    server_default=sa.text(default) if default else None,
                ),
            )
    # SQLite cannot add a named foreign-key constraint after table creation.
    # The nullable reference is verified by the migration verifier and ORM; new
    # installations get the full FK from metadata when tables are created.
    if not has_column("historical_matches", "matched_analysis_run_id"):
        op.add_column(
            "historical_matches", sa.Column("matched_analysis_run_id", sa.Uuid(), nullable=True)
        )
    if "ix_analysis_runs_input_config" not in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("analysis_runs")
    }:
        op.create_index(
            "ix_analysis_runs_input_config", "analysis_runs", ["input_snapshot_hash", "config_hash"]
        )
    if "evidence_items" not in table_names:
        op.create_table(
            "evidence_items",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
            sa.Column("evidence_type", sa.String(64), nullable=False),
            sa.Column("subject_type", sa.String(64), nullable=False),
            sa.Column("subject_id", sa.String(128), nullable=False),
            sa.Column("source_artifact_id", sa.Uuid()),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("unit", sa.String(64)),
            sa.Column("observed_at", sa.DateTime(timezone=True)),
            sa.Column("quality_grade", sa.String(16), nullable=False),
            sa.Column("is_fixture", sa.Boolean(), nullable=False),
            sa.Column("is_proxy", sa.Boolean(), nullable=False),
            sa.Column("is_manual", sa.Boolean(), nullable=False),
            sa.Column("limitations_json", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_artifact_id"], ["source_artifacts.id"]),
        )
        op.create_index("ix_evidence_items_run", "evidence_items", ["analysis_run_id"])
    if "research_claims" not in table_names:
        op.create_table(
            "research_claims",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
            sa.Column("claim_type", sa.String(64), nullable=False),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("is_inference", sa.Boolean(), nullable=False),
            sa.Column("causal_language", sa.String(32), nullable=False),
            sa.Column("limitations_json", sa.JSON(), nullable=False),
            sa.Column("falsifier", sa.Text()),
            sa.Column("contradicting_evidence_ids_json", sa.JSON(), nullable=False),
            sa.Column("validation_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_research_claims_run", "research_claims", ["analysis_run_id"])


def downgrade() -> None:
    raise RuntimeError(
        "v0.4 stabilization downgrade is intentionally unsupported; restore a backup instead."
    )
