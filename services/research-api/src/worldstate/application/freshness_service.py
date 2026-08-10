"""Series-level data freshness and coverage classification."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import Observation, Provider, Series

DataMode = Literal["observed", "fixture", "all"]


def _status(
    *,
    latest: Observation | None,
    series: Series,
    data_mode: str,
    now: datetime,
) -> tuple[str, float | None, str | None]:
    if latest is None:
        return ("FIXTURE" if data_mode == "fixture" else "MISSING"), None, "no observation"
    if data_mode == "fixture" or latest.data_mode == "fixture":
        return "FIXTURE", 0.0, "fixture observation"
    if latest.available_at is None:
        return "PARTIAL", None, "observation has no available_at"
    available_at = (
        latest.available_at.replace(tzinfo=UTC)
        if latest.available_at.tzinfo is None
        else latest.available_at.astimezone(UTC)
    )
    retrieval_age_days = max(0.0, (now - available_at).total_seconds() / 86400)
    period_age_days = max(0, (now.date() - latest.period_start).days)
    half_life = float((series.metadata_json or {}).get("freshness_half_life_days") or 30.0)
    # Retrieval can be recent even when the latest covered period is old.  Use
    # the older of those two clocks so a newly fetched stale monthly series is
    # never presented as live.
    effective_age_days = max(retrieval_age_days, float(period_age_days))
    freshness = math.exp(-effective_age_days / max(1.0, half_life))
    reason = (
        "latest observation period is older than the freshness threshold"
        if effective_age_days > half_life
        else None
    )
    return ("LIVE" if reason is None else "STALE"), freshness, reason


def _available_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _age_days(value: datetime | None, now: datetime) -> float | None:
    available = _available_at(value)
    return max(0.0, (now - available).total_seconds() / 86400) if available else None


async def build_data_freshness(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    now = as_of or datetime.now(UTC)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        query = (
            select(Series, Provider)
            .join(Provider, Provider.id == Series.provider_id)
            .where(Series.active.is_(True))
            .order_by(Series.canonical_key)
        )
        rows = (await session.execute(query)).all()
        items: list[dict[str, Any]] = []
        for series, provider in rows:
            observation_query = select(Observation).where(Observation.series_id == series.id)
            if data_mode != "all":
                observation_query = observation_query.where(Observation.data_mode == data_mode)
            latest = await session.scalar(
                observation_query.order_by(
                    Observation.period_start.desc(), Observation.id.desc()
                ).limit(1)
            )
            status, freshness, reason = _status(
                latest=latest, series=series, data_mode=data_mode, now=now
            )
            retrieval_age_days = _age_days(latest.available_at if latest else None, now)
            period_age_days = (
                max(0, (now.date() - latest.period_start).days) if latest else None
            )
            items.append(
                {
                    "canonical_key": series.canonical_key,
                    "title": series.title,
                    "provider": provider.key,
                    "entity": series.metadata_json.get("entity")
                    or series.canonical_key.split(".")[0],
                    "frequency": series.frequency,
                    "unit": series.unit,
                    "data_mode": data_mode,
                    "status": status,
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
                    "fetched_at": latest.fetched_at.isoformat() if latest else None,
                    "age_days": max(
                        item
                        for item in (retrieval_age_days, period_age_days)
                        if item is not None
                    )
                    if latest
                    else None,
                    "retrieval_age_days": retrieval_age_days,
                    "period_age_days": period_age_days,
                    "freshness_score": round(freshness, 4) if freshness is not None else None,
                    "stale_threshold_days": float(
                        (series.metadata_json or {}).get("freshness_half_life_days") or 30.0
                    ),
                    "quality_flags": list(latest.quality_flags) if latest else [],
                    "source_url": series.source_url,
                    "reason": reason,
                    "state_dimensions": list(series.metadata_json.get("state_dimensions") or []),
                }
            )
    counts: dict[str, int] = {}
    for item in items:
        status = str(item["status"])
        counts[status] = counts.get(status, 0) + 1
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "items": items,
        "summary": counts,
        "methodology_version": "wst-freshness-v1",
        "limitations": [
            "LIVE/STALE uses catalog freshness_half_life_days, not a provider release guarantee.",
            "Provider-specific blocked states are reported separately by /v2/data/providers.",
        ],
    }


__all__ = ["build_data_freshness"]
