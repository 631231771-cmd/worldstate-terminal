"""Licensed consensus and market-data ingestion with explicit entitlement/cost gates."""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worldstate.application.data_foundation_service import (
    complete_provider_run,
    fail_provider_run,
    record_provider_run,
    record_quota,
    upsert_entitlement,
)
from worldstate.application.data_manifest_service import (
    record_calendar_snapshot,
    record_market_data_manifest,
)
from worldstate.application.provider_runtime import (
    build_provider_clients,
    persist_provider_artifact,
    persist_quality_record,
)
from worldstate.application.reconciliation_service import (
    reconcile_values,
    record_market_reconciliation,
)
from worldstate.config import Settings
from worldstate.db.models import (
    ConsensusSnapshot,
    DataQualityRecord,
    FuturesContract,
    Indicator,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    MarketInstrument,
    ProviderQuota,
    ReleaseStage,
    ReleaseValue,
)
from worldstate.market_core.sessions import expected_tradable_bars
from worldstate.provider_kit import (
    BarQuery,
    ConsensusCalendarBatch,
    ConsensusSnapshotRecord,
    DatabentoCostEstimate,
    DatabentoDownloadRequest,
    MarketInstrumentRef,
    ProviderBudgetError,
    ProviderError,
    ProviderErrorCode,
    TradingEconomicsBrowserPage,
    TradingEconomicsConsensusProvider,
)

_ROOT_TO_INSTRUMENT_KEY = {
    "GC": "gold_gc",
    "SI": "silver_si",
    "CL": "wti_cl",
    "ES": "sp500_es",
    "NQ": "nasdaq_nq",
    "ZT": "ust2y_zt",
    "ZN": "ust10y_zn",
    "DX": "dollar_dxy",
    "VX": "vix",
}
_TE_SYNC_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class _MarketDownloadPlan:
    """One quoted Databento request prepared before any paid download starts."""

    root: str
    instrument: MarketInstrument
    schema_name: str
    start: datetime
    end: datetime
    interval_seconds: int
    estimate: DatabentoCostEstimate


@dataclass(frozen=True)
class _TeComparison:
    subject_type: str
    subject_id: str
    field_name: str
    authoritative_provider_key: str
    authoritative_value: Decimal | str | None
    comparison_value: Decimal | str | None
    unit: str
    tolerance: Decimal
    authoritative_artifact_id: uuid.UUID | None


def _normalize_unit(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().lower().replace("_", " ").split())
    aliases = {
        "%": "percent",
        "percentage": "percent",
        "percentage point": "percent",
        "percentage points": "percent",
        "thousands of persons": "thousand persons",
        "thousands persons": "thousand persons",
        "k persons": "thousand persons",
    }
    return aliases.get(normalized, normalized)


