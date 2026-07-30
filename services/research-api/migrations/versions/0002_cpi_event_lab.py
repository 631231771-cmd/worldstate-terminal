"""Add the CPI Event Lab schema.

Revision ID: 0002_cpi_event_lab
Revises: 0001_initial_schema
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_cpi_event_lab"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
IDENTITY_INTEGER = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DECIMAL_VALUE = sa.Numeric(precision=30, scale=12)
JSON_OBJECT = sa.text("'{}'")
JSON_ARRAY = sa.text("'[]'")


def upgrade() -> None:
    op.create_table(
        "data_quality_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_proxy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_seconds", sa.Integer()),
        sa.Column("granularity_seconds", sa.Integer()),
        sa.Column("missing_reason", sa.Text()),
        sa.Column("quality_grade", sa.String(16), nullable=False),
        sa.Column("verification_notes", sa.Text()),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "quality_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_data_quality_grade",
        ),
    )
    op.create_index(
        "ix_data_quality_source_acquired",
        "data_quality_records",
        ["source_name", "acquired_at"],
    )

    op.create_table(
        "macro_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_key", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("country", sa.String(3), nullable=False),
        sa.Column("period_label", sa.String(64), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("data_version", sa.String(64), nullable=False),
        sa.Column("is_fixture", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("contamination_level", sa.String(32), nullable=False, server_default="none"),
        sa.Column("clean_window", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("overlapping_events", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("confounding_notes", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column(
            "primary_quality_id",
            sa.Uuid(),
            sa.ForeignKey("data_quality_records.id"),
        ),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("event_type", "release_at", name="uq_macro_events_type_release"),
    )
    op.create_index("ix_macro_events_release", "macro_events", ["release_at", "event_type"])

    op.create_table(
        "event_indicators",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("macro_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("indicator_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("actual_value", DECIMAL_VALUE),
        sa.Column("previous_value", DECIMAL_VALUE),
        sa.Column("revised_previous_value", DECIMAL_VALUE),
        sa.Column("first_release_value", DECIMAL_VALUE),
        sa.Column("data_version", sa.String(64), nullable=False),
        sa.Column("hotter_when_higher", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("bundle_weight", sa.Float(), nullable=False),
        sa.Column("raw_surprise", DECIMAL_VALUE),
        sa.Column("relative_surprise", sa.Float()),
        sa.Column("standardized_surprise", sa.Float()),
        sa.Column("surprise_direction", sa.String(32), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column(
            "actual_quality_id",
            sa.Uuid(),
            sa.ForeignKey("data_quality_records.id"),
        ),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.UniqueConstraint("event_id", "indicator_key", name="uq_event_indicator_key"),
    )
    op.create_index(
        "ix_event_indicators_event",
        "event_indicators",
        ["event_id", "indicator_key"],
    )

    op.create_table(
        "consensus_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("macro_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("indicator_key", sa.String(64), nullable=False),
        sa.Column("consensus_value", DECIMAL_VALUE, nullable=False),
        sa.Column("consensus_source", sa.String(255), nullable=False),
        sa.Column("consensus_source_url", sa.String(2048)),
        sa.Column("consensus_captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consensus_quality", sa.String(32), nullable=False),
        sa.Column("consensus_is_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_notes", sa.Text()),
        sa.Column(
            "quality_id",
            sa.Uuid(),
            sa.ForeignKey("data_quality_records.id"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "event_id",
            "indicator_key",
            "consensus_captured_at",
            "consensus_source",
            name="uq_consensus_capture",
        ),
    )
    op.create_index(
        "ix_consensus_event_indicator_captured",
        "consensus_snapshots",
        ["event_id", "indicator_key", "consensus_captured_at"],
    )

    op.create_table(
        "market_instruments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_key", sa.String(64), nullable=False, unique=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("root_symbol", sa.String(32), nullable=False),
        sa.Column("contract_code", sa.String(64)),
        sa.Column("exchange", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("asset_class", sa.String(64), nullable=False),
        sa.Column("quote_unit", sa.String(64), nullable=False),
        sa.Column("measurement_type", sa.String(64), nullable=False),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("is_proxy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("proxy_for", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "market_bars",
        sa.Column("id", IDENTITY_INTEGER, sa.Identity(), primary_key=True),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("market_instruments.id"),
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("open_value", DECIMAL_VALUE, nullable=False),
        sa.Column("high_value", DECIMAL_VALUE, nullable=False),
        sa.Column("low_value", DECIMAL_VALUE, nullable=False),
        sa.Column("close_value", DECIMAL_VALUE, nullable=False),
        sa.Column("volume", DECIMAL_VALUE),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("source_symbol", sa.String(128), nullable=False),
        sa.Column("contract_code", sa.String(64)),
        sa.Column(
            "quality_id",
            sa.Uuid(),
            sa.ForeignKey("data_quality_records.id"),
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.UniqueConstraint(
            "instrument_id",
            "timestamp",
            "interval_seconds",
            "provider_key",
            name="uq_market_bar_provider_time",
        ),
    )
    op.create_index(
        "ix_market_bars_instrument_time",
        "market_bars",
        ["instrument_id", "timestamp", "interval_seconds"],
    )

    op.create_table(
        "event_window_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("macro_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "instrument_id",
            sa.Uuid(),
            sa.ForeignKey("market_instruments.id"),
            nullable=False,
        ),
        sa.Column("window_key", sa.String(32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_value", DECIMAL_VALUE),
        sa.Column("end_value", DECIMAL_VALUE),
        sa.Column("change_absolute", DECIMAL_VALUE),
        sa.Column("return_percent", sa.Float()),
        sa.Column("max_up_percent", sa.Float()),
        sa.Column("max_down_percent", sa.Float()),
        sa.Column("realized_volatility", sa.Float()),
        sa.Column("volume_change_percent", sa.Float()),
        sa.Column("coverage_ratio", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("spike_fade", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dip_recovery", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("direction_reversal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granularity_seconds", sa.Integer(), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("quality_grade", sa.String(16), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.UniqueConstraint(
            "event_id",
            "instrument_id",
            "window_key",
            name="uq_event_window_instrument",
        ),
    )
    op.create_index(
        "ix_event_windows_event",
        "event_window_metrics",
        ["event_id", "window_key"],
    )

    op.create_table(
        "event_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("macro_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("methodology_version", sa.String(64), nullable=False),
        sa.Column("composite_classification", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("facts_json", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("explanations_json", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("historical_json", JSON_DOCUMENT, nullable=False, server_default=JSON_OBJECT),
        sa.Column(
            "earliest_reactions_json",
            JSON_DOCUMENT,
            nullable=False,
            server_default=JSON_ARRAY,
        ),
        sa.Column("data_gaps_json", JSON_DOCUMENT, nullable=False, server_default=JSON_ARRAY),
        sa.Column("report_text", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "methodology_version",
            name="uq_event_analysis_methodology",
        ),
    )


def downgrade() -> None:
    op.drop_table("event_analyses")
    op.drop_index("ix_event_windows_event", table_name="event_window_metrics")
    op.drop_table("event_window_metrics")
    op.drop_index("ix_market_bars_instrument_time", table_name="market_bars")
    op.drop_table("market_bars")
    op.drop_table("market_instruments")
    op.drop_index(
        "ix_consensus_event_indicator_captured",
        table_name="consensus_snapshots",
    )
    op.drop_table("consensus_snapshots")
    op.drop_index("ix_event_indicators_event", table_name="event_indicators")
    op.drop_table("event_indicators")
    op.drop_index("ix_macro_events_release", table_name="macro_events")
    op.drop_table("macro_events")
    op.drop_index(
        "ix_data_quality_source_acquired",
        table_name="data_quality_records",
    )
    op.drop_table("data_quality_records")
