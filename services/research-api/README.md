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

## CPI Event Lab

After migration, the first request to `GET /v1/events/lab/status` seeds a
traceable February 2024 U.S. CPI demonstration plus clearly labelled historical
and minute-bar fixtures. Open the terminal with `?lang=zh&view=lab`.

The lab owns its event bundle, append-only consensus snapshots, data-quality
records, market-bar provider boundary, event windows, contamination flags,
fixed historical comparison, competing explanations, and report. The bundled
market bars are illustrative fixtures rather than exchange-recorded prices;
ZT and ZN are explicitly represented as Treasury-futures price proxies.

Manual or provider data can replace fixtures through:

- `POST /v1/events/cpi`;
- `POST /v1/events/{event_id}/consensus`;
- `POST /v1/events/{event_id}/market-bars/import`;
- `POST /v1/events/{event_id}/analyze`.

Local desktop writes are allowed only from loopback origins. Non-local writes
require both `MACRO_ENABLE_WRITES=true` and `MACRO_WRITE_TOKEN`.
