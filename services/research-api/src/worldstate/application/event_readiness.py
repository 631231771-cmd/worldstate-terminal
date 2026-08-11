"""Canonical readiness checks for observed macro-event research."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.event_intraday_service import (
    evaluate_stored_event_intraday_manifest,
    resolve_release_t0,
)
from worldstate.db.models import (
    ConsensusSnapshot,
    Indicator,
    MacroRelease,
    MarketDataManifest,
    ReleaseStage,
    ReleaseValue,
)
from worldstate.macro_core.catalog import RELEASE_INDICATORS


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AnalysisReadiness:
    ready: bool
    release_inputs: dict[str, Any]
    surprise_inputs: dict[str, Any]
    market_inputs: dict[str, Any]
    blockers: tuple[str, ...]
    t0: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


async def build_analysis_readiness(
    engine: AsyncEngine,
    release_id: str,
    *,
    data_mode: str | None = None,
) -> AnalysisReadiness:
    """Return the structured gate used by both the UI and analysis command.

    Actual and consensus are matched per canonical indicator.  A global
    ``some actual`` + ``some consensus`` check is deliberately not sufficient.
    Market manifests are revalidated using the same persisted policy as the
    selector, keeping fixture/observed and legacy data isolated.
    """

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return AnalysisReadiness(
                False, {}, {}, {}, ("release_not_found",), None
            )
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            return AnalysisReadiness(False, {}, {}, {}, ("release_not_found",), None)
        mode = data_mode or release.data_mode
        stages = list(
            (
                await session.scalars(
                    select(ReleaseStage)
                    .where(ReleaseStage.macro_release_id == release.id)
                    .order_by(ReleaseStage.sequence)
                )
            ).all()
        )
        t0 = resolve_release_t0(release, stages)
        keys = RELEASE_INDICATORS.get(release.release_type, ())
        indicator_rows = list(
            (
                await session.scalars(
                    select(Indicator).where(Indicator.indicator_key.in_(keys))
                )
            ).all()
        )
        by_key = {row.indicator_key: row for row in indicator_rows}
        values = list(
            (
                await session.scalars(
                    select(ReleaseValue)
                    .where(
                        ReleaseValue.macro_release_id == release.id,
                        ReleaseValue.data_mode == mode,
                    )
                    .order_by(ReleaseValue.captured_at, ReleaseValue.id)
                )
            ).all()
        )
        consensus = list(
            (
                await session.scalars(
                    select(ConsensusSnapshot)
                    .where(
                        ConsensusSnapshot.macro_release_id == release.id,
                        ConsensusSnapshot.data_mode == mode,
                    )
                    .order_by(ConsensusSnapshot.captured_at, ConsensusSnapshot.id)
                )
            ).all()
        )
        actual_by_indicator: dict[uuid.UUID, ReleaseValue] = {}
        for value_row in values:
            if value_row.value_kind == "actual" and _aware(value_row.captured_at) <= t0:
                actual_by_indicator[value_row.indicator_id] = value_row
        consensus_by_indicator: dict[uuid.UUID, ConsensusSnapshot] = {}
        for consensus_row in consensus:
            if (
                _aware(consensus_row.captured_at) < t0
                and consensus_row.quality_grade in {"A", "B", "C"}
            ):
                consensus_by_indicator[consensus_row.indicator_id] = consensus_row

        required = [key for key in keys if key in by_key]
        missing_actual = [
            key for key in required if by_key[key].id not in actual_by_indicator
        ]
        missing_consensus = [
            key for key in required if by_key[key].id not in consensus_by_indicator
        ]
        matched = [
            key
            for key in required
            if by_key[key].id in actual_by_indicator and by_key[key].id in consensus_by_indicator
        ]

        manifests = list(
            (
                await session.scalars(
                    select(MarketDataManifest)
                    .where(
                        MarketDataManifest.macro_release_id == release.id,
                        MarketDataManifest.data_mode == mode,
                        MarketDataManifest.interval_seconds == 60,
                        MarketDataManifest.row_count > 0,
                    )
                    .order_by(MarketDataManifest.created_at.desc())
                )
            ).all()
        )
        eligible_manifests = []
        rejected_manifests = []
        for manifest in manifests:
            check = evaluate_stored_event_intraday_manifest(
                manifest.metadata_json,
                data_mode=mode,
                row_count=manifest.row_count,
                interval_seconds=manifest.interval_seconds,
                is_fixture=mode == "fixture",
            )
            if check["eligible"]:
                eligible_manifests.append(manifest)
            else:
                rejected_manifests.append(
                    {"manifest_id": str(manifest.id), "reasons": check["reasons"]}
                )

        blockers: list[str] = []
        if release.data_mode != mode:
            blockers.append("release_data_mode_mismatch")
        if missing_actual:
            blockers.append("missing_actual:" + ",".join(missing_actual))
        if missing_consensus:
            blockers.append("missing_pre_t0_consensus:" + ",".join(missing_consensus))
        if not matched:
            blockers.append("no_matched_indicator_actual_consensus")
        if not eligible_manifests:
            blockers.append("missing_eligible_event_minute_manifest")

        return AnalysisReadiness(
            ready=not blockers,
            release_inputs={
                "ready": not missing_actual,
                "required_indicators": required,
                "missing_actual": missing_actual,
                "available_actual": [key for key in required if key not in missing_actual],
            },
            surprise_inputs={
                "ready": bool(matched) and not missing_consensus,
                "required_indicators": required,
                "matched_indicators": matched,
                "missing_actual": missing_actual,
                "missing_consensus": missing_consensus,
                "point_in_time_cutoff": t0.isoformat(),
            },
            market_inputs={
                "ready": bool(eligible_manifests),
                "eligible_manifest_ids": [str(item.id) for item in eligible_manifests],
                "rejected_manifests": rejected_manifests,
                "required_granularity_seconds": 60,
            },
            blockers=tuple(blockers),
            t0=t0.isoformat(),
        )


__all__ = ["AnalysisReadiness", "build_analysis_readiness"]
