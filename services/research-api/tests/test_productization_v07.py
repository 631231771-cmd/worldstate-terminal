from __future__ import annotations

import uuid
from datetime import UTC, datetime

from worldstate.application.quality_resolver import resolve_quality_grade
from worldstate.db.models import DataQualityRecord


def _quality(grade: str) -> DataQualityRecord:
    return DataQualityRecord(
        id=uuid.uuid4(),
        subject_type="market_context_batch",
        subject_id="gold_gc",
        source_name="test",
        source_url="https://example.test/source",
        source_type="manual_csv",
        acquired_at=datetime.now(UTC),
        quality_grade=grade,
        verification_notes="test record",
        metadata_json={},
    )


def test_quality_resolver_uses_persisted_grade() -> None:
    assert resolve_quality_grade(_quality("C")) == "C"


def test_quality_resolver_does_not_infer_grade_from_missing_record() -> None:
    assert resolve_quality_grade(None) == "UNKNOWN"


def test_quality_resolver_rejects_unknown_storage_value() -> None:
    assert resolve_quality_grade(_quality("provider_is_fred")) == "UNKNOWN"
