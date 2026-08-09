"""Safe data-foundation status and bounded backfill API.

Browser requests can estimate or enqueue work, but paid downloads are executed
only by the durable background worker after it repeats every cost gate.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.api.v2.schemas import BackfillRequestInput
from worldstate.application.analysis_orchestrator import select_analysis_inputs_from_rows
from worldstate.application.backfill_service import (
    BackfillEstimate,
    BackfillRequest,
    cancel_backfill_job,
    create_backfill_job,
    estimate_backfill,
    get_backfill_job,
    make_backfill_idempotency_key,
)
from worldstate.application.data_foundation_service import get_provider_data_status
from worldstate.application.licensed_sync_service import (
    snapshot_trading_economics_consensus,
    sync_databento_release_market,
)
from worldstate.application.official_sync_service import (
    sync_bls_calendar,
    sync_fomc_materials,
    sync_official_data,
)
from worldstate.application.provider_runtime import (
    build_provider_clients,
    provider_health_snapshot,
)
from worldstate.application.reconciliation_service import reconcile_persisted_data
from worldstate.config import Settings
from worldstate.db.models import (
    BackfillJob,
    CalendarSnapshot,
    ConsensusSnapshot,
    DataQualityRecord,
    DataReconciliationRecord,
    MacroRelease,
    MarketDataManifest,
    Observation,
    Provider,
    ProviderRun,
    ReleaseValue,
    Series,
    SourceArtifact,
    SyncJob,
    SyncJobRun,
)
from worldstate.macro_core.errors import MacroEngineError
from worldstate.provider_kit import DatabentoDownloadRequest

data_router = APIRouter(prefix="/data", tags=["data"])
data_write_router = APIRouter(prefix="/data", tags=["data"])

AssetRoot = Literal["GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX"]


def _default_asset_roots() -> list[AssetRoot]:
    return ["GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX"]


class DataRangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_range(self) -> DataRangeInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class ConsensusSyncInput(DataRangeInput):
    pit_at: AwareDatetime | None = None


class MarketSyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: uuid.UUID
    assets: list[AssetRoot] = Field(default_factory=_default_asset_roots)
    include_daily: bool = True


class ReconcileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: uuid.UUID | None = None


EVENT_TITLES = {
    "US_CPI": "US CPI",
    "US_NFP": "US Nonfarm Payrolls",
    "FOMC": "Federal Open Market Committee",
}
DEFAULT_EVENT_TYPES = tuple(EVENT_TITLES)
DEFAULT_ASSETS = ("GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX")
DEFAULT_SCHEMAS = ("ohlcv-1m", "ohlcv-1d")
DATA_OPERATION_STATUS_CONTRACT: dict[str, dict[str, object]] = {
    "completed": {
        "http_status": 200,
        "cli_exit_code": 0,
        "meaning": "The requested operation completed without a known provider failure.",
    },
    "partial": {
        "http_status": 207,
        "cli_exit_code": 4,
        "meaning": "At least one independent source completed and at least one failed.",
    },
    "blocked": {
        "http_status": 424,
        "cli_exit_code": 3,
        "meaning": (
            "A required upstream dependency, entitlement, paid-data guard, or persisted "
            "input is unavailable."
        ),
    },
    "invalid_request": {
        "http_status": 422,
        "cli_exit_code": 2,
        "meaning": "The request is invalid; missing resources may instead return HTTP 404.",
    },
}
DATASET_BY_ASSET = {
    "GC": "GLBX.MDP3",
    "SI": "GLBX.MDP3",
    "CL": "GLBX.MDP3",
    "ES": "GLBX.MDP3",
    "NQ": "GLBX.MDP3",
    "ZT": "GLBX.MDP3",
    "ZN": "GLBX.MDP3",
    "DX": "IFUS.IMPACT",
    "VX": "XCBF.PITCH",
}

_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "provider_id": "fred_alfred",
        "display_name": "FRED / ALFRED",
        "aliases": ("fred_alfred", "fred", "alfred"),
        "credential": "fred_api_key",
        "public": False,
        "capabilities": (
            "macro_series",
            "vintages",
            "point_in_time_observations",
            "release_calendar",
        ),
    },
    {
        "provider_id": "bls_official",
        "display_name": "BLS",
        "aliases": ("bls_official", "bls"),
        "credential": "bls_api_key",
        "public": True,
        "capabilities": ("official_cpi", "official_nfp", "release_schedule"),
    },
    {
        "provider_id": "federal_reserve_fomc",
        "display_name": "Federal Reserve",
        "aliases": ("federal_reserve_fomc", "federal_reserve", "fed"),
        "credential": None,
        "public": True,
        "capabilities": ("fomc_calendar", "statements", "minutes", "press_materials"),
    },
    {
        "provider_id": "trading_economics_consensus",
        "display_name": "Trading Economics",
        "aliases": ("trading_economics", "trading_economics_consensus", "te_consensus"),
        "credential": "trading_economics_api_key",
        "public": False,
        "capabilities": ("survey_consensus", "economic_calendar", "pit_when_entitled"),
    },
    {
        "provider_id": "databento_market",
        "display_name": "Databento",
        "aliases": ("databento", "databento_market"),
        "credential": "databento_api_key",
        "public": False,
        "capabilities": (
            "market_bars_1m",
            "market_bars_1d",
            "futures_symbology",
            "cost_estimate",
        ),
    },
)


def _has_secret(settings: Settings, field: str | None) -> bool:
    if field is None:
        return False
    value = getattr(settings, field, None)
    return bool(value is not None and value.get_secret_value().strip())


def _provider_record(
    persisted: list[dict[str, Any]], aliases: tuple[str, ...]
) -> dict[str, Any] | None:
    for item in persisted:
        if str(item.get("provider_key", "")).lower() in aliases:
            return item
    return None


def _provider_entitlement(record: dict[str, Any] | None, *, public: bool, configured: bool) -> str:
    statuses = [
        str(item.get("status"))
        for item in (record or {}).get("entitlements", [])
        if item.get("status")
    ]
    if "granted" in statuses and any(
        status in statuses for status in ("denied", "expired", "not_configured")
    ):
        return "partial_access"
    for priority in ("denied", "expired", "not_configured", "unknown", "granted"):
        if priority in statuses:
            return priority
    if public:
        return "public_access"
    return "configured_unverified" if configured else "not_configured"


def _redact_provider_message(value: object, settings: Settings) -> str | None:
    if value is None:
        return None
    message = str(value)
    for field in (
        "fred_api_key",
        "bls_api_key",
        "trading_economics_api_key",
        "databento_api_key",
    ):
        secret = getattr(settings, field, None)
        raw = secret.get_secret_value() if secret is not None else ""
        if raw:
            message = message.replace(raw, "[REDACTED]")
    return re.sub(
        r"(?i)((?:api[_-]?key|token|authorization)=)[^&\s]+",
        r"\1[REDACTED]",
        message,
    )


def _optional_float(value: object) -> float | None:
    return float(str(value)) if value is not None else None


def _range_sort_value(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return datetime.combine(value, time.min, tzinfo=UTC)


async def build_provider_status(
    engine: AsyncEngine,
    settings: Settings,
    *,
    probe: bool = False,
) -> dict[str, Any]:
    """Return fixed provider slots without exposing credential values."""

    persisted = await get_provider_data_status(engine)
    live_health = await provider_health_snapshot(settings) if probe else []
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        latest_runs = (
            await session.scalars(
                select(ProviderRun).order_by(ProviderRun.started_at.desc()).limit(500)
            )
        ).all()
        market_ranges = (
            await session.execute(
                select(
                    MarketDataManifest.provider_key,
                    func.min(MarketDataManifest.start_at),
                    func.max(MarketDataManifest.end_at),
                ).group_by(MarketDataManifest.provider_key)
            )
        ).all()
        calendar_ranges = (
            await session.execute(
                select(
                    CalendarSnapshot.provider_key,
                    func.min(CalendarSnapshot.period_start),
                    func.max(CalendarSnapshot.period_end),
                ).group_by(CalendarSnapshot.provider_key)
            )
        ).all()
        observation_ranges = (
            await session.execute(
                select(
                    Provider.key,
                    func.min(Observation.period_start),
                    func.max(Observation.period_end),
                )
                .join(Series, Series.provider_id == Provider.id)
                .join(Observation, Observation.series_id == Series.id)
                .where(Observation.data_mode == "observed")
                .group_by(Provider.key)
            )
        ).all()
        planned_snapshots = (
            await session.execute(
                select(SyncJob.provider_key, func.min(SyncJobRun.scheduled_for))
                .join(SyncJobRun, SyncJobRun.sync_job_id == SyncJob.id)
                .where(
                    SyncJob.operation == "snapshot_consensus",
                    SyncJobRun.status.in_(("pending", "retry_wait")),
                    SyncJobRun.scheduled_for >= datetime.now(UTC),
                )
                .group_by(SyncJob.provider_key)
            )
        ).all()

    range_rows = cast(
        list[tuple[str, date | datetime | None, date | datetime | None]],
        [*market_ranges, *calendar_ranges, *observation_ranges],
    )
    ranges: dict[str, tuple[date | datetime | None, date | datetime | None]] = {}
    for provider_key, range_start, range_end in range_rows:
        current_start, current_end = ranges.get(provider_key, (None, None))
        starts = [item for item in (current_start, range_start) if item is not None]
        ends = [item for item in (current_end, range_end) if item is not None]
        ranges[provider_key] = (
            min(starts, key=_range_sort_value) if starts else None,
            max(ends, key=_range_sort_value) if ends else None,
        )
    next_snapshots = {
        str(provider_key): scheduled_for
        for provider_key, scheduled_for in planned_snapshots
        if provider_key is not None
    }
    items: list[dict[str, Any]] = []
    for definition in _PROVIDERS:
        aliases = tuple(str(item) for item in definition["aliases"])
        public = bool(definition["public"])
        credential_configured = _has_secret(settings, definition["credential"])
        configured = public or credential_configured
        record = _provider_record(persisted, aliases)
        live = next(
            (item for item in live_health if str(item.get("provider_key", "")).lower() in aliases),
            None,
        )
        last_run = cast(dict[str, Any] | None, (record or {}).get("last_run"))
        health_snapshot = cast(
            dict[str, Any] | None,
            (record or {}).get("health_snapshot"),
        )
        run_status = str(last_run.get("status")) if last_run else None
        matching_run = next(
            (
                item
                for item in latest_runs
                if item.provider_key.lower() in aliases
                and item.operation != "configuration_health_snapshot"
            ),
            None,
        )
        live_status = str(live.get("status")) if live else None
        if live_status == "ok" or (live_status is None and run_status == "completed"):
            healthy: bool | None = True
        elif live_status == "unavailable" or (
            live_status is None and run_status in {"failed", "error", "unavailable"}
        ):
            healthy = False
        else:
            healthy = None
        entitlement = _provider_entitlement(record, public=public, configured=credential_configured)
        pit_entitled: bool | None = None
        if definition["provider_id"] == "trading_economics_consensus":
            pit_entitled = bool(getattr(settings, "trading_economics_pit_entitled", False))
            entitlement_rows = {
                str(item.get("capability")): str(item.get("status"))
                for item in (record or {}).get("entitlements", [])
            }
            if entitlement_rows.get("calendar_consensus") == "granted":
                entitlement = (
                    "pit_granted"
                    if entitlement_rows.get("historical_pit_consensus") == "granted"
                    else "calendar_only"
                )
            elif credential_configured and not entitlement_rows:
                entitlement = "pit_configured" if pit_entitled else "calendar_only"
        if not configured:
            healthy = None
            provider_status = "not_configured"
        elif live_status:
            provider_status = live_status
        elif run_status:
            provider_status = run_status
        elif health_snapshot and health_snapshot.get("status"):
            provider_status = str(health_snapshot["status"])
        elif public:
            provider_status = "available_public"
        elif credential_configured:
            provider_status = "configured_unverified"
        else:
            provider_status = "not_configured"
        quota = (record or {}).get("quota")
        quota_payload = None
        if quota:
            quota_payload = {
                "limit": _optional_float(quota.get("limit")),
                "used": _optional_float(quota.get("used")),
                "remaining": _optional_float(quota.get("remaining")),
                "period": quota.get("quota_key"),
                "unit": quota.get("unit"),
                "captured_at": quota.get("captured_at"),
            }
        provider_range = next(
            (ranges[key] for key in aliases if key in ranges),
            (None, None),
        )
        next_planned_snapshot = next(
            (next_snapshots[key] for key in aliases if key in next_snapshots),
            None,
        )
        items.append(
            {
                "provider_id": definition["provider_id"],
                "display_name": definition["display_name"],
                "configured": configured,
                "credential_configured": credential_configured,
                "pit_entitled": pit_entitled,
                "healthy": healthy,
                "entitlement": entitlement,
                "status": provider_status,
                "last_success_at": (
                    last_run.get("completed_at")
                    if last_run is not None and run_status == "completed"
                    else None
                ),
                "last_error": _redact_provider_message(
                    live.get("message")
                    if live is not None and live_status == "unavailable"
                    else (last_run.get("error_message") if last_run else None),
                    settings,
                ),
                "quota": quota_payload,
                "data_range": {
                    "start": provider_range[0],
                    "end": provider_range[1],
                }
                if provider_range != (None, None)
                else None,
                "quality_grade": matching_run.quality_grade if matching_run else None,
                "next_planned_snapshot": (
                    _range_sort_value(next_planned_snapshot)
                    if next_planned_snapshot is not None
                    else None
                ),
                "capabilities": list(definition["capabilities"]),
                "health_source": (
                    "live_probe"
                    if live is not None
                    else "successful_sync"
                    if run_status == "completed"
                    else "persisted_configuration"
                    if health_snapshot is not None
                    else "persisted_state"
                ),
                "latency_ms": live.get("latency_ms") if live else None,
                "health_warnings": (
                    list(cast(list[str], live.get("warnings", []))) if live else []
                ),
            }
        )
    return {
        "items": items,
        "checked_at": datetime.now(UTC),
        "data_mode": "observed",
        "probe_performed": probe,
        "secrets_returned": False,
    }


def _coverage_dimension(
    *,
    stored_count: int,
    eligible_count: int,
    data_mode: Literal["observed", "fixture"],
    updated_at: datetime | None,
    missing_reason: str,
    eligibility_reason: str,
    quality_grade: str | None = None,
    stored_item_count: int | None = None,
) -> dict[str, Any]:
    stored = (stored_item_count or 0) > 0 if stored_item_count is not None else stored_count > 0
    eligible = eligible_count > 0
    return {
        "status": "analysis_ready" if eligible else "stored_not_eligible" if stored else "missing",
        # Kept for older clients; availability now means analysis eligibility,
        # not merely the existence of a database row.
        "available": eligible,
        "stored": stored,
        "analysis_eligible": eligible,
        "data_mode": data_mode if stored else None,
        "quality_grade": quality_grade,
        "last_updated_at": updated_at,
        "missing_reason": None if stored else missing_reason,
        "eligibility_reason": None if eligible else eligibility_reason,
        "record_count": stored_count,
        "stored_record_count": stored_count,
        "analysis_eligible_record_count": eligible_count,
        "stored_item_count": stored_item_count,
    }


def _aggregate_quality(grades: list[str]) -> str | None:
    rank = {"A": 0, "B": 1, "C": 2, "D": 3}
    usable = {grade.upper() for grade in grades if grade.upper() in rank}
    return max(usable, key=rank.__getitem__) if usable else None


async def build_data_coverage(
    engine: AsyncEngine, *, data_mode: Literal["observed", "fixture"]
) -> dict[str, Any]:
    """Build an event-family matrix; fixture and observed rows never mix."""

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        releases = (
            await session.scalars(
                select(MacroRelease).where(
                    MacroRelease.data_mode == data_mode,
                    MacroRelease.status != "invalidated",
                )
            )
        ).all()
        release_ids = [item.id for item in releases]
        values = (
            (
                await session.scalars(
                    select(ReleaseValue).where(
                        ReleaseValue.data_mode == data_mode,
                        ReleaseValue.macro_release_id.in_(release_ids),
                    )
                )
            ).all()
            if release_ids
            else []
        )
        values = [item for item in values if not item.metadata_json.get("superseded")]
        consensus = (
            (
                await session.scalars(
                    select(ConsensusSnapshot).where(
                        ConsensusSnapshot.data_mode == data_mode,
                        ConsensusSnapshot.macro_release_id.in_(release_ids),
                    )
                )
            ).all()
            if release_ids
            else []
        )
        manifests = (
            (
                await session.scalars(
                    select(MarketDataManifest).where(
                        MarketDataManifest.data_mode == data_mode,
                        MarketDataManifest.macro_release_id.in_(release_ids),
                    )
                )
            ).all()
            if release_ids
            else []
        )
        artifact_ids = {
            row.source_artifact_id for row in values if row.source_artifact_id is not None
        } | {row.source_artifact_id for row in consensus if row.source_artifact_id is not None}
        artifacts = {
            item.id: item
            for item in (
                (
                    await session.scalars(
                        select(SourceArtifact).where(SourceArtifact.id.in_(artifact_ids))
                    )
                ).all()
                if artifact_ids
                else []
            )
        }
        quality_ids = {item.quality_id for item in values if item.quality_id is not None}
        quality_by_id = {
            item.id: item
            for item in (
                (
                    await session.scalars(
                        select(DataQualityRecord).where(DataQualityRecord.id.in_(quality_ids))
                    )
                ).all()
                if quality_ids
                else []
            )
        }
        manifest_ids = {str(item.id) for item in manifests}
        market_reconciliations = (
            (
                await session.scalars(
                    select(DataReconciliationRecord).where(
                        DataReconciliationRecord.data_mode == data_mode,
                        DataReconciliationRecord.reconciliation_type == "market_integrity",
                        DataReconciliationRecord.subject_id.in_(manifest_ids),
                    )
                )
            ).all()
            if manifest_ids
            else []
        )

    release_type_by_id = {item.id: item.release_type for item in releases}
    values_by_release: dict[uuid.UUID, list[ReleaseValue]] = {}
    consensus_by_release: dict[uuid.UUID, list[ConsensusSnapshot]] = {}
    for value_row in values:
        values_by_release.setdefault(value_row.macro_release_id, []).append(value_row)
    for consensus_row in consensus:
        consensus_by_release.setdefault(consensus_row.macro_release_id, []).append(consensus_row)
    selected_actuals: list[ReleaseValue] = []
    selected_consensus: list[ConsensusSnapshot] = []
    for release in releases:
        selected_values, selected_snapshots = select_analysis_inputs_from_rows(
            release,
            values=values_by_release.get(release.id, []),
            consensus=consensus_by_release.get(release.id, []),
            artifacts=artifacts,
        )
        selected_actuals.extend(
            row
            for (_indicator_id, value_kind), row in selected_values.items()
            if value_kind == "actual" and row.value is not None and row.is_initial
        )
        selected_consensus.extend(selected_snapshots.values())
    market_reconciliation_by_subject: dict[str, list[DataReconciliationRecord]] = {}
    for reconciliation_row in market_reconciliations:
        market_reconciliation_by_subject.setdefault(reconciliation_row.subject_id, []).append(
            reconciliation_row
        )

    def eligible_manifest(item: MarketDataManifest) -> bool:
        checks = market_reconciliation_by_subject.get(str(item.id), [])
        return (
            item.row_count > 0
            and item.quality_grade.upper() in {"A", "B", "C"}
            and bool(checks)
            and all(check.status in {"matched", "resolved"} for check in checks)
        )

    items: list[dict[str, Any]] = []
    for event_type, title in EVENT_TITLES.items():
        event_ids = {
            release_id
            for release_id, release_type in release_type_by_id.items()
            if release_type == event_type
        }
        event_values = [
            item
            for item in values
            if item.macro_release_id in event_ids and item.value_kind == "actual"
        ]
        event_consensus = [item for item in consensus if item.macro_release_id in event_ids]
        eligible_actuals = [item for item in selected_actuals if item.macro_release_id in event_ids]
        eligible_consensus = [
            item for item in selected_consensus if item.macro_release_id in event_ids
        ]
        event_manifests = [item for item in manifests if item.macro_release_id in event_ids]
        intraday = [
            item
            for item in event_manifests
            if item.interval_seconds <= 60 or "1m" in item.schema_name.lower()
        ]
        daily = [
            item
            for item in event_manifests
            if item.interval_seconds >= 86_400 or "1d" in item.schema_name.lower()
        ]
        eligible_intraday = [item for item in intraday if eligible_manifest(item)]
        eligible_daily = [item for item in daily if eligible_manifest(item)]
        actual_grades = [
            quality_by_id[item.quality_id].quality_grade
            for item in eligible_actuals
            if item.quality_id in quality_by_id
        ]
        consensus_grades = [item.quality_grade for item in eligible_consensus]
        market_grades = [item.quality_grade for item in [*eligible_intraday, *eligible_daily]]
        source_grades = [*actual_grades, *consensus_grades, *market_grades]
        items.append(
            {
                "event_type": event_type,
                "title": title,
                "actual": _coverage_dimension(
                    stored_count=len(event_values),
                    eligible_count=len(eligible_actuals),
                    data_mode=data_mode,
                    updated_at=max((item.captured_at for item in event_values), default=None),
                    missing_reason="No release actuals are stored in this data mode.",
                    eligibility_reason=(
                        "Stored actuals are revisions or do not contain a reconstructable "
                        "initial point-in-time value."
                    ),
                    quality_grade=_aggregate_quality(actual_grades),
                ),
                "consensus": _coverage_dimension(
                    stored_count=len(event_consensus),
                    eligible_count=len(eligible_consensus),
                    data_mode=data_mode,
                    updated_at=max((item.captured_at for item in event_consensus), default=None),
                    missing_reason="No consensus snapshot is stored.",
                    eligibility_reason=(
                        "Stored snapshots are post-release or fail the shared consensus "
                        "quality selector."
                    ),
                    quality_grade=_aggregate_quality(consensus_grades),
                ),
                "intraday": _coverage_dimension(
                    stored_count=sum(max(item.row_count, 0) for item in intraday),
                    eligible_count=sum(max(item.row_count, 0) for item in eligible_intraday),
                    data_mode=data_mode,
                    updated_at=max((item.created_at for item in intraday), default=None),
                    missing_reason="No event-linked one-minute manifest is stored.",
                    eligibility_reason=(
                        "Stored manifests need rows, grade A-C, and a passing market-integrity "
                        "reconciliation."
                    ),
                    quality_grade=_aggregate_quality(
                        [item.quality_grade for item in eligible_intraday]
                    ),
                    stored_item_count=len(intraday),
                ),
                "daily": _coverage_dimension(
                    stored_count=sum(max(item.row_count, 0) for item in daily),
                    eligible_count=sum(max(item.row_count, 0) for item in eligible_daily),
                    data_mode=data_mode,
                    updated_at=max((item.created_at for item in daily), default=None),
                    missing_reason="No event-linked daily manifest is stored.",
                    eligibility_reason=(
                        "Stored manifests need rows, grade A-C, and a passing market-integrity "
                        "reconciliation."
                    ),
                    quality_grade=_aggregate_quality(
                        [item.quality_grade for item in eligible_daily]
                    ),
                    stored_item_count=len(daily),
                ),
                "source_quality": _aggregate_quality(source_grades),
                "source_quality_basis": {
                    "assessed_record_count": len(source_grades),
                    "grades": sorted(set(source_grades)),
                    "ungraded_eligible_actuals": max(0, len(eligible_actuals) - len(actual_grades)),
                },
            }
        )
    return {
        "items": items,
        "as_of": datetime.now(UTC),
        "data_mode": data_mode,
        "observed_only": data_mode == "observed",
    }


def parse_csv_values(value: str | None, defaults: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return defaults
    return tuple(item.strip().upper() for item in value.split(",") if item.strip())


def _month_count(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def expected_release_count(start: date, end: date, event_types: tuple[str, ...]) -> int:
    """Conservative schedule estimate used before official calendars are populated."""

    months = _month_count(start, end)
    count = months * sum(item in {"US_CPI", "US_NFP"} for item in event_types)
    if "FOMC" in event_types:
        days = (end - start).days + 1
        count += max(1, round(days * 8 / 365.2425))
    return count


def build_backfill_request(
    payload: BackfillRequestInput,
    settings: Settings,
) -> BackfillRequest:
    _ = payload.estimate_id  # An estimate is always recomputed server-side.
    return BackfillRequest(
        start_date=payload.start_date,
        end_date=payload.end_date,
        event_types=tuple(payload.event_types),
        instruments=tuple(payload.assets),
        datasets=DEFAULT_SCHEMAS,
        dataset_schemas=tuple(
            sorted(
                {
                    (DATASET_BY_ASSET[asset], schema)
                    for asset in payload.assets
                    for schema in DEFAULT_SCHEMAS
                }
            )
        ),
        data_mode="observed",
        intraday_pre_minutes=settings.market_intraday_pre_minutes,
        intraday_post_minutes=settings.market_intraday_post_minutes,
        daily_pre_days=settings.market_daily_pre_days,
        daily_post_days=settings.market_daily_post_days,
        expected_event_count=expected_release_count(
            payload.start_date, payload.end_date, tuple(payload.event_types)
        ),
    )


def _dataset_estimates(
    request: BackfillRequest,
    estimate: BackfillEstimate,
    provider_quotes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if provider_quotes:
        return provider_quotes
    result: list[dict[str, Any]] = []
    combinations = [
        (
            dataset,
            schema,
            [asset for asset in request.instruments if DATASET_BY_ASSET[asset] == dataset],
        )
        for dataset in sorted(set(DATASET_BY_ASSET.values()))
        for schema in request.datasets
    ]
    per_asset_minute = estimate.event_count * estimate.minute_range_per_event
    per_asset_daily = estimate.event_count * (request.daily_pre_days + request.daily_post_days + 1)
    for dataset, schema, assets in combinations:
        if not assets:
            continue
        records = len(assets) * (per_asset_minute if "1m" in schema else per_asset_daily)
        share = Decimal(records) / Decimal(max(1, estimate.estimated_record_count))
        result.append(
            {
                "dataset": f"{dataset}:{schema}",
                "assets": assets,
                "estimated_records": records,
                "estimated_bytes": records * 80,
                "estimated_cost_usd": float(estimate.estimated_cost_usd * share),
            }
        )
    return result


async def _databento_backfill_quote(
    settings: Settings,
    request: BackfillRequest,
) -> dict[str, Any]:
    """Quote representative event slices; metadata calls never download market data."""

    if not _has_secret(settings, "databento_api_key"):
        return {
            "source": "fallback_estimate",
            "confidence": "low",
            "cost_usd": None,
            "estimated_records": None,
            "estimated_bytes": None,
            "datasets": [],
            "warnings": ["Databento is not configured; local record-size assumptions were used."],
        }
    provider = build_provider_clients(settings).databento
    event_count = request.expected_event_count or 1
    representative_start = datetime.combine(request.start_date, time.min, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for dataset in sorted(set(DATASET_BY_ASSET.values())):
        symbols = tuple(item for item in request.instruments if DATASET_BY_ASSET[item] == dataset)
        if not symbols:
            continue
        for schema in request.datasets:
            if schema == "ohlcv-1m":
                duration = timedelta(minutes=request.intraday_pre_minutes)
                duration += timedelta(minutes=request.intraday_post_minutes)
            else:
                duration = timedelta(days=request.daily_pre_days + request.daily_post_days + 1)
            provider_request = DatabentoDownloadRequest.model_validate(
                {
                    "symbols": symbols,
                    "start": representative_start,
                    "end": representative_start + duration,
                    "schema": schema,
                    "event_count": 1,
                    "known_record_count": 0,
                }
            )
            try:
                quote = await provider.estimate_download(provider_request)
            except Exception as exc:
                warnings.append(f"{dataset}:{schema} metadata quote failed: {type(exc).__name__}")
                quote = provider.estimate_cost(provider_request)
            multiplier = Decimal(event_count)
            rows.append(
                {
                    "dataset": f"{dataset}:{schema}",
                    "assets": list(symbols),
                    "estimated_records": quote.estimated_records * event_count,
                    "estimated_bytes": quote.estimated_billable_bytes * event_count,
                    "estimated_cost_usd": float(quote.estimated_cost_usd * multiplier),
                    "quote_source": quote.source,
                    "quote_confidence": quote.confidence,
                    "provider_quoted_at": quote.provider_quoted_at,
                    "limitations": list(quote.uncertainty_notes),
                }
            )
    metadata_rows = [item for item in rows if item["quote_source"] == "provider_metadata"]
    confidence = "medium" if rows and len(metadata_rows) == len(rows) else "low"
    source = (
        "provider_metadata"
        if rows and len(metadata_rows) == len(rows)
        else ("mixed_provider_and_fallback" if metadata_rows else "fallback_estimate")
    )
    return {
        "source": source,
        "confidence": confidence,
        "cost_usd": sum(
            (Decimal(str(item["estimated_cost_usd"])) for item in rows),
            start=Decimal("0"),
        ),
        "estimated_records": sum(int(item["estimated_records"]) for item in rows),
        "estimated_bytes": sum(int(item["estimated_bytes"]) for item in rows),
        "datasets": rows,
        "warnings": warnings,
    }


async def estimate_backfill_payload(
    engine: AsyncEngine,
    settings: Settings,
    payload: BackfillRequestInput,
) -> tuple[BackfillRequest, BackfillEstimate, dict[str, Any]]:
    request = build_backfill_request(payload, settings)
    key_configured = _has_secret(settings, "databento_api_key")
    provider_quote = await _databento_backfill_quote(settings, request)
    quoted_cost = cast(Decimal | None, provider_quote["cost_usd"])
    authoritative_quote = provider_quote["source"] == "provider_metadata"
    estimate = await estimate_backfill(
        engine,
        request,
        budget_limit_usd=settings.databento_max_estimated_cost_usd,
        paid_download_allowed=(
            settings.allow_paid_download and key_configured and authoritative_quote
        ),
        provider_estimated_cost_usd=quoted_cost,
    )
    quoted_records = cast(int | None, provider_quote["estimated_records"])
    quoted_bytes = cast(int | None, provider_quote["estimated_bytes"])
    if quoted_records is not None and quoted_bytes is not None:
        estimate = replace(
            estimate,
            estimated_record_count=quoted_records,
            estimated_download_records=max(0, quoted_records - estimate.existing_record_count),
            estimated_size_bytes=quoted_bytes,
            estimation_method=str(provider_quote["source"]),
        )
    allow_execute = estimate.execution_allowed and key_configured
    if not key_configured:
        blocked_reason = "Databento API key is not configured."
    elif not settings.allow_paid_download:
        blocked_reason = "Paid downloads are disabled by WORLDSTATE_ALLOW_PAID_DOWNLOAD."
    elif not authoritative_quote:
        blocked_reason = (
            "A fresh Databento metadata quote is unavailable; fallback estimates "
            "never authorize a paid download."
        )
    elif estimate.estimated_cost_usd > settings.databento_max_estimated_cost_usd:
        blocked_reason = "Estimated cost exceeds WORLDSTATE_DATABENTO_MAX_ESTIMATED_COST_USD."
    else:
        blocked_reason = None
    response = {
        "estimate_id": make_backfill_idempotency_key(request),
        "start_date": request.start_date,
        "end_date": request.end_date,
        "event_count": estimate.event_count,
        "asset_count": estimate.asset_count,
        "datasets": _dataset_estimates(
            request,
            estimate,
            cast(list[dict[str, Any]], provider_quote["datasets"]),
        ),
        "minute_range": (f"T-{request.intraday_pre_minutes}m..T+{request.intraday_post_minutes}m"),
        "pre_minutes": request.intraday_pre_minutes,
        "post_minutes": request.intraday_post_minutes,
        "estimated_records": estimate.estimated_record_count,
        "estimated_bytes": estimate.estimated_size_bytes,
        "estimated_cost_usd": float(estimate.estimated_cost_usd),
        "budget_limit_usd": float(estimate.budget_limit_usd),
        "allow_execute": allow_execute,
        "already_available_records": estimate.existing_record_count,
        "records_to_download": estimate.estimated_download_records,
        "blocked_reason": blocked_reason,
        "provider_status": (
            "configured_metadata_estimate"
            if key_configured and authoritative_quote
            else "configured_quote_unavailable"
            if key_configured
            else "not_configured"
        ),
        "estimation_method": estimate.estimation_method,
        "cost_confidence": provider_quote["confidence"],
        "quote_warnings": provider_quote["warnings"],
        "estimation_limitations": [
            "Event count is a schedule-frequency estimate until official calendars are stored.",
            (
                "Provider metadata quotes cover representative event windows and are "
                "multiplied by the estimated event count."
                if provider_quote["source"] == "provider_metadata"
                else "One or more costs use conservative local record-size assumptions."
            ),
            (
                "This estimate performs no paid download. Starting an approved job schedules "
                "the local worker; Databento calls remain blocked unless credentials, "
                "entitlement, the aggregate budget gate, and the explicit paid-download flag "
                "all permit execution."
            ),
        ],
    }
    return request, estimate, response


def serialize_backfill_job(row: BackfillJob) -> dict[str, Any]:
    result = row.result_json or {}
    public_status = "blocked" if row.status == "rejected" else row.status
    return {
        "id": str(row.id),
        "status": public_status,
        "persisted_status": row.status,
        "progress_percent": round(row.progress * 100, 2),
        "current_stage": row.current_stage,
        "events_total": row.estimated_event_count,
        "events_completed": int(result.get("events_completed", 0)),
        "downloaded_records": row.downloaded_record_count,
        "skipped_records": row.existing_record_count,
        "failed_records": int(result.get("failed_records", 0)),
        "estimated_cost_usd": float(row.estimated_cost_usd),
        "actual_cost_usd": result.get("actual_cost_usd"),
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "last_error": row.error_message,
        "can_cancel": row.status in {"estimated", "pending", "running"},
        "execution_allowed": row.execution_allowed,
        "paid_download_allowed": row.paid_download_allowed,
        "data_mode": row.data_mode,
        "note": (
            "Queued for the background worker; this API response itself performed no paid download."
            if row.status == "pending"
            else None
        ),
    }


async def start_backfill(
    engine: AsyncEngine, settings: Settings, payload: BackfillRequestInput
) -> tuple[BackfillJob, dict[str, Any]]:
    request, estimate, _ = await estimate_backfill_payload(engine, settings, payload)
    row = await create_backfill_job(
        engine,
        request,
        estimate,
        execute_requested=True,
        provider_key="databento",
    )
    return row, serialize_backfill_job(row)


def _safe_service_failure(exc: Exception, settings: Settings) -> dict[str, Any]:
    if isinstance(exc, MacroEngineError):
        status = (
            "error"
            if exc.code in {"provider_request_invalid", "provider_data_not_found"}
            else "blocked"
        )
        return {
            "status": status,
            "error_type": type(exc).__name__,
            "code": exc.code,
            "message": _redact_provider_message(exc.message, settings),
        }
    if isinstance(exc, LookupError | ValueError):
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "code": "invalid_request",
            "message": str(exc),
        }
    return {
        "status": "error",
        "error_type": type(exc).__name__,
        "code": "operation_failed",
        "message": "Provider operation failed; inspect the local provider run.",
    }


def _http_error_for_service(exc: Exception, settings: Settings) -> HTTPException:
    failure = _safe_service_failure(exc, settings)
    code = str(failure["code"])
    if code == "provider_data_not_found" or isinstance(exc, LookupError):
        status_code = 404
    elif code in {"provider_request_invalid", "invalid_request"} or isinstance(exc, ValueError):
        status_code = 422
    elif isinstance(exc, MacroEngineError):
        # 403 is reserved for WorldState's own write authorization.  Provider
        # configuration, entitlement, quota, network and paid-data guards are
        # upstream dependencies and therefore share the documented 424 contract.
        status_code = 424
    else:
        status_code = 424
    return HTTPException(status_code=status_code, detail=failure)


def normalize_multi_operation_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize fan-out jobs to the public completed/partial/blocked contract."""

    normalized = dict(result)
    results = normalized.get("results")
    failures = normalized.get("failures")
    result_rows = results if isinstance(results, dict) else {}
    failure_rows = failures if isinstance(failures, dict) else {}
    successful_statuses = {"completed", "ok", "success"}
    blocked_statuses = {
        "blocked",
        "failed",
        "error",
        "unavailable",
        "not_configured",
    }
    nested_statuses = {
        str(key): str(value.get("status", "completed"))
        for key, value in result_rows.items()
        if isinstance(value, dict)
    }
    nested_blocked = {
        key: status for key, status in nested_statuses.items() if status in blocked_statuses
    }
    nested_partial = {
        key: status for key, status in nested_statuses.items() if status == "partial"
    }
    successful_count = sum(status in successful_statuses for status in nested_statuses.values())
    # A result without its own status is a successful legacy operation result.
    successful_count += sum(not isinstance(value, dict) for value in result_rows.values())
    if nested_blocked:
        normalized["blocked_operations"] = nested_blocked
    has_problem = bool(failure_rows or nested_blocked or nested_partial)
    if has_problem:
        normalized["status"] = "partial" if successful_count else "blocked"
    elif normalized.get("status") == "blocked":
        normalized["status"] = "blocked"
    else:
        normalized["status"] = "completed"
    return normalized


