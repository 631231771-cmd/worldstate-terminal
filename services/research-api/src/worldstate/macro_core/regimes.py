"""Transparent rule-based macro regime labels."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeResult:
    labels: tuple[str, ...]
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
    """Derive a modest regime update and keep every rule visible."""

    labels: list[str] = []
    evidence: list[dict[str, object]] = []
    if release_type == "US_CPI":
        label = (
            "通胀上升/偏热"
            if bundle_direction == "hot"
            else "通胀下降/偏冷"
            if bundle_direction == "cold"
            else "通胀信号混合"
        )
        labels.append(label)
        evidence.append(
            {
                "rule": "latest_cpi_bundle",
                "label": label,
                "value": surprise_score,
            }
        )
    elif release_type == "US_NFP":
        label = (
            "增长与就业韧性"
            if bundle_direction == "hot"
            else "增长与就业放缓"
            if bundle_direction == "cold"
            else "增长信号混合"
        )
        labels.append(label)
        evidence.append(
            {
                "rule": "latest_nfp_bundle",
                "label": label,
                "value": surprise_score,
            }
        )
        if surprise_score is not None and surprise_score < -2:
            labels.append("衰退风险上升")
    else:
        label = (
            "高利率暂停/偏鹰"
            if bundle_direction == "hot"
            else "降息预期/偏鸽"
            if bundle_direction == "cold"
            else "政策路径混合"
        )
        labels.append(label)
        evidence.append(
            {
                "rule": "latest_fomc_bundle",
                "label": label,
                "value": surprise_score,
            }
        )

    dollar = returns.get("dollar_dxy:post_5m")
    if dollar is not None:
        label = "美元强势" if dollar > 0.05 else "美元弱势" if dollar < -0.05 else "美元中性"
        labels.append(label)
        evidence.append({"rule": "dxy_5m", "label": label, "value": dollar, "unit": "%"})
    equity = returns.get("sp500_es:post_5m")
    volatility = returns.get("vix:post_5m")
    if equity is not None and volatility is not None:
        if equity > 0 and volatility < 0:
            label = "风险偏好"
        elif equity < 0 and volatility > 0:
            label = "风险规避"
        else:
            label = "风险偏好分歧"
        labels.append(label)
        evidence.append(
            {
                "rule": "es_vix_confirmation",
                "label": label,
                "es_return_percent": equity,
                "vix_return_percent": volatility,
            }
        )
        labels.append("高波动" if abs(volatility) >= 2 else "低波动")
    confidence = min(0.85, 0.35 + 0.12 * len(evidence))
    gaps = (
        "该快照反映事件后的市场定价，不是对真实经济状态的完整测量。",
        "需要连续官方时间序列确认增长和通胀趋势。",
    )
    return RegimeResult(tuple(dict.fromkeys(labels)), tuple(evidence), confidence, gaps)
