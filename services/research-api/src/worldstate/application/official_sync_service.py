"""Observed official-data ingestion for BLS, Federal Reserve, and FRED/ALFRED."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import (
    complete_provider_run,
    fail_provider_run,
    record_provider_run,
    upsert_entitlement,
)
from worldstate.application.data_manifest_service import record_calendar_snapshot
from worldstate.application.provider_runtime import (
    build_provider_clients,
    persist_provider_artifact,
    persist_quality_record,
)
from worldstate.application.scheduler_service import (
    ensure_default_schedule,
    schedule_release_tasks,
)
from worldstate.config import Settings, repository_root
from worldstate.db.models import (
    EconomicEntity,
    Indicator,
    MacroRelease,
    MarketBar,
    MarketInstrument,
    Observation,
    Provider,
    ReleaseStage,
    ReleaseValue,
    Series,
)
from worldstate.db.models import (
    SourceArtifact as StoredSourceArtifact,
)
from worldstate.provider_kit import (
    FomcDocument,
    FomcMaterialType,
    ProviderError,
    ProviderErrorCode,
)
from worldstate.provider_kit.catalog import load_catalog

_BLS_INDICATOR_MAP = {
    "US_CPI.HEADLINE.MOM": "headline_mom",
    "US_CPI.HEADLINE.YOY": "headline_yoy",
    "US_CPI.CORE.MOM": "core_mom",
    "US_CPI.CORE.YOY": "core_yoy",
    "US_NFP.NONFARM_PAYROLLS": "nonfarm_payrolls",
    "US_NFP.UNEMPLOYMENT_RATE": "unemployment_rate",
    "US_NFP.AVERAGE_HOURLY_EARNINGS.MOM": "average_hourly_earnings_mom",
    "US_NFP.AVERAGE_HOURLY_EARNINGS.YOY": "average_hourly_earnings_yoy",
    "US_NFP.LABOR_FORCE_PARTICIPATION": "labor_force_participation",
}

_FRED_FOUNDATION_SERIES = {
    "DGS2",
    "DGS10",
    "DFII10",
    "DTWEXBGS",
    "VIXCLS",
}

_FRED_MARKET_CONTEXT = {
    "SP500": "sp500_cash",
    "NASDAQ100": "nasdaq100_cash",
    "VIXCLS": "vix_cash",
    "DCOILWTICO": "wti_spot",
    "DCOILBRENTEU": "brent_spot",
    "DTWEXBGS": "dollar_broad_context",
    "DGS2": "ust2y_yield_context",
    "DGS3MO": "ust3m_yield_context",
    "DGS5": "ust5y_yield_context",
    "DGS10": "ust10y_yield_context",
    "DGS30": "ust30y_yield_context",
    "DFII10": "ust10y_real_yield_context",
    "DEXUSEU": "eurusd_context",
    "DEXJPUS": "usdjpy_context",
    "DEXCHUS": "usdcny_context",
    "BAMLH0A0HYM2": "hy_spread_context",
}

_DERIVED_MARKET_CONTEXT = {
    "curve_2s10s_derived": (
        "ust10y_yield_context",
        "ust2y_yield_context",
        "US10Y - US2Y",
    ),
    "curve_3m10y_derived": (
        "ust10y_yield_context",
        "ust3m_yield_context",
        "US10Y - US3M",
    ),
}
_DERIVED_MARKET_VERSION = "market-derived-v1"

_FOMC_VALUE_PARSER_VERSION = "fomc-target-range-v2"
_INVALIDATED_RELEASE_STATUS = "invalidated"

BlsFamily = Literal["US_CPI", "US_NFP"]
_BLS_FAMILIES: tuple[BlsFamily, ...] = ("US_CPI", "US_NFP")
_SUPPORTED_EVENT_TYPES = frozenset({*_BLS_FAMILIES, "FOMC"})


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _previous_month(value: date) -> date:
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


async def _upsert_fred_context_bar(
    session: AsyncSession,
    *,
    instrument: MarketInstrument,
    existing: dict[datetime, MarketBar],
    observation: Any,
    quality_id: uuid.UUID,
    provider_key: str,
    source_mode: str,
    retrieved_at: datetime,
    native_id: str,
) -> None:
    if observation.value is None:
        return
    timestamp = datetime.combine(
        observation.period_start,
        datetime.min.time(),
        tzinfo=UTC,
    )
    bar = existing.get(timestamp)
    values = {
        "interval_seconds": 86400,
        "open_value": observation.value,
        "high_value": observation.value,
        "low_value": observation.value,
        "close_value": observation.value,
        "volume": None,
        "source_symbol": native_id,
        "contract_code": "",
        "quality_id": quality_id,
        "fetched_at": retrieved_at,
        "metadata_json": {
            "context_only": True,
            "not_event_window": True,
            "source_series": native_id,
            "source_mode": source_mode,
            "point_in_time": source_mode != "current_public_csv",
        },
    }
    if bar is None:
        session.add(
            MarketBar(
                instrument_id=instrument.id,
                futures_contract_id=None,
                timestamp=timestamp,
                provider_key=provider_key,
                data_mode="observed",
                is_regular_session=True,
                **values,
            )
        )
    else:
        for key, value in values.items():
            setattr(bar, key, value)


async def _sync_derived_market_context(
    engine: AsyncEngine, *, calculated_at: datetime
) -> int:
    """Persist auditable curve spreads from locally observed input bars."""

    written = 0
    factory = _factory(engine)
    async with factory() as session, session.begin():
        keys = {
            key
            for output_key, (left_key, right_key, _) in _DERIVED_MARKET_CONTEXT.items()
            for key in (output_key, left_key, right_key)
        }
        instruments = {
            row.canonical_key: row
            for row in (
                await session.scalars(
                    select(MarketInstrument).where(MarketInstrument.canonical_key.in_(keys))
                )
            ).all()
        }
        for output_key, (left_key, right_key, formula) in _DERIVED_MARKET_CONTEXT.items():
            output = instruments.get(output_key)
            left = instruments.get(left_key)
            right = instruments.get(right_key)
            if output is None or left is None or right is None:
                continue
            left_bars = {
                _aware(row.timestamp): row
                for row in (
                    await session.scalars(
                        select(MarketBar).where(
                            MarketBar.instrument_id == left.id,
                            MarketBar.provider_key == "fred_alfred",
                            MarketBar.interval_seconds == 86400,
                            MarketBar.data_mode == "observed",
                        )
                    )
                ).all()
            }
            right_bars = {
                _aware(row.timestamp): row
                for row in (
                    await session.scalars(
                        select(MarketBar).where(
                            MarketBar.instrument_id == right.id,
                            MarketBar.provider_key == "fred_alfred",
                            MarketBar.interval_seconds == 86400,
                            MarketBar.data_mode == "observed",
                        )
                    )
                ).all()
            }
            existing = {
                _aware(row.timestamp): row
                for row in (
                    await session.scalars(
                        select(MarketBar).where(
                            MarketBar.instrument_id == output.id,
                            MarketBar.provider_key == "worldstate_derived",
                            MarketBar.interval_seconds == 86400,
                            MarketBar.data_mode == "observed",
                        )
                    )
                ).all()
            }
            for timestamp in sorted(left_bars.keys() & right_bars.keys()):
                left_bar = left_bars[timestamp]
                right_bar = right_bars[timestamp]
                value = left_bar.close_value - right_bar.close_value
                metadata = {
                    "context_only": True,
                    "not_event_window": True,
                    "derived": True,
                    "input_datasets": [left_key, right_key],
                    "input_bar_ids": [left_bar.id, right_bar.id],
                    "formula": formula,
                    "calculation_version": _DERIVED_MARKET_VERSION,
                    "calculated_at": calculated_at.isoformat(),
                    "point_in_time": bool(left_bar.metadata_json.get("point_in_time"))
                    and bool(right_bar.metadata_json.get("point_in_time")),
                }
                values = {
                    "open_value": value,
                    "high_value": value,
                    "low_value": value,
                    "close_value": value,
                    "volume": None,
                    "source_symbol": f"{left.symbol}-{right.symbol}",
                    "contract_code": "",
                    "is_regular_session": True,
                    "quality_id": left_bar.quality_id
                    if left_bar.quality_id == right_bar.quality_id
                    else None,
                    "fetched_at": calculated_at,
                    "metadata_json": metadata,
                }
                row = existing.get(timestamp)
                if row is None:
                    session.add(
                        MarketBar(
                            instrument_id=output.id,
                            futures_contract_id=None,
                            timestamp=timestamp,
                            interval_seconds=86400,
                            provider_key="worldstate_derived",
                            data_mode="observed",
                            **values,
                        )
                    )
                    written += 1
                else:
                    for field, field_value in values.items():
                        setattr(row, field, field_value)
    return written


async def _upsert_release_stage(
    session: AsyncSession,
    *,
    release: MacroRelease,
    stage_key: str,
    title: str,
    sequence: int,
    published_at: datetime,
    source_artifact_id: uuid.UUID,
    released: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReleaseStage:
    is_released = published_at <= datetime.now(UTC) if released is None else released
    stage = await session.scalar(
        select(ReleaseStage).where(
            ReleaseStage.macro_release_id == release.id,
            ReleaseStage.stage_key == stage_key,
        )
    )
    if stage is None:
        stage = ReleaseStage(
            id=uuid.uuid4(),
            macro_release_id=release.id,
            stage_key=stage_key,
            title=title,
            sequence=sequence,
            scheduled_at=published_at,
            released_at=published_at if is_released else None,
            status="released" if is_released else "scheduled",
            source_artifact_id=source_artifact_id,
            metadata_json=metadata or {},
        )
        session.add(stage)
    else:
        stage.title = title
        stage.sequence = sequence
        stage.scheduled_at = published_at
        # Provider retries are allowed to fail after an earlier successful
        # ingestion.  Calendar-only evidence must never downgrade a released
        # stage or replace its document provenance with a calendar artifact.
        if is_released or stage.released_at is None:
            stage.released_at = published_at if is_released else None
            stage.status = "released" if stage.released_at else "scheduled"
            stage.source_artifact_id = source_artifact_id
            stage.metadata_json = metadata or stage.metadata_json
    await session.flush()
    return stage


async def _append_fomc_target_value(
    session: AsyncSession,
    *,
    release: MacroRelease,
    stage: ReleaseStage,
    indicator: Indicator,
    value: Decimal,
    raw_value: str,
    data_version: str,
    published_at: datetime,
    statement: FomcDocument,
    statement_artifact_id: uuid.UUID,
    quality_id: uuid.UUID,
) -> bool:
    """Append one canonical statement fact and supersede provider retry noise.

    Raw Fed HTML includes dynamic site bytes, so repeated downloads can have
    different artifact hashes even when the policy statement is unchanged.
    We retain every raw artifact, but only one non-superseded value per
    statement URL, semantic version, indicator and value kind is analysis
    eligible.  Existing rows remain available for frozen AnalysisRun replay.
    """

    candidates = (
        await session.execute(
            select(ReleaseValue, StoredSourceArtifact.source_url)
            .outerjoin(
                StoredSourceArtifact,
                StoredSourceArtifact.id == ReleaseValue.source_artifact_id,
            )
            .where(
                ReleaseValue.macro_release_id == release.id,
                ReleaseValue.indicator_id == indicator.id,
                ReleaseValue.value_kind == "actual",
                ReleaseValue.data_mode == "observed",
            )
            .order_by(ReleaseValue.captured_at, ReleaseValue.id)
        )
    ).all()
    provider_owned: list[ReleaseValue] = []
    canonical: ReleaseValue | None = None
    for row, artifact_url in candidates:
        row_url = row.metadata_json.get("official_statement_url")
        if artifact_url != statement.source_url and row_url != statement.source_url:
            continue
        provider_owned.append(row)
        if (
            not row.metadata_json.get("superseded")
            and row.data_version == data_version
            and row.value == value
            and row.raw_value == raw_value
            and canonical is None
        ):
            canonical = row

    if canonical is not None:
        duplicate_rows = [
            row
            for row in provider_owned
            if row.id != canonical.id and not row.metadata_json.get("superseded")
        ]
        for row in duplicate_rows:
            row.metadata_json = {
                **row.metadata_json,
                "superseded": True,
                "superseded_reason": "duplicate_official_statement_fact",
                "superseded_by_release_value_id": str(canonical.id),
                "superseded_at": datetime.now(UTC).isoformat(),
            }
        return False

    new_id = uuid.uuid4()
    superseded_ids: list[str] = []
    for row in provider_owned:
        if row.metadata_json.get("superseded"):
            continue
        superseded_ids.append(str(row.id))
        row.metadata_json = {
            **row.metadata_json,
            "superseded": True,
            "superseded_reason": "reparsed_official_statement_fact",
            "superseded_by_release_value_id": str(new_id),
            "superseded_at": datetime.now(UTC).isoformat(),
        }
    session.add(
        ReleaseValue(
            id=new_id,
            macro_release_id=release.id,
            release_stage_id=stage.id,
            indicator_id=indicator.id,
            value_kind="actual",
            value=value,
            raw_value=raw_value,
            data_version=data_version,
            valid_from=published_at,
            captured_at=statement.artifact.retrieved_at,
            is_initial=True,
            data_mode="observed",
            source_artifact_id=statement_artifact_id,
            quality_id=quality_id,
            metadata_json={
                "official_statement_parse": True,
                "official_statement_url": statement.source_url,
                "semantic_hash": statement.metadata.get("semantic_hash"),
                "parser_version": _FOMC_VALUE_PARSER_VERSION,
                "supersedes_release_value_ids": superseded_ids,
            },
        )
    )
    return True


async def _invalidate_stale_fomc_releases(
    engine: AsyncEngine,
    *,
    start_date: date,
    end_date: date,
    authoritative_meeting_dates: set[date],
    calendar_coverage: dict[int, tuple[date, date, uuid.UUID]],
    provider_run_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Soft-invalidate only provider-owned rows disproved by the Fed calendar."""

    factory = _factory(engine)
    invalidated: list[uuid.UUID] = []
    async with factory() as session, session.begin():
        candidates = (
            await session.execute(
                select(MacroRelease, StoredSourceArtifact.provider_key)
                .outerjoin(
                    StoredSourceArtifact,
                    StoredSourceArtifact.id == MacroRelease.source_artifact_id,
                )
                .where(
                    MacroRelease.release_type == "FOMC",
                    MacroRelease.data_mode == "observed",
                )
            )
        ).all()
        for release, provider_key in candidates:
            if provider_key != "federal_reserve_fomc":
                continue
            raw_meeting_date = release.metadata_json.get("meeting_end_date")
            if not isinstance(raw_meeting_date, str):
                raw_meeting_date = release.period_label
            try:
                meeting_date = date.fromisoformat(raw_meeting_date)
            except ValueError:
                continue
            if not start_date <= meeting_date <= end_date:
                continue
            coverage = calendar_coverage.get(meeting_date.year)
            if coverage is None or not coverage[0] <= meeting_date <= coverage[1]:
                continue
            if meeting_date in authoritative_meeting_dates:
                continue
            if release.status == _INVALIDATED_RELEASE_STATUS:
                continue
            previous_status = release.status
            release.status = _INVALIDATED_RELEASE_STATUS
            release.metadata_json = {
                **release.metadata_json,
                "provider_reconciliation": {
                    "state": "invalidated",
                    "reason": "not_present_in_authoritative_fomc_calendar",
                    "provider_key": "federal_reserve_fomc",
                    "provider_run_id": str(provider_run_id),
                    "calendar_artifact_id": str(coverage[2]),
                    "invalidated_at": datetime.now(UTC).isoformat(),
                    "previous_status": previous_status,
                    "requested_start_date": start_date.isoformat(),
                    "requested_end_date": end_date.isoformat(),
                },
            }
            note = "invalidated: not present in authoritative Federal Reserve FOMC calendar"
            if note not in release.confounding_notes:
                release.confounding_notes = [*release.confounding_notes, note]
            invalidated.append(release.id)
    return invalidated


