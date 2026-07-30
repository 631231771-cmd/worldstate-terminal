"""Create the initial World State Terminal macro schema.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
IDENTITY_INTEGER = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
JSON_OBJECT = sa.text("'{}'")
JSON_ARRAY = sa.text("'[]'")


def upgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("id", IDENTITY_INTEGER, sa.Identity(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requires_credentials", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("terms_url", sa.String(2048)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "economic_entities",
        sa.Column("id", IDENTITY_INTEGER, sa.Identity(), primary_key=True),
        sa.Column("iso2", sa.String(2), unique=True),
        sa.Column("iso3", sa.String(3), unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("economic_entities.id")),
        sa.Column("currency", sa.String(3)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.CheckConstraint(
            "entity_type IN ('country','economic_area','global','region')",
            name="ck_economic_entities_type",
        ),
    )
    op.create_table(
        "series",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("native_id", sa.String(255), nullable=False),
        sa.Column("canonical_key", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "entity_id", sa.BigInteger(), sa.ForeignKey("economic_entities.id"), nullable=False
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(128), nullable=False),
        sa.Column("seasonal_adjustment", sa.String(128)),
        sa.Column("observation_type", sa.String(64), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("release_key", sa.String(255)),
        sa.Column("availability_method", sa.String(64), nullable=False),
        sa.Column("availability_precision", sa.String(32), nullable=False),
        sa.Column("default_transform", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("provider_id", "native_id", name="uq_series_provider_native"),
    )
    op.create_index("ix_series_entity_active", "series", ["entity_id", "active"])
    op.create_table(
        "observations",
        sa.Column("id", IDENTITY_INTEGER, sa.Identity(), primary_key=True),
        sa.Column("series_id", sa.Uuid(), sa.ForeignKey("series.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(30, 12)),
        sa.Column("raw_value", sa.Text()),
        sa.Column("vintage_date", sa.Date(), nullable=False),
        sa.Column("realtime_start", sa.Date()),
        sa.Column("realtime_end", sa.Date()),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("availability_method", sa.String(64), nullable=False),
        sa.Column("availability_precision", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_preliminary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_revised", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("quality_flags", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "series_id",
            "period_start",
            "vintage_date",
            name="uq_observations_series_period_vintage",
        ),
    )
    op.create_index("ix_observations_series_period", "observations", ["series_id", "period_start"])
    op.create_index(
        "ix_observations_series_available", "observations", ["series_id", "available_at"]
    )
    op.create_index("ix_observations_series_vintage", "observations", ["series_id", "vintage_date"])
    op.create_index(
        "ix_observations_as_of",
        "observations",
        ["series_id", "available_at", "period_start", "vintage_date"],
    )
    op.create_index(
        "ix_observations_latest",
        "observations",
        ["series_id", "period_start", "vintage_date"],
    )
    op.create_table(
        "releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("native_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), sa.ForeignKey("economic_entities.id")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("actual_at", sa.DateTime(timezone=True)),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.UniqueConstraint(
            "provider_id", "native_id", "scheduled_at", name="uq_release_native_time"
        ),
    )
    op.create_index("ix_releases_scheduled", "releases", ["scheduled_at", "status"])
    op.create_table(
        "release_series",
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "series_id", sa.Uuid(), sa.ForeignKey("series.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_series", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("inserted_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warnings", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("errors", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
    )
    op.create_index("ix_sync_runs_provider_started", "sync_runs", ["provider", "started_at"])
    op.create_table(
        "state_definitions",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("meaning_of_positive", sa.Text(), nullable=False),
        sa.Column("methodology_version", sa.String(64), nullable=False),
        sa.Column("config_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
    )
    op.create_table(
        "state_components",
        sa.Column(
            "state_key", sa.String(64), sa.ForeignKey("state_definitions.key"), primary_key=True
        ),
        sa.Column("series_id", sa.Uuid(), sa.ForeignKey("series.id"), primary_key=True),
        sa.Column("transform", sa.String(64), nullable=False),
        sa.Column("orientation", sa.Integer(), nullable=False),
        sa.Column("base_weight", sa.Float(), nullable=False),
        sa.Column("freshness_half_life_days", sa.Float(), nullable=False),
        sa.Column("minimum_history", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "state_snapshots",
        sa.Column(
            "entity_id", sa.BigInteger(), sa.ForeignKey("economic_entities.id"), primary_key=True
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), primary_key=True),
        sa.Column(
            "state_key", sa.String(64), sa.ForeignKey("state_definitions.key"), primary_key=True
        ),
        sa.Column("methodology_version", sa.String(64), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("momentum", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column("coverage", sa.Float(), nullable=False),
        sa.Column("agreement", sa.Float(), nullable=False),
        sa.Column("freshness", sa.Float(), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("components_json", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("score >= -1 AND score <= 1", name="ck_state_snapshots_score"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_state_snapshots_confidence"
        ),
    )
    op.create_index("ix_state_snapshots_entity_as_of", "state_snapshots", ["entity_id", "as_of"])
    op.create_table(
        "causal_nodes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("linked_series", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
    )
    op.create_table(
        "causal_edges",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_node_id", sa.Uuid(), sa.ForeignKey("causal_nodes.id"), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), sa.ForeignKey("causal_nodes.id"), nullable=False),
        sa.Column("sign", sa.Integer(), nullable=False),
        sa.Column("lag_min_days", sa.Integer(), nullable=False),
        sa.Column("lag_max_days", sa.Integer(), nullable=False),
        sa.Column("conditions", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column("evidence", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("counterexamples", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "theses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(128), nullable=False),
        sa.Column("base_case", sa.Text(), nullable=False),
        sa.Column("bull_case", sa.Text(), nullable=False),
        sa.Column("bear_case", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','confirmed','invalidated','archived')",
            name="ck_theses_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_theses_confidence"),
    )
    op.create_table(
        "thesis_conditions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "thesis_id", sa.Uuid(), sa.ForeignKey("theses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("condition_type", sa.String(32), nullable=False),
        sa.Column("metric_ref", sa.String(255), nullable=False),
        sa.Column("operator", sa.String(16), nullable=False),
        sa.Column("threshold", sa.Numeric(30, 12), nullable=False),
        sa.Column("evaluation_window", sa.String(64), nullable=False),
        sa.Column("current_status", sa.String(32), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text()),
        sa.CheckConstraint(
            "condition_type IN ('confirm','invalidate','watch')",
            name="ck_thesis_conditions_type",
        ),
    )
    op.create_table(
        "thesis_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "thesis_id", sa.Uuid(), sa.ForeignKey("theses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=False),
        sa.Column("stance", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.CheckConstraint(
            "stance IN ('support','contradict','neutral')",
            name="ck_thesis_evidence_stance",
        ),
    )
    op.create_table(
        "thesis_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "thesis_id", sa.Uuid(), sa.ForeignKey("theses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_state", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("world_state", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_thesis_snapshots_thesis_captured",
        "thesis_snapshots",
        ["thesis_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_thesis_snapshots_thesis_captured", table_name="thesis_snapshots")
    op.drop_table("thesis_snapshots")
    op.drop_table("thesis_evidence")
    op.drop_table("thesis_conditions")
    op.drop_table("theses")
    op.drop_table("causal_edges")
    op.drop_table("causal_nodes")
    op.drop_index("ix_state_snapshots_entity_as_of", table_name="state_snapshots")
    op.drop_table("state_snapshots")
    op.drop_table("state_components")
    op.drop_table("state_definitions")
    op.drop_index("ix_sync_runs_provider_started", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_table("release_series")
    op.drop_index("ix_releases_scheduled", table_name="releases")
    op.drop_table("releases")
    op.drop_index("ix_observations_latest", table_name="observations")
    op.drop_index("ix_observations_as_of", table_name="observations")
    op.drop_index("ix_observations_series_vintage", table_name="observations")
    op.drop_index("ix_observations_series_available", table_name="observations")
    op.drop_index("ix_observations_series_period", table_name="observations")
    op.drop_table("observations")
    op.drop_index("ix_series_entity_active", table_name="series")
    op.drop_table("series")
    op.drop_table("economic_entities")
    op.drop_table("providers")
