"""Add durable provider, synchronization, reconciliation and backfill state."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_provider_data_foundation"
down_revision: str | None = "0004_analysis_reproducibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSON = sa.JSON()
MONEY = sa.Numeric(precision=30, scale=12)


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table: str, column: str) -> bool:
    return column in {
        item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)
    }


def _has_index(table: str, index: str) -> bool:
    return index in {
        item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)
    }


def _unique_names(table: str) -> set[str]:
    return {
        str(item["name"])
        for item in sa.inspect(op.get_bind()).get_unique_constraints(table)
        if item["name"]
    }


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _add_existing_columns() -> None:
    def add(table: str, column: sa.Column[object]) -> None:
        if not _has_column(table, str(column.name)):
            op.add_column(table, column)

    add("source_artifacts", sa.Column("provider_run_id", sa.Uuid(), nullable=True))
    add("source_artifacts", sa.Column("content_type", sa.String(255), nullable=True))
    add("source_artifacts", sa.Column("byte_length", sa.BigInteger(), nullable=True))
    add("source_artifacts", sa.Column("content_bytes", sa.LargeBinary(), nullable=True))
    add(
        "source_artifacts",
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
    )
    for table in (
        "macro_releases",
        "release_values",
        "consensus_snapshots",
        "market_bars",
        "observations",
        "analysis_runs",
    ):
        add(
            table,
            sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        )
    add(
        "consensus_snapshots",
        sa.Column("metadata_json", JSON, server_default="{}", nullable=False),
    )
    add(
        "provider_runs",
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
    )
    add("provider_runs", sa.Column("idempotency_key", sa.String(255)))
    add(
        "provider_runs",
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
    )
    add("provider_runs", sa.Column("estimated_cost_usd", MONEY))
    add("provider_runs", sa.Column("actual_cost_usd", MONEY))
    add("provider_runs", sa.Column("terms_url", sa.String(2048)))
    if not _has_index("provider_runs", "uq_provider_run_idempotency_mode"):
        op.create_index(
            "uq_provider_run_idempotency_mode",
            "provider_runs",
            ["provider_key", "operation", "idempotency_key", "data_mode"],
            unique=True,
        )

    bind = op.get_bind()
    foreign_keys = {
        tuple(item["constrained_columns"])
        for item in sa.inspect(bind).get_foreign_keys("source_artifacts")
    }
    if bind.dialect.name != "sqlite" and ("provider_run_id",) not in foreign_keys:
        op.create_foreign_key(
            "fk_source_artifacts_provider_run",
            "source_artifacts",
            "provider_runs",
            ["provider_run_id"],
            ["id"],
        )


def _backfill_data_modes() -> None:
    """Preserve v0.4 demonstrations as fixture instead of relabelling them observed."""

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        json_mode = "parameters_json ->> 'data_mode'"
        output_mode = "output_json ->> 'data_mode'"
    else:
        json_mode = "json_extract(parameters_json, '$.data_mode')"
        output_mode = "json_extract(output_json, '$.data_mode')"

    op.execute(sa.text("UPDATE source_artifacts SET data_mode = CASE WHEN is_fixture THEN 'fixture' ELSE 'observed' END"))
    op.execute(
        sa.text(
            """
            UPDATE macro_releases
            SET data_mode = CASE WHEN EXISTS (
                SELECT 1 FROM source_artifacts a
                WHERE a.id = macro_releases.source_artifact_id AND a.is_fixture
            ) THEN 'fixture' ELSE 'observed' END
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE analysis_runs
            SET data_mode = CASE
                WHEN COALESCE({json_mode}, 'fixture') = 'observed' THEN 'observed'
                ELSE 'fixture' END
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE provider_runs
            SET data_mode = CASE WHEN
                COALESCE({output_mode}, '') = 'fixture' OR EXISTS (
                    SELECT 1 FROM source_artifacts a
                    WHERE a.id = provider_runs.source_artifact_id AND a.is_fixture
                ) THEN 'fixture' ELSE 'observed' END
            """
        )
    )
    for table in ("release_values", "consensus_snapshots"):
        op.execute(
            sa.text(
                f"""
                UPDATE {table}
                SET data_mode = CASE WHEN
                    EXISTS (
                        SELECT 1 FROM source_artifacts a
                        WHERE a.id = {table}.source_artifact_id AND a.is_fixture
                    ) OR EXISTS (
                        SELECT 1 FROM data_quality_records q
                        WHERE q.id = {table}.quality_id AND q.is_fixture
                    ) THEN 'fixture' ELSE 'observed' END
                """
            )
        )
    op.execute(
        sa.text(
            """
            UPDATE market_bars
            SET data_mode = CASE WHEN EXISTS (
                SELECT 1 FROM data_quality_records q
                WHERE q.id = market_bars.quality_id AND q.is_fixture
            ) THEN 'fixture' ELSE 'observed' END
            """
        )
    )
    if bind.dialect.name == "postgresql":
        series_source_mode = "s.metadata_json ->> 'source_mode'"
    else:
        series_source_mode = "json_extract(s.metadata_json, '$.source_mode')"
    op.execute(
        sa.text(
            f"""
            UPDATE observations
            SET data_mode = CASE WHEN EXISTS (
                SELECT 1 FROM series s
                WHERE s.id = observations.series_id
                  AND LOWER(COALESCE({series_source_mode}, '')) IN ('demo', 'fixture')
            ) THEN 'fixture' ELSE 'observed' END
            """
        )
    )


def _upgrade_mode_unique_constraints() -> None:
    definitions = (
        (
            "source_artifacts",
            "uq_source_artifact_hash",
            "uq_source_artifact_hash_mode",
            ["provider_key", "content_hash", "data_mode"],
        ),
        (
            "macro_releases",
            "uq_macro_release_type_time",
            "uq_macro_release_type_time_mode",
            ["release_type", "released_at", "data_mode"],
        ),
        (
            "release_values",
            "uq_release_value_vintage",
            "uq_release_value_vintage_mode",
            [
                "macro_release_id",
                "indicator_id",
                "value_kind",
                "data_version",
                "captured_at",
                "data_mode",
            ],
        ),
        (
            "consensus_snapshots",
            "uq_consensus_snapshot",
            "uq_consensus_snapshot_mode",
            [
                "macro_release_id",
                "indicator_id",
                "captured_at",
                "source_name",
                "data_mode",
            ],
        ),
        (
            "market_bars",
            "uq_market_bar_provider_time",
            "uq_market_bar_provider_time_mode",
            [
                "instrument_id",
                "timestamp",
                "interval_seconds",
                "provider_key",
                "contract_code",
                "data_mode",
            ],
        ),
        (
            "observations",
            "uq_observations_series_period_vintage",
            "uq_observations_series_period_vintage_mode",
            ["series_id", "period_start", "vintage_date", "data_mode"],
        ),
    )
    for table, old_name, new_name, columns in definitions:
        names = _unique_names(table)
        if new_name in names:
            continue
        if op.get_bind().dialect.name != "sqlite":
            if old_name in names:
                op.drop_constraint(old_name, table, type_="unique")
            op.create_unique_constraint(new_name, table, columns)
            continue
        with op.batch_alter_table(table, recreate="always") as batch:
            if old_name in names:
                batch.drop_constraint(old_name, type_="unique")
            batch.create_unique_constraint(new_name, columns)
            if table != "source_artifacts":
                continue
            constrained = {
                tuple(item["constrained_columns"])
                for item in sa.inspect(op.get_bind()).get_foreign_keys(table)
            }
            if ("provider_run_id",) not in constrained:
                batch.create_foreign_key(
                    "fk_source_artifacts_provider_run",
                    "provider_runs",
                    ["provider_run_id"],
                    ["id"],
                )


def _create_provider_state() -> None:
    op.create_table(
        "provider_entitlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("provider_run_id", sa.Uuid(), sa.ForeignKey("provider_runs.id")),
        sa.Column("source_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("terms_url", sa.String(2048)),
        sa.Column("metadata_json", JSON, server_default="{}", nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('unknown','granted','denied','expired','not_configured')",
            name="ck_provider_entitlement_status",
        ),
        sa.UniqueConstraint("provider_key", "capability", name="uq_provider_entitlement"),
    )
    op.create_index(
        "ix_provider_entitlements_status", "provider_entitlements", ["provider_key", "status"]
    )
    op.create_table(
        "provider_quotas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("quota_key", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limit_value", MONEY),
        sa.Column("used_value", MONEY, server_default="0", nullable=False),
        sa.Column("remaining_value", MONEY),
        sa.Column("warning_threshold", MONEY),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_run_id", sa.Uuid(), sa.ForeignKey("provider_runs.id")),
        sa.Column("source_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("metadata_json", JSON, server_default="{}", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "provider_key", "quota_key", "period_start", name="uq_provider_quota_period"
        ),
    )
    op.create_index("ix_provider_quotas_period", "provider_quotas", ["provider_key", "period_end"])


def _create_sync_state() -> None:
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_key", sa.String(128), nullable=False),
        sa.Column("provider_key", sa.String(64)),
        sa.Column("operation", sa.String(128), nullable=False),
        sa.Column("schedule_type", sa.String(32), nullable=False),
        sa.Column("schedule_json", JSON, server_default="{}", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("retry_backoff_seconds", sa.Integer(), server_default="60", nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("config_json", JSON, server_default="{}", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("job_key", name="uq_sync_job_key"),
    )
    op.create_index("ix_sync_jobs_due", "sync_jobs", ["enabled", "next_run_at"])
    op.create_table(
        "sync_job_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sync_job_id", sa.Uuid(), sa.ForeignKey("sync_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_run_id", sa.Uuid(), sa.ForeignKey("provider_runs.id")),
        sa.Column("source_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("retry_of_id", sa.Uuid(), sa.ForeignKey("sync_job_runs.id")),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("records_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checkpoint_json", JSON, server_default="{}", nullable=False),
        sa.Column("input_json", JSON, server_default="{}", nullable=False),
        sa.Column("output_json", JSON, server_default="{}", nullable=False),
        sa.Column("error_type", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('pending','running','retry_wait','completed','failed','cancelled')",
            name="ck_sync_job_run_status",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_sync_job_run_idempotency"),
    )
    op.create_index("ix_sync_job_runs_status_schedule", "sync_job_runs", ["status", "scheduled_for"])
    op.create_index("ix_sync_job_runs_job_started", "sync_job_runs", ["sync_job_id", "started_at"])


def _create_data_products() -> None:
    op.create_table(
        "data_reconciliation_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reconciliation_key", sa.String(255), nullable=False),
        sa.Column("reconciliation_type", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("field_name", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), server_default="info", nullable=False),
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        sa.Column("authoritative_provider_key", sa.String(64), nullable=False),
        sa.Column("comparison_provider_key", sa.String(64), nullable=False),
        sa.Column("authoritative_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("comparison_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("sync_job_run_id", sa.Uuid(), sa.ForeignKey("sync_job_runs.id")),
        sa.Column("authoritative_value_json", JSON, server_default="{}", nullable=False),
        sa.Column("comparison_value_json", JSON, server_default="{}", nullable=False),
        sa.Column("difference_json", JSON, server_default="{}", nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_action", sa.String(64)),
        sa.Column("resolution_notes", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("reconciliation_key", name="uq_data_reconciliation_key"),
    )
    op.create_index("ix_data_reconciliation_status", "data_reconciliation_records", ["status", "detected_at"])
    op.create_index("ix_data_reconciliation_subject", "data_reconciliation_records", ["subject_type", "subject_id"])
    op.create_table(
        "market_data_manifests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("macro_release_id", sa.Uuid(), sa.ForeignKey("macro_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("release_stage_id", sa.Uuid(), sa.ForeignKey("release_stages.id")),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("schema_name", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), sa.ForeignKey("market_instruments.id"), nullable=False),
        sa.Column("futures_contract_id", sa.Uuid(), sa.ForeignKey("futures_contracts.id")),
        sa.Column("source_symbol", sa.String(128), nullable=False),
        sa.Column("contract_code", sa.String(64)),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        sa.Column("quality_grade", sa.String(16), server_default="UNKNOWN", nullable=False),
        sa.Column("is_aggregated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("aggregation_method", sa.String(128)),
        sa.Column("aggregation_version", sa.String(64)),
        sa.Column("contract_selection_rule", sa.Text()),
        sa.Column("continuous_resolution_json", JSON, server_default="{}", nullable=False),
        sa.Column("roll_status", sa.String(32)),
        sa.Column("estimated_cost_usd", MONEY),
        sa.Column("actual_cost_usd", MONEY),
        sa.Column("provider_run_id", sa.Uuid(), sa.ForeignKey("provider_runs.id")),
        sa.Column("sync_job_run_id", sa.Uuid(), sa.ForeignKey("sync_job_runs.id")),
        sa.Column("source_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metadata_json", JSON, server_default="{}", nullable=False),
        sa.UniqueConstraint("manifest_hash", name="uq_market_data_manifest_hash"),
    )
    op.create_index(
        "ix_market_data_manifest_coverage",
        "market_data_manifests",
        ["macro_release_id", "instrument_id", "interval_seconds", "start_at", "end_at"],
    )


def _create_backfill_and_calendar() -> None:
    op.create_table(
        "backfill_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("event_types_json", JSON, server_default="[]", nullable=False),
        sa.Column("instruments_json", JSON, server_default="[]", nullable=False),
        sa.Column("datasets_json", JSON, server_default="[]", nullable=False),
        sa.Column("estimated_event_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_size_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", MONEY, server_default="0", nullable=False),
        sa.Column("budget_limit_usd", MONEY, server_default="0", nullable=False),
        sa.Column("paid_download_allowed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("execution_allowed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("existing_record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("downloaded_record_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("current_stage", sa.String(64)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("sync_job_run_id", sa.Uuid(), sa.ForeignKey("sync_job_runs.id")),
        sa.Column("estimate_json", JSON, server_default="{}", nullable=False),
        sa.Column("result_json", JSON, server_default="{}", nullable=False),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('estimated','pending','running','completed','failed','cancelled','rejected')",
            name="ck_backfill_job_status",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_backfill_job_idempotency"),
    )
    op.create_index("ix_backfill_jobs_status", "backfill_jobs", ["status", "requested_at"])
    op.create_table(
        "calendar_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("calendar_kind", sa.String(64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("event_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("data_mode", sa.String(16), server_default="observed", nullable=False),
        sa.Column("is_point_in_time", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("provider_run_id", sa.Uuid(), sa.ForeignKey("provider_runs.id")),
        sa.Column("source_artifact_id", sa.Uuid(), sa.ForeignKey("source_artifacts.id")),
        sa.Column("payload_json", JSON, server_default="[]", nullable=False),
        sa.Column("metadata_json", JSON, server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "provider_key",
            "calendar_kind",
            "captured_at",
            "content_hash",
            "data_mode",
            name="uq_calendar_snapshot_mode",
        ),
    )
    op.create_index(
        "ix_calendar_snapshots_range",
        "calendar_snapshots",
        ["calendar_kind", "period_start", "period_end"],
    )


def upgrade() -> None:
    _add_existing_columns()
    _backfill_data_modes()
    _upgrade_mode_unique_constraints()
    tables = _table_names()
    if not {"provider_entitlements", "provider_quotas"} & tables:
        _create_provider_state()
    tables = _table_names()
    if not {"sync_jobs", "sync_job_runs"} & tables:
        _create_sync_state()
    tables = _table_names()
    if not {"data_reconciliation_records", "market_data_manifests"} & tables:
        _create_data_products()
    tables = _table_names()
    if not {"backfill_jobs", "calendar_snapshots"} & tables:
        _create_backfill_and_calendar()


def downgrade() -> None:
    raise RuntimeError(
        "v0.5 data foundation downgrade is intentionally unsupported; restore a backup instead."
    )
