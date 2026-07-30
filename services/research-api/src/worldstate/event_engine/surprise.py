"""CPI indicator and release-bundle surprise calculations."""

from __future__ import annotations

from decimal import Decimal
from statistics import pstdev

from worldstate.event_engine.types import (
    BundleSurprise,
    IndicatorInput,
    IndicatorSurprise,
)

CPI_KEYS = (
    "headline_mom",
    "headline_yoy",
    "core_mom",
    "core_yoy",
)
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


def _direction(oriented_raw: float | None, tolerance: float) -> str:
    sign = _sign(oriented_raw, tolerance)
    return "hot" if sign > 0 else "cold" if sign < 0 else "in_line"


def calculate_indicator_surprise(
    indicator: IndicatorInput,
    *,
    historical_raw: list[float] | None = None,
) -> IndicatorSurprise:
    history = [value for value in historical_raw or [] if value == value]
    if indicator.actual is None or indicator.consensus is None:
        return IndicatorSurprise(
            key=indicator.key,
            raw=None,
            relative=None,
            standardized=None,
            direction="missing",
            revision=(
                indicator.revised_previous - indicator.previous
                if indicator.revised_previous is not None and indicator.previous is not None
                else None
            ),
            history_samples=len(history),
        )

    raw = indicator.actual - indicator.consensus
    oriented = float(raw) * (1 if indicator.hotter_when_higher else -1)
    tolerance = SURPRISE_TOLERANCE.get(indicator.key, 1e-9)
    relative = (
        float(raw / abs(indicator.consensus))
        if abs(indicator.consensus) > Decimal("0.000000001")
        else None
    )
    dispersion = pstdev(history) if len(history) >= 5 else 0.0
    standardized = oriented / dispersion if dispersion > 1e-12 else oriented / tolerance
    revision = (
        indicator.revised_previous - indicator.previous
        if indicator.revised_previous is not None and indicator.previous is not None
        else None
    )
    return IndicatorSurprise(
        key=indicator.key,
        raw=raw,
        relative=relative,
        standardized=standardized,
        direction=_direction(oriented, tolerance),
        revision=revision,
        history_samples=len(history),
    )


def _mean_sign(results: dict[str, IndicatorSurprise], keys: tuple[str, ...]) -> int:
    values = [
        float(item.standardized)
        for key in keys
        if (item := results.get(key)) is not None and item.standardized is not None
    ]
    return _sign(sum(values) / len(values)) if values else 0


def calculate_bundle_surprise(
    indicators: list[IndicatorInput],
    *,
    historical_surprises: dict[str, list[float]] | None = None,
) -> BundleSurprise:
    """Classify simultaneous headline/core and monthly/annual CPI readings."""

    history = historical_surprises or {}
    calculated = tuple(
        calculate_indicator_surprise(
            indicator,
            historical_raw=history.get(indicator.key),
        )
        for indicator in indicators
    )
    by_key = {result.key: result for result in calculated}
    usable = [
        (indicator.weight, result.standardized)
        for indicator, result in zip(indicators, calculated, strict=True)
        if result.standardized is not None
    ]
    score = (
        sum(weight * float(value) for weight, value in usable)
        / sum(weight for weight, _value in usable)
        if usable
        else None
    )

    headline_sign = _mean_sign(by_key, ("headline_mom", "headline_yoy"))
    core_sign = _mean_sign(by_key, ("core_mom", "core_yoy"))
    monthly_sign = _mean_sign(by_key, ("headline_mom", "core_mom"))
    annual_sign = _mean_sign(by_key, ("headline_yoy", "core_yoy"))
    directions = [result.direction for result in calculated]
    revisions = [
        abs(float(result.revision)) for result in calculated if result.revision is not None
    ]
    current_raw = [abs(float(result.raw)) for result in calculated if result.raw is not None]
    revision_dominant = bool(revisions) and (
        sum(revisions) / len(revisions)
        > max(0.025, sum(current_raw) / len(current_raw) if current_raw else 0.0)
    )

    reasons: list[str] = []
    if headline_sign and core_sign and headline_sign != core_sign:
        classification = "Headline与Core方向冲突"
        reasons.append("Headline与核心指标给出相反的预期差信号。")
    elif monthly_sign and annual_sign and monthly_sign != annual_sign:
        classification = "月率和年率方向冲突"
        reasons.append("月率与年率没有给出同方向确认。")
    elif directions and all(direction == "hot" for direction in directions):
        classification = "全面偏热"
        reasons.append("所有偏离共识的CPI指标均高于预期。")
    elif directions and all(direction == "cold" for direction in directions):
        classification = "全面偏冷"
        reasons.append("所有偏离共识的CPI指标均低于预期。")
    elif core_sign > 0:
        classification = "核心通胀偏热"
        reasons.append("核心月率或年率的偏热信号强于Headline。")
    elif core_sign < 0:
        classification = "核心通胀偏冷"
        reasons.append("核心月率或年率的偏冷信号强于Headline。")
    else:
        classification = "大体符合预期"
        reasons.append("指标偏离幅度不足以形成一致方向。")

    if revision_dominant:
        classification = "主要变化来自前值修正"
        reasons.append("前值修正的平均幅度大于本次相对共识的平均偏离。")

    direction = "hot" if _sign(score, 0.25) > 0 else "cold" if _sign(score, 0.25) < 0 else "mixed"
    return BundleSurprise(
        classification=classification,
        score=score,
        direction=direction,
        indicators=calculated,
        reasons=tuple(reasons),
        revision_dominant=revision_dominant,
    )


