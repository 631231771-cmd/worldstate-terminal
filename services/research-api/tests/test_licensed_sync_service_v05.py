from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Never

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.analysis_orchestrator import initialize_research_catalog
from worldstate.application.data_foundation_service import record_source_artifact
from worldstate.application.data_manifest_service import record_market_data_manifest
from worldstate.application.licensed_sync_service import (
    snapshot_trading_economics_consensus,
    sync_databento_release_market,
)
from worldstate.config import Settings
from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import (
    ConsensusSnapshot,
    DataQualityRecord,
    DataReconciliationRecord,
    Indicator,
    MacroRelease,
    MarketInstrument,
    ProviderRun,
    ReleaseValue,
)
from worldstate.db.session import create_engine
from worldstate.provider_kit import (
    ConsensusCalendarBatch,
    ConsensusSnapshotRecord,
    DatabentoCostEstimate,
    DatabentoDownloadRequest,
    DatabentoMarketProvider,
    ProviderError,
    ProviderErrorCode,
    TradingEconomicsConsensusProvider,
    TradingEconomicsEntitlement,
    TradingEconomicsQuota,
)
from worldstate.provider_kit import (
    SourceArtifact as ProviderSourceArtifact,
)


async def _database(tmp_path: Path) -> tuple[AsyncEngine, uuid.UUID, MarketInstrument]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'licensed.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await initialize_research_catalog(engine)
    release_id = uuid.uuid4()
    released_at = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        instrument = await session.scalar(
            select(MarketInstrument).where(MarketInstrument.canonical_key == "gold_gc")
        )
        assert instrument is not None
        session.add(
            MacroRelease(
                id=release_id,
                release_key="test-cpi-observed",
                release_type="US_CPI",
                title="Test CPI",
                country="USA",
                period_label="2024-02",
                scheduled_at=released_at,
                released_at=released_at,
                source_timezone="America/New_York",
                status="released",
                data_version="test-v1",
                data_mode="observed",
                contamination_level="unknown",
                clean_window=False,
                overlapping_events=[],
                confounding_notes=[],
                metadata_json={},
            )
        )
    return engine, release_id, instrument


async def test_databento_aggregate_budget_blocks_before_contract_or_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, release_id, _instrument = await _database(tmp_path)
    provider = DatabentoMarketProvider(
        "secret",
        max_estimated_cost_usd=Decimal("0.10"),
        allow_paid_download=True,
    )
    resolved = 0

    async def estimate(request: DatabentoDownloadRequest) -> DatabentoCostEstimate:
        return provider.estimate_cost(
            request,
            provider_cost_usd=Decimal("0.06"),
            provider_record_count=10,
            provider_billable_bytes=640,
        )

    async def resolve(*_args: object, **_kwargs: object) -> Never:
        nonlocal resolved
        resolved += 1
        raise AssertionError("aggregate gate must run before symbology")

    monkeypatch.setattr(provider, "estimate_download", estimate)
    monkeypatch.setattr(provider, "resolve_contract_online", resolve)
    monkeypatch.setattr(
        "worldstate.application.licensed_sync_service.build_provider_clients",
        lambda _settings: SimpleNamespace(databento=provider),
    )
    settings = Settings(
        database_url="sqlite+aiosqlite:///unused.db",
        databento_api_key="secret",
        allow_paid_download=True,
        databento_max_estimated_cost_usd=Decimal("0.10"),
        scheduler_enabled=False,
    )
    with pytest.raises(ProviderError) as error:
        await sync_databento_release_market(
            engine,
            settings,
            release_id=release_id,
            roots=("GC", "SI"),
            include_daily=False,
            available_until=datetime(2024, 3, 12, 16, 30, tzinfo=UTC),
        )
    assert error.value.error_code == ProviderErrorCode.BUDGET_EXCEEDED
    assert resolved == 0
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        run = await session.scalar(select(ProviderRun))
        assert run is not None
        assert run.status == "blocked"
    await engine.dispose()


