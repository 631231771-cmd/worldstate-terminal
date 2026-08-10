"""Read-side market dashboard and macro-series explorer projections."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.quality_resolver import resolve_quality_grade
from worldstate.db.models import (
    DataQualityRecord,
    MarketBar,
    MarketInstrument,
    Observation,
    Provider,
    Series,
)

DataMode = Literal["observed", "fixture", "all"]
Horizon = Literal["1d", "1w", "1m", "3m"]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _horizon_delta(horizon: Horizon) -> timedelta:
    return {
        "1d": timedelta(days=1),
        "1w": timedelta(days=7),
        "1m": timedelta(days=30),
        "3m": timedelta(days=90),
    }[horizon]


def _percentile(value: float, sample: list[float]) -> float | None:
    if not sample:
        return None
    return round(100.0 * sum(item <= value for item in sample) / len(sample), 2)


async def build_market_dashboard(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    horizon: Horizon = "1d",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    delta = _horizon_delta(horizon)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        query = (
            select(MarketBar, MarketInstrument, DataQualityRecord)
            .join(MarketInstrument, MarketInstrument.id == MarketBar.instrument_id)
            .outerjoin(DataQualityRecord, DataQualityRecord.id == MarketBar.quality_id)
            .where(MarketBar.timestamp <= cutoff)
            .order_by(MarketBar.timestamp.desc())
        )
        if data_mode != "all":
            query = query.where(MarketBar.data_mode == data_mode)
        rows = (await session.execute(query.limit(30_000))).all()
    by_key: dict[str, list[tuple[MarketBar, MarketInstrument, DataQualityRecord | None]]] = {}
    for bar, instrument, quality in rows:
        by_key.setdefault(str(instrument.canonical_key), []).append((bar, instrument, quality))
    items: list[dict[str, Any]] = []
    for key, series in by_key.items():
        latest, instrument, latest_quality = series[0]
        baseline = next(
            (bar for bar, _, _ in series if _aware(bar.timestamp) <= cutoff - delta),
            None,
        )
        latest_value = float(latest.close_value)
        change = None
        if baseline is not None and float(baseline.close_value) != 0:
            change = latest_value / float(baseline.close_value) - 1.0
        returns: list[float] = []
        previous: float | None = None
        for bar, _, _ in reversed(series):
            close = float(bar.close_value)
            if previous is not None and previous != 0:
                returns.append(close / previous - 1.0)
            previous = close
        items.append(
            {
                "instrument_key": key,
                "title": instrument.title,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class,
                "instrument_type": instrument.instrument_type,
                "is_proxy": instrument.is_proxy,
                "proxy_for": instrument.proxy_for,
                "latest": latest_value,
                "change_percent": round(change * 100, 4) if change is not None else None,
                "direction": "up"
                if change and change > 0.0005
                else "down"
                if change and change < -0.0005
                else "flat"
                if change is not None
                else "unavailable",
                "percentile": _percentile(change, returns) if change is not None else None,
                "timestamp": latest.timestamp.isoformat(),
                "provider": latest.provider_key,
                "data_mode": latest.data_mode,
                "quality_grade": resolve_quality_grade(latest_quality),
                "quality_limitation": (
                    latest_quality.verification_notes
                    if latest_quality
                    else "No quality record was persisted for this observation."
                ),
                "granularity_seconds": latest.interval_seconds,
                "bar_count": len(series),
                "data_gap": baseline is None,
                "limitation": "代理合约或非结算价；仅作跨资产确认线索。"
                if instrument.is_proxy
                else None,
                "evidence_ids": [str(latest.id)],
            }
        )
    items.sort(key=lambda item: abs(item["change_percent"] or 0), reverse=True)
    return {
        "as_of": cutoff.isoformat(),
        "data_mode": data_mode,
        "horizon": horizon,
        "methodology_version": "wst-market-dashboard-v1",
        "items": items,
        "available_assets": len(items),
        "missing_assets": [],
        "limitations": [
            "百分位基于当前可见 bars 的简单经验分布，样本不足时不会制造概率。",
            "期货连续合约、夜盘和结算价语义由 manifest/provider 声明；代理资产会显式标记。",
        ],
    }


def _transform(values: list[float], periods: list[date], transform: str) -> list[float | None]:
    result: list[float | None] = []
    for index, value in enumerate(values):
        lag = 12 if transform == "yoy" else 1
        if transform in {"yoy", "mom"}:
            lag = 12 if transform == "yoy" else 1
            if index < lag or values[index - lag] == 0:
                result.append(None)
            else:
                result.append(value / values[index - lag] - 1.0)
        elif transform == "3m_annualized":
            if index < 3 or values[index - 3] == 0:
                result.append(None)
            else:
                result.append((value / values[index - 3]) ** 4 - 1.0)
        elif transform == "moving_average":
            window = values[max(0, index - 5) : index + 1]
            result.append(sum(window) / len(window))
        elif transform in {"zscore", "percentile"}:
            history = values[: index + 1]
            mean = sum(history) / len(history)
            std = math.sqrt(sum((item - mean) ** 2 for item in history) / max(1, len(history) - 1))
            result.append(
                (value - mean) / std
                if transform == "zscore" and std > 1e-12
                else 100.0 * sum(item <= value for item in history) / len(history)
                if transform == "percentile"
                else 0.0
            )
        else:
            result.append(value)
    return result


async def search_series(
    engine: AsyncEngine,
    *,
    query: str | None = None,
    data_mode: DataMode = "observed",
    limit: int = 100,
) -> list[dict[str, Any]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        statement = (
            select(Series, Provider)
            .join(Provider, Provider.id == Series.provider_id)
            .where(Series.active.is_(True))
            .order_by(Series.canonical_key)
        )
        rows = (await session.execute(statement)).all()
        output: list[dict[str, Any]] = []
        needle = (query or "").lower().strip()
        for series, provider in rows:
            haystack = f"{series.canonical_key} {series.title} {series.native_id}".lower()
            if needle and needle not in haystack:
                continue
            observations_query = (
                select(Observation, DataQualityRecord)
                .outerjoin(
                    DataQualityRecord,
                    DataQualityRecord.id
                    == (
                        select(DataQualityRecord.id)
                        .where(
                            DataQualityRecord.subject_type == "macro_series",
                            DataQualityRecord.subject_id == series.canonical_key,
                        )
                        .order_by(DataQualityRecord.acquired_at.desc())
                        .limit(1)
                        .scalar_subquery()
                    ),
                )
                .where(Observation.series_id == series.id)
                .order_by(Observation.period_start.desc())
                .order_by(DataQualityRecord.acquired_at.desc())
                .limit(1)
            )
            if data_mode != "all":
                observations_query = observations_query.where(Observation.data_mode == data_mode)
            latest_row = (await session.execute(observations_query)).first()
            latest = latest_row[0] if latest_row else None
            latest_quality = latest_row[1] if latest_row else None
            output.append(
                {
                    "canonical_key": series.canonical_key,
                    "native_id": series.native_id,
                    "title": series.title,
                    "provider": provider.key,
                    "unit": series.unit,
                    "frequency": series.frequency,
                    "source_url": series.source_url,
                    "default_transform": series.default_transform,
                    "latest_value": float(latest.value)
                    if latest and latest.value is not None
                    else None,
                    "latest_period": latest.period_start.isoformat() if latest else None,
                    "available_at": latest.available_at.isoformat()
                    if latest and latest.available_at
                    else None,
                    "fetched_at": latest.fetched_at.isoformat() if latest else None,
                    "vintage": latest.vintage_date.isoformat() if latest else None,
                    "revision": bool(latest.is_revised) if latest else None,
                    "data_mode": latest.data_mode if latest else data_mode,
                    "quality": resolve_quality_grade(latest_quality),
                    "quality_limitation": (
                        latest_quality.verification_notes
                        if latest_quality
                        else "No quality record was persisted for this observation."
                    ),
                    "observations_available": latest is not None,
                    "state_dimensions": series.metadata_json.get("state_dimensions", []),
                }
            )
            if len(output) >= limit:
                break
    return output


async def get_series_history(
    engine: AsyncEngine,
    canonical_key: str,
    *,
    data_mode: DataMode = "observed",
    transform: str = "raw",
    limit: int = 240,
) -> dict[str, Any] | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        series = await session.scalar(select(Series).where(Series.canonical_key == canonical_key))
        if series is None:
            return None
        query = (
            select(Observation)
            .where(Observation.series_id == series.id)
            .order_by(Observation.period_start.desc())
            .limit(limit)
        )
        if data_mode != "all":
            query = query.where(Observation.data_mode == data_mode)
        observations = list((await session.scalars(query)).all())[::-1]
        valid_observations = [item for item in observations if item.value is not None]
        values = []
        for item in valid_observations:
            assert item.value is not None
            values.append(float(item.value))
        periods = [item.period_start for item in valid_observations]
        transformed = _transform(values, periods, transform)
        provider = await session.scalar(select(Provider).where(Provider.id == series.provider_id))
        if provider is None:
            return None
        points = []
        for index, (period, value) in enumerate(zip(periods, values, strict=False)):
            available_at = valid_observations[index].available_at
            points.append(
                {
                    "period": period.isoformat(),
                    "value": value,
                    "transformed": transformed[index],
                    "vintage": valid_observations[index].vintage_date.isoformat(),
                    "available_at": available_at.isoformat() if available_at else None,
                    "observation_id": valid_observations[index].id,
                }
            )
        return {
            "canonical_key": series.canonical_key,
            "title": series.title,
            "provider": provider.key,
            "native_id": series.native_id,
            "unit": series.unit,
            "frequency": series.frequency,
            "transform": transform,
            "data_mode": data_mode,
            "points": points,
            "limitations": ["转换只用于研究浏览，不改变数据库中的原始观测。"],
        }
