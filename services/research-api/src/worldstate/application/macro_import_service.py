"""Traceable manual import for official macro-series exports.

This is deliberately a file-import boundary, not a scraper or a synthetic
provider.  It is useful for official Japan/China exports while their public
endpoints are not yet stable enough for an automated adapter.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import (
    complete_provider_run,
    fail_provider_run,
    record_provider_run,
    record_source_artifact,
)
from worldstate.application.provider_runtime import persist_quality_record
from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.db.models import EconomicEntity, Observation, Provider, Series


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _parse_date(value: str, *, field: str, row_number: int) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise ValueError(f"row {row_number}: {field} must be YYYY-MM-DD") from exc


def _parse_datetime(value: str, *, field: str, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"row {row_number}: {field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"row {row_number}: {field} must include an explicit timezone")
    return parsed.astimezone(UTC)


async def import_official_macro_csv(
    engine: AsyncEngine,
    *,
    csv_text: str,
    provider_key: str,
    source_name: str,
    source_url: str,
    verified: bool,
    verification_notes: str | None,
) -> dict[str, object]:
    """Import observed official export rows with explicit provenance.

    Required columns: ``canonical_key``, ``period_start`` and ``value``.
    Optional columns provide ``native_id``, ``title``, ``entity_iso3``,
    ``frequency``, ``unit``, ``period_end``, ``vintage_date`` and
    ``available_at``.  Omitting vintage/availability is intentionally marked
    as an ingestion-time proxy and is not point-in-time history.
    """

    if not source_url.strip():
        raise ValueError("source_url is required so imported data remains traceable")
    content = csv_text.encode("utf-8")
    content_hash = hashlib.sha256(content).hexdigest()
    idempotency_key = f"official-macro-csv:{provider_key}:{content_hash}"
    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = set(reader.fieldnames or [])
    run = await record_provider_run(
        engine,
        provider_key=provider_key,
        operation="import_official_macro_csv",
        idempotency_key=idempotency_key,
        input_data={
            "source_name": source_name,
            "source_url": source_url,
            "content_hash": content_hash,
            "verified": verified,
            "point_in_time": "vintage_date" in fieldnames and "available_at" in fieldnames,
        },
        terms_url=source_url,
    )
    if run.status == "completed":
        return {**run.output_json, "idempotent_replay": True}

    acquired_at = datetime.now(UTC)
    required = {"canonical_key", "period_start", "value"}
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        error = ValueError(f"CSV is missing required columns: {', '.join(missing)}")
        await fail_provider_run(engine, run.id, error=error)
        raise error
    rows = list(reader)
    if not rows:
        error = ValueError("CSV contains no data rows")
        await fail_provider_run(engine, run.id, error=error)
        raise error

    point_in_time = all(
        str(row.get("vintage_date") or "").strip()
        and str(row.get("available_at") or "").strip()
        for row in rows
    )
    artifact = await record_source_artifact(
        engine,
        source_key=f"{provider_key}:{content_hash}",
        provider_key=provider_key,
        artifact_type="official_macro_csv",
        title=source_name,
        source_url=source_url,
        content=content,
        content_type="text/csv",
        retrieved_at=acquired_at,
        citation_text=f"{source_name}: {source_url}",
        data_mode="observed",
        provider_run_id=run.id,
        metadata={
            "manual_import": True,
            "verified": verified,
            "point_in_time": point_in_time,
            "source_content_hash": content_hash,
        },
    )
    grade = QualityGrade.B if verified else QualityGrade.C
    series_keys = sorted(
        {
            str(row.get("canonical_key") or "").strip()
            for row in rows
            if str(row.get("canonical_key") or "").strip()
        }
    )
    for canonical_key in series_keys:
        quality = DataQuality(
            source_name=source_name,
            source_url=source_url,
            source_type="manual_official_csv",
            acquired_at=acquired_at,
            is_manual=True,
            is_verified=verified,
            quality_grade=grade,
            verification_notes=verification_notes or "Imported from an official export file.",
            metadata={
                "source_content_hash": content_hash,
                "point_in_time": point_in_time,
                "manual_import": True,
            },
        )
        await persist_quality_record(
            engine,
            quality,
            subject_type="macro_series",
            subject_id=canonical_key,
            identity=f"official-csv:{content_hash}:{canonical_key}",
        )
    written = 0
    warnings: list[str] = []
    try:
        async with _factory(engine)() as session, session.begin():
            provider = await session.scalar(select(Provider).where(Provider.key == provider_key))
            if provider is None:
                provider = Provider(
                    key=provider_key,
                    name=source_name,
                    base_url=source_url,
                    enabled=True,
                    requires_credentials=False,
                    terms_url=source_url,
                )
                session.add(provider)
                await session.flush()

            series_by_key: dict[str, Series] = {}
            for row_number, row in enumerate(rows, start=2):
                canonical_key = str(row.get("canonical_key") or "").strip()
                if not canonical_key:
                    warnings.append(f"row {row_number}: canonical_key is required")
                    continue
                try:
                    period_start = _parse_date(
                        str(row.get("period_start") or ""),
                        field="period_start",
                        row_number=row_number,
                    )
                    raw_value = str(row.get("value") or "").strip()
                    value = Decimal(raw_value)
                except (ValueError, InvalidOperation) as exc:
                    warnings.append(
                        str(exc)
                        if isinstance(exc, ValueError)
                        else f"row {row_number}: value is invalid"
                    )
                    continue
                period_end = _parse_date(
                    str(row.get("period_end") or row.get("period_start") or ""),
                    field="period_end",
                    row_number=row_number,
                )
                entity_iso3 = str(row.get("entity_iso3") or "").strip().upper()
                if not entity_iso3:
                    warnings.append(f"row {row_number}: entity_iso3 is required")
                    continue
                title = str(row.get("title") or canonical_key).strip()
                frequency = str(row.get("frequency") or "unknown").strip()
                unit = str(row.get("unit") or "unknown").strip()
                entity = await session.scalar(
                    select(EconomicEntity).where(EconomicEntity.iso3 == entity_iso3)
                )
                if entity is None:
                    entity = EconomicEntity(
                        iso3=entity_iso3,
                        name=entity_iso3,
                        entity_type="economic_area" if entity_iso3 == "EA19" else "country",
                        metadata_json={"source": provider_key, "manual_import": True},
                    )
                    session.add(entity)
                    await session.flush()
                series = series_by_key.get(canonical_key)
                if series is None:
                    series = await session.scalar(
                        select(Series).where(Series.canonical_key == canonical_key)
                    )
                    if series is not None and series.provider_id != provider.id:
                        raise ValueError(
                            f"row {row_number}: canonical_key already belongs to another provider"
                        )
                    if series is None:
                        series = Series(
                            id=uuid.uuid4(),
                            provider_id=provider.id,
                            native_id=str(row.get("native_id") or canonical_key),
                            canonical_key=canonical_key,
                            entity_id=entity.id,
                            title=title,
                            description=None,
                            frequency=frequency,
                            unit=unit,
                            seasonal_adjustment=None,
                            observation_type="official_series",
                            source_url=source_url,
                            release_key=None,
                            availability_method=(
                                "official_update_date"
                                if point_in_time
                                else "ingestion_time_proxy"
                            ),
                            availability_precision="timestamp" if point_in_time else "day",
                            default_transform="level",
                            active=True,
                            metadata_json={
                                "source_mode": "manual_official_csv",
                                "point_in_time": point_in_time,
                                "manual_import": True,
                                "provider_series_id": str(row.get("native_id") or canonical_key),
                            },
                        )
                        session.add(series)
                        await session.flush()
                    series_by_key[canonical_key] = series
                vintage = (
                    _parse_date(
                        str(row["vintage_date"]),
                        field="vintage_date",
                        row_number=row_number,
                    )
                    if str(row.get("vintage_date") or "").strip()
                    else acquired_at.date()
                )
                available_at = (
                    _parse_datetime(
                        str(row["available_at"]),
                        field="available_at",
                        row_number=row_number,
                    )
                    if str(row.get("available_at") or "").strip()
                    else acquired_at
                )
                existing = await session.scalar(
                    select(Observation).where(
                        Observation.series_id == series.id,
                        Observation.period_start == period_start,
                        Observation.vintage_date == vintage,
                        Observation.data_mode == "observed",
                    )
                )
                if existing is not None:
                    continue
                row_hash = hashlib.sha256(
                    f"{canonical_key}|{period_start}|{vintage}|{raw_value}|{content_hash}".encode()
                ).hexdigest()
                session.add(
                    Observation(
                        series_id=series.id,
                        period_start=period_start,
                        period_end=period_end,
                        value=value,
                        raw_value=raw_value,
                        vintage_date=vintage,
                        realtime_start=None,
                        realtime_end=None,
                        available_at=available_at,
                        availability_method=(
                            "official_update_date"
                            if point_in_time
                            else "ingestion_time_proxy"
                        ),
                        availability_precision="timestamp" if point_in_time else "day",
                        fetched_at=acquired_at,
                        is_preliminary=str(row.get("is_preliminary") or "").lower() == "true",
                        is_revised=str(row.get("is_revised") or "").lower() == "true",
                        data_mode="observed",
                        quality_flags=[
                            "manual_official_csv",
                            "point_in_time" if point_in_time else "not_point_in_time",
                        ],
                        source_hash=row_hash,
                    )
                )
                written += 1
        output = {
            "status": "completed",
            "provider": provider_key,
            "inserted": written,
            "records_read": len(rows),
            "series": sorted(series_by_key),
            "warnings": warnings,
            "quality_grade": grade.value,
            "data_mode": "observed",
            "manual": True,
            "point_in_time": point_in_time,
            "source_artifact_id": str(artifact.id),
            "idempotent_replay": False,
        }
        await complete_provider_run(
            engine,
            run.id,
            records_read=len(rows),
            records_written=written,
            request_count=0,
            source_artifact_id=artifact.id,
            quality_grade=grade.value,
            warnings=warnings,
            output_data=output,
        )
        return output
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


__all__ = ["import_official_macro_csv"]
