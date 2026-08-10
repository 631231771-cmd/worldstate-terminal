from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def test_clean_database_migrates_to_v051_with_reference_integrity(
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

    assert revision == ("0010_operational_state_defaults",)
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
        "theses",
        "world_state_snapshots",
        "watchlist_items",
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


def test_existing_v04_database_upgrades_to_v051(
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
    assert revision == ("0010_operational_state_defaults",)
    assert {"data_mode", "metadata_json"} <= columns
    assert migrated_demo_mode == ("fixture",)
    assert integrity_errors == []


def test_existing_v05_database_upgrades_to_v051(
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

    assert revision == ("0010_operational_state_defaults",)
    assert "data_mode" in observation_columns
    assert "uq_provider_run_idempotency_mode" in unique_indexes
    assert integrity_errors == []


def test_truthfulness_migration_reclassifies_consensus_and_guards_future_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "mismatch.db"
    monkeypatch.setenv(
        "WORLDSTATE_DATABASE_URL",
        f"sqlite+aiosqlite:///{database.as_posix()}",
    )
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "0006_data_mode_integrity")
    release_id = uuid.uuid4().hex
    indicator_id = uuid.uuid4().hex
    quality_id = uuid.uuid4().hex
    consensus_id = uuid.uuid4().hex
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO macro_releases
            (id, release_key, release_type, title, country, period_label,
             scheduled_at, released_at, source_timezone, status, data_version,
             data_mode, contamination_level, clean_window, overlapping_events,
             confounding_notes, metadata_json, created_at, updated_at)
            VALUES (?, 'fixture-cpi', 'US_CPI', 'Fixture CPI', 'USA', '2024-01',
                    '2024-02-13T13:30:00+00:00', '2024-02-13T13:30:00+00:00',
                    'America/New_York', 'released', 'v1', 'fixture', 'none', 1,
                    '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (release_id,),
        )
        connection.execute(
            """
            INSERT INTO indicators
            (id, indicator_key, name, family, country, unit, periodicity,
             hotter_when_higher, bundle_weight, active, metadata_json,
             created_at, updated_at)
            VALUES (?, 'TEST_CPI', 'Test CPI', 'inflation', 'USA', 'percent',
                    'monthly', 1, 1.0, 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (indicator_id,),
        )
        connection.execute(
            """
            INSERT INTO data_quality_records
            (id, subject_type, subject_id, source_name, source_type, acquired_at,
             is_manual, is_verified, is_fixture, is_proxy, quality_grade,
             verification_notes, metadata_json, created_at)
            VALUES (?, 'consensus_snapshot', ?, 'manual', 'manual', CURRENT_TIMESTAMP,
                    1, 1, 0, 0, 'B', 'pre-release snapshot', '{}', CURRENT_TIMESTAMP)
            """,
            (quality_id, consensus_id),
        )
        connection.execute(
            """
            INSERT INTO consensus_snapshots
            (id, macro_release_id, indicator_id, consensus_value, source_name,
             captured_at, quality_grade, is_manual, data_mode, verification_notes,
             quality_id, metadata_json, created_at)
            VALUES (?, ?, ?, 0.2, 'manual', '2024-02-13T12:00:00+00:00',
                    'B', 1, 'observed', 'pre-release snapshot', ?, '{}', CURRENT_TIMESTAMP)
            """,
            (consensus_id, release_id, indicator_id, quality_id),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(config, "head")
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT data_mode FROM consensus_snapshots WHERE id = ?", (consensus_id,)
        ).fetchone()
        quality = connection.execute(
            "SELECT is_fixture, is_verified, quality_grade FROM data_quality_records WHERE id = ?",
            (quality_id,),
        ).fetchone()
        triggers = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND name LIKE 'ws_consensussnapshots_mode_%'"
        ).fetchall()
        assert row == ("fixture",)
        assert quality == (1, 0, "C")
        assert len(triggers) == 2
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO consensus_snapshots
                (id, macro_release_id, indicator_id, consensus_value, source_name,
                 captured_at, quality_grade, is_manual, data_mode, metadata_json, created_at)
                VALUES (?, ?, ?, 0.3, 'manual', '2024-02-13T12:01:00+00:00',
                        'B', 1, 'observed', '{}', CURRENT_TIMESTAMP)
                """,
                (uuid.uuid4().hex, release_id, indicator_id),
            )
    finally:
        connection.close()
