"""CSV, fixture, and waterfall market-bar providers.

The provider boundary is independently written for WorldState after reviewing
the provider/failover concepts in OpenTerminalUI at commit
fc16fd646405aec7a5525387be89c0cb376137c5.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar, Protocol, runtime_checkable

from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.provider_kit.models import (
    BarQuery,
    MarketBarBatch,
    MarketBarRecord,
)


@runtime_checkable
class MarketBarProvider(Protocol):
    @property
    def key(self) -> str: ...

    async def fetch_bars(self, query: BarQuery) -> MarketBarBatch: ...


def _aware_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit timezone")
    return parsed.astimezone(UTC)


class CsvMarketBarProvider:
    """Read normalized bars from user-controlled CSV text."""

    REQUIRED_COLUMNS: ClassVar[set[str]] = {
        "timestamp",
        "instrument_key",
        "open",
        "high",
        "low",
        "close",
    }

    def __init__(
        self,
        csv_text: str,
        *,
        provider_key: str = "csv",
        source_name: str = "User CSV import",
        source_url: str | None = None,
        acquired_at: datetime | None = None,
        verified: bool = False,
        is_fixture: bool = False,
        verification_notes: str | None = None,
    ) -> None:
        self._csv_text = csv_text
        self._key = provider_key
        self._source_name = source_name
        self._source_url = source_url
        self._acquired_at = (acquired_at or datetime.now(UTC)).astimezone(UTC)
        self._verified = verified
        self._is_fixture = is_fixture
        self._verification_notes = verification_notes

    @property
    def key(self) -> str:
        return self._key

    def _parse(self, query: BarQuery) -> tuple[list[MarketBarRecord], list[str]]:
        reader = csv.DictReader(io.StringIO(self._csv_text))
        columns = set(reader.fieldnames or [])
        missing = sorted(self.REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

        bars: list[MarketBarRecord] = []
        warnings: list[str] = []
        seen: set[datetime] = set()
        for row_number, row in enumerate(reader, start=2):
            if str(row.get("instrument_key") or "").strip() != query.instrument.canonical_key:
                continue
            try:
                timestamp = _aware_timestamp(str(row["timestamp"]))
                if not query.start <= timestamp <= query.end:
                    continue
                if timestamp in seen:
                    warnings.append(f"row {row_number}: duplicate timestamp replaced")
                    bars = [bar for bar in bars if bar.timestamp != timestamp]
                interval = int(row.get("interval_seconds") or query.interval_seconds)
                if interval != query.interval_seconds:
                    continue
                volume_text = str(row.get("volume") or "").strip()
                bars.append(
                    MarketBarRecord(
                        instrument_key=query.instrument.canonical_key,
                        timestamp=timestamp,
                        interval_seconds=interval,
                        open_value=Decimal(str(row["open"])),
                        high_value=Decimal(str(row["high"])),
                        low_value=Decimal(str(row["low"])),
                        close_value=Decimal(str(row["close"])),
                        volume=Decimal(volume_text) if volume_text else None,
                        source_symbol=str(row.get("source_symbol") or query.instrument.symbol),
                        contract_code=str(row.get("contract_code") or "").strip() or None,
                        metadata={"csv_row": row_number},
                    )
                )
                seen.add(timestamp)
            except (InvalidOperation, TypeError, ValueError) as exc:
                warnings.append(f"row {row_number}: {exc}")
        bars.sort(key=lambda item: item.timestamp)
        return bars, warnings

    async def fetch_bars(self, query: BarQuery) -> MarketBarBatch:
        bars, warnings = self._parse(query)
        quality = DataQuality(
            source_name=self._source_name,
            source_url=self._source_url,
            source_type="csv_import",
            acquired_at=self._acquired_at,
            is_manual=True,
            is_verified=self._verified,
            is_fixture=self._is_fixture,
            is_proxy=query.instrument.is_proxy,
            latency_seconds=max(
                0,
                int((self._acquired_at - query.end).total_seconds()),
            ),
            granularity_seconds=query.interval_seconds,
            missing_reason=None if bars else "no_rows_for_instrument_and_window",
            quality_grade=(
                QualityGrade.B if self._verified and not self._is_fixture else QualityGrade.C
            ),
            verification_notes=self._verification_notes,
            metadata={"warnings": len(warnings)},
        )
        return MarketBarBatch(
            provider_key=self.key,
            instrument=query.instrument,
            bars=bars,
            quality=quality,
            fetched_at=self._acquired_at,
            warnings=warnings,
        )


class FixtureMarketBarProvider:
    """Serve deterministic fixture bars without disguising them as live data."""

    def __init__(
        self,
        batches: Mapping[str, Sequence[MarketBarRecord]],
        *,
        source_name: str,
        source_url: str | None = None,
        acquired_at: datetime | None = None,
    ) -> None:
        self._batches = {key: list(value) for key, value in batches.items()}
        self._source_name = source_name
        self._source_url = source_url
        self._acquired_at = (acquired_at or datetime.now(UTC)).astimezone(UTC)

    @property
    def key(self) -> str:
        return "fixture"

    async def fetch_bars(self, query: BarQuery) -> MarketBarBatch:
        bars = [
            bar
            for bar in self._batches.get(query.instrument.canonical_key, [])
            if query.start <= bar.timestamp <= query.end
            and bar.interval_seconds == query.interval_seconds
        ]
        bars.sort(key=lambda item: item.timestamp)
        quality = DataQuality(
            source_name=self._source_name,
            source_url=self._source_url,
            source_type="fixture",
            acquired_at=self._acquired_at,
            is_verified=True,
            is_fixture=True,
            is_proxy=query.instrument.is_proxy,
            latency_seconds=0,
            granularity_seconds=query.interval_seconds,
            missing_reason=None if bars else "fixture_has_no_rows",
            quality_grade=QualityGrade.C,
            verification_notes=(
                "Deterministic research fixture. Shape is illustrative and must not be "
                "presented as exchange-recorded market data."
            ),
        )
        return MarketBarBatch(
            provider_key=self.key,
            instrument=query.instrument,
            bars=bars,
            quality=quality,
            fetched_at=self._acquired_at,
        )


class ProviderWaterfall:
    """Try providers in explicit order and preserve every failed attempt."""

    def __init__(self, providers: Sequence[MarketBarProvider]) -> None:
        self._providers = list(providers)

    async def fetch_bars(self, query: BarQuery) -> MarketBarBatch:
        warnings: list[str] = []
        empty_batch: MarketBarBatch | None = None
        for provider in self._providers:
            try:
                batch = await provider.fetch_bars(query)
            except Exception as exc:
                warnings.append(f"{provider.key}: {type(exc).__name__}: {exc}")
                continue
            if batch.bars:
                return batch.model_copy(update={"warnings": [*warnings, *batch.warnings]})
            warnings.extend(f"{provider.key}: {warning}" for warning in batch.warnings)
            empty_batch = batch
        if empty_batch is not None:
            return empty_batch.model_copy(update={"warnings": warnings})
        raise RuntimeError("no market-bar provider could service the query")
