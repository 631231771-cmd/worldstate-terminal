"""Point-in-time consensus capture commands."""

from __future__ import annotations

import csv
import io
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


async def import_consensus_csv(
    engine: AsyncEngine,
    *,
    release_id: str,
    csv_text: str,
    default_source_name: str = "Manual consensus CSV",
    default_source_url: str | None = None,
) -> dict[str, object]:
    """Append pre-release consensus snapshots from a traceable CSV file."""
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"indicator_key", "consensus_value", "captured_at"}
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
    captured: list[str] = []
    warnings: list[str] = []
    for row_number, row in enumerate(reader, start=2):
        indicator_key = str(row.get("indicator_key") or "").strip()
        value_text = str(row.get("consensus_value") or "").strip()
        captured_at_text = str(row.get("captured_at") or "").strip()
        if not indicator_key or not value_text or not captured_at_text:
            warnings.append(
                f"row {row_number}: indicator_key, consensus_value and captured_at are required"
            )
            continue
        try:
            value = Decimal(value_text)
            captured_at = datetime.fromisoformat(captured_at_text.replace("Z", "+00:00"))
            if captured_at.tzinfo is None:
                raise ValueError("captured_at must include an explicit timezone")
            snapshot_id = await append_consensus(
                engine,
                release_id=release_id,
                indicator_key=indicator_key,
                value=value,
                source_name=str(row.get("source_name") or default_source_name),
                source_url=str(row.get("source_url") or default_source_url or "") or None,
                captured_at=captured_at,
                quality_grade=str(row.get("quality_grade") or "C").upper(),
                is_manual=True,
                verification_notes=(
                    str(row.get("verification_notes") or "Imported from user CSV")
                ),
            )
            captured.append(snapshot_id)
        except (ValueError, LookupError, ArithmeticError) as exc:
            warnings.append(f"row {row_number}: {exc}")
    if not captured and warnings:
        raise ValueError("no valid consensus rows were imported: " + "; ".join(warnings[:3]))
    return {
        "release_id": release_id,
        "inserted": len(captured),
        "snapshot_ids": captured,
        "warnings": warnings,
        "data_mode": "observed",
        "is_manual": True,
        "point_in_time": True,
    }


__all__ = ["append_consensus", "import_consensus_csv"]
