"""Traceable CPI fixtures used to prove the vertical slice end to end."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

from macro_engine.market_data import MarketBarRecord

BLS_JAN_2024_URL = "https://www.bls.gov/news.release/archives/cpi_02132024.htm"
CONSENSUS_JAN_2024_URL = (
    "https://www.investing.com/news/economic-indicators/"
    "sticky-jan-us-cpi-inflation-supports-fed-reticence-on-easing-3302278"
)


@dataclass(frozen=True)
class CpiFixture:
    event_key: str
    release_at: datetime
    period_label: str
    source_url: str
    actuals: tuple[float, float, float, float]
    consensus: tuple[float, float, float, float]
    previous: tuple[float, float, float, float]
    revised_previous: tuple[float, float, float, float]
    consensus_source_url: str | None
    verified_actual: bool
    verified_consensus: bool
    contamination_level: str = "none"
    clean_window: bool = True
    overlapping_events: tuple[dict[str, str], ...] = ()
    confounding_notes: tuple[str, ...] = ()


class FixtureInstrument(TypedDict):
    canonical_key: str
    symbol: str
    root_symbol: str
    contract_code: str | None
    exchange: str
    title: str
    asset_class: str
    quote_unit: str
    measurement_type: str
    source_timezone: str
    is_proxy: bool
    proxy_for: str | None
    base: float
    hot_shock: float
    noise: float


CPI_FIXTURES = (
    CpiFixture(
        event_key="us-cpi-2023-02-14",
        release_at=datetime(2023, 2, 14, 13, 30, tzinfo=UTC),
        period_label="2023-01",
        source_url="https://www.bls.gov/news.release/archives/cpi_02142023.htm",
        actuals=(0.5, 6.4, 0.4, 5.6),
        consensus=(0.4, 6.2, 0.4, 5.5),
        previous=(0.1, 6.5, 0.3, 5.7),
        revised_previous=(0.1, 6.5, 0.4, 5.7),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2023-09-13",
        release_at=datetime(2023, 9, 13, 12, 30, tzinfo=UTC),
        period_label="2023-08",
        source_url="https://www.bls.gov/news.release/archives/cpi_09132023.htm",
        actuals=(0.6, 3.7, 0.3, 4.3),
        consensus=(0.6, 3.6, 0.2, 4.3),
        previous=(0.2, 3.2, 0.2, 4.7),
        revised_previous=(0.2, 3.2, 0.2, 4.7),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2023-10-12",
        release_at=datetime(2023, 10, 12, 12, 30, tzinfo=UTC),
        period_label="2023-09",
        source_url="https://www.bls.gov/news.release/archives/cpi_10122023.htm",
        actuals=(0.4, 3.7, 0.3, 4.1),
        consensus=(0.3, 3.6, 0.3, 4.1),
        previous=(0.6, 3.7, 0.3, 4.3),
        revised_previous=(0.6, 3.7, 0.3, 4.3),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2024-01-11",
        release_at=datetime(2024, 1, 11, 13, 30, tzinfo=UTC),
        period_label="2023-12",
        source_url="https://www.bls.gov/news.release/archives/cpi_01112024.htm",
        actuals=(0.3, 3.4, 0.3, 3.9),
        consensus=(0.2, 3.2, 0.3, 3.8),
        previous=(0.1, 3.1, 0.3, 4.0),
        revised_previous=(0.1, 3.1, 0.3, 4.0),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2024-02-13",
        release_at=datetime(2024, 2, 13, 13, 30, tzinfo=UTC),
        period_label="2024-01",
        source_url=BLS_JAN_2024_URL,
        actuals=(0.3, 3.1, 0.4, 3.9),
        consensus=(0.2, 2.9, 0.3, 3.7),
        previous=(0.3, 3.4, 0.3, 3.9),
        revised_previous=(0.2, 3.4, 0.3, 3.9),
        consensus_source_url=CONSENSUS_JAN_2024_URL,
        verified_actual=True,
        verified_consensus=True,
        contamination_level="low",
        clean_window=True,
        confounding_notes=(
            "未登记同一8:30 ET时点的另一项美国一级宏观发布；盘中仍可能存在未结构化新闻。",
        ),
    ),
    CpiFixture(
        event_key="us-cpi-2024-03-12",
        release_at=datetime(2024, 3, 12, 12, 30, tzinfo=UTC),
        period_label="2024-02",
        source_url="https://www.bls.gov/news.release/archives/cpi_03122024.htm",
        actuals=(0.4, 3.2, 0.4, 3.8),
        consensus=(0.4, 3.1, 0.3, 3.7),
        previous=(0.3, 3.1, 0.4, 3.9),
        revised_previous=(0.3, 3.1, 0.4, 3.9),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2024-04-10",
        release_at=datetime(2024, 4, 10, 12, 30, tzinfo=UTC),
        period_label="2024-03",
        source_url="https://www.bls.gov/news.release/archives/cpi_04102024.htm",
        actuals=(0.4, 3.5, 0.4, 3.8),
        consensus=(0.3, 3.4, 0.3, 3.7),
        previous=(0.4, 3.2, 0.4, 3.8),
        revised_previous=(0.4, 3.2, 0.4, 3.8),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2023-04-12",
        release_at=datetime(2023, 4, 12, 12, 30, tzinfo=UTC),
        period_label="2023-03",
        source_url="https://www.bls.gov/news.release/archives/cpi_04122023.htm",
        actuals=(0.1, 5.0, 0.4, 5.6),
        consensus=(0.2, 5.2, 0.4, 5.6),
        previous=(0.4, 6.0, 0.5, 5.5),
        revised_previous=(0.4, 6.0, 0.5, 5.5),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
    ),
    CpiFixture(
        event_key="us-cpi-2023-11-14",
        release_at=datetime(2023, 11, 14, 13, 30, tzinfo=UTC),
        period_label="2023-10",
        source_url="https://www.bls.gov/news.release/archives/cpi_11142023.htm",
        actuals=(0.0, 3.2, 0.2, 4.0),
        consensus=(0.1, 3.3, 0.3, 4.1),
        previous=(0.4, 3.7, 0.3, 4.1),
        revised_previous=(0.4, 3.7, 0.3, 4.1),
        consensus_source_url=None,
        verified_actual=False,
        verified_consensus=False,
        contamination_level="medium",
        clean_window=False,
        overlapping_events=(
            {
                "title": "同窗市场新闻fixture",
                "occurred_at": "2023-11-14T13:37:00Z",
                "source": "fixture",
            },
        ),
        confounding_notes=("该历史案例用于验证污染降级，不用于强因果统计。",),
    ),
)

INSTRUMENTS: tuple[FixtureInstrument, ...] = (
    {
        "canonical_key": "gold_gc",
        "symbol": "GC",
        "root_symbol": "GC",
        "contract_code": "GCJ24",
        "exchange": "COMEX",
        "title": "黄金期货",
        "asset_class": "metals",
        "quote_unit": "USD/oz",
        "measurement_type": "futures_price",
        "source_timezone": "America/Chicago",
        "is_proxy": False,
        "proxy_for": None,
        "base": 2035.0,
        "hot_shock": -0.85,
        "noise": 0.018,
    },
    {
        "canonical_key": "silver_si",
        "symbol": "SI",
        "root_symbol": "SI",
        "contract_code": "SIH24",
        "exchange": "COMEX",
        "title": "白银期货",
        "asset_class": "metals",
        "quote_unit": "USD/oz",
        "measurement_type": "futures_price",
        "source_timezone": "America/Chicago",
        "is_proxy": False,
        "proxy_for": None,
        "base": 22.8,
        "hot_shock": -1.15,
        "noise": 0.028,
    },
    {
        "canonical_key": "dollar_dxy",
        "symbol": "DXY",
        "root_symbol": "DXY",
        "contract_code": None,
        "exchange": "ICE_INDEX_FIXTURE",
        "title": "美元指数",
        "asset_class": "fx",
        "quote_unit": "index points",
        "measurement_type": "index_level",
        "source_timezone": "America/New_York",
        "is_proxy": False,
        "proxy_for": None,
        "base": 104.2,
        "hot_shock": 0.35,
        "noise": 0.007,
    },
    {
        "canonical_key": "sp500_es",
        "symbol": "ES",
        "root_symbol": "ES",
        "contract_code": "ESH24",
        "exchange": "CME",
        "title": "标普500指数期货",
        "asset_class": "equity_index",
        "quote_unit": "index points",
        "measurement_type": "futures_price",
        "source_timezone": "America/Chicago",
        "is_proxy": False,
        "proxy_for": None,
        "base": 5040.0,
        "hot_shock": -0.75,
        "noise": 0.014,
    },
    {
        "canonical_key": "nasdaq_nq",
        "symbol": "NQ",
        "root_symbol": "NQ",
        "contract_code": "NQH24",
        "exchange": "CME",
        "title": "纳斯达克100指数期货",
        "asset_class": "equity_index",
        "quote_unit": "index points",
        "measurement_type": "futures_price",
        "source_timezone": "America/Chicago",
        "is_proxy": False,
        "proxy_for": None,
        "base": 17850.0,
        "hot_shock": -1.05,
        "noise": 0.02,
    },
    {
        "canonical_key": "ust2y_zt",
        "symbol": "ZT",
        "root_symbol": "ZT",
        "contract_code": "ZTH24",
        "exchange": "CBOT",
        "title": "2年期美债期货",
        "asset_class": "rates",
        "quote_unit": "price points",
        "measurement_type": "yield_proxy_futures_price",
        "source_timezone": "America/Chicago",
        "is_proxy": True,
        "proxy_for": "美国2年期国债收益率分钟变化",
        "base": 102.2,
        "hot_shock": -0.18,
        "noise": 0.004,
    },
    {
        "canonical_key": "ust10y_zn",
        "symbol": "ZN",
        "root_symbol": "ZN",
        "contract_code": "ZNH24",
        "exchange": "CBOT",
        "title": "10年期美债期货",
        "asset_class": "rates",
        "quote_unit": "price points",
        "measurement_type": "yield_proxy_futures_price",
        "source_timezone": "America/Chicago",
        "is_proxy": True,
        "proxy_for": "美国10年期国债收益率分钟变化",
        "base": 110.5,
        "hot_shock": -0.14,
        "noise": 0.005,
    },
)


def _event_direction(fixture: CpiFixture) -> int:
    raw = [
        actual - consensus
        for actual, consensus in zip(fixture.actuals, fixture.consensus, strict=True)
    ]
    score = sum(raw)
    return 1 if score > 0.02 else -1 if score < -0.02 else 0


def _shock_path(key: str, minute: int, target: float) -> float:
    if minute < 0:
        return 0.0
    if key == "silver_si" and target < 0:
        if minute == 0:
            return 0.15
        if minute == 1:
            return 0.08
        if minute <= 5:
            return 0.08 + (target - 0.08) * ((minute - 1) / 4)
    if minute <= 5:
        return target * ((minute + 1) / 6)
    if key == "gold_gc" and target < 0 and minute <= 30:
        return target + (target * 0.2 - target) * ((minute - 5) / 25)
    if minute <= 30:
        return target + (target * 0.72 - target) * ((minute - 5) / 25)
    return target * 0.72


def generate_fixture_bars(
    fixture: CpiFixture,
    instrument: FixtureInstrument,
) -> list[MarketBarRecord]:
    """Generate reproducible bars with an explicit non-market-data fixture label."""

    key = str(instrument["canonical_key"])
    direction = _event_direction(fixture)
    target = float(instrument["hot_shock"]) * direction
    base = float(instrument["base"])
    noise_scale = float(instrument["noise"])
    seed = sum(ord(char) for char in f"{fixture.event_key}:{key}")
    randomizer = random.Random(seed)
    bars: list[MarketBarRecord] = []
    previous_close = base
    for minute in range(-60, 241):
        timestamp = fixture.release_at + timedelta(minutes=minute)
        shock = _shock_path(key, minute, target)
        cyclical = math.sin((minute + seed % 17) / 9) * noise_scale * 0.35
        random_noise = randomizer.gauss(0, noise_scale * (0.25 if minute < 0 else 0.35))
        close = base * (1 + (shock + cyclical + random_noise) / 100)
        open_value = previous_close
        range_percent = noise_scale * (1.5 if 0 <= minute <= 10 else 0.7)
        high = max(open_value, close) * (1 + range_percent / 100)
        low = min(open_value, close) * (1 - range_percent / 100)
        volume = 1000 + abs(randomizer.gauss(0, 90))
        if 0 <= minute <= 15:
            volume *= 3.2 - minute * 0.08
        bars.append(
            MarketBarRecord(
                instrument_key=key,
                timestamp=timestamp,
                interval_seconds=60,
                open_value=Decimal(f"{open_value:.8f}"),
                high_value=Decimal(f"{high:.8f}"),
                low_value=Decimal(f"{low:.8f}"),
                close_value=Decimal(f"{close:.8f}"),
                volume=Decimal(f"{volume:.2f}"),
                source_symbol=f"FIXTURE:{instrument['symbol']}",
                contract_code=(
                    str(instrument["contract_code"])
                    if instrument["contract_code"] is not None
                    else None
                ),
                metadata={
                    "fixture": True,
                    "fixture_method": "cpi-reaction-shape-v1",
                    "not_exchange_recorded": True,
                },
            )
        )
        previous_close = close
    return bars
