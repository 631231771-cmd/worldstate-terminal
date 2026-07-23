import asyncio
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from macro_engine import cli
from macro_engine.config import Settings
from macro_engine.db.models import Observation
from macro_engine.db.session import create_engine
from macro_engine.domain.enums import AvailabilityMethod, AvailabilityPrecision
from macro_engine.domain.models import ObservationRecord, SeriesMetadata
from macro_engine.main import create_app
from macro_engine.providers.fred_alfred import FredAlfredProvider
from macro_engine.services.terminal import (
    build_snapshot,
    ensure_catalog,
    query_series,
    session_factory,
    synchronize,
)
from macro_engine.transforms.core import (
    apply_transform,
    binary_transform,
    moving_average,
    rolling_quantile,
    rolling_zscore,
)


def database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def migrate_database(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MACRO_DATABASE_URL", database_url(path))
    assert cli.run(["migrate"]) == cli.EXIT_OK
    capsys.readouterr()


def test_sqlite_migration_creates_complete_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "migration.db"
    migrate_database(path, monkeypatch, capsys)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"series", "observations", "state_snapshots", "sync_runs"} <= tables


def test_demo_sync_is_idempotent_revision_aware_and_queryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "demo.db"
    migrate_database(path, monkeypatch, capsys)
    settings = Settings(database_url=database_url(path))

    async def exercise() -> None:
        engine = create_engine(settings.database_url)
        try:
            first = await synchronize(engine, settings)
            second = await synchronize(engine, settings)

            assert first.mode == "DEMO"
            assert first.inserted > 9_000
            assert second.inserted == 0
            assert second.updated == 0
            assert second.skipped == first.inserted

            factory = session_factory(engine)
            async with factory() as session:
                revisions = await session.scalar(
                    select(func.count())
                    .select_from(Observation)
                    .where(Observation.is_revised.is_(True))
                )
            assert revisions is not None
            assert revisions > 0

            snapshot = await build_snapshot(engine, settings)
            assert snapshot["mode"] == "DEMO"
            assert len(snapshot["states"]) == 8
            assert all(
                state["score"] is None or -1 <= state["score"] <= 1 for state in snapshot["states"]
            )
            assert snapshot["top_changes"]
            assert snapshot["releases"]

            historical = await query_series(
                engine,
                "US.INFLATION.CPI_HEADLINE",
                transform="yoy",
                as_of=datetime(2025, 1, 15, tzinfo=UTC),
            )
            assert historical is not None
            assert historical["observations"]
            assert all(
                item["vintage_date"] <= date(2025, 1, 15) for item in historical["observations"]
            )

            class FixtureFred:
                key = "fred_alfred"

                def __init__(self, _api_key: str) -> None:
                    pass

                async def fetch_metadata(self, native_id: str) -> SeriesMetadata:
                    return SeriesMetadata(
                        native_id=native_id,
                        title="Live CPI fixture",
                        frequency="monthly",
                        unit="index",
                        source_url=f"https://fred.stlouisfed.org/series/{native_id}",
                    )

                async def fetch_observations(
                    self,
                    native_id: str,
                    *,
                    start: date | None = None,
                    end: date | None = None,
                ) -> AsyncIterator[ObservationRecord]:
                    del start, end
                    yield ObservationRecord(
                        native_id=native_id,
                        period_start=date(2026, 6, 1),
                        period_end=date(2026, 6, 1),
                        value=Decimal("321.0"),
                        raw_value="321.0",
                        vintage_date=date(2026, 7, 1),
                        realtime_start=date(2026, 7, 1),
                        realtime_end=date(9999, 12, 31),
                        available_at=datetime(2026, 7, 1, tzinfo=UTC),
                        availability_method=AvailabilityMethod.PROVIDER_REALTIME_START,
                        availability_precision=AvailabilityPrecision.DAY,
                        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
                        source_hash="a" * 64,
                    )

                async def fetch_releases(
                    self,
                    *,
                    start: date | None = None,
                    end: date | None = None,
                ) -> list[object]:
                    del start, end
                    return []

            monkeypatch.setattr(
                "macro_engine.services.terminal.FredAlfredProvider",
                FixtureFred,
            )
            monkeypatch.setenv("FRED_API_KEY", "test-key")
            live_settings = Settings(database_url=database_url(path))
            live = await synchronize(
                engine,
                live_settings,
                canonical_keys=["CPIAUCSL"],
            )
            async with factory() as session:
                remaining = await session.scalar(select(func.count()).select_from(Observation))
            assert live.mode == "LIVE"
            assert remaining == 1
        finally:
            await engine.dispose()

    asyncio.run(exercise())

    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/snapshot").status_code == 200
        assert len(client.get("/v1/series").json()) == 38
        assert (
            client.get(
                "/v1/series/US.INFLATION.CPI_HEADLINE",
                params={"transform": "yoy"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/v1/series/US.INFLATION.CPI_HEADLINE",
                params={"transform": "not-a-transform"},
            ).status_code
            == 400
        )
        assert client.get("/v1/series/US.DOES.NOT_EXIST").status_code == 404


def test_empty_database_builds_insufficient_states_without_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "empty.db"
    migrate_database(path, monkeypatch, capsys)
    settings = Settings(database_url=database_url(path))

    async def exercise() -> None:
        engine = create_engine(settings.database_url)
        try:
            factory = session_factory(engine)
            async with factory() as session:
                await ensure_catalog(session, settings)
                await session.commit()
            snapshot = await build_snapshot(engine, settings)
            assert snapshot["mode"] == "EMPTY"
            assert all(state["score"] is None for state in snapshot["states"])
            assert all(state["label"] == "insufficient_data" for state in snapshot["states"])
        finally:
            await engine.dispose()

    asyncio.run(exercise())


async def test_fred_parsing_preserves_vintages_and_missing_values() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/series/observations"):
            return httpx.Response(
                200,
                json={
                    "observations": [
                        {
                            "date": "2025-01-01",
                            "realtime_start": "2025-02-01",
                            "realtime_end": "2025-02-28",
                            "value": "100.0",
                        },
                        {
                            "date": "2025-01-01",
                            "realtime_start": "2025-03-01",
                            "realtime_end": "9999-12-31",
                            "value": "101.0",
                        },
                        {
                            "date": "2025-02-01",
                            "realtime_start": "2025-03-01",
                            "realtime_end": "9999-12-31",
                            "value": ".",
                        },
                    ]
                },
            )
        if path.endswith("/series/vintagedates"):
            return httpx.Response(200, json={"vintage_dates": ["2025-02-01", "2025-03-01"]})
        if path.endswith("/releases/dates"):
            return httpx.Response(
                200,
                json={
                    "release_dates": [
                        {
                            "release_id": 10,
                            "release_name": "Fixture release",
                            "date": "2025-04-01",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "seriess": [
                    {
                        "id": "TEST",
                        "title": "Fixture series",
                        "frequency": "Monthly",
                        "units": "Index",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FredAlfredProvider("secret", client)
        metadata = await provider.fetch_metadata("TEST")
        rows = [row async for row in provider.fetch_observations("TEST")]
        search = await provider.search_series("Fixture")
        vintages = await provider.fetch_vintages("TEST")
        releases = await provider.fetch_releases()
        health = await provider.healthcheck()

    assert metadata.title == "Fixture series"
    assert [row.vintage_date for row in rows[:2]] == [date(2025, 2, 1), date(2025, 3, 1)]
    assert rows[0].is_revised is False
    assert rows[1].is_revised is True
    assert rows[2].value is None
    assert rows[2].quality_flags == ["missing_value"]
    assert search[0].native_id == "TEST"
    assert vintages == [date(2025, 2, 1), date(2025, 3, 1)]
    assert releases[0].name == "Fixture release"
    assert health.status == "ok"


def test_point_in_time_transforms_do_not_fill_missing_or_look_forward() -> None:
    values = [100.0, 101.0, None, 104.0, 108.0]

    assert apply_transform(values, "difference") == [None, 1.0, None, None, 4.0]
    assert apply_transform(values, "percent_change")[2] is None
    assert moving_average(values, 3)[2] is None
    assert len(rolling_quantile(list(range(20)), 12)) == 20
    assert rolling_zscore([1.0] * 20, 12)[-1] is None
    assert binary_transform([3.0, None], [1.0, 2.0], "spread") == [2.0, None]
    assert binary_transform([3.0], [0.0], "ratio") == [None]
    complete = [float(value) for value in range(1, 40)]
    for transform in [
        "yoy",
        "qoq",
        "annualized_3m",
        "annualized_6m",
        "moving_average",
        "rolling_percentile",
        "rolling_zscore",
    ]:
        assert len(apply_transform(complete, transform)) == len(complete)
    assert binary_transform([3.0], [1.0], "inversion") == [-2.0]
    assert binary_transform([3.0], [1.0], "real_rate") == [2.0]
    assert binary_transform([3.0], [2.0], "ratio") == [1.5]
    with pytest.raises(ValueError, match="unsupported"):
        apply_transform(complete, "future_magic")
    with pytest.raises(ValueError, match="unsupported"):
        binary_transform([1.0], [1.0], "future_magic")
