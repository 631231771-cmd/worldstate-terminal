"""Federal Reserve FOMC calendar and publication adapter."""

from __future__ import annotations

import hashlib
import html as html_module
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from pydantic import AwareDatetime, Field

from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.macro_core.enums import ProviderStatus
from worldstate.macro_core.models import ProviderHealth
from worldstate.provider_kit.contracts import (
    ProviderBatch,
    ProviderCapabilities,
    ProviderDomain,
    ProviderModel,
    ProviderRateLimit,
    ProviderRetryPolicy,
    ProviderTerms,
    SourceArtifact,
)
from worldstate.provider_kit.errors import ProviderError, ProviderErrorCode, ProviderSchemaError
from worldstate.provider_kit.transport import HttpProviderTransport


class FomcMaterialType(StrEnum):
    STATEMENT = "statement"
    IMPLEMENTATION_NOTE = "implementation_note"
    SEP = "sep"
    PROJECTION_TABLES = "projection_tables"
    PRESS_CONFERENCE = "press_conference"
    OPENING_STATEMENT = "opening_statement"
    TRANSCRIPT = "transcript"
    MINUTES = "minutes"
    OTHER = "other"


class FomcMaterialLink(ProviderModel):
    material_type: FomcMaterialType
    title: str
    url: str
    source_date: date | None = None


class FomcMeeting(ProviderModel):
    meeting_key: str
    start_date: date
    end_date: date
    source_timezone: str = "America/New_York"
    materials: tuple[FomcMaterialLink, ...]
    statement_published_at: AwareDatetime | None = None
    press_conference_at: AwareDatetime | None = None
    minutes_published_at: AwareDatetime | None = None
    has_sep: bool = False
    key_qa_at: AwareDatetime | None = None
    key_qa_verified: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class FomcCalendarBatch(ProviderBatch):
    meetings: tuple[FomcMeeting, ...]


class FomcDocument(ProviderModel):
    document_type: FomcMaterialType
    title: str
    text: str
    source_url: str
    published_at: AwareDatetime | None = None
    target_rate_lower: str | None = None
    target_rate_upper: str | None = None
    artifact: SourceArtifact
    metadata: dict[str, object] = Field(default_factory=dict)


class _VisibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self._current_href: str | None = None
        self._current_link_text: list[str] = []
        self._hidden_depth = 0
        self.text: list[str] = []
        self.title: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        if tag == "a":
            self._current_href = attributes.get("href")
            self._current_link_text = []
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content")
            if key and content:
                self.meta[key.lower()] = content

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag == "a" and self._current_href is not None:
            text = " ".join(" ".join(self._current_link_text).split())
            self.links.append((self._current_href, text))
            self._current_href = None
            self._current_link_text = []
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        normalized = " ".join(data.split())
        if not normalized:
            return
        self.text.append(normalized)
        if self._current_href is not None:
            self._current_link_text.append(normalized)
        if self._in_title:
            self.title.append(normalized)


