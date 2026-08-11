"""Capability-aware product projections for the terminal UI."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncEngine

from worldstate.application.capability_service import build_capability_inventory
from worldstate.application.daily_brief_service import build_daily_brief
from worldstate.application.event_product_service import build_event_product_detail
from worldstate.application.global_macro_service import build_global_macro
from worldstate.application.market_research_service import build_market_dashboard
from worldstate.application.release_queries import list_releases
from worldstate.application.state_history_service import list_world_state_snapshots

DataMode = Literal["observed", "fixture", "all"]
DIMENSION_LABELS = {
    "growth": "\u589e\u957f",
    "inflation": "\u901a\u80c0",
    "liquidity": "\u6d41\u52a8\u6027",
    "policy_tightness": "\u653f\u7b56\u7ea6\u675f",
    "credit": "\u4fe1\u7528",
    "risk": "\u98ce\u9669",
    "fiscal": "\u8d22\u653f",
    "external": "\u5916\u90e8",
}
MARKET_LABELS = {
    "gold_gc": "\u9ec4\u91d1",
    "silver_si": "\u767d\u94f6",
    "sp500_cash": "\u6807\u666e 500",
    "nasdaq100_cash": "\u7eb3\u65af\u8fbe\u514b 100",
    "vix_cash": "VIX",
    "ust2y_yield_context": "\u7f8e\u56fd 2Y",
    "ust5y_yield_context": "\u7f8e\u56fd 5Y",
    "ust10y_yield_context": "\u7f8e\u56fd 10Y",
    "ust30y_yield_context": "\u7f8e\u56fd 30Y",
    "ust3m_yield_context": "\u7f8e\u56fd 3M",
    "ust10y_real_yield_context": "\u7f8e\u56fd 10Y \u5b9e\u9645\u5229\u7387",
    "curve_2s10s_derived": "2s10s \u5229\u5dee",
    "curve_3m10y_derived": "3m10y \u5229\u5dee",
    "dollar_broad_context": "\u7f8e\u5143",
    "eurusd_context": "EUR/USD",
    "usdjpy_context": "USD/JPY",
    "usdcny_context": "USD/CNY",
    "wti_spot": "WTI \u539f\u6cb9",
    "brent_spot": "\u5e03\u4f26\u7279\u539f\u6cb9",
    "copper_spot": "\u94dc",
    "hy_spread_context": "\u7f8e\u56fd\u9ad8\u6536\u76ca\u5229\u5dee",
}
COUNTRY_LABELS = {
    "USA": "\u7f8e\u56fd",
    "CHN": "\u4e2d\u56fd",
    "EA19": "\u6b27\u5143\u533a",
    "JPN": "\u65e5\u672c",
    "GBR": "\u82f1\u56fd",
}

COUNTRY_MARKETS = {
    "USA": (
        "ust2y_yield_context",
        "ust10y_yield_context",
        "ust10y_real_yield_context",
        "dollar_broad_context",
        "sp500_cash",
        "nasdaq100_cash",
        "vix_cash",
        "hy_spread_context",
    ),
    "CHN": ("usdcny_context",),
    "EA19": ("eurusd_context",),
    "JPN": ("usdjpy_context",),
    "GBR": (),
}


def _capability_map(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["canonical_key"]): item for item in inventory.get("items", [])}


def _direction(value: Any) -> str:
    if value is None:
        return "unavailable"
    number = float(value)
    return "up" if number > 0 else "down" if number < 0 else "flat"


def _market_item(item: dict[str, Any], capabilities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = str(item.get("instrument_key"))
    capability = capabilities.get(key, {})
    is_rate = item.get("change_unit") == "bp" or (
        "yield" in key or "rate" in str(item.get("instrument_type", "")).lower()
    )
    change = item.get("change_value")
    if change is None and item.get("change_percent") is not None:
        change = float(item["change_percent"]) / 100.0
    display_change: float | None
    if is_rate and change is not None:
        display_change = round(float(change) * 100.0, 2)
        change_unit = "bp"
    else:
        display_change = (
            round(float(item["change_percent"]), 2)
            if item.get("change_percent") is not None
            else None
        )
        change_unit = "%"
    state = capability.get("capabilities", {}).get("CURRENT_STATE", {})
    freshness = capability.get("freshness", {})
    return {
        "key": key,
        "label": MARKET_LABELS.get(key, str(item.get("title") or key)),
        "symbol": item.get("symbol"),
        "asset_class": item.get("asset_class"),
        "value": item.get("latest"),
        "formatted_value": "—" if item.get("latest") is None else f"{float(item['latest']):,.3f}",
        "change": display_change,
        "change_unit": change_unit,
        "direction": _direction(display_change),
        "trend": item.get("direction", "unavailable"),
        "status": "available" if state.get("available") else "missing",
        "freshness": freshness.get("status", "MISSING"),
        "proxy": bool(item.get("is_proxy")),
        "derived": bool(item.get("is_derived")),
        "sparkline": item.get("sparkline", []),
        "chart_points": item.get("chart_points", []),
        "capabilities": capability.get("capabilities", {}),
        "details": {
            "provider": item.get("provider"),
            "canonical_key": key,
            "data_mode": item.get("data_mode"),
            "quality": item.get("quality_grade"),
            "limitation": item.get("quality_limitation") or item.get("limitation"),
            "timestamp": item.get("timestamp"),
            "granularity_seconds": item.get("granularity_seconds"),
            "derivation": item.get("derivation"),
            "continuity_status": item.get("continuity_status"),
            "continuity_segments": item.get("continuity_segments", []),
            "active_segment_rows": item.get("active_segment_rows"),
        },
    }


def _market_horizon(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a dashboard change into one explicit product unit.

    Rates are stored as level differences in percentage points and are exposed
    as basis points. Price-like assets use the already calculated percentage
    return. The UI must never infer this from an instrument key.
    """
    is_rate = item.get("change_unit") == "bp" or "yield" in str(item.get("instrument_key", ""))
    if is_rate:
        raw = item.get("change_value")
        value = round(float(raw) * 100.0, 4) if raw is not None else None
        unit = "bp"
    else:
        raw = item.get("change_percent")
        value = round(float(raw), 4) if raw is not None else None
        unit = "%"
    direction = _direction(value)
    return {"value": value, "unit": unit, "direction": direction}


