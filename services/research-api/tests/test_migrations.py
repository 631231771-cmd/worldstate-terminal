from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def test_clean_database_migrates_to_v06_with_reference_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "clean.db"
    monkeypatch.setenv(
        "WORLDSTATE_DATABASE_URL",
        f"sqlite+aiosqlite:///{database.as_posix()}",
    )
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "head")

    connection = sqlite3.connect(database)
    try:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        integrity_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        analysis_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(analysis_runs)").fetchall()
        }
        consensus_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(consensus_snapshots)").fetchall()
        }
    finally:
        connection.close()

    assert revision == ("0006_data_mode_integrity",)
    assert {
        "evidence_items",
        "research_claims",
        "analysis_runs",
        "provider_entitlements",
        "provider_quotas",
        "sync_jobs",
        "sync_job_runs",
        "data_reconciliation_records",
        "market_data_manifests",
        "backfill_jobs",
        "calendar_snapshots",
    } <= tables
    assert {
        "input_snapshot_hash",
        "config_hash",
        "output_hash",
        "release_snapshot_json",
        "market_dataset_manifest_json",
        "data_mode",
    } <= analysis_columns
    assert {"data_mode", "metadata_json"} <= consensus_columns
    assert integrity_errors == []


def test_existing_v04_database_upgrades_to_v06(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "v04.db"
    monkeypatch.setenv(
        "WORLDSTATE_DATABASE_URL",
        f"sqlite+aiosqlite:///{database.as_posix()}",
    )
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "0004_analysis_reproducibility")

    connection = sqlite3.connect(database)
    try:
        before_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        provider_id = connection.execute(
            """
            INSERT INTO providers (
                key, name, base_url, enabled, requires_credentials, terms_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, 1, 1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            ("fred_demo_migration", "Legacy FRED demo", "https://example.test"),
        ).lastrowid
        entity_id = connection.execute(
            """
            INSERT INTO economic_entities (
                iso2, iso3, name, entity_type, parent_id, currency, timezone,
                latitude, longitude, metadata_json
            ) VALUES ('US', NULL, 'Migration test', 'country', NULL, 'USD',
                      'UTC', NULL, NULL, '{}')
            """
        ).lastrowid
        series_id = uuid.uuid4().hex
        connection.execute(
            """
            INSERT INTO series (
                id, provider_id, native_id, canonical_key, entity_id, title,
                description, frequency, unit, seasonal_adjustment,
                observation_type, source_url, release_key,
                availability_method, availability_precision, default_transform,
                active, metadata_json, created_at, updated_at
            ) VALUES (?, ?, 'DGS10_DEMO', ?, ?, 'Legacy demo yield', NULL,
                      'daily', 'percent', NULL, 'rate', 'fixture://fred-demo',
                      NULL, 'provider_timestamp', 'day', 'level', 1,
                      '{"source_mode":"demo"}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (series_id, provider_id, f"fred-demo-{series_id}", entity_id),
        )
        connection.execute(
            """
            INSERT INTO observations (
                series_id, period_start, period_end, value, raw_value,
                vintage_date, realtime_start, realtime_end, available_at,
                availability_method, availability_precision, fetched_at,
                is_preliminary, is_revised, quality_flags, source_hash
            ) VALUES (?, '2025-01-02', '2025-01-02', 4.0, '4.0',
                      '2025-01-03', '2025-01-03', NULL, '2025-01-03T00:00:00+00:00',
                      'provider_timestamp', 'day', '2025-01-03T00:00:00+00:00',
                      0, 0, '[]', ?)
            """,
            (series_id, "d" * 64),
        )
        connection.commit()
    finally:
        connection.close()
    assert "analysis_runs" in before_tables

    command.upgrade(config, "head")
    connection = sqlite3.connect(database)
    try:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        integrity_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(consensus_snapshots)").fetchall()
        }
        migrated_demo_mode = connection.execute(
            """
            SELECT o.data_mode
            FROM observations o
            JOIN series s ON s.id = o.series_id
            WHERE s.native_id = 'DGS10_DEMO'
            """
        ).fetchone()
    finally:
        connection.close()
    assert revision == ("0006_data_mode_integrity",)
    assert {"data_mode", "metadata_json"} <= columns
    assert migrated_demo_mode == ("fixture",)
    assert integrity_errors == []


def test_existing_v05_database_upgrades_to_v06(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "v05.db"
    monkeypatch.setenv(
        "WORLDSTATE_DATABASE_URL",
        f"sqlite+aiosqlite:///{database.as_posix()}",
    )
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "0005_provider_data_foundation")

    connection = sqlite3.connect(database)
    try:
        revision_before = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
    finally:
        connection.close()
    assert revision_before == ("0005_provider_data_foundation",)

    command.upgrade(config, "head")
    connection = sqlite3.connect(database)
    try:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        integrity_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        observation_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(observations)").fetchall()
        }
        unique_indexes = {
            row[1]
            for table in ("provider_runs", "calendar_snapshots", "observations")
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
            if row[2]
        }
    finally:
        connection.close()

    assert revision == ("0006_data_mode_integrity",)
    assert "data_mode" in observation_columns
    assert "uq_provider_run_idempotency_mode" in unique_indexes
    assert integrity_errors == []
