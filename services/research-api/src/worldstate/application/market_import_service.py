"""Traceable market-bar import commands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.db.models import (
    DataQualityRecord,
    MacroRelease,
    MarketBar,
    MarketInstrument,
    ProviderRun,
    ReleaseStage,
)
from worldstate.provider_kit import BarQuery, CsvMarketBarProvider, MarketInstrumentRef


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
) -> dict[str, object]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        release = await session.get(MacroRelease, uuid.UUID(release_id))
        if release is None:
            raise LookupError("macro release not found")
        instrument = await session.scalar(
            select(MarketInstrument).where(MarketInstrument.canonical_key == instrument_key)
        )
        if instrument is None:
            raise LookupError("market instrument not found")
        stages = (
            await session.scalars(
                select(ReleaseStage).where(ReleaseStage.macro_release_id == release.id)
            )
        ).all()
        start = min(_aware(item.scheduled_at) for item in stages) - timedelta(minutes=60)
        end = max(_aware(item.scheduled_at) for item in stages) + timedelta(days=7)
        provider = CsvMarketBarProvider(
            csv_text,
            provider_key=provider_key,
            source_name=source_name,
            source_url=source_url,
            verified=verified,
            is_fixture=is_fixture,
        )
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
                operation="csv_market_bar_import",
                status="completed",
                started_at=batch.fetched_at,
                completed_at=datetime.now(UTC),
                records_read=len(batch.bars),
                records_written=inserted + updated,
                source_artifact_id=None,
                quality_grade=quality.quality_grade,
                input_json={"release_id": release_id, "instrument_key": instrument_key},
                output_json={"inserted": inserted, "updated": updated},
                warnings_json=batch.warnings,
                error_message=None,
            )
        )
        return {
            "release_id": release_id,
            "instrument_key": instrument_key,
            "inserted": inserted,
            "updated": updated,
            "quality_grade": quality.quality_grade,
            "warnings": batch.warnings,
        }


__all__ = ["import_market_csv"]
