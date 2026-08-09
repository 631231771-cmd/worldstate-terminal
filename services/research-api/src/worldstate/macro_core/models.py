"""Normalized provider-facing domain records."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from worldstate.macro_core.enums import (
    AvailabilityMethod,
    AvailabilityPrecision,
    ProviderStatus,
)


class DomainModel(BaseModel):
    """Immutable base for records crossing a provider boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SeriesSearchResult(DomainModel):
    native_id: str
    title: str
    description: str | None = None
    source_url: str | None = None


class SeriesMetadata(DomainModel):
    native_id: str
    title: str
    description: str | None = None
    frequency: str
    unit: str
    seasonal_adjustment: str | None = None
    observation_type: str = "value"
    source_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationRecord(DomainModel):
    native_id: str
    period_start: date
    period_end: date
    value: Decimal | None
    raw_value: str | None = None
    vintage_date: date
    realtime_start: date | None = None
    realtime_end: date | None = None
    available_at: AwareDatetime | None = None
    availability_method: AvailabilityMethod = AvailabilityMethod.UNKNOWN
    availability_precision: AvailabilityPrecision = AvailabilityPrecision.UNKNOWN
    fetched_at: AwareDatetime
    is_preliminary: bool = False
    is_revised: bool = False
    quality_flags: list[str] = Field(default_factory=list)
    source_hash: str


class ReleaseRecord(DomainModel):
    native_id: str
    name: str
    scheduled_at: AwareDatetime | None = None
    actual_at: AwareDatetime | None = None
    source_timezone: str
    status: str
    importance: int = Field(ge=0, le=3)
    source_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderHealth(DomainModel):
    key: str
    status: ProviderStatus
    checked_at: AwareDatetime
    latency_ms: float | None = Field(default=None, ge=0)
    message: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ObservationQuery(DomainModel):
    native_id: str
    start: date | None = None
    end: date | None = None
    as_of: datetime | None = None
