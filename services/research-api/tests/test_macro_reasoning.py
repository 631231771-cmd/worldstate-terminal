from __future__ import annotations

from typing import cast

from fastapi.testclient import TestClient

from worldstate.application.reasoning_service import list_playbooks
from worldstate.reasoning.loader import load_playbook

SOURCE_TEXT = (
    "原油供给中断可能推高通胀压力，并迫使美联储维持更鹰的政策路径。"
    "这可能令两年期美债收益率和美元上升，同时使黄金与纳斯达克承压。"
)
EXACT_QUOTE = "原油供给中断可能推高通胀压力"


def _create_source(client: TestClient, *, data_mode: str = "observed") -> dict[str, object]:
    response = client.post(
        "/v2/reasoning/sources",
        json={
            "title": "能源冲击研究摘录",
            "author": "示例研究者",
            "source_type": "note",
            "source_url": "https://example.test/research/energy-shock",
            "content_text": SOURCE_TEXT,
            "notes": "用户提供的研究文本，不是系统结论。",
            "data_mode": data_mode,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def _extract_claim(client: TestClient, source_id: str) -> dict[str, object]:
    response = client.post(
        f"/v2/reasoning/sources/{source_id}/claims",
        json={
            "statement": (
                "原油供给冲击经通胀和政策路径传导，支持美元与短端利率，"
                "并压制黄金和纳指。"
            ),
            "exact_quote": EXACT_QUOTE,
            "extraction_method": "manual",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_playbook_is_versioned_strict_and_competitive() -> None:
    playbook, digest = load_playbook()
    assert playbook.version == "1.1.0"
    assert len(digest) == 64
    assert {item.key for item in playbook.mechanisms} == {
        "energy_supply_shock",
        "demand_acceleration",
        "dollar_liquidity_easing",
    }
    supply = next(item for item in playbook.mechanisms if item.key == "energy_supply_shock")
    assert len(supply.causal_chain) == 6
    assert supply.competing_mechanisms == [
        "demand_acceleration",
        "dollar_liquidity_easing",
    ]
    public = list_playbooks()
    assert public["policy"].startswith("Playbooks define hypotheses")


def test_source_claim_confirmation_and_reproducible_assessment(client: TestClient) -> None:
    source = _create_source(client)
    assert source["provenance"]["capture_method"] == "user_supplied_text"  # type: ignore[index]
    assert len(str(source["content_hash"])) == 64
    claim = _extract_claim(client, str(source["id"]))
    assert claim["status"] == "draft"
    assert claim["extraction_method"] == "manual"

    blocked = client.post(
        f"/v2/reasoning/claims/{claim['id']}/assessments",
        json={"as_of": "2026-08-12T15:00:00Z"},
    )
    assert blocked.status_code == 409

    review = client.patch(
        f"/v2/reasoning/claims/{claim['id']}",
        json={
            "decision": "confirmed",
            "mechanism_key": "energy_supply_shock",
            "review_notes": "确认这是作者的假设，而不是已证实事实。",
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()["confirmed_by"] == "local_user"
    assert review.json()["mechanism_version"] == "1.1.0"

    first = client.post(
        f"/v2/reasoning/claims/{claim['id']}/assessments",
        json={"as_of": "2026-08-12T15:00:00Z"},
    )
    assert first.status_code == 201, first.text
    result = first.json()
    mechanisms = result["result"]["system_assessment"]["mechanisms"]
    assert [item["key"] for item in mechanisms] == [
        "energy_supply_shock",
        "demand_acceleration",
        "dollar_liquidity_easing",
    ]
    assert result["result"]["author_claim"]["author"] == "示例研究者"
    assert "不是因果证明" in result["result"]["system_assessment"]["truthfulness_note"]
    assert all("confidence" not in item for item in mechanisms)
    assert len(result["input_snapshot_hash"]) == 64
    assert len(result["output_hash"]) == 64

    repeated = client.post(
        f"/v2/reasoning/claims/{claim['id']}/assessments",
        json={"as_of": "2026-08-12T15:00:00Z"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["input_snapshot_hash"] == result["input_snapshot_hash"]
    assert repeated.json()["output_hash"] == result["output_hash"]

    cases = client.get("/v2/reasoning/cases?data_mode=observed")
    assert cases.status_code == 200
    case = next(item for item in cases.json() if item["source"]["id"] == source["id"])
    assert case["claims"][0]["latest_assessment"]["output_hash"] == result["output_hash"]


def test_exact_quote_and_ai_provenance_are_enforced(client: TestClient) -> None:
    source = _create_source(client)
    missing_quote = client.post(
        f"/v2/reasoning/sources/{source['id']}/claims",
        json={
            "statement": "这是一个没有原文支持的候选观点。",
            "exact_quote": "原文中不存在的句子",
            "extraction_method": "manual",
        },
    )
    assert missing_quote.status_code == 422
    ai_without_model = client.post(
        f"/v2/reasoning/sources/{source['id']}/claims",
        json={
            "statement": "候选观点",
            "exact_quote": EXACT_QUOTE,
            "extraction_method": "ai",
        },
    )
    assert ai_without_model.status_code == 422
