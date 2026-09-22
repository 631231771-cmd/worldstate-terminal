"""Persist official evidence in the existing observation/artifact/run infrastructure."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.data_foundation_service import (
    complete_provider_run,
    fail_provider_run,
    record_provider_run,
    record_source_artifact,
)
from worldstate.application.provider_runtime import persist_quality_record
from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.db.models import EconomicEntity, Observation, Provider, ProviderRun, Series
from worldstate.provider_kit.official_evidence import (
    EvidencePoint,
    export_urls,
    fetch_export,
    parse_export,
)

LIMITATION = (
    "Current-version official export; historical first-print vintages unavailable. "
    "Available only from actual acquisition."
)


async def persist_export(
    engine: AsyncEngine,
    *,
    dataset: str,
    provider_key: str,
    url: str,
    content: bytes,
    content_type: str,
    retrieved_at: datetime,
    points: list[EvidencePoint],
    run_id: uuid.UUID,
) -> dict[str, Any]:
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")
    retrieved_at = retrieved_at.astimezone(UTC)
    if not points or any(p.period > retrieved_at.date() for p in points):
        raise ValueError("empty or future-dated official export")
    artifact = await record_source_artifact(
        engine,
        source_key=dataset,
        provider_key=provider_key,
        artifact_type="official_evidence_export",
        title=dataset,
        source_url=url,
        content=content,
        content_type=content_type,
        retrieved_at=retrieved_at,
        provider_run_id=run_id,
        metadata={
            "dataset": dataset,
            "official_source": True,
            "manual": False,
            "point_in_time": False,
            "limitation": LIMITATION,
            "parser_version": "1.0.0",
        },
    )
    inserted = 0
    conflicts = 0
    async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
        provider = await session.scalar(select(Provider).where(Provider.key == provider_key))
        if provider is None:
            provider = Provider(
                key=provider_key,
                name=provider_key,
                base_url=url,
                enabled=True,
                requires_credentials=False,
                terms_url=url,
            )
            session.add(provider)
            await session.flush()
        entity = await session.scalar(select(EconomicEntity).where(EconomicEntity.iso3 == "USA"))
        if entity is None:
            entity = EconomicEntity(iso3="USA", name="United States", entity_type="country")
            session.add(entity)
            await session.flush()
        series_map: dict[str, Series] = {}
        for point in points:
            series = series_map.get(point.key)
            if series is None:
                series = await session.scalar(
                    select(Series).where(Series.canonical_key == point.key)
                )
                if series is None:
                    series = Series(
                        provider_id=provider.id,
                        native_id=point.key,
                        canonical_key=point.key,
                        entity_id=entity.id,
                        title=point.title,
                        frequency=point.frequency,
                        unit=point.unit,
                        observation_type="official_evidence",
                        source_url=url,
                        availability_method="ingestion_time_proxy",
                        availability_precision="timestamp",
                        default_transform="level",
                        active=True,
                        metadata_json={
                            "point_in_time": False,
                            "current_version": True,
                            "official_source": True,
                            "manual": False,
                            "is_proxy": point.key == "eia.products_supplied",
                            "dataset": dataset,
                            "limitation": LIMITATION,
                        },
                    )
                    session.add(series)
                    await session.flush()
                if series.provider_id != provider.id or series.unit != point.unit:
                    raise ValueError(f"provider/unit collision: {point.key}")
                series_map[point.key] = series
            existing = await session.scalar(
                select(Observation).where(
                    Observation.series_id == series.id,
                    Observation.period_start == point.period,
                    Observation.vintage_date == retrieved_at.date(),
                    Observation.data_mode == "observed",
                )
            )
            if existing is not None:
                # Existing daily-vintage model cannot preserve intraday revisions. Never overwrite.
                conflicts += int(existing.value != point.value)
                continue
            session.add(
                Observation(
                    series_id=series.id,
                    period_start=point.period,
                    period_end=point.period,
                    value=point.value,
                    raw_value=str(point.value),
                    vintage_date=retrieved_at.date(),
                    available_at=retrieved_at,
                    fetched_at=retrieved_at,
                    availability_method="ingestion_time_proxy",
                    availability_precision="timestamp",
                    data_mode="observed",
                    is_preliminary=provider_key == "eia_official",
                    is_revised=False,
                    quality_flags=[
                        "official_source",
                        "current_version",
                        "not_point_in_time",
                        f"artifact:{artifact.id}",
                        f"artifact_hash:{artifact.content_hash}",
                    ],
                    source_hash=hashlib.sha256(
                        f"{artifact.content_hash}|{point.key}|{point.period}|{point.value}".encode()
                    ).hexdigest(),
                )
            )
            inserted += 1
    for key in series_map:
        await persist_quality_record(
            engine,
            DataQuality(
                source_name=provider_key,
                source_url=url,
                source_type="official_export",
                acquired_at=retrieved_at,
                is_manual=False,
                is_verified=False,
                is_proxy=key == "eia.products_supplied",
                quality_grade=QualityGrade.B,
                verification_notes="Official parser; not independently human verified.",
                metadata={
                    "artifact_id": str(artifact.id),
                    "point_in_time": False,
                    "limitation": LIMITATION,
                },
            ),
            subject_type="macro_series",
            subject_id=key,
            identity=f"evidence:{artifact.id}:{key}",
        )
    return {
        "dataset": dataset,
        "inserted": inserted,
        "records_read": len(points),
        "series": sorted(series_map),
        "source_artifact_id": str(artifact.id),
        "same_day_revision_conflicts": conflicts,
        "point_in_time": False,
        "latest_period": max(p.period for p in points).isoformat(),
    }


async def sync_official_evidence(engine: AsyncEngine) -> dict[str, Any]:
    """Bounded seven-export sync, six-hour persistent cache, independent failures."""
    results: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    for dataset, (provider, url) in export_urls(now.year).items():
        async with async_sessionmaker(engine)() as session:
            previous = await session.scalar(
                select(ProviderRun)
                .where(
                    ProviderRun.provider_key == provider,
                    ProviderRun.operation == dataset,
                    ProviderRun.started_at >= now - timedelta(hours=6),
                    ProviderRun.data_mode == "observed",
                )
                .order_by(ProviderRun.started_at.desc())
                .limit(1)
            )
            if previous:
                results.append(
                    {
                        "dataset": dataset,
                        "status": previous.status,
                        "cached": True,
                        **previous.output_json,
                    }
                )
                continue
        run = await record_provider_run(
            engine,
            provider_key=provider,
            operation=dataset,
            idempotency_key=f"{dataset}:{now.isoformat()}",
            input_data={"source_url": url, "point_in_time": False},
        )
        try:
            response = await fetch_export(provider, url)
            captured = datetime.now(UTC)
            points = parse_export(dataset, response.content)
            output = await persist_export(
                engine,
                dataset=dataset,
                provider_key=provider,
                url=url,
                content=response.content,
                content_type=response.headers.get("content-type", ""),
                retrieved_at=captured,
                points=points,
                run_id=run.id,
            )
            status: Literal["partial", "completed"] = (
                "partial" if output["same_day_revision_conflicts"] else "completed"
            )
            await complete_provider_run(
                engine,
                run.id,
                records_read=len(points),
                records_written=output["inserted"],
                request_count=1,
                output_data=output,
                quality_grade="B",
                status=status,
                source_artifact_id=uuid.UUID(output["source_artifact_id"]),
                warnings=[LIMITATION]
                + (
                    ["Same-day revisions retained in raw artifact only."]
                    if status == "partial"
                    else []
                ),
            )
            results.append({"status": status, **output})
        except Exception as exc:
            await fail_provider_run(engine, run.id, error=exc)
            results.append({"dataset": dataset, "status": "failed", "error": type(exc).__name__})
    return {"items": results, "data_mode": "observed", "point_in_time": False}
