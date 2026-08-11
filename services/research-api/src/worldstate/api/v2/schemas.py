"""Write contracts for the local research API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

BackfillEventType = Literal["US_CPI", "US_NFP", "FOMC"]
BackfillAsset = Literal["GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX"]


def _default_backfill_events() -> list[BackfillEventType]:
    return ["US_CPI", "US_NFP", "FOMC"]


def _default_backfill_assets() -> list[BackfillAsset]:
    return ["GC", "SI", "CL", "ES", "NQ", "ZT", "ZN", "DX", "VX"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseValueInput(StrictModel):
    actual: Decimal | None = None
    previous: Decimal | None = None
    revised_previous: Decimal | None = None
    stage_key: str | None = None


class ReleaseStageInput(StrictModel):
    key: str
    title: str
    scheduled_at: AwareDatetime
    released_at: AwareDatetime | None = None


class ReleaseCreateInput(StrictModel):
    release_key: str
    release_type: Literal["US_CPI", "US_NFP", "FOMC"]
    title: str
    period_label: str
    scheduled_at: AwareDatetime
    released_at: AwareDatetime | None = None
    source_timezone: str = "America/New_York"
    source_name: str
    source_url: str
    verified: bool = False
    values: dict[str, ReleaseValueInput]
    stages: list[ReleaseStageInput] = Field(default_factory=list)
    contamination_level: Literal["none", "low", "medium", "high"] = "none"
    clean_window: bool = True
    overlapping_events: list[dict[str, object]] = Field(default_factory=list)
    confounding_notes: list[str] = Field(default_factory=list)


class ConsensusInput(StrictModel):
    indicator_key: str
    consensus_value: Decimal
    source_name: str
    source_url: str | None = None
    captured_at: AwareDatetime
    quality_grade: Literal["A", "B", "C", "D", "UNKNOWN"] = "C"
    is_manual: bool = True
    verification_notes: str | None = None


class ConsensusCsvInput(StrictModel):
    csv_text: str = Field(min_length=1)
    default_source_name: str = "Manual consensus CSV"
    default_source_url: str | None = None


class OfficialMacroCsvInput(StrictModel):
    """Observed official export; never silently treated as a live provider."""

    csv_text: str = Field(min_length=1)
    provider_key: str = Field(default="manual_official", min_length=1, max_length=64)
    source_name: str = Field(default="Official macro CSV", min_length=1, max_length=255)
    source_url: str = Field(min_length=1, max_length=2048)
    verified: bool = False
    verification_notes: str | None = None


class MarketCsvImportInput(StrictModel):
    instrument_key: str
    csv_text: str
    provider_key: str = "csv"
    source_name: str = "User CSV import"
    source_url: str | None = None
    verified: bool = False
    is_fixture: bool = False
    interval_seconds: int = Field(default=86400, ge=1)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    column_mapping: dict[str, str] = Field(default_factory=dict)


class BackfillRequestInput(StrictModel):
    start_date: date
    end_date: date
    event_types: list[BackfillEventType] = Field(default_factory=_default_backfill_events)
    assets: list[BackfillAsset] = Field(default_factory=_default_backfill_assets)
    estimate_id: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> BackfillRequestInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if not self.event_types:
            raise ValueError("at least one event type is required")
        if not self.assets:
            raise ValueError("at least one asset is required")
        return self


class AssistantInput(StrictModel):
    release_id: str
    question: str = Field(min_length=2, max_length=2000)


class ThesisInput(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    thesis: str = Field(min_length=3, max_length=4000)
    horizon: str = Field(default="未来 3 个月", max_length=64)
    confidence: float = Field(default=0.5, ge=0, le=1)
    status: Literal["active", "paused", "falsified", "confirmed", "archived"] = "active"
    entities: list[str] = Field(default_factory=list)
    related_states: list[str] = Field(default_factory=list)
    supporting_evidence: list[dict[str, object]] = Field(default_factory=list)
    contradicting_evidence: list[dict[str, object]] = Field(default_factory=list)
    confirmation_conditions: list[str] = Field(default_factory=list)
    falsification_conditions: list[str] = Field(default_factory=list)
    watch_variables: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=10000)


class ThesisUpdateInput(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    thesis: str | None = Field(default=None, min_length=3, max_length=4000)
    horizon: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "paused", "falsified", "confirmed", "archived"] | None = None
    entities: list[str] | None = None
    related_states: list[str] | None = None
    supporting_evidence: list[dict[str, object]] | None = None
    contradicting_evidence: list[dict[str, object]] | None = None
    confirmation_conditions: list[str] | None = None
    falsification_conditions: list[str] | None = None
    watch_variables: list[str] | None = None
    notes: str | None = Field(default=None, max_length=10000)


class ContextAssistantInput(StrictModel):
    question: str = Field(min_length=2, max_length=2000)
    data_mode: Literal["observed", "fixture", "all"] = "observed"


class WatchlistInput(StrictModel):
    item_type: Literal["series", "market", "country", "release", "thesis"]
    item_key: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    notes: str = Field(default="", max_length=4000)
    data_mode: Literal["observed", "fixture"] = "observed"


class MarketHorizon(StrictModel):
    value: float | None
    unit: Literal["%", "bp"]
    direction: str


class ProductMarketItem(StrictModel):
    key: str
    label: str
    symbol: str | None = None
    asset_class: str | None = None
    value: float | None = None
    formatted_value: str
    change: float | None = None
    change_unit: Literal["%", "bp"]
    direction: str
    trend: str
    status: str
    freshness: str
    proxy: bool = False
    sparkline: list[float] = Field(default_factory=list)
    horizons: dict[Literal["1d", "1w", "1m", "3m"], MarketHorizon] = Field(default_factory=dict)
    capabilities: dict[str, object] = Field(default_factory=dict)
    details: dict[str, object] = Field(default_factory=dict)


class ProductMarketsResponse(StrictModel):
    as_of: AwareDatetime
    data_mode: str
    methodology_version: str
    items: list[ProductMarketItem]
    limitations: list[str] = Field(default_factory=list)


class ProductDimension(StrictModel):
    key: str
    label: str
    score: float | None = None
    direction: str
    momentum: float | None = None
    confidence: float = 0.0
    coverage: float = 0.0
    status: str
    drivers: list[dict[str, object]] = Field(default_factory=list)
    details_ref: str


class ProductCountry(StrictModel):
    key: str
    label: str
    status: str
    available_dimensions: list[str] = Field(default_factory=list)
    dimensions: dict[str, dict[str, object]] = Field(default_factory=dict)
    latest_data_at: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class ProductMacroResponse(StrictModel):
    as_of: AwareDatetime
    data_mode: str
    methodology_version: str
    countries: list[ProductCountry]
    limitations: list[str] = Field(default_factory=list)


class ProductEventSummary(StrictModel):
    id: str
    release_key: str
    release_type: str
    title: str
    period_label: str
    scheduled_at: AwareDatetime
    released_at: AwareDatetime | None = None
    status: str
    classification: str | None = None
    surprise_score: float | None = None
    confidence: float | None = None
    analysis_status: str
    reproducibility_status: str | None = None
    analysis_completed_at: AwareDatetime | None = None
    data_mode: str
    clean_window: bool
    contamination_level: str


class ProductEventsResponse(StrictModel):
    as_of: AwareDatetime
    data_mode: str
    methodology_version: str
    items: list[ProductEventSummary]
    upcoming: list[ProductEventSummary] = Field(default_factory=list)
    recent: list[ProductEventSummary] = Field(default_factory=list)
    default_event_id: str | None = None
    limitations: list[str] = Field(default_factory=list)


class ProductEventHeader(StrictModel):
    id: str
    release_key: str
    type: str
    title: str
    country: str
    period_label: str
    scheduled_at: AwareDatetime
    released_at: AwareDatetime | None = None
    source_timezone: str
    status: str
    data_mode: str


class ProductSupportedIndicator(StrictModel):
    key: str
    label: str
    unit: str
    family: str
    hotter_when_higher: bool


class ProductExpectationIndicator(StrictModel):
    key: str
    label: str
    unit: str
    consensus: float | None = None
    captured_at: AwareDatetime | None = None
    source: str | None = None
    snapshot_id: str | None = None
    eligibility: Literal["pre_t0", "missing"]


class ProductExpectations(StrictModel):
    available: bool
    indicators: list[ProductExpectationIndicator] = Field(default_factory=list)
    eligible_count: int = 0
    rule: str


class ProductActualIndicator(StrictModel):
    key: str
    label: str
    unit: str
    actual: float | None = None
    previous: float | None = None
    revised_previous: float | None = None
    revision: float | None = None
    source: str | None = None
    release_value_id: str | None = None


class ProductActual(StrictModel):
    available: bool
    indicators: list[ProductActualIndicator] = Field(default_factory=list)


class ProductSurpriseIndicator(StrictModel):
    key: str
    label: str
    unit: str
    available: bool
    raw_surprise: float | None = None
    relative_surprise: float | None = None
    surprise_z: float | None = None
    threshold_scaled_surprise: float | None = None
    direction: str | None = None
    sample_count: int | None = None


class ProductSurprise(StrictModel):
    available: bool
    classification: str | None = None
    score: float | None = None
    direction: str | None = None
    indicators: list[ProductSurpriseIndicator] = Field(default_factory=list)
    methodology: str | None = None


class ProductReactionAsset(StrictModel):
    model_config = ConfigDict(extra="allow")

    key: str
    label: str
    symbol: str | None = None
    status: str | None = None
    eligible: bool | None = None
    row_count: int | None = None
    is_proxy: bool = False
    proxy_for: str | None = None


class ProductMarketReaction(StrictModel):
    status: str
    available: bool
    available_assets: list[ProductReactionAsset] = Field(default_factory=list)
    partial_assets: list[ProductReactionAsset] = Field(default_factory=list)
    missing_assets: list[ProductReactionAsset] = Field(default_factory=list)
    required_granularity_seconds: int
    limitations: list[str] = Field(default_factory=list)
    matrix: list[dict[str, object]] = Field(default_factory=list)
    analysis_run_id: str | None = None


class ProductAnalysisSummary(StrictModel):
    run_id: str | None = None
    status: str
    reproducibility: str | None = None
    confidence: float | None = None
    data_gaps: list[str] = Field(default_factory=list)


class ProductEventActions(StrictModel):
    can_add_consensus: bool
    can_import_consensus_csv: bool
    can_import_minutes: bool
    can_run_analysis: bool
    analysis_blockers: list[str] = Field(default_factory=list)


class ProductEventDetail(StrictModel):
    """Stable product event workflow with additive Event Lab compatibility fields."""

    model_config = ConfigDict(extra="allow")

    event: ProductEventHeader
    supported_indicators: list[ProductSupportedIndicator] = Field(default_factory=list)
    expectations: ProductExpectations
    actual: ProductActual
    surprise: ProductSurprise
    market_reaction: ProductMarketReaction
    historical_context: dict[str, object] = Field(default_factory=dict)
    analysis: ProductAnalysisSummary
    actions: ProductEventActions
    id: str
    release_key: str
    release_type: str
    title: str
    country: str
    period_label: str
    scheduled_at: AwareDatetime
    released_at: AwareDatetime | None = None
    source_timezone: str
    status: str
    data_mode: str
    values: dict[str, dict[str, object]] = Field(default_factory=dict)
    stages: list[dict[str, object]] = Field(default_factory=list)
    contamination: dict[str, object] = Field(default_factory=dict)
    bundle: dict[str, object] = Field(default_factory=dict)
    latest_analysis: dict[str, object] | None = None
    source: dict[str, object] = Field(default_factory=dict)
    data_provenance: dict[str, object] = Field(default_factory=dict)
    data_quality: list[dict[str, object]] = Field(default_factory=list)


class ProductTodayResponse(StrictModel):
    as_of: AwareDatetime
    data_mode: str
    methodology_version: str
    macro_snapshot: list[ProductDimension] = Field(default_factory=list)
    markets: list[ProductMarketItem] = Field(default_factory=list)
    what_changed: list[dict[str, object]] = Field(default_factory=list)
    upcoming: list[dict[str, object]] = Field(default_factory=list)
    latest_research: list[dict[str, object]] = Field(default_factory=list)
    global_: list[ProductCountry] = Field(default_factory=list, alias="global")
    watch_next: list[str] = Field(default_factory=list)
    capability_summary: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


def stage_payload(items: list[ReleaseStageInput]) -> list[dict[str, object]]:
    return [
        {
            "key": item.key,
            "title": item.title,
            "scheduled_at": datetime.fromisoformat(item.scheduled_at.isoformat()),
            "released_at": (
                datetime.fromisoformat(item.released_at.isoformat()) if item.released_at else None
            ),
        }
        for item in items
    ]
