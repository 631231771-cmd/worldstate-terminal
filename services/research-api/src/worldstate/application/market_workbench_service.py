"""Small read-only projections for the default market workbench.

These are context observations and official headlines, never event-window evidence.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from defusedxml import ElementTree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import Observation, Series

FACTOR_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "gold": (
        ("美国 10 年实际收益率", "treasury.real_10y"),
        ("美国 2 年国债收益率", "treasury.nominal_2y"),
        ("美国 10 年国债收益率", "treasury.nominal_10y"),
        ("广义美元", "US.EXTERNAL.BROAD_DOLLAR"),
        ("美国核心 CPI 月率", "USA.INFLATION.BLS_CPI_CORE_MOM"),
    ),
    "silver": (
        ("美国 10 年实际收益率", "treasury.real_10y"),
        ("广义美元", "US.EXTERNAL.BROAD_DOLLAR"),
        ("美国核心 CPI 月率", "USA.INFLATION.BLS_CPI_CORE_MOM"),
    ),
    "oil": (
        ("美国商业原油库存", "eia.crude_stocks"),
        ("美国原油产量", "eia.production"),
        ("美国原油进口", "eia.imports"),
        ("美国原油出口", "eia.exports"),
        ("美国石油产品供应量", "eia.products_supplied"),
        ("美国炼厂开工率", "eia.refinery_utilization"),
    ),
    "rates10": (
        ("美国 10 年国债收益率", "treasury.nominal_10y"),
        ("美国 10 年实际收益率", "treasury.real_10y"),
        ("美国核心 CPI 月率", "USA.INFLATION.BLS_CPI_CORE_MOM"),
    ),
    "rates2": (
        ("美国 2 年国债收益率", "treasury.nominal_2y"),
        ("美国核心 CPI 月率", "USA.INFLATION.BLS_CPI_CORE_MOM"),
    ),
    "dollar": (
        ("广义美元", "US.EXTERNAL.BROAD_DOLLAR"),
        ("美国 2 年国债收益率", "treasury.nominal_2y"),
        ("美国 10 年实际收益率", "treasury.real_10y"),
    ),
    "equity": (
        ("美国 2 年国债收益率", "treasury.nominal_2y"),
        ("美国 10 年实际收益率", "treasury.real_10y"),
        ("美国核心 CPI 月率", "USA.INFLATION.BLS_CPI_CORE_MOM"),
    ),
    "nasdaq": (
        ("美国 2 年国债收益率", "treasury.nominal_2y"),
        ("美国 10 年实际收益率", "treasury.real_10y"),
        ("广义美元", "US.EXTERNAL.BROAD_DOLLAR"),
    ),
}


def _factor_row(
    label: str, key: str, series: Series | None, rows: list[Observation]
) -> dict[str, Any]:
    latest = rows[0] if rows else None
    previous = rows[1] if len(rows) > 1 else None
    metadata = series.metadata_json if series else {}
    return {
        "label": label,
        "series_key": key,
        "value": float(latest.value) if latest and latest.value is not None else None,
        "previous_value": float(previous.value)
        if previous and previous.value is not None
        else None,
        "unit": series.unit if series else None,
        "frequency": series.frequency if series else None,
        "period": latest.period_start.isoformat() if latest else None,
        "available_at": latest.available_at.isoformat() if latest and latest.available_at else None,
        "source_url": series.source_url if series else None,
        "observed": bool(latest),
        "proxy": bool(metadata.get("is_proxy")),
        "point_in_time": bool(metadata.get("point_in_time")),
        "limitation": metadata.get("limitation"),
    }


async def market_factors(engine: AsyncEngine, asset: str) -> dict[str, Any]:
    definitions = FACTOR_GROUPS.get(asset, FACTOR_GROUPS["equity"])
    now = datetime.now(UTC)
    keys = [key for _, key in definitions]
    async with async_sessionmaker(engine)() as session:
        series = (await session.scalars(select(Series).where(Series.canonical_key.in_(keys)))).all()
        by_key = {item.canonical_key: item for item in series}
        items = []
        for label, key in definitions:
            current = by_key.get(key)
            rows: list[Observation] = []
            if current:
                result = await session.scalars(
                    select(Observation)
                    .where(
                        Observation.series_id == current.id,
                        Observation.data_mode == "observed",
                        Observation.value.is_not(None),
                        Observation.available_at <= now,
                        Observation.fetched_at <= now,
                        Observation.period_start <= now.date(),
                        Observation.vintage_date <= now.date(),
                    )
                    .order_by(
                        Observation.period_start.desc(),
                        Observation.available_at.desc(),
                        Observation.id.desc(),
                    )
                    .limit(20)
                )
                seen = set()
                for row in result:
                    if row.period_start not in seen:
                        rows.append(row)
                        seen.add(row.period_start)
                    if len(rows) == 2:
                        break
            items.append(_factor_row(label, key, current, rows))
    return {"asset": asset, "as_of": now.isoformat(), "items": items}


FEEDS = (
    ("Federal Reserve", "policy", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("EIA", "energy", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("EIA", "energy", "https://www.eia.gov/petroleum/weekly/includes/week_in_petroleum_rss.xml"),
)


def parse_official_feed(
    content: bytes, *, source: str, topic: str, retrieved_at: datetime
) -> list[dict[str, str]]:
    if (
        len(content) > 1_000_000
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("unexpected feed content")
    root = ElementTree.fromstring(content)
    items = []
    for node in root.findall(".//item")[:25]:
        title = (node.findtext("title") or "").strip()
        url = (node.findtext("link") or "").strip()
        if (
            not title
            or urlparse(url).scheme != "https"
            or urlparse(url).hostname not in {"www.federalreserve.gov", "www.eia.gov", "eia.gov"}
        ):
            continue
        published = node.findtext("pubDate") or node.findtext("date")
        try:
            published_at = (
                parsedate_to_datetime(published).astimezone(UTC).isoformat() if published else None
            )
        except (TypeError, ValueError, IndexError):
            published_at = None
        items.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "topic": topic,
                "published_at": published_at or "",
                "retrieved_at": retrieved_at.isoformat(),
            }
        )
    return items


def _fetch_feed(source: str, topic: str, url: str) -> list[dict[str, str]]:
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in {
        "www.federalreserve.gov", "www.eia.gov"
    }:
        raise ValueError("non-official feed URL")
    request = Request(  # noqa: S310 - official HTTPS hosts validated above
        url,
        headers={
            "User-Agent": "WorldStateTerminal/0.7 (+https://github.com/631231771-cmd/worldstate-terminal)"
        },
    )
    with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed official HTTPS URLs
        content = response.read(1_000_001)
    return parse_official_feed(content, source=source, topic=topic, retrieved_at=datetime.now(UTC))


class OfficialHeadlines:
    """Bounded cache: unavailable feeds never erase previously fetched items."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []
        self.next_refresh = 0.0
        self.lock = asyncio.Lock()

    async def read(self) -> dict[str, Any]:
        async with self.lock:
            if monotonic() >= self.next_refresh:
                results = await asyncio.gather(
                    *(
                        asyncio.to_thread(_fetch_feed, source, topic, url)
                        for source, topic, url in FEEDS
                    ),
                    return_exceptions=True,
                )
                latest = [item for result in results if isinstance(result, list) for item in result]
                if latest:
                    self.items = sorted(
                        {item["url"]: item for item in latest}.values(),
                        key=lambda item: item["published_at"],
                        reverse=True,
                    )[:40]
                self.next_refresh = monotonic() + 900
            return {
                "as_of": datetime.now(UTC).isoformat(),
                "items": list(self.items),
                "source_scope": (
                    "Federal Reserve 和 EIA 官方公告；"
                    "不代表完整市场新闻流，也不证明行情因果。"
                ),
            }
