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
) -> RegimeResult:
    """Produce explicit, intentionally limited event-time regime dimensions."""
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
    if release_type == "US_CPI":
        value = (
            "rising_or_hot"
            if bundle_direction == "hot"
            else "falling_or_cool"
            if bundle_direction == "cold"
            else "mixed"
        )
        dimensions["inflation_regime"] = value
        labels.append(f"inflation:{value}")
        evidence.append(
            {
                "rule": "latest_cpi_bundle",
                "dimension": "inflation_regime",
                "value": value,
                "surprise": surprise_score,
            }
        )
    elif release_type == "US_NFP":
        value = (
            "accelerating_or_strong"
            if bundle_direction == "hot"
            else "slowing_or_weak"
            if bundle_direction == "cold"
            else "mixed"
        )
        dimensions["growth_regime"] = value
        labels.append(f"growth:{value}")
        evidence.append(
            {
                "rule": "latest_nfp_bundle",
                "dimension": "growth_regime",
                "value": value,
                "surprise": surprise_score,
            }
        )
    else:
        value = (
            "high_for_longer_or_hawkish"
            if bundle_direction == "hot"
            else "easing_expectations_or_dovish"
            if bundle_direction == "cold"
            else "mixed"
        )
        dimensions["monetary_policy_regime"] = value
        labels.append(f"policy:{value}")
        evidence.append(
            {
                "rule": "latest_fomc_bundle",
                "dimension": "monetary_policy_regime",
                "value": value,
                "surprise": surprise_score,
            }
        )
    dollar = returns.get("dollar_dxy:post_5m")
    if dollar is not None:
        value = "strong" if dollar > 0.05 else "weak" if dollar < -0.05 else "mixed"
        dimensions["dollar_regime"] = value
        labels.append(f"dollar:{value}")
        evidence.append(
            {
                "rule": "dxy_5m",
                "dimension": "dollar_regime",
                "value": value,
                "return_percent": dollar,
            }
        )
    equity, vix = returns.get("sp500_es:post_5m"), returns.get("vix:post_5m")
    if equity is not None and vix is not None:
        risk = (
            "risk_on"
            if equity > 0 and vix < 0
            else "risk_off"
            if equity < 0 and vix > 0
            else "mixed"
        )
        dimensions["risk_regime"] = risk
        dimensions["volatility_regime"] = "high" if abs(vix) >= 2 else "low"
        labels.extend((f"risk:{risk}", f"volatility:{dimensions['volatility_regime']}"))
        evidence.append(
            {
                "rule": "es_vix_confirmation",
                "risk": risk,
                "vix_return_percent": vix,
                "es_return_percent": equity,
            }
        )
    gaps = tuple(
        f"{key} is unknown at this event-time snapshot"
        for key, value in dimensions.items()
        if value == "unknown"
    )
    confidence = min(0.85, 0.35 + 0.12 * len(evidence))
    return RegimeResult(tuple(labels), dimensions, tuple(evidence), confidence, gaps)
