"""Evidence-first daily world briefing and deterministic causal explanations."""

# ruff: noqa: RUF001

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from macro_engine.config import Settings
from macro_engine.providers.public_intelligence import PublicIntelligenceProvider
from macro_engine.services.terminal import build_snapshot

UP_WORDS = {"up": "上涨", "down": "下跌", "flat": "变化不大", "unavailable": "暂无"}
LOW_SIGNAL_TERMS = (
    "enforcement action",
    "consent order",
    "former chief",
    "application for acquisition",
    "application to acquire",
    "prohibition order",
    "termination of enforcement",
)
EASING_TERMS = (
    "rate cut",
    "cuts rates",
    "cuts interest rates",
    "lower rates",
    "dovish",
    "easing",
    "disinflation",
    "slowdown",
    "recession",
)
TIGHTENING_TERMS = (
    "rate hike",
    "hike",
    "higher rates",
    "hawkish",
    "high inflation",
    "no rate cut",
    "hold rates",
    "sticky inflation",
)


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _policy_bias(title: str) -> str:
    if _has_any(title, EASING_TERMS):
        return "easing"
    if _has_any(title, TIGHTENING_TERMS):
        return "tightening"
    return "uncertain"


def _energy_bias(title: str) -> str:
    if _has_any(
        title,
        (
            "sanction",
            "attack",
            "war",
            "supply cut",
            "output cut",
            "disruption",
            "shortage",
        ),
    ):
        return "scarcity"
    if _has_any(title, ("ceasefire", "output increase", "supply increase", "demand falls")):
        return "relief"
    return "uncertain"


def _risk_bias(title: str) -> str:
    if _has_any(title, ("ceasefire", "peace deal", "truce", "de-escalation")):
        return "deescalation"
    if _has_any(title, ("war", "attack", "sanction", "conflict", "strike")):
        return "escalation"
    return "uncertain"


