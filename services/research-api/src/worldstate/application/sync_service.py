"""Durable, idempotent synchronization jobs with retry and restart recovery."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import (
    DataMode,
    redact_sensitive_text,
    validate_data_mode,
)
from worldstate.db.models import SyncJob, SyncJobRun


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def make_sync_idempotency_key(
    job_key: str, scheduled_for: datetime, data_mode: DataMode, input_data: dict[str, Any]
) -> str:
    payload = json.dumps(
        {
            "job_key": job_key,
            "scheduled_for": _utc(scheduled_for).isoformat(),
            "data_mode": data_mode,
            "input": input_data,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def ensure_sync_job(
    engine: AsyncEngine,
    *,
    job_key: str,
    operation: str,
    schedule_type: str,
    schedule: dict[str, Any],
    provider_key: str | None = None,
    data_mode: DataMode = "observed",
    enabled: bool = True,
    max_attempts: int = 3,
    retry_backoff_seconds: int = 60,
    timeout_seconds: int = 300,
    next_run_at: datetime | None = None,
    config: dict[str, Any] | None = None,
) -> SyncJob:
    validate_data_mode(data_mode)
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least one")
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.scalar(select(SyncJob).where(SyncJob.job_key == job_key))
        values = {
            "provider_key": provider_key,
            "operation": operation,
            "schedule_type": schedule_type,
            "schedule_json": schedule,
            "enabled": enabled,
            "data_mode": data_mode,
            "max_attempts": max_attempts,
            "retry_backoff_seconds": retry_backoff_seconds,
            "timeout_seconds": timeout_seconds,
            "next_run_at": _utc(next_run_at) if next_run_at else None,
            "config_json": config or {},
        }
        if row is None:
            row = SyncJob(id=uuid.uuid4(), job_key=job_key, last_scheduled_at=None, **values)
            session.add(row)
        else:
            if row.next_run_at is not None:
                values["next_run_at"] = row.next_run_at
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row


async def enqueue_sync_run(
    engine: AsyncEngine,
    *,
    sync_job_id: uuid.UUID,
    scheduled_for: datetime,
    input_data: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    available_at: datetime | None = None,
) -> SyncJobRun:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        job = await session.get(SyncJob, sync_job_id)
        if job is None:
            raise LookupError("sync job not found")
        payload = input_data or {}
        key = idempotency_key or make_sync_idempotency_key(
            job.job_key, scheduled_for, validate_data_mode(job.data_mode), payload
        )
        existing = await session.scalar(
            select(SyncJobRun).where(SyncJobRun.idempotency_key == key)
        )
        if existing is not None:
            return existing
        scheduled = _utc(scheduled_for)
        row = SyncJobRun(
            id=uuid.uuid4(),
            sync_job_id=job.id,
            provider_run_id=None,
            source_artifact_id=None,
            retry_of_id=None,
            idempotency_key=key,
            status="pending",
            data_mode=job.data_mode,
            attempt=1,
            scheduled_for=scheduled,
            available_at=_utc(available_at) if available_at else scheduled,
            started_at=None,
            heartbeat_at=None,
            completed_at=None,
            records_read=0,
            records_written=0,
            checkpoint_json={},
            input_json=payload,
            output_json={},
            error_type=None,
            error_message=None,
        )
        job.last_scheduled_at = scheduled
        session.add(row)
        await session.flush()
        return row


async def start_sync_run(
    engine: AsyncEngine, run_id: uuid.UUID, *, now: datetime | None = None
) -> SyncJobRun:
    timestamp = _utc(now)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(SyncJobRun, run_id)
        if row is None:
            raise LookupError("sync job run not found")
        if row.status == "completed":
            return row
        if row.status not in {"pending", "retry_wait"}:
            raise ValueError(f"sync job run cannot start from {row.status}")
        if _utc(row.available_at) > timestamp:
            raise ValueError("sync job run is not available yet")
        row.status = "running"
        row.started_at = timestamp
        row.heartbeat_at = timestamp
        await session.flush()
        return row


async def heartbeat_sync_run(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    *,
    checkpoint: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> SyncJobRun:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(SyncJobRun, run_id)
        if row is None:
            raise LookupError("sync job run not found")
        if row.status != "running":
            raise ValueError("only a running sync job can heartbeat")
        row.heartbeat_at = _utc(now)
        if checkpoint is not None:
            row.checkpoint_json = checkpoint
        await session.flush()
        return row


async def complete_sync_run(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    *,
    records_read: int,
    records_written: int,
    output_data: dict[str, Any] | None = None,
    provider_run_id: uuid.UUID | None = None,
    source_artifact_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> SyncJobRun:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(SyncJobRun, run_id)
        if row is None:
            raise LookupError("sync job run not found")
        if row.status == "completed":
            return row
        if row.status != "running":
            raise ValueError("only a running sync job can complete")
        row.status = "completed"
        row.completed_at = _utc(now)
        row.records_read = records_read
        row.records_written = records_written
        row.output_json = output_data or {}
        row.provider_run_id = provider_run_id
        row.source_artifact_id = source_artifact_id
        row.error_type = None
        row.error_message = None
        await session.flush()
        return row


async def _fail_in_session(
    session: AsyncSession,
    row: SyncJobRun,
    *,
    error_type: str,
    error_message: str,
    timestamp: datetime,
) -> SyncJobRun | None:
    if row.status in {"completed", "cancelled"}:
        return None
    row.status = "failed"
    row.completed_at = timestamp
    row.error_type = error_type
    row.error_message = redact_sensitive_text(error_message)[:2000]
    job = await session.get(SyncJob, row.sync_job_id)
    if job is None or row.attempt >= job.max_attempts:
        return None
    attempt = row.attempt + 1
    retry_key = f"{row.idempotency_key}:retry:{attempt}"
    existing = await session.scalar(
        select(SyncJobRun).where(SyncJobRun.idempotency_key == retry_key)
    )
    if existing is not None:
        return existing
    delay = job.retry_backoff_seconds * (2 ** (row.attempt - 1))
    retry = SyncJobRun(
        id=uuid.uuid4(),
        sync_job_id=row.sync_job_id,
        provider_run_id=None,
        source_artifact_id=None,
        retry_of_id=row.id,
        idempotency_key=retry_key,
        status="retry_wait",
        data_mode=row.data_mode,
        attempt=attempt,
        scheduled_for=row.scheduled_for,
        available_at=timestamp + timedelta(seconds=delay),
        started_at=None,
        heartbeat_at=None,
        completed_at=None,
        records_read=0,
        records_written=0,
        checkpoint_json=row.checkpoint_json,
        input_json=row.input_json,
        output_json={},
        error_type=None,
        error_message=None,
    )
    session.add(retry)
    await session.flush()
    return retry


async def fail_sync_run(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    *,
    error_type: str,
    error_message: str,
    now: datetime | None = None,
) -> tuple[SyncJobRun, SyncJobRun | None]:
    timestamp = _utc(now)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(SyncJobRun, run_id)
        if row is None:
            raise LookupError("sync job run not found")
        retry = await _fail_in_session(
            session,
            row,
            error_type=error_type,
            error_message=error_message,
            timestamp=timestamp,
        )
        return row, retry


async def recover_interrupted_runs(
    engine: AsyncEngine,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 600,
) -> list[SyncJobRun]:
    """Fail stale running attempts and return any durable retry attempts created."""

    timestamp = _utc(now)
    cutoff = timestamp - timedelta(seconds=stale_after_seconds)
    factory = _factory(engine)
    retries: list[SyncJobRun] = []
    async with factory() as session, session.begin():
        candidates = (
            await session.scalars(select(SyncJobRun).where(SyncJobRun.status == "running"))
        ).all()
        for row in candidates:
            last_seen = row.heartbeat_at or row.started_at
            if last_seen is None or _utc(last_seen) > cutoff:
                continue
            retry = await _fail_in_session(
                session,
                row,
                error_type="InterruptedRun",
                error_message="run was stale when the local scheduler restarted",
                timestamp=timestamp,
            )
            if retry is not None:
                retries.append(retry)
    return retries


__all__ = [
    "complete_sync_run",
    "enqueue_sync_run",
    "ensure_sync_job",
    "fail_sync_run",
    "heartbeat_sync_run",
    "make_sync_idempotency_key",
    "recover_interrupted_runs",
    "start_sync_run",
]
