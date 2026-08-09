from __future__ import annotations

from fastapi.testclient import TestClient

from worldstate.application.market_research_service import _transform
from worldstate.application.world_state_service import calculate_signal, classify_regime


def test_state_signal_is_bounded_and_orientation_aware() -> None:
    score, momentum, gap = calculate_signal([100, 101, 103, 106, 110, 115], orientation=1)
    assert gap is None
    assert -1 <= (score or 0) <= 1
    assert -1 <= (momentum or 0) <= 1
    inverted, _, _ = calculate_signal([100, 101, 103, 106, 110, 115], orientation=-1)
    assert inverted is not None
    assert score is not None
    assert inverted * score <= 0


def test_state_signal_reports_insufficient_history_and_zero_variance() -> None:
    score, momentum, gap = calculate_signal([1, 1], minimum_history=3)
    assert score is None
    assert momentum is None
    assert gap
    score, momentum, gap = calculate_signal([10, 10, 10, 10], minimum_history=3)
    assert score == 0
    assert momentum == 0
    assert gap is None


def test_regime_label_does_not_treat_positive_as_unconditionally_good() -> None:
    result = classify_regime(
        {
            "growth": {"score": -0.6, "confidence": 0.8},
            "inflation": {"score": 0.7, "confidence": 0.8},
            "policy_tightness": {"score": 0.5, "confidence": 0.7},
            "risk": {"score": 0.4, "confidence": 0.7},
        }
    )
    assert "滞胀" in result["label"]
    assert "政策偏紧" in result["tags"]
    assert "风险规避" in result["tags"]


def test_world_state_endpoint_is_explicit_about_demo_data(client: TestClient) -> None:
    response = client.get("/v2/world-state?data_mode=fixture")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "fixture"
    assert payload["methodology_version"] == "wst-state-v1"
    assert payload["dimensions"]["growth"]["coverage"] > 0
    assert payload["dimensions"]["growth"]["top_drivers"][0]["data_mode"] == "fixture"
    observed = client.get("/v2/world-state?data_mode=observed").json()
    assert observed["data_mode"] == "observed"
    assert all(
        item["data_mode"] == "observed"
        for dimension in observed["dimensions"].values()
        for item in dimension["top_drivers"]
    )


def test_daily_brief_is_deterministic_and_has_explicit_sections(client: TestClient) -> None:
    response = client.get("/v2/daily-brief?data_mode=fixture")
    assert response.status_code == 200
    payload = response.json()
    assert payload["methodology_version"] == "wst-daily-brief-v1"
    assert payload["world_state"]["data_mode"] == "fixture"
    assert isinstance(payload["biggest_changes"], list)
    assert isinstance(payload["upcoming"], list)
    assert "AI 只可在此基础上解释" in payload["ai_note"]


def test_series_transforms_preserve_missing_leads() -> None:
    points = _transform([100, 101, 102, 104, 108], [], "mom")
    assert points[0] is None
    assert points[-1] is not None
    zscores = _transform([1, 1, 1, 2], [], "zscore")
    assert zscores[-1] is not None
    assert zscores[-1] > 0


def test_market_and_series_endpoints_are_mode_explicit(client: TestClient) -> None:
    market = client.get("/v2/market-dashboard?horizon=1w&data_mode=fixture")
    assert market.status_code == 200
    assert market.json()["methodology_version"] == "wst-market-dashboard-v1"
    series = client.get("/v2/series?data_mode=fixture")
    assert series.status_code == 200
    assert all(item["data_mode"] == "fixture" for item in series.json())
    detail = client.get("/v2/series/US.INFLATION.CPI_HEADLINE?data_mode=fixture&transform=mom")
    assert detail.status_code == 200
    assert detail.json()["transform"] == "mom"
    assert detail.json()["points"]


def test_thesis_book_is_user_owned_and_evaluation_does_not_auto_confirm(client: TestClient) -> None:
    created = client.post(
        "/v2/theses",
        json={
            "title": "增长放缓但金融条件稳定",
            "thesis": "未来三个月美国增长继续放缓，但金融条件暂时不会明显恶化。",
            "horizon": "3m",
            "related_states": ["growth", "risk"],
            "watch_variables": ["US.GROWTH.INDUSTRIAL_PRODUCTION"],
            "confirmation_conditions": ["增长状态继续走弱"],
            "falsification_conditions": ["风险状态显著恶化"],
        },
    )
    assert created.status_code == 200, created.text
    thesis_id = created.json()["id"]
    listed = client.get("/v2/theses").json()
    assert any(item["id"] == thesis_id for item in listed)
    evaluated = client.get(f"/v2/theses/{thesis_id}/evaluate")
    assert evaluated.status_code == 200
    assert "不自动修改用户观点" in evaluated.json()["interpretation"]
    updated = client.patch(f"/v2/theses/{thesis_id}", json={"confidence": 0.7})
    assert updated.status_code == 200
    assert updated.json()["confidence"] == 0.7
    assistant = client.post(
        "/v2/research/assistant/context",
        json={"question": "最近通胀是变热还是变冷？", "data_mode": "fixture"},
    )
    assert assistant.status_code == 200
    assert assistant.json()["mode"] == "deterministic_context"
    assert assistant.json()["facts"][0]["claim_type"] == "fact"


def test_global_macro_marks_uncovered_countries_unavailable(client: TestClient) -> None:
    response = client.get("/v2/global-macro?data_mode=observed")
    assert response.status_code == 200
    payload = response.json()
    assert {item["iso3"] for item in payload["countries"]} == {"USA", "CHN", "EA19", "JPN", "GBR"}
    assert all(item["data_mode"] == "observed" for item in payload["countries"])
    assert any(item["status"] == "unavailable" for item in payload["countries"])
    assert payload["context_cards"]
