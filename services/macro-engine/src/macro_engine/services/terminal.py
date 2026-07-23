"""Local-first ingestion, query, and explainable state computation."""

from __future__ import annotations

import calendar
import hashlib
import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import yaml
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from macro_engine.config import Settings
from macro_engine.db.models import (
    EconomicEntity,
    Observation,
    Provider,
    Release,
    Series,
    StateComponent,
    StateDefinition,
    SyncRun,
)
from macro_engine.domain.enums import AvailabilityMethod, AvailabilityPrecision
from macro_engine.domain.models import ObservationRecord
from macro_engine.ingestion.catalog import CatalogSeries, load_catalog
from macro_engine.providers.fred_alfred import FredAlfredProvider
from macro_engine.transforms.core import apply_transform, rolling_quantile

METHODOLOGY_VERSION = "wst-state-v1"
STATE_ORDER = [
    "growth",
    "inflation",
    "liquidity",
    "credit",
    "fiscal",
    "external",
    "policy_tightness",
    "risk",
]
EXPERIMENTAL_STATES = {"fiscal", "external"}


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def ensure_catalog(session: AsyncSession, settings: Settings) -> list[CatalogSeries]:
    """Upsert the YAML catalog and scoring component definitions."""

    catalog = load_catalog(settings.catalog_root)
    provider = await session.scalar(select(Provider).where(Provider.key == "fred_alfred"))
    if provider is None:
        provider = Provider(
            key="fred_alfred",
            name="Federal Reserve Economic Data / ALFRED",
            base_url=FredAlfredProvider.base_url,
            enabled=True,
            requires_credentials=True,
            terms_url="https://fred.stlouisfed.org/legal/",
        )
        session.add(provider)
        await session.flush()

    entity = await session.scalar(select(EconomicEntity).where(EconomicEntity.iso2 == "US"))
    if entity is None:
        entity = EconomicEntity(
            iso2="US",
            iso3="USA",
            name="United States",
            entity_type="country",
            currency="USD",
            timezone="America/New_York",
            metadata_json={"catalog_key": "US"},
        )
        session.add(entity)
        await session.flush()

    states_document = yaml.safe_load(
        (settings.catalog_root / "states.yaml").read_text(encoding="utf-8")
    )
    for definition in states_document["states"]:
        existing_state = await session.get(StateDefinition, definition["key"])
        if existing_state is None:
            session.add(
                StateDefinition(
                    key=definition["key"],
                    title=definition["title"],
                    meaning_of_positive=definition["meaning_of_positive"],
                    methodology_version=METHODOLOGY_VERSION,
                    config_json={
                        "experimental": definition["key"] in EXPERIMENTAL_STATES,
                    },
                )
            )
        else:
            existing_state.title = definition["title"]
            existing_state.meaning_of_positive = definition["meaning_of_positive"]
            existing_state.methodology_version = METHODOLOGY_VERSION

    await session.flush()
    for item in catalog:
        series = await session.scalar(
            select(Series).where(Series.canonical_key == item.canonical_key)
        )
        metadata = {
            "tags": item.tags,
            "state_dimensions": item.state_dimensions,
            "weight": item.weight,
            "freshness_half_life_days": item.freshness_half_life_days,
            "minimum_history": item.minimum_history,
        }
        if series is None:
            series = Series(
                id=uuid.uuid4(),
                provider_id=provider.id,
                native_id=item.native_id,
                canonical_key=item.canonical_key,
                entity_id=entity.id,
                title=item.title,
                frequency=item.frequency,
                unit=item.unit,
                observation_type="value",
                source_url=item.source_url,
                availability_method=item.availability.method.value,
                availability_precision=item.availability.precision.value,
                default_transform=item.transform,
                metadata_json=metadata,
            )
            session.add(series)
            await session.flush()
        else:
            source_mode = series.metadata_json.get("source_mode")
            series.title = item.title
            series.frequency = item.frequency
            series.unit = item.unit
            series.default_transform = item.transform
            series.metadata_json = {
                **metadata,
                **({"source_mode": source_mode} if source_mode else {}),
            }

        for state_key in item.state_dimensions:
            component = await session.get(
                StateComponent,
                {"state_key": state_key, "series_id": series.id},
            )
            if component is None:
                session.add(
                    StateComponent(
                        state_key=state_key,
                        series_id=series.id,
                        transform=item.transform,
                        orientation=item.orientation,
                        base_weight=item.weight,
                        freshness_half_life_days=item.freshness_half_life_days,
                        minimum_history=item.minimum_history,
                        enabled=True,
                    )
                )
            else:
                component.transform = item.transform
                component.orientation = item.orientation
                component.base_weight = item.weight
                component.freshness_half_life_days = item.freshness_half_life_days
                component.minimum_history = item.minimum_history
                component.enabled = True
    await session.flush()
    return catalog


