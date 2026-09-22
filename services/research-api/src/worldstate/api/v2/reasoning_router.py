"""API surface for the source-to-mechanism reasoning workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from worldstate.application.official_evidence_service import sync_official_evidence
from worldstate.application.reasoning_service import (
    assess_author_claim,
    create_research_source,
    extract_author_claim,
    list_playbooks,
    list_reasoning_cases,
    review_author_claim,
)

reasoning_read_router = APIRouter(prefix="/reasoning", tags=["reasoning"])
reasoning_write_router = APIRouter(prefix="/reasoning", tags=["reasoning"])


@reasoning_write_router.post("/evidence/sync")
async def evidence_sync(request: Request) -> dict[str, object]:
    return await sync_official_evidence(request.app.state.database_engine)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchSourceInput(StrictModel):
    title: str = Field(min_length=1, max_length=512)
    author: str = Field(min_length=1, max_length=255)
    source_type: Literal["article", "report", "transcript", "note", "book", "other"]
    source_url: str | None = Field(default=None, max_length=2048)
    published_at: AwareDatetime | None = None
    content_text: str = Field(min_length=10, max_length=200_000)
    notes: str = Field(default="", max_length=10_000)
    data_mode: Literal["observed", "fixture"] = "observed"


class AuthorClaimExtractionInput(StrictModel):
    statement: str = Field(min_length=3, max_length=4000)
    exact_quote: str = Field(min_length=1, max_length=20_000)
    extraction_method: Literal["manual", "ai"] = "manual"
    extractor_model: str | None = Field(default=None, max_length=128)


class AuthorClaimReviewInput(StrictModel):
    decision: Literal["confirmed", "rejected"]
    mechanism_key: str | None = Field(default=None, max_length=128)
    review_notes: str = Field(default="", max_length=10_000)


class MechanismAssessmentInput(StrictModel):
    as_of: AwareDatetime | None = None


@reasoning_read_router.get("/playbooks")
async def playbooks() -> dict[str, object]:
    return list_playbooks()


@reasoning_read_router.get("/cases")
async def cases(
    request: Request,
    data_mode: Literal["observed", "fixture"] = Query(default="observed"),
) -> list[dict[str, object]]:
    return await list_reasoning_cases(request.app.state.database_engine, data_mode=data_mode)


@reasoning_write_router.post("/sources", status_code=201)
async def source_create(payload: ResearchSourceInput, request: Request) -> dict[str, object]:
    return await create_research_source(
        request.app.state.database_engine,
        title=payload.title,
        author=payload.author,
        source_type=payload.source_type,
        content_text=payload.content_text,
        source_url=payload.source_url,
        published_at=payload.published_at,
        notes=payload.notes,
        data_mode=payload.data_mode,
    )


@reasoning_write_router.post("/sources/{source_id}/claims", status_code=201)
async def claim_extract(
    source_id: str, payload: AuthorClaimExtractionInput, request: Request
) -> dict[str, object]:
    try:
        result = await extract_author_claim(
            request.app.state.database_engine,
            source_id,
            statement=payload.statement,
            exact_quote=payload.exact_quote,
            extraction_method=payload.extraction_method,
            extractor_model=payload.extractor_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="research source not found")
    return result


@reasoning_write_router.patch("/claims/{claim_id}")
async def claim_review(
    claim_id: str, payload: AuthorClaimReviewInput, request: Request
) -> dict[str, object]:
    try:
        result = await review_author_claim(
            request.app.state.database_engine,
            claim_id,
            decision=payload.decision,
            mechanism_key=payload.mechanism_key,
            review_notes=payload.review_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="author claim not found")
    return result


@reasoning_write_router.post("/claims/{claim_id}/assessments", status_code=201)
async def claim_assess(
    claim_id: str, payload: MechanismAssessmentInput, request: Request
) -> dict[str, object]:
    cutoff: datetime | None = payload.as_of
    try:
        result = await assess_author_claim(
            request.app.state.database_engine, claim_id, as_of=cutoff
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="author claim not found")
    return result
