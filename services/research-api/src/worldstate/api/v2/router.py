"""Macro Research Terminal API v2."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from secrets import compare_digest
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from worldstate import __version__
from worldstate.ai_researcher import answer_question
from worldstate.api.v2.data_router import data_router, data_write_router
from worldstate.api.v2.schemas import (
    AssistantInput,
    ConsensusInput,
    ContextAssistantInput,
    MarketCsvImportInput,
    ReleaseCreateInput,
    ThesisInput,
    ThesisUpdateInput,
    WatchlistInput,
    stage_payload,
)
from worldstate.application.analysis_orchestrator import METHODOLOGY_VERSION, analyze_release
from worldstate.application.analysis_persistence import (
    diff_analysis_runs,
    get_analysis_manifest,
    replay_analysis_run,
)
from worldstate.application.consensus_service import append_consensus
from worldstate.application.daily_brief_service import build_daily_brief
from worldstate.application.evidence_service import get_evidence_pack
from worldstate.application.global_macro_service import build_global_macro
from worldstate.application.macro_system_service import build_macro_systems
from worldstate.application.market_import_service import import_market_csv
from worldstate.application.market_research_service import (
    build_market_dashboard,
    get_series_history,
    search_series,
)
from worldstate.application.release_commands import create_manual_release
from worldstate.application.release_queries import (
    get_current_regime,
    get_provider_runs,
    get_quality_overview,
    get_release_detail,
    get_release_historical,
    get_release_timeline,
    get_release_windows,
    list_releases,
)
from worldstate.application.report_service import get_release_explanations
from worldstate.application.state_history_service import (
    add_watchlist_item,
    list_watchlist,
    list_world_state_snapshots,
    persist_world_state_snapshot,
    remove_watchlist_item,
)
from worldstate.application.thesis_service import (
    create_thesis,
    evaluate_thesis,
    get_thesis,
    list_theses,
    update_thesis,
)
from worldstate.application.world_state_service import build_world_state
from worldstate.config import Settings
from worldstate.db.models import (
    AnalysisRun,
    ConsensusSnapshot,
    EvidenceItem,
    Indicator,
    MacroRelease,
    MarketInstrument,
    ResearchClaim,
)
from worldstate.research_engine.history import (
    CASE_STUDY_SAMPLE,
    LIMITED_STATISTICAL_SAMPLE,
    ROBUST_SAMPLE,
)

router = APIRouter(prefix="/v2")

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_LOCAL_ORIGINS = {
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "tauri://localhost",
    "https://tauri.localhost",
}


def require_write_access(
    request: Request,
    authorization: str | None = Header(default=None),
    x_write_token: str | None = Header(default=None),
) -> None:
    client_host = request.client.host if request.client else ""
    origin = request.headers.get("origin")
    if client_host in _LOCAL_HOSTS and (origin is None or origin in _LOCAL_ORIGINS):
        return
    settings: Settings = request.app.state.settings
    supplied = x_write_token
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    configured = settings.write_token.get_secret_value() if settings.write_token else None
    if (
        not settings.writes_available
        or configured is None
        or supplied is None
        or not compare_digest(supplied, configured)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="writes require a local desktop request or configured write token",
        )


def required[T](result: T | None, message: str = "macro release not found") -> T:
    if result is None:
        raise HTTPException(status_code=404, detail=message)
    return result


def requested_data_mode(
    request: Request,
    explicit: Literal["observed", "fixture", "all"] | None = None,
) -> Literal["observed", "fixture", "all"]:
    if explicit is not None:
        return explicit
    return "all" if request.app.state.settings.demo_mode else "observed"


@router.get("/health", tags=["system"])
async def health(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    database_status = "ok"
    database_message = None
    try:
        async with asyncio.timeout(settings.health_timeout_seconds):
            async with request.app.state.database_engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception as exc:
        database_status = "unavailable"
        database_message = type(exc).__name__
    return {
        "product": "worldstate-terminal",
        "service": "worldstate-research-api",
        "version": __version__,
        "api_version": "v2",
        "status": "ok" if database_status == "ok" else "degraded",
        "generated_at": datetime.now(UTC).isoformat(),
        "database": {"status": database_status, "message": database_message},
        "methodology_version": METHODOLOGY_VERSION,
        "ai_provider": settings.resolved_ai_provider,
        "writes_enabled": settings.writes_available,
        "demo_mode": settings.demo_mode,
        "scheduler_enabled": settings.scheduler_enabled,
        "paid_download_enabled": settings.allow_paid_download,
        "data_foundation": {
            "demo_mode": settings.demo_mode,
            "scheduler_enabled": settings.scheduler_enabled,
            "paid_download_enabled": settings.allow_paid_download,
            "databento_budget_limit_usd": float(settings.databento_max_estimated_cost_usd),
            "credentials_exposed": False,
        },
    }


@router.get("/analysis-runs/{run_id}/manifest", tags=["analysis"])
async def analysis_manifest(run_id: str, request: Request) -> object:
    return required(
        await get_analysis_manifest(request.app.state.database_engine, run_id),
        "analysis run not found",
    )


@router.post(
    "/analysis-runs/{run_id}/replay",
    tags=["analysis"],
    dependencies=[Depends(require_write_access)],
)
async def analysis_replay(run_id: str, request: Request) -> object:
    return required(
        await replay_analysis_run(request.app.state.database_engine, run_id),
        "analysis run not found",
    )


@router.get("/analysis-runs/{run_id}/diff/{other_id}", tags=["analysis"])
async def analysis_diff(run_id: str, other_id: str, request: Request) -> object:
    return required(
        await diff_analysis_runs(request.app.state.database_engine, run_id, other_id),
        "analysis run not found",
    )


@router.get("/analysis-runs/{run_id}/evidence", tags=["research"])
async def analysis_evidence(run_id: str, request: Request) -> object:
    factory = async_sessionmaker(request.app.state.database_engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(EvidenceItem).where(EvidenceItem.analysis_run_id == uuid.UUID(run_id))
            )
        ).all()
        return {
            "run_id": run_id,
            "items": [
                {
                    "evidence_id": str(item.id),
                    "evidence_type": item.evidence_type,
                    "statement": item.statement,
                    "quality_grade": item.quality_grade,
                    "is_fixture": item.is_fixture,
                    "is_proxy": item.is_proxy,
                    "is_manual": item.is_manual,
                    "limitations": item.limitations_json,
                    "content_hash": item.content_hash,
                }
                for item in rows
            ],
        }


@router.get("/analysis-runs/{run_id}/claims", tags=["research"])
async def analysis_claims(run_id: str, request: Request) -> object:
    factory = async_sessionmaker(request.app.state.database_engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(ResearchClaim).where(ResearchClaim.analysis_run_id == uuid.UUID(run_id))
            )
        ).all()
        return {
            "run_id": run_id,
            "items": [
                {
                    "claim_id": str(item.id),
                    "claim_type": item.claim_type,
                    "statement": item.statement,
                    "evidence_ids": item.evidence_ids_json,
                    "confidence": item.confidence,
                    "is_inference": item.is_inference,
                    "limitations": item.limitations_json,
                    "falsifier": item.falsifier,
                    "validation": item.validation_json,
                }
                for item in rows
            ],
        }


@router.get("/today", tags=["research"])
async def today(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> dict[str, object]:
    requested_mode = requested_data_mode(request, data_mode)
    items = await list_releases(
        request.app.state.database_engine,
        limit=100,
        data_mode=requested_mode,
    )
    now = datetime.now(UTC)
    current = now.date()
    scheduled_today = [
        item
        for item in items
        if datetime.fromisoformat(str(item["scheduled_at"])).date() == current
    ]
    eligible = [
        item
        for item in items
        if item.get("status") == "released"
        and item.get("released_at") is not None
        and datetime.fromisoformat(str(item["scheduled_at"])) <= now
        and item.get("analysis_status") == "completed"
        and item.get("reproducibility_status") == "complete"
        and (requested_mode == "all" or item.get("data_mode") == requested_mode)
    ]
    eligible.sort(
        key=lambda item: str(
            item.get("analysis_completed_at") or item.get("released_at") or item.get("scheduled_at")
        ),
        reverse=True,
    )
    return {
        "date": current.isoformat(),
        "scheduled_releases": scheduled_today,
        "latest_research": eligible[:5],
        "latest_research_policy": {
            "data_mode": requested_mode,
            "requires_released": True,
            "requires_completed_analysis": True,
            "requires_reproducible_analysis": True,
            "excludes_fixture_from_observed": requested_mode == "observed",
        },
        "question": "今天的宏观信息改变了哪条政策、增长或通胀定价链？",
        "data_note": (
            "只展示当前数据模式下已发布、已完成且可复现的研究；没有符合条件的记录时保持空白。"
        ),
    }


@router.get("/calendar", tags=["releases"])
async def calendar(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, object]:
    items = await list_releases(
        request.app.state.database_engine,
        limit=500,
        data_mode=requested_data_mode(request),
    )
    lower = date_from or date.today()
    upper = date_to or lower
    visible = [
        item
        for item in items
        if lower <= datetime.fromisoformat(str(item["scheduled_at"])).date() <= upper
    ]
    return {
        "date_from": lower.isoformat(),
        "date_to": upper.isoformat(),
        "items": visible,
        "count": len(visible),
        "timezone_note": "筛选按API返回时间戳的UTC日历日执行；UI负责显示本地时区。",
    }


@router.get("/releases", tags=["releases"])
async def releases(
    request: Request,
    release_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> list[dict[str, object]]:
    return await list_releases(
        request.app.state.database_engine,
        release_type=release_type,
        limit=limit,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.post("/releases", tags=["releases"], dependencies=[Depends(require_write_access)])
async def create_release(
    payload: ReleaseCreateInput,
    request: Request,
) -> dict[str, str]:
    try:
        release_id = await create_manual_release(
            request.app.state.database_engine,
            release_key=payload.release_key,
            release_type=payload.release_type,
            title=payload.title,
            period_label=payload.period_label,
            scheduled_at=payload.scheduled_at,
            released_at=payload.released_at,
            source_timezone=payload.source_timezone,
            source_name=payload.source_name,
            source_url=payload.source_url,
            verified=payload.verified,
            values={key: item.model_dump() for key, item in payload.values.items()},
            stages=stage_payload(payload.stages),
            contamination_level=payload.contamination_level,
            clean_window=payload.clean_window,
            overlapping_events=payload.overlapping_events,
            confounding_notes=payload.confounding_notes,
        )
    except (LookupError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"release_id": release_id, "status": "created"}


@router.get("/releases/{release_id}", tags=["releases"])
async def release_detail(release_id: str, request: Request) -> object:
    return required(await get_release_detail(request.app.state.database_engine, release_id))


@router.get("/releases/{release_id}/stages", tags=["releases"])
async def release_stages(release_id: str, request: Request) -> object:
    detail = required(await get_release_detail(request.app.state.database_engine, release_id))
    return {
        "release_id": release_id,
        "items": detail["stages"],
    }


@router.get("/releases/{release_id}/values", tags=["releases"])
async def release_values(release_id: str, request: Request) -> object:
    detail = required(await get_release_detail(request.app.state.database_engine, release_id))
    return {
        "release_id": release_id,
        "items": detail["values"],
        "point_in_time": True,
    }


@router.get("/releases/{release_id}/consensus", tags=["releases"])
async def release_consensus(release_id: str, request: Request) -> object:
    try:
        release_uuid = uuid.UUID(release_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="macro release not found") from None
    factory = async_sessionmaker(request.app.state.database_engine, expire_on_commit=False)
    async with factory() as session:
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            raise HTTPException(status_code=404, detail="macro release not found")
        rows = (
            await session.execute(
                select(ConsensusSnapshot, Indicator)
                .join(Indicator, Indicator.id == ConsensusSnapshot.indicator_id)
                .where(
                    ConsensusSnapshot.macro_release_id == release_uuid,
                    ConsensusSnapshot.data_mode == release.data_mode,
                )
                .order_by(ConsensusSnapshot.captured_at)
            )
        ).all()
        return {
            "release_id": release_id,
            "items": [
                {
                    "id": str(snapshot.id),
                    "indicator_key": indicator.indicator_key,
                    "indicator_name": indicator.name,
                    "consensus_value": float(snapshot.consensus_value),
                    "source_name": snapshot.source_name,
                    "source_url": snapshot.source_url,
                    "captured_at": snapshot.captured_at.isoformat(),
                    "quality_grade": snapshot.quality_grade,
                    "is_manual": snapshot.is_manual,
                    "verification_notes": snapshot.verification_notes,
                    "available_before_t0": snapshot.captured_at < release.scheduled_at,
                    "metadata": snapshot.metadata_json,
                }
                for snapshot, indicator in rows
            ],
        }


@router.get("/releases/{release_id}/windows", tags=["analysis"])
async def release_windows(release_id: str, request: Request) -> object:
    return required(await get_release_windows(request.app.state.database_engine, release_id))


@router.get("/releases/{release_id}/timeline", tags=["analysis"])
async def release_timeline(release_id: str, request: Request) -> object:
    return required(await get_release_timeline(request.app.state.database_engine, release_id))


@router.get("/releases/{release_id}/reactions", tags=["analysis"])
async def release_reactions(release_id: str, request: Request) -> object:
    result = required(await get_release_windows(request.app.state.database_engine, release_id))
    return {
        "release_id": release_id,
        "analysis_run_id": result["analysis_run_id"],
        "items": result.get("reactions", []),
    }


@router.get("/releases/{release_id}/cross-asset", tags=["analysis"])
async def release_cross_asset(release_id: str, request: Request) -> object:
    return required(await get_release_timeline(request.app.state.database_engine, release_id))


@router.get("/releases/{release_id}/historical-matches", tags=["research"])
async def historical_matches(release_id: str, request: Request) -> object:
    return required(await get_release_historical(request.app.state.database_engine, release_id))


@router.get("/releases/{release_id}/explanations", tags=["research"])
async def explanations(release_id: str, request: Request) -> object:
    return required(await get_release_explanations(request.app.state.database_engine, release_id))


@router.get("/releases/{release_id}/hypotheses", tags=["research"])
async def hypotheses(release_id: str, request: Request) -> object:
    result = required(await get_release_explanations(request.app.state.database_engine, release_id))
    return {
        "release_id": release_id,
        "analysis_run_id": result["analysis_run_id"],
        "items": result["explanations"],
        "causality_policy": "These are competing attribution hypotheses, not unique causes.",
    }


@router.get("/releases/{release_id}/report", tags=["research"])
async def report(release_id: str, request: Request) -> object:
    result = required(await get_release_explanations(request.app.state.database_engine, release_id))
    return {
        "release_id": release_id,
        "analysis_run_id": result["analysis_run_id"],
        "format": "markdown",
        "content": result["report"],
        "validation": result["report_validation"],
    }


@router.get("/releases/{release_id}/evidence-pack", tags=["research"])
async def evidence_pack(release_id: str, request: Request) -> object:
    return required(await get_evidence_pack(request.app.state.database_engine, release_id))


@router.post(
    "/releases/{release_id}/consensus",
    tags=["releases"],
    dependencies=[Depends(require_write_access)],
)
async def capture_consensus(
    release_id: str,
    payload: ConsensusInput,
    request: Request,
) -> dict[str, str]:
    try:
        snapshot_id = await append_consensus(
            request.app.state.database_engine,
            release_id=release_id,
            indicator_key=payload.indicator_key,
            value=payload.consensus_value,
            source_name=payload.source_name,
            source_url=payload.source_url,
            captured_at=payload.captured_at,
            quality_grade=payload.quality_grade,
            is_manual=payload.is_manual,
            verification_notes=payload.verification_notes,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"release_id": release_id, "snapshot_id": snapshot_id, "status": "captured"}


@router.post(
    "/releases/{release_id}/market-bars/import",
    tags=["providers"],
    dependencies=[Depends(require_write_access)],
)
async def import_bars(
    release_id: str,
    payload: MarketCsvImportInput,
    request: Request,
) -> dict[str, object]:
    try:
        return await import_market_csv(
            request.app.state.database_engine,
            release_id=release_id,
            instrument_key=payload.instrument_key,
            csv_text=payload.csv_text,
            provider_key=payload.provider_key,
            source_name=payload.source_name,
            source_url=payload.source_url,
            verified=payload.verified,
            is_fixture=payload.is_fixture,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/releases/{release_id}/analysis-runs",
    tags=["analysis"],
    dependencies=[Depends(require_write_access)],
)
async def run_analysis(
    release_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    force: bool = Query(default=False),
) -> dict[str, str]:
    try:
        run_id = await analyze_release(
            request.app.state.database_engine,
            release_id,
            idempotency_key=idempotency_key,
            force=force,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"release_id": release_id, "analysis_run_id": run_id, "status": "completed"}


@router.get("/analysis-runs/{run_id}", tags=["analysis"])
async def analysis_run(run_id: str, request: Request) -> object:
    try:
        run_uuid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="analysis run not found") from None
    factory = async_sessionmaker(request.app.state.database_engine, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(AnalysisRun, run_uuid)
        if row is None:
            raise HTTPException(status_code=404, detail="analysis run not found")
        release = await session.get(MacroRelease, row.macro_release_id)
        return {
            "id": str(row.id),
            "release_id": str(row.macro_release_id),
            "release_key": release.release_key if release else None,
            "methodology_version": row.methodology_version,
            "code_version": row.code_version,
            "status": row.status,
            "started_at": row.started_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "classification": row.composite_classification,
            "surprise_score": row.composite_surprise_score,
            "confidence": row.confidence,
            "facts": row.facts_json,
            "earliest_reactions": row.earliest_reactions_json,
            "data_gaps": row.data_gaps_json,
            "parameters": row.parameters_json,
            "input_snapshot_hash": row.input_snapshot_hash,
            "config_hash": row.config_hash,
            "market_dataset_hash": row.market_dataset_hash,
            "historical_sample_hash": row.historical_sample_hash,
            "output_hash": row.output_hash,
            "reproducibility_status": row.reproducibility_status,
        }


@router.get("/instruments", tags=["market"])
async def instruments(request: Request) -> list[dict[str, object]]:
    factory = async_sessionmaker(request.app.state.database_engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.scalars(select(MarketInstrument).order_by(MarketInstrument.canonical_key))
        ).all()
        return [
            {
                "id": str(item.id),
                "key": item.canonical_key,
                "symbol": item.symbol,
                "title": item.title,
                "asset_class": item.asset_class,
                "instrument_type": item.instrument_type,
                "exchange": item.exchange,
                "quote_unit": item.quote_unit,
                "measurement_type": item.measurement_type,
                "is_proxy": item.is_proxy,
                "proxy_for": item.proxy_for,
            }
            for item in rows
        ]


@router.get("/data-quality", tags=["system"])
async def data_quality(request: Request) -> dict[str, object]:
    return await get_quality_overview(request.app.state.database_engine)


@router.get("/provider-runs", tags=["providers"])
async def provider_runs(request: Request) -> list[dict[str, object]]:
    return await get_provider_runs(request.app.state.database_engine)


@router.get("/providers", tags=["providers"])
async def providers(request: Request) -> dict[str, object]:
    runs = await get_provider_runs(request.app.state.database_engine)
    grouped: dict[str, list[dict[str, object]]] = {}
    for run in runs:
        grouped.setdefault(str(run["provider_key"]), []).append(run)
    return {
        "items": [
            {
                "provider_key": key,
                "latest_status": items[0].get("status"),
                "latest_completed_at": items[0].get("completed_at"),
                "quality_grade": items[0].get("quality_grade"),
                "operations": sorted({str(item.get("operation")) for item in items}),
                "run_count": len(items),
            }
            for key, items in sorted(grouped.items())
        ],
        "fallback_policy": "Provider attempts and quality grades remain traceable.",
    }


@router.get("/regime", tags=["research"])
async def regime(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> dict[str, object]:
    return await get_current_regime(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.get("/regimes", tags=["research"])
async def regimes(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> dict[str, object]:
    return await get_current_regime(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.get("/world-state", tags=["macro"])
async def world_state(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Return the deterministic, point-in-time macro state snapshot.

    This endpoint is intentionally separate from the event-regime endpoint:
    ``/regime`` describes the pre-event context attached to a research run,
    while this response describes the latest series state for the terminal.
    """
    mode = requested_data_mode(request, data_mode)
    return await build_world_state(
        request.app.state.database_engine, data_mode=mode, as_of=as_of
    )


