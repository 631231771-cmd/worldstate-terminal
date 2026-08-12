from fastapi.testclient import TestClient


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
