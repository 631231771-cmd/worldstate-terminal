"""Canonical readiness checks for observed macro-event research."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.consensus_policy import (
    ConsensusEligibility as ConsensusEligibility,
)
from worldstate.application.consensus_policy import (
    evaluate_consensus_eligibility as evaluate_consensus_eligibility,
)
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
    consensus_eligibility: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["consensus_eligibility"] = list(self.consensus_eligibility)
        return payload


def evaluate_release_linked_minute_manifests(
    manifests: list[MarketDataManifest],
    *,
    data_mode: str,
) -> tuple[list[MarketDataManifest], list[dict[str, Any]]]:
    """Validate every release-linked one-minute manifest, without asset filtering."""

    eligible: list[MarketDataManifest] = []
    rejected: list[dict[str, Any]] = []
    for manifest in manifests:
        check = evaluate_stored_event_intraday_manifest(
            manifest.metadata_json,
            data_mode=data_mode,
            row_count=manifest.row_count,
            interval_seconds=manifest.interval_seconds,
            is_fixture=data_mode == "fixture",
        )
        if check["eligible"]:
            eligible.append(manifest)
        else:
            rejected.append(
                {"manifest_id": str(manifest.id), "reasons": check["reasons"]}
            )
    return eligible, rejected


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
        # Use the same canonical release-value selector as the analysis engine.
        # Actuals are release facts and may be captured after T0; consensus is
        # the only input constrained to pre-T0.
        from worldstate.application.analysis_orchestrator import (
            _artifact_lookup,
            select_analysis_inputs_from_rows,
        )

        artifacts = await _artifact_lookup(
            session,
            {row.source_artifact_id for row in values if row.source_artifact_id is not None}
            | {
                row.source_artifact_id
                for row in consensus
                if row.source_artifact_id is not None
            },
        )
        selected_values, _selected_consensus = select_analysis_inputs_from_rows(
            release,
            values=values,
            consensus=[],
            artifacts=artifacts,
        )
        actual_by_indicator = {
            indicator_id: row
            for (indicator_id, value_kind), row in selected_values.items()
            if value_kind == "actual"
        }
        consensus_by_indicator: dict[uuid.UUID, ConsensusSnapshot] = {}
        consensus_eligibility: list[dict[str, Any]] = []
        for consensus_row in consensus:
            eligibility = evaluate_consensus_eligibility(
                consensus_row,
                (
                    artifacts.get(consensus_row.source_artifact_id)
                    if consensus_row.source_artifact_id is not None
                    else None
                ),
                t0=t0,
                release_data_mode=mode,
                indicator_belongs_to_release=consensus_row.indicator_id
                in {row.id for row in indicator_rows},
            )
            consensus_eligibility.append(
                {
                    "indicator_id": str(consensus_row.indicator_id),
                    "captured_at": _aware(consensus_row.captured_at).isoformat(),
                    **eligibility.as_dict(),
                }
            )
            if eligibility.eligible:
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
                    )
                    .order_by(MarketDataManifest.created_at.desc())
                )
            ).all()
        )
        eligible_manifests, rejected_manifests = evaluate_release_linked_minute_manifests(
            manifests,
            data_mode=mode,
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
        if rejected_manifests:
            blockers.append("ineligible_release_linked_event_minute_manifest")

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
            consensus_eligibility=tuple(consensus_eligibility),
        )


__all__ = [
    "AnalysisReadiness",
    "ConsensusEligibility",
    "build_analysis_readiness",
    "evaluate_consensus_eligibility",
    "evaluate_release_linked_minute_manifests",
]
