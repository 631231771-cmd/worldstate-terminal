"""Durable, user-owned research theses with deterministic evidence links."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.daily_brief_service import build_daily_brief
from worldstate.application.world_state_service import build_world_state
from worldstate.db.models import Thesis

DataMode = Literal["observed", "fixture", "all"]
VALID_STATUSES = {"active", "paused", "falsified", "confirmed", "archived"}


def _serialize(row: Thesis) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "thesis": row.thesis,
        "horizon": row.horizon,
        "confidence": row.confidence,
        "status": row.status,
        "entities": row.entities_json,
        "related_states": row.related_states_json,
        "supporting_evidence": row.supporting_evidence_json,
        "contradicting_evidence": row.contradicting_evidence_json,
        "confirmation_conditions": row.confirmation_conditions_json,
        "falsification_conditions": row.falsification_conditions_json,
        "watch_variables": row.watch_variables_json,
        "notes": row.notes,
        "history": row.history_json,
        "data_mode": row.data_mode,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def list_theses(
    engine: AsyncEngine, *, data_mode: DataMode = "observed"
) -> list[dict[str, Any]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        query = select(Thesis).order_by(Thesis.updated_at.desc())
        if data_mode != "all":
            query = query.where(Thesis.data_mode == data_mode)
        return [_serialize(row) for row in (await session.scalars(query)).all()]


async def get_thesis(engine: AsyncEngine, thesis_id: str) -> dict[str, Any] | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        row = await session.get(Thesis, uuid.UUID(thesis_id))
        return _serialize(row) if row else None


async def create_thesis(
    engine: AsyncEngine, payload: dict[str, Any], *, data_mode: DataMode = "observed"
) -> dict[str, Any]:
    confidence = float(payload.get("confidence", 0.5))
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    status = str(payload.get("status", "active"))
    if status not in VALID_STATUSES:
        raise ValueError("invalid thesis status")
    now = datetime.now(UTC)
    row = Thesis(
        title=str(payload["title"]).strip(),
        thesis=str(payload["thesis"]).strip(),
        horizon=str(payload.get("horizon", "未来 3 个月")),
        confidence=confidence,
        status=status,
        entities_json=list(payload.get("entities", [])),
        related_states_json=list(payload.get("related_states", [])),
        supporting_evidence_json=list(payload.get("supporting_evidence", [])),
        contradicting_evidence_json=list(payload.get("contradicting_evidence", [])),
        confirmation_conditions_json=list(payload.get("confirmation_conditions", [])),
        falsification_conditions_json=list(payload.get("falsification_conditions", [])),
        watch_variables_json=list(payload.get("watch_variables", [])),
        notes=str(payload.get("notes", "")),
        history_json=[{"at": now.isoformat(), "action": "created", "status": status}],
        data_mode=data_mode,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(row)
        await session.flush()
        return _serialize(row)


async def update_thesis(
    engine: AsyncEngine, thesis_id: str, payload: dict[str, Any]
) -> dict[str, Any] | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.get(Thesis, uuid.UUID(thesis_id))
        if row is None:
            return None
        if "status" in payload and payload["status"] not in VALID_STATUSES:
            raise ValueError("invalid thesis status")
        if "confidence" in payload and not 0 <= float(payload["confidence"]) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        allowed = {
            "title",
            "thesis",
            "horizon",
            "confidence",
            "status",
            "entities_json",
            "related_states_json",
            "supporting_evidence_json",
            "contradicting_evidence_json",
            "confirmation_conditions_json",
            "falsification_conditions_json",
            "watch_variables_json",
            "notes",
        }
        for key, value in payload.items():
            target = (
                f"{key}_json"
                if key
                in {
                    "entities",
                    "related_states",
                    "supporting_evidence",
                    "contradicting_evidence",
                    "confirmation_conditions",
                    "falsification_conditions",
                    "watch_variables",
                }
                else key
            )
            if target in allowed:
                setattr(row, target, value)
        row.updated_at = datetime.now(UTC)
        row.history_json = [
            *row.history_json,
            {"at": row.updated_at.isoformat(), "action": "updated", "fields": sorted(payload)},
        ]
        await session.flush()
        return _serialize(row)


async def evaluate_thesis(engine: AsyncEngine, thesis_id: str) -> dict[str, Any] | None:
    thesis = await get_thesis(engine, thesis_id)
    if thesis is None:
        return None
    mode = cast(DataMode, str(thesis["data_mode"]))
    state = await build_world_state(engine, data_mode=mode)
    brief = await build_daily_brief(engine, data_mode=mode)
    related = {str(item) for item in thesis["related_states"]}
    watch = {str(item).lower() for item in thesis["watch_variables"]}
    signals: list[dict[str, Any]] = []
    for key, dimension in state["dimensions"].items():
        if related and key not in related:
            continue
        matched = [
            driver
            for driver in dimension["top_drivers"]
            if driver["series_key"].lower() in watch or driver["title"].lower() in watch
        ]
        signals.append(
            {
                "dimension": key,
                "score": dimension["score"],
                "direction": dimension["direction"],
                "matched_watch_variables": matched,
                "evidence_ids": [
                    evidence for driver in matched for evidence in driver["evidence_ids"]
                ],
            }
        )
    return {
        "thesis": thesis,
        "as_of": state["as_of"],
        "state_signals": signals,
        "recent_changes": brief["biggest_changes"][:5],
        "interpretation": (
            "系统只提示与 Thesis 相关的状态和证据，不自动修改用户观点或确认/证伪 Thesis。"
        ),
        "limitations": ["自然语言 Thesis 的方向无法由系统自动判定；请由用户确认条件。"],
    }
