"""Single quality policy for user-facing projections.

Provider identity is not a quality grade.  A projection may use a documented
fallback only when no quality record exists, and must then say UNKNOWN.
"""

from __future__ import annotations

from worldstate.db.models import DataQualityRecord

VALID_GRADES = {"A", "B", "C", "D", "UNKNOWN"}


def resolve_quality_grade(record: DataQualityRecord | None) -> str:
    if record is None:
        return "UNKNOWN"
    grade = str(record.quality_grade).upper()
    return grade if grade in VALID_GRADES else "UNKNOWN"


def quality_limitation(record: DataQualityRecord | None) -> str | None:
    if record is None:
        return "No quality record was persisted for this observation."
    return record.verification_notes or record.missing_reason


__all__ = ["quality_limitation", "resolve_quality_grade"]
