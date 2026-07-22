from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from macro_engine.api import health as health_module
from macro_engine.config import Settings
from macro_engine.domain.enums import ServiceStatus
from macro_engine.domain.schemas import ComponentHealth
from macro_engine.main import create_app


def test_health_response_is_explicit_and_secret_free(monkeypatch: object) -> None:
    async def healthy_database(_request: object, _timeout: float) -> ComponentHealth:
        return ComponentHealth(status=ServiceStatus.OK)

    monkeypatch.setattr(health_module, "probe_database", healthy_database)  # type: ignore[attr-defined]
    app = create_app(Settings(database_url="postgresql+asyncpg://user:pass@localhost/test"))

    with TestClient(app) as client:
        response = client.get("/v1/health", headers={"x-request-id": "test-request"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request"
    body = response.json()
    assert body["status"] == "ok"
    assert body["providers"][0]["status"] == "not_configured"
    assert body["default_locale"] == "zh-CN"
    assert "pass" not in response.text


def test_health_degrades_when_database_probe_fails(monkeypatch: object) -> None:
    async def unavailable_database(_request: object, _timeout: float) -> ComponentHealth:
        return ComponentHealth(status=ServiceStatus.UNAVAILABLE, message="database probe failed")

    monkeypatch.setattr(health_module, "probe_database", unavailable_database)  # type: ignore[attr-defined]
    app = create_app(Settings())

    with TestClient(app) as client:
        body = client.get("/v1/health").json()

    assert body["status"] == "degraded"
    assert body["database"]["status"] == "unavailable"


async def test_probe_database_collapses_driver_errors() -> None:
    class BrokenEngine:
        @asynccontextmanager
        async def connect(self) -> AsyncIterator[None]:
            raise RuntimeError("connection contains a secret that must not escape")
            yield

    class State:
        database_engine = BrokenEngine()

    class App:
        state = State()

    class Request:
        app = App()

    result = await health_module.probe_database(Request(), 0.2)  # type: ignore[arg-type]

    assert result.status is ServiceStatus.UNAVAILABLE
    assert result.message == "database probe failed: RuntimeError"

