"""Deterministic fact, rule, competition, and report generation."""

from __future__ import annotations

from collections.abc import Mapping

from macro_engine.data_quality import quality_score
from macro_engine.event_lab.types import (
    BundleSurprise,
    ComputedWindow,
    EarliestReaction,
)


def _window_return(
    windows: Mapping[str, Mapping[str, ComputedWindow]],
    instrument: str,
    key: str = "post_5m",
) -> float | None:
    row = windows.get(instrument, {}).get(key)
    return row.return_percent if row else None


def _moves(value: float | None, direction: str) -> bool:
    if value is None:
        return False
    return value > 0 if direction == "up" else value < 0


def build_structured_explanation(
    *,
    event_title: str,
    bundle: BundleSurprise,
    windows: Mapping[str, Mapping[str, ComputedWindow]],
    earliest: list[EarliestReaction],
    contamination_level: str,
    clean_window: bool,
    quality_grades: list[str],
    is_fixture: bool,
    historical: dict[str, object],
) -> dict[str, object]:
    """Create bounded explanations without asking an AI to invent evidence."""

    facts: list[dict[str, object]] = [
        {
            "kind": "confirmed_fact",
            "key": indicator.key,
            "statement": (
                f"{indicator.key} 相对共识的原始惊喜为 "
                f"{float(indicator.raw):+.2f}，方向为 {indicator.direction}。"
                if indicator.raw is not None
                else f"{indicator.key} 缺少Actual或Consensus，无法计算惊喜。"
            ),
            "confidence": 1.0 if indicator.raw is not None else 0.0,
        }
        for indicator in bundle.indicators
    ]
    if earliest:
        first = min(earliest, key=lambda item: item.detected_at)
        facts.append(
            {
                "kind": "confirmed_fact",
                "key": "earliest_observed",
                "statement": (
                    f"{first.instrument_key} 在T+{first.lag_seconds}秒最早观察到"
                    f"{first.direction}方向的显著反应，阈值"
                    f"{first.threshold_percent:.3f}%。"
                ),
                "confidence": 0.78,
                "limitation": first.limitation,
            }
        )

    for instrument, rows in windows.items():
        five = rows.get("post_5m")
        if five and five.return_percent is not None:
            facts.append(
                {
                    "kind": "confirmed_fact",
                    "key": f"{instrument}_post_5m",
                    "statement": (
                        f"{instrument} 公布后5分钟变化"
                        f"{five.return_percent:+.3f}%，覆盖率{five.coverage_ratio:.0%}。"
                    ),
                    "confidence": five.coverage_ratio,
                }
            )
        reversal = next((row for row in rows.values() if row.direction_reversal), None)
        if reversal:
            facts.append(
                {
                    "kind": "confirmed_fact",
                    "key": f"{instrument}_reversal",
                    "statement": f"{instrument} 在{reversal.label}相对第一阶段发生方向反转。",
                    "confidence": reversal.coverage_ratio,
                }
            )

    dollar = _window_return(windows, "dollar_dxy")
    gold = _window_return(windows, "gold_gc")
    silver = _window_return(windows, "silver_si")
    es = _window_return(windows, "sp500_es")
    nq = _window_return(windows, "nasdaq_nq")
    zt = _window_return(windows, "ust2y_zt")
    zn = _window_return(windows, "ust10y_zn")

    hot_confirmations = sum(
        (
            _moves(dollar, "up"),
            _moves(gold, "down"),
            _moves(silver, "down"),
            _moves(es, "down"),
            _moves(nq, "down"),
            _moves(zt, "down"),
            _moves(zn, "down"),
        )
    )
    explanations: list[dict[str, object]] = []
    if bundle.direction == "hot":
        explanations.append(
            {
                "kind": "historical_rule",
                "rule": "inflation_hotter_policy_path",
                "label": "通胀偏热 → 降息预期后移/实际利率压力",
                "status": "supported" if hot_confirmations >= 4 else "partial",
                "evidence": [
                    "ZT与ZN为美债期货价格代理，价格下跌通常对应收益率上升。",
                    f"七项跨资产确认中有{hot_confirmations}项方向一致。",
                ],
                "inference": (
                    "当前最合理的推断是偏热CPI推动市场重新评估政策利率路径，"
                    "随后经美元与利率通道影响贵金属和股指。"
                ),
                "certainty": "plausible_inference",
            }
        )
    elif bundle.direction == "cold":
        explanations.append(
            {
                "kind": "historical_rule",
                "rule": "inflation_cooler_easing_path",
                "label": "通胀偏冷 → 宽松预期增强",
                "status": "supported",
                "evidence": ["综合CPI惊喜方向偏冷。"],
                "inference": "偏冷数据通常先通过利率和美元通道重新定价。",
                "certainty": "historical_relationship",
            }
        )
    else:
        explanations.append(
            {
                "kind": "historical_rule",
                "rule": "mixed_cpi_bundle",
                "label": "CPI内部信号冲突",
                "status": "active",
                "evidence": list(bundle.reasons),
                "inference": "混合数据不支持单一方向，应等待利率与美元确认。",
                "certainty": "plausible_inference",
            }
        )

    if bundle.direction == "hot" and gold is not None and gold > 0:
        explanations.append(
            {
                "kind": "competing_explanation",
                "rule": "safe_haven_overrides_rates",
                "label": "避险或其他需求压过利率通道",
                "status": "competing",
                "evidence": ["黄金在偏热数据后仍上涨，与典型实际利率通道相反。"],
                "inference": "需要检查同窗新闻、地缘风险和美元是否未确认。",
                "certainty": "unconfirmed",
            }
        )
    if zt is not None and zn is not None and (zt * zn < 0 or abs(zt - zn) > 0.12):
        explanations.append(
            {
                "kind": "competing_explanation",
                "rule": "curve_divergence",
                "label": "短端与长端定价分化",
                "status": "active",
                "evidence": [f"ZT 5分钟{zt:+.3f}%，ZN 5分钟{zn:+.3f}%。"],
                "inference": "短端更接近政策路径，长端还包含增长与期限溢价。",
                "certainty": "plausible_inference",
            }
        )
    if not clean_window:
        explanations.append(
            {
                "kind": "competing_explanation",
                "rule": "event_contamination",
                "label": "事件窗口受到其他信息污染",
                "status": "active",
                "evidence": [f"污染等级：{contamination_level}。"],
                "inference": "不得将全部价格变化归因于CPI。",
                "certainty": "confirmed_limitation",
            }
        )

    covered = [
        row.coverage_ratio
        for rows in windows.values()
        for key, row in rows.items()
        if key in {"post_1m", "post_5m", "post_15m"} and row.return_percent is not None
    ]
    coverage_score = sum(covered) / len(covered) if covered else 0.0
    quality = (
        sum(quality_score(grade) for grade in quality_grades) / len(quality_grades)
        if quality_grades
        else 0.2
    )
    contamination_penalty = {
        "none": 1.0,
        "low": 0.88,
        "medium": 0.68,
        "high": 0.42,
    }.get(contamination_level, 0.6)
    confirmation_score = min(1.0, 0.55 + hot_confirmations * 0.06)
    confidence = quality * coverage_score * contamination_penalty * confirmation_score
    if is_fixture:
        confidence = min(confidence, 0.62)
    confidence = round(max(0.0, min(confidence, 0.92)), 2)

    earliest_text = (
        min(earliest, key=lambda item: item.detected_at).instrument_key if earliest else "没有资产"
    )
    historical_mode = str(historical.get("mode") or "case_studies")
    report = (
        f"{event_title}的指标集合被归类为“{bundle.classification}”。"
        f"分钟数据中，{earliest_text}最早观察到达到波动率调整阈值且连续确认的反应。"
        f"公布后5分钟，美元{(dollar or 0):+.3f}%，黄金{(gold or 0):+.3f}%，"
        f"白银{(silver or 0):+.3f}%，ES{(es or 0):+.3f}%，NQ{(nq or 0):+.3f}%。"
        "当前跨资产结构与通胀经政策利率预期、美元和实际利率传导的典型路径"
        f"{'较一致' if hot_confirmations >= 4 else '仅部分一致'}。"
        f"历史模块当前以{historical_mode}模式输出。"
        f"解释置信度为{confidence:.0%}；"
        + (
            "事件窗口存在污染，不能使用强因果措辞。"
            if not clean_window
            else "窗口未发现已登记的显著同窗事件，但仍不能证明唯一因果。"
        )
    )
    return {
        "facts": facts,
        "explanations": explanations,
        "confidence": confidence,
        "report": report,
        "data_gaps": [
            message
            for message, present in (
                ("缺少逐笔行情，无法识别同一分钟内的真实先后。", True),
                ("ZT/ZN是期货价格代理，不是现金收益率。", True),
                ("fixture行情仅用于验证计算流程。", is_fixture),
                ("历史样本不足，统计输出已降级。", historical_mode != "statistics"),
            )
            if present
        ],
    }
