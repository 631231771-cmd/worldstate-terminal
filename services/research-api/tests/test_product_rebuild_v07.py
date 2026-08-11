from __future__ import annotations

from fastapi.testclient import TestClient

from worldstate.application.product_projection_service import _change_projection, _market_horizon


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


def test_market_horizon_contract_normalizes_price_percent_without_double_scaling() -> None:
    point = _market_horizon(
        {"instrument_key": "gold_gc", "change_percent": 5.0, "change_unit": "percent"}
    )
    assert point == {"value": 5.0, "unit": "%", "direction": "up"}


def test_market_horizon_contract_normalizes_rates_to_basis_points() -> None:
    point = _market_horizon(
        {"instrument_key": "ust10y_yield_context", "change_value": 0.05, "change_unit": "bp"}
    )
    assert point == {"value": 5.0, "unit": "bp", "direction": "up"}


def test_product_events_projection_exposes_server_ordered_views(client: TestClient) -> None:
    response = client.get("/v2/product/events", params={"data_mode": "observed", "limit": 100})
    assert response.status_code == 200
    payload = response.json()
    assert {"items", "upcoming", "recent", "default_event_id"} <= set(payload)
    upcoming = payload["upcoming"]
    assert all(item["status"] == "scheduled" for item in upcoming)
    assert [item["scheduled_at"] for item in upcoming] == sorted(
        item["scheduled_at"] for item in upcoming
    )
    if payload["default_event_id"] is not None:
        assert any(item["id"] == payload["default_event_id"] for item in payload["items"])


def test_change_projection_does_not_repeat_dimension_label() -> None:
    change = _change_projection(
        {
            "what_changed": "inflation state is weak",
            "why_it_matters": "inflation 的主要驱动是 crude oil",
            "magnitude": -0.4,
        }
    )
    assert change["what"] == "通胀 state is weak"
    assert change["why"] == " 的主要驱动是 crude oil"


def test_product_event_detail_uses_product_route(client: TestClient) -> None:
    events = client.get("/v2/product/events", params={"data_mode": "all", "limit": 1}).json()
    event_id = events["items"][0]["id"]
    response = client.get(f"/v2/product/events/{event_id}", params={"data_mode": "all"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == event_id
    assert payload["event"]["id"] == event_id
    assert payload["supported_indicators"]
    assert {"expectations", "actual", "surprise", "market_reaction", "analysis", "actions"} <= set(
        payload
    )
    assert all(
        item["key"] not in {"headline_cpi_mom", "target_rate_upper"}
        for item in payload["supported_indicators"]
    )
