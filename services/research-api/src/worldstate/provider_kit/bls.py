"""BLS Public Data API adapter for CPI and employment releases."""

from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, ClassVar, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import AwareDatetime, Field

from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.macro_core.enums import ProviderStatus
from worldstate.macro_core.models import ProviderHealth
from worldstate.provider_kit.contracts import (
    NormalizedObservation,
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


class _IndicatorSpec:
    def __init__(
        self,
        canonical_key: str,
        series_id: str,
        raw_unit: str,
        standard_unit: str,
        metric: Literal["level", "change_1", "pct_1", "pct_12"],
        scale_factor: Decimal = Decimal("1"),
    ) -> None:
        self.canonical_key = canonical_key
        self.series_id = series_id
        self.raw_unit = raw_unit
        self.standard_unit = standard_unit
        self.metric = metric
        self.scale_factor = scale_factor


CPI_INDICATORS: tuple[_IndicatorSpec, ...] = (
    _IndicatorSpec(
        "US_CPI.HEADLINE.MOM",
        "CUSR0000SA0",
        "index_1982_84_100",
        "percent_change",
        "pct_1",
    ),
    _IndicatorSpec(
        "US_CPI.HEADLINE.YOY",
        "CUSR0000SA0",
        "index_1982_84_100",
        "percent_change",
        "pct_12",
    ),
    _IndicatorSpec(
        "US_CPI.CORE.MOM",
        "CUSR0000SA0L1E",
        "index_1982_84_100",
        "percent_change",
        "pct_1",
    ),
    _IndicatorSpec(
        "US_CPI.CORE.YOY",
        "CUSR0000SA0L1E",
        "index_1982_84_100",
        "percent_change",
        "pct_12",
    ),
)

NFP_INDICATORS: tuple[_IndicatorSpec, ...] = (
    _IndicatorSpec(
        "US_NFP.NONFARM_PAYROLLS",
        "CES0000000001",
        "thousand_persons_level",
        "thousand_persons",
        "change_1",
    ),
    _IndicatorSpec(
        "US_NFP.UNEMPLOYMENT_RATE",
        "LNS14000000",
        "percent",
        "percentage_points",
        "level",
    ),
    _IndicatorSpec(
        "US_NFP.AVERAGE_HOURLY_EARNINGS.MOM",
        "CES0500000003",
        "usd_per_hour",
        "percent_change",
        "pct_1",
    ),
    _IndicatorSpec(
        "US_NFP.AVERAGE_HOURLY_EARNINGS.YOY",
        "CES0500000003",
        "usd_per_hour",
        "percent_change",
        "pct_12",
    ),
    _IndicatorSpec(
        "US_NFP.LABOR_FORCE_PARTICIPATION",
        "LNS11300000",
        "percent",
        "percentage_points",
        "level",
    ),
)

BLS_SERIES_MAP: dict[str, str] = {
    spec.canonical_key: spec.series_id for spec in (*CPI_INDICATORS, *NFP_INDICATORS)
}


class BlsReleaseBatch(ProviderBatch):
    release_family: Literal["US_CPI", "US_NFP"]
    observations: tuple[NormalizedObservation, ...]
    unavailable_series: tuple[str, ...] = ()


class BlsScheduleEntry(ProviderModel):
    release_family: Literal["US_CPI", "US_NFP"]
    title: str
    release_date: date
    scheduled_local: AwareDatetime
    source_timezone: str = "America/New_York"
    source_time_text: str
    source_url: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_period: str | None = None


class BlsScheduleBatch(ProviderBatch):
    release_family: Literal["US_CPI", "US_NFP"]
    entries: tuple[BlsScheduleEntry, ...]


class _ScheduleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            normalized = html_module.unescape(" ".join(data.split()))
            if normalized:
                self._cell.append(normalized)


_SCHEDULE_DATE = re.compile(
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(?P<day>\d{1,2})(?:,?\s+(?P<year>20\d{2}))?",
    re.IGNORECASE,
)
_SCHEDULE_TIME = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>[AP])\.?M\.?")
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_ICS_PERIOD = re.compile(
    r"\bfor\s+(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
_PLAIN_PERIOD = re.compile(
    r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
_BLS_MONTH_CELL = re.compile(
    r"<td\b[^>]*\bid=[\"']d(?P<month>\d{2})(?P<day>\d{2})[\"'][^>]*>"
    r"(?P<body>.*?)</td>",
    re.IGNORECASE | re.DOTALL,
)
_BLS_EVENT_PARAGRAPH = re.compile(
    r"<p>\s*<strong>(?P<title>.*?)</strong>(?P<body>.*?)</p>",
    re.IGNORECASE | re.DOTALL,
)


def _unfold_ics_lines(payload: bytes | str) -> list[str]:
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    physical = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in physical:
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape_ics(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _reference_period(text: str) -> str | None:
    match = _ICS_PERIOD.search(text) or _PLAIN_PERIOD.search(text)
    if match is None:
        return None
    month = _MONTHS[match.group("month")[:3].lower()]
    return f"{match.group('year')}-{month:02d}"


def _plain_html(text: str) -> str:
    return html_module.unescape(re.sub(r"<[^>]+>", " ", text))


def _parse_ics_datetime(value: str, parameters: dict[str, str]) -> datetime | None:
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%S")
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y%m%dT%H%M")
        except ValueError:
            return None
    timezone_name = parameters.get("TZID", "America/New_York")
    try:
        return parsed.replace(tzinfo=ZoneInfo(timezone_name))
    except Exception:
        return parsed.replace(tzinfo=ZoneInfo("America/New_York"))


class BlsOfficialProvider:
    """Normalize BLS payloads without pretending the current API is a vintage API."""

    key = "bls_official"
    endpoint = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
    schedule_urls: ClassVar[dict[str, str]] = {
        "US_CPI": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "US_NFP": "https://www.bls.gov/schedule/news_release/empsit.htm",
    }
    public_calendar_url = "https://www.bls.gov/schedule/news_release/bls.ics"
    user_agent = "WorldStateTerminal/0.7 (+https://github.com/631231771-cmd/worldstate-terminal)"
    terms = ProviderTerms(
        license_name="United States Government public data",
        terms_url="https://www.bls.gov/bls/linksite.htm",
        redistribution_allowed=True,
        notes="BLS API usage limits and attribution guidance still apply.",
    )

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 30,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._historical_schedule_cache: dict[int, tuple[bytes, datetime, str]] = {}
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
            domains=(ProviderDomain.MACRO_RELEASE, ProviderDomain.MACRO_SERIES),
            operations=(
                "fetch_cpi",
                "fetch_nfp",
                "fetch_public_calendar",
                "healthcheck",
            ),
            supports_point_in_time=False,
            supports_revisions=True,
            supports_batch=True,
            paid_access=False,
            metadata={
                "families": ["US_CPI", "US_NFP"],
                "terms_url": self.terms.terms_url,
                "license_name": self.terms.license_name,
                "point_in_time_constraint": (
                    "BLS current API responses are PIT only from the local capture timestamp"
                ),
                "public_limits": {
                    "series_per_query": 25,
                    "years_per_query": 10,
                    "requests_per_day": 25,
                    "calendar": "public ICS feed does not require a registered API key",
                },
                "registered_limits": {
                    "series_per_query": 50,
                    "years_per_query": 20,
                    "requests_per_day": 500,
                },
            },
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    @staticmethod
    def _specs(family: Literal["US_CPI", "US_NFP"]) -> tuple[_IndicatorSpec, ...]:
        return CPI_INDICATORS if family == "US_CPI" else NFP_INDICATORS

    @staticmethod
    def _period(item: dict[str, Any]) -> date | None:
        period = str(item.get("period", ""))
        if len(period) != 3 or not period.startswith("M") or period == "M13":
            return None
        try:
            return date(int(str(item["year"])), int(period[1:]), 1)
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        if value in {None, "", ".", "NaN"}:
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    @classmethod
    def _metric_value(cls, spec: _IndicatorSpec, item: dict[str, Any]) -> Decimal | None:
        if spec.metric in {"level", "change_1"}:
            return cls._decimal(item.get("value"))
        calculations = item.get("calculations")
        if not isinstance(calculations, dict):
            return None
        changes = calculations.get("pct_changes")
        if not isinstance(changes, dict):
            return None
        months = "1" if spec.metric == "pct_1" else "12"
        return cls._decimal(changes.get(months))

    @staticmethod
    def _snapshot_key(series_id: str, period: date, metric: str) -> str:
        return f"{series_id}:{period.isoformat()}:{metric}"

    @staticmethod
    def _prior_month(period: date, months: int) -> date:
        month_index = period.year * 12 + period.month - 1 - months
        return date(month_index // 12, month_index % 12 + 1, 1)

    async def fetch_release(
        self,
        family: Literal["US_CPI", "US_NFP"],
        *,
        start_year: int,
        end_year: int,
        available_at: AwareDatetime | None = None,
        as_of: AwareDatetime | None = None,
        prior_snapshot: dict[str, Decimal] | None = None,
    ) -> BlsReleaseBatch:
        """Fetch a range, automatically respecting registered/public year limits."""

        return await self.fetch_bundle(
            family,
            start_year=start_year,
            end_year=end_year,
            available_at=available_at,
            as_of=as_of,
            prior_snapshot=prior_snapshot,
        )

    async def fetch_bundle(
        self,
        family: Literal["US_CPI", "US_NFP"],
        *,
        start_year: int,
        end_year: int,
        available_at: AwareDatetime | None = None,
        as_of: AwareDatetime | None = None,
        prior_snapshot: dict[str, Decimal] | None = None,
    ) -> BlsReleaseBatch:
        if start_year > end_year:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "start_year cannot be later than end_year",
            )
        maximum_years = 20 if self._api_key else 10
        batches: list[BlsReleaseBatch] = []
        chunk_start = start_year
        while chunk_start <= end_year:
            chunk_end = min(end_year, chunk_start + maximum_years - 1)
            batches.append(
                await self._fetch_release_chunk(
                    family,
                    start_year=chunk_start,
                    end_year=chunk_end,
                    available_at=available_at,
                    as_of=as_of,
                    prior_snapshot=prior_snapshot,
                )
            )
            chunk_start = chunk_end + 1
        first = batches[0]
        artifacts = tuple(artifact for batch in batches for artifact in batch.artifacts)
        observations = tuple(observation for batch in batches for observation in batch.observations)
        missing = tuple(
            sorted({series_id for batch in batches for series_id in batch.unavailable_series})
        )
        warnings = tuple(warning for batch in batches for warning in batch.warnings)
        return BlsReleaseBatch(
            provider_key=self.key,
            retrieved_at=max(batch.retrieved_at for batch in batches),
            artifacts=artifacts,
            quality=first.quality,
            warnings=warnings,
            idempotency_key=hashlib.sha256(
                (family + ":" + ":".join(item.content_hash for item in artifacts)).encode()
            ).hexdigest(),
            release_family=family,
            observations=observations,
            unavailable_series=missing,
        )

    async def _fetch_release_chunk(
        self,
        family: Literal["US_CPI", "US_NFP"],
        *,
        start_year: int,
        end_year: int,
        available_at: AwareDatetime | None,
        as_of: AwareDatetime | None,
        prior_snapshot: dict[str, Decimal] | None,
    ) -> BlsReleaseBatch:
        request_body: dict[str, object] = {
            "seriesid": sorted({spec.series_id for spec in self._specs(family)}),
            "startyear": str(start_year),
            "endyear": str(end_year),
            "calculations": True,
            "annualaverage": False,
        }
        if self._api_key:
            request_body["registrationkey"] = self._api_key
        response = await self._transport.request(
            "POST",
            self.endpoint,
            json_body=request_body,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        retrieved_at = datetime.now(UTC)
        return self.adapt_payload(
            response.content,
            family=family,
            retrieved_at=retrieved_at,
            source_url=str(response.url),
            available_at=available_at,
            as_of=as_of,
            prior_snapshot=prior_snapshot,
        )

    def adapt_payload(
        self,
        payload: bytes | str | dict[str, Any],
        *,
        family: Literal["US_CPI", "US_NFP"],
        retrieved_at: AwareDatetime,
        source_url: str | None = None,
        available_at: AwareDatetime | None = None,
        as_of: AwareDatetime | None = None,
        prior_snapshot: dict[str, Decimal] | None = None,
    ) -> BlsReleaseBatch:
        if as_of is not None and retrieved_at > as_of:
            raise ProviderError(
                self.key,
                ProviderErrorCode.POINT_IN_TIME,
                "A BLS snapshot captured after the requested cutoff cannot be used point-in-time",
                details={"retrieved_at": retrieved_at.isoformat(), "as_of": as_of.isoformat()},
            )
        if isinstance(payload, dict):
            document = payload
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        else:
            raw = payload.encode() if isinstance(payload, str) else payload
            try:
                decoded = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderSchemaError(
                    self.key,
                    "BLS response was not valid JSON",
                    structure="Results.series[]",
                ) from exc
            if not isinstance(decoded, dict):
                raise ProviderSchemaError(
                    self.key,
                    "BLS response root was not an object",
                    structure="Results.series[]",
                )
            document = decoded
        if document.get("status") != "REQUEST_SUCCEEDED":
            messages = document.get("message")
            raise ProviderError(
                self.key,
                ProviderErrorCode.TRANSPORT,
                "BLS did not accept the data request",
                details={"messages": messages if isinstance(messages, list) else []},
            )
        results = document.get("Results")
        series_rows = results.get("series") if isinstance(results, dict) else None
        if not isinstance(series_rows, list):
            raise ProviderSchemaError(
                self.key,
                "BLS response no longer contains a series array",
                structure="Results.series[]",
            )

        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url or self.endpoint,
            retrieved_at=retrieved_at,
            published_at=available_at,
            content_type="application/json",
            content=raw,
            terms=self.terms,
            metadata={"release_family": family},
        )
        known_at = available_at or retrieved_at
        quality = DataQuality(
            source_name="U.S. Bureau of Labor Statistics",
            source_url=source_url or self.endpoint,
            source_type="official_api",
            acquired_at=retrieved_at,
            is_verified=True,
            latency_seconds=max(0, int((retrieved_at - known_at).total_seconds())),
            quality_grade=QualityGrade.A if available_at else QualityGrade.B,
            verification_notes=(
                None
                if available_at
                else "Official release timestamp absent; retrieval time is the availability proxy."
            ),
            metadata={"pit_capture": True, "supports_historical_vintages": False},
        )
        rows_by_series: dict[str, list[dict[str, Any]]] = {}
        for series in series_rows:
            if not isinstance(series, dict) or not isinstance(series.get("seriesID"), str):
                continue
            data = series.get("data")
            if isinstance(data, list):
                rows_by_series[str(series["seriesID"])] = [
                    row for row in data if isinstance(row, dict)
                ]

        response_messages = document.get("message")
        provider_warnings = (
            [str(item) for item in response_messages if str(item).strip()]
            if isinstance(response_messages, list)
            else []
        )
        observations: list[NormalizedObservation] = []
        missing: list[str] = []
        previous_snapshot = prior_snapshot or {}
        for spec in self._specs(family):
            series_data = rows_by_series.get(spec.series_id)
            if series_data is None:
                missing.append(spec.series_id)
                continue
            parsed: list[tuple[date, dict[str, Any], Decimal | None, str]] = []
            for row in series_data:
                period = self._period(row)
                if period is None:
                    continue
                metric_value = self._metric_value(spec, row)
                calculation_source = (
                    "bls_calculations"
                    if spec.metric in {"pct_1", "pct_12"} and metric_value is not None
                    else "bls_reported_level"
                )
                parsed.append((period, row, metric_value, calculation_source))
            parsed.sort(key=lambda part: part[0])
            if spec.metric == "change_1":
                differenced: list[tuple[date, dict[str, Any], Decimal | None, str]] = []
                prior_level: Decimal | None = None
                for period, row, level, _calculation_source in parsed:
                    change = (
                        level - prior_level
                        if level is not None and prior_level is not None
                        else None
                    )
                    differenced.append(
                        (period, row, change, "worldstate_first_difference")
                    )
                    prior_level = level
                parsed = differenced
            elif spec.metric in {"pct_1", "pct_12"}:
                levels = {
                    period: self._decimal(row.get("value"))
                    for period, row, _value, _calculation_source in parsed
                }
                lag_months = 1 if spec.metric == "pct_1" else 12
                derived: list[tuple[date, dict[str, Any], Decimal | None, str]] = []
                for period, row, value, calculation_source in parsed:
                    if value is not None:
                        derived.append((period, row, value, calculation_source))
                        continue
                    level = levels.get(period)
                    prior_level = levels.get(self._prior_month(period, lag_months))
                    if level is None or prior_level is None or prior_level == Decimal("0"):
                        derived.append((period, row, None, "unavailable"))
                        continue
                    # The unregistered public API can disable `calculations` even
                    # when requested.  Reproduce the one-decimal release convention
                    # from official levels and disclose that derivation explicitly.
                    percent = ((level / prior_level) - Decimal("1")) * Decimal("100")
                    derived.append(
                        (
                            period,
                            row,
                            percent.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
                            "worldstate_from_official_levels",
                        )
                    )
                parsed = derived
            for index, (period, row, value, calculation_source) in enumerate(parsed):
                if value is None:
                    continue
                prior_period_value = parsed[index - 1][2] if index else None
                snapshot_key = self._snapshot_key(spec.series_id, period, spec.metric)
                old_value = previous_snapshot.get(snapshot_key)
                prior_period_old: Decimal | None = None
                if index:
                    prior_period_old = previous_snapshot.get(
                        self._snapshot_key(spec.series_id, parsed[index - 1][0], spec.metric)
                    )
                is_revision = old_value is not None and old_value != value
                observations.append(
                    NormalizedObservation(
                        canonical_key=spec.canonical_key,
                        provider_series_id=spec.series_id,
                        reference_period_start=period,
                        reference_period_end=period,
                        value=value * spec.scale_factor,
                        raw_value=str(row.get("value")),
                        raw_unit=spec.raw_unit,
                        standard_unit=spec.standard_unit,
                        scale_factor=spec.scale_factor,
                        available_at=known_at,
                        retrieved_at=retrieved_at,
                        vintage_date=retrieved_at.date(),
                        version=artifact.content_hash[:16],
                        is_first_release=False,
                        is_revision=is_revision,
                        previous_value=prior_period_old,
                        revised_previous_value=(
                            prior_period_value
                            if (
                                prior_period_old is not None
                                and prior_period_old != prior_period_value
                            )
                            else None
                        ),
                        quality=quality,
                        artifact_hash=artifact.content_hash,
                        metadata={
                            "metric": spec.metric,
                            "calculation_source": calculation_source,
                            "bls_latest_flag": bool(row.get("latest", False)),
                            "availability_method": (
                                "official_release_timestamp"
                                if available_at
                                else "ingestion_time_proxy"
                            ),
                            "revision_from_value": str(old_value) if is_revision else None,
                            "normalized_value_from_calculation": (
                                str(value) if spec.metric != "level" else None
                            ),
                            "derivation": (
                                "first_difference_of_seasonally_adjusted_payroll_level"
                                if spec.metric == "change_1"
                                else spec.metric
                            ),
                            "first_release_status": "unknown_from_bls_current_api",
                            "revision_chain_scope": "worldstate_continuous_retrievals",
                            "previous_value_reconstruction": (
                                "local_prior_snapshot"
                                if prior_period_old is not None
                                else "unavailable_without_prior_local_capture"
                            ),
                        },
                    )
                )
        idempotency_key = hashlib.sha256(
            f"{family}:{artifact.content_hash}:{retrieved_at.isoformat()}".encode()
        ).hexdigest()
        return BlsReleaseBatch(
            provider_key=self.key,
            retrieved_at=retrieved_at,
            artifacts=(artifact,),
            quality=quality,
            warnings=(
                *provider_warnings,
                *(
                    (
                        "Some requested BLS series were unavailable: "
                        + ", ".join(sorted(set(missing))),
                    )
                    if missing
                    else ()
                ),
            ),
            idempotency_key=idempotency_key,
            release_family=family,
            observations=tuple(observations),
            unavailable_series=tuple(sorted(set(missing))),
        )

    async def fetch_schedule(
        self,
        family: Literal["US_CPI", "US_NFP"],
        *,
        year: int,
    ) -> BlsScheduleBatch:
        # BLS publishes the current and forward release calendar as a public
        # ICS feed.  It is intentionally independent of the registered Data
        # API entitlement used by fetch_bundle/fetch_actuals.
        public_error: ProviderError | ProviderSchemaError | None = None
        if year >= datetime.now(UTC).year:
            try:
                return await self.fetch_public_calendar(family, year=year)
            except (ProviderError, ProviderSchemaError) as exc:
                # Keep the official schedule HTML as a secondary fallback;
                # callers retain the warning/provenance from the final source.
                public_error = exc
        base_url = self.schedule_urls[family]
        current_year = datetime.now(UTC).year
        source_url = (
            f"https://www.bls.gov/schedule/{year}/home.htm"
            if year < current_year
            else base_url
        )
        cached = self._historical_schedule_cache.get(year) if year < current_year else None
        if cached is None:
            try:
                response = await self._transport.request(
                    "GET",
                    source_url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    },
                )
            except ProviderError as exc:
                if public_error is not None:
                    raise ProviderError(
                        self.key,
                        ProviderErrorCode.PUBLIC_CALENDAR_UNAVAILABLE,
                        "BLS official public calendar and HTML fallback are unavailable",
                        retryable=public_error.retryable or exc.retryable,
                        status_code=exc.status_code,
                        details={
                            "public_calendar_error": public_error.error_code.value,
                            "fallback_error": exc.error_code.value,
                            "public_calendar_url": self.public_calendar_url,
                            "fallback_url": source_url,
                        },
                    ) from exc
                raise
            content = response.content
            retrieved_at = datetime.now(UTC)
            resolved_url = str(response.url)
            if year < current_year:
                self._historical_schedule_cache[year] = (
                    content,
                    retrieved_at,
                    resolved_url,
                )
        else:
            content, retrieved_at, resolved_url = cached
        return self.adapt_schedule_html(
            content,
            family=family,
            year=year,
            retrieved_at=retrieved_at,
            source_url=resolved_url,
            calendar_provider=(
                "bls_official_schedule_html_fallback"
                if public_error is not None
                else "bls_official_schedule_html"
            ),
            fallback_from=(self.public_calendar_url if public_error is not None else None),
        )

    async def fetch_public_calendar(
        self,
        family: Literal["US_CPI", "US_NFP"],
        *,
        year: int,
    ) -> BlsScheduleBatch:
        response = await self._transport.request(
            "GET",
            self.public_calendar_url,
            headers={
                "Accept": "text/calendar,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": self.user_agent,
            },
        )
        return self.adapt_schedule_ics(
            response.content,
            family=family,
            year=year,
            retrieved_at=datetime.now(UTC),
            source_url=str(response.url),
        )

    def adapt_schedule_ics(
        self,
        payload: bytes | str,
        *,
        family: Literal["US_CPI", "US_NFP"],
        year: int,
        retrieved_at: AwareDatetime,
        source_url: str,
    ) -> BlsScheduleBatch:
        """Parse BLS's public calendar without requiring a BLS API key."""

        raw = payload.encode() if isinstance(payload, str) else payload
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=retrieved_at,
            content_type="text/calendar",
            content=raw,
            terms=self.terms,
            metadata={
                "release_family": family,
                "schedule_year": year,
                "calendar_provider": "bls_public_calendar",
                "official": True,
                "parser": "bls-public-calendar-ics-v1",
            },
        )
        entries: list[BlsScheduleEntry] = []
        event: dict[str, tuple[dict[str, str], str]] | None = None
        for line in [*_unfold_ics_lines(raw), "END:VEVENT"]:
            if line == "BEGIN:VEVENT":
                event = {}
                continue
            if line == "END:VEVENT":
                if event is None:
                    continue
                summary = _unescape_ics(event.get("SUMMARY", ({}, ""))[1])
                description = _unescape_ics(event.get("DESCRIPTION", ({}, ""))[1])
                combined = f"{summary} {description}".lower()
                marker = (
                    "consumer price index"
                    if family == "US_CPI"
                    else "employment situation"
                )
                if marker not in combined:
                    event = None
                    continue
                start_data = event.get("DTSTART")
                if start_data is None:
                    event = None
                    continue
                scheduled = _parse_ics_datetime(start_data[1], start_data[0])
                if scheduled is None or scheduled.year != year:
                    event = None
                    continue
                period = _reference_period(f"{summary} {description}")
                title = (
                    "Consumer Price Index"
                    if family == "US_CPI"
                    else "Employment Situation"
                )
                entries.append(
                    BlsScheduleEntry(
                        release_family=family,
                        title=title,
                        release_date=scheduled.date(),
                        scheduled_local=scheduled,
                        source_timezone="America/New_York",
                        source_time_text=scheduled.strftime("%I:%M %p"),
                        source_url=source_url,
                        artifact_hash=artifact.content_hash,
                        reference_period=period,
                    )
                )
                event = None
                continue
            if event is None or ":" not in line:
                continue
            name, value = line.split(":", 1)
            parts = name.split(";")
            params = {
                item.split("=", 1)[0].upper(): item.split("=", 1)[1]
                for item in parts[1:]
                if "=" in item
            }
            event[parts[0].upper()] = (params, value)
        if not entries:
            raise ProviderSchemaError(
                self.key,
                "BLS public calendar ICS yielded no requested release events",
                structure="VEVENT with DTSTART and CPI/NFP summary",
                details={"release_family": family, "schedule_year": year},
            )
        quality = DataQuality(
            source_name="U.S. Bureau of Labor Statistics public release calendar",
            source_url=source_url,
            source_type="official_ics",
            acquired_at=retrieved_at,
            is_verified=True,
            quality_grade=QualityGrade.A,
            metadata={
                "source_timezone": "America/New_York",
                "calendar_provider": "bls_public_calendar",
                "official": True,
                "parser": "bls-public-calendar-ics-v1",
            },
        )
        return BlsScheduleBatch(
            provider_key=self.key,
            retrieved_at=retrieved_at,
            artifacts=(artifact,),
            quality=quality,
            idempotency_key=hashlib.sha256(
                f"bls-public-calendar:{family}:{year}:{artifact.content_hash}".encode()
            ).hexdigest(),
            release_family=family,
            entries=tuple(sorted(entries, key=lambda item: item.scheduled_local)),
        )

    def adapt_schedule_html(
        self,
        payload: bytes | str,
        *,
        family: Literal["US_CPI", "US_NFP"],
        year: int,
        retrieved_at: AwareDatetime,
        source_url: str,
        calendar_provider: str = "bls_official_schedule_html",
        fallback_from: str | None = None,
    ) -> BlsScheduleBatch:
        raw = payload.encode() if isinstance(payload, str) else payload
        try:
            rendered = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProviderSchemaError(
                self.key,
                "BLS release schedule was not UTF-8 HTML",
                structure="schedule table with month/day and ET release time",
            ) from exc
        parser = _ScheduleTableParser()
        parser.feed(rendered)
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=retrieved_at,
            content_type="text/html",
            content=raw,
            terms=self.terms,
            metadata={
                "release_family": family,
                "schedule_year": year,
                "calendar_provider": calendar_provider,
                "official": True,
                **({"fallback_from": fallback_from} if fallback_from else {}),
            },
        )
        entries: list[BlsScheduleEntry] = []
        historical_full_calendar = f"/schedule/{year}/" in source_url
        family_marker = (
            "consumer price index" if family == "US_CPI" else "employment situation"
        )
        if historical_full_calendar:
            # Month-view pages encode the actual calendar day in the cell id
            # (for example d0812).  Do not infer that day from the period text.
            for cell in _BLS_MONTH_CELL.finditer(rendered):
                month = int(cell.group("month"))
                day = int(cell.group("day"))
                for event in _BLS_EVENT_PARAGRAPH.finditer(cell.group("body")):
                    event_text = _plain_html(
                        f"{event.group('title')} {event.group('body')}"
                    )
                    if family_marker not in event_text.lower():
                        continue
                    time_match = _SCHEDULE_TIME.search(event_text)
                    if time_match is None:
                        continue
                    hour = int(time_match.group("hour"))
                    if time_match.group("ampm").upper() == "P" and hour != 12:
                        hour += 12
                    if time_match.group("ampm").upper() == "A" and hour == 12:
                        hour = 0
                    try:
                        release_date = date(year, month, day)
                    except ValueError:
                        continue
                    entries.append(
                        BlsScheduleEntry(
                            release_family=family,
                            title=(
                                "Consumer Price Index"
                                if family == "US_CPI"
                                else "Employment Situation"
                            ),
                            release_date=release_date,
                            scheduled_local=datetime(
                                year,
                                month,
                                day,
                                hour,
                                int(time_match.group("minute")),
                                tzinfo=ZoneInfo("America/New_York"),
                            ),
                            source_time_text=time_match.group(0),
                            source_url=source_url,
                            artifact_hash=artifact.content_hash,
                            reference_period=_reference_period(event_text),
                        )
                    )
        if not entries:
            for row in parser.rows:
                row_text = " ".join(row)
                date_match = _SCHEDULE_DATE.search(row_text)
                time_match = _SCHEDULE_TIME.search(row_text)
                if date_match is None or time_match is None:
                    continue
                row_year = int(date_match.group("year") or year)
                if row_year != year or (
                    historical_full_calendar and family_marker not in row_text.lower()
                ):
                    continue
                month = _MONTHS[date_match.group("month")[:3].lower()]
                day = int(date_match.group("day"))
                hour = int(time_match.group("hour"))
                if time_match.group("ampm").upper() == "P" and hour != 12:
                    hour += 12
                if time_match.group("ampm").upper() == "A" and hour == 12:
                    hour = 0
                try:
                    release_date = date(row_year, month, day)
                except ValueError:
                    continue
                entries.append(
                    BlsScheduleEntry(
                        release_family=family,
                        title=(
                            "Consumer Price Index"
                            if family == "US_CPI"
                            else "Employment Situation"
                        ),
                        release_date=release_date,
                        scheduled_local=datetime(
                            row_year,
                            month,
                            day,
                            hour,
                            int(time_match.group("minute")),
                            tzinfo=ZoneInfo("America/New_York"),
                        ),
                        source_time_text=time_match.group(0),
                        source_url=source_url,
                        artifact_hash=artifact.content_hash,
                        reference_period=_reference_period(row_text),
                    )
                )
        if not entries:
            raise ProviderSchemaError(
                self.key,
                "BLS schedule structure did not yield any dated release times",
                structure="schedule table with month/day and ET release time",
                details={"release_family": family, "year": year},
            )
        quality = DataQuality(
            source_name="U.S. Bureau of Labor Statistics release calendar",
            source_url=source_url,
            source_type="official_html",
            acquired_at=retrieved_at,
            is_verified=True,
            quality_grade=QualityGrade.A,
            metadata={
                "source_timezone": "America/New_York",
                "calendar_provider": calendar_provider,
                "official": True,
                "parser": "bls-schedule-v1",
                **({"fallback_from": fallback_from} if fallback_from else {}),
            },
        )
        return BlsScheduleBatch(
            provider_key=self.key,
            retrieved_at=retrieved_at,
            artifacts=(artifact,),
            quality=quality,
            idempotency_key=hashlib.sha256(
                f"bls-schedule:{family}:{year}:{artifact.content_hash}".encode()
            ).hexdigest(),
            release_family=family,
            entries=tuple(sorted(entries, key=lambda item: item.scheduled_local)),
        )

    def adapt_browser_schedule_html(
        self,
        payload: bytes | str,
        *,
        family: Literal["US_CPI", "US_NFP"],
        year: int,
        retrieved_at: AwareDatetime,
        source_url: str,
    ) -> BlsScheduleBatch:
        """Adapt an official BLS page captured by the controlled browser.

        This is intentionally separate from HTTP sync so provenance never
        claims that the Research API fetched a page it did not fetch.
        """

        if not source_url.startswith("https://www.bls.gov/schedule/"):
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "browser calendar capture must use an official BLS schedule URL",
            )
        batch = self.adapt_schedule_html(
            payload,
            family=family,
            year=year,
            retrieved_at=retrieved_at,
            source_url=source_url,
            calendar_provider="bls_public_calendar",
        )
        artifact = batch.artifacts[0].model_copy(
            update={
                "provider_key": "bls_public_calendar",
                "metadata": {
                    **batch.artifacts[0].metadata,
                    "provider": "bls_public_calendar",
                    "calendar_provider": "bls_public_calendar",
                    "acquisition_transport": "browser_capture",
                    "official_source": True,
                    "manual_user_entry": False,
                }
            }
        )
        quality = batch.quality.model_copy(
            update={
                "source_type": "official_browser_capture",
                "metadata": {
                    **batch.quality.metadata,
                    "calendar_provider": "bls_public_calendar",
                    "acquisition_transport": "browser_capture",
                    "official_source": True,
                    "manual_user_entry": False,
                },
            }
        )
        return batch.model_copy(update={"artifacts": (artifact,), "quality": quality})

    async def healthcheck(self) -> ProviderHealth:
        checked_at = datetime.now(UTC)
        try:
            response = await self._transport.request(
                "POST",
                self.endpoint,
                json_body={
                    "seriesid": ["LNS14000000"],
                    "startyear": str(checked_at.year - 1),
                    "endyear": str(checked_at.year),
                },
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "REQUEST_SUCCEEDED":
                raise ValueError("unexpected BLS status")
        except Exception as exc:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                message=f"BLS request failed: {type(exc).__name__}",
            )
        latency_ms = (datetime.now(UTC) - checked_at).total_seconds() * 1000
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.OK,
            checked_at=datetime.now(UTC),
            latency_ms=latency_ms,
            warnings=[] if self._api_key else ["Using unregistered BLS public rate limits"],
        )
