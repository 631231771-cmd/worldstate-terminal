"""CPI Event Lab read and controlled-write API."""

from __future__ import annotations

from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from macro_engine.config import Settings
from macro_engine.event_lab.schemas import (
    ConsensusCaptureInput,
    CpiEventInput,
    CsvMarketImportInput,
)
from macro_engine.event_lab.service import (
    analyze_event,
    append_consensus_snapshot,
    cpi_event_lab_summary,
    get_cpi_event_detail,
    import_market_csv,
    list_cpi_events,
    upsert_cpi_event,
)

router = APIRouter(prefix="/v1/events", tags=["event-lab"])

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_LOCAL_ORIGINS = {
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
}


def require_event_lab_write_access(
    request: Request,
    authorization: str | None = Header(default=None),
    x_write_token: str | None = Header(default=None),
) -> None:
    """Allow desktop-local writes or an explicitly enabled server write token."""

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
            detail="event lab writes require a local desktop request or configured write token",
        )


@router.get("/lab/status")
async def event_lab_status(request: Request) -> dict[str, object]:
    return await cpi_event_lab_summary(request.app.state.database_engine)


@router.get("")
async def event_list(request: Request, event_type: str = "US_CPI") -> list[dict[str, object]]:
    if event_type != "US_CPI":
        return []
    return await list_cpi_events(request.app.state.database_engine)


@router.get("/{event_id}")
async def event_detail(event_id: str, request: Request) -> dict[str, object]:
    result = await get_cpi_event_detail(request.app.state.database_engine, event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="CPI event not found")
    return result


@router.post("/cpi", dependencies=[Depends(require_event_lab_write_access)])
async def create_or_update_cpi_event(
    payload: CpiEventInput,
    request: Request,
) -> dict[str, str]:
    try:
        event_id = await upsert_cpi_event(request.app.state.database_engine, payload)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": event_id, "status": "analyzed"}


@router.post("/{event_id}/consensus", dependencies=[Depends(require_event_lab_write_access)])
async def capture_consensus(
    event_id: str,
    payload: ConsensusCaptureInput,
    request: Request,
) -> dict[str, str]:
    try:
        await append_consensus_snapshot(
            request.app.state.database_engine,
            event_id,
            payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": event_id, "status": "consensus_snapshot_appended"}


@router.post(
    "/{event_id}/market-bars/import",
    dependencies=[Depends(require_event_lab_write_access)],
)
async def import_event_market_bars(
    event_id: str,
    payload: CsvMarketImportInput,
    request: Request,
) -> dict[str, object]:
    try:
        return await import_market_csv(
            request.app.state.database_engine,
            event_id,
            payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{event_id}/analyze", dependencies=[Depends(require_event_lab_write_access)])
async def rerun_event_analysis(event_id: str, request: Request) -> dict[str, str]:
    try:
        await analyze_event(request.app.state.database_engine, event_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": event_id, "status": "analyzed"}
