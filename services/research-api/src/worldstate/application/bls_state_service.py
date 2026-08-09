"""Persist current BLS observations for the live World State.

The BLS public API is a current-observation endpoint, not an ALFRED vintage
store.  This service deliberately writes a separate provider-owned series
family and marks every observation as non-PIT.  Release analysis continues to
use ``sync_bls_actuals`` and verified release timestamps; these rows are only
for current state, freshness and daily brief context.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

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

BlsFamily = Literal["US_CPI", "US_NFP"]


_KEY_MAP = {
    "US_CPI.HEADLINE.MOM": (
        "USA.INFLATION.BLS_CPI_HEADLINE_MOM",
        "BLS CPI headline monthly change",
        "inflation",
        "percent",
        "percent_change",
    ),
    "US_CPI.HEADLINE.YOY": (
        "USA.INFLATION.BLS_CPI_HEADLINE_YOY",
        "BLS CPI headline annual change",
        "inflation",
        "percent",
        "percent_change",
    ),
    "US_CPI.CORE.MOM": (
        "USA.INFLATION.BLS_CPI_CORE_MOM",
        "BLS core CPI monthly change",
        "inflation",
        "percent",
        "percent_change",
    ),
    "US_CPI.CORE.YOY": (
        "USA.INFLATION.BLS_CPI_CORE_YOY",
        "BLS core CPI annual change",
        "inflation",
        "percent",
        "percent_change",
    ),
    "US_NFP.NONFARM_PAYROLLS": (
        "USA.GROWTH.BLS_NONFARM_PAYROLLS",
        "BLS nonfarm payroll change",
        "growth",
        "thousand_persons",
        "level",
    ),
    "US_NFP.UNEMPLOYMENT_RATE": (
        "USA.GROWTH.BLS_UNEMPLOYMENT_RATE",
        "BLS unemployment rate",
        "growth",
        "percent",
        "level",
    ),
    "US_NFP.AVERAGE_HOURLY_EARNINGS.MOM": (
        "USA.GROWTH.BLS_AVERAGE_HOURLY_EARNINGS_MOM",
        "BLS average hourly earnings monthly change",
        "growth",
        "percent",
        "percent_change",
    ),
    "US_NFP.AVERAGE_HOURLY_EARNINGS.YOY": (
        "USA.GROWTH.BLS_AVERAGE_HOURLY_EARNINGS_YOY",
        "BLS average hourly earnings annual change",
        "growth",
        "percent",
        "percent_change",
    ),
    "US_NFP.LABOR_FORCE_PARTICIPATION": (
        "USA.GROWTH.BLS_LABOR_FORCE_PARTICIPATION",
        "BLS labor force participation rate",
        "growth",
        "percent",
        "level",
    ),
}


def _factory(engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def sync_bls_current_state(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    families: tuple[BlsFamily, ...] = ("US_CPI", "US_NFP"),
) -> dict[str, object]:
    """Fetch and upsert a bounded current BLS history for live state."""

    today = date.today()
    end = end_date or today
    start = start_date or (end - timedelta(days=365 * 5))
    if end < start:
        raise ValueError("end_date must not be before start_date")
    clients = build_provider_clients(settings)
    run = await record_provider_run(
        engine,
        provider_key=clients.bls.key,
        operation="sync_current_state",
        idempotency_key=f"bls-current-state:{start}:{end}:{','.join(families)}:{today}",
        input_data={
            "start_date": start,
            "end_date": end,
            "families": list(families),
            "point_in_time": False,
        },
        terms_url=clients.bls.terms.terms_url,
    )
    read = written = requests = 0
    warnings: list[str] = []
    primary_artifact_id: uuid.UUID | None = None
    try:
        async with _factory(engine)() as session, session.begin():
            provider = await session.scalar(select(Provider).where(Provider.key == clients.bls.key))
            if provider is None:
                provider = Provider(
                    key=clients.bls.key,
                    name="U.S. Bureau of Labor Statistics",
                    base_url=clients.bls.endpoint,
                    enabled=True,
                    requires_credentials=False,
                    terms_url=clients.bls.terms.terms_url,
                )
                session.add(provider)
            entity = await session.scalar(
                select(EconomicEntity).where(EconomicEntity.iso3 == "USA")
            )
            if entity is None:
                entity = EconomicEntity(
                    iso2="US",
                    iso3="USA",
                    name="United States",
                    entity_type="country",
                    currency="USD",
                    timezone="America/New_York",
                    metadata_json={"source": clients.bls.key},
                )
                session.add(entity)
            await session.flush()

        for family in families:
            batch = await clients.bls.fetch_bundle(
                family,
                start_year=start.year - 1,
                end_year=end.year,
            )
            requests += len(batch.artifacts)
            read += len(batch.observations)
            warnings.extend(batch.warnings)
            for provider_artifact in batch.artifacts:
                stored = await persist_provider_artifact(
                    engine,
                    provider_artifact,
                    provider_run_id=run.id,
                    title=f"BLS {family} current state response",
                )
                primary_artifact_id = primary_artifact_id or stored.id
            await persist_quality_record(
                engine,
                batch.quality,
                subject_type="macro_series_current",
                subject_id=family,
                identity=f"quality:bls-current:{family}:{batch.idempotency_key}",
            )
            async with _factory(engine)() as session, session.begin():
                provider = await session.scalar(
                    select(Provider).where(Provider.key == clients.bls.key)
                )
                entity = await session.scalar(
                    select(EconomicEntity).where(EconomicEntity.iso3 == "USA")
                )
                if provider is None or entity is None:
                    raise RuntimeError("BLS provider/entity setup failed")
                for observation in batch.observations:
                    mapped = _KEY_MAP.get(observation.canonical_key)
                    period = observation.reference_period_start
                    if mapped is None or observation.value is None or not (start <= period <= end):
                        continue
                    canonical_key, title, dimension, unit, transform = mapped
                    series = await session.scalar(
                        select(Series).where(Series.canonical_key == canonical_key)
                    )
                    if series is None:
                        series = Series(
                            id=uuid.uuid4(),
                            provider_id=provider.id,
                            native_id=observation.provider_series_id,
                            canonical_key=canonical_key,
                            entity_id=entity.id,
                            title=title,
                            description="Current BLS API capture; not a historical PIT vintage.",
                            frequency="monthly",
                            unit=unit,
                            seasonal_adjustment=None,
                            observation_type="official_current_series",
                            source_url=clients.bls.endpoint,
                            release_key=None,
                            availability_method="ingestion_time_proxy",
                            availability_precision="timestamp",
                            default_transform=transform,
                            active=True,
                            metadata_json={
                                "state_dimensions": [dimension],
                                "orientation": 1,
                                "weight": 1.0,
                                "minimum_history": 3,
                                "source_mode": "observed",
                                "point_in_time": False,
                                "current_observation_only": True,
                                "provider_series_id": observation.provider_series_id,
                            },
                        )
                        session.add(series)
                        await session.flush()
                    else:
                        series.metadata_json = {
                            **series.metadata_json,
                            "point_in_time": False,
                            "current_observation_only": True,
                        }
                    existing = await session.scalar(
                        select(Observation).where(
                            Observation.series_id == series.id,
                            Observation.period_start == period,
                            Observation.vintage_date == observation.vintage_date,
                            Observation.data_mode == "observed",
                        )
                    )
                    if existing is not None:
                        continue
                    quality_flags = ["current_bls_capture", "not_point_in_time"]
                    if (
                        observation.metadata.get("calculation_source")
                        == "worldstate_from_official_levels"
                    ):
                        quality_flags.append("derived_from_official_levels")
                    session.add(
                        Observation(
                            series_id=series.id,
                            period_start=period,
                            period_end=observation.reference_period_end,
                            value=observation.value,
                            raw_value=observation.raw_value,
                            vintage_date=observation.vintage_date,
                            realtime_start=None,
                            realtime_end=None,
                            available_at=observation.available_at,
                            availability_method="ingestion_time_proxy",
                            availability_precision="timestamp",
                            fetched_at=observation.retrieved_at,
                            is_preliminary=not observation.is_first_release,
                            is_revised=observation.is_revision,
                            data_mode="observed",
                            quality_flags=quality_flags,
                            source_hash=observation.artifact_hash,
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
            output_data={
                "families": list(families),
                "point_in_time": False,
                "current_capture": True,
                "series_written": sorted({item[0] for item in _KEY_MAP.values()}),
            },
        )
        return {
            "status": "completed",
            "provider": clients.bls.key,
            "records_read": read,
            "records_written": written,
            "warnings": warnings,
            "point_in_time": False,
            "current_capture": True,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


__all__ = ["sync_bls_current_state"]
