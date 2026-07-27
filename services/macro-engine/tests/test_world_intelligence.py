# ruff: noqa: RUF001

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from macro_engine.api import world as world_api
from macro_engine.config import Settings
from macro_engine.main import create_app
from macro_engine.providers.public_intelligence import (
    FEEDS,
    MARKETS,
    PERSPECTIVE_FEEDS,
    FeedSpec,
    PublicIntelligenceProvider,
    _priority_value,
    article_importance,
    clean_text,
    google_news_url,
    parse_feed,
    parse_published,
    parse_x_search,
    parse_yahoo_quote,
)
from macro_engine.services.ai_tutor import (
    _chat_output_text,
    _openai_output_text,
    answer_tutor,
    build_evidence_pack,
    deterministic_answer,
    evidence_sources,
    request_ai,
    tutor_prompt,
)
from macro_engine.services.world_briefing import (
    build_world_briefing,
    complete_macro_chain,
    compose_events,
    compose_perspectives,
    compose_world_briefing,
    daily_lesson,
    daily_research_seminar,
    event_playbook,
    lead_validation,
    market_explanation,
)


def settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": f"sqlite+aiosqlite:///{(tmp_path / 'world.db').as_posix()}",
    }
    values.update(overrides)
    return Settings(**values)


def yahoo_payload(price: float = 105.0, previous: float = 100.0) -> dict[str, object]:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "previousClose": previous,
                        "chartPreviousClose": previous,
                    },
                    "timestamp": [1_700_000_000, 1_700_086_400],
                    "indicators": {"quote": [{"close": [99.0, None, price]}]},
                }
            ]
        }
    }


def news_item(
    title: str,
    category: str = "markets",
    source: str = "Fixture News",
    importance: int = 80,
) -> dict[str, object]:
    return {
        "id": title.lower().replace(" ", "-"),
        "title": title,
        "summary": "Fixture summary",
        "source": source,
        "url": "https://example.com/story",
        "published_at": "2026-07-23T08:00:00+00:00",
        "category": category,
        "language": "en",
        "importance": importance,
    }


def market_rows() -> list[dict[str, object]]:
    changes = {
        "gold": 1.2,
        "sp500": 0.6,
        "nasdaq": 0.9,
        "dollar": -0.4,
        "us10y": -1.1,
        "oil": 0.8,
        "bitcoin": 2.0,
        "a_shares": 0.3,
        "hong_kong": -0.2,
        "nikkei": 0.4,
        "kospi": -0.3,
    }
    return [
        {
            "key": spec.key,
            "name_zh": spec.name_zh,
            "name_en": spec.name_en,
            "symbol": spec.symbol,
            "unit": spec.unit,
            "region": spec.region,
            "price": 100.0,
            "previous_close": 99.0,
            "change_percent": changes[spec.key],
            "as_of": "2026-07-23T08:00:00+00:00",
            "source": "Fixture",
            "source_url": "https://example.com/market",
            "sparkline": [98.0, 99.0, 100.0],
            "available": True,
        }
        for spec in MARKETS
    ]


def macro_snapshot(mode: str = "DEMO") -> dict[str, object]:
    return {
        "mode": mode,
        "methodology_version": "fixture-v1",
        "states": [
            {"key": "growth", "score": 0.2, "label": "neutral", "confidence": 0.8},
            "ignore-me",
        ],
        "releases": [{"title": "CPI", "scheduled_at": "2026-07-24T12:30:00Z"}],
    }


def briefing_fixture() -> dict[str, object]:
    cfg = Settings()
    return compose_world_briefing(
        market_rows(),
        [news_item("Federal Reserve signals lower interest rates", "central_bank")],
        macro_snapshot(),
        cfg,
        [
            {
                **news_item("Liquidity is improving", source="Fixture Research"),
                "source_class": "researcher",
                "summary": "Dollar liquidity and credit conditions are improving.",
            }
        ],
    )