class _FomcMeetingGridParser(HTMLParser):
    """Extract dated meeting rows, including future rows without material links."""

    _YEAR = re.compile(r"\b(20\d{2})\s+FOMC\s+Meetings\b", re.IGNORECASE)
    _VOID_TAGS: ClassVar[set[str]] = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[int, str, str, tuple[tuple[str, str], ...]]] = []
        self._depth = 0
        self._year: int | None = None
        self._year_depth: int | None = None
        self._year_text: list[str] = []
        self._row_depth: int | None = None
        self._month_depth: int | None = None
        self._date_depth: int | None = None
        self._month_text: list[str] = []
        self._date_text: list[str] = []
        self._row_links: list[tuple[str, str]] = []
        self._link_depth: int | None = None
        self._link_href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        current_depth = self._depth
        if "panel-heading" in classes:
            self._year_depth = current_depth
            self._year_text = []
        if "fomc-meeting" in classes and self._row_depth is None:
            self._row_depth = current_depth
            self._month_text = []
            self._date_text = []
            self._row_links = []
        if self._row_depth is not None:
            if "fomc-meeting__month" in classes:
                self._month_depth = current_depth
            if "fomc-meeting__date" in classes:
                self._date_depth = current_depth
            if tag == "a":
                self._link_depth = current_depth
                self._link_href = attributes.get("href") or None
                self._link_text = []
        if tag not in self._VOID_TAGS:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag not in self._VOID_TAGS:
            self._depth = max(0, self._depth - 1)
        if self._link_depth is not None and self._depth == self._link_depth and tag == "a":
            if self._link_href:
                self._row_links.append(
                    (self._link_href, " ".join(" ".join(self._link_text).split()))
                )
            self._link_depth = None
            self._link_href = None
            self._link_text = []
        if self._month_depth is not None and self._depth == self._month_depth and tag == "div":
            self._month_depth = None
        if self._date_depth is not None and self._depth == self._date_depth and tag == "div":
            self._date_depth = None
        if self._row_depth is not None and self._depth == self._row_depth and tag == "div":
            month = " ".join(" ".join(self._month_text).split())
            meeting_dates = " ".join(" ".join(self._date_text).split())
            if self._year is not None and month and meeting_dates:
                self.rows.append((self._year, month, meeting_dates, tuple(self._row_links)))
            self._row_depth = None
            self._month_depth = None
            self._date_depth = None
            self._month_text = []
            self._date_text = []
            self._row_links = []
        if self._year_depth is not None and self._depth == self._year_depth:
            text = " ".join(" ".join(self._year_text).split())
            match = self._YEAR.search(text)
            if match:
                self._year = int(match.group(1))
            self._year_depth = None
            self._year_text = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._year_depth is not None:
            self._year_text.append(normalized)
        if self._month_depth is not None:
            self._month_text.append(normalized)
        if self._date_depth is not None:
            self._date_text.append(normalized)
        if self._link_depth is not None:
            self._link_text.append(normalized)


