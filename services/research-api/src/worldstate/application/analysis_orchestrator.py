"""Analysis orchestration and transitional implementation services.

Public callers use the focused application modules.  This module owns the
transactional analysis workflow while the compatibility facade in events.py
preserves the pre-v0.4 import surface.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.ai_researcher.claims import deterministic_claims, validate_claims
from worldstate.application.data_foundation_service import redact_sensitive_text
from worldstate.application.event_intraday_service import resolve_release_t0
from worldstate.application.event_readiness import AnalysisReadiness, build_analysis_readiness
from worldstate.application.market_selection_service import select_release_market_data
from worldstate.config import repository_root
from worldstate.db.models import (
    AnalysisRun,
    ConsensusSnapshot,
    DataQualityRecord,
    DataReconciliationRecord,
    EventWindowDefinition,
    EventWindowResult,
    EvidenceItem,
    Explanation,
    FuturesContract,
    HistoricalMatch,
    Indicator,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    MarketInstrument,
    MarketReaction,
    Observation,
    ProviderRun,
    RegimeSnapshot,
    ReleaseStage,
    ReleaseValue,
    ReportArtifact,
    ResearchClaim,
    Series,
    SourceArtifact,
)
from worldstate.event_engine.explanation import build_structured_explanation
from worldstate.event_engine.surprise import (
    calculate_bundle_surprise,
    calculate_nfp_bundle_surprise,
    calculate_policy_bundle_surprise,
)
from worldstate.event_engine.types import (
    BundleSurprise,
    ComputedWindow,
    HistoricalCase,
    HistoricalSurpriseObservation,
    IndicatorInput,
)
from worldstate.event_engine.windows import (
    MINUTE_WINDOW_SPECS,
    WINDOW_SPECS,
    apply_direction_reversals,
    calculate_event_windows,
    calculate_session_close_windows,
    detect_earliest_reaction,
)
from worldstate.macro_core.catalog import (
    INDICATORS,
    RELEASE_INDICATORS,
)
from worldstate.macro_core.regimes import derive_regime
from worldstate.market_core.catalog import INSTRUMENTS
from worldstate.provider_kit import MarketBarRecord, generate_scenario_bars
from worldstate.research_engine.history import compare_historical_events, magnitude_bucket

METHODOLOGY_VERSION = "macro-event-engine-v0.7-live-global"
CODE_VERSION = "macro-research-terminal-v0.5"
_NAMESPACE = uuid.UUID("fbf59be7-d632-4f3c-a5a0-104425f478c2")


class AnalysisReadinessError(ValueError):
    """Raised when a release is not eligible for a completed analysis run."""

    def __init__(self, readiness: AnalysisReadiness) -> None:
        self.readiness = readiness
        super().__init__("analysis readiness blocked: " + "; ".join(readiness.blockers))


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _stable_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, value)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _release_t0(session: AsyncSession, release: MacroRelease) -> datetime:
    stages = list(
        (
            await session.scalars(
                select(ReleaseStage)
                .where(ReleaseStage.macro_release_id == release.id)
                .order_by(ReleaseStage.sequence)
            )
        ).all()
    )
    return resolve_release_t0(release, stages)


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _fixture_path() -> Path:
    return repository_root() / "data" / "fixtures" / "macro-research-demos.json"


def _load_demo_releases() -> list[dict[str, Any]]:
    document = json.loads(_fixture_path().read_text(encoding="utf-8"))
    releases = document.get("releases")
    if not isinstance(releases, list):
        raise ValueError("macro research demo file has no releases array")
    return [item for item in releases if isinstance(item, dict)]


async def _ensure_catalog(session: AsyncSession) -> None:
    existing_indicators = {
        row.indicator_key: row for row in (await session.scalars(select(Indicator))).all()
    }
    now = datetime.now(UTC)
    for indicator_definition in INDICATORS:
        existing_indicator = existing_indicators.get(indicator_definition.key)
        if existing_indicator is not None:
            existing_indicator.name = indicator_definition.name
            existing_indicator.family = indicator_definition.family
            existing_indicator.unit = indicator_definition.unit
            existing_indicator.periodicity = indicator_definition.periodicity
            existing_indicator.description = indicator_definition.description
            existing_indicator.hotter_when_higher = indicator_definition.hotter_when_higher
            existing_indicator.bundle_weight = indicator_definition.bundle_weight
            existing_indicator.active = True
            existing_indicator.metadata_json = {"catalog_version": CODE_VERSION}
            continue
        session.add(
            Indicator(
                id=_stable_uuid(f"indicator:{indicator_definition.key}"),
                indicator_key=indicator_definition.key,
                name=indicator_definition.name,
                family=indicator_definition.family,
                country="USA",
                unit=indicator_definition.unit,
                periodicity=indicator_definition.periodicity,
                description=indicator_definition.description,
                hotter_when_higher=indicator_definition.hotter_when_higher,
                bundle_weight=indicator_definition.bundle_weight,
                active=True,
                metadata_json={"catalog_version": CODE_VERSION},
                created_at=now,
                updated_at=now,
            )
        )

    existing_instruments = {
        row.canonical_key: row for row in (await session.scalars(select(MarketInstrument))).all()
    }
    for instrument_definition in INSTRUMENTS:
        instrument_metadata = {
            "catalog_version": CODE_VERSION,
            "derived": instrument_definition.is_derived,
            "input_datasets": list(instrument_definition.input_datasets),
            "formula": instrument_definition.formula,
            "calculation_version": instrument_definition.calculation_version,
        }
        existing_instrument = existing_instruments.get(instrument_definition.key)
        if existing_instrument is not None:
            existing_instrument.symbol = instrument_definition.symbol
            existing_instrument.title = instrument_definition.title
            existing_instrument.asset_class = instrument_definition.asset_class
            existing_instrument.instrument_type = instrument_definition.instrument_type
            existing_instrument.exchange = instrument_definition.exchange
            existing_instrument.quote_unit = instrument_definition.quote_unit
            existing_instrument.measurement_type = instrument_definition.measurement_type
            existing_instrument.source_timezone = instrument_definition.timezone
            existing_instrument.is_proxy = instrument_definition.is_proxy
            existing_instrument.proxy_for = instrument_definition.proxy_for
            existing_instrument.active = True
            existing_instrument.metadata_json = instrument_metadata
            continue
        session.add(
            MarketInstrument(
                id=_stable_uuid(f"instrument:{instrument_definition.key}"),
                canonical_key=instrument_definition.key,
                symbol=instrument_definition.symbol,
                title=instrument_definition.title,
                asset_class=instrument_definition.asset_class,
                instrument_type=instrument_definition.instrument_type,
                exchange=instrument_definition.exchange,
                quote_unit=instrument_definition.quote_unit,
                measurement_type=instrument_definition.measurement_type,
                source_timezone=instrument_definition.timezone,
                is_proxy=instrument_definition.is_proxy,
                proxy_for=instrument_definition.proxy_for,
                active=True,
                metadata_json=instrument_metadata,
                created_at=now,
                updated_at=now,
            )
        )
    existing_windows = set((await session.scalars(select(EventWindowDefinition.window_key))).all())
    for sequence, spec in enumerate(WINDOW_SPECS, start=1):
        if spec.key in existing_windows:
            continue
        session.add(
            EventWindowDefinition(
                window_key=spec.key,
                label=spec.label,
                start_offset_seconds=spec.start_seconds,
                end_offset_seconds=None if spec.session_based else spec.end_seconds,
                close_rule=spec.key if spec.session_based else None,
                anchor_stage_key="release",
                sequence=sequence,
                active=True,
                methodology_notes="WorldState canonical event-window definition.",
            )
        )
    await session.flush()


async def _seed_release(session: AsyncSession, fixture: dict[str, Any]) -> uuid.UUID:
    release_key = str(fixture["release_key"])
    existing = await session.scalar(
        select(MacroRelease).where(MacroRelease.release_key == release_key)
    )
    if existing is not None:
        return existing.id

    release_id = _stable_uuid(f"release:{release_key}")
    released_at = _as_datetime(str(fixture["released_at"]))
    source_json = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
    source_hash = hashlib.sha256(source_json.encode()).hexdigest()
    artifact_id = _stable_uuid(f"source-artifact:{release_key}")
    quality_id = _stable_uuid(f"quality:{release_key}:release")
    now = datetime.now(UTC)
    session.add(
        SourceArtifact(
            id=artifact_id,
            source_key=f"{release_key}:fixture-source",
            provider_key="worldstate_fixture",
            artifact_type="release_fixture",
            title=str(fixture["title"]),
            source_url=str(fixture["source_url"]),
            published_at=released_at,
            retrieved_at=now,
            content_hash=source_hash,
            license_name="Source-site terms apply",
            citation_text=f"{fixture['source_name']}: {fixture['source_url']}",
            is_fixture=True,
            data_mode="fixture",
            metadata_json={
                "fixture_file": "data/fixtures/macro-research-demos.json",
                "notice": "Official source family plus non-official research fixture fields.",
            },
        )
    )
    session.add(
        DataQualityRecord(
            id=quality_id,
            subject_type="macro_release",
            subject_id=str(release_id),
            source_name=str(fixture["source_name"]),
            source_url=str(fixture["source_url"]),
            source_type="traceable_fixture",
            acquired_at=now,
            is_manual=True,
            is_verified=False,
            is_fixture=True,
            is_proxy=False,
            latency_seconds=None,
            granularity_seconds=None,
            missing_reason=None,
            quality_grade="C",
            verification_notes=(
                "Bundled demo values must be re-verified before being used as a production "
                "historical observation. Source URL identifies the official release family."
            ),
            metadata_json={"fixture_file": "data/fixtures/macro-research-demos.json"},
        )
    )
    session.add(
        MacroRelease(
            id=release_id,
            release_key=release_key,
            release_type=str(fixture["release_type"]),
            title=str(fixture["title"]),
            country="USA",
            period_label=str(fixture["period_label"]),
            scheduled_at=released_at,
            released_at=released_at,
            source_timezone=str(fixture["source_timezone"]),
            status="released",
            data_version="fixture-v1",
            data_mode="fixture",
            source_artifact_id=artifact_id,
            primary_quality_id=quality_id,
            contamination_level=str(fixture["contamination_level"]),
            clean_window=bool(fixture["clean_window"]),
            overlapping_events=[],
            confounding_notes=list(fixture.get("confounding_notes", [])),
            metadata_json={
                "data_mode": "fixture",
                "fixture_file": "data/fixtures/macro-research-demos.json",
            },
        )
    )
    await session.flush()

    stage_ids: dict[str, uuid.UUID] = {}
    for sequence, stage in enumerate(fixture["stages"], start=1):
        stage_key = str(stage["key"])
        stage_id = _stable_uuid(f"release-stage:{release_key}:{stage_key}")
        stage_ids[stage_key] = stage_id
        stage_at = _as_datetime(str(stage["released_at"]))
        session.add(
            ReleaseStage(
                id=stage_id,
                macro_release_id=release_id,
                stage_key=stage_key,
                title=str(stage["title"]),
                sequence=sequence,
                scheduled_at=stage_at,
                released_at=stage_at,
                status="released",
                source_artifact_id=artifact_id,
                metadata_json={"fixture": True},
            )
        )
    await session.flush()

    indicators = {
        row.indicator_key: row
        for row in (
            await session.scalars(
                select(Indicator).where(
                    Indicator.indicator_key.in_(RELEASE_INDICATORS[str(fixture["release_type"])])
                )
            )
        ).all()
    }
    captured_at = released_at - timedelta(hours=12)
    for indicator_key, values in fixture["values"].items():
        indicator = indicators[indicator_key]
        stage_key = str(values.get("stage") or fixture["stages"][0]["key"])
        stage_id = stage_ids[stage_key]
        for value_kind in ("actual", "previous", "revised_previous"):
            value = values.get(value_kind)
            if value is None:
                continue
            session.add(
                ReleaseValue(
                    id=_stable_uuid(f"release-value:{release_key}:{indicator_key}:{value_kind}"),
                    macro_release_id=release_id,
                    release_stage_id=stage_id,
                    indicator_id=indicator.id,
                    value_kind=value_kind,
                    value=Decimal(str(value)),
                    raw_value=str(value),
                    data_version="fixture-v1",
                    valid_from=released_at,
                    captured_at=released_at,
                    is_initial=value_kind == "actual",
                    data_mode="fixture",
                    source_artifact_id=artifact_id,
                    quality_id=quality_id,
                    metadata_json={
                        "fixture": True,
                        "manual_coding": "tone_score" in indicator_key,
                    },
                )
            )
        session.add(
            ConsensusSnapshot(
                id=_stable_uuid(f"consensus:{release_key}:{indicator_key}"),
                macro_release_id=release_id,
                indicator_id=indicator.id,
                consensus_value=Decimal(str(values["consensus"])),
                source_name="WorldState pre-release consensus fixture",
                source_url=None,
                captured_at=captured_at,
                quality_grade="C",
                is_manual=True,
                data_mode="fixture",
                verification_notes=(
                    "Fixture snapshot captured before T0; replaceable provider boundary."
                ),
                source_artifact_id=artifact_id,
                quality_id=quality_id,
            )
        )
    await session.flush()

    instruments = {
        row.canonical_key: row for row in (await session.scalars(select(MarketInstrument))).all()
    }
    contract_codes = {
        "gold_gc": "GC-DEMO",
        "silver_si": "SI-DEMO",
        "wti_cl": "CL-DEMO",
        "sp500_es": "ES-DEMO",
        "nasdaq_nq": "NQ-DEMO",
        "ust2y_zt": "ZT-DEMO",
        "ust10y_zn": "ZN-DEMO",
        "dollar_dxy": "DX-DEMO",
        "eurusd": "SPOT",
        "usdjpy": "SPOT",
        "vix": "VX-DEMO",
    }
    contract_ids: dict[str, uuid.UUID | None] = {}
    for key, instrument in instruments.items():
        code = contract_codes.get(key, "DEMO")
        if instrument.instrument_type not in {"futures", "futures_proxy"}:
            contract_ids[key] = None
            continue
        existing_contract = await session.scalar(
            select(FuturesContract).where(
                FuturesContract.instrument_id == instrument.id,
                FuturesContract.contract_code == code,
            )
        )
        if existing_contract is None:
            existing_contract = FuturesContract(
                id=_stable_uuid(f"contract:{key}:{code}"),
                instrument_id=instrument.id,
                contract_code=code,
                provider_symbol=f"FIXTURE:{instrument.symbol}",
                first_trade_date=None,
                last_trade_date=None,
                expiry_date=None,
                roll_start_at=None,
                roll_end_at=None,
                is_proxy=instrument.is_proxy,
                metadata_json={
                    "fixture": True,
                    "roll_policy": "explicit_non_tradable_demo_contract",
                },
            )
            session.add(existing_contract)
            await session.flush()
        contract_ids[key] = existing_contract.id

    stage_times = {
        str(stage["key"]): _as_datetime(str(stage["released_at"])) for stage in fixture["stages"]
    }
    for key, instrument in instruments.items():
        shocks: list[tuple[datetime, float]] = []
        for stage_key, stage_values in fixture["stage_shocks"].items():
            if key in stage_values:
                shocks.append((stage_times[stage_key], float(stage_values[key])))
        if not shocks:
            continue
        bar_quality_id = _stable_uuid(f"quality:{release_key}:bars:{key}")
        session.add(
            DataQualityRecord(
                id=bar_quality_id,
                subject_type="market_bar_batch",
                subject_id=str(release_id),
                source_name="WorldState deterministic market fixture",
                source_url=None,
                source_type="fixture",
                acquired_at=now,
                is_manual=False,
                is_verified=True,
                is_fixture=True,
                is_proxy=instrument.is_proxy,
                latency_seconds=0,
                granularity_seconds=60,
                missing_reason=None,
                quality_grade="C",
                verification_notes=(
                    "Illustrative path for engine validation; not exchange-recorded prices."
                ),
                metadata_json={"scenario_key": release_key, "instrument_key": key},
            )
        )
        bars = generate_scenario_bars(
            scenario_key=release_key,
            instrument_key=key,
            symbol=instrument.symbol,
            contract_code=contract_codes[key],
            stages=shocks,
        )
        session.add_all(
            [
                MarketBar(
                    instrument_id=instrument.id,
                    futures_contract_id=contract_ids[key],
                    timestamp=bar.timestamp,
                    interval_seconds=bar.interval_seconds,
                    open_value=bar.open_value,
                    high_value=bar.high_value,
                    low_value=bar.low_value,
                    close_value=bar.close_value,
                    volume=bar.volume,
                    provider_key="fixture",
                    data_mode="fixture",
                    source_symbol=bar.source_symbol,
                    contract_code=bar.contract_code or "",
                    is_regular_session=None,
                    quality_id=bar_quality_id,
                    fetched_at=now,
                    metadata_json=bar.metadata,
                )
                for bar in bars
            ]
        )
        manifest_hash = hashlib.sha256(
            (
                f"fixture:{release_id}:{instrument.id}:{contract_ids[key]}:"
                f"{bars[0].timestamp.isoformat()}:{bars[-1].timestamp.isoformat()}"
            ).encode()
        ).hexdigest()
        session.add(
            MarketDataManifest(
                id=_stable_uuid(f"market-manifest:{release_key}:{key}:ohlcv-1m"),
                manifest_hash=manifest_hash,
                macro_release_id=release_id,
                release_stage_id=stage_ids[str(fixture["stages"][0]["key"])],
                provider_key="fixture",
                dataset="WORLDSTATE.FIXTURE",
                schema_name="ohlcv-1m",
                instrument_id=instrument.id,
                futures_contract_id=contract_ids[key],
                source_symbol=bars[0].source_symbol,
                contract_code=bars[0].contract_code,
                start_at=bars[0].timestamp,
                end_at=bars[-1].timestamp,
                interval_seconds=60,
                row_count=len(bars),
                size_bytes=None,
                data_mode="fixture",
                quality_grade="C",
                is_aggregated=False,
                aggregation_method=None,
                aggregation_version=None,
                contract_selection_rule="deterministic fixture contract at T0",
                continuous_resolution_json={},
                roll_status="fixture",
                estimated_cost_usd=Decimal("0"),
                actual_cost_usd=Decimal("0"),
                provider_run_id=None,
                sync_job_run_id=None,
                source_artifact_id=artifact_id,
                metadata_json={
                    "fixture": True,
                    "no_cross_contract_splice": True,
                    "source_content_hash": manifest_hash,
                    "is_fixture": True,
                    "event_intraday_eligibility": "eligible",
                    "event_intraday_eligibility_v1": {
                        "policy_version": "event-intraday-v1",
                        "status": "eligible",
                        "eligible": True,
                        "data_mode": "fixture",
                        "is_fixture": True,
                        "window_coverage": {},
                    },
                },
            )
        )
    session.add(
        ProviderRun(
            id=_stable_uuid(f"provider-run:{release_key}:fixture-seed"),
            provider_key="worldstate_fixture",
            operation="seed_release_and_market_bars",
            status="completed",
            started_at=now,
            completed_at=now,
            records_read=1,
            records_written=1,
            source_artifact_id=artifact_id,
            data_mode="fixture",
            idempotency_key=f"fixture-seed:{release_key}",
            request_count=0,
            estimated_cost_usd=Decimal("0"),
            actual_cost_usd=Decimal("0"),
            terms_url=None,
            quality_grade="C",
            input_json={"release_key": release_key},
            output_json={"data_mode": "fixture"},
            warnings_json=["Fixture data must never be presented as live or official market data."],
            error_message=None,
        )
    )
    await session.flush()
    return release_id


async def bootstrap_research_data(engine: AsyncEngine) -> dict[str, object]:
    """Ensure catalogs and three visible demo workflows exist."""

    created: list[uuid.UUID] = []
    factory = _factory(engine)
    async with factory() as session, session.begin():
        await _ensure_catalog(session)
        for fixture in _load_demo_releases():
            release_id = await _seed_release(session, fixture)
            current_run = await session.scalar(
                select(AnalysisRun.id).where(
                    AnalysisRun.macro_release_id == release_id,
                    AnalysisRun.code_version == CODE_VERSION,
                    AnalysisRun.status == "completed",
                )
            )
            if current_run is None:
                created.append(release_id)
        for release_type in ("US_CPI", "US_NFP", "FOMC"):
            latest_release = await session.scalar(
                select(MacroRelease)
                .where(MacroRelease.release_type == release_type)
                .where(MacroRelease.data_mode == "fixture")
                .order_by(MacroRelease.scheduled_at.desc())
            )
            if latest_release is None:
                continue
            current_run = await session.scalar(
                select(AnalysisRun.id).where(
                    AnalysisRun.macro_release_id == latest_release.id,
                    AnalysisRun.code_version == CODE_VERSION,
                    AnalysisRun.status == "completed",
                )
            )
            if current_run is None and latest_release.id not in created:
                created.append(latest_release.id)
    for release_id in created:
        await analyze_release(engine, str(release_id))

    async with factory() as session:
        counts = {
            "releases": int(
                (await session.scalar(select(func.count()).select_from(MacroRelease))) or 0
            ),
            "analysis_runs": int(
                (await session.scalar(select(func.count()).select_from(AnalysisRun))) or 0
            ),
            "market_bars": int(
                (await session.scalar(select(func.count()).select_from(MarketBar))) or 0
            ),
        }
    return {"state": "ready", "created_release_ids": [str(item) for item in created], **counts}


async def initialize_research_catalog(engine: AsyncEngine) -> None:
    """Seed only stable indicator/instrument/window catalogs, never demo releases."""

    factory = _factory(engine)
    async with factory() as session, session.begin():
        await _ensure_catalog(session)


def _value_source_priority(provider_key: str) -> int:
    if provider_key in {"bls_official", "federal_reserve_fomc"}:
        return 50
    if provider_key == "trading_economics":
        return 40
    if provider_key == "manual":
        return 30
    if "csv" in provider_key:
        return 20
    if provider_key in {"worldstate_fixture", "fixture"}:
        return 10
    return 15


async def _artifact_lookup(
    session: AsyncSession,
    artifact_ids: set[uuid.UUID],
) -> dict[uuid.UUID, SourceArtifact]:
    if not artifact_ids:
        return {}
    return {
        row.id: row
        for row in (
            await session.scalars(select(SourceArtifact).where(SourceArtifact.id.in_(artifact_ids)))
        ).all()
    }


def _artifact_for(
    artifact_id: uuid.UUID | None,
    artifacts: dict[uuid.UUID, SourceArtifact],
) -> SourceArtifact | None:
    return artifacts.get(artifact_id) if artifact_id is not None else None


def _select_release_values(
    rows: list[ReleaseValue],
    artifacts: dict[uuid.UUID, SourceArtifact],
) -> dict[tuple[uuid.UUID, str], ReleaseValue]:
    grouped: dict[tuple[uuid.UUID, str], list[ReleaseValue]] = defaultdict(list)
    for row in rows:
        if row.metadata_json.get("superseded"):
            continue
        if (
            row.metadata_json.get("historical_initial_status")
            == "not_reconstructable_from_current_bls_api"
        ):
            continue
        # Event surprise uses the first published actual. Later revisions stay
        # queryable but may never replace the event-time actual in a replay.
        if row.value_kind == "actual" and not row.is_initial:
            continue
        grouped[(row.indicator_id, row.value_kind)].append(row)

    selected: dict[tuple[uuid.UUID, str], ReleaseValue] = {}
    for identity, candidates in grouped.items():
        selected[identity] = max(
            candidates,
            key=lambda row: (
                _value_source_priority(
                    artifact.provider_key
                    if (artifact := _artifact_for(row.source_artifact_id, artifacts))
                    else "unknown"
                ),
                -_aware(row.captured_at).timestamp(),
                str(row.id),
            ),
        )
    return selected


def _consensus_priority(
    snapshot: ConsensusSnapshot,
    artifact: SourceArtifact | None,
) -> int:
    source = snapshot.source_name.lower()
    provider_key = artifact.provider_key if artifact is not None else ""
    # The same licensed response bytes can legitimately be observed by both a
    # current capture and a historical PIT query. SourceArtifact deduplication
    # therefore cannot carry snapshot-level PIT semantics: use the immutable
    # metadata stored on the ConsensusSnapshot itself.
    pit_verified = bool(snapshot.metadata_json.get("pit_verified"))
    if provider_key == "trading_economics" or "trading economics" in source:
        return 50 if pit_verified else 35
    if snapshot.is_manual:
        if "csv" in source:
            return 25
        return 40 if snapshot.quality_grade.upper() in {"A", "B"} else 20
    if "fixture" in source:
        return 10
    return 30


def _select_consensus_snapshots(
    rows: list[ConsensusSnapshot],
    artifacts: dict[uuid.UUID, SourceArtifact],
) -> dict[uuid.UUID, ConsensusSnapshot]:
    grouped: dict[uuid.UUID, list[ConsensusSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[row.indicator_id].append(row)
    return {
        indicator_id: max(
            candidates,
            key=lambda snapshot: (
                _consensus_priority(
                    snapshot,
                    _artifact_for(snapshot.source_artifact_id, artifacts),
                ),
                _aware(snapshot.captured_at).timestamp(),
                str(snapshot.id),
            ),
        )
        for indicator_id, candidates in grouped.items()
    }


async def _pre_event_regime_context(
    session: AsyncSession,
    cutoff: datetime,
    *,
    data_mode: str,
) -> dict[str, object]:
    """Build a strictly pre-event PIT context from stored FRED/ALFRED vintages."""

    native_ids = {"DGS2", "DGS10", "DFII10", "DTWEXBGS", "VIXCLS"}
    rows = (
        await session.execute(
            select(Series.native_id, Observation)
            .join(Observation, Observation.series_id == Series.id)
            .where(
                Series.native_id.in_(native_ids),
                Observation.data_mode == data_mode,
                Observation.value.is_not(None),
                Observation.period_start < cutoff.date(),
                Observation.vintage_date <= cutoff.date(),
                Observation.available_at.is_not(None),
                Observation.available_at < cutoff,
            )
            .order_by(
                Series.native_id,
                Observation.period_start,
                Observation.vintage_date,
            )
        )
    ).all()
    by_series_period: dict[tuple[str, object], Observation] = {}
    for native_id, observation in rows:
        by_series_period[(str(native_id), observation.period_start)] = observation
    histories: dict[str, list[Observation]] = defaultdict(list)
    for (native_id, _period), observation in by_series_period.items():
        histories[native_id].append(observation)
    for history in histories.values():
        history.sort(key=lambda item: item.period_start)

    context: dict[str, object] = {
        "as_of": cutoff.isoformat(),
        "source": f"FRED/ALFRED stored point-in-time {data_mode} observations",
        "data_mode": data_mode,
        "series": {},
    }
    serialized_series: dict[str, object] = {}
    aliases = {
        "DGS2": "two_year_yield",
        "DGS10": "ten_year_yield",
        "DFII10": "ten_year_real_yield",
        "DTWEXBGS": "broad_dollar_index",
        "VIXCLS": "vix_close",
    }
    for native_id, alias in aliases.items():
        history = histories.get(native_id, [])
        if not history:
            continue
        latest = history[-1]
        lookback = history[-21] if len(history) >= 21 else history[0]
        latest_value = float(latest.value) if latest.value is not None else None
        lookback_value = float(lookback.value) if lookback.value is not None else None
        change = (
            latest_value - lookback_value
            if latest_value is not None and lookback_value is not None
            else None
        )
        percent_change = (
            change / abs(lookback_value) * 100
            if change is not None and lookback_value is not None and lookback_value != 0
            else None
        )
        context[alias] = latest_value
        context[f"{alias}_change_20"] = change
        context[f"{alias}_change_20_percent"] = percent_change
        serialized_series[native_id] = {
            "value": latest_value,
            "period_start": latest.period_start.isoformat(),
            "vintage_date": latest.vintage_date.isoformat(),
            "available_at": (
                _aware(latest.available_at).isoformat() if latest.available_at else None
            ),
            "lookback_period_start": lookback.period_start.isoformat(),
            "source_hash": latest.source_hash,
        }
    context["series"] = serialized_series
    context["missing_series"] = sorted(native_ids - set(histories))
    return context


async def select_analysis_inputs(
    session: AsyncSession,
    release: MacroRelease,
) -> tuple[
    dict[tuple[uuid.UUID, str], ReleaseValue],
    dict[uuid.UUID, ConsensusSnapshot],
    dict[uuid.UUID, SourceArtifact],
]:
    """Select the exact point-in-time actual and consensus inputs used by analysis."""

    cutoff = await _release_t0(session, release)
    values = list(
        (
            await session.scalars(
                select(ReleaseValue)
                .where(
                    ReleaseValue.macro_release_id == release.id,
                    ReleaseValue.data_mode == release.data_mode,
                )
                .order_by(ReleaseValue.captured_at)
            )
        ).all()
    )
    consensus = list(
        (
            await session.scalars(
                select(ConsensusSnapshot)
                .where(
                    ConsensusSnapshot.macro_release_id == release.id,
                    ConsensusSnapshot.data_mode == release.data_mode,
                    ConsensusSnapshot.captured_at < cutoff,
                    ConsensusSnapshot.quality_grade.in_(("A", "B", "C")),
                )
                .order_by(ConsensusSnapshot.captured_at)
            )
        ).all()
    )
    artifacts = await _artifact_lookup(
        session,
        {row.source_artifact_id for row in values if row.source_artifact_id is not None}
        | {row.source_artifact_id for row in consensus if row.source_artifact_id is not None},
    )
    selected_values, selected_consensus = select_analysis_inputs_from_rows(
        release,
        values=values,
        consensus=consensus,
        artifacts=artifacts,
    )
    return selected_values, selected_consensus, artifacts


def select_analysis_inputs_from_rows(
    release: MacroRelease,
    *,
    values: list[ReleaseValue],
    consensus: list[ConsensusSnapshot],
    artifacts: dict[uuid.UUID, SourceArtifact],
) -> tuple[
    dict[tuple[uuid.UUID, str], ReleaseValue],
    dict[uuid.UUID, ConsensusSnapshot],
]:
    """Apply the analysis input policy to an already-loaded release batch.

    Coverage reporting uses this same selector so a row being stored cannot be
    confused with the row being eligible for point-in-time analysis.
    """

    cutoff = _aware(release.released_at or release.scheduled_at)
    eligible_values = [
        row
        for row in values
        if row.macro_release_id == release.id and row.data_mode == release.data_mode
    ]
    eligible_consensus = [
        row
        for row in consensus
        if row.macro_release_id == release.id
        and row.data_mode == release.data_mode
        and _aware(row.captured_at) < cutoff
        and row.quality_grade in {"A", "B", "C"}
    ]
    return (
        _select_release_values(eligible_values, artifacts),
        _select_consensus_snapshots(eligible_consensus, artifacts),
    )


async def _value_inputs(
    session: AsyncSession,
    release: MacroRelease,
) -> tuple[list[IndicatorInput], dict[str, dict[str, object]], dict[str, Indicator]]:
    keys = RELEASE_INDICATORS.get(release.release_type, ())
    indicator_rows = (
        await session.scalars(select(Indicator).where(Indicator.indicator_key.in_(keys)))
    ).all()
    indicators = {row.indicator_key: row for row in indicator_rows}
    latest_values, latest_consensus, input_artifacts = await select_analysis_inputs(
        session, release
    )

    inputs: list[IndicatorInput] = []
    serialized: dict[str, dict[str, object]] = {}
    for key in keys:
        indicator = indicators.get(key)
        if indicator is None:
            continue
        actual = latest_values.get((indicator.id, "actual"))
        previous = latest_values.get((indicator.id, "previous"))
        revised = latest_values.get((indicator.id, "revised_previous"))
        snapshot = latest_consensus.get(indicator.id)
        inputs.append(
            IndicatorInput(
                key=key,
                title=indicator.name,
                actual=actual.value if actual else None,
                consensus=snapshot.consensus_value if snapshot else None,
                previous=previous.value if previous else None,
                revised_previous=revised.value if revised else None,
                weight=indicator.bundle_weight,
                hotter_when_higher=indicator.hotter_when_higher,
            )
        )
        serialized[key] = {
            "indicator_id": str(indicator.id),
            "name": indicator.name,
            "unit": indicator.unit,
            "actual": _float(actual.value) if actual else None,
            "consensus": _float(snapshot.consensus_value) if snapshot else None,
            "previous": _float(previous.value) if previous else None,
            "revised_previous": _float(revised.value) if revised else None,
            "consensus_source": snapshot.source_name if snapshot else None,
            "actual_source": (
                artifact.provider_key
                if actual
                and (artifact := _artifact_for(actual.source_artifact_id, input_artifacts))
                else None
            ),
            "actual_release_value_id": str(actual.id) if actual else None,
            "consensus_snapshot_id": str(snapshot.id) if snapshot else None,
            "consensus_captured_at": (
                _aware(snapshot.captured_at).isoformat() if snapshot else None
            ),
        }
    return inputs, serialized, indicators


def _bundle(
    release_type: str,
    inputs: list[IndicatorInput],
    *,
    historical_surprises: dict[str, list[HistoricalSurpriseObservation]] | None = None,
    released_at: datetime | None = None,
) -> BundleSurprise:
    if release_type == "US_CPI":
        return calculate_bundle_surprise(
            inputs, historical_surprises=historical_surprises, current_release_at=released_at
        )
    if release_type == "US_NFP":
        return calculate_nfp_bundle_surprise(
            inputs, historical_surprises=historical_surprises, current_release_at=released_at
        )
    return calculate_policy_bundle_surprise(
        inputs, historical_surprises=historical_surprises, current_release_at=released_at
    )


async def _historical_surprises(
    session: AsyncSession, release: MacroRelease, indicators: dict[str, Indicator]
) -> dict[str, list[HistoricalSurpriseObservation]]:
    """Load only contemporaneous historical actual/consensus pairs before T0."""
    cutoff = await _release_t0(session, release)
    historical = (
        await session.scalars(
            select(MacroRelease)
            .where(
                MacroRelease.release_type == release.release_type,
                MacroRelease.id != release.id,
                MacroRelease.released_at < cutoff,
                MacroRelease.data_mode == release.data_mode,
                MacroRelease.status != "invalidated",
            )
            .order_by(MacroRelease.released_at)
        )
    ).all()
    output: dict[str, list[HistoricalSurpriseObservation]] = {key: [] for key in indicators}
    for prior in historical:
        selected_values, selected_consensus, _artifacts = await select_analysis_inputs(
            session, prior
        )
        for key, indicator in indicators.items():
            actual = selected_values.get((indicator.id, "actual"))
            consensus = selected_consensus.get(indicator.id)
            if actual and consensus and actual.value is not None:
                output[key].append(
                    HistoricalSurpriseObservation(
                        _aware(prior.released_at or prior.scheduled_at),
                        float(actual.value - consensus.consensus_value),
                    )
                )
    return output


def _bar_record(row: MarketBar, instrument_key: str) -> MarketBarRecord:
    return MarketBarRecord(
        instrument_key=instrument_key,
        timestamp=_aware(row.timestamp),
        interval_seconds=row.interval_seconds,
        open_value=row.open_value,
        high_value=row.high_value,
        low_value=row.low_value,
        close_value=row.close_value,
        volume=row.volume,
        source_symbol=row.source_symbol,
        contract_code=row.contract_code or None,
        metadata=row.metadata_json,
    )


async def _historical_cases(
    session: AsyncSession,
    release: MacroRelease,
) -> list[HistoricalCase]:
    releases = (
        await session.scalars(
            select(MacroRelease).where(
                MacroRelease.release_type == release.release_type,
                MacroRelease.data_mode == release.data_mode,
                MacroRelease.status != "invalidated",
            )
        )
    ).all()
    output: list[HistoricalCase] = []
    for candidate in releases:
        if candidate.id == release.id or _aware(
            candidate.released_at or candidate.scheduled_at
        ) >= _aware(release.released_at or release.scheduled_at):
            continue
        run = await session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.macro_release_id == candidate.id,
                AnalysisRun.status == "completed",
            )
            .order_by(AnalysisRun.completed_at.desc())
        )
        if run is None:
            continue
        regime = (
            await session.get(RegimeSnapshot, run.regime_snapshot_id)
            if run.regime_snapshot_id
            else None
        )
        rows = (
            await session.execute(
                select(EventWindowResult, EventWindowDefinition, MarketInstrument)
                .join(
                    EventWindowDefinition,
                    EventWindowDefinition.id == EventWindowResult.window_definition_id,
                )
                .join(
                    MarketInstrument,
                    MarketInstrument.id == EventWindowResult.instrument_id,
                )
                .where(
                    EventWindowResult.analysis_run_id == run.id,
                    EventWindowDefinition.window_key == "post_5m",
                )
            )
        ).all()
        returns = {
            f"{instrument.canonical_key}:post_5m": window.return_percent
            for window, _definition, instrument in rows
        }
        score = run.composite_surprise_score
        direction = (
            "hot" if score and score > 0.25 else "cold" if score and score < -0.25 else "mixed"
        )
        output.append(
            HistoricalCase(
                event_id=str(candidate.id),
                release_at=_aware(candidate.released_at or candidate.scheduled_at),
                classification=run.composite_classification,
                direction=direction,
                magnitude_bucket=magnitude_bucket(score),
                core_direction=str(run.parameters_json.get("component_direction", direction)),
                regime_tags=tuple(regime.labels_json) if regime else (),
                contamination_level=candidate.contamination_level,
                clean_window=candidate.clean_window,
                returns=returns,
                release_type=candidate.release_type,
                regime_dimensions=dict(regime.dimensions_json) if regime else {},
                analysis_run_id=str(run.id),
                is_fixture=run.data_mode == "fixture",
                proxy_instrument_count=sum(
                    1 for _window, _definition, instrument in rows if instrument.is_proxy
                ),
            )
        )
    return output


async def _execute_analysis(engine: AsyncEngine, release_id: str) -> str:
    """Append one analysis run and all of its evidence-bound artifacts."""

    release_uuid = uuid.UUID(release_id)
    factory = _factory(engine)
    async with factory() as session, session.begin():
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            raise LookupError("macro release not found")
        if release.status == "invalidated":
            raise LookupError("macro release was invalidated by provider reconciliation")
        started_at = datetime.now(UTC)
        run = AnalysisRun(
            id=uuid.uuid4(),
            macro_release_id=release.id,
            methodology_version=METHODOLOGY_VERSION,
            code_version=CODE_VERSION,
            status="running",
            started_at=started_at,
            completed_at=None,
            regime_snapshot_id=None,
            composite_classification="pending",
            composite_surprise_score=None,
            confidence=0.0,
            facts_json=[],
            earliest_reactions_json=[],
            data_gaps_json=[],
            parameters_json={},
            data_mode=release.data_mode,
        )
        session.add(run)
        await session.flush()

        inputs, serialized_values, indicator_rows = await _value_inputs(session, release)
        history = await _historical_surprises(session, release, indicator_rows)
        bundle = _bundle(
            release.release_type,
            inputs,
            historical_surprises=history,
            released_at=_aware(release.released_at or release.scheduled_at),
        )
        stages = (
            await session.scalars(
                select(ReleaseStage)
                .where(ReleaseStage.macro_release_id == release.id)
                .order_by(ReleaseStage.sequence)
            )
        ).all()
        instruments = (
            await session.scalars(
                select(MarketInstrument)
                .where(MarketInstrument.active.is_(True))
                .order_by(MarketInstrument.canonical_key)
            )
        ).all()
        window_definitions = {
            row.window_key: row
            for row in (
                await session.scalars(
                    select(EventWindowDefinition)
                    .where(EventWindowDefinition.active.is_(True))
                    .order_by(EventWindowDefinition.sequence)
                )
            ).all()
        }
        if not stages:
            raise ValueError("release has no stages")
        release_t0 = resolve_release_t0(release, list(stages))
        market_selection = await select_release_market_data(session, release, list(stages))
        instruments_by_id = {row.id: row for row in instruments}
        selected_instrument_ids = {
            instrument_id for instrument_id, _interval in market_selection.series
        }
        instruments = [row for row in instruments if row.id in selected_instrument_ids]
        market_manifest = [
            series.snapshot(
                instrument_key=(
                    instruments_by_id[series.instrument_id].canonical_key
                    if series.instrument_id in instruments_by_id
                    else str(series.instrument_id)
                )
            )
            for _identity, series in sorted(
                market_selection.series.items(),
                key=lambda item: (
                    instruments_by_id[item[0][0]].canonical_key
                    if item[0][0] in instruments_by_id
                    else str(item[0][0]),
                    item[0][1],
                ),
            )
        ]
        bars = [
            bar
            for _identity, series in sorted(
                market_selection.series.items(),
                key=lambda item: (str(item[0][0]), item[0][1]),
            )
            for bar in series.bars
        ]

        release_values = (
            await session.scalars(
                select(ReleaseValue)
                .where(ReleaseValue.macro_release_id == release.id)
                .where(ReleaseValue.data_mode == release.data_mode)
                .order_by(ReleaseValue.captured_at, ReleaseValue.id)
            )
        ).all()
        consensus_rows = (
            await session.scalars(
                select(ConsensusSnapshot)
                .where(
                    ConsensusSnapshot.macro_release_id == release.id,
                    ConsensusSnapshot.data_mode == release.data_mode,
                    ConsensusSnapshot.captured_at < release_t0,
                )
                .order_by(ConsensusSnapshot.captured_at, ConsensusSnapshot.id)
            )
        ).all()
        market_hash = _stable_hash(market_manifest)
        regime_context = await _pre_event_regime_context(
            session,
            _aware(release.released_at or release.scheduled_at),
            data_mode=release.data_mode,
        )
        release_snapshot = {
            "release_id": str(release.id),
            "release_key": release.release_key,
            "release_type": release.release_type,
            "data_mode": release.data_mode,
            "scheduled_at": _aware(release.scheduled_at).isoformat(),
            "released_at": release_t0.isoformat(),
            "contamination_level": release.contamination_level,
            "clean_window": release.clean_window,
            "values": serialized_values,
            "surprise_history": {
                key: [
                    {"released_at": item.released_at.isoformat(), "raw_surprise": item.raw_surprise}
                    for item in observations
                ]
                for key, observations in history.items()
            },
            "pre_event_regime_context": regime_context,
        }
        algorithm_versions = {
            "surprise": "surprise-v0.5",
            "history": "macro-history-v0.5-mode-isolated",
            "windows": "manifest-isolated-mixed-granularity-v0.5",
            "market_selection": "release-manifest-series-v1",
        }
        rule_versions = {
            "regime": "macro-regime-v0.5-pre-event-pit",
            "explanation": "deterministic-explanation-v3",
        }
        analysis_parameters = {
            "minimum_z_score_sample": 20,
            "historical_data_mode": release.data_mode,
            "calendar_precision": "exchange_session_lite",
            "long_window_policy": (
                "provider session-close when declared; UTC-day daily bars are experimental"
            ),
            "contamination_policy": "exclude_high_penalize_mismatch_v1",
        }
        run.release_snapshot_json = release_snapshot
        run.release_value_ids_json = [str(row.id) for row in release_values]
        run.consensus_snapshot_ids_json = [str(row.id) for row in consensus_rows]
        run.release_stage_ids_json = [str(row.id) for row in stages]
        run.market_dataset_manifest_json = market_manifest
        run.market_dataset_hash = market_hash
        run.provider_manifest_json = [
            {
                "provider_key": series.provider_key,
                "instrument_id": str(series.instrument_id),
                "interval_seconds": series.interval_seconds,
                "dataset": series.dataset,
                "schema_name": series.schema_name,
                "source_symbol": series.source_symbol,
                "contract_code": series.contract_code,
                "futures_contract_id": (
                    str(series.futures_contract_id) if series.futures_contract_id else None
                ),
                "manifest_ids": [str(item) for item in series.manifest_ids],
            }
            for _identity, series in sorted(
                market_selection.series.items(),
                key=lambda item: (str(item[0][0]), item[0][1]),
            )
        ]
        run.source_artifact_ids_json = sorted(
            {str(row.source_artifact_id) for row in release_values if row.source_artifact_id}
            | {
                str(manifest.source_artifact_id)
                for series in market_selection.series.values()
                for manifest in series.manifests
                if manifest.source_artifact_id
            }
        )
        run.algorithm_versions_json = algorithm_versions
        run.rule_versions_json = rule_versions
        run.analysis_parameters_json = analysis_parameters
        run.config_hash = _stable_hash(
            {
                "algorithms": algorithm_versions,
                "rules": rule_versions,
                "parameters": analysis_parameters,
            }
        )
        run.input_snapshot_hash = _stable_hash(
            {
                "release": release_snapshot,
                "release_value_ids": run.release_value_ids_json,
                "consensus_snapshot_ids": run.consensus_snapshot_ids_json,
                "stage_ids": run.release_stage_ids_json,
                "market_hash": market_hash,
                "config_hash": run.config_hash,
            }
        )
        run.reproducibility_status = "complete"

        quality_ids = {bar.quality_id for bar in bars if bar.quality_id is not None}
        if release.primary_quality_id:
            quality_ids.add(release.primary_quality_id)
        quality_rows = (
            (
                await session.scalars(
                    select(DataQualityRecord).where(DataQualityRecord.id.in_(quality_ids))
                )
            ).all()
            if quality_ids
            else []
        )
        quality_by_id = {row.id: row for row in quality_rows}
        quality_grades = [row.quality_grade for row in quality_rows]
        is_fixture = any(row.is_fixture for row in quality_rows)
        run.data_mode = "fixture" if is_fixture else release.data_mode

        stage_windows: dict[str, dict[str, dict[str, ComputedWindow]]] = {}
        earliest_rows: list[dict[str, object]] = []
        reaction_records: list[MarketReaction] = []
        for stage in stages:
            stage_key = stage.stage_key
            stage_at = _aware(stage.released_at or stage.scheduled_at)
            stage_windows[stage_key] = {}
            stage_reactions: list[tuple[MarketInstrument, Any]] = []
            for instrument in instruments:
                minute_series = market_selection.get(instrument.id, 60)
                daily_series = market_selection.get(instrument.id, 86_400)
                minute_rows = list(minute_series.bars) if minute_series else []
                daily_rows = list(daily_series.bars) if daily_series else []
                minute_records = [_bar_record(row, instrument.canonical_key) for row in minute_rows]
                daily_records = [_bar_record(row, instrument.canonical_key) for row in daily_rows]
                minute_grade = next(
                    (
                        quality_by_id[row.quality_id].quality_grade
                        for row in minute_rows
                        if row.quality_id in quality_by_id
                    ),
                    minute_series.quality_grade if minute_series else "UNKNOWN",
                )
                daily_grade = next(
                    (
                        quality_by_id[row.quality_id].quality_grade
                        for row in daily_rows
                        if row.quality_id in quality_by_id
                    ),
                    daily_series.quality_grade if daily_series else "UNKNOWN",
                )
                short_windows = calculate_event_windows(
                    minute_records,
                    release_at=stage_at,
                    interval_seconds=60,
                    source_grade=minute_grade,
                    specs=MINUTE_WINDOW_SPECS,
                    instrument_key=instrument.canonical_key,
                )
                long_windows = calculate_session_close_windows(
                    daily_records,
                    release_at=stage_at,
                    source_grade=daily_grade,
                    instrument_key=instrument.canonical_key,
                    session_close_semantics=(
                        daily_series.session_close_semantics if daily_series else "unavailable"
                    ),
                    limitations=(daily_series.limitations if daily_series else ()),
                )
                computed = apply_direction_reversals([*short_windows, *long_windows])
                stage_windows[stage_key][instrument.canonical_key] = {
                    item.key: item for item in computed
                }
                for item in computed:
                    definition = window_definitions.get(item.key)
                    if definition is None:
                        continue
                    selected_series = (
                        daily_series if item.granularity_seconds == 86_400 else minute_series
                    )
                    session.add(
                        EventWindowResult(
                            id=uuid.uuid4(),
                            analysis_run_id=run.id,
                            release_stage_id=stage.id,
                            instrument_id=instrument.id,
                            window_definition_id=definition.id,
                            start_at=item.start_at,
                            end_at=item.end_at,
                            start_value=item.start_value,
                            end_value=item.end_value,
                            change_absolute=item.change_absolute,
                            return_percent=item.return_percent,
                            change_basis_points=None,
                            max_up_percent=item.max_up_percent,
                            max_down_percent=item.max_down_percent,
                            realized_volatility=item.realized_volatility,
                            volume_change_percent=item.volume_change_percent,
                            coverage_ratio=item.coverage_ratio,
                            direction=item.direction,
                            spike_fade=item.spike_fade,
                            dip_recovery=item.dip_recovery,
                            direction_reversal=item.direction_reversal,
                            granularity_seconds=item.granularity_seconds,
                            provider_key=(
                                selected_series.provider_key if selected_series else "unavailable"
                            ),
                            quality_grade=item.quality_grade,
                            missing_reason=item.missing_reason,
                            calculated_at=datetime.now(UTC),
                            metadata_json={
                                "stage_key": stage_key,
                                "proxy_disclosure": instrument.proxy_for,
                                "calendar": item.calendar_name,
                                "calendar_precision": item.calendar_precision,
                                "expected_tradable_bars": item.expected_tradable_bars,
                                "experimental": item.experimental,
                                "limitations": list(item.limitations),
                                "manifest_ids": (
                                    [str(value) for value in selected_series.manifest_ids]
                                    if selected_series
                                    else []
                                ),
                                "dataset": (selected_series.dataset if selected_series else None),
                                "schema_name": (
                                    selected_series.schema_name if selected_series else None
                                ),
                                "contract_code": (
                                    selected_series.contract_code if selected_series else None
                                ),
                                "futures_contract_id": (
                                    str(selected_series.futures_contract_id)
                                    if selected_series and selected_series.futures_contract_id
                                    else None
                                ),
                            },
                        )
                    )
                earliest = detect_earliest_reaction(
                    instrument.canonical_key,
                    minute_records,
                    release_at=stage_at,
                    interval_seconds=60,
                )
                if earliest is not None:
                    stage_reactions.append((instrument, earliest))
                    earliest_rows.append(
                        {
                            "stage_key": stage_key,
                            "instrument_key": earliest.instrument_key,
                            "detected_at": earliest.detected_at.isoformat(),
                            "lag_seconds": earliest.lag_seconds,
                            "move_percent": earliest.move_percent,
                            "direction": earliest.direction,
                            "threshold_percent": earliest.threshold_percent,
                            "pre_event_volatility": earliest.pre_event_volatility,
                            "granularity_seconds": earliest.granularity_seconds,
                            "confirmation_bars": earliest.confirmation_bars,
                            "limitation": earliest.limitation,
                        }
                    )
                strength_candidates = [
                    item
                    for item in computed
                    if item.return_percent is not None and not item.experimental
                ] or computed
                strongest = max(
                    strength_candidates,
                    key=lambda item: abs(item.return_percent or 0.0),
                )
                reaction_records.append(
                    MarketReaction(
                        id=uuid.uuid4(),
                        analysis_run_id=run.id,
                        release_stage_id=stage.id,
                        instrument_id=instrument.id,
                        earliest_significant_at=(
                            earliest.detected_at if earliest is not None else None
                        ),
                        latency_seconds=(earliest.lag_seconds if earliest is not None else None),
                        pre_event_volatility=(
                            earliest.pre_event_volatility if earliest is not None else None
                        ),
                        significance_threshold=(
                            earliest.threshold_percent if earliest is not None else None
                        ),
                        confirmation_bars=(
                            earliest.confirmation_bars if earliest is not None else 2
                        ),
                        initial_direction=(
                            earliest.direction if earliest is not None else "missing"
                        ),
                        strongest_window_key=strongest.key,
                        reaction_strength=abs(strongest.return_percent or 0.0),
                        lead_rank=None,
                        spike_fade=any(item.spike_fade for item in computed),
                        dip_recovery=any(item.dip_recovery for item in computed),
                        direction_reversal=any(item.direction_reversal for item in computed),
                        granularity_seconds=60,
                        limitations_json=list(
                            dict.fromkeys(
                                (
                                    [earliest.limitation]
                                    if earliest is not None
                                    else [
                                        "No volatility-adjusted significant reaction was "
                                        "observed from the selected minute series."
                                    ]
                                )
                                + (
                                    list(minute_series.limitations)
                                    if minute_series
                                    else ["Event-linked minute series is unavailable."]
                                )
                                + list(daily_series.limitations if daily_series else ())
                            )
                        ),
                    )
                )
            ranked = sorted(
                stage_reactions,
                key=lambda item: (
                    item[1].detected_at,
                    -abs(item[1].move_percent),
                ),
            )
            rank_by_instrument = {
                instrument.id: rank for rank, (instrument, _earliest) in enumerate(ranked, start=1)
            }
            for reaction in reaction_records:
                if reaction.release_stage_id == stage.id:
                    reaction.lead_rank = rank_by_instrument.get(reaction.instrument_id)
        session.add_all(reaction_records)
        await session.flush()
        if len(stages) > 1:
            post_5m_definition = window_definitions.get("post_5m")
            for previous_stage, current_stage in pairwise(stages):
                previous_windows = stage_windows.get(previous_stage.stage_key, {})
                current_windows = stage_windows.get(current_stage.stage_key, {})
                for instrument in instruments:
                    previous_item = previous_windows.get(instrument.canonical_key, {}).get(
                        "post_5m"
                    )
                    current_item = current_windows.get(instrument.canonical_key, {}).get("post_5m")
                    if (
                        previous_item is None
                        or current_item is None
                        or previous_item.return_percent is None
                        or current_item.return_percent is None
                        or previous_item.return_percent * current_item.return_percent >= 0
                    ):
                        continue
                    current_reaction = next(
                        (
                            item
                            for item in reaction_records
                            if item.release_stage_id == current_stage.id
                            and item.instrument_id == instrument.id
                        ),
                        None,
                    )
                    if current_reaction is not None:
                        current_reaction.direction_reversal = True
                    if post_5m_definition is not None:
                        window_row = await session.scalar(
                            select(EventWindowResult).where(
                                EventWindowResult.analysis_run_id == run.id,
                                EventWindowResult.release_stage_id == current_stage.id,
                                EventWindowResult.instrument_id == instrument.id,
                                EventWindowResult.window_definition_id == post_5m_definition.id,
                            )
                        )
                        if window_row is not None:
                            window_row.direction_reversal = True

        release_stage_key = "release" if "release" in stage_windows else stages[0].stage_key
        current_returns = {
            f"{instrument_key}:post_5m": current_window.return_percent
            for instrument_key, windows in stage_windows.get(release_stage_key, {}).items()
            if (current_window := windows.get("post_5m")) is not None
        }
        regime = derive_regime(
            release_type=release.release_type,
            bundle_direction=bundle.direction,
            surprise_score=bundle.score,
            returns=current_returns,
            macro_context=regime_context,
        )
        regime_hash = hashlib.sha256(
            json.dumps(
                {
                    "release_id": str(release.id),
                    "labels": regime.labels,
                    "evidence": regime.evidence,
                    "pre_event_context": regime_context,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        regime_row = RegimeSnapshot(
            id=uuid.uuid4(),
            as_of=_aware(release.released_at or release.scheduled_at),
            methodology_version="macro-regime-v2-pre-event-pit",
            labels_json=list(regime.labels),
            dimensions_json=regime.dimensions,
            evidence_json=list(regime.evidence),
            confidence=regime.confidence,
            data_gaps_json=list(regime.data_gaps),
            source_snapshot_hash=regime_hash,
        )
        session.add(regime_row)
        await session.flush()
        run.regime_snapshot_id = regime_row.id
        component_keys = (
            ("core_mom", "core_yoy")
            if release.release_type == "US_CPI"
            else (
                "average_hourly_earnings_mom",
                "average_hourly_earnings_yoy",
            )
            if release.release_type == "US_NFP"
            else ("statement_tone_score", "press_conference_tone_score")
        )
        component_values: list[float] = []
        for indicator_surprise in bundle.indicators:
            if indicator_surprise.key not in component_keys:
                continue
            value = (
                indicator_surprise.surprise_z
                if indicator_surprise.surprise_z is not None
                else indicator_surprise.threshold_scaled_surprise
            )
            if value is not None:
                component_values.append(value)
        component_score = sum(component_values) / len(component_values) if component_values else 0.0
        component_direction = (
            "hot" if component_score > 0.25 else "cold" if component_score < -0.25 else "mixed"
        )
        candidates = await _historical_cases(session, release)
        current_case = HistoricalCase(
            event_id=str(release.id),
            release_at=_aware(release.released_at or release.scheduled_at),
            classification=bundle.classification,
            direction=bundle.direction,
            magnitude_bucket=magnitude_bucket(bundle.score),
            core_direction=component_direction,
            regime_tags=regime.labels,
            contamination_level=release.contamination_level,
            clean_window=release.clean_window,
            returns=current_returns,
            release_type=release.release_type,
            regime_dimensions=regime.dimensions,
            is_fixture=is_fixture,
        )
        historical = cast(
            dict[str, Any],
            compare_historical_events(
                current_case,
                candidates,
                current_returns=current_returns,
            ),
        )
        run.historical_sample_manifest_json = {
            "sample_manifest": historical["sample_manifest"],
            "release_ids": historical["sample_release_ids"],
            "analysis_run_ids": historical["sample_analysis_run_ids"],
            "filters": historical["filters"],
            "contamination_policy": historical["contamination_policy"],
        }
        run.historical_sample_hash = str(historical["sample_manifest_hash"])
        # The historical cohort is an analysis input just as much as release values
        # and market bars.  Include its point-in-time manifest in the immutable input
        # hash so a changed comparison set cannot reproduce under the same identity.
        run.input_snapshot_hash = _stable_hash(
            {
                "release": release_snapshot,
                "release_value_ids": run.release_value_ids_json,
                "consensus_snapshot_ids": run.consensus_snapshot_ids_json,
                "stage_ids": run.release_stage_ids_json,
                "market_hash": market_hash,
                "historical_sample_hash": run.historical_sample_hash,
                "config_hash": run.config_hash,
            }
        )
        earliest_objects = []
        for stage in stages:
            stage_at = _aware(stage.released_at or stage.scheduled_at)
            for instrument in instruments:
                minute_series = market_selection.get(instrument.id, 60)
                records = [
                    _bar_record(row, instrument.canonical_key)
                    for row in (minute_series.bars if minute_series else ())
                ]
                earliest = detect_earliest_reaction(
                    instrument.canonical_key,
                    records,
                    release_at=stage_at,
                    interval_seconds=60,
                )
                if earliest is not None:
                    earliest_objects.append(earliest)
        structured = cast(
            dict[str, Any],
            build_structured_explanation(
                release_type=release.release_type,
                event_title=release.title,
                bundle=bundle,
                windows=stage_windows,
                earliest=earliest_objects,
                contamination_level=release.contamination_level,
                clean_window=release.clean_window,
                quality_grades=quality_grades,
                is_fixture=is_fixture,
                historical=historical,
            ),
        )
        market_data_gaps: list[str] = []
        if not market_selection.series:
            market_data_gaps.append(
                "No event-linked market manifest with matching provider/contract bars was "
                "available; cross-asset reaction analysis is unavailable."
            )
        missing_minute = [
            instrument.canonical_key
            for instrument in instruments
            if market_selection.get(instrument.id, 60) is None
        ]
        if missing_minute:
            market_data_gaps.append(
                "Short event windows are unavailable for event-linked minute series: "
                f"{', '.join(sorted(missing_minute))}."
            )
        missing_daily = [
            instrument.canonical_key
            for instrument in instruments
            if market_selection.get(instrument.id, 86_400) is None
        ]
        experimental_daily = [
            instrument.canonical_key
            for instrument in instruments
            if (series := market_selection.get(instrument.id, 86_400)) is not None
            and series.session_close_semantics == "utc_day"
        ]
        if missing_daily:
            market_data_gaps.append(
                "T+1/T+5 session-close windows are unavailable for event-linked daily "
                f"series: {', '.join(sorted(missing_daily))}."
            )
        if experimental_daily:
            market_data_gaps.append(
                "T+1/T+5 windows use experimental UTC-day proxies, not exchange "
                f"settlement prices: {', '.join(sorted(experimental_daily))}."
            )
        if market_selection.rejected_manifest_ids:
            market_data_gaps.append(
                "Alternative event-linked provider/contract manifests were excluded to "
                "prevent cross-provider or cross-contract mixing."
            )
        structured["data_gaps"] = list(dict.fromkeys([*structured["data_gaps"], *market_data_gaps]))

        indicator_surprises = {
            item.key: {
                "raw_surprise": _float(item.raw_surprise),
                "oriented_surprise": item.oriented_surprise,
                "relative_surprise": item.relative_surprise,
                "threshold_scaled_surprise": item.threshold_scaled_surprise,
                "surprise_z": item.surprise_z,
                "direction": item.direction,
                "revision": _float(item.revision),
                "history_sample_count": item.history_sample_count,
                "history_mean": item.history_mean,
                "history_std": item.history_std,
                "history_cutoff_at": item.history_cutoff_at.isoformat()
                if item.history_cutoff_at
                else None,
                "surprise_method": item.surprise_method,
                "z_score_unavailable_reason": item.z_score_unavailable_reason,
            }
            for item in bundle.indicators
        }
        for values in serialized_values.values():
            key = next(
                (
                    item_key
                    for item_key, item_value in serialized_values.items()
                    if item_value is values
                ),
                None,
            )
            if key and key in indicator_surprises:
                values["surprise"] = indicator_surprises[key]

        run.composite_classification = bundle.classification
        run.composite_surprise_score = bundle.score
        run.confidence = float(structured["confidence"])
        run.facts_json = list(structured["facts"])
        run.earliest_reactions_json = earliest_rows
        run.data_gaps_json = list(structured["data_gaps"])
        run.parameters_json = {
            "bundle_direction": bundle.direction,
            "bundle_reasons": list(bundle.reasons),
            "revision_dominant": bundle.revision_dominant,
            "revision_analysis": bundle.revision_analysis,
            "composite_method": bundle.composite_method,
            "component_methods": bundle.component_methods,
            "component_direction": component_direction,
            "indicator_surprises": indicator_surprises,
            "historical": historical,
            "data_mode": run.data_mode,
            "regime": {
                "labels": list(regime.labels),
                "dimensions": regime.dimensions,
                "evidence": list(regime.evidence),
                "confidence": regime.confidence,
                "data_gaps": list(regime.data_gaps),
            },
        }
        run.status = "completed"
        run.completed_at = datetime.now(UTC)

        for rank, item in enumerate(structured["explanations"], start=1):
            session.add(
                Explanation(
                    id=uuid.uuid4(),
                    analysis_run_id=run.id,
                    explanation_type=str(item["kind"]),
                    rank=rank,
                    title=str(item["title"]),
                    summary=str(item["summary"]),
                    confidence=float(item["confidence"]),
                    causal_language=str(item["causal_language"]),
                    mechanism_steps_json=list(item["mechanism_steps"]),
                    confirming_evidence_json=list(item["confirming_evidence"]),
                    contradicting_evidence_json=list(item["contradicting_evidence"]),
                    unresolved_json=list(item["unresolved"]),
                    rule_key=str(item["rule_key"]),
                )
            )
        for rank, item in enumerate(historical["similar_cases"], start=1):
            session.add(
                HistoricalMatch(
                    id=uuid.uuid4(),
                    analysis_run_id=run.id,
                    matched_release_id=uuid.UUID(str(item["event_id"])),
                    matched_analysis_run_id=(
                        uuid.UUID(str(item["analysis_run_id"]))
                        if item.get("analysis_run_id")
                        else None
                    ),
                    similarity_score=float(item["similarity"]),
                    rank=rank,
                    included=True,
                    filters_json=[str(value["condition"]) for value in historical["filters"]],
                    comparable_metrics_json=dict(item["returns"]),
                    exclusion_reason=None,
                )
            )
        evidence_document = {
            "release_id": str(release.id),
            "run_id": str(run.id),
            "values": serialized_values,
            "facts": structured["facts"],
            "hypotheses": structured["explanations"],
            "historical": historical,
            "quality_ids": [str(item.id) for item in quality_rows],
        }
        evidence_hash = hashlib.sha256(
            json.dumps(
                evidence_document,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()
        snapshot_evidence_id = uuid.uuid4()
        session.add(
            EvidenceItem(
                id=snapshot_evidence_id,
                analysis_run_id=run.id,
                evidence_type="analysis_snapshot",
                subject_type="macro_release",
                subject_id=str(release.id),
                source_artifact_id=release.source_artifact_id,
                statement=(
                    "Structured release values, deterministic facts, historical sample "
                    "manifest, and data quality were captured for this run."
                ),
                value_json=evidence_document,
                unit=None,
                observed_at=_aware(release.released_at or release.scheduled_at),
                quality_grade="C" if is_fixture else "B",
                is_fixture=is_fixture,
                is_proxy=any(item.is_proxy for item in instruments),
                is_manual=False,
                limitations_json=list(structured["data_gaps"]),
                content_hash=evidence_hash,
            )
        )
        proxy_keys = {item.canonical_key for item in instruments if item.is_proxy}
        fact_evidence_ids: list[str] = []
        evidence_registry: dict[str, dict[str, object]] = {}
        for index, fact in enumerate(structured["facts"]):
            statement = (
                str(fact.get("statement") or fact.get("text") or fact)
                if isinstance(fact, dict)
                else str(fact)
            )
            evidence_id = uuid.uuid5(run.id, f"fact:{index}")
            fact_is_proxy = any(key in statement for key in proxy_keys)
            fact_hash = _stable_hash(
                {"statement": statement, "release_id": str(release.id), "index": index}
            )
            session.add(
                EvidenceItem(
                    id=evidence_id,
                    analysis_run_id=run.id,
                    evidence_type="computed_fact",
                    subject_type="macro_release",
                    subject_id=str(release.id),
                    source_artifact_id=release.source_artifact_id,
                    statement=statement,
                    value_json={"fact_index": index, "statement": statement},
                    unit=None,
                    observed_at=_aware(release.released_at or release.scheduled_at),
                    quality_grade="C" if is_fixture else "B",
                    is_fixture=is_fixture,
                    is_proxy=fact_is_proxy,
                    is_manual=False,
                    limitations_json=list(structured["data_gaps"]),
                    content_hash=fact_hash,
                )
            )
            fact_evidence_ids.append(str(evidence_id))
            evidence_registry[str(evidence_id)] = {
                "is_fixture": is_fixture,
                "is_proxy": fact_is_proxy,
                "evidence_type": "computed_fact",
                "statement": statement,
            }
        if not fact_evidence_ids:
            fact_evidence_ids.append(str(snapshot_evidence_id))
            evidence_registry[str(snapshot_evidence_id)] = {
                "is_fixture": is_fixture,
                "is_proxy": any(item.is_proxy for item in instruments),
                "evidence_type": "analysis_snapshot",
            }
        claims_payload = deterministic_claims(
            list(structured["facts"]),
            list(structured["explanations"]),
            fact_evidence_ids,
            limitations=list(structured["data_gaps"])
            + (["fixture data"] if is_fixture else [])
            + (["proxy market data"] if any(item.is_proxy for item in instruments) else []),
        )
        validation = validate_claims(
            claims_payload,
            evidence_registry,
        )
        if not validation.valid:
            raise ValueError(f"deterministic claim validation failed: {validation.errors}")
        for claim in claims_payload:
            session.add(
                ResearchClaim(
                    id=uuid.uuid4(),
                    analysis_run_id=run.id,
                    claim_type=str(claim["claim_type"]),
                    statement=str(claim["statement"]),
                    evidence_ids_json=list(claim["evidence_ids"]),
                    confidence=float(claim["confidence"]),
                    is_inference=bool(claim["is_inference"]),
                    causal_language=str(claim["causal_language"]),
                    limitations_json=list(claim["limitations"]),
                    falsifier=claim.get("falsifier"),
                    contradicting_evidence_ids_json=list(claim["contradicting_evidence_ids"]),
                    validation_json={"valid": True},
                )
            )
        session.add(
            ReportArtifact(
                id=uuid.uuid4(),
                analysis_run_id=run.id,
                format="markdown",
                content=str(structured["report"]),
                evidence_pack_hash=evidence_hash,
                generator="worldstate_deterministic",
                model_name=None,
                generated_at=datetime.now(UTC),
                validation_json={
                    "facts_only_source": True,
                    "causal_language_checked": True,
                    "data_gaps_included": True,
                    "claim_validation": {
                        "valid": validation.valid,
                        "errors": list(validation.errors),
                    },
                },
            )
        )
        normalized_claims = [
            {
                key: value
                for key, value in claim.items()
                if key not in {"evidence_ids", "contradicting_evidence_ids"}
            }
            for claim in claims_payload
        ]
        output_snapshot = {
            "surprises": indicator_surprises,
            "bundle": {
                "classification": bundle.classification,
                "score": bundle.score,
                "method": bundle.composite_method,
                "revision_analysis": bundle.revision_analysis,
            },
            "historical": historical,
            "regime": regime.dimensions,
            "facts": structured["facts"],
            "claims": normalized_claims,
        }
        run.parameters_json = {**run.parameters_json, "output_snapshot": output_snapshot}
        run.output_hash = _stable_hash(output_snapshot)
        await session.flush()
        return str(run.id)


async def analyze_release(
    engine: AsyncEngine,
    release_id: str,
    *,
    idempotency_key: str | None = None,
    force: bool = False,
) -> str:
    """Run analysis with an externally durable lifecycle and idempotency guard."""

    factory = _factory(engine)
    release_uuid = uuid.UUID(release_id)
    if idempotency_key and not force:
        async with factory() as session:
            existing = await session.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.macro_release_id == release_uuid,
                    AnalysisRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return str(existing.id)
    # Observed analysis is gated before the transactional run is created.  A
    # missing consensus or minute manifest therefore cannot leave a misleading
    # completed/failed run behind; fixture demonstrations retain their legacy
    # workflow and remain explicitly fixture-labelled.
    async with factory() as session:
        release = await session.get(MacroRelease, release_uuid)
    if release is None:
        raise LookupError("macro release not found")
    if release.data_mode == "observed":
        readiness = await build_analysis_readiness(engine, release_id)
        if not readiness.ready:
            raise AnalysisReadinessError(readiness)
    try:
        run_id = await _execute_analysis(engine, release_id)
    except (LookupError, AnalysisReadinessError):
        raise
    except Exception as exc:
        # The analysis transaction has rolled back all partial windows/reactions.
        # Persist a separate failure record so failures are never mislabeled completed.
        async with factory() as session, session.begin():
            release = await session.get(MacroRelease, release_uuid)
            if release is not None:
                failed = AnalysisRun(
                    id=uuid.uuid4(),
                    macro_release_id=release.id,
                    methodology_version=METHODOLOGY_VERSION,
                    code_version=CODE_VERSION,
                    status="failed",
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    regime_snapshot_id=None,
                    composite_classification="analysis_failed",
                    composite_surprise_score=None,
                    confidence=0.0,
                    facts_json=[],
                    earliest_reactions_json=[],
                    data_gaps_json=["analysis did not complete"],
                    parameters_json={},
                    data_mode=release.data_mode,
                    release_snapshot_json={
                        "release_id": str(release.id),
                        "released_at": _aware(
                            release.released_at or release.scheduled_at
                        ).isoformat(),
                    },
                    reproducibility_status="failed_incomplete",
                    idempotency_key=idempotency_key,
                    failure_stage="analysis_transaction",
                    error_type=type(exc).__name__,
                    error_message=redact_sensitive_text(exc)[:2000],
                )
                session.add(failed)
        raise
    if idempotency_key:
        async with factory() as session, session.begin():
            completed = await session.get(AnalysisRun, uuid.UUID(run_id))
            if completed is not None:
                completed.idempotency_key = idempotency_key
    return run_id


async def _latest_run(session: AsyncSession, release_id: uuid.UUID) -> AnalysisRun | None:
    return cast(
        AnalysisRun | None,
        await session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.macro_release_id == release_id,
                AnalysisRun.status == "completed",
            )
            .order_by(AnalysisRun.completed_at.desc())
        ),
    )


def _quality_dict(row: DataQualityRecord) -> dict[str, object]:
    return {
        "id": str(row.id),
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "source_type": row.source_type,
        "acquired_at": _aware(row.acquired_at).isoformat(),
        "is_manual": row.is_manual,
        "is_verified": row.is_verified,
        "is_fixture": row.is_fixture,
        "is_proxy": row.is_proxy,
        "latency_seconds": row.latency_seconds,
        "granularity_seconds": row.granularity_seconds,
        "missing_reason": row.missing_reason,
        "quality_grade": row.quality_grade,
        "verification_notes": row.verification_notes,
        "metadata": row.metadata_json,
    }


async def list_releases(
    engine: AsyncEngine,
    *,
    release_type: str | None = None,
    limit: int = 100,
    data_mode: str = "observed",
) -> list[dict[str, object]]:
    factory = _factory(engine)
    async with factory() as session:
        query = (
            select(MacroRelease)
            .where(MacroRelease.status != "invalidated")
            .order_by(MacroRelease.scheduled_at.desc())
            .limit(limit)
        )
        if release_type:
            query = query.where(MacroRelease.release_type == release_type)
        if data_mode != "all":
            query = query.where(MacroRelease.data_mode == data_mode)
        releases = (await session.scalars(query)).all()
        output: list[dict[str, object]] = []
        for release in releases:
            run = await _latest_run(session, release.id)
            output.append(
                {
                    "id": str(release.id),
                    "release_key": release.release_key,
                    "release_type": release.release_type,
                    "title": release.title,
                    "period_label": release.period_label,
                    "scheduled_at": _aware(release.scheduled_at).isoformat(),
                    "released_at": (
                        _aware(release.released_at).isoformat() if release.released_at else None
                    ),
                    "status": release.status,
                    "classification": run.composite_classification if run else None,
                    "surprise_score": run.composite_surprise_score if run else None,
                    "confidence": run.confidence if run else 0.0,
                    "analysis_status": run.status if run else "pending",
                    "reproducibility_status": (run.reproducibility_status if run else None),
                    "analysis_completed_at": (
                        _aware(run.completed_at).isoformat() if run and run.completed_at else None
                    ),
                    "data_mode": run.data_mode if run else release.data_mode,
                    "clean_window": release.clean_window,
                    "contamination_level": release.contamination_level,
                }
            )
        return output


async def _release_quality(
    session: AsyncSession,
    release: MacroRelease,
) -> list[DataQualityRecord]:
    ids: set[uuid.UUID] = set()
    if release.primary_quality_id:
        ids.add(release.primary_quality_id)
    run = await _latest_run(session, release.id)
    selection_series = (
        [
            item
            for item in run.market_dataset_manifest_json
            if isinstance(item, dict)
            and item.get("selection_version") == "release-manifest-series-v1"
        ]
        if run
        else []
    )
    for item in selection_series:
        for bar in item.get("selected_bars", []):
            if not isinstance(bar, dict) or not bar.get("quality_id"):
                continue
            with suppress(ValueError):
                ids.add(uuid.UUID(str(bar["quality_id"])))
    stage_times = (
        await session.scalars(
            select(ReleaseStage).where(ReleaseStage.macro_release_id == release.id)
        )
    ).all()
    if stage_times and not selection_series:
        lower = min(_aware(item.scheduled_at) for item in stage_times) - timedelta(minutes=60)
        upper = max(_aware(item.scheduled_at) for item in stage_times) + timedelta(hours=4)
        ids.update(
            item
            for item in (
                await session.scalars(
                    select(MarketBar.quality_id)
                    .where(
                        MarketBar.timestamp >= lower,
                        MarketBar.timestamp <= upper,
                        MarketBar.data_mode == release.data_mode,
                        MarketBar.quality_id.is_not(None),
                    )
                    .distinct()
                )
            ).all()
            if item is not None
        )
    if not ids:
        return []
    return list(
        (
            await session.scalars(
                select(DataQualityRecord)
                .where(DataQualityRecord.id.in_(ids))
                .order_by(DataQualityRecord.source_name)
            )
        ).all()
    )


async def _release_data_provenance(
    session: AsyncSession,
    release: MacroRelease,
    artifact: SourceArtifact | None,
    run: AnalysisRun | None,
) -> dict[str, object]:
    """Assemble release-level provenance without exposing licensed raw payloads."""

    all_manifest_rows = (
        await session.execute(
            select(MarketDataManifest, MarketInstrument, FuturesContract)
            .join(MarketInstrument, MarketInstrument.id == MarketDataManifest.instrument_id)
            .outerjoin(
                FuturesContract,
                FuturesContract.id == MarketDataManifest.futures_contract_id,
            )
            .where(
                MarketDataManifest.macro_release_id == release.id,
                MarketDataManifest.data_mode == release.data_mode,
            )
            .order_by(MarketInstrument.canonical_key, MarketDataManifest.start_at)
        )
    ).all()
    selection_series = (
        [
            item
            for item in run.market_dataset_manifest_json
            if isinstance(item, dict)
            and item.get("selection_version") == "release-manifest-series-v1"
        ]
        if run
        else []
    )
    selected_manifest_ids = {
        str(manifest.get("manifest_id"))
        for item in selection_series
        for manifest in item.get("manifests", [])
        if isinstance(manifest, dict) and manifest.get("manifest_id")
    }
    manifest_rows = (
        [row for row in all_manifest_rows if str(row[0].id) in selected_manifest_ids]
        if selection_series
        else list(all_manifest_rows)
    )
    selected_values, selected_consensus, input_artifacts = await select_analysis_inputs(
        session, release
    )
    consensus = max(
        selected_consensus.values(),
        key=lambda item: _aware(item.captured_at),
        default=None,
    )
    consensus_artifact = (
        input_artifacts.get(consensus.source_artifact_id)
        if consensus and consensus.source_artifact_id
        else None
    )
    release_value_ids = sorted(
        {
            str(value.id)
            for (_indicator_id, value_kind), value in selected_values.items()
            if value_kind in {"actual", "previous", "revised_previous"} and value.value is not None
        }
    )
    manifest_ids = [
        str(manifest.id)
        for manifest, _instrument, _contract in manifest_rows
        if manifest.row_count > 0
    ]
    reconciliation_subjects = {
        str(release.id),
        release.release_key,
        *release_value_ids,
        *manifest_ids,
    }
    reconciliations = (
        await session.scalars(
            select(DataReconciliationRecord).where(
                DataReconciliationRecord.data_mode == release.data_mode,
                DataReconciliationRecord.subject_id.in_(reconciliation_subjects),
            )
        )
    ).all()

    gaps: list[str] = []
    if artifact is None:
        gaps.append("official source artifact is missing")
    if consensus is None:
        gaps.append("eligible pre-release consensus snapshot is missing")
    if not manifest_rows:
        gaps.append("event market dataset manifest is missing")
    if run and not selection_series:
        gaps.append(
            "analysis run predates release-linked provider/contract market selection provenance"
        )
    expected_reconciliation_subjects = {*release_value_ids, *manifest_ids}
    relevant_reconciliations = [
        row for row in reconciliations if row.subject_id in expected_reconciliation_subjects
    ]
    covered_reconciliation_subjects = {row.subject_id for row in relevant_reconciliations}
    missing_reconciliation_subjects = sorted(
        expected_reconciliation_subjects - covered_reconciliation_subjects
    )
    if expected_reconciliation_subjects and not relevant_reconciliations:
        gaps.append("data reconciliation has not run for this release")
    elif missing_reconciliation_subjects:
        gaps.append("data reconciliation covers only part of this release")
    if release.data_mode == "fixture":
        gaps.append("fixture data is a demonstration, not an observed market record")
    if run:
        gaps.extend(str(item) for item in run.data_gaps_json)
    gaps = list(dict.fromkeys(gaps))

    manifest_hash = run.market_dataset_hash if run else None
    datasets = sorted({manifest.dataset for manifest, _instrument, _contract in manifest_rows})
    schemas = sorted({manifest.schema_name for manifest, _instrument, _contract in manifest_rows})
    range_start = min(
        (_aware(manifest.start_at) for manifest, _instrument, _contract in manifest_rows),
        default=None,
    )
    range_end = max(
        (_aware(manifest.end_at) for manifest, _instrument, _contract in manifest_rows),
        default=None,
    )
    # Release-level comparisons (time, unit and reference period) may use the
    # release id rather than a value/manifest id.  They do not satisfy missing
    # value coverage, but any mismatch must still prevent a complete result.
    statuses = {row.status for row in reconciliations}
    reconciliation_complete = (
        bool(expected_reconciliation_subjects)
        and not missing_reconciliation_subjects
        and bool(relevant_reconciliations)
        and statuses <= {"matched", "resolved"}
    )
    if not expected_reconciliation_subjects:
        reconciliation_status = "not_applicable"
    elif not relevant_reconciliations:
        reconciliation_status = "not_run"
    elif statuses - {"matched", "resolved"}:
        reconciliation_status = "attention_required"
    elif missing_reconciliation_subjects:
        reconciliation_status = "partial"
    else:
        reconciliation_status = "complete"
    reconciliation_notes = [
        f"{row.reconciliation_type}:{row.field_name or row.subject_type}={row.status}"
        for row in reconciliations
    ]

    return {
        "official_source": (
            {
                "provider_key": artifact.provider_key,
                "display_name": artifact.title,
                "source_url": artifact.source_url,
                "artifact_id": str(artifact.id),
                "retrieved_at": _aware(artifact.retrieved_at).isoformat(),
                "content_hash": artifact.content_hash,
            }
            if artifact
            else None
        ),
        "consensus_source": (
            {
                "provider_key": (
                    consensus_artifact.provider_key if consensus_artifact else consensus.source_name
                ),
                "source_name": consensus.source_name,
                "source_url": consensus.source_url,
                "artifact_id": (str(consensus_artifact.id) if consensus_artifact else None),
                "snapshot_id": str(consensus.id),
                "captured_at": _aware(consensus.captured_at).isoformat(),
                "quality_grade": consensus.quality_grade,
            }
            if consensus
            else None
        ),
        "consensus_captured_at": (_aware(consensus.captured_at).isoformat() if consensus else None),
        "market_dataset": (
            {
                "provider_key": ", ".join(
                    sorted(
                        {
                            manifest.provider_key
                            for manifest, _instrument, _contract in manifest_rows
                        }
                    )
                ),
                "dataset": ", ".join(datasets),
                "schema": ", ".join(schemas),
                "manifest_hash": manifest_hash,
                "range_start": range_start.isoformat() if range_start else None,
                "range_end": range_end.isoformat() if range_end else None,
                "granularity": ", ".join(
                    sorted(
                        {
                            f"{manifest.interval_seconds}s"
                            for manifest, _instrument, _contract in manifest_rows
                        }
                    )
                ),
                "selection_policy": (
                    "release-manifest-series-v1" if selection_series else "legacy_unscoped"
                ),
                "selected_manifest_ids": sorted(selected_manifest_ids),
            }
            if manifest_rows
            else None
        ),
        "contracts": [
            {
                "instrument_key": instrument.canonical_key,
                "instrument_title": instrument.title,
                "symbol": instrument.symbol,
                "contract_code": manifest.contract_code,
                "provider_symbol": (
                    contract.provider_symbol if contract else manifest.source_symbol
                ),
                "instrument_id": (
                    str(contract.id)
                    if contract and contract.metadata_json.get("provider_instrument_id") is None
                    else (
                        str(contract.metadata_json.get("provider_instrument_id"))
                        if contract
                        else None
                    )
                ),
                "dataset": manifest.dataset,
                "expiry": (
                    contract.expiry_date.isoformat() if contract and contract.expiry_date else None
                ),
                "first_notice": (
                    str(contract.metadata_json.get("first_notice"))
                    if contract and contract.metadata_json.get("first_notice")
                    else None
                ),
                "last_trade": (
                    contract.last_trade_date.isoformat()
                    if contract and contract.last_trade_date
                    else None
                ),
                "roll_status": manifest.roll_status,
                "selection_rule": manifest.contract_selection_rule,
            }
            for manifest, instrument, contract in manifest_rows
        ],
        "analysis_market_input": (
            {
                "market_dataset_hash": run.market_dataset_hash,
                "series": selection_series,
            }
            if run and selection_series
            else None
        ),
        "data_mode": release.data_mode,
        "reconciled": reconciliation_complete,
        "reconciliation_status": reconciliation_status,
        "reconciliation_notes": reconciliation_notes,
        "reconciliation_summary": {
            "expected_subject_count": len(expected_reconciliation_subjects),
            "covered_subject_count": len(covered_reconciliation_subjects),
            "comparison_record_count": len(reconciliations),
            "missing_subject_ids": missing_reconciliation_subjects,
            "partial_comparisons_are_complete": False,
        },
        "data_gaps": gaps,
    }


async def get_release_detail(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    factory = _factory(engine)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return None
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            return None
        run = await _latest_run(session, release.id)
        inputs, values, indicator_rows = await _value_inputs(session, release)
        history = await _historical_surprises(session, release, indicator_rows)
        bundle = _bundle(
            release.release_type,
            inputs,
            historical_surprises=history,
            released_at=_aware(release.released_at or release.scheduled_at),
        )
        surprises = dict(run.parameters_json.get("indicator_surprises", {})) if run else {}
        for key, item in values.items():
            item["surprise"] = surprises.get(key)
        stages = (
            await session.scalars(
                select(ReleaseStage)
                .where(ReleaseStage.macro_release_id == release.id)
                .order_by(ReleaseStage.sequence)
            )
        ).all()
        quality = await _release_quality(session, release)
        artifact = (
            await session.get(SourceArtifact, release.source_artifact_id)
            if release.source_artifact_id
            else None
        )
        data_provenance = await _release_data_provenance(session, release, artifact, run)
        return {
            "id": str(release.id),
            "release_key": release.release_key,
            "release_type": release.release_type,
            "title": release.title,
            "country": release.country,
            "period_label": release.period_label,
            "scheduled_at": _aware(release.scheduled_at).isoformat(),
            "released_at": (
                _aware(release.released_at).isoformat() if release.released_at else None
            ),
            "source_timezone": release.source_timezone,
            "status": release.status,
            "data_version": release.data_version,
            "data_mode": run.data_mode if run else release.data_mode,
            "bundle": {
                "classification": (run.composite_classification if run else bundle.classification),
                "score": run.composite_surprise_score if run else bundle.score,
                "direction": bundle.direction,
                "reasons": list(bundle.reasons),
                "revision_dominant": bundle.revision_dominant,
                "revision_analysis": bundle.revision_analysis,
                "composite_method": bundle.composite_method,
                "component_methods": bundle.component_methods,
                "minimum_z_score_sample": 20,
                "methodology_version": (run.methodology_version if run else METHODOLOGY_VERSION),
            },
            "values": values,
            "stages": [
                {
                    "id": str(stage.id),
                    "key": stage.stage_key,
                    "title": stage.title,
                    "sequence": stage.sequence,
                    "scheduled_at": _aware(stage.scheduled_at).isoformat(),
                    "released_at": (
                        _aware(stage.released_at).isoformat() if stage.released_at else None
                    ),
                    "status": stage.status,
                }
                for stage in stages
            ],
            "contamination": {
                "level": release.contamination_level,
                "clean_window": release.clean_window,
                "overlapping_events": release.overlapping_events,
                "confounding_notes": release.confounding_notes,
                "causal_language": ("bounded" if release.clean_window else "weak_only"),
            },
            "latest_analysis": (
                {
                    "id": str(run.id),
                    "status": run.status,
                    "confidence": run.confidence,
                    "started_at": _aware(run.started_at).isoformat(),
                    "completed_at": (
                        _aware(run.completed_at).isoformat() if run.completed_at else None
                    ),
                    "code_version": run.code_version,
                    "input_snapshot_hash": run.input_snapshot_hash,
                    "config_hash": run.config_hash,
                    "market_dataset_hash": run.market_dataset_hash,
                    "historical_sample_hash": run.historical_sample_hash,
                    "output_hash": run.output_hash,
                    "reproducibility_status": run.reproducibility_status,
                    "data_gaps": run.data_gaps_json,
                }
                if run
                else None
            ),
            "source": (
                {
                    "id": str(artifact.id),
                    "title": artifact.title,
                    "url": artifact.source_url,
                    "provider_key": artifact.provider_key,
                    "retrieved_at": _aware(artifact.retrieved_at).isoformat(),
                    "content_hash": artifact.content_hash,
                    "is_fixture": artifact.is_fixture,
                    "citation": artifact.citation_text,
                }
                if artifact
                else None
            ),
            "data_provenance": data_provenance,
            "data_quality": [_quality_dict(item) for item in quality],
        }


async def get_release_windows(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    factory = _factory(engine)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return None
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            return None
        run = await _latest_run(session, release.id)
        if run is None:
            return {"release_id": release_id, "analysis_run_id": None, "items": []}
        rows = (
            await session.execute(
                select(
                    EventWindowResult,
                    EventWindowDefinition,
                    ReleaseStage,
                    MarketInstrument,
                )
                .join(
                    EventWindowDefinition,
                    EventWindowDefinition.id == EventWindowResult.window_definition_id,
                )
                .join(
                    ReleaseStage,
                    ReleaseStage.id == EventWindowResult.release_stage_id,
                )
                .join(
                    MarketInstrument,
                    MarketInstrument.id == EventWindowResult.instrument_id,
                )
                .where(EventWindowResult.analysis_run_id == run.id)
                .order_by(
                    ReleaseStage.sequence,
                    MarketInstrument.canonical_key,
                    EventWindowDefinition.sequence,
                )
            )
        ).all()
        items = []
        for window, definition, stage, instrument in rows:
            items.append(
                {
                    "stage_key": stage.stage_key,
                    "stage_title": stage.title,
                    "instrument_key": instrument.canonical_key,
                    "instrument_title": instrument.title,
                    "symbol": instrument.symbol,
                    "is_proxy": instrument.is_proxy,
                    "proxy_for": instrument.proxy_for,
                    "window_key": definition.window_key,
                    "window_label": definition.label,
                    "start_at": _aware(window.start_at).isoformat(),
                    "end_at": _aware(window.end_at).isoformat(),
                    "start_value": _float(window.start_value),
                    "end_value": _float(window.end_value),
                    "change_absolute": _float(window.change_absolute),
                    "return_percent": window.return_percent,
                    "change_basis_points": window.change_basis_points,
                    "max_up_percent": window.max_up_percent,
                    "max_down_percent": window.max_down_percent,
                    "realized_volatility": window.realized_volatility,
                    "volume_change_percent": window.volume_change_percent,
                    "coverage_ratio": window.coverage_ratio,
                    "direction": window.direction,
                    "spike_fade": window.spike_fade,
                    "dip_recovery": window.dip_recovery,
                    "direction_reversal": window.direction_reversal,
                    "granularity_seconds": window.granularity_seconds,
                    "provider_key": window.provider_key,
                    "quality_grade": window.quality_grade,
                    "missing_reason": window.missing_reason,
                    "calendar_name": window.metadata_json.get("calendar"),
                    "calendar_precision": window.metadata_json.get("calendar_precision"),
                    "expected_tradable_bars": window.metadata_json.get("expected_tradable_bars"),
                    "experimental": bool(window.metadata_json.get("experimental", False)),
                    "limitations": list(window.metadata_json.get("limitations", [])),
                    "manifest_ids": list(window.metadata_json.get("manifest_ids", [])),
                    "dataset": window.metadata_json.get("dataset"),
                    "schema_name": window.metadata_json.get("schema_name"),
                    "contract_code": window.metadata_json.get("contract_code"),
                    "futures_contract_id": window.metadata_json.get("futures_contract_id"),
                }
            )
        reactions = (
            await session.execute(
                select(MarketReaction, ReleaseStage, MarketInstrument)
                .join(ReleaseStage, ReleaseStage.id == MarketReaction.release_stage_id)
                .join(
                    MarketInstrument,
                    MarketInstrument.id == MarketReaction.instrument_id,
                )
                .where(MarketReaction.analysis_run_id == run.id)
                .order_by(ReleaseStage.sequence, MarketReaction.lead_rank)
            )
        ).all()
        return {
            "release_id": release_id,
            "analysis_run_id": str(run.id),
            "items": items,
            "reactions": [
                {
                    "stage_key": stage.stage_key,
                    "instrument_key": instrument.canonical_key,
                    "earliest_significant_at": (
                        _aware(reaction.earliest_significant_at).isoformat()
                        if reaction.earliest_significant_at
                        else None
                    ),
                    "latency_seconds": reaction.latency_seconds,
                    "pre_event_volatility": reaction.pre_event_volatility,
                    "significance_threshold": reaction.significance_threshold,
                    "confirmation_bars": reaction.confirmation_bars,
                    "initial_direction": reaction.initial_direction,
                    "reaction_strength": reaction.reaction_strength,
                    "lead_rank": reaction.lead_rank,
                    "granularity_seconds": reaction.granularity_seconds,
                    "limitations": reaction.limitations_json,
                }
                for reaction, stage, instrument in reactions
            ],
        }


async def get_release_timeline(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    factory = _factory(engine)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return None
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            return None
        stages = (
            await session.scalars(
                select(ReleaseStage)
                .where(ReleaseStage.macro_release_id == release.id)
                .order_by(ReleaseStage.sequence)
            )
        ).all()
        if not stages:
            return {"release_id": release_id, "stages": [], "series": {}}
        lower = min(_aware(item.scheduled_at) for item in stages) - timedelta(minutes=60)
        upper = max(_aware(item.scheduled_at) for item in stages) + timedelta(minutes=60)
        instruments = {
            str(row.id): row
            for row in (
                await session.scalars(select(MarketInstrument).order_by(MarketInstrument.id))
            ).all()
        }
        run = await _latest_run(session, release.id)
        snapshots = (
            [
                item
                for item in run.market_dataset_manifest_json
                if isinstance(item, dict)
                and item.get("selection_version") == "release-manifest-series-v1"
                and item.get("interval_seconds") == 60
            ]
            if run
            else []
        )
        if not snapshots:
            live_selection = await select_release_market_data(session, release, list(stages))
            snapshots = [
                selected.snapshot(
                    instrument_key=(
                        instruments[str(selected.instrument_id)].canonical_key
                        if str(selected.instrument_id) in instruments
                        else str(selected.instrument_id)
                    )
                )
                for (_instrument_id, interval), selected in live_selection.series.items()
                if interval == 60
            ]
        series: dict[str, object] = {}
        for snapshot in snapshots:
            instrument = instruments.get(str(snapshot.get("instrument_id")))
            if instrument is None:
                continue
            points = [
                item
                for item in snapshot.get("selected_bars", [])
                if isinstance(item, dict)
                and lower <= _aware(datetime.fromisoformat(str(item["timestamp"]))) <= upper
            ]
            if not points:
                continue
            points.sort(key=lambda item: str(item["timestamp"]))
            pre = [
                item
                for item in points
                if _aware(datetime.fromisoformat(str(item["timestamp"])))
                < lower + timedelta(minutes=60)
            ]
            baseline = Decimal(str((pre[-1] if pre else points[0])["close"]))
            series[instrument.canonical_key] = {
                "title": instrument.title,
                "symbol": instrument.symbol,
                "is_proxy": instrument.is_proxy,
                "proxy_for": instrument.proxy_for,
                "provider_key": snapshot.get("provider_key"),
                "contract_code": snapshot.get("contract_code"),
                "manifest_ids": [
                    item.get("manifest_id")
                    for item in snapshot.get("manifests", [])
                    if isinstance(item, dict)
                ],
                "points": [
                    {
                        "timestamp": str(item["timestamp"]),
                        "value": _float(Decimal(str(item["close"]))),
                        "normalized_percent": (
                            float(
                                (Decimal(str(item["close"])) - baseline) / baseline * Decimal(100)
                            )
                            if baseline != 0
                            else None
                        ),
                        "volume": (
                            _float(Decimal(str(item["volume"])))
                            if item.get("volume") is not None
                            else None
                        ),
                    }
                    for item in points
                ],
            }
        return {
            "release_id": release_id,
            "stages": [
                {
                    "key": item.stage_key,
                    "title": item.title,
                    "timestamp": _aware(item.released_at or item.scheduled_at).isoformat(),
                }
                for item in stages
            ],
            "series": series,
            "granularity_seconds": 60,
            "limitation": "标准化曲线不能判断同一分钟bar内的逐笔先后顺序。",
        }


async def get_release_historical(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    factory = _factory(engine)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return None
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            return None
        run = await _latest_run(session, release_uuid)
        if run is None:
            return {
                "release_id": release_id,
                "analysis_run_id": None,
                "mode": "not_analyzed",
                "reliability": "unavailable",
                "pre_filter_count": 0,
                "post_filter_count": 0,
                "filters": [],
                "metrics": {},
                "similar_cases": [],
                "warning": (
                    "No AnalysisRun exists for this release. Historical probabilities and "
                    "percentiles are unavailable until eligible actual, consensus and market "
                    "inputs have been analyzed."
                ),
            }
        return {
            "release_id": release_id,
            "analysis_run_id": str(run.id),
            **dict(run.parameters_json.get("historical", {})),
        }


async def get_release_explanations(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    factory = _factory(engine)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return None
        run = await _latest_run(session, release_uuid)
        if run is None:
            return None
        explanations = (
            await session.scalars(
                select(Explanation)
                .where(Explanation.analysis_run_id == run.id)
                .order_by(Explanation.rank)
            )
        ).all()
        report = await session.scalar(
            select(ReportArtifact).where(
                ReportArtifact.analysis_run_id == run.id,
                ReportArtifact.generator == "worldstate_deterministic",
            )
        )
        return {
            "release_id": release_id,
            "analysis_run_id": str(run.id),
            "facts": run.facts_json,
            "explanations": [
                {
                    "id": str(item.id),
                    "type": item.explanation_type,
                    "rank": item.rank,
                    "title": item.title,
                    "summary": item.summary,
                    "confidence": item.confidence,
                    "causal_language": item.causal_language,
                    "mechanism_steps": item.mechanism_steps_json,
                    "confirming_evidence": item.confirming_evidence_json,
                    "contradicting_evidence": item.contradicting_evidence_json,
                    "unresolved": item.unresolved_json,
                    "rule_key": item.rule_key,
                }
                for item in explanations
            ],
            "confidence": run.confidence,
            "data_gaps": run.data_gaps_json,
            "report": report.content if report else None,
            "report_validation": report.validation_json if report else None,
        }


async def get_evidence_pack(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    detail = await get_release_detail(engine, release_id)
    if detail is None:
        return None
    windows = await get_release_windows(engine, release_id)
    historical = await get_release_historical(engine, release_id)
    explanations = await get_release_explanations(engine, release_id)
    document: dict[str, object] = {
        "schema_version": "evidence-pack-v1",
        "release": detail,
        "market_reaction": windows,
        "historical": historical,
        "research": explanations,
        "constraints": {
            "facts_and_inferences_separated": True,
            "no_unique_causality_claim": True,
            "proxy_assets_labelled": True,
            "fixture_data_labelled": True,
        },
    }
    digest = hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    document["evidence_pack_hash"] = digest
    return document


async def get_quality_overview(engine: AsyncEngine) -> dict[str, object]:
    factory = _factory(engine)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(DataQualityRecord).order_by(DataQualityRecord.acquired_at.desc())
            )
        ).all()
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            counts[row.quality_grade] += 1
        return {
            "records": len(rows),
            "by_grade": dict(counts),
            "fixture_records": sum(row.is_fixture for row in rows),
            "proxy_records": sum(row.is_proxy for row in rows),
            "manual_records": sum(row.is_manual for row in rows),
            "items": [_quality_dict(row) for row in rows[:200]],
        }


async def get_provider_runs(engine: AsyncEngine) -> list[dict[str, object]]:
    factory = _factory(engine)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ProviderRun).order_by(ProviderRun.started_at.desc()).limit(200)
            )
        ).all()
        return [
            {
                "id": str(row.id),
                "provider_key": row.provider_key,
                "operation": row.operation,
                "status": row.status,
                "started_at": _aware(row.started_at).isoformat(),
                "completed_at": (
                    _aware(row.completed_at).isoformat() if row.completed_at else None
                ),
                "records_read": row.records_read,
                "records_written": row.records_written,
                "quality_grade": row.quality_grade,
                "warnings": row.warnings_json,
                "error_message": row.error_message,
            }
            for row in rows
        ]


async def get_current_regime(
    engine: AsyncEngine,
    *,
    data_mode: Literal["observed", "fixture", "all"] = "observed",
) -> dict[str, object]:
    factory = _factory(engine)
    async with factory() as session:
        run_query = (
            select(AnalysisRun)
            .join(MacroRelease, MacroRelease.id == AnalysisRun.macro_release_id)
            .where(
                AnalysisRun.status == "completed",
                AnalysisRun.regime_snapshot_id.is_not(None),
                AnalysisRun.reproducibility_status == "complete",
                AnalysisRun.data_mode == MacroRelease.data_mode,
            )
            .order_by(AnalysisRun.completed_at.desc(), AnalysisRun.id.desc())
        )
        if data_mode != "all":
            run_query = run_query.where(AnalysisRun.data_mode == data_mode)
        run = await session.scalar(run_query)
        if run is None or run.regime_snapshot_id is None:
            return {
                "state": "unavailable",
                "labels": [],
                "data_mode": data_mode,
                "data_gaps": ["尚无完成的宏观事件分析。"],
            }
        regime = await session.get(RegimeSnapshot, run.regime_snapshot_id)
        release = await session.get(MacroRelease, run.macro_release_id)
        if regime is None or release is None:
            return {
                "state": "unavailable",
                "labels": [],
                "data_mode": data_mode,
                "data_gaps": ["分析运行缺少对应的regime快照。"],
            }
        return {
            "state": "ready",
            "data_mode": run.data_mode,
            "as_of": _aware(regime.as_of).isoformat(),
            "release_id": str(release.id),
            "release_type": release.release_type,
            "release_title": release.title,
            "labels": regime.labels_json,
            "evidence": regime.evidence_json,
            "confidence": regime.confidence,
            "data_gaps": regime.data_gaps_json,
            "methodology_version": regime.methodology_version,
            "interpretation": "市场定价状态，不是对真实经济状态的预测。",
        }


async def create_manual_release(
    engine: AsyncEngine,
    *,
    release_key: str,
    release_type: str,
    title: str,
    period_label: str,
    scheduled_at: datetime,
    released_at: datetime | None,
    source_timezone: str,
    source_name: str,
    source_url: str,
    verified: bool,
    values: dict[str, dict[str, object]],
    stages: list[dict[str, object]],
    contamination_level: str,
    clean_window: bool,
    overlapping_events: list[dict[str, object]],
    confounding_notes: list[str],
) -> str:
    """Create a traceable manual release without silently inventing consensus."""

    if release_type not in RELEASE_INDICATORS:
        raise ValueError(f"unsupported release_type: {release_type}")
    factory = _factory(engine)
    async with factory() as session, session.begin():
        await _ensure_catalog(session)
        existing = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_key == release_key)
        )
        if existing is not None:
            raise ValueError("release_key already exists")
        release_id = uuid.uuid4()
        artifact_id = uuid.uuid4()
        quality_id = uuid.uuid4()
        now = datetime.now(UTC)
        payload_hash = hashlib.sha256(
            json.dumps(
                {
                    "release_key": release_key,
                    "values": values,
                    "stages": stages,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        session.add(
            SourceArtifact(
                id=artifact_id,
                source_key=f"{release_key}:manual-source",
                provider_key="manual",
                artifact_type="manual_release_entry",
                title=title,
                source_url=source_url,
                published_at=_aware(released_at or scheduled_at),
                retrieved_at=now,
                content_hash=payload_hash,
                license_name=None,
                citation_text=f"{source_name}: {source_url}",
                is_fixture=False,
                data_mode="observed",
                metadata_json={"entry_mode": "manual"},
            )
        )
        session.add(
            DataQualityRecord(
                id=quality_id,
                subject_type="macro_release",
                subject_id=str(release_id),
                source_name=source_name,
                source_url=source_url,
                source_type="manual_release_entry",
                acquired_at=now,
                is_manual=True,
                is_verified=verified,
                is_fixture=False,
                is_proxy=False,
                latency_seconds=None,
                granularity_seconds=None,
                missing_reason=None,
                quality_grade="B" if verified else "C",
                verification_notes=(
                    "Manually entered and marked verified."
                    if verified
                    else "Manual entry has not been independently verified."
                ),
                metadata_json={},
            )
        )
        session.add(
            MacroRelease(
                id=release_id,
                release_key=release_key,
                release_type=release_type,
                title=title,
                country="USA",
                period_label=period_label,
                scheduled_at=_aware(scheduled_at),
                released_at=_aware(released_at) if released_at else None,
                source_timezone=source_timezone,
                status="released" if released_at else "scheduled",
                data_version="manual-v1",
                data_mode="observed",
                source_artifact_id=artifact_id,
                primary_quality_id=quality_id,
                contamination_level=contamination_level,
                clean_window=clean_window,
                overlapping_events=overlapping_events,
                confounding_notes=confounding_notes,
                metadata_json={"data_mode": "manual"},
            )
        )
        stage_items = stages or [
            {
                "key": "release",
                "title": "数据公布",
                "scheduled_at": scheduled_at,
                "released_at": released_at,
            }
        ]
        stage_ids: dict[str, uuid.UUID] = {}
        for sequence, item in enumerate(stage_items, start=1):
            key = str(item["key"])
            stage_id = uuid.uuid4()
            stage_ids[key] = stage_id
            item_scheduled = item.get("scheduled_at") or scheduled_at
            item_released = item.get("released_at")
            if not isinstance(item_scheduled, datetime):
                raise TypeError("stage scheduled_at must be datetime")
            if item_released is not None and not isinstance(item_released, datetime):
                raise TypeError("stage released_at must be datetime")
            session.add(
                ReleaseStage(
                    id=stage_id,
                    macro_release_id=release_id,
                    stage_key=key,
                    title=str(item["title"]),
                    sequence=sequence,
                    scheduled_at=_aware(item_scheduled),
                    released_at=_aware(item_released) if item_released else None,
                    status="released" if item_released else "scheduled",
                    source_artifact_id=artifact_id,
                    metadata_json={"entry_mode": "manual"},
                )
            )
        await session.flush()
        indicator_rows = {
            row.indicator_key: row
            for row in (
                await session.scalars(
                    select(Indicator).where(
                        Indicator.indicator_key.in_(RELEASE_INDICATORS[release_type])
                    )
                )
            ).all()
        }
        captured_at = _aware(released_at or scheduled_at)
        for key, entry in values.items():
            indicator = indicator_rows.get(key)
            if indicator is None:
                raise ValueError(f"indicator {key} is not valid for {release_type}")
            stage_key = str(entry.get("stage_key") or stage_items[0]["key"])
            value_stage_id = stage_ids.get(stage_key)
            if value_stage_id is None:
                raise ValueError(f"unknown stage_key for value {key}: {stage_key}")
            for value_kind in ("actual", "previous", "revised_previous"):
                value = entry.get(value_kind)
                if value is None:
                    continue
                session.add(
                    ReleaseValue(
                        id=uuid.uuid4(),
                        macro_release_id=release_id,
                        release_stage_id=value_stage_id,
                        indicator_id=indicator.id,
                        value_kind=value_kind,
                        value=Decimal(str(value)),
                        raw_value=str(value),
                        data_version="manual-v1",
                        valid_from=captured_at,
                        captured_at=captured_at,
                        is_initial=value_kind == "actual",
                        data_mode="observed",
                        source_artifact_id=artifact_id,
                        quality_id=quality_id,
                        metadata_json={"entry_mode": "manual"},
                    )
                )
        return str(release_id)
