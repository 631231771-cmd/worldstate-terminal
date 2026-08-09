"""Persistence boundary for provider access, quotas, runs and data-mode isolation."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.db.models import (
    ProviderEntitlement,
    ProviderQuota,
    ProviderRun,
    SourceArtifact,
)

DataMode = Literal["observed", "fixture"]
EntitlementStatus = Literal["unknown", "granted", "denied", "expired", "not_configured"]
ProviderRunCompletionStatus = Literal["completed", "partial", "blocked"]

_SECRET_VALUE = re.compile(
    r"(?i)((?:api[_-]?key|registrationkey|token|authorization)[\"']?\s*[:=]\s*[\"']?)"
    r"(?:(?:basic|bearer|client)\s+)?[^&\s,;}\]\"']+"
)


def json_safe(value: Any) -> Any:
    """Convert domain values into stable JSON primitives before ORM persistence."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [json_safe(item) for item in value]
    return str(value)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def validate_data_mode(data_mode: str) -> DataMode:
    if data_mode not in {"observed", "fixture"}:
        raise ValueError("data_mode must be 'observed' or 'fixture'")
    return cast(DataMode, data_mode)


def assert_matching_data_mode(
    parent_mode: str,
    child_mode: str,
    relationship: str,
) -> None:
    """Reject a child row that would silently cross the observed/fixture boundary."""

    parent = validate_data_mode(parent_mode)
    child = validate_data_mode(child_mode)
    if parent != child:
        raise ValueError(
            f"data_mode mismatch for {relationship}: parent={parent!r}, child={child!r}"
        )


def redact_sensitive_text(value: object) -> str:
    """Remove labelled credentials before errors enter durable local state."""

    return _SECRET_VALUE.sub(r"\1[REDACTED]", str(value))