async def run_calendar_sync(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    results: dict[str, object] = {}
    failures: dict[str, object] = {}
    for key, operation in (
        ("bls", sync_bls_calendar),
        ("fomc", sync_fomc_materials),
    ):
        try:
            results[key] = await operation(
                engine,
                settings,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as exc:
            failures[key] = _safe_service_failure(exc, settings)
    return normalize_multi_operation_result(
        {
            "status": "completed" if not failures else ("partial" if results else "blocked"),
            "results": results,
            "failures": failures,
        }
    )


async def run_data_reconciliation(
    engine: AsyncEngine,
    *,
    release_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper around the shared scheduler/API reconciliation service."""

    return await reconcile_persisted_data(engine, release_id=release_id)


@data_router.get("/providers")
async def provider_status(
    request: Request,
    probe: bool = Query(default=False),
) -> dict[str, Any]:
    return await build_provider_status(
        request.app.state.database_engine,
        request.app.state.settings,
        probe=probe,
    )


@data_router.get("/operation-contract")
async def data_operation_contract() -> dict[str, Any]:
    """Document API status and CLI exit semantics for provider operations.

    WorldState authorization failures remain HTTP 403 and are intentionally
    outside this provider-operation contract.
    """

    return {
        "statuses": DATA_OPERATION_STATUS_CONTRACT,
        "authorization_failure_http_status": 403,
        "notes": [
            "HTTP 424 means the operation was accepted but an upstream dependency blocked it.",
            "No paid market-data download is started by an estimate request.",
        ],
    }


@data_router.get("/coverage")
async def data_coverage(
    request: Request,
    data_mode: Literal["observed", "fixture"] | None = Query(default=None),
) -> dict[str, Any]:
    selected = data_mode or ("fixture" if request.app.state.settings.demo_mode else "observed")
    return await build_data_coverage(
        request.app.state.database_engine,
        data_mode=selected,
    )


def _set_multi_status(response: Response, result: dict[str, Any]) -> None:
    if result.get("status") == "partial":
        response.status_code = 207
    elif result.get("status") == "blocked":
        response.status_code = 424


@data_write_router.post("/sync/official")
async def sync_official_endpoint(
    payload: DataRangeInput,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    result = normalize_multi_operation_result(
        cast(
            dict[str, Any],
            await sync_official_data(
                request.app.state.database_engine,
                settings,
                start_date=payload.start_date,
                end_date=payload.end_date,
            ),
        )
    )
    result["failures"] = {
        key: _redact_provider_message(value, settings)
        for key, value in cast(dict[str, object], result.get("failures", {})).items()
    }
    _set_multi_status(response, result)
    return result


@data_write_router.post("/sync/calendar")
async def sync_calendar_endpoint(
    payload: DataRangeInput,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    result = await run_calendar_sync(
        request.app.state.database_engine,
        request.app.state.settings,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    _set_multi_status(response, result)
    return result


@data_write_router.post("/sync/consensus")
async def sync_consensus_endpoint(
    payload: ConsensusSyncInput,
    request: Request,
) -> dict[str, Any]:
    try:
        return cast(
            dict[str, Any],
            await snapshot_trading_economics_consensus(
                request.app.state.database_engine,
                request.app.state.settings,
                start_date=payload.start_date,
                end_date=payload.end_date,
                pit_at=payload.pit_at,
            ),
        )
    except Exception as exc:
        raise _http_error_for_service(exc, request.app.state.settings) from exc


@data_write_router.post("/sync/market")
async def sync_market_endpoint(
    payload: MarketSyncInput,
    request: Request,
) -> dict[str, Any]:
    try:
        return cast(
            dict[str, Any],
            await sync_databento_release_market(
                request.app.state.database_engine,
                request.app.state.settings,
                release_id=payload.release_id,
                roots=tuple(payload.assets),
                include_daily=payload.include_daily,
            ),
        )
    except Exception as exc:
        raise _http_error_for_service(exc, request.app.state.settings) from exc


@data_write_router.post("/reconcile")
async def reconcile_endpoint(
    payload: ReconcileInput,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    try:
        result = await run_data_reconciliation(
            request.app.state.database_engine,
            release_id=payload.release_id,
        )
    except Exception as exc:
        raise _http_error_for_service(exc, request.app.state.settings) from exc
    _set_multi_status(response, result)
    return result


@data_router.get("/backfill/estimate")
async def estimate_backfill_endpoint(
    request: Request,
    start_date: date,
    end_date: date,
    event_types: str | None = Query(default=None),
    assets: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        payload = BackfillRequestInput(
            start_date=start_date,
            end_date=end_date,
            event_types=parse_csv_values(event_types, DEFAULT_EVENT_TYPES),
            assets=parse_csv_values(assets, DEFAULT_ASSETS),
        )
    except ValidationError as exc:
        detail = [
            {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
            for item in exc.errors(include_url=False)
        ]
        raise HTTPException(status_code=422, detail=detail) from exc
    _, _, response = await estimate_backfill_payload(
        request.app.state.database_engine, request.app.state.settings, payload
    )
    return response


@data_write_router.post("/backfill")
async def create_backfill_endpoint(
    payload: BackfillRequestInput, request: Request, response: Response
) -> dict[str, Any]:
    _, result = await start_backfill(
        request.app.state.database_engine, request.app.state.settings, payload
    )
    if result.get("status") == "blocked":
        response.status_code = 424
    return result


@data_router.get("/backfill/{job_id}")
async def backfill_status(job_id: str, request: Request) -> dict[str, Any]:
    try:
        identifier = uuid.UUID(job_id)
        row = await get_backfill_job(request.app.state.database_engine, identifier)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="backfill job not found") from exc
    return serialize_backfill_job(row)


@data_write_router.post("/backfill/{job_id}/cancel")
async def cancel_backfill_endpoint(job_id: str, request: Request) -> dict[str, Any]:
    try:
        identifier = uuid.UUID(job_id)
        row = await cancel_backfill_job(request.app.state.database_engine, identifier)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="backfill job not found") from exc
    return serialize_backfill_job(row)


__all__ = [
    "DATA_OPERATION_STATUS_CONTRACT",
    "build_backfill_request",
    "build_data_coverage",
    "build_provider_status",
    "data_router",
    "data_write_router",
    "estimate_backfill_payload",
    "expected_release_count",
    "normalize_multi_operation_result",
    "parse_csv_values",
    "serialize_backfill_job",
    "start_backfill",
]
