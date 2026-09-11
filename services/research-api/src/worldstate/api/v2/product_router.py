"""Stable product projections consumed by the Terminal UI."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from worldstate.api.v2.schemas import (
    ProductCountryResponse,
    ProductEventDetail,
    ProductEventsResponse,
    ProductMacroResponse,
    ProductMarketsResponse,
    ProductTodayResponse,
)
from worldstate.application.product_projection_service import (
    build_country_projection,
    build_event_detail_projection,
    build_events_projection,
    build_macro_projection,
    build_markets_projection,
    build_today_projection,
)

DataMode = Literal["observed", "fixture", "all"]
product_router = APIRouter(prefix="/product", tags=["product"])


def _requested_data_mode(request: Request, explicit: DataMode | None) -> DataMode:
    if explicit is not None:
        return explicit
    return "all" if request.app.state.settings.demo_mode else "observed"


@product_router.get("/today", response_model=ProductTodayResponse)
async def product_today(
    request: Request,
    data_mode: Annotated[DataMode | None, Query()] = None,
    as_of: datetime | None = None,
) -> dict[str, object]:
    """Capability-driven first-screen projection for the terminal shell."""
    return await build_today_projection(
        request.app.state.database_engine,
        data_mode=_requested_data_mode(request, data_mode),
        as_of=as_of,
    )


@product_router.get("/markets", response_model=ProductMarketsResponse)
async def product_markets(
    request: Request,
    data_mode: Annotated[DataMode, Query()] = "observed",
) -> dict[str, object]:
    return await build_markets_projection(request.app.state.database_engine, data_mode=data_mode)


@product_router.get("/macro", response_model=ProductMacroResponse)
async def product_macro(
    request: Request,
    data_mode: Annotated[DataMode, Query()] = "observed",
) -> dict[str, object]:
    return await build_macro_projection(request.app.state.database_engine, data_mode=data_mode)


@product_router.get("/macro/{country_key}", response_model=ProductCountryResponse)
async def product_country(
    country_key: str,
    request: Request,
    dimension: Annotated[str | None, Query()] = None,
    data_mode: Annotated[DataMode, Query()] = "observed",
) -> dict[str, object]:
    detail = await build_country_projection(
        request.app.state.database_engine,
        country_key.upper(),
        data_mode=data_mode,
        dimension=dimension,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="country not found")
    return detail


@product_router.get("/events", response_model=ProductEventsResponse)
async def product_events(
    request: Request,
    data_mode: Annotated[DataMode, Query()] = "observed",
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> dict[str, object]:
    return await build_events_projection(
        request.app.state.database_engine,
        data_mode=data_mode,
        limit=limit,
    )


@product_router.get("/events/{release_id}", response_model=ProductEventDetail)
async def product_event_detail(
    release_id: str,
    request: Request,
    data_mode: Annotated[DataMode, Query()] = "observed",
) -> dict[str, object]:
    detail = await build_event_detail_projection(
        request.app.state.database_engine,
        release_id,
        data_mode=data_mode,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="event not found")
    return detail


__all__ = ["product_router"]
