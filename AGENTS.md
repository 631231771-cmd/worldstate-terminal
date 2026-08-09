# AGENTS.md

WorldState Terminal is a local-first macro research and cross-asset event-analysis
application. It is not a news wall or a geopolitical map.

## Repository map

- `services/research-api`: FastAPI, SQLAlchemy, Alembic and domain logic.
- `apps/terminal-ui`: Preact terminal interface.
- `apps/desktop-tauri`: Windows desktop shell.
- `data/fixtures`: traceable demonstrations, never presented as live data.
- `data/macro`: indicator and macro taxonomy inputs.
- `docs`: architecture, methodology, data and desktop documentation.
- `research`: migration checks and reproducible research outputs.
- `project-memory`: hand-off notes that can be opened as an Obsidian vault.

## Dependency direction

`macro_core` and `market_core` are foundational. `event_engine` may use them;
`research_engine` may use the cores and event engine; `ai_researcher` only
summarizes a completed EvidencePack. HTTP and application orchestration remain
outside all domain packages. Keep provider-specific schemas behind
`provider_kit`.

## Non-negotiable research rules

- Store release values and consensus snapshots append-only and point-in-time.
- Keep source, capture time, quality grade, fixture/manual/proxy status visible.
- Never label a proxy instrument as the original instrument.
- Historical filters are fixed before seeing the result; sample-size thresholds
  control whether statistics, case studies or no inference are shown.
- “Earliest reaction” means earliest statistically significant observed reaction
  at the available bar resolution, not causality or execution order.
- Explanations contain confirmed facts, historical relationships, hypotheses,
  competing explanations and data gaps. They do not claim a unique cause.
- AI receives only an EvidencePack and may not invent missing observations.

## Local validation

From the repository root:

```powershell
.\WorldState.bat migrate
.\WorldState.bat bootstrap
.\WorldState.bat build

$env:PYTHONPATH="$PWD\services\research-api\src"
services\research-api\.venv\Scripts\python.exe -m ruff check services\research-api
services\research-api\.venv\Scripts\python.exe -m mypy services\research-api\src services\research-api\tests
services\research-api\.venv\Scripts\python.exe -m pytest services\research-api\tests
npm run build --prefix apps\terminal-ui
```

Never commit `.runtime`, local databases, credentials, imported proprietary
consensus data, generated builds or dependency directories.