def test_public_intelligence_helpers_cover_rss_and_yahoo() -> None:
    assert "ceid=CN" in google_news_url("中国 经济", chinese=True)
    assert "ceid=US" in google_news_url("Federal Reserve")
    assert clean_text("<b>A &amp; B</b>\n news") == "A & B news"
    assert clean_text(None) == ""
    assert parse_published(None) is None
    assert parse_published("Wed, 23 Jul 2026 08:00:00 GMT") is not None
    assert parse_published("2026-07-23T08:00:00Z") == datetime(2026, 7, 23, 8, tzinfo=UTC)
    assert parse_published("not-a-date") is None
    assert article_importance("Federal Reserve inflation decision", "Federal Reserve") == 96
    assert article_importance("Ordinary market update", "Fixture") == 42
    ranking_now = datetime(2026, 7, 23, 8, tzinfo=UTC)
    assert _priority_value(
        {"importance": 60, "published_at": "2026-07-23T07:00:00Z"},
        ranking_now,
    ) > _priority_value(
        {"importance": 78, "published_at": "2026-07-21T12:00:00Z"},
        ranking_now,
    )

    feed = FeedSpec("Fixture", "https://example.com/rss", "markets")
    xml = """
    <rss><channel>
      <item>
        <title>Federal Reserve &amp; markets</title>
        <link>https://example.com/one</link>
        <pubDate>Wed, 23 Jul 2026 08:00:00 GMT</pubDate>
        <description><![CDATA[<b>Policy</b> changed.]]></description>
      </item>
      <item><title>Missing link</title></item>
    </channel></rss>
    """
    parsed = parse_feed(xml, feed)
    assert len(parsed) == 1
    assert parsed[0]["summary"] == "Policy changed."
    assert parsed[0]["source_class"] == "fact"
    assert parse_feed("<broken", feed) == []

    atom = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom title</title><link href="https://example.com/atom"/>
      <updated>2026-07-23T08:00:00Z</updated><summary>Atom summary</summary></entry>
    </feed>
    """
    assert parse_feed(atom, feed)[0]["title"] == "Atom title"

    quote = parse_yahoo_quote(yahoo_payload(), MARKETS[0])
    assert quote is not None
    assert quote["change_percent"] == 5.0
    assert quote["sparkline"] == [99.0, 105.0]
    range_payload = yahoo_payload()
    del range_payload["chart"]["result"][0]["meta"]["previousClose"]  # type: ignore[index]
    range_payload["chart"]["result"][0]["meta"]["chartPreviousClose"] = 80.0  # type: ignore[index]
    range_quote = parse_yahoo_quote(range_payload, MARKETS[0])
    assert range_quote is not None
    assert range_quote["previous_close"] == 99.0
    assert parse_yahoo_quote({}, MARKETS[0]) is None
    assert parse_yahoo_quote({"chart": {"result": []}}, MARKETS[0]) is None
    assert parse_yahoo_quote({"chart": {"result": [{}]}}, MARKETS[0]) is None
    assert (
        parse_yahoo_quote(
            {"chart": {"result": [{"meta": {"regularMarketPrice": "bad"}}]}},
            MARKETS[0],
        )
        is None
    )

    x_rows = parse_x_search(
        {
            "includes": {
                "users": [{"id": "7", "username": "macro_author", "name": "Macro Author"}]
            },
            "data": [
                {
                    "id": "99",
                    "author_id": "7",
                    "text": "Liquidity conditions are changing",
                    "created_at": "2026-07-23T08:00:00Z",
                    "lang": "en",
                    "public_metrics": {"like_count": 50, "retweet_count": 10},
                }
            ],
        }
    )
    assert x_rows[0]["source_class"] == "social"
    assert x_rows[0]["url"] == "https://x.com/macro_author/status/99"
    assert parse_x_search({"includes": "bad", "data": "bad"}) == []


async def test_public_provider_handles_success_failure_and_dedup(monkeypatch: Any) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "macro_engine.providers.public_intelligence.asyncio.sleep",
        no_sleep,
    )

    rss = """
    <rss><channel><item><title>Federal Reserve changes rates</title>
    <link>https://example.com/rates</link>
    <pubDate>Wed, 23 Jul 2026 08:00:00 GMT</pubDate></item></channel></rss>
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        if "query1.finance.yahoo.com" in request.url.host:
            if "GC%3DF" in str(request.url) or "GC=F" in str(request.url):
                return httpx.Response(200, json=yahoo_payload())
            return httpx.Response(503)
        if "bbc" in request.url.host:
            return httpx.Response(503)
        return httpx.Response(200, text=rss)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = PublicIntelligenceProvider(client=client)
        markets = await provider.fetch_markets()
        stories = await provider.fetch_news()
        perspectives = await provider.fetch_perspectives()

    assert len(markets) == len(MARKETS)
    assert any(row.get("available") for row in markets)
    assert any(not row.get("available") for row in markets)
    assert len(stories) == 1
    assert stories[0]["source"] == "Federal Reserve"
    assert perspectives
    assert perspectives[0]["source_class"] in {"institutional", "practitioner", "researcher"}
    assert len(FEEDS) >= 7
    assert len(PERSPECTIVE_FEEDS) >= 5


