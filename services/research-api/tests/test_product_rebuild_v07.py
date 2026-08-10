from __future__ import annotations

from fastapi.testclient import TestClient


def test_capability_inventory_is_mode_explicit_and_actionable(client: TestClient) -> None:
    response = client.get("/v2/data/capabilities", params={"data_mode": "observed"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "observed"
    assert "CURRENT_STATE" in payload["summary"]
    assert "EVENT_INTRADAY" in payload["summary"]
    assert isinstance(payload["items"], list)
    for item in payload["items"][:5]:
        assert {"dataset_key", "rows", "capabilities", "data_mode"} <= set(item)
        assert "CURRENT_STATE" in item["capabilities"]


def test_today_projection_uses_product_labels_and_valid_session_changes(client: TestClient) -> None:
    response = client.get("/v2/product/today", params={"data_mode": "observed"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "observed"
    assert {
        "macro_snapshot",
        "markets",
        "what_changed",
        "global",
        "capability_summary",
    } <= set(payload)
    for item in payload["markets"]:
        assert "formatted_value" in item
        assert item["change_unit"] in {"%", "bp"}
        assert item["details"]["canonical_key"] == item["key"]
    if payload["markets"]:
        assert all("window_semantics" not in item for item in payload["markets"])
