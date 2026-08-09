"""Small, honest global macro layer built from existing entity/series data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import EconomicEntity, Observation, Series

DataMode = Literal["observed", "fixture", "all"]

_COUNTRIES = (
    ("USA", "美国", "US"),
    ("CHN", "中国", "CN"),
    ("EA19", "欧元区", "EA"),
    ("JPN", "日本", "JP"),
    ("GBR", "英国", "GB"),
)


async def build_global_macro(
    engine: AsyncEngine, *, data_mode: DataMode = "observed"
) -> dict[str, Any]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        entities = {
            str(row.iso3): row for row in (await session.scalars(select(EconomicEntity))).all()
        }
        rows = (
            await session.execute(
                select(Series, EconomicEntity)
                .join(EconomicEntity, EconomicEntity.id == Series.entity_id)
                .where(Series.active.is_(True))
            )
        ).all()
        result: list[dict[str, Any]] = []
        for iso3, title, iso2 in _COUNTRIES:
            entity = entities.get(iso3)
            series_rows = [
                (series, row_entity) for series, row_entity in rows if row_entity.iso3 == iso3
            ]
            dimensions: dict[str, dict[str, Any]] = {}
            latest_at: datetime | None = None
            for series, _ in series_rows:
                query = (
                    select(Observation)
                    .where(Observation.series_id == series.id)
                    .order_by(Observation.period_start.desc())
                    .limit(1)
                )
                if data_mode != "all":
                    query = query.where(Observation.data_mode == data_mode)
                observation = await session.scalar(query)
                if observation is None:
                    continue
                for dimension in series.metadata_json.get("state_dimensions", []):
                    dimensions[str(dimension)] = {
                        "value": float(observation.value)
                        if observation.value is not None
                        else None,
                        "period": observation.period_start.isoformat(),
                        "provider": "series_catalog",
                        "data_mode": observation.data_mode,
                        "quality": "A" if observation.data_mode != "fixture" else "C",
                    }
                if observation.available_at is not None:
                    candidate = (
                        observation.available_at.replace(tzinfo=UTC)
                        if observation.available_at.tzinfo is None
                        else observation.available_at.astimezone(UTC)
                    )
                    latest_at = max(latest_at, candidate) if latest_at else candidate
            result.append(
                {
                    "iso3": iso3,
                    "iso2": iso2,
                    "name": title,
                    "status": "available" if dimensions else "unavailable",
                    "dimensions": dimensions,
                    "latest_data_at": latest_at.isoformat() if latest_at else None,
                    "data_mode": data_mode,
                    "source": "WorldState Series/Observation catalog",
                    "limitations": []
                    if dimensions
                    else ["当前没有该经济体的点时 observed 序列；不会用新闻或 fixture 补齐。"],
                    "entity_registered": entity is not None,
                }
            )
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-global-macro-v1",
        "countries": result,
        "context_cards": [
            {
                "key": "global_liquidity",
                "title": "全球流动性",
                "status": "framework",
                "components": ["Fed", "ECB", "BoJ", "PBoC", "Treasury"],
            },
            {
                "key": "rates_system",
                "title": "利率系统",
                "status": "partial",
                "components": ["US curve", "real yield", "central-bank rates"],
            },
            {
                "key": "dollar_system",
                "title": "美元系统",
                "status": "partial",
                "components": ["broad USD", "major FX", "dollar liquidity"],
            },
            {
                "key": "energy_and_credit",
                "title": "能源与信用",
                "status": "partial",
                "components": ["WTI", "Brent", "HY", "IG"],
            },
        ],
        "limitations": [
            "全球层第一版只展示已进入 WorldState Series/Observation 的数据。",
            "未注册或没有真实观测的经济体明确显示 unavailable，不以标签冒充状态。",
        ],
    }
