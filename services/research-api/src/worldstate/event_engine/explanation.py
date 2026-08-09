"""Deterministic fact and competing-hypothesis construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worldstate.event_engine.types import BundleSurprise, ComputedWindow, EarliestReaction

StageWindows = Mapping[str, Mapping[str, Mapping[str, ComputedWindow]]]


def _return(
    windows: StageWindows,
    stage: str,
    instrument: str,
    window_key: str = "post_5m",
) -> float | None:
    item = windows.get(stage, {}).get(instrument, {}).get(window_key)
    return item.return_percent if item else None


def _direction(value: float | None) -> str:
    if value is None:
        return "missing"
    if abs(value) < 0.0001:
        return "flat"
    return "up" if value > 0 else "down"


def _fact_windows(windows: StageWindows) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    for stage_key, instruments in windows.items():
        for instrument_key, values in instruments.items():
            item = values.get("post_5m")
            if item is None or item.return_percent is None:
                continue
            facts.append(
                {
                    "kind": "confirmed_fact",
                    "key": f"{stage_key}:{instrument_key}:post_5m",
                    "statement": (
                        f"{stage_key}阶段后5分钟，{instrument_key}变化"
                        f"{item.return_percent:+.3f}%，覆盖率{item.coverage_ratio:.0%}。"
                    ),
                    "value": item.return_percent,
                    "unit": "%",
                    "confidence": item.coverage_ratio,
                }
            )
            if item.spike_fade:
                facts.append(
                    {
                        "kind": "confirmed_fact",
                        "key": f"{stage_key}:{instrument_key}:spike_fade",
                        "statement": f"{instrument_key}在{stage_key}阶段出现冲高回落。",
                        "confidence": item.coverage_ratio,
                    }
                )
            if item.dip_recovery:
                facts.append(
                    {
                        "kind": "confirmed_fact",
                        "key": f"{stage_key}:{instrument_key}:dip_recovery",
                        "statement": f"{instrument_key}在{stage_key}阶段出现探底回升。",
                        "confidence": item.coverage_ratio,
                    }
                )
    return facts


def _hypothesis(
    *,
    kind: str,
    rule_key: str,
    title: str,
    summary: str,
    steps: list[str],
    confirming: list[str],
    contradicting: list[str],
    unresolved: list[str],
    confidence: float,
    causal_language: str = "plausible_inference",
) -> dict[str, object]:
    return {
        "kind": kind,
        "rule_key": rule_key,
        "title": title,
        "summary": summary,
        "mechanism_steps": steps,
        "confirming_evidence": [
            {"statement": item, "evidence_type": "computed_market_fact"} for item in confirming
        ],
        "contradicting_evidence": [
            {"statement": item, "evidence_type": "computed_market_fact"} for item in contradicting
        ],
        "unresolved": unresolved,
        "confidence": round(max(0.0, min(confidence, 0.95)), 2),
        "causal_language": causal_language,
    }


def build_structured_explanation(
    *,
    release_type: str,
    event_title: str,
    bundle: BundleSurprise,
    windows: StageWindows,
    earliest: list[EarliestReaction],
    contamination_level: str,
    clean_window: bool,
    quality_grades: list[str],
    is_fixture: bool,
    historical: dict[str, object],
) -> dict[str, object]:
    """Build evidence-bounded facts, hypotheses, confidence, and a report."""

    facts: list[dict[str, object]] = []
    for indicator in bundle.indicators:
        facts.append(
            {
                "kind": "confirmed_fact",
                "key": indicator.key,
                "statement": (
                    f"{indicator.key}相对共识的原始惊喜为"
                    f"{float(indicator.raw):+.3f}，方向为{indicator.direction}。"
                    if indicator.raw is not None
                    else f"{indicator.key}缺少Actual或Consensus，无法计算惊喜。"
                ),
                "value": float(indicator.raw) if indicator.raw is not None else None,
                "confidence": 1.0 if indicator.raw is not None else 0.0,
            }
        )
    facts.extend(_fact_windows(windows))
    for reaction in earliest:
        facts.append(
            {
                "kind": "confirmed_fact",
                "key": f"earliest:{reaction.instrument_key}",
                "statement": (
                    f"{reaction.instrument_key}在T+{reaction.lag_seconds}秒最早观察到"
                    f"{reaction.direction}方向显著反应；数据粒度"
                    f"{reaction.granularity_seconds}秒。"
                ),
                "confidence": 0.78,
                "limitation": reaction.limitation,
            }
        )

    stage = "release"
    dollar = _return(windows, stage, "dollar_dxy")
    gold = _return(windows, stage, "gold_gc")
    silver = _return(windows, stage, "silver_si")
    es = _return(windows, stage, "sp500_es")
    nq = _return(windows, stage, "nasdaq_nq")
    zt = _return(windows, stage, "ust2y_zt")
    zn = _return(windows, stage, "ust10y_zn")
    confirming: list[str] = []
    contradicting: list[str] = []

    policy_hawkish = bundle.direction == "hot"
    expected = {
        "dollar_dxy": "up" if policy_hawkish else "down",
        "gold_gc": "down" if policy_hawkish else "up",
        "silver_si": "down" if policy_hawkish else "up",
        "sp500_es": "down" if policy_hawkish else "up",
        "nasdaq_nq": "down" if policy_hawkish else "up",
        "ust2y_zt": "down" if policy_hawkish else "up",
        "ust10y_zn": "down" if policy_hawkish else "up",
    }
    values = {
        "dollar_dxy": dollar,
        "gold_gc": gold,
        "silver_si": silver,
        "sp500_es": es,
        "nasdaq_nq": nq,
        "ust2y_zt": zt,
        "ust10y_zn": zn,
    }
    for key, expected_direction in expected.items():
        actual_direction = _direction(values[key])
        message = f"{key} 5分钟方向为{actual_direction}，规则预期为{expected_direction}。"
        if actual_direction == expected_direction:
            confirming.append(message)
        elif actual_direction != "missing":
            contradicting.append(message)

    base_confidence = 0.38 + min(0.35, len(confirming) * 0.05)
    if quality_grades:
        grade_score = {"A": 1.0, "B": 0.85, "C": 0.65, "D": 0.35, "UNKNOWN": 0.2}
        base_confidence *= sum(grade_score.get(item, 0.2) for item in quality_grades) / len(
            quality_grades
        )
    if not clean_window:
        base_confidence *= {"low": 0.82, "medium": 0.62, "high": 0.38}.get(contamination_level, 0.6)
    if is_fixture:
        base_confidence = min(base_confidence, 0.58)

    hypotheses: list[dict[str, Any]] = []
    if release_type == "US_CPI":
        title = (
            "通胀偏热后，政策利率与实际利率路径重新定价"
            if policy_hawkish
            else "通胀偏冷后，宽松预期与实际利率回落路径"
        )
        hypotheses.append(
            _hypothesis(
                kind="primary",
                rule_key="cpi_policy_rate_real_yield",
                title=title,
                summary=(
                    "当前跨资产结构与CPI预期差先进入短端利率和美元、"
                    "再影响贵金属与成长股贴现率的传导链较为一致。"
                ),
                steps=[
                    "CPI指标集合相对事前共识形成预期差。",
                    "市场重新评估未来联邦基金利率路径与实际利率。",
                    "短端美债期货和美元先反映政策路径变化。",
                    "黄金、白银和股指再通过持有成本、贴现率与风险偏好调整。",
                ],
                confirming=confirming,
                contradicting=contradicting,
                unresolved=["分钟数据不能识别同一根bar内的真实先后顺序。"],
                confidence=base_confidence,
            )
        )
    elif release_type == "US_NFP":
        hypotheses.append(
            _hypothesis(
                kind="primary",
                rule_key="nfp_policy_growth_balance",
                title="就业与工资预期差改变政策路径和增长定价",
                summary=(
                    "非农不是单一就业人数。就业、失业率和工资共同决定市场更重视"
                    "政策利率压力，还是更重视增长韧性。"
                ),
                steps=[
                    "非农、失业率与工资指标分别相对共识形成预期差。",
                    "工资与劳动力紧张程度影响通胀和政策反应函数。",
                    "短端利率与美元验证政策路径定价。",
                    "股指在更高贴现率和更强增长之间权衡。",
                ],
                confirming=confirming,
                contradicting=contradicting,
                unresolved=["参与率变化对劳动力供给的影响需要结合更多人口数据。"],
                confidence=base_confidence,
            )
        )
        hypotheses.append(
            _hypothesis(
                kind="competitive",
                rule_key="nfp_growth_relief",
                title="增长韧性可能抵消部分利率压力",
                summary="如果股指与收益率同时上行，市场可能更重视盈利和软着陆而非纯粹鹰派。",
                steps=["就业强度提高增长与企业盈利预期。", "增长效应与贴现率效应竞争。"],
                confirming=[
                    f"ES 5分钟方向为{_direction(es)}。",
                    f"NQ 5分钟方向为{_direction(nq)}。",
                ],
                contradicting=[],
                unresolved=["需要行业广度和信用利差进一步确认。"],
                confidence=base_confidence * 0.72,
            )
        )
    else:
        statement_gold = _return(windows, "statement", "gold_gc")
        press_gold = _return(windows, "press_conference", "gold_gc")
        reversal = (
            statement_gold is not None
            and press_gold is not None
            and statement_gold * press_gold < 0
        )
        hypotheses.append(
            _hypothesis(
                kind="primary",
                rule_key="fomc_multistage_policy_path",
                title="FOMC声明与新闻发布会分阶段重定价",
                summary=("FOMC需要分别读取声明、预测和主席问答；整晚最终涨跌不能替代阶段性解释。"),
                steps=[
                    "声明公布后，市场先定价利率决定、措辞和预测。",
                    "新闻发布会提供反应函数、风险平衡和未来路径信息。",
                    "短端、长端、美元与黄金用于验证解释是否改变。",
                ],
                confirming=[
                    f"声明后黄金5分钟{(statement_gold or 0):+.3f}%。",
                    f"发布会后黄金5分钟{(press_gold or 0):+.3f}%。",
                    "两个阶段发生方向反转。" if reversal else "两个阶段未形成明确反转。",
                ],
                contradicting=[],
                unresolved=["定性语气分数是人工核验编码，不是美联储官方数据。"],
                confidence=base_confidence,
            )
        )

    if not clean_window:
        hypotheses.append(
            _hypothesis(
                kind="competitive",
                rule_key="window_contamination",
                title="同窗事件或新闻可能污染价格反应",
                summary="已登记的重叠事件使本次解释只能使用弱因果措辞。",
                steps=["识别同一窗口内的其他数据、讲话或新闻。", "降低解释置信度。"],
                confirming=[f"污染等级为{contamination_level}。"],
                contradicting=[],
                unresolved=["无法确认未被数据源收录的即时新闻。"],
                confidence=0.75,
                causal_language="confirmed_limitation",
            )
        )

    if (
        release_type != "FOMC"
        and gold is not None
        and ((policy_hawkish and gold > 0) or (not policy_hawkish and gold < 0))
    ):
        hypotheses.append(
            _hypothesis(
                kind="competitive",
                rule_key="gold_competing_demand",
                title="黄金的避险、央行或仓位需求可能压过利率通道",
                summary="黄金方向与典型政策利率通道相反，需要寻找独立证据，不能强行归因。",
                steps=["检查美元与实际利率代理是否确认。", "检查同窗新闻和仓位放大机制。"],
                confirming=[f"黄金5分钟方向为{_direction(gold)}。"],
                contradicting=confirming,
                unresolved=["当前系统没有逐笔资金流与完整期权仓位数据。"],
                confidence=base_confidence * 0.68,
            )
        )

    confidence = max((float(item["confidence"]) for item in hypotheses), default=0.0)
    historical_mode = str(historical.get("mode", "insufficient"))
    report = (
        f"{event_title}的指标集合被分类为“{bundle.classification}”。"
        f"最早显著反应基于{earliest[0].granularity_seconds if earliest else 60}秒数据；"
        "它表示最早观察到，而不是逐笔交易层面的严格领先。"
        f"主解释为“{hypotheses[0]['title'] if hypotheses else '数据不足'}”，"
        f"解释置信度{confidence:.0%}。历史模块处于{historical_mode}模式。"
        + (
            "事件窗口存在污染，因此不使用强因果措辞。"
            if not clean_window
            else "未登记显著同窗事件，但这仍不能证明唯一因果。"
        )
    )
    data_gaps = [
        "缺少逐笔行情，无法识别同一分钟内的真实先后顺序。",
        "ZT/ZN是期货价格代理，不是原始现券收益率。",
    ]
    if is_fixture:
        data_gaps.append("行情或事件数据包含明确标记的fixture，仅用于验证计算流程。")
    if historical_mode in {"case_studies", "insufficient"}:
        data_gaps.append("历史样本不足，概率与百分位输出已被抑制。")
    return {
        "facts": facts,
        "explanations": hypotheses,
        "confidence": round(confidence, 2),
        "report": report,
        "data_gaps": data_gaps,
    }
