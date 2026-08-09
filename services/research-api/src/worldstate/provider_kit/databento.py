"""Databento historical market adapter with mandatory cost and budget gates."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from pydantic import AwareDatetime, Field, model_validator

from worldstate.data_quality import DataQuality, QualityGrade
from worldstate.macro_core.enums import ProviderStatus
from worldstate.macro_core.models import ProviderHealth
from worldstate.provider_kit.contracts import (
    ProviderCapabilities,
    ProviderDomain,
    ProviderModel,
    ProviderRateLimit,
    ProviderRetryPolicy,
    ProviderTerms,
    SourceArtifact,
)
from worldstate.provider_kit.errors import (
    ProviderBudgetError,
    ProviderError,
    ProviderErrorCode,
    ProviderSchemaError,
)
from worldstate.provider_kit.models import BarQuery, MarketBarBatch, MarketBarRecord
from worldstate.provider_kit.transport import HttpProviderTransport


class DatabentoInstrument(ProviderModel):
    root: str
    dataset: str
    venue: str
    continuous_supported: bool = True


DATABENTO_INSTRUMENTS: dict[str, DatabentoInstrument] = {
    "GC": DatabentoInstrument(root="GC", dataset="GLBX.MDP3", venue="COMEX"),
    "SI": DatabentoInstrument(root="SI", dataset="GLBX.MDP3", venue="COMEX"),
    "CL": DatabentoInstrument(root="CL", dataset="GLBX.MDP3", venue="NYMEX"),
    "ES": DatabentoInstrument(root="ES", dataset="GLBX.MDP3", venue="CME Globex"),
    "NQ": DatabentoInstrument(root="NQ", dataset="GLBX.MDP3", venue="CME Globex"),
    "ZT": DatabentoInstrument(root="ZT", dataset="GLBX.MDP3", venue="CBOT"),
    "ZN": DatabentoInstrument(root="ZN", dataset="GLBX.MDP3", venue="CBOT"),
    "DX": DatabentoInstrument(root="DX", dataset="IFUS.IMPACT", venue="ICE Futures US"),
    "VX": DatabentoInstrument(root="VX", dataset="XCBF.PITCH", venue="Cboe Futures Exchange"),
}


class DatabentoContract(ProviderModel):
    root: str
    dataset: str
    venue: str
    continuous_symbol: str
    continuous_rule: Literal["volume", "calendar"]
    raw_symbol: str
    instrument_id: int | None = None
    activation: AwareDatetime | None = None
    expiry: AwareDatetime | None = None
    first_notice: date | None = None
    last_trade: date | None = None
    roll_state: Literal["stable", "near_roll", "rolled", "unknown"] = "unknown"
    resolution_source: str = "databento_symbology"
    metadata: dict[str, object] = Field(default_factory=dict)


class DatabentoSymbologyResolution(ProviderModel):
    contract: DatabentoContract
    artifact: SourceArtifact
    mapping_count: int = Field(ge=1)


class DatabentoDownloadRequest(ProviderModel):
    symbols: tuple[str, ...]
    start: AwareDatetime
    end: AwareDatetime
    schema_name: Literal["ohlcv-1m", "ohlcv-1d"] = Field(
        default="ohlcv-1m",
        alias="schema",
    )
    event_count: int = Field(default=1, ge=1)
    known_record_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range_and_symbols(self) -> DatabentoDownloadRequest:
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        unknown = sorted({symbol.upper() for symbol in self.symbols} - set(DATABENTO_INSTRUMENTS))
        if unknown:
            raise ValueError(f"unsupported Databento roots: {', '.join(unknown)}")
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        return self


class DatabentoCostEstimate(ProviderModel):
    request: DatabentoDownloadRequest
    datasets: tuple[str, ...]
    estimated_records: int = Field(ge=0)
    already_present_records: int = Field(ge=0)
    estimated_billable_bytes: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=0)
    budget_usd: Decimal = Field(ge=0)
    allow_paid_download: bool
    execution_allowed: bool
    source: Literal["provider_metadata", "fallback_estimate"]
    confidence: Literal["high", "low"]
    uncertainty_notes: tuple[str, ...] = ()
    provider_quoted_at: AwareDatetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class DatabentoDedupeMetadata(ProviderModel):
    input_records: int = Field(ge=0)
    duplicate_payload_records: int = Field(ge=0)
    existing_records_skipped: int = Field(ge=0)
    output_records: int = Field(ge=0)
    unique_key: str = "instrument_key,timestamp,interval_seconds,provider_key"


class DatabentoBarBatch(MarketBarBatch):
    dataset: str
    schema_name: Literal["ohlcv-1m", "ohlcv-1d"]
    contract: DatabentoContract
    artifact: SourceArtifact
    dataset_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dedupe: DatabentoDedupeMetadata


def _aware_datetime(value: object) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, int | float):
        divisor = 1_000_000_000 if value > 10_000_000_000_000 else 1
        try:
            return datetime.fromtimestamp(value / divisor, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _date(value: object) -> date | None:
    timestamp = _aware_datetime(value)
    if timestamp is not None:
        return timestamp.date()
    try:
        return date.fromisoformat(str(value)) if value not in {None, ""} else None
    except ValueError:
        return None


def _decimal(value: object, scale: Decimal) -> Decimal:
    try:
        return Decimal(str(value)) * scale
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid price value: {value!r}") from exc


class DatabentoMarketProvider:
    key = "databento"
    base_url = "https://hist.databento.com/v0"
    terms = ProviderTerms(
        license_name="Databento and exchange-licensed market data",
        terms_url="https://databento.com/terms",
        redistribution_allowed=False,
        notes="Exchange entitlements and redistribution restrictions apply per dataset.",
    )

    def __init__(
        self,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        *,
        max_estimated_cost_usd: Decimal = Decimal("0"),
        allow_paid_download: bool = False,
        timeout_seconds: float = 60,
        retry_policy: ProviderRetryPolicy | None = None,
        fallback_usd_per_million_records: Decimal = Decimal("1"),
    ) -> None:
        self._api_key = api_key
        self.max_estimated_cost_usd = max_estimated_cost_usd
        self.allow_paid_download = allow_paid_download
        self._fallback_usd_per_million_records = fallback_usd_per_million_records
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
            domains=(
                ProviderDomain.MARKET_BARS,
                ProviderDomain.MARKET_SYMBOLOGY,
                ProviderDomain.COST_ESTIMATE,
            ),
            operations=(
                "resolve_symbology",
                "estimate_cost",
                "fetch_ohlcv_1m",
                "fetch_ohlcv_1d",
                "healthcheck",
            ),
            supports_point_in_time=True,
            supports_revisions=False,
            supports_batch=True,
            supported_intervals=("ohlcv-1m", "ohlcv-1d"),
            paid_access=True,
            metadata={
                "datasets": sorted({item.dataset for item in DATABENTO_INSTRUMENTS.values()}),
                "venues": {key: item.venue for key, item in DATABENTO_INSTRUMENTS.items()},
                "daily_boundary": "UTC day; not an exchange session close",
                "download_gate": "explicit opt-in and budget ceiling",
                "terms_url": self.terms.terms_url,
                "license_name": self.terms.license_name,
            },
        )

    def get_capabilities(self) -> ProviderCapabilities:
        return self.capabilities

    def _authorization_headers(self) -> dict[str, str]:
        if not self._api_key:
            raise ProviderError(
                self.key,
                ProviderErrorCode.NOT_CONFIGURED,
                "Databento API key is not configured",
            )
        token = base64.b64encode(f"{self._api_key}:".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    @staticmethod
    def continuous_symbol(
        root: str,
        *,
        rank: int = 0,
        rule: Literal["volume", "calendar"] = "volume",
    ) -> str:
        normalized = root.upper()
        if normalized not in DATABENTO_INSTRUMENTS:
            raise ProviderError(
                "databento",
                ProviderErrorCode.UNSUPPORTED,
                f"Databento mapping is not configured for {normalized}",
            )
        if rank < 0:
            raise ProviderError(
                "databento",
                ProviderErrorCode.INVALID_REQUEST,
                "continuous rank cannot be negative",
            )
        infix = "v" if rule == "volume" else "c"
        return f"{normalized}.{infix}.{rank}"

    @staticmethod
    def _mapping_value(record: dict[str, Any], *keys: str) -> object:
        for key in keys:
            if record.get(key) not in {None, ""}:
                return record[key]
        return None

    def resolve_contract(
        self,
        root: str,
        *,
        event_at: AwareDatetime,
        mappings: list[dict[str, Any]],
        rule: Literal["volume", "calendar"] = "volume",
        rank: int = 0,
    ) -> DatabentoContract:
        normalized = root.upper()
        instrument = DATABENTO_INSTRUMENTS.get(normalized)
        if instrument is None:
            raise ProviderError(
                self.key,
                ProviderErrorCode.UNSUPPORTED,
                f"Databento mapping is not configured for {normalized}",
            )
        continuous = self.continuous_symbol(normalized, rank=rank, rule=rule)
        candidates: list[tuple[dict[str, Any], datetime | None, datetime | None]] = []
        for mapping in mappings:
            parent = str(
                self._mapping_value(
                    mapping,
                    "stype_in_symbol",
                    "parent",
                    "continuous_symbol",
                )
                or continuous
            ).upper()
            raw_symbol = str(
                self._mapping_value(mapping, "stype_out_symbol", "raw_symbol", "symbol") or ""
            ).upper()
            if parent != continuous.upper() and not raw_symbol.startswith(normalized):
                continue
            activation = _aware_datetime(
                self._mapping_value(mapping, "start", "activation", "start_ts")
            )
            expiry = _aware_datetime(
                self._mapping_value(mapping, "end", "expiration", "expiry", "end_ts")
            )
            if activation and event_at < activation:
                continue
            if expiry and event_at >= expiry:
                continue
            candidates.append((mapping, activation, expiry))
        if not candidates:
            raise ProviderError(
                self.key,
                ProviderErrorCode.NOT_FOUND,
                f"No active {normalized} contract mapping exists at the event timestamp",
                details={"event_at": event_at.isoformat(), "continuous_symbol": continuous},
            )
        candidates.sort(
            key=lambda part: (
                -float(part[0].get("volume") or 0) if rule == "volume" else 0,
                part[2] or datetime.max.replace(tzinfo=UTC),
                str(self._mapping_value(part[0], "raw_symbol", "symbol") or ""),
            )
        )
        selected, activation, expiry = candidates[0]
        raw_symbol = str(
            self._mapping_value(selected, "stype_out_symbol", "raw_symbol", "symbol") or ""
        )
        if not raw_symbol:
            raise ProviderSchemaError(
                self.key,
                "Databento symbology record omitted the resolved raw symbol",
                structure="stype_out_symbol or raw_symbol",
            )
        days_to_expiry = (expiry - event_at).days if expiry else None
        roll_state: Literal["stable", "near_roll", "rolled", "unknown"] = (
            "near_roll" if days_to_expiry is not None and days_to_expiry <= 5 else "stable"
        )
        return DatabentoContract(
            root=normalized,
            dataset=instrument.dataset,
            venue=instrument.venue,
            continuous_symbol=continuous,
            continuous_rule=rule,
            raw_symbol=raw_symbol,
            instrument_id=(
                int(selected["instrument_id"])
                if str(selected.get("instrument_id") or "").isdigit()
                else None
            ),
            activation=activation,
            expiry=expiry,
            first_notice=_date(selected.get("first_notice")),
            last_trade=_date(selected.get("last_trade")),
            roll_state=roll_state,
            metadata={
                "rank": rank,
                "selection_rule": rule,
                "candidate_count": len(candidates),
                "no_cross_contract_splice": True,
            },
        )

    async def resolve_contract_online(
        self,
        root: str,
        *,
        event_at: AwareDatetime,
        rule: Literal["volume", "calendar"] = "volume",
        rank: int = 0,
    ) -> DatabentoSymbologyResolution:
        """Resolve a continuous symbol and retain the exact provider response."""

        normalized = root.upper()
        instrument = DATABENTO_INSTRUMENTS.get(normalized)
        if instrument is None:
            raise ProviderError(
                self.key,
                ProviderErrorCode.UNSUPPORTED,
                f"Databento mapping is not configured for {normalized}",
            )
        continuous = self.continuous_symbol(normalized, rank=rank, rule=rule)
        response = await self._transport.request(
            "GET",
            f"{self.base_url}/symbology.resolve",
            params={
                "dataset": instrument.dataset,
                "symbols": continuous,
                "stype_in": "continuous",
                "stype_out": "raw_symbol",
                "start_date": event_at.date().isoformat(),
                "end_date": event_at.date().isoformat(),
            },
            headers=self._authorization_headers(),
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderSchemaError(
                self.key,
                "Databento symbology response was not JSON",
                structure="result mapping or mappings[]",
            ) from exc
        mappings: list[dict[str, Any]] = []
        if isinstance(payload, dict) and isinstance(payload.get("mappings"), list):
            mappings = [item for item in payload["mappings"] if isinstance(item, dict)]
        elif isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            result = payload["result"]
            values = result.get(continuous) or result.get(continuous.upper())
            if isinstance(values, list):
                for item in values:
                    if not isinstance(item, dict):
                        continue
                    mappings.append(
                        {
                            **item,
                            "continuous_symbol": continuous,
                            "raw_symbol": item.get("symbol") or item.get("s"),
                            "start": item.get("start") or item.get("start_date") or item.get("d0"),
                            "end": item.get("end") or item.get("end_date") or item.get("d1"),
                        }
                    )
        if not mappings:
            raise ProviderSchemaError(
                self.key,
                "Databento symbology response contained no usable mappings",
                structure="result[continuous][] or mappings[]",
            )
        contract = self.resolve_contract(
            normalized,
            event_at=event_at,
            mappings=mappings,
            rule=rule,
            rank=rank,
        )
        raw = response.content
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=str(response.url),
            retrieved_at=datetime.now(UTC),
            content_type="application/json",
            content=raw,
            terms=self.terms,
            metadata={
                "dataset": instrument.dataset,
                "continuous_symbol": continuous,
                "resolved_symbol": contract.raw_symbol,
                "redistribution_restricted": True,
            },
        )
        return DatabentoSymbologyResolution(
            contract=contract,
            artifact=artifact,
            mapping_count=len(mappings),
        )

    @staticmethod
    def _fallback_dimensions(request: DatabentoDownloadRequest) -> tuple[int, int]:
        seconds = max(0, int((request.end - request.start).total_seconds()))
        intervals = (
            math.ceil(seconds / 60)
            if request.schema_name == "ohlcv-1m"
            else math.ceil(seconds / 86_400)
        )
        gross = intervals * len(request.symbols)
        net = max(0, gross - request.known_record_count)
        return gross, net

    def estimate_cost(
        self,
        request: DatabentoDownloadRequest,
        *,
        provider_cost_usd: Decimal | None = None,
        provider_record_count: int | None = None,
        provider_billable_bytes: int | None = None,
        provider_quoted_at: AwareDatetime | None = None,
    ) -> DatabentoCostEstimate:
        gross, net = self._fallback_dimensions(request)
        already_present = min(gross, request.known_record_count)
        if provider_cost_usd is not None:
            records = max(0, provider_record_count if provider_record_count is not None else net)
            billable_bytes = max(0, provider_billable_bytes or 0)
            cost = max(Decimal("0"), provider_cost_usd)
            source: Literal["provider_metadata", "fallback_estimate"] = "provider_metadata"
            confidence: Literal["high", "low"] = "high"
            notes: tuple[str, ...] = ()
        else:
            records = net
            billable_bytes = records * 64
            cost = (Decimal(records) / Decimal("1000000")) * self._fallback_usd_per_million_records
            source = "fallback_estimate"
            confidence = "low"
            notes = (
                "Provider metadata cost was unavailable; record size and unit cost "
                "are assumptions.",
                "Execution should obtain a fresh provider quote before a paid download.",
            )
        allowed = self.allow_paid_download and cost <= self.max_estimated_cost_usd
        return DatabentoCostEstimate(
            request=request,
            datasets=tuple(
                sorted(
                    {DATABENTO_INSTRUMENTS[symbol.upper()].dataset for symbol in request.symbols}
                )
            ),
            estimated_records=records,
            already_present_records=already_present,
            estimated_billable_bytes=billable_bytes,
            estimated_cost_usd=cost,
            budget_usd=self.max_estimated_cost_usd,
            allow_paid_download=self.allow_paid_download,
            execution_allowed=allowed,
            source=source,
            confidence=confidence,
            uncertainty_notes=notes,
            provider_quoted_at=provider_quoted_at,
            metadata={
                "gross_records_before_dedupe": gross,
                "daily_boundary": "UTC" if request.schema_name == "ohlcv-1d" else None,
            },
        )

    async def estimate_download(
        self,
        request: DatabentoDownloadRequest,
    ) -> DatabentoCostEstimate:
        if not self._api_key:
            # A fallback estimate is still useful in setup mode and performs no
            # paid API request.
            return self.estimate_cost(request)
        datasets = sorted(
            {DATABENTO_INSTRUMENTS[symbol.upper()].dataset for symbol in request.symbols}
        )
        if len(datasets) != 1:
            # Provider quotes are dataset-specific; avoid presenting a partial
            # quote as an authoritative total.
            return self.estimate_cost(request)
        params = {
            "dataset": datasets[0],
            "schema": request.schema_name,
            "symbols": ",".join(request.symbols),
            "stype_in": "continuous",
            "start": request.start.isoformat(),
            "end": request.end.isoformat(),
        }
        try:
            response = await self._transport.request(
                "GET",
                f"{self.base_url}/metadata.get_cost",
                params=params,
                headers=self._authorization_headers(),
            )
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("metadata quote is not an object")
            cost_value = payload.get("cost", payload.get("estimated_cost"))
            if cost_value is None:
                raise ValueError("metadata quote omitted cost")
            cost = Decimal(str(cost_value))
            record_count = payload.get("record_count")
            billable_size = payload.get("billable_size", payload.get("billable_bytes"))
            return self.estimate_cost(
                request,
                provider_cost_usd=cost,
                provider_record_count=(int(record_count) if record_count is not None else None),
                provider_billable_bytes=(int(billable_size) if billable_size is not None else None),
                provider_quoted_at=datetime.now(UTC),
            )
        except (ProviderError, ValueError, InvalidOperation, json.JSONDecodeError):
            return self.estimate_cost(request)

    def assert_download_allowed(self, estimate: DatabentoCostEstimate) -> None:
        if not self.allow_paid_download:
            raise ProviderError(
                self.key,
                ProviderErrorCode.PAID_DOWNLOAD_DISABLED,
                "Databento paid download is disabled; enable it explicitly after reviewing cost",
                details={"estimated_cost_usd": str(estimate.estimated_cost_usd)},
            )
        if estimate.estimated_cost_usd > self.max_estimated_cost_usd:
            raise ProviderBudgetError(
                self.key,
                "Databento estimated cost exceeds the configured budget",
                estimated_cost_usd=str(estimate.estimated_cost_usd),
                budget_usd=str(self.max_estimated_cost_usd),
            )
        if (
            estimate.source != "provider_metadata"
            or estimate.confidence != "high"
            or estimate.provider_quoted_at is None
        ):
            raise ProviderError(
                self.key,
                ProviderErrorCode.COST_ESTIMATE_UNAVAILABLE,
                "Databento paid download requires a fresh provider metadata quote",
                details={
                    "estimate_source": estimate.source,
                    "estimate_confidence": estimate.confidence,
                },
            )

    async def fetch_bars(
        self,
        query: BarQuery,
        *,
        contract: DatabentoContract,
        estimate: DatabentoCostEstimate,
        existing_keys: set[tuple[str, datetime, int]] | None = None,
        price_scale: Decimal = Decimal("1"),
    ) -> DatabentoBarBatch:
        self.assert_download_allowed(estimate)
        if estimate.request.schema_name == "ohlcv-1m" and query.interval_seconds != 60:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "ohlcv-1m requires a 60 second BarQuery interval",
            )
        if estimate.request.schema_name == "ohlcv-1d" and query.interval_seconds != 86_400:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                "ohlcv-1d requires an 86400 second BarQuery interval",
            )
        response = await self._transport.request(
            "GET",
            f"{self.base_url}/timeseries.get_range",
            params={
                "dataset": contract.dataset,
                "schema": estimate.request.schema_name,
                "symbols": contract.raw_symbol,
                "stype_in": "raw_symbol",
                "start": query.start.isoformat(),
                "end": query.end.isoformat(),
                "encoding": "json",
            },
            headers=self._authorization_headers(),
        )
        return self.adapt_bars(
            response.content,
            query=query,
            contract=contract,
            schema=estimate.request.schema_name,
            retrieved_at=datetime.now(UTC),
            source_url=f"{self.base_url}/timeseries.get_range",
            existing_keys=existing_keys,
            price_scale=price_scale,
        )

    def adapt_bars(
        self,
        payload: bytes | str | list[dict[str, Any]] | dict[str, Any],
        *,
        query: BarQuery,
        contract: DatabentoContract,
        schema: Literal["ohlcv-1m", "ohlcv-1d"],
        retrieved_at: AwareDatetime,
        source_url: str,
        existing_keys: set[tuple[str, datetime, int]] | None = None,
        price_scale: Decimal = Decimal("1"),
    ) -> DatabentoBarBatch:
        if isinstance(payload, list | dict):
            document: object = payload
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        else:
            raw = payload.encode() if isinstance(payload, str) else payload
            try:
                document = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProviderSchemaError(
                    self.key,
                    "Databento response was not JSON-normalizable OHLCV",
                    structure="records[] with ts_event/open/high/low/close",
                ) from exc
        rows = document.get("records") if isinstance(document, dict) else document
        if not isinstance(rows, list):
            raise ProviderSchemaError(
                self.key,
                "Databento response omitted the OHLCV records array",
                structure="records[] with ts_event/open/high/low/close",
            )
        interval = 60 if schema == "ohlcv-1m" else 86_400
        if interval != query.interval_seconds:
            raise ProviderError(
                self.key,
                ProviderErrorCode.INVALID_REQUEST,
                f"{schema} does not match the requested interval",
            )
        deduped: dict[tuple[str, datetime, int], MarketBarRecord] = {}
        duplicate_payload = 0
        existing_skipped = 0
        existing = existing_keys or set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            timestamp = _aware_datetime(row.get("ts_event", row.get("timestamp")))
            required = ("open", "high", "low", "close")
            if timestamp is None or any(row.get(key) is None for key in required):
                raise ProviderSchemaError(
                    self.key,
                    "Databento OHLCV record is missing timestamp or prices",
                    structure="ts_event + open + high + low + close",
                )
            if not query.start <= timestamp <= query.end:
                continue
            key = (query.instrument.canonical_key, timestamp, interval)
            if key in existing:
                existing_skipped += 1
                continue
            if key in deduped:
                duplicate_payload += 1
            try:
                deduped[key] = MarketBarRecord(
                    instrument_key=query.instrument.canonical_key,
                    timestamp=timestamp,
                    interval_seconds=interval,
                    open_value=_decimal(row["open"], price_scale),
                    high_value=_decimal(row["high"], price_scale),
                    low_value=_decimal(row["low"], price_scale),
                    close_value=_decimal(row["close"], price_scale),
                    volume=(
                        _decimal(row["volume"], Decimal("1"))
                        if row.get("volume") is not None
                        else None
                    ),
                    source_symbol=str(row.get("symbol") or contract.raw_symbol),
                    contract_code=contract.raw_symbol,
                    metadata={
                        "dataset": contract.dataset,
                        "schema": schema,
                        "instrument_id": row.get("instrument_id", contract.instrument_id),
                        "bar_time_semantics": (
                            "interval_start_utc"
                            if schema == "ohlcv-1m"
                            else "utc_day_not_session_close"
                        ),
                        "price_scale": str(price_scale),
                    },
                )
            except ValueError as exc:
                raise ProviderSchemaError(
                    self.key,
                    "Databento OHLCV values failed validation",
                    structure="valid open/high/low/close/volume",
                ) from exc
        bars = sorted(deduped.values(), key=lambda item: item.timestamp)
        artifact = SourceArtifact.capture(
            provider_key=self.key,
            source_url=source_url,
            retrieved_at=retrieved_at,
            content_type="application/json",
            content=raw,
            terms=self.terms,
            metadata={
                "dataset": contract.dataset,
                "schema": schema,
                "raw_symbol": contract.raw_symbol,
                "redistribution_restricted": True,
            },
        )
        manifest_payload = {
            "artifact_hash": artifact.content_hash,
            "dataset": contract.dataset,
            "schema": schema,
            "raw_symbol": contract.raw_symbol,
            "instrument_id": contract.instrument_id,
            "start": query.start.isoformat(),
            "end": query.end.isoformat(),
            "bar_keys": [
                [bar.instrument_key, bar.timestamp.isoformat(), bar.interval_seconds]
                for bar in bars
            ],
        }
        manifest_hash = hashlib.sha256(
            json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        quality = DataQuality(
            source_name="Databento historical market data",
            source_url=source_url,
            source_type="licensed_market_api",
            acquired_at=retrieved_at,
            is_verified=True,
            is_proxy=query.instrument.is_proxy,
            granularity_seconds=interval,
            missing_reason=None if bars else "provider_returned_no_new_records",
            quality_grade=QualityGrade.A if bars else QualityGrade.C,
            verification_notes=(
                "ohlcv-1d uses Databento UTC-day boundaries, not an exchange session close."
                if schema == "ohlcv-1d"
                else None
            ),
            metadata={
                "dataset": contract.dataset,
                "schema": schema,
                "contract": contract.raw_symbol,
                "roll_state": contract.roll_state,
                "redistribution_restricted": True,
            },
        )
        warnings = (
            ("Daily bars use UTC-day boundaries and are not exchange session-close bars",)
            if schema == "ohlcv-1d"
            else ()
        )
        return DatabentoBarBatch(
            provider_key=self.key,
            instrument=query.instrument,
            bars=bars,
            quality=quality,
            fetched_at=retrieved_at,
            warnings=list(warnings),
            dataset=contract.dataset,
            schema_name=schema,
            contract=contract,
            artifact=artifact,
            dataset_manifest_hash=manifest_hash,
            dedupe=DatabentoDedupeMetadata(
                input_records=len(rows),
                duplicate_payload_records=duplicate_payload,
                existing_records_skipped=existing_skipped,
                output_records=len(bars),
            ),
        )

    async def healthcheck(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.NOT_CONFIGURED,
                checked_at=datetime.now(UTC),
                message="Databento API key is not configured",
            )
        started = datetime.now(UTC)
        try:
            response = await self._transport.request(
                "GET",
                f"{self.base_url}/metadata.list_datasets",
                headers=self._authorization_headers(),
            )
            payload = response.json()
            if not isinstance(payload, list | dict):
                raise ValueError("dataset metadata root is invalid")
        except Exception as exc:
            return ProviderHealth(
                key=self.key,
                status=ProviderStatus.UNAVAILABLE,
                checked_at=datetime.now(UTC),
                message=f"Databento request failed: {type(exc).__name__}",
            )
        warnings = []
        if not self.allow_paid_download:
            warnings.append("Paid downloads are disabled")
        return ProviderHealth(
            key=self.key,
            status=ProviderStatus.OK,
            checked_at=datetime.now(UTC),
            latency_ms=(datetime.now(UTC) - started).total_seconds() * 1000,
            warnings=warnings,
        )
