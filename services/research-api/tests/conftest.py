from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from worldstate.config import Settings
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.session import create_engine
from worldstate.main import create_app


@pytest.fixture(scope="session")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    database_path = tmp_path_factory.mktemp("worldstate") / "test.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"

    async def create_schema() -> None:
        engine = create_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create_schema())
    settings = Settings(
        database_url=database_url,
        ai_provider="none",
        log_level="WARNING",
        demo_mode=True,
        scheduler_enabled=False,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def release_index(client: TestClient) -> dict[str, dict[str, object]]:
    response = client.get("/v2/releases")
    assert response.status_code == 200
    return {str(item["release_type"]): item for item in response.json()}