def _normalize_reference(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = " ".join(value.strip().split())
    if match := re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", text):
        return f"{match.group(1)}-{match.group(2)}"
    for pattern in ("%b %Y", "%B %Y", "%Y %b", "%Y %B"):
        try:
            parsed = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return parsed.strftime("%Y-%m")
    return text.casefold()


def _lower_quality_grade(value: str) -> str:
    return {"A": "B", "B": "C", "C": "D"}.get(value.upper(), "D")


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _continuous_manifest_prefix(
    manifests: list[MarketDataManifest],
    *,
    start: datetime,
) -> tuple[datetime | None, list[MarketDataManifest]]:
    """Return the longest single-contract manifest chain beginning at ``start``.

    Combining only min(start)/max(end) can hide an internal gap. Combining
    different contracts can also make an event appear cached even though no
    analysis-eligible single-contract dataset exists.
    """

    groups: dict[tuple[object, ...], list[MarketDataManifest]] = {}
    for manifest in manifests:
        identity = (
            manifest.dataset,
            manifest.schema_name,
            manifest.futures_contract_id,
            manifest.contract_code,
        )
        groups.setdefault(identity, []).append(manifest)
    best_end: datetime | None = None
    best_rows: list[MarketDataManifest] = []
    for rows in groups.values():
        cursor = _aware(start)
        used: list[MarketDataManifest] = []
        for row in sorted(rows, key=lambda item: (_aware(item.start_at), _aware(item.end_at))):
            row_start = _aware(row.start_at)
            row_end = _aware(row.end_at)
            if row_end <= cursor:
                continue
            if row_start > cursor:
                break
            cursor = max(cursor, row_end)
            used.append(row)
        if used and (best_end is None or cursor > best_end):
            best_end = cursor
            best_rows = used
    return best_end, best_rows


async def _te_monthly_requests_used(engine: AsyncEngine) -> int:
    now = datetime.now(UTC)
    factory = _factory(engine)
    async with factory() as session:
        value = await session.scalar(
            select(ProviderQuota.used_value)
            .where(
                ProviderQuota.provider_key == "trading_economics",
                ProviderQuota.quota_key == "calendar_requests",
                ProviderQuota.period_start <= now,
                ProviderQuota.period_end > now,
            )
            .order_by(ProviderQuota.captured_at.desc())
            .limit(1)
        )
    return int(value or 0)


def _te_mapping(snapshot: ConsensusSnapshotRecord) -> tuple[str, str] | None:
    text = f"{snapshot.event} {snapshot.ticker or ''}".lower().replace("-", " ")
    is_cpi = any(marker in text for marker in ("consumer price", "cpi", "inflation rate"))
    if "core" in text and is_cpi:
        return (
            "US_CPI",
            "core_yoy" if "year" in text or "yoy" in text else "core_mom",
        )
    if is_cpi:
        return (
            "US_CPI",
            "headline_yoy" if "year" in text or "yoy" in text else "headline_mom",
        )
    if "nonfarm" in text or "non farm" in text or "payroll" in text:
        return "US_NFP", "nonfarm_payrolls"
    if "unemployment rate" in text:
        return "US_NFP", "unemployment_rate"
    if "average hourly earnings" in text or "hourly earning" in text:
        return (
            "US_NFP",
            (
                "average_hourly_earnings_yoy"
                if "year" in text or "yoy" in text
                else "average_hourly_earnings_mom"
            ),
        )
    if "participation" in text:
        return "US_NFP", "labor_force_participation"
    if "interest rate decision" in text or "fed funds" in text:
        return "FOMC", "fed_funds_upper"
    return None


async def _matching_release(
    session: AsyncSession,
    *,
    release_type: str,
    release_at: datetime,
) -> MacroRelease | None:
    lower = release_at - timedelta(minutes=15)
    upper = release_at + timedelta(minutes=15)
    return cast(
        MacroRelease | None,
        await session.scalar(
            select(MacroRelease)
            .where(
                MacroRelease.release_type == release_type,
                MacroRelease.data_mode == "observed",
                MacroRelease.status != "invalidated",
                MacroRelease.scheduled_at >= lower,
                MacroRelease.scheduled_at <= upper,
            )
            .order_by(MacroRelease.scheduled_at)
            .limit(1)
        ),
    )


async def _snapshot_trading_economics_consensus(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    pit_at: datetime | None = None,
    captured_batch: ConsensusCalendarBatch | None = None,
) -> dict[str, object]:
    invocation_id = uuid.uuid4()
    clients = build_provider_clients(
        settings,
        trading_economics_monthly_requests_used=await _te_monthly_requests_used(engine),
    )
    provider = clients.trading_economics
    run = await record_provider_run(
        engine,
        provider_key=provider.key,
        operation="snapshot_consensus",
        idempotency_key=f"te-consensus:{start_date}:{end_date}:{pit_at}:{invocation_id}",
        input_data={"start_date": start_date, "end_date": end_date, "pit_at": pit_at},
        terms_url=provider.terms.terms_url,
    )
    warnings: list[str] = []
    try:
        if captured_batch is None and settings.trading_economics_api_key is None:
            await upsert_entitlement(
                engine,
                provider_key=provider.key,
                capability="calendar_consensus",
                status="not_configured",
                provider_run_id=run.id,
                error_code=ProviderErrorCode.NOT_CONFIGURED.value,
                terms_url=provider.terms.terms_url,
            )
            raise ProviderError(
                provider.key,
                ProviderErrorCode.NOT_CONFIGURED,
                "Trading Economics API key is not configured",
            )
        if (
            captured_batch is None
            and pit_at is not None
            and not settings.trading_economics_pit_entitled
        ):
            await upsert_entitlement(
                engine,
                provider_key=provider.key,
                capability="historical_pit_consensus",
                status="denied",
                provider_run_id=run.id,
                error_code=ProviderErrorCode.ENTITLEMENT.value,
                terms_url=provider.terms.terms_url,
            )
            raise ProviderError(
                provider.key,
                ProviderErrorCode.ENTITLEMENT,
                "Trading Economics historical PIT entitlement is not enabled",
            )
        batch = captured_batch or await provider.fetch_calendar(
            start=start_date, end=end_date, pit_at=pit_at
        )
        warnings.extend(batch.warnings)
        artifact = await persist_provider_artifact(
            engine,
            batch.artifacts[0],
            provider_run_id=run.id,
            title="Trading Economics economic calendar snapshot",
        )
        await record_calendar_snapshot(
            engine,
            provider_key=provider.key,
            calendar_kind="US_MACRO_CONSENSUS",
            period_start=start_date,
            period_end=end_date,
            captured_at=batch.retrieved_at,
            payload=[snapshot.model_dump(mode="json") for snapshot in batch.snapshots],
            is_point_in_time=batch.pit_query_at is not None,
            provider_run_id=run.id,
            source_artifact_id=artifact.id,
            metadata={
                "survey_field": "Forecast",
                "proprietary_field": "TEForecast",
                "actual_authority": "cross_check_only",
                "redistribution_restricted": True,
            },
        )
        quota = batch.quota
        month_start = datetime(
            batch.retrieved_at.year,
            batch.retrieved_at.month,
            1,
            tzinfo=UTC,
        )
        month_end = (
            datetime(batch.retrieved_at.year + 1, 1, 1, tzinfo=UTC)
            if batch.retrieved_at.month == 12
            else datetime(
                batch.retrieved_at.year,
                batch.retrieved_at.month + 1,
                1,
                tzinfo=UTC,
            )
        )
        if captured_batch is None:
            await record_quota(
                engine,
                provider_key=provider.key,
                quota_key="calendar_requests",
                unit="requests",
                period_start=month_start,
                period_end=month_end,
                used_value=Decimal(quota.monthly_used),
                limit_value=(Decimal(quota.monthly_limit) if quota.monthly_limit else None),
                remaining_value=(
                    Decimal(quota.remaining) if quota.remaining is not None else None
                ),
                captured_at=quota.observed_at,
                provider_run_id=run.id,
                source_artifact_id=artifact.id,
            )
            await upsert_entitlement(
                engine,
                provider_key=provider.key,
                capability="calendar_consensus",
                status="granted",
                provider_run_id=run.id,
                source_artifact_id=artifact.id,
                terms_url=provider.terms.terms_url,
            )
            await upsert_entitlement(
                engine,
                provider_key=provider.key,
                capability="historical_pit_consensus",
                status="granted" if batch.entitlement.historical_point_in_time else "denied",
                provider_run_id=run.id,
                source_artifact_id=artifact.id,
                error_message=batch.entitlement.reason,
                terms_url=provider.terms.terms_url,
            )
        quality = await persist_quality_record(
            engine,
            batch.quality,
            subject_type="consensus_calendar",
            subject_id=f"{start_date}:{end_date}:{pit_at}",
            identity=f"quality:te:{artifact.content_hash}",
        )
        written = reconciled = skipped = 0
        factory = _factory(engine)
        async with factory() as session, session.begin():
            indicators = {
                row.indicator_key: row for row in (await session.scalars(select(Indicator))).all()
            }
            for snapshot in batch.snapshots:
                mapping = _te_mapping(snapshot)
                if mapping is None:
                    skipped += 1
                    continue
                release_type, indicator_key = mapping
                indicator = indicators.get(indicator_key)
                release = await _matching_release(
                    session,
                    release_type=release_type,
                    release_at=_aware(snapshot.release_at),
                )
                if indicator is None or release is None:
                    skipped += 1
                    continue
                if snapshot.survey_consensus is not None:
                    existing = await session.scalar(
                        select(ConsensusSnapshot).where(
                            ConsensusSnapshot.macro_release_id == release.id,
                            ConsensusSnapshot.indicator_id == indicator.id,
                            ConsensusSnapshot.captured_at == snapshot.effective_snapshot_at,
                            ConsensusSnapshot.source_name == "Trading Economics Survey Consensus",
                            ConsensusSnapshot.data_mode == "observed",
                        )
                    )
                    if existing is None:
                        eligible = _aware(snapshot.effective_snapshot_at) < _aware(
                            release.scheduled_at
                        )
                        session.add(
                            ConsensusSnapshot(
                                id=uuid.uuid4(),
                                macro_release_id=release.id,
                                indicator_id=indicator.id,
                                consensus_value=snapshot.survey_consensus,
                                source_name="Trading Economics Survey Consensus",
                                source_url=batch.artifacts[0].source_url,
                                captured_at=snapshot.effective_snapshot_at,
                                quality_grade=quality.quality_grade,
                                is_manual=False,
                                data_mode="observed",
                                verification_notes=(
                                    "Eligible last-pre-release candidate; TEForecast is excluded."
                                    if eligible
                                    else (
                                        "Post-release snapshot; excluded from surprise calculation."
                                    )
                                ),
                                source_artifact_id=artifact.id,
                                quality_id=quality.id,
                                metadata_json={
                                    "calendar_id": snapshot.calendar_id,
                                    "ticker": snapshot.ticker,
                                    "event": snapshot.event,
                                    "country": snapshot.country,
                                    "reference": snapshot.reference,
                                    "release_at": snapshot.release_at.isoformat(),
                                    "actual": str(snapshot.actual)
                                    if snapshot.actual is not None
                                    else None,
                                    "previous": str(snapshot.previous)
                                    if snapshot.previous is not None
                                    else None,
                                    "revised": str(snapshot.revised)
                                    if snapshot.revised is not None
                                    else None,
                                    "survey_consensus": str(snapshot.survey_consensus),
                                    "te_forecast": str(snapshot.te_forecast)
                                    if snapshot.te_forecast is not None
                                    else None,
                                    "raw_actual": snapshot.raw_actual,
                                    "raw_previous": snapshot.raw_previous,
                                    "raw_revised": snapshot.raw_revised,
                                    "raw_survey_consensus": snapshot.raw_survey_consensus,
                                    "raw_te_forecast": snapshot.raw_te_forecast,
                                    "unit": snapshot.unit,
                                    "provider_updated_at": (
                                        snapshot.provider_updated_at.isoformat()
                                        if snapshot.provider_updated_at
                                        else None
                                    ),
                                    "snapshot_captured_at": snapshot.captured_at.isoformat(),
                                    "pit_query_at": snapshot.pit_query_at.isoformat()
                                    if snapshot.pit_query_at
                                    else None,
                                    "pit_verified": snapshot.pit_verified,
                                    "raw_response_hash": snapshot.artifact_hash,
                                    "provider": snapshot.provider_key,
                                    "license_name": snapshot.license_name,
                                    "provider_metadata": snapshot.metadata,
                                    "surprise_eligible": eligible,
                                    "te_forecast_used_as_consensus": False,
                                },
                            )
                        )
                        written += 1
        # Reconciliation uses separate transactions after the insert transaction is durable.
        # TE remains a comparison source only; it never overwrites official values.
        reconciliation_inputs: list[_TeComparison] = []
        factory = _factory(engine)
        async with factory() as session:
            indicators = {
                row.indicator_key: row for row in (await session.scalars(select(Indicator))).all()
            }
            for snapshot in batch.snapshots:
                mapping = _te_mapping(snapshot)
                if mapping is None:
                    continue
                release_type, indicator_key = mapping
                indicator = indicators.get(indicator_key)
                release = await _matching_release(
                    session,
                    release_type=release_type,
                    release_at=_aware(snapshot.release_at),
                )
                if indicator is None or release is None:
                    continue
                official_rows = (
                    await session.scalars(
                        select(ReleaseValue)
                        .where(
                            ReleaseValue.macro_release_id == release.id,
                            ReleaseValue.indicator_id == indicator.id,
                            ReleaseValue.data_mode == "observed",
                        )
                        .order_by(ReleaseValue.captured_at.desc())
                    )
                ).all()
                official_by_kind: dict[str, ReleaseValue] = {}
                for official_value_row in official_rows:
                    if official_value_row.metadata_json.get("superseded"):
                        continue
                    official_by_kind.setdefault(official_value_row.value_kind, official_value_row)
                official_provider = (
                    "federal_reserve_fomc" if release.release_type == "FOMC" else "bls_official"
                )
                actual_row = official_by_kind.get("actual")
                official_artifact_id = (
                    actual_row.source_artifact_id
                    if actual_row and actual_row.source_artifact_id
                    else release.source_artifact_id
                )
                reconciliation_inputs.append(
                    _TeComparison(
                        subject_type="macro_release",
                        subject_id=str(release.id),
                        field_name=f"{indicator_key}.release_time",
                        authoritative_provider_key=official_provider,
                        authoritative_value=Decimal(
                            str(
                                int(_aware(release.released_at or release.scheduled_at).timestamp())
                            )
                        ),
                        comparison_value=Decimal(str(int(_aware(snapshot.release_at).timestamp()))),
                        unit="unix_seconds",
                        tolerance=Decimal("60"),
                        authoritative_artifact_id=release.source_artifact_id,
                    )
                )
                for value_kind, comparison_value in (
                    ("actual", snapshot.actual),
                    ("previous", snapshot.previous),
                    ("revised_previous", snapshot.revised),
                ):
                    official = official_by_kind.get(value_kind)
                    reconciliation_inputs.append(
                        _TeComparison(
                            subject_type=("release_value" if official else "macro_release"),
                            subject_id=str(official.id if official else release.id),
                            field_name=(
                                value_kind if official else f"{indicator_key}.{value_kind}"
                            ),
                            authoritative_provider_key=official_provider,
                            authoritative_value=official.value if official else None,
                            comparison_value=comparison_value,
                            unit=indicator.unit,
                            tolerance=Decimal("0"),
                            authoritative_artifact_id=(
                                official.source_artifact_id
                                if official and official.source_artifact_id
                                else official_artifact_id
                            ),
                        )
                    )
                reference_value = (
                    str(actual_row.metadata_json.get("reference_period"))
                    if actual_row and actual_row.metadata_json.get("reference_period")
                    else release.period_label
                )
                reconciliation_inputs.extend(
                    (
                        _TeComparison(
                            subject_type="macro_release",
                            subject_id=str(release.id),
                            field_name=f"{indicator_key}.unit",
                            authoritative_provider_key=official_provider,
                            authoritative_value=_normalize_unit(indicator.unit),
                            comparison_value=_normalize_unit(snapshot.unit),
                            unit="normalized_unit",
                            tolerance=Decimal("0"),
                            authoritative_artifact_id=official_artifact_id,
                        ),
                        _TeComparison(
                            subject_type="macro_release",
                            subject_id=str(release.id),
                            field_name=f"{indicator_key}.reference_period",
                            authoritative_provider_key=official_provider,
                            authoritative_value=_normalize_reference(reference_value),
                            comparison_value=_normalize_reference(snapshot.reference),
                            unit="normalized_reference_period",
                            tolerance=Decimal("0"),
                            authoritative_artifact_id=official_artifact_id,
                        ),
                    )
                )
        reconciliation_statuses: dict[str, int] = {}
        for comparison in reconciliation_inputs:
            reconciliation_row = await reconcile_values(
                engine,
                subject_type=comparison.subject_type,
                subject_id=comparison.subject_id,
                field_name=comparison.field_name,
                authoritative_provider_key=comparison.authoritative_provider_key,
                comparison_provider_key=provider.key,
                authoritative_value=comparison.authoritative_value,
                comparison_value=comparison.comparison_value,
                unit=comparison.unit,
                tolerance=comparison.tolerance,
                authoritative_artifact_id=comparison.authoritative_artifact_id,
                comparison_artifact_id=artifact.id,
                data_mode="observed",
            )
            reconciliation_statuses[reconciliation_row.status] = (
                reconciliation_statuses.get(reconciliation_row.status, 0) + 1
            )
            reconciled += 1
        mismatch_count = reconciliation_statuses.get("mismatch", 0)
        effective_quality_grade = quality.quality_grade
        if mismatch_count:
            effective_quality_grade = _lower_quality_grade(quality.quality_grade)
            quality_note = (
                f"Official cross-check found {mismatch_count} mismatched field(s); "
                f"TE quality downgraded to {effective_quality_grade}."
            )
            warnings.append(quality_note)
            factory = _factory(engine)
            async with factory() as session, session.begin():
                quality_row = await session.get(DataQualityRecord, quality.id)
                if quality_row is not None:
                    quality_row.quality_grade = effective_quality_grade
                    quality_row.metadata_json = {
                        **quality_row.metadata_json,
                        "official_reconciliation_statuses": reconciliation_statuses,
                        "official_reconciliation_artifact_id": str(artifact.id),
                    }
                    existing_note = quality_row.verification_notes or ""
                    if quality_note not in existing_note:
                        quality_row.verification_notes = " ".join(
                            part for part in (existing_note, quality_note) if part
                        )
                consensus_rows = (
                    await session.scalars(
                        select(ConsensusSnapshot).where(
                            ConsensusSnapshot.source_artifact_id == artifact.id,
                            ConsensusSnapshot.data_mode == "observed",
                        )
                    )
                ).all()
                for consensus_row in consensus_rows:
                    consensus_row.quality_grade = effective_quality_grade
                    note = consensus_row.verification_notes or ""
                    if quality_note not in note:
                        consensus_row.verification_notes = " ".join(
                            part for part in (note, quality_note) if part
                        )
        await complete_provider_run(
            engine,
            run.id,
            records_read=len(batch.snapshots),
            records_written=written,
            request_count=1,
            output_data={
                "calendar_rows": len(batch.snapshots),
                "consensus_rows": written,
                "reconciled_rows": reconciled,
                "reconciliation_statuses": reconciliation_statuses,
                "unmapped_rows": skipped,
                "te_forecast_used_as_consensus": False,
            },
            warnings=warnings,
            source_artifact_id=artifact.id,
            quality_grade=effective_quality_grade,
        )
        return {
            "status": "completed",
            "provider": provider.key,
            "provider_run_id": str(run.id),
            "source_artifact_id": str(artifact.id),
            "records_read": len(batch.snapshots),
            "records_written": written,
            "reconciled": reconciled,
            "reconciliation_statuses": reconciliation_statuses,
            "quality_grade": effective_quality_grade,
            "skipped": skipped,
            "warnings": warnings,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


async def snapshot_trading_economics_consensus(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    pit_at: datetime | None = None,
) -> dict[str, object]:
    """Serialize licensed quota checks and capture within the local process."""

    async with _TE_SYNC_LOCK:
        return await _snapshot_trading_economics_consensus(
            engine,
            settings,
            start_date=start_date,
            end_date=end_date,
            pit_at=pit_at,
        )


async def capture_trading_economics_browser_consensus(
    engine: AsyncEngine,
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    rows: list[dict[str, Any]],
    pages: tuple[TradingEconomicsBrowserPage, ...],
) -> dict[str, object]:
    """Persist a browser-captured TE consensus snapshot without API claims."""

    provider = TradingEconomicsConsensusProvider(None)
    batch = provider.adapt_browser_calendar(rows, pages=pages)
    return await _snapshot_trading_economics_consensus(
        engine,
        settings,
        start_date=start_date,
        end_date=end_date,
        captured_batch=batch,
    )


async def sync_databento_release_market(
    engine: AsyncEngine,
    settings: Settings,
    *,
    release_id: uuid.UUID,
    roots: tuple[str, ...] = tuple(_ROOT_TO_INSTRUMENT_KEY),
    include_daily: bool = True,
    available_until: datetime | None = None,
    budget_limit_usd: Decimal | None = None,
) -> dict[str, object]:
    clients = build_provider_clients(settings)
    provider = clients.databento
    request_cutoff = _aware(available_until or datetime.now(UTC)).replace(
        second=0,
        microsecond=0,
    )
    run = await record_provider_run(
        engine,
        provider_key=provider.key,
        operation="sync_event_market",
        idempotency_key=(
            f"databento-market:{release_id}:{','.join(sorted(roots))}:"
            f"{settings.market_intraday_pre_minutes}:{settings.market_intraday_post_minutes}:"
            f"{include_daily}:{request_cutoff.isoformat()}:{uuid.uuid4()}"
        ),
        input_data={
            "release_id": str(release_id),
            "roots": list(roots),
            "available_until": request_cutoff,
        },
        terms_url=provider.terms.terms_url,
    )
    warnings: list[str] = []
    try:
        factory = _factory(engine)
        async with factory() as session:
            release = await session.get(MacroRelease, release_id)
            if release is None:
                raise LookupError("macro release not found")
            if release.data_mode != "observed":
                raise ValueError("Databento can only be attached to observed releases")
            stage = await session.scalar(
                select(ReleaseStage)
                .where(ReleaseStage.macro_release_id == release.id)
                .order_by(ReleaseStage.sequence)
                .limit(1)
            )
            instruments = {
                row.canonical_key: row
                for row in (
                    await session.scalars(
                        select(MarketInstrument).where(
                            MarketInstrument.canonical_key.in_(
                                [_ROOT_TO_INSTRUMENT_KEY[root] for root in roots]
                            )
                        )
                    )
                ).all()
            }
        t0 = _aware(release.released_at or release.scheduled_at)
        schemas = ["ohlcv-1m"]
        if include_daily:
            schemas.append("ohlcv-1d")
        total_read = total_written = request_count = 0
        estimated_cost = Decimal("0")
        primary_artifact_id: uuid.UUID | None = None
        manifest_ids: list[str] = []

        # Quote the complete batch before contract resolution or the first paid
        # timeseries request. A per-request gate alone can let a nine-asset job
        # exceed its user-approved total budget one small request at a time.
        download_plans: dict[tuple[str, str], _MarketDownloadPlan] = {}
        for root in roots:
            instrument = instruments.get(_ROOT_TO_INSTRUMENT_KEY[root])
            if instrument is None:
                warnings.append(f"{root}: instrument catalog entry missing")
                continue
            for schema_name in schemas:
                if schema_name == "ohlcv-1m":
                    base_start = t0 - timedelta(minutes=settings.market_intraday_pre_minutes)
                    base_end = min(
                        t0 + timedelta(minutes=settings.market_intraday_post_minutes),
                        request_cutoff,
                    )
                    interval = 60
                else:
                    base_start = t0 - timedelta(days=settings.market_daily_pre_days + 3)
                    base_end = min(
                        t0 + timedelta(days=settings.market_daily_post_days + 7),
                        request_cutoff,
                    )
                    interval = 86_400
                if base_end <= base_start:
                    warnings.append(
                        f"{root} {schema_name}: no completed provider window is available yet"
                    )
                    continue
                factory = _factory(engine)
                async with factory() as session:
                    coverage = list(
                        (
                            await session.scalars(
                                select(MarketDataManifest).where(
                                    MarketDataManifest.macro_release_id == release.id,
                                    MarketDataManifest.instrument_id == instrument.id,
                                    MarketDataManifest.provider_key == provider.key,
                                    MarketDataManifest.schema_name == schema_name,
                                    MarketDataManifest.interval_seconds == interval,
                                    MarketDataManifest.data_mode == "observed",
                                    MarketDataManifest.row_count > 0,
                                )
                            )
                        ).all()
                    )
                    coverage_end, coverage_chain = _continuous_manifest_prefix(
                        coverage,
                        start=base_start,
                    )
                    if coverage_end is not None and coverage_end >= base_end:
                        manifest_ids.extend(str(item.id) for item in coverage_chain)
                        warnings.append(
                            f"{root} {schema_name}: existing manifests cover the request; "
                            "paid redownload skipped"
                        )
                        continue
                    start = base_start
                    if coverage_end is not None and base_start < coverage_end < base_end:
                        # Keep one overlapping bar for continuity validation;
                        # provider-level dedupe prevents rewriting it.
                        start = max(
                            base_start,
                            coverage_end - timedelta(seconds=interval),
                        )
                    end = base_end
                request = DatabentoDownloadRequest.model_validate(
                    {
                        "symbols": (root,),
                        "start": start,
                        "end": end,
                        "schema": schema_name,
                        "event_count": 1,
                        # Contract resolution deliberately happens only after the
                        # aggregate paid-cost gate. Until then, no existing bar
                        # from another contract may discount the quote.
                        "known_record_count": 0,
                    }
                )
                estimate = await provider.estimate_download(request)
                request_count += 1
                estimated_cost += estimate.estimated_cost_usd
                download_plans[(root, schema_name)] = _MarketDownloadPlan(
                    root=root,
                    instrument=instrument,
                    schema_name=schema_name,
                    start=start,
                    end=end,
                    interval_seconds=interval,
                    estimate=estimate,
                )

        if download_plans and settings.databento_api_key is None:
            await upsert_entitlement(
                engine,
                provider_key=provider.key,
                capability="historical_market_data",
                status="not_configured",
                provider_run_id=run.id,
                error_code=ProviderErrorCode.NOT_CONFIGURED.value,
                terms_url=provider.terms.terms_url,
            )
            raise ProviderError(
                provider.key,
                ProviderErrorCode.NOT_CONFIGURED,
                "Databento API key is not configured",
            )
        if download_plans and not settings.allow_paid_download:
            raise ProviderError(
                provider.key,
                ProviderErrorCode.PAID_DOWNLOAD_DISABLED,
                "Databento paid download is disabled; review the aggregate quote first",
                details={"aggregate_estimated_cost_usd": str(estimated_cost)},
            )
        if download_plans and estimated_cost > settings.databento_max_estimated_cost_usd:
            raise ProviderBudgetError(
                provider.key,
                "Databento aggregate estimated cost exceeds the configured job budget",
                estimated_cost_usd=str(estimated_cost),
                budget_usd=str(settings.databento_max_estimated_cost_usd),
            )
        effective_budget = min(
            settings.databento_max_estimated_cost_usd,
            budget_limit_usd
            if budget_limit_usd is not None
            else settings.databento_max_estimated_cost_usd,
        )
        if download_plans and estimated_cost > effective_budget:
            raise ProviderBudgetError(
                provider.key,
                "Databento aggregate estimate exceeds the remaining operation budget",
                estimated_cost_usd=str(estimated_cost),
                budget_usd=str(effective_budget),
            )
        untrusted_quotes = [
            plan
            for plan in download_plans.values()
            if plan.estimate.source != "provider_metadata"
            or plan.estimate.confidence != "high"
            or plan.estimate.provider_quoted_at is None
        ]
        if untrusted_quotes:
            raise ProviderError(
                provider.key,
                ProviderErrorCode.COST_ESTIMATE_UNAVAILABLE,
                "Databento paid download requires fresh provider metadata quotes for every slice",
                details={"untrusted_quote_count": len(untrusted_quotes)},
            )

        for root in roots:
            instrument = instruments.get(_ROOT_TO_INSTRUMENT_KEY[root])
            if instrument is None:
                continue
            if not any(plan_root == root for plan_root, _schema in download_plans):
                continue
            resolution = await provider.resolve_contract_online(root, event_at=t0)
            request_count += 1
            symbology_artifact = await persist_provider_artifact(
                engine,
                resolution.artifact,
                provider_run_id=run.id,
                title=f"Databento {root} contract resolution at {t0.isoformat()}",
            )
            primary_artifact_id = primary_artifact_id or symbology_artifact.id
            contract = resolution.contract
            factory = _factory(engine)
            async with factory() as session, session.begin():
                contract_row = await session.scalar(
                    select(FuturesContract).where(
                        FuturesContract.instrument_id == instrument.id,
                        FuturesContract.contract_code == contract.raw_symbol,
                    )
                )
                if contract_row is None:
                    contract_row = FuturesContract(
                        id=uuid.uuid4(),
                        instrument_id=instrument.id,
                        contract_code=contract.raw_symbol,
                        provider_symbol=contract.raw_symbol,
                        first_trade_date=(
                            contract.activation.date() if contract.activation else None
                        ),
                        last_trade_date=contract.last_trade,
                        expiry_date=contract.expiry.date() if contract.expiry else None,
                        roll_start_at=None,
                        roll_end_at=None,
                        is_proxy=instrument.is_proxy,
                        metadata_json={
                            "provider_instrument_id": contract.instrument_id,
                            "first_notice": (
                                contract.first_notice.isoformat() if contract.first_notice else None
                            ),
                            "continuous_symbol": contract.continuous_symbol,
                            "continuous_rule": contract.continuous_rule,
                            "resolution_artifact_id": str(symbology_artifact.id),
                        },
                    )
                    session.add(contract_row)
                    await session.flush()
                contract_row_id = contract_row.id
            for schema_name in schemas:
                plan = download_plans.get((root, schema_name))
                if plan is None:
                    continue
                start = plan.start
                end = plan.end
                interval = plan.interval_seconds
                estimate = plan.estimate
                provider.assert_download_allowed(estimate)
                factory = _factory(engine)
                async with factory() as session:
                    existing_rows = (
                        await session.scalars(
                            select(MarketBar).where(
                                MarketBar.instrument_id == instrument.id,
                                MarketBar.provider_key == provider.key,
                                MarketBar.data_mode == "observed",
                                MarketBar.interval_seconds == interval,
                                MarketBar.contract_code == contract.raw_symbol,
                                MarketBar.timestamp >= start,
                                MarketBar.timestamp <= end,
                            )
                        )
                    ).all()
                existing_keys = {
                    (instrument.canonical_key, _aware(row.timestamp), row.interval_seconds)
                    for row in existing_rows
                }
                batch = await provider.fetch_bars(
                    BarQuery(
                        instrument=MarketInstrumentRef(
                            canonical_key=instrument.canonical_key,
                            symbol=instrument.symbol,
                            title=instrument.title,
                            exchange=instrument.exchange,
                            quote_unit=instrument.quote_unit,
                            is_proxy=instrument.is_proxy,
                            proxy_for=instrument.proxy_for,
                        ),
                        start=start,
                        end=end,
                        interval_seconds=interval,
                    ),
                    contract=contract,
                    estimate=estimate,
                    existing_keys=existing_keys,
                )
                request_count += 1
                total_read += batch.dedupe.input_records
                artifact = await persist_provider_artifact(
                    engine,
                    batch.artifact,
                    provider_run_id=run.id,
                    title=f"Databento {contract.raw_symbol} {schema_name}",
                )
                primary_artifact_id = primary_artifact_id or artifact.id
                quality = await persist_quality_record(
                    engine,
                    batch.quality,
                    subject_type="market_bar_batch",
                    subject_id=f"{release_id}:{instrument.canonical_key}:{schema_name}",
                    identity=f"quality:databento:{batch.dataset_manifest_hash}",
                )
                factory = _factory(engine)
                async with factory() as session, session.begin():
                    for bar in batch.bars:
                        session.add(
                            MarketBar(
                                instrument_id=instrument.id,
                                futures_contract_id=contract_row_id,
                                timestamp=bar.timestamp,
                                interval_seconds=bar.interval_seconds,
                                open_value=bar.open_value,
                                high_value=bar.high_value,
                                low_value=bar.low_value,
                                close_value=bar.close_value,
                                volume=bar.volume,
                                provider_key=provider.key,
                                data_mode="observed",
                                source_symbol=bar.source_symbol,
                                contract_code=bar.contract_code or contract.raw_symbol,
                                is_regular_session=None,
                                quality_id=quality.id,
                                fetched_at=batch.fetched_at,
                                metadata_json=bar.metadata,
                            )
                        )
                        total_written += 1
                manifest = await record_market_data_manifest(
                    engine,
                    macro_release_id=release.id,
                    release_stage_id=stage.id if stage else None,
                    provider_key=provider.key,
                    dataset=batch.dataset,
                    schema_name=batch.schema_name,
                    instrument_id=instrument.id,
                    futures_contract_id=contract_row_id,
                    source_symbol=contract.continuous_symbol,
                    contract_code=contract.raw_symbol,
                    start_at=start,
                    end_at=end,
                    interval_seconds=interval,
                    row_count=len(batch.bars),
                    size_bytes=batch.artifact.byte_length,
                    source_content_hash=batch.artifact.content_hash,
                    data_mode="observed",
                    quality_grade=quality.quality_grade,
                    contract_selection_rule=(
                        f"continuous {contract.continuous_rule} rank 0 resolved at T0"
                    ),
                    continuous_resolution={
                        "continuous_symbol": contract.continuous_symbol,
                        "raw_symbol": contract.raw_symbol,
                        "instrument_id": contract.instrument_id,
                        "activation": contract.activation,
                        "expiry": contract.expiry,
                    },
                    roll_status=contract.roll_state,
                    estimated_cost_usd=estimate.estimated_cost_usd,
                    provider_run_id=run.id,
                    source_artifact_id=artifact.id,
                    metadata={
                        "daily_boundary": "UTC" if interval == 86_400 else None,
                        "no_cross_contract_splice": True,
                    },
                )
                manifest_ids.append(str(manifest.id))
                expected = expected_tradable_bars(
                    start,
                    end,
                    interval,
                    instrument.canonical_key,
                )
                ohlc_valid = all(
                    bar.low_value
                    <= min(bar.open_value, bar.close_value)
                    <= max(bar.open_value, bar.close_value)
                    <= bar.high_value
                    for bar in batch.bars
                )
                contract_dates_known = (
                    contract.activation is not None and contract.expiry is not None
                )
                checks: dict[str, bool | int | float | str | None] = {
                    "contract_dates_known": contract_dates_known,
                    "contract_active_at_t0": (
                        contract.activation is not None
                        and contract.expiry is not None
                        and contract.activation <= t0
                        and t0 < contract.expiry
                    ),
                    "ohlc_valid": ohlc_valid,
                    "duplicate_free": batch.dedupe.duplicate_payload_records == 0,
                    "timezone_utc": all(
                        bar.timestamp.utcoffset() == timedelta(0) for bar in batch.bars
                    ),
                    "expected_tradable_bars_lite_calendar": expected,
                    "coverage_ratio": round(len(batch.bars) / max(1, expected), 4),
                    "large_gap_absent": (
                        len(batch.bars) >= max(1, int(expected * 0.8)) if interval == 60 else None
                    ),
                    "session_close_semantics_supported": (True if interval == 60 else None),
                }
                await record_market_reconciliation(
                    engine,
                    subject_id=str(manifest.id),
                    provider_key=provider.key,
                    checks=checks,
                    source_artifact_id=artifact.id,
                    data_mode="observed",
                )
                warnings.extend(batch.warnings)
        await upsert_entitlement(
            engine,
            provider_key=provider.key,
            capability="historical_market_data",
            status="granted" if settings.databento_api_key is not None else "not_configured",
            provider_run_id=run.id,
            source_artifact_id=primary_artifact_id,
            error_code=(
                None
                if settings.databento_api_key is not None
                else ProviderErrorCode.NOT_CONFIGURED.value
            ),
            terms_url=provider.terms.terms_url,
        )
        await complete_provider_run(
            engine,
            run.id,
            records_read=total_read,
            records_written=total_written,
            request_count=request_count,
            output_data={
                "manifest_ids": list(dict.fromkeys(manifest_ids)),
                "cache_only": not bool(download_plans),
            },
            warnings=warnings,
            source_artifact_id=primary_artifact_id,
            quality_grade="A" if total_written else "C",
            estimated_cost_usd=estimated_cost,
            actual_cost_usd=None,
        )
        return {
            "status": "completed",
            "provider": provider.key,
            "provider_run_id": str(run.id),
            "source_artifact_id": (
                str(primary_artifact_id) if primary_artifact_id is not None else None
            ),
            "records_read": total_read,
            "records_written": total_written,
            "estimated_cost_usd": str(estimated_cost),
            "manifest_ids": list(dict.fromkeys(manifest_ids)),
            "cache_only": not bool(download_plans),
            "warnings": warnings,
        }
    except Exception as exc:
        await fail_provider_run(engine, run.id, error=exc, warnings=warnings)
        raise


__all__ = [
    "capture_trading_economics_browser_consensus",
    "snapshot_trading_economics_consensus",
    "sync_databento_release_market",
]
