from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest

from worldstate.application.licensed_sync_service import _te_mapping
from worldstate.data_quality import QualityGrade
from worldstate.provider_kit import (
    BLS_SERIES_MAP,
    DATABENTO_INSTRUMENTS,
    BarQuery,
    BlsOfficialProvider,
    DatabentoDownloadRequest,
    DatabentoMarketProvider,
    FederalReserveFomcProvider,
    FomcMaterialType,
    FredAlfredProvider,
    MarketInstrumentRef,
    ProviderError,
    ProviderErrorCode,
    ProviderSchemaError,
    TradingEconomicsBrowserPage,
    TradingEconomicsConsensusProvider,
)

NOW = datetime(2024, 3, 12, 13, 0, tzinfo=UTC)


def _bls_payload() -> dict[str, object]:
    def row(
        series_id: str,
        february: str,
        january: str,
        pct_1: str = "0.4",
        pct_12: str = "3.2",
    ) -> dict[str, object]:
        return {
            "seriesID": series_id,
            "data": [
                {
                    "year": "2024",
                    "period": "M02",
                    "value": february,
                    "latest": "true",
                    "calculations": {"pct_changes": {"1": pct_1, "12": pct_12}},
                },
                {
                    "year": "2024",
                    "period": "M01",
                    "value": january,
                    "calculations": {"pct_changes": {"1": "0.3", "12": "3.1"}},
                },
            ],
        }

    return {
        "status": "REQUEST_SUCCEEDED",
        "message": [],
        "Results": {
            "series": [
                row("CUSR0000SA0", "311.054", "309.685"),
                row("CUSR0000SA0L1E", "317.129", "315.536", "0.4", "3.8"),
            ]
        },
    }


def test_bls_cpi_mapping_units_revision_and_point_in_time_guard() -> None:
    provider = BlsOfficialProvider()
    previous = {
        "CUSR0000SA0:2024-02-01:pct_1": Decimal("0.3"),
        "CUSR0000SA0:2024-01-01:pct_1": Decimal("0.2"),
    }
    batch = provider.adapt_payload(
        _bls_payload(),
        family="US_CPI",
        retrieved_at=NOW,
        available_at=datetime(2024, 3, 12, 12, 30, tzinfo=UTC),
        prior_snapshot=previous,
    )
    assert BLS_SERIES_MAP["US_CPI.HEADLINE.MOM"] == "CUSR0000SA0"
    assert BLS_SERIES_MAP["US_CPI.HEADLINE.YOY"] == "CUSR0000SA0"
    latest_mom = next(
        item
        for item in batch.observations
        if item.canonical_key == "US_CPI.HEADLINE.MOM"
        and item.reference_period_start == date(2024, 2, 1)
    )
    assert latest_mom.value == Decimal("0.4")
    assert latest_mom.raw_unit == "index_1982_84_100"
    assert latest_mom.standard_unit == "percent_change"
    assert latest_mom.is_revision is True
    assert latest_mom.previous_value == Decimal("0.2")
    assert latest_mom.revised_previous_value == Decimal("0.3")
    assert batch.artifacts[0].content_hash == latest_mom.artifact_hash

    with pytest.raises(ProviderError) as error:
        provider.adapt_payload(
            _bls_payload(),
            family="US_CPI",
            retrieved_at=NOW,
            as_of=datetime(2024, 3, 12, 12, 59, tzinfo=UTC),
        )
    assert error.value.error_code == ProviderErrorCode.POINT_IN_TIME


def test_bls_nfp_mapping_and_schedule_structure_error() -> None:
    assert BLS_SERIES_MAP["US_NFP.NONFARM_PAYROLLS"] == "CES0000000001"
    assert BLS_SERIES_MAP["US_NFP.UNEMPLOYMENT_RATE"] == "LNS14000000"
    assert BLS_SERIES_MAP["US_NFP.AVERAGE_HOURLY_EARNINGS.MOM"] == "CES0500000003"
    assert BLS_SERIES_MAP["US_NFP.LABOR_FORCE_PARTICIPATION"] == "LNS11300000"
    provider = BlsOfficialProvider()
    payroll_batch = provider.adapt_payload(
        {
            "status": "REQUEST_SUCCEEDED",
            "message": [],
            "Results": {
                "series": [
                    {
                        "seriesID": "CES0000000001",
                        "data": [
                            {"year": "2024", "period": "M02", "value": "157000"},
                            {"year": "2024", "period": "M01", "value": "156725"},
                            {"year": "2023", "period": "M12", "value": "156496"},
                        ],
                    }
                ]
            },
        },
        family="US_NFP",
        retrieved_at=NOW,
    )
    payrolls = [
        item
        for item in payroll_batch.observations
        if item.canonical_key == "US_NFP.NONFARM_PAYROLLS"
    ]
    assert [(item.reference_period_start, item.value) for item in payrolls] == [
        (date(2024, 1, 1), Decimal("229")),
        (date(2024, 2, 1), Decimal("275")),
    ]
    assert payrolls[-1].raw_unit == "thousand_persons_level"
    assert payrolls[-1].standard_unit == "thousand_persons"
    assert (
        payrolls[-1].metadata["derivation"]
        == "first_difference_of_seasonally_adjusted_payroll_level"
    )
    schedule = provider.adapt_schedule_html(
        """
        <table class="release-list">
          <tr><th>Date</th><th>Time</th></tr>
          <tr><td>March 12</td><td>08:30 AM</td></tr>
        </table>
        """,
        family="US_CPI",
        year=2024,
        retrieved_at=NOW,
        source_url="https://www.bls.gov/schedule/news_release/cpi.htm",
    )
    assert schedule.entries[0].source_timezone == "America/New_York"
    assert schedule.entries[0].scheduled_local.hour == 8
    with pytest.raises(ProviderSchemaError):
        provider.adapt_schedule_html(
            "<html><p>layout changed</p></html>",
            family="US_CPI",
            year=2024,
            retrieved_at=NOW,
            source_url="https://www.bls.gov/schedule/news_release/cpi.htm",
        )


