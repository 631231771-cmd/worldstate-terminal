"""PIT-filtered normalized observation matching; no provider/network dependencies."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import Observation, Series
from worldstate.reasoning.schema import EvidenceRule


async def load_series_evidence(
    engine: AsyncEngine, keys: set[str], mode: str, cutoff: datetime
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    async with async_sessionmaker(engine)() as session:
        series_rows = (
            await session.scalars(select(Series).where(Series.canonical_key.in_(keys)))
        ).all()
        for series in series_rows:
            rows = (
                await session.scalars(
                    select(Observation)
                    .where(
                        Observation.series_id == series.id,
                        Observation.data_mode == mode,
                        Observation.available_at <= cutoff,
                        Observation.fetched_at <= cutoff,
                        Observation.period_start <= cutoff.date(),
                        Observation.vintage_date <= cutoff.date(),
                        Observation.value.is_not(None),
                    )
                    .order_by(
                        Observation.period_start.desc(),
                        Observation.available_at.desc(),
                        Observation.id.desc(),
                    )
                )
            ).all()
            unique: dict[str, Any] = {}
            for row in rows:
                if row.value is None:
                    continue
                period = row.period_start.isoformat()
                if period not in unique:
                    unique[period] = {
                        "id": str(row.id),
                        "period": period,
                        "value": float(row.value),
                        "available_at": row.available_at.isoformat() if row.available_at else None,
                        "fetched_at": row.fetched_at.isoformat(),
                        "vintage_date": row.vintage_date.isoformat(),
                        "source_hash": row.source_hash,
                        "quality_flags": row.quality_flags,
                    }
            output[series.canonical_key] = {
                "title": series.title,
                "unit": series.unit,
                "frequency": series.frequency,
                "source_url": series.source_url,
                "metadata": series.metadata_json,
                "points": list(unique.values())[:157],
            }
    return output


def match_series(rule: EvidenceRule, datasets: dict[str, Any], cutoff: datetime) -> dict[str, Any]:
    dataset = datasets.get(str(rule.series_key), {})
    points = dataset.get("points", [])
    base: dict[str, Any] = {
        "rule_key": rule.key,
        "label": rule.label,
        "role": rule.role,
        "series_key": rule.series_key,
        "state": "missing",
        "evidence_ids": [],
        "source_url": dataset.get("source_url"),
        "transform": rule.transform,
        "point_in_time": bool(dataset.get("metadata", {}).get("point_in_time")),
        "proxy": bool(dataset.get("metadata", {}).get("is_proxy")),
        "limitation": dataset.get("metadata", {}).get("limitation"),
    }

    def missing(reason: str, message: str) -> dict[str, Any]:
        return {**base, "missing_reason": reason, "statement": f"{rule.label}：{message}"}

    if not points:
        return missing("series_missing_at_cutoff", "检查时点没有已获取的有效记录。")
    latest = points[0]
    age = (cutoff.date() - datetime.fromisoformat(latest["period"]).date()).days
    base.update(
        observed_at=latest["period"],
        age_days=age,
        latest_value=latest["value"],
        unit=dataset.get("unit"),
        sample_count=len(points),
    )
    if age > rule.max_age_days:
        return missing("series_stale", f"数据已过期（{age} 天）。")
    used = [latest]
    value = float(latest["value"])
    if rule.transform == "change":
        if len(points) < 2:
            return missing("comparison_missing", "缺少前一个有效观察期。")
        previous = points[1]
        gap = (
            datetime.fromisoformat(latest["period"]) - datetime.fromisoformat(previous["period"])
        ).days
        if gap > (10 if dataset.get("frequency") == "weekly" else 7):
            return missing("comparison_gap", "相邻观察期存在缺口，无法计算可靠变化。")
        used.append(previous)
        value -= float(previous["value"])
        if dataset.get("unit") == "percent":
            value *= 100
            base["unit"] = "bp"
    elif rule.transform == "percentile":
        history = points[1:157]
        base.update(sample_count=len(history), minimum_samples=rule.minimum_samples)
        if len(history) < rule.minimum_samples:
            return missing(
                "insufficient_percentile_history",
                f"历史只有 {len(history)} 期，至少需要 {rule.minimum_samples} 期。",
            )
        if max(p["value"] for p in history) == min(p["value"] for p in history):
            return missing("constant_percentile_history", "历史样本没有变异。")
        value = (
            100
            * (
                sum(p["value"] < value for p in history)
                + 0.5 * sum(p["value"] == value for p in history)
            )
            / len(history)
        )
        used += history
        base["unit"] = "percentile"
    state = "neutral"
    if rule.transform == "percentile":
        extreme = (
            value >= rule.minimum_absolute
            if rule.expected_direction == "up"
            else value <= 100 - rule.minimum_absolute
        )
        if extreme:
            state = "supporting"
    elif abs(value) >= rule.minimum_absolute and value != 0:
        state = (
            "supporting" if (value > 0) == (rule.expected_direction == "up") else "contradicting"
        )
    base.update(
        state=state,
        observed_value=value,
        evidence_ids=[p["id"] for p in used],
        inputs=used,
        missing_reason=None,
        statement=f"{rule.label}：{value:+.3f} {base['unit']}。"
        + ("仅作仓位风险提示，不推断机构动机。" if rule.role == "risk" else ""),
    )
    return base
