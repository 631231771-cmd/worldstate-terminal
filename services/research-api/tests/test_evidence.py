from __future__ import annotations

from worldstate.ai_researcher.evidence import (
    evidence_hash,
    validate_ai_output,
    validate_evidence_pack,
)


def pack() -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "evidence-pack-v1",
        "release": {
            "source": {"url": "https://example.test/official"},
            "data_quality": [{"is_fixture": True, "is_proxy": False}],
        },
        "constraints": {
            "facts_and_inferences_separated": True,
            "no_unique_causality_claim": True,
            "proxy_assets_labelled": True,
            "fixture_data_labelled": True,
        },
    }
    value["evidence_pack_hash"] = evidence_hash(value)
    return value


def test_evidence_pack_hash_detects_mutation() -> None:
    value = pack()
    assert validate_evidence_pack(value).valid
    value["release"] = {"source": {"url": "https://example.test/changed"}}
    result = validate_evidence_pack(value)
    assert result.valid is False
    assert "evidence_pack_hash_mismatch" in result.errors


def test_ai_output_rejects_unsupported_source_and_strong_causality() -> None:
    text = "\n".join(
        (
            "已确认事实",
            "历史关系",
            "当前推断",
            "竞争性解释",
            "无法确认",
            "这必然导致下跌。https://unsupported.test/story",
        )
    )
    result = validate_ai_output(text, pack())
    assert result.valid is False
    assert any(item.startswith("unsupported_citation") for item in result.errors)
    assert any(item.startswith("strong_causality_language") for item in result.errors)
