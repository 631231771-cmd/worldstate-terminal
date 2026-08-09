from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.analysis_orchestrator import _consensus_priority
from worldstate.application.backfill_service import (
    BackfillRequest,
    cancel_backfill_job,
    create_backfill_job,
    estimate_backfill,
)
from worldstate.application.data_foundation_service import (
    assert_matching_data_mode,
    associate_source_artifact,
    fail_provider_run,
    record_provider_run,
    record_quota,
    record_source_artifact,
    upsert_entitlement,
)
from worldstate.application.data_manifest_service import (
    record_calendar_snapshot,
    record_market_data_manifest,
)
from worldstate.application.provider_runtime import persist_quality_record
from worldstate.application.reconciliation_service import (
    reconcile_values,
    record_market_reconciliation,
)
from worldstate.application.scheduler_service import (
    ensure_default_schedule,
    schedule_release_tasks,
)
from worldstate.application.sync_service import (
    enqueue_sync_run,
    ensure_sync_job,
    recover_interrupted_runs,
    start_sync_run,
)
from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import (
    AnalysisRun,
    BackfillJob,
    CalendarSnapshot,
    ConsensusSnapshot,
    DataQualityRecord,
    DataReconciliationRecord,
    MacroRelease,
    MarketDataManifest,
    MarketInstrument,
    ProviderRun,
    SourceArtifact,
    SyncJobRun,
)
from worldstate.db.session import create_engine


def test_data_mode_guard_rejects_cross_mode_child() -> None:
    assert_matching_data_mode("observed", "observed", "test-child")
    with pytest.raises(ValueError, match="data_mode mismatch"):
        assert_matching_data_mode("fixture", "observed", "test-child")

T0 = datetime(2026, 7, 14, 12, 30, tzinfo=UTC)


