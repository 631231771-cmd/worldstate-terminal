from fastapi.testclient import TestClient


def test_freshness_exposes_mode_and_statuses(client: TestClient) -> None:
    response = client.get("/v2/data/freshness?data_mode=fixture")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "fixture"
    assert payload["summary"].get("FIXTURE", 0) >= 1
    assert all("available_at" in item and "status" in item for item in payload["items"])


def test_macro_system_status_never_promotes_partial_coverage(client: TestClient) -> None:
    response = client.get("/v2/macro-systems?data_mode=fixture")
    assert response.status_code == 200
    for system in response.json()["systems"]:
        assert system["status"] in {"available", "partial", "unavailable"}
        if 0 < system["available_components"] < system["component_count"]:
            assert system["status"] == "partial"


def test_world_state_snapshot_history_is_replayable(client: TestClient) -> None:
    response = client.post(
        "/v2/world-state/snapshot?data_mode=fixture", headers={"x-worldstate-local": "1"}
    )
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["data_mode"] == "fixture"
    assert len(snapshot["source_snapshot_hash"]) == 64
    assert isinstance(snapshot["dimensions"], dict)
    assert isinstance(snapshot["regime"], dict)
    assert isinstance(snapshot["top_changes"], list)
    assert isinstance(snapshot["evidence"], list)
    assert isinstance(snapshot["data_gaps"], list)
    assert snapshot["methodology_version"]
    brief_response = client.get(
        "/v2/daily-brief",
        params={"data_mode": "fixture", "as_of": snapshot["as_of"]},
    )
    assert brief_response.status_code == 200, brief_response.text
    brief = brief_response.json()
    assert snapshot["top_changes"] == brief["biggest_changes"]
    history = client.get("/v2/world-state/history?data_mode=fixture")
    assert history.status_code == 200
    assert history.json()[0]["source_snapshot_hash"] == snapshot["source_snapshot_hash"]
    assert client.get("/v2/world-state/history?data_mode=fixture&window=7d").status_code == 200


def test_watchlist_is_user_owned_and_idempotent(client: TestClient) -> None:
    payload = {
        "item_type": "series",
        "item_key": "US.POLICY.TREASURY_10Y",
        "label": "US 10Y",
        "notes": "观察实际利率与黄金的关系",
    }
    headers = {"x-worldstate-local": "1"}
    first = client.post("/v2/watchlist", json=payload, headers=headers)
    second = client.post("/v2/watchlist", json=payload, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    rows = client.get("/v2/watchlist").json()
    assert len([item for item in rows if item["item_key"] == payload["item_key"]]) == 1
