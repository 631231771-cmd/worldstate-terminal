"""Normalized provider contracts and source-specific adapters."""

from worldstate.provider_kit.bls import (
    BLS_SERIES_MAP,
    BlsOfficialProvider,
    BlsReleaseBatch,
    BlsScheduleBatch,
    BlsScheduleEntry,
)
from worldstate.provider_kit.contracts import (
    NormalizedObservation,
    ProviderBatch,
    ProviderCapabilities,
    ProviderContract,
    ProviderDomain,
    ProviderRateLimit,
    ProviderRetryPolicy,
    ProviderRunMetadata,
    ProviderTerms,
    SourceArtifact,
)
from worldstate.provider_kit.databento import (
    DATABENTO_INSTRUMENTS,
    DatabentoBarBatch,
    DatabentoContract,
    DatabentoCostEstimate,
    DatabentoDownloadRequest,
    DatabentoMarketProvider,
    DatabentoSymbologyResolution,
)
from worldstate.provider_kit.errors import (
    ProviderBudgetError,
    ProviderError,
    ProviderErrorCode,
    ProviderSchemaError,
)
from worldstate.provider_kit.federal_reserve import (
    FederalReserveFomcProvider,
    FomcCalendarBatch,
    FomcDocument,
    FomcMaterialType,
    FomcMeeting,
)
from worldstate.provider_kit.fixtures import generate_scenario_bars
from worldstate.provider_kit.fred_alfred import FredAlfredProvider, FredObservationBatch
from worldstate.provider_kit.official_public import (
    OfficialPublicCsvProvider,
    PublicObservationBatch,
    PublicSeriesSpec,
)
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
from worldstate.provider_kit.trading_economics import (
    ConsensusCalendarBatch,
    ConsensusSnapshotRecord,
    TradingEconomicsConsensusProvider,
    TradingEconomicsEntitlement,
    TradingEconomicsQuota,
)

__all__ = [
    "BLS_SERIES_MAP",
    "DATABENTO_INSTRUMENTS",
    "BarQuery",
    "BlsOfficialProvider",
    "BlsReleaseBatch",
    "BlsScheduleBatch",
    "BlsScheduleEntry",
    "ConsensusCalendarBatch",
    "ConsensusSnapshotRecord",
    "CsvMarketBarProvider",
    "DatabentoBarBatch",
    "DatabentoContract",
    "DatabentoCostEstimate",
    "DatabentoDownloadRequest",
    "DatabentoMarketProvider",
    "DatabentoSymbologyResolution",
    "FederalReserveFomcProvider",
    "FixtureMarketBarProvider",
    "FomcCalendarBatch",
    "FomcDocument",
    "FomcMaterialType",
    "FomcMeeting",
    "FredAlfredProvider",
    "FredObservationBatch",
    "OfficialPublicCsvProvider",
    "PublicObservationBatch",
    "PublicSeriesSpec",
    "MacroProvider",
    "MarketBarBatch",
    "MarketBarProvider",
    "MarketBarRecord",
    "MarketInstrumentRef",
    "NormalizedObservation",
    "ProviderBatch",
    "ProviderBudgetError",
    "ProviderCapabilities",
    "ProviderContract",
    "ProviderDomain",
    "ProviderError",
    "ProviderErrorCode",
    "ProviderRateLimit",
    "ProviderRetryPolicy",
    "ProviderRunMetadata",
    "ProviderSchemaError",
    "ProviderTerms",
    "ProviderWaterfall",
    "SourceArtifact",
    "TradingEconomicsConsensusProvider",
    "TradingEconomicsEntitlement",
    "TradingEconomicsQuota",
    "generate_scenario_bars",
]
