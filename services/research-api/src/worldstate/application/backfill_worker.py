"""Recoverable background worker for bounded v0.5 data backfills."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Mapping
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol, cast

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.analysis_orchestrator import (
    analyze_release,
    select_analysis_inputs,
)
from worldstate.application.analysis_persistence import (
    get_analysis_manifest,
    replay_analysis_run,
)
from worldstate.application.backfill_service import update_backfill_progress
from worldstate.application.data_foundation_service import redact_sensitive_text
from worldstate.application.licensed_sync_service import (
    snapshot_trading_economics_consensus,
    sync_databento_release_market,
)
from worldstate.application.official_sync_service import sync_official_data
from worldstate.config import Settings
from worldstate.db.models import (
    BackfillJob,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    ReleaseStage,
)
from worldstate.provider_kit import ProviderError, ProviderErrorCode

logger = structlog.get_logger(__name__)

_QUALIFIED_CONSENSUS_GRADES = ("A", "B", "C")
_NON_RETRYABLE_PROVIDER_CODES = frozenset(
    {
        ProviderErrorCode.NOT_CONFIGURED,
        ProviderErrorCode.AUTHENTICATION,
        ProviderErrorCode.ENTITLEMENT,
        ProviderErrorCode.QUOTA_EXHAUSTED,
        ProviderErrorCode.PAID_DOWNLOAD_DISABLED,
        ProviderErrorCode.BUDGET_EXCEEDED,
        ProviderErrorCode.COST_ESTIMATE_UNAVAILABLE,
    }
)
_OFFICIAL_PROVIDER_KEYS = {
    "bls_calendar": "bls",
    "bls_actuals": "bls",
    "fomc": "federal_reserve",
    "fred": "fred_alfred",
}


class PartialBackfillError(RuntimeError):
    """A bounded run retained useful work but did not satisfy the full request."""


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved.replace(tzinfo=UTC) if resolved.tzinfo is None else resolved.astimezone(UTC)


def _int_value(value: object) -> int:
    if isinstance(value, int | float | Decimal | str):
        try:
            return int(value)
        except (ValueError, ArithmeticError):
            return 0
    return 0


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _provider_blocker(
    *,
    stage: str,
    error: Exception,
    provider_key: str | None = None,
    release_id: uuid.UUID | None = None,
) -> dict[str, object]:
    if isinstance(error, ProviderError):
        provider = error.provider_key
        code = error.error_code.value
        retryable = error.retryable
        details = cast(dict[str, object], _json_safe(error.details))
    else:
        provider = provider_key or "worldstate"
        code = "backfill_stage_failed"
        retryable = False
        details = {}
    return {
        "stage": stage,
        "provider_key": provider,
        "code": code,
        "message": str(error)[:1800],
        "retryable": retryable,
        "release_id": str(release_id) if release_id else None,
        "details": details,
    }


def _is_persistent_provider_blocker(error: Exception) -> bool:
    return isinstance(error, ProviderError) and error.error_code in _NON_RETRYABLE_PROVIDER_CODES


class BackfillExecutor(Protocol):
    def __call__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        job: BackfillJob,
    ) -> Awaitable[dict[str, object]]: ...


async def recover_interrupted_backfills(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 900,
) -> int:
    """Return only stale interrupted jobs to pending.

    A second desktop/backend process must not reclaim an actively progressing
    paid backfill merely because it starts while the first process is alive.
    ``updated_at`` acts as the durable lease heartbeat because every progress
    checkpoint updates the row.
    """

    factory = _factory(engine)
    timestamp = _utc(now)
    cutoff = timestamp - timedelta(seconds=stale_after_seconds)
    recovered = 0
    async with factory() as session, session.begin():
        rows = (
            await session.scalars(select(BackfillJob).where(BackfillJob.status == "running"))
        ).all()
        for row in rows:
            last_seen = row.updated_at or row.started_at
            if last_seen is not None and _utc(last_seen) > cutoff:
                continue
            if not row.execution_allowed:
                row.status = "failed"
                row.completed_at = timestamp
                row.error_message = "restart recovery rejected a job without execution approval"
                continue
            recovery_count = int(row.result_json.get("recovery_count", 0) or 0) + 1
            row.status = "pending"
            row.current_stage = "restart_recovery"
            row.started_at = None
            row.error_message = None
            row.result_json = {**row.result_json, "recovery_count": recovery_count}
            recovered += 1
    return recovered


async def claim_next_backfill(engine: AsyncEngine) -> BackfillJob | None:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        timestamp = _utc()
        if session.bind is not None and session.bind.dialect.name == "sqlite":
            candidate_id = (
                select(BackfillJob.id)
                .where(BackfillJob.status == "pending")
                .order_by(BackfillJob.requested_at, BackfillJob.id)
                .limit(1)
                .scalar_subquery()
            )
            row = await session.scalar(
                update(BackfillJob)
                .where(
                    BackfillJob.id == candidate_id,
                    BackfillJob.status == "pending",
                )
                .values(
                    status="running",
                    started_at=timestamp,
                    current_stage="preflight",
                    error_message=None,
                )
                .returning(BackfillJob)
            )
        else:
            row = await session.scalar(
                select(BackfillJob)
                .where(BackfillJob.status == "pending")
                .order_by(BackfillJob.requested_at, BackfillJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        if row is None:
            return None
        if not row.execution_allowed:
            row.status = "failed"
            row.completed_at = _utc()
            row.error_message = "backfill execution approval is absent"
            return None
        row.status = "running"
        row.started_at = row.started_at or timestamp
        row.current_stage = "preflight"
        row.error_message = None
        await session.flush()
        return row


async def _current_job(engine: AsyncEngine, job_id: uuid.UUID) -> BackfillJob:
    factory = _factory(engine)
    async with factory() as session:
        row = await session.get(BackfillJob, job_id)
    if row is None:
        raise LookupError("backfill job not found")
    return row


async def _cancelled(engine: AsyncEngine, job_id: uuid.UUID) -> bool:
    return (await _current_job(engine, job_id)).status == "cancelled"


async def fail_backfill_job(
    engine: AsyncEngine,
    job_id: uuid.UUID,
    error: Exception,
    *,
    now: datetime | None = None,
) -> BackfillJob:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, job_id)
        if row is None:
            raise LookupError("backfill job not found")
        if row.status == "cancelled":
            return row
        if row.status == "completed":
            return row
        row.status = "failed"
        row.completed_at = _utc(now)
        row.current_stage = "failed"
        safe_message = redact_sensitive_text(error)[:1800]
        row.error_message = f"{type(error).__name__}: {safe_message}"
        row.result_json = {
            **row.result_json,
            "failure": {
                "error_type": type(error).__name__,
                "message": safe_message,
            },
        }
        await session.flush()
        return row


def _preflight(job: BackfillJob, settings: Settings) -> None:
    if job.data_mode == "fixture":
        return
    if job.data_mode != "observed":
        raise ValueError(f"unsupported backfill data mode: {job.data_mode}")
    if job.provider_key != "databento":
        raise ValueError(f"unsupported observed backfill provider: {job.provider_key}")
    if not job.execution_allowed or not job.paid_download_allowed:
        raise PermissionError("backfill did not pass the persisted API cost gate")
    if not settings.allow_paid_download:
        raise ProviderError(
            "databento",
            ProviderErrorCode.PAID_DOWNLOAD_DISABLED,
            "Databento paid download is disabled at worker execution time",
        )
    if job.estimated_cost_usd > settings.databento_max_estimated_cost_usd:
        raise ProviderError(
            "databento",
            ProviderErrorCode.BUDGET_EXCEEDED,
            "Backfill estimate exceeds the current Databento budget",
            details={
                "estimated_cost_usd": str(job.estimated_cost_usd),
                "current_budget_usd": str(settings.databento_max_estimated_cost_usd),
            },
        )


def _require_complete(result: dict[str, object], stage: str) -> None:
    status = str(result.get("status", "completed"))
    if status not in {"completed", "ok", "success"}:
        raise RuntimeError(f"backfill {stage} stage finished as {status}: {result.get('failures')}")


async def _job_releases(engine: AsyncEngine, job: BackfillJob) -> list[MacroRelease]:
    factory = _factory(engine)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(MacroRelease)
                .where(
                    MacroRelease.data_mode == job.data_mode,
                    MacroRelease.release_type.in_(tuple(job.event_types_json)),
                    MacroRelease.status != "invalidated",
                )
                .order_by(MacroRelease.scheduled_at)
            )
        ).all()
    return [
        row
        for row in rows
        if job.start_date <= _utc(row.scheduled_at).date() <= job.end_date
    ]


async def assess_release_analysis_inputs(
    engine: AsyncEngine,
    release: MacroRelease,
) -> dict[str, object]:
    """Decide whether an observed release has evidence sufficient for analysis.

    Consensus must have been captured before T0 and use a declared usable quality
    grade.  A manifest alone is insufficient: at least one matching minute bar
    must still exist so an orphaned manifest cannot trigger a misleading run.
    """

    cutoff = _utc(release.released_at or release.scheduled_at)
    factory = _factory(engine)
    async with factory() as session:
        selected_values, selected_consensus, _artifacts = await select_analysis_inputs(
            session, release
        )
        actual_indicator_ids = {
            indicator_id
            for (indicator_id, value_kind), row in selected_values.items()
            if value_kind == "actual" and row.value is not None
        }
        consensus_indicator_ids = set(selected_consensus)
        stages = (
            await session.scalars(
                select(ReleaseStage.id).where(ReleaseStage.macro_release_id == release.id)
            )
        ).all()
        manifests = (
            await session.scalars(
                select(MarketDataManifest).where(
                    MarketDataManifest.macro_release_id == release.id,
                    MarketDataManifest.data_mode == "observed",
                    MarketDataManifest.interval_seconds == 60,
                    MarketDataManifest.row_count > 0,
                )
            )
        ).all()
        market_bar_count = 0
        if manifests:
            lower = min(_utc(row.start_at) for row in manifests)
            upper = max(_utc(row.end_at) for row in manifests)
            instrument_ids = {row.instrument_id for row in manifests}
            candidate_bars = (
                await session.scalars(
                    select(MarketBar).where(
                        MarketBar.instrument_id.in_(instrument_ids),
                        MarketBar.data_mode == "observed",
                        MarketBar.interval_seconds == 60,
                        MarketBar.timestamp >= lower,
                        MarketBar.timestamp <= upper,
                    )
                )
            ).all()
            market_bar_count = sum(
                any(
                    bar.instrument_id == manifest.instrument_id
                    and bar.provider_key == manifest.provider_key
                    and _utc(manifest.start_at)
                    <= _utc(bar.timestamp)
                    <= _utc(manifest.end_at)
                    for manifest in manifests
                )
                for bar in candidate_bars
            )

    matched_indicator_ids = actual_indicator_ids & consensus_indicator_ids
    gaps: list[str] = []
    if release.data_mode != "observed":
        gaps.append("release_is_not_observed")
    if not actual_indicator_ids:
        gaps.append("historical_initial_actual_unavailable")
    if not consensus_indicator_ids:
        gaps.append("qualified_pre_release_consensus_missing")
    elif not matched_indicator_ids:
        gaps.append("actual_consensus_indicator_overlap_missing")
    if not manifests:
        gaps.append("minute_market_manifest_missing")
    elif market_bar_count == 0:
        gaps.append("minute_market_bars_missing_or_orphaned_manifest")
    if not stages:
        gaps.append("release_stage_missing")
    return {
        "ready": not gaps,
        "gaps": gaps,
        "actual_indicator_count": len(actual_indicator_ids),
        "qualified_consensus_count": len(selected_consensus),
        "matched_indicator_count": len(matched_indicator_ids),
        "qualified_consensus_grades": list(_QUALIFIED_CONSENSUS_GRADES),
        "consensus_cutoff": cutoff.isoformat(),
        "market_manifest_count": len(manifests),
        "market_bar_count": market_bar_count,
        "release_stage_count": len(stages),
    }


async def execute_backfill_job(
    engine: AsyncEngine,
    settings: Settings,
    job: BackfillJob,
) -> dict[str, object]:
    """Execute independent stages, retaining partial work before an honest failure."""

    if job.data_mode == "fixture":
        result: dict[str, object] = {
            "status": "completed",
            "data_mode": "fixture",
            "attempt": {
                "scope_idempotency_key": job.result_json.get(
                    "scope_idempotency_key", job.idempotency_key
                ),
                "attempt_number": job.result_json.get("attempt_number", 1),
                "prior_attempt_id": job.result_json.get("prior_attempt_id"),
                "attempt_reason": job.result_json.get("attempt_reason", "initial"),
            },
            "external_calls": 0,
            "downloaded_records": 0,
            "note": "Fixture mode remains isolated and performs no paid provider download.",
        }
        await update_backfill_progress(
            engine,
            job.id,
            progress=1,
            current_stage="completed_fixture",
            downloaded_record_count=0,
            result=result,
            completed=True,
        )
        return result

    partial_results: dict[str, object] = {}
    blockers: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    downloaded = 0
    estimated_cost = Decimal("0")

    def result_snapshot(status: str = "running") -> dict[str, object]:
        return cast(
            dict[str, object],
            _json_safe(
                {
                    "status": status,
                    "data_mode": job.data_mode,
                    "attempt": {
                        "scope_idempotency_key": job.result_json.get(
                            "scope_idempotency_key", job.idempotency_key
                        ),
                        "attempt_number": job.result_json.get("attempt_number", 1),
                        "prior_attempt_id": job.result_json.get("prior_attempt_id"),
                        "attempt_reason": job.result_json.get("attempt_reason", "initial"),
                    },
                    "partial_results": partial_results,
                    "blockers": blockers,
                    "gaps": gaps,
                    "downloaded_records": downloaded,
                    "estimated_cost_usd": str(estimated_cost),
                }
            ),
        )

    try:
        official = await sync_official_data(
            engine,
            settings,
            start_date=job.start_date,
            end_date=job.end_date,
            event_types=tuple(job.event_types_json),
        )
    except Exception as exc:
        official = {
            "status": "failed",
            "results": {},
            "failures": {"official": f"{type(exc).__name__}: {exc}"},
        }
        blockers.append(
            _provider_blocker(stage="official", error=exc, provider_key="official")
        )
    else:
        failures = official.get("failures")
        if isinstance(failures, Mapping):
            for operation, message in failures.items():
                blockers.append(
                    _provider_blocker(
                        stage=f"official.{operation}",
                        error=RuntimeError(str(message)),
                        provider_key=_OFFICIAL_PROVIDER_KEYS.get(
                            str(operation), "official"
                        ),
                    )
                )
    partial_results["official"] = official
    await update_backfill_progress(
        engine,
        job.id,
        progress=0.15,
        current_stage=(
            "official_completed"
            if str(official.get("status")) == "completed"
            else "official_partial"
        ),
        downloaded_record_count=downloaded,
        result=result_snapshot(),
    )
    if await _cancelled(engine, job.id):
        return result_snapshot("cancelled")

    releases = await _job_releases(engine, job)
    if not releases and job.estimated_event_count:
        gaps.append(
            {
                "stage": "release_discovery",
                "code": "eligible_release_missing",
                "message": "official synchronization produced no eligible observed releases",
            }
        )
    consensus_results: list[dict[str, object]] = []
    reconciled = 0
    consensus_unavailable: dict[str, object] | None = None
    for index, release in enumerate(releases, start=1):
        if await _cancelled(engine, job.id):
            return result_snapshot("cancelled")
        if consensus_unavailable is not None:
            consensus_results.append(
                {
                    "status": "skipped",
                    "release_id": str(release.id),
                    "reason": "persistent provider blocker",
                    "blocker_code": consensus_unavailable["code"],
                }
            )
            continue
        release_at = _utc(release.scheduled_at)
        pit_at = release_at - timedelta(minutes=5) if release_at <= _utc() else None
        try:
            item = await snapshot_trading_economics_consensus(
                engine,
                settings,
                start_date=release_at.date(),
                end_date=release_at.date(),
                pit_at=pit_at,
            )
            _require_complete(item, "consensus")
        except Exception as exc:
            blocker = _provider_blocker(
                stage="consensus",
                error=exc,
                provider_key="trading_economics",
                release_id=release.id,
            )
            blockers.append(blocker)
            consensus_results.append(
                {
                    "status": "failed",
                    "release_id": str(release.id),
                    "blocker_code": blocker["code"],
                }
            )
            if _is_persistent_provider_blocker(exc):
                consensus_unavailable = blocker
        else:
            consensus_results.append({"release_id": str(release.id), **item})
            reconciled += _int_value(item.get("reconciled", 0))
        partial_results["consensus"] = consensus_results
        progress = 0.15 + 0.25 * index / max(1, len(releases))
        await update_backfill_progress(
            engine,
            job.id,
            progress=progress,
            current_stage="consensus_snapshot",
            downloaded_record_count=downloaded,
            result=result_snapshot(),
        )
    partial_results["consensus"] = consensus_results

    roots = tuple(str(item) for item in job.instruments_json)
    include_daily = any("1d" in item for item in job.datasets_json)
    market_results: list[dict[str, object]] = []
    market_unavailable: dict[str, object] | None = None
    for index, release in enumerate(releases, start=1):
        if await _cancelled(engine, job.id):
            return result_snapshot("cancelled")
        if market_unavailable is not None:
            market_results.append(
                {
                    "status": "skipped",
                    "release_id": str(release.id),
                    "reason": "persistent provider blocker",
                    "blocker_code": market_unavailable["code"],
                }
            )
            continue
        try:
            item = await sync_databento_release_market(
                engine,
                settings,
                release_id=release.id,
                roots=roots,
                include_daily=include_daily,
                budget_limit_usd=max(Decimal("0"), job.budget_limit_usd - estimated_cost),
            )
            _require_complete(item, "market")
        except Exception as exc:
            blocker = _provider_blocker(
                stage="market",
                error=exc,
                provider_key="databento",
                release_id=release.id,
            )
            blockers.append(blocker)
            market_results.append(
                {
                    "status": "failed",
                    "release_id": str(release.id),
                    "blocker_code": blocker["code"],
                }
            )
            # Once a paid request fails, WorldState cannot prove whether the
            # provider already incurred billable usage. Stop this job's later
            # market slices instead of risking an aggregate budget overrun.
            market_unavailable = blocker
        else:
            market_results.append({"release_id": str(release.id), **item})
            downloaded += _int_value(item.get("records_written", 0))
            with suppress(ArithmeticError):
                estimated_cost += Decimal(str(item.get("estimated_cost_usd", "0")))
        partial_results["market"] = market_results
        progress = 0.4 + 0.35 * index / max(1, len(releases))
        await update_backfill_progress(
            engine,
            job.id,
            progress=progress,
            current_stage="market_download",
            downloaded_record_count=downloaded,
            result=result_snapshot(),
        )
    partial_results["market"] = market_results
    partial_results["reconciliation"] = {
        "status": "completed",
        "records": reconciled,
        "method": "existing licensed ingestion reconciliation services",
    }

    analysis_results: list[dict[str, object]] = []
    for index, release in enumerate(releases, start=1):
        if await _cancelled(engine, job.id):
            return result_snapshot("cancelled")
        readiness = await assess_release_analysis_inputs(engine, release)
        if not bool(readiness["ready"]):
            gap = {
                "stage": "analysis",
                "code": "analysis_inputs_missing",
                "release_id": str(release.id),
                "missing": readiness["gaps"],
            }
            gaps.append(gap)
            analysis_results.append(
                {
                    "status": "skipped",
                    "release_id": str(release.id),
                    "reason": "required analysis inputs are incomplete",
                    "input_assessment": readiness,
                }
            )
        else:
            try:
                run_id = await analyze_release(
                    engine,
                    str(release.id),
                    idempotency_key=f"backfill:{job.id}:{release.id}:analysis-v0.5",
                )
                manifest = await get_analysis_manifest(engine, run_id)
                replay = await replay_analysis_run(engine, run_id)
                replayed = bool(replay and replay.get("replayed"))
                analysis_results.append(
                    {
                        "status": "completed" if replayed else "replay_failed",
                        "release_id": str(release.id),
                        "analysis_run_id": run_id,
                        "input_assessment": readiness,
                        "replayed": replayed,
                        "replay_checks": replay.get("checks", {}) if replay else {},
                        "input_snapshot_hash": (
                            manifest.get("input_snapshot_hash") if manifest else None
                        ),
                        "output_hash": manifest.get("output_hash") if manifest else None,
                        "historical_sample_hash": (
                            manifest.get("historical_sample_hash") if manifest else None
                        ),
                    }
                )
                if not replayed:
                    blockers.append(
                        {
                            "stage": "analysis_replay",
                            "provider_key": "worldstate",
                            "code": "analysis_replay_failed",
                            "message": "saved AnalysisRun did not replay to the same core result",
                            "retryable": False,
                            "release_id": str(release.id),
                            "details": replay or {},
                        }
                    )
            except Exception as exc:
                blocker = _provider_blocker(
                    stage="analysis",
                    error=exc,
                    provider_key="worldstate",
                    release_id=release.id,
                )
                blockers.append(blocker)
                analysis_results.append(
                    {
                        "status": "failed",
                        "release_id": str(release.id),
                        "input_assessment": readiness,
                        "blocker_code": blocker["code"],
                    }
                )
        partial_results["analysis"] = analysis_results
        await update_backfill_progress(
            engine,
            job.id,
            progress=0.75 + 0.24 * index / max(1, len(releases)),
            current_stage="release_analysis",
            downloaded_record_count=downloaded,
            result=result_snapshot(),
        )
    partial_results["analysis"] = analysis_results

    if blockers or gaps:
        result = result_snapshot("failed_with_partial_results")
        await update_backfill_progress(
            engine,
            job.id,
            progress=0.99,
            current_stage="partial_results_retained",
            downloaded_record_count=downloaded,
            result=result,
        )
        raise PartialBackfillError(
            "backfill retained available data but did not satisfy the full request "
            f"({len(blockers)} provider/stage blocker(s), {len(gaps)} input gap(s))"
        )

    result = result_snapshot("completed")
    await update_backfill_progress(
        engine,
        job.id,
        progress=1,
        current_stage="completed",
        downloaded_record_count=downloaded,
        result=result,
        completed=True,
    )
    return result


class BackfillWorker:
    """Poll pending BackfillJob rows without blocking API startup."""

    def __init__(
        self,
        engine: AsyncEngine,
        settings: Settings,
        *,
        poll_seconds: float = 5,
        executor: BackfillExecutor = execute_backfill_job,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.poll_seconds = poll_seconds
        self.executor = executor
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="worldstate-backfill-worker")

    async def stop(self) -> None:
        self._stopping.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def run_once(self) -> BackfillJob | None:
        job = await claim_next_backfill(self.engine)
        if job is None:
            return None
        try:
            _preflight(job, self.settings)
            result = await self.executor(self.engine, self.settings, job)
            result.setdefault(
                "attempt",
                {
                    "scope_idempotency_key": job.result_json.get(
                        "scope_idempotency_key", job.idempotency_key
                    ),
                    "attempt_number": job.result_json.get("attempt_number", 1),
                    "prior_attempt_id": job.result_json.get("prior_attempt_id"),
                    "attempt_reason": job.result_json.get("attempt_reason", "initial"),
                },
            )
            current = await _current_job(self.engine, job.id)
            if current.status == "running":
                current = await update_backfill_progress(
                    self.engine,
                    job.id,
                    progress=1,
                    current_stage="completed",
                    downloaded_record_count=_int_value(result.get("downloaded_records", 0)),
                    result=result,
                    completed=True,
                )
            return current
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return await fail_backfill_job(self.engine, job.id, exc)

    async def _run(self) -> None:
        try:
            await recover_interrupted_backfills(self.engine)
            while not self._stopping.is_set():
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "backfill_worker_cycle_failed",
                        error_type=type(exc).__name__,
                        error_message=redact_sensitive_text(exc)[:500],
                    )
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_seconds)
        finally:
            self._stopping.set()


__all__ = [
    "BackfillExecutor",
    "BackfillWorker",
    "PartialBackfillError",
    "assess_release_analysis_inputs",
    "claim_next_backfill",
    "execute_backfill_job",
    "fail_backfill_job",
    "recover_interrupted_backfills",
]
