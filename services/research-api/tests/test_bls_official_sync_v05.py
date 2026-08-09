from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application import official_sync_service
from worldstate.application.analysis_orchestrator import initialize_research_catalog
from worldstate.application.official_sync_service import (
    sync_bls_actuals,
    sync_bls_calendar,
    sync_official_data,
)
from worldstate.config import Settings
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import Indicator, MacroRelease, ProviderRun, ReleaseValue
from worldstate.db.session import create_engine
from worldstate.provider_kit import (
    BlsOfficialProvider,
    ProviderError,
    ProviderErrorCode,
)


@pytest.fixture
async def bls_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'bls.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _cpi_payload() -> dict[str, object]:
    monthly = {"M01": "0.3", "M02": "0.4", "M03": "0.5"}
    yearly = {"M01": "3.1", "M02": "3.2", "M03": "3.3"}
    values = (
        ("2024", "M03", "312.100"),
        ("2024", "M02", "311.000"),
        ("2024", "M01", "309.800"),
    )

    def series(series_id: str) -> dict[str, object]:
        return {
            "seriesID": series_id,
            "data": [
                {
                    "year": year,
                    "period": period,
                    "value": level,
                    "calculations": {
                        "pct_changes": {"1": monthly[period], "12": yearly[period]}
                    },
                }
                for year, period, level in values
            ],
        }

    return {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {
            "series": [series("CUSR0000SA0"), series("CUSR0000SA0L1E")]
        },
    }


async def _add_observed_release(
    engine: AsyncEngine,
    *,
    release_type: str,
    period_label: str,
    scheduled_at: datetime,
) -> uuid.UUID:
    release_id = uuid.uuid4()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(
            MacroRelease(
                id=release_id,
                release_key=f"test-{release_type.lower()}-{period_label}-{release_id}",
                release_type=release_type,
                title=release_type,
                country="USA",
                period_label=period_label,
                scheduled_at=scheduled_at,
                released_at=scheduled_at,
                source_timezone="America/New_York",
                status="released",
                data_version="calendar-test",
                data_mode="observed",
                contamination_level="unknown",
                clean_window=False,
                overlapping_events=[],
                confounding_notes=[],
                metadata_json={"official_schedule": True},
            )
        )
    return release_id


async def test_bls_actual_range_uses_release_date_and_selected_family(
    bls_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await initialize_research_catalog(bls_engine)
    february_release_id = await _add_observed_release(
        bls_engine,
        release_type="US_CPI",
        period_label="2024-02",
        scheduled_at=datetime(2024, 3, 12, 12, 30, tzinfo=UTC),
    )
    march_release_id = await _add_observed_release(
        bls_engine,
        release_type="US_CPI",
        period_label="2024-03",
        scheduled_at=datetime(2024, 4, 10, 12, 30, tzinfo=UTC),
    )
    nfp_release_id = await _add_observed_release(
        bls_engine,
        release_type="US_NFP",
        period_label="2024-02",
        scheduled_at=datetime(2024, 3, 8, 13, 30, tzinfo=UTC),
    )
    adapter = BlsOfficialProvider()
    batch = adapter.adapt_payload(
        _cpi_payload(),
        family="US_CPI",
        retrieved_at=datetime(2024, 3, 12, 13, 0, tzinfo=UTC),
    )
    calls: list[tuple[str, int, int]] = []

    class FakeBls:
        key = adapter.key
        terms = adapter.terms

        async def fetch_bundle(
            self,
            family: str,
            *,
            start_year: int,
            end_year: int,
            prior_snapshot: object,
        ) -> object:
            calls.append((family, start_year, end_year))
            assert isinstance(prior_snapshot, dict)
            return batch

    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(bls=FakeBls()),
    )
    settings = Settings(database_url="sqlite+aiosqlite://", scheduler_enabled=False)
    result = await sync_bls_actuals(
        bls_engine,
        settings,
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        families=("US_CPI",),
    )
    assert result["status"] == "completed"
    assert calls == [("US_CPI", 2023, 2024)]

    factory = async_sessionmaker(bls_engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.execute(
                select(ReleaseValue, Indicator.indicator_key)
                .join(Indicator, Indicator.id == ReleaseValue.indicator_id)
                .where(ReleaseValue.value_kind == "actual")
            )
        ).all()
    by_release = {
        release_id: {
            indicator_key: value.value
            for value, indicator_key in rows
            if value.macro_release_id == release_id
        }
        for release_id in (february_release_id, march_release_id, nfp_release_id)
    }
    assert by_release[february_release_id] == {
        "headline_mom": Decimal("0.4"),
        "headline_yoy": Decimal("3.2"),
        "core_mom": Decimal("0.4"),
        "core_yoy": Decimal("3.2"),
    }
    assert by_release[march_release_id] == {}
    assert by_release[nfp_release_id] == {}
    headline_row = next(
        value
        for value, indicator_key in rows
        if value.macro_release_id == february_release_id
        and indicator_key == "headline_mom"
    )
    assert headline_row.raw_value == "311.000"
    assert headline_row.source_artifact_id is not None
    assert headline_row.quality_id is not None
    assert headline_row.metadata_json["calculation_source"] == "bls_calculations"
    assert len(headline_row.metadata_json["source_artifact_hash"]) == 64
    assert headline_row.metadata_json["availability_method"] == "ingestion_time_proxy"

    repeated = await sync_bls_actuals(
        bls_engine,
        settings,
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        families=("US_CPI",),
    )
    assert repeated["records_written"] == 0


