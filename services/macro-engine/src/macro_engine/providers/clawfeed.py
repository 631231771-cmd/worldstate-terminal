"""Optional adapter for a local or self-hosted ClawFeed editorial service."""

# ruff: noqa: RUF001

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx


def _compact_text(value: object, limit: int = 1200) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_clawfeed_digests(payload: object, base_url: str) -> list[dict[str, object]]:
    """Normalize ClawFeed's public digest API without trusting embedded markup."""

    if not isinstance(payload, list):
        return []
    rows: list[dict[str, object]] = []
    for item in payload[:5]:
        if not isinstance(item, dict):
            continue
        digest_id = item.get("id")
        content = _compact_text(item.get("content"))
        digest_type = str(item.get("type") or "daily")
        if digest_id is None or not content:
            continue
        metadata = item.get("metadata")
        if isinstance(metadata, str):
            metadata = _compact_text(metadata, 400)
        rows.append(
            {
                "id": str(digest_id),
                "type": digest_type,
                "content": content,
                "metadata": metadata if isinstance(metadata, (dict, str)) else {},
                "created_at": item.get("created_at"),
                "source": "ClawFeed",
                "url": f"{base_url.rstrip('/')}/#digest-{digest_id}",
            }
        )
    return rows


class ClawFeedProvider:
    """Read a bounded set of public editions from a configured ClawFeed server."""

    def __init__(
        self,
        base_url: str | None,
        timeout_seconds: float = 4.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def fetch_digests(self) -> list[dict[str, object]]:
        if not self.base_url:
            return []
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "WorldStateTerminal/0.3 (+local research)"},
        )
        try:
            response = await client.get(
                f"{self.base_url}/api/digests",
                params={"type": "daily", "limit": 3, "offset": 0},
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload: Any = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return []
        finally:
            if owns_client:
                await client.aclose()
        return parse_clawfeed_digests(payload, self.base_url)


def clawfeed_status(
    *,
    configured: bool,
    digests: list[dict[str, object]],
) -> dict[str, object]:
    """Describe integration state without exposing local addresses or credentials."""

    return {
        "configured": configured,
        "connected": bool(digests),
        "editions": len(digests),
        "mode": "external" if digests else "built_in_editorial",
        "checked_at": datetime.now(UTC).isoformat(),
        "principle": "扩大信息池，但保持最终简报篇幅固定。",
    }
