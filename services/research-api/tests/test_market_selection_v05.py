from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.market_selection_service import select_release_market_data
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import (
    FuturesContract,
    MacroRelease,
    MarketBar,
    MarketDataManifest,
    MarketInstrument,
    ReleaseStage,
)
from worldstate.db.session import create_engine
from worldstate.event_engine.windows import calculate_session_close_windows
from worldstate.provider_kit import MarketBarRecord

T0 = datetime(2026, 1, 13, 13, 30, tzinfo=UTC)


@pytest.fixture
async def market_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'market-selection.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


def _manifest(
    *,
    release: MacroRelease,
    stage: ReleaseStage,
    instrument: MarketInstrument,
    contract: FuturesContract,
    suffix: str,
    start: datetime,
    end: datetime,
    row_count: int,
) -> MarketDataManifest:
    return MarketDataManifest(
        id=uuid.uuid4(),
        manifest_hash=(suffix * 64)[:64],
        macro_release_id=release.id,
        release_stage_id=stage.id,
        provider_key="databento",
        dataset="GLBX.MDP3",
        schema_name="ohlcv-1m",
        instrument_id=instrument.id,
        futures_contract_id=contract.id,
        source_symbol=f"{contract.contract_code}.c.0",
        contract_code=contract.contract_code,
        start_at=start,
        end_at=end,
        interval_seconds=60,
        row_count=row_count,
        size_bytes=None,
        data_mode="observed",
        quality_grade="A",
        is_aggregated=False,
        aggregation_method=None,
        aggregation_version=None,
        contract_selection_rule="continuous rank 0 resolved at T0",
        continuous_resolution_json={},
        roll_status="resolved",
        estimated_cost_usd=Decimal("0"),
        actual_cost_usd=Decimal("0"),
        provider_run_id=None,
        sync_job_run_id=None,
        source_artifact_id=None,
        metadata_json={
            "no_cross_contract_splice": True,
            "event_intraday_eligibility": "eligible",
            "is_fixture": False,
            "event_intraday_eligibility_v1": {
                "policy_version": "event-intraday-v1",
                "data_mode": "observed",
                "status": "eligible",
            },
        },
    )


def _market_bar(
    *,
    instrument: MarketInstrument,
    contract: FuturesContract | None,
    at: datetime,
    value: Decimal,
    provider: str = "databento",
    contract_code: str | None = None,
) -> MarketBar:
    code = contract_code if contract_code is not None else (
        contract.contract_code if contract else ""
    )
    return MarketBar(
        instrument_id=instrument.id,
        futures_contract_id=contract.id if contract else None,
        timestamp=at,
        interval_seconds=60,
        open_value=value,
        high_value=value + 1,
        low_value=value - 1,
        close_value=value,
        volume=Decimal("100"),
        provider_key=provider,
        data_mode="observed",
        source_symbol=code or "SPOT",
        contract_code=code,
        is_regular_session=True,
        quality_id=None,
        fetched_at=T0 + timedelta(days=1),
        metadata_json={},
    )


