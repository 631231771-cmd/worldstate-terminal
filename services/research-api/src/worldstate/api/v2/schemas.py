"""Write contracts for the local research API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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


class MarketCsvImportInput(StrictModel):
    instrument_key: str
    csv_text: str
    provider_key: str = "csv"
    source_name: str = "User CSV import"
    source_url: str | None = None
    verified: bool = False
    is_fixture: bool = False


class AssistantInput(StrictModel):
    release_id: str
    question: str = Field(min_length=2, max_length=2000)


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