def event_playbook(title: str, category: str) -> dict[str, object]:
    """Map a headline to a falsifiable macro transmission hypothesis."""

    lowered = title.lower()
    rate_terms = (
        "interest rate",
        "rates",
        "inflation",
        "cpi",
        "fomc",
        "monetary policy",
        "powell",
        "payroll",
        "jobs report",
    )
    is_rate_story = _has_any(lowered, rate_terms) or (
        ("federal reserve" in lowered or "fed " in lowered)
        and not _has_any(lowered, LOW_SIGNAL_TERMS)
    )
    if is_rate_story:
        bias = _policy_bias(lowered)
        if bias == "easing":
            scenario = "利率路径偏松"
            expectation_shift = "市场可能正在下调未来政策利率或实际利率路径。"
            expected_moves = {
                "us10y": "down",
                "dollar": "down",
                "gold": "up",
                "nasdaq": "up",
            }
        elif bias == "tightening":
            scenario = "利率路径偏紧"
            expectation_shift = "市场可能正在上调未来政策利率、通胀或实际利率路径。"
            expected_moves = {
                "us10y": "up",
                "dollar": "up",
                "gold": "down",
                "nasdaq": "down",
            }
        else:
            scenario = "利率路径仍有分歧"
            expectation_shift = "先判断信息究竟改变了降息、加息还是经济增长预期。"
            expected_moves = {}
        return {
            "event_type": "rates",
            "display_title": "美联储与美国利率路径出现新的重要信号",
            "core_question": "这条信息改变的是利率路径，还是央行对经济的判断？",
            "why_it_matters": "利率预期会先进入美债和美元，再通过贴现率与风险溢价影响黄金和股票。",
            "expectation_shift": expectation_shift,
            "causal_chain": [
                "新信息相对原有预期产生意外",
                "未来政策利率与实际利率路径重估",
                "美债收益率和美元先反应",
                "黄金与成长股再评估持有成本",
            ],
            "chain_labels": ["意外", "预期", "定价变量", "资产"],
            "assets": ["us10y", "dollar", "gold", "nasdaq", "sp500"],
            "concept": "预期差、实际利率与央行信息效应",
            "scenario": scenario,
            "expected_moves": expected_moves,
            "market_thesis": (
                "若利率路径是主要驱动，美债收益率与美元应先给出方向，黄金和纳斯达克随后确认；"
                "若股票与收益率同向上涨，则也可能是增长信息而非纯政策冲击。"
            ),
            "confirmations": [
                "两年期或十年期收益率沿假设方向移动",
                "美元与实际利率方向一致",
                "黄金和高久期成长股给出相反方向的二次确认",
            ],
            "falsifiers": [
                "美债和美元没有沿假设方向变化",
                "价格只在讲话瞬间波动，随后迅速完全反转",
            ],
            "alternatives": [
                "央行透露的是经济增长信息，而不是纯政策冲击",
                "期限溢价、财政供给或市场仓位主导了长端收益率",
            ],
            "learning_prompt": (
                "如果收益率上升、美元上涨，但纳斯达克也上涨，纯加息冲击的解释还完整吗？"
            ),
            "learning_answer": (
                "不完整。收益率和美元支持偏紧解释，但股票上涨提示增长信息、盈利预期或风险溢价下降"
                "可能同时存在，需要把“央行信息效应”列为替代解释。"
            ),
            "confidence": 0.82 if bias != "uncertain" else 0.68,
        }

    if _has_any(lowered, ("oil", "opec", "energy", "lng")) or category == "energy":
        bias = _energy_bias(lowered)
        if bias == "scarcity":
            scenario = "供应风险上升"
            expectation_shift = "市场可能在提高短期供应中断概率与原油风险溢价。"
            expected_moves = {"oil": "up", "us10y": "up", "sp500": "down", "gold": "up"}
        elif bias == "relief":
            scenario = "供应风险缓和"
            expectation_shift = "市场可能在下调供应中断概率与能源通胀风险。"
            expected_moves = {"oil": "down", "us10y": "down", "sp500": "up"}
        else:
            scenario = "供需方向待确认"
            expectation_shift = "先区分需求改善与供应收缩，因为两者对股票的含义相反。"
            expected_moves = {}
        return {
            "event_type": "energy",
            "display_title": "能源供应与油价变化正在重塑通胀路径",
            "core_question": "油价变化来自需求，还是来自供应风险溢价？",
            "why_it_matters": "能源同时影响通胀、企业利润率、居民实际收入和央行反应函数。",
            "expectation_shift": expectation_shift,
            "causal_chain": [
                "供需或地缘信息改变短缺概率",
                "现货价格与原油风险溢价调整",
                "通胀预期和债券收益率重估",
                "能源股、消费股与大盘出现分化",
            ],
            "chain_labels": ["冲击", "商品", "通胀利率", "股票"],
            "assets": ["oil", "us10y", "sp500", "gold"],
            "concept": "需求冲击与供应冲击",
            "scenario": scenario,
            "expected_moves": expected_moves,
            "market_thesis": (
                "油价上涨本身不能说明原因。油价与股票同涨更像需求改善；油价上涨而股票下跌、"
                "收益率上升，更像供应型通胀冲击。"
            ),
            "confirmations": [
                "油价方向与事件假设一致",
                "债券收益率或通胀预期同步反应",
                "能源股与消费、运输行业出现可解释的分化",
            ],
            "falsifiers": [
                "油价在事件后未延续或迅速反转",
                "库存、产量或运输数据与供应叙事相反",
            ],
            "alternatives": ["全球需求预期变化", "美元变化或短期仓位挤压"],
            "learning_prompt": "油价上涨时，为什么不能直接断言股票一定下跌？",
            "learning_answer": (
                "因为需求改善也会推高油价，并可能同时支持企业盈利与股票。只有供应收缩推高成本、"
                "压低实际收入时，油价上涨才更明确地构成股票逆风。"
            ),
            "confidence": 0.78 if bias != "uncertain" else 0.66,
        }

    if _has_any(lowered, ("china", "pboc", "中国", "央行")) or category == "china":
        supportive = _has_any(
            lowered,
            ("stimulus", "support", "rate cut", "reserve cut", "增长", "支持", "降准", "降息"),
        )
        expected_moves = {"a_shares": "up", "hong_kong": "up", "oil": "up"} if supportive else {}
        return {
            "event_type": "china_growth",
            "display_title": "中国政策与增长预期成为亚洲市场焦点",
            "core_question": "政策是在改善名义增长预期，还是只缓解短期流动性压力？",
            "why_it_matters": "中国增长会通过信用、人民币、商品需求和区域贸易影响亚洲资产。",
            "expectation_shift": (
                "市场可能在上调政策支持力度与名义增长预期。"
                if supportive
                else "需要区分政策信号、实际信用扩张和最终需求是否真的改善。"
            ),
            "causal_chain": [
                "政策或数据改变增长预期",
                "人民币、信用与内需预期调整",
                "A股和港股先重新定价",
                "商品与亚洲出口市场进一步确认",
            ],
            "chain_labels": ["政策数据", "信用汇率", "中国资产", "区域外溢"],
            "assets": ["a_shares", "hong_kong", "oil", "nikkei", "kospi"],
            "concept": "政策脉冲、信用脉冲与增长",
            "scenario": "政策支持增强" if supportive else "增长信号待确认",
            "expected_moves": expected_moves,
            "market_thesis": (
                "真正的增长改善通常不只表现为A股上涨，还应看到港股、商品需求和亚洲出口市场"
                "形成更广泛确认。"
            ),
            "confirmations": [
                "A股和港股同步而非单一市场上涨",
                "人民币、信用或商品需求数据改善",
                "亚洲出口型市场出现外溢反应",
            ],
            "falsifiers": ["行情只持续一个交易日", "信用与需求数据没有跟进"],
            "alternatives": ["技术性超跌反弹", "监管或行业单点政策而非宏观增长改善"],
            "learning_prompt": "为什么降息或降准不一定马上等于经济增长回升？",
            "learning_answer": (
                "政策只能先改善资金价格和可得性。企业与居民是否愿意借贷、银行是否愿意扩张信用、"
                "最终需求是否回升，决定了政策能否进入真实增长。"
            ),
            "confidence": 0.75 if supportive else 0.66,
        }

    if _has_any(lowered, ("japan", "boj", "yen", "korea", "bank of korea")):
        return {
            "event_type": "asia_fx",
            "display_title": "日本或韩国的利率与汇率预期正在变化",
            "core_question": "本币变化是在反映利差，还是在触发套息交易去杠杆？",
            "why_it_matters": "日元或韩元会影响出口竞争力、进口成本、银行利润和跨境资金成本。",
            "expectation_shift": "先观察本国收益率与汇率是否同步，判断央行路径是否真的改变。",
            "causal_chain": [
                "央行或通胀信息改变利差预期",
                "本币与本国收益率调整",
                "出口股、银行股和进口成本重估",
                "套息交易与亚洲资金流进一步变化",
            ],
            "chain_labels": ["政策", "利差汇率", "行业", "资金流"],
            "assets": ["nikkei", "kospi", "dollar", "us10y"],
            "concept": "利差、汇率与套息交易",
            "scenario": "区域利差重新定价",
            "expected_moves": {},
            "market_thesis": (
                "汇率与本国收益率必须一起看；单独的股指涨跌无法区分出口利好和金融条件收紧。"
            ),
            "confirmations": ["本币与本国收益率同步反应", "出口股与银行股出现合理分化"],
            "falsifiers": ["汇率变化没有利率市场确认", "股指主要由全球科技股而非本地政策驱动"],
            "alternatives": ["美国利率变化", "全球科技或半导体周期"],
            "learning_prompt": "为什么日元升值可能同时利空出口股、却利好居民购买力？",
            "learning_answer": (
                "出口企业换回日元的利润可能下降，但进口能源和商品变便宜，居民实际购买力改善。"
            ),
            "confidence": 0.7,
        }

    if _has_any(lowered, ("war", "attack", "sanction", "ceasefire", "conflict")):
        bias = _risk_bias(lowered)
        if bias == "escalation":
            scenario = "风险升级"
            expectation_shift = "市场可能在提高能源中断、制裁或尾部风险概率。"
            expected_moves = {"oil": "up", "gold": "up", "sp500": "down"}
        elif bias == "deescalation":
            scenario = "风险缓和"
            expectation_shift = "市场可能在下调能源中断与尾部风险概率。"
            expected_moves = {"oil": "down", "gold": "down", "sp500": "up"}
        else:
            scenario = "风险后果待确认"
            expectation_shift = "先判断事件是否改变能源、贸易或金融制裁的实际概率。"
            expected_moves = {}
        return {
            "event_type": "geopolitical_risk",
            "display_title": "地缘风险正在改变避险与能源定价",
            "core_question": "事件是否改变了真实经济后果，还是只制造了短期情绪？",
            "why_it_matters": (
                "只有进入能源、贸易、财政或金融制裁渠道，地缘风险才更可能形成持续价格影响。"
            ),
            "expectation_shift": expectation_shift,
            "causal_chain": [
                "冲突或制裁改变尾部风险概率",
                "能源供应与避险需求先调整",
                "原油、黄金和美元重新定价",
                "股票评估成本、增长与政策反应",
            ],
            "chain_labels": ["风险事件", "真实渠道", "先行资产", "宏观后果"],
            "assets": ["gold", "oil", "dollar", "sp500", "bitcoin"],
            "concept": "风险溢价与真实经济渠道",
            "scenario": scenario,
            "expected_moves": expected_moves,
            "market_thesis": (
                "持续的地缘风险行情应看到原油、黄金、运输或信用市场留下痕迹；"
                "只有新闻热度而无跨资产确认，通常不足以证明宏观影响。"
            ),
            "confirmations": ["原油或运输成本改变", "黄金、信用利差或波动率同步反应"],
            "falsifiers": ["相关市场在短时间内完全反转", "没有供应、贸易或制裁层面的实际变化"],
            "alternatives": ["同期利率或美元变化", "市场仓位导致的短期避险挤压"],
            "learning_prompt": "为什么战争新闻出现后，黄金并不一定持续上涨？",
            "learning_answer": (
                "如果事件没有改变能源、贸易或政策路径，最初避险买盘可能很快消退；"
                "同时美元和实际利率上升也可能抵消黄金的避险需求。"
            ),
            "confidence": 0.72 if bias != "uncertain" else 0.62,
        }

    if _has_any(lowered, ("tariff", "trade", "export control")):
        return {
            "event_type": "trade_policy",
            "display_title": "贸易政策正在改变增长、成本与供应链预期",
            "core_question": "这项政策主要冲击需求、成本，还是企业供应链？",
            "why_it_matters": "贸易限制会同时改变进口价格、利润率、汇率和跨国资本开支。",
            "expectation_shift": "市场需要重估企业成本、贸易量和政策报复概率。",
            "causal_chain": [
                "关税或出口限制改变贸易成本",
                "企业利润率与供应链计划调整",
                "汇率、商品与行业股票先分化",
                "增长和通胀预期进一步变化",
            ],
            "chain_labels": ["政策", "企业", "市场", "宏观"],
            "assets": ["dollar", "sp500", "a_shares", "hong_kong", "oil"],
            "concept": "贸易冲击的增长与通胀双重效应",
            "scenario": "贸易摩擦升温",
            "expected_moves": {},
            "market_thesis": "先看受影响行业和汇率，再判断冲击是否扩散到总需求与通胀。",
            "confirmations": ["受影响行业明显跑输", "汇率或航运价格出现持续变化"],
            "falsifiers": ["政策豁免迅速扩大", "企业利润指引没有变化"],
            "alternatives": ["行业自身盈利变化", "国内财政或货币政策对冲"],
            "learning_prompt": "为什么关税可能同时推高通胀并压低增长？",
            "learning_answer": (
                "进口成本上升会推高价格，但更高价格和不确定性又会压制实际需求与投资。"
            ),
            "confidence": 0.66,
        }

    event_type = f"general_{category}"
    return {
        "event_type": event_type,
        "display_title": "全球政策与增长预期出现新的变化",
        "core_question": "这条消息改变了哪个可观察的经济变量？",
        "why_it_matters": (
            "只有能落到增长、通胀、利率、汇率或风险溢价的消息，才更可能持续影响市场。"
        ),
        "expectation_shift": "当前标题不足以判断市场预期改变的方向，需要更多来源与价格确认。",
        "causal_chain": [
            "新信息进入市场",
            "参与者更新可量化预期",
            "最相关定价变量先调整",
            "其他资产确认或否定叙事",
        ],
        "chain_labels": ["信息", "预期", "变量", "验证"],
        "assets": ["sp500", "dollar", "gold"],
        "concept": "信息、预期与市场确认",
        "scenario": "方向待确认",
        "expected_moves": {},
        "market_thesis": "先找到最相关的定价变量；若跨资产没有一致反应，就应降低因果确信。",
        "confirmations": ["至少两个相关市场方向一致", "后续数据支持同一机制"],
        "falsifiers": ["价格没有延续", "更直接的数据指向另一种原因"],
        "alternatives": ["同期宏观数据", "行业或市场内部因素"],
        "learning_prompt": "如果一条新闻很重要，但相关资产完全不动，应该怎样更新判断？",
        "learning_answer": (
            "降低它是当前市场主要驱动的概率，并检查它是否早已被预期或被另一项冲击抵消。"
        ),
        "confidence": 0.5,
    }


