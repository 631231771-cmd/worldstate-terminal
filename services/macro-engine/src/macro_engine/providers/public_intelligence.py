"""Free, keyless market and news evidence for the daily world briefing."""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree.ElementTree import Element

import httpx
from defusedxml import ElementTree

USER_AGENT = "WorldStateTerminal/0.2 (+local educational research)"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


@dataclass(frozen=True)
class MarketSpec:
    key: str
    name_zh: str
    name_en: str
    symbol: str
    unit: str
    region: str


@dataclass(frozen=True)
class FeedSpec:
    name: str
    url: str
    category: str
    language: str = "en"


MARKETS = (
    MarketSpec("gold", "黄金", "Gold", "GC=F", "USD/oz", "global"),
    MarketSpec("sp500", "标普500", "S&P 500", "^GSPC", "index", "US"),
    MarketSpec("nasdaq", "纳斯达克", "Nasdaq", "^IXIC", "index", "US"),
    MarketSpec("dollar", "美元指数", "US Dollar Index", "DX-Y.NYB", "index", "global"),
    MarketSpec("us10y", "美国十年期国债收益率", "US 10Y Yield", "^TNX", "%", "US"),
    MarketSpec("oil", "WTI原油", "WTI Crude", "CL=F", "USD/bbl", "global"),
    MarketSpec("bitcoin", "比特币", "Bitcoin", "BTC-USD", "USD", "global"),
    MarketSpec("a_shares", "上证指数", "Shanghai Composite", "000001.SS", "index", "China"),
    MarketSpec("hong_kong", "恒生指数", "Hang Seng", "^HSI", "index", "Hong Kong"),
    MarketSpec("nikkei", "日经225", "Nikkei 225", "^N225", "index", "Japan"),
    MarketSpec("kospi", "韩国综合指数", "KOSPI", "^KS11", "index", "South Korea"),
)


def google_news_url(query: str, *, chinese: bool = False) -> str:
    """Build an explicit regional Google News RSS search URL."""

    locale = "hl=zh-CN&gl=CN&ceid=CN:zh-Hans" if chinese else "hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&{locale}"


FEEDS = (
    FeedSpec(
        "Federal Reserve",
        "https://www.federalreserve.gov/feeds/press_all.xml",
        "central_bank",
    ),
    FeedSpec("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "geopolitics"),
    FeedSpec(
        "Reuters Markets",
        google_news_url("site:reuters.com markets economy central bank when:2d"),
        "markets",
    ),
    FeedSpec(
        "Reuters World",
        google_news_url("site:reuters.com world politics trade war when:2d"),
        "geopolitics",
    ),
    FeedSpec(
        "Asia Macro",
        google_news_url("(China economy OR PBOC OR Bank of Japan OR Bank of Korea) when:3d"),
        "asia",
    ),
    FeedSpec(
        "中国宏观",
        google_news_url("中国 央行 经济 政策 A股 港股 when:3d", chinese=True),
        "china",
        "zh",
    ),
    FeedSpec(
        "Energy",
        google_news_url("(oil OR OPEC OR LNG OR energy sanctions) when:3d"),
        "energy",
    ),
)

HIGH_IMPACT_TERMS = {
    "federal reserve",
    "fed ",
    "interest rate",
    "inflation",
    "cpi",
    "jobs",
    "payroll",
    "tariff",
    "sanction",
    "war",
    "ceasefire",
    "opec",
    "central bank",
    "bank of japan",
    "pboc",
    "中国人民银行",
    "央行",
}


def clean_text(value: str | None) -> str:
    """Normalize feed text without allowing embedded markup into the UI or prompt."""

    if not value:
        return ""
    unescaped = html.unescape(value)
    without_tags = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", without_tags).strip()


def parse_published(value: str | None) -> datetime | None:
    """Parse common RSS and Atom timestamps into UTC."""

    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _child_text(node: Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names and child.text:
            return child.text
    return ""


def _item_link(node: Element) -> str:
    for child in node.iter():
        if child.tag.rsplit("}", 1)[-1].lower() != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href
        if child.text:
            return child.text.strip()
    return ""


def article_importance(title: str, source: str) -> int:
    """Rank likely market-moving events using transparent, deterministic rules."""

    lowered = title.lower()
    hits = sum(term in lowered for term in HIGH_IMPACT_TERMS)
    if source == "Federal Reserve":
        hits += 1
    return min(100, 42 + hits * 18)


def _importance_value(item: dict[str, object]) -> int:
    value = item.get("importance")
    return value if isinstance(value, int) else 0


def parse_feed(xml_text: str, feed: FeedSpec) -> list[dict[str, object]]:
    """Parse RSS/Atom into a small normalized evidence contract."""

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    nodes = [
        node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}
    ]
    articles: list[dict[str, object]] = []
    for node in nodes[:15]:
        title = clean_text(_child_text(node, ("title",)))
        url = _item_link(node)
        if not title or not url or not url.startswith(("http://", "https://")):
            continue
        published = parse_published(_child_text(node, ("pubdate", "published", "updated", "date")))
        description = clean_text(
            _child_text(node, ("description", "summary", "encoded", "content"))
        )
        digest = hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:16]
        articles.append(
            {
                "id": digest,
                "title": title[:320],
                "summary": description[:600],
                "source": feed.name,
                "url": url,
                "published_at": published.isoformat() if published else None,
                "category": feed.category,
                "language": feed.language,
                "importance": article_importance(title, feed.name),
            }
        )
    return articles


