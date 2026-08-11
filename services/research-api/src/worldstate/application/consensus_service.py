"""Point-in-time consensus capture commands."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.data_foundation_service import assert_matching_data_mode
from worldstate.db.models import ConsensusSnapshot, Indicator, MacroRelease

SUPPORTED_INDICATOR_KEYS: dict[str, tuple[str, ...]] = {
    "US_CPI": ("headline_mom", "core_mom", "headline_yoy", "core_yoy"),
    "US_NFP": (
        "nonfarm_payrolls",
        "unemployment_rate",
        "average_hourly_earnings_mom",
        "average_hourly_earnings_yoy",
        "labor_force_participation",
    ),
    "FOMC": ("fed_funds_lower", "fed_funds_upper"),
}


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


async def supported_indicators_for_release(
    engine: AsyncEngine, release_id: str
) -> list[dict[str, object]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError as exc:
            raise LookupError("macro release not found") from exc
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            raise LookupError("macro release not found")
        keys = SUPPORTED_INDICATOR_KEYS.get(release.release_type, ())
        rows = list(
            (
                await session.scalars(
                    select(Indicator)
                    .where(Indicator.indicator_key.in_(keys), Indicator.active.is_(True))
                    .order_by(Indicator.indicator_key)
                )
            ).all()
        )
    by_key = {item.indicator_key: item for item in rows}
    return [
        {
            "key": key,
            "label": by_key[key].name,
            "unit": by_key[key].unit,
            "family": by_key[key].family,
            "hotter_when_higher": by_key[key].hotter_when_higher,
        }
        for key in keys
        if key in by_key
    ]


async def preview_consensus_csv(
    engine: AsyncEngine,
    *,
    release_id: str,
    csv_text: str,
    default_source_name: str = "Manual consensus CSV",
    default_source_url: str | None = None,
) -> dict[str, object]:
    """Validate a consensus file without writing snapshots."""

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError as exc:
            raise LookupError("macro release not found") from exc
        release = await session.get(MacroRelease, release_uuid)
        if release is None:
            raise LookupError("macro release not found")
        t0 = _aware(release.released_at or release.scheduled_at)
        supported = await supported_indicators_for_release(engine, release_id)
    supported_keys = {str(item["key"]) for item in supported}
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"indicator_key", "consensus_value", "captured_at"}
    missing = sorted(required - set(reader.fieldnames or []))
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    items: list[dict[str, object]] = []
    counts = {"eligible": 0, "post_t0": 0, "unknown_indicator": 0, "invalid": 0}
    for row_number, row in enumerate(reader, start=2):
        key = str(row.get("indicator_key") or "").strip()
        value_text = str(row.get("consensus_value") or "").strip()
        captured_text = str(row.get("captured_at") or "").strip()
        status = "eligible"
        reason: str | None = None
        value: Decimal | None = None
        captured_at: datetime | None = None
        try:
            value = Decimal(value_text)
            captured_at = datetime.fromisoformat(captured_text.replace("Z", "+00:00"))
            if captured_at.tzinfo is None:
                raise ValueError("captured_at must include an explicit timezone")
            captured_at = _aware(captured_at)
            if key not in supported_keys:
                status = "unknown_indicator"
                reason = "indicator is not supported by this release"
            elif captured_at >= t0:
                status = "post_t0"
                reason = "captured_at is at or after release T0"
        except (ArithmeticError, ValueError) as exc:
            status = "invalid"
            reason = str(exc)
        counts[status] += 1
        items.append(
            {
                "row": row_number,
                "indicator_key": key,
                "indicator_label": next(
                    (str(item["label"]) for item in supported if item["key"] == key), key
                ),
                "consensus_value": str(value) if value is not None else value_text,
                "captured_at": captured_at.isoformat() if captured_at else captured_text,
                "source_name": str(row.get("source_name") or default_source_name),
                "source_url": str(row.get("source_url") or default_source_url or "") or None,
                "status": status,
                "eligible": status == "eligible",
                "reason": reason,
            }
        )
    return {
        "release_id": release_id,
        "t0": t0.isoformat(),
        "supported_indicators": supported,
        "items": items,
        "summary": {**counts, "total": len(items)},
        "can_confirm": counts["eligible"] > 0,
    }


async def import_consensus_csv(
    engine: AsyncEngine,
    *,
    release_id: str,
    csv_text: str,
    default_source_name: str = "Manual consensus CSV",
    default_source_url: str | None = None,
) -> dict[str, object]:
    """Append pre-release consensus snapshots from a traceable CSV file."""
    preview = await preview_consensus_csv(
        engine,
        release_id=release_id,
        csv_text=csv_text,
        default_source_name=default_source_name,
        default_source_url=default_source_url,
    )
    reader = csv.DictReader(io.StringIO(csv_text))
    captured: list[str] = []
    warnings: list[str] = []
    preview_rows = cast(list[dict[str, object]], preview["items"])
    preview_items = {int(cast(Any, item["row"])): item for item in preview_rows}
    for row_number, row in enumerate(reader, start=2):
        preview_item = preview_items[row_number]
        if not preview_item["eligible"]:
            warnings.append(f"row {row_number}: {preview_item['reason']}")
            continue
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
                verification_notes=(str(row.get("verification_notes") or "Imported from user CSV")),
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
        "preview_summary": preview["summary"],
    }


__all__ = [
    "SUPPORTED_INDICATOR_KEYS",
    "append_consensus",
    "import_consensus_csv",
    "preview_consensus_csv",
    "supported_indicators_for_release",
]