@router.get("/global-macro", tags=["macro"])
async def global_macro(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
    as_of: datetime | None = None,
) -> dict[str, object]:
    return await build_global_macro(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
        as_of=as_of,
    )


@router.get("/macro-systems", tags=["macro"])
async def macro_systems(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> dict[str, object]:
    return await build_macro_systems(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.get("/daily-brief", tags=["macro"])
async def daily_brief(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Build the deterministic daily entry point used by the Today workspace."""
    mode = requested_data_mode(request, data_mode)
    return await build_daily_brief(
        request.app.state.database_engine, data_mode=mode, as_of=as_of
    )


@router.get("/market-dashboard", tags=["market"])
async def market_dashboard(
    request: Request,
    horizon: Literal["1d", "1w", "1m", "3m"] = Query(default="1d"),
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
    as_of: datetime | None = None,
) -> dict[str, object]:
    return await build_market_dashboard(
        request.app.state.database_engine,
        horizon=horizon,
        data_mode=requested_data_mode(request, data_mode),
        as_of=as_of,
    )


@router.get("/series", tags=["macro"])
async def series_search(
    request: Request,
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> list[dict[str, object]]:
    return await search_series(
        request.app.state.database_engine,
        query=q,
        limit=limit,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.get("/series/{canonical_key:path}", tags=["macro"])
async def series_history(
    canonical_key: str,
    request: Request,
    transform: str = Query(default="raw"),
    limit: int = Query(default=240, ge=1, le=2000),
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> object:
    return required(
        await get_series_history(
            request.app.state.database_engine,
            canonical_key,
            transform=transform,
            limit=limit,
            data_mode=requested_data_mode(request, data_mode),
        ),
        "series not found",
    )


@router.get("/methodology", tags=["system"])
async def methodology() -> dict[str, object]:
    return {
        "version": METHODOLOGY_VERSION,
        "workflow": [
            "point-in-time release and consensus",
            "surprise calculation",
            "stage-relative market windows",
            "volatility-adjusted earliest observed reaction",
            "fixed-recipe historical matching",
            "competing macro hypotheses",
            "EvidencePack",
            "deterministic World State",
            "Daily Macro Brief and Top Changes",
            "cross-asset market dashboard",
            "Series Explorer and Thesis Book",
            "global macro coverage map",
            "optional AI summary",
        ],
        "historical_sample_policy": {
            "robust_statistics": ROBUST_SAMPLE,
            "limited_statistics": LIMITED_STATISTICAL_SAMPLE,
            "case_studies": CASE_STUDY_SAMPLE,
            "probability_minimum": LIMITED_STATISTICAL_SAMPLE,
        },
        "causality_policy": "No unique deterministic cause is emitted.",
        "proxy_policy": "Proxy instruments remain explicitly labelled in every response.",
        "fixture_policy": "Fixture data is traceable and never presented as observed market data.",
    }


@router.get("/methods", tags=["system"])
async def methods() -> dict[str, object]:
    return await methodology()


@router.post("/world-state/snapshot", tags=["macro"], dependencies=[Depends(require_write_access)])
async def world_state_snapshot(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> dict[str, object]:
    return await persist_world_state_snapshot(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.get("/world-state/history", tags=["macro"])
async def world_state_history(
    request: Request,
    limit: int = Query(default=30, ge=1, le=365),
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> list[dict[str, object]]:
    return await list_world_state_snapshots(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
        limit=limit,
    )


@router.get("/watchlist", tags=["research"])
async def watchlist(request: Request) -> list[dict[str, object]]:
    return await list_watchlist(request.app.state.database_engine)


@router.post("/watchlist", tags=["research"], dependencies=[Depends(require_write_access)])
async def watchlist_add(payload: WatchlistInput, request: Request) -> dict[str, object]:
    return await add_watchlist_item(
        request.app.state.database_engine,
        item_type=payload.item_type,
        item_key=payload.item_key,
        label=payload.label,
        notes=payload.notes,
        data_mode=payload.data_mode,
    )


@router.delete(
    "/watchlist/{item_id}",
    tags=["research"],
    dependencies=[Depends(require_write_access)],
)
async def watchlist_delete(item_id: str, request: Request) -> dict[str, object]:
    try:
        identifier = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="watchlist item id must be a UUID") from exc
    if not await remove_watchlist_item(request.app.state.database_engine, identifier):
        raise HTTPException(status_code=404, detail="watchlist item not found")
    return {"status": "deleted", "id": item_id}


@router.post("/research/assistant", tags=["research"])
async def research_assistant(payload: AssistantInput, request: Request) -> dict[str, object]:
    pack = await get_evidence_pack(request.app.state.database_engine, payload.release_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="macro release not found")
    try:
        return await answer_question(
            question=payload.question,
            pack=pack,
            settings=request.app.state.settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/theses", tags=["research"])
async def theses(
    request: Request,
    data_mode: Literal["observed", "fixture", "all"] | None = Query(default=None),
) -> list[dict[str, object]]:
    return await list_theses(
        request.app.state.database_engine,
        data_mode=requested_data_mode(request, data_mode),
    )


@router.post("/theses", tags=["research"], dependencies=[Depends(require_write_access)])
async def thesis_create(payload: ThesisInput, request: Request) -> dict[str, object]:
    try:
        return await create_thesis(
            request.app.state.database_engine,
            payload.model_dump(),
            data_mode=requested_data_mode(request),
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/theses/{thesis_id}", tags=["research"])
async def thesis_detail(thesis_id: str, request: Request) -> object:
    try:
        result = await get_thesis(request.app.state.database_engine, thesis_id)
    except ValueError:
        result = None
    return required(result, "thesis not found")


@router.patch(
    "/theses/{thesis_id}", tags=["research"], dependencies=[Depends(require_write_access)]
)
async def thesis_update(
    thesis_id: str,
    payload: ThesisUpdateInput,
    request: Request,
) -> object:
    values = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        result = await update_thesis(request.app.state.database_engine, thesis_id, values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return required(result, "thesis not found")


@router.get("/theses/{thesis_id}/evaluate", tags=["research"])
async def thesis_evaluate(thesis_id: str, request: Request) -> object:
    try:
        result = await evaluate_thesis(request.app.state.database_engine, thesis_id)
    except ValueError:
        result = None
    return required(result, "thesis not found")


@router.post("/research/assistant/context", tags=["research"])
async def context_assistant(
    payload: ContextAssistantInput,
    request: Request,
) -> dict[str, object]:
    """Answer broad research questions from the deterministic terminal context.

    This endpoint deliberately returns a structured context bundle first.  A
    configured AI provider may be added on top without allowing it to compute
    state or invent evidence.
    """
    brief = await build_daily_brief(
        request.app.state.database_engine,
        data_mode=payload.data_mode,
    )
    state = brief["world_state"]
    dimensions = state["dimensions"]
    facts = [
        {
            "claim_type": "fact",
            "statement": f"当前 regime：{state['regime']['label']}",
            "evidence_ids": [
                evidence_id
                for dimension in dimensions.values()
                for driver in dimension.get("top_drivers", [])
                for evidence_id in driver.get("evidence_ids", [])
            ],
            "confidence": state["regime"]["confidence"],
            "is_inference": False,
            "limitations": state["limitations"],
            "falsifier": "下一次有效数据更新后状态标签发生变化。",
        },
    ]
    return {
        "question": payload.question,
        "mode": "deterministic_context",
        "provider": request.app.state.settings.resolved_ai_provider,
        "facts": facts,
        "world_state": state,
        "biggest_changes": brief["biggest_changes"],
        "answer": (
            "已确认事实："
            f"{state['regime']['label']}。\n"
            "当前推断：请结合 Top Changes 和各维度驱动阅读；"
            "系统不会把相关性写成唯一因果。\n"
            "无法确认：自然语言问题需要更多指定事件或来源证据。"
        ),
        "limitations": brief["limitations"],
    }


# Data Foundation has public read routes and separately protected state-changing routes.
router.include_router(data_router)
router.include_router(data_write_router, dependencies=[Depends(require_write_access)])
