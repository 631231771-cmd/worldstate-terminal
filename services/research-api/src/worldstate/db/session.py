"""Async database engine creation for SQLite desktop and PostgreSQL server modes."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(database_url: str) -> AsyncEngine:
    """Create a lazy async engine without opening a connection."""

    options: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite+"):
        # Product projections fan out across several read-only views.  A
        # desktop SQLite process still benefits from a bounded read pool;
        # without it, Today + Markets loaded together can exhaust SQLAlchemy's
        # small default QueuePool before the UI receives a response.
        options.update({"pool_size": 20, "max_overflow": 20, "pool_timeout": 60})
        options["connect_args"] = {"timeout": 30}
    else:
        options["pool_recycle"] = 1800
    return create_async_engine(database_url, **options)