class _FomcHistoricalMeetingParser(HTMLParser):
    """Extract meeting panels from the Fed's year-specific historical pages."""

    # Official archive headings vary between ordinary meetings, cross-month
    # meetings and unscheduled decisions without a trailing "Meeting" label.
    _MEETING_HEADING = re.compile(
        r"^(?P<month>[A-Za-z]+(?:\s*/\s*[A-Za-z]+)?)\s+"
        r"(?P<dates>\d{1,2}(?:\s*[-\N{EN DASH}\N{EM DASH}]\s*\d{1,2})?)"
        r"(?P<qualifier>\s*(?:\([^)]*\))?)\s*(?:(?:Meeting|Vote))?\s*-\s*"
        r"(?P<year>20\d{2})$",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[
            tuple[int, str, str, bool, tuple[tuple[str, str], ...]]
        ] = []
        self._heading = False
        self._heading_text: list[str] = []
        self._active: tuple[int, str, str, bool] | None = None
        self._active_links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def _flush(self) -> None:
        if self._active is not None:
            year, month, dates, unscheduled = self._active
            self.rows.append((year, month, dates, unscheduled, tuple(self._active_links)))
        self._active = None
        self._active_links = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag in {"h4", "h5", "h6"} and "panel-heading" in classes:
            self._heading = True
            self._heading_text = []
        if self._active is not None and tag == "a":
            self._href = attributes.get("href") or None
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h4", "h5", "h6"} and self._heading:
            heading = " ".join(" ".join(self._heading_text).split())
            # Every panel heading starts a new ownership boundary.  Without
            # this flush, links from an unrecognised notation-vote/cancelled
            # panel leak into the preceding regular meeting.
            self._flush()
            match = self._MEETING_HEADING.match(heading)
            if match:
                qualifier = match.group("qualifier").lower()
                if not any(
                    marker in qualifier for marker in ("notation", "cancelled", "canceled")
                ):
                    self._active = (
                        int(match.group("year")),
                        match.group("month"),
                        match.group("dates"),
                        "unscheduled" in qualifier,
                    )
            self._heading = False
            self._heading_text = []
        if tag == "a" and self._href is not None:
            self._active_links.append(
                (self._href, " ".join(" ".join(self._link_text).split()))
            )
            self._href = None
            self._link_text = []

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._heading:
            self._heading_text.append(normalized)
        if self._href is not None:
            self._link_text.append(normalized)

    def close(self) -> None:
        super().close()
        self._flush()


_DATE_IN_URL = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_RATE_VALUE_PATTERN = (
    r"(?:[0-9]+-[0-9]+/[0-9]+|[0-9]+/[0-9]+|[0-9]+(?:\.[0-9]+)?)"
)
_TARGET_RANGE = re.compile(
    rf"target range[^.]{{0,160}}?({_RATE_VALUE_PATTERN})\s*(?:percent|%)?\s+to\s+"
    rf"({_RATE_VALUE_PATTERN})\s*(?:percent|%)",
    re.IGNORECASE,
)
_RELEASE_TIME = re.compile(
    r"(?:for release at|released at)\s+([0-9]{1,2})(?::([0-9]{2}))?\s*"
    r"([ap])\.?m\.?(?:\s+(EDT|EST))?",
    re.IGNORECASE,
)
_DATED_RELEASE_TIME = re.compile(
    r"released\s+(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+"
    r"(?P<year>20\d{2})\s+at\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
    r"(?P<period>[ap])\.?m\.?(?:\s+(?P<zone>EDT|EST))?",
    re.IGNORECASE,
)
_MEETING_DAY = re.compile(r"\d{1,2}")
_MONTH_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _meeting_dates(year: int, month_text: str, date_text: str) -> tuple[date, date] | None:
    month_names = [part.strip().lower() for part in month_text.split("/") if part.strip()]
    months = [_MONTH_NUMBER.get(name) for name in month_names]
    days = [int(value) for value in _MEETING_DAY.findall(date_text)]
    if not months or any(month is None for month in months) or not days:
        return None
    start_month = months[0]
    end_month = months[-1]
    assert start_month is not None
    assert end_month is not None
    end_year = year + 1 if end_month < start_month else year
    try:
        return date(year, start_month, days[0]), date(end_year, end_month, days[-1])
    except ValueError:
        return None


def _material_type(title: str, url: str) -> FomcMaterialType:
    text = f"{title} {url}".lower()
    if "implementation note" in text:
        return FomcMaterialType.IMPLEMENTATION_NOTE
    if (
        "projection material" in text
        or "economic projections" in text
        or "fomcproj" in text
        or ("sep" in text and ("compilation" in text or "participant" in text))
    ):
        return FomcMaterialType.SEP
    if "projection table" in text:
        return FomcMaterialType.PROJECTION_TABLES
    if "opening statement" in text:
        return FomcMaterialType.OPENING_STATEMENT
    if (
        "press conference transcript" in text
        or ("fomcpresconf" in text and text.endswith(".pdf"))
        or "caption" in text
    ):
        return FomcMaterialType.TRANSCRIPT
    if "press conference" in text or "fomcpresconf" in text:
        return FomcMaterialType.PRESS_CONFERENCE
    if "minutes" in text:
        return FomcMaterialType.MINUTES
    # Framework statements, balance-sheet principles and notation votes are
    # official FOMC publications, but they are not post-meeting rate-decision
    # statements and must not create Event Lab releases.
    if (
        "longer-run goals" in text
        or "monetary policy strategy" in text
        or "principles for reducing" in text
        or "notation vote" in text
    ):
        return FomcMaterialType.OTHER
    if re.search(
        r"/newsevents/pressreleases/monetary20\d{6}a\.htm(?:$|[?#])",
        url.lower(),
    ):
        return FomcMaterialType.STATEMENT
    if re.search(
        r"/monetarypolicy/files/monetary20\d{6}a1\.pdf(?:$|[?#])",
        url.lower(),
    ):
        return FomcMaterialType.STATEMENT
    if title.strip().lower() in {"statement", "fomc statement"}:
        return FomcMaterialType.STATEMENT
    return FomcMaterialType.OTHER


def _url_date(url: str) -> date | None:
    match = _DATE_IN_URL.search(url)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _rate_value(value: str) -> str | None:
    """Convert the fraction notation used in official statements to decimals."""

    if "/" not in value:
        return value
    try:
        whole_text, fraction_text = (value.split("-", 1) if "-" in value else ("0", value))
        numerator_text, denominator_text = fraction_text.split("/", 1)
        denominator = Decimal(denominator_text)
        if denominator == 0:
            return None
        result = Decimal(whole_text) + Decimal(numerator_text) / denominator
    except (InvalidOperation, ValueError):
        return None
    return format(result.normalize(), "f")


def _published_time(
    parser: _VisibleHtmlParser,
    source_url: str,
    text: str,
    *,
    material_type: FomcMaterialType,
) -> datetime | None:
    # Aware publication metadata is authoritative for every material type.
    raw_meta = (
        parser.meta.get("article:published_time")
        or parser.meta.get("date")
        or parser.meta.get("dc.date")
    )
    if raw_meta:
        try:
            parsed = datetime.fromisoformat(raw_meta.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
        except ValueError:
            pass
    dated_match = _DATED_RELEASE_TIME.search(text)
    if dated_match:
        month = _MONTH_NUMBER.get(dated_match.group("month").lower())
        if month is not None:
            hour = int(dated_match.group("hour"))
            minute = int(dated_match.group("minute") or "0")
            if dated_match.group("period").lower() == "p" and hour != 12:
                hour += 12
            if dated_match.group("period").lower() == "a" and hour == 12:
                hour = 0
            try:
                return datetime(
                    int(dated_match.group("year")),
                    month,
                    int(dated_match.group("day")),
                    hour,
                    minute,
                    tzinfo=ZoneInfo("America/New_York"),
                ).astimezone(UTC)
            except ValueError:
                pass
    # FOMC minutes, projection pages and press-conference landing pages quote
    # statement text containing "for release at 2:00 p.m." Their URLs encode
    # the meeting date, not necessarily the document publication date.  Only
    # a policy-decision statement may combine that text with its URL date.
    if material_type != FomcMaterialType.STATEMENT:
        return None
    publication_date = _url_date(source_url)
    time_match = _RELEASE_TIME.search(text)
    if publication_date and time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "0")
        if time_match.group(3).lower() == "p" and hour != 12:
            hour += 12
        if time_match.group(3).lower() == "a" and hour == 12:
            hour = 0
        tz_label = time_match.group(4)
        # The IANA zone is authoritative for DST.  An explicit inconsistent
        # abbreviation is retained by the caller as text rather than trusted.
        local = datetime(
            publication_date.year,
            publication_date.month,
            publication_date.day,
            hour,
            minute,
            tzinfo=ZoneInfo("America/New_York"),
        )
        if tz_label in {"EDT", "EST", None}:
            return local.astimezone(UTC)
    return None


class FederalReserveFomcProvider:
    key = "federal_reserve_fomc"
    base_url = "https://www.federalreserve.gov"
    calendar_url = f"{base_url}/monetarypolicy/fomccalendars.htm"
    historical_calendar_url = f"{base_url}/monetarypolicy/fomchistorical{{year}}.htm"
    terms = ProviderTerms(
        license_name="Federal Reserve Board public website content",
        terms_url="https://www.federalreserve.gov/aboutthefed/website-linking-policies.htm",
        redistribution_allowed=False,
        notes="Store provenance and links; review third-party material embedded by the Board.",
    )

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 30,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        self._transport = HttpProviderTransport(
            provider_key=self.key,
            client=client,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy or ProviderRetryPolicy(),
        )

    @property
    def timeout_seconds(self) -> float:
        return self._transport.timeout_seconds

    @property
    def retry_policy(self) -> ProviderRetryPolicy:
        return self._transport.retry_policy

    @property
    def rate_limit(self) -> ProviderRateLimit:
        return self._transport.rate_limit

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_key=self.key,
            domains=(ProviderDomain.EVENT_CALENDAR, ProviderDomain.MACRO_RELEASE),
            operations=("fetch_calendar", "fetch_material", "healthcheck"),
            supports_point_in_time=True,
            supports_revisions=True,
            supports_batch=True,
            paid_access=False,
            metadata={
                "materials": [item.value for item in FomcMaterialType if item != "other"],
                "key_qa_policy": "manual_verified_timestamp_only",
                "terms_url": self.terms.terms_url,
                "license_name": self.terms.license_name,
            },
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    async def fetch_calendar(self, *, year: int | None = None) -> FomcCalendarBatch:
        source_url = (
            self.historical_calendar_url.format(year=year)
            if year is not None and year <= 2020
            else self.calendar_url
        )
        response = await self._transport.request("GET", source_url)
        return self.adapt_calendar_html(
            response.content,
            retrieved_at=datetime.now(UTC),
            source_url=str(response.url),
            year=year,
        )

    def adapt_calendar_html(
        self,
        payload: bytes | str,
        *,
        retrieved_at: AwareDatetime,
        source_url: str | None = None,
        year: int | None = None,
    ) -> FomcCalendarBatch:
        raw = payload.encode() if isinstance(payload, str) else payload
        try:
            rendered = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProviderSchemaError(
                self.key,
                "FOMC calendar was not UTF-8 HTML",
                structure="calendar links with dated official material URLs",
            ) from exc
        parser = _VisibleHtmlParser()
        parser.feed(rendered)
        meeting_grid = _FomcMeetingGridParser()
        meeting_grid.feed(rendered)
        historical_grid = _FomcHistoricalMeetingParser()
        historical_grid.feed(rendered)
        historical_grid.close()
        grouped: dict[date, list[FomcMaterialLink]] = {}
        for href, title in parser.links:
            absolute_url = urljoin(source_url or self.calendar_url, href)
            material = _material_type(title, absolute_url)
            if material == FomcMaterialType.OTHER:
                continue
            source_date = _url_date(absolute_url)
            if source_date is None or (year is not None and source_date.year != year):
                continue
            grouped.setdefault(source_date, []).append(
                FomcMaterialLink(
                    material_type=material,
                    title=title or material.value.replace("_", " ").title(),
                    url=absolute_url,
                    source_date=source_date,
                )
            )
        scheduled_rows: list[
            tuple[date, date, tuple[FomcMaterialLink, ...], bool, bool]
        ] = []
        for row_year, month_text, day_text, row_links in meeting_grid.rows:
            if year is not None and row_year != year:
                continue
            # The Board includes notation votes in the same visual grid as
            # scheduled meetings.  A notation vote is not a rate-decision
            # meeting and must not become a MacroRelease.
            row_qualifier = day_text.lower()
            if "notation vote" in row_qualifier or any(
                marker in row_qualifier for marker in ("cancelled", "canceled")
            ):
                continue
            parsed_dates = _meeting_dates(row_year, month_text, day_text)
            if parsed_dates is None:
                continue
            start_date, end_date = parsed_dates
            current_materials: list[FomcMaterialLink] = []
            for href, title in row_links:
                absolute_url = urljoin(source_url or self.calendar_url, href)
                material = _material_type(title, absolute_url)
                if material == FomcMaterialType.OTHER:
                    continue
                current_materials.append(
                    FomcMaterialLink(
                        material_type=material,
                        title=title or material.value.replace("_", " ").title(),
                        url=absolute_url,
                        source_date=_url_date(absolute_url),
                    )
                )
            # Some recorded/minimal pages expose only dated material links.
            # Real Fed grid rows are authoritative for the meeting date and
            # allow future meetings with no published materials to survive.
            if not current_materials:
                current_materials.extend(grouped.get(end_date, ()))
            deduped = tuple({item.url: item for item in current_materials}.values())
            scheduled_rows.append(
                (
                    start_date,
                    end_date,
                    deduped,
                    "*" in day_text,
                    "unscheduled" in row_qualifier,
                )
            )

        for row_year, month_text, day_text, unscheduled, row_links in historical_grid.rows:
            if year is not None and row_year != year:
                continue
            parsed_dates = _meeting_dates(row_year, month_text, day_text)
            if parsed_dates is None:
                continue
            start_date, end_date = parsed_dates
            historical_materials: list[FomcMaterialLink] = []
            for href, title in row_links:
                absolute_url = urljoin(source_url or self.calendar_url, href)
                material = _material_type(title, absolute_url)
                if material == FomcMaterialType.OTHER:
                    continue
                historical_materials.append(
                    FomcMaterialLink(
                        material_type=material,
                        title=title or material.value.replace("_", " ").title(),
                        url=absolute_url,
                        source_date=_url_date(absolute_url),
                    )
                )
            deduped = tuple({item.url: item for item in historical_materials}.values())
            scheduled_rows.append((start_date, end_date, deduped, False, unscheduled))

        if not scheduled_rows:
            raise ProviderSchemaError(
                self.key,
                "FOMC calendar structure did not yield any authoritative meeting rows",
                structure="FOMC meeting grid or historical meeting panels",
                details={"requested_year": year},
            )
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url or self.calendar_url,
            retrieved_at=retrieved_at,
            content_type="text/html",
            content=raw,
            terms=self.terms,
            metadata={"requested_year": year},
        )
        quality = DataQuality(
            source_name="Federal Reserve Board",
            source_url=source_url or self.calendar_url,
            source_type="official_html",
            acquired_at=retrieved_at,
            is_verified=True,
            quality_grade=QualityGrade.A,
            metadata={"parser": "fomc-calendar-v1", "point_in_time_capture": True},
        )
        meetings: list[FomcMeeting] = []
        for start_date, end_date, meeting_materials, sep_marker, unscheduled in sorted(
            scheduled_rows,
            key=lambda item: item[1],
        ):
            has_press_conference = any(
                item.material_type == FomcMaterialType.PRESS_CONFERENCE
                for item in meeting_materials
            )
            statement_published_at = None
            if not unscheduled and end_date >= date(2013, 3, 1):
                statement_published_at = datetime(
                    end_date.year,
                    end_date.month,
                    end_date.day,
                    14,
                    0,
                    tzinfo=ZoneInfo("America/New_York"),
                ).astimezone(UTC)
            # The Board documents 2:30 p.m. ET as the regular post-meeting
            # news-conference time since March 2013.  We only apply that
            # official rule when the meeting page links a conference, or for
            # the post-2019 every-meeting conference schedule.  Unscheduled
            # meetings retain an unknown start time.
            press_conference_at = None
            if (
                not unscheduled
                and end_date >= date(2013, 3, 1)
                and (has_press_conference or end_date >= date(2019, 1, 1))
            ):
                press_conference_at = datetime(
                    end_date.year,
                    end_date.month,
                    end_date.day,
                    14,
                    30,
                    tzinfo=ZoneInfo("America/New_York"),
                ).astimezone(UTC)
            meetings.append(
                FomcMeeting(
                    meeting_key=f"FOMC-{end_date.isoformat()}",
                    start_date=start_date,
                    end_date=end_date,
                    materials=meeting_materials,
                    statement_published_at=statement_published_at,
                    press_conference_at=press_conference_at,
                    has_sep=sep_marker
                    or any(
                        item.material_type
                        in {FomcMaterialType.SEP, FomcMaterialType.PROJECTION_TABLES}
                        for item in meeting_materials
                    ),
                    metadata={
                        "start_date_precision": (
                            "official_meeting_grid"
                            if start_date != end_date or meeting_grid.rows
                            else "end_date_only"
                        ),
                        "future_materials_may_be_empty": not bool(meeting_materials),
                        "unscheduled_meeting": unscheduled,
                        "statement_time_verified": statement_published_at is not None,
                        "statement_time_basis": (
                            "official_standard_schedule_since_2013"
                            if statement_published_at
                            else "unavailable"
                        ),
                        "press_conference_time_verified": press_conference_at is not None,
                        "press_conference_time_basis": (
                            "official_standard_schedule_since_2013_and_meeting_specific_link"
                            if press_conference_at and has_press_conference
                            else "official_every_meeting_schedule_since_2019"
                            if press_conference_at
                            else "unavailable"
                        ),
                        "calendar_artifact_hash": artifact.content_hash,
                    },
                )
            )
        return FomcCalendarBatch(
            provider_key=self.key,
            retrieved_at=retrieved_at,
            artifacts=(artifact,),
            quality=quality,
            idempotency_key=hashlib.sha256(
                f"fomc-calendar:{artifact.content_hash}".encode()
            ).hexdigest(),
            meetings=tuple(meetings),
        )

    async def fetch_material(
        self,
        url: str,
        material_type: FomcMaterialType,
    ) -> FomcDocument:
        if not url.startswith(self.base_url):
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "FOMC material URL must be hosted by federalreserve.gov",
            )
        response = await self._transport.request("GET", url)
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type == "application/pdf" or str(response.url).lower().endswith(".pdf"):
            retrieved_at = datetime.now(UTC)
            source_url = str(response.url)
            source_date = _url_date(source_url)
            artifact = SourceArtifact.capture(
                provider_key=self.key,
                source_url=source_url,
                retrieved_at=retrieved_at,
                content_type="application/pdf",
                content=response.content,
                terms=self.terms,
                metadata={
                    "material_type": material_type.value,
                    "source_date": source_date.isoformat() if source_date else None,
                    "binary_document": True,
                },
            )
            return FomcDocument(
                document_type=material_type,
                title=material_type.value.replace("_", " ").title(),
                text="",
                source_url=source_url,
                published_at=None,
                artifact=artifact,
                metadata={
                    "publication_time_precision": "date_only" if source_date else "unknown",
                    "source_date": source_date.isoformat() if source_date else None,
                    "binary_document": True,
                    "key_qa_timestamp_generated": False,
                    "semantic_hash": artifact.content_hash,
                    "semantic_hash_scope": "raw_pdf",
                },
            )
        return self.adapt_material_html(
            response.content,
            material_type=material_type,
            retrieved_at=datetime.now(UTC),
            source_url=str(response.url),
        )

    def adapt_material_html(
        self,
        payload: bytes | str,
        *,
        material_type: FomcMaterialType,
        retrieved_at: AwareDatetime,
        source_url: str,
    ) -> FomcDocument:
        raw = payload.encode() if isinstance(payload, str) else payload
        try:
            rendered = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProviderSchemaError(
                self.key,
                "FOMC material was not UTF-8 HTML",
                structure="official article title and body text",
            ) from exc
        parser = _VisibleHtmlParser()
        parser.feed(rendered)
        visible_text = html_module.unescape(" ".join(parser.text))
        normalized = " ".join(visible_text.split())
        semantic_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        expected_terms: dict[FomcMaterialType, tuple[str, ...]] = {
            FomcMaterialType.STATEMENT: ("federal open market committee", "target range"),
            FomcMaterialType.IMPLEMENTATION_NOTE: ("implementation note",),
            FomcMaterialType.SEP: ("economic projections",),
            FomcMaterialType.PROJECTION_TABLES: ("projection",),
            FomcMaterialType.PRESS_CONFERENCE: ("press conference",),
            FomcMaterialType.OPENING_STATEMENT: ("opening statement",),
            FomcMaterialType.TRANSCRIPT: ("transcript",),
            FomcMaterialType.MINUTES: ("minutes", "federal open market committee"),
            FomcMaterialType.OTHER: (),
        }
        lowered = normalized.lower()
        required = expected_terms[material_type]
        if len(normalized) < 40 or (required and not any(term in lowered for term in required)):
            raise ProviderSchemaError(
                self.key,
                f"FOMC {material_type.value} page no longer matches the expected structure",
                structure=f"official article body containing one of: {', '.join(required)}",
                details={"source_url": source_url},
            )
        published_at = _published_time(
            parser,
            source_url,
            normalized,
            material_type=material_type,
        )
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=retrieved_at,
            published_at=published_at,
            content_type="text/html",
            content=raw,
            terms=self.terms,
            metadata={
                "material_type": material_type.value,
                "semantic_hash": semantic_hash,
                "semantic_hash_scope": "normalized_visible_text",
            },
        )
        target_match = _TARGET_RANGE.search(normalized)
        target_rate_lower = _rate_value(target_match.group(1)) if target_match else None
        target_rate_upper = _rate_value(target_match.group(2)) if target_match else None
        title = " ".join(parser.title).strip() or material_type.value.replace("_", " ").title()
        linked_materials: list[dict[str, str]] = []
        for href, link_title in parser.links:
            linked_url = urljoin(source_url, href)
            linked_type = _material_type(link_title, linked_url)
            if linked_type == FomcMaterialType.OTHER or linked_url == source_url:
                continue
            linked_materials.append(
                {
                    "material_type": linked_type.value,
                    "title": link_title or linked_type.value.replace("_", " ").title(),
                    "url": linked_url,
                }
            )
        return FomcDocument(
            document_type=material_type,
            title=title,
            text=normalized,
            source_url=source_url,
            published_at=published_at,
            target_rate_lower=target_rate_lower,
            target_rate_upper=target_rate_upper,
            artifact=artifact,
            metadata={
                "publication_time_precision": "timestamp" if published_at else "unknown",
                "key_qa_timestamp_generated": False,
                "semantic_hash": semantic_hash,
                "semantic_hash_scope": "normalized_visible_text",
                "linked_materials": list({item["url"]: item for item in linked_materials}.values()),
            },
        )

    async def healthcheck(self) -> ProviderHealth:
        started = datetime.now(UTC)
        try:
            response = await self._transport.request("GET", self.calendar_url)
            if "fomc" not in response.text.lower():
                raise ValueError("calendar marker absent")
        except Exception as exc:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                message=f"Federal Reserve request failed: {type(exc).__name__}",
            )
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.OK,
            checked_at=datetime.now(UTC),
            latency_ms=(datetime.now(UTC) - started).total_seconds() * 1000,
        )
