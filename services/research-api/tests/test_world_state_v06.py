from __future__ import annotations

from fastapi.testclient import TestClient

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
