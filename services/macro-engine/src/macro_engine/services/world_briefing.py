"""Evidence-first daily world briefing and deterministic causal explanations."""

# ruff: noqa: RUF001

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from macro_engine.config import Settings
from macro_engine.providers.public_intelligence import PublicIntelligenceProvider
from macro_engine.services.terminal import build_snapshot


def event_playbook(title: str, category: str) -> dict[str, object]:
    """Map a headline to a transparent macro transmission hypothesis."""

    lowered = title.lower()
    if any(term in lowered for term in ("federal reserve", "fed ", "interest rate", "cpi")):
        return {
            "display_title": "美联储与美国利率路径出现新的重要信号",
            "why_it_matters": (
                "它可能改变市场对美国利率路径的预期，并通过实际利率和美元影响全球资产。"
            ),
            "causal_chain": [
                "政策或通胀信息改变利率预期",
                "美债收益率与美元重新定价",
                "黄金和成长股的持有成本发生变化",
                "全球风险资产随后调整",
            ],
            "assets": ["us10y", "dollar", "gold", "nasdaq", "sp500"],
            "concept": "预期差与实际利率",
            "confidence": 0.82,
        }
    if any(term in lowered for term in ("oil", "opec", "energy", "lng")) or category == "energy":
        return {
            "display_title": "能源供应与油价变化正在影响全球通胀预期",
            "why_it_matters": "能源价格同时影响通胀、企业成本、居民消费能力和能源出口国收入。",
            "causal_chain": [
                "供应、制裁或需求预期改变",
                "原油风险溢价变化",
                "通胀预期与债券收益率受到影响",
                "股票行业和消费预期分化",
            ],
            "assets": ["oil", "us10y", "sp500", "gold"],
            "concept": "能源冲击如何传导到通胀",
            "confidence": 0.76,
        }
    if any(term in lowered for term in ("china", "pboc", "中国", "央行")) or category == "china":
        return {
            "display_title": "中国政策与增长预期成为亚洲市场焦点",
            "why_it_matters": (
                "中国的增长与政策变化会影响亚洲股票、工业品需求、人民币相关资产和全球贸易。"
            ),
            "causal_chain": [
                "政策或增长预期变化",
                "人民币、信用与内需预期调整",
                "A股和港股首先反应",
                "亚洲市场与大宗商品进一步定价",
            ],
            "assets": ["a_shares", "hong_kong", "oil", "nikkei", "kospi"],
            "concept": "中国政策的跨市场传导",
            "confidence": 0.74,
        }
    if any(term in lowered for term in ("japan", "boj", "yen", "korea", "bank of korea")):
        return {
            "display_title": "日本或韩国的利率与汇率预期正在变化",
            "why_it_matters": (
                "日本或韩国的利率与汇率变化会重塑亚洲资金成本、出口竞争力和套息交易。"
            ),
            "causal_chain": [
                "央行或汇率预期变化",
                "本币与本国收益率调整",
                "出口股和银行股重新定价",
                "亚洲跨境资金流受到影响",
            ],
            "assets": ["nikkei", "kospi", "dollar", "us10y"],
            "concept": "汇率、出口与套息交易",
            "confidence": 0.7,
        }
    if any(term in lowered for term in ("war", "attack", "sanction", "ceasefire", "conflict")):
        return {
            "display_title": "地缘风险正在改变避险与能源市场定价",
            "why_it_matters": (
                "地缘事件会改变能源供应、避险需求与全球风险偏好，但影响能否持续取决于实际经济后果。"
            ),
            "causal_chain": [
                "冲突或制裁风险变化",
                "避险与能源供应预期调整",
                "黄金、原油和美元先行反应",
                "股票市场评估增长与成本影响",
            ],
            "assets": ["gold", "oil", "dollar", "sp500", "bitcoin"],
            "concept": "风险溢价与避险资产",
            "confidence": 0.68,
        }
    return {
        "display_title": "全球政策与风险事件正在改变市场预期",
        "why_it_matters": (
            "这件事可能改变增长、通胀或风险偏好，需要结合利率、美元和跨市场价格确认其影响。"
        ),
        "causal_chain": [
            "新信息进入市场",
            "投资者与算法更新预期",
            "最相关资产首先调整",
            "其他市场决定是否确认这条叙事",
        ],
        "assets": ["sp500", "dollar", "gold"],
        "concept": "信息、预期与市场确认",
        "confidence": 0.55,
    }


