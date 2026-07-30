"""Validated write payloads for the CPI Event Lab."""

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl


class EventLabInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CpiIndicatorInput(EventLabInput):
    indicator_key: Literal[
        "headline_mom",
        "headline_yoy",
        "core_mom",
        "core_yoy",
    ]
    actual_value: Decimal
    consensus_value: Decimal
    previous_value: Decimal | None = None
    revised_previous_value: Decimal | None = None
    actual_source: str = Field(min_length=1, max_length=255)
    actual_source_url: HttpUrl
    actual_is_manual: bool = False
    actual_verified: bool = False
    actual_is_fixture: bool = False
    consensus_source: str = Field(min_length=1, max_length=255)
    consensus_source_url: HttpUrl | None = None
    consensus_captured_at: AwareDatetime
    consensus_quality: Literal["verified", "reviewed", "unverified", "fixture"]
    consensus_is_manual: bool = True
    consensus_is_fixture: bool = False
    verification_notes: str | None = None


class CpiEventInput(EventLabInput):
    event_key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{4,254}$")
    title: str = Field(default="美国消费者价格指数（CPI）", max_length=512)
    period_label: str = Field(min_length=4, max_length=64)
    release_at: AwareDatetime
    source_timezone: str = "America/New_York"
    status: Literal["scheduled", "released", "revised"] = "released"
    source_url: HttpUrl
    data_version: str = Field(default="initial", max_length=64)
    contamination_level: Literal["none", "low", "medium", "high"] = "none"
    clean_window: bool = True
    overlapping_events: list[dict[str, str]] = Field(default_factory=list)
    confounding_notes: list[str] = Field(default_factory=list)
    indicators: list[CpiIndicatorInput] = Field(min_length=4, max_length=4)


class ConsensusCaptureInput(EventLabInput):
    indicator_key: Literal[
        "headline_mom",
        "headline_yoy",
        "core_mom",
        "core_yoy",
    ]
    consensus_value: Decimal
    consensus_source: str = Field(min_length=1, max_length=255)
    consensus_source_url: HttpUrl | None = None
    consensus_captured_at: AwareDatetime
    consensus_quality: Literal["verified", "reviewed", "unverified", "fixture"]
    consensus_is_manual: bool = True
    consensus_is_fixture: bool = False
    verification_notes: str | None = None


class CsvMarketImportInput(EventLabInput):
    csv_text: str = Field(min_length=20, max_length=20_000_000)
    instrument_key: str = Field(min_length=2, max_length=64)
    provider_key: str = Field(default="csv", min_length=2, max_length=64)
    source_name: str = Field(default="User CSV import", min_length=2, max_length=255)
    source_url: HttpUrl | None = None
    acquired_at: AwareDatetime
    verified: bool = False
    is_fixture: bool = False
    verification_notes: str | None = None