def parse_yahoo_quote(payload: dict[str, Any], spec: MarketSpec) -> dict[str, object] | None:
    """Convert a Yahoo chart response to a provenance-bearing daily quote."""

    chart = payload.get("chart")
    if not isinstance(chart, dict):
        return None
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    result: dict[str, Any] = results[0]
    meta = result.get("meta")
    if not isinstance(meta, dict):
        return None
    price = meta.get("regularMarketPrice")
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    if (
        not isinstance(price, (int, float))
        or not isinstance(previous, (int, float))
        or not previous
    ):
        return None
    timestamps = result.get("timestamp")
    as_of = datetime.now(UTC)
    if isinstance(timestamps, list) and timestamps and isinstance(timestamps[-1], (int, float)):
        as_of = datetime.fromtimestamp(timestamps[-1], tz=UTC)
    indicators = result.get("indicators")
    closes: list[float] = []
    if isinstance(indicators, dict):
        quote_rows = indicators.get("quote")
        if isinstance(quote_rows, list) and quote_rows and isinstance(quote_rows[0], dict):
            raw_closes = quote_rows[0].get("close")
            if isinstance(raw_closes, list):
                closes = [float(value) for value in raw_closes if isinstance(value, (int, float))][
                    -20:
                ]
    return {
        **asdict(spec),
        "price": float(price),
        "previous_close": float(previous),
        "change_percent": (float(price) - float(previous)) / float(previous) * 100,
        "as_of": as_of.isoformat(),
        "source": "Yahoo Finance",
        "source_url": f"https://finance.yahoo.com/quote/{quote_plus(spec.symbol)}",
        "sparkline": closes,
        "available": True,
    }


class PublicIntelligenceProvider:
    """Fetch public evidence with bounded timeouts and partial-failure semantics."""

    def __init__(
        self,
        timeout_seconds: float = 8.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def _client_context(self) -> httpx.AsyncClient:
        if self.client is not None:
            return self.client
        return httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    async def fetch_markets(self) -> list[dict[str, object]]:
        client = await self._client_context()
        owns_client = self.client is None
        rows: list[dict[str, object]] = []
        try:
            for index, spec in enumerate(MARKETS):
                if index:
                    await asyncio.sleep(0.15)
                url = YAHOO_CHART_URL.format(symbol=quote_plus(spec.symbol))
                try:
                    response = await client.get(
                        url,
                        params={"range": "1mo", "interval": "1d"},
                    )
                    response.raise_for_status()
                    parsed = parse_yahoo_quote(response.json(), spec)
                except (httpx.HTTPError, ValueError, TypeError):
                    parsed = None
                if parsed is None:
                    rows.append({**asdict(spec), "available": False})
                else:
                    rows.append(parsed)
        finally:
            if owns_client:
                await client.aclose()
        return rows

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        feed: FeedSpec,
    ) -> list[dict[str, object]]:
        try:
            response = await client.get(
                feed.url,
                headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return []
        return parse_feed(response.text, feed)

    async def fetch_news(self) -> list[dict[str, object]]:
        client = await self._client_context()
        owns_client = self.client is None
        try:
            groups = await asyncio.gather(*(self._fetch_feed(client, feed) for feed in FEEDS))
        finally:
            if owns_client:
                await client.aclose()
        deduplicated: dict[str, dict[str, object]] = {}
        for item in (article for group in groups for article in group):
            title_key = re.sub(r"\W+", "", str(item["title"]).lower())[:180]
            current = deduplicated.get(title_key)
            if current is None or _importance_value(item) > _importance_value(current):
                deduplicated[title_key] = item
        return sorted(
            deduplicated.values(),
            key=lambda item: (_importance_value(item), str(item.get("published_at") or "")),
            reverse=True,
        )[:40]
