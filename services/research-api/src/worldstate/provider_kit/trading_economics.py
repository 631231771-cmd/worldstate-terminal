"""Trading Economics calendar adapter used only for consensus and cross-checks."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

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


class TradingEconomicsEntitlement(ProviderModel):
    calendar: bool = True
    historical_point_in_time: bool = False
    reason: str | None = None


class TradingEconomicsQuota(ProviderModel):
    monthly_limit: int | None = Field(default=None, ge=0)
    monthly_used: int = Field(default=0, ge=0)
    remaining: int | None = Field(default=None, ge=0)
    observed_at: AwareDatetime
    warning: str | None = None


class ConsensusSnapshotRecord(ProviderModel):
    calendar_id: str
    ticker: str | None = None
    event: str
    country: str
    reference: str | None = None
    release_at: AwareDatetime
    actual: Decimal | None = None
    previous: Decimal | None = None
    revised: Decimal | None = None
    survey_consensus: Decimal | None = None
    te_forecast: Decimal | None = None
    raw_actual: str | None = None
    raw_previous: str | None = None
    raw_revised: str | None = None
    raw_survey_consensus: str | None = None
    raw_te_forecast: str | None = None
    unit: str | None = None
    importance: int | None = Field(default=None, ge=0)
    provider_updated_at: AwareDatetime | None = None
    captured_at: AwareDatetime
    pit_query_at: AwareDatetime | None = None
    pit_verified: bool = False
    provider_key: str = "trading_economics"
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    license_name: str
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def effective_snapshot_at(self) -> datetime:
        return self.pit_query_at or self.captured_at


class ConsensusCalendarBatch(ProviderBatch):
    snapshots: tuple[ConsensusSnapshotRecord, ...]
    entitlement: TradingEconomicsEntitlement
    quota: TradingEconomicsQuota
    pit_query_at: AwareDatetime | None = None


class TradingEconomicsBrowserPage(ProviderModel):
    source_url: str
    captured_at: AwareDatetime
    html: str = Field(min_length=100)


def _utc_datetime(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Trading Economics Calendar API documents Date as UTC.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decimal(
    value: object,
    *,
    unit: str | None = None,
    normalize_to_thousands: bool = False,
) -> Decimal | None:
    if value in {None, "", ".", "N/A"}:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    suffix = text[-1:].upper()
    if suffix in {"K", "M", "B"}:
        text = text[:-1]
    if normalize_to_thousands:
        multiplier = {
            "K": Decimal("1"),
            "M": Decimal("1000"),
            "B": Decimal("1000000"),
        }.get(suffix)
        if multiplier is None:
            normalized_unit = (unit or "").strip().lower()
            multiplier = Decimal("1") if "thousand" in normalized_unit else Decimal("0.001")
    else:
        multiplier = {
            "K": Decimal("1000"),
            "M": Decimal("1000000"),
            "B": Decimal("1000000000"),
        }.get(suffix, Decimal("1"))
    try:
        return Decimal(text) * multiplier
    except InvalidOperation:
        return None


class TradingEconomicsConsensusProvider:
    """Batch calendar/PIT snapshot provider.

    ``Forecast`` is normalized as survey consensus. ``TEForecast`` remains a
    separate proprietary forecast and is never substituted for consensus.
    """

    key = "trading_economics"
    base_url = "https://api.tradingeconomics.com"
    terms = ProviderTerms(
        license_name="Trading Economics subscription data",
        terms_url="https://tradingeconomics.com/analytics/pricing.aspx",
        redistribution_allowed=False,
        notes="Entitlement and redistribution terms depend on the account plan.",
    )

    def __init__(
        self,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        *,
        pit_entitled: bool = False,
        monthly_quota: int | None = None,
        monthly_requests_used: int = 0,
        timeout_seconds: float = 30,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        self._api_key = api_key
        self._pit_entitled = pit_entitled
        self._monthly_quota = monthly_quota
        self._monthly_requests_used = monthly_requests_used
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
    def entitlement(self) -> TradingEconomicsEntitlement:
        return TradingEconomicsEntitlement(
            calendar=bool(self._api_key),
            historical_point_in_time=self._pit_entitled,
            reason=None if self._pit_entitled else "Historical PIT access not confirmed",
        )

    @property
    def quota(self) -> TradingEconomicsQuota:
        remaining = (
            max(0, self._monthly_quota - self._monthly_requests_used)
            if self._monthly_quota is not None
            else None
        )
        warning = None
        if (
            remaining is not None
            and self._monthly_quota
            and remaining <= max(1, int(self._monthly_quota * 0.1))
        ):
            warning = "Trading Economics monthly request quota is nearly exhausted"
        return TradingEconomicsQuota(
            monthly_limit=self._monthly_quota,
            monthly_used=self._monthly_requests_used,
            remaining=remaining,
            observed_at=datetime.now(UTC),
            warning=warning,
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_key=self.key,
            domains=(ProviderDomain.CONSENSUS, ProviderDomain.EVENT_CALENDAR),
            operations=("fetch_calendar_batch", "fetch_pit_calendar", "healthcheck"),
            supports_point_in_time=self._pit_entitled,
            supports_revisions=True,
            supports_batch=True,
            paid_access=True,
            metadata={
                "survey_field": "Forecast",
                "proprietary_field": "TEForecast",
                "actual_usage": "official_source_cross_check_only",
                "terms_url": self.terms.terms_url,
                "license_name": self.terms.license_name,
            },
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    def _check_request_allowed(self, *, pit: bool) -> None:
        if not self._api_key:
            raise ProviderError(
                self.key,
                ProviderErrorCode.NOT_CONFIGURED,
                "Trading Economics API key is not configured",
            )
        if pit and not self._pit_entitled:
            raise ProviderError(
                self.key,
                ProviderErrorCode.ENTITLEMENT,
                "Trading Economics historical PIT entitlement is not available",
            )
        if self._monthly_quota is not None and self._monthly_requests_used >= self._monthly_quota:
            raise ProviderError(
                self.key,
                ProviderErrorCode.QUOTA_EXHAUSTED,
                "Trading Economics monthly request quota is exhausted",
                details={
                    "monthly_limit": self._monthly_quota,
                    "monthly_used": self._monthly_requests_used,
                },
            )

    async def fetch_calendar(
        self,
        *,
        start: date,
        end: date,
        pit_at: AwareDatetime | None = None,
    ) -> ConsensusCalendarBatch:
        if start > end:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "calendar start cannot be later than end",
            )
        self._check_request_allowed(pit=pit_at is not None)
        path = f"/calendar/country/united states/{start.isoformat()}/{end.isoformat()}"
        params: dict[str, str] = {}
        if pit_at is not None:
            # TE's PIT query time remains distinct from the local retrieval time.
            params["time"] = pit_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        response = await self._transport.request(
            "GET",
            f"{self.base_url}{path}",
            params=params,
            headers={"Authorization": f"Client {self._api_key}"},
        )
        self._monthly_requests_used += 1
        return self.adapt_calendar(
            response.content,
            captured_at=datetime.now(UTC),
            source_url=f"{self.base_url}{path}",
            pit_query_at=pit_at,
        )

    def adapt_calendar(
        self,
        payload: bytes | str | list[dict[str, Any]],
        *,
        captured_at: AwareDatetime,
        source_url: str,
        pit_query_at: AwareDatetime | None = None,
    ) -> ConsensusCalendarBatch:
        if pit_query_at is not None and not self._pit_entitled:
            raise ProviderError(
                self.key,
                ProviderErrorCode.ENTITLEMENT,
                "Historical PIT payload cannot be accepted without confirmed entitlement",
            )
        if isinstance(payload, list):
            rows: object = payload
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        else:
            raw = payload.encode() if isinstance(payload, str) else payload
            try:
                rows = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderSchemaError(
                    self.key,
                    "Trading Economics response was not valid JSON",
                    structure="calendar event array",
                ) from exc
        if not isinstance(rows, list):
            raise ProviderSchemaError(
                self.key,
                "Trading Economics calendar response was not an array",
                structure="calendar event array",
            )
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=captured_at,
            content_type="application/json",
            content=raw,
            terms=self.terms,
            metadata={
                "pit_query_at": pit_query_at.isoformat() if pit_query_at else None,
                "redistribution_restricted": True,
            },
        )
        snapshots: list[ConsensusSnapshotRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            release_at = _utc_datetime(row.get("Date"))
            event = str(row.get("Event") or "").strip()
            calendar_id = str(row.get("CalendarId") or row.get("CalendarID") or "").strip()
            if release_at is None or not event or not calendar_id:
                raise ProviderSchemaError(
                    self.key,
                    "Trading Economics event is missing CalendarId, Event, or UTC Date",
                    structure="CalendarId + Event + Date",
                )
            forecast_raw = row.get("Forecast")
            te_forecast_raw = row.get("TEForecast")
            unit = str(row.get("Unit") or "").strip() or None
            event_identity = f"{event} {row.get('Ticker') or ''}".lower()
            normalize_to_thousands = any(
                marker in event_identity for marker in ("nonfarm", "non farm", "payroll")
            )
            snapshots.append(
                ConsensusSnapshotRecord(
                    calendar_id=calendar_id,
                    ticker=str(row.get("Ticker") or "").strip() or None,
                    event=event,
                    country=str(row.get("Country") or "United States"),
                    reference=str(row.get("Reference") or "").strip() or None,
                    release_at=release_at,
                    actual=_decimal(
                        row.get("Actual"),
                        unit=unit,
                        normalize_to_thousands=normalize_to_thousands,
                    ),
                    previous=_decimal(
                        row.get("Previous"),
                        unit=unit,
                        normalize_to_thousands=normalize_to_thousands,
                    ),
                    revised=_decimal(
                        row.get("Revised"),
                        unit=unit,
                        normalize_to_thousands=normalize_to_thousands,
                    ),
                    survey_consensus=_decimal(
                        forecast_raw,
                        unit=unit,
                        normalize_to_thousands=normalize_to_thousands,
                    ),
                    te_forecast=_decimal(
                        te_forecast_raw,
                        unit=unit,
                        normalize_to_thousands=normalize_to_thousands,
                    ),
                    raw_actual=str(row.get("Actual")) if row.get("Actual") is not None else None,
                    raw_previous=(
                        str(row.get("Previous")) if row.get("Previous") is not None else None
                    ),
                    raw_revised=(
                        str(row.get("Revised")) if row.get("Revised") is not None else None
                    ),
                    raw_survey_consensus=(
                        str(forecast_raw) if forecast_raw not in {None, ""} else None
                    ),
                    raw_te_forecast=(
                        str(te_forecast_raw) if te_forecast_raw not in {None, ""} else None
                    ),
                    unit="thousand persons" if normalize_to_thousands else unit,
                    importance=(
                        int(row["Importance"])
                        if str(row.get("Importance") or "").isdigit()
                        else None
                    ),
                    provider_updated_at=_utc_datetime(row.get("LastUpdate")),
                    captured_at=captured_at,
                    pit_query_at=pit_query_at,
                    pit_verified=pit_query_at is not None and self._pit_entitled,
                    artifact_hash=artifact.content_hash,
                    license_name=self.terms.license_name,
                    metadata={
                        "actual_authority": "cross_check_only",
                        "consensus_field": "Forecast",
                        "te_forecast_field": "TEForecast",
                        "raw_provider_unit": unit,
                        "normalization": (
                            "payroll_values_to_thousand_persons"
                            if normalize_to_thousands
                            else "numeric_value_without_display_suffix"
                        ),
                    },
                )
            )
        quality = DataQuality(
            source_name="Trading Economics Economic Calendar API",
            source_url=source_url,
            source_type="licensed_api",
            acquired_at=captured_at,
            is_verified=pit_query_at is not None and self._pit_entitled,
            quality_grade=(
                QualityGrade.B
                if pit_query_at is not None and self._pit_entitled
                else QualityGrade.C
            ),
            metadata={
                "pit_available": self._pit_entitled,
                "redistribution_restricted": True,
                "actual_is_authoritative": False,
            },
        )
        quota = self.quota
        return ConsensusCalendarBatch(
            provider_key=self.key,
            retrieved_at=captured_at,
            artifacts=(artifact,),
            quality=quality,
            warnings=(quota.warning,) if quota.warning else (),
            idempotency_key=hashlib.sha256(
                f"te-calendar:{artifact.content_hash}:{pit_query_at}".encode()
            ).hexdigest(),
            snapshots=tuple(snapshots),
            entitlement=self.entitlement,
            quota=quota,
            pit_query_at=pit_query_at,
        )

    def adapt_browser_calendar(
        self,
        rows: list[dict[str, Any]],
        *,
        pages: tuple[TradingEconomicsBrowserPage, ...],
    ) -> ConsensusCalendarBatch:
        """Normalize rows read from visible Trading Economics pages."""

        if not pages or any(
            not page.source_url.startswith("https://tradingeconomics.com/")
            for page in pages
        ):
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "browser consensus capture must use Trading Economics pages",
            )
        base = self.adapt_calendar(
            rows,
            captured_at=max(page.captured_at for page in pages),
            source_url=pages[0].source_url,
        )
        raw = json.dumps(
            {
                "pages": [
                    {
                        "source_url": page.source_url,
                        "captured_at": page.captured_at.isoformat(),
                        "html": page.html,
                    }
                    for page in pages
                ],
                "rows": rows,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        captured_at = max(page.captured_at for page in pages)
        artifact = base.artifacts[0].model_copy(
            update={
                "source_url": "https://tradingeconomics.com/united-states/inflation-cpi",
                "content_type": "application/json+browser-capture",
                "content": raw,
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "byte_length": len(raw),
                "retrieved_at": captured_at,
                "metadata": {
                    **base.artifacts[0].metadata,
                    "acquisition_transport": "browser_capture",
                    "official_source": False,
                    "manual_user_entry": False,
                    "page_urls": [page.source_url for page in pages],
                    "forecast_semantics": (
                        "Forecast=survey_consensus; TEForecast=proprietary_forecast"
                    ),
                },
            }
        )
        quality = base.quality.model_copy(
            update={
                "source_type": "licensed_browser_capture",
                "acquired_at": captured_at,
                "metadata": {
                    **base.quality.metadata,
                    "acquisition_transport": "browser_capture",
                    "official_source": False,
                    "manual_user_entry": False,
                    "forecast_semantics": (
                        "Forecast=survey_consensus; TEForecast=proprietary_forecast"
                    ),
                },
            }
        )
        return base.model_copy(update={"artifacts": (artifact,), "quality": quality})

    @staticmethod
    def select_last_pre_release_snapshot(
        snapshots: list[ConsensusSnapshotRecord] | tuple[ConsensusSnapshotRecord, ...],
        *,
        release_at: AwareDatetime,
        calendar_id: str | None = None,
    ) -> ConsensusSnapshotRecord | None:
        eligible = [
            snapshot
            for snapshot in snapshots
            if snapshot.effective_snapshot_at < release_at
            and snapshot.survey_consensus is not None
            and (calendar_id is None or snapshot.calendar_id == calendar_id)
        ]
        return max(eligible, key=lambda item: item.effective_snapshot_at) if eligible else None

    async def healthcheck(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.NOT_CONFIGURED,
                checked_at=datetime.now(UTC),
                message="Trading Economics API key is not configured",
            )
        warnings = [self.quota.warning] if self.quota.warning else []
        warnings.append(
            "Quota-free configuration check only; a successful calendar synchronization "
            "is required for live-health evidence"
        )
        if not self._pit_entitled:
            warnings.append("Historical PIT entitlement is not confirmed")
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.DEGRADED,
            checked_at=datetime.now(UTC),
            message="Trading Economics credential is configured but not probed",
            warnings=warnings,
        )