def calculate_nfp_bundle_surprise(
    indicators: list[IndicatorInput],
    *,
    historical_surprises: dict[str, list[float]] | None = None,
) -> BundleSurprise:
    """Classify payrolls, unemployment, wages, and participation as one release."""

    history = historical_surprises or {}
    calculated = tuple(
        calculate_indicator_surprise(
            indicator,
            historical_raw=history.get(indicator.key),
        )
        for indicator in indicators
    )
    usable = [
        (indicator.weight, result.standardized)
        for indicator, result in zip(indicators, calculated, strict=True)
        if result.standardized is not None
    ]
    score = (
        sum(weight * float(value) for weight, value in usable) / sum(weight for weight, _ in usable)
        if usable
        else None
    )
    by_key = {item.key: item for item in calculated}
    payroll_direction = by_key.get("nonfarm_payrolls")
    unemployment_direction = by_key.get("unemployment_rate")
    wage_values = [
        item.standardized
        for key in ("average_hourly_earnings_mom", "average_hourly_earnings_yoy")
        if (item := by_key.get(key)) is not None and item.standardized is not None
    ]
    wage_sign = _sign(sum(wage_values) / len(wage_values)) if wage_values else 0
    growth_sign = _sign(
        sum(
            float(item.standardized)
            for item in (payroll_direction, unemployment_direction)
            if item is not None and item.standardized is not None
        )
    )
    reasons: list[str] = []
    if growth_sign > 0 and wage_sign > 0:
        classification = "就业与工资全面偏强"
        reasons.append("就业数量、失业率方向与工资压力共同指向更强的劳动力市场。")
    elif growth_sign < 0 and wage_sign < 0:
        classification = "就业与工资全面偏弱"
        reasons.append("就业数量、失业率方向与工资压力共同弱于共识。")
    elif growth_sign and wage_sign and growth_sign != wage_sign:
        classification = "就业增长与工资方向冲突"
        reasons.append("就业数量信号与工资通胀信号没有互相确认。")
    elif growth_sign > 0:
        classification = "就业增长偏强"
        reasons.append("非农与失业率的综合信号偏强，但工资没有同向确认。")
    elif growth_sign < 0:
        classification = "就业增长偏弱"
        reasons.append("非农与失业率的综合信号偏弱，但工资没有同向确认。")
    elif wage_sign > 0:
        classification = "工资通胀偏热"
        reasons.append("就业数量大体符合预期，但工资压力高于共识。")
    elif wage_sign < 0:
        classification = "工资通胀偏冷"
        reasons.append("就业数量大体符合预期，但工资压力低于共识。")
    else:
        classification = "就业报告大体符合预期"
        reasons.append("可用指标没有形成足够强的一致预期差。")

    revisions = [abs(float(item.revision)) for item in calculated if item.revision is not None]
    raw_values = [abs(float(item.raw)) for item in calculated if item.raw is not None]
    revision_dominant = bool(revisions) and (
        sum(revisions) / len(revisions)
        > max(0.05, sum(raw_values) / len(raw_values) if raw_values else 0.0)
    )
    if revision_dominant:
        classification = "主要变化来自前值修正"
        reasons.append("前值修正对就业报告方向的影响大于本次实际值偏离。")
    direction = "hot" if _sign(score, 0.25) > 0 else "cold" if _sign(score, 0.25) < 0 else "mixed"
    return BundleSurprise(
        classification=classification,
        score=score,
        direction=direction,
        indicators=calculated,
        reasons=tuple(reasons),
        revision_dominant=revision_dominant,
    )


def calculate_policy_bundle_surprise(
    indicators: list[IndicatorInput],
    *,
    historical_surprises: dict[str, list[float]] | None = None,
) -> BundleSurprise:
    """Orient rate decisions and human-coded policy tone versus consensus."""

    history = historical_surprises or {}
    calculated = tuple(
        calculate_indicator_surprise(
            indicator,
            historical_raw=history.get(indicator.key),
        )
        for indicator in indicators
    )
    usable = [
        (indicator.weight, result.standardized)
        for indicator, result in zip(indicators, calculated, strict=True)
        if result.standardized is not None
    ]
    score = (
        sum(weight * float(value) for weight, value in usable) / sum(weight for weight, _ in usable)
        if usable
        else None
    )
    sign = _sign(score, 0.25)
    classification = (
        "FOMC综合信息偏鹰"
        if sign > 0
        else "FOMC综合信息偏鸽"
        if sign < 0
        else "利率决定大体符合预期，阶段信息混合"
    )
    return BundleSurprise(
        classification=classification,
        score=score,
        direction="hot" if sign > 0 else "cold" if sign < 0 else "mixed",
        indicators=calculated,
        reasons=("利率决定与人工核验的声明/发布会语气分别相对事前预期计算。",),
        revision_dominant=False,
    )
