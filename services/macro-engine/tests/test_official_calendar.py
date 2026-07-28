from __future__ import annotations

from datetime import UTC, datetime

import httpx

from macro_engine.providers.official_calendar import (
    BEA_ICS_URL,
    BLS_ICS_URL,
    ECB_CALENDAR_URL,
    FED_CALENDAR_URL,
    OfficialCalendarProvider,
    _bls_fallback_rows,
    _calendar_impact,
    _calendar_kind,
    _census_schedule_rows,
    _extract_ecb_dates,
    _extract_fomc_dates,
    _parse_ics_datetime,
    _static_date_rows,
    _unescape_ics,
    _unfold_ics,
    parse_ics_events,
    reset_official_calendar_cache,
)


def sample_ics(title: str, stamp: str) -> str:
    return "\r\n".join(
        (
            "BEGIN:VCALENDAR",
            "BEGIN:VEVENT",
            f"DTSTART:{stamp}",
            f"SUMMARY:{title}",
            "DESCRIPTION:First line\\nsecond line",
            "END:VEVENT",
            "END:VCALENDAR",
        )
    )


def test_calendar_parsers_and_playbooks() -> None:
    assert _unescape_ics(r"One\, two\; three\\four") == r"One, two; three\four"
    assert _unfold_ics("A:one\r\n two\r\nB:three") == ["A:onetwo", "B:three"]
    assert _parse_ics_datetime("20260731T123000Z") == datetime(2026, 7, 31, 12, 30, tzinfo=UTC)
    assert _parse_ics_datetime("bad") is None
    assert _calendar_kind("Consumer Price Index") == "inflation"
    assert _calendar_kind("Employment Situation") == "labor"
    assert _calendar_kind("GDP (Advance Estimate)") == "growth"
    assert _calendar_kind("Import and Export Prices") == "trade"
    assert _calendar_kind("Personal Income and Outlays") == "income"
    assert _calendar_kind("FOMC rate decision") == "policy"
    assert _calendar_kind("Wholesale inventories") == "macro"
    assert _calendar_impact("Consumer Price Index") == "high"
    assert _calendar_impact("Wholesale inventories") == "medium"

    rows = parse_ics_events(
        sample_ics("Consumer Price Index\\, July 2026", "20260731T123000Z"),
        source="Fixture Agency",
        source_url="https://agency.test/calendar",
        start=datetime(2026, 7, 27, tzinfo=UTC),
        end=datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Consumer Price Index, July 2026"
    assert rows[0]["kind"] == "inflation"
    assert rows[0]["impact"] == "high"
    assert rows[0]["retrieval"] == "live_official"
    assert rows[0]["watch_assets"] == ["us10y", "dollar", "gold", "silver", "nasdaq"]
    assert (
        parse_ics_events(
            "BEGIN:VEVENT\nDTSTART:bad\nSUMMARY:Bad\nEND:VEVENT",
            source="Fixture",
            source_url="https://example.test",
            start=datetime(2026, 7, 27, tzinfo=UTC),
            end=datetime(2026, 8, 2, tzinfo=UTC),
        )
        == []
    )

    static = _static_date_rows(
        ("2026-07-29",),
        title="FOMC 利率决议与新闻发布会",
        country="US",
        source="Federal Reserve",
        source_url=FED_CALENDAR_URL,
        hour=14,
    )
    assert static[0]["kind"] == "policy"
    assert static[0]["retrieval"] == "bundled_official_schedule"
    assert _bls_fallback_rows()
    assert _census_schedule_rows()[0]["kind"] == "growth"
    assert _extract_fomc_dates("<p>July 28\u201329, 2026</p>") == ["2026-07-29"]
    assert _extract_fomc_dates("<p>not a meeting</p>") == []
    assert _extract_ecb_dates(
        '<time datetime="2026-09-09">Day 1</time>'
        '<time datetime="2026-09-10">Day 2 monetary policy meeting</time>'
    ) == ["2026-09-10"]


async def test_official_calendar_live_merge_and_cache() -> None:
    reset_official_calendar_cache()

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == BLS_ICS_URL:
            return httpx.Response(
                200,
                text=sample_ics("Consumer Price Index, July 2026", "20260731T123000Z"),
            )
        if url == BEA_ICS_URL:
            return httpx.Response(
                200,
                text=sample_ics("GDP (Advance Estimate), Q2 2026", "20260730T123000Z"),
            )
        if url == FED_CALENDAR_URL:
            return httpx.Response(200, text="<p>July 28-29, 2026</p>")
        if url == ECB_CALENDAR_URL:
            return httpx.Response(
                200,
                text=(
                    '<time datetime="2026-09-09">Day 1</time>'
                    '<time datetime="2026-09-10">Day 2 monetary policy</time>'
                ),
            )
        raise AssertionError(url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OfficialCalendarProvider(client=client, horizon_days=45)
        rows, status = await provider.fetch(now=datetime(2026, 7, 27, tzinfo=UTC))
        cached_rows, cached_status = await provider.fetch(now=datetime(2026, 7, 27, tzinfo=UTC))

    assert any(row["source"] == "U.S. Bureau of Labor Statistics" for row in rows)
    assert any(row["source"] == "U.S. Bureau of Economic Analysis" for row in rows)
    assert any(row["source"] == "Federal Reserve" for row in rows)
    assert any(row["source"] == "Bank of England" for row in rows)
    assert any(row["source"] == "Bank of Japan" for row in rows)
    assert status["connected"] is True
    assert any(row["source"] == "U.S. Census Bureau" for row in rows)
    assert status["sources_attempted"] == 7
    assert status["sources_succeeded"] == 7
    assert cached_rows == rows
    assert cached_status["cache"]["hit"] is True


async def test_official_calendar_explicit_fallbacks() -> None:
    reset_official_calendar_cache()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows, status = await OfficialCalendarProvider(
            client=client,
            horizon_days=45,
        ).fetch(fresh=True, now=datetime(2026, 7, 27, tzinfo=UTC))

    assert rows
    assert any(row["retrieval"] == "bundled_official_schedule" for row in rows)
    assert status["connected"] is True
    assert status["calls"][0]["status"] == "fallback"
    assert status["calls"][1]["status"] == "failed"
    assert status["cache"]["hit"] is False
