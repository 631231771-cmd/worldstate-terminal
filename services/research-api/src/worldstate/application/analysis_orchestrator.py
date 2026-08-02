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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.ai_researcher.claims import deterministic_claims, validate_claims
from worldstate.config import repository_root
from worldstate.db.models import (
    AnalysisRun,
    ConsensusSnapshot,
    DataQualityRecord,
    EventWindowDefinition,
    EventWindowResult,
    EvidenceItem,
    Explanation,
    FuturesContract,
    HistoricalMatch,
    Indicator,
    MacroRelease,
    MarketBar,
    MarketInstrument,
    MarketReaction,
    ProviderRun,
    RegimeSnapshot,
    ReleaseStage,
    ReleaseValue,
    ReportArtifact,
    ResearchClaim,
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
    WINDOW_SPECS,
    calculate_event_windows,
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

METHODOLOGY_VERSION = "macro-event-engine-v0.4"
CODE_VERSION = "macro-research-terminal-v0.4"
_NAMESPACE = uuid.UUID("fbf59be7-d632-4f3c-a5a0-104425f478c2")


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _stable_uuid(value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, value)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
        if indicator_definition.key in existing_indicators:
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
        if instrument_definition.key in existing_instruments:
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
                metadata_json={"catalog_version": CODE_VERSION},
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
        "dollar_dxy": "SPOT",
        "eurusd": "SPOT",
        "usdjpy": "SPOT",
        "vix": "INDEX",
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
        release_types = set(
            (await session.scalars(select(MacroRelease.release_type).distinct())).all()
        )
        for fixture in _load_demo_releases():
            if str(fixture["release_type"]) in release_types:
                continue
            created.append(await _seed_release(session, fixture))
            release_types.add(str(fixture["release_type"]))
        for release_type in ("US_CPI", "US_NFP", "FOMC"):
            latest_release = await session.scalar(
                select(MacroRelease)
                .where(MacroRelease.release_type == release_type)
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


async def _value_inputs(
    session: AsyncSession,
    release: MacroRelease,
) -> tuple[list[IndicatorInput], dict[str, dict[str, object]], dict[str, Indicator]]:
    keys = RELEASE_INDICATORS.get(release.release_type, ())
    indicator_rows = (
        await session.scalars(select(Indicator).where(Indicator.indicator_key.in_(keys)))
    ).all()
    indicators = {row.indicator_key: row for row in indicator_rows}
    values = (
        await session.scalars(
            select(ReleaseValue)
            .where(ReleaseValue.macro_release_id == release.id)
            .order_by(ReleaseValue.captured_at)
        )
    ).all()
    latest_values: dict[tuple[uuid.UUID, str], ReleaseValue] = {}
    for row in values:
        latest_values[(row.indicator_id, row.value_kind)] = row
    consensus = (
        await session.scalars(
            select(ConsensusSnapshot)
            .where(
                ConsensusSnapshot.macro_release_id == release.id,
                ConsensusSnapshot.captured_at <= (release.released_at or release.scheduled_at),
            )
            .order_by(ConsensusSnapshot.captured_at)
        )
    ).all()
    latest_consensus: dict[uuid.UUID, ConsensusSnapshot] = {}
    for consensus_row in consensus:
        latest_consensus[consensus_row.indicator_id] = consensus_row

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
    cutoff = _aware(release.released_at or release.scheduled_at)
    historical = (
        await session.scalars(
            select(MacroRelease)
            .where(
                MacroRelease.release_type == release.release_type,
                MacroRelease.id != release.id,
                MacroRelease.released_at < cutoff,
            )
            .order_by(MacroRelease.released_at)
        )
    ).all()
    output: dict[str, list[HistoricalSurpriseObservation]] = {key: [] for key in indicators}
    for prior in historical:
        for key, indicator in indicators.items():
            actual = await session.scalar(
                select(ReleaseValue)
                .where(
                    ReleaseValue.macro_release_id == prior.id,
                    ReleaseValue.indicator_id == indicator.id,
                    ReleaseValue.value_kind == "actual",
                )
                .order_by(ReleaseValue.captured_at)
                .limit(1)
            )
            consensus = await session.scalar(
                select(ConsensusSnapshot)
                .where(
                    ConsensusSnapshot.macro_release_id == prior.id,
                    ConsensusSnapshot.indicator_id == indicator.id,
                    ConsensusSnapshot.captured_at
                    <= _aware(prior.released_at or prior.scheduled_at),
                )
                .order_by(ConsensusSnapshot.captured_at.desc())
                .limit(1)
            )
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
            select(MacroRelease).where(MacroRelease.release_type == release.release_type)
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
                is_fixture=run.parameters_json.get("data_mode") == "fixture",
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
        lower = min(
            _aware(stage.released_at or stage.scheduled_at) for stage in stages
        ) - timedelta(minutes=60)
        upper = max(
            _aware(stage.released_at or stage.scheduled_at) for stage in stages
        ) + timedelta(days=7)
        bars = (
            await session.scalars(
                select(MarketBar)
                .where(
                    MarketBar.timestamp >= lower,
                    MarketBar.timestamp <= upper,
                    MarketBar.interval_seconds == 60,
                )
                .order_by(MarketBar.timestamp)
            )
        ).all()
        bars_by_instrument: dict[uuid.UUID, list[MarketBar]] = defaultdict(list)
        for bar in bars:
            bars_by_instrument[bar.instrument_id].append(bar)

        release_values = (
            await session.scalars(
                select(ReleaseValue)
                .where(ReleaseValue.macro_release_id == release.id)
                .order_by(ReleaseValue.captured_at, ReleaseValue.id)
            )
        ).all()
        consensus_rows = (
            await session.scalars(
                select(ConsensusSnapshot)
                .where(
                    ConsensusSnapshot.macro_release_id == release.id,
                    ConsensusSnapshot.captured_at
                    <= _aware(release.released_at or release.scheduled_at),
                )
                .order_by(ConsensusSnapshot.captured_at, ConsensusSnapshot.id)
            )
        ).all()
        market_manifest = [
            {
                "market_bar_id": row.id,
                "instrument_id": str(row.instrument_id),
                "contract_id": str(row.futures_contract_id) if row.futures_contract_id else None,
                "provider_key": row.provider_key,
                "source_symbol": row.source_symbol,
                "contract_code": row.contract_code,
                "timestamp": _aware(row.timestamp).isoformat(),
                "interval_seconds": row.interval_seconds,
                "open": str(row.open_value),
                "high": str(row.high_value),
                "low": str(row.low_value),
                "close": str(row.close_value),
                "volume": str(row.volume) if row.volume is not None else None,
                "quality_id": str(row.quality_id) if row.quality_id else None,
            }
            for row in bars
        ]
        market_hash = _stable_hash(market_manifest)
        release_snapshot = {
            "release_id": str(release.id),
            "release_key": release.release_key,
            "release_type": release.release_type,
            "scheduled_at": _aware(release.scheduled_at).isoformat(),
            "released_at": _aware(release.released_at or release.scheduled_at).isoformat(),
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
        }
        algorithm_versions = {
            "surprise": "surprise-v0.4",
            "history": "macro-history-v0.4-fixed",
            "windows": "exchange-session-lite-v0.4",
        }
        rule_versions = {
            "regime": "macro-regime-v0.4",
            "explanation": "deterministic-explanation-v3",
        }
        analysis_parameters = {
            "minimum_z_score_sample": 20,
            "calendar_precision": "exchange_session_lite",
            "contamination_policy": "exclude_high_penalize_mismatch_v1",
        }
        run.release_snapshot_json = release_snapshot
        run.release_value_ids_json = [str(row.id) for row in release_values]
        run.consensus_snapshot_ids_json = [str(row.id) for row in consensus_rows]
        run.release_stage_ids_json = [str(row.id) for row in stages]
        run.market_dataset_manifest_json = market_manifest
        run.market_dataset_hash = market_hash
        run.provider_manifest_json = [
            json.loads(item)
            for item in sorted(
                {
                    json.dumps(
                        {
                            "provider_key": row.provider_key,
                            "source_symbol": row.source_symbol,
                            "contract_code": row.contract_code,
                        },
                        sort_keys=True,
                    )
                    for row in bars
                }
            )
        ]
        run.source_artifact_ids_json = [
            str(row.source_artifact_id) for row in release_values if row.source_artifact_id
        ]
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

        stage_windows: dict[str, dict[str, dict[str, ComputedWindow]]] = {}
        earliest_rows: list[dict[str, object]] = []
        reaction_records: list[MarketReaction] = []
        for stage in stages:
            stage_key = stage.stage_key
            stage_at = _aware(stage.released_at or stage.scheduled_at)
            stage_windows[stage_key] = {}
            stage_reactions: list[tuple[MarketInstrument, Any]] = []
            for instrument in instruments:
                rows = bars_by_instrument.get(instrument.id, [])
                if not rows:
                    continue
                records = [_bar_record(row, instrument.canonical_key) for row in rows]
                grade = next(
                    (
                        quality_by_id[row.quality_id].quality_grade
                        for row in rows
                        if row.quality_id in quality_by_id
                    ),
                    "UNKNOWN",
                )
                computed = calculate_event_windows(
                    records,
                    release_at=stage_at,
                    interval_seconds=60,
                    source_grade=grade,
                    instrument_key=instrument.canonical_key,
                )
                stage_windows[stage_key][instrument.canonical_key] = {
                    item.key: item for item in computed
                }
                provider_key = rows[0].provider_key
                for item in computed:
                    definition = window_definitions.get(item.key)
                    if definition is None:
                        continue
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
                            provider_key=provider_key,
                            quality_grade=item.quality_grade,
                            missing_reason=item.missing_reason,
                            calculated_at=datetime.now(UTC),
                            metadata_json={
                                "stage_key": stage_key,
                                "proxy_disclosure": instrument.proxy_for,
                                "calendar": item.calendar_name,
                                "calendar_precision": item.calendar_precision,
                                "expected_tradable_bars": item.expected_tradable_bars,
                            },
                        )
                    )
                earliest = detect_earliest_reaction(
                    instrument.canonical_key,
                    records,
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
                strongest = max(
                    computed,
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
                        limitations_json=(
                            [earliest.limitation]
                            if earliest is not None
                            else ["No volatility-adjusted significant reaction was observed."]
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
        )
        regime_hash = hashlib.sha256(
            json.dumps(
                {
                    "release_id": str(release.id),
                    "labels": regime.labels,
                    "evidence": regime.evidence,
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        regime_row = RegimeSnapshot(
            id=uuid.uuid4(),
            as_of=_aware(release.released_at or release.scheduled_at),
            methodology_version="macro-regime-v1",
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
                records = [
                    _bar_record(row, instrument.canonical_key)
                    for row in bars_by_instrument.get(instrument.id, [])
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
            "data_mode": "fixture" if is_fixture else "observed",
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
    try:
        run_id = await _execute_analysis(engine, release_id)
    except LookupError:
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
                    error_message=str(exc)[:2000],
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
) -> list[dict[str, object]]:
    await bootstrap_research_data(engine)
    factory = _factory(engine)
    async with factory() as session:
        query = select(MacroRelease).order_by(MacroRelease.scheduled_at.desc()).limit(limit)
        if release_type:
            query = query.where(MacroRelease.release_type == release_type)
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
                    "data_mode": (
                        str(run.parameters_json.get("data_mode", "unknown")) if run else "unknown"
                    ),
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
    stage_times = (
        await session.scalars(
            select(ReleaseStage).where(ReleaseStage.macro_release_id == release.id)
        )
    ).all()
    if stage_times:
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


async def get_release_detail(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    await bootstrap_research_data(engine)
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
        rows = (
            await session.execute(
                select(MarketBar, MarketInstrument)
                .join(MarketInstrument, MarketInstrument.id == MarketBar.instrument_id)
                .where(
                    MarketBar.timestamp >= lower,
                    MarketBar.timestamp <= upper,
                    MarketBar.interval_seconds == 60,
                )
                .order_by(MarketInstrument.canonical_key, MarketBar.timestamp)
            )
        ).all()
        grouped: dict[str, list[tuple[MarketBar, MarketInstrument]]] = defaultdict(list)
        for bar, instrument in rows:
            grouped[instrument.canonical_key].append((bar, instrument))
        series: dict[str, object] = {}
        for key, items in grouped.items():
            pre = [
                bar
                for bar, _instrument in items
                if _aware(bar.timestamp) < lower + timedelta(minutes=60)
            ]
            baseline = pre[-1].close_value if pre else items[0][0].close_value
            instrument = items[0][1]
            series[key] = {
                "title": instrument.title,
                "symbol": instrument.symbol,
                "is_proxy": instrument.is_proxy,
                "proxy_for": instrument.proxy_for,
                "points": [
                    {
                        "timestamp": _aware(bar.timestamp).isoformat(),
                        "value": _float(bar.close_value),
                        "normalized_percent": (
                            float((bar.close_value - baseline) / baseline * Decimal(100))
                            if baseline != 0
                            else None
                        ),
                        "volume": _float(bar.volume),
                    }
                    for bar, _instrument in items
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
        run = await _latest_run(session, release_uuid)
        if run is None:
            return None
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


async def get_current_regime(engine: AsyncEngine) -> dict[str, object]:
    factory = _factory(engine)
    async with factory() as session:
        run = await session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.status == "completed",
                AnalysisRun.regime_snapshot_id.is_not(None),
            )
            .order_by(AnalysisRun.completed_at.desc())
        )
        if run is None or run.regime_snapshot_id is None:
            return {
                "state": "unavailable",
                "labels": [],
                "data_gaps": ["尚无完成的宏观事件分析。"],
            }
        regime = await session.get(RegimeSnapshot, run.regime_snapshot_id)
        release = await session.get(MacroRelease, run.macro_release_id)
        if regime is None or release is None:
            return {
                "state": "unavailable",
                "labels": [],
                "data_gaps": ["分析运行缺少对应的regime快照。"],
            }
        return {
            "state": "ready",
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
                        source_artifact_id=artifact_id,
                        quality_id=quality_id,
                        metadata_json={"entry_mode": "manual"},
                    )
                )
        return str(release_id)
