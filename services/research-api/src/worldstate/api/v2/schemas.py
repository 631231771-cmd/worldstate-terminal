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


class MarketCsvImportInput(StrictModel):
    instrument_key: str
    csv_text: str
    provider_key: str = "csv"
    source_name: str = "User CSV import"
    source_url: str | None = None
    verified: bool = False
    is_fixture: bool = False
    interval_seconds: int = Field(default=86400, ge=1)


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