def _country_projection(country: dict[str, Any]) -> dict[str, Any]:
    dimensions = country.get("dimensions", {})
    available = [key for key, value in dimensions.items() if value.get("score") is not None]
    stale_dimensions = [
        key for key in available if (dimensions[key].get("freshness") or 0.0) < 0.3679
    ]
    if available and len(stale_dimensions) == len(available):
        status = "stale"
    elif stale_dimensions:
        status = "partial"
    else:
        status = country.get("status", "missing")
    limitations = list(country.get("limitations", []))
    if stale_dimensions:
        limitations.append(
            "数据较旧：" + "、".join(DIMENSION_LABELS.get(key, key) for key in stale_dimensions)
        )
    return {
        "key": country.get("iso3"),
        "label": COUNTRY_LABELS.get(str(country.get("iso3")), country.get("name")),
        "status": status,
        "available_dimensions": available,
        "dimensions": {
            key: {
                "label": DIMENSION_LABELS.get(key, key),
                "score": value.get("score"),
                "direction": value.get("direction", "unavailable"),
                "momentum": value.get("momentum"),
                "confidence": value.get("confidence", 0.0),
                "coverage": value.get("coverage", 0.0),
                "freshness": value.get("freshness"),
                "drivers": value.get("top_drivers", [])[:3],
                "missing": value.get("missing_inputs", []),
            }
            for key, value in dimensions.items()
        },
        "latest_data_at": country.get("latest_data_at"),
        "details": {
            "entity_registered": country.get("entity_registered"),
            "source": country.get("source"),
            "limitations": limitations,
        },
    }