@pytest.fixture
async def data_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'data-v05.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _seed_release_and_instrument(
    engine: AsyncEngine,
    *,
    release_id: uuid.UUID | None = None,
    release_key: str = "us-cpi-2026-07-observed",
) -> tuple[MacroRelease, MarketInstrument]:
    release = MacroRelease(
        id=release_id or uuid.uuid4(),
        release_key=release_key,
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2026-07",
        scheduled_at=T0,
        released_at=T0,
        source_timezone="America/New_York",
        status="released",
        data_version="initial",
        data_mode="observed",
        source_artifact_id=None,
        primary_quality_id=None,
        contamination_level="none",
        clean_window=True,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    instrument = MarketInstrument(
        id=uuid.uuid4(),
        canonical_key=f"GC-{release.id}",
        symbol="GC",
        title="Gold futures",
        asset_class="commodity",
        instrument_type="future",
        exchange="COMEX",
        quote_unit="USD/oz",
        measurement_type="price",
        source_timezone="America/New_York",
        is_proxy=False,
        proxy_for=None,
        active=True,
        metadata_json={},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all([release, instrument])
    return release, instrument


async def test_data_mode_is_first_class_and_release_identity_includes_mode(
    data_engine: AsyncEngine,
) -> None:
    observed, _ = await _seed_release_and_instrument(data_engine)
    fixture = MacroRelease(
        id=uuid.uuid4(),
        release_key="us-cpi-2026-07-fixture",
        release_type=observed.release_type,
        title=observed.title,
        country=observed.country,
        period_label=observed.period_label,
        scheduled_at=observed.scheduled_at,
        released_at=observed.released_at,
        source_timezone=observed.source_timezone,
        status="released",
        data_version="fixture-v1",
        data_mode="fixture",
        source_artifact_id=None,
        primary_quality_id=None,
        contamination_level="none",
        clean_window=True,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    factory = async_sessionmaker(data_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(fixture)
    async with factory() as session:
        modes = set((await session.scalars(select(MacroRelease.data_mode))).all())
    assert modes == {"observed", "fixture"}
    assert AnalysisRun.data_mode.default is not None


async def test_provider_entitlement_quota_run_and_artifact_are_traceable_and_idempotent(
    data_engine: AsyncEngine,
) -> None:
    run = await record_provider_run(
        data_engine,
        provider_key="trading_economics",
        operation="calendar_batch",
        idempotency_key="te:2026-07-14",
        input_data={"date": "2026-07-14"},
    )
    duplicate = await record_provider_run(
        data_engine,
        provider_key="trading_economics",
        operation="calendar_batch",
        idempotency_key="te:2026-07-14",
    )
    assert duplicate.id == run.id

    artifact = await record_source_artifact(
        data_engine,
        source_key="te-calendar-2026-07-14",
        provider_key="trading_economics",
        artifact_type="json",
        title="TE calendar batch",
        source_url="https://api.tradingeconomics.com/calendar",
        content=b'{"CalendarId": 42}',
        content_type="application/json",
        published_at=None,
        retrieved_at=T0,
        license_name="subscription",
        citation_text=None,
        data_mode="observed",
    )
    fixture_artifact = await record_source_artifact(
        data_engine,
        source_key="te-calendar-demo",
        provider_key="trading_economics",
        artifact_type="json",
        title="TE calendar fixture",
        source_url="fixture://te-calendar",
        content=b'{"CalendarId": 42}',
        content_type="application/json",
        retrieved_at=T0,
        data_mode="fixture",
    )
    assert fixture_artifact.id != artifact.id
    factory = async_sessionmaker(data_engine, expire_on_commit=False)
    await associate_source_artifact(
        data_engine,
        provider_run_id=run.id,
        source_artifact_id=artifact.id,
        primary=True,
    )
    entitlement = await upsert_entitlement(
        data_engine,
        provider_key="trading_economics",
        capability="historical_pit_consensus",
        status="denied",
        checked_at=T0,
        provider_run_id=run.id,
        source_artifact_id=artifact.id,
        error_code="ENTITLEMENT_REQUIRED",
    )
    updated = await upsert_entitlement(
        data_engine,
        provider_key="trading_economics",
        capability="historical_pit_consensus",
        status="granted",
        checked_at=T0 + timedelta(hours=1),
    )
    assert updated.id == entitlement.id
    assert updated.status == "granted"
    quota = await record_quota(
        data_engine,
        provider_key="trading_economics",
        quota_key="calendar_requests",
        unit="requests",
        period_start=datetime(2026, 7, 1, tzinfo=UTC),
        period_end=datetime(2026, 8, 1, tzinfo=UTC),
        used_value=Decimal("12"),
        limit_value=Decimal("100"),
        remaining_value=Decimal("88"),
    )
    assert quota.remaining_value == Decimal("88")
    async with factory() as session:
        saved_run = await session.get(ProviderRun, run.id)
        saved_artifact = await session.get(SourceArtifact, artifact.id)
    assert saved_run is not None
    assert saved_run.source_artifact_id == artifact.id
    assert saved_artifact is not None
    assert saved_artifact.provider_run_id == run.id
    assert saved_artifact.content_type == "application/json"
    assert saved_artifact.byte_length == len(saved_artifact.content_bytes or b"")
    assert saved_artifact.content_bytes == b'{"CalendarId": 42}'

    failed = await record_provider_run(
        data_engine,
        provider_key="secret_safety",
        operation="failure",
        idempotency_key="secret-failure",
    )
    await fail_provider_run(
        data_engine,
        failed.id,
        error=(
            "request failed api_key=do-not-persist authorization: Bearer also-secret "
            "headers={'Authorization': 'Client dict-secret'}"
        ),
    )
    async with factory() as session:
        failed_saved = await session.get(ProviderRun, failed.id)
    assert failed_saved is not None
    assert "do-not-persist" not in str(failed_saved.error_message)
    assert "also-secret" not in str(failed_saved.error_message)
    assert "dict-secret" not in str(failed_saved.error_message)
    assert str(failed_saved.error_message).count("[REDACTED]") == 3


async def test_provider_calendar_and_quality_identities_isolate_fixture_from_observed(
    data_engine: AsyncEngine,
) -> None:
    fixture_run = await record_provider_run(
        data_engine,
        provider_key="test_provider",
        operation="same_operation",
        idempotency_key="same-key",
        data_mode="fixture",
    )
    observed_run = await record_provider_run(
        data_engine,
        provider_key="test_provider",
        operation="same_operation",
        idempotency_key="same-key",
        data_mode="observed",
    )
    assert fixture_run.id != observed_run.id

    payload = [{"event": "same bytes and capture time"}]
    fixture_calendar = await record_calendar_snapshot(
        data_engine,
        provider_key="test_provider",
        calendar_kind="TEST",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        captured_at=T0,
        payload=payload,
        data_mode="fixture",
    )
    observed_calendar = await record_calendar_snapshot(
        data_engine,
        provider_key="test_provider",
        calendar_kind="TEST",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        captured_at=T0,
        payload=payload,
        data_mode="observed",
    )
    assert fixture_calendar.id != observed_calendar.id

    fixture_quality = await persist_quality_record(
        data_engine,
        DataQuality(
            source_name="same source",
            source_url="fixture://same",
            source_type="fixture",
            acquired_at=T0,
            is_fixture=True,
            quality_grade=QualityGrade.C,
        ),
        subject_type="test",
        subject_id="same",
        identity="same-quality-identity",
    )
    observed_quality = await persist_quality_record(
        data_engine,
        DataQuality(
            source_name="same source",
            source_url="https://example.test/observed",
            source_type="observed_api",
            acquired_at=T0,
            is_fixture=False,
            quality_grade=QualityGrade.A,
        ),
        subject_type="test",
        subject_id="same",
        identity="same-quality-identity",
    )
    assert fixture_quality.id != observed_quality.id
    factory = async_sessionmaker(data_engine, expire_on_commit=False)
    async with factory() as session:
        modes = set((await session.scalars(select(CalendarSnapshot.data_mode))).all())
        qualities = (await session.scalars(select(DataQualityRecord))).all()
    assert modes >= {"fixture", "observed"}
    assert {row.is_fixture for row in qualities} >= {False, True}


def test_consensus_pit_priority_uses_snapshot_not_deduplicated_artifact_metadata() -> None:
    artifact = SourceArtifact(
        id=uuid.uuid4(),
        provider_run_id=None,
        source_key="te:same-content",
        provider_key="trading_economics",
        artifact_type="application/json",
        title="same licensed payload",
        source_url="https://api.tradingeconomics.com/calendar",
        published_at=None,
        retrieved_at=T0,
        content_hash="a" * 64,
        content_type="application/json",
        byte_length=2,
        content_bytes=b"[]",
        license_name="subscription",
        citation_text=None,
        is_fixture=False,
        data_mode="observed",
        # This metadata belongs to whichever identical raw response happened
        # to be persisted first and must not classify later snapshots.
        metadata_json={"pit_query_at": T0.isoformat()},
    )
    common = {
        "macro_release_id": uuid.uuid4(),
        "indicator_id": uuid.uuid4(),
        "consensus_value": Decimal("0.3"),
        "source_name": "Trading Economics Survey Consensus",
        "source_url": artifact.source_url,
        "captured_at": T0 - timedelta(minutes=5),
        "quality_grade": "B",
        "is_manual": False,
        "data_mode": "observed",
        "verification_notes": None,
        "source_artifact_id": artifact.id,
        "quality_id": None,
    }
    current = ConsensusSnapshot(
        id=uuid.uuid4(),
        metadata_json={"pit_verified": False, "pit_query_at": None},
        **common,
    )
    pit = ConsensusSnapshot(
        id=uuid.uuid4(),
        metadata_json={"pit_verified": True, "pit_query_at": T0.isoformat()},
        **common,
    )
    assert _consensus_priority(current, artifact) == 35
    assert _consensus_priority(pit, artifact) == 50


async def test_scheduler_release_offsets_idempotency_and_restart_retry(
    data_engine: AsyncEngine,
) -> None:
    jobs = await ensure_default_schedule(data_engine, now=T0)
    assert {job.job_key for job in jobs} >= {
        "daily-official-sync",
        "pre-release-consensus-snapshot",
        "post-release-market-sync",
    }
    release_id = uuid.uuid4()
    first = await schedule_release_tasks(data_engine, macro_release_id=release_id, release_at=T0)
    repeated = await schedule_release_tasks(data_engine, macro_release_id=release_id, release_at=T0)
    assert len(first) == 7
    assert {row.id for row in first} == {row.id for row in repeated}
    offsets = sorted(int(row.input_json["offset_minutes"]) for row in first)
    assert offsets == [-1440, -60, -5, 5, 5, 5, 240]

    recovery_job = await ensure_sync_job(
        data_engine,
        job_key="recovery-test",
        operation="test",
        schedule_type="manual",
        schedule={},
        max_attempts=2,
        retry_backoff_seconds=10,
    )
    run = await enqueue_sync_run(
        data_engine,
        sync_job_id=recovery_job.id,
        scheduled_for=T0,
        input_data={"cursor": 4},
    )
    await start_sync_run(data_engine, run.id, now=T0)
    retries = await recover_interrupted_runs(
        data_engine,
        now=T0 + timedelta(minutes=20),
        stale_after_seconds=60,
    )
    assert len(retries) == 1
    assert retries[0].attempt == 2
    assert retries[0].checkpoint_json == {}
    factory = async_sessionmaker(data_engine, expire_on_commit=False)
    async with factory() as session:
        original = await session.get(SyncJobRun, run.id)
    assert original is not None
    assert original.status == "failed"


async def test_backfill_cost_policy_rejection_idempotency_and_cancel(
    data_engine: AsyncEngine,
) -> None:
    request = BackfillRequest(
        start_date=date(2015, 1, 1),
        end_date=date(2026, 7, 14),
        event_types=("US_CPI", "US_NFP", "FOMC"),
        instruments=("GC", "SI", "ES"),
        datasets=("ohlcv-1m", "ohlcv-1d"),
        expected_event_count=200,
    )
    estimate = await estimate_backfill(
        data_engine,
        request,
        budget_limit_usd=Decimal("1"),
        paid_download_allowed=False,
        provider_estimated_cost_usd=Decimal("12.50"),
    )
    assert estimate.execution_allowed is False
    assert estimate.minute_range_per_event == 330
    rejected = await create_backfill_job(data_engine, request, estimate, execute_requested=True)
    repeated = await create_backfill_job(data_engine, request, estimate, execute_requested=True)
    assert rejected.id == repeated.id
    assert rejected.status == "rejected"

    fixture_request = BackfillRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        event_types=("US_CPI",),
        instruments=("GC",),
        datasets=("ohlcv-1m",),
        data_mode="fixture",
        expected_event_count=1,
    )
    fixture_estimate = await estimate_backfill(
        data_engine,
        fixture_request,
        budget_limit_usd=Decimal("0"),
        paid_download_allowed=False,
    )
    pending = await create_backfill_job(
        data_engine, fixture_request, fixture_estimate, execute_requested=True
    )
    cancelled = await cancel_backfill_job(data_engine, pending.id, now=T0)
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None


async def test_reconciliation_is_non_destructive_and_idempotent(
    data_engine: AsyncEngine,
) -> None:
    first = await reconcile_values(
        data_engine,
        subject_type="release_value",
        subject_id="cpi-2026-07:headline_yoy",
        field_name="actual",
        authoritative_provider_key="bls",
        comparison_provider_key="trading_economics",
        authoritative_value=Decimal("2.7"),
        comparison_value=Decimal("2.8"),
        unit="percent",
        tolerance=Decimal("0.01"),
    )
    second = await reconcile_values(
        data_engine,
        subject_type="release_value",
        subject_id="cpi-2026-07:headline_yoy",
        field_name="actual",
        authoritative_provider_key="bls",
        comparison_provider_key="trading_economics",
        authoritative_value=Decimal("2.7"),
        comparison_value=Decimal("2.8"),
        unit="percent",
        tolerance=Decimal("0.01"),
    )
    assert first.id == second.id
    assert first.status == "mismatch"
    assert first.difference_json["authoritative_source_wins"] is True
    factory = async_sessionmaker(data_engine, expire_on_commit=False)
    async with factory() as session:
        count = await session.scalar(select(func.count(DataReconciliationRecord.id)))
    assert count == 1


async def test_overnight_market_reconciliation_preserves_ingestion_checks(
    data_engine: AsyncEngine,
) -> None:
    first = await record_market_reconciliation(
        data_engine,
        subject_id="manifest-rich-checks",
        provider_key="databento",
        checks={
            "contract_active_at_t0": True,
            "ohlc_valid": True,
            "timezone_conversion_valid": True,
            "no_large_gaps": True,
        },
    )
    repeated = await record_market_reconciliation(
        data_engine,
        subject_id="manifest-rich-checks",
        provider_key="databento",
        checks={
            "bars_present": True,
            "stored_rows_cover_manifest": True,
        },
    )
    assert repeated.id == first.id
    checks = repeated.authoritative_value_json["checks"]
    assert checks["contract_active_at_t0"] is True
    assert checks["ohlc_valid"] is True
    assert checks["timezone_conversion_valid"] is True
    assert checks["no_large_gaps"] is True
    assert checks["bars_present"] is True
    assert repeated.status == "matched"


async def test_event_market_manifest_and_calendar_snapshot_are_idempotent(
    data_engine: AsyncEngine,
) -> None:
    release, instrument = await _seed_release_and_instrument(
        data_engine, release_key="us-cpi-manifest"
    )
    manifest = await record_market_data_manifest(
        data_engine,
        macro_release_id=release.id,
        release_stage_id=None,
        provider_key="databento",
        dataset="GLBX.MDP3",
        schema_name="ohlcv-1m",
        instrument_id=instrument.id,
        futures_contract_id=None,
        source_symbol="GCQ6",
        contract_code="GCQ6",
        start_at=T0 - timedelta(minutes=90),
        end_at=T0 + timedelta(hours=4),
        interval_seconds=60,
        row_count=330,
        size_bytes=26_400,
        source_content_hash="b" * 64,
        contract_selection_rule="highest volume before T0",
    )
    duplicate = await record_market_data_manifest(
        data_engine,
        macro_release_id=release.id,
        release_stage_id=None,
        provider_key="databento",
        dataset="GLBX.MDP3",
        schema_name="ohlcv-1m",
        instrument_id=instrument.id,
        futures_contract_id=None,
        source_symbol="GCQ6",
        contract_code="GCQ6",
        start_at=T0 - timedelta(minutes=90),
        end_at=T0 + timedelta(hours=4),
        interval_seconds=60,
        row_count=330,
        size_bytes=26_400,
        source_content_hash="b" * 64,
        contract_selection_rule="highest volume before T0",
    )
    assert duplicate.id == manifest.id
    assert manifest.macro_release_id == release.id
    assert manifest.contract_selection_rule == "highest volume before T0"

    snapshot = await record_calendar_snapshot(
        data_engine,
        provider_key="federal_reserve",
        calendar_kind="FOMC",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        captured_at=T0,
        payload=[{"meeting_date": "2026-07-29"}],
    )
    again = await record_calendar_snapshot(
        data_engine,
        provider_key="federal_reserve",
        calendar_kind="FOMC",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        captured_at=T0,
        payload=[{"meeting_date": "2026-07-29"}],
    )
    assert snapshot.id == again.id
    factory = async_sessionmaker(data_engine, expire_on_commit=False)
    async with factory() as session:
        manifest_count = await session.scalar(select(func.count(MarketDataManifest.id)))
        backfill_count = await session.scalar(select(func.count(BackfillJob.id)))
    assert manifest_count == 1
    assert backfill_count == 0