async def sync_bls_calendar(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    families: tuple[BlsFamily, ...] = _BLS_FAMILIES,
) -> dict[str, object]:
    families = tuple(dict.fromkeys(families))
    if not families:
        raise ValueError("at least one BLS release family is required")
    clients = build_provider_clients(settings)
    family_scope = ",".join(families)
    run = await record_provider_run(
        engine,
        provider_key=clients.bls.key,
        operation="sync_release_calendar",
        idempotency_key=(f"bls-calendar:{family_scope}:{start_date}:{end_date}:{date.today()}"),
        input_data={
            "start_date": start_date,
            "end_date": end_date,
            "families": list(families),
        },
        terms_url=clients.bls.terms.terms_url,
    )
    warnings: list[str] = []
    read = written = requests = 0
    successful_requests = blocked_requests = 0
    primary_artifact_id: uuid.UUID | None = None
    scheduled_release_ids: list[uuid.UUID] = []
    try:
        await ensure_default_schedule(engine)
        for family in families:
            for year in range(start_date.year, end_date.year + 1):
                requests += 1
                try:
                    batch = await clients.bls.fetch_schedule(family, year=year)
                except ProviderError as exc:
                    blocked_requests += 1
                    warnings.append(f"{family} {year}: {exc.code}")
                    continue
                successful_requests += 1
                read += len(batch.entries)
                artifact = await persist_provider_artifact(
                    engine,
                    batch.artifacts[0],
                    provider_run_id=run.id,
                    title=f"BLS {family} release calendar {year}",
                )
                primary_artifact_id = primary_artifact_id or artifact.id
                await record_calendar_snapshot(
                    engine,
                    provider_key=clients.bls.key,
                    calendar_kind=family,
                    period_start=date(year, 1, 1),
                    period_end=date(year, 12, 31),
                    captured_at=batch.retrieved_at,
                    payload=[entry.model_dump(mode="json") for entry in batch.entries],
                    provider_run_id=run.id,
                    source_artifact_id=artifact.id,
                    metadata={"source_timezone": "America/New_York"},
                )
                quality = await persist_quality_record(
                    engine,
                    batch.quality,
                    subject_type="release_calendar",
                    subject_id=f"{family}:{year}",
                    identity=f"quality:{family}:{year}:{artifact.content_hash}",
                )
                for entry in batch.entries:
                    released_at = _aware(entry.scheduled_local)
                    if not start_date <= released_at.date() <= end_date:
                        continue
                    period = _previous_month(released_at.date())
                    release_key = f"{family.lower()}-{period.isoformat()}-observed"
                    factory = _factory(engine)
                    async with factory() as session, session.begin():
                        release = await session.scalar(
                            select(MacroRelease).where(
                                MacroRelease.release_key == release_key,
                                MacroRelease.data_mode == "observed",
                            )
                        )
                        if release is None:
                            release = MacroRelease(
                                id=uuid.uuid4(),
                                release_key=release_key,
                                release_type=family,
                                title=entry.title,
                                country="USA",
                                period_label=period.strftime("%Y-%m"),
                                scheduled_at=released_at,
                                released_at=(
                                    released_at if released_at <= datetime.now(UTC) else None
                                ),
                                source_timezone=entry.source_timezone,
                                status=(
                                    "released" if released_at <= datetime.now(UTC) else "scheduled"
                                ),
                                data_version=f"bls-calendar-{artifact.content_hash[:16]}",
                                data_mode="observed",
                                source_artifact_id=artifact.id,
                                primary_quality_id=quality.id,
                                contamination_level="unknown",
                                clean_window=False,
                                overlapping_events=[],
                                confounding_notes=[
                                    "overlap and news contamination have not been reconciled"
                                ],
                                metadata_json={
                                    "period_derivation": "calendar month before release month",
                                    "official_schedule": True,
                                },
                            )
                            session.add(release)
                            written += 1
                        else:
                            release.scheduled_at = released_at
                            release.released_at = (
                                released_at if released_at <= datetime.now(UTC) else None
                            )
                            release.status = "released" if release.released_at else "scheduled"
                            release.data_version = f"bls-calendar-{artifact.content_hash[:16]}"
                            release.source_artifact_id = artifact.id
                            release.primary_quality_id = quality.id
                        await session.flush()
                        await _upsert_release_stage(
                            session,
                            release=release,
                            stage_key="release",
                            title="Official release",
                            sequence=1,
                            published_at=released_at,
                            source_artifact_id=artifact.id,
                            metadata={"timestamp_source": "BLS official release calendar"},
                        )
                        scheduled_release_ids.append(release.id)
        for release_id in dict.fromkeys(scheduled_release_ids):
            factory = _factory(engine)
            async with factory() as session:
                release = await session.get(MacroRelease, release_id)
                if release is not None:
                    await schedule_release_tasks(
                        engine,
                        macro_release_id=release.id,
                        release_at=release.scheduled_at,
                    )
        operation_status: Literal["completed", "partial", "blocked"] = (
            "blocked"
            if successful_requests == 0
            else "partial"
            if blocked_requests
            else "completed"
        )
        await complete_provider_run(
            engine,
            run.id,
            records_read=read,
            records_written=written,
            request_count=requests,
            source_artifact_id=primary_artifact_id,
            quality_grade="A" if read else "D",
            warnings=warnings,
            output_data={
                "release_ids": [str(item) for item in dict.fromkeys(scheduled_release_ids)]
            },
            status=operation_status,
            error_message=(
                "BLS official release calendar was unavailable for every requested scope."
                if operation_status == "blocked"
                else None
            ),
        )
        return {
            "status": operation_status,
            "provider": clients.bls.key,
            "records_read": read,
            "records_written": written,
            "warnings": warnings,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


async def _prior_bls_snapshot(engine: AsyncEngine) -> dict[str, Decimal]:
    factory = _factory(engine)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ReleaseValue).where(
                    ReleaseValue.data_mode == "observed",
                    ReleaseValue.value_kind == "actual",
                )
            )
        ).all()
    snapshot: dict[str, Decimal] = {}
    for row in rows:
        key = row.metadata_json.get("bls_snapshot_key")
        if isinstance(key, str) and row.value is not None:
            snapshot[key] = row.value
    return snapshot


