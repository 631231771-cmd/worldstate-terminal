"""Normalized market bars and provider adapters."""

from worldstate.provider_kit.fixtures import generate_scenario_bars
from worldstate.provider_kit.fred_alfred import FredAlfredProvider
from worldstate.provider_kit.macro import MacroProvider
from worldstate.provider_kit.models import (
    BarQuery,
    MarketBarBatch,
    MarketBarRecord,
    MarketInstrumentRef,
)
from worldstate.provider_kit.providers import (
    CsvMarketBarProvider,
    FixtureMarketBarProvider,
    MarketBarProvider,
    ProviderWaterfall,
)

__all__ = [
    "BarQuery",
    "CsvMarketBarProvider",
    "FixtureMarketBarProvider",
    "FredAlfredProvider",
    "MacroProvider",
    "MarketBarBatch",
    "MarketBarProvider",
    "MarketBarRecord",
    "MarketInstrumentRef",
    "ProviderWaterfall",
    "generate_scenario_bars",
]