def _shift_month(anchor: date, offset: int) -> date:
    month_index = anchor.year * 12 + anchor.month - 1 + offset
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def _demo_dates(frequency: str) -> list[date]:
    if frequency == "daily":
        anchor = date(2026, 6, 30)
        return [anchor - timedelta(days=(399 - index)) for index in range(400)]
    if frequency == "weekly":
        anchor = date(2026, 6, 26)
        return [anchor - timedelta(weeks=(155 - index)) for index in range(156)]
    if frequency == "quarterly":
        anchor = date(2026, 4, 1)
        return [_shift_month(anchor, (index - 31) * 3) for index in range(32)]
    if frequency == "annual":
        return [date(year, 1, 1) for year in range(1997, 2027)]
    anchor = date(2026, 6, 1)
    return [_shift_month(anchor, index - 83) for index in range(84)]


def _demo_value(item: CatalogSeries, index: int) -> float:
    seed = int(hashlib.sha256(item.native_id.encode()).hexdigest()[:8], 16)
    phase = (seed % 31) / 7
    wave = math.sin(index / 7 + phase) + 0.35 * math.cos(index / 19 + phase)
    unit = item.unit.lower()
    if "percent" in unit or item.native_id.startswith(("DGS", "DFII", "T5Y", "T10Y")):
        return max(-1.5, 3.2 + wave * 1.4 + (seed % 13) / 10)
    if item.native_id in {"VIXCLS", "STLFSI4", "NFCI"}:
        return 18 + wave * 6 if item.native_id == "VIXCLS" else wave * 0.8
    if "dollar" in unit or item.native_id in {"WALCL", "M2SL", "WTREGEN", "RRPONTSYD"}:
        return 1000 + index * (2 + seed % 5) + wave * 30
    return 80 + index * (0.18 + (seed % 7) / 100) + wave * 4