def compose_events(news: list[dict[str, object]]) -> list[dict[str, object]]:
    """Select diverse high-impact stories and attach explicit causal hypotheses."""

    selected: list[dict[str, object]] = []
    seen_categories: set[str] = set()
    for item in news:
        category = str(item.get("category") or "world")
        if category in seen_categories and len(selected) < 3:
            continue
        playbook = event_playbook(str(item["title"]), category)
        selected.append(
            {
                **item,
                **playbook,
                "rank": len(selected) + 1,
                "analysis_type": "evidence_based_hypothesis",
            }
        )
        seen_categories.add(category)
        if len(selected) == 5:
            break
    return selected


def _available_market(
    markets: list[dict[str, object]],
    key: str,
) -> dict[str, object] | None:
    return next((row for row in markets if row["key"] == key and row.get("available")), None)


def _move(row: dict[str, object] | None) -> float | None:
    if row is None:
        return None
    value = row.get("change_percent")
    return float(value) if isinstance(value, (int, float)) else None


def market_explanation(
    market: dict[str, object],
    all_markets: list[dict[str, object]],
) -> dict[str, object]:
    """Explain a daily move using cross-asset confirmations, never hidden order flow."""

    if not market.get("available"):
        return {
            **market,
            "direction": "unavailable",
            "explanation": "免费行情源暂时没有返回该市场数据。",
            "evidence": [],
            "confidence": 0.0,
        }
    key = str(market["key"])
    change = _move(market) or 0.0
    direction = "up" if change > 0.05 else "down" if change < -0.05 else "flat"
    dollar = _move(_available_market(all_markets, "dollar"))
    yield_10y = _move(_available_market(all_markets, "us10y"))
    oil = _move(_available_market(all_markets, "oil"))
    evidence: list[str] = []

    if key == "gold":
        if dollar is not None:
            evidence.append(f"美元指数当日{dollar:+.2f}%")
        if yield_10y is not None:
            evidence.append(f"十年期收益率代理当日{yield_10y:+.2f}%")
        if change > 0 and (dollar or 0) < 0 and (yield_10y or 0) < 0:
            explanation = "美元与长端收益率同步走弱，为黄金上涨提供了跨资产确认。"
            confidence = 0.78
        elif change > 0:
            explanation = "黄金上涨，但美元和利率并未同时确认；避险、仓位或流动性可能是放大因素。"
            confidence = 0.55
        else:
            explanation = "黄金走弱，需优先检查美元、实际利率和避险需求是否反向变化。"
            confidence = 0.58
    elif key in {"sp500", "nasdaq"}:
        if yield_10y is not None:
            evidence.append(f"十年期收益率代理当日{yield_10y:+.2f}%")
        if oil is not None:
            evidence.append(f"WTI原油当日{oil:+.2f}%")
        explanation = (
            "股票上涨通常意味着增长或流动性预期改善；利率下降时，成长股估值也会得到支持。"
            if change > 0
            else "股票下跌通常反映增长、政策利率或风险溢价压力，需要结合债券与能源市场判断。"
        )
        confidence = 0.62
    elif key == "dollar":
        explanation = (
            "美元走强通常对应美国利率优势、避险需求或海外增长担忧。"
            if change > 0
            else "美元走弱通常对应降息预期、风险偏好改善或其他经济体预期回升。"
        )
        confidence = 0.6
    elif key == "us10y":
        explanation = (
            "长端收益率上升可能来自更强增长、通胀担忧、政策预期或期限溢价上升。"
            if change > 0
            else "长端收益率下降可能反映降息预期、增长担忧或避险买入。"
        )
        confidence = 0.6
    elif key == "oil":
        explanation = (
            "油价上涨需要区分需求改善与供应风险；两者对股票和通胀的含义不同。"
            if change > 0
            else "油价下跌可能来自需求担忧、供应增加或地缘风险溢价消退。"
        )
        confidence = 0.6
    elif key == "bitcoin":
        explanation = (
            "比特币上涨通常与风险偏好、流动性和加密资产自身催化剂共同相关。"
            if change > 0
            else "比特币下跌可能反映流动性收紧、风险偏好下降或加密市场内部去杠杆。"
        )
        confidence = 0.52
    else:
        explanation = (
            "该指数上涨，需结合本地政策、汇率、出口权重和隔夜美股表现判断原因。"
            if change > 0
            else "该指数下跌，需结合本地政策、汇率、出口权重和全球风险偏好判断原因。"
        )
        confidence = 0.5
    return {
        **market,
        "direction": direction,
        "explanation": explanation,
        "evidence": evidence,
        "confidence": confidence,
        "order_flow_known": False,
    }


