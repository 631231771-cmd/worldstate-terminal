# Macro Terminal operations

Status: Phase 3 world-explanation MVP.

## Windows one-click workflow

From the repository root, double-click `WorldState.bat`. It:

1. checks Python, Node.js, npm, and installs `uv` if needed;
2. installs locked Python and frontend dependencies when missing;
3. creates `.runtime/worldstate.env`;
4. migrates `.runtime/worldstate.db`;
5. starts Macro Engine and the `macro` frontend variant;
6. starts a non-blocking recent-data synchronization;
7. waits for both services and opens the Chinese terminal.

Runtime files stay under `.runtime/`:

- `worldstate.env`: local configuration and optional FRED key;
- `worldstate.db`: SQLite database;
- `*.pid`: managed process IDs;
- `logs/`: separate engine, frontend, and synchronization logs.

The stop command validates both the saved PID and command line before stopping a
process tree. It does not search for or terminate unrelated Python/Node
processes.

## Commands

```powershell
WorldState.bat start
WorldState.bat stop
WorldState.bat restart
WorldState.bat status
WorldState.bat doctor
WorldState.bat logs
WorldState.bat sync
WorldState.bat sync --series CPIAUCSL
```

`start` is the default when no command is supplied.

## Configure FRED/ALFRED

1. Start once so `.runtime/worldstate.env` exists.
2. Add the key after `FRED_API_KEY=`.
3. Run `WorldState.bat sync`.
4. Refresh the terminal. Successful real observations change the mode to
   `LIVE`.

The key is loaded into the Macro Engine process only. It is never added to a
Vite variable, browser storage, response, or log.

Without a key, synchronization loads deterministic fixtures and the UI displays
`DEMO` prominently. If a configured provider later fails while real local data
exists, the app keeps the last-known-good observations and reports `STALE`.

The daily world briefing does not need the FRED key. Its public RSS and daily
market evidence are keyless and report their own `LIVE`, `PARTIAL`, or `OFFLINE`
status.

## Connect an optional ClawFeed instance

The built-in five-part deep brief is always available. If a separately running
ClawFeed instance should also contribute its latest daily editions, add this to
the ignored `.runtime/worldstate.env` and restart:

```text
MACRO_CLAWFEED_URL=http://127.0.0.1:8767
```

Only the public, read-only digest endpoint is used. No ClawFeed cookie or API key
is stored. See [CLAWFEED_WEBMCP.md](CLAWFEED_WEBMCP.md) for the integration and
security boundaries.

## Configure the optional AI tutor

The terminal is useful without an AI key. In that state,
`POST /v1/world/ask` uses `evidence-rules-v1` and still distinguishes facts,
hypotheses, unknown order flow, and validation signals.

Edit ignored `.runtime/worldstate.env`, then restart.

OpenAI:

```text
MACRO_AI_PROVIDER=openai
OPENAI_API_KEY=your-key
MACRO_AI_MODEL=gpt-5.6-sol
```

Local Ollama:

```text
MACRO_AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
MACRO_OLLAMA_MODEL=qwen3:8b
```

Generic OpenAI-compatible endpoint:

```text
MACRO_AI_PROVIDER=compatible
MACRO_AI_BASE_URL=https://provider.example/v1
MACRO_AI_COMPATIBLE_API_KEY=your-key
MACRO_AI_MODEL=provider-model-id
```

`MACRO_AI_PROVIDER=auto` selects OpenAI when its key exists, then Ollama when a
base URL exists, then a compatible provider key. Secrets are read only by the
backend. ChatGPT subscriptions and OpenAI API billing are separate.

## Direct developer workflow

```powershell
cd services/macro-engine
python -m uv sync --locked --group dev
.venv\Scripts\macro-engine.exe migrate
.venv\Scripts\macro-engine.exe sync --all
.venv\Scripts\macro-engine.exe serve
```

In another terminal:

```powershell
npm run dev:macro -- --host 127.0.0.1 --port 4173
```

## PostgreSQL and containers

SQLite is the desktop default. Set `MACRO_DATABASE_URL` to a
`postgresql+asyncpg://...` URL to use PostgreSQL. Both engines use the same
SQLAlchemy models and Alembic revision.

```text
docker compose -f docker-compose.macro.yml up --build
```

## Verification

```powershell
cd services/macro-engine
python -m uv lock --check
.venv\Scripts\ruff.exe check src tests
.venv\Scripts\mypy.exe src
.venv\Scripts\pytest.exe
cd ..\..
npm run typecheck
npm run build:macro
```

## Troubleshooting

| Symptom | Action |
| --- | --- |
| page says engine offline | `WorldState.bat status`, then `WorldState.bat logs` |
| mode remains `DEMO` | check `FRED_API_KEY` and run `WorldState.bat sync` |
| mode is `STALE` | provider failed or last live sync exceeded 72 hours |
| world evidence is `PARTIAL` | one or more free news/market upstreams are unavailable |
| AI shows evidence rules mode | add an AI provider, or keep using the free fallback |
| AI provider fails | inspect engine logs; the answer automatically falls back to evidence rules |
| one series fails | inspect sync warnings; remaining series continue |
| port already in use | stop the owning application; WorldState never kills an unowned process |
| migration error | back up `.runtime/worldstate.db`, then inspect engine logs |

SQLite backup is a copy of `worldstate.db` made while WorldState is stopped.
PostgreSQL deployments should use native database backup tooling.
