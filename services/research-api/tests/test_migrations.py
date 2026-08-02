from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def test_clean_database_migrates_to_v04_with_reference_integrity(
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
    finally:
        connection.close()

    assert revision == ("0004_analysis_reproducibility",)
    assert {"evidence_items", "research_claims", "analysis_runs"} <= tables
    assert {
        "input_snapshot_hash",
        "config_hash",
        "output_hash",
        "release_snapshot_json",
        "market_dataset_manifest_json",
    } <= analysis_columns
    assert integrity_errors == []