async def test_bls_actuals_block_without_verified_release_calendar(
    bls_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoNetworkBls:
        key = "bls_official"
        terms = SimpleNamespace(terms_url="https://www.bls.gov/bls/linksite.htm")

        async def fetch_bundle(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("actual API must not run without a release-to-T0 mapping")

    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(bls=NoNetworkBls()),
    )
    result = await sync_bls_actuals(
        bls_engine,
        Settings(database_url="sqlite+aiosqlite://", scheduler_enabled=False),
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        families=("US_CPI",),
    )
    assert result["status"] == "blocked"
    assert result["records_read"] == 0
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    assert "verified T0" in warnings[0]
    factory = async_sessionmaker(bls_engine, expire_on_commit=False)
    async with factory() as session:
        run = await session.scalar(
            select(ProviderRun).where(ProviderRun.operation == "sync_actuals_revisions")
        )
    assert run is not None
    assert run.status == "blocked"
    assert run.error_message is not None


async def test_bls_calendar_network_denial_is_an_explicit_blocker(
    bls_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockedCalendar:
        key = "bls_official"
        terms = SimpleNamespace(terms_url="https://www.bls.gov/bls/linksite.htm")

        async def fetch_schedule(self, family: str, *, year: int) -> object:
            assert family == "US_CPI"
            assert year == 2024
            raise ProviderError(
                self.key,
                ProviderErrorCode.TRANSPORT,
                "BLS schedule returned HTTP 403",
            )

    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(bls=BlockedCalendar()),
    )
    result = await sync_bls_calendar(
        bls_engine,
        Settings(database_url="sqlite+aiosqlite://", scheduler_enabled=False),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        families=("US_CPI",),
    )
    assert result["status"] == "blocked"
    assert result["records_read"] == 0
    assert result["records_written"] == 0
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    assert warnings == ["US_CPI 2024: provider_transport_error"]
    factory = async_sessionmaker(bls_engine, expire_on_commit=False)
    async with factory() as session:
        run = await session.scalar(
            select(ProviderRun).where(ProviderRun.operation == "sync_release_calendar")
        )
    assert run is not None
    assert run.status == "blocked"
    assert run.request_count == 1
    assert run.error_message is not None


async def test_nfp_level_is_differenced_across_year_boundary_and_revisions_append(
    bls_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await initialize_research_catalog(bls_engine)
    release_id = await _add_observed_release(
        bls_engine,
        release_type="US_NFP",
        period_label="2024-01",
        scheduled_at=datetime(2024, 2, 2, 13, 30, tzinfo=UTC),
    )
    adapter = BlsOfficialProvider()
    january_level = Decimal("156200")
    calls: list[tuple[int, int]] = []

    class FakeBls:
        key = adapter.key
        terms = adapter.terms

        async def fetch_bundle(
            self,
            family: str,
            *,
            start_year: int,
            end_year: int,
            prior_snapshot: dict[str, Decimal],
        ) -> object:
            assert family == "US_NFP"
            calls.append((start_year, end_year))
            return adapter.adapt_payload(
                {
                    "status": "REQUEST_SUCCEEDED",
                    "message": [],
                    "Results": {
                        "series": [
                            {
                                "seriesID": "CES0000000001",
                                "data": [
                                    {
                                        "year": "2024",
                                        "period": "M01",
                                        "value": str(january_level),
                                    },
                                    {
                                        "year": "2023",
                                        "period": "M12",
                                        "value": "156000",
                                    },
                                ],
                            }
                        ]
                    },
                },
                family="US_NFP",
                retrieved_at=datetime(2024, 2, 2, 14, 0, tzinfo=UTC),
                prior_snapshot=prior_snapshot,
            )

    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(bls=FakeBls()),
    )
    settings = Settings(database_url="sqlite+aiosqlite://", scheduler_enabled=False)
    first = await sync_bls_actuals(
        bls_engine,
        settings,
        start_date=date(2024, 2, 2),
        end_date=date(2024, 2, 2),
        families=("US_NFP",),
    )
    assert first["records_written"] == 1
    assert calls == [(2023, 2024)]

    factory = async_sessionmaker(bls_engine, expire_on_commit=False)
    async with factory() as session:
        first_value = await session.scalar(
            select(ReleaseValue).where(
                ReleaseValue.macro_release_id == release_id,
                ReleaseValue.value_kind == "actual",
            )
        )
    assert first_value is not None
    assert first_value.value == Decimal("200")
    assert first_value.raw_value == "156200"
    assert first_value.is_initial is True
    assert first_value.metadata_json["raw_unit"] == "thousand_persons_level"
    assert first_value.metadata_json["standard_unit"] == "thousand_persons"

    january_level = Decimal("156210")
    revised = await sync_bls_actuals(
        bls_engine,
        settings,
        start_date=date(2024, 2, 2),
        end_date=date(2024, 2, 2),
        families=("US_NFP",),
    )
    assert revised["records_written"] == 1
    async with factory() as session:
        values = (
            await session.scalars(
                select(ReleaseValue)
                .where(
                    ReleaseValue.macro_release_id == release_id,
                    ReleaseValue.value_kind == "actual",
                )
                .order_by(ReleaseValue.value)
            )
        ).all()
    assert [item.value for item in values] == [Decimal("200"), Decimal("210")]
    assert [item.is_initial for item in values] == [True, False]
    assert values[-1].metadata_json["provider_revision_flag"] is True


async def test_official_aggregate_propagates_child_blockers_and_selection(
    bls_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_families: list[tuple[str, ...]] = []

    async def blocked_bls(
        _engine: AsyncEngine,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
        families: tuple[str, ...],
    ) -> dict[str, object]:
        assert start_date <= end_date
        selected_families.append(families)
        return {"status": "blocked", "warnings": ["simulated provider block"]}

    async def completed_fred(
        _engine: AsyncEngine,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        assert start_date <= end_date
        return {"status": "completed"}

    monkeypatch.setattr(official_sync_service, "sync_bls_calendar", blocked_bls)
    monkeypatch.setattr(official_sync_service, "sync_bls_actuals", blocked_bls)
    monkeypatch.setattr(official_sync_service, "sync_fred_foundation", completed_fred)
    result = await sync_official_data(
        bls_engine,
        Settings(database_url="sqlite+aiosqlite://", scheduler_enabled=False),
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        event_types=("US_CPI",),
    )
    assert result["status"] == "partial"
    assert result["requested_event_types"] == ["US_CPI"]
    assert selected_families == [("US_CPI",), ("US_CPI",)]
    failures = result["failures"]
    assert isinstance(failures, dict)
    assert set(failures) == {"bls_calendar", "bls_actuals"}

    # The shared FRED operation has no family kwarg, so use a matching blocked stub.
    async def blocked_fred(
        _engine: AsyncEngine,
        _settings: Settings,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, object]:
        assert start_date <= end_date
        return {"status": "blocked"}

    monkeypatch.setattr(official_sync_service, "sync_fred_foundation", blocked_fred)
    all_blocked = await sync_official_data(
        bls_engine,
        Settings(database_url="sqlite+aiosqlite://", scheduler_enabled=False),
        start_date=date(2024, 3, 1),
        end_date=date(2024, 3, 31),
        event_types=("US_CPI",),
    )
    assert all_blocked["status"] == "blocked"
