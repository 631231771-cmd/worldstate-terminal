from __future__ import annotations

from typing import Any

import pytest

from worldstate.ai_researcher.claims import deterministic_claims, validate_claims


def evidence(**overrides: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "evidence_type": "computed_fact",
        "supported": True,
        "is_fixture": False,
        "is_proxy": False,
        "value": 1.0,
    }
    item.update(overrides)
    return item


def claim(**overrides: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "claim_type": "confirmed_fact",
        "statement": "The observed value was 1.0.",
        "evidence_ids": ["fact-1"],
        "confidence": 0.9,
        "is_inference": False,
        "causal_language": "none",
        "limitations": [],
        "falsifier": None,
        "contradicting_evidence_ids": [],
    }
    item.update(overrides)
    return item


def test_confirmed_fact_requires_real_supported_evidence() -> None:
    assert validate_claims([claim()], {"fact-1": evidence()}).valid
    missing = validate_claims([claim(evidence_ids=["absent"])], {"fact-1": evidence()})
    unsupported = validate_claims([claim()], {"fact-1": evidence(supported=False)})
    empty = validate_claims([claim(evidence_ids=[])], {})
    assert "claims[0]: unknown evidence id" in missing.errors
    assert any("unsupported evidence" in item for item in unsupported.errors)
    assert "claims[0]: confirmed_fact requires evidence" in empty.errors


@pytest.mark.parametrize("missing_field", ["limitations", "falsifier"])
def test_inference_requires_explicit_limits_and_falsifier(missing_field: str) -> None:
    payload = claim(
        claim_type="plausible_inference",
        is_inference=True,
        causal_language="qualified",
        limitations=["Other drivers are unobserved."],
        falsifier="A reversed yield response would weaken it.",
    )
    payload[missing_field] = [] if missing_field == "limitations" else None
    result = validate_claims([payload], {"fact-1": evidence()})
    assert result.valid is False


def test_fixture_proxy_and_numeric_claims_must_be_disclosed_and_consistent() -> None:
    registry = {"fact-1": evidence(is_fixture=True, is_proxy=True, value=2.0)}
    invalid = validate_claims([claim(value=1.0)], registry)
    assert any("fixture disclosure" in item for item in invalid.errors)
    assert any("proxy disclosure" in item for item in invalid.errors)
    assert any("numeric value" in item for item in invalid.errors)
    valid = validate_claims(
        [claim(value=2.0, limitations=["fixture data", "proxy instrument"])],
        registry,
    )
    assert valid.valid


def test_historical_claim_must_cite_historical_evidence() -> None:
    payload = claim(claim_type="historical_relationship")
    assert not validate_claims([payload], {"fact-1": evidence()}).valid
    assert validate_claims(
        [payload], {"fact-1": evidence(evidence_type="historical_statistics")}
    ).valid


def test_deterministic_fallback_binds_each_fact_to_its_own_id() -> None:
    claims = deterministic_claims(
        ["first", "second"],
        [{"summary": "inferred", "confidence": 0.4}],
        ["e-1", "e-2"],
        limitations=["rule-based interpretation"],
    )
    assert claims[0]["evidence_ids"] == ["e-1"]
    assert claims[1]["evidence_ids"] == ["e-2"]
    assert claims[2]["is_inference"] is True
    assert claims[2]["falsifier"]


def test_validator_rejects_invalid_types_contradictions_and_causal_overclaim() -> None:
    invalid = [
        claim(claim_type="invented"),
        claim(contradicting_evidence_ids=["missing"]),
        claim(is_inference=True),
        claim(
            claim_type="plausible_inference",
            evidence_ids=[],
            is_inference=False,
            limitations=[],
            falsifier=None,
        ),
        claim(
            claim_type="competing_explanation",
            evidence_ids=[],
            is_inference=False,
            limitations=[],
            falsifier=None,
        ),
        claim(claim_type="unknown", evidence_ids=[], limitations=[]),
        claim(
            claim_type="plausible_inference",
            is_inference=True,
            causal_language="certain",
            limitations=["limited"],
            falsifier="counterexample",
        ),
    ]
    result = validate_claims(invalid, {"fact-1": evidence()})
    assert not result.valid
    assert any("unsupported claim_type" in item for item in result.errors)
    assert any("unknown contradicting" in item for item in result.errors)
    assert any("prohibited deterministic" in item for item in result.errors)


def test_historical_and_competing_claims_require_evidence() -> None:
    historical = claim(claim_type="historical_relationship", evidence_ids=[])
    competing = claim(
        claim_type="competing_explanation",
        evidence_ids=["fact-1"],
        is_inference=True,
        limitations=["limited"],
        falsifier="counterexample",
    )
    result = validate_claims([historical, competing], {"fact-1": evidence()})
    assert any("historical relationship requires evidence" in item for item in result.errors)
    assert not any("competing explanation" in item for item in result.errors)