def _change_projection(item: dict[str, Any]) -> dict[str, Any]:
    raw_what = str(item.get("what_changed") or "")
    category = str(item.get("category") or "research")
    inferred = next((key for key in DIMENSION_LABELS if key in raw_what), None)
    if inferred:
        category = inferred
        raw_what = raw_what.replace(inferred, DIMENSION_LABELS[inferred])
    raw_why = item.get("why_it_matters")
    if isinstance(raw_why, str):
        for key, label in DIMENSION_LABELS.items():
            raw_why = raw_why.replace(key, label)
        # The brief often prefixes the explanation with the same dimension
        # label already rendered as the change headline.  Keep the sentence
        # readable in the product projection instead of repeating it in the
        # Today button.
        for label in DIMENSION_LABELS.values():
            prefix = f"{label} "
            if raw_why.startswith(prefix):
                raw_why = raw_why[len(prefix) :]
                break
    return {
        "what": raw_what,
        "why": f" {raw_why}" if isinstance(raw_why, str) and raw_why else raw_why,
        "magnitude": item.get("magnitude"),
        "direction": _direction(item.get("magnitude")),
        "confidence": item.get("confidence", 0.0),
        "category": category,
        "category_label": DIMENSION_LABELS.get(category, category),
        "details_ref": f"/v2/product/{category}",
    }


async def build_today_projection(
    engine: AsyncEngine, *, data_mode: DataMode = "observed", as_of: datetime | None = None
) -> dict[str, Any]:
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    brief, markets, global_macro, inventory = await _load_projection_sources(
        engine, data_mode=data_mode, as_of=now
    )
    capability_map = _capability_map(inventory)
    dimensions = brief.get("world_state", {}).get("dimensions", {})
    macro_snapshot = [
        {
            "key": key,
            "label": DIMENSION_LABELS.get(key, key),
            "score": value.get("score"),
            "direction": value.get("direction", "unavailable"),
            "momentum": value.get("momentum"),
            "confidence": value.get("confidence", 0.0),
            "coverage": value.get("coverage", 0.0),
            "status": "available" if value.get("score") is not None else "missing",
            "drivers": value.get("top_drivers", [])[:3],
            "details_ref": f"/v2/product/macro/{key}",
        }
        for key, value in dimensions.items()
    ]
    changes = [_change_projection(item) for item in brief.get("biggest_changes", [])[:5]]
    upcoming = sorted(
        [item for item in brief.get("upcoming", []) if item.get("scheduled_at")],
        key=lambda item: str(item["scheduled_at"]),
    )[:6]
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-product-v1",
        "macro_snapshot": macro_snapshot,
        "markets": [_market_item(item, capability_map) for item in markets.get("items", [])],
        "what_changed": changes,
        "upcoming": upcoming,
        "latest_research": brief.get("macro_events", [])[:5],
        "global": [_country_projection(country) for country in global_macro.get("countries", [])],
        "watch_next": brief.get("watch_next", [])[:6],
        "capability_summary": inventory.get("summary", {}),
        "limitations": brief.get("limitations", []) + inventory.get("limitations", []),
    }