def test_bls_public_response_derives_disabled_percent_calculations_from_levels() -> None:
    provider = BlsOfficialProvider()
    batch = provider.adapt_payload(
        {
            "status": "REQUEST_SUCCEEDED",
            "message": ["Calculations have been disabled for this request."],
            "Results": {
                "series": [
                    {
                        "seriesID": series_id,
                        "data": [
                            {"year": "2024", "period": "M02", "value": "101.0"},
                            {"year": "2024", "period": "M01", "value": "100.0"},
                            {"year": "2023", "period": "M02", "value": "100.0"},
                        ],
                    }
                    for series_id in ("CUSR0000SA0", "CUSR0000SA0L1E")
                ]
            },
        },
        family="US_CPI",
        retrieved_at=NOW,
    )
    february = {
        item.canonical_key: item
        for item in batch.observations
        if item.reference_period_start == date(2024, 2, 1)
    }
    assert february["US_CPI.HEADLINE.MOM"].value == Decimal("1.0")
    assert february["US_CPI.HEADLINE.YOY"].value == Decimal("1.0")
    assert february["US_CPI.CORE.MOM"].value == Decimal("1.0")
    assert february["US_CPI.CORE.YOY"].value == Decimal("1.0")
    assert all(
        item.metadata["calculation_source"] == "worldstate_from_official_levels"
        for item in february.values()
    )
    headline = february["US_CPI.HEADLINE.MOM"]
    assert headline.raw_value == "101.0"
    assert headline.raw_unit == "index_1982_84_100"
    assert headline.standard_unit == "percent_change"
    assert headline.artifact_hash == batch.artifacts[0].content_hash
    assert batch.quality.quality_grade == QualityGrade.B
    assert batch.quality.metadata["pit_capture"] is True
    assert batch.warnings == ("Calculations have been disabled for this request.",)


async def test_bls_public_mode_splits_ranges_into_ten_year_batches() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await BlsOfficialProvider(client=client).fetch_bundle(
            "US_CPI",
            start_year=2015,
            end_year=2026,
        )
    assert calls == 2
    assert len(batch.artifacts) == 2


async def test_bls_historical_schedule_uses_year_calendar_and_filters_family() -> None:
    requested_urls: list[str] = []
    payload = """
    <table class="release-list">
      <tr><th>Date</th><th>Time</th><th>Release</th></tr>
      <tr><td>Friday, January 16, 2015</td><td>08:30 AM</td>
          <td>Consumer Price Index for December 2014</td></tr>
      <tr><td>Friday, February 06, 2015</td><td>08:30 AM</td>
          <td>Employment Situation for January 2015</td></tr>
    </table>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, text=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BlsOfficialProvider(client=client)
        cpi = await provider.fetch_schedule("US_CPI", year=2015)
        nfp = await provider.fetch_schedule("US_NFP", year=2015)
    assert requested_urls == [
        "https://www.bls.gov/schedule/2015/home.htm",
    ]
    assert [(item.release_date, item.title) for item in cpi.entries] == [
        (date(2015, 1, 16), "Consumer Price Index")
    ]
    assert [(item.release_date, item.title) for item in nfp.entries] == [
        (date(2015, 2, 6), "Employment Situation")
    ]


def test_bls_public_calendar_ics_maps_family_period_and_dst() -> None:
    payload = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260812T083000
SUMMARY:Consumer Price Index for July 2026
DESCRIPTION:Consumer Price Index for July 2026
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260807T083000
SUMMARY:Employment Situation for July 2026
END:VEVENT
END:VCALENDAR
"""
    provider = BlsOfficialProvider()
    cpi = provider.adapt_schedule_ics(
        payload,
        family="US_CPI",
        year=2026,
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_url=provider.public_calendar_url,
    )
    assert len(cpi.entries) == 1
    entry = cpi.entries[0]
    assert entry.reference_period == "2026-07"
    assert entry.scheduled_local == datetime(
        2026, 8, 12, 8, 30, tzinfo=ZoneInfo("America/New_York")
    )
    assert entry.scheduled_local.astimezone(UTC) == datetime(2026, 8, 12, 12, 30, tzinfo=UTC)
    assert cpi.artifacts[0].metadata["calendar_provider"] == "bls_public_calendar"


