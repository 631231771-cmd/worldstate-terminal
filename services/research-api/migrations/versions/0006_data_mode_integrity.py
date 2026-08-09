"""Repair fixture/observed isolation for databases already upgraded to v0.5.

The first published 0005 revision did not include ``observations.data_mode``
and its provider/calendar idempotency keys did not distinguish fixture data
from observed data. 0005 is intentionally kept usable for clean installs,
while this follow-up migration makes the correction durable for existing
databases which have already recorded the original 0005 revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_data_mode_integrity"
down_revision: str | None = "0005_provider_data_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in _inspector().get_columns(table)}


def _unique_names(table: str) -> set[str]:
    return {
        str(item["name"])
        for item in _inspector().get_unique_constraints(table)
        if item["name"]
    }


def _index_names(table: str) -> set[str]:
    return {
        str(item["name"])
        for item in _inspector().get_indexes(table)
        if item["name"]
    }


def _backfill_observation_modes() -> None:
    if not _has_column("observations", "data_mode"):
        op.add_column(
            "observations",
            sa.Column(
                "data_mode",
                sa.String(16),
                server_default="observed",
                nullable=False,
            ),
        )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        source_mode = "s.metadata_json ->> 'source_mode'"
    else:
        source_mode = "json_extract(s.metadata_json, '$.source_mode')"
    op.execute(
        sa.text(
            f"""
            UPDATE observations
            SET data_mode = CASE WHEN EXISTS (
                SELECT 1 FROM series s
                WHERE s.id = observations.series_id
                  AND LOWER(COALESCE({source_mode}, '')) IN ('demo', 'fixture')
            ) THEN 'fixture' ELSE 'observed' END
            """
        )
    )


def _upgrade_provider_run_identity() -> None:
    old_name = "uq_provider_run_idempotency"
    new_name = "uq_provider_run_idempotency_mode"
    uniques = _unique_names("provider_runs")
    indexes = _index_names("provider_runs")
    if new_name in uniques or new_name in indexes:
        return

    # The originally published 0005 used a unique index rather than a named
    # table constraint. Account for both shapes so SQLite and PostgreSQL
    # upgrades behave identically.
    if old_name in indexes:
        op.drop_index(old_name, table_name="provider_runs")
    if old_name in uniques:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("provider_runs", recreate="always") as batch:
                batch.drop_constraint(old_name, type_="unique")
        else:
            op.drop_constraint(old_name, "provider_runs", type_="unique")
    op.create_index(
        new_name,
        "provider_runs",
        ["provider_key", "operation", "idempotency_key", "data_mode"],
        unique=True,
    )


def _upgrade_unique_constraint(
    table: str,
    old_name: str,
    new_name: str,
    columns: list[str],
) -> None:
    uniques = _unique_names(table)
    indexes = _index_names(table)
    if new_name in uniques or new_name in indexes:
        return
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch:
            if old_name in uniques:
                batch.drop_constraint(old_name, type_="unique")
            batch.create_unique_constraint(new_name, columns)
        return
    if old_name in uniques:
        op.drop_constraint(old_name, table, type_="unique")
    elif old_name in indexes:
        op.drop_index(old_name, table_name=table)
    op.create_unique_constraint(new_name, table, columns)


def upgrade() -> None:
    _backfill_observation_modes()
    _upgrade_provider_run_identity()
    _upgrade_unique_constraint(
        "calendar_snapshots",
        "uq_calendar_snapshot",
        "uq_calendar_snapshot_mode",
        ["provider_key", "calendar_kind", "captured_at", "content_hash", "data_mode"],
    )
    _upgrade_unique_constraint(
        "observations",
        "uq_observations_series_period_vintage",
        "uq_observations_series_period_vintage_mode",
        ["series_id", "period_start", "vintage_date", "data_mode"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "v0.5 data-mode integrity downgrade is unsupported; restore a backup instead."
    )
