"""Async PostgreSQL engine creation."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Create a lazy async engine without opening a connection."""

    return create_async_engine(database_url, pool_pre_ping=True, pool_recycle=1800)

