"""Public API schemas."""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from macro_engine.domain.enums import ProviderStatus, ServiceStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentHealth(ApiModel):
    status: ServiceStatus
    message: str | None = None


class ProviderHealthSummary(ApiModel):
    key: str
    status: ProviderStatus
    message: str | None = None


class HealthResponse(ApiModel):
    service: str = "world-state-macro-engine"
    version: str
    status: ServiceStatus
    generated_at: AwareDatetime
    database: ComponentHealth
    providers: list[ProviderHealthSummary]
    writes_enabled: bool
    default_locale: str
    default_timezone: str
    methodology_version: str = "unavailable"
    warnings: list[str] = Field(default_factory=list)


class ErrorResponse(ApiModel):
    code: str
    message: str
    generated_at: datetime
