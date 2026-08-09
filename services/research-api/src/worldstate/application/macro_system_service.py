"""Transparent component dashboards for liquidity, dollar, rates and energy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import Observation, Provider, Series

DataMode = Literal["observed", "fixture", "all"]

_SYSTEMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "global_liquidity": (
        "Global Liquidity",
        (
            "US.LIQUIDITY.FED_BALANCE_SHEET",
            "US.LIQUIDITY.TREASURY_GENERAL_ACCOUNT",
            "US.LIQUIDITY.REVERSE_REPO",
            "US.LIQUIDITY.M2",
        ),
    ),
    "dollar_system": (
        "Dollar System",
        (
            "US.EXTERNAL.BROAD_DOLLAR",
            "EA.EXTERNAL.EURUSD",
            "US.POLICY.REAL_YIELD_10Y",
            "US.POLICY.TREASURY_2Y",
        ),
    ),
    "rates_system": (
        "Rates System",
        (
            "US.POLICY.FED_FUNDS_EFFECTIVE",
            "US.POLICY.TREASURY_2Y",
            "US.POLICY.TREASURY_10Y",
            "US.GROWTH.YIELD_CURVE_10Y2Y",
            "US.GROWTH.YIELD_CURVE_10Y3M",
        ),
    ),
    "energy_and_commodities": (
        "Energy & Commodities",
        (
            "US.INFLATION.WTI_CRUDE",
            "US.INFLATION.BRENT_CRUDE",
            "US.EXTERNAL.BROAD_DOLLAR",
        ),
    ),
}


async def build_macro_systems(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
) -> dict[str, Any]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.execute(
                select(Series, Provider).join(Provider, Provider.id == Series.provider_id)
            )
        ).all()
        by_key = {str(series.canonical_key): (series, provider) for series, provider in rows}
        systems: list[dict[str, Any]] = []
        for key, (title, components) in _SYSTEMS.items():
            component_rows: list[dict[str, Any]] = []
            for canonical_key in components:
                pair = by_key.get(canonical_key)
                if pair is None:
                    component_rows.append(
                        {"canonical_key": canonical_key, "status": "missing_catalog"}
                    )
                    continue
                series, provider = pair
                query = select(Observation).where(Observation.series_id == series.id)
                if data_mode != "all":
                    query = query.where(Observation.data_mode == data_mode)
                latest = await session.scalar(
                    query.order_by(Observation.period_start.desc()).limit(1)
                )
                component_rows.append(
                    {
                        "canonical_key": canonical_key,
                        "title": series.title,
                        "provider": provider.key,
                        "status": "available" if latest else "unavailable",
                        "latest_value": (
                            float(latest.value)
                            if latest and latest.value is not None
                            else None
                        ),
                        "latest_period": latest.period_start.isoformat() if latest else None,
                        "available_at": (
                            latest.available_at.isoformat()
                            if latest and latest.available_at
                            else None
                        ),
                        "data_mode": latest.data_mode if latest else data_mode,
                        "proxy": bool(series.metadata_json.get("is_proxy", False)),
                        "source_url": series.source_url,
                    }
                )
            available = [item for item in component_rows if item["status"] == "available"]
            systems.append(
                {
                    "key": key,
                    "title": title,
                    "status": "available" if available else "unavailable",
                    "coverage": round(len(available) / len(component_rows), 4)
                    if component_rows
                    else 0.0,
                    "components": component_rows,
                    "interpretation": "组件状态和相对变化，非单一因果评分。",
                }
            )
    return {
        "as_of": datetime.now(UTC).isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-macro-systems-v1",
        "systems": systems,
        "limitations": [
            "系统卡片只汇总已登记序列；缺失序列不会用代理或 fixture 补齐。",
            "组件之间的相关性不构成唯一因果关系。",
        ],
    }


__all__ = ["build_macro_systems"]
