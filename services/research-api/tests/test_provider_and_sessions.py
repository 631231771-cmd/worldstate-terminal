from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from worldstate.market_core.sessions import (
    is_us_cash_session,
    resolve_us_cash_close,
)
from worldstate.provider_kit.models import BarQuery, MarketInstrumentRef
from worldstate.provider_kit.providers import CsvMarketBarProvider, ProviderWaterfall


def query() -> BarQuery:
    return BarQuery(
        instrument=MarketInstrumentRef(
            canonical_key="gold_gc",
            symbol="GC",
            title="黄金期货",
            exchange="COMEX",
            quote_unit="USD/oz",
        ),
        start=datetime(2024, 3, 8, 13, 30, tzinfo=UTC),
        end=datetime(2024, 3, 8, 13, 32, tzinfo=UTC),
    )


async def test_csv_provider_requires_timezone_and_preserves_warnings() -> None:
    provider = CsvMarketBarProvider(
        "\n".join(
            (
                "timestamp,instrument_key,open,high,low,close,volume",
                "2024-03-08T13:30:00Z,gold_gc,2000,2002,1999,2001,10",
                "2024-03-08T13:30:00Z,gold_gc,2001,2003,2000,2002,11",
                "2024-03-08T13:31:00,gold_gc,2002,2004,2001,2003,12",
            )
        ),
        verified=True,
    )
    batch = await provider.fetch_bars(query())
    assert len(batch.bars) == 1
    assert batch.bars[0].close_value == 2002
    assert any("duplicate timestamp" in item for item in batch.warnings)
    assert any("explicit timezone" in item for item in batch.warnings)


async def test_provider_waterfall_falls_back_after_malformed_source() -> None:
    malformed = CsvMarketBarProvider("timestamp,instrument_key\n")
    working = CsvMarketBarProvider(
        "timestamp,instrument_key,open,high,low,close\n"
        "2024-03-08T13:30:00Z,gold_gc,2000,2002,1999,2001\n"
    )
    batch = await ProviderWaterfall([malformed, working]).fetch_bars(query())
    assert len(batch.bars) == 1
    assert any("missing required columns" in item for item in batch.warnings)


def test_session_close_handles_dst_and_holidays() -> None:
    winter = resolve_us_cash_close(datetime(2024, 1, 8, 13, 30, tzinfo=UTC))
    summer = resolve_us_cash_close(datetime(2024, 7, 8, 12, 30, tzinfo=UTC))
    assert winter.hour == 21
    assert summer.hour == 20
    assert is_us_cash_session(date(2024, 7, 4)) is False
    after_close = resolve_us_cash_close(datetime(2024, 7, 3, 21, 0, tzinfo=UTC))
    assert after_close.date() == date(2024, 7, 5)


def test_csv_provider_rejects_missing_columns() -> None:
    provider = CsvMarketBarProvider("timestamp,instrument_key\n")
    with pytest.raises(ValueError, match="missing required columns"):
        provider._parse(query())
