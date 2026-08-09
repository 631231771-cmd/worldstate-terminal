"""Bounded historical backfill estimation, budget enforcement and lifecycle."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import DataMode, validate_data_mode
from worldstate.db.models import BackfillJob, MacroRelease, MarketDataManifest, MarketInstrument

SUPPORTED_EVENT_TYPES = frozenset({"US_CPI", "US_NFP", "FOMC"})
SUPPORTED_INSTRUMENTS = frozenset({"GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX"})


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    start_date: date
    end_date: date
    event_types: tuple[str, ...]
    instruments: tuple[str, ...]
    datasets: tuple[str, ...]
    dataset_schemas: tuple[tuple[str, str], ...] = ()
    data_mode: DataMode = "observed"
    intraday_pre_minutes: int = 90
    intraday_post_minutes: int = 240
    daily_pre_days: int = 5
    daily_post_days: int = 5
    expected_event_count: int | None = None


@dataclass(frozen=True, slots=True)
class BackfillEstimate:
    event_count: int
    asset_count: int
    minute_range_per_event: int
    estimated_record_count: int
    existing_record_count: int
    estimated_download_records: int
    estimated_size_bytes: int
    estimated_cost_usd: Decimal
    budget_limit_usd: Decimal
    paid_download_allowed: bool
    execution_allowed: bool
    estimation_method: str
    datasets: tuple[str, ...]


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _validate_request(request: BackfillRequest) -> None:
    validate_data_mode(request.data_mode)
    if request.end_date < request.start_date:
        raise ValueError("backfill end_date must not precede start_date")
    unsupported_events = set(request.event_types) - SUPPORTED_EVENT_TYPES
    if unsupported_events:
        raise ValueError(f"unsupported event types: {sorted(unsupported_events)}")
    unsupported_instruments = set(request.instruments) - SUPPORTED_INSTRUMENTS
    if unsupported_instruments:
        raise ValueError(f"unsupported instruments: {sorted(unsupported_instruments)}")
    if request.intraday_pre_minutes < 0 or request.intraday_post_minutes < 0:
        raise ValueError("intraday minute ranges cannot be negative")
    if any(not dataset or not schema for dataset, schema in request.dataset_schemas):
        raise ValueError("dataset/schema mappings cannot be empty")


def make_backfill_idempotency_key(request: BackfillRequest) -> str:
    payload = json.dumps(asdict(request), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _attempt_number(row: BackfillJob, scope_key: str) -> int:
    stored = row.estimate_json.get("attempt_number")
    if isinstance(stored, int) and stored > 0:
        return stored
    prefix = f"{scope_key}:attempt:"
    if row.idempotency_key.startswith(prefix):
        try:
            return max(1, int(row.idempotency_key.removeprefix(prefix)))
        except ValueError:
            pass
    return 1


async def _observed_event_count(session: AsyncSession, request: BackfillRequest) -> int:
    releases = (
        await session.scalars(
            select(MacroRelease).where(
                MacroRelease.release_type.in_(request.event_types),
                MacroRelease.data_mode == request.data_mode,
                MacroRelease.status != "invalidated",
            )
        )
    ).all()
    return sum(
        1
        for release in releases
        if request.start_date <= release.scheduled_at.date() <= request.end_date
    )


async def _existing_records(session: AsyncSession, request: BackfillRequest) -> int:
    instruments = (
        await session.scalars(
            select(MarketInstrument).where(MarketInstrument.symbol.in_(request.instruments))
        )
    ).all()
    ids = [row.id for row in instruments]
    if not ids:
        return 0
    manifests = (
        await session.execute(
            select(MarketDataManifest, MacroRelease.scheduled_at)
            .join(MacroRelease, MacroRelease.id == MarketDataManifest.macro_release_id)
            .where(
                MarketDataManifest.instrument_id.in_(ids),
                MarketDataManifest.data_mode == request.data_mode,
                MacroRelease.release_type.in_(request.event_types),
                MacroRelease.status != "invalidated",
            )
        )
    ).all()
    allowed_pairs = set(request.dataset_schemas)
    allowed_schemas = {item for item in request.datasets if item.startswith("ohlcv-")}
    allowed_datasets = set(request.datasets) - allowed_schemas
    covered_slices: dict[tuple[object, ...], int] = {}
    for manifest, scheduled_at in manifests:
        if not request.start_date <= scheduled_at.date() <= request.end_date:
            continue
        if allowed_pairs:
            matches = (manifest.dataset, manifest.schema_name) in allowed_pairs
        else:
            matches = (
                manifest.schema_name in allowed_schemas or manifest.dataset in allowed_datasets
            )
        if not matches:
            continue
        # A refreshed raw artifact can produce another immutable manifest for the
        # same event slice.  Count the largest slice once; downloaded bars are
        # themselves deduplicated on provider/instrument/timestamp.
        coverage_key = (
            manifest.macro_release_id,
            manifest.instrument_id,
            manifest.dataset,
            manifest.schema_name,
            manifest.start_at,
            manifest.end_at,
        )
        covered_slices[coverage_key] = max(
            manifest.row_count,
            covered_slices.get(coverage_key, 0),
        )
    return sum(covered_slices.values())


async def estimate_backfill(
    engine: AsyncEngine,
    request: BackfillRequest,
    *,
    budget_limit_usd: Decimal,
    paid_download_allowed: bool,
    provider_estimated_cost_usd: Decimal | None = None,
    fallback_cost_per_million_records_usd: Decimal = Decimal("1.00"),
    estimated_bytes_per_record: int = 80,
) -> BackfillEstimate:
    """Estimate first; observed paid execution remains disabled unless explicitly allowed."""

    _validate_request(request)
    factory = _factory(engine)
    async with factory() as session:
        event_count = request.expected_event_count
        if event_count is None:
            event_count = await _observed_event_count(session, request)
        existing = await _existing_records(session, request)

    minute_range = request.intraday_pre_minutes + request.intraday_post_minutes
    intraday_datasets = sum("1m" in item or "intraday" in item for item in request.datasets)
    daily_datasets = len(request.datasets) - intraday_datasets
    per_event_asset = (
        minute_range * intraday_datasets
        + (request.daily_pre_days + request.daily_post_days + 1) * daily_datasets
    )
    estimated_records = event_count * len(request.instruments) * per_event_asset
    download_records = max(0, estimated_records - existing)
    if provider_estimated_cost_usd is None:
        estimated_cost = (
            Decimal(download_records) / Decimal(1_000_000)
        ) * fallback_cost_per_million_records_usd
        method = "fallback_record_estimate"
    else:
        estimated_cost = provider_estimated_cost_usd
        method = "provider_estimate"
    estimated_cost = estimated_cost.quantize(Decimal("0.000001"))
    allowed = request.data_mode == "fixture" or (
        paid_download_allowed and estimated_cost <= budget_limit_usd
    )
    return BackfillEstimate(
        event_count=event_count,
        asset_count=len(request.instruments),
        minute_range_per_event=minute_range,
        estimated_record_count=estimated_records,
        existing_record_count=existing,
        estimated_download_records=download_records,
        estimated_size_bytes=download_records * estimated_bytes_per_record,
        estimated_cost_usd=estimated_cost,
        budget_limit_usd=budget_limit_usd,
        paid_download_allowed=paid_download_allowed,
        execution_allowed=allowed,
        estimation_method=method,
        datasets=request.datasets,
    )


async def create_backfill_job(
    engine: AsyncEngine,
    request: BackfillRequest,
    estimate: BackfillEstimate,
    *,
    execute_requested: bool,
    provider_key: str = "databento",
    requested_at: datetime | None = None,
) -> BackfillJob:
    _validate_request(request)
    key = make_backfill_idempotency_key(request)
    now = requested_at or datetime.now(UTC)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        scope_rows = (
            await session.scalars(
                select(BackfillJob).where(
                    or_(
                        BackfillJob.idempotency_key == key,
                        BackfillJob.idempotency_key.like(f"{key}:attempt:%"),
                    )
                )
            )
        ).all()
        existing = (
            max(scope_rows, key=lambda row: (_attempt_number(row, key), row.requested_at))
            if scope_rows
            else None
        )
        attempt_number = _attempt_number(existing, key) if existing is not None else 1
        if existing is not None:
            if execute_requested and existing.status == "estimated":
                existing.estimated_event_count = estimate.event_count
                existing.estimated_record_count = estimate.estimated_record_count
                existing.estimated_size_bytes = estimate.estimated_size_bytes
                existing.estimated_cost_usd = estimate.estimated_cost_usd
                existing.budget_limit_usd = estimate.budget_limit_usd
                existing.paid_download_allowed = estimate.paid_download_allowed
                existing.execution_allowed = estimate.execution_allowed
                existing.status = "pending" if estimate.execution_allowed else "rejected"
                existing.error_message = (
                    None
                    if estimate.execution_allowed
                    else "paid download is disabled or the estimate exceeds the budget"
                )
                return existing
            if existing.status in {"pending", "running", "estimated", "cancelled"}:
                return existing
            if existing.status == "rejected" and not estimate.execution_allowed:
                # Repeated blocked requests remain idempotent until the cost gate changes.
                existing.estimated_cost_usd = estimate.estimated_cost_usd
                existing.budget_limit_usd = estimate.budget_limit_usd
                existing.paid_download_allowed = estimate.paid_download_allowed
                existing.execution_allowed = False
                return existing
            if not execute_requested:
                return existing
            # POSTing the same bounded scope after failed/rejected/completed is an
            # explicit retry/refresh. Keep the terminal attempt immutable and create
            # a new durable attempt instead of returning a stale result forever.
            attempt_number += 1
        if execute_requested and not estimate.execution_allowed:
            status = "rejected"
            error_message = "paid download is disabled or the estimate exceeds the budget"
        elif execute_requested:
            status = "pending"
            error_message = None
        else:
            status = "estimated"
            error_message = None
        estimate_data: dict[str, Any] = asdict(estimate)
        estimate_data["estimated_cost_usd"] = str(estimate.estimated_cost_usd)
        estimate_data["budget_limit_usd"] = str(estimate.budget_limit_usd)
        estimate_data["scope_idempotency_key"] = key
        estimate_data["attempt_number"] = attempt_number
        if existing is not None:
            estimate_data["prior_attempt_id"] = str(existing.id)
            estimate_data["attempt_reason"] = (
                "refresh" if existing.status == "completed" else "retry"
            )
        row_key = key if attempt_number == 1 else f"{key}:attempt:{attempt_number}"
        row = BackfillJob(
            id=uuid.uuid4(),
            idempotency_key=row_key,
            provider_key=provider_key,
            status=status,
            data_mode=request.data_mode,
            start_date=request.start_date,
            end_date=request.end_date,
            event_types_json=list(request.event_types),
            instruments_json=list(request.instruments),
            datasets_json=(
                [f"{dataset}:{schema}" for dataset, schema in request.dataset_schemas]
                if request.dataset_schemas
                else list(request.datasets)
            ),
            estimated_event_count=estimate.event_count,
            estimated_record_count=estimate.estimated_record_count,
            estimated_size_bytes=estimate.estimated_size_bytes,
            estimated_cost_usd=estimate.estimated_cost_usd,
            budget_limit_usd=estimate.budget_limit_usd,
            paid_download_allowed=estimate.paid_download_allowed,
            execution_allowed=estimate.execution_allowed,
            existing_record_count=estimate.existing_record_count,
            downloaded_record_count=0,
            progress=0,
            current_stage=None,
            requested_at=now,
            started_at=None,
            completed_at=None,
            cancelled_at=None,
            sync_job_run_id=None,
            estimate_json=estimate_data,
            result_json={
                "scope_idempotency_key": key,
                "attempt_number": attempt_number,
                "prior_attempt_id": str(existing.id) if existing is not None else None,
                "attempt_reason": (
                    "refresh"
                    if existing is not None and existing.status == "completed"
                    else "retry"
                    if existing is not None
                    else "initial"
                ),
            },
            error_message=error_message,
        )
        session.add(row)
        await session.flush()
        return row


async def update_backfill_progress(
    engine: AsyncEngine,
    job_id: uuid.UUID,
    *,
    progress: float,
    current_stage: str,
    downloaded_record_count: int,
    result: dict[str, Any] | None = None,
    completed: bool = False,
    now: datetime | None = None,
) -> BackfillJob:
    if not 0 <= progress <= 1:
        raise ValueError("progress must be between zero and one")
    timestamp = now or datetime.now(UTC)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, job_id)
        if row is None:
            raise LookupError("backfill job not found")
        if row.status in {"cancelled", "rejected", "completed"}:
            return row
        if not row.execution_allowed:
            raise PermissionError("backfill execution was not approved by the cost policy")
        if row.started_at is None:
            row.started_at = timestamp
        row.status = "completed" if completed else "running"
        row.progress = 1 if completed else progress
        row.current_stage = current_stage
        row.downloaded_record_count = downloaded_record_count
        row.result_json = result or row.result_json
        row.completed_at = timestamp if completed else None
        await session.flush()
        return row


async def cancel_backfill_job(
    engine: AsyncEngine, job_id: uuid.UUID, *, now: datetime | None = None
) -> BackfillJob:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(BackfillJob, job_id)
        if row is None:
            raise LookupError("backfill job not found")
        if row.status in {"completed", "cancelled", "rejected"}:
            return row
        row.status = "cancelled"
        row.cancelled_at = now or datetime.now(UTC)
        row.current_stage = "cancelled"
        await session.flush()
        return row


async def get_backfill_job(engine: AsyncEngine, job_id: uuid.UUID) -> BackfillJob:
    factory = _factory(engine)
    async with factory() as session:
        row = await session.get(BackfillJob, job_id)
        if row is None:
            raise LookupError("backfill job not found")
        return row


__all__ = [
    "SUPPORTED_EVENT_TYPES",
    "SUPPORTED_INSTRUMENTS",
    "BackfillEstimate",
    "BackfillRequest",
    "cancel_backfill_job",
    "create_backfill_job",
    "estimate_backfill",
    "get_backfill_job",
    "make_backfill_idempotency_key",
    "update_backfill_progress",
]
