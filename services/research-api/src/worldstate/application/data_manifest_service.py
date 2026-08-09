"""Immutable calendar and event-market dataset manifests."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import (
    DataMode,
    assert_matching_data_mode,
    json_safe,
    validate_data_mode,
)
from worldstate.db.models import CalendarSnapshot, MacroRelease, MarketDataManifest


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _hash(payload: dict[str, Any] | list[dict[str, Any]]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


async def record_market_data_manifest(
    engine: AsyncEngine,
    *,
    macro_release_id: uuid.UUID,
    release_stage_id: uuid.UUID | None,
    provider_key: str,
    dataset: str,
    schema_name: str,
    instrument_id: uuid.UUID,
    futures_contract_id: uuid.UUID | None,
    source_symbol: str,
    contract_code: str | None,
    start_at: datetime,
    end_at: datetime,
    interval_seconds: int,
    row_count: int,
    size_bytes: int | None,
    source_content_hash: str,
    data_mode: DataMode = "observed",
    quality_grade: str = "UNKNOWN",
    is_aggregated: bool = False,
    aggregation_method: str | None = None,
    aggregation_version: str | None = None,
    contract_selection_rule: str | None = None,
    continuous_resolution: dict[str, Any] | None = None,
    roll_status: str | None = None,
    estimated_cost_usd: Decimal | None = None,
    actual_cost_usd: Decimal | None = None,
    provider_run_id: uuid.UUID | None = None,
    sync_job_run_id: uuid.UUID | None = None,
    source_artifact_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> MarketDataManifest:
    """Record one event slice; the hash includes release/stage and contract resolution."""

    validate_data_mode(data_mode)
    identity = {
        "macro_release_id": str(macro_release_id),
        "release_stage_id": str(release_stage_id or ""),
        "provider_key": provider_key,
        "dataset": dataset,
        "schema_name": schema_name,
        "instrument_id": str(instrument_id),
        "futures_contract_id": str(futures_contract_id or ""),
        "source_symbol": source_symbol,
        "contract_code": contract_code,
        "start_at": start_at,
        "end_at": end_at,
        "interval_seconds": interval_seconds,
        "data_mode": data_mode,
        "source_content_hash": source_content_hash,
        "aggregation_method": aggregation_method,
        "aggregation_version": aggregation_version,
        "contract_selection_rule": contract_selection_rule,
        "continuous_resolution": continuous_resolution or {},
        "roll_status": roll_status,
    }
    manifest_hash = _hash(identity)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        release = await session.get(MacroRelease, macro_release_id)
        if release is None:
            raise LookupError("macro release not found")
        assert_matching_data_mode(release.data_mode, data_mode, "market_data_manifest")
        existing = await session.scalar(
            select(MarketDataManifest).where(MarketDataManifest.manifest_hash == manifest_hash)
        )
        if existing is not None:
            return existing
        row = MarketDataManifest(
            id=uuid.uuid4(),
            manifest_hash=manifest_hash,
            macro_release_id=macro_release_id,
            release_stage_id=release_stage_id,
            provider_key=provider_key,
            dataset=dataset,
            schema_name=schema_name,
            instrument_id=instrument_id,
            futures_contract_id=futures_contract_id,
            source_symbol=source_symbol,
            contract_code=contract_code,
            start_at=start_at,
            end_at=end_at,
            interval_seconds=interval_seconds,
            row_count=row_count,
            size_bytes=size_bytes,
            data_mode=data_mode,
            quality_grade=quality_grade,
            is_aggregated=is_aggregated,
            aggregation_method=aggregation_method,
            aggregation_version=aggregation_version,
            contract_selection_rule=contract_selection_rule,
            continuous_resolution_json=json_safe(continuous_resolution or {}),
            roll_status=roll_status,
            estimated_cost_usd=estimated_cost_usd,
            actual_cost_usd=actual_cost_usd,
            provider_run_id=provider_run_id,
            sync_job_run_id=sync_job_run_id,
            source_artifact_id=source_artifact_id,
            metadata_json=json_safe(
                {**(metadata or {}), "source_content_hash": source_content_hash}
            ),
        )
        session.add(row)
        await session.flush()
        return row


async def record_calendar_snapshot(
    engine: AsyncEngine,
    *,
    provider_key: str,
    calendar_kind: str,
    period_start: date,
    period_end: date,
    captured_at: datetime,
    payload: list[dict[str, Any]],
    data_mode: DataMode = "observed",
    is_point_in_time: bool = True,
    provider_run_id: uuid.UUID | None = None,
    source_artifact_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> CalendarSnapshot:
    validate_data_mode(data_mode)
    content_hash = _hash(payload)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        existing = await session.scalar(
            select(CalendarSnapshot).where(
                CalendarSnapshot.provider_key == provider_key,
                CalendarSnapshot.calendar_kind == calendar_kind,
                CalendarSnapshot.captured_at == captured_at,
                CalendarSnapshot.content_hash == content_hash,
                CalendarSnapshot.data_mode == data_mode,
            )
        )
        if existing is not None:
            return existing
        row = CalendarSnapshot(
            id=uuid.uuid4(),
            provider_key=provider_key,
            calendar_kind=calendar_kind,
            period_start=period_start,
            period_end=period_end,
            captured_at=captured_at,
            content_hash=content_hash,
            event_count=len(payload),
            data_mode=data_mode,
            is_point_in_time=is_point_in_time,
            provider_run_id=provider_run_id,
            source_artifact_id=source_artifact_id,
            payload_json=json_safe(payload),
            metadata_json=json_safe(metadata or {}),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        await session.flush()
        return row


__all__ = ["record_calendar_snapshot", "record_market_data_manifest"]
