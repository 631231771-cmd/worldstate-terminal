"""Validate a WorldState v3 SQLite database after the one-time migration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

REQUIRED_TABLES = {
    "source_artifacts",
    "indicators",
    "macro_releases",
    "release_stages",
    "release_values",
    "consensus_snapshots",
    "market_instruments",
    "futures_contracts",
    "market_bars",
    "regime_snapshots",
    "analysis_runs",
    "event_window_definitions",
    "event_window_results",
    "market_reactions",
    "historical_matches",
    "explanations",
    "data_quality_records",
    "report_artifacts",
    "provider_runs",
}


def scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise SystemExit(f"database not found: {database}")

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(REQUIRED_TABLES - tables)
        counts = {
            table: scalar(connection, f'SELECT COUNT(*) FROM "{table}"')  # noqa: S608
            for table in sorted(REQUIRED_TABLES & tables)
        }
        orphan_release_values = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM release_values rv
            LEFT JOIN macro_releases mr ON mr.id = rv.macro_release_id
            LEFT JOIN indicators i ON i.id = rv.indicator_id
            WHERE mr.id IS NULL OR i.id IS NULL
            """,
        )
        orphan_bars = scalar(
            connection,
            """
            SELECT COUNT(*)
            FROM market_bars mb
            LEFT JOIN market_instruments mi ON mi.id = mb.instrument_id
            WHERE mi.id IS NULL
            """,
        )
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]

    result = {
        "database": str(database),
        "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        "alembic_revision": revision,
        "missing_tables": missing,
        "orphan_release_values": orphan_release_values,
        "orphan_market_bars": orphan_bars,
        "row_counts": counts,
        "valid": not missing and orphan_release_values == 0 and orphan_bars == 0,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
