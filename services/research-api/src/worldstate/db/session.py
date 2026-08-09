"""Async database engine creation for SQLite desktop and PostgreSQL server modes."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Create a lazy async engine without opening a connection."""

    options: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite+"):
        options["connect_args"] = {"timeout": 30}
    else:
        options["pool_recycle"] = 1800
    return create_async_engine(database_url, **options)