async def test_release_market_selection_never_mixes_provider_contract_or_manifest_overlap(
    market_engine: AsyncEngine,
) -> None:
    release = MacroRelease(
        id=uuid.uuid4(),
        release_key="selection-cpi",
        release_type="US_CPI",
        title="US CPI",
        country="USA",
        period_label="2025-12",
        scheduled_at=T0,
        released_at=T0,
        source_timezone="America/New_York",
        status="released",
        data_version="initial",
        data_mode="observed",
        source_artifact_id=None,
        primary_quality_id=None,
        contamination_level="none",
        clean_window=True,
        overlapping_events=[],
        confounding_notes=[],
        metadata_json={},
    )
    stage = ReleaseStage(
        id=uuid.uuid4(),
        macro_release_id=release.id,
        stage_key="release",
        title="Release",
        sequence=1,
        scheduled_at=T0,
        released_at=T0,
        status="released",
        source_artifact_id=None,
        metadata_json={},
    )
    instrument = MarketInstrument(
        id=uuid.uuid4(),
        canonical_key="gold_selection_test",
        symbol="GC",
        title="Gold",
        asset_class="commodity",
        instrument_type="futures",
        exchange="COMEX",
        quote_unit="USD",
        measurement_type="price",
        source_timezone="America/Chicago",
        is_proxy=False,
        proxy_for=None,
        active=True,
        metadata_json={},
    )
    contract_a = FuturesContract(
        id=uuid.uuid4(),
        instrument_id=instrument.id,
        contract_code="GCG6",
        provider_symbol="GCG6",
        first_trade_date=None,
        last_trade_date=None,
        expiry_date=None,
        roll_start_at=None,
        roll_end_at=None,
        is_proxy=False,
        metadata_json={},
    )
    contract_b = FuturesContract(
        id=uuid.uuid4(),
        instrument_id=instrument.id,
        contract_code="GCJ6",
        provider_symbol="GCJ6",
        first_trade_date=None,
        last_trade_date=None,
        expiry_date=None,
        roll_start_at=None,
        roll_end_at=None,
        is_proxy=False,
        metadata_json={},
    )
    times = [T0 + timedelta(minutes=value) for value in (-60, -30, 0, 5, 240)]
    primary = _manifest(
        release=release,
        stage=stage,
        instrument=instrument,
        contract=contract_a,
        suffix="a",
        start=times[0],
        end=times[-1],
        row_count=5,
    )
    overlap = _manifest(
        release=release,
        stage=stage,
        instrument=instrument,
        contract=contract_a,
        suffix="b",
        start=times[1],
        end=times[-1],
        row_count=4,
    )
    alternate_contract = _manifest(
        release=release,
        stage=stage,
        instrument=instrument,
        contract=contract_b,
        suffix="c",
        start=times[0],
        end=times[3],
        row_count=2,
    )
    factory = async_sessionmaker(market_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add_all(
            [
                release,
                stage,
                instrument,
                contract_a,
                contract_b,
                primary,
                overlap,
                alternate_contract,
                *[
                    _market_bar(
                        instrument=instrument,
                        contract=contract_a,
                        at=at,
                        value=Decimal("2000") + index,
                    )
                    for index, at in enumerate(times)
                ],
                _market_bar(
                    instrument=instrument,
                    contract=contract_b,
                    at=times[0],
                    value=Decimal("9000"),
                ),
                _market_bar(
                    instrument=instrument,
                    contract=contract_b,
                    at=times[3],
                    value=Decimal("9001"),
                ),
                *[
                    _market_bar(
                        instrument=instrument,
                        contract=contract_a,
                        at=at,
                        value=Decimal("7000") + index,
                        provider="unlinked_provider",
                    )
                    for index, at in enumerate(times)
                ],
            ]
        )

    async with factory() as session:
        persisted_release = await session.get(MacroRelease, release.id)
        persisted_stage = await session.get(ReleaseStage, stage.id)
        assert persisted_release is not None
        assert persisted_stage is not None
        selection = await select_release_market_data(
            session, persisted_release, [persisted_stage]
        )

    selected = selection.get(instrument.id, 60)
    assert selected is not None
    assert selected.provider_key == "databento"
    assert selected.futures_contract_id == contract_a.id
    assert selected.contract_code == "GCG6"
    assert set(selected.manifest_ids) == {primary.id, overlap.id}
    assert alternate_contract.id in selection.rejected_manifest_ids
    assert len(selected.bars) == 5
    assert len({bar.timestamp for bar in selected.bars}) == 5
    assert all(bar.provider_key == "databento" for bar in selected.bars)
    assert all(bar.futures_contract_id == contract_a.id for bar in selected.bars)
    assert max(bar.close_value for bar in selected.bars) < Decimal("3000")
    snapshot = selected.snapshot(instrument_key=instrument.canonical_key)
    manifest_snapshot = snapshot["manifests"]
    selected_bar_snapshot = snapshot["selected_bars"]
    assert isinstance(manifest_snapshot, list)
    assert isinstance(selected_bar_snapshot, list)
    assert len(manifest_snapshot) == 2
    assert len(selected_bar_snapshot) == 5


def _daily_bar(at: datetime, value: str) -> MarketBarRecord:
    resolved = Decimal(value)
    return MarketBarRecord(
        instrument_key="gold_gc",
        timestamp=at,
        interval_seconds=86_400,
        open_value=resolved,
        high_value=resolved + 1,
        low_value=resolved - 1,
        close_value=resolved,
        volume=Decimal("100"),
        source_symbol="GC.c.0",
        contract_code="GCG6",
        metadata={"daily_boundary": "UTC"},
    )


def test_utc_daily_long_windows_are_computed_but_explicitly_experimental() -> None:
    dates = (12, 13, 14, 15, 16, 20, 21)
    bars = [
        _daily_bar(datetime(2026, 1, day, tzinfo=UTC), str(99 + index))
        for index, day in enumerate(dates)
    ]
    windows = calculate_session_close_windows(
        bars,
        release_at=T0,
        source_grade="A",
        instrument_key="gold_gc",
        session_close_semantics="utc_day",
    )
    by_key = {item.key: item for item in windows}
    assert by_key["next_close"].end_value == Decimal("101")
    assert by_key["day_5_close"].end_value == Decimal("105")
    assert all(item.granularity_seconds == 86_400 for item in windows)
    assert all(item.experimental is True for item in windows)
    assert all(item.calendar_precision == "experimental_utc_day" for item in windows)
    assert all(
        item.missing_reason == "experimental_utc_day_boundary_not_exchange_settlement"
        for item in windows
    )
    assert all(item.quality_grade == "C" for item in windows)
    assert all("not an exchange settlement" in " ".join(item.limitations) for item in windows)


def test_long_windows_degrade_to_explicit_missing_without_daily_series() -> None:
    windows = calculate_session_close_windows(
        [],
        release_at=T0,
        source_grade="UNKNOWN",
        instrument_key="gold_gc",
        session_close_semantics="unavailable",
    )
    assert {item.key for item in windows} == {
        "us_cash_close",
        "next_close",
        "day_5_close",
    }
    assert all(item.return_percent is None for item in windows)
    assert all(
        item.missing_reason == "event_linked_daily_or_session_close_bars_unavailable"
        for item in windows
    )
    assert all(item.limitations for item in windows)


def test_analysis_manifest_and_windows_expose_selected_series_provenance(
    client: TestClient,
    release_index: dict[str, dict[str, object]],
) -> None:
    release_id = str(release_index["US_CPI"]["id"])
    detail = client.get(f"/v2/releases/{release_id}").json()
    run_id = detail["latest_analysis"]["id"]
    manifest = client.get(f"/v2/analysis-runs/{run_id}/manifest").json()
    selected = manifest["market_dataset"]
    assert selected
    assert all(item["selection_version"] == "release-manifest-series-v1" for item in selected)
    assert all(item["manifests"] for item in selected)
    assert all(item["selected_bars"] for item in selected)
    for item in selected:
        timestamps = [bar["timestamp"] for bar in item["selected_bars"]]
        assert len(timestamps) == len(set(timestamps))
        assert all(bar["provider_key"] == item["provider_key"] for bar in item["selected_bars"])
        if item["contract_code"] is not None:
            assert all(
                bar["contract_code"] == item["contract_code"]
                for bar in item["selected_bars"]
            )
        else:
            assert all(
                bar["source_symbol"] == item["source_symbol"]
                for bar in item["selected_bars"]
            )
    windows = client.get(f"/v2/releases/{release_id}/windows").json()["items"]
    long_windows = [item for item in windows if item["window_key"] in {"next_close", "day_5_close"}]
    assert long_windows
    assert all(item["granularity_seconds"] == 86_400 for item in long_windows)
    assert all(item["missing_reason"] for item in long_windows)
    assert all(item["limitations"] for item in long_windows)
    assert client.post(f"/v2/analysis-runs/{run_id}/replay").json()["replayed"] is True
