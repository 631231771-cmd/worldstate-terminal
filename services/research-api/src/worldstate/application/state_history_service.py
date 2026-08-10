"""Persist and query reproducible daily World State snapshots."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.daily_brief_service import build_daily_brief
from worldstate.application.world_state_service import build_world_state
from worldstate.db.models import WatchlistItem, WorldStateSnapshot

DataMode = Literal["observed", "fixture", "all"]


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _serialize_snapshot(row: WorldStateSnapshot) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "snapshot_date": row.snapshot_date.isoformat(),
        "as_of": row.as_of.isoformat(),
        "methodology_version": row.methodology_version,
        "data_mode": row.data_mode,
        "dimensions": row.dimensions_json,
        "regime": row.regime_json,
        "top_changes": row.top_changes_json,
        "evidence": row.evidence_json,
        "data_gaps": row.data_gaps_json,
        "source_snapshot_hash": row.source_snapshot_hash,
        "created_at": row.created_at.isoformat(),
    }


async def persist_world_state_snapshot(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    timestamp = as_of or datetime.now(UTC)
    state = await build_world_state(engine, data_mode=data_mode, as_of=timestamp)
    brief = await build_daily_brief(engine, data_mode=data_mode, as_of=timestamp)
    source_payload = {
        "dimensions": state.get("dimensions", {}),
        "regime": state.get("regime", {}),
        # Daily brief calls this field ``biggest_changes``.  Keep the
        # persisted snapshot contract stable as ``top_changes`` while using
        # the actual brief payload as the source of truth.
        "top_changes": brief.get("biggest_changes", []),
        "data_gaps": state.get("data_gaps", []),
        "data_mode": data_mode,
        "as_of": timestamp.isoformat(),
    }
    source_hash = _hash_payload(source_payload)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(WorldStateSnapshot).where(
                WorldStateSnapshot.snapshot_date == timestamp.date(),
                WorldStateSnapshot.data_mode == data_mode,
            )
        )
        if row is None:
            row = WorldStateSnapshot(
                id=uuid.uuid4(),
                snapshot_date=timestamp.date(),
                as_of=timestamp,
                methodology_version="wst-state-v1",
                data_mode=data_mode,
                dimensions_json=state.get("dimensions", {}),
                regime_json=state.get("regime", {}),
                top_changes_json=brief.get("biggest_changes", []),
                evidence_json=state.get("evidence", []),
                data_gaps_json=state.get("data_gaps", []),
                source_snapshot_hash=source_hash,
                created_at=timestamp,
            )
            session.add(row)
        else:
            # A snapshot is immutable for a day/mode.  If a later sync produces
            # different data, it is represented by the next day's snapshot.
            pass
        await session.flush()
        return _serialize_snapshot(row)


async def list_world_state_snapshots(
    engine: AsyncEngine,
    *,
    data_mode: DataMode = "observed",
    limit: int = 30,
) -> list[dict[str, Any]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(WorldStateSnapshot)
                .where(WorldStateSnapshot.data_mode == data_mode)
                .order_by(WorldStateSnapshot.snapshot_date.desc())
                .limit(max(1, min(limit, 365)))
            )
        ).all()
        return [_serialize_snapshot(row) for row in rows]


async def list_watchlist(engine: AsyncEngine) -> list[dict[str, Any]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            await session.scalars(
                select(WatchlistItem).order_by(WatchlistItem.updated_at.desc())
            )
        ).all()
        return [
            {
                "id": str(row.id),
                "item_type": row.item_type,
                "item_key": row.item_key,
                "label": row.label,
                "notes": row.notes,
                "data_mode": row.data_mode,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]


async def add_watchlist_item(
    engine: AsyncEngine,
    *,
    item_type: str,
    item_key: str,
    label: str,
    notes: str = "",
    data_mode: str = "observed",
) -> dict[str, Any]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.item_type == item_type,
                WatchlistItem.item_key == item_key,
            )
        )
        if row is None:
            row = WatchlistItem(
                id=uuid.uuid4(),
                item_type=item_type,
                item_key=item_key,
                label=label,
                notes=notes,
                data_mode=data_mode,
            )
            session.add(row)
        else:
            row.label = label
            row.notes = notes
            row.data_mode = data_mode
        await session.flush()
        return {
            "id": str(row.id),
            "item_type": row.item_type,
            "item_key": row.item_key,
            "label": row.label,
            "notes": row.notes,
            "data_mode": row.data_mode,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }


async def remove_watchlist_item(engine: AsyncEngine, item_id: uuid.UUID) -> bool:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.get(WatchlistItem, item_id)
        if row is None:
            return False
        await session.delete(row)
        return True


__all__ = [
    "add_watchlist_item",
    "list_watchlist",
    "list_world_state_snapshots",
    "persist_world_state_snapshot",
    "remove_watchlist_item",
]