def demo_records(item: CatalogSeries) -> list[ObservationRecord]:
    """Return deterministic fixture observations, including a few explicit revisions."""

    records: list[ObservationRecord] = []
    dates = _demo_dates(item.frequency)
    now = datetime(2026, 7, 1, tzinfo=UTC)
    for index, period in enumerate(dates):
        value = _demo_value(item, index)
        vintage = min(period + timedelta(days=14), date(2026, 7, 1))
        payload = f"demo:{item.native_id}:{period}:{value:.6f}:initial"
        records.append(
            ObservationRecord(
                native_id=item.native_id,
                period_start=period,
                period_end=period,
                value=Decimal(f"{value:.6f}"),
                raw_value=f"{value:.6f}",
                vintage_date=vintage,
                realtime_start=vintage,
                realtime_end=date(9999, 12, 31),
                available_at=datetime.combine(vintage, datetime.min.time(), UTC),
                availability_method=AvailabilityMethod.PROVIDER_REALTIME_START,
                availability_precision=AvailabilityPrecision.DAY,
                fetched_at=now,
                source_hash=hashlib.sha256(payload.encode()).hexdigest(),
            )
        )
        if item.frequency in {"monthly", "quarterly"} and index >= len(dates) - 4:
            revised_value = value * (1 + ((index % 3) - 1) * 0.002)
            revised_vintage = min(vintage + timedelta(days=30), date(2026, 7, 1))
            revision_payload = f"demo:{item.native_id}:{period}:{revised_value:.6f}:revision"
            records.append(
                ObservationRecord(
                    native_id=item.native_id,
                    period_start=period,
                    period_end=period,
                    value=Decimal(f"{revised_value:.6f}"),
                    raw_value=f"{revised_value:.6f}",
                    vintage_date=revised_vintage,
                    realtime_start=revised_vintage,
                    realtime_end=date(9999, 12, 31),
                    available_at=datetime.combine(revised_vintage, datetime.min.time(), UTC),
                    availability_method=AvailabilityMethod.PROVIDER_REALTIME_START,
                    availability_precision=AvailabilityPrecision.DAY,
                    fetched_at=now,
                    is_revised=True,
                    source_hash=hashlib.sha256(revision_payload.encode()).hexdigest(),
                )
            )
    return records


async def persist_observations(
    session: AsyncSession,
    series: Series,
    records: Iterable[ObservationRecord],
) -> tuple[int, int, int]:
    """Idempotently store observations while preserving distinct vintage rows."""

    existing_rows = (
        await session.scalars(select(Observation).where(Observation.series_id == series.id))
    ).all()
    existing = {
        (row.period_start, row.vintage_date): (row.id, row.source_hash) for row in existing_rows
    }
    inserted = updated_count = skipped = 0
    for record in records:
        key = (record.period_start, record.vintage_date)
        current = existing.get(key)
        values = {
            "period_end": record.period_end,
            "value": record.value,
            "raw_value": record.raw_value,
            "realtime_start": record.realtime_start,
            "realtime_end": record.realtime_end,
            "available_at": record.available_at,
            "availability_method": record.availability_method.value,
            "availability_precision": record.availability_precision.value,
            "fetched_at": record.fetched_at,
            "is_preliminary": record.is_preliminary,
            "is_revised": record.is_revised,
            "quality_flags": record.quality_flags,
            "source_hash": record.source_hash,
        }
        if current is None:
            session.add(
                Observation(
                    series_id=series.id,
                    period_start=record.period_start,
                    vintage_date=record.vintage_date,
                    **values,
                )
            )
            existing[key] = (-1, record.source_hash)
            inserted += 1
        elif current[1] == record.source_hash:
            skipped += 1
        else:
            await session.execute(
                update(Observation).where(Observation.id == current[0]).values(**values)
            )
            existing[key] = (current[0], record.source_hash)
            updated_count += 1
    await session.flush()
    return inserted, updated_count, skipped


@dataclass
class SyncSummary:
    mode: str
    inserted: int
    updated: int
    skipped: int
    warnings: list[str]


