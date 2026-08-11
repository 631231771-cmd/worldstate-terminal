"""Product-facing event workflow projection built from the stable research engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.consensus_service import supported_indicators_for_release
from worldstate.application.event_intraday_service import (
    evaluate_stored_event_intraday_manifest,
    release_event_assets,
)
from worldstate.application.event_readiness import build_analysis_readiness
from worldstate.application.release_queries import (
    get_release_detail,
    get_release_historical,
    get_release_windows,
)
from worldstate.db.models import MacroRelease, MarketDataManifest, MarketInstrument

REACTION_WINDOWS = ("post_1m", "post_5m", "post_15m", "post_30m", "post_60m")


def _actual_indicator(
    key: str, supported: dict[str, object], value: dict[str, object]
) -> dict[str, object]:
    previous = value.get("previous")
    revised = value.get("revised_previous")
    return {
        "key": key,
        "label": supported["label"],
        "unit": supported["unit"],
        "actual": value.get("actual"),
        "previous": value.get("previous"),
        "revised_previous": value.get("revised_previous"),
        "revision": (
            float(cast(Any, revised)) - float(cast(Any, previous))
            if revised is not None and previous is not None
            else None
        ),
        "source": value.get("actual_source"),
        "release_value_id": value.get("actual_release_value_id"),
    }


def _expectation_indicator(
    key: str, supported: dict[str, object], value: dict[str, object], *, t0: str
) -> dict[str, object]:
    captured_at = value.get("consensus_captured_at")
    eligible = False
    if captured_at:
        try:
            captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
            anchor = datetime.fromisoformat(str(t0).replace("Z", "+00:00"))
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=UTC)
            else:
                captured = captured.astimezone(UTC)
            anchor = anchor.replace(tzinfo=UTC) if anchor.tzinfo is None else anchor.astimezone(UTC)
            eligible = captured < anchor
        except ValueError:
            eligible = False
    return {
        "key": key,
        "label": supported["label"],
        "unit": supported["unit"],
        "consensus": value.get("consensus"),
        "captured_at": captured_at,
        "source": value.get("consensus_source"),
        "snapshot_id": value.get("consensus_snapshot_id"),
        "eligibility": "pre_t0" if eligible else "missing",
    }


def _surprise_indicator(
    key: str, supported: dict[str, object], value: dict[str, object]
) -> dict[str, object]:
    surprise = value.get("surprise")
    return {
        "key": key,
        "label": supported["label"],
        "unit": supported["unit"],
        "available": surprise is not None,
        "raw_surprise": surprise.get("raw") if isinstance(surprise, dict) else None,
        "relative_surprise": surprise.get("relative") if isinstance(surprise, dict) else None,
        "surprise_z": surprise.get("surprise_z") if isinstance(surprise, dict) else None,
        "threshold_scaled_surprise": (
            surprise.get("threshold_scaled_surprise") if isinstance(surprise, dict) else None
        ),
        "direction": surprise.get("direction") if isinstance(surprise, dict) else None,
        "sample_count": surprise.get("historical_sample_count")
        if isinstance(surprise, dict)
        else None,
    }


async def _market_capability(
    engine: AsyncEngine, release_id: str, assets: list[dict[str, object]]
) -> dict[str, object]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return {"status": "missing", "available_assets": [], "missing_assets": assets}
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            return {
                "status": "missing",
                "available": False,
                "available_assets": [],
                "missing_assets": assets,
            }
        rows = list(
            (
                await session.execute(
                    select(MarketDataManifest, MarketInstrument)
                    .join(MarketInstrument, MarketInstrument.id == MarketDataManifest.instrument_id)
                    .where(
                        MarketDataManifest.macro_release_id == release_uuid,
                        MarketDataManifest.data_mode == release.data_mode,
                        MarketDataManifest.interval_seconds == 60,
                        MarketDataManifest.row_count > 0,
                    )
                    .order_by(MarketDataManifest.created_at.desc())
                )
            ).all()
        )
    declared: dict[str, dict[str, object]] = {}
    for manifest, instrument in rows:
        validation = evaluate_stored_event_intraday_manifest(
            manifest.metadata_json,
            data_mode=release.data_mode,
            row_count=manifest.row_count,
            interval_seconds=manifest.interval_seconds,
            is_fixture=release.data_mode == "fixture",
        )
        eligibility = manifest.metadata_json.get("event_intraday_eligibility_v1")
        status = str(manifest.metadata_json.get("event_intraday_eligibility") or "ineligible")
        effective_eligible = bool(validation["eligible"])
        current = declared.get(instrument.canonical_key)
        if current is None or effective_eligible:
            declared[instrument.canonical_key] = {
                "key": instrument.canonical_key,
                "label": instrument.title,
                "symbol": instrument.symbol,
                "status": status,
                "eligible": effective_eligible,
                "row_count": manifest.row_count,
                "start_at": manifest.start_at.isoformat(),
                "end_at": manifest.end_at.isoformat(),
                "quality": manifest.quality_grade,
                "manual": manifest.provider_key == "csv",
                "is_proxy": instrument.is_proxy,
                "proxy_for": instrument.proxy_for,
                "eligibility": eligibility if isinstance(eligibility, dict) else None,
                "rejection_reasons": validation["reasons"],
            }
    available = [item for item in declared.values() if item["eligible"]]
    partial = [item for item in declared.values() if not item["eligible"]]
    missing = [item for item in assets if item["key"] not in declared]
    return {
        "status": "available" if available else "partial" if partial else "missing",
        "available": bool(available),
        "available_assets": available,
        "partial_assets": partial,
        "missing_assets": missing,
        "required_granularity_seconds": 60,
        "limitations": [
            "Only event-linked, eligibility-approved minute manifests enter the Event Engine.",
            "Treasury futures are price proxies and are not displayed as cash-yield basis points.",
        ],
    }


def _reaction_matrix(windows: dict[str, Any] | None) -> list[dict[str, object]]:
    if not windows:
        return []
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for item in windows.get("items", []):
        if item.get("window_key") not in REACTION_WINDOWS:
            continue
        identity = (str(item.get("stage_key")), str(item.get("instrument_key")))
        row = grouped.setdefault(
            identity,
            {
                "stage_key": item.get("stage_key"),
                "instrument_key": item.get("instrument_key"),
                "instrument_label": item.get("instrument_title"),
                "symbol": item.get("symbol"),
                "is_proxy": item.get("is_proxy", False),
                "windows": {},
            },
        )
        basis_points = item.get("change_basis_points")
        row_windows = cast(dict[str, object], row["windows"])
        row_windows[str(item["window_key"])] = {
            "value": basis_points if basis_points is not None else item.get("return_percent"),
            "unit": "bp" if basis_points is not None else "%",
            "direction": item.get("direction"),
            "coverage": item.get("coverage_ratio"),
            "reversal": item.get("direction_reversal", False),
            "missing_reason": item.get("missing_reason"),
        }
    return list(grouped.values())


async def build_event_product_detail(
    engine: AsyncEngine, release_id: str, *, data_mode: str = "observed"
) -> dict[str, Any] | None:
    raw = await get_release_detail(engine, release_id)
    if raw is None or (data_mode != "all" and raw.get("data_mode") != data_mode):
        return None
    supported_rows = await supported_indicators_for_release(engine, release_id)
    supported = {str(item["key"]): item for item in supported_rows}
    values = cast(dict[str, dict[str, object]], raw.get("values", {}))
    bundle = cast(dict[str, object], raw.get("bundle", {}))
    stage_items = cast(list[dict[str, object]], raw.get("stages") or [])
    anchor_stage = next(
        (
            item
            for item in stage_items
            if (
                (raw.get("release_type") == "FOMC" and item.get("key") == "statement")
                or item.get("key") in {"release", "decision"}
            )
        ),
        stage_items[0] if stage_items else None,
    )
    t0 = str(
        (anchor_stage or {}).get("released_at")
        or (anchor_stage or {}).get("scheduled_at")
        or raw.get("released_at")
        or raw["scheduled_at"]
    )
    expectations = [
        _expectation_indicator(key, item, dict(values.get(key, {})), t0=t0)
        for key, item in supported.items()
    ]
    actual = [
        _actual_indicator(key, item, dict(values.get(key, {}))) for key, item in supported.items()
    ]
    surprise = [
        _surprise_indicator(key, item, dict(values.get(key, {}))) for key, item in supported.items()
    ]
    assets = await release_event_assets(engine)
    market_capability = await _market_capability(engine, release_id, assets)
    windows = await get_release_windows(engine, release_id)
    historical = await get_release_historical(engine, release_id)
    analysis = raw.get("latest_analysis")
    readiness = await build_analysis_readiness(engine, release_id, data_mode=data_mode)
    actual_available = bool(readiness.release_inputs.get("ready"))
    consensus_available = bool(readiness.surprise_inputs.get("ready"))
    market_available = bool(market_capability["available"])
    return {
        "event": {
            "id": raw["id"],
            "release_key": raw["release_key"],
            "type": raw["release_type"],
            "title": raw["title"],
            "country": raw["country"],
            "period_label": raw["period_label"],
            "scheduled_at": raw["scheduled_at"],
            "released_at": raw.get("released_at"),
            "source_timezone": raw["source_timezone"],
            "status": raw["status"],
            "data_mode": raw["data_mode"],
        },
        "supported_indicators": supported_rows,
        "expectations": {
            "available": consensus_available,
            "indicators": expectations,
            "eligible_count": sum(item["eligibility"] == "pre_t0" for item in expectations),
            "rule": "captured_at must be strictly earlier than release T0",
        },
        "actual": {"available": actual_available, "indicators": actual},
        "surprise": {
            "available": bool(readiness.surprise_inputs.get("matched_indicators")),
            "classification": bundle.get("classification"),
            "score": bundle.get("score"),
            "direction": bundle.get("direction"),
            "indicators": surprise,
            "methodology": bundle.get("methodology_version"),
        },
        "market_reaction": {
            **market_capability,
            "matrix": _reaction_matrix(windows),
            "analysis_run_id": windows.get("analysis_run_id") if windows else None,
        },
        "historical_context": historical or {"items": [], "data_gaps": []},
        "analysis": {
            "run_id": analysis.get("id") if isinstance(analysis, dict) else None,
            "status": analysis.get("status") if isinstance(analysis, dict) else "not_run",
            "reproducibility": (
                analysis.get("reproducibility_status") if isinstance(analysis, dict) else None
            ),
            "confidence": analysis.get("confidence") if isinstance(analysis, dict) else None,
            "data_gaps": analysis.get("data_gaps", []) if isinstance(analysis, dict) else [],
        },
        "actions": {
            "can_add_consensus": bool(supported_rows),
            "can_import_consensus_csv": bool(supported_rows),
            "can_import_minutes": bool(assets),
            "can_run_analysis": readiness.ready and market_available,
            "analysis_blockers": list(readiness.blockers),
        },
        "analysis_readiness": readiness.as_dict(),
        "stages": raw.get("stages", []),
        "contamination": raw.get("contamination", {}),
        "source": raw.get("source"),
        "data_provenance": raw.get("data_provenance", {}),
        "data_quality": raw.get("data_quality", []),
        # Additive compatibility fields for the existing Event Lab.
        "id": raw["id"],
        "release_key": raw["release_key"],
        "release_type": raw["release_type"],
        "title": raw["title"],
        "country": raw["country"],
        "period_label": raw["period_label"],
        "scheduled_at": raw["scheduled_at"],
        "released_at": raw.get("released_at"),
        "source_timezone": raw["source_timezone"],
        "status": raw["status"],
        "data_mode": raw["data_mode"],
        "values": values,
        "bundle": raw.get("bundle", {}),
        "latest_analysis": analysis,
    }


__all__ = ["build_event_product_detail"]
