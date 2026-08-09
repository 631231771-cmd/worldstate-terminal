"""Provider-neutral contracts shared by official and licensed data adapters.

Provider response schemas intentionally stop at this package boundary.  The
models below describe provenance, runtime policy, and normalized observations;
they never expose a vendor SDK object.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from worldstate.data_quality import DataQuality
from worldstate.macro_core.models import ProviderHealth


class ProviderModel(BaseModel):
    """Immutable provider-boundary value object."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ProviderDomain(StrEnum):
    MACRO_RELEASE = "macro_release"
    MACRO_SERIES = "macro_series"
    CONSENSUS = "consensus"
    EVENT_CALENDAR = "event_calendar"
    MARKET_BARS = "market_bars"
    MARKET_SYMBOLOGY = "market_symbology"
    COST_ESTIMATE = "cost_estimate"


class ProviderRetryPolicy(ProviderModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    backoff_seconds: float = Field(default=0.25, ge=0, le=60)
    retry_status_codes: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)


class ProviderRateLimit(ProviderModel):
    """Latest non-secret rate/quota information observed from a provider."""

    limit: int | None = Field(default=None, ge=0)
    remaining: int | None = Field(default=None, ge=0)
    reset_at: AwareDatetime | None = None
    period: str | None = None
    source: str = "unknown"
    observed_at: AwareDatetime | None = None


class ProviderTerms(ProviderModel):
    license_name: str
    terms_url: str
    redistribution_allowed: bool = False
    notes: str | None = None


class ProviderCapabilities(ProviderModel):
    provider_key: str
    domains: tuple[ProviderDomain, ...]
    operations: tuple[str, ...]
    supports_point_in_time: bool
    supports_revisions: bool
    supports_batch: bool
    supported_intervals: tuple[str, ...] = ()
    paid_access: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class ProviderContract(Protocol):
    """Common operational surface implemented by every v0.5 provider."""

    key: str
    terms: ProviderTerms

    @property
    def timeout_seconds(self) -> float: ...

    @property
    def retry_policy(self) -> ProviderRetryPolicy: ...

    @property
    def rate_limit(self) -> ProviderRateLimit: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def get_capabilities(self) -> ProviderCapabilities: ...

    def healthcheck(self) -> Awaitable[ProviderHealth]: ...


class SourceArtifact(ProviderModel):
    """Provider-neutral envelope suitable for durable SourceArtifact storage."""

    provider_key: str
    source_url: str
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None = None
    content_type: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(ge=0)
    content: bytes = Field(repr=False)
    license_name: str
    terms_url: str
    metadata: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def capture(
        cls,
        *,
        provider_key: str,
        source_url: str,
        retrieved_at: AwareDatetime,
        content_type: str,
        content: bytes,
        terms: ProviderTerms,
        published_at: AwareDatetime | None = None,
        metadata: dict[str, object] | None = None,
    ) -> SourceArtifact:
        return cls(
            provider_key=provider_key,
            source_url=source_url,
            retrieved_at=retrieved_at,
            published_at=published_at,
            content_type=content_type,
            content_hash=hashlib.sha256(content).hexdigest(),
            byte_length=len(content),
            content=content,
            license_name=terms.license_name,
            terms_url=terms.terms_url,
            metadata=metadata or {},
        )


class NormalizedObservation(ProviderModel):
    """A point-in-time value with both source and standardized units."""

    canonical_key: str
    provider_series_id: str
    reference_period_start: date
    reference_period_end: date
    value: Decimal | None
    raw_value: str | None = None
    raw_unit: str
    standard_unit: str
    scale_factor: Decimal = Decimal("1")
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    vintage_date: date
    version: str
    is_first_release: bool
    is_revision: bool
    previous_value: Decimal | None = None
    revised_previous_value: Decimal | None = None
    quality: DataQuality
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_point_in_time(self) -> NormalizedObservation:
        if self.available_at > self.retrieved_at:
            raise ValueError("available_at cannot be later than retrieved_at")
        return self


class ProviderBatch(ProviderModel):
    provider_key: str
    retrieved_at: AwareDatetime
    artifacts: tuple[SourceArtifact, ...]
    quality: DataQuality
    warnings: tuple[str, ...] = ()
    request_id: str | None = None
    idempotency_key: str


class ProviderRunMetadata(ProviderModel):
    """Information application services can persist as a provider run."""

    provider_key: str
    operation: str
    started_at: AwareDatetime
    completed_at: AwareDatetime
    request_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    artifact_hashes: tuple[str, ...]
    idempotency_key: str
    rate_limit: ProviderRateLimit
    warnings: tuple[str, ...] = ()
