from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.api.v2.data_router import build_provider_status
from worldstate.application.backfill_service import (
    BackfillRequest,
    cancel_backfill_job,
    create_backfill_job,
    estimate_backfill,
)
from worldstate.application.backfill_worker import (
    BackfillWorker,
    assess_release_analysis_inputs,
    claim_next_backfill,
    recover_interrupted_backfills,
)
from worldstate.application.scheduler_runtime import (
    SchedulerRuntime,
    enqueue_release_relative_jobs,
    execute_scheduled_operation,
    run_scheduler_cycle,
)
from worldstate.application.scheduler_service import (
    claim_next_run,
    enqueue_due_jobs,
    ensure_default_schedule,
)
from worldstate.application.sync_service import (
    enqueue_sync_run,
    ensure_sync_job,
    fail_sync_run,
    start_sync_run,
)
from worldstate.config import Settings
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import (
    BackfillJob,
    ConsensusSnapshot,
    Indicator,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    MarketInstrument,
    ProviderQuota,
    ProviderRun,
    ReleaseStage,
    ReleaseValue,
    SyncJob,
    SyncJobRun,
)
from worldstate.db.session import create_engine
from worldstate.provider_kit import ProviderError, ProviderErrorCode

T0 = datetime(2026, 7, 14, 12, 30, tzinfo=UTC)


@pytest.fixture
async def worker_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'workers.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "sqlite+aiosqlite://",
        "ai_provider": "none",
        "scheduler_enabled": False,
        "allow_paid_download": True,
        "databento_max_estimated_cost_usd": Decimal("1"),
        "fred_api_key": "fred-test",
        "trading_economics_api_key": "te-test",
        "trading_economics_pit_entitled": True,
        "databento_api_key": "db-test",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


async def _pending_backfill(
    engine: AsyncEngine,
    *,
    data_mode: str = "observed",
) -> BackfillJob:
    request = BackfillRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        event_types=("US_CPI",),
        instruments=("GC",),
        datasets=("ohlcv-1m",),
        data_mode=data_mode,  # type: ignore[arg-type]
        expected_event_count=1,
    )
    estimate = await estimate_backfill(
        engine,
        request,
        budget_limit_usd=Decimal("1"),
        paid_download_allowed=True,
        provider_estimated_cost_usd=Decimal("0.25"),
    )
    return await create_backfill_job(engine, request, estimate, execute_requested=True)