def compose_events(news: list[dict[str, object]]) -> list[dict[str, object]]:
    """Select diverse high-impact stories and attach explicit causal hypotheses."""

    selected: list[dict[str, object]] = []
    seen_event_types: set[str] = set()
    for item in news:
        title = str(item["title"])
        category = str(item.get("category") or "world")
        lowered = title.lower()
        if category == "central_bank" and _has_any(lowered, LOW_SIGNAL_TERMS):
            continue
        playbook = event_playbook(title, category)
        event_type = str(playbook["event_type"])
        if event_type in seen_event_types:
            continue
        selected.append(
            {
                **item,
                **playbook,
                "rank": len(selected) + 1,
                "analysis_type": "evidence_based_hypothesis",
            }
        )
        seen_event_types.add(event_type)
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


MARKET_ROLES = {
    "gold": ("实际利率 / 避险", "这次波动由实际利率、美元还是避险需求主导？"),
    "sp500": ("增长 / 风险溢价", "盈利预期和风险溢价哪一个变化更大？"),
    "nasdaq": ("久期 / 流动性", "长端利率是否解释了成长股的相对表现？"),
    "dollar": ("利差 / 全球流动性", "美元变化来自美国利率优势还是全球避险？"),
    "us10y": ("增长 / 通胀 / 期限溢价", "收益率变化来自政策路径还是期限溢价？"),
    "oil": ("需求 / 供应风险", "油价变化是需求信号还是供应冲击？"),
    "bitcoin": ("流动性 / 去杠杆", "这是宏观流动性还是加密市场内部催化？"),
    "a_shares": ("中国政策 / 内需", "政策预期有没有进入信用与盈利？"),
    "hong_kong": ("中国增长 / 全球资金", "本地政策与海外流动性谁更重要？"),
    "nikkei": ("日元 / 出口 / 全球科技", "汇率还是全球科技周期在主导？"),
    "kospi": ("韩元 / 出口 / 半导体", "汇率、出口与半导体周期是否一致？"),
}


