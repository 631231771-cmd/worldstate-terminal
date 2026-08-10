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


def test_macro_projection_keeps_canonical_dimension_keys(client: TestClient) -> None:
    payload = client.get("/v2/product/today", params={"data_mode": "observed"}).json()
    for country in payload["global"]:
        for key, dimension in country["dimensions"].items():
            assert key in {
                "growth",
                "inflation",
                "liquidity",
                "policy_tightness",
                "credit",
                "risk",
                "fiscal",
                "external",
            }
            assert dimension["label"]
        for key in country["available_dimensions"]:
            assert key in country["dimensions"]


def test_markets_projection_returns_all_horizons_in_one_response(client: TestClient) -> None:
    response = client.get("/v2/product/markets", params={"data_mode": "observed"})
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert set(item.get("horizons", {})) <= {"1d", "1w", "1m", "3m"}
