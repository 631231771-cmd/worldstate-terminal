"""Transparent rule-based macro regime labels and comparable dimensions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeResult:
    labels: tuple[str, ...]
    dimensions: dict[str, str]
    evidence: tuple[dict[str, object], ...]
    confidence: float
    data_gaps: tuple[str, ...]


def derive_regime(
    *,
    release_type: str,
    bundle_direction: str,
    surprise_score: float | None,
    returns: dict[str, float | None],
    macro_context: dict[str, object] | None = None,
) -> RegimeResult:
    """Derive a pre-event regime without leaking the event's later market outcome."""
    dimensions = {
        "inflation_regime": "unknown",
        "growth_regime": "unknown",
        "monetary_policy_regime": "unknown",
        "risk_regime": "unknown",
        "dollar_regime": "unknown",
        "real_yield_regime": "unknown",
        "volatility_regime": "unknown",
    }
    labels: list[str] = []
    evidence: list[dict[str, object]] = []
    context = macro_context or {}

    def numeric(key: str) -> float | None:
        value = context.get(key)
        return float(value) if isinstance(value, int | float) else None

    two_year = numeric("two_year_yield")
    two_year_change = numeric("two_year_yield_change_20")
    ten_year = numeric("ten_year_yield")
    if two_year is not None:
        policy = (
            "high_and_rising"
            if two_year >= 4 and (two_year_change or 0) >= 0.20
            else "high_but_easing"
            if two_year >= 4 and (two_year_change or 0) <= -0.20
            else "easing"
            if (two_year_change or 0) <= -0.20
            else "stable_or_mixed"
        )
        dimensions["monetary_policy_regime"] = policy
        labels.append(f"policy:{policy}")
        evidence.append(
            {
                "rule": "pre_event_two_year_yield_level_and_20_observation_change",
                "dimension": "monetary_policy_regime",
                "value": policy,
                "level": two_year,
                "change_20": two_year_change,
                "point_in_time": True,
            }
        )
    if two_year is not None and ten_year is not None:
        curve = ten_year - two_year
        growth = (
            "inverted_slowdown_risk"
            if curve < 0
            else "positive_curve"
            if curve > 0.75
            else "flat_or_mixed"
        )
        dimensions["growth_regime"] = growth
        labels.append(f"growth:{growth}")
        evidence.append(
            {
                "rule": "pre_event_ten_year_minus_two_year_curve",
                "dimension": "growth_regime",
                "value": growth,
                "curve_percentage_points": curve,
                "point_in_time": True,
            }
        )

    real_yield = numeric("ten_year_real_yield")
    if real_yield is not None:
        value = "high" if real_yield >= 1.5 else "low" if real_yield <= 0.5 else "moderate"
        dimensions["real_yield_regime"] = value
        labels.append(f"real_yield:{value}")
        evidence.append(
            {
                "rule": "pre_event_ten_year_real_yield_level",
                "dimension": "real_yield_regime",
                "value": value,
                "level": real_yield,
                "point_in_time": True,
            }
        )

    dollar_change = numeric("broad_dollar_index_change_20_percent")
    if dollar_change is not None:
        value = "strong" if dollar_change >= 1 else "weak" if dollar_change <= -1 else "mixed"
        dimensions["dollar_regime"] = value
        labels.append(f"dollar:{value}")
        evidence.append(
            {
                "rule": "pre_event_broad_dollar_20_observation_change",
                "dimension": "dollar_regime",
                "value": value,
                "change_percent": dollar_change,
                "point_in_time": True,
            }
        )

    vix = numeric("vix_close")
    if vix is not None:
        volatility = "high" if vix >= 25 else "low" if vix <= 15 else "moderate"
        risk = "risk_off" if vix >= 25 else "risk_on" if vix <= 15 else "mixed"
        dimensions["risk_regime"] = risk
        dimensions["volatility_regime"] = volatility
        labels.extend((f"risk:{risk}", f"volatility:{volatility}"))
        evidence.append(
            {
                "rule": "pre_event_vix_close_level",
                "risk_regime": risk,
                "volatility_regime": volatility,
                "vix_close": vix,
                "point_in_time": True,
            }
        )
    if returns:
        evidence.append(
            {
                "rule": "outcome_leakage_guard",
                "excluded_dimensions": sorted(returns),
                "note": "Post-event returns are excluded from regime classification.",
            }
        )
    gaps = tuple(
        f"{key} is unknown at this event-time snapshot"
        for key, value in dimensions.items()
        if value == "unknown"
    )
    confidence = min(0.85, 0.15 + 0.12 * sum("dimension" in item for item in evidence))
    return RegimeResult(tuple(labels), dimensions, tuple(evidence), confidence, gaps)
