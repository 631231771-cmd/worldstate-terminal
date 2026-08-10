"""FRED/ALFRED adapter with explicit series-vintage point-in-time semantics."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

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
    ReleaseRecord,
    SeriesMetadata,
    SeriesSearchResult,
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


class FredObservationBatch(ProviderBatch):
    native_id: str
    observations: tuple[ObservationRecord, ...]
    as_of: date | None = None


class FredAlfredProvider:
    """FRED REST adapter. Provider response models never cross this boundary."""

    key = "fred_alfred"
    base_url = "https://api.stlouisfed.org/fred"
    public_csv_base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    terms = ProviderTerms(
        license_name="FRED/ALFRED terms of use; underlying series terms vary",
        terms_url="https://fred.stlouisfed.org/legal/",
        redistribution_allowed=False,
        notes="Check the source and copyright notes for every underlying series.",
    )

    def __init__(
        self,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 30,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        self._api_key = api_key
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
            domains=(ProviderDomain.MACRO_SERIES, ProviderDomain.EVENT_CALENDAR),
            operations=(
                "search_series",
                "fetch_metadata",
                "fetch_observations",
                "fetch_observation_batch",
                "fetch_vintages",
                "fetch_releases",
                "healthcheck",
            ),
            supports_point_in_time=True,
            supports_revisions=True,
            supports_batch=True,
            paid_access=False,
            metadata={
                "vintage_source": "ALFRED realtime_start/realtime_end",
                "availability_precision": "day",
                "terms_url": self.terms.terms_url,
                "license_name": self.terms.license_name,
                "public_current_csv": True,
                "public_current_csv_url": self.public_csv_base_url,
            },
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    async def _request_raw(
        self,
        path: str,
        **parameters: object,
    ) -> tuple[dict[str, Any], bytes, str]:
        if not self._api_key:
            raise ProviderError(
                self.key,
                ProviderErrorCode.NOT_CONFIGURED,
                "FRED API key is not configured",
            )
        params = {
            "api_key": self._api_key,
            "file_type": "json",
            **{key: str(value) for key, value in parameters.items() if value is not None},
        }
        clean_url = f"{self.base_url}/{path}"
        response = await self._transport.request("GET", clean_url, params=params)
        raw = response.content
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderSchemaError(
                self.key,
                "FRED response was not valid JSON",
                structure="FRED JSON object",
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderSchemaError(
                self.key,
                "FRED response root was not an object",
                structure="FRED JSON object",
            )
        if "error_message" in payload:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "FRED rejected the request",
                details={"error_code": payload.get("error_code")},
            )
        return dict(payload), raw, clean_url

    async def _request(self, path: str, **parameters: object) -> dict[str, Any]:
        """Compatibility helper retained for callers that only need normalized JSON."""

        payload, _, _ = await self._request_raw(path, **parameters)
        return payload

    async def search_series(self, query: str, *, limit: int = 25) -> Sequence[SeriesSearchResult]:
        payload = await self._request("series/search", search_text=query, limit=limit)
        rows = payload.get("seriess")
        if not isinstance(rows, list):
            raise ProviderSchemaError(
                self.key,
                "FRED search response omitted seriess",
                structure="seriess[]",
            )
        return [
            SeriesSearchResult(
                native_id=str(item["id"]),
                title=str(item["title"]),
                description=item.get("notes"),
                source_url=f"https://fred.stlouisfed.org/series/{item['id']}",
            )
            for item in rows
            if isinstance(item, dict) and item.get("id") and item.get("title")
        ]

    async def fetch_metadata(self, native_id: str) -> SeriesMetadata:
        payload = await self._request("series", series_id=native_id)
        items = payload.get("seriess")
        if not isinstance(items, list):
            raise ProviderSchemaError(
                self.key,
                "FRED series response omitted seriess",
                structure="seriess[]",
            )
        if not items:
            raise ProviderError(
                self.key,
                ProviderErrorCode.NOT_FOUND,
                f"FRED series was not found: {native_id}",
            )
        item = items[0]
        if not isinstance(item, dict):
            raise ProviderSchemaError(
                self.key,
                "FRED series metadata was not an object",
                structure="seriess[0] object",
            )
        return SeriesMetadata(
            native_id=native_id,
            title=str(item["title"]),
            description=item.get("notes"),
            frequency=str(item.get("frequency_short") or item.get("frequency") or "unknown"),
            unit=str(item.get("units_short") or item.get("units") or "value"),
            seasonal_adjustment=item.get("seasonal_adjustment"),
            source_url=f"https://fred.stlouisfed.org/series/{native_id}",
            metadata={
                "last_updated": item.get("last_updated"),
                "popularity": item.get("popularity"),
                "observation_start": item.get("observation_start"),
                "observation_end": item.get("observation_end"),
                "underlying_series_terms_must_be_checked": True,
            },
        )

    def fetch_observations(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        as_of: date | None = None,
    ) -> AsyncIterator[ObservationRecord]:
        return self._iter_observations(native_id, start=start, end=end, as_of=as_of)

    async def _iter_observations(
        self,
        native_id: str,
        *,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> AsyncIterator[ObservationRecord]:
        batch = await self.fetch_observation_batch(
            native_id,
            start=start,
            end=end,
            as_of=as_of,
        )
        for observation in batch.observations:
            yield observation

    async def fetch_observation_batch(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        as_of: date | None = None,
    ) -> FredObservationBatch:
        if self._api_key is None:
            if as_of is not None:
                raise ProviderError(
                    self.key,
                    ProviderErrorCode.POINT_IN_TIME,
                    "public FRED CSV does not provide point-in-time vintages",
                )
            return await self.fetch_public_current_batch(
                native_id,
                start=start,
                end=end,
            )
        if start and end and start > end:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "observation start cannot be later than end",
            )
        if as_of and as_of > datetime.now(UTC).date():
            raise ProviderError(
                self.key,
                ProviderErrorCode.POINT_IN_TIME,
                "FRED point-in-time cutoff cannot be in the future",
            )
        parameters: dict[str, object] = {
            "series_id": native_id,
            "output_type": 2,
            "limit": 100000,
            "sort_order": "asc",
        }
        if start is not None:
            parameters["observation_start"] = start.isoformat()
        if end is not None:
            parameters["observation_end"] = end.isoformat()
        if as_of is not None:
            parameters["realtime_start"] = "1776-07-04"
            parameters["realtime_end"] = as_of.isoformat()
        payload, raw, source_url = await self._request_raw(
            "series/observations",
            **parameters,
        )
        fetched_at = datetime.now(UTC)
        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise ProviderSchemaError(
                self.key,
                "FRED observations response omitted observations",
                structure="observations[]",
            )
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=fetched_at,
            content_type="application/json",
            content=raw,
            terms=self.terms,
            metadata={"native_id": native_id, "as_of": as_of.isoformat() if as_of else None},
        )
        records: list[ObservationRecord] = []
        seen_periods: set[date] = set()
        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                period = date.fromisoformat(str(item["date"]))
                realtime_start = date.fromisoformat(str(item["realtime_start"]))
                realtime_end = date.fromisoformat(str(item["realtime_end"]))
            except (KeyError, ValueError) as exc:
                raise ProviderSchemaError(
                    self.key,
                    "FRED observation lacks date/realtime vintage fields",
                    structure="date + realtime_start + realtime_end",
                ) from exc
            if as_of is not None and realtime_start > as_of:
                # Defensive enforcement even if the provider ignored the query.
                continue
            raw_value = str(item.get("value", "."))
            try:
                value = None if raw_value in {".", "", "NaN"} else Decimal(raw_value)
            except InvalidOperation:
                value = None
            digest = hashlib.sha256(
                json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            is_revised = period in seen_periods
            seen_periods.add(period)
            records.append(
                ObservationRecord(
                    native_id=native_id,
                    period_start=period,
                    period_end=period,
                    value=value,
                    raw_value=raw_value,
                    vintage_date=realtime_start,
                    realtime_start=realtime_start,
                    realtime_end=realtime_end,
                    available_at=datetime.combine(realtime_start, datetime.min.time(), UTC),
                    availability_method=AvailabilityMethod.PROVIDER_REALTIME_START,
                    availability_precision=AvailabilityPrecision.DAY,
                    fetched_at=fetched_at,
                    is_revised=is_revised,
                    quality_flags=[] if value is not None else ["missing_value"],
                    source_hash=digest,
                )
            )
        quality = DataQuality(
            source_name="Federal Reserve Bank of St. Louis FRED/ALFRED",
            source_url=source_url,
            source_type="official_or_licensed_series_api",
            acquired_at=fetched_at,
            is_verified=as_of is not None,
            quality_grade=QualityGrade.A if as_of is not None else QualityGrade.B,
            metadata={
                "native_id": native_id,
                "point_in_time_cutoff": as_of.isoformat() if as_of else None,
                "availability_precision": "day",
                "underlying_series_terms_must_be_checked": True,
            },
        )
        return FredObservationBatch(
            provider_key=self.key,
            retrieved_at=fetched_at,
            artifacts=(artifact,),
            quality=quality,
            idempotency_key=hashlib.sha256(
                f"fred:{native_id}:{as_of}:{artifact.content_hash}".encode()
            ).hexdigest(),
            native_id=native_id,
            observations=tuple(records),
            as_of=as_of,
        )

    async def fetch_public_current_batch(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> FredObservationBatch:
        """Fetch the current public FRED graph CSV without a credential.

        The graph export is a current-state convenience path.  It deliberately
        does not claim ALFRED vintages: every accepted row receives the fetch
        date as its observation vintage and is marked with an ingestion-time
        availability boundary.  A configured API key continues to use the
        point-in-time REST path above.
        """

        if start and end and start > end:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "observation start cannot be later than end",
            )
        source_url = f"{self.public_csv_base_url}?id={native_id}"
        response = await self._transport.request(
            "GET",
            self.public_csv_base_url,
            params={"id": native_id},
            headers={"Accept": "text/csv"},
        )
        raw = response.content
        fetched_at = datetime.now(UTC)
        try:
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            fieldnames = reader.fieldnames or []
            value_column = next(
                (name for name in fieldnames if name != "observation_date"),
                None,
            )
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ProviderSchemaError(
                self.key,
                "public FRED response was not valid CSV",
                structure="observation_date + value",
            ) from exc
        if (
            not rows
            or "observation_date" not in fieldnames
            or value_column is None
        ):
            raise ProviderSchemaError(
                self.key,
                "public FRED CSV omitted observation columns",
                structure="observation_date + value",
            )
        records: list[ObservationRecord] = []
        for row in rows:
            try:
                period = date.fromisoformat(str(row.get("observation_date") or ""))
            except ValueError as exc:
                raise ProviderSchemaError(
                    self.key,
                    "public FRED observation has an invalid date",
                    structure="YYYY-MM-DD observation_date",
                ) from exc
            if start is not None and period < start:
                continue
            if end is not None and period > end:
                continue
            raw_value = str(row.get(value_column) or ".")
            try:
                value = None if raw_value in {".", "", "NaN"} else Decimal(raw_value)
            except InvalidOperation:
                value = None
            digest = hashlib.sha256(
                f"{native_id}|{period.isoformat()}|{raw_value}".encode()
            ).hexdigest()
            records.append(
                ObservationRecord(
                    native_id=native_id,
                    period_start=period,
                    period_end=period,
                    value=value,
                    raw_value=raw_value,
                    vintage_date=fetched_at.date(),
                    realtime_start=None,
                    realtime_end=None,
                    available_at=fetched_at,
                    availability_method=AvailabilityMethod.INGESTION_TIME_PROXY,
                    availability_precision=AvailabilityPrecision.TIMESTAMP,
                    fetched_at=fetched_at,
                    is_revised=False,
                    quality_flags=["current_public_csv", "not_point_in_time"]
                    + (["missing_value"] if value is None else []),
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
            metadata={
                "native_id": native_id,
                "source_mode": "current_public_csv",
                "point_in_time": False,
                "observation_vintage": fetched_at.date().isoformat(),
            },
        )
        quality = DataQuality(
            source_name="Federal Reserve Bank of St. Louis FRED public graph CSV",
            source_url=source_url,
            source_type="official_public_current_csv",
            acquired_at=fetched_at,
            is_verified=False,
            quality_grade=QualityGrade.B,
            verification_notes=(
                "Current public graph export; no ALFRED realtime vintage or first-print history."
            ),
            metadata={
                "native_id": native_id,
                "point_in_time": False,
                "current_observation_only": True,
            },
        )
        return FredObservationBatch(
            provider_key=self.key,
            retrieved_at=fetched_at,
            artifacts=(artifact,),
            quality=quality,
            idempotency_key=hashlib.sha256(
                f"fred-public:{native_id}:{artifact.content_hash}".encode()
            ).hexdigest(),
            native_id=native_id,
            observations=tuple(records),
            as_of=None,
        )

    async def fetch_vintages(
        self,
        native_id: str,
        *,
        as_of: date | None = None,
    ) -> Sequence[date]:
        payload = await self._request("series/vintagedates", series_id=native_id, limit=100000)
        values = payload.get("vintage_dates")
        if not isinstance(values, list):
            raise ProviderSchemaError(
                self.key,
                "FRED vintage response omitted vintage_dates",
                structure="vintage_dates[]",
            )
        vintages = [date.fromisoformat(str(value)) for value in values]
        return [value for value in vintages if as_of is None or value <= as_of]

    async def fetch_releases(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Sequence[ReleaseRecord]:
        parameters: dict[str, object] = {"include_release_dates_with_no_data": "false"}
        if start:
            parameters["realtime_start"] = start.isoformat()
        if end:
            parameters["realtime_end"] = end.isoformat()
        payload = await self._request("releases/dates", **parameters)
        rows = payload.get("release_dates")
        if not isinstance(rows, list):
            raise ProviderSchemaError(
                self.key,
                "FRED release response omitted release_dates",
                structure="release_dates[]",
            )
        records: list[ReleaseRecord] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            release_date = date.fromisoformat(str(item["date"]))
            records.append(
                ReleaseRecord(
                    native_id=str(item["release_id"]),
                    name=str(item["release_name"]),
                    scheduled_at=datetime.combine(release_date, datetime.min.time(), UTC),
                    source_timezone="America/Chicago",
                    status="scheduled",
                    importance=1,
                    source_url=f"https://fred.stlouisfed.org/release?rid={item['release_id']}",
                    metadata={"date_precision_only": True},
                )
            )
        return records

    async def healthcheck(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.DEGRADED,
                checked_at=datetime.now(UTC),
                message="FRED API key is not configured; public current CSV is available",
                warnings=[
                    "Public graph CSV has no ALFRED point-in-time vintages; use a key for PIT sync."
                ],
            )
        started = datetime.now(UTC)
        try:
            await self._request("series", series_id="DFF")
        except Exception as exc:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                message=f"FRED request failed: {type(exc).__name__}",
            )
        elapsed = (datetime.now(UTC) - started).total_seconds() * 1000
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.OK,
            checked_at=datetime.now(UTC),
            latency_ms=elapsed,
        )