async def test_public_provider_uses_official_x_api_when_configured() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.x.com":
            assert request.headers["Authorization"] == "Bearer read-only-token"
            return httpx.Response(
                200,
                json={
                    "includes": {
                        "users": [{"id": "1", "username": "researcher", "name": "Researcher"}]
                    },
                    "data": [
                        {
                            "id": "2",
                            "author_id": "1",
                            "text": "Treasury supply may raise the term premium.",
                            "created_at": "2026-07-23T08:00:00Z",
                            "lang": "en",
                            "public_metrics": {"like_count": 125},
                        }
                    ],
                },
            )
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = "-".join(("read", "only", "token"))
        rows = await PublicIntelligenceProvider(
            client=client,
            x_bearer_token=token,
        ).fetch_perspectives()

    assert len(rows) == 1
    assert rows[0]["source_class"] == "social"


def test_event_playbooks_market_explanations_and_composition(tmp_path: Path) -> None:
    cases = [
        ("Federal Reserve cuts interest rates", "central_bank", "预期差、实际利率与央行信息效应"),
        ("OPEC discusses oil supply", "energy", "需求冲击与供应冲击"),
        ("China PBOC announces policy", "china", "政策脉冲、信用脉冲与增长"),
        ("Bank of Japan changes yen policy", "asia", "利差、汇率与套息交易"),
        ("War sanctions expand", "geopolitics", "风险溢价与真实经济渠道"),
        ("Technology summit opens", "world", "信息、预期与市场确认"),
    ]
    for title, category, concept in cases:
        assert event_playbook(title, category)["concept"] == concept

    stories = [news_item("Federal Reserve enforcement action", "central_bank", importance=101)]
    stories.extend(
        news_item(title, category, importance=100 - index)
        for index, (title, category, _concept) in enumerate(cases)
    )
    events = compose_events(stories)
    assert len(events) == 5
    assert events[0]["rank"] == 1
    assert events[0]["analysis_type"] == "evidence_based_hypothesis"
    assert events[0]["expectation_shift"]
    assert events[0]["falsifiers"]
    assert events[0]["learning_answer"]
    assert len({event["event_type"] for event in events}) == len(events)
    assert all("enforcement" not in str(event["title"]).lower() for event in events)

    markets = market_rows()
    explanations = {str(row["key"]): market_explanation(row, markets) for row in markets}
    assert "跨资产确认" in str(explanations["gold"]["explanation"])
    assert explanations["nasdaq"]["direction"] == "up"
    assert explanations["hong_kong"]["direction"] == "down"
    assert explanations["dollar"]["confidence"] == 0.6
    assert explanations["us10y"]["confidence"] == 0.6
    assert explanations["oil"]["confidence"] == 0.6
    assert explanations["bitcoin"]["confidence"] == 0.52
    assert explanations["nikkei"]["confidence"] == 0.5
    assert explanations["gold"]["role"] == "实际利率 / 避险"
    assert explanations["gold"]["question"]

    no_data = {**markets[0], "available": False}
    assert market_explanation(no_data, markets)["direction"] == "unavailable"
    unconfirmed = [
        {**row, "change_percent": 0.4 if row["key"] in {"gold", "dollar", "us10y"} else 0.0}
        for row in markets
    ]
    assert "没有同时确认" in str(market_explanation(unconfirmed[0], unconfirmed)["explanation"])
    gold_down = [
        {**row, "change_percent": -0.4 if row["key"] == "gold" else 0.0} for row in markets
    ]
    assert "黄金走弱" in str(market_explanation(gold_down[0], gold_down)["explanation"])

    assert daily_lesson([])["concept"] == "信息、预期与价格"
    assert daily_lesson(events)["concept"] == events[0]["concept"]
    assert daily_lesson(events)["retrieval_answer"]

    raw_perspectives = [
        {
            **news_item("Treasury supply and term premium", source="Macro Research"),
            "summary": "Fiscal deficits and Treasury issuance may lift the term premium.",
            "source_class": "researcher",
        },
        {
            **news_item("Liquidity pulse", source="Market Author"),
            "summary": "Dollar liquidity may support risk assets.",
            "source_class": "social",
        },
    ]
    perspectives = compose_perspectives(raw_perspectives)
    assert perspectives[0]["lens"] == "财政与债券供给"
    assert perspectives[0]["test_with"]
    assert "反证" not in str(perspectives[0]["caveat"])
    seminar = daily_research_seminar(events, perspectives)
    assert seminar["level"] == "研究生研讨"
    assert len(seminar["agenda"]) == 4  # type: ignore[arg-type]
    assert seminar["assignment"]["rubric"]  # type: ignore[index]

    validation = lead_validation(events, list(explanations.values()))
    assert validation["status"] == "supports"
    assert validation["supports"] == 4
    assert all(row["status"] == "supports" for row in validation["rows"])
    chain = complete_macro_chain(events, list(explanations.values()), validation)
    assert len(chain["stages"]) == 8  # type: ignore[arg-type]
    assert chain["current_stage"] == "pricing"
    assert chain["stages"][0]["title"] == "事实冲击"  # type: ignore[index]
    assert chain["stages"][-1]["title"] == "资产结果"  # type: ignore[index]

    cfg = settings(tmp_path)
    live = compose_world_briefing(
        markets,
        stories,
        macro_snapshot("LIVE"),
        cfg,
        raw_perspectives,
    )
    assert live["evidence_mode"] == "LIVE"
    assert live["macro_context"]["states"][0]["key"] == "growth"  # type: ignore[index]
    assert len(live["macro_chain"]["stages"]) == 8  # type: ignore[index]
    assert live["lead_validation"]["rows"]  # type: ignore[index]
    assert live["seminar"]["research_question"]  # type: ignore[index]
    assert len(live["curriculum"]) == 6  # type: ignore[arg-type]
    assert len(live["perspectives"]) == 2  # type: ignore[arg-type]
    assert live["integrations"]["x"]["configured"] is False  # type: ignore[index]
    partial = compose_world_briefing(
        [{**row, "available": False} for row in markets],
        stories,
        macro_snapshot(),
        cfg,
    )
    assert partial["evidence_mode"] == "PARTIAL"
    offline = compose_world_briefing(
        [{**row, "available": False} for row in markets],
        [],
        {"mode": "EMPTY"},
        cfg,
    )
    assert offline["evidence_mode"] == "OFFLINE"


