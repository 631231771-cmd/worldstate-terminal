"""Daily world briefing and evidence-grounded tutor API."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from macro_engine.services.ai_tutor import answer_tutor
from macro_engine.services.world_briefing import build_world_briefing

router = APIRouter(prefix="/v1/world", tags=["world-intelligence"])

_CACHE_SECONDS = 300.0
_briefing_cache: tuple[float, dict[str, object]] | None = None
_briefing_lock = asyncio.Lock()


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class TutorRequest(BaseModel):
    question: str = Field(min_length=2, max_length=3000)
    mode: Literal["beginner", "deep", "socratic"] = "beginner"
    history: list[ConversationMessage] = Field(default_factory=list, max_length=8)


async def cached_briefing(request: Request, *, fresh: bool = False) -> dict[str, object]:
    """Coalesce public upstream calls and retain a five-minute research snapshot."""

    global _briefing_cache
    now = monotonic()
    if not fresh and _briefing_cache and now - _briefing_cache[0] < _CACHE_SECONDS:
        return _briefing_cache[1]
    async with _briefing_lock:
        now = monotonic()
        if not fresh and _briefing_cache and now - _briefing_cache[0] < _CACHE_SECONDS:
            return _briefing_cache[1]
        briefing = await build_world_briefing(
            request.app.state.database_engine,
            request.app.state.settings,
        )
        _briefing_cache = (now, briefing)
        return briefing


@router.get("/briefing")
async def world_briefing(
    request: Request,
    fresh: bool = Query(default=False),
) -> dict[str, object]:
    """Return today's ranked events, market moves, causal chains, and lesson."""

    return await cached_briefing(request, fresh=fresh)


@router.get("/ai-status")
async def ai_status(request: Request) -> dict[str, object]:
    """Describe the selected tutor provider without exposing credentials."""

    settings = request.app.state.settings
    provider = settings.resolved_ai_provider
    return {
        "provider": provider,
        "available": provider != "none",
        "model": settings.ollama_model if provider == "ollama" else settings.ai_model,
        "fallback": "evidence-rules-v1",
    }


@router.post("/ask")
async def ask_world_tutor(payload: TutorRequest, request: Request) -> dict[str, object]:
    """Answer from the same evidence snapshot shown in the terminal."""

    briefing = await cached_briefing(request)
    return await answer_tutor(
        request.app.state.settings,
        payload.question,
        payload.mode,
        briefing,
        [message.model_dump() for message in payload.history],
    )
