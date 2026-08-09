"""Schema validation for evidence-bound deterministic and AI claims."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

VALID_CLAIM_TYPES = {
    "confirmed_fact",
    "historical_relationship",
    "plausible_inference",
    "competing_explanation",
    "unknown",
}


@dataclass(frozen=True)
class ClaimValidation:
    valid: bool
    errors: tuple[str, ...]


def validate_claims(
    claims: list[dict[str, Any]], evidence: dict[str, dict[str, Any]]
) -> ClaimValidation:
    errors: list[str] = []
    for index, claim in enumerate(claims):
        prefix = f"claims[{index}]"
        claim_type = claim.get("claim_type")
        if claim_type not in VALID_CLAIM_TYPES:
            errors.append(f"{prefix}: unsupported claim_type")
        evidence_ids = claim.get("evidence_ids") or []
        contradicting_ids = claim.get("contradicting_evidence_ids") or []
        if any(evidence_id not in evidence for evidence_id in evidence_ids):
            errors.append(f"{prefix}: unknown evidence id")
        if any(evidence_id not in evidence for evidence_id in contradicting_ids):
            errors.append(f"{prefix}: unknown contradicting evidence id")
        referenced = [evidence[item] for item in evidence_ids if item in evidence]
        if any(item.get("supported") is False for item in referenced):
            errors.append(f"{prefix}: unsupported evidence cannot substantiate a claim")
        if claim_type == "confirmed_fact" and not evidence_ids:
            errors.append(f"{prefix}: confirmed_fact requires evidence")
        if claim_type == "confirmed_fact" and claim.get("is_inference"):
            errors.append(f"{prefix}: confirmed_fact cannot be marked as inference")
        if claim_type == "plausible_inference":
            if not claim.get("is_inference"):
                errors.append(f"{prefix}: inference flag is required")
            if not evidence_ids:
                errors.append(f"{prefix}: inference requires evidence")
            if not claim.get("limitations"):
                errors.append(f"{prefix}: inference requires limitations")
            if not claim.get("falsifier"):
                errors.append(f"{prefix}: inference requires a falsifier")
        if claim_type == "historical_relationship":
            if not evidence_ids:
                errors.append(f"{prefix}: historical relationship requires evidence")
            if referenced and not any(
                item.get("evidence_type") in {"historical_statistics", "historical_case"}
                for item in referenced
            ):
                errors.append(f"{prefix}: historical claim requires historical evidence")
        if claim_type == "competing_explanation":
            if not claim.get("is_inference"):
                errors.append(f"{prefix}: competing explanation must be inference")
            if not evidence_ids:
                errors.append(f"{prefix}: competing explanation requires evidence")
            if not claim.get("limitations") or not claim.get("falsifier"):
                errors.append(f"{prefix}: competing explanation requires limits and falsifier")
        if claim_type == "unknown" and not claim.get("limitations"):
            errors.append(f"{prefix}: unknown claim requires limitations")
        if claim.get("is_inference") and claim.get("causal_language") in {
            "certain",
            "proven",
            "definitive",
        }:
            errors.append(f"{prefix}: inference uses prohibited deterministic causal language")
        if "value" in claim and referenced:
            evidence_values = [item.get("value") for item in referenced if "value" in item]
            if evidence_values and claim["value"] not in evidence_values:
                errors.append(f"{prefix}: numeric value is not present in cited evidence")
        if (
            any(item.get("is_fixture") for item in referenced)
            and "fixture" not in " ".join(claim.get("limitations") or []).lower()
        ):
            errors.append(f"{prefix}: fixture disclosure required")
        if (
            any(item.get("is_proxy") for item in referenced)
            and "proxy" not in " ".join(claim.get("limitations") or []).lower()
        ):
            errors.append(f"{prefix}: proxy disclosure required")
    return ClaimValidation(not errors, tuple(errors))


def deterministic_claims(
    facts: list[dict[str, Any] | str],
    explanations: list[dict[str, Any]],
    evidence_ids: list[str],
    *,
    limitations: list[str],
) -> list[dict[str, Any]]:
    """Safe fallback; it never upgrades rule output into a causal fact."""
    fallback = evidence_ids[:1]
    claims = []
    for index, fact in enumerate(facts):
        linked = [evidence_ids[index]] if index < len(evidence_ids) else fallback
        claims.append(
            {
                "claim_type": "confirmed_fact",
                "statement": str(fact.get("statement") or fact.get("text") or fact)
                if isinstance(fact, dict)
                else str(fact),
                "evidence_ids": linked,
                "confidence": 0.8,
                "is_inference": False,
                "causal_language": "none",
                "limitations": limitations,
                "falsifier": None,
                "contradicting_evidence_ids": [],
            }
        )
    claims.extend(
        {
            "claim_type": "plausible_inference",
            "statement": str(item.get("summary") or item),
            "evidence_ids": fallback,
            "confidence": float(item.get("confidence", 0.4)),
            "is_inference": True,
            "causal_language": "qualified",
            "limitations": limitations
            or ["rule-based interpretation; competing drivers may be unobserved"],
            "falsifier": (
                "A conflicting cross-asset sequence or verified overlapping event "
                "would weaken this interpretation."
            ),
            "contradicting_evidence_ids": [],
        }
        for item in explanations
    )
    return claims
