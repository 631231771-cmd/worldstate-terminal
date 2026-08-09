"""Typed inputs and outputs for evidence-bound macro event analysis."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class IndicatorInput:
    key: str
    title: str
    actual: Decimal | None
    consensus: Decimal | None
    previous: Decimal | None
    revised_previous: Decimal | None
    weight: float
    hotter_when_higher: bool = True


@dataclass(frozen=True)
class HistoricalSurpriseObservation:
    """A historical consensus error available before the current release."""

    released_at: datetime
    raw_surprise: float


@dataclass(frozen=True)
class IndicatorSurprise:
    key: str
    raw_surprise: Decimal | None
    oriented_surprise: float | None
    relative_surprise: float | None
    threshold_scaled_surprise: float | None
    surprise_z: float | None
    direction: str
    revision: Decimal | None
    history_sample_count: int
    history_mean: float | None
    history_std: float | None
    history_cutoff_at: datetime | None
    surprise_method: str
    z_score_unavailable_reason: str | None = None

    # Transitional internal alias.  It deliberately exposes only a genuine z-score.
    # API serializers must use the explicit fields above.
    @property
    def standardized(self) -> float | None:
        return self.surprise_z

    @property
    def raw(self) -> Decimal | None:
        return self.raw_surprise

    @property
    def relative(self) -> float | None:
        return self.relative_surprise

    @property
    def history_samples(self) -> int:
        return self.history_sample_count


@dataclass(frozen=True)
class BundleSurprise:
    classification: str
    score: float | None
    direction: str
    indicators: tuple[IndicatorSurprise, ...]
    reasons: tuple[str, ...]
    revision_dominant: bool
    composite_method: str = "insufficient"
    component_methods: dict[str, str] = field(default_factory=dict)
    revision_analysis: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WindowSpec:
    key: str
    label: str
    start_seconds: int
    end_seconds: int
    session_based: bool = False


@dataclass(frozen=True)
class ComputedWindow:
    key: str
    label: str
    start_at: datetime
    end_at: datetime
    start_value: Decimal | None
    end_value: Decimal | None
    change_absolute: Decimal | None
    return_percent: float | None
    max_up_percent: float | None
    max_down_percent: float | None
    realized_volatility: float | None
    volume_change_percent: float | None
    coverage_ratio: float
    direction: str
    spike_fade: bool
    dip_recovery: bool
    direction_reversal: bool
    granularity_seconds: int
    quality_grade: str
    missing_reason: str | None = None
    calendar_name: str = "exchange_session_lite"
    calendar_precision: str = "limited"
    expected_tradable_bars: int | None = None
    experimental: bool = False
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class EarliestReaction:
    instrument_key: str
    detected_at: datetime
    lag_seconds: int
    move_percent: float
    direction: str
    threshold_percent: float
    pre_event_volatility: float
    granularity_seconds: int
    confirmation_bars: int
    limitation: str


REGIME_DIMENSIONS = (
    "inflation_regime",
    "growth_regime",
    "monetary_policy_regime",
    "risk_regime",
    "dollar_regime",
    "real_yield_regime",
    "volatility_regime",
)


@dataclass(frozen=True)
class HistoricalCase:
    event_id: str
    release_at: datetime
    classification: str
    direction: str
    magnitude_bucket: str
    core_direction: str
    regime_tags: tuple[str, ...]
    contamination_level: str
    clean_window: bool
    returns: dict[str, float | None] = field(default_factory=dict)
    release_type: str = "US_CPI"
    regime_dimensions: dict[str, str] = field(default_factory=dict)
    analysis_run_id: str | None = None
    is_fixture: bool = False
    proxy_instrument_count: int = 0
