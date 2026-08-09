"""Point-in-time surprise calculations with explicit statistical fallbacks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from statistics import mean, pstdev
from typing import cast

from worldstate.event_engine.types import (
    BundleSurprise,
    HistoricalSurpriseObservation,
    IndicatorInput,
    IndicatorSurprise,
)

MIN_Z_SCORE_SAMPLE = 20
SURPRISE_METHOD_VERSION = "surprise-v0.4"
REVISION_DOMINANCE_RATIO = 1.25
MIN_COMPARABLE_REVISION_COMPONENTS = 2

CPI_KEYS = ("headline_mom", "headline_yoy", "core_mom", "core_yoy")
SURPRISE_TOLERANCE = {
    "headline_mom": 0.025,
    "headline_yoy": 0.05,
    "core_mom": 0.025,
    "core_yoy": 0.05,
    "nonfarm_payrolls": 20.0,
    "unemployment_rate": 0.05,
    "average_hourly_earnings_mom": 0.025,
    "average_hourly_earnings_yoy": 0.05,
    "labor_force_participation": 0.05,
    "fed_funds_lower": 0.125,
    "fed_funds_upper": 0.125,
    "statement_tone_score": 0.1,
    "press_conference_tone_score": 0.1,
}


def _sign(value: float | None, tolerance: float = 1e-12) -> int:
    if value is None or abs(value) <= tolerance:
        return 0
    return 1 if value > 0 else -1


def _direction(oriented: float | None, tolerance: float) -> str:
    sign = _sign(oriented, tolerance)
    return "hot" if sign > 0 else "cold" if sign < 0 else "in_line"


def _history_values(
    historical_raw: Iterable[float | HistoricalSurpriseObservation | tuple[datetime, float]],
    *,
    current_release_at: datetime | None,
    hotter_when_higher: bool,
) -> tuple[list[float], datetime | None, bool]:
    values: list[float] = []
    cutoff_seen = False
    for item in historical_raw:
        release_at: datetime | None = None
        raw: float
        if isinstance(item, HistoricalSurpriseObservation):
            release_at, raw = item.released_at, item.raw_surprise
        elif isinstance(item, tuple):
            release_at, raw = item
        else:
            raw = item
        # Untimestamped records are only accepted for legacy direct calculation.
        # Production callers must pass a release cutoff and timestamped records.
        if current_release_at is not None:
            if release_at is None:
                continue
            cutoff_seen = True
            if release_at >= current_release_at:
                continue
        if raw == raw:
            values.append(float(raw) * (1 if hotter_when_higher else -1))
    return values, current_release_at, cutoff_seen


def calculate_indicator_surprise(
    indicator: IndicatorInput,
    *,
    historical_raw: Iterable[float | HistoricalSurpriseObservation | tuple[datetime, float]]
    | None = None,
    current_release_at: datetime | None = None,
) -> IndicatorSurprise:
    """Calculate raw, threshold-scaled, and (only when valid) z-score surprise."""
    history, cutoff, timestamped = _history_values(
        historical_raw or (),
        current_release_at=current_release_at,
        hotter_when_higher=indicator.hotter_when_higher,
    )
    revision = (
        indicator.revised_previous - indicator.previous
        if indicator.revised_previous is not None and indicator.previous is not None
        else None
    )
    tolerance = SURPRISE_TOLERANCE.get(indicator.key, 1e-9)
    if indicator.actual is None or indicator.consensus is None:
        return IndicatorSurprise(
            indicator.key,
            None,
            None,
            None,
            None,
            None,
            "missing",
            revision,
            len(history),
            None,
            None,
            cutoff,
            "missing",
            "actual_or_consensus_missing",
        )
    raw = indicator.actual - indicator.consensus
    oriented = float(raw) * (1 if indicator.hotter_when_higher else -1)
    relative = (
        float(raw / abs(indicator.consensus))
        if abs(indicator.consensus) > Decimal("0.000000001")
        else None
    )
    threshold = oriented / tolerance
    history_mean = mean(history) if history else None
    history_std = pstdev(history) if len(history) >= MIN_Z_SCORE_SAMPLE else None
    unavailable: str | None = None
    surprise_z: float | None = None
    if current_release_at is not None and historical_raw and not timestamped:
        unavailable = "point_in_time_history_missing_timestamps"
    elif len(history) < MIN_Z_SCORE_SAMPLE:
        unavailable = f"minimum_{MIN_Z_SCORE_SAMPLE}_historical_samples_required"
    elif history_std is None or history_std <= 1e-12:
        unavailable = "historical_variance_is_zero"
    else:
        surprise_z = (oriented - (history_mean or 0.0)) / history_std
    return IndicatorSurprise(
        indicator.key,
        raw,
        oriented,
        relative,
        threshold,
        surprise_z,
        _direction(oriented, tolerance),
        revision,
        len(history),
        history_mean,
        history_std,
        cutoff,
        "z_score" if surprise_z is not None else "threshold_scaled_only",
        unavailable,
    )


def _component_value(item: IndicatorSurprise) -> tuple[float | None, str]:
    if item.surprise_z is not None:
        return item.surprise_z, "z_score"
    if item.threshold_scaled_surprise is not None:
        return item.threshold_scaled_surprise, "threshold_scaled"
    return None, "missing"


def _composite(
    calculated: tuple[IndicatorSurprise, ...], inputs: list[IndicatorInput]
) -> tuple[float | None, str, dict[str, str]]:
    usable: list[tuple[float, float, str]] = []
    methods: dict[str, str] = {}
    for source, item in zip(inputs, calculated, strict=True):
        value, method = _component_value(item)
        methods[item.key] = method
        if value is not None:
            usable.append((source.weight, value, method))
    if not usable:
        return None, "insufficient", methods
    score = sum(weight * value for weight, value, _ in usable) / sum(
        weight for weight, _, _ in usable
    )
    kinds = {method for _, _, method in usable}
    method = (
        "z_score"
        if kinds == {"z_score"}
        else "threshold_only"
        if kinds == {"threshold_scaled"}
        else "mixed_z_and_threshold"
    )
    return score, method, methods


def _mean_sign(results: dict[str, IndicatorSurprise], keys: tuple[str, ...]) -> int:
    values = [_component_value(item)[0] for key in keys if (item := results.get(key)) is not None]
    available = [value for value in values if value is not None]
    return _sign(sum(available) / len(available)) if available else 0


def calculate_bundle_surprise(
    indicators: list[IndicatorInput],
    *,
    historical_surprises: Mapping[
        str, Iterable[float | HistoricalSurpriseObservation | tuple[datetime, float]]
    ]
    | None = None,
    current_release_at: datetime | None = None,
) -> BundleSurprise:
    """Classify the CPI bundle without claiming a missing component is confirming."""
    history = historical_surprises or {}
    calculated = tuple(
        calculate_indicator_surprise(
            i, historical_raw=history.get(i.key), current_release_at=current_release_at
        )
        for i in indicators
    )
    by_key = {item.key: item for item in calculated}
    score, composite_method, component_methods = _composite(calculated, indicators)
    headline = _mean_sign(by_key, ("headline_mom", "headline_yoy"))
    core = _mean_sign(by_key, ("core_mom", "core_yoy"))
    monthly = _mean_sign(by_key, ("headline_mom", "core_mom"))
    annual = _mean_sign(by_key, ("headline_yoy", "core_yoy"))
    present = [by_key.get(key) for key in CPI_KEYS]
    complete = len(present) == 4 and all(
        item is not None and item.direction != "missing" for item in present
    )
    reasons: list[str] = []
    if not complete:
        classification = "数据不足"
        reasons.append("CPI 分项不完整；不将缺失分项视为方向确认。")
    elif headline and core and headline != core:
        classification = "Headline与Core方向冲突"
        reasons.append("Headline 与核心通胀的可比惊喜方向相反。")
    elif monthly and annual and monthly != annual:
        classification = "月率与年率方向冲突"
        reasons.append("月率与年率没有给出同向确认。")
    elif all(item is not None and item.direction == "hot" for item in present):
        classification = "全面偏热"
        reasons.append("四项已发布 CPI 指标均高于各自共识。")
    elif all(item is not None and item.direction == "cold" for item in present):
        classification = "全面偏冷"
        reasons.append("四项已发布 CPI 指标均低于各自共识。")
    elif core > 0:
        classification = "核心通胀偏热"
        reasons.append("核心通胀分项的综合偏热信号较强。")
    elif core < 0:
        classification = "核心通胀偏冷"
        reasons.append("核心通胀分项的综合偏冷信号较强。")
    else:
        classification = "大体符合预期"
        reasons.append("可用分项未形成足够一致的方向。")
    direction = "hot" if _sign(score, 0.25) > 0 else "cold" if _sign(score, 0.25) < 0 else "mixed"
    return BundleSurprise(
        classification,
        score,
        direction,
        calculated,
        tuple(reasons),
        False,
        composite_method,
        component_methods,
        {"dominant": False, "method": "not_applicable", "limitations": []},
    )


def _revision_analysis(
    calculated: tuple[IndicatorSurprise, ...], inputs: list[IndicatorInput]
) -> dict[str, object]:
    contributions: list[dict[str, object]] = []
    current_total = revision_total = 0.0
    comparable = 0
    for source, item in zip(inputs, calculated, strict=True):
        current, method = _component_value(item)
        if item.revision is None:
            continue
        tolerance = SURPRISE_TOLERANCE.get(item.key, 1e-9)
        # Revisions use the same orientation and scale as their own indicator.
        revision_oriented = float(item.revision) * (1 if source.hotter_when_higher else -1)
        if item.surprise_z is not None and item.history_std and item.history_std > 1e-12:
            revision_scaled, revision_method = revision_oriented / item.history_std, "z_score"
        else:
            revision_scaled, revision_method = revision_oriented / tolerance, "threshold_scaled"
        if current is not None:
            comparable += 1
            current_total += source.weight * abs(current)
            revision_total += source.weight * abs(revision_scaled)
        contributions.append(
            {
                "indicator": item.key,
                "weight": source.weight,
                "current_surprise_scaled": current,
                "revision_surprise_scaled": revision_scaled,
                "current_method": method,
                "revision_method": revision_method,
            }
        )
    main = [
        str(row["indicator"])
        for row in contributions
        if abs(cast(float, row["revision_surprise_scaled"])) >= 1
    ]
    z_standardized = comparable >= MIN_COMPARABLE_REVISION_COMPONENTS and all(
        row["current_method"] == "z_score" and row["revision_method"] == "z_score"
        for row in contributions
        if row["current_surprise_scaled"] is not None
    )
    dominant = (
        comparable >= MIN_COMPARABLE_REVISION_COMPONENTS
        and z_standardized
        and bool(main)
        and revision_total > current_total * REVISION_DOMINANCE_RATIO
    )
    limitation: list[str] = []
    if comparable < MIN_COMPARABLE_REVISION_COMPONENTS:
        limitation.append(
            "insufficient comparable components for cross-indicator revision judgement"
        )
    if not z_standardized:
        limitation.append(
            "historical samples are insufficient for cross-indicator "
            "z-standardized revision dominance"
        )
    return {
        "dominant": dominant,
        "method": "weighted_per_indicator_standardization",
        "dominance_comparison_available": z_standardized,
        "weighted_current_magnitude": current_total,
        "weighted_revision_magnitude": revision_total,
        "main_revision_indicators": main,
        "component_contributions": contributions,
        "limitations": limitation,
    }


def calculate_nfp_bundle_surprise(
    indicators: list[IndicatorInput],
    *,
    historical_surprises: Mapping[
        str, Iterable[float | HistoricalSurpriseObservation | tuple[datetime, float]]
    ]
    | None = None,
    current_release_at: datetime | None = None,
) -> BundleSurprise:
    history = historical_surprises or {}
    calculated = tuple(
        calculate_indicator_surprise(
            i, historical_raw=history.get(i.key), current_release_at=current_release_at
        )
        for i in indicators
    )
    score, composite_method, component_methods = _composite(calculated, indicators)
    by_key = {item.key: item for item in calculated}
    growth = _mean_sign(by_key, ("nonfarm_payrolls", "unemployment_rate"))
    wages = _mean_sign(by_key, ("average_hourly_earnings_mom", "average_hourly_earnings_yoy"))
    if growth > 0 and wages > 0:
        classification = "就业与工资全面偏强"
    elif growth < 0 and wages < 0:
        classification = "就业与工资全面偏弱"
    elif growth and wages and growth != wages:
        classification = "就业增长与工资方向冲突"
    elif growth > 0:
        classification = "就业增长偏强"
    elif growth < 0:
        classification = "就业增长偏弱"
    elif wages > 0:
        classification = "工资通胀偏热"
    elif wages < 0:
        classification = "工资通胀偏冷"
    else:
        classification = "就业报告大体符合预期"
    revision_analysis = _revision_analysis(calculated, indicators)
    if revision_analysis["dominant"]:
        classification = "主要变化来自前值修正"
    elif revision_analysis["main_revision_indicators"] and revision_analysis["limitations"]:
        classification = "存在显著前值修正，但无法完成跨指标标准化比较"
    direction = "hot" if _sign(score, 0.25) > 0 else "cold" if _sign(score, 0.25) < 0 else "mixed"
    return BundleSurprise(
        classification,
        score,
        direction,
        calculated,
        ("各指标先按自身历史或阈值尺度标准化，再按固定权重合成。",),
        bool(revision_analysis["dominant"]),
        composite_method,
        component_methods,
        revision_analysis,
    )


def calculate_policy_bundle_surprise(
    indicators: list[IndicatorInput],
    *,
    historical_surprises: Mapping[
        str, Iterable[float | HistoricalSurpriseObservation | tuple[datetime, float]]
    ]
    | None = None,
    current_release_at: datetime | None = None,
) -> BundleSurprise:
    history = historical_surprises or {}
    calculated = tuple(
        calculate_indicator_surprise(
            i, historical_raw=history.get(i.key), current_release_at=current_release_at
        )
        for i in indicators
    )
    score, composite_method, component_methods = _composite(calculated, indicators)
    sign = _sign(score, 0.25)
    classification = (
        "FOMC综合信息偏鹰"
        if sign > 0
        else "FOMC综合信息偏鸽"
        if sign < 0
        else "利率决定大体符合预期，阶段信息混合"
    )
    return BundleSurprise(
        classification,
        score,
        "hot" if sign > 0 else "cold" if sign < 0 else "mixed",
        calculated,
        ("利率决定与经人工核验的声明/发布会语气相对事前共识计算。",),
        False,
        composite_method,
        component_methods,
        {"dominant": False, "method": "not_applicable", "limitations": []},
    )
