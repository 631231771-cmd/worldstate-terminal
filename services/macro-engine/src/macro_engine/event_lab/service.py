"""Persistence and orchestration for the CPI Event Lab vertical slice."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from macro_engine.data_quality import DataQuality, QualityGrade
from macro_engine.db.models import (
    ConsensusSnapshot,
    DataQualityRecord,
    EventAnalysis,
    EventIndicator,
    EventWindowMetric,
    MacroEvent,
    MarketBar,
    MarketInstrument,
)
from macro_engine.event_lab.explanation import build_structured_explanation
from macro_engine.event_lab.fixtures import (
    CPI_FIXTURES,
    INSTRUMENTS,
    CpiFixture,
    generate_fixture_bars,
)
from macro_engine.event_lab.history import (
    compare_historical_events,
    magnitude_bucket,
)
from macro_engine.event_lab.macrosynergy_adapter import MacrosynergyAdapter
from macro_engine.event_lab.schemas import (
    ConsensusCaptureInput,
    CpiEventInput,
    CsvMarketImportInput,
)
from macro_engine.event_lab.surprise import calculate_bundle_surprise
from macro_engine.event_lab.types import (
    BundleSurprise,
    ComputedWindow,
    EarliestReaction,
    HistoricalCase,
    IndicatorInput,
)
from macro_engine.event_lab.windows import (
    calculate_event_windows,
    detect_earliest_reaction,
)
from macro_engine.market_data import (
    BarQuery,
    CsvMarketBarProvider,
    FixtureMarketBarProvider,
    MarketBarRecord,
    MarketInstrumentRef,
)

METHODOLOGY_VERSION = "cpi-event-lab-v1"


class IndicatorDefinition(TypedDict):
    title: str
    unit: str
    weight: float


INDICATOR_DEFINITIONS: dict[str, IndicatorDefinition] = {
    "headline_mom": {
        "title": "Headline CPI MoM",
        "unit": "%",
        "weight": 0.2,
    },
    "headline_yoy": {
        "title": "Headline CPI YoY",
        "unit": "%",
        "weight": 0.2,
    },
    "core_mom": {
        "title": "Core CPI MoM",
        "unit": "%",
        "weight": 0.35,
    },
    "core_yoy": {
        "title": "Core CPI YoY",
        "unit": "%",
        "weight": 0.25,
    },
}
INDICATOR_KEYS = tuple(INDICATOR_DEFINITIONS)


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _required_float(value: object) -> float:
    if not isinstance(value, int | float | Decimal):
        raise TypeError(f"expected numeric value, received {type(value).__name__}")
    return float(value)


def _required_int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError(f"expected integer value, received {type(value).__name__}")
    return value


def _quality_lookup(
    rows: dict[uuid.UUID, DataQualityRecord],
    quality_id: uuid.UUID | None,
) -> DataQualityRecord | None:
    return rows.get(quality_id) if quality_id is not None else None


async def _persist_quality(
    session: AsyncSession,
    quality: DataQuality,
) -> DataQualityRecord:
    row = DataQualityRecord(**quality.to_storage())
    session.add(row)
    await session.flush()
    return row


def _instrument_ref(row: MarketInstrument) -> MarketInstrumentRef:
    return MarketInstrumentRef(
        canonical_key=row.canonical_key,
        symbol=row.symbol,
        title=row.title,
        exchange=row.exchange,
        quote_unit=row.quote_unit,
        is_proxy=row.is_proxy,
        proxy_for=row.proxy_for,
    )


def _bar_record(row: MarketBar, instrument_key: str) -> MarketBarRecord:
    return MarketBarRecord(
        instrument_key=instrument_key,
        timestamp=_as_utc(row.timestamp),
        interval_seconds=row.interval_seconds,
        open_value=row.open_value,
        high_value=row.high_value,
        low_value=row.low_value,
        close_value=row.close_value,
        volume=row.volume,
        source_symbol=row.source_symbol,
        contract_code=row.contract_code,
        metadata=row.metadata_json,
    )


def _window_storage(
    *,
    event_id: uuid.UUID,
    instrument_id: uuid.UUID,
    provider_key: str,
    item: ComputedWindow,
    calculated_at: datetime,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "instrument_id": instrument_id,
        "window_key": item.key,
        "start_at": item.start_at,
        "end_at": item.end_at,
        "start_value": item.start_value,
        "end_value": item.end_value,
        "change_absolute": item.change_absolute,
        "return_percent": item.return_percent,
        "max_up_percent": item.max_up_percent,
        "max_down_percent": item.max_down_percent,
        "realized_volatility": item.realized_volatility,
        "volume_change_percent": item.volume_change_percent,
        "coverage_ratio": item.coverage_ratio,
        "direction": item.direction,
        "spike_fade": item.spike_fade,
        "dip_recovery": item.dip_recovery,
        "direction_reversal": item.direction_reversal,
        "granularity_seconds": item.granularity_seconds,
        "provider_key": provider_key,
        "quality_grade": item.quality_grade,
        "calculated_at": calculated_at,
        "metadata_json": {
            "label": item.label,
            "missing_reason": item.missing_reason,
        },
    }


async def _upsert_windows(
    session: AsyncSession,
    *,
    event: MacroEvent,
    instrument: MarketInstrument,
    bars: list[MarketBarRecord],
    provider_key: str,
    quality_grade: str,
) -> list[ComputedWindow]:
    calculated = calculate_event_windows(
        bars,
        release_at=_as_utc(event.release_at),
        interval_seconds=60,
        source_grade=quality_grade,
    )
    existing = {
        row.window_key: row
        for row in (
            await session.scalars(
                select(EventWindowMetric).where(
                    EventWindowMetric.event_id == event.id,
                    EventWindowMetric.instrument_id == instrument.id,
                )
            )
        ).all()
    }
    calculated_at = datetime.now(UTC)
    for item in calculated:
        values = _window_storage(
            event_id=event.id,
            instrument_id=instrument.id,
            provider_key=provider_key,
            item=item,
            calculated_at=calculated_at,
        )
        row = existing.get(item.key)
        if row is None:
            session.add(EventWindowMetric(**values))
        else:
            for key, value in values.items():
                if key not in {"event_id", "instrument_id", "window_key"}:
                    setattr(row, key, value)
    await session.flush()
    return calculated


async def _ensure_instruments(
    session: AsyncSession,
) -> dict[str, MarketInstrument]:
    existing = {
        row.canonical_key: row for row in (await session.scalars(select(MarketInstrument))).all()
    }
    for definition in INSTRUMENTS:
        key = str(definition["canonical_key"])
        if key in existing:
            continue
        row = MarketInstrument(
            canonical_key=key,
            symbol=str(definition["symbol"]),
            root_symbol=str(definition["root_symbol"]),
            contract_code=(
                str(definition["contract_code"])
                if definition["contract_code"] is not None
                else None
            ),
            exchange=str(definition["exchange"]),
            title=str(definition["title"]),
            asset_class=str(definition["asset_class"]),
            quote_unit=str(definition["quote_unit"]),
            measurement_type=str(definition["measurement_type"]),
            source_timezone=str(definition["source_timezone"]),
            is_proxy=bool(definition["is_proxy"]),
            proxy_for=(
                str(definition["proxy_for"]) if definition["proxy_for"] is not None else None
            ),
            metadata_json={
                "contract_policy": "explicit_contract_no_silent_roll",
                "fixture_contract": definition["contract_code"],
            },
        )
        session.add(row)
        await session.flush()
        existing[key] = row
    return existing


def _fixture_indicator_inputs(fixture: CpiFixture) -> list[IndicatorInput]:
    return [
        IndicatorInput(
            key=key,
            title=str(INDICATOR_DEFINITIONS[key]["title"]),
            actual=Decimal(str(fixture.actuals[index])),
            consensus=Decimal(str(fixture.consensus[index])),
            previous=Decimal(str(fixture.previous[index])),
            revised_previous=Decimal(str(fixture.revised_previous[index])),
            weight=float(INDICATOR_DEFINITIONS[key]["weight"]),
        )
        for index, key in enumerate(INDICATOR_KEYS)
    ]


def _core_direction(bundle: BundleSurprise) -> str:
    core = [
        row.standardized
        for row in bundle.indicators
        if row.key in {"core_mom", "core_yoy"} and row.standardized is not None
    ]
    if not core:
        return "mixed"
    average = sum(core) / len(core)
    return "hot" if average > 0.25 else "cold" if average < -0.25 else "mixed"


async def _seed_fixture_event(
    session: AsyncSession,
    fixture: CpiFixture,
    instruments: dict[str, MarketInstrument],
) -> MacroEvent:
    actual_quality = await _persist_quality(
        session,
        DataQuality(
            source_name="U.S. Bureau of Labor Statistics",
            source_url=fixture.source_url,
            source_type="official_release",
            acquired_at=datetime(2026, 7, 30, tzinfo=UTC),
            is_manual=not fixture.verified_actual,
            is_verified=fixture.verified_actual,
            is_fixture=not fixture.verified_actual,
            quality_grade=QualityGrade.A if fixture.verified_actual else QualityGrade.C,
            verification_notes=(
                "January 2024 values checked against the archived BLS release."
                if fixture.verified_actual
                else "Historical comparison fixture; re-check before production use."
            ),
        ),
    )
    consensus_quality = await _persist_quality(
        session,
        DataQuality(
            source_name=(
                "Reuters economist poll via archived report"
                if fixture.verified_consensus
                else "WorldState historical consensus fixture"
            ),
            source_url=fixture.consensus_source_url,
            source_type="consensus_snapshot",
            acquired_at=fixture.release_at - timedelta(hours=12),
            is_manual=True,
            is_verified=fixture.verified_consensus,
            is_fixture=not fixture.verified_consensus,
            quality_grade=QualityGrade.B if fixture.verified_consensus else QualityGrade.C,
            verification_notes=("Captured as a pre-release consensus snapshot for demonstration."),
        ),
    )
    bundle = calculate_bundle_surprise(_fixture_indicator_inputs(fixture))
    event = MacroEvent(
        event_key=fixture.event_key,
        event_type="US_CPI",
        title="美国消费者价格指数（CPI）",
        country="USA",
        period_label=fixture.period_label,
        release_at=fixture.release_at,
        source_timezone="America/New_York",
        status="released",
        source_url=fixture.source_url,
        data_version="initial",
        is_fixture=True,
        contamination_level=fixture.contamination_level,
        clean_window=fixture.clean_window,
        overlapping_events=list(fixture.overlapping_events),
        confounding_notes=list(fixture.confounding_notes),
        primary_quality_id=actual_quality.id,
        metadata_json={
            "bundle_classification": bundle.classification,
            "bundle_score": bundle.score,
            "bundle_direction": bundle.direction,
            "core_direction": _core_direction(bundle),
            "regime_tags": ["high_rates_pause", "inflation_disinflating"],
            "fixture_scope": "market_bars_and_unverified_historical_consensus",
        },
    )
    session.add(event)
    await session.flush()

    for index, indicator_input in enumerate(_fixture_indicator_inputs(fixture)):
        surprise = bundle.indicators[index]
        session.add(
            EventIndicator(
                event_id=event.id,
                indicator_key=indicator_input.key,
                title=indicator_input.title,
                unit="%",
                actual_value=indicator_input.actual,
                previous_value=indicator_input.previous,
                revised_previous_value=indicator_input.revised_previous,
                first_release_value=indicator_input.actual,
                data_version="initial",
                hotter_when_higher=True,
                bundle_weight=indicator_input.weight,
                raw_surprise=surprise.raw,
                relative_surprise=surprise.relative,
                standardized_surprise=surprise.standardized,
                surprise_direction=surprise.direction,
                source_url=fixture.source_url,
                actual_quality_id=actual_quality.id,
                metadata_json={"history_samples": surprise.history_samples},
            )
        )
        session.add(
            ConsensusSnapshot(
                event_id=event.id,
                indicator_key=indicator_input.key,
                consensus_value=indicator_input.consensus,
                consensus_source=(
                    "Reuters economist poll (archived secondary page)"
                    if fixture.verified_consensus
                    else "WorldState historical consensus fixture"
                ),
                consensus_source_url=fixture.consensus_source_url,
                consensus_captured_at=fixture.release_at - timedelta(hours=12),
                consensus_quality=("verified" if fixture.verified_consensus else "fixture"),
                consensus_is_manual=True,
                verification_notes=consensus_quality.verification_notes,
                quality_id=consensus_quality.id,
            )
        )
    await session.flush()

    for definition in INSTRUMENTS:
        key = str(definition["canonical_key"])
        instrument = instruments[key]
        records = generate_fixture_bars(fixture, definition)
        provider = FixtureMarketBarProvider(
            {key: records},
            source_name="WorldState deterministic CPI market fixture",
            source_url=None,
            acquired_at=datetime(2026, 7, 30, tzinfo=UTC),
        )
        query = BarQuery(
            instrument=_instrument_ref(instrument),
            start=fixture.release_at - timedelta(minutes=60),
            end=fixture.release_at + timedelta(hours=4),
            interval_seconds=60,
        )
        batch = await provider.fetch_bars(query)
        quality = await _persist_quality(session, batch.quality)
        session.add_all(
            [
                MarketBar(
                    instrument_id=instrument.id,
                    timestamp=bar.timestamp,
                    interval_seconds=bar.interval_seconds,
                    open_value=bar.open_value,
                    high_value=bar.high_value,
                    low_value=bar.low_value,
                    close_value=bar.close_value,
                    volume=bar.volume,
                    provider_key=batch.provider_key,
                    source_symbol=bar.source_symbol,
                    contract_code=bar.contract_code,
                    quality_id=quality.id,
                    fetched_at=batch.fetched_at,
                    metadata_json=bar.metadata,
                )
                for bar in batch.bars
            ]
        )
        await session.flush()
        await _upsert_windows(
            session,
            event=event,
            instrument=instrument,
            bars=batch.bars,
            provider_key=batch.provider_key,
            quality_grade=batch.quality.quality_grade.value,
        )
    return event


async def _latest_consensus(
    session: AsyncSession,
    event_id: uuid.UUID,
) -> dict[str, ConsensusSnapshot]:
    rows = (
        await session.scalars(
            select(ConsensusSnapshot)
            .where(ConsensusSnapshot.event_id == event_id)
            .order_by(ConsensusSnapshot.consensus_captured_at)
        )
    ).all()
    output: dict[str, ConsensusSnapshot] = {}
    for row in rows:
        output[row.indicator_key] = row
    return output


async def _bundle_for_event(
    session: AsyncSession,
    event: MacroEvent,
) -> tuple[BundleSurprise, list[EventIndicator], dict[str, ConsensusSnapshot]]:
    indicators = (
        await session.scalars(
            select(EventIndicator)
            .where(EventIndicator.event_id == event.id)
            .order_by(EventIndicator.indicator_key)
        )
    ).all()
    latest = await _latest_consensus(session, event.id)
    history_rows = (
        await session.scalars(select(EventIndicator).where(EventIndicator.event_id != event.id))
    ).all()
    histories: dict[str, list[float]] = defaultdict(list)
    for row in history_rows:
        if row.raw_surprise is not None:
            histories[row.indicator_key].append(float(row.raw_surprise))

    inputs = [
        IndicatorInput(
            key=row.indicator_key,
            title=row.title,
            actual=row.actual_value,
            consensus=(
                latest[row.indicator_key].consensus_value if row.indicator_key in latest else None
            ),
            previous=row.previous_value,
            revised_previous=row.revised_previous_value,
            weight=row.bundle_weight,
            hotter_when_higher=row.hotter_when_higher,
        )
        for row in indicators
    ]
    bundle = calculate_bundle_surprise(inputs, historical_surprises=dict(histories))
    by_key = {item.key: item for item in bundle.indicators}
    for row in indicators:
        result = by_key[row.indicator_key]
        row.raw_surprise = result.raw
        row.relative_surprise = result.relative
        row.standardized_surprise = result.standardized
        row.surprise_direction = result.direction
        row.metadata_json = {
            **row.metadata_json,
            "history_samples": result.history_samples,
        }
    event.metadata_json = {
        **event.metadata_json,
        "bundle_classification": bundle.classification,
        "bundle_score": bundle.score,
        "bundle_direction": bundle.direction,
        "core_direction": _core_direction(bundle),
    }
    await session.flush()
    return bundle, list(indicators), latest


async def _load_window_map(
    session: AsyncSession,
    event_id: uuid.UUID,
) -> tuple[
    dict[str, dict[str, ComputedWindow]],
    dict[str, MarketInstrument],
    dict[str, str],
]:
    rows = (
        await session.execute(
            select(EventWindowMetric, MarketInstrument)
            .join(MarketInstrument, EventWindowMetric.instrument_id == MarketInstrument.id)
            .where(EventWindowMetric.event_id == event_id)
        )
    ).all()
    output: dict[str, dict[str, ComputedWindow]] = defaultdict(dict)
    instruments: dict[str, MarketInstrument] = {}
    providers: dict[str, str] = {}
    for metric, instrument in rows:
        instruments[instrument.canonical_key] = instrument
        providers[instrument.canonical_key] = metric.provider_key
        output[instrument.canonical_key][metric.window_key] = ComputedWindow(
            key=metric.window_key,
            label=str(metric.metadata_json.get("label") or metric.window_key),
            start_at=_as_utc(metric.start_at),
            end_at=_as_utc(metric.end_at),
            start_value=metric.start_value,
            end_value=metric.end_value,
            change_absolute=metric.change_absolute,
            return_percent=metric.return_percent,
            max_up_percent=metric.max_up_percent,
            max_down_percent=metric.max_down_percent,
            realized_volatility=metric.realized_volatility,
            volume_change_percent=metric.volume_change_percent,
            coverage_ratio=metric.coverage_ratio,
            direction=metric.direction,
            spike_fade=metric.spike_fade,
            dip_recovery=metric.dip_recovery,
            direction_reversal=metric.direction_reversal,
            granularity_seconds=metric.granularity_seconds,
            quality_grade=metric.quality_grade,
            missing_reason=(
                str(metric.metadata_json["missing_reason"])
                if metric.metadata_json.get("missing_reason")
                else None
            ),
        )
    return dict(output), instruments, providers


async def _earliest_reactions(
    session: AsyncSession,
    event: MacroEvent,
    instruments: dict[str, MarketInstrument],
    providers: dict[str, str],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for key, instrument in instruments.items():
        provider_key = providers.get(key)
        conditions = [
            MarketBar.instrument_id == instrument.id,
            MarketBar.timestamp >= event.release_at - timedelta(minutes=60),
            MarketBar.timestamp <= event.release_at + timedelta(minutes=60),
            MarketBar.interval_seconds == 60,
        ]
        if provider_key:
            conditions.append(MarketBar.provider_key == provider_key)
        rows = (
            await session.scalars(
                select(MarketBar).where(*conditions).order_by(MarketBar.timestamp)
            )
        ).all()
        reaction = detect_earliest_reaction(
            key,
            [_bar_record(row, key) for row in rows],
            release_at=_as_utc(event.release_at),
            interval_seconds=60,
        )
        if reaction is None:
            continue
        results.append(
            {
                "instrument_key": reaction.instrument_key,
                "detected_at": reaction.detected_at.isoformat(),
                "lag_seconds": reaction.lag_seconds,
                "move_percent": reaction.move_percent,
                "direction": reaction.direction,
                "threshold_percent": reaction.threshold_percent,
                "pre_event_volatility": reaction.pre_event_volatility,
                "granularity_seconds": reaction.granularity_seconds,
                "confirmation_bars": reaction.confirmation_bars,
                "limitation": reaction.limitation,
            }
        )
    results.sort(key=lambda row: (_required_int(row["lag_seconds"]), str(row["instrument_key"])))
    return results


async def _historical_cases(
    session: AsyncSession,
) -> list[HistoricalCase]:
    events = (
        await session.scalars(select(MacroEvent).where(MacroEvent.event_type == "US_CPI"))
    ).all()
    metric_rows = (
        await session.execute(
            select(EventWindowMetric, MarketInstrument)
            .join(MarketInstrument, EventWindowMetric.instrument_id == MarketInstrument.id)
            .where(EventWindowMetric.window_key == "post_5m")
        )
    ).all()
    returns: dict[uuid.UUID, dict[str, float | None]] = defaultdict(dict)
    for metric, instrument in metric_rows:
        returns[metric.event_id][f"{instrument.canonical_key}:post_5m"] = metric.return_percent
    cases: list[HistoricalCase] = []
    for event in events:
        metadata = event.metadata_json
        cases.append(
            HistoricalCase(
                event_id=str(event.id),
                release_at=_as_utc(event.release_at),
                classification=str(metadata.get("bundle_classification") or "unknown"),
                direction=str(metadata.get("bundle_direction") or "mixed"),
                magnitude_bucket=magnitude_bucket(
                    float(metadata["bundle_score"])
                    if metadata.get("bundle_score") is not None
                    else None
                ),
                core_direction=str(metadata.get("core_direction") or "mixed"),
                regime_tags=tuple(str(value) for value in metadata.get("regime_tags", [])),
                contamination_level=event.contamination_level,
                clean_window=event.clean_window,
                returns=returns.get(event.id, {}),
            )
        )
    return cases


async def _quality_grades_for_event(
    session: AsyncSession,
    event_id: uuid.UUID,
    windows: dict[str, dict[str, ComputedWindow]],
) -> list[str]:
    indicator_quality_ids = (
        await session.scalars(
            select(EventIndicator.actual_quality_id).where(
                EventIndicator.event_id == event_id,
                EventIndicator.actual_quality_id.is_not(None),
            )
        )
    ).all()
    consensus_quality_ids = (
        await session.scalars(
            select(ConsensusSnapshot.quality_id).where(
                ConsensusSnapshot.event_id == event_id,
                ConsensusSnapshot.quality_id.is_not(None),
            )
        )
    ).all()
    ids = [value for value in [*indicator_quality_ids, *consensus_quality_ids] if value]
    grades = (
        list(
            await session.scalars(
                select(DataQualityRecord.quality_grade).where(DataQualityRecord.id.in_(ids))
            )
        )
        if ids
        else []
    )
    grades.extend(
        row.quality_grade
        for instrument_windows in windows.values()
        for key, row in instrument_windows.items()
        if key in {"post_1m", "post_5m", "post_15m"}
    )
    return grades


async def _analyze_event(
    session: AsyncSession,
    event: MacroEvent,
) -> EventAnalysis:
    bundle, _indicators, _latest = await _bundle_for_event(session, event)
    windows, instruments, providers = await _load_window_map(session, event.id)
    earliest_rows = await _earliest_reactions(
        session,
        event,
        instruments,
        providers,
    )
    cases = await _historical_cases(session)
    current_case = next(case for case in cases if case.event_id == str(event.id))
    current_returns = {
        f"{instrument_key}:post_5m": (rows["post_5m"].return_percent if "post_5m" in rows else None)
        for instrument_key, rows in windows.items()
    }
    historical = compare_historical_events(
        current_case,
        cases,
        current_returns=current_returns,
    )
    earliest = [
        EarliestReaction(
            instrument_key=str(row["instrument_key"]),
            detected_at=datetime.fromisoformat(str(row["detected_at"])),
            lag_seconds=_required_int(row["lag_seconds"]),
            move_percent=_required_float(row["move_percent"]),
            direction=str(row["direction"]),
            threshold_percent=_required_float(row["threshold_percent"]),
            pre_event_volatility=_required_float(row["pre_event_volatility"]),
            granularity_seconds=_required_int(row["granularity_seconds"]),
            confirmation_bars=_required_int(row["confirmation_bars"]),
            limitation=str(row["limitation"]),
        )
        for row in earliest_rows
    ]
    grades = await _quality_grades_for_event(session, event.id, windows)
    explanation = build_structured_explanation(
        event_title=event.title,
        bundle=bundle,
        windows=windows,
        earliest=earliest,
        contamination_level=event.contamination_level,
        clean_window=event.clean_window,
        quality_grades=grades,
        is_fixture=event.is_fixture,
        historical=historical,
    )
    analysis = await session.scalar(
        select(EventAnalysis).where(
            EventAnalysis.event_id == event.id,
            EventAnalysis.methodology_version == METHODOLOGY_VERSION,
        )
    )
    values = {
        "composite_classification": bundle.classification,
        "confidence": _required_float(explanation["confidence"]),
        "facts_json": explanation["facts"],
        "explanations_json": explanation["explanations"],
        "historical_json": historical,
        "earliest_reactions_json": earliest_rows,
        "data_gaps_json": explanation["data_gaps"],
        "report_text": str(explanation["report"]),
        "generated_at": datetime.now(UTC),
    }
    if analysis is None:
        analysis = EventAnalysis(
            event_id=event.id,
            methodology_version=METHODOLOGY_VERSION,
            **values,
        )
        session.add(analysis)
    else:
        for key, value in values.items():
            setattr(analysis, key, value)
    await session.flush()
    return analysis


async def ensure_cpi_demo(engine: AsyncEngine) -> str:
    """Idempotently seed one verified historical event plus labelled fixtures."""

    factory = _factory(engine)
    async with factory() as session, session.begin():
        demo = await session.scalar(
            select(MacroEvent).where(MacroEvent.event_key == "us-cpi-2024-02-13")
        )
        if demo is not None:
            analysis = await session.scalar(
                select(EventAnalysis).where(
                    EventAnalysis.event_id == demo.id,
                    EventAnalysis.methodology_version == METHODOLOGY_VERSION,
                )
            )
            if analysis is None:
                await _analyze_event(session, demo)
            return str(demo.id)

        instruments = await _ensure_instruments(session)
        events = [
            await _seed_fixture_event(session, fixture, instruments) for fixture in CPI_FIXTURES
        ]
        for event in events:
            await _analyze_event(session, event)
        demo = next(event for event in events if event.event_key == "us-cpi-2024-02-13")
        return str(demo.id)


async def upsert_cpi_event(engine: AsyncEngine, payload: CpiEventInput) -> str:
    keys = [item.indicator_key for item in payload.indicators]
    if set(keys) != set(INDICATOR_KEYS) or len(keys) != len(set(keys)):
        raise ValueError("CPI bundle must contain each required indicator exactly once")

    factory = _factory(engine)
    async with factory() as session, session.begin():
        event = await session.scalar(
            select(MacroEvent).where(MacroEvent.event_key == payload.event_key)
        )
        if event is None:
            event = MacroEvent(
                event_key=payload.event_key,
                event_type="US_CPI",
                title=payload.title,
                country="USA",
                period_label=payload.period_label,
                release_at=payload.release_at,
                source_timezone=payload.source_timezone,
                status=payload.status,
                source_url=str(payload.source_url),
                data_version=payload.data_version,
                is_fixture=any(
                    item.actual_is_fixture or item.consensus_is_fixture
                    for item in payload.indicators
                ),
                contamination_level=payload.contamination_level,
                clean_window=payload.clean_window,
                overlapping_events=payload.overlapping_events,
                confounding_notes=payload.confounding_notes,
                metadata_json={"regime_tags": []},
            )
            session.add(event)
            await session.flush()
        else:
            event.title = payload.title
            event.period_label = payload.period_label
            event.release_at = payload.release_at
            event.source_timezone = payload.source_timezone
            event.status = payload.status
            event.source_url = str(payload.source_url)
            event.data_version = payload.data_version
            event.contamination_level = payload.contamination_level
            event.clean_window = payload.clean_window
            event.overlapping_events = payload.overlapping_events
            event.confounding_notes = payload.confounding_notes

        existing_indicators = {
            row.indicator_key: row
            for row in (
                await session.scalars(
                    select(EventIndicator).where(EventIndicator.event_id == event.id)
                )
            ).all()
        }
        primary_quality_id: uuid.UUID | None = None
        for item in payload.indicators:
            definition = INDICATOR_DEFINITIONS[item.indicator_key]
            actual_quality = await _persist_quality(
                session,
                DataQuality(
                    source_name=item.actual_source,
                    source_url=item.actual_source_url,
                    source_type="manual_actual" if item.actual_is_manual else "provider_actual",
                    acquired_at=datetime.now(UTC),
                    is_manual=item.actual_is_manual,
                    is_verified=item.actual_verified,
                    is_fixture=item.actual_is_fixture,
                    quality_grade=(
                        QualityGrade.A
                        if item.actual_verified and not item.actual_is_fixture
                        else QualityGrade.C
                    ),
                    verification_notes=item.verification_notes,
                ),
            )
            primary_quality_id = primary_quality_id or actual_quality.id
            indicator = existing_indicators.get(item.indicator_key)
            values = {
                "title": str(definition["title"]),
                "unit": "%",
                "actual_value": item.actual_value,
                "previous_value": item.previous_value,
                "revised_previous_value": item.revised_previous_value,
                "first_release_value": (
                    indicator.first_release_value
                    if indicator is not None and indicator.first_release_value is not None
                    else item.actual_value
                ),
                "data_version": payload.data_version,
                "hotter_when_higher": True,
                "bundle_weight": float(definition["weight"]),
                "surprise_direction": "pending",
                "source_url": str(item.actual_source_url),
                "actual_quality_id": actual_quality.id,
                "metadata_json": {},
            }
            if indicator is None:
                indicator = EventIndicator(
                    event_id=event.id,
                    indicator_key=item.indicator_key,
                    **values,
                )
                session.add(indicator)
            else:
                for key, value in values.items():
                    setattr(indicator, key, value)

            consensus_payload = ConsensusCaptureInput(
                indicator_key=item.indicator_key,
                consensus_value=item.consensus_value,
                consensus_source=item.consensus_source,
                consensus_source_url=item.consensus_source_url,
                consensus_captured_at=item.consensus_captured_at,
                consensus_quality=item.consensus_quality,
                consensus_is_manual=item.consensus_is_manual,
                consensus_is_fixture=item.consensus_is_fixture,
                verification_notes=item.verification_notes,
            )
            await _append_consensus(session, event, consensus_payload)
        event.primary_quality_id = primary_quality_id
        await session.flush()
        await _analyze_event(session, event)
        return str(event.id)


async def _append_consensus(
    session: AsyncSession,
    event: MacroEvent,
    payload: ConsensusCaptureInput,
) -> ConsensusSnapshot:
    captured = _as_utc(payload.consensus_captured_at)
    if captured >= _as_utc(event.release_at):
        raise ValueError("consensus snapshot must be captured before release_at")
    existing = await session.scalar(
        select(ConsensusSnapshot).where(
            ConsensusSnapshot.event_id == event.id,
            ConsensusSnapshot.indicator_key == payload.indicator_key,
            ConsensusSnapshot.consensus_captured_at == captured,
            ConsensusSnapshot.consensus_source == payload.consensus_source,
        )
    )
    if existing is not None:
        if existing.consensus_value != payload.consensus_value:
            raise ValueError("an append-only consensus snapshot cannot be overwritten")
        return existing
    quality = await _persist_quality(
        session,
        DataQuality(
            source_name=payload.consensus_source,
            source_url=payload.consensus_source_url,
            source_type="consensus_snapshot",
            acquired_at=captured,
            is_manual=payload.consensus_is_manual,
            is_verified=payload.consensus_quality in {"verified", "reviewed"},
            is_fixture=payload.consensus_is_fixture,
            quality_grade={
                "verified": QualityGrade.A,
                "reviewed": QualityGrade.B,
                "unverified": QualityGrade.C,
                "fixture": QualityGrade.C,
            }[payload.consensus_quality],
            verification_notes=payload.verification_notes,
        ),
    )
    row = ConsensusSnapshot(
        event_id=event.id,
        indicator_key=payload.indicator_key,
        consensus_value=payload.consensus_value,
        consensus_source=payload.consensus_source,
        consensus_source_url=(
            str(payload.consensus_source_url) if payload.consensus_source_url else None
        ),
        consensus_captured_at=captured,
        consensus_quality=payload.consensus_quality,
        consensus_is_manual=payload.consensus_is_manual,
        verification_notes=payload.verification_notes,
        quality_id=quality.id,
    )
    session.add(row)
    await session.flush()
    return row


async def append_consensus_snapshot(
    engine: AsyncEngine,
    event_id: str,
    payload: ConsensusCaptureInput,
) -> None:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        event = await session.get(MacroEvent, uuid.UUID(event_id))
        if event is None:
            raise LookupError("event not found")
        await _append_consensus(session, event, payload)
        await _analyze_event(session, event)


async def import_market_csv(
    engine: AsyncEngine,
    event_id: str,
    payload: CsvMarketImportInput,
) -> dict[str, object]:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        event = await session.get(MacroEvent, uuid.UUID(event_id))
        if event is None:
            raise LookupError("event not found")
        instrument = await session.scalar(
            select(MarketInstrument).where(MarketInstrument.canonical_key == payload.instrument_key)
        )
        if instrument is None:
            raise LookupError("instrument not found")
        provider = CsvMarketBarProvider(
            payload.csv_text,
            provider_key=payload.provider_key,
            source_name=payload.source_name,
            source_url=str(payload.source_url) if payload.source_url else None,
            acquired_at=payload.acquired_at,
            verified=payload.verified,
            is_fixture=payload.is_fixture,
            verification_notes=payload.verification_notes,
        )
        query = BarQuery(
            instrument=_instrument_ref(instrument),
            start=_as_utc(event.release_at) - timedelta(minutes=60),
            end=_as_utc(event.release_at) + timedelta(days=7),
            interval_seconds=60,
        )
        batch = await provider.fetch_bars(query)
        if not batch.bars:
            raise ValueError("CSV contains no valid bars for the selected instrument")
        quality = await _persist_quality(session, batch.quality)
        existing = {
            _as_utc(row.timestamp): row
            for row in (
                await session.scalars(
                    select(MarketBar).where(
                        MarketBar.instrument_id == instrument.id,
                        MarketBar.provider_key == payload.provider_key,
                        MarketBar.timestamp >= query.start,
                        MarketBar.timestamp <= query.end,
                    )
                )
            ).all()
        }
        inserted = 0
        updated = 0
        for bar in batch.bars:
            row = existing.get(_as_utc(bar.timestamp))
            values = {
                "interval_seconds": bar.interval_seconds,
                "open_value": bar.open_value,
                "high_value": bar.high_value,
                "low_value": bar.low_value,
                "close_value": bar.close_value,
                "volume": bar.volume,
                "source_symbol": bar.source_symbol,
                "contract_code": bar.contract_code,
                "quality_id": quality.id,
                "fetched_at": batch.fetched_at,
                "metadata_json": bar.metadata,
            }
            if row is None:
                session.add(
                    MarketBar(
                        instrument_id=instrument.id,
                        timestamp=bar.timestamp,
                        provider_key=payload.provider_key,
                        **values,
                    )
                )
                inserted += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1
        await session.flush()
        await _upsert_windows(
            session,
            event=event,
            instrument=instrument,
            bars=batch.bars,
            provider_key=batch.provider_key,
            quality_grade=batch.quality.quality_grade.value,
        )
        await _analyze_event(session, event)
        return {
            "event_id": event_id,
            "instrument_key": payload.instrument_key,
            "provider_key": payload.provider_key,
            "inserted": inserted,
            "updated": updated,
            "warnings": batch.warnings,
            "quality_grade": batch.quality.quality_grade.value,
        }


async def analyze_event(engine: AsyncEngine, event_id: str) -> None:
    factory = _factory(engine)
    async with factory() as session, session.begin():
        event = await session.get(MacroEvent, uuid.UUID(event_id))
        if event is None:
            raise LookupError("event not found")
        await _analyze_event(session, event)


def _quality_dict(row: DataQualityRecord | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "source_name": row.source_name,
        "source_url": row.source_url,
        "source_type": row.source_type,
        "acquired_at": _as_utc(row.acquired_at).isoformat(),
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


async def list_cpi_events(engine: AsyncEngine) -> list[dict[str, object]]:
    await ensure_cpi_demo(engine)
    factory = _factory(engine)
    async with factory() as session:
        events = (
            await session.scalars(
                select(MacroEvent)
                .where(MacroEvent.event_type == "US_CPI")
                .order_by(MacroEvent.release_at.desc())
            )
        ).all()
        output: list[dict[str, object]] = []
        for event in events:
            indicators = (
                await session.scalars(
                    select(EventIndicator).where(EventIndicator.event_id == event.id)
                )
            ).all()
            latest = await _latest_consensus(session, event.id)
            analysis = await session.scalar(
                select(EventAnalysis).where(
                    EventAnalysis.event_id == event.id,
                    EventAnalysis.methodology_version == METHODOLOGY_VERSION,
                )
            )
            output.append(
                {
                    "id": str(event.id),
                    "event_key": event.event_key,
                    "event_type": event.event_type,
                    "title": event.title,
                    "period_label": event.period_label,
                    "release_at": _as_utc(event.release_at).isoformat(),
                    "status": event.status,
                    "classification": event.metadata_json.get("bundle_classification"),
                    "surprise_score": event.metadata_json.get("bundle_score"),
                    "impact": "high",
                    "analysis_status": "complete" if analysis else "pending",
                    "confidence": analysis.confidence if analysis else 0.0,
                    "is_fixture": event.is_fixture,
                    "clean_window": event.clean_window,
                    "contamination_level": event.contamination_level,
                    "indicators": [
                        {
                            "key": row.indicator_key,
                            "actual": _float(row.actual_value),
                            "consensus": (
                                _float(latest[row.indicator_key].consensus_value)
                                if row.indicator_key in latest
                                else None
                            ),
                            "previous": _float(row.previous_value),
                            "revised_previous": _float(row.revised_previous_value),
                            "surprise": _float(row.raw_surprise),
                            "direction": row.surprise_direction,
                        }
                        for row in sorted(
                            indicators,
                            key=lambda value: INDICATOR_KEYS.index(value.indicator_key),
                        )
                    ],
                }
            )
        return output


async def _event_quality_records(
    session: AsyncSession,
    event: MacroEvent,
) -> list[DataQualityRecord]:
    quality_ids: set[uuid.UUID] = set()
    if event.primary_quality_id:
        quality_ids.add(event.primary_quality_id)
    indicator_ids = (
        await session.scalars(
            select(EventIndicator.actual_quality_id).where(
                EventIndicator.event_id == event.id,
                EventIndicator.actual_quality_id.is_not(None),
            )
        )
    ).all()
    consensus_ids = (
        await session.scalars(
            select(ConsensusSnapshot.quality_id).where(
                ConsensusSnapshot.event_id == event.id,
                ConsensusSnapshot.quality_id.is_not(None),
            )
        )
    ).all()
    instrument_ids = (
        await session.scalars(
            select(EventWindowMetric.instrument_id).where(EventWindowMetric.event_id == event.id)
        )
    ).all()
    bar_ids: list[uuid.UUID | None] = []
    if instrument_ids:
        bar_ids = list(
            await session.scalars(
                select(MarketBar.quality_id)
                .where(
                    MarketBar.instrument_id.in_(instrument_ids),
                    MarketBar.timestamp >= event.release_at - timedelta(minutes=60),
                    MarketBar.timestamp <= event.release_at + timedelta(hours=4),
                    MarketBar.quality_id.is_not(None),
                )
                .distinct()
            )
        )
    quality_ids.update(
        value for value in [*indicator_ids, *consensus_ids, *bar_ids] if value is not None
    )
    if not quality_ids:
        return []
    return list(
        await session.scalars(
            select(DataQualityRecord)
            .where(DataQualityRecord.id.in_(quality_ids))
            .order_by(DataQualityRecord.source_name)
        )
    )


async def get_cpi_event_detail(
    engine: AsyncEngine,
    event_id: str,
) -> dict[str, object] | None:
    await ensure_cpi_demo(engine)
    factory = _factory(engine)
    async with factory() as session:
        try:
            event_uuid = uuid.UUID(event_id)
        except ValueError:
            return None
        event = await session.get(MacroEvent, event_uuid)
        if event is None or event.event_type != "US_CPI":
            return None
        indicators = (
            await session.scalars(select(EventIndicator).where(EventIndicator.event_id == event.id))
        ).all()
        latest = await _latest_consensus(session, event.id)
        consensus_history = (
            await session.scalars(
                select(ConsensusSnapshot)
                .where(ConsensusSnapshot.event_id == event.id)
                .order_by(ConsensusSnapshot.consensus_captured_at)
            )
        ).all()
        windows, instruments, providers = await _load_window_map(session, event.id)
        analysis = await session.scalar(
            select(EventAnalysis).where(
                EventAnalysis.event_id == event.id,
                EventAnalysis.methodology_version == METHODOLOGY_VERSION,
            )
        )
        quality_rows = await _event_quality_records(session, event)
        quality_by_id = {row.id: row for row in quality_rows}

        timeline: dict[str, list[dict[str, object]]] = {}
        for key, instrument in instruments.items():
            provider_key = providers.get(key)
            conditions = [
                MarketBar.instrument_id == instrument.id,
                MarketBar.timestamp >= event.release_at - timedelta(minutes=60),
                MarketBar.timestamp <= event.release_at + timedelta(minutes=60),
                MarketBar.interval_seconds == 60,
            ]
            if provider_key:
                conditions.append(MarketBar.provider_key == provider_key)
            bars = (
                await session.scalars(
                    select(MarketBar).where(*conditions).order_by(MarketBar.timestamp)
                )
            ).all()
            pre = [bar for bar in bars if bar.timestamp < event.release_at]
            baseline = pre[-1].close_value if pre else None
            normalized_baseline = baseline if baseline is not None and baseline != 0 else None
            timeline[key] = [
                {
                    "timestamp": _as_utc(bar.timestamp).isoformat(),
                    "value": _float(bar.close_value),
                    "normalized_percent": (
                        float(
                            (bar.close_value - normalized_baseline)
                            / normalized_baseline
                            * Decimal(100)
                        )
                        if normalized_baseline is not None
                        else None
                    ),
                    "volume": _float(bar.volume),
                }
                for bar in bars
            ]

        return {
            "id": str(event.id),
            "event_key": event.event_key,
            "event_type": event.event_type,
            "title": event.title,
            "country": event.country,
            "period_label": event.period_label,
            "release_at": _as_utc(event.release_at).isoformat(),
            "source_timezone": event.source_timezone,
            "status": event.status,
            "source_url": event.source_url,
            "data_version": event.data_version,
            "data_mode": "mixed_real_and_fixture" if event.is_fixture else "observed",
            "bundle": {
                "classification": event.metadata_json.get("bundle_classification"),
                "score": event.metadata_json.get("bundle_score"),
                "direction": event.metadata_json.get("bundle_direction"),
                "core_direction": event.metadata_json.get("core_direction"),
                "methodology_version": METHODOLOGY_VERSION,
            },
            "indicators": [
                {
                    "key": row.indicator_key,
                    "title": row.title,
                    "unit": row.unit,
                    "actual": _float(row.actual_value),
                    "consensus": (
                        _float(latest[row.indicator_key].consensus_value)
                        if row.indicator_key in latest
                        else None
                    ),
                    "previous": _float(row.previous_value),
                    "revised_previous": _float(row.revised_previous_value),
                    "first_release": _float(row.first_release_value),
                    "raw_surprise": _float(row.raw_surprise),
                    "relative_surprise": row.relative_surprise,
                    "standardized_surprise": row.standardized_surprise,
                    "surprise_direction": row.surprise_direction,
                    "actual_quality": _quality_dict(
                        _quality_lookup(quality_by_id, row.actual_quality_id)
                    ),
                    "latest_consensus_quality": _quality_dict(
                        _quality_lookup(
                            quality_by_id,
                            latest[row.indicator_key].quality_id,
                        )
                        if row.indicator_key in latest
                        else None
                    ),
                }
                for row in sorted(
                    indicators,
                    key=lambda value: INDICATOR_KEYS.index(value.indicator_key),
                )
            ],
            "consensus_history": [
                {
                    "indicator_key": row.indicator_key,
                    "value": _float(row.consensus_value),
                    "source": row.consensus_source,
                    "source_url": row.consensus_source_url,
                    "captured_at": _as_utc(row.consensus_captured_at).isoformat(),
                    "quality": row.consensus_quality,
                    "is_manual": row.consensus_is_manual,
                    "verification_notes": row.verification_notes,
                }
                for row in consensus_history
            ],
            "contamination": {
                "level": event.contamination_level,
                "clean_window": event.clean_window,
                "overlapping_events": event.overlapping_events,
                "confounding_notes": event.confounding_notes,
                "causal_language": (
                    "bounded" if event.clean_window else "weak_only_due_to_contamination"
                ),
            },
            "assets": [
                {
                    "key": key,
                    "title": instrument.title,
                    "symbol": instrument.symbol,
                    "contract_code": instrument.contract_code,
                    "exchange": instrument.exchange,
                    "quote_unit": instrument.quote_unit,
                    "measurement_type": instrument.measurement_type,
                    "is_proxy": instrument.is_proxy,
                    "proxy_for": instrument.proxy_for,
                    "provider_key": providers.get(key),
                    "windows": [
                        {
                            "key": item.key,
                            "label": item.label,
                            "start_at": item.start_at.isoformat(),
                            "end_at": item.end_at.isoformat(),
                            "start_value": _float(item.start_value),
                            "end_value": _float(item.end_value),
                            "change_absolute": _float(item.change_absolute),
                            "return_percent": item.return_percent,
                            "max_up_percent": item.max_up_percent,
                            "max_down_percent": item.max_down_percent,
                            "realized_volatility": item.realized_volatility,
                            "volume_change_percent": item.volume_change_percent,
                            "coverage_ratio": item.coverage_ratio,
                            "direction": item.direction,
                            "spike_fade": item.spike_fade,
                            "dip_recovery": item.dip_recovery,
                            "direction_reversal": item.direction_reversal,
                            "granularity_seconds": item.granularity_seconds,
                            "quality_grade": item.quality_grade,
                            "missing_reason": item.missing_reason,
                        }
                        for item in windows.get(key, {}).values()
                    ],
                }
                for key, instrument in instruments.items()
            ],
            "timeline": timeline,
            "facts": analysis.facts_json if analysis else [],
            "earliest_reactions": (analysis.earliest_reactions_json if analysis else []),
            "explanations": analysis.explanations_json if analysis else [],
            "historical": analysis.historical_json if analysis else {},
            "confidence": analysis.confidence if analysis else 0.0,
            "data_gaps": analysis.data_gaps_json if analysis else [],
            "report": analysis.report_text if analysis else "",
            "generated_at": (_as_utc(analysis.generated_at).isoformat() if analysis else None),
            "data_quality": [
                value for row in quality_rows if (value := _quality_dict(row)) is not None
            ],
            "integrations": {
                "macrosynergy": MacrosynergyAdapter().status(),
                "market_provider_boundary": "worldstate-market-bars-v1",
                "consensus_provider_boundary": "append-only-snapshot-v1",
            },
        }


async def cpi_event_lab_summary(engine: AsyncEngine) -> dict[str, object]:
    demo_id = await ensure_cpi_demo(engine)
    factory = _factory(engine)
    async with factory() as session:
        events = await session.scalar(
            select(func.count()).select_from(MacroEvent).where(MacroEvent.event_type == "US_CPI")
        )
        bars = await session.scalar(select(func.count()).select_from(MarketBar))
        windows = await session.scalar(select(func.count()).select_from(EventWindowMetric))
        analyses = await session.scalar(select(func.count()).select_from(EventAnalysis))
    return {
        "state": "ready",
        "methodology_version": METHODOLOGY_VERSION,
        "demo_event_id": demo_id,
        "events": events or 0,
        "market_bars": bars or 0,
        "window_metrics": windows or 0,
        "analyses": analyses or 0,
        "required_indicators": list(INDICATOR_KEYS),
        "supported_instruments": [str(definition["canonical_key"]) for definition in INSTRUMENTS],
        "warnings": [
            "Bundled market bars are deterministic fixtures, not exchange-recorded prices.",
            "ZT and ZN are explicitly labelled yield proxies.",
            "Historical probability output requires at least five fixed-filter samples.",
        ],
    }
