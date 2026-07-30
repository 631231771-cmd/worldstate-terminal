"""Internal event-lab value objects."""

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
class IndicatorSurprise:
    key: str
    raw: Decimal | None
    relative: float | None
    standardized: float | None
    direction: str
    revision: Decimal | None
    history_samples: int


@dataclass(frozen=True)
class BundleSurprise:
    classification: str
    score: float | None
    direction: str
    indicators: tuple[IndicatorSurprise, ...]
    reasons: tuple[str, ...]
    revision_dominant: bool


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
