"""HTTP transport shared by provider adapters.

Retries are deliberately small and deterministic.  Application schedulers may
retry a failed provider run later; this layer only absorbs transient request
failures and records rate metadata.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from worldstate.provider_kit.contracts import ProviderRateLimit, ProviderRetryPolicy
from worldstate.provider_kit.errors import ProviderError, ProviderErrorCode

QueryParameter = str | int | float | bool | None


class HttpProviderTransport:
    """Composable async transport with timeout, retry, and error normalization."""

    def __init__(
        self,
        *,
        provider_key: str,
        client: httpx.AsyncClient | None,
        timeout_seconds: float,
        retry_policy: ProviderRetryPolicy,
    ) -> None:
        self.provider_key = provider_key
        self._client = client
        self.timeout_seconds = timeout_seconds
        self.retry_policy = retry_policy
        self.rate_limit = ProviderRateLimit()

    @staticmethod
    def _optional_int(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return max(0, int(float(value)))
        except ValueError:
            return None

    @staticmethod
    def _reset_at(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromtimestamp(float(value), UTC)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _capture_rate_limit(self, response: httpx.Response) -> None:
        headers = response.headers
        limit = headers.get("x-ratelimit-limit") or headers.get("x-rate-limit-limit")
        remaining = headers.get("x-ratelimit-remaining") or headers.get(
            "x-rate-limit-remaining"
        )
        reset = headers.get("x-ratelimit-reset") or headers.get("x-rate-limit-reset")
        self.rate_limit = ProviderRateLimit(
            limit=self._optional_int(limit),
            remaining=self._optional_int(remaining),
            reset_at=self._reset_at(reset),
            period=headers.get("x-ratelimit-period"),
            source="response_headers" if any((limit, remaining, reset)) else "not_reported",
            observed_at=datetime.now(UTC),
        )

    def _status_error(self, response: httpx.Response) -> ProviderError:
        status = response.status_code
        if status in {401}:
            code = ProviderErrorCode.AUTHENTICATION
            message = f"{self.provider_key} rejected the configured credential"
            retryable = False
        elif status in {402, 403}:
            code = ProviderErrorCode.ENTITLEMENT
            message = f"{self.provider_key} entitlement does not permit this request"
            retryable = False
        elif status == 404:
            code = ProviderErrorCode.NOT_FOUND
            message = f"{self.provider_key} did not find the requested resource"
            retryable = False
        elif status == 429:
            code = ProviderErrorCode.RATE_LIMITED
            message = f"{self.provider_key} rate limit was reached"
            retryable = True
        elif status in self.retry_policy.retry_status_codes:
            code = ProviderErrorCode.TRANSPORT
            message = f"{self.provider_key} returned a transient HTTP failure"
            retryable = True
        else:
            code = ProviderErrorCode.TRANSPORT
            message = f"{self.provider_key} returned an HTTP failure"
            retryable = False
        return ProviderError(
            self.provider_key,
            code,
            message,
            retryable=retryable,
            status_code=status,
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, QueryParameter] | None = None,
        json_body: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self._client is None:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                return await self._request_with_client(
                    client,
                    method,
                    url,
                    params=params,
                    json_body=json_body,
                    headers=headers,
                )
        return await self._request_with_client(
            self._client,
            method,
            url,
            params=params,
            json_body=json_body,
            headers=headers,
        )

    async def _request_with_client(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: Mapping[str, QueryParameter] | None,
        json_body: object | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        last_error: ProviderError | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    self.provider_key,
                    ProviderErrorCode.TIMEOUT,
                    f"{self.provider_key} request timed out",
                    retryable=True,
                )
                if attempt == self.retry_policy.max_attempts:
                    raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = ProviderError(
                    self.provider_key,
                    ProviderErrorCode.TRANSPORT,
                    f"{self.provider_key} transport failed: {type(exc).__name__}",
                    retryable=True,
                )
                if attempt == self.retry_policy.max_attempts:
                    raise last_error from exc
            else:
                self._capture_rate_limit(response)
                if response.is_success:
                    return response
                last_error = self._status_error(response)
                if not last_error.retryable or attempt == self.retry_policy.max_attempts:
                    raise last_error
            if self.retry_policy.backoff_seconds:
                await asyncio.sleep(self.retry_policy.backoff_seconds * attempt)
        if last_error is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("provider request exhausted without a response")
        raise last_error