def market_explanation(
    market: dict[str, object],
    all_markets: list[dict[str, object]],
) -> dict[str, object]:
    """Explain a daily move using cross-asset confirmations, never hidden order flow."""

    key = str(market["key"])
    role, question = MARKET_ROLES.get(key, ("本地政策 / 全球风险", "哪个变量最能解释本次波动？"))
    if not market.get("available"):
        return {
            **market,
            "direction": "unavailable",
            "role": role,
            "question": question,
            "explanation": "免费行情源暂时没有返回该市场数据。",
            "evidence": [],
            "confidence": 0.0,
        }
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
            explanation = "美元与长端收益率同步走弱，黄金上涨得到跨资产确认。"
            confidence = 0.78
        elif change > 0:
            explanation = "黄金上涨，但美元和利率没有同时确认，避险或仓位可能在放大波动。"
            confidence = 0.55
        else:
            explanation = "黄金走弱；检查美元、实际利率和避险需求是否反向变化。"
            confidence = 0.58
    elif key in {"sp500", "nasdaq"}:
        if yield_10y is not None:
            evidence.append(f"十年期收益率代理当日{yield_10y:+.2f}%")
        if oil is not None:
            evidence.append(f"WTI原油当日{oil:+.2f}%")
        explanation = (
            "股票上涨；下一步区分盈利预期改善、利率下降与风险溢价收窄。"
            if change > 0
            else "股票下跌；下一步区分增长下修、利率压力与风险溢价上升。"
        )
        confidence = 0.62
    elif key == "dollar":
        explanation = (
            "美元走强；检查美国利率优势与全球避险是否同时上升。"
            if change > 0
            else "美元走弱；检查降息预期或海外增长预期是否改善。"
        )
        confidence = 0.6
    elif key == "us10y":
        explanation = (
            "长端收益率上升；增长、通胀、政策路径和期限溢价都可能贡献。"
            if change > 0
            else "长端收益率下降；降息预期、增长担忧或避险买入都可能贡献。"
        )
        confidence = 0.6
    elif key == "oil":
        explanation = (
            "油价上涨；用股票与收益率区分需求改善和供应型通胀。"
            if change > 0
            else "油价下跌；检查需求担忧、供应增加或风险溢价消退。"
        )
        confidence = 0.6
    elif key == "bitcoin":
        explanation = (
            "比特币上涨；检查风险偏好、美元流动性与加密内部催化。"
            if change > 0
            else "比特币下跌；检查流动性收紧、风险偏好与内部去杠杆。"
        )
        confidence = 0.52
    else:
        explanation = (
            "指数上涨；结合本地政策、汇率、出口权重与隔夜美股判断。"
            if change > 0
            else "指数下跌；结合本地政策、汇率、出口权重与全球风险判断。"
        )
        confidence = 0.5
    return {
        **market,
        "direction": direction,
        "role": role,
        "question": question,
        "explanation": explanation,
        "evidence": evidence,
        "confidence": confidence,
        "order_flow_known": False,
    }