def daily_lesson(events: list[dict[str, object]]) -> dict[str, object]:
    """Create one teachable concept from the day's highest-ranked event."""

    if not events:
        return {
            "concept": "信息、预期与价格",
            "question": "为什么有新闻时市场不一定上涨或下跌？",
            "simple": "价格反映的不是新闻本身，而是新闻相对于市场原有预期带来了多大的意外。",
            "deep": "同一条消息的影响取决于预期差、仓位、流动性、政策反应函数和其他资产是否确认。",
            "check_question": "如果数据很好但低于市场预期，价格更可能怎样反应？",
        }
    event = events[0]
    return {
        "concept": event["concept"],
        "question": f"今天如何理解：{event['title']}",
        "simple": event["why_it_matters"],
        "deep": (
            "先区分已确认事实与因果假设，再观察债券、美元、商品和股票"
            "是否给出一致信号。算法可以触发第一段波动，"
            "但持续行情需要新的预期和资金行为确认。"
        ),
        "check_question": "这条因果链中，哪一个跨资产信号最能证伪当前解释？",
    }


def compose_world_briefing(
    markets: list[dict[str, object]],
    news: list[dict[str, object]],
    macro_snapshot: dict[str, object],
    settings: Settings,
) -> dict[str, object]:
    """Combine deterministic numbers and traceable narrative into the API contract."""

    events = compose_events(news)
    explained_markets = [market_explanation(row, markets) for row in markets]
    available_markets = sum(bool(row.get("available")) for row in markets)
    evidence_mode = (
        "LIVE"
        if news and available_markets >= len(markets) // 2
        else "PARTIAL"
        if news or available_markets
        else "OFFLINE"
    )
    top_title = (
        str(events[0]["display_title"])
        if events
        else "免费新闻源暂不可用；宏观数据底座仍可继续学习"
    )
    states = macro_snapshot.get("states")
    compact_states = []
    if isinstance(states, list):
        compact_states = [
            {
                "key": row.get("key"),
                "score": row.get("score"),
                "label": row.get("label"),
                "confidence": row.get("confidence"),
            }
            for row in states
            if isinstance(row, dict)
        ]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of_timezone": settings.default_timezone,
        "evidence_mode": evidence_mode,
        "headline": top_title,
        "mission": "用十分钟理解今天的世界，以及世界如何影响主要市场。",
        "events": events,
        "markets": explained_markets,
        "lesson": daily_lesson(events),
        "upcoming": macro_snapshot.get("releases", []),
        "macro_context": {
            "mode": macro_snapshot.get("mode", "EMPTY"),
            "methodology_version": macro_snapshot.get("methodology_version"),
            "states": compact_states,
        },
        "ai": {
            "provider": settings.resolved_ai_provider,
            "model": (
                settings.ollama_model
                if settings.resolved_ai_provider == "ollama"
                else settings.ai_model
            ),
            "available": settings.resolved_ai_provider != "none",
            "grounding": "server_evidence_pack",
        },
        "sources": {
            "news": sorted({str(item["source"]) for item in news}),
            "markets": ["Yahoo Finance"] if available_markets else [],
            "macro": ["FRED/ALFRED", "World State deterministic engine"],
        },
        "limitations": [
            "免费新闻与行情可能延迟、缺失或受上游访问限制。",
            "市场原因是带置信度的假设，不代表已观察到具体机构订单流。",
            "本终端用于学习与研究，不构成投资建议。",
        ],
    }


async def build_world_briefing(
    engine: AsyncEngine,
    settings: Settings,
    provider: PublicIntelligenceProvider | None = None,
) -> dict[str, object]:
    """Fetch public evidence and combine it with the existing macro state engine."""

    resolved_provider = provider or PublicIntelligenceProvider(settings.public_data_timeout_seconds)
    markets = await resolved_provider.fetch_markets()
    news = await resolved_provider.fetch_news()
    snapshot = await build_snapshot(engine, settings)
    return compose_world_briefing(markets, news, snapshot, settings)
