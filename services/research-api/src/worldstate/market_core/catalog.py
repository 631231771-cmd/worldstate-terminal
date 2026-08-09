"""Canonical instruments used by event-window analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentDefinition:
    key: str
    symbol: str
    title: str
    asset_class: str
    instrument_type: str
    exchange: str | None
    quote_unit: str
    measurement_type: str
    timezone: str
    is_proxy: bool = False
    proxy_for: str | None = None


INSTRUMENTS: tuple[InstrumentDefinition, ...] = (
    InstrumentDefinition(
        "gold_gc",
        "GC",
        "黄金期货",
        "metals",
        "futures",
        "COMEX",
        "USD/troy ounce",
        "price",
        "America/Chicago",
    ),
    InstrumentDefinition(
        "silver_si",
        "SI",
        "白银期货",
        "metals",
        "futures",
        "COMEX",
        "USD/troy ounce",
        "price",
        "America/Chicago",
    ),
    InstrumentDefinition(
        "wti_cl",
        "CL",
        "WTI 原油期货",
        "energy",
        "futures",
        "NYMEX",
        "USD/barrel",
        "price",
        "America/Chicago",
    ),
    InstrumentDefinition(
        "sp500_es",
        "ES",
        "标普500指数期货",
        "equity_index",
        "futures",
        "CME",
        "index points",
        "price",
        "America/Chicago",
    ),
    InstrumentDefinition(
        "nasdaq_nq",
        "NQ",
        "纳斯达克100指数期货",
        "equity_index",
        "futures",
        "CME",
        "index points",
        "price",
        "America/Chicago",
    ),
    InstrumentDefinition(
        "ust2y_zt",
        "ZT",
        "2年期美债期货（收益率代理）",
        "rates",
        "futures_proxy",
        "CBOT",
        "price points",
        "yield_proxy_futures_price",
        "America/Chicago",
        True,
        "美国2年期国债收益率分钟变化",
    ),
    InstrumentDefinition(
        "ust10y_zn",
        "ZN",
        "10年期美债期货（收益率代理）",
        "rates",
        "futures_proxy",
        "CBOT",
        "price points",
        "yield_proxy_futures_price",
        "America/Chicago",
        True,
        "美国10年期国债收益率分钟变化",
    ),
    InstrumentDefinition(
        "dollar_dxy",
        "DX",
        "美元指数期货",
        "fx",
        "futures",
        "ICE Futures US",
        "index points",
        "price",
        "America/New_York",
    ),
    InstrumentDefinition(
        "eurusd", "EURUSD", "EUR/USD", "fx", "spot", None, "USD per EUR", "price", "UTC"
    ),
    InstrumentDefinition(
        "usdjpy", "USDJPY", "USD/JPY", "fx", "spot", None, "JPY per USD", "price", "UTC"
    ),
    InstrumentDefinition(
        "vix",
        "VX",
        "VIX 波动率期货",
        "volatility",
        "futures",
        "Cboe Futures Exchange",
        "index points",
        "price",
        "America/Chicago",
    ),
)

INSTRUMENT_BY_KEY = {item.key: item for item in INSTRUMENTS}
