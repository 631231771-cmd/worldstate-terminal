"""Read-only Macro Terminal API."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from macro_engine.services.terminal import build_snapshot, list_series, query_series

router = APIRouter(prefix="/v1", tags=["terminal"])


@router.get("/snapshot")
async def snapshot(request: Request) -> dict[str, object]:
    return await build_snapshot(
        request.app.state.database_engine,
        request.app.state.settings,
    )


@router.get("/series")
async def series_catalog(request: Request) -> list[dict[str, object]]:
    return await list_series(request.app.state.database_engine)


@router.get("/series/{canonical_key}")
async def series_detail(
    canonical_key: str,
    request: Request,
    transform: str = "level",
    as_of: datetime | None = None,
) -> dict[str, object]:
    try:
        result = await query_series(
            request.app.state.database_engine,
            canonical_key,
            transform=transform,
            as_of=as_of or datetime.now(UTC),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="series not found")
    return result
