"""Deterministic macro state construction for the v0.6 daily terminal.

The state engine intentionally sits on top of the existing Series/Observation
point-in-time tables.  It never manufactures an observed value: when the
requested mode has no usable observations the dimension is returned as
unavailable with an explicit gap.  The algorithm is deliberately simple so a
reader can reproduce it from the response and the cited observation ids.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.db.models import EconomicEntity, Observation, Provider, Series

DataMode = Literal["observed", "fixture", "all"]
DIMENSIONS = (
    "growth",
    "inflation",
    "liquidity",
    "policy_tightness",
    "credit",
    "risk",
    "fiscal",
    "external",
)


@dataclass(frozen=True)
class SeriesSignal:
    series_key: str
    title: str
    dimension: str
    score: float | None
    momentum: float | None
    latest_value: float | None
    period_start: date | None
    available_at: datetime | None
    observation_count: int
    provider_key: str
    source_url: str
    data_mode: str
    quality: str
    missing_reason: str | None
    evidence_ids: tuple[str, ...]


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _percent_change(current: float, prior: float) -> float | None:
    if prior == 0:
        return None
    return (current / abs(prior) - 1.0) * 100.0


def calculate_signal(
    values: Iterable[float],
    *,
    orientation: int = 1,
    transform: str = "level",
    minimum_history: int = 3,
) -> tuple[float | None, float | None, str | None]:
    """Return ``(score, momentum, missing_reason)`` for an ordered history.

    Scores are a robust, bounded z-like distance of the latest change from its
    own recent history.  It is not a forecast and is not comparable to an
    event surprise z-score.  ``orientation`` only changes the interpretation
    (for example unemployment and TGA are negative when higher).
    """

    history = [item for item in (_finite(item) for item in values) if item is not None]
    if len(history) < max(2, minimum_history):
        return None, None, f"需要至少 {minimum_history} 个有效观测，当前 {len(history)} 个"
    if transform in {"yoy", "percent_change"} or transform == "level":
        changes = [
            change
            for left, right in pairwise(history)
            if (change := _percent_change(right, left)) is not None
        ]
    else:
        changes = [right - left for left, right in pairwise(history)]
    if len(changes) < 2:
        return None, None, "无法从历史观测计算变化"
    current = changes[-1]
    baseline = changes[:-1]
    mean = sum(baseline) / len(baseline)
    variance = sum((item - mean) ** 2 for item in baseline) / max(1, len(baseline) - 1)
    std = math.sqrt(variance)
    # A zero-variance series still has a meaningful direction, but no claim of
    # unusualness.  Use a small scale only to preserve the sign.
    standardized = (
        (current - mean) / std
        if std > 1e-12
        else (1.0 if current > 0 else -1.0 if current < 0 else 0.0)
    )
    score = clamp(float(orientation) * math.tanh(standardized / 2.0))
    momentum = clamp(float(orientation) * math.tanh(current / (abs(mean) + 1e-9) / 2.0))
    return score, momentum, None


def aggregate_dimension(signals: Iterable[SeriesSignal]) -> dict[str, Any]:
    usable = [item for item in signals if item.score is not None]
    total_weight = len(list(signals)) if not isinstance(signals, list) else len(signals)
    if not usable:
        return {
            "score": None,
            "direction": "unavailable",
            "momentum": None,
            "confidence": 0.0,
            "coverage": 0.0,
            "freshness": None,
            "top_drivers": [],
            "missing_inputs": [item.missing_reason or item.series_key for item in signals],
        }
    score = sum(item.score or 0 for item in usable) / len(usable)
    momentum_values = [item.momentum for item in usable if item.momentum is not None]
    latest_times = [item.available_at for item in usable if item.available_at is not None]
    freshness = None
    if latest_times:
        age_days = max(
            0.0, (datetime.now(UTC) - max(latest_times).astimezone(UTC)).total_seconds() / 86400
        )
        freshness = math.exp(-age_days / 45.0)
    direction = "strong" if score >= 0.35 else "weak" if score <= -0.35 else "mixed"
    return {
        "score": round(clamp(score), 4),
        "direction": direction,
        "momentum": round(sum(momentum_values) / len(momentum_values), 4)
        if momentum_values
        else None,
        "confidence": round(clamp(0.25 + 0.15 * len(usable) + 0.25 * (freshness or 0)), 4),
        "coverage": round(len(usable) / max(1, total_weight), 4),
        "freshness": round(freshness, 4) if freshness is not None else None,
        "top_drivers": [
            {
                "series_key": item.series_key,
                "title": item.title,
                "score": round(item.score or 0, 4),
                "momentum": round(item.momentum or 0, 4),
                "latest_value": item.latest_value,
                "period_start": item.period_start.isoformat() if item.period_start else None,
                "provider": item.provider_key,
                "source_url": item.source_url,
                "data_mode": item.data_mode,
                "quality": item.quality,
                "evidence_ids": list(item.evidence_ids),
            }
            for item in sorted(usable, key=lambda row: abs(row.score or 0), reverse=True)[:5]
        ],
        "missing_inputs": [
            item.missing_reason or item.series_key for item in signals if item.score is None
        ],
    }


def classify_regime(dimensions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    growth = dimensions.get("growth", {}).get("score")
    inflation = dimensions.get("inflation", {}).get("score")
    policy = dimensions.get("policy_tightness", {}).get("score")
    risk = dimensions.get("risk", {}).get("score")
    if growth is None or inflation is None:
        label = "数据不足"
    elif growth >= 0.2 and inflation >= 0.2:
        label = "再通胀 / Reflation"
    elif growth >= 0.2 and inflation <= -0.2:
        label = "扩张中的去通胀 / Disinflationary expansion"
    elif growth <= -0.2 and inflation >= 0.2:
        label = "滞胀倾向 / Stagflation-like"
    elif growth <= -0.2 and inflation <= -0.2:
        label = "放缓 / Slowdown"
    else:
        label = "混合 / Mixed"
    tags = [label]
    if policy is not None and policy >= 0.35:
        tags.append("政策偏紧")
    elif policy is not None and policy <= -0.35:
        tags.append("政策偏松")
    if risk is not None and risk >= 0.35:
        tags.append("风险规避")
    elif risk is not None and risk <= -0.35:
        tags.append("风险偏好")
    known = [
        item.get("confidence", 0.0) for item in dimensions.values() if item.get("score") is not None
    ]
    return {
        "label": label,
        "tags": tags,
        "confidence": round(sum(known) / len(known), 4) if known else 0.0,
    }


def _orientation(series: Series) -> int:
    value = series.metadata_json.get("orientation", 1)
    return int(value) if value in (-1, 1) else 1


async def _load_signals(
    session: AsyncSession, data_mode: DataMode, as_of: datetime
) -> list[SeriesSignal]:
    rows = (
        await session.execute(
            select(Series, Provider)
            .join(Provider, Provider.id == Series.provider_id)
            .where(Series.active.is_(True))
        )
    ).all()
    result: list[SeriesSignal] = []
    for series, provider in rows:
        metadata = series.metadata_json or {}
        dimensions = metadata.get("state_dimensions") or []
        if not isinstance(dimensions, list) or not dimensions:
            continue
        observations_query = select(Observation).where(
            Observation.series_id == series.id,
            Observation.available_at.is_not(None),
            Observation.available_at <= as_of,
            Observation.vintage_date <= as_of.date(),
        )
        if data_mode != "all":
            observations_query = observations_query.where(Observation.data_mode == data_mode)
        observations = list(
            (await session.scalars(observations_query.order_by(Observation.period_start))).all()
        )
        key = str(series.canonical_key)
        if not observations:
            result.extend(
                SeriesSignal(
                    key,
                    series.title,
                    str(dimension),
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    provider.key,
                    series.source_url,
                    data_mode,
                    "UNKNOWN",
                    "该数据模式没有可用的点时观测",
                    (),
                )
                for dimension in dimensions
            )
            continue
        values = [float(item.value) for item in observations if item.value is not None]
        minimum_history = metadata.get("minimum_history", 3)
        try:
            minimum_history = int(minimum_history)
        except (TypeError, ValueError):
            minimum_history = 3
        score, momentum, gap = calculate_signal(
            values,
            orientation=_orientation(series),
            transform=series.default_transform,
            minimum_history=minimum_history,
        )
        latest = observations[-1]
        result.extend(
            SeriesSignal(
                key,
                series.title,
                str(dimension),
                score,
                momentum,
                _finite(latest.value),
                latest.period_start,
                latest.available_at,
                len(values),
                provider.key,
                series.source_url,
                str(latest.data_mode),
                "A" if provider.key in {"fred_alfred", "bls_official"} else "B",
                gap,
                (str(latest.id),),
            )
            for dimension in dimensions
        )
    return result


async def build_world_state(
    engine: AsyncEngine, *, data_mode: DataMode = "observed", as_of: datetime | None = None
) -> dict[str, Any]:
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        signals = await _load_signals(session, data_mode, cutoff)
    by_dimension: dict[str, list[SeriesSignal]] = {dimension: [] for dimension in DIMENSIONS}
    for signal in signals:
        if signal.dimension in by_dimension:
            by_dimension[signal.dimension].append(signal)
    dimensions = {key: aggregate_dimension(items) for key, items in by_dimension.items()}
    regime = classify_regime(dimensions)
    return {
        "as_of": cutoff.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-state-v1",
        "dimensions": dimensions,
        "regime": regime,
        "limitations": [
            "状态分数是可解释的变化标准化，不是预测或交易信号。",
            "缺失、过期或样本不足的序列不会被补成 observed。",
            "fixture 模式只用于演示完整界面，不能与 observed 统计混合。",
        ],
    }


_FIXTURE_STATE_SERIES = (
    ("US.GROWTH.REAL_GDP", "Real GDP", "quarterly", "index", "growth", 1),
    ("US.GROWTH.INDUSTRIAL_PRODUCTION", "Industrial Production", "monthly", "index", "growth", 1),
    ("US.INFLATION.CPI_HEADLINE", "Headline CPI", "monthly", "index", "inflation", 1),
    ("US.INFLATION.CPI_CORE", "Core CPI", "monthly", "index", "inflation", 1),
    ("US.POLICY.TREASURY_2Y", "US 2Y Treasury Yield", "monthly", "percent", "policy_tightness", 1),
    (
        "US.POLICY.TREASURY_10Y",
        "US 10Y Treasury Yield",
        "monthly",
        "percent",
        "policy_tightness",
        1,
    ),
    ("US.LIQUIDITY.FED_BALANCE_SHEET", "Fed Balance Sheet", "monthly", "index", "liquidity", 1),
    ("US.GROWTH.YIELD_CURVE_10Y2Y", "10Y minus 2Y Curve", "monthly", "percent", "growth", 1),
    ("US.RISK.VIX", "VIX", "monthly", "index", "risk", 1),
)


async def seed_state_fixture_data(engine: AsyncEngine) -> None:
    """Create a small, visibly-labelled state fixture for demo-mode only.

    The fixture is useful for a clean checkout and local UI review.  It uses a
    separate provider and ``data_mode='fixture'`` on every row, so production
    observed queries cannot see it.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        provider = await session.scalar(
            select(Provider).where(Provider.key == "worldstate_state_fixture")
        )
        if provider is None:
            provider = Provider(
                key="worldstate_state_fixture",
                name="WorldState state fixture",
                base_url="https://example.invalid",
                enabled=True,
                requires_credentials=False,
            )
            session.add(provider)
            await session.flush()
        entity = await session.scalar(select(EconomicEntity).where(EconomicEntity.iso3 == "USA"))
        if entity is None:
            entity = EconomicEntity(
                iso2="US",
                iso3="USA",
                name="United States",
                entity_type="country",
                currency="USD",
                timezone="America/New_York",
                metadata_json={},
            )
            session.add(entity)
            await session.flush()
        today = date.today().replace(day=1)
        for _index, (key, title, frequency, unit, dimension, orientation) in enumerate(
            _FIXTURE_STATE_SERIES
        ):
            series = await session.scalar(select(Series).where(Series.canonical_key == key))
            if series is None:
                series = Series(
                    provider_id=provider.id,
                    native_id=f"FIXTURE:{key}",
                    canonical_key=key,
                    entity_id=entity.id,
                    title=title,
                    description="Deterministic local fixture; not an official observation.",
                    frequency=frequency,
                    unit=unit,
                    observation_type="fixture_series",
                    source_url="https://example.invalid/worldstate-fixture",
                    release_key=None,
                    availability_method="fixture",
                    availability_precision="month",
                    default_transform="level",
                    active=True,
                    metadata_json={
                        "state_dimensions": [dimension],
                        "orientation": orientation,
                        "source_mode": "fixture",
                        "minimum_history": 6,
                    },
                )
                session.add(series)
                await session.flush()
            existing = await session.scalar(
                select(Observation.id)
                .where(Observation.series_id == series.id, Observation.data_mode == "fixture")
                .limit(1)
            )
            if existing is not None:
                continue
            for offset in range(24, 0, -1):
                period = (today - timedelta(days=30 * offset)).replace(day=1)
                # Smooth but distinct paths make the state direction readable.
                value = 100.0 + (24 - offset) * (0.8 if dimension == "growth" else 0.35)
                if dimension == "inflation":
                    value += math.sin(offset / 3.0) * 1.2
                elif dimension == "policy_tightness":
                    value = 4.4 - (24 - offset) * 0.025
                elif dimension == "liquidity":
                    value += (24 - offset) * 0.7
                elif dimension == "risk":
                    value = 18.0 + math.sin(offset / 2.0) * 3.0
                session.add(
                    Observation(
                        series_id=series.id,
                        period_start=period,
                        period_end=period,
                        value=round(value, 6),
                        raw_value=str(round(value, 6)),
                        vintage_date=period,
                        realtime_start=period,
                        realtime_end=None,
                        available_at=datetime.combine(period, datetime.min.time(), tzinfo=UTC),
                        availability_method="fixture",
                        availability_precision="month",
                        fetched_at=datetime.now(UTC),
                        is_preliminary=False,
                        is_revised=False,
                        data_mode="fixture",
                        quality_flags=["fixture", "not_official"],
                        source_hash=f"worldstate-state-fixture-{key}-{period.isoformat()}",
                    )
                )
