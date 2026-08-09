"""Small, dependency-free adapters for official public macro endpoints.

The adapters intentionally normalize only the transport boundary.  Catalog
ownership, entity mapping, point-in-time policy and persistence remain in
WorldState.  This keeps a provider outage or schema change from leaking into
the research domain model.
"""

from __future__ import annotations

import csv
import hashlib
import io
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import httpx

from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.macro_core.enums import (
    AvailabilityMethod,
    AvailabilityPrecision,
    ProviderStatus,
)
from worldstate.macro_core.models import (
    ObservationRecord,
    ProviderHealth,
    SeriesMetadata,
)
from worldstate.provider_kit.contracts import (
    ProviderBatch,
    ProviderCapabilities,
    ProviderDomain,
    ProviderRateLimit,
    ProviderRetryPolicy,
    ProviderTerms,
    SourceArtifact,
)
from worldstate.provider_kit.errors import ProviderError, ProviderErrorCode, ProviderSchemaError
from worldstate.provider_kit.transport import HttpProviderTransport


@dataclass(frozen=True, slots=True)
class PublicSeriesSpec:
    native_id: str
    canonical_key: str
    title: str
    entity: str
    frequency: str
    unit: str
    source_url: str
    value_column: str = "OBS_VALUE"
    date_column: str = "TIME_PERIOD"
    endpoint_kind: str = "ecb"


class PublicObservationBatch(ProviderBatch):
    native_id: str
    observations: tuple[ObservationRecord, ...]
    series: PublicSeriesSpec


def _parse_date(value: str) -> date:
    cleaned = value.strip()
    for candidate in (cleaned, cleaned[:10], f"{cleaned}-01"):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%d/%b/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b-%y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unsupported official date: {value!r}")