async def sync_bls_actuals(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    families: tuple[BlsFamily, ...] = _BLS_FAMILIES,
) -> dict[str, object]:
    families = tuple(dict.fromkeys(families))
    if not families:
        raise ValueError("at least one BLS release family is required")
    clients = build_provider_clients(settings)
    family_scope = ",".join(families)
    run = await record_provider_run(
        engine,
        provider_key=clients.bls.key,
        operation="sync_actuals_revisions",
        idempotency_key=(f"bls-actuals:{family_scope}:{start_date}:{end_date}:{date.today()}"),
        input_data={
            "start_date": start_date,
            "end_date": end_date,
            "families": list(families),
            "date_semantics": "official_release_date",
        },
        terms_url=clients.bls.terms.terms_url,
    )
    prior_snapshot = await _prior_bls_snapshot(engine)
    read = written = requests = 0
    warnings: list[str] = []
    primary_artifact_id: uuid.UUID | None = None
    try:
        # The public command range is a release-event range, not a reference-month
        # range.  Resolve the official calendar records first so a request for the
        # March release imports February data (and never the March reference month
        # that was not known at T0).
        factory = _factory(engine)
        async with factory() as session:
            releases = (
                await session.scalars(
                    select(MacroRelease).where(
                        MacroRelease.release_type.in_(families),
                        MacroRelease.data_mode == "observed",
                    )
                )
            ).all()
        releases = [
            release
            for release in releases
            if start_date <= _aware(release.scheduled_at).date() <= end_date
        ]
        target_release_ids: dict[tuple[str, str], uuid.UUID] = {}
        target_periods: dict[str, list[date]] = {family: [] for family in families}
        for release in releases:
            try:
                reference_period = date.fromisoformat(f"{release.period_label}-01")
            except ValueError:
                warnings.append(
                    f"{release.release_type} release {release.id} has an unsupported "
                    f"period label: {release.period_label}"
                )
                continue
            target_key = (release.release_type, release.period_label)
            existing_id = target_release_ids.get(target_key)
            if existing_id is not None:
                warnings.append(
                    f"duplicate observed release for {release.release_type} "
                    f"{release.period_label}; using the first calendar record"
                )
                continue
            target_release_ids[target_key] = release.id
            target_periods[release.release_type].append(reference_period)

        if not target_release_ids:
            warning = (
                "No observed BLS calendar release falls inside the requested release-date "
                "range; actual values were not fetched because they could not be attached "
                "to a verified T0."
            )
            warnings.append(warning)
            await complete_provider_run(
                engine,
                run.id,
                records_read=0,
                records_written=0,
                request_count=0,
                quality_grade="D",
                warnings=warnings,
                output_data={
                    "release_ids": [],
                    "date_semantics": "official_release_date",
                    "historical_vintage_reconstruction": False,
                },
                status="blocked",
                error_message=warning,
            )
            return {
                "status": "blocked",
                "provider": clients.bls.key,
                "records_read": 0,
                "records_written": 0,
                "warnings": warnings,
            }

        matched = 0
        for family in families:
            periods = target_periods[family]
            if not periods:
                continue
            first_period = min(periods)
            # Public/unregistered BLS responses may disable server-side
            # calculations.  One prior year supplies the exact lag needed for
            # CPI/AHE YoY, while also supplying December for January payroll and
            # MoM derivations from official levels.
            fetch_start_year = first_period.year - 1
            batch = await clients.bls.fetch_bundle(
                family,
                start_year=fetch_start_year,
                end_year=max(periods).year,
                prior_snapshot=prior_snapshot,
            )
            requests += len(batch.artifacts)
            read += len(batch.observations)
            warnings.extend(batch.warnings)
            artifacts: dict[str, uuid.UUID] = {}
            for provider_artifact in batch.artifacts:
                stored = await persist_provider_artifact(
                    engine,
                    provider_artifact,
                    provider_run_id=run.id,
                    title=f"BLS {family} data response",
                )
                artifacts[provider_artifact.content_hash] = stored.id
                primary_artifact_id = primary_artifact_id or stored.id
            quality = await persist_quality_record(
                engine,
                batch.quality,
                subject_type="official_release_values",
                subject_id=family,
                identity=f"quality:{family}:{batch.idempotency_key}",
            )
            factory = _factory(engine)
            async with factory() as session, session.begin():
                indicators = {
                    row.indicator_key: row
                    for row in (
                        await session.scalars(
                            select(Indicator).where(
                                Indicator.indicator_key.in_(_BLS_INDICATOR_MAP.values())
                            )
                        )
                    ).all()
                }
                for observation in batch.observations:
                    period_label = observation.reference_period_start.strftime("%Y-%m")
                    release_id = target_release_ids.get((family, period_label))
                    if release_id is None:
                        continue
                    indicator_key = _BLS_INDICATOR_MAP.get(observation.canonical_key)
                    indicator = indicators.get(indicator_key or "")
                    target_release = await session.get(MacroRelease, release_id)
                    if indicator is None or target_release is None or observation.value is None:
                        continue
                    matched += 1
                    stage = await session.scalar(
                        select(ReleaseStage).where(
                            ReleaseStage.macro_release_id == target_release.id,
                            ReleaseStage.stage_key == "release",
                        )
                    )
                    artifact_id = artifacts.get(observation.artifact_hash)
                    version = f"bls-{observation.version}"
                    snapshot_key = (
                        f"{observation.provider_series_id}:"
                        f"{observation.reference_period_start.isoformat()}:"
                        f"{observation.metadata.get('metric')}"
                    )
                    value_map = {
                        "actual": observation.value,
                        "previous": observation.previous_value,
                        "revised_previous": observation.revised_previous_value,
                    }
                    capture_delay = _aware(observation.retrieved_at) - _aware(
                        target_release.scheduled_at
                    )
                    current_release_capture = timedelta(0) <= capture_delay <= timedelta(hours=36)
                    for value_kind, value in value_map.items():
                        if value is None:
                            continue
                        existing = await session.scalar(
                            select(ReleaseValue).where(
                                ReleaseValue.macro_release_id == target_release.id,
                                ReleaseValue.indicator_id == indicator.id,
                                ReleaseValue.value_kind == value_kind,
                                ReleaseValue.data_version == version,
                                ReleaseValue.data_mode == "observed",
                            )
                        )
                        if existing is not None:
                            continue
                        prior_initial = None
                        if value_kind == "actual":
                            prior_initial = await session.scalar(
                                select(ReleaseValue.id).where(
                                    ReleaseValue.macro_release_id == target_release.id,
                                    ReleaseValue.indicator_id == indicator.id,
                                    ReleaseValue.value_kind == "actual",
                                    ReleaseValue.is_initial.is_(True),
                                    ReleaseValue.data_mode == "observed",
                                )
                            )
                        session.add(
                            ReleaseValue(
                                id=uuid.uuid4(),
                                macro_release_id=target_release.id,
                                release_stage_id=stage.id if stage else None,
                                indicator_id=indicator.id,
                                value_kind=value_kind,
                                value=value,
                                raw_value=(
                                    observation.raw_value if value_kind == "actual" else str(value)
                                ),
                                data_version=version,
                                valid_from=observation.available_at,
                                captured_at=observation.retrieved_at,
                                is_initial=(
                                    value_kind == "actual"
                                    and current_release_capture
                                    and prior_initial is None
                                ),
                                data_mode="observed",
                                source_artifact_id=artifact_id,
                                quality_id=quality.id,
                                metadata_json={
                                    "provider_series_id": observation.provider_series_id,
                                    "reference_period": (
                                        observation.reference_period_start.isoformat()
                                    ),
                                    "raw_unit": observation.raw_unit,
                                    "standard_unit": observation.standard_unit,
                                    "calculation_source": observation.metadata.get(
                                        "calculation_source"
                                    ),
                                    "derivation": observation.metadata.get("derivation"),
                                    "source_artifact_hash": observation.artifact_hash,
                                    "availability_method": observation.metadata.get(
                                        "availability_method"
                                    ),
                                    "vintage_date": observation.vintage_date.isoformat(),
                                    "provider_first_release_flag": observation.is_first_release,
                                    "provider_revision_flag": observation.is_revision,
                                    "historical_initial_status": (
                                        "verified_current_capture"
                                        if current_release_capture
                                        else "not_reconstructable_from_current_bls_api"
                                    ),
                                    "capture_delay_seconds": capture_delay.total_seconds(),
                                    "bls_snapshot_key": snapshot_key,
                                },
                            )
                        )
                        written += 1
                    target_release.data_version = version
        await complete_provider_run(
            engine,
            run.id,
            records_read=read,
            records_written=written,
            request_count=requests,
            source_artifact_id=primary_artifact_id,
            quality_grade="B",
            warnings=warnings,
            output_data={
                "release_ids": [str(item) for item in target_release_ids.values()],
                "families": list(families),
                "date_semantics": "official_release_date",
                "records_matched_to_release": matched,
                "historical_vintage_reconstruction": False,
                "point_in_time_basis": "local capture time",
            },
        )
        return {
            "status": "completed",
            "provider": clients.bls.key,
            "records_read": read,
            "records_written": written,
            "warnings": warnings,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


async def sync_fomc_materials(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    clients = build_provider_clients(settings)
    run = await record_provider_run(
        engine,
        provider_key=clients.federal_reserve.key,
        operation="sync_fomc_materials",
        idempotency_key=f"fomc-materials:{start_date}:{end_date}:{date.today()}",
        input_data={"start_date": start_date, "end_date": end_date},
        terms_url=clients.federal_reserve.terms.terms_url,
    )
    warnings: list[str] = []
    read = written = requests = 0
    primary_artifact_id: uuid.UUID | None = None
    try:
        calendar_batches = []
        for archive_year in range(start_date.year, min(end_date.year, 2020) + 1):
            calendar_batches.append(await clients.federal_reserve.fetch_calendar(year=archive_year))
            requests += 1
        if end_date.year >= 2021:
            calendar_batches.append(await clients.federal_reserve.fetch_calendar())
            requests += 1

        meetings = []
        calendar_artifact_by_meeting: dict[str, uuid.UUID] = {}
        calendar_coverage: dict[int, tuple[date, date, uuid.UUID]] = {}
        quality = None
        for batch in calendar_batches:
            calendar_artifact = await persist_provider_artifact(
                engine,
                batch.artifacts[0],
                provider_run_id=run.id,
                title="Federal Reserve FOMC calendar",
            )
            if primary_artifact_id is None:
                primary_artifact_id = calendar_artifact.id
            batch_meetings = [
                item for item in batch.meetings if start_date <= item.end_date <= end_date
            ]
            calendar_artifact_by_meeting.update(
                {item.meeting_key: calendar_artifact.id for item in batch_meetings}
            )
            batch_years = {item.end_date.year for item in batch.meetings}
            for meeting_year in batch_years:
                year_dates = [
                    item.end_date for item in batch.meetings if item.end_date.year == meeting_year
                ]
                if not year_dates:
                    continue
                prior_coverage = calendar_coverage.get(meeting_year)
                lower = min(year_dates)
                upper = max(year_dates)
                if prior_coverage is not None:
                    lower = min(lower, prior_coverage[0])
                    upper = max(upper, prior_coverage[1])
                calendar_coverage[meeting_year] = (lower, upper, calendar_artifact.id)
            meetings.extend(batch_meetings)
            await record_calendar_snapshot(
                engine,
                provider_key=clients.federal_reserve.key,
                calendar_kind="FOMC",
                period_start=(
                    min(item.end_date for item in batch_meetings) if batch_meetings else start_date
                ),
                period_end=(
                    max(item.end_date for item in batch_meetings) if batch_meetings else end_date
                ),
                captured_at=batch.retrieved_at,
                payload=[meeting.model_dump(mode="json") for meeting in batch_meetings],
                provider_run_id=run.id,
                source_artifact_id=calendar_artifact.id,
                metadata={
                    "key_qa_automatic_timestamp": False,
                    "source_url": batch.artifacts[0].source_url,
                },
            )
            quality = quality or await persist_quality_record(
                engine,
                batch.quality,
                subject_type="release_calendar",
                subject_id="FOMC",
                identity=f"quality:fomc-calendar:{calendar_artifact.content_hash}",
            )
        if quality is None:
            raise RuntimeError("Federal Reserve calendar returned no source batches")
        meetings = sorted(
            {item.meeting_key: item for item in meetings}.values(),
            key=lambda item: item.end_date,
        )
        read += len(meetings)
        await ensure_default_schedule(engine)
        for meeting in meetings:
            documents: list[tuple[FomcDocument, uuid.UUID]] = []
            seen_document_urls: set[str] = set()
            for link in meeting.materials:
                if link.url in seen_document_urls:
                    continue
                try:
                    document = await clients.federal_reserve.fetch_material(
                        link.url,
                        link.material_type,
                    )
                except ProviderError as exc:
                    warnings.append(f"{meeting.meeting_key} {link.material_type}: {exc.code}")
                    continue
                requests += 1
                stored = await persist_provider_artifact(
                    engine,
                    document.artifact,
                    provider_run_id=run.id,
                    title=document.title,
                )
                documents.append((document, stored.id))
                seen_document_urls.add(document.source_url)
                linked_materials = document.metadata.get("linked_materials", [])
                if not isinstance(linked_materials, list):
                    continue
                for linked in linked_materials:
                    if not isinstance(linked, dict):
                        continue
                    linked_url = linked.get("url")
                    linked_kind = linked.get("material_type")
                    if (
                        not isinstance(linked_url, str)
                        or linked_url in seen_document_urls
                        or linked_kind
                        not in {
                            FomcMaterialType.OPENING_STATEMENT.value,
                            FomcMaterialType.TRANSCRIPT.value,
                        }
                    ):
                        continue
                    try:
                        linked_document = await clients.federal_reserve.fetch_material(
                            linked_url,
                            FomcMaterialType(linked_kind),
                        )
                    except ProviderError as exc:
                        warnings.append(f"{meeting.meeting_key} linked {linked_kind}: {exc.code}")
                        continue
                    requests += 1
                    linked_stored = await persist_provider_artifact(
                        engine,
                        linked_document.artifact,
                        provider_run_id=run.id,
                        title=linked_document.title,
                    )
                    documents.append((linked_document, linked_stored.id))
                    seen_document_urls.add(linked_document.source_url)
            statement_candidates = [
                item for item in documents if item[0].document_type == FomcMaterialType.STATEMENT
            ]
            statement_pair = (
                max(
                    statement_candidates,
                    key=lambda item: (
                        item[0].published_at is not None,
                        item[0].target_rate_lower is not None
                        and item[0].target_rate_upper is not None,
                        item[0].artifact.content_type == "text/html",
                    ),
                )
                if statement_candidates
                else None
            )
            statement_published_at = (
                statement_pair[0].published_at
                if statement_pair and statement_pair[0].published_at
                else meeting.statement_published_at
            )
            if statement_published_at is None:
                warnings.append(
                    f"{meeting.meeting_key}: verified statement publication timestamp unavailable"
                )
                continue
            statement = statement_pair[0] if statement_pair else None
            statement_artifact_id = (
                statement_pair[1]
                if statement_pair
                else calendar_artifact_by_meeting[meeting.meeting_key]
            )
            published_at = _aware(statement_published_at)
            release_key = f"fomc-{meeting.end_date.isoformat()}-observed"
            statement_released = statement is not None and published_at <= datetime.now(UTC)
            source_hash = (
                str(statement.metadata.get("semantic_hash") or statement.artifact.content_hash)
                if statement is not None
                else str(meeting.metadata.get("calendar_artifact_hash", "unknown"))
            )
            statement_data_version = (
                f"fed-{source_hash[:16]}-{_FOMC_VALUE_PARSER_VERSION.rsplit('-', 1)[-1]}"
                if statement is not None
                else f"fed-calendar-{source_hash[:16]}"
            )
            meeting_calendar_artifact_id = calendar_artifact_by_meeting[meeting.meeting_key]
            current_materials = [
                {
                    "document_type": document.document_type.value,
                    "artifact_id": str(artifact_id),
                    "source_url": document.source_url,
                    "published_at": (
                        document.published_at.isoformat() if document.published_at else None
                    ),
                }
                for document, artifact_id in documents
            ]
            factory = _factory(engine)
            async with factory() as session, session.begin():
                release = await session.scalar(
                    select(MacroRelease).where(
                        MacroRelease.release_key == release_key,
                    )
                )
                if release is None:
                    release = MacroRelease(
                        id=uuid.uuid4(),
                        release_key=release_key,
                        release_type="FOMC",
                        title="Federal Open Market Committee decision",
                        country="USA",
                        period_label=meeting.end_date.isoformat(),
                        scheduled_at=published_at,
                        released_at=published_at if statement_released else None,
                        source_timezone=meeting.source_timezone,
                        status="released" if statement_released else "scheduled",
                        data_version=statement_data_version,
                        data_mode="observed",
                        source_artifact_id=statement_artifact_id,
                        primary_quality_id=quality.id,
                        contamination_level="unknown",
                        clean_window=False,
                        overlapping_events=[],
                        confounding_notes=[
                            "key-Q&A and press-end timestamps require manual verification"
                        ],
                        metadata_json={
                            "meeting_start_date": meeting.start_date.isoformat(),
                            "meeting_end_date": meeting.end_date.isoformat(),
                            "has_sep": meeting.has_sep,
                            "key_qa_timestamp_generated": False,
                            "unresolved_stages": ["key_qa", "press_end"],
                            "unresolved_stage_reason": (
                                "official source does not publish verified timestamps; "
                                "manual verification is required"
                            ),
                            "calendar_artifact_ids": [str(meeting_calendar_artifact_id)],
                            "materials": current_materials,
                        },
                    )
                    session.add(release)
                    written += 1
                else:
                    was_invalidated = release.status == _INVALIDATED_RELEASE_STATUS
                    release.scheduled_at = published_at
                    if statement_released:
                        release.released_at = published_at
                        release.status = "released"
                        release.data_version = statement_data_version
                    elif was_invalidated:
                        release.released_at = None
                        release.status = "scheduled"
                        release.data_version = statement_data_version
                    if statement is not None or release.status != "released":
                        release.source_artifact_id = statement_artifact_id
                    release.primary_quality_id = quality.id
                    prior_materials = release.metadata_json.get("materials", [])
                    merged_materials = {
                        item["source_url"]: item
                        for item in prior_materials
                        if isinstance(item, dict) and isinstance(item.get("source_url"), str)
                    }
                    merged_materials.update(
                        {item["source_url"]: item for item in current_materials}
                    )
                    release.metadata_json = {
                        **release.metadata_json,
                        "meeting_start_date": meeting.start_date.isoformat(),
                        "meeting_end_date": meeting.end_date.isoformat(),
                        "has_sep": meeting.has_sep,
                        "key_qa_timestamp_generated": False,
                        "unresolved_stages": ["key_qa", "press_end"],
                        "unresolved_stage_reason": (
                            "official source does not publish verified timestamps; "
                            "manual verification is required"
                        ),
                        "calendar_artifact_ids": [str(meeting_calendar_artifact_id)],
                        "materials": list(merged_materials.values()),
                    }
                    if was_invalidated:
                        release.confounding_notes = [
                            note
                            for note in release.confounding_notes
                            if not note.startswith("invalidated: not present in authoritative")
                        ]
                        release.metadata_json = {
                            **release.metadata_json,
                            "provider_reconciliation": {
                                "state": "restored",
                                "reason": "present_in_authoritative_fomc_calendar",
                                "provider_key": "federal_reserve_fomc",
                                "provider_run_id": str(run.id),
                                "calendar_artifact_id": str(meeting_calendar_artifact_id),
                                "restored_at": datetime.now(UTC).isoformat(),
                            },
                        }
                await session.flush()
                stage = await _upsert_release_stage(
                    session,
                    release=release,
                    stage_key="statement",
                    title="FOMC statement",
                    sequence=1,
                    published_at=published_at,
                    source_artifact_id=statement_artifact_id,
                    released=statement_released,
                    metadata={
                        "timestamp_source": (
                            "Federal Reserve publication metadata"
                            if statement is not None and statement.published_at is not None
                            else meeting.metadata.get("statement_time_basis")
                        ),
                        "scheduled_from_calendar": statement is None,
                    },
                )
                press_pair = next(
                    (
                        item
                        for item in documents
                        if item[0].document_type == FomcMaterialType.PRESS_CONFERENCE
                    ),
                    None,
                )
                if meeting.press_conference_at is not None:
                    await _upsert_release_stage(
                        session,
                        release=release,
                        stage_key="press_conference",
                        title="FOMC press conference",
                        sequence=2,
                        published_at=_aware(meeting.press_conference_at),
                        source_artifact_id=(
                            press_pair[1]
                            if press_pair is not None
                            else calendar_artifact_by_meeting[meeting.meeting_key]
                        ),
                        released=(
                            press_pair is not None
                            and _aware(meeting.press_conference_at) <= datetime.now(UTC)
                        ),
                        metadata={
                            "timestamp_source": meeting.metadata.get("press_conference_time_basis"),
                            "meeting_specific_material_url": (
                                press_pair[0].source_url if press_pair is not None else None
                            ),
                            "scheduled_from_calendar": press_pair is None,
                            "key_qa_timestamp_generated": False,
                            "press_end_timestamp_generated": False,
                        },
                    )
                indicators = {
                    row.indicator_key: row
                    for row in (
                        await session.scalars(
                            select(Indicator).where(
                                Indicator.indicator_key.in_(("fed_funds_lower", "fed_funds_upper"))
                            )
                        )
                    ).all()
                }
                for indicator_key, raw_value in (
                    (
                        "fed_funds_lower",
                        statement.target_rate_lower if statement is not None else None,
                    ),
                    (
                        "fed_funds_upper",
                        statement.target_rate_upper if statement is not None else None,
                    ),
                ):
                    indicator = indicators.get(indicator_key)
                    if indicator is None or raw_value is None:
                        continue
                    assert statement is not None
                    try:
                        value = Decimal(raw_value)
                    except InvalidOperation:
                        warnings.append(f"{meeting.meeting_key}: invalid target rate {raw_value}")
                        continue
                    if await _append_fomc_target_value(
                        session,
                        release=release,
                        stage=stage,
                        indicator=indicator,
                        value=value,
                        raw_value=raw_value,
                        data_version=release.data_version,
                        published_at=published_at,
                        statement=statement,
                        statement_artifact_id=statement_artifact_id,
                        quality_id=quality.id,
                    ):
                        written += 1
            await schedule_release_tasks(
                engine,
                macro_release_id=release.id,
                release_at=published_at,
            )
        invalidated_release_ids = await _invalidate_stale_fomc_releases(
            engine,
            start_date=start_date,
            end_date=end_date,
            authoritative_meeting_dates={item.end_date for item in meetings},
            calendar_coverage=calendar_coverage,
            provider_run_id=run.id,
        )
        if invalidated_release_ids:
            written += len(invalidated_release_ids)
            warnings.append(
                "soft-invalidated provider-owned FOMC releases absent from the "
                f"authoritative calendar: {len(invalidated_release_ids)}"
            )
        await complete_provider_run(
            engine,
            run.id,
            records_read=read,
            records_written=written,
            request_count=requests,
            source_artifact_id=primary_artifact_id,
            quality_grade="A" if meetings else "C",
            warnings=warnings,
            output_data={
                "meeting_count": len(meetings),
                "invalidated_release_ids": [str(item) for item in invalidated_release_ids],
                "key_qa_timestamp_generated": False,
            },
        )
        return {
            "status": "completed",
            "provider": clients.federal_reserve.key,
            "records_read": read,
            "records_written": written,
            "invalidated_release_ids": [str(item) for item in invalidated_release_ids],
            "warnings": warnings,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


async def sync_fred_foundation(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    as_of: date | None = None,
) -> dict[str, object]:
    clients = build_provider_clients(settings)
    public_current = settings.fred_api_key is None
    run = await record_provider_run(
        engine,
        provider_key=clients.fred.key,
        operation="sync_current_public_series" if public_current else "sync_foundation_series",
        idempotency_key=(
            f"fred-public:{start_date}:{end_date}:{date.today()}"
            if public_current
            else f"fred-foundation:{start_date}:{end_date}:{as_of}:{date.today()}"
        ),
        input_data={
            "start_date": start_date,
            "end_date": end_date,
            "as_of": as_of,
            "source_mode": "current_public_csv" if public_current else "alfred_api",
        },
        terms_url=clients.fred.terms.terms_url,
    )
    read = written = requests = 0
    warnings: list[str] = []
    primary_artifact_id: uuid.UUID | None = None
    try:
        if public_current and as_of is not None:
            await upsert_entitlement(
                engine,
                provider_key=clients.fred.key,
                capability="series_vintages",
                status="not_configured",
                provider_run_id=run.id,
                error_code="provider_not_configured",
                terms_url=clients.fred.terms.terms_url,
            )
            raise ProviderError(
                clients.fred.key,
                ProviderErrorCode.POINT_IN_TIME,
                "FRED public current CSV cannot provide point-in-time vintages",
            )
        catalog = [
            item
            for item in load_catalog(repository_root() / "data" / "macro")
            if item.provider == clients.fred.key
        ]
        factory = _factory(engine)
        async with factory() as session, session.begin():
            provider_row = await session.scalar(
                select(Provider).where(Provider.key == clients.fred.key)
            )
            if provider_row is None:
                provider_row = Provider(
                    key=clients.fred.key,
                    name="FRED/ALFRED",
                    base_url=clients.fred.base_url,
                    enabled=True,
                    requires_credentials=True,
                    terms_url=clients.fred.terms.terms_url,
                )
                session.add(provider_row)
                await session.flush()
            entity_definitions = {
                "US": ("US", "USA", "United States", "USD", "America/New_York"),
                "CHN": ("CN", "CHN", "China", "CNY", "Asia/Shanghai"),
                "JPN": ("JP", "JPN", "Japan", "JPY", "Asia/Tokyo"),
                "EA19": ("EA", "EA19", "Euro Area", "EUR", "Europe/Brussels"),
                "GBR": ("GB", "GBR", "United Kingdom", "GBP", "Europe/London"),
            }
            entity_ids: dict[str, int] = {}
            for entity_code in sorted({item.entity for item in catalog}):
                iso2, iso3, name, currency, timezone = entity_definitions[entity_code]
                entity = await session.scalar(
                    select(EconomicEntity).where(EconomicEntity.iso3 == iso3)
                )
                if entity is None:
                    entity = EconomicEntity(
                        iso2=iso2,
                        iso3=iso3,
                        name=name,
                        entity_type="country",
                        parent_id=None,
                        currency=currency,
                        timezone=timezone,
                        latitude=None,
                        longitude=None,
                        metadata_json={"catalog_source": "fred_alfred"},
                    )
                    session.add(entity)
                    await session.flush()
                entity_ids[entity_code] = entity.id
            provider_id = provider_row.id
        for definition in catalog:
            if public_current:
                batch = await clients.fred.fetch_public_current_batch(
                    definition.native_id,
                    start=start_date,
                    end=end_date,
                )
            else:
                batch = await clients.fred.fetch_observation_batch(
                    definition.native_id,
                    start=start_date,
                    end=end_date,
                    as_of=as_of,
                )
            requests += 1
            read += len(batch.observations)
            artifact = await persist_provider_artifact(
                engine,
                batch.artifacts[0],
                provider_run_id=run.id,
                title=f"FRED {definition.native_id} observations",
            )
            primary_artifact_id = primary_artifact_id or artifact.id
            quality_row = await persist_quality_record(
                engine,
                batch.quality,
                subject_type="macro_series",
                subject_id=definition.canonical_key,
                identity=f"quality:fred:{definition.native_id}:{artifact.content_hash}",
            )
            factory = _factory(engine)
            async with factory() as session, session.begin():
                context_instrument = None
                existing_context_bars: dict[datetime, MarketBar] = {}
                context_key = _FRED_MARKET_CONTEXT.get(definition.native_id)
                if context_key is not None:
                    context_instrument = await session.scalar(
                        select(MarketInstrument).where(
                            MarketInstrument.canonical_key == context_key
                        )
                    )
                    if context_instrument is not None:
                        existing_context_bars = {
                            _aware(row.timestamp): row
                            for row in (
                                await session.scalars(
                                    select(MarketBar).where(
                                        MarketBar.instrument_id == context_instrument.id,
                                        MarketBar.provider_key == clients.fred.key,
                                        MarketBar.interval_seconds == 86400,
                                        MarketBar.data_mode == "observed",
                                    )
                                )
                            ).all()
                        }
                series = await session.scalar(
                    select(Series).where(
                        Series.provider_id == provider_id,
                        Series.native_id == definition.native_id,
                    )
                )
                if series is None:
                    series = Series(
                        id=uuid.uuid4(),
                        provider_id=provider_id,
                        native_id=definition.native_id,
                        canonical_key=definition.canonical_key,
                        entity_id=entity_ids[definition.entity],
                        title=definition.title,
                        description=None,
                        frequency=definition.frequency,
                        unit=definition.unit,
                        seasonal_adjustment=None,
                        observation_type="official_series",
                        source_url=definition.source_url,
                        release_key=None,
                        availability_method=(
                            "ingestion_time_proxy"
                            if public_current
                            else definition.availability.method.value
                        ),
                        availability_precision=(
                            "timestamp"
                            if public_current
                            else definition.availability.precision.value
                        ),
                        default_transform=definition.transform,
                        active=True,
                        metadata_json={
                            "state_dimensions": definition.state_dimensions,
                            "orientation": definition.orientation,
                            "weight": definition.weight,
                            "minimum_history": definition.minimum_history,
                            "freshness_half_life_days": definition.freshness_half_life_days,
                            "source_mode": "current_public_csv" if public_current else "observed",
                            "point_in_time": not public_current,
                            "current_observation_only": public_current,
                            "provider_metric": "fred_graph_csv" if public_current else "alfred_api",
                            "underlying_series_terms_must_be_checked": True,
                        },
                    )
                    session.add(series)
                    await session.flush()
                else:
                    series.entity_id = entity_ids[definition.entity]
                    prior_source_mode = str(series.metadata_json.get("source_mode") or "")
                    series.metadata_json = {
                        **series.metadata_json,
                        "state_dimensions": definition.state_dimensions,
                        "orientation": definition.orientation,
                        "weight": definition.weight,
                        "minimum_history": definition.minimum_history,
                        "freshness_half_life_days": definition.freshness_half_life_days,
                        "source_mode": "current_public_csv" if public_current else "observed",
                        "point_in_time": not public_current,
                        "current_observation_only": public_current,
                        "provider_metric": "fred_graph_csv" if public_current else "alfred_api",
                        "fixture_observations_retained": prior_source_mode in {"demo", "fixture"},
                        "underlying_series_terms_must_be_checked": True,
                    }
                for observation in batch.observations:
                    existing = await session.scalar(
                        select(Observation).where(
                            Observation.series_id == series.id,
                            Observation.period_start == observation.period_start,
                            Observation.vintage_date == observation.vintage_date,
                            Observation.data_mode == "observed",
                        )
                    )
                    if existing is not None:
                        if context_instrument is not None:
                            await _upsert_fred_context_bar(
                                session,
                                instrument=context_instrument,
                                existing=existing_context_bars,
                                observation=observation,
                                quality_id=quality_row.id,
                                provider_key=clients.fred.key,
                                source_mode=(
                                    "current_public_csv" if public_current else "alfred_api"
                                ),
                                retrieved_at=batch.retrieved_at,
                                native_id=definition.native_id,
                            )
                        continue
                    session.add(
                        Observation(
                            series_id=series.id,
                            period_start=observation.period_start,
                            period_end=observation.period_end,
                            value=observation.value,
                            raw_value=observation.raw_value,
                            vintage_date=observation.vintage_date,
                            realtime_start=observation.realtime_start,
                            realtime_end=observation.realtime_end,
                            available_at=observation.available_at,
                            availability_method=observation.availability_method.value,
                            availability_precision=observation.availability_precision.value,
                            fetched_at=observation.fetched_at,
                            is_preliminary=False,
                            is_revised=observation.is_revised,
                            data_mode="observed",
                            quality_flags=observation.quality_flags,
                            source_hash=observation.source_hash,
                        )
                    )
                    written += 1
                    if context_instrument is not None:
                        await _upsert_fred_context_bar(
                            session,
                            instrument=context_instrument,
                            existing=existing_context_bars,
                            observation=observation,
                            quality_id=quality_row.id,
                            provider_key=clients.fred.key,
                            source_mode=("current_public_csv" if public_current else "alfred_api"),
                            retrieved_at=batch.retrieved_at,
                            native_id=definition.native_id,
                        )
        derived_written = await _sync_derived_market_context(
            engine, calculated_at=datetime.now(UTC)
        )
        written += derived_written
        if derived_written:
            warnings.append(
                f"persisted {derived_written} WorldState-derived Treasury curve observations"
            )
        await upsert_entitlement(
            engine,
            provider_key=clients.fred.key,
            capability="series_vintages",
            status="not_configured" if public_current else "granted",
            provider_run_id=run.id,
            terms_url=clients.fred.terms.terms_url,
            metadata={
                "public_current_csv": public_current,
                "point_in_time": not public_current,
            },
        )
        if public_current:
            await upsert_entitlement(
                engine,
                provider_key=clients.fred.key,
                capability="current_series",
                status="granted",
                provider_run_id=run.id,
                terms_url=clients.fred.terms.terms_url,
                metadata={"source_mode": "current_public_csv", "point_in_time": False},
            )
        await complete_provider_run(
            engine,
            run.id,
            records_read=read,
            records_written=written,
            request_count=requests,
            source_artifact_id=primary_artifact_id,
            quality_grade="A" if as_of else "B",
            warnings=warnings,
            output_data={
                "series": sorted(item.native_id for item in catalog),
                "series_count": len(catalog),
                "as_of": as_of,
                "source_mode": "current_public_csv" if public_current else "alfred_api",
                "point_in_time": not public_current,
            },
        )
        return {
            "status": "completed",
            "provider": clients.fred.key,
            "records_read": read,
            "records_written": written,
            "warnings": warnings,
            "source_mode": "current_public_csv" if public_current else "alfred_api",
            "point_in_time": not public_current,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


async def sync_official_data(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    event_types: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Run independent official sources and report partial success honestly."""

    selected = tuple(dict.fromkeys(event_types or ("US_CPI", "US_NFP", "FOMC")))
    unsupported = set(selected) - _SUPPORTED_EVENT_TYPES
    if unsupported:
        raise ValueError(f"unsupported event types: {sorted(unsupported)}")
    if not selected:
        raise ValueError("at least one event type is required")
    bls_families: tuple[BlsFamily, ...] = tuple(item for item in selected if item in _BLS_FAMILIES)
    results: dict[str, object] = {}
    failures: dict[str, str] = {}
    operations: list[tuple[str, Any, dict[str, object]]] = []
    if bls_families:
        operations.extend(
            (
                ("bls_calendar", sync_bls_calendar, {"families": bls_families}),
                ("bls_actuals", sync_bls_actuals, {"families": bls_families}),
            )
        )
    if "FOMC" in selected:
        operations.append(("fomc", sync_fomc_materials, {}))
    # FRED/ALFRED supplies the shared pre-event macro environment for every
    # supported release family, so it remains part of each selected sync.
    operations.append(("fred", sync_fred_foundation, {}))
    usable_operation_count = 0
    for key, operation, extra in operations:
        try:
            operation_result = await operation(
                engine,
                settings,
                start_date=start_date,
                end_date=end_date,
                **extra,
            )
            results[key] = operation_result
            child_status = (
                str(operation_result.get("status", "completed"))
                if isinstance(operation_result, dict)
                else "completed"
            )
            if child_status in {"completed", "ok"}:
                usable_operation_count += 1
            elif child_status == "partial":
                usable_operation_count += 1
                failures[key] = "operation returned partial provider coverage"
            elif child_status == "blocked":
                failures[key] = "operation was blocked by its provider or verified-data gate"
            else:
                failures[key] = f"operation returned unsupported status {child_status!r}"
        except Exception as exc:
            failures[key] = f"{type(exc).__name__}: {exc}"
    overall_status = "completed"
    if failures:
        overall_status = "partial" if usable_operation_count else "blocked"
    return {
        "status": overall_status,
        "requested_event_types": list(selected),
        "results": results,
        "failures": failures,
    }


__all__ = [
    "sync_bls_actuals",
    "sync_bls_calendar",
    "sync_fomc_materials",
    "sync_fred_foundation",
    "sync_official_data",
]