async def build_markets_projection(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Return all market horizons in one product response."""
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    horizons: tuple[Literal["1d", "1w", "1m", "3m"], ...] = ("1d", "1w", "1m", "3m")
    dashboard = await build_market_dashboard(
        engine, data_mode=data_mode, horizon="1d", as_of=now
    )
    capability_map: dict[str, dict[str, Any]] = {}
    for item in dashboard.get("items", []):
        key = str(item.get("instrument_key"))
        timestamp_text = item.get("timestamp")
        latest_at = (
            datetime.fromisoformat(str(timestamp_text).replace("Z", "+00:00")).astimezone(UTC)
            if timestamp_text
            else None
        )
        stale = latest_at is not None and (now - latest_at).days > 7
        is_daily = int(item.get("granularity_seconds") or 0) >= 86400
        is_intraday = int(item.get("granularity_seconds") or 0) <= 60
        capability_map[key] = {
            "capabilities": {
                "CURRENT_STATE": {"available": True, "status": "AVAILABLE", "reason": None},
                "DAILY_MARKET": {
                    "available": is_daily,
                    "status": "AVAILABLE" if is_daily else "MISSING",
                    "reason": None if is_daily else "No daily bar is stored.",
                },
                "EVENT_INTRADAY": {
                    "available": is_intraday,
                    "status": "AVAILABLE" if is_intraday else "MISSING",
                    "reason": None if is_intraday else "Daily context is not event intraday data.",
                },
            },
            "freshness": {
                "status": "STALE" if stale else "AVAILABLE",
                "reason": "Latest bar is more than seven days old." if stale else None,
            },
        }
    by_key: dict[str, dict[str, Any]] = {}
    for item in dashboard.get("items", []):
        key = str(item.get("instrument_key"))
        by_key[key] = _market_item(item, capability_map)
        changes = item.get("horizon_changes", {})
        by_key[key]["horizons"] = {
            horizon: _market_horizon(
                {
                    **item,
                    **(changes.get(horizon, {}) if isinstance(changes, dict) else {}),
                }
            )
            for horizon in horizons
        }
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-markets-v1",
        "items": list(by_key.values()),
        "limitations": dashboard.get("limitations", []),
    }


async def _load_projection_sources(
    engine: AsyncEngine, *, data_mode: DataMode, as_of: datetime
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    import asyncio

    return await asyncio.gather(
        build_daily_brief(engine, data_mode=data_mode, as_of=as_of),
        build_market_dashboard(engine, data_mode=data_mode, horizon="1d", as_of=as_of),
        build_global_macro(engine, data_mode=data_mode, as_of=as_of),
        build_capability_inventory(engine, data_mode=data_mode, as_of=as_of),
    )


async def build_macro_projection(
    engine: AsyncEngine, *, data_mode: DataMode = "observed", as_of: datetime | None = None
) -> dict[str, Any]:
    """Stable macro product projection; canonical keys stay in the payload."""
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    payload = await build_global_macro(engine, data_mode=data_mode, as_of=now)
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-macro-v1",
        "countries": [_country_projection(item) for item in payload.get("countries", [])],
        "comparison": payload.get("comparison", []),
        "divergence": payload.get("divergence", []),
        "context_cards": payload.get("context_cards", []),
        "limitations": payload.get("limitations", []),
    }


async def build_country_projection(
    engine: AsyncEngine,
    country_key: str,
    *,
    data_mode: DataMode = "observed",
    dimension: str | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    """Return one honest country research projection.

    Global country state is computed from the existing point-in-time signal
    pipeline.  Daily state snapshots currently describe the US World State,
    so they are never relabelled as history for another country.
    """
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    payload = await build_global_macro(engine, data_mode=data_mode, as_of=now)
    raw_country = next(
        (item for item in payload.get("countries", []) if item.get("iso3") == country_key),
        None,
    )
    if raw_country is None:
        return None
    country = _country_projection(raw_country)
    selected_raw = country["dimensions"].get(dimension) if dimension else None
    selected_dimension = (
        {"key": dimension, **selected_raw} if isinstance(selected_raw, dict) else None
    )

    key_series: list[dict[str, Any]] = []
    seen_series: set[str] = set()
    for dimension_key, value in country["dimensions"].items():
        for driver in value.get("drivers", []):
            series_key = str(driver.get("series_key") or "")
            if not series_key or series_key in seen_series:
                continue
            seen_series.add(series_key)
            key_series.append(
                {
                    "key": series_key,
                    "title": driver.get("title") or series_key,
                    "dimension": dimension_key,
                    "dimension_label": DIMENSION_LABELS.get(dimension_key, dimension_key),
                    "latest_value": driver.get("latest_value"),
                    "period_start": driver.get("period_start"),
                    "score": driver.get("score"),
                    "momentum": driver.get("momentum"),
                    "quality": driver.get("quality"),
                    "data_mode": driver.get("data_mode"),
                    "source_url": driver.get("source_url"),
                }
            )

    markets_payload = await build_markets_projection(engine, data_mode=data_mode, as_of=now)
    related_keys = set(COUNTRY_MARKETS.get(country_key, ()))
    related_markets = [
        item for item in markets_payload.get("items", []) if item.get("key") in related_keys
    ]

    # MacroRelease currently covers US CPI/NFP/FOMC.  Do not present those
    # releases as a calendar for China, Japan, the euro area, or the UK.
    releases = await list_releases(engine, limit=500, data_mode=data_mode)
    country_releases = releases if country_key == "USA" else []
    recent_releases = sorted(
        (item for item in country_releases if item.get("status") == "released"),
        key=lambda item: str(item.get("released_at") or item.get("scheduled_at") or ""),
        reverse=True,
    )[:6]
    upcoming_releases = sorted(
        (
            item
            for item in country_releases
            if item.get("status") == "scheduled"
            and str(item.get("scheduled_at") or "") >= now.isoformat()
        ),
        key=lambda item: str(item.get("scheduled_at") or ""),
    )[:6]

    state_history: list[dict[str, Any]] = []
    history_scope = "unavailable"
    if country_key == "USA":
        history_scope = "us_world_state"
        snapshots = await list_world_state_snapshots(engine, data_mode=data_mode, limit=365)
        for snapshot in reversed(snapshots):
            dimensions = snapshot.get("dimensions") or {}
            if dimension:
                state = dimensions.get(dimension) or {}
                if state.get("score") is None:
                    continue
                state_history.append(
                    {
                        "date": snapshot["snapshot_date"],
                        "value": state["score"],
                        "direction": state.get("direction"),
                        "confidence": state.get("confidence"),
                        "methodology_version": snapshot.get("methodology_version"),
                    }
                )

    comparisons: list[dict[str, Any]] = []
    if dimension:
        for item in payload.get("countries", []):
            state = item.get("dimensions", {}).get(dimension, {})
            if state.get("score") is None:
                continue
            comparisons.append(
                {
                    "country_key": item.get("iso3"),
                    "country_label": COUNTRY_LABELS.get(
                        str(item.get("iso3")), str(item.get("name"))
                    ),
                    "score": state.get("score"),
                    "direction": state.get("direction"),
                    "coverage": state.get("coverage"),
                }
            )
        comparisons.sort(key=lambda item: float(item["score"]), reverse=True)

    limitations = list(country.get("details", {}).get("limitations", []))
    if country_key != "USA":
        limitations.append("该经济体尚未积累独立的每日状态快照；不会借用美国历史。")
        limitations.append("当前正式事件日历仅覆盖美国 CPI、非农与 FOMC。")
    elif dimension and not state_history:
        limitations.append("该维度尚无可展示的真实每日状态快照。")
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-country-v1",
        "country": country,
        "selected_dimension": selected_dimension,
        "key_series": key_series,
        "markets": related_markets,
        "recent_releases": recent_releases,
        "upcoming_releases": upcoming_releases,
        "state_history": state_history,
        "history_scope": history_scope,
        "comparisons": comparisons,
        "limitations": limitations,
    }


async def build_events_projection(
    engine: AsyncEngine, *, data_mode: DataMode = "observed", limit: int = 500
) -> dict[str, Any]:
    """Event workflow projection with clean labels and status metadata."""
    items = await list_releases(engine, limit=limit, data_mode=data_mode)
    now = datetime.now(UTC)

    def scheduled(item: dict[str, Any]) -> datetime:
        return datetime.fromisoformat(str(item["scheduled_at"]).replace("Z", "+00:00")).astimezone(
            UTC
        )

    def released(item: dict[str, Any]) -> datetime:
        value = item.get("released_at") or item.get("scheduled_at")
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)

    upcoming = sorted(
        (item for item in items if item.get("status") == "scheduled" and scheduled(item) >= now),
        key=scheduled,
    )
    recent = sorted(
        (item for item in items if item.get("status") == "released"), key=released, reverse=True
    )
    completed = [
        item
        for item in items
        if item.get("analysis_status") == "completed"
        and item.get("reproducibility_status") == "complete"
    ]
    default_item = (
        sorted(completed, key=released, reverse=True)[0]
        if completed
        else recent[0]
        if recent
        else upcoming[0]
        if upcoming
        else None
    )
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-events-v1",
        "items": items,
        "upcoming": upcoming,
        "recent": recent,
        "default_event_id": default_item.get("id") if default_item else None,
        "limitations": [
            "Minute reaction analysis is available only where eligible observed bars exist.",
            "Consensus is eligible only when captured before the release timestamp.",
        ],
    }


async def build_event_detail_projection(
    engine: AsyncEngine,
    release_id: str,
    *,
    data_mode: DataMode = "observed",
) -> dict[str, Any] | None:
    """Return a product workflow projection while retaining Event Lab compatibility."""
    return await build_event_product_detail(engine, release_id, data_mode=data_mode)


__all__ = [
    "build_country_projection",
    "build_event_detail_projection",
    "build_events_projection",
    "build_macro_projection",
    "build_markets_projection",
    "build_today_projection",
]