async def _observed_release(
    engine: AsyncEngine,
    *,
    suffix: str,
    with_analysis_inputs: bool = False,
    initial_actual: bool = True,
    day: int = 13,
) -> MacroRelease:
    release_at = datetime(2026, 1, day, 13, 30, tzinfo=UTC)
    release = MacroRelease(
        id=uuid.uuid4(),
        release_key=f"worker-cpi-{suffix}",
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2025-12",
        scheduled_at=release_at,
        released_at=release_at,
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
    stage = ReleaseStage(
        id=uuid.uuid4(),
        macro_release_id=release.id,
        stage_key="release",
        title="CPI release",
        sequence=1,
        scheduled_at=release_at,
        released_at=release_at,
        status="released",
        source_artifact_id=None,
        metadata_json={},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all([release, stage])
        if with_analysis_inputs:
            indicator = Indicator(
                id=uuid.uuid4(),
                indicator_key=f"US_CPI_HEADLINE_MOM_{suffix}",
                name="Headline CPI MoM",
                family="inflation",
                country="USA",
                unit="percent",
                periodicity="monthly",
                description=None,
                hotter_when_higher=True,
                bundle_weight=1,
                active=True,
                metadata_json={},
            )
            instrument = MarketInstrument(
                id=uuid.uuid4(),
                canonical_key=f"GC_WORKER_{suffix}",
                symbol="GC",
                title="Gold",
                asset_class="commodity",
                instrument_type="future",
                exchange="COMEX",
                quote_unit="USD",
                measurement_type="price",
                source_timezone="America/Chicago",
                is_proxy=False,
                proxy_for=None,
                active=True,
                metadata_json={},
            )
            session.add_all([indicator, instrument])
            session.add(
                ReleaseValue(
                    id=uuid.uuid4(),
                    macro_release_id=release.id,
                    release_stage_id=stage.id,
                    indicator_id=indicator.id,
                    value_kind="actual",
                    value=Decimal("0.3"),
                    raw_value="0.3",
                    data_version="initial",
                    valid_from=release_at,
                    captured_at=release_at,
                    is_initial=initial_actual,
                    data_mode="observed",
                    source_artifact_id=None,
                    quality_id=None,
                    metadata_json=(
                        {}
                        if initial_actual
                        else {
                            "historical_initial_status": (
                                "not_reconstructable_from_current_bls_api"
                            )
                        }
                    ),
                )
            )
            session.add(
                ConsensusSnapshot(
                    id=uuid.uuid4(),
                    macro_release_id=release.id,
                    indicator_id=indicator.id,
                    consensus_value=Decimal("0.2"),
                    source_name="manual verified",
                    source_url=None,
                    captured_at=release_at - timedelta(minutes=10),
                    quality_grade="B",
                    is_manual=True,
                    data_mode="observed",
                    verification_notes="test",
                    source_artifact_id=None,
                    quality_id=None,
                )
            )
            session.add(
                MarketBar(
                    instrument_id=instrument.id,
                    futures_contract_id=None,
                    timestamp=release_at,
                    interval_seconds=60,
                    open_value=Decimal("2000"),
                    high_value=Decimal("2001"),
                    low_value=Decimal("1999"),
                    close_value=Decimal("2000.5"),
                    volume=Decimal("100"),
                    provider_key="databento",
                    data_mode="observed",
                    source_symbol="GCG6",
                    contract_code="GCG6",
                    is_regular_session=True,
                    quality_id=None,
                    fetched_at=release_at,
                    metadata_json={},
                )
            )
            session.add(
                MarketDataManifest(
                    id=uuid.uuid4(),
                    manifest_hash=(suffix * 64)[:64],
                    macro_release_id=release.id,
                    release_stage_id=stage.id,
                    provider_key="databento",
                    dataset="GLBX.MDP3",
                    schema_name="ohlcv-1m",
                    instrument_id=instrument.id,
                    futures_contract_id=None,
                    source_symbol="GCG6",
                    contract_code="GCG6",
                    start_at=release_at - timedelta(minutes=1),
                    end_at=release_at + timedelta(minutes=1),
                    interval_seconds=60,
                    row_count=1,
                    size_bytes=80,
                    data_mode="observed",
                    quality_grade="B",
                    is_aggregated=False,
                    aggregation_method=None,
                    aggregation_version=None,
                    contract_selection_rule="point in time",
                    continuous_resolution_json={},
                    roll_status="resolved",
                    estimated_cost_usd=Decimal("0"),
                    actual_cost_usd=Decimal("0"),
                    provider_run_id=None,
                    sync_job_run_id=None,
                    source_artifact_id=None,
                    metadata_json={},
                )
            )
    return release


async def test_scheduler_due_job_executes_once_and_is_idempotent(
    worker_engine: AsyncEngine,
) -> None:
    jobs = await ensure_default_schedule(worker_engine, now=T0)
    target = next(job for job in jobs if job.job_key == "daily-official-sync")
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        persisted = await session.get(SyncJob, target.id)
        assert persisted is not None
        persisted.next_run_at = T0 - timedelta(minutes=1)

    calls: list[uuid.UUID] = []

    async def executor(
        engine: AsyncEngine,
        settings: Settings,
        run: SyncJobRun,
        job: SyncJob,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del engine, settings, job, now
        calls.append(run.id)
        return {"status": "completed", "records_read": 3, "records_written": 2}

    first = await run_scheduler_cycle(
        worker_engine,
        _settings(),
        now=T0,
        executor=executor,
        max_runs=1,
    )
    second = await run_scheduler_cycle(
        worker_engine,
        _settings(),
        now=T0,
        executor=executor,
        max_runs=1,
    )
    assert first["daily_enqueued"] == 1
    assert first["completed"] == 1
    assert second["daily_enqueued"] == 0
    assert calls
    assert len(calls) == 1
    async with factory() as session:
        run = await session.get(SyncJobRun, calls[0])
        run_count = await session.scalar(select(func.count(SyncJobRun.id)))
    assert run is not None
    assert run.status == "completed"
    assert run.records_written == 2
    assert run_count == 1


async def test_sqlite_scheduler_claim_is_atomic_across_concurrent_workers(
    worker_engine: AsyncEngine,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="atomic-claim",
        operation="provider-sync",
        schedule_type="manual",
        schedule={},
    )
    run = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0,
        input_data={},
    )
    claimed = await asyncio.gather(
        claim_next_run(worker_engine, now=T0),
        claim_next_run(worker_engine, now=T0),
    )
    claimed_ids = [item.id for item in claimed if item is not None]
    assert claimed_ids == [run.id]

    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session:
        persisted = await session.get(SyncJobRun, run.id)
    assert persisted is not None
    assert persisted.status == "running"


async def test_expected_provider_block_is_not_persisted_as_scheduler_failure(
    worker_engine: AsyncEngine,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="blocked-provider",
        operation="snapshot_consensus",
        schedule_type="manual",
        schedule={},
    )
    run = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0,
    )

    async def executor(
        engine: AsyncEngine,
        settings: Settings,
        run: SyncJobRun,
        job: SyncJob,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del engine, settings, run, job, now
        raise ProviderError(
            "trading_economics",
            ProviderErrorCode.NOT_CONFIGURED,
            "provider is not configured",
        )

    result = await run_scheduler_cycle(
        worker_engine,
        _settings(),
        now=T0,
        executor=executor,
        max_runs=1,
    )
    assert result["blocked"] == 1
    assert result["failed"] == 0
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session:
        persisted = await session.get(SyncJobRun, run.id)
    assert persisted is not None
    assert persisted.status == "completed"
    assert persisted.output_json["status"] == "blocked"


async def test_first_desktop_start_catches_up_today_once(
    worker_engine: AsyncEngine,
) -> None:
    jobs = await ensure_default_schedule(
        worker_engine,
        now=T0,
        catch_up_missed=True,
    )
    daily = [job for job in jobs if job.schedule_type == "daily"]
    assert {job.job_key for job in daily} == {
        "daily-provider-health",
        "daily-official-sync",
        "daily-calendar-sync",
        "overnight-reconciliation",
    }
    assert all(job.next_run_at is not None and job.next_run_at <= T0 for job in daily)

    first = await enqueue_due_jobs(worker_engine, now=T0)
    repeated = await enqueue_due_jobs(worker_engine, now=T0)
    assert len(first) == len(daily)
    assert repeated == []
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session:
        persisted = (
            await session.scalars(select(SyncJob).where(SyncJob.schedule_type == "daily"))
        ).all()
    assert all(
        job.next_run_at is not None and job.next_run_at.replace(tzinfo=UTC) > T0
        for job in persisted
    )


@pytest.mark.parametrize(
    ("offset_minutes", "scheduled_for", "now", "expected_pit", "expected_mode"),
    [
        (-5, T0 - timedelta(minutes=5), T0 - timedelta(minutes=4), None, "current_capture"),
        (5, T0 + timedelta(minutes=5), T0 + timedelta(minutes=6), None, "current_capture"),
        (
            -5,
            T0 - timedelta(minutes=5),
            T0 + timedelta(minutes=1),
            T0 - timedelta(minutes=5),
            "historical_pit_replay",
        ),
    ],
)
async def test_consensus_scheduler_uses_current_capture_unless_run_was_missed(
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    offset_minutes: int,
    scheduled_for: datetime,
    now: datetime,
    expected_pit: datetime | None,
    expected_mode: str,
) -> None:
    release = MacroRelease(
        id=uuid.uuid4(),
        release_key=f"snapshot-mode-{offset_minutes}-{scheduled_for.isoformat()}",
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2026-06",
        scheduled_at=T0,
        released_at=None,
        source_timezone="America/New_York",
        status="scheduled",
        data_version="scheduled",
        data_mode="observed",
        source_artifact_id=None,
        primary_quality_id=None,
        contamination_level="unknown",
        clean_window=False,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(release)
    job = await ensure_sync_job(
        worker_engine,
        job_key=f"snapshot-mode-{uuid.uuid4()}",
        provider_key="trading_economics",
        operation="snapshot_consensus",
        schedule_type="release_relative",
        schedule={"offset_minutes": [offset_minutes]},
    )
    run = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=scheduled_for,
        input_data={
            "macro_release_id": str(release.id),
            "offset_minutes": offset_minutes,
        },
    )
    observed_pit: list[datetime | None] = []

    async def snapshot(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        observed_pit.append(kwargs.get("pit_at"))  # type: ignore[arg-type]
        return {"status": "completed", "records_written": 1}

    monkeypatch.setattr(
        "worldstate.application.scheduler_runtime.snapshot_trading_economics_consensus",
        snapshot,
    )
    result = await execute_scheduled_operation(
        worker_engine,
        _settings(),
        run,
        job,
        now=now,
    )
    assert observed_pit == [expected_pit]
    assert result["snapshot_mode"] == expected_mode


async def test_periodic_scheduler_cycle_recovers_a_run_after_it_becomes_stale(
    worker_engine: AsyncEngine,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="periodic-recovery",
        operation="noop",
        schedule_type="manual",
        schedule={},
        max_attempts=2,
    )
    original = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0 - timedelta(minutes=20),
    )
    await start_sync_run(worker_engine, original.id, now=T0 - timedelta(minutes=20))
    result = await run_scheduler_cycle(
        worker_engine,
        _settings(),
        now=T0,
        max_runs=0,
    )
    assert result["recovered"] == 1
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session:
        old = await session.get(SyncJobRun, original.id)
        retry = await session.scalar(
            select(SyncJobRun).where(SyncJobRun.retry_of_id == original.id)
        )
    assert old is not None
    assert old.status == "failed"
    assert retry is not None
    assert retry.status == "retry_wait"


async def test_overnight_reconciliation_uses_persisted_checks_not_te_fetch(
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="reconcile-direct",
        operation="reconcile_data",
        schedule_type="manual",
        schedule={},
    )
    run = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0,
    )
    called = 0

    async def reconcile(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal called
        del args, kwargs
        called += 1
        return {"status": "completed", "source_comparisons": 2}

    async def forbidden(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        raise AssertionError("overnight reconciliation must not fetch TE")

    monkeypatch.setattr(
        "worldstate.application.scheduler_runtime.reconcile_persisted_data",
        reconcile,
    )
    monkeypatch.setattr(
        "worldstate.application.scheduler_runtime.snapshot_trading_economics_consensus",
        forbidden,
    )
    result = await execute_scheduled_operation(
        worker_engine,
        _settings(),
        run,
        job,
        now=T0,
    )
    assert called == 1
    assert result["source_comparisons"] == 2


async def test_daily_provider_health_is_persisted_without_te_quota_request(
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="provider-health-direct",
        operation="record_provider_health",
        schedule_type="manual",
        schedule={},
    )
    run = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0,
    )

    async def forbidden_healthcheck(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("daily configuration health must not make a TE request")

    monkeypatch.setattr(
        "worldstate.provider_kit.trading_economics.TradingEconomicsConsensusProvider.healthcheck",
        forbidden_healthcheck,
    )
    result = await execute_scheduled_operation(
        worker_engine,
        _settings(),
        run,
        job,
        now=T0,
    )
    assert result["network_requests"] == 0
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session:
        te_health = await session.scalar(
            select(ProviderRun).where(
                ProviderRun.provider_key == "trading_economics",
                ProviderRun.operation == "configuration_health_snapshot",
            )
        )
        quota_count = await session.scalar(select(func.count(ProviderQuota.id)))
    assert te_health is not None
    assert te_health.request_count == 0
    assert te_health.output_json["health_status"] == "configured_unverified"
    assert te_health.output_json["network_probe"] is False
    assert quota_count == 0
    provider_status = await build_provider_status(worker_engine, _settings())
    te_status = next(
        item
        for item in provider_status["items"]
        if item["provider_id"] == "trading_economics_consensus"
    )
    assert te_status["status"] == "configured_unverified"
    assert te_status["healthy"] is None
    assert te_status["health_source"] == "persisted_configuration"


async def test_scheduler_failure_is_durable_and_creates_retry(
    worker_engine: AsyncEngine,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="failure-test",
        operation="test_failure",
        schedule_type="manual",
        schedule={},
        max_attempts=2,
        retry_backoff_seconds=1,
    )
    original = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0,
    )

    async def failing_executor(
        engine: AsyncEngine,
        settings: Settings,
        run: SyncJobRun,
        job: SyncJob,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del engine, settings, run, job, now
        raise RuntimeError("provider entitlement denied")

    result = await run_scheduler_cycle(
        worker_engine,
        _settings(),
        now=T0,
        executor=failing_executor,
        max_runs=1,
    )
    assert result["failed"] == 1
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session:
        old = await session.get(SyncJobRun, original.id)
        retries = (
            await session.scalars(select(SyncJobRun).where(SyncJobRun.retry_of_id == original.id))
        ).all()
    assert old is not None
    assert old.status == "failed"
    assert old.error_message == "provider entitlement denied"
    assert len(retries) == 1
    assert retries[0].status == "retry_wait"


async def test_release_relative_scan_includes_deferred_session_windows(
    worker_engine: AsyncEngine,
) -> None:
    await ensure_default_schedule(worker_engine, now=T0)
    release = MacroRelease(
        id=uuid.uuid4(),
        release_key="scheduler-cpi-2026-07",
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2026-06",
        scheduled_at=T0 + timedelta(days=1),
        released_at=None,
        source_timezone="America/New_York",
        status="scheduled",
        data_version="scheduled",
        data_mode="observed",
        source_artifact_id=None,
        primary_quality_id=None,
        contamination_level="unknown",
        clean_window=False,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(release)
    first = await enqueue_release_relative_jobs(worker_engine, now=T0)
    repeated = await enqueue_release_relative_jobs(worker_engine, now=T0)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(SyncJobRun).where(
                    SyncJobRun.input_json["macro_release_id"].as_string() == str(release.id)
                )
            )
        ).all()
    assert first == 9
    assert repeated == 9
    assert len(rows) == 9
    assert {row.input_json.get("window_key") for row in rows} >= {
        "next_trading_day",
        "fifth_trading_day",
    }


async def test_backfill_worker_completes_once_and_preserves_progress(
    worker_engine: AsyncEngine,
) -> None:
    pending = await _pending_backfill(worker_engine)
    calls = 0

    async def executor(
        engine: AsyncEngine,
        settings: Settings,
        job: BackfillJob,
    ) -> dict[str, object]:
        nonlocal calls
        del engine, settings
        calls += 1
        assert job.status == "running"
        return {"status": "completed", "downloaded_records": 17}

    worker = BackfillWorker(worker_engine, _settings(), executor=executor)
    completed = await worker.run_once()
    repeated = await worker.run_once()
    assert completed is not None
    assert completed.id == pending.id
    assert completed.status == "completed"
    assert completed.progress == 1
    assert completed.downloaded_record_count == 17
    assert repeated is None
    assert calls == 1


async def test_sqlite_backfill_claim_is_atomic_across_concurrent_workers(
    worker_engine: AsyncEngine,
) -> None:
    pending = await _pending_backfill(worker_engine)
    claimed = await asyncio.gather(
        claim_next_backfill(worker_engine),
        claim_next_backfill(worker_engine),
    )
    claimed_ids = [item.id for item in claimed if item is not None]
    assert claimed_ids == [pending.id]


async def test_backfill_worker_rechecks_paid_gate_before_any_executor_call(
    worker_engine: AsyncEngine,
) -> None:
    pending = await _pending_backfill(worker_engine)
    called = False

    async def executor(
        engine: AsyncEngine,
        settings: Settings,
        job: BackfillJob,
    ) -> dict[str, object]:
        nonlocal called
        del engine, settings, job
        called = True
        return {"status": "completed"}

    worker = BackfillWorker(
        worker_engine,
        _settings(allow_paid_download=False),
        executor=executor,
    )
    failed = await worker.run_once()
    assert failed is not None
    assert failed.id == pending.id
    assert failed.status == "failed"
    assert "paid download is disabled" in (failed.error_message or "")
    assert failed.progress == 0
    assert called is False


async def test_backfill_provider_blockers_do_not_rollback_or_short_circuit_other_stages(
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = await _pending_backfill(worker_engine)
    await _observed_release(worker_engine, suffix="partial")
    calls: list[str] = []
    official_event_types: list[tuple[str, ...]] = []

    async def official(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        calls.append("official")
        event_types = kwargs.get("event_types")
        assert isinstance(event_types, tuple)
        official_event_types.append(event_types)
        return {
            "status": "partial",
            "results": {"bls_actuals": {"status": "completed", "records_written": 1}},
            "failures": {"fred": "ProviderError: FRED API key is not configured"},
        }

    async def consensus(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        calls.append("consensus")
        raise ProviderError(
            "trading_economics",
            ProviderErrorCode.ENTITLEMENT,
            "historical PIT entitlement is missing",
        )

    async def market(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        calls.append("market")
        raise ProviderError(
            "databento",
            ProviderErrorCode.NOT_CONFIGURED,
            "Databento API key is not configured",
        )

    monkeypatch.setattr("worldstate.application.backfill_worker.sync_official_data", official)
    monkeypatch.setattr(
        "worldstate.application.backfill_worker.snapshot_trading_economics_consensus",
        consensus,
    )
    monkeypatch.setattr(
        "worldstate.application.backfill_worker.sync_databento_release_market", market
    )

    worker = BackfillWorker(
        worker_engine,
        _settings(
            fred_api_key=None,
            trading_economics_api_key=None,
            trading_economics_pit_entitled=False,
            databento_api_key=None,
        ),
    )
    failed = await worker.run_once()
    assert failed is not None
    assert failed.id == pending.id
    assert failed.status == "failed"
    assert failed.progress == pytest.approx(0.99)
    assert calls == ["official", "consensus", "market"]
    assert failed.result_json["status"] == "failed_with_partial_results"
    assert official_event_types == [("US_CPI",)]
    assert failed.result_json["partial_results"]["official"]["status"] == "partial"
    provider_keys = {item["provider_key"] for item in failed.result_json["blockers"]}
    assert {"fred_alfred", "trading_economics", "databento"} <= provider_keys
    analysis = failed.result_json["partial_results"]["analysis"]
    assert analysis[0]["status"] == "skipped"
    assert "historical_initial_actual_unavailable" in analysis[0]["input_assessment"]["gaps"]


async def test_backfill_propagates_one_aggregate_budget_across_releases(
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _pending_backfill(worker_engine)
    await _observed_release(worker_engine, suffix="budget-a", day=13)
    await _observed_release(worker_engine, suffix="budget-b", day=20)
    remaining_budgets: list[Decimal] = []

    async def official(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "completed", "results": {}, "failures": {}}

    async def consensus(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "completed", "reconciled": 0}

    async def market(*args: object, **kwargs: object) -> dict[str, object]:
        del args
        budget = kwargs.get("budget_limit_usd")
        assert isinstance(budget, Decimal)
        remaining_budgets.append(budget)
        if len(remaining_budgets) == 1:
            return {
                "status": "completed",
                "records_written": 10,
                "estimated_cost_usd": "0.75",
            }
        raise ProviderError(
            "databento",
            ProviderErrorCode.BUDGET_EXCEEDED,
            "second release exceeds the remaining operation budget",
        )

    monkeypatch.setattr("worldstate.application.backfill_worker.sync_official_data", official)
    monkeypatch.setattr(
        "worldstate.application.backfill_worker.snapshot_trading_economics_consensus",
        consensus,
    )
    monkeypatch.setattr(
        "worldstate.application.backfill_worker.sync_databento_release_market",
        market,
    )

    failed = await BackfillWorker(worker_engine, _settings()).run_once()
    assert failed is not None
    assert failed.status == "failed"
    assert remaining_budgets == [Decimal("1"), Decimal("0.25")]


async def test_backfill_analyzes_and_replays_release_only_when_inputs_are_eligible(
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = await _pending_backfill(worker_engine)
    release = await _observed_release(
        worker_engine,
        suffix="ready",
        with_analysis_inputs=True,
    )
    analyzed: list[str] = []
    run_id = str(uuid.uuid4())

    async def official(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "completed", "results": {}, "failures": {}}

    async def consensus(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "completed", "reconciled": 0}

    async def market(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"status": "completed", "records_written": 0, "estimated_cost_usd": "0"}

    async def analyze(
        engine: AsyncEngine,
        release_id: str,
        *,
        idempotency_key: str | None = None,
        force: bool = False,
    ) -> str:
        del engine, idempotency_key, force
        analyzed.append(release_id)
        return run_id

    async def manifest(engine: AsyncEngine, value: str) -> dict[str, object]:
        del engine, value
        return {
            "input_snapshot_hash": "input-hash",
            "output_hash": "output-hash",
            "historical_sample_hash": "history-hash",
        }

    async def replay(engine: AsyncEngine, value: str) -> dict[str, object]:
        del engine, value
        return {"replayed": True, "checks": {"output_hash": True}}

    monkeypatch.setattr("worldstate.application.backfill_worker.sync_official_data", official)
    monkeypatch.setattr(
        "worldstate.application.backfill_worker.snapshot_trading_economics_consensus",
        consensus,
    )
    monkeypatch.setattr(
        "worldstate.application.backfill_worker.sync_databento_release_market", market
    )
    monkeypatch.setattr("worldstate.application.backfill_worker.analyze_release", analyze)
    monkeypatch.setattr("worldstate.application.backfill_worker.get_analysis_manifest", manifest)
    monkeypatch.setattr("worldstate.application.backfill_worker.replay_analysis_run", replay)

    worker = BackfillWorker(worker_engine, _settings())
    completed = await worker.run_once()
    assert completed is not None
    assert completed.id == pending.id
    assert completed.status == "completed"
    assert analyzed == [str(release.id)]
    analysis = completed.result_json["partial_results"]["analysis"]
    assert analysis == [
        {
            "status": "completed",
            "release_id": str(release.id),
            "analysis_run_id": run_id,
            "input_assessment": analysis[0]["input_assessment"],
            "replayed": True,
            "replay_checks": {"output_hash": True},
            "input_snapshot_hash": "input-hash",
            "output_hash": "output-hash",
            "historical_sample_hash": "history-hash",
        }
    ]


async def test_analysis_readiness_rejects_non_initial_historical_actual(
    worker_engine: AsyncEngine,
) -> None:
    release = await _observed_release(
        worker_engine,
        suffix="current-only",
        with_analysis_inputs=True,
        initial_actual=False,
    )
    readiness = await assess_release_analysis_inputs(worker_engine, release)
    assert readiness["ready"] is False
    gaps = readiness["gaps"]
    assert isinstance(gaps, list)
    assert "historical_initial_actual_unavailable" in gaps


async def test_terminal_backfill_can_retry_and_completed_scope_can_refresh(
    worker_engine: AsyncEngine,
) -> None:
    first = await _pending_backfill(worker_engine)
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, first.id)
        assert row is not None
        row.status = "failed"
        row.completed_at = T0
        row.error_message = "provider_not_configured"

    request = BackfillRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        event_types=("US_CPI",),
        instruments=("GC",),
        datasets=("ohlcv-1m",),
        data_mode="observed",
        expected_event_count=1,
    )
    estimate = await estimate_backfill(
        worker_engine,
        request,
        budget_limit_usd=Decimal("1"),
        paid_download_allowed=True,
        provider_estimated_cost_usd=Decimal("0.25"),
    )
    retry = await create_backfill_job(worker_engine, request, estimate, execute_requested=True)
    duplicate = await create_backfill_job(worker_engine, request, estimate, execute_requested=True)
    assert retry.id != first.id
    assert retry.status == "pending"
    assert retry.result_json["attempt_number"] == 2
    assert retry.result_json["prior_attempt_id"] == str(first.id)
    assert duplicate.id == retry.id

    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, retry.id)
        assert row is not None
        row.status = "completed"
        row.completed_at = T0
        row.progress = 1
    refresh = await create_backfill_job(worker_engine, request, estimate, execute_requested=True)
    assert refresh.id not in {first.id, retry.id}
    assert refresh.status == "pending"
    assert refresh.result_json["attempt_number"] == 3
    assert refresh.result_json["attempt_reason"] == "refresh"
    assert refresh.result_json["prior_attempt_id"] == str(retry.id)

    rejected_request = BackfillRequest(
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
        event_types=("US_CPI",),
        instruments=("GC",),
        datasets=("ohlcv-1m",),
        data_mode="observed",
        expected_event_count=1,
    )
    blocked_estimate = await estimate_backfill(
        worker_engine,
        rejected_request,
        budget_limit_usd=Decimal("1"),
        paid_download_allowed=False,
        provider_estimated_cost_usd=Decimal("0.25"),
    )
    rejected = await create_backfill_job(
        worker_engine,
        rejected_request,
        blocked_estimate,
        execute_requested=True,
    )
    assert rejected.status == "rejected"
    allowed_estimate = await estimate_backfill(
        worker_engine,
        rejected_request,
        budget_limit_usd=Decimal("1"),
        paid_download_allowed=True,
        provider_estimated_cost_usd=Decimal("0.25"),
    )
    unblocked = await create_backfill_job(
        worker_engine,
        rejected_request,
        allowed_estimate,
        execute_requested=True,
    )
    assert unblocked.id != rejected.id
    assert unblocked.status == "pending"
    assert unblocked.result_json["attempt_number"] == 2
    assert unblocked.result_json["prior_attempt_id"] == str(rejected.id)


async def test_backfill_restart_recovery_is_idempotent(worker_engine: AsyncEngine) -> None:
    pending = await _pending_backfill(worker_engine)
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, pending.id)
        assert row is not None
        row.status = "running"
        row.current_stage = "market_download"
        row.started_at = T0
        row.updated_at = T0
        row.progress = 0.6
    first = await recover_interrupted_backfills(worker_engine, now=T0 + timedelta(hours=1))
    second = await recover_interrupted_backfills(worker_engine, now=T0 + timedelta(hours=1))
    async with factory() as session:
        recovered = await session.get(BackfillJob, pending.id)
    assert first == 1
    assert second == 0
    assert recovered is not None
    assert recovered.status == "pending"
    assert recovered.progress == 0.6
    assert recovered.result_json["recovery_count"] == 1


async def test_backfill_restart_does_not_reclaim_active_lease(
    worker_engine: AsyncEngine,
) -> None:
    pending = await _pending_backfill(worker_engine)
    factory = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, pending.id)
        assert row is not None
        row.status = "running"
        row.current_stage = "market_download"
        row.started_at = T0
        row.updated_at = T0 + timedelta(minutes=59)

    recovered_count = await recover_interrupted_backfills(
        worker_engine,
        now=T0 + timedelta(hours=1),
    )
    async with factory() as session:
        active = await session.get(BackfillJob, pending.id)
    assert recovered_count == 0
    assert active is not None
    assert active.status == "running"


async def test_sync_failure_redacts_credentials_before_retry_persistence(
    worker_engine: AsyncEngine,
) -> None:
    job = await ensure_sync_job(
        worker_engine,
        job_key="redaction-job",
        operation="provider-sync",
        schedule_type="manual",
        schedule={},
        max_attempts=2,
    )
    run = await enqueue_sync_run(
        worker_engine,
        sync_job_id=job.id,
        scheduled_for=T0,
        input_data={},
    )
    await start_sync_run(worker_engine, run.id, now=T0)
    failed, retry = await fail_sync_run(
        worker_engine,
        run.id,
        error_type="ProviderError",
        error_message="headers={'Authorization': 'Bearer never-store-this'}",
        now=T0 + timedelta(minutes=1),
    )
    assert failed.error_message is not None
    assert "never-store-this" not in failed.error_message
    assert "[REDACTED]" in failed.error_message
    assert retry is not None


async def test_backfill_cancellation_wins_over_executor_completion(
    worker_engine: AsyncEngine,
) -> None:
    pending = await _pending_backfill(worker_engine)

    async def cancelling_executor(
        engine: AsyncEngine,
        settings: Settings,
        job: BackfillJob,
    ) -> dict[str, object]:
        del settings
        await cancel_backfill_job(engine, job.id, now=T0)
        return {"status": "completed", "downloaded_records": 99}

    worker = BackfillWorker(worker_engine, _settings(), executor=cancelling_executor)
    cancelled = await worker.run_once()
    assert cancelled is not None
    assert cancelled.id == pending.id
    assert cancelled.status == "cancelled"
    assert cancelled.downloaded_record_count == 0
    assert cancelled.progress == 0


async def test_background_start_is_non_blocking_and_stops_cleanly(
    worker_engine: AsyncEngine,
) -> None:
    async def sync_executor(
        engine: AsyncEngine,
        settings: Settings,
        run: SyncJobRun,
        job: SyncJob,
        *,
        now: datetime,
    ) -> dict[str, object]:
        del engine, settings, run, job, now
        return {"status": "completed"}

    async def backfill_executor(
        engine: AsyncEngine,
        settings: Settings,
        job: BackfillJob,
    ) -> dict[str, object]:
        del engine, settings, job
        return {"status": "completed"}

    scheduler = SchedulerRuntime(
        worker_engine,
        _settings(),
        poll_seconds=3600,
        executor=sync_executor,
    )
    worker = BackfillWorker(
        worker_engine,
        _settings(),
        poll_seconds=3600,
        executor=backfill_executor,
    )
    scheduler.start()
    worker.start()
    scheduler_started = scheduler.running
    worker_started = worker.running
    assert scheduler_started
    assert worker_started
    await scheduler.stop()
    await worker.stop()
    scheduler_stopped = scheduler.running
    worker_stopped = worker.running
    assert not scheduler_stopped
    assert not worker_stopped