def lead_validation(
    events: list[dict[str, object]],
    markets: list[dict[str, object]],
) -> dict[str, object]:
    """Compare the lead hypothesis with observed cross-asset directions."""

    if not events:
        return {
            "status": "no_thesis",
            "label": "等待主线",
            "summary": "没有足够事件证据建立可检验假设。",
            "rows": [],
        }
    event = events[0]
    raw_expected = event.get("expected_moves")
    expected_moves = raw_expected if isinstance(raw_expected, dict) else {}
    rows: list[dict[str, object]] = []
    supports = 0
    weakens = 0
    for key, expected in expected_moves.items():
        market = next((row for row in markets if row.get("key") == key), None)
        if market is None:
            continue
        observed = str(market.get("direction") or "unavailable")
        if observed in {"flat", "unavailable"}:
            status = "unclear"
        elif observed == expected:
            status = "supports"
            supports += 1
        else:
            status = "weakens"
            weakens += 1
        rows.append(
            {
                "market_key": key,
                "market_name": market.get("name_zh"),
                "role": market.get("role"),
                "expected": expected,
                "expected_label": UP_WORDS.get(str(expected), str(expected)),
                "observed": observed,
                "observed_label": UP_WORDS.get(observed, observed),
                "status": status,
            }
        )
    if not rows:
        status = "direction_unknown"
        label = "方向待确认"
        summary = "事件方向尚不明确，先观察最相关市场，不对价格强行归因。"
    elif supports and weakens:
        status = "mixed"
        label = "信号分裂"
        summary = "部分资产支持主线，部分资产反向；当前更像多重冲击同时存在。"
    elif supports >= 2 and not weakens:
        status = "supports"
        label = "初步一致"
        summary = "多个相关市场方向与假设一致，但日线共振仍不等于因果证明。"
    elif weakens > supports:
        status = "weakens"
        label = "证据偏弱"
        summary = "主要市场没有沿假设方向运行，应降低这条叙事的置信度。"
    else:
        status = "unclear"
        label = "证据不足"
        summary = "可用市场信号还不足以确认或推翻这条主线。"
    return {
        "event_id": event.get("id"),
        "scenario": event.get("scenario"),
        "status": status,
        "label": label,
        "summary": summary,
        "supports": supports,
        "weakens": weakens,
        "rows": rows,
        "timing_note": "当前为日线证据，可能混合事件前后的其他信息，不代表窄窗口因果识别。",
    }


