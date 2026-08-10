"""Local-only schedule registration and durable enqueue/recovery helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.sync_service import (
    enqueue_sync_run,
    ensure_sync_job,
    recover_interrupted_runs,
)
from worldstate.db.models import SyncJob, SyncJobRun

DEFAULT_SCHEDULES: tuple[dict[str, Any], ...] = (
    {
        "job_key": "daily-provider-health",
        "provider_key": None,
        "operation": "record_provider_health",
        "schedule_type": "daily",
        "schedule": {"at_utc": "04:00"},
    },
    {
        "job_key": "daily-official-sync",
        "provider_key": "official",
        "operation": "sync_official",
        "schedule_type": "daily",
        "schedule": {"at_utc": "05:00"},
    },
    {
        "job_key": "daily-bls-current-state",
        "provider_key": "bls_official",
        "operation": "sync_bls_current_state",
        "schedule_type": "daily",
        "schedule": {"at_utc": "05:15"},
    },
    {
        "job_key": "daily-public-macro-sync",
        "provider_key": "public_official",
        "operation": "sync_public_macro",
        "schedule_type": "daily",
        "schedule": {
            "at_utc": "05:30",
            "providers": ["fred", "ecb", "boe", "boj", "china"],
        },
    },
    {
        "job_key": "daily-calendar-sync",
        "provider_key": "official",
        "operation": "sync_calendar",
        "schedule_type": "daily",
        "schedule": {"at_utc": "04:30"},
    },
    {
        "job_key": "pre-release-consensus-snapshot",
        "provider_key": "trading_economics",
        "operation": "snapshot_consensus",
        "schedule_type": "release_relative",
        "schedule": {"offset_minutes": [-1440, -60, -5, 5]},
    },
    {
        "job_key": "post-release-official-refresh",
        "provider_key": "official",
        "operation": "refresh_official_release",
        "schedule_type": "release_relative",
        "schedule": {"offset_minutes": [5]},
    },
    {
        "job_key": "post-release-market-sync",
        "provider_key": "databento",
        "operation": "sync_event_market",
        "schedule_type": "release_relative",
        "schedule": {
            "offset_minutes": [5, 240],
            "deferred_windows": ["next_trading_day", "fifth_trading_day"],
        },
    },
    {
        "job_key": "overnight-reconciliation",
        "provider_key": None,
        "operation": "reconcile_data",
        "schedule_type": "daily",
        "schedule": {"at_utc": "07:00"},
    },
    {
        "job_key": "daily-world-state-snapshot",
        "provider_key": None,
        "operation": "snapshot_world_state",
        "schedule_type": "daily",
        "schedule": {"at_utc": "07:30"},
    },
)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def next_daily_occurrence(at_utc: str, now: datetime) -> datetime:
    hour, minute = (int(item) for item in at_utc.split(":", 1))
    candidate = datetime.combine(_utc(now).date(), time(hour, minute), tzinfo=UTC)
    return candidate if candidate > _utc(now) else candidate + timedelta(days=1)


def first_daily_occurrence(at_utc: str, now: datetime) -> datetime:
    """Return today's declared run, even when desktop startup is later.

    A desktop may be powered off at the scheduled hour.  On the first local
    registration we enqueue at most today's missed run instead of silently
    waiting until tomorrow (and instead of replaying an unbounded backlog).
    """

    hour, minute = (int(item) for item in at_utc.split(":", 1))
    return datetime.combine(_utc(now).date(), time(hour, minute), tzinfo=UTC)


async def ensure_default_schedule(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    catch_up_missed: bool = False,
) -> list[SyncJob]:
    timestamp = _utc(now)
    factory = _factory(engine)
    async with factory() as session:
        existing_jobs = {row.job_key: row for row in (await session.scalars(select(SyncJob))).all()}
    jobs: list[SyncJob] = []
    for definition in DEFAULT_SCHEDULES:
        schedule = dict(definition["schedule"])
        existing = existing_jobs.get(str(definition["job_key"]))
        if definition["schedule_type"] == "daily":
            at_utc = str(schedule["at_utc"])
            next_run_at = (
                first_daily_occurrence(at_utc, timestamp)
                if catch_up_missed
                and (
                    existing is None
                    or (existing.next_run_at is None and existing.last_scheduled_at is None)
                )
                else next_daily_occurrence(at_utc, timestamp)
            )
        else:
            next_run_at = None
        jobs.append(
            await ensure_sync_job(
                engine,
                job_key=str(definition["job_key"]),
                provider_key=(
                    str(definition["provider_key"])
                    if definition["provider_key"] is not None
                    else None
                ),
                operation=str(definition["operation"]),
                schedule_type=str(definition["schedule_type"]),
                schedule=schedule,
                next_run_at=next_run_at,
                data_mode="observed",
                max_attempts=3,
                retry_backoff_seconds=60,
                timeout_seconds=900,
            )
        )
    return jobs


async def enqueue_due_jobs(engine: AsyncEngine, *, now: datetime | None = None) -> list[SyncJobRun]:
    timestamp = _utc(now)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        due = (
            await session.scalars(
                select(SyncJob).where(
                    SyncJob.enabled.is_(True),
                    SyncJob.schedule_type == "daily",
                    SyncJob.next_run_at.is_not(None),
                    SyncJob.next_run_at <= timestamp,
                )
            )
        ).all()
        definitions = [
            (row.id, row.next_run_at or timestamp, row.job_key, dict(row.schedule_json))
            for row in due
        ]
        for row in due:
            row.last_scheduled_at = row.next_run_at
            row.next_run_at = next_daily_occurrence(str(row.schedule_json["at_utc"]), timestamp)
    return [
        await enqueue_sync_run(
            engine,
            sync_job_id=job_id,
            scheduled_for=scheduled_for,
            input_data={"schedule": schedule, "job_key": job_key},
        )
        for job_id, scheduled_for, job_key, schedule in definitions
    ]


async def schedule_release_tasks(
    engine: AsyncEngine,
    *,
    macro_release_id: uuid.UUID,
    release_at: datetime,
) -> list[SyncJobRun]:
    factory = _factory(engine)
    async with factory() as session:
        jobs = (
            await session.scalars(
                select(SyncJob).where(
                    SyncJob.enabled.is_(True),
                    SyncJob.schedule_type == "release_relative",
                )
            )
        ).all()
    runs: list[SyncJobRun] = []
    for job in jobs:
        offsets = [int(item) for item in job.schedule_json.get("offset_minutes", [])]
        for offset in offsets:
            scheduled = _utc(release_at) + timedelta(minutes=offset)
            runs.append(
                await enqueue_sync_run(
                    engine,
                    sync_job_id=job.id,
                    scheduled_for=scheduled,
                    input_data={
                        "macro_release_id": str(macro_release_id),
                        "offset_minutes": offset,
                        "phase": "pre" if offset < 0 else "post",
                    },
                )
            )
    return runs


async def claim_next_run(engine: AsyncEngine, *, now: datetime | None = None) -> SyncJobRun | None:
    timestamp = _utc(now)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        eligibility = (
            SyncJobRun.status.in_(("pending", "retry_wait")),
            SyncJobRun.available_at <= timestamp,
        )
        if session.bind is not None and session.bind.dialect.name == "sqlite":
            # SQLite ignores SELECT ... FOR UPDATE. Claim with one conditional
            # UPDATE ... RETURNING statement so two local workers cannot both
            # receive the same run.
            candidate_id = (
                select(SyncJobRun.id)
                .where(*eligibility)
                .order_by(SyncJobRun.available_at, SyncJobRun.scheduled_for, SyncJobRun.id)
                .limit(1)
                .scalar_subquery()
            )
            return await session.scalar(
                update(SyncJobRun)
                .where(SyncJobRun.id == candidate_id, *eligibility)
                .values(
                    status="running",
                    started_at=timestamp,
                    heartbeat_at=timestamp,
                )
                .returning(SyncJobRun)
            )
        row = await session.scalar(
            select(SyncJobRun)
            .where(*eligibility)
            .order_by(SyncJobRun.available_at, SyncJobRun.scheduled_for, SyncJobRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        # Claim and state transition share one transaction. A second worker on
        # a database with row locking can no longer select the same run between
        # this query and a separate start transaction.
        row.status = "running"
        row.started_at = timestamp
        row.heartbeat_at = timestamp
        await session.flush()
        return row


async def schedule_deferred_market_window(
    engine: AsyncEngine,
    *,
    macro_release_id: uuid.UUID,
    window_key: str,
    scheduled_for: datetime,
) -> SyncJobRun:
    """Enqueue an instrument-calendar-resolved next/fifth-session market window."""

    if window_key not in {"next_trading_day", "fifth_trading_day"}:
        raise ValueError("unsupported deferred market window")
    factory = _factory(engine)
    async with factory() as session:
        job = await session.scalar(
            select(SyncJob).where(SyncJob.job_key == "post-release-market-sync")
        )
    if job is None:
        raise LookupError("post-release-market-sync job is not registered")
    return await enqueue_sync_run(
        engine,
        sync_job_id=job.id,
        scheduled_for=_utc(scheduled_for),
        input_data={
            "macro_release_id": str(macro_release_id),
            "window_key": window_key,
            "phase": "post",
        },
    )


async def recover_scheduler(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 600,
) -> list[SyncJobRun]:
    """Desktop startup may always call this; failures remain data, not startup blockers."""

    return await recover_interrupted_runs(
        engine,
        now=now,
        stale_after_seconds=stale_after_seconds,
    )


__all__ = [
    "DEFAULT_SCHEDULES",
    "claim_next_run",
    "enqueue_due_jobs",
    "ensure_default_schedule",
    "first_daily_occurrence",
    "next_daily_occurrence",
    "recover_scheduler",
    "schedule_deferred_market_window",
    "schedule_release_tasks",
]