async def synchronize(
    engine: AsyncEngine,
    settings: Settings,
    *,
    canonical_keys: Sequence[str] | None = None,
    start: date | None = None,
) -> SyncSummary:
    """Synchronize selected catalog records, falling back to explicit Demo mode."""

    factory = session_factory(engine)
    async with factory() as session:
        catalog = await ensure_catalog(session, settings)
        selected = [
            item
            for item in catalog
            if canonical_keys is None
            or item.canonical_key in canonical_keys
            or item.native_id in canonical_keys
        ]
        run = SyncRun(
            id=uuid.uuid4(),
            provider="fred_alfred",
            job_type="sync",
            started_at=datetime.now(UTC),
            status="running",
            requested_series=[item.canonical_key for item in selected],
            metadata_json={"data_mode": "initializing"},
        )
        session.add(run)
        await session.commit()

        inserted = updated_count = skipped = 0
        warnings: list[str] = []
        if canonical_keys and not selected:
            warnings.append(f"unknown series selection: {', '.join(canonical_keys)}")
        live_success = 0
        provider = (
            FredAlfredProvider(settings.fred_api_key.get_secret_value())
            if settings.fred_api_key
            else None
        )

        for item in selected:
            series = await session.scalar(
                select(Series).where(Series.canonical_key == item.canonical_key)
            )
            if series is None:
                continue
            records: list[ObservationRecord]
            source_mode = "demo"
            if provider is None:
                records = demo_records(item)
            else:
                try:
                    was_demo = series.metadata_json.get("source_mode") == "demo"
                    metadata = await provider.fetch_metadata(item.native_id)
                    series.title = metadata.title
                    series.description = metadata.description
                    series.seasonal_adjustment = metadata.seasonal_adjustment
                    series.metadata_json = {
                        **series.metadata_json,
                        **metadata.metadata,
                    }
                    records = [
                        record
                        async for record in provider.fetch_observations(
                            item.native_id,
                            start=start,
                        )
                    ]
                    if records and was_demo:
                        await session.execute(
                            delete(Observation).where(Observation.series_id == series.id)
                        )
                        await session.flush()
                    if records:
                        live_success += 1
                    source_mode = "live"
                except Exception as exc:
                    warnings.append(
                        f"{item.native_id}: provider request failed ({type(exc).__name__})"
                    )
                    records = []
            if records:
                added, changed, unchanged = await persist_observations(session, series, records)
                inserted += added
                updated_count += changed
                skipped += unchanged
                series.metadata_json = {
                    **series.metadata_json,
                    "source_mode": source_mode,
                    "last_sync_at": datetime.now(UTC).isoformat(),
                }
                await session.commit()

        if live_success:
            demo_series = (
                await session.scalars(select(Series).where(Series.active.is_(True)))
            ).all()
            for series in demo_series:
                if series.metadata_json.get("source_mode") != "demo":
                    continue
                await session.execute(delete(Observation).where(Observation.series_id == series.id))
                series.metadata_json = {
                    **series.metadata_json,
                    "source_mode": "unavailable",
                }
            await session.commit()

        if provider is not None and live_success:
            try:
                release_records = await provider.fetch_releases(
                    start=date.today() - timedelta(days=7),
                    end=date.today() + timedelta(days=60),
                )
                provider_row = await session.scalar(
                    select(Provider).where(Provider.key == provider.key)
                )
                for record in release_records:
                    if provider_row is None or record.scheduled_at is None:
                        continue
                    scheduled_at = record.scheduled_at
                    if scheduled_at.date() < date.today() - timedelta(days=7):
                        continue
                    existing_release = await session.scalar(
                        select(Release).where(
                            Release.provider_id == provider_row.id,
                            Release.native_id == record.native_id,
                            Release.scheduled_at == scheduled_at,
                        )
                    )
                    if existing_release is None:
                        session.add(
                            Release(
                                id=uuid.uuid4(),
                                provider_id=provider_row.id,
                                native_id=record.native_id,
                                name=record.name,
                                scheduled_at=scheduled_at,
                                actual_at=record.actual_at,
                                source_timezone=record.source_timezone,
                                status=record.status,
                                importance=record.importance,
                                source_url=str(record.source_url),
                                metadata_json=record.metadata,
                            )
                        )
                await session.commit()
            except Exception as exc:
                warnings.append(f"release calendar request failed ({type(exc).__name__})")

        observation_count = await session.scalar(select(func.count()).select_from(Observation))
        if provider is None:
            mode = "DEMO"
        elif live_success:
            mode = "LIVE"
        elif observation_count:
            mode = await _mode_from_existing(session, settings)
            if mode == "LIVE":
                mode = "STALE"
        else:
            # A bad key or provider outage must not make the first launch unusable.
            for item in selected:
                series = await session.scalar(
                    select(Series).where(Series.canonical_key == item.canonical_key)
                )
                if series is None:
                    continue
                added, changed, unchanged = await persist_observations(
                    session, series, demo_records(item)
                )
                inserted += added
                updated_count += changed
                skipped += unchanged
                series.metadata_json = {
                    **series.metadata_json,
                    "source_mode": "demo",
                    "last_sync_at": datetime.now(UTC).isoformat(),
                }
            mode = "DEMO"
            warnings.append("FRED was unavailable; explicit Demo fixtures were loaded")

        run.finished_at = datetime.now(UTC)
        run.status = "complete" if not warnings else "partial"
        run.inserted_rows = inserted
        run.updated_rows = updated_count
        run.skipped_rows = skipped
        run.warnings = warnings
        run.metadata_json = {"data_mode": mode}
        await session.commit()
        return SyncSummary(mode, inserted, updated_count, skipped, warnings)


