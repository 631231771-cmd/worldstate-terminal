"""Global macro comparison built only from persisted Series/Observation data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.world_state_service import (
    SeriesSignal,
    aggregate_dimension,
    calculate_signal,
)
from worldstate.db.models import EconomicEntity, Observation, Provider, Series

DataMode = Literal["observed", "fixture", "all"]

_COUNTRIES = (
    ("USA", "美国", "US"),
    ("CHN", "中国", "CN"),
    ("EA19", "欧元区", "EA"),
    ("JPN", "日本", "JP"),
    ("GBR", "英国", "GB"),
)
_DIMENSIONS = (
    "growth",
    "inflation",
    "policy_tightness",
    "liquidity",
    "credit",
    "risk",
    "external",
    "fiscal",
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def build_global_macro(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    cutoff = _aware(as_of) or datetime.now(UTC)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        entities = {
            str(row.iso3): row for row in (await session.scalars(select(EconomicEntity))).all()
        }
        rows = (
            await session.execute(
                select(Series, Provider)
                .join(Provider, Provider.id == Series.provider_id)
                .where(Series.active.is_(True))
            )
        ).all()
        countries: list[dict[str, Any]] = []
        for iso3, title, iso2 in _COUNTRIES:
            entity_series = [
                (series, provider)
                for series, provider in rows
                if str(series.canonical_key).startswith(f"{iso3}.")
                or (iso3 == "EA19" and str(series.canonical_key).startswith("EA."))
            ]
            by_dimension: dict[str, list[SeriesSignal]] = {key: [] for key in _DIMENSIONS}
            latest_data_at: datetime | None = None
            for series, provider in entity_series:
                query = select(Observation).where(
                    Observation.series_id == series.id,
                    Observation.available_at.is_not(None),
                    Observation.available_at <= cutoff,
                    Observation.vintage_date <= cutoff.date(),
                )
                if data_mode != "all":
                    query = query.where(Observation.data_mode == data_mode)
                observations = list(
                    (
                        await session.scalars(
                            query.order_by(Observation.period_start).limit(240)
                        )
                    ).all()
                )
                dimensions = [
                    str(item)
                    for item in (series.metadata_json or {}).get("state_dimensions", [])
                    if str(item) in _DIMENSIONS
                ]
                if not observations or not dimensions:
                    continue
                values = [float(item.value) for item in observations if item.value is not None]
                orientation = int((series.metadata_json or {}).get("orientation") or 1)
                score, momentum, missing = calculate_signal(
                    values,
                    orientation=orientation,
                    transform=str(series.metadata_json.get("default_transform", "level")),
                    minimum_history=max(3, int(series.metadata_json.get("minimum_history", 3))),
                )
                latest = observations[-1]
                available_at = _aware(latest.available_at)
                if available_at is not None:
                    latest_data_at = (
                        max(latest_data_at, available_at) if latest_data_at else available_at
                    )
                signal = SeriesSignal(
                    series_key=series.canonical_key,
                    title=series.title,
                    dimension=dimensions[0],
                    score=score,
                    momentum=momentum,
                    latest_value=float(latest.value) if latest.value is not None else None,
                    period_start=latest.period_start,
                    available_at=available_at,
                    observation_count=len(observations),
                    provider_key=provider.key,
                    source_url=series.source_url,
                    data_mode=latest.data_mode,
                    quality="C" if latest.data_mode == "fixture" else "B",
                    missing_reason=missing,
                    evidence_ids=(f"observation:{latest.id}",),
                )
                for dimension in dimensions:
                    by_dimension[dimension].append(
                        signal if dimension == signal.dimension else SeriesSignal(
                            **{**signal.__dict__, "dimension": dimension}
                        )
                    )
            dimensions_result = {
                dimension: aggregate_dimension(by_dimension[dimension])
                for dimension in _DIMENSIONS
            }
            available_dimensions = [
                key for key, value in dimensions_result.items() if value.get("score") is not None
            ]
            countries.append(
                {
                    "iso3": iso3,
                    "iso2": iso2,
                    "name": title,
                    "status": "available" if available_dimensions else "unavailable",
                    "dimensions": dimensions_result,
                    "available_dimensions": available_dimensions,
                    "latest_data_at": latest_data_at.isoformat() if latest_data_at else None,
                    "data_mode": data_mode,
                    "entity_registered": iso3 in entities,
                    "source": "WorldState Series/Observation catalog",
                    "limitations": []
                    if available_dimensions
                    else ["该经济体没有符合 point-in-time 条件的 observed 序列"],
                }
            )
    comparison = [
        {
            "dimension": dimension,
            "countries": [
                {
                    "iso3": item["iso3"],
                    "name": item["name"],
                    "score": item["dimensions"][dimension]["score"],
                    "direction": item["dimensions"][dimension]["direction"],
                }
                for item in countries
            ],
        }
        for dimension in _DIMENSIONS
    ]
    divergence: list[dict[str, Any]] = []
    for dimension in _DIMENSIONS:
        usable = [
            (item["iso3"], item["name"], item["dimensions"][dimension].get("score"))
            for item in countries
            if item["dimensions"][dimension].get("score") is not None
        ]
        if len(usable) >= 2:
            high = max(usable, key=lambda item: float(item[2]))
            low = min(usable, key=lambda item: float(item[2]))
            divergence.append(
                {
                    "dimension": dimension,
                    "stronger": {"iso3": high[0], "name": high[1], "score": high[2]},
                    "weaker": {"iso3": low[0], "name": low[1], "score": low[2]},
                    "spread": round(float(high[2]) - float(low[2]), 4),
                    "interpretation": "相对状态差异，不是单一因果结论",
                }
            )
    available_keys = {key for item in countries for key in item["available_dimensions"]}
    return {
        "as_of": cutoff.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-global-macro-v2",
        "countries": countries,
        "comparison": comparison,
        "divergence": sorted(divergence, key=lambda item: item["spread"], reverse=True),
        "context_cards": [
            {
                "key": "global_liquidity",
                "title": "全球流动性",
                "status": "available" if "liquidity" in available_keys else "framework",
                "components": ["Fed", "ECB", "BoJ", "PBoC", "Treasury"],
            },
            {
                "key": "rates_system",
                "title": "利率系统",
                "status": "available" if "policy_tightness" in available_keys else "partial",
                "components": ["US curve", "real yield", "central-bank rates"],
            },
            {
                "key": "dollar_system",
                "title": "美元系统",
                "status": "available" if "external" in available_keys else "partial",
                "components": ["broad USD", "major FX", "rate differentials"],
            },
            {
                "key": "energy_and_credit",
                "title": "能源与信用",
                "status": (
                    "available"
                    if {"credit", "risk"}.intersection(available_keys)
                    else "partial"
                ),
                "components": ["WTI", "Brent", "HY", "IG"],
            },
        ],
        "limitations": [
            "跨经济体比较只使用已有 Series/Observation，缺失、过期或未配置的数据不会被补齐。",
            "divergence 描述相对状态差异，不等于资产价格的唯一因果解释。",
        ],
    }


__all__ = ["build_global_macro"]
