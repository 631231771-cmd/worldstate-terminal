from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from worldstate.market_core.sessions import (
    expected_tradable_bars,
    is_tradable_minute,
    is_us_cash_session,
    resolve_instrument_close,
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


def test_good_friday_memorial_day_and_early_close_are_calendar_aware() -> None:
    assert is_us_cash_session(date(2024, 3, 29)) is False
    assert is_us_cash_session(date(2024, 5, 27)) is False
    july_third = resolve_us_cash_close(datetime(2024, 7, 3, 14, 0, tzinfo=UTC))
    assert july_third == datetime(2024, 7, 3, 17, 0, tzinfo=UTC)


def test_cme_weekend_and_daily_maintenance_are_not_expected_bars() -> None:
    saturday = datetime(2024, 3, 9, 15, 0, tzinfo=UTC)
    sunday_open = datetime(2024, 3, 10, 23, 0, tzinfo=UTC)  # 19:00 New York after DST
    maintenance = datetime(2024, 3, 11, 21, 30, tzinfo=UTC)  # 17:30 New York
    assert is_tradable_minute(saturday, "gold_gc") is False
    assert is_tradable_minute(sunday_open, "gold_gc") is True
    assert is_tradable_minute(maintenance, "gold_gc") is False


def test_long_window_uses_instrument_sessions_not_natural_minutes() -> None:
    start = datetime(2024, 3, 8, 13, 30, tzinfo=UTC)
    end = datetime(2024, 3, 11, 21, 0, tzinfo=UTC)
    expected = expected_tradable_bars(start, end, 60, "gold_gc")
    natural = int((end - start).total_seconds() / 60)
    assert 0 < expected < natural
    assert resolve_instrument_close(start, "gold_gc").hour == 22
    assert resolve_instrument_close(start, "sp500_cash").hour == 21


def test_csv_provider_rejects_missing_columns() -> None:
    provider = CsvMarketBarProvider("timestamp,instrument_key\n")
    with pytest.raises(ValueError, match="missing required columns"):
        provider._parse(query())
