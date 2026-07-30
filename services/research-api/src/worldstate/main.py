"""FastAPI application for the WorldState Macro Research Terminal."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import make_asgi_app

from worldstate import __version__
from worldstate.api import router
from worldstate.application.events import bootstrap_research_data
from worldstate.config import Settings
from worldstate.db.session import create_engine
from worldstate.logging import configure_logging
from worldstate.macro_core.errors import MacroEngineError


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved
        app.state.database_engine = create_engine(resolved.database_url)
        await bootstrap_research_data(app.state.database_engine)
        yield
        await app.state.database_engine.dispose()

    app = FastAPI(
        title="WorldState Macro Research API",
        description=(
            "Point-in-time macro releases, cross-asset reaction windows, fixed-recipe "
            "historical comparison, competing explanations, and EvidencePack."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "tauri://localhost",
            "https://tauri.localhost",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))[:128]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    @app.exception_handler(MacroEngineError)
    async def macro_error_handler(_request: Request, exc: MacroEngineError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "code": exc.code,
                "message": exc.message,
                "generated_at": datetime.now(UTC).isoformat(),
            },
        )

    app.include_router(router)
    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()
