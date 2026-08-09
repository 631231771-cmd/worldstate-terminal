"""Manual macro-release command boundary."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.analysis_orchestrator import _ensure_catalog
from worldstate.db.models import (
    DataQualityRecord,
    Indicator,
    MacroRelease,
    ReleaseStage,
    ReleaseValue,
    SourceArtifact,
)
from worldstate.macro_core.catalog import RELEASE_INDICATORS


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def create_manual_release(
    engine: AsyncEngine,
    *,
    release_key: str,
    release_type: str,
    title: str,
    period_label: str,
    scheduled_at: datetime,
    released_at: datetime | None,
    source_timezone: str,
    source_name: str,
    source_url: str,
    verified: bool,
    values: dict[str, dict[str, object]],
    stages: list[dict[str, object]],
    contamination_level: str,
    clean_window: bool,
    overlapping_events: list[dict[str, object]],
    confounding_notes: list[str],
) -> str:
    """Create a traceable manual release without silently inventing consensus."""

    if release_type not in RELEASE_INDICATORS:
        raise ValueError(f"unsupported release_type: {release_type}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await _ensure_catalog(session)
        existing = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_key == release_key)
        )
        if existing is not None:
            raise ValueError("release_key already exists")
        release_id, artifact_id, quality_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        now = datetime.now(UTC)
        payload_hash = hashlib.sha256(
            json.dumps(
                {"release_key": release_key, "values": values, "stages": stages},
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        session.add(
            SourceArtifact(
                id=artifact_id,
                source_key=f"{release_key}:manual-source",
                provider_key="manual",
                artifact_type="manual_release_entry",
                title=title,
                source_url=source_url,
                published_at=_aware(released_at or scheduled_at),
                retrieved_at=now,
                content_hash=payload_hash,
                license_name=None,
                citation_text=f"{source_name}: {source_url}",
                is_fixture=False,
                data_mode="observed",
                metadata_json={"entry_mode": "manual"},
            )
        )
        session.add(
            DataQualityRecord(
                id=quality_id,
                subject_type="macro_release",
                subject_id=str(release_id),
                source_name=source_name,
                source_url=source_url,
                source_type="manual_release_entry",
                acquired_at=now,
                is_manual=True,
                is_verified=verified,
                is_fixture=False,
                is_proxy=False,
                latency_seconds=None,
                granularity_seconds=None,
                missing_reason=None,
                quality_grade="B" if verified else "C",
                verification_notes=(
                    "Manually entered and marked verified."
                    if verified
                    else "Manual entry has not been independently verified."
                ),
                metadata_json={},
            )
        )
        session.add(
            MacroRelease(
                id=release_id,
                release_key=release_key,
                release_type=release_type,
                title=title,
                country="USA",
                period_label=period_label,
                scheduled_at=_aware(scheduled_at),
                released_at=_aware(released_at) if released_at else None,
                source_timezone=source_timezone,
                status="released" if released_at else "scheduled",
                data_version="manual-v1",
                data_mode="observed",
                source_artifact_id=artifact_id,
                primary_quality_id=quality_id,
                contamination_level=contamination_level,
                clean_window=clean_window,
                overlapping_events=overlapping_events,
                confounding_notes=confounding_notes,
                metadata_json={"data_mode": "manual"},
            )
        )
        stage_items = stages or [
            {
                "key": "release",
                "title": "数据公布",
                "scheduled_at": scheduled_at,
                "released_at": released_at,
            }
        ]
        stage_ids: dict[str, uuid.UUID] = {}
        for sequence, item in enumerate(stage_items, start=1):
            key, stage_id = str(item["key"]), uuid.uuid4()
            stage_ids[key] = stage_id
            item_scheduled = item.get("scheduled_at") or scheduled_at
            item_released = item.get("released_at")
            if not isinstance(item_scheduled, datetime):
                raise TypeError("stage scheduled_at must be datetime")
            if item_released is not None and not isinstance(item_released, datetime):
                raise TypeError("stage released_at must be datetime")
            session.add(
                ReleaseStage(
                    id=stage_id,
                    macro_release_id=release_id,
                    stage_key=key,
                    title=str(item["title"]),
                    sequence=sequence,
                    scheduled_at=_aware(item_scheduled),
                    released_at=_aware(item_released) if item_released else None,
                    status="released" if item_released else "scheduled",
                    source_artifact_id=artifact_id,
                    metadata_json={"entry_mode": "manual"},
                )
            )
        await session.flush()
        indicator_rows = {
            row.indicator_key: row
            for row in (
                await session.scalars(
                    select(Indicator).where(
                        Indicator.indicator_key.in_(RELEASE_INDICATORS[release_type])
                    )
                )
            ).all()
        }
        captured_at = _aware(released_at or scheduled_at)
        for key, entry in values.items():
            indicator = indicator_rows.get(key)
            if indicator is None:
                raise ValueError(f"indicator {key} is not valid for {release_type}")
            stage_key = str(entry.get("stage_key") or stage_items[0]["key"])
            value_stage_id = stage_ids.get(stage_key)
            if value_stage_id is None:
                raise ValueError(f"unknown stage_key for value {key}: {stage_key}")
            for value_kind in ("actual", "previous", "revised_previous"):
                value = entry.get(value_kind)
                if value is None:
                    continue
                session.add(
                    ReleaseValue(
                        id=uuid.uuid4(),
                        macro_release_id=release_id,
                        release_stage_id=value_stage_id,
                        indicator_id=indicator.id,
                        value_kind=value_kind,
                        value=Decimal(str(value)),
                        raw_value=str(value),
                        data_version="manual-v1",
                        valid_from=captured_at,
                        captured_at=captured_at,
                        is_initial=value_kind == "actual",
                        data_mode="observed",
                        source_artifact_id=artifact_id,
                        quality_id=quality_id,
                        metadata_json={"entry_mode": "manual"},
                    )
                )
        return str(release_id)


__all__ = ["create_manual_release"]