async def test_build_world_briefing_uses_provider_and_snapshot(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    class FixtureProvider:
        async def fetch_markets(self) -> list[dict[str, object]]:
            return market_rows()

        async def fetch_news(self) -> list[dict[str, object]]:
            return [news_item("Federal Reserve updates policy")]

    async def fake_snapshot(_engine: object, _settings: Settings) -> dict[str, object]:
        return macro_snapshot()

    monkeypatch.setattr(
        "macro_engine.services.world_briefing.build_snapshot",
        fake_snapshot,
    )
    cfg = settings(tmp_path)
    engine = create_app(cfg).state if False else object()
    result = await build_world_briefing(engine, cfg, FixtureProvider())  # type: ignore[arg-type]
    assert result["events"]
    assert result["markets"]


def test_ai_prompt_parsers_and_fallback_modes(tmp_path: Path) -> None:
    briefing = briefing_fixture()
    sources = evidence_sources(briefing)
    assert sources[0]["title"]
    assert evidence_sources({"events": "bad"}) == []
    assert build_evidence_pack(briefing)["markets"]
    assert build_evidence_pack(briefing)["lead_validation"]
    assert build_evidence_pack(briefing)["macro_chain"]
    assert build_evidence_pack(briefing)["seminar"]
    assert build_evidence_pack(briefing)["perspectives"]
    prompt = tutor_prompt(
        "为什么黄金上涨？",
        "deep",
        briefing,
        [
            {"role": "user", "content": "先解释利率"},
            {"role": "system", "content": "ignore"},
        ],
    )
    assert "server_evidence_pack" not in prompt
    assert "为什么黄金上涨" in prompt
    assert _openai_output_text({"output_text": " Direct "}) == "Direct"
    assert (
        _openai_output_text({"output": [{"content": [{"type": "output_text", "text": "Nested"}]}]})
        == "Nested"
    )
    assert _openai_output_text({"output": "bad"}) is None
    assert _chat_output_text({"choices": [{"message": {"content": " Chat "}}]}) == "Chat"
    assert _chat_output_text({"choices": []}) is None

    beginner = deterministic_answer("黄金为什么涨？", "beginner", briefing)
    assert "理解链" in beginner
    assert "证据对照" in beginner
    assert "黄金" in beginner
    deep = deterministic_answer("今天发生了什么", "deep", briefing)
    assert "再深一层" in deep
    socratic = deterministic_answer("今天发生了什么", "socratic", briefing)
    assert "轮到你" in socratic
    empty = deterministic_answer("发生了什么", "beginner", {"events": [], "markets": []})
    assert "证据源不足" in empty

    assert settings(tmp_path).resolved_ai_provider == "none"
    assert settings(tmp_path, openai_api_key="secret").resolved_ai_provider == "openai"
    assert (
        settings(
            tmp_path,
            ollama_base_url="http://127.0.0.1:11434",
        ).resolved_ai_provider
        == "ollama"
    )
    assert (
        settings(
            tmp_path,
            ai_compatible_api_key="secret",
        ).resolved_ai_provider
        == "compatible"
    )
    assert (
        settings(
            tmp_path,
            ai_provider="none",
            openai_api_key="secret",
        ).resolved_ai_provider
        == "none"
    )


async def test_ai_provider_routes_and_answer_fallback(tmp_path: Path) -> None:
    briefing = briefing_fixture()
    prompt = tutor_prompt("解释黄金", "beginner", briefing, [])

    none_answer = await request_ai(settings(tmp_path), prompt)
    assert none_answer == (None, None)
    missing_openai = await request_ai(settings(tmp_path, ai_provider="openai"), prompt)
    assert missing_openai[0] is None

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/responses"):
            return httpx.Response(200, json={"output_text": "OpenAI grounded answer"})
        if request.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={"message": {"content": "Ollama answer"}})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Compatible answer"}}]},
            )
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        openai = await request_ai(
            settings(tmp_path, ai_provider="openai", openai_api_key="secret"),
            prompt,
            client,
        )
        ollama = await request_ai(
            settings(
                tmp_path,
                ai_provider="ollama",
                ollama_base_url="http://ollama.test",
            ),
            prompt,
            client,
        )
        compatible = await request_ai(
            settings(
                tmp_path,
                ai_provider="compatible",
                ai_base_url="http://compatible.test/v1",
            ),
            prompt,
            client,
        )
    assert openai[0] == "OpenAI grounded answer"
    assert ollama[0] == "Ollama answer"
    assert compatible[0] == "Compatible answer"

    async def failing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(failing)) as client:
        failed = await request_ai(
            settings(tmp_path, ai_provider="openai", openai_api_key="secret"),
            prompt,
            client,
        )
    assert failed[0] is None
    assert "HTTPStatusError" in str(failed[1])

    response = await answer_tutor(
        settings(tmp_path),
        "黄金为什么上涨？",
        "beginner",
        briefing,
        [],
    )
    assert response["provider"] == "deterministic"
    assert response["grounded"] is True


