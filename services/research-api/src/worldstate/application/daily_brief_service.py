"""Deterministic daily macro brief and top-change ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.analysis_orchestrator import list_releases
from worldstate.application.quality_resolver import resolve_quality_grade
from worldstate.application.world_state_service import build_world_state
from worldstate.db.models import DataQualityRecord, MarketBar, MarketInstrument, Observation, Series

DataMode = Literal["observed", "fixture", "all"]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _direction(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return "up" if value > 0.05 else "down" if value < -0.05 else "flat"


async def _market_confirmation(
    engine: AsyncEngine,
    *,
    data_mode: DataMode,
    cutoff: datetime,
    lookback: timedelta = timedelta(days=1),
) -> list[dict[str, Any]]:
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
        rows = (await session.execute(query.limit(5000))).all()
    grouped: dict[str, list[tuple[MarketBar, MarketInstrument, DataQualityRecord | None]]] = {}
    for bar, instrument, quality in rows:
        grouped.setdefault(str(instrument.canonical_key), []).append((bar, instrument, quality))
    result: list[dict[str, Any]] = []
    for key, items in grouped.items():
        latest, instrument, latest_quality = items[0]
        # Market confirmation uses valid observations, not elapsed wall-clock
        # time, so a weekend does not become a false 0.00% move.
        baseline = items[1][0] if len(items) > 1 else None
        latest_close = float(latest.close_value)
        baseline_close = float(baseline.close_value) if baseline is not None else None
        if baseline_close is None or baseline_close == 0:
            change = None
        else:
            change = latest_close / baseline_close - 1.0
        is_rate = "yield" in str(instrument.canonical_key) or "rate" in (
            instrument.instrument_type.lower()
        )
        result.append(
            {
                "instrument_key": key,
                "title": instrument.title,
                "symbol": instrument.symbol,
                "asset_class": instrument.asset_class,
                "is_proxy": instrument.is_proxy,
                "proxy_for": instrument.proxy_for,
                "latest": latest_close,
                "baseline": baseline_close,
                "change_percent": round((change or 0) * 100, 4) if change is not None else None,
                "change_value": (
                    round(latest_close - baseline_close, 6) if baseline_close is not None else None
                ),
                "change_unit": "bp" if is_rate else "percent",
                "baseline_timestamp": baseline.timestamp.isoformat() if baseline else None,
                "window_semantics": "valid_observation_lag",
                "direction": _direction(change),
                "timestamp": latest.timestamp.isoformat(),
                "provider": latest.provider_key,
                "data_mode": latest.data_mode,
                "quality": resolve_quality_grade(latest_quality),
                "quality_limitation": latest_quality.verification_notes
                if latest_quality
                else "No quality record was persisted for this observation.",
                "evidence_ids": [str(latest.id)],
            }
        )
    return sorted(result, key=lambda item: abs(item["change_percent"] or 0), reverse=True)


def _top_changes(
    state: dict[str, Any],
    releases: list[dict[str, Any]],
    markets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for dimension, payload in state["dimensions"].items():
        score = payload.get("score")
        if score is None:
            continue
        driver = (payload.get("top_drivers") or [None])[0]
        if driver is None:
            continue
        changes.append(
            {
                "what_changed": f"{dimension} 状态为 {payload.get('direction')}",
                "magnitude": score,
                "why_it_matters": (
                    f"{dimension} 的主要驱动是 {driver['title']}，当前变化只作为状态线索。"
                ),
                "related_state": dimension,
                "evidence": driver.get("evidence_ids", []),
                "source": driver.get("source_url"),
                "timestamp": state["as_of"],
                "confidence": payload.get("confidence", 0.0),
                "category": "state",
                "data_mode": state["data_mode"],
            }
        )
    for release in releases:
        surprise = release.get("surprise_score")
        if surprise is None:
            continue
        changes.append(
            {
                "what_changed": (
                    f"{release['title']} 发布：{release.get('classification') or '有结构化数据'}"
                ),
                "magnitude": float(surprise),
                "why_it_matters": (
                    "Actual 与共识的差异可能改变利率和风险资产定价，需结合事件窗口阅读。"
                ),
                "related_state": "inflation"
                if release.get("release_type") == "US_CPI"
                else "growth",
                "evidence": [str(release["id"])],
                "source": None,
                "timestamp": release.get("released_at") or release.get("scheduled_at"),
                "confidence": release.get("confidence") or 0.0,
                "category": "release",
                "data_mode": release.get("data_mode"),
            }
        )
    for market in markets[:12]:
        change = market.get("change_percent")
        if change is None:
            continue
        changes.append(
            {
                "what_changed": f"{market['title']} {market['direction']} {abs(change):.2f}%",
                "magnitude": change / 100.0,
                "why_it_matters": "这是跨资产确认线索，不单独构成宏观因果结论。",
                "related_state": "risk"
                if market.get("asset_class") in {"equity_index", "volatility"}
                else "external",
                "evidence": market.get("evidence_ids", []),
                "source": None,
                "timestamp": market.get("timestamp"),
                "confidence": 0.45,
                "category": "market",
                "data_mode": market.get("data_mode"),
            }
        )
    return sorted(changes, key=lambda item: abs(float(item.get("magnitude") or 0)), reverse=True)[
        :10
    ]


async def build_daily_brief(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    cutoff = (as_of or datetime.now(UTC)).astimezone(UTC)
    state = await build_world_state(engine, data_mode=data_mode, as_of=cutoff)
    rows = await list_releases(engine, limit=500, data_mode=data_mode)
    recent = [
        row
        for row in rows
        if row.get("released_at")
        and _aware(datetime.fromisoformat(str(row["released_at"]))) >= cutoff - timedelta(days=1)
        and _aware(datetime.fromisoformat(str(row["released_at"]))) <= cutoff
    ]
    upcoming = [
        row for row in rows if _aware(datetime.fromisoformat(str(row["scheduled_at"]))) > cutoff
    ][:12]
    markets = await _market_confirmation(engine, data_mode=data_mode, cutoff=cutoff)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        revised_rows = (
            await session.execute(
                select(Observation, Series)
                .join(Series, Series.id == Observation.series_id)
                .where(
                    Observation.is_revised.is_(True),
                    Observation.fetched_at >= cutoff - timedelta(days=30),
                    Observation.fetched_at <= cutoff,
                )
                .order_by(Observation.fetched_at.desc())
                .limit(50)
            )
        ).all()
    revisions = [
        {
            "series_key": str(series.canonical_key),
            "title": series.title,
            "period": observation.period_start.isoformat(),
            "value": float(observation.value) if observation.value is not None else None,
            "vintage": observation.vintage_date.isoformat(),
            "fetched_at": observation.fetched_at.isoformat(),
            "data_mode": observation.data_mode,
            "point_in_time": bool(series.metadata_json.get("point_in_time", False)),
            "evidence_ids": [str(observation.id)],
            "limitation": ("当前 provider 标记为修订；没有本地首发快照时，不能重建完整修订幅度。"),
        }
        for observation, series in revised_rows
        if data_mode == "all" or observation.data_mode == data_mode
    ]
    changes = _top_changes(state, recent, markets)
    return {
        "as_of": cutoff.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-daily-brief-v1",
        "world_state": state,
        "biggest_changes": changes,
        "macro_events": recent,
        "market_confirmation": markets,
        "revisions": revisions,
        "upcoming": upcoming,
        "watch_next": [
            "观察增长与通胀状态是否同向变化。",
            "检查收益率、美元与黄金/股指是否确认同一条传导链。",
            "下一次数据发布前确认 Consensus 是否在 T0 前捕获。",
        ],
        "ai_note": "本 Brief 完全由结构化数据和规则生成；AI 只可在此基础上解释。",
        "limitations": state["limitations"],
    }