@pytest.mark.asyncio
async def test_bls_current_schedule_prefers_public_ics_without_api_key() -> None:
    requested: list[str] = []
    user_agents: list[str | None] = []
    payload = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20260812T083000
SUMMARY:Consumer Price Index for July 2026
END:VEVENT
END:VCALENDAR
"""

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        user_agents.append(request.headers.get("user-agent"))
        return httpx.Response(200, content=payload.encode(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        schedule = await BlsOfficialProvider(client=client).fetch_schedule("US_CPI", year=2026)
    assert requested == ["https://www.bls.gov/schedule/news_release/bls.ics"]
    assert user_agents == [BlsOfficialProvider.user_agent]
    assert schedule.entries[0].reference_period == "2026-07"


@pytest.mark.asyncio
async def test_bls_public_calendar_html_fallback_is_explicit() -> None:
    requested: list[str] = []
    html = b"""
    <html><body><table><tr><td>August 12, 2026</td><td>8:30 AM</td>
    <td>Consumer Price Index for July 2026</td></tr></table></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path.endswith("bls.ics"):
            return httpx.Response(403, request=request)
        return httpx.Response(200, content=html, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        schedule = await BlsOfficialProvider(client=client).fetch_schedule(
            "US_CPI", year=2026
        )
    assert requested == [
        "https://www.bls.gov/schedule/news_release/bls.ics",
        "https://www.bls.gov/schedule/news_release/cpi.htm",
    ]
    assert schedule.entries[0].reference_period == "2026-07"
    assert schedule.artifacts[0].metadata["calendar_provider"] == (
        "bls_official_schedule_html_fallback"
    )
    assert schedule.artifacts[0].metadata["fallback_from"] == (
        "https://www.bls.gov/schedule/news_release/bls.ics"
    )


@pytest.mark.asyncio
async def test_bls_public_calendar_failure_is_not_reported_as_api_entitlement() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    with pytest.raises(ProviderError) as caught:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await BlsOfficialProvider(client=client).fetch_schedule(
                "US_CPI", year=2026
            )
    assert caught.value.error_code == ProviderErrorCode.PUBLIC_CALENDAR_UNAVAILABLE
    assert caught.value.details["public_calendar_error"] == (
        ProviderErrorCode.ENTITLEMENT.value
    )


def test_bls_browser_month_view_uses_calendar_cell_day_and_provenance() -> None:
    provider = BlsOfficialProvider()
    batch = provider.adapt_browser_schedule_html(
        """
        <table class="release-calendar"><tr>
          <td id="d0812"><p class="day">12</p>
            <p><strong>Consumer Price Index<br></strong>July 2026<br>08:30 AM</p>
          </td>
        </tr></table>
        """,
        family="US_CPI",
        year=2026,
        retrieved_at=datetime(2026, 8, 12, 3, 44, tzinfo=UTC),
        source_url="https://www.bls.gov/schedule/2026/08_sched.htm",
    )
    assert batch.entries[0].scheduled_local.astimezone(UTC) == datetime(
        2026, 8, 12, 12, 30, tzinfo=UTC
    )
    assert batch.entries[0].reference_period == "2026-07"
    assert batch.artifacts[0].provider_key == "bls_public_calendar"
    assert batch.artifacts[0].metadata["acquisition_transport"] == "browser_capture"


def test_trading_economics_browser_capture_keeps_forecast_distinct() -> None:
    provider = TradingEconomicsConsensusProvider(None)
    batch = provider.adapt_browser_calendar(
        [
            {
                "CalendarId": "browser-cpi-yoy",
                "Event": "Inflation Rate YoY",
                "Country": "United States",
                "Reference": "Jul",
                "Date": "2026-08-12T12:30:00Z",
                "Previous": "3.5%",
                "Forecast": "3.4%",
                "TEForecast": "3.4%",
                "Unit": "percent",
            }
        ],
        pages=(
            TradingEconomicsBrowserPage(
                source_url="https://tradingeconomics.com/united-states/inflation-cpi",
                captured_at=datetime(2026, 8, 12, 3, 53, tzinfo=UTC),
                html="<html><body>Forecast TEForecast " + ("x" * 100) + "</body></html>",
            ),
        ),
    )
    snapshot = batch.snapshots[0]
    assert snapshot.survey_consensus == Decimal("3.4")
    assert snapshot.te_forecast == Decimal("3.4")
    assert batch.artifacts[0].metadata["acquisition_transport"] == "browser_capture"


def test_fomc_calendar_statement_sep_and_structure_change() -> None:
    provider = FederalReserveFomcProvider()
    calendar = provider.adapt_calendar_html(
        """
        <html><body>
          <div class="panel-heading"><h4>2024 FOMC Meetings</h4></div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month">June</div>
            <div class="fomc-meeting__date">11-12*</div>
            <a href="/newsevents/pressreleases/monetary20240612a.htm">Statement</a>
            <a href="/monetarypolicy/files/fomcprojtabl20240612.pdf">Projection Materials</a>
            <a href="/monetarypolicy/fomcpresconf20240612.htm">Press Conference</a>
          </div>
        </body></html>
        """,
        retrieved_at=NOW,
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        year=2024,
    )
    assert len(calendar.meetings) == 1
    assert calendar.meetings[0].has_sep is True
    assert calendar.meetings[0].key_qa_at is None

    statement = provider.adapt_material_html(
        """
        <html><head><title>Federal Reserve issues FOMC statement</title></head>
        <body><main>For release at 2:00 p.m. EDT. The Federal Open Market Committee
        decided to maintain the target range for the federal funds rate at 5.25 to
        5.50 percent. Additional policy text makes this a complete release.</main></body></html>
        """,
        material_type=FomcMaterialType.STATEMENT,
        retrieved_at=datetime(2024, 6, 12, 19, 0, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20240612a.htm",
    )
    assert statement.published_at == datetime(2024, 6, 12, 18, 0, tzinfo=UTC)
    assert statement.target_rate_lower == "5.25"
    assert statement.target_rate_upper == "5.50"
    assert statement.metadata["key_qa_timestamp_generated"] is False

    fractional_statement = provider.adapt_material_html(
        """
        <html><head><title>Federal Reserve issues FOMC statement</title></head>
        <body><main>For release at 2:00 p.m. EDT. The Federal Open Market Committee
        decided to maintain the target range for the federal funds rate at 4-1/4 to
        4-1/2 percent. Additional policy text makes this a complete release.</main>
        </body></html>
        """,
        material_type=FomcMaterialType.STATEMENT,
        retrieved_at=datetime(2025, 6, 18, 19, 0, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20250618a.htm",
    )
    assert fractional_statement.target_rate_lower == "4.25"
    assert fractional_statement.target_rate_upper == "4.5"

    minutes = provider.adapt_material_html(
        """
        <html><head><title>Minutes of the Federal Open Market Committee</title></head>
        <body><main>Minutes of the Federal Open Market Committee. Released February 19,
        2020 at 2:00 p.m. EST. The minutes describe the Committee's policy discussion
        and contain enough official body text for structural validation.</main></body></html>
        """,
        material_type=FomcMaterialType.MINUTES,
        retrieved_at=datetime(2020, 2, 19, 20, 0, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/monetarypolicy/fomcminutes20200129.htm",
    )
    assert minutes.published_at == datetime(2020, 2, 19, 19, 0, tzinfo=UTC)

    minutes_without_publication_header = provider.adapt_material_html(
        """
        <html><head><title>Minutes of the Federal Open Market Committee</title></head>
        <body><main>Minutes of the Federal Open Market Committee. The vote encompassed
        approval of a statement for release at 2:00 p.m. The remaining official body
        describes the meeting discussion but does not publish a minutes release time.
        </main></body></html>
        """,
        material_type=FomcMaterialType.MINUTES,
        retrieved_at=datetime(2025, 7, 9, 19, 0, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/monetarypolicy/fomcminutes20250618.htm",
    )
    assert minutes_without_publication_header.published_at is None

    dynamic_payload = """
        <html><head><title>Federal Reserve issues FOMC statement</title>
        <script>window.dynamicNonce = %s;</script></head>
        <body><main>For release at 2:00 p.m. EDT. The Federal Open Market Committee
        decided to maintain the target range for the federal funds rate at 3-3/4 to
        4 percent. Additional policy text makes this a complete release.</main>
        </body></html>
    """
    first_capture = provider.adapt_material_html(
        dynamic_payload % "'first'",
        material_type=FomcMaterialType.STATEMENT,
        retrieved_at=datetime(2025, 10, 29, 18, 1, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20251029a.htm",
    )
    second_capture = provider.adapt_material_html(
        dynamic_payload % "'second'",
        material_type=FomcMaterialType.STATEMENT,
        retrieved_at=datetime(2025, 10, 29, 18, 2, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/newsevents/pressreleases/monetary20251029a.htm",
    )
    assert first_capture.artifact.content_hash != second_capture.artifact.content_hash
    assert first_capture.metadata["semantic_hash"] == second_capture.metadata["semantic_hash"]
    assert first_capture.target_rate_lower == "3.75"
    assert first_capture.target_rate_upper == "4"

    with pytest.raises(ProviderSchemaError):
        provider.adapt_calendar_html(
            "<html><a href='/different-layout'>meeting</a></html>",
            retrieved_at=NOW,
            year=2024,
        )


def test_fomc_calendar_keeps_future_rows_with_documented_standard_schedule() -> None:
    provider = FederalReserveFomcProvider()
    calendar = provider.adapt_calendar_html(
        """
        <div class="panel panel-default">
          <div class="panel-heading"><h4>2027 FOMC Meetings</h4><br></div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month"><strong>March</strong></div>
            <div class="fomc-meeting__date">16-17*</div>
            <div class="fomc-meeting__minutes"><br></div>
          </div>
        </div>
        """,
        retrieved_at=NOW,
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        year=2027,
    )
    meeting = calendar.meetings[0]
    assert meeting.start_date == date(2027, 3, 16)
    assert meeting.end_date == date(2027, 3, 17)
    assert meeting.has_sep is True
    assert meeting.materials == ()
    assert meeting.statement_published_at == datetime(2027, 3, 17, 18, 0, tzinfo=UTC)
    assert meeting.press_conference_at == datetime(2027, 3, 17, 18, 30, tzinfo=UTC)
    assert meeting.key_qa_at is None
    assert meeting.metadata["statement_time_verified"] is True
    assert meeting.metadata["statement_time_basis"] == "official_standard_schedule_since_2013"


def test_fomc_calendar_excludes_notation_votes_and_keeps_cross_month_meetings() -> None:
    provider = FederalReserveFomcProvider()
    calendar = provider.adapt_calendar_html(
        """
        <div class="panel panel-default">
          <div class="panel-heading"><h4>2025 FOMC Meetings</h4><br></div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month"><strong>Jan/Feb</strong></div>
            <div class="fomc-meeting__date">31-1</div>
            <a href="/monetarypolicy/files/monetary20250201a1.pdf">PDF</a>
            <a href="/newsevents/pressreleases/monetary20250201a.htm">HTML</a>
            <a href="/newsevents/pressreleases/monetary20250201b.htm">
              Statement on Longer-Run Goals and Monetary Policy Strategy
            </a>
          </div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month"><strong>August</strong></div>
            <div class="fomc-meeting__date">22 (notation vote)</div>
            <a href="/newsevents/pressreleases/monetary20250822a.htm">
              Statement on Longer-Run Goals and Monetary Policy Strategy
            </a>
          </div>
        </div>
        """,
        retrieved_at=NOW,
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        year=2025,
    )

    assert len(calendar.meetings) == 1
    meeting = calendar.meetings[0]
    assert (meeting.start_date, meeting.end_date) == (
        date(2025, 1, 31),
        date(2025, 2, 1),
    )
    assert {item.url for item in meeting.materials} == {
        "https://www.federalreserve.gov/monetarypolicy/files/monetary20250201a1.pdf",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250201a.htm",
    }
    assert all(
        item.material_type == FomcMaterialType.STATEMENT for item in meeting.materials
    )


def test_fomc_historical_cross_month_heading_is_not_dropped() -> None:
    provider = FederalReserveFomcProvider()
    calendar = provider.adapt_calendar_html(
        """
        <div class="panel panel-default panel-padded">
          <h5 class="panel-heading panel-heading--shaded">
            Jan/Feb 31-1 Meeting - 2017
          </h5>
          <p><a href="/newsevents/pressreleases/monetary20170201a.htm">Statement</a></p>
        </div>
        """,
        retrieved_at=NOW,
        source_url="https://www.federalreserve.gov/monetarypolicy/fomchistorical2017.htm",
        year=2017,
    )
    assert [(item.start_date, item.end_date) for item in calendar.meetings] == [
        (date(2017, 1, 31), date(2017, 2, 1))
    ]


def test_fomc_historical_panels_do_not_leak_notation_vote_materials() -> None:
    provider = FederalReserveFomcProvider()
    calendar = provider.adapt_calendar_html(
        """
        <h5 class="panel-heading">September 17-18 Meeting - 2019</h5>
        <a href="/newsevents/pressreleases/monetary20190918a.htm">Statement</a>
        <h5 class="panel-heading">October 4 (unscheduled) - 2019</h5>
        <a href="/newsevents/pressreleases/monetary20191011a.htm">Statement</a>
        <h5 class="panel-heading">October 18 (notation vote) - 2019</h5>
        <a href="/newsevents/pressreleases/monetary20191018a.htm">Statement</a>
        <h5 class="panel-heading">October 29-30 Meeting - 2019</h5>
        <a href="/newsevents/pressreleases/monetary20191030a.htm">Statement</a>
        """,
        retrieved_at=NOW,
        source_url="https://www.federalreserve.gov/monetarypolicy/fomchistorical2019.htm",
        year=2019,
    )
    assert [item.end_date for item in calendar.meetings] == [
        date(2019, 9, 18),
        date(2019, 10, 4),
        date(2019, 10, 30),
    ]
    assert calendar.meetings[1].metadata["unscheduled_meeting"] is True
    assert [
        [material.source_date for material in meeting.materials]
        for meeting in calendar.meetings
    ] == [
        [date(2019, 9, 18)],
        [date(2019, 10, 11)],
        [date(2019, 10, 30)],
    ]


def test_fomc_historical_page_keeps_meeting_boundaries_and_verified_press_time() -> None:
    provider = FederalReserveFomcProvider()
    calendar = provider.adapt_calendar_html(
        """
        <div class="panel panel-default panel-padded">
          <h5 class="panel-heading panel-heading--shaded">
            January 28-29 Meeting - 2020
          </h5>
          <p><a href="/newsevents/pressreleases/monetary20200129a.htm">Statement</a></p>
          <p><a href="/monetarypolicy/fomcpresconf20200129.htm">Press Conference</a></p>
          <p><a href="/monetarypolicy/fomcminutes20200129.htm">Minutes</a></p>
          <p><a href="/monetarypolicy/files/FOMC20200129SEPcompilation.pdf">
            SEP: Individual Projections
          </a></p>
          <p><a href="/monetarypolicy/files/FOMC20200129meeting.pdf">Transcript</a></p>
        </div>
        <div class="panel panel-default panel-padded">
          <h5 class="panel-heading panel-heading--shaded">
            March 2 (unscheduled) Meeting - 2020
          </h5>
          <p><a href="/newsevents/pressreleases/monetary20200303a.htm">Statement</a></p>
          <p><a href="/monetarypolicy/fomcpresconf20200303.htm">Press Conference</a></p>
        </div>
        """,
        retrieved_at=NOW,
        source_url="https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm",
        year=2020,
    )
    regular, unscheduled = calendar.meetings
    assert (regular.start_date, regular.end_date) == (
        date(2020, 1, 28),
        date(2020, 1, 29),
    )
    assert regular.press_conference_at == datetime(2020, 1, 29, 19, 30, tzinfo=UTC)
    assert regular.has_sep is True
    assert {item.material_type for item in regular.materials} >= {
        FomcMaterialType.STATEMENT,
        FomcMaterialType.PRESS_CONFERENCE,
        FomcMaterialType.MINUTES,
        FomcMaterialType.SEP,
    }
    assert all("meeting.pdf" not in item.url for item in regular.materials)
    assert unscheduled.metadata["unscheduled_meeting"] is True
    assert unscheduled.press_conference_at is None


async def test_fomc_fetch_calendar_routes_historical_year_to_official_archive() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            text="""
            <h5 class="panel-heading">December 15-16 Meeting - 2020</h5>
            <a href="/newsevents/pressreleases/monetary20201216a.htm">Statement</a>
            """,
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await FederalReserveFomcProvider(client).fetch_calendar(year=2020)
    assert requested_urls == [
        "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
    ]
    assert batch.meetings[0].end_date == date(2020, 12, 16)


async def test_fomc_pdf_material_is_preserved_without_fabricated_timestamp() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.7 recorded projection material",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        document = await FederalReserveFomcProvider(client).fetch_material(
            "https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20240612.pdf",
            FomcMaterialType.PROJECTION_TABLES,
        )
    assert document.artifact.content_type == "application/pdf"
    assert document.artifact.content.startswith(b"%PDF")
    assert document.published_at is None
    assert document.metadata["publication_time_precision"] == "date_only"


async def test_fred_alfred_as_of_filters_future_vintage_and_keeps_artifact() -> None:
    observed_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_url
        observed_url = str(request.url)
        return httpx.Response(
            200,
            json={
                "observations": [
                    {
                        "date": "2024-01-01",
                        "realtime_start": "2024-02-01",
                        "realtime_end": "2024-03-01",
                        "value": "3.1",
                    },
                    {
                        "date": "2024-01-01",
                        "realtime_start": "2024-04-01",
                        "realtime_end": "9999-12-31",
                        "value": "3.2",
                    },
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FredAlfredProvider("secret", client)
        batch = await provider.fetch_observation_batch("CPIAUCSL", as_of=date(2024, 3, 15))
    assert "realtime_end=2024-03-15" in observed_url
    assert len(batch.observations) == 1
    assert batch.observations[0].value == Decimal("3.1")
    assert len(batch.artifacts[0].content_hash) == 64
    assert "secret" not in batch.artifacts[0].source_url


async def test_fred_public_csv_is_current_only_and_explicitly_not_pit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/fredgraph.csv"
        assert request.url.params["id"] == "DGS2"
        return httpx.Response(
            200,
            text="observation_date,DGS2\n2026-08-07,3.75\n2026-08-08,.\n",
            headers={"content-type": "text/csv"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FredAlfredProvider(None, client)
        batch = await provider.fetch_observation_batch(
            "DGS2", start=date(2026, 8, 1), end=date(2026, 8, 9)
        )

    assert len(batch.observations) == 2
    assert batch.observations[0].value == Decimal("3.75")
    assert batch.observations[0].availability_method.value == "ingestion_time_proxy"
    assert batch.observations[0].quality_flags == ["current_public_csv", "not_point_in_time"]
    assert batch.observations[1].value is None
    assert batch.quality.is_verified is False
    assert batch.quality.metadata["point_in_time"] is False
    assert batch.artifacts[0].content_type == "text/csv"


async def test_fred_public_csv_rejects_pit_cutoff() -> None:
    provider = FredAlfredProvider(None)
    with pytest.raises(ProviderError) as error:
        await provider.fetch_observation_batch("DGS2", as_of=date(2026, 8, 8))
    assert error.value.error_code == ProviderErrorCode.POINT_IN_TIME


def _te_event(forecast: str = "3.1%", te_forecast: str = "3.3%") -> dict[str, object]:
    return {
        "CalendarId": "123",
        "Ticker": "USCPIYY",
        "Country": "United States",
        "Event": "Inflation Rate YoY",
        "Date": "2024-03-12T12:30:00",
        "Reference": "Feb",
        "Actual": "3.2%",
        "Previous": "3.1%",
        "Revised": "3.0%",
        "Forecast": forecast,
        "TEForecast": te_forecast,
        "LastUpdate": "2024-03-12T11:00:00Z",
        "Unit": "%",
        "Importance": 3,
    }


def test_te_consensus_is_separate_from_teforecast_and_selects_pre_t0() -> None:
    provider = TradingEconomicsConsensusProvider(
        "secret",
        pit_entitled=True,
        monthly_quota=100,
        monthly_requests_used=91,
    )
    batch = provider.adapt_calendar(
        [_te_event()],
        captured_at=datetime(2024, 3, 12, 11, 30, tzinfo=UTC),
        source_url="https://api.tradingeconomics.com/calendar/country/united states",
        pit_query_at=datetime(2024, 3, 12, 11, 0, tzinfo=UTC),
    )
    snapshot = batch.snapshots[0]
    assert _te_mapping(snapshot) == ("US_CPI", "headline_yoy")
    assert snapshot.release_at == datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    assert snapshot.survey_consensus == Decimal("3.1")
    assert snapshot.te_forecast == Decimal("3.3")
    assert snapshot.pit_verified is True
    assert batch.quota.warning is not None
    chosen = provider.select_last_pre_release_snapshot(
        batch.snapshots,
        release_at=snapshot.release_at,
    )
    assert chosen == snapshot

    without_pit = TradingEconomicsConsensusProvider("secret", pit_entitled=False)
    with pytest.raises(ProviderError) as error:
        without_pit.adapt_calendar(
            [_te_event()],
            captured_at=NOW,
            source_url="https://api.tradingeconomics.com/calendar",
            pit_query_at=NOW,
        )
    assert error.value.error_code == ProviderErrorCode.ENTITLEMENT


def test_te_payroll_values_are_normalized_to_thousand_persons() -> None:
    provider = TradingEconomicsConsensusProvider("secret")
    row = _te_event(forecast="205K", te_forecast="210K")
    row.update(
        {
            "Ticker": "USNFP",
            "Event": "Non Farm Payrolls",
            "Actual": "200K",
            "Previous": "0.18M",
            "Revised": "175000",
            "Unit": "Persons",
        }
    )
    snapshot = provider.adapt_calendar(
        [row],
        captured_at=NOW,
        source_url="https://api.tradingeconomics.com/calendar",
    ).snapshots[0]
    assert snapshot.actual == Decimal("200")
    assert snapshot.previous == Decimal("180")
    assert snapshot.revised == Decimal("175")
    assert snapshot.survey_consensus == Decimal("205")
    assert snapshot.te_forecast == Decimal("210")
    assert snapshot.unit == "thousand persons"
    assert snapshot.metadata["raw_provider_unit"] == "Persons"


async def test_te_healthcheck_is_quota_free_configuration_evidence() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        health = await TradingEconomicsConsensusProvider("secret", client).healthcheck()
    assert str(health.status) == "degraded"
    assert calls == 0
    assert any("Quota-free" in warning for warning in health.warnings)


def _market_query(interval: int = 60) -> BarQuery:
    return BarQuery(
        instrument=MarketInstrumentRef(
            canonical_key="gold_gc",
            symbol="GC",
            title="Gold futures",
            exchange="COMEX",
            quote_unit="USD/oz",
        ),
        start=datetime(2024, 3, 12, 12, 30, tzinfo=UTC),
        end=datetime(2024, 3, 12, 12, 32, tzinfo=UTC),
        interval_seconds=interval,
    )


def test_databento_mappings_contract_cost_gates_and_dedupe() -> None:
    assert DATABENTO_INSTRUMENTS["GC"].dataset == "GLBX.MDP3"
    assert DATABENTO_INSTRUMENTS["DX"].dataset == "IFUS.IMPACT"
    assert DATABENTO_INSTRUMENTS["VX"].dataset == "XCBF.PITCH"
    provider = DatabentoMarketProvider(
        "secret",
        max_estimated_cost_usd=Decimal("2"),
        allow_paid_download=False,
    )
    contract = provider.resolve_contract(
        "GC",
        event_at=NOW,
        mappings=[
            {
                "stype_in_symbol": "GC.v.0",
                "stype_out_symbol": "GCJ4",
                "instrument_id": 42,
                "start": "2024-02-01T00:00:00Z",
                "end": "2024-03-28T00:00:00Z",
                "first_notice": "2024-03-27",
                "last_trade": "2024-03-26",
                "volume": 1000,
            }
        ],
    )
    assert contract.raw_symbol == "GCJ4"
    assert contract.continuous_symbol == "GC.v.0"
    request = DatabentoDownloadRequest(
        symbols=("GC",),
        start=_market_query().start,
        end=_market_query().end,
        schema_name="ohlcv-1m",
    )
    estimate = provider.estimate_cost(
        request,
        provider_cost_usd=Decimal("0.25"),
        provider_record_count=2,
        provider_billable_bytes=256,
        provider_quoted_at=NOW,
    )
    assert estimate.source == "provider_metadata"
    assert estimate.execution_allowed is False
    with pytest.raises(ProviderError) as disabled:
        provider.assert_download_allowed(estimate)
    assert disabled.value.error_code == ProviderErrorCode.PAID_DOWNLOAD_DISABLED

    enabled = DatabentoMarketProvider(
        "secret",
        max_estimated_cost_usd=Decimal("0.10"),
        allow_paid_download=True,
    )
    with pytest.raises(ProviderError) as over_budget:
        enabled.assert_download_allowed(estimate)
    assert over_budget.value.error_code == ProviderErrorCode.BUDGET_EXCEEDED

    fallback = enabled.estimate_cost(request)
    with pytest.raises(ProviderError) as unavailable_quote:
        DatabentoMarketProvider(
            "secret",
            max_estimated_cost_usd=Decimal("10"),
            allow_paid_download=True,
        ).assert_download_allowed(fallback)
    assert (
        unavailable_quote.value.error_code
        == ProviderErrorCode.COST_ESTIMATE_UNAVAILABLE
    )

    bars = enabled.adapt_bars(
        [
            {
                "ts_event": "2024-03-12T12:30:00Z",
                "open": "2150",
                "high": "2152",
                "low": "2149",
                "close": "2151",
                "volume": 10,
                "symbol": "GCJ4",
            },
            {
                "ts_event": "2024-03-12T12:30:00Z",
                "open": "2151",
                "high": "2153",
                "low": "2150",
                "close": "2152",
                "volume": 11,
                "symbol": "GCJ4",
            },
            {
                "ts_event": "2024-03-12T12:31:00Z",
                "open": "2152",
                "high": "2154",
                "low": "2151",
                "close": "2153",
                "volume": 12,
                "symbol": "GCJ4",
            },
        ],
        query=_market_query(),
        contract=contract,
        schema="ohlcv-1m",
        retrieved_at=NOW,
        source_url="https://hist.databento.com/v0/timeseries.get_range",
        existing_keys={("gold_gc", datetime(2024, 3, 12, 12, 31, tzinfo=UTC), 60)},
    )
    assert len(bars.bars) == 1
    assert bars.bars[0].close_value == Decimal("2152")
    assert bars.dedupe.duplicate_payload_records == 1
    assert bars.dedupe.existing_records_skipped == 1
    assert bars.contract.raw_symbol == "GCJ4"
    assert len(bars.dataset_manifest_hash) == 64


async def test_databento_provider_metadata_estimate_does_not_download() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(
            200,
            json={"cost": "0.42", "record_count": 100, "billable_size": 6400},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DatabentoMarketProvider(
            "secret",
            client,
            max_estimated_cost_usd=Decimal("1"),
            allow_paid_download=False,
        )
        estimate = await provider.estimate_download(
            DatabentoDownloadRequest(
                symbols=("GC",),
                start=datetime(2024, 3, 12, 11, 0, tzinfo=UTC),
                end=datetime(2024, 3, 12, 16, 30, tzinfo=UTC),
                schema_name="ohlcv-1m",
            )
        )
    assert estimate.source == "provider_metadata"
    assert estimate.estimated_cost_usd == Decimal("0.42")
    assert estimate.execution_allowed is False
    assert calls == ["/v0/metadata.get_cost"]


def test_all_provider_capabilities_expose_terms_without_secrets() -> None:
    providers = (
        BlsOfficialProvider(),
        FederalReserveFomcProvider(),
        FredAlfredProvider(None),
        TradingEconomicsConsensusProvider(None),
        DatabentoMarketProvider(None),
    )
    for provider in providers:
        capabilities = provider.get_capabilities()
        assert str(capabilities.metadata["terms_url"]).startswith("https://")
        assert capabilities.operations
        assert provider.timeout_seconds > 0
        assert provider.retry_policy.max_attempts >= 1
        assert "secret" not in json.dumps(capabilities.model_dump(mode="json"))