def daily_lesson(events: list[dict[str, object]]) -> dict[str, object]:
    """Create a retrieval-practice loop from the day's highest-ranked event."""

    if not events:
        return {
            "concept": "信息、预期与价格",
            "question": "为什么好消息出现时，市场也可能下跌？",
            "simple": "价格反映的是消息相对原有预期的意外，而不是消息的绝对好坏。",
            "deep": "同一消息还会被仓位、流动性、政策反应和其他冲击改变。",
            "check_question": "如果数据很好但低于预期，价格更可能如何反应？",
            "worked_example": ["公布值很好", "市场预期更高", "形成负面预期差", "价格下跌"],
            "retrieval_answer": "市场交易的是预期差，因此绝对好消息也可能对应负面价格反应。",
            "transfer_question": "如果新闻完全符合预期，但价格大涨，你还会优先检查什么？",
        }
    event = events[0]
    return {
        "concept": event["concept"],
        "question": event["core_question"],
        "simple": event["why_it_matters"],
        "deep": event["market_thesis"],
        "check_question": event["learning_prompt"],
        "worked_example": event["causal_chain"],
        "retrieval_answer": event["learning_answer"],
        "transfer_question": (
            "把同一套判断方法换到另一个事件：先写出原预期、关键变量、确认资产和一个反证。"
        ),
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
        "mission": "先找预期差，再沿定价变量追踪传导，最后用跨资产价格验证。",
        "events": events,
        "markets": explained_markets,
        "lead_validation": lead_validation(events, explained_markets),
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