async def _mode_from_existing(session: AsyncSession, settings: Settings) -> str:
    count = await session.scalar(select(func.count()).select_from(Observation))
    if not count:
        return "EMPTY"
    latest = await session.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
    if latest is not None:
        configured = str(latest.metadata_json.get("data_mode", "")).upper()
        if configured == "DEMO":
            return "DEMO"
        finished = _aware(latest.finished_at or latest.started_at)
        if configured == "LIVE" and finished is not None:
            age = datetime.now(UTC) - finished
            return "STALE" if age > timedelta(hours=settings.stale_after_hours) else "LIVE"
    modes = (
        await session.scalars(select(Series.metadata_json).where(Series.active.is_(True)))
    ).all()
    if any(item.get("source_mode") == "demo" for item in modes):
        return "DEMO"
    return "STALE"


async def data_health(engine: AsyncEngine, settings: Settings) -> dict[str, Any]:
    factory = session_factory(engine)
    async with factory() as session:
        mode = await _mode_from_existing(session, settings)
        observations = await session.scalar(select(func.count()).select_from(Observation))
        series_count = await session.scalar(select(func.count()).select_from(Series))
        latest = await session.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
        return {
            "mode": mode,
            "database": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
            "observations": observations or 0,
            "series": series_count or 0,
            "last_sync_at": _aware(latest.finished_at or latest.started_at) if latest else None,
            "syncing": bool(latest and latest.status == "running"),
            "fred_configured": settings.fred_api_key is not None,
            "warnings": latest.warnings if latest else [],
        }


async def _latest_series_data(
    session: AsyncSession,
    *,
    as_of: datetime,
) -> dict[uuid.UUID, list[Observation]]:
    rows = (
        await session.scalars(
            select(Observation)
            .where(Observation.available_at <= as_of)
            .order_by(
                Observation.series_id,
                Observation.period_start,
                Observation.vintage_date,
            )
        )
    ).all()
    latest: dict[tuple[uuid.UUID, date], Observation] = {}
    for row in rows:
        latest[(row.series_id, row.period_start)] = row
    grouped: dict[uuid.UUID, list[Observation]] = defaultdict(list)
    for (series_id, _period), row in latest.items():
        grouped[series_id].append(row)
    for values in grouped.values():
        values.sort(key=lambda item: item.period_start)
    return grouped