async def test_existing_manifest_skips_paid_redownload_even_without_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, release_id, instrument = await _database(tmp_path)
    t0 = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    start = t0 - timedelta(minutes=90)
    end = t0 + timedelta(minutes=240)
    manifest = await record_market_data_manifest(
        engine,
        macro_release_id=release_id,
        release_stage_id=None,
        provider_key="databento",
        dataset="GLBX.MDP3",
        schema_name="ohlcv-1m",
        instrument_id=instrument.id,
        futures_contract_id=None,
        source_symbol="GC.v.0",
        contract_code="GCJ4",
        start_at=start,
        end_at=end,
        interval_seconds=60,
        row_count=300,
        size_bytes=1000,
        source_content_hash="a" * 64,
        data_mode="observed",
    )
    provider = DatabentoMarketProvider(None, allow_paid_download=False)

    async def unexpected(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("covered data must not call Databento")

    monkeypatch.setattr(provider, "estimate_download", unexpected)
    monkeypatch.setattr(provider, "resolve_contract_online", unexpected)
    monkeypatch.setattr(
        "worldstate.application.licensed_sync_service.build_provider_clients",
        lambda _settings: SimpleNamespace(databento=provider),
    )
    result = await sync_databento_release_market(
        engine,
        Settings(scheduler_enabled=False),
        release_id=release_id,
        roots=("GC",),
        include_daily=False,
        available_until=end,
    )
    assert result["status"] == "completed"
    assert result["cache_only"] is True
    assert result["manifest_ids"] == [str(manifest.id)]
    assert result["estimated_cost_usd"] == "0"
    await engine.dispose()


async def test_disjoint_manifests_do_not_fake_complete_cache_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, release_id, instrument = await _database(tmp_path)
    t0 = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    start = t0 - timedelta(minutes=90)
    end = t0 + timedelta(minutes=240)
    for index, (slice_start, slice_end) in enumerate(
        (
            (start, start + timedelta(minutes=30)),
            (start + timedelta(minutes=60), end),
        )
    ):
        await record_market_data_manifest(
            engine,
            macro_release_id=release_id,
            release_stage_id=None,
            provider_key="databento",
            dataset="GLBX.MDP3",
            schema_name="ohlcv-1m",
            instrument_id=instrument.id,
            futures_contract_id=None,
            source_symbol="GC.v.0",
            contract_code="GCJ4",
            start_at=slice_start,
            end_at=slice_end,
            interval_seconds=60,
            row_count=30,
            size_bytes=100,
            source_content_hash=str(index + 1) * 64,
            data_mode="observed",
        )
    provider = DatabentoMarketProvider(None, allow_paid_download=False)
    quote_calls = 0

    async def quote(request: DatabentoDownloadRequest) -> DatabentoCostEstimate:
        nonlocal quote_calls
        quote_calls += 1
        return provider.estimate_cost(request)

    async def forbidden(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("missing-key gate must run before symbology")

    monkeypatch.setattr(provider, "estimate_download", quote)
    monkeypatch.setattr(provider, "resolve_contract_online", forbidden)
    monkeypatch.setattr(
        "worldstate.application.licensed_sync_service.build_provider_clients",
        lambda _settings: SimpleNamespace(databento=provider),
    )
    with pytest.raises(ProviderError) as error:
        await sync_databento_release_market(
            engine,
            Settings(scheduler_enabled=False),
            release_id=release_id,
            roots=("GC",),
            include_daily=False,
            available_until=end,
        )
    assert error.value.error_code == ProviderErrorCode.NOT_CONFIGURED
    assert quote_calls == 1
    await engine.dispose()


async def test_fallback_quote_never_authorizes_paid_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, release_id, _instrument = await _database(tmp_path)
    provider = DatabentoMarketProvider(
        "secret",
        max_estimated_cost_usd=Decimal("10"),
        allow_paid_download=True,
    )

    async def quote(request: DatabentoDownloadRequest) -> DatabentoCostEstimate:
        return provider.estimate_cost(request)

    async def forbidden(*_args: object, **_kwargs: object) -> Never:
        raise AssertionError("untrusted cost estimate must block before symbology")

    monkeypatch.setattr(provider, "estimate_download", quote)
    monkeypatch.setattr(provider, "resolve_contract_online", forbidden)
    monkeypatch.setattr(
        "worldstate.application.licensed_sync_service.build_provider_clients",
        lambda _settings: SimpleNamespace(databento=provider),
    )
    settings = Settings(
        databento_api_key="secret",
        allow_paid_download=True,
        databento_max_estimated_cost_usd=Decimal("10"),
        scheduler_enabled=False,
    )
    with pytest.raises(ProviderError) as error:
        await sync_databento_release_market(
            engine,
            settings,
            release_id=release_id,
            roots=("GC",),
            include_daily=False,
            available_until=datetime(2024, 3, 12, 16, 30, tzinfo=UTC),
        )
    assert error.value.error_code == ProviderErrorCode.COST_ESTIMATE_UNAVAILABLE
    await engine.dispose()


async def test_te_cross_check_compares_all_fields_and_downgrades_quality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, release_id, _instrument = await _database(tmp_path)
    release_at = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    official_artifact = await record_source_artifact(
        engine,
        source_key="bls:test-cpi-2024-02",
        provider_key="bls_official",
        artifact_type="application/json",
        title="BLS CPI official test payload",
        source_url="https://www.bls.gov/cpi/",
        content=b'{"official":true}',
        content_type="application/json",
        retrieved_at=release_at,
        data_mode="observed",
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        release = await session.get(MacroRelease, release_id)
        indicator = await session.scalar(
            select(Indicator).where(Indicator.indicator_key == "headline_mom")
        )
        assert release is not None
        assert indicator is not None
        release.source_artifact_id = official_artifact.id
        for value_kind, value in (
            ("actual", Decimal("0.3")),
            ("previous", Decimal("0.2")),
            ("revised_previous", Decimal("0.25")),
        ):
            session.add(
                ReleaseValue(
                    id=uuid.uuid4(),
                    macro_release_id=release.id,
                    release_stage_id=None,
                    indicator_id=indicator.id,
                    value_kind=value_kind,
                    value=value,
                    raw_value=str(value),
                    data_version="official-v1",
                    valid_from=release_at,
                    captured_at=release_at,
                    is_initial=value_kind == "actual",
                    data_mode="observed",
                    source_artifact_id=official_artifact.id,
                    quality_id=None,
                    metadata_json={"reference_period": "2024-02"},
                )
            )

    provider = TradingEconomicsConsensusProvider(
        "secret",
        pit_entitled=True,
        monthly_quota=100,
        monthly_requests_used=7,
    )
    captured_at = release_at - timedelta(minutes=5)
    raw_content = b'[{"CalendarId":"test-cpi"}]'
    te_artifact = ProviderSourceArtifact.capture(
        provider_key=provider.key,
        source_url="https://api.tradingeconomics.com/calendar",
        retrieved_at=captured_at,
        content_type="application/json",
        content=raw_content,
        terms=provider.terms,
        metadata={"title": "TE comparison fixture for service test"},
    )
    snapshot = ConsensusSnapshotRecord(
        calendar_id="test-cpi",
        ticker="USCPI",
        event="CPI MoM",
        country="United States",
        reference="Feb 2024",
        release_at=release_at,
        actual=Decimal("0.4"),
        previous=Decimal("0.2"),
        revised=Decimal("0.25"),
        survey_consensus=Decimal("0.3"),
        te_forecast=Decimal("0.35"),
        raw_actual="0.4%",
        raw_previous="0.2%",
        raw_revised="0.25%",
        raw_survey_consensus="0.3%",
        raw_te_forecast="0.35%",
        unit="%",
        captured_at=captured_at,
        pit_query_at=None,
        pit_verified=False,
        artifact_hash=te_artifact.content_hash,
        license_name=provider.terms.license_name,
    )
    batch = ConsensusCalendarBatch(
        provider_key=provider.key,
        retrieved_at=captured_at,
        artifacts=(te_artifact,),
        quality=DataQuality(
            source_name="Trading Economics",
            source_url="https://api.tradingeconomics.com/calendar",
            source_type="licensed_api",
            acquired_at=captured_at,
            is_verified=True,
            quality_grade=QualityGrade.B,
        ),
        idempotency_key="te-service-test",
        snapshots=(snapshot,),
        entitlement=TradingEconomicsEntitlement(
            calendar=True,
            historical_point_in_time=True,
        ),
        quota=TradingEconomicsQuota(
            monthly_limit=100,
            monthly_used=8,
            remaining=92,
            observed_at=captured_at,
        ),
    )

    async def fetch_calendar(*args: object, **kwargs: object) -> ConsensusCalendarBatch:
        del args, kwargs
        return batch

    monkeypatch.setattr(provider, "fetch_calendar", fetch_calendar)
    monkeypatch.setattr(
        "worldstate.application.licensed_sync_service.build_provider_clients",
        lambda _settings, **_kwargs: SimpleNamespace(trading_economics=provider),
    )
    result = await snapshot_trading_economics_consensus(
        engine,
        Settings(
            database_url="sqlite+aiosqlite:///unused.db",
            trading_economics_api_key="secret",
            trading_economics_pit_entitled=True,
            trading_economics_monthly_quota=100,
            scheduler_enabled=False,
        ),
        start_date=release_at.date(),
        end_date=release_at.date(),
    )
    assert result["status"] == "completed"
    assert result["quality_grade"] == "C"
    assert result["reconciliation_statuses"] == {"matched": 5, "mismatch": 1}

    async with factory() as session:
        reconciliations = (
            await session.scalars(
                select(DataReconciliationRecord).order_by(DataReconciliationRecord.field_name)
            )
        ).all()
        consensus = await session.scalar(
            select(ConsensusSnapshot).where(ConsensusSnapshot.macro_release_id == release_id)
        )
        quality = await session.scalar(
            select(DataQualityRecord).where(DataQualityRecord.subject_type == "consensus_calendar")
        )
    assert {row.field_name for row in reconciliations} == {
        "actual",
        "previous",
        "revised_previous",
        "headline_mom.reference_period",
        "headline_mom.release_time",
        "headline_mom.unit",
    }
    assert all(row.authoritative_artifact_id == official_artifact.id for row in reconciliations)
    assert all(row.comparison_artifact_id is not None for row in reconciliations)
    assert consensus is not None
    assert consensus.quality_grade == "C"
    assert quality is not None
    assert quality.quality_grade == "C"
    await engine.dispose()
