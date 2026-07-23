"""Practical FRED/ALFRED adapter with normalized records and revision support."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from macro_engine.domain.enums import (
    AvailabilityMethod,
    AvailabilityPrecision,
    ProviderStatus,
)
from macro_engine.domain.models import (
    ObservationRecord,
    ProviderHealth,
    ReleaseRecord,
    SeriesMetadata,
    SeriesSearchResult,
)


class FredAlfredProvider:
    """FRED REST adapter. API keys remain server-side."""

    key = "fred_alfred"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def _request(self, path: str, **parameters: object) -> dict[str, Any]:
        params = {
            "api_key": self._api_key,
            "file_type": "json",
            **{key: str(value) for key, value in parameters.items() if value is not None},
        }
        if self._client is not None:
            response = await self._client.get(f"{self.base_url}/{path}", params=params)
        else:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(f"{self.base_url}/{path}", params=params)
        response.raise_for_status()
        payload = response.json()
        if "error_message" in payload:
            raise RuntimeError(str(payload["error_message"]))
        return dict(payload)

    async def search_series(self, query: str, *, limit: int = 25) -> Sequence[SeriesSearchResult]:
        payload = await self._request("series/search", search_text=query, limit=limit)
        return [
            SeriesSearchResult(
                native_id=str(item["id"]),
                title=str(item["title"]),
                description=item.get("notes"),
                source_url=f"https://fred.stlouisfed.org/series/{item['id']}",
            )
            for item in payload.get("seriess", [])
        ]

    async def fetch_metadata(self, native_id: str) -> SeriesMetadata:
        payload = await self._request("series", series_id=native_id)
        items = payload.get("seriess", [])
        if not items:
            raise LookupError(f"FRED series not found: {native_id}")
        item = items[0]
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
            },
        )

    def fetch_observations(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> AsyncIterator[ObservationRecord]:
        return self._iter_observations(native_id, start=start, end=end)

    async def _iter_observations(
        self,
        native_id: str,
        *,
        start: date | None,
        end: date | None,
    ) -> AsyncIterator[ObservationRecord]:
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
        payload = await self._request("series/observations", **parameters)
        fetched_at = datetime.now(UTC)
        seen_periods: set[date] = set()
        for item in payload.get("observations", []):
            period = date.fromisoformat(str(item["date"]))
            realtime_start = date.fromisoformat(str(item["realtime_start"]))
            realtime_end = date.fromisoformat(str(item["realtime_end"]))
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
            yield ObservationRecord(
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

    async def fetch_vintages(self, native_id: str) -> Sequence[date]:
        payload = await self._request("series/vintagedates", series_id=native_id, limit=100000)
        return [date.fromisoformat(value) for value in payload.get("vintage_dates", [])]

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
        records: list[ReleaseRecord] = []
        for item in payload.get("release_dates", []):
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
                )
            )
        return records

    async def healthcheck(self) -> ProviderHealth:
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
