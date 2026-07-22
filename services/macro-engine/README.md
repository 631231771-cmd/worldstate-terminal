# World State Macro Engine

Deterministic, point-in-time macro data service for World State Terminal.

License status: **License decision pending legal review.** The surrounding World
Monitor project remains subject to its upstream AGPL-3.0-only license and notices.

## Local commands

```powershell
python -m uv sync --group dev
python -m uv run macro-engine --help
python -m uv run macro-engine catalog validate
python -m uv run macro-engine serve
```

The service starts without provider credentials. Health responses report those
providers as `not_configured`; fixtures are used only in tests.

Database changes are applied with Alembic:

```powershell
python -m uv run macro-engine migrate
```

Production schema creation must never call SQLAlchemy `create_all`.

