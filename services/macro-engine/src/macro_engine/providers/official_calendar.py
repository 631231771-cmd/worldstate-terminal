"""Keyless official macro release and central-bank calendar.

The calendar deliberately prefers first-party schedules. BLS is known to block
some automated clients, so a small, dated 2026 fallback contains only the major
releases copied from its official annual schedule. Every row exposes whether it
came from a live calendar or that explicit fallback.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime, timedelta, tzinfo
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from macro_engine.providers.public_intelligence import USER_AGENT

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BEA_ICS_URL = "https://bea.gov/news/schedule/ics/online-calendar-subscription.ics"
FED_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ECB_CALENDAR_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
BOJ_CALENDAR_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
BOE_CALENDAR_URL = "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates"
CENSUS_CALENDAR_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"

NEW_YORK = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")

# High-information BLS releases only. Source:
# https://www.bls.gov/schedule/2026/ (reviewed 2026-07-27).
BLS_2026_MAJOR: tuple[tuple[str, str, str], ...] = (
    ("2026-07-31", "08:30", "Employment Cost Index, Q2 2026"),
    ("2026-08-04", "10:00", "Job Openings and Labor Turnover Survey, June 2026"),
    ("2026-08-06", "08:30", "Productivity and Costs, Q2 2026"),
    ("2026-08-07", "08:30", "Employment Situation, July 2026"),
    ("2026-08-12", "08:30", "Consumer Price Index, July 2026"),
    ("2026-08-13", "08:30", "Producer Price Index, July 2026"),
    ("2026-08-18", "08:30", "U.S. Import and Export Price Indexes, July 2026"),
    ("2026-09-01", "10:00", "Job Openings and Labor Turnover Survey, July 2026"),
    ("2026-09-03", "08:30", "Productivity and Costs, Q2 2026 (revised)"),
    ("2026-09-04", "08:30", "Employment Situation, August 2026"),
    ("2026-09-10", "08:30", "Producer Price Index, August 2026"),
    ("2026-09-11", "08:30", "Consumer Price Index, August 2026"),
    ("2026-09-16", "08:30", "U.S. Import and Export Price Indexes, August 2026"),
    ("2026-09-29", "10:00", "Job Openings and Labor Turnover Survey, August 2026"),
    ("2026-10-02", "08:30", "Employment Situation, September 2026"),
    ("2026-10-14", "08:30", "Consumer Price Index, September 2026"),
    ("2026-10-15", "08:30", "Producer Price Index, September 2026"),
    ("2026-10-16", "08:30", "U.S. Import and Export Price Indexes, September 2026"),
    ("2026-10-30", "08:30", "Employment Cost Index, Q3 2026"),
    ("2026-11-03", "10:00", "Job Openings and Labor Turnover Survey, September 2026"),
    ("2026-11-05", "08:30", "Productivity and Costs, Q3 2026"),
    ("2026-11-06", "08:30", "Employment Situation, October 2026"),
    ("2026-11-10", "08:30", "Consumer Price Index, October 2026"),
    ("2026-11-13", "08:30", "Producer Price Index, October 2026"),
    ("2026-11-17", "08:30", "U.S. Import and Export Price Indexes, October 2026"),
    ("2026-12-01", "10:00", "Job Openings and Labor Turnover Survey, October 2026"),
    ("2026-12-04", "08:30", "Employment Situation, November 2026"),
    ("2026-12-08", "08:30", "Productivity and Costs, Q3 2026 (revised)"),
    ("2026-12-10", "08:30", "Consumer Price Index, November 2026"),
    ("2026-12-15", "08:30", "Producer Price Index, November 2026"),
    ("2026-12-17", "08:30", "U.S. Import and Export Price Indexes, November 2026"),
)

FOMC_2026 = (
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
)
ECB_2026 = (
    "2026-01-30",
    "2026-03-19",
    "2026-04-30",
    "2026-06-11",
    "2026-07-23",
    "2026-09-10",
    "2026-10-29",
    "2026-12-17",
)
BOJ_2026 = (
    "2026-01-23",
    "2026-03-19",
    "2026-04-28",
    "2026-06-16",
    "2026-07-31",
    "2026-09-18",
    "2026-10-30",
    "2026-12-18",
)
BOE_2026 = (
    "2026-02-05",
    "2026-03-19",
    "2026-04-30",
    "2026-06-18",
    "2026-07-30",
    "2026-09-17",
    "2026-11-05",
    "2026-12-17",
)

# High-information Census manufacturing releases only. Source:
# https://www.census.gov/manufacturing/m3/release_schedule.html
# (reviewed 2026-07-27). These rows intentionally provide timing only;
# consensus and actual values require a separate results source.
CENSUS_DURABLE_GOODS_2026: tuple[tuple[str, str], ...] = (
    ("2026-07-27", "June 2026"),
    ("2026-08-26", "July 2026"),
    ("2026-09-25", "August 2026"),
    ("2026-10-27", "September 2026"),
    ("2026-11-25", "October 2026"),
    ("2026-12-23", "November 2026"),
)

_CACHE_LOCK = asyncio.Lock()
_CACHE_AT = 0.0
_CACHE_EVENTS: list[dict[str, object]] = []
_CACHE_STATUS: dict[str, object] = {}


def _unescape_ics(value: str) -> str:
    return (
        value.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_ics_datetime(value: str, timezone: ZoneInfo = NEW_YORK) -> datetime | None:
    cleaned = value.strip()
    formats = (
        ("%Y%m%dT%H%M%SZ", UTC),
        ("%Y%m%dT%H%M%S", timezone),
        ("%Y%m%d", timezone),
    )
    for fmt, tz in formats:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            continue
    return None


def parse_ics_events(
    text: str,
    *,
    source: str,
    source_url: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, object]]:
    """Parse the small iCalendar subset used by official release schedules."""

    rows: list[dict[str, object]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is None:
                continue
            scheduled = _parse_ics_datetime(current.get("DTSTART", ""))
            title = _unescape_ics(current.get("SUMMARY", ""))
            if scheduled and title and start <= scheduled <= end:
                rows.append(
                    _calendar_row(
                        title=title,
                        scheduled=scheduled,
                        country="US",
                        source=source,
                        source_url=source_url,
                        retrieval="live_official",
                    )
                )
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.split(";", 1)[0]] = value
    return rows


def _calendar_kind(title: str) -> str:
    lowered = title.lower()
    if any(
        term in lowered
        for term in (
            "fomc",
            "rate decision",
            "monetary policy",
            "bank rate",
            "利率决议",
            "货币政策",
        )
    ):
        return "policy"
    if any(term in lowered for term in ("consumer price", "producer price", "pce", "inflation")):
        return "inflation"
    if any(
        term in lowered
        for term in (
            "employment situation",
            "job openings",
            "labor turnover",
            "employment cost",
            "unemployment",
        )
    ):
        return "labor"
    if any(
        term in lowered
        for term in ("gdp", "productivity", "industrial production", "durable goods")
    ):
        return "growth"
    if "trade" in lowered or "import and export" in lowered:
        return "trade"
    if "personal income" in lowered or "outlays" in lowered:
        return "income"
    return "macro"


def _calendar_impact(title: str) -> str:
    lowered = title.lower()
    high_terms = (
        "fomc",
        "rate decision",
        "monetary policy",
        "bank rate",
        "consumer price",
        "employment situation",
        "gdp (advance",
        "personal income and outlays",
        "employment cost",
        "durable goods",
        "利率决议",
        "货币政策",
    )
    return "high" if any(term in lowered for term in high_terms) else "medium"


CALENDAR_PLAYBOOKS: dict[str, dict[str, object]] = {
    "policy": {
        "question": "声明、预测与新闻发布会相对市场定价更鹰派还是更鸽派？",
        "hotter": "更鹰派：短端利率与美元先上行，黄金和久期资产承压。",
        "softer": "更鸽派：利率与美元回落，黄金和成长股可能受益。",
        "watch_assets": ["us10y", "dollar", "gold", "silver", "nasdaq"],
    },
    "inflation": {
        "question": "公布值相对共识的意外来自住房、工资还是商品成本？",
        "hotter": "高于预期：利率路径上修，美元偏强，黄金与成长股先承压。",
        "softer": "低于预期：实际利率预期回落，久期资产和黄金更容易获得支持。",
        "watch_assets": ["us10y", "dollar", "gold", "silver", "nasdaq"],
    },
    "labor": {
        "question": "就业与工资是否同时偏强，还是数量强但质量正在转弱？",
        "hotter": "强于预期：增长韧性与政策维持高利率的概率同时上升。",
        "softer": "弱于预期：先区分温和降温与衰退风险，股票反应可能不同。",
        "watch_assets": ["us10y", "dollar", "sp500", "nasdaq"],
    },
    "growth": {
        "question": "增长意外是需求扩张、库存波动还是价格因素造成？",
        "hotter": "强于预期：周期资产受益，但若通胀同步走高，利率压力会抵消。",
        "softer": "弱于预期：收益率可能下降，但盈利预期和原油也可能承压。",
        "watch_assets": ["us10y", "sp500", "oil", "silver", "dollar"],
    },
    "trade": {
        "question": "变化来自国内需求、外部需求、价格还是汇率？",
        "hotter": "进口走强可能反映内需，出口走强可能改善增长与本币预期。",
        "softer": "贸易走弱需要区分需求放缓、供应受限和价格回落。",
        "watch_assets": ["dollar", "oil", "sp500", "a_shares"],
    },
    "income": {
        "question": "实际收入和消费能否在储蓄率与价格压力下继续支撑需求？",
        "hotter": "收入与消费偏强：增长韧性提高，但也可能推迟宽松。",
        "softer": "收入与消费偏弱：增长担忧增加，利率下降未必利好股票。",
        "watch_assets": ["us10y", "sp500", "dollar", "gold"],
    },
    "macro": {
        "question": "公布值相对共识改变了增长、通胀还是政策路径？",
        "hotter": "强于预期：检查利率、美元和周期资产是否同步确认。",
        "softer": "弱于预期：区分政策宽松预期与增长风险。",
        "watch_assets": ["us10y", "dollar", "sp500", "gold"],
    },
}


def _calendar_row(
    *,
    title: str,
    scheduled: datetime,
    country: str,
    source: str,
    source_url: str,
    retrieval: str,
    time_precision: str = "minute",
) -> dict[str, object]:
    kind = _calendar_kind(title)
    playbook = CALENDAR_PLAYBOOKS[kind]
    return {
        "id": re.sub(
            r"[^a-z0-9]+", "-", f"{country}-{scheduled.isoformat()}-{title}".lower()
        ).strip("-")[:180],
        "title": title,
        "scheduled_at": scheduled.astimezone(UTC).isoformat(),
        "country": country,
        "kind": kind,
        "impact": _calendar_impact(title),
        "source": source,
        "source_url": source_url,
        "retrieval": retrieval,
        "time_precision": time_precision,
        "question": playbook["question"],
        "scenario_hotter": playbook["hotter"],
        "scenario_softer": playbook["softer"],
        "watch_assets": playbook["watch_assets"],
    }


def _static_date_rows(
    dates: tuple[str, ...],
    *,
    title: str,
    country: str,
    source: str,
    source_url: str,
    hour: int,
    minute: int = 0,
    timezone: tzinfo = UTC,
    retrieval: str = "bundled_official_schedule",
    time_precision: str = "minute",
) -> list[dict[str, object]]:
    rows = []
    for raw in dates:
        scheduled = datetime.strptime(raw, "%Y-%m-%d").replace(
            hour=hour,
            minute=minute,
            tzinfo=timezone,
        )
        rows.append(
            _calendar_row(
                title=title,
                scheduled=scheduled,
                country=country,
                source=source,
                source_url=source_url,
                retrieval=retrieval,
                time_precision=time_precision,
            )
        )
    return rows


def _bls_fallback_rows() -> list[dict[str, object]]:
    rows = []
    for raw_date, raw_time, title in BLS_2026_MAJOR:
        local = datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M").replace(
            tzinfo=NEW_YORK
        )
        rows.append(
            _calendar_row(
                title=title,
                scheduled=local,
                country="US",
                source="U.S. Bureau of Labor Statistics",
                source_url="https://www.bls.gov/schedule/2026/",
                retrieval="bundled_official_schedule",
            )
        )
    return rows


def _census_schedule_rows() -> list[dict[str, object]]:
    rows = []
    for raw_date, reference_period in CENSUS_DURABLE_GOODS_2026:
        local = datetime.strptime(f"{raw_date} 08:30", "%Y-%m-%d %H:%M").replace(
            tzinfo=NEW_YORK
        )
        rows.append(
            _calendar_row(
                title=f"Advance Durable Goods Orders, {reference_period}",
                scheduled=local,
                country="US",
                source="U.S. Census Bureau",
                source_url=CENSUS_CALENDAR_URL,
                retrieval="bundled_official_schedule",
            )
        )
    return rows


def _extract_fomc_dates(page: str) -> list[str]:
    months = {
        "January": "01",
        "February": "02",
        "March": "03",
        "April": "04",
        "May": "05",
        "June": "06",
        "July": "07",
        "August": "08",
        "September": "09",
        "October": "10",
        "November": "11",
        "December": "12",
    }
    month_pattern = "|".join(months)
    pattern = re.compile(
        rf"\b({month_pattern})\s+\d{{1,2}}[-–](\d{{1,2}})\*?\s*,\s*(20\d{{2}})",
        re.IGNORECASE,
    )
    rows = []
    for month, day, year in pattern.findall(html.unescape(page)):
        canonical_month = next(key for key in months if key.lower() == month.lower())
        rows.append(f"{year}-{months[canonical_month]}-{int(day):02d}")
    return sorted(set(rows))


def _extract_ecb_dates(page: str) -> list[str]:
    rows: list[str] = []
    matches = list(re.finditer(r'datetime="(\d{4}-\d{2}-\d{2})"', page))
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else match.end() + 900
        context = html.unescape(page[match.start() : next_start])
        if re.search(r"monetary policy", context, re.IGNORECASE) and re.search(
            r"\bDay\s*2\b", context, re.IGNORECASE
        ):
            rows.append(match.group(1))
    return sorted(set(rows))


def _call_status(
    source: str,
    *,
    status: str,
    items: int,
    duration_ms: int,
    reason: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "source": source,
        "status": status,
        "items": items,
        "duration_ms": duration_ms,
    }
    if reason:
        row["reason"] = reason
    return row


class OfficialCalendarProvider:
    """Fetch and merge official release schedules with explicit fallbacks."""

    def __init__(
        self,
        timeout_seconds: float = 12.0,
        *,
        client: httpx.AsyncClient | None = None,
        horizon_days: int = 45,
        cache_seconds: float = 30 * 60,
    ) -> None:
        self.timeout_seconds = max(3.0, min(timeout_seconds, 30.0))
        self.client = client
        self.horizon_days = max(7, min(horizon_days, 92))
        self.cache_seconds = max(60.0, cache_seconds)

    async def _client_context(self) -> httpx.AsyncClient:
        if self.client is not None:
            return self.client
        return httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/calendar,text/html,application/xhtml+xml,*/*",
            },
        )

    async def _get(self, client: httpx.AsyncClient, url: str) -> tuple[str | None, int]:
        started = monotonic()
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.text, int((monotonic() - started) * 1000)
        except httpx.HTTPError:
            return None, int((monotonic() - started) * 1000)

    async def fetch(
        self,
        *,
        fresh: bool = False,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        """Return upcoming events and a source-level retrieval ledger."""

        global _CACHE_AT, _CACHE_EVENTS, _CACHE_STATUS
        resolved_now = (now or datetime.now(UTC)).astimezone(UTC)
        start = resolved_now - timedelta(hours=12)
        end = resolved_now + timedelta(days=self.horizon_days)

        async with _CACHE_LOCK:
            age = monotonic() - _CACHE_AT
            if not fresh and _CACHE_EVENTS and age < self.cache_seconds:
                status = {**_CACHE_STATUS}
                cached_cache = _CACHE_STATUS.get("cache")
                status["cache"] = {
                    **(cached_cache if isinstance(cached_cache, dict) else {}),
                    "hit": True,
                    "age_seconds": int(age),
                }
                status["checked_at"] = datetime.now(UTC).isoformat()
                return [
                    dict(row)
                    for row in _CACHE_EVENTS
                    if start <= datetime.fromisoformat(str(row["scheduled_at"])) <= end
                ], status

            client = await self._client_context()
            owns_client = self.client is None
            try:
                bls_result, bea_result, fed_result, ecb_result = await asyncio.gather(
                    self._get(client, BLS_ICS_URL),
                    self._get(client, BEA_ICS_URL),
                    self._get(client, FED_CALENDAR_URL),
                    self._get(client, ECB_CALENDAR_URL),
                )
            finally:
                if owns_client:
                    await client.aclose()

            rows: list[dict[str, object]] = []
            calls: list[dict[str, object]] = []

            bls_text, bls_ms = bls_result
            bls_rows = (
                parse_ics_events(
                    bls_text,
                    source="U.S. Bureau of Labor Statistics",
                    source_url=BLS_ICS_URL,
                    start=start,
                    end=end,
                )
                if bls_text
                else []
            )
            if not bls_rows:
                bls_rows = [
                    row
                    for row in _bls_fallback_rows()
                    if start <= datetime.fromisoformat(str(row["scheduled_at"])) <= end
                ]
                calls.append(
                    _call_status(
                        "BLS",
                        status="fallback",
                        items=len(bls_rows),
                        duration_ms=bls_ms,
                        reason="official_ics_unavailable",
                    )
                )
            else:
                calls.append(
                    _call_status("BLS", status="ok", items=len(bls_rows), duration_ms=bls_ms)
                )
            rows.extend(bls_rows)

            bea_text, bea_ms = bea_result
            bea_rows = (
                parse_ics_events(
                    bea_text,
                    source="U.S. Bureau of Economic Analysis",
                    source_url=BEA_ICS_URL,
                    start=start,
                    end=end,
                )
                if bea_text
                else []
            )
            rows.extend(bea_rows)
            calls.append(
                _call_status(
                    "BEA",
                    status="ok" if bea_rows else "failed",
                    items=len(bea_rows),
                    duration_ms=bea_ms,
                    reason=None if bea_rows else "official_ics_unavailable",
                )
            )

            fed_text, fed_ms = fed_result
            extracted_fomc_dates = [
                value
                for value in _extract_fomc_dates(fed_text or "")
                if value.startswith(str(resolved_now.year))
            ]
            fomc_dates = extracted_fomc_dates or list(FOMC_2026)
            fomc_retrieval = (
                "live_official" if extracted_fomc_dates else "bundled_official_schedule"
            )
            fomc_rows = [
                row
                for row in _static_date_rows(
                    tuple(fomc_dates),
                    title="FOMC 利率决议与新闻发布会",
                    country="US",
                    source="Federal Reserve",
                    source_url=FED_CALENDAR_URL,
                    hour=14,
                    timezone=NEW_YORK,
                    retrieval=fomc_retrieval,
                )
                if start <= datetime.fromisoformat(str(row["scheduled_at"])) <= end
            ]
            rows.extend(fomc_rows)
            calls.append(
                _call_status(
                    "Federal Reserve",
                    status="ok" if extracted_fomc_dates else "fallback",
                    items=len(fomc_rows),
                    duration_ms=fed_ms,
                    reason=None if extracted_fomc_dates else "current_year_dates_unavailable",
                )
            )

            ecb_text, ecb_ms = ecb_result
            extracted_ecb_dates = [
                value
                for value in _extract_ecb_dates(ecb_text or "")
                if value.startswith(str(resolved_now.year))
            ]
            ecb_dates = extracted_ecb_dates or list(ECB_2026)
            ecb_retrieval = "live_official" if extracted_ecb_dates else "bundled_official_schedule"
            ecb_rows = [
                row
                for row in _static_date_rows(
                    tuple(ecb_dates),
                    title="ECB 利率决议与新闻发布会",
                    country="EU",
                    source="European Central Bank",
                    source_url=ECB_CALENDAR_URL,
                    hour=14,
                    minute=15,
                    timezone=ZoneInfo("Europe/Berlin"),
                    retrieval=ecb_retrieval,
                )
                if start <= datetime.fromisoformat(str(row["scheduled_at"])) <= end
            ]
            rows.extend(ecb_rows)
            calls.append(
                _call_status(
                    "European Central Bank",
                    status="ok" if extracted_ecb_dates else "fallback",
                    items=len(ecb_rows),
                    duration_ms=ecb_ms,
                    reason=None if extracted_ecb_dates else "current_year_dates_unavailable",
                )
            )

            static_rows = [
                *_census_schedule_rows(),
                *_static_date_rows(
                    BOJ_2026,
                    title="日本银行货币政策会议结果",
                    country="JP",
                    source="Bank of Japan",
                    source_url=BOJ_CALENDAR_URL,
                    hour=6,
                    timezone=ZoneInfo("Asia/Tokyo"),
                    time_precision="date",
                ),
                *_static_date_rows(
                    BOE_2026,
                    title="英格兰银行利率决议",
                    country="GB",
                    source="Bank of England",
                    source_url=BOE_CALENDAR_URL,
                    hour=12,
                    timezone=LONDON,
                ),
            ]
            rows.extend(
                row
                for row in static_rows
                if start <= datetime.fromisoformat(str(row["scheduled_at"])) <= end
            )
            calls.extend(
                (
                    _call_status(
                        "U.S. Census Bureau",
                        status="scheduled",
                        items=sum(row["source"] == "U.S. Census Bureau" for row in rows),
                        duration_ms=0,
                    ),
                    _call_status(
                        "Bank of Japan",
                        status="scheduled",
                        items=sum(row["source"] == "Bank of Japan" for row in rows),
                        duration_ms=0,
                    ),
                    _call_status(
                        "Bank of England",
                        status="scheduled",
                        items=sum(row["source"] == "Bank of England" for row in rows),
                        duration_ms=0,
                    ),
                )
            )

            deduplicated: dict[tuple[str, str], dict[str, object]] = {}
            for row in rows:
                title_key = re.sub(r"\W+", "", str(row["title"]).lower())
                key = (str(row["scheduled_at"])[:16], title_key)
                deduplicated[key] = row
            ordered = sorted(
                deduplicated.values(),
                key=lambda row: (str(row["scheduled_at"]), str(row["title"])),
            )
            fetched_at = datetime.now(UTC).isoformat()
            status = {
                "state": "connected" if ordered else "unavailable",
                "connected": bool(ordered),
                "sources_attempted": len(calls),
                "sources_succeeded": sum(
                    call["status"] in {"ok", "scheduled", "fallback"} for call in calls
                ),
                "items": len(ordered),
                "calls": calls,
                "horizon_days": self.horizon_days,
                "cache": {
                    "hit": False,
                    "ttl_seconds": int(self.cache_seconds),
                    "fetched_at": fetched_at,
                    "age_seconds": 0,
                },
                "checked_at": fetched_at,
            }
            _CACHE_EVENTS = [dict(row) for row in ordered]
            _CACHE_STATUS = {**status}
            _CACHE_AT = monotonic()
            return ordered, status


def reset_official_calendar_cache() -> None:
    """Clear module cache for deterministic tests."""

    global _CACHE_AT, _CACHE_EVENTS, _CACHE_STATUS
    _CACHE_AT = 0.0
    _CACHE_EVENTS = []
    _CACHE_STATUS = {}