class OfficialPublicCsvProvider:
    """Provider for official CSV/SDMX-style observation feeds.

    ECB uses SDMX CSV and the Bank of England uses a CSV query endpoint.  BOJ
    and China can use the same adapter when an official export URL is supplied
    in settings, otherwise they remain explicitly unavailable.
    """

    def __init__(
        self,
        *,
        key: str,
        name: str,
        base_url: str,
        terms: ProviderTerms,
        series: tuple[PublicSeriesSpec, ...],
        enabled: bool = True,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        self.key = key
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.terms = terms
        self.series = {item.native_id: item for item in series}
        self._enabled = enabled and bool(self.base_url)
        self._transport = HttpProviderTransport(
            provider_key=key,
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
            domains=(ProviderDomain.MACRO_SERIES,),
            operations=("fetch_metadata", "fetch_observation_batch", "healthcheck"),
            supports_point_in_time=False,
            supports_revisions=True,
            supports_batch=True,
            metadata={"terms_url": self.terms.terms_url, "endpoint_kind": "official_csv"},
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    def _spec(self, native_id: str) -> PublicSeriesSpec:
        try:
            return self.series[native_id]
        except KeyError as exc:
            raise ProviderError(
                self.key, ProviderErrorCode.NOT_FOUND, f"unknown official series: {native_id}"
            ) from exc

    def _request_url_params(
        self, spec: PublicSeriesSpec, start: date | None, end: date | None
    ) -> tuple[str, dict[str, str]]:
        if spec.endpoint_kind == "boe":
            return (
                self.base_url,
                {
                    "csv.x": "yes",
                    "Datefrom": (start or date(1990, 1, 1)).strftime("%d/%b/%Y"),
                    "Dateto": (end or date.today()).strftime("%d/%b/%Y"),
                    "SeriesCodes": spec.native_id,
                    "CSVF": "TN",
                    "UsingCodes": "Y",
                    "VPD": "Y",
                    "VFD": "N",
                },
            )
        url = f"{self.base_url}/{spec.native_id}"
        params = {"format": "csvdata"}
        if start:
            params["startPeriod"] = start.isoformat()
        if end:
            params["endPeriod"] = end.isoformat()
        return url, params

    async def _fetch_csv(
        self, spec: PublicSeriesSpec, *, start: date | None, end: date | None
    ) -> tuple[bytes, str]:
        if not self._enabled:
            raise ProviderError(
                self.key,
                ProviderErrorCode.NOT_CONFIGURED,
                f"{self.name} public endpoint is not configured",
            )
        url, params = self._request_url_params(spec, start, end)
        response = await self._transport.request("GET", url, params=params)
        return response.content, str(response.url)

    async def fetch_metadata(self, native_id: str) -> SeriesMetadata:
        spec = self._spec(native_id)
        return SeriesMetadata(
            native_id=spec.native_id,
            title=spec.title,
            frequency=spec.frequency,
            unit=spec.unit,
            source_url=spec.source_url,
            metadata={"canonical_key": spec.canonical_key, "entity": spec.entity},
        )

    async def fetch_observation_batch(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> PublicObservationBatch:
        spec = self._spec(native_id)
        raw, source_url = await self._fetch_csv(spec, start=start, end=end)
        fetched_at = datetime.now(UTC)
        try:
            text = raw.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(text)))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ProviderSchemaError(
                self.key, "official response was not valid CSV", structure="CSV header + rows"
            ) from exc
        if not rows:
            raise ProviderSchemaError(
                self.key, "official response contained no observation rows", structure="CSV rows"
            )
        records: list[ObservationRecord] = []
        for row in rows:
            date_value = row.get(spec.date_column) or row.get("DATE") or row.get("date")
            value_text = row.get(spec.value_column) or row.get("VALUE") or row.get("value")
            if not date_value:
                continue
            try:
                period = _parse_date(str(date_value))
            except ValueError as exc:
                raise ProviderSchemaError(
                    self.key, "official response contained an invalid date", structure="date column"
                ) from exc
            try:
                value = (
                    None
                    if value_text in (None, "", ".", "NA", "NaN")
                    else Decimal(str(value_text))
                )
            except InvalidOperation:
                value = None
            digest = hashlib.sha256(
                (native_id + "|" + period.isoformat() + "|" + str(value_text)).encode()
            ).hexdigest()
            records.append(
                ObservationRecord(
                    native_id=native_id,
                    period_start=period,
                    period_end=period,
                    value=value,
                    raw_value=str(value_text) if value_text is not None else None,
                    vintage_date=fetched_at.date(),
                    available_at=fetched_at,
                    availability_method=AvailabilityMethod.OFFICIAL_UPDATE_DATE,
                    availability_precision=AvailabilityPrecision.TIMESTAMP,
                    fetched_at=fetched_at,
                    is_preliminary=False,
                    is_revised=False,
                    quality_flags=[] if value is not None else ["missing_value"],
                    source_hash=digest,
                )
            )
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=fetched_at,
            content_type="text/csv",
            content=raw,
            terms=self.terms,
            metadata={"native_id": native_id, "canonical_key": spec.canonical_key},
        )
        quality = DataQuality(
            source_name=self.name,
            source_url=source_url,
            source_type="official_public_csv",
            acquired_at=fetched_at,
            is_verified=True,
            quality_grade=QualityGrade.B,
            metadata={"point_in_time": False, "availability_basis": "provider retrieval timestamp"},
        )
        return PublicObservationBatch(
            provider_key=self.key,
            retrieved_at=fetched_at,
            artifacts=(artifact,),
            quality=quality,
            idempotency_key=hashlib.sha256(
                f"{self.key}:{native_id}:{start}:{end}:{artifact.content_hash}".encode()
            ).hexdigest(),
            native_id=native_id,
            observations=tuple(records),
            series=spec,
        )

    async def healthcheck(self) -> ProviderHealth:
        if not self._enabled or not self.series:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.NOT_CONFIGURED,
                checked_at=datetime.now(UTC),
                message=f"{self.name} endpoint is not configured",
            )
        started = time.perf_counter()
        try:
            await self.fetch_observation_batch(
                next(iter(self.series)), start=date.today(), end=date.today()
            )
        except ProviderError as exc:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                message=exc.message,
            )
        except Exception as exc:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                message=f"{type(exc).__name__}: official response unavailable",
            )
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.OK,
            checked_at=datetime.now(UTC),
            latency_ms=(time.perf_counter() - started) * 1000,
        )


__all__ = ["OfficialPublicCsvProvider", "PublicObservationBatch", "PublicSeriesSpec"]