def _score_component(
    series: Series,
    component: StateComponent,
    rows: Sequence[Observation],
    *,
    cutoff: date | None = None,
) -> dict[str, Any] | None:
    filtered = [row for row in rows if cutoff is None or row.period_start <= cutoff]
    raw = [float(row.value) if row.value is not None else None for row in filtered]
    if not raw:
        return None
    try:
        transformed = apply_transform(
            raw,
            component.transform,
            frequency=series.frequency,
        )
    except ValueError:
        return None
    quantiles = rolling_quantile(transformed)
    available = [
        (index, value)
        for index, value in enumerate(transformed)
        if value is not None and quantiles[index] is not None
    ]
    if len(available) < min(component.minimum_history, 12):
        return None
    index, value = available[-1]
    quantile = quantiles[index]
    if quantile is None:
        return None
    score = max(-1.0, min(1.0, component.orientation * (2 * quantile - 1)))
    previous_score: float | None = None
    if len(available) > 1:
        previous_index = available[-2][0]
        previous_quantile = quantiles[previous_index]
        if previous_quantile is not None:
            previous_score = max(
                -1.0,
                min(1.0, component.orientation * (2 * previous_quantile - 1)),
            )
    row = filtered[index]
    return {
        "canonical_key": series.canonical_key,
        "title": series.title,
        "score": score,
        "previous_score": previous_score,
        "value": value,
        "raw_value": raw[index],
        "as_of": row.period_start,
        "available_at": _aware(row.available_at),
        "weight": component.base_weight,
        "freshness_half_life_days": component.freshness_half_life_days,
        "transform": component.transform,
    }


