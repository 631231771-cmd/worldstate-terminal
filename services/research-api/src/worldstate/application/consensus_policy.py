"""Canonical point-in-time eligibility policy for consensus snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from worldstate.db.models import ConsensusSnapshot, SourceArtifact


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ConsensusEligibility:
    """Research eligibility, independent from the generic quality letter."""

    eligible: bool
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    source_semantics: str
    capture_transport: str | None
    provenance_complete: bool
    policy_version: str = "consensus-eligibility-v1"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["limitations"] = list(self.limitations)
        return payload


def evaluate_consensus_eligibility(
    snapshot: ConsensusSnapshot,
    artifact: SourceArtifact | None,
    *,
    t0: datetime,
    release_data_mode: str,
    indicator_belongs_to_release: bool = True,
) -> ConsensusEligibility:
    """Evaluate a consensus row without changing its stored value or timestamp."""

    reasons: list[str] = []
    limitations: list[str] = []
    captured_at = _aware(snapshot.captured_at)
    artifact_metadata = artifact.metadata_json if artifact is not None else {}
    provider_metadata = snapshot.metadata_json.get("provider_metadata", {})
    if not isinstance(provider_metadata, dict):
        provider_metadata = {}
    transport = (
        str(artifact_metadata.get("acquisition_transport"))
        if artifact_metadata.get("acquisition_transport")
        else None
    )
    manual_semantics_verified = bool(
        snapshot.is_manual
        and bool(snapshot.source_url or (artifact is not None and artifact.source_url))
        and bool(snapshot.verification_notes)
    )
    semantics_verified = (
        provider_metadata.get("consensus_field") == "Forecast"
        and provider_metadata.get("te_forecast_field") == "TEForecast"
        and snapshot.metadata_json.get("te_forecast_used_as_consensus") is False
    ) or manual_semantics_verified
    source_semantics = (
        "Forecast=survey_consensus; TEForecast=proprietary_forecast"
        if not manual_semantics_verified and semantics_verified
        else "manual_verified_consensus"
        if manual_semantics_verified
        else "unverified"
    )
    provenance_complete = bool(
        snapshot.source_artifact_id
        and artifact is not None
        and artifact.content_hash
        and (snapshot.source_url or artifact.source_url)
    ) or manual_semantics_verified
    quality_grade = snapshot.quality_grade.upper()
    trusted_quality = quality_grade in {"A", "B", "C"}
    if captured_at >= _aware(t0):
        reasons.append("consensus_captured_at_must_be_before_t0")
    if snapshot.data_mode != release_data_mode:
        reasons.append("consensus_data_mode_mismatch")
    if not indicator_belongs_to_release:
        reasons.append("indicator_not_declared_for_release")
    if snapshot.data_mode == "fixture" or (artifact is not None and artifact.is_fixture):
        reasons.append("fixture_consensus_not_allowed")
    if not provenance_complete:
        (limitations if trusted_quality else reasons).append(
            "consensus_provenance_incomplete"
        )
    if not semantics_verified:
        (limitations if trusted_quality else reasons).append(
            "consensus_source_semantics_unverified"
        )
    if artifact is not None and captured_at > _aware(artifact.retrieved_at):
        reasons.append("consensus_capture_is_after_artifact_retrieval")
    if quality_grade == "D":
        if transport == "browser_capture" and semantics_verified and provenance_complete:
            limitations.append("quality_grade_D_requires_careful_interpretation")
        else:
            reasons.append("quality_grade_D_has_no_explicit_research_policy")
    elif not trusted_quality:
        reasons.append("quality_grade_not_research_approved")
    if transport == "browser_capture":
        limitations.append("browser_capture_is_not_provider_api_access")
    return ConsensusEligibility(
        eligible=not reasons,
        reasons=tuple(reasons),
        limitations=tuple(limitations),
        source_semantics=source_semantics,
        capture_transport=transport,
        provenance_complete=provenance_complete,
    )


__all__ = ["ConsensusEligibility", "evaluate_consensus_eligibility"]
