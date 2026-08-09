"""Point-in-time consensus capture commands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.data_foundation_service import assert_matching_data_mode
from worldstate.db.models import ConsensusSnapshot, Indicator, MacroRelease


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def append_consensus(
    engine: AsyncEngine,
    *,
    release_id: str,
    indicator_key: str,
    value: Decimal,
    source_name: str,
    source_url: str | None,
    captured_at: datetime,
    quality_grade: str,
    is_manual: bool,
    verification_notes: str | None,
) -> str:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        release = await session.get(MacroRelease, uuid.UUID(release_id))
        if release is None:
            raise LookupError("macro release not found")
        if _aware(captured_at) >= _aware(release.released_at or release.scheduled_at):
            raise ValueError("consensus snapshot must be captured before release T0")
        assert_matching_data_mode(release.data_mode, release.data_mode, "consensus_snapshot")
        indicator = await session.scalar(
            select(Indicator).where(Indicator.indicator_key == indicator_key)
        )
        if indicator is None:
            raise LookupError("indicator not found")
        snapshot = ConsensusSnapshot(
            id=uuid.uuid4(),
            macro_release_id=release.id,
            indicator_id=indicator.id,
            consensus_value=value,
            source_name=source_name,
            source_url=source_url,
            captured_at=_aware(captured_at),
            quality_grade=quality_grade,
            is_manual=is_manual,
            data_mode=release.data_mode,
            verification_notes=verification_notes,
            source_artifact_id=None,
            quality_id=None,
        )
        session.add(snapshot)
        await session.flush()
        return str(snapshot.id)


__all__ = ["append_consensus"]