def test_world_api_cache_status_and_tutor(tmp_path: Path, monkeypatch: Any) -> None:
    world_api._briefing_cache = None
    briefing = briefing_fixture()
    calls = 0

    async def fake_build(_engine: object, _settings: Settings) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return briefing

    async def fake_answer(
        _settings: Settings,
        question: str,
        mode: str,
        _briefing: dict[str, object],
        _history: list[dict[str, str]],
    ) -> dict[str, object]:
        return {
            "answer": f"{mode}:{question}",
            "provider": "fixture",
            "grounded": True,
        }

    monkeypatch.setattr(world_api, "build_world_briefing", fake_build)
    monkeypatch.setattr(world_api, "answer_tutor", fake_answer)
    cfg = settings(tmp_path)
    with TestClient(create_app(cfg)) as client:
        assert client.get("/v1/world/briefing").status_code == 200
        assert client.get("/v1/world/briefing").status_code == 200
        assert calls == 1
        assert client.get("/v1/world/briefing?fresh=true").status_code == 200
        assert calls == 2
        status = client.get("/v1/world/ai-status").json()
        assert status["provider"] == "none"
        response = client.post(
            "/v1/world/ask",
            json={
                "question": "为什么黄金上涨？",
                "mode": "deep",
                "history": [{"role": "user", "content": "先说利率"}],
            },
        )
        assert response.status_code == 200
        assert response.json()["answer"].startswith("deep:")
        assert client.post("/v1/world/ask", json={"question": ""}).status_code == 422


def test_provider_can_own_and_close_client(monkeypatch: Any) -> None:
    class FakeClient:
        closed = False

        async def get(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return httpx.Response(503, request=httpx.Request("GET", "https://example.com"))

        async def aclose(self) -> None:
            self.closed = True

    fake = FakeClient()

    async def client_context(_self: PublicIntelligenceProvider) -> Any:
        return fake

    monkeypatch.setattr(PublicIntelligenceProvider, "_client_context", client_context)
    provider = PublicIntelligenceProvider()
    asyncio.run(provider.fetch_news())
    assert fake.closed is True
