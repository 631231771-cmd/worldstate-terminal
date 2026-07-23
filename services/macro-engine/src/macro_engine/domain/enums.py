"""Stable domain enumerations."""

from enum import StrEnum


class ServiceStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class EntityType(StrEnum):
    COUNTRY = "country"
    ECONOMIC_AREA = "economic_area"
    GLOBAL = "global"
    REGION = "region"


class AvailabilityMethod(StrEnum):
    OFFICIAL_RELEASE_TIMESTAMP = "official_release_timestamp"
    PROVIDER_REALTIME_START = "provider_realtime_start"
    OFFICIAL_UPDATE_DATE = "official_update_date"
    CONFIGURED_RELEASE_LAG = "configured_release_lag"
    INGESTION_TIME_PROXY = "ingestion_time_proxy"
    UNKNOWN = "unknown"


class AvailabilityPrecision(StrEnum):
    TIMESTAMP = "timestamp"
    DAY = "day"
    MONTH = "month"
    UNKNOWN = "unknown"


class ThesisStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    ARCHIVED = "archived"


class ThesisConditionType(StrEnum):
    CONFIRM = "confirm"
    INVALIDATE = "invalidate"
    WATCH = "watch"


class EvidenceStance(StrEnum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    NEUTRAL = "neutral"
