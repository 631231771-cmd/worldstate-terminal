"""Non-blocking local scheduler runtime for durable synchronization jobs."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import redact_sensitive_text
from worldstate.application.licensed_sync_service import (
    snapshot_trading_economics_consensus,
    sync_databento_release_market,
)
from worldstate.application.official_sync_service import (
    sync_bls_actuals,
    sync_bls_calendar,
    sync_fomc_materials,
    sync_official_data,
)
from worldstate.application.provider_runtime import persist_configured_provider_health
from worldstate.application.public_sync_service import sync_public_providers
from worldstate.application.reconciliation_service import reconcile_persisted_data
from worldstate.application.scheduler_service import (
    claim_next_run,
    enqueue_due_jobs,
    ensure_default_schedule,
    recover_scheduler,
    schedule_deferred_market_window,
    schedule_release_tasks,
)
from worldstate.application.sync_service import complete_sync_run, fail_sync_run
from worldstate.config import Settings
from worldstate.db.models import MacroRelease, SyncJob, SyncJobRun
from worldstate.market_core.sessions import resolve_instrument_close
from worldstate.provider_kit import ProviderError, ProviderErrorCode

logger = structlog.get_logger(__name__)

_LIVE_CAPTURE_GRACE = timedelta(minutes=15)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved.replace(tzinfo=UTC) if resolved.tzinfo is None else resolved.astimezone(UTC)


class SyncRunExecutor(Protocol):
    def __call__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        run: SyncJobRun,
        job: SyncJob,
        *,
        now: datetime,
    ) -> Awaitable[dict[str, object]]: ...


def _date_input(input_data: dict[str, Any], key: str, fallback: date) -> date:
    value = input_data.get(key)
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return fallback
    return fallback


async def _release_for_run(engine: AsyncEngine, run: SyncJobRun) -> MacroRelease:
    raw_id = run.input_json.get("macro_release_id")
    if not isinstance(raw_id, str):
        raise ValueError("release-relative run omitted macro_release_id")
    try:
        release_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise ValueError("release-relative run has an invalid macro_release_id") from exc
    factory = _factory(engine)
    async with factory() as session:
        release = await session.get(MacroRelease, release_id)
    if release is None:
        raise LookupError("macro release for scheduled run was not found")
    return release


def _result_counts(result: object) -> tuple[int, int]:
    """Extract conservative read/write totals from nested service results."""

    if not isinstance(result, dict):
        return 0, 0
    read = int(result.get("records_read", 0) or 0)
    written = int(result.get("records_written", 0) or 0)
    nested = result.get("results")
    if isinstance(nested, dict):
        for item in nested.values():
            child_read, child_written = _result_counts(item)
            read += child_read
            written += child_written
    return read, written


_EXPECTED_PROVIDER_BLOCKS = {
    ProviderErrorCode.NOT_CONFIGURED.value,
    ProviderErrorCode.ENTITLEMENT.value,
    ProviderErrorCode.PAID_DOWNLOAD_DISABLED.value,
    ProviderErrorCode.BUDGET_EXCEEDED.value,
    ProviderErrorCode.COST_ESTIMATE_UNAVAILABLE.value,
}


def _require_complete(result: dict[str, object], operation: str) -> None:
    status = str(result.get("status", "completed"))
    if status not in {
        "completed",
        "ok",
        "success",
        "partial",
        "blocked",
        "skipped",
        "not_configured",
        "not_entitled",
        "paid_download_disabled",
    }:
        failures = result.get("failures")
        raise RuntimeError(f"{operation} finished as {status}: {failures or 'incomplete'}")


async def execute_scheduled_operation(
    engine: AsyncEngine,
    settings: Settings,
    run: SyncJobRun,
    job: SyncJob,
    *,
    now: datetime,
) -> dict[str, object]:
    """Dispatch one durable run to the existing official/licensed services."""

    today = _utc(now).date()
    operation = job.operation
    if operation == "record_provider_health":
        result = await persist_configured_provider_health(
            engine,
            settings,
            checked_at=_utc(now),
        )
        _require_complete(result, operation)
        return result
    if operation == "sync_official":
        default_start = max(settings.data_start_date, today - timedelta(days=400))
        result = await sync_official_data(
            engine,
            settings,
            start_date=_date_input(run.input_json, "start_date", default_start),
            end_date=_date_input(run.input_json, "end_date", today),
        )
        _require_complete(result, operation)
        return result
    if operation == "sync_public_macro":
        default_start = max(settings.data_start_date, today - timedelta(days=400))
        providers = tuple(
            str(item)
            for item in run.input_json.get(
                "providers", job.schedule_json.get("providers", ["ecb", "boe", "boj", "china"])
            )
        )
        result = await sync_public_providers(
            engine,
            settings,
            start_date=_date_input(run.input_json, "start_date", default_start),
            end_date=_date_input(run.input_json, "end_date", today),
            providers=providers,
        )
        _require_complete(result, operation)
        return result
    if operation == "sync_calendar":
        start = _date_input(run.input_json, "start_date", today)
        end = _date_input(run.input_json, "end_date", today + timedelta(days=370))
        bls = await sync_bls_calendar(engine, settings, start_date=start, end_date=end)
        fomc = await sync_fomc_materials(engine, settings, start_date=start, end_date=end)
        _require_complete(bls, "sync_bls_calendar")
        _require_complete(fomc, "sync_fomc_materials")
        return {"status": "completed", "results": {"bls": bls, "fomc": fomc}}
    if operation == "snapshot_consensus":
        release = await _release_for_run(engine, run)
        release_at = _utc(release.scheduled_at)
        scheduled_for = _utc(run.scheduled_for)
        offset_minutes = int(run.input_json.get("offset_minutes", 0) or 0)
        # On-time T-24h/T-1h/T-5m and T+5m jobs are genuine current captures.
        # A missed pre-release job cannot use a post-T0 response, and any job
        # outside the declared grace window is an explicit historical replay.
        missed_pre_release = offset_minutes < 0 and _utc(now) >= release_at
        delayed_replay = _utc(now) > scheduled_for + _LIVE_CAPTURE_GRACE
        pit_at = scheduled_for if missed_pre_release or delayed_replay else None
        result = await snapshot_trading_economics_consensus(
            engine,
            settings,
            start_date=release_at.date(),
            end_date=release_at.date(),
            pit_at=pit_at,
        )
        _require_complete(result, operation)
        return {
            **result,
            "snapshot_mode": "historical_pit_replay" if pit_at else "current_capture",
            "scheduled_for": scheduled_for.isoformat(),
            "pit_at": pit_at.isoformat() if pit_at else None,
        }
    if operation == "refresh_official_release":
        release = await _release_for_run(engine, run)
        if release.release_type in {"US_CPI", "US_NFP"}:
            try:
                period = date.fromisoformat(f"{release.period_label}-01")
            except ValueError:
                period = _utc(release.scheduled_at).date().replace(day=1)
            result = await sync_bls_actuals(
                engine,
                settings,
                start_date=period,
                end_date=period,
            )
        elif release.release_type == "FOMC":
            meeting_date = _utc(release.scheduled_at).date()
            result = await sync_fomc_materials(
                engine,
                settings,
                start_date=meeting_date,
                end_date=meeting_date,
            )
        else:
            raise ValueError(f"unsupported release refresh type: {release.release_type}")
        _require_complete(result, operation)
        return result
    if operation == "sync_event_market":
        release = await _release_for_run(engine, run)
        raw_roots = run.input_json.get("roots")
        roots = (
            tuple(str(item) for item in raw_roots)
            if isinstance(raw_roots, list)
            else ("GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX")
        )
        result = await sync_databento_release_market(
            engine,
            settings,
            release_id=release.id,
            roots=roots,
            include_daily=run.input_json.get("window_key")
            in {"next_trading_day", "fifth_trading_day"},
        )
        _require_complete(result, operation)
        return result
    if operation == "reconcile_data":
        result = await reconcile_persisted_data(engine)
        _require_complete(result, operation)
        return result
    raise ValueError(f"unsupported scheduled operation: {operation}")


async def enqueue_release_relative_jobs(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    lookback_days: int = 2,
    lookahead_days: int = 45,
) -> int:
    """Discover scheduled releases; durable run idempotency prevents duplicates."""

    timestamp = _utc(now)
    lower = timestamp - timedelta(days=lookback_days)
    upper = timestamp + timedelta(days=lookahead_days)
    factory = _factory(engine)
    async with factory() as session:
        releases = (
            await session.scalars(
                select(MacroRelease).where(
                    MacroRelease.data_mode == "observed",
                    MacroRelease.release_type.in_(("US_CPI", "US_NFP", "FOMC")),
                    MacroRelease.status != "invalidated",
                    MacroRelease.scheduled_at >= lower,
                    MacroRelease.scheduled_at <= upper,
                )
            )
        ).all()
    count = 0
    instrument_keys = (
        "gold_gc",
        "silver_si",
        "wti_cl",
        "sp500_es",
        "nasdaq_nq",
        "ust2y_zt",
        "ust10y_zn",
        "dollar_dxy",
        "vix",
    )
    for release in releases:
        count += len(
            await schedule_release_tasks(
                engine,
                macro_release_id=release.id,
                release_at=_utc(release.scheduled_at),
            )
        )
        for window_key, trading_days_after in (
            ("next_trading_day", 1),
            ("fifth_trading_day", 5),
        ):
            # Run after the latest declared close across the fixed v0.5 asset
            # set. The market service still records each instrument's own
            # calendar/UTC-day limitations in its manifest.
            scheduled_for = max(
                resolve_instrument_close(
                    _utc(release.scheduled_at),
                    instrument_key,
                    trading_days_after=trading_days_after,
                )
                for instrument_key in instrument_keys
            )
            await schedule_deferred_market_window(
                engine,
                macro_release_id=release.id,
                window_key=window_key,
                scheduled_for=scheduled_for,
            )
            count += 1
    return count


async def run_scheduler_cycle(
    engine: AsyncEngine,
    settings: Settings,
    *,
    now: datetime | None = None,
    executor: SyncRunExecutor = execute_scheduled_operation,
    max_runs: int = 4,
    catch_up_missed: bool = False,
) -> dict[str, int]:
    """Enqueue and execute a bounded amount of work without blocking startup."""

    timestamp = _utc(now)
    await ensure_default_schedule(
        engine,
        now=timestamp,
        catch_up_missed=catch_up_missed,
    )
    recovered = await recover_scheduler(engine, now=timestamp)
    due = await enqueue_due_jobs(engine, now=timestamp)
    relative_count = await enqueue_release_relative_jobs(engine, now=timestamp)
    completed = failed = blocked = 0
    for _ in range(max_runs):
        run = await claim_next_run(engine, now=timestamp)
        if run is None:
            break
        factory = _factory(engine)
        async with factory() as session:
            job = await session.get(SyncJob, run.sync_job_id)
        if job is None:
            await fail_sync_run(
                engine,
                run.id,
                error_type="MissingSyncJob",
                error_message="scheduled definition was removed",
                now=timestamp,
            )
            failed += 1
            continue
        try:
            result = await asyncio.wait_for(
                executor(engine, settings, run, job, now=timestamp),
                timeout=job.timeout_seconds,
            )
            read, written = _result_counts(result)
            provider_run_id: uuid.UUID | None = None
            source_artifact_id: uuid.UUID | None = None
            for field_name, target in (
                ("provider_run_id", "provider"),
                ("source_artifact_id", "artifact"),
            ):
                raw_identifier = result.get(field_name)
                if not isinstance(raw_identifier, str):
                    continue
                try:
                    identifier = uuid.UUID(raw_identifier)
                except ValueError:
                    continue
                if target == "provider":
                    provider_run_id = identifier
                else:
                    source_artifact_id = identifier
            await complete_sync_run(
                engine,
                run.id,
                records_read=read,
                records_written=written,
                output_data=result,
                provider_run_id=provider_run_id,
                source_artifact_id=source_artifact_id,
                now=_utc(),
            )
            completed += 1
            if str(result.get("status")) in {
                "blocked",
                "not_configured",
                "not_entitled",
                "paid_download_disabled",
                "skipped",
            }:
                blocked += 1
        except asyncio.CancelledError:
            # Leave the run in running state; restart recovery will create an
            # idempotent retry instead of pretending the interrupted call ended.
            raise
        except ProviderError as exc:
            if exc.error_code.value in _EXPECTED_PROVIDER_BLOCKS:
                blocked_result = {
                    "status": "blocked",
                    "operation": job.operation,
                    "provider_status": exc.error_code.value,
                    "message": redact_sensitive_text(str(exc))[:500],
                }
                await complete_sync_run(
                    engine,
                    run.id,
                    records_read=0,
                    records_written=0,
                    output_data=blocked_result,
                    now=_utc(),
                )
                completed += 1
                blocked += 1
                continue
            await fail_sync_run(
                engine,
                run.id,
                error_type=type(exc).__name__,
                error_message=redact_sensitive_text(exc)[:2000],
                now=_utc(),
            )
            failed += 1
        except Exception as exc:
            await fail_sync_run(
                engine,
                run.id,
                error_type=type(exc).__name__,
                error_message=redact_sensitive_text(exc)[:2000],
                now=_utc(),
            )
            failed += 1
    return {
        "recovered": len(recovered),
        "daily_enqueued": len(due),
        "release_runs_seen": relative_count,
        "completed": completed,
        "blocked": blocked,
        "failed": failed,
    }


class SchedulerRuntime:
    """Own one local scheduler task and stop it cleanly with the FastAPI app."""

    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        *,
        poll_seconds: float = 5,
        executor: SyncRunExecutor = execute_scheduled_operation,
        max_runs_per_cycle: int = 4,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.poll_seconds = poll_seconds
        self.executor = executor
        self.max_runs_per_cycle = max_runs_per_cycle
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Schedule background initialization and return immediately."""

        if self.running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="worldstate-data-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        try:
            await recover_scheduler(self.engine)
            first_cycle = True
            while not self._stopping.is_set():
                try:
                    await run_scheduler_cycle(
                        self.engine,
                        self.settings,
                        executor=self.executor,
                        max_runs=self.max_runs_per_cycle,
                        catch_up_missed=first_cycle,
                    )
                    first_cycle = False
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Scheduler failures are visible in durable runs/logs but may
                    # never prevent the desktop API from starting.
                    await logger.awarning(
                        "scheduler_cycle_failed",
                        error_type=type(exc).__name__,
                        error_message=redact_sensitive_text(exc)[:500],
                    )
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_seconds)
        finally:
            self._stopping.set()


__all__ = [
    "SchedulerRuntime",
    "SyncRunExecutor",
    "enqueue_release_relative_jobs",
    "execute_scheduled_operation",
    "run_scheduler_cycle",
]
