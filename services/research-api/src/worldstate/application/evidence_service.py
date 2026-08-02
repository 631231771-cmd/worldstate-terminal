"""EvidencePack assembly from focused read projections."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncEngine

from worldstate.application.release_queries import (
    get_release_detail,
    get_release_historical,
    get_release_windows,
)
from worldstate.application.report_service import get_release_explanations


async def get_evidence_pack(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    detail = await get_release_detail(engine, release_id)
    if detail is None:
        return None
    document: dict[str, object] = {
        "schema_version": "evidence-pack-v1",
        "release": detail,
        "market_reaction": await get_release_windows(engine, release_id),
        "historical": await get_release_historical(engine, release_id),
        "research": await get_release_explanations(engine, release_id),
        "constraints": {
            "facts_and_inferences_separated": True,
            "no_unique_causality_claim": True,
            "proxy_assets_labelled": True,
            "fixture_data_labelled": True,
        },
    }
    digest = hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    document["evidence_pack_hash"] = digest
    return document


__all__ = ["get_evidence_pack"]
