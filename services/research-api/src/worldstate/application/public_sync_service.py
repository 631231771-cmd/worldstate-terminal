"""Persistence orchestration for no-key official public macro providers."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import (
    complete_provider_run,
    fail_provider_run,
    record_provider_run,
)
from worldstate.application.provider_runtime import (
    build_provider_clients,
    persist_provider_artifact,
    persist_quality_record,
)
from worldstate.config import Settings
from worldstate.db.models import EconomicEntity, Observation, Provider, Series
from worldstate.provider_kit import OfficialPublicCsvProvider


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _dimensions(canonical_key: str) -> list[str]:
    parts = canonical_key.split(".")
    if len(parts) < 2:
        return []
    mapping = {
        "GROWTH": "growth",
        "INFLATION": "inflation",
        "POLICY": "policy_tightness",
        "LIQUIDITY": "liquidity",
        "CREDIT": "credit",
        "RISK": "risk",
        "FISCAL": "fiscal",
        "EXTERNAL": "external",
    }
    dimension = mapping.get(parts[1])
    return [dimension] if dimension else []


def _orientation(canonical_key: str) -> int:
    # A higher inflation/risk-spread/unemployment value is adverse for the
    # corresponding state.  The rule is metadata only; it is never causality.
    key = canonical_key.upper()
    return -1 if any(token in key for token in ("UNEMPLOYMENT", "SPREAD", "STRESS")) else 1


async def _ensure_provider_entity(
    session: AsyncSession,
    provider_client: OfficialPublicCsvProvider,
    *,
    entity_code: str,
) -> tuple[Provider, EconomicEntity]:
    provider = await session.scalar(select(Provider).where(Provider.key == provider_client.key))
    if provider is None:
        provider = Provider(
            key=provider_client.key,
            name=provider_client.name,
            base_url=provider_client.base_url,
            enabled=True,
            requires_credentials=False,
            terms_url=provider_client.terms.terms_url,
        )
        session.add(provider)
        await session.flush()
    entity = await session.scalar(
        select(EconomicEntity).where(EconomicEntity.iso3 == entity_code)
    )
    if entity is None:
        entity = EconomicEntity(
            iso2={"EA19": "EA", "GBR": "GB", "JPN": "JP", "CHN": "CN"}.get(entity_code),
            iso3=entity_code,
            name={
                "EA19": "Euro Area",
                "GBR": "United Kingdom",
                "JPN": "Japan",
                "CHN": "China",
            }.get(entity_code, entity_code),
            entity_type="economic_area" if entity_code == "EA19" else "country",
            currency={"EA19": "EUR", "GBR": "GBP", "JPN": "JPY", "CHN": "CNY"}.get(entity_code),
            timezone={
                "EA19": "Europe/Brussels",
                "GBR": "Europe/London",
                "JPN": "Asia/Tokyo",
                "CHN": "Asia/Shanghai",
            }.get(entity_code),
            metadata_json={"source": provider_client.key},
        )
        session.add(entity)
        await session.flush()
    return provider, entity


async def sync_public_provider(
    engine: AsyncEngine,
    settings: Settings,
    *,
    provider_name: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    clients = build_provider_clients(settings)
    provider_client = getattr(clients, provider_name, None)
    if not isinstance(provider_client, OfficialPublicCsvProvider):
        raise ValueError(f"unsupported public provider: {provider_name}")
    run = await record_provider_run(
        engine,
        provider_key=provider_client.key,
        operation="sync_public_macro",
        idempotency_key=f"{provider_client.key}:{start_date}:{end_date}",
        input_data={"start_date": start_date, "end_date": end_date},
        terms_url=provider_client.terms.terms_url,
    )
    read = written = requests = 0
    warnings: list[str] = []
    primary_artifact_id: uuid.UUID | None = None
    try:
        if not provider_client.series:
            await complete_provider_run(
                engine,
                run.id,
                records_read=0,
                records_written=0,
                request_count=0,
                quality_grade="C",
                warnings=[
                    "provider has no configured series; use an official export URL or "
                    "catalog mapping"
                ],
            )
            return {
                "status": "blocked",
                "provider": provider_client.key,
                "reason": "no series configured",
            }
        for spec in provider_client.series.values():
            batch = await provider_client.fetch_observation_batch(
                spec.native_id, start=start_date, end=end_date
            )
            requests += 1
            read += len(batch.observations)
            artifact = await persist_provider_artifact(
                engine,
                batch.artifacts[0],
                provider_run_id=run.id,
                title=f"{provider_client.name} {spec.native_id} observations",
            )
            primary_artifact_id = primary_artifact_id or artifact.id
            await persist_quality_record(
                engine,
                batch.quality,
                subject_type="macro_series",
                subject_id=spec.canonical_key,
                identity=f"quality:{provider_client.key}:{spec.native_id}:{artifact.content_hash}",
            )
            async with _factory(engine)() as session, session.begin():
                provider, entity = await _ensure_provider_entity(
                    session, provider_client, entity_code=spec.entity
                )
                series = await session.scalar(
                    select(Series).where(Series.canonical_key == spec.canonical_key)
                )
                metadata = {
                    "state_dimensions": _dimensions(spec.canonical_key),
                    "orientation": _orientation(spec.canonical_key),
                    "weight": 1.0,
                    "minimum_history": 3,
                    "freshness_half_life_days": 30.0,
                    "source_mode": "observed",
                    "provider_series_id": spec.native_id,
                    "point_in_time": False,
                }
                if series is None:
                    series = Series(
                        id=uuid.uuid4(),
                        provider_id=provider.id,
                        native_id=spec.native_id,
                        canonical_key=spec.canonical_key,
                        entity_id=entity.id,
                        title=spec.title,
                        description=None,
                        frequency=spec.frequency,
                        unit=spec.unit,
                        seasonal_adjustment=None,
                        observation_type="official_series",
                        source_url=spec.source_url,
                        release_key=None,
                        availability_method="official_update_date",
                        availability_precision="timestamp",
                        default_transform="level",
                        active=True,
                        metadata_json=metadata,
                    )
                    session.add(series)
                    await session.flush()
                else:
                    series.metadata_json = {**series.metadata_json, **metadata}
                for observation in batch.observations:
                    existing = await session.scalar(
                        select(Observation).where(
                            Observation.series_id == series.id,
                            Observation.period_start == observation.period_start,
                            Observation.vintage_date == observation.vintage_date,
                            Observation.data_mode == "observed",
                        )
                    )
                    if existing is not None:
                        continue
                    session.add(
                        Observation(
                            series_id=series.id,
                            period_start=observation.period_start,
                            period_end=observation.period_end,
                            value=observation.value,
                            raw_value=observation.raw_value,
                            vintage_date=observation.vintage_date,
                            realtime_start=None,
                            realtime_end=None,
                            available_at=observation.available_at,
                            availability_method=observation.availability_method.value,
                            availability_precision=observation.availability_precision.value,
                            fetched_at=observation.fetched_at,
                            is_preliminary=observation.is_preliminary,
                            is_revised=observation.is_revised,
                            data_mode="observed",
                            quality_flags=observation.quality_flags,
                            source_hash=observation.source_hash,
                        )
                    )
                    written += 1
        await complete_provider_run(
            engine,
            run.id,
            records_read=read,
            records_written=written,
            request_count=requests,
            source_artifact_id=primary_artifact_id,
            quality_grade="B",
            warnings=warnings,
        )
        return {
            "status": "completed",
            "provider": provider_client.key,
            "records_read": read,
            "records_written": written,
            "warnings": warnings,
            "point_in_time": False,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


async def sync_public_providers(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    providers: tuple[str, ...] = ("ecb", "boe", "boj", "china"),
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    failures: dict[str, str] = {}
    for provider_name in providers:
        try:
            results[provider_name] = await sync_public_provider(
                engine,
                settings,
                provider_name=provider_name,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            failures[provider_name] = f"{type(exc).__name__}: {exc}"
    status = "completed" if not failures else ("partial" if results else "blocked")
    return {"status": status, "results": results, "failures": failures}


__all__ = ["sync_public_provider", "sync_public_providers"]