async def upsert_entitlement(
    engine: AsyncEngine,
    *,
    provider_key: str,
    capability: str,
    status: EntitlementStatus,
    checked_at: datetime | None = None,
    expires_at: datetime | None = None,
    provider_run_id: uuid.UUID | None = None,
    source_artifact_id: uuid.UUID | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    terms_url: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProviderEntitlement:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(ProviderEntitlement).where(
                ProviderEntitlement.provider_key == provider_key,
                ProviderEntitlement.capability == capability,
            )
        )
        values = {
            "status": status,
            "checked_at": _utc(checked_at),
            "expires_at": _utc(expires_at) if expires_at else None,
            "provider_run_id": provider_run_id,
            "source_artifact_id": source_artifact_id,
            "error_code": error_code,
            "error_message": error_message,
            "terms_url": terms_url,
            "metadata_json": metadata or {},
        }
        if row is None:
            row = ProviderEntitlement(
                id=uuid.uuid4(),
                provider_key=provider_key,
                capability=capability,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row


async def record_quota(
    engine: AsyncEngine,
    *,
    provider_key: str,
    quota_key: str,
    unit: str,
    period_start: datetime,
    period_end: datetime,
    used_value: Decimal,
    limit_value: Decimal | None,
    remaining_value: Decimal | None,
    warning_threshold: Decimal | None = None,
    captured_at: datetime | None = None,
    provider_run_id: uuid.UUID | None = None,
    source_artifact_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> ProviderQuota:
    start = _utc(period_start)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(ProviderQuota).where(
                ProviderQuota.provider_key == provider_key,
                ProviderQuota.quota_key == quota_key,
                ProviderQuota.period_start == start,
            )
        )
        values = {
            "unit": unit,
            "period_end": _utc(period_end),
            "limit_value": limit_value,
            "used_value": used_value,
            "remaining_value": remaining_value,
            "warning_threshold": warning_threshold,
            "captured_at": _utc(captured_at),
            "provider_run_id": provider_run_id,
            "source_artifact_id": source_artifact_id,
            "metadata_json": metadata or {},
        }
        if row is None:
            row = ProviderQuota(
                id=uuid.uuid4(),
                provider_key=provider_key,
                quota_key=quota_key,
                period_start=start,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row


async def record_provider_run(
    engine: AsyncEngine,
    *,
    provider_key: str,
    operation: str,
    idempotency_key: str,
    data_mode: DataMode = "observed",
    input_data: dict[str, Any] | None = None,
    estimated_cost_usd: Decimal | None = None,
    terms_url: str | None = None,
    started_at: datetime | None = None,
) -> ProviderRun:
    """Create a run exactly once; repeated calls return the original run."""

    validate_data_mode(data_mode)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(ProviderRun).where(
                ProviderRun.provider_key == provider_key,
                ProviderRun.operation == operation,
                ProviderRun.idempotency_key == idempotency_key,
                ProviderRun.data_mode == data_mode,
            )
        )
        if row is not None:
            return row
        row = ProviderRun(
            id=uuid.uuid4(),
            provider_key=provider_key,
            operation=operation,
            status="running",
            started_at=_utc(started_at),
            completed_at=None,
            records_read=0,
            records_written=0,
            source_artifact_id=None,
            data_mode=data_mode,
            idempotency_key=idempotency_key,
            request_count=0,
            estimated_cost_usd=estimated_cost_usd,
            actual_cost_usd=None,
            terms_url=terms_url,
            quality_grade="UNKNOWN",
            input_json=json_safe(input_data or {}),
            output_json={},
            warnings_json=[],
            error_message=None,
        )
        session.add(row)
        await session.flush()
        return row


async def record_source_artifact(
    engine: AsyncEngine,
    *,
    source_key: str,
    provider_key: str,
    artifact_type: str,
    title: str,
    source_url: str,
    content: bytes,
    content_type: str | None,
    retrieved_at: datetime,
    published_at: datetime | None = None,
    license_name: str | None = None,
    citation_text: str | None = None,
    data_mode: DataMode = "observed",
    provider_run_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceArtifact:
    """Store a recoverable local raw response without exposing it through status APIs."""

    validate_data_mode(data_mode)
    content_hash = hashlib.sha256(content).hexdigest()
    factory = _factory(engine)
    async with factory() as session, session.begin():
        existing = await session.scalar(
            select(SourceArtifact).where(
                SourceArtifact.provider_key == provider_key,
                SourceArtifact.content_hash == content_hash,
                SourceArtifact.data_mode == data_mode,
            )
        )
        if existing is not None:
            return existing
        row = SourceArtifact(
            id=uuid.uuid4(),
            provider_run_id=provider_run_id,
            source_key=source_key,
            provider_key=provider_key,
            artifact_type=artifact_type,
            title=title,
            source_url=source_url,
            published_at=_utc(published_at) if published_at else None,
            retrieved_at=_utc(retrieved_at),
            content_hash=content_hash,
            content_type=content_type,
            byte_length=len(content),
            content_bytes=content,
            license_name=license_name,
            citation_text=citation_text,
            is_fixture=data_mode == "fixture",
            data_mode=data_mode,
            metadata_json=json_safe(metadata or {}),
        )
        session.add(row)
        await session.flush()
        return row


async def complete_provider_run(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    *,
    records_read: int,
    records_written: int,
    request_count: int,
    output_data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    source_artifact_id: uuid.UUID | None = None,
    quality_grade: str = "UNKNOWN",
    estimated_cost_usd: Decimal | None = None,
    actual_cost_usd: Decimal | None = None,
    completed_at: datetime | None = None,
    status: ProviderRunCompletionStatus = "completed",
    error_message: str | None = None,
) -> ProviderRun:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(ProviderRun, run_id)
        if row is None:
            raise LookupError("provider run not found")
        row.status = status
        row.completed_at = _utc(completed_at)
        row.records_read = records_read
        row.records_written = records_written
        row.request_count = request_count
        row.output_json = json_safe(output_data or {})
        row.warnings_json = json_safe(warnings or [])
        row.source_artifact_id = source_artifact_id
        row.quality_grade = quality_grade
        row.error_message = (
            redact_sensitive_text(error_message)[:2000] if error_message is not None else None
        )
        if estimated_cost_usd is not None:
            row.estimated_cost_usd = estimated_cost_usd
        row.actual_cost_usd = actual_cost_usd
        await session.flush()
        return row


async def fail_provider_run(
    engine: AsyncEngine,
    run_id: uuid.UUID,
    *,
    error: Exception | str,
    warnings: list[str] | None = None,
    completed_at: datetime | None = None,
) -> ProviderRun:
    """Persist a sanitized provider failure without serializing credentials."""

    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(ProviderRun, run_id)
        if row is None:
            raise LookupError("provider run not found")
        error_code = getattr(getattr(error, "error_code", None), "value", None)
        expected_block = error_code in {
            "provider_not_configured",
            "provider_entitlement_required",
            "provider_paid_download_disabled",
            "provider_budget_exceeded",
            "provider_cost_estimate_unavailable",
        }
        row.status = "blocked" if expected_block else "failed"
        row.completed_at = _utc(completed_at)
        message = str(error) if isinstance(error, str) else f"{type(error).__name__}: {error}"
        row.error_message = redact_sensitive_text(message)[:2000]
        row.warnings_json = warnings or []
        row.quality_grade = "C" if expected_block else "D"
        await session.flush()
        return row


async def associate_source_artifact(
    engine: AsyncEngine,
    *,
    provider_run_id: uuid.UUID,
    source_artifact_id: uuid.UUID,
    primary: bool = False,
) -> None:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        run = await session.get(ProviderRun, provider_run_id)
        artifact = await session.get(SourceArtifact, source_artifact_id)
        if run is None or artifact is None:
            raise LookupError("provider run or source artifact not found")
        artifact.provider_run_id = provider_run_id
        if primary or run.source_artifact_id is None:
            run.source_artifact_id = source_artifact_id


async def get_provider_data_status(engine: AsyncEngine) -> list[dict[str, Any]]:
    factory = _factory(engine)
    async with factory() as session:
        entitlements = (
            await session.scalars(
                select(ProviderEntitlement).order_by(ProviderEntitlement.provider_key)
            )
        ).all()
        quotas = (
            await session.scalars(
                select(ProviderQuota).order_by(
                    ProviderQuota.provider_key, ProviderQuota.captured_at.desc()
                )
            )
        ).all()
        runs = (
            await session.scalars(
                select(ProviderRun).order_by(ProviderRun.started_at.desc()).limit(500)
            )
        ).all()

    provider_keys = sorted(
        {row.provider_key for row in entitlements}
        | {row.provider_key for row in quotas}
        | {row.provider_key for row in runs}
    )
    return [
        {
            "provider_key": provider_key,
            "entitlements": [
                {
                    "capability": item.capability,
                    "status": item.status,
                    "checked_at": item.checked_at,
                    "error_code": item.error_code,
                    "error_message": item.error_message,
                }
                for item in entitlements
                if item.provider_key == provider_key
            ],
            "quota": next(
                (
                    {
                        "quota_key": item.quota_key,
                        "unit": item.unit,
                        "used": item.used_value,
                        "limit": item.limit_value,
                        "remaining": item.remaining_value,
                        "captured_at": item.captured_at,
                    }
                    for item in quotas
                    if item.provider_key == provider_key
                ),
                None,
            ),
            "last_run": next(
                (
                    {
                        "status": item.status,
                        "operation": item.operation,
                        "started_at": item.started_at,
                        "completed_at": item.completed_at,
                        "error_message": item.error_message,
                    }
                    for item in runs
                    if item.provider_key == provider_key
                    and item.operation != "configuration_health_snapshot"
                ),
                None,
            ),
            "health_snapshot": next(
                (
                    {
                        "status": item.output_json.get("health_status"),
                        "checked_at": item.output_json.get("checked_at") or item.completed_at,
                        "network_probe": item.output_json.get("network_probe", False),
                        "request_count": item.request_count,
                    }
                    for item in runs
                    if item.provider_key == provider_key
                    and item.operation == "configuration_health_snapshot"
                ),
                None,
            ),
        }
        for provider_key in provider_keys
    ]


__all__ = [
    "DataMode",
    "EntitlementStatus",
    "assert_matching_data_mode",
    "associate_source_artifact",
    "complete_provider_run",
    "fail_provider_run",
    "get_provider_data_status",
    "json_safe",
    "record_provider_run",
    "record_quota",
    "record_source_artifact",
    "redact_sensitive_text",
    "upsert_entitlement",
    "validate_data_mode",
]
