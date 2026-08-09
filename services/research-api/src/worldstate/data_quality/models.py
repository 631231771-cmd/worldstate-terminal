"""Normalized, source-aware data-quality metadata."""

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class QualityGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


_QUALITY_SCORES = {
    QualityGrade.A: 1.0,
    QualityGrade.B: 0.82,
    QualityGrade.C: 0.62,
    QualityGrade.D: 0.35,
    QualityGrade.UNKNOWN: 0.2,
}


def quality_score(grade: QualityGrade | str) -> float:
    try:
        resolved = grade if isinstance(grade, QualityGrade) else QualityGrade(grade)
    except ValueError:
        resolved = QualityGrade.UNKNOWN
    return _QUALITY_SCORES[resolved]


class DataQuality(BaseModel):
    """Portable quality record used at provider and service boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_name: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    source_type: str = Field(min_length=1, max_length=64)
    acquired_at: AwareDatetime
    is_manual: bool = False
    is_verified: bool = False
    is_fixture: bool = False
    is_proxy: bool = False
    latency_seconds: int | None = Field(default=None, ge=0)
    granularity_seconds: int | None = Field(default=None, ge=1)
    missing_reason: str | None = None
    quality_grade: QualityGrade = QualityGrade.UNKNOWN
    verification_notes: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @property
    def score(self) -> float:
        return quality_score(self.quality_grade)

    def to_storage(self) -> dict[str, object]:
        payload = self.model_dump(mode="json")
        payload["source_url"] = str(self.source_url) if self.source_url else None
        payload["acquired_at"] = self.acquired_at
        payload["quality_grade"] = self.quality_grade.value
        payload["metadata_json"] = payload.pop("metadata")
        return payload
