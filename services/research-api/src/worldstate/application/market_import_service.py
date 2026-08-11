"""Traceable market-bar import commands."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.event_intraday_service import preview_event_minute_csv
from worldstate.db.models import (
    DataQualityRecord,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    MarketInstrument,
    ProviderRun,
    ReleaseStage,
)
from worldstate.provider_kit import (
    BarQuery,
    CsvMarketBarProvider,
    MarketBarRecord,
    MarketInstrumentRef,
)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _instrument_ref(instrument: MarketInstrument) -> MarketInstrumentRef:
    return MarketInstrumentRef(
        canonical_key=instrument.canonical_key,
        symbol=instrument.symbol,
        title=instrument.title,
        exchange=instrument.exchange,
        quote_unit=instrument.quote_unit,
        is_proxy=instrument.is_proxy,
        proxy_for=instrument.proxy_for,
    )


async def import_market_csv(
    engine: AsyncEngine,
    *,
    release_id: str,
    instrument_key: str,
    csv_text: str,
    provider_key: str,
    source_name: str,
    source_url: str | None,
    verified: bool,
    is_fixture: bool,
    timezone_name: str = "UTC",
    column_mapping: dict[str, str] | None = None,
) -> dict[str, object]:
    """Import minute bars bounded to a release's declared event window."""
    preview = await preview_event_minute_csv(
        engine,
        release_id=release_id,
        instrument_key=instrument_key,
        csv_text=csv_text,
        timezone_name=timezone_name,
        column_mapping=column_mapping,
        verified=verified,
        is_fixture=is_fixture,
    )
    normalized_csv = str(preview["normalized_csv"])
    eligibility = dict(preview["eligibility"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        release = await session.get(MacroRelease, uuid.UUID(release_id))
        if release is None:
            raise LookupError("macro release not found")
        requested_mode = "fixture" if is_fixture else "observed"
        if requested_mode != release.data_mode:
            raise ValueError(
                f"market import data mode must match the target release ({release.data_mode})"
            )
        instrument = await session.scalar(
            select(MarketInstrument).where(MarketInstrument.canonical_key == instrument_key)
        )
        if instrument is None:
            raise LookupError("market instrument not found")
        content_hash = hashlib.sha256(normalized_csv.encode()).hexdigest()
        idempotency_key = (
            f"csv:{release_id}:{instrument_key}:{provider_key}:{requested_mode}:{content_hash}"
        )
        previous_run = await session.scalar(
            select(ProviderRun).where(
                ProviderRun.provider_key == provider_key,
                ProviderRun.operation == "csv_market_bar_import",
                ProviderRun.idempotency_key == idempotency_key,
            )
        )
        if previous_run is not None and previous_run.status == "completed":
            return {
                "release_id": release_id,
                "instrument_key": instrument_key,
                "inserted": 0,
                "updated": 0,
                "quality_grade": previous_run.quality_grade,
                "warnings": ["identical import already completed; no rows were rewritten"],
                "idempotent_replay": True,
                "eligibility": eligibility,
            }
        stages = (
            await session.scalars(
                select(ReleaseStage).where(ReleaseStage.macro_release_id == release.id)
            )
        ).all()
        if not stages:
            raise ValueError("release has no stages")
        start = min(_aware(item.scheduled_at) for item in stages) - timedelta(minutes=60)
        end = max(_aware(item.scheduled_at) for item in stages) + timedelta(days=7)
        provider = CsvMarketBarProvider(
            normalized_csv,
            provider_key=provider_key,
            source_name=source_name,
            source_url=source_url,
            verified=verified,
            is_fixture=is_fixture,
        )
        batch = await provider.fetch_bars(
            BarQuery(
                instrument=_instrument_ref(instrument),
                start=start,
                end=end,
                interval_seconds=60,
            )
        )
        quality = DataQualityRecord(
            id=uuid.uuid4(),
            subject_type="market_bar_batch",
            subject_id=str(release.id),
            source_name=batch.quality.source_name,
            source_url=batch.quality.source_url,
            source_type=batch.quality.source_type,
            acquired_at=batch.quality.acquired_at,
            is_manual=batch.quality.is_manual,
            is_verified=batch.quality.is_verified,
            is_fixture=batch.quality.is_fixture,
            is_proxy=batch.quality.is_proxy,
            latency_seconds=batch.quality.latency_seconds,
            granularity_seconds=batch.quality.granularity_seconds,
            missing_reason=batch.quality.missing_reason,
            quality_grade=batch.quality.quality_grade.value,
            verification_notes=batch.quality.verification_notes,
            metadata_json=batch.quality.metadata,
        )
        session.add(quality)
        existing = {
            (_aware(row.timestamp), row.contract_code): row
            for row in (
                await session.scalars(
                    select(MarketBar).where(
                        MarketBar.instrument_id == instrument.id,
                        MarketBar.provider_key == provider_key,
                        MarketBar.data_mode == requested_mode,
                        MarketBar.timestamp >= start,
                        MarketBar.timestamp <= end,
                    )
                )
            ).all()
        }
        inserted = updated = 0
        for item in batch.bars:
            contract_code = item.contract_code or ""
            row = existing.get((_aware(item.timestamp), contract_code))
            values = {
                "interval_seconds": item.interval_seconds,
                "open_value": item.open_value,
                "high_value": item.high_value,
                "low_value": item.low_value,
                "close_value": item.close_value,
                "volume": item.volume,
                "source_symbol": item.source_symbol,
                "contract_code": contract_code,
                "quality_id": quality.id,
                "fetched_at": batch.fetched_at,
                "metadata_json": item.metadata,
            }
            if row is None:
                session.add(
                    MarketBar(
                        instrument_id=instrument.id,
                        futures_contract_id=None,
                        timestamp=item.timestamp,
                        provider_key=provider_key,
                        data_mode=requested_mode,
                        is_regular_session=None,
                        **values,
                    )
                )
                inserted += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1
        provider_run_id = uuid.uuid4()
        provider_run = ProviderRun(
            id=provider_run_id,
            provider_key=provider_key,
            operation="csv_market_bar_import",
            status="completed",
            started_at=batch.fetched_at,
            completed_at=datetime.now(UTC),
            records_read=len(batch.bars),
            records_written=inserted + updated,
            source_artifact_id=None,
            data_mode=requested_mode,
            idempotency_key=idempotency_key,
            request_count=0,
            estimated_cost_usd=0,
            actual_cost_usd=0,
            terms_url=None,
            quality_grade=quality.quality_grade,
            input_json={
                "release_id": release_id,
                "instrument_key": instrument_key,
                "content_hash": content_hash,
            },
            output_json={"inserted": inserted, "updated": updated},
            warnings_json=batch.warnings,
            error_message=None,
        )
        session.add(provider_run)
        await session.flush()
        manifest_ids: list[str] = []
        bars_by_contract: dict[str, list[MarketBarRecord]] = {}
        for item in batch.bars:
            bars_by_contract.setdefault(item.contract_code or "", []).append(item)
        for contract_code, contract_bars in sorted(bars_by_contract.items()):
            first = contract_bars[0]
            manifest_hash = hashlib.sha256(
                f"csv-manifest:{release.id}:{instrument.id}:{provider_key}:{contract_code}:{content_hash}".encode()
            ).hexdigest()
            existing_manifest = await session.scalar(
                select(MarketDataManifest).where(MarketDataManifest.manifest_hash == manifest_hash)
            )
            if existing_manifest is not None:
                manifest_ids.append(str(existing_manifest.id))
                continue
            manifest = MarketDataManifest(
                id=uuid.uuid4(),
                manifest_hash=manifest_hash,
                macro_release_id=release.id,
                release_stage_id=stages[0].id,
                provider_key=provider_key,
                dataset="CSV.EVENT_IMPORT",
                schema_name="ohlcv-1m",
                instrument_id=instrument.id,
                futures_contract_id=None,
                source_symbol=first.source_symbol,
                contract_code=contract_code or None,
                start_at=min(item.timestamp for item in contract_bars),
                end_at=max(item.timestamp for item in contract_bars),
                interval_seconds=60,
                row_count=len(contract_bars),
                size_bytes=len(normalized_csv.encode()),
                data_mode=requested_mode,
                quality_grade=quality.quality_grade,
                is_aggregated=False,
                aggregation_method=None,
                aggregation_version=None,
                contract_selection_rule="explicit CSV event import contract column",
                continuous_resolution_json={},
                roll_status="manual_import",
                estimated_cost_usd=0,
                actual_cost_usd=0,
                provider_run_id=provider_run_id,
                sync_job_run_id=None,
                source_artifact_id=None,
                metadata_json={
                    "source_content_hash": content_hash,
                    "no_cross_contract_splice": True,
                    "verified": verified,
                    "fixture": is_fixture,
                    "is_fixture": is_fixture,
                    "event_intraday_eligibility": eligibility["status"],
                    "event_intraday_eligibility_v1": eligibility,
                    "source_timezone": timezone_name,
                },
            )
            session.add(manifest)
            await session.flush()
            manifest_ids.append(str(manifest.id))
        provider_run.output_json = {
            "inserted": inserted,
            "updated": updated,
            "manifest_ids": manifest_ids,
            "eligibility": eligibility,
        }
        return {
            "release_id": release_id,
            "instrument_key": instrument_key,
            "inserted": inserted,
            "updated": updated,
            "quality_grade": quality.quality_grade,
            "warnings": batch.warnings,
            "idempotent_replay": False,
            "manifest_ids": manifest_ids,
            "eligibility": eligibility,
        }


async def import_observed_market_csv(
    engine: AsyncEngine,
    *,
    instrument_key: str,
    csv_text: str,
    provider_key: str,
    source_name: str,
    source_url: str | None,
    verified: bool,
    interval_seconds: int = 86400,
) -> dict[str, object]:
    """Import observed context bars without attaching them to an event."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    content_hash = hashlib.sha256(csv_text.encode()).hexdigest()
    idempotency_key = (
        f"csv-context:{instrument_key}:{provider_key}:{interval_seconds}:{content_hash}"
    )
    async with factory() as session, session.begin():
        instrument = await session.scalar(
            select(MarketInstrument).where(MarketInstrument.canonical_key == instrument_key)
        )
        if instrument is None:
            raise LookupError("market instrument not found")
        previous_run = await session.scalar(
            select(ProviderRun).where(
                ProviderRun.provider_key == provider_key,
                ProviderRun.operation == "csv_market_context_import",
                ProviderRun.idempotency_key == idempotency_key,
            )
        )
        if previous_run is not None and previous_run.status == "completed":
            return {
                "instrument_key": instrument_key,
                "inserted": 0,
                "updated": 0,
                "quality_grade": previous_run.quality_grade,
                "idempotent_replay": True,
                "data_mode": "observed",
                "context_only": True,
            }
        provider = CsvMarketBarProvider(
            csv_text,
            provider_key=provider_key,
            source_name=source_name,
            source_url=source_url,
            verified=verified,
            is_fixture=False,
            verification_notes="User supplied observed CSV; no provider-side PIT guarantee.",
        )
        batch = await provider.fetch_bars(
            BarQuery(
                instrument=_instrument_ref(instrument),
                start=datetime(1970, 1, 1, tzinfo=UTC),
                end=datetime(2100, 1, 1, tzinfo=UTC),
                interval_seconds=interval_seconds,
            )
        )
        quality = DataQualityRecord(
            id=uuid.uuid4(),
            subject_type="market_context_batch",
            subject_id=instrument_key,
            source_name=batch.quality.source_name,
            source_url=batch.quality.source_url,
            source_type=batch.quality.source_type,
            acquired_at=batch.quality.acquired_at,
            is_manual=True,
            is_verified=batch.quality.is_verified,
            is_fixture=False,
            is_proxy=batch.quality.is_proxy,
            latency_seconds=batch.quality.latency_seconds,
            granularity_seconds=batch.quality.granularity_seconds,
            missing_reason=batch.quality.missing_reason,
            quality_grade=batch.quality.quality_grade.value,
            verification_notes=batch.quality.verification_notes,
            metadata_json={
                **batch.quality.metadata,
                "source_content_hash": content_hash,
                "context_only": True,
                "not_event_window": True,
            },
        )
        session.add(quality)
        existing = {
            (_aware(row.timestamp), row.contract_code): row
            for row in (
                await session.scalars(
                    select(MarketBar).where(
                        MarketBar.instrument_id == instrument.id,
                        MarketBar.provider_key == provider_key,
                        MarketBar.data_mode == "observed",
                    )
                )
            ).all()
        }
        inserted = updated = 0
        for item in batch.bars:
            contract_code = item.contract_code or ""
            row = existing.get((_aware(item.timestamp), contract_code))
            values = {
                "interval_seconds": item.interval_seconds,
                "open_value": item.open_value,
                "high_value": item.high_value,
                "low_value": item.low_value,
                "close_value": item.close_value,
                "volume": item.volume,
                "source_symbol": item.source_symbol,
                "contract_code": contract_code,
                "quality_id": quality.id,
                "fetched_at": batch.fetched_at,
                "metadata_json": {
                    **item.metadata,
                    "context_only": True,
                    "not_event_window": True,
                    "source_content_hash": content_hash,
                },
            }
            if row is None:
                session.add(
                    MarketBar(
                        instrument_id=instrument.id,
                        futures_contract_id=None,
                        timestamp=item.timestamp,
                        provider_key=provider_key,
                        data_mode="observed",
                        is_regular_session=None,
                        **values,
                    )
                )
                inserted += 1
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                updated += 1
        session.add(
            ProviderRun(
                id=uuid.uuid4(),
                provider_key=provider_key,
                operation="csv_market_context_import",
                status="completed",
                started_at=batch.fetched_at,
                completed_at=datetime.now(UTC),
                records_read=len(batch.bars),
                records_written=inserted + updated,
                source_artifact_id=None,
                data_mode="observed",
                idempotency_key=idempotency_key,
                request_count=0,
                estimated_cost_usd=0,
                actual_cost_usd=0,
                terms_url=None,
                quality_grade=quality.quality_grade,
                input_json={
                    "instrument_key": instrument_key,
                    "interval_seconds": interval_seconds,
                    "content_hash": content_hash,
                    "context_only": True,
                },
                output_json={"inserted": inserted, "updated": updated},
                warnings_json=batch.warnings,
                error_message=None,
            )
        )
        return {
            "instrument_key": instrument_key,
            "inserted": inserted,
            "updated": updated,
            "quality_grade": quality.quality_grade,
            "warnings": batch.warnings,
            "idempotent_replay": False,
            "data_mode": "observed",
            "context_only": True,
            "not_event_window": True,
        }


__all__ = ["import_market_csv", "import_observed_market_csv"]
