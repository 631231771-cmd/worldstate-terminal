"""Capability-driven inventory for the product layer.

The database deliberately stores observations, bars and release artifacts in
their domain models.  This module is the read-only bridge that answers the
product question: *what can this dataset actually support?*  A row being
``observed`` is not enough to claim PIT, intraday event or historical replay
capability.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.freshness_service import build_data_freshness
from worldstate.db.models import (
    AnalysisRun,
    ConsensusSnapshot,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    MarketInstrument,
    Observation,
    Provider,
    ReleaseValue,
    Series,
)

DataMode = Literal["observed", "fixture", "all"]
CAPABILITY_KEYS = (
    "CURRENT_STATE",
    "DAILY_MARKET",
    "MACRO_HISTORY",
    "POINT_IN_TIME",
    "EVENT_INTRADAY",
    "HISTORICAL_REPLAY",
    "SURPRISE_ELIGIBLE",
    "WORLD_STATE",
    "GLOBAL_MACRO",
)


def _source_class(provider: str, *, data_mode: str, proxy: bool = False) -> str:
    if data_mode == "fixture":
        return "fixture"
    if proxy:
        return "proxy"
    if provider in {
        "bls_official",
        "federal_reserve_fomc",
        "ecb_data_portal",
        "bank_of_england_iadb",
    }:
        return "official"
    if provider == "fred_alfred":
        return "public_current_or_alfred"
    if provider in {"manual_csv", "manual_official", "china_official_public", "boj_public"}:
        return "manual_or_official_export"
    if provider in {"databento_market", "trading_economics_consensus"}:
        return "licensed"
    return "provider"


def _status(available: bool, *, stale: bool = False) -> str:
    if not available:
        return "MISSING"
    return "STALE" if stale else "AVAILABLE"


def _dimension_state(
    available: bool,
    *,
    stale: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "available": available,
        "status": _status(available, stale=stale),
        "reason": reason if not available or stale else None,
    }


def _series_item(
    series: Series,
    provider: Provider,
    observations: list[Observation],
    freshness: dict[str, Any],
    *,
    data_mode: str,
) -> dict[str, Any]:
    latest = (
        max(observations, key=lambda item: (item.period_start, item.id)) if observations else None
    )
    flags = {flag.lower() for item in observations for flag in item.quality_flags}
    point_in_time = (
        bool(observations)
        and "not_point_in_time" not in flags
        and any(item.realtime_start is not None for item in observations)
    )
    dimensions = list((series.metadata_json or {}).get("state_dimensions") or [])
    state = str(freshness.get("status") or "MISSING")
    current = bool(observations)
    history = len(observations) >= 2
    world_state = current and bool(dimensions)
    return {
        "dataset_key": f"series:{series.canonical_key}",
        "kind": "series",
        "canonical_key": series.canonical_key,
        "label": series.title,
        "entity": (series.metadata_json or {}).get("entity") or series.canonical_key.split(".")[0],
        "rows": len(observations),
        "coverage_start": min((item.period_start for item in observations), default=None),
        "coverage_end": max((item.period_start for item in observations), default=None),
        "latest_timestamp": latest.period_start if latest else None,
        "latest_available_at": latest.available_at if latest else None,
        "freshness": {
            "status": state,
            "score": freshness.get("freshness_score"),
            "reason": freshness.get("reason"),
        },
        "frequency": series.frequency,
        "source_class": _source_class(provider.key, data_mode=data_mode),
        "provider": provider.key,
        "source_url": series.source_url,
        "data_mode": data_mode,
        "proxy": False,
        "manual": "manual" in provider.key or "manual" in flags,
        "fixture": data_mode == "fixture",
        "point_in_time": point_in_time,
        "quality_flags": sorted(flags),
        "capabilities": {
            "CURRENT_STATE": _dimension_state(current, reason="No observation is stored."),
            "DAILY_MARKET": _dimension_state(
                False, reason="This is a macro series, not a market bar."
            ),
            "MACRO_HISTORY": _dimension_state(
                history, reason="At least two observations are required."
            ),
            "POINT_IN_TIME": _dimension_state(
                point_in_time,
                reason="No realtime vintage fields are stored for this series.",
            ),
            "EVENT_INTRADAY": _dimension_state(
                False, reason="Macro series has no minute event bars."
            ),
            "HISTORICAL_REPLAY": _dimension_state(
                point_in_time and history,
                reason="Historical replay needs PIT vintages and multiple observations.",
            ),
            "SURPRISE_ELIGIBLE": _dimension_state(
                False,
                reason="Surprise requires a release actual and a pre-T0 consensus snapshot.",
            ),
            "WORLD_STATE": _dimension_state(
                world_state, reason="No mapped World State dimension is available."
            ),
            "GLOBAL_MACRO": _dimension_state(current, reason="No observed macro value is stored."),
        },
    }


def _market_item(
    instrument: MarketInstrument,
    bars: list[MarketBar],
    manifests: list[MarketDataManifest],
    *,
    data_mode: str,
    now: datetime,
) -> dict[str, Any]:
    latest = max(bars, key=lambda item: item.timestamp) if bars else None
    intervals = {item.interval_seconds for item in bars}
    daily = any(interval >= 86_400 for interval in intervals)
    manifest_intraday = any(
        item.interval_seconds <= 60 and item.row_count > 0 for item in manifests
    )
    intraday = any(interval <= 60 for interval in intervals) or manifest_intraday
    stale = bool(latest and (now - latest.timestamp.replace(tzinfo=UTC)).days > 7)
    current = bool(bars)
    return {
        "dataset_key": f"market:{instrument.canonical_key}",
        "kind": "market",
        "canonical_key": instrument.canonical_key,
        "label": instrument.title,
        "symbol": instrument.symbol,
        "asset_class": instrument.asset_class,
        "rows": len(bars),
        "coverage_start": min((item.timestamp for item in bars), default=None),
        "coverage_end": max((item.timestamp for item in bars), default=None),
        "latest_timestamp": latest.timestamp if latest else None,
        "latest_available_at": latest.fetched_at if latest else None,
        "freshness": {
            "status": _status(current, stale=stale),
            "score": None,
            "reason": "Latest bar is more than seven days old." if stale else None,
        },
        "frequency": "intraday" if intraday else "daily" if daily else "unknown",
        "source_class": _source_class(
            latest.provider_key if latest else instrument.canonical_key,
            data_mode=data_mode,
            proxy=instrument.is_proxy,
        ),
        "provider": latest.provider_key if latest else None,
        "source_url": None,
        "data_mode": data_mode,
        "proxy": bool(instrument.is_proxy),
        "manual": latest.provider_key.startswith("manual") if latest else False,
        "fixture": data_mode == "fixture",
        "point_in_time": False,
        "quality_flags": [],
        "capabilities": {
            "CURRENT_STATE": _dimension_state(current, reason="No market bar is stored."),
            "DAILY_MARKET": _dimension_state(daily, reason="No daily bar is stored."),
            "MACRO_HISTORY": _dimension_state(
                False, reason="This is a market dataset, not a macro series."
            ),
            "POINT_IN_TIME": _dimension_state(
                False, reason="Market bars do not provide macro vintages."
            ),
            "EVENT_INTRADAY": _dimension_state(
                intraday, reason="No minute bars or event-linked intraday manifest."
            ),
            "HISTORICAL_REPLAY": _dimension_state(
                manifest_intraday,
                reason="Historical replay needs an event-linked minute manifest.",
            ),
            "SURPRISE_ELIGIBLE": _dimension_state(
                False, reason="Surprise is calculated from macro releases."
            ),
            "WORLD_STATE": _dimension_state(
                False, reason="Market bars confirm state but do not define it."
            ),
            "GLOBAL_MACRO": _dimension_state(
                False, reason="Market bars are not country macro data."
            ),
        },
    }


async def build_capability_inventory(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Return one honest capability record per observed dataset family."""

    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    freshness_payload = await build_data_freshness(engine, data_mode=data_mode, as_of=now)
    freshness_by_key = {str(item["canonical_key"]): item for item in freshness_payload["items"]}
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        series_rows = (
            await session.execute(
                select(Series, Provider)
                .join(Provider, Provider.id == Series.provider_id)
                .where(Series.active.is_(True))
            )
        ).all()
        observations = (
            await session.scalars(
                select(Observation).where(
                    Observation.data_mode == data_mode
                    if data_mode != "all"
                    else Observation.data_mode.in_(("observed", "fixture"))
                )
            )
        ).all()
        bars = (
            await session.scalars(
                select(MarketBar).where(
                    MarketBar.data_mode == data_mode
                    if data_mode != "all"
                    else MarketBar.data_mode.in_(("observed", "fixture"))
                )
            )
        ).all()
        instruments = (
            await session.scalars(select(MarketInstrument).where(MarketInstrument.active.is_(True)))
        ).all()
        manifests = (
            await session.scalars(
                select(MarketDataManifest).where(
                    MarketDataManifest.data_mode == data_mode
                    if data_mode != "all"
                    else MarketDataManifest.data_mode.in_(("observed", "fixture"))
                )
            )
        ).all()
        releases = (
            await session.scalars(
                select(MacroRelease).where(
                    MacroRelease.data_mode == data_mode
                    if data_mode != "all"
                    else MacroRelease.data_mode.in_(("observed", "fixture")),
                    MacroRelease.status != "invalidated",
                )
            )
        ).all()
        release_ids = [item.id for item in releases]
        values = (
            (
                await session.scalars(
                    select(ReleaseValue).where(ReleaseValue.macro_release_id.in_(release_ids))
                )
            ).all()
            if release_ids
            else []
        )
        consensus = (
            (
                await session.scalars(
                    select(ConsensusSnapshot).where(
                        ConsensusSnapshot.macro_release_id.in_(release_ids)
                    )
                )
            ).all()
            if release_ids
            else []
        )
        analysis_runs = (
            (
                await session.scalars(
                    select(AnalysisRun).where(AnalysisRun.macro_release_id.in_(release_ids))
                )
            ).all()
            if release_ids
            else []
        )
    observations_by_series: dict[Any, list[Observation]] = defaultdict(list)
    for observation in observations:
        observations_by_series[observation.series_id].append(observation)
    bars_by_instrument: dict[Any, list[MarketBar]] = defaultdict(list)
    for bar in bars:
        bars_by_instrument[bar.instrument_id].append(bar)
    manifests_by_instrument: dict[Any, list[MarketDataManifest]] = defaultdict(list)
    for manifest in manifests:
        manifests_by_instrument[manifest.instrument_id].append(manifest)
    items = [
        _series_item(
            series,
            provider,
            observations_by_series[series.id],
            freshness_by_key.get(series.canonical_key, {}),
            data_mode=data_mode,
        )
        for series, provider in series_rows
    ]
    items.extend(
        _market_item(
            instrument,
            bars_by_instrument[instrument.id],
            manifests_by_instrument[instrument.id],
            data_mode=data_mode,
            now=now,
        )
        for instrument in instruments
    )
    by_event: dict[str, list[MacroRelease]] = defaultdict(list)
    for release in releases:
        by_event[release.release_type].append(release)
    values_by_release = defaultdict(list)
    for value in values:
        values_by_release[value.macro_release_id].append(value)
    consensus_by_release = defaultdict(list)
    for snapshot in consensus:
        consensus_by_release[snapshot.macro_release_id].append(snapshot)
    analysis_by_release = defaultdict(list)
    for analysis_run in analysis_runs:
        analysis_by_release[analysis_run.macro_release_id].append(analysis_run)
    manifests_by_release = defaultdict(list)
    for manifest in manifests:
        manifests_by_release[manifest.macro_release_id].append(manifest)
    for event_type, event_releases in sorted(by_event.items()):
        actual_count = sum(len(values_by_release[item.id]) for item in event_releases)
        eligible_consensus = sum(
            1
            for release in event_releases
            for snapshot in consensus_by_release[release.id]
            if snapshot.captured_at < release.scheduled_at and snapshot.data_mode == data_mode
        )
        event_manifests = [
            manifest for release in event_releases for manifest in manifests_by_release[release.id]
        ]
        has_analysis = any(
            analysis_run.status == "completed" and analysis_run.reproducibility_status == "complete"
            for release in event_releases
            for analysis_run in analysis_by_release[release.id]
        )
        intraday = any(
            manifest.interval_seconds <= 60 and manifest.row_count > 0
            for manifest in event_manifests
        )
        items.append(
            {
                "dataset_key": f"event:{event_type}",
                "kind": "event",
                "canonical_key": event_type,
                "label": event_type,
                "entity": "USA" if event_type.startswith("US_") else None,
                "rows": len(event_releases),
                "coverage_start": min((item.scheduled_at for item in event_releases), default=None),
                "coverage_end": max((item.scheduled_at for item in event_releases), default=None),
                "latest_timestamp": max(
                    (item.released_at or item.scheduled_at for item in event_releases), default=None
                ),
                "latest_available_at": None,
                "freshness": {"status": "AVAILABLE", "score": None, "reason": None},
                "frequency": "event",
                "source_class": "official_or_manual",
                "provider": None,
                "source_url": None,
                "data_mode": data_mode,
                "proxy": False,
                "manual": False,
                "fixture": data_mode == "fixture",
                "point_in_time": bool(actual_count),
                "quality_flags": [],
                "capabilities": {
                    "CURRENT_STATE": _dimension_state(
                        bool(event_releases), reason="No release is stored."
                    ),
                    "DAILY_MARKET": _dimension_state(False, reason="Events are not market bars."),
                    "MACRO_HISTORY": _dimension_state(
                        len(event_releases) >= 2, reason="A history needs multiple releases."
                    ),
                    "POINT_IN_TIME": _dimension_state(
                        bool(actual_count), reason="No release actual is stored."
                    ),
                    "EVENT_INTRADAY": _dimension_state(
                        intraday, reason="No event-linked minute manifest is stored."
                    ),
                    "HISTORICAL_REPLAY": _dimension_state(
                        has_analysis and intraday,
                        reason="Replay needs a completed analysis and minute data.",
                    ),
                    "SURPRISE_ELIGIBLE": _dimension_state(
                        eligible_consensus > 0 and actual_count > 0,
                        reason="Requires actual plus a consensus captured before T0.",
                    ),
                    "WORLD_STATE": _dimension_state(
                        False, reason="Events feed research but do not define the state snapshot."
                    ),
                    "GLOBAL_MACRO": _dimension_state(
                        bool(event_releases), reason="No event calendar data is stored."
                    ),
                },
                "event_counts": {
                    "actual": actual_count,
                    "consensus_pre_t0": eligible_consensus,
                    "intraday_manifests": sum(
                        1 for manifest in event_manifests if manifest.interval_seconds <= 60
                    ),
                    "completed_analysis": sum(
                        1
                        for release in event_releases
                        for analysis_run in analysis_by_release[release.id]
                        if analysis_run.status == "completed"
                    ),
                },
            }
        )
    summary = {
        key: sum(1 for item in items if item["capabilities"][key]["available"])
        for key in CAPABILITY_KEYS
    }
    return {
        "as_of": now.isoformat(),
        "data_mode": data_mode,
        "methodology_version": "wst-capability-v1",
        "items": items,
        "summary": summary,
        "limitations": [
            (
                "Capabilities are derived from local rows and provenance; an observed row "
                "does not imply PIT or event-minute eligibility."
            ),
            "Market context bars remain separate from event-linked intraday manifests.",
        ],
    }


__all__ = ["CAPABILITY_KEYS", "build_capability_inventory"]