def _label(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 0.6:
        return "high"
    if score >= 0.2:
        return "elevated"
    if score > -0.2:
        return "neutral"
    if score > -0.6:
        return "soft"
    return "low"


def _aggregate_state(
    state_key: str,
    components: Sequence[tuple[Series, StateComponent, Sequence[Observation]]],
    *,
    now: datetime,
    cutoff: date | None = None,
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    missing: list[str] = []
    total_weight = sum(component.base_weight for _series, component, _rows in components)
    for series, component, rows in components:
        result = _score_component(series, component, rows, cutoff=cutoff)
        if result is None:
            missing.append(series.canonical_key)
        else:
            scored.append(result)
    active_weight = sum(item["weight"] for item in scored)
    score = (
        sum(item["score"] * item["weight"] for item in scored) / active_weight
        if active_weight
        else None
    )
    previous_values = [item for item in scored if item["previous_score"] is not None]
    previous_score = (
        sum(item["previous_score"] * item["weight"] for item in previous_values)
        / sum(item["weight"] for item in previous_values)
        if previous_values
        else None
    )
    coverage = active_weight / total_weight if total_weight else 0.0
    freshness_values: list[float] = []
    for item in scored:
        available_at = item["available_at"]
        if available_at is None:
            freshness_values.append(0.5)
            continue
        age_days = max(0.0, (now - available_at).total_seconds() / 86400)
        freshness_values.append(
            math.exp(-math.log(2) * age_days / item["freshness_half_life_days"])
        )
    freshness = sum(freshness_values) / len(freshness_values) if freshness_values else 0.0
    confidence = max(0.0, min(1.0, coverage * (0.45 + 0.55 * freshness)))
    delta = score - previous_score if score is not None and previous_score is not None else 0
    trend = "rising" if delta > 0.04 else "falling" if delta < -0.04 else "stable"
    drivers = sorted(
        (
            {
                **item,
                "contribution": item["score"] * item["weight"],
            }
            for item in scored
        ),
        key=lambda item: abs(item["contribution"]),
        reverse=True,
    )[:3]
    latest_dates = [item["as_of"] for item in scored]
    return {
        "key": state_key,
        "score": round(score, 4) if score is not None else None,
        "label": _label(score),
        "confidence": round(confidence, 4),
        "trend": trend,
        "top_drivers": drivers,
        "missing_series": missing,
        "stale": confidence < 0.35,
        "as_of": max(latest_dates) if latest_dates else None,
        "experimental": state_key in EXPERIMENTAL_STATES,
    }


async def build_snapshot(
    engine: AsyncEngine,
    settings: Settings,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Build the terminal home payload without inventing missing state values."""

    now = as_of or datetime.now(UTC)
    factory = session_factory(engine)
    async with factory() as session:
        health = await data_health(engine, settings)
        series_rows = (await session.scalars(select(Series).where(Series.active.is_(True)))).all()
        components_rows = (
            await session.scalars(select(StateComponent).where(StateComponent.enabled.is_(True)))
        ).all()
        data = await _latest_series_data(session, as_of=now)
        series_map = {item.id: item for item in series_rows}
        by_state: dict[str, list[tuple[Series, StateComponent, Sequence[Observation]]]] = (
            defaultdict(list)
        )
        for component in components_rows:
            series = series_map.get(component.series_id)
            if series is not None:
                by_state[component.state_key].append((series, component, data.get(series.id, [])))

        states = [_aggregate_state(key, by_state.get(key, []), now=now) for key in STATE_ORDER]
        history: list[dict[str, Any]] = []
        for months_ago in range(5, -1, -1):
            cutoff = _shift_month(now.date(), -months_ago)
            growth = _aggregate_state("growth", by_state.get("growth", []), now=now, cutoff=cutoff)
            inflation = _aggregate_state(
                "inflation", by_state.get("inflation", []), now=now, cutoff=cutoff
            )
            if growth["score"] is not None and inflation["score"] is not None:
                history.append(
                    {
                        "date": cutoff,
                        "growth": growth["score"],
                        "inflation": inflation["score"],
                    }
                )
        state_map = {item["key"]: item for item in states}
        releases = (
            _demo_releases() if health["mode"] == "DEMO" else await _release_calendar(session, now)
        )
        revision_changes = await _revision_changes(session, series_map)
        changes = _top_changes(states, health, revision_changes, releases)
        regime = {
            "growth": state_map["growth"]["score"],
            "inflation": state_map["inflation"]["score"],
            "confidence": round(
                min(
                    state_map["growth"]["confidence"],
                    state_map["inflation"]["confidence"],
                ),
                4,
            ),
            "trajectory": history,
        }
        return {
            "generated_at": now,
            "mode": health["mode"],
            "methodology_version": METHODOLOGY_VERSION,
            "states": states,
            "top_changes": changes,
            "regime": regime,
            "releases": releases,
            "system": health,
        }


async def _revision_changes(
    session: AsyncSession,
    series_map: dict[uuid.UUID, Series],
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Observation)
            .where(Observation.is_revised.is_(True))
            .order_by(Observation.vintage_date.desc())
            .limit(8)
        )
    ).all()
    changes: list[dict[str, Any]] = []
    for current in rows:
        series = series_map.get(current.series_id)
        if series is None:
            continue
        previous = await session.scalar(
            select(Observation)
            .where(
                Observation.series_id == current.series_id,
                Observation.period_start == current.period_start,
                Observation.vintage_date < current.vintage_date,
            )
            .order_by(Observation.vintage_date.desc())
            .limit(1)
        )
        if previous is None or previous.value == current.value:
            continue
        changes.append(
            {
                "type": "revision",
                "title": f"{series.title} was revised",
                "explanation": ("The latest available vintage differs from its prior release."),
                "previous": float(previous.value) if previous.value is not None else None,
                "current": float(current.value) if current.value is not None else None,
                "date": current.vintage_date,
                "state": (series.metadata_json.get("state_dimensions") or [None])[0],
                "importance": 2,
                "source": series.source_url,
            }
        )
    return changes


async def _release_calendar(
    session: AsyncSession,
    now: datetime,
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(Release)
            .where(Release.scheduled_at >= now - timedelta(days=1))
            .order_by(Release.scheduled_at)
            .limit(12)
        )
    ).all()
    return [
        {
            "title": item.name,
            "scheduled_at": _aware(item.scheduled_at),
            "importance": item.importance,
            "source": item.source_url,
        }
        for item in rows
    ]


def _top_changes(
    states: Sequence[dict[str, Any]],
    health: dict[str, Any],
    revision_changes: Sequence[dict[str, Any]],
    releases: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for state in states:
        if state["score"] is None:
            continue
        if abs(state["score"]) >= 0.55:
            changes.append(
                {
                    "type": "extreme",
                    "title": f"{state['key']} state is outside its neutral range",
                    "explanation": (
                        "Rolling component percentiles place this state near an extreme."
                    ),
                    "previous": None,
                    "current": state["score"],
                    "date": state["as_of"],
                    "state": state["key"],
                    "importance": min(3, 1 + int(abs(state["score"]) > 0.75)),
                    "source": "World State methodology",
                }
            )
    changes.extend(revision_changes)
    changes.extend(
        {
            "type": "release",
            "title": item["title"],
            "explanation": "Scheduled macroeconomic data release.",
            "previous": None,
            "current": None,
            "date": item["scheduled_at"],
            "state": None,
            "importance": item["importance"],
            "source": item["source"],
        }
        for item in releases[:3]
    )
    if health["mode"] == "STALE":
        changes.insert(
            0,
            {
                "type": "stale",
                "title": "Provider data is stale",
                "explanation": (
                    "The last successful live synchronization is older than the "
                    "configured threshold."
                ),
                "previous": None,
                "current": health["last_sync_at"],
                "date": datetime.now(UTC).date(),
                "state": None,
                "importance": 3,
                "source": "System health",
            },
        )
    return sorted(changes, key=lambda item: item["importance"], reverse=True)[:10]


def _demo_releases() -> list[dict[str, Any]]:
    return [
        {
            "title": "Demo: Initial Jobless Claims",
            "scheduled_at": datetime(2026, 7, 23, 12, 30, tzinfo=UTC),
            "importance": 2,
            "source": "Demo fixture",
        },
        {
            "title": "Demo: Personal Income and Outlays",
            "scheduled_at": datetime(2026, 7, 31, 12, 30, tzinfo=UTC),
            "importance": 3,
            "source": "Demo fixture",
        },
    ]


async def list_series(engine: AsyncEngine) -> list[dict[str, Any]]:
    factory = session_factory(engine)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(Series).where(Series.active.is_(True)).order_by(Series.title)
            )
        ).all()
        return [
            {
                "canonical_key": item.canonical_key,
                "native_id": item.native_id,
                "title": item.title,
                "frequency": item.frequency,
                "unit": item.unit,
                "default_transform": item.default_transform,
                "source_url": item.source_url,
                "source_mode": item.metadata_json.get("source_mode"),
            }
            for item in rows
        ]


async def query_series(
    engine: AsyncEngine,
    canonical_key: str,
    *,
    transform: str,
    as_of: datetime,
) -> dict[str, Any] | None:
    factory = session_factory(engine)
    async with factory() as session:
        series = await session.scalar(select(Series).where(Series.canonical_key == canonical_key))
        if series is None:
            return None
        grouped = await _latest_series_data(session, as_of=as_of)
        rows = grouped.get(series.id, [])
        values = [float(row.value) if row.value is not None else None for row in rows]
        transformed = apply_transform(values, transform, frequency=series.frequency)
        percentiles = rolling_quantile(transformed)
        revision_count = await session.scalar(
            select(func.count())
            .select_from(Observation)
            .where(Observation.series_id == series.id, Observation.is_revised.is_(True))
        )
        return {
            "canonical_key": series.canonical_key,
            "native_id": series.native_id,
            "title": series.title,
            "frequency": series.frequency,
            "unit": series.unit,
            "transform": transform,
            "source_url": series.source_url,
            "source_mode": series.metadata_json.get("source_mode"),
            "last_updated": series.metadata_json.get("last_sync_at"),
            "revision_count": revision_count or 0,
            "observations": [
                {
                    "date": row.period_start,
                    "raw": values[index],
                    "value": transformed[index],
                    "percentile": percentiles[index],
                    "vintage_date": row.vintage_date,
                }
                for index, row in enumerate(rows)
            ],
        }
