"""Non-destructive official/secondary and market-data reconciliation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import DataMode, validate_data_mode
from worldstate.db.models import (
    DataReconciliationRecord,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    ReleaseValue,
)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def make_reconciliation_key(
    *,
    reconciliation_type: str,
    subject_type: str,
    subject_id: str,
    field_name: str | None,
    authoritative_artifact_id: uuid.UUID | None,
    comparison_artifact_id: uuid.UUID | None,
) -> str:
    payload = json.dumps(
        {
            "type": reconciliation_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "field": field_name,
            "official_artifact": str(authoritative_artifact_id or ""),
            "comparison_artifact": str(comparison_artifact_id or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def reconcile_values(
    engine: AsyncEngine,
    *,
    subject_type: str,
    subject_id: str,
    field_name: str,
    authoritative_provider_key: str,
    comparison_provider_key: str,
    authoritative_value: Decimal | str | None,
    comparison_value: Decimal | str | None,
    unit: str,
    tolerance: Decimal = Decimal("0"),
    authoritative_artifact_id: uuid.UUID | None = None,
    comparison_artifact_id: uuid.UUID | None = None,
    sync_job_run_id: uuid.UUID | None = None,
    data_mode: DataMode = "observed",
    detected_at: datetime | None = None,
) -> DataReconciliationRecord:
    """Persist the difference while retaining both artifacts; never overwrite either value."""

    validate_data_mode(data_mode)
    numeric_difference: Decimal | None = None
    if authoritative_value is None or comparison_value is None:
        status = "missing"
        severity = "warning"
    else:
        try:
            numeric_difference = Decimal(str(comparison_value)) - Decimal(str(authoritative_value))
        except ArithmeticError:
            numeric_difference = None
        if numeric_difference is None:
            status = "matched" if str(authoritative_value) == str(comparison_value) else "mismatch"
        else:
            status = "matched" if abs(numeric_difference) <= tolerance else "mismatch"
        severity = "info" if status == "matched" else "warning"
    key = make_reconciliation_key(
        reconciliation_type="official_vs_secondary",
        subject_type=subject_type,
        subject_id=subject_id,
        field_name=field_name,
        authoritative_artifact_id=authoritative_artifact_id,
        comparison_artifact_id=comparison_artifact_id,
    )
    official_json = {
        "value": str(authoritative_value) if authoritative_value is not None else None,
        "unit": unit,
    }
    comparison_json = {
        "value": str(comparison_value) if comparison_value is not None else None,
        "unit": unit,
    }
    difference_json = {
        "absolute": str(numeric_difference) if numeric_difference is not None else None,
        "tolerance": str(tolerance),
        "authoritative_source_wins": True,
    }
    return await _upsert_record(
        engine,
        reconciliation_key=key,
        reconciliation_type="official_vs_secondary",
        subject_type=subject_type,
        subject_id=subject_id,
        field_name=field_name,
        status=status,
        severity=severity,
        data_mode=data_mode,
        authoritative_provider_key=authoritative_provider_key,
        comparison_provider_key=comparison_provider_key,
        authoritative_artifact_id=authoritative_artifact_id,
        comparison_artifact_id=comparison_artifact_id,
        sync_job_run_id=sync_job_run_id,
        authoritative_value_json=official_json,
        comparison_value_json=comparison_json,
        difference_json=difference_json,
        detected_at=detected_at or datetime.now(UTC),
    )


async def record_market_reconciliation(
    engine: AsyncEngine,
    *,
    subject_id: str,
    provider_key: str,
    checks: dict[str, bool | int | float | str | None],
    source_artifact_id: uuid.UUID | None = None,
    sync_job_run_id: uuid.UUID | None = None,
    data_mode: DataMode = "observed",
    detected_at: datetime | None = None,
) -> DataReconciliationRecord:
    validate_data_mode(data_mode)
    key = make_reconciliation_key(
        reconciliation_type="market_integrity",
        subject_type="market_data_manifest",
        subject_id=subject_id,
        field_name=None,
        authoritative_artifact_id=source_artifact_id,
        comparison_artifact_id=None,
    )
    # A later overnight/count-only pass must not erase the richer contract,
    # OHLC, gap, timezone and roll checks captured during ingestion.
    factory = _factory(engine)
    async with factory() as session:
        existing = await session.scalar(
            select(DataReconciliationRecord).where(
                DataReconciliationRecord.reconciliation_key == key
            )
        )
    if existing is not None:
        previous = existing.authoritative_value_json.get("checks")
        if isinstance(previous, dict):
            checks = {**previous, **checks}
    failed = sorted(key for key, value in checks.items() if value is False)
    not_evaluated = sorted(key for key, value in checks.items() if value is None)
    status = "mismatch" if failed else "missing" if not_evaluated else "matched"
    return await _upsert_record(
        engine,
        reconciliation_key=key,
        reconciliation_type="market_integrity",
        subject_type="market_data_manifest",
        subject_id=subject_id,
        field_name=None,
        status=status,
        severity="info" if status == "matched" else "warning",
        data_mode=data_mode,
        authoritative_provider_key=provider_key,
        comparison_provider_key="worldstate_validator",
        authoritative_artifact_id=source_artifact_id,
        comparison_artifact_id=None,
        sync_job_run_id=sync_job_run_id,
        authoritative_value_json={"checks": checks},
        comparison_value_json={"ruleset": "market-integrity-v1"},
        difference_json={"failed_checks": failed, "not_evaluated_checks": not_evaluated},
        detected_at=detected_at or datetime.now(UTC),
    )


async def _upsert_record(
    engine: AsyncEngine,
    *,
    reconciliation_key: str,
    reconciliation_type: str,
    subject_type: str,
    subject_id: str,
    field_name: str | None,
    status: str,
    severity: str,
    data_mode: DataMode,
    authoritative_provider_key: str,
    comparison_provider_key: str,
    authoritative_artifact_id: uuid.UUID | None,
    comparison_artifact_id: uuid.UUID | None,
    sync_job_run_id: uuid.UUID | None,
    authoritative_value_json: dict[str, Any],
    comparison_value_json: dict[str, Any],
    difference_json: dict[str, Any],
    detected_at: datetime,
) -> DataReconciliationRecord:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(DataReconciliationRecord).where(
                DataReconciliationRecord.reconciliation_key == reconciliation_key
            )
        )
        values: dict[str, Any] = {
            "reconciliation_type": reconciliation_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "field_name": field_name,
            "status": status,
            "severity": severity,
            "data_mode": data_mode,
            "authoritative_provider_key": authoritative_provider_key,
            "comparison_provider_key": comparison_provider_key,
            "authoritative_artifact_id": authoritative_artifact_id,
            "comparison_artifact_id": comparison_artifact_id,
            "sync_job_run_id": sync_job_run_id,
            "authoritative_value_json": authoritative_value_json,
            "comparison_value_json": comparison_value_json,
            "difference_json": difference_json,
            "detected_at": detected_at,
        }
        if row is None:
            row = DataReconciliationRecord(
                id=uuid.uuid4(),
                reconciliation_key=reconciliation_key,
                resolved_at=None,
                resolution_action=None,
                resolution_notes=None,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        return row


async def resolve_reconciliation(
    engine: AsyncEngine,
    reconciliation_id: uuid.UUID,
    *,
    resolution_action: str,
    resolution_notes: str,
    resolved_at: datetime | None = None,
) -> DataReconciliationRecord:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        row = await session.get(DataReconciliationRecord, reconciliation_id)
        if row is None:
            raise LookupError("reconciliation record not found")
        row.status = "resolved"
        row.resolution_action = resolution_action
        row.resolution_notes = resolution_notes
        row.resolved_at = resolved_at or datetime.now(UTC)
        await session.flush()
        return row


async def reconcile_persisted_data(
    engine: AsyncEngine,
    *,
    release_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Re-run persisted source and market checks without fetching a provider.

    This is the operation used by both the API/CLI and the overnight scheduler.
    It is intentionally non-destructive: authoritative and comparison artifacts
    remain separate and richer ingestion-time market checks are merged above.
    """

    factory = _factory(engine)
    async with factory() as session:
        if release_id is not None and await session.get(MacroRelease, release_id) is None:
            raise LookupError("macro release not found")
        comparison_rows = (
            await session.scalars(
                select(DataReconciliationRecord).where(
                    DataReconciliationRecord.reconciliation_type == "official_vs_secondary",
                    DataReconciliationRecord.status != "resolved",
                )
            )
        ).all()
        manifest_query = select(MarketDataManifest)
        if release_id is not None:
            manifest_query = manifest_query.where(MarketDataManifest.macro_release_id == release_id)
        manifests = (await session.scalars(manifest_query)).all()
        allowed_value_ids: set[str] | None = None
        if release_id is not None:
            allowed_value_ids = {
                str(item.id)
                for item in (
                    await session.scalars(
                        select(ReleaseValue).where(ReleaseValue.macro_release_id == release_id)
                    )
                ).all()
                if not item.metadata_json.get("superseded")
            }

    source_comparisons = 0
    for row in comparison_rows:
        if (
            release_id is not None
            and row.subject_id != str(release_id)
            and allowed_value_ids is not None
            and row.subject_id not in allowed_value_ids
        ):
            continue
        tolerance = Decimal(str(row.difference_json.get("tolerance", "0")))
        await reconcile_values(
            engine,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            field_name=row.field_name or "value",
            authoritative_provider_key=row.authoritative_provider_key,
            comparison_provider_key=row.comparison_provider_key,
            authoritative_value=row.authoritative_value_json.get("value"),
            comparison_value=row.comparison_value_json.get("value"),
            unit=str(row.authoritative_value_json.get("unit") or "unknown"),
            tolerance=tolerance,
            authoritative_artifact_id=row.authoritative_artifact_id,
            comparison_artifact_id=row.comparison_artifact_id,
            sync_job_run_id=row.sync_job_run_id,
            data_mode=cast(Literal["observed", "fixture"], row.data_mode),
        )
        source_comparisons += 1

    market_checks = 0
    for manifest in manifests:
        conditions = [
            MarketBar.instrument_id == manifest.instrument_id,
            MarketBar.provider_key == manifest.provider_key,
            MarketBar.data_mode == manifest.data_mode,
            MarketBar.interval_seconds == manifest.interval_seconds,
            MarketBar.timestamp >= manifest.start_at,
            MarketBar.timestamp <= manifest.end_at,
        ]
        if manifest.futures_contract_id is not None:
            conditions.append(MarketBar.futures_contract_id == manifest.futures_contract_id)
        async with factory() as session:
            stored_rows = int(
                await session.scalar(select(func.count(MarketBar.id)).where(*conditions)) or 0
            )
        checks: dict[str, bool | int | float | str | None] = {
            "window_valid": manifest.start_at < manifest.end_at,
            "interval_positive": manifest.interval_seconds > 0,
            "bars_present": stored_rows > 0,
            "stored_rows_cover_manifest": stored_rows >= manifest.row_count,
            "source_artifact_linked": manifest.source_artifact_id is not None,
            "stored_rows": stored_rows,
            "manifest_rows": manifest.row_count,
        }
        await record_market_reconciliation(
            engine,
            subject_id=str(manifest.id),
            provider_key=manifest.provider_key,
            checks=checks,
            source_artifact_id=manifest.source_artifact_id,
            sync_job_run_id=manifest.sync_job_run_id,
            data_mode=cast(Literal["observed", "fixture"], manifest.data_mode),
        )
        market_checks += 1
    total = source_comparisons + market_checks
    return {
        "status": "completed" if total else "blocked",
        "release_id": str(release_id) if release_id else None,
        "source_comparisons": source_comparisons,
        "market_integrity_checks": market_checks,
        "reason": None if total else "No persisted comparison or market manifest is available.",
    }


__all__ = [
    "make_reconciliation_key",
    "reconcile_persisted_data",
    "reconcile_values",
    "record_market_reconciliation",
    "resolve_reconciliation",
]
