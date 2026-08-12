"""Stable, non-secret errors for every provider adapter."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from worldstate.macro_core.errors import MacroEngineError


class ProviderErrorCode(StrEnum):
    NOT_CONFIGURED = "provider_not_configured"
    AUTHENTICATION = "provider_authentication_failed"
    ENTITLEMENT = "provider_entitlement_required"
    QUOTA_EXHAUSTED = "provider_quota_exhausted"
    RATE_LIMITED = "provider_rate_limited"
    TIMEOUT = "provider_timeout"
    TRANSPORT = "provider_transport_error"
    MALFORMED_RESPONSE = "provider_response_malformed"
    SCHEMA_CHANGED = "provider_schema_changed"
    UNSUPPORTED = "provider_operation_unsupported"
    NOT_FOUND = "provider_data_not_found"
    POINT_IN_TIME = "provider_point_in_time_unavailable"
    BUDGET_EXCEEDED = "provider_budget_exceeded"
    COST_ESTIMATE_UNAVAILABLE = "provider_cost_estimate_unavailable"
    PAID_DOWNLOAD_DISABLED = "provider_paid_download_disabled"
    PUBLIC_CALENDAR_UNAVAILABLE = "provider_public_calendar_unavailable"
    INVALID_REQUEST = "provider_request_invalid"


class ProviderError(MacroEngineError):
    """Normalized provider failure without credentials or raw response bodies."""

    def __init__(
        self,
        provider_key: str,
        code: ProviderErrorCode,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = dict(details or {})
        safe_details.update(
            {
                "provider_key": provider_key,
                "retryable": retryable,
                "status_code": status_code,
            }
        )
        super().__init__(code.value, message, details=safe_details)
        self.provider_key = provider_key
        self.error_code = code
        self.retryable = retryable
        self.status_code = status_code


class ProviderSchemaError(ProviderError):
    def __init__(
        self,
        provider_key: str,
        message: str,
        *,
        structure: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"expected_structure": structure, **(details or {})}
        super().__init__(
            provider_key,
            ProviderErrorCode.SCHEMA_CHANGED,
            message,
            details=merged,
        )


class ProviderBudgetError(ProviderError):
    def __init__(
        self,
        provider_key: str,
        message: str,
        *,
        estimated_cost_usd: str,
        budget_usd: str,
    ) -> None:
        super().__init__(
            provider_key,
            ProviderErrorCode.BUDGET_EXCEEDED,
            message,
            details={
                "estimated_cost_usd": estimated_cost_usd,
                "budget_usd": budget_usd,
            },
        )
