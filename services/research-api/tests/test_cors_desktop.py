from fastapi.testclient import TestClient

from worldstate.api.origins import LOCAL_BROWSER_ORIGINS


def test_desktop_write_and_remove_watchlist_in_isolated_database(client: TestClient) -> None:
    headers = {"Origin": "http://tauri.localhost"}
    payload = {"item_type": "country", "item_key": "USA", "label": "Desktop CORS test"}
    denied = client.post("/v2/watchlist", json=payload, headers={"Origin": "https://evil.example"})
    assert denied.status_code == 403
    created = client.post("/v2/watchlist", json=payload, headers=headers)
    assert created.status_code == 200
    assert created.headers["access-control-allow-origin"] == headers["Origin"]
    removed = client.delete(f"/v2/watchlist/{created.json()['id']}", headers=headers)
    assert removed.status_code == 200


def test_all_local_origins_allow_existing_mutation_methods(client: TestClient) -> None:
    for origin in LOCAL_BROWSER_ORIGINS:
        for method in ("POST", "PATCH", "DELETE"):
            response = client.options(
                "/v2/watchlist",
                headers={"Origin": origin, "Access-Control-Request-Method": method},
            )
            assert response.status_code == 200
            assert response.headers["access-control-allow-origin"] == origin


def test_tauri_v2_production_origin_is_allowed(client: TestClient) -> None:
    response = client.get("/v2/health", headers={"Origin": "http://tauri.localhost"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_tauri_v2_production_preflight_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/v2/health",
        headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_other_known_origins_remain_allowed_and_unknown_is_not(
    client: TestClient,
) -> None:
    for origin in ("https://tauri.localhost", "tauri://localhost", "http://127.0.0.1:4173"):
        response = client.get("/v2/health", headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

    unknown = client.get("/v2/health", headers={"Origin": "https://evil.example"})
    assert unknown.status_code == 200
    assert "access-control-allow-origin" not in unknown.headers
