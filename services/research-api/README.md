# WorldState Research API

FastAPI service for point-in-time macro releases, cross-asset event windows,
historical matching and evidence-bounded explanations.

```powershell
python -m uv sync --all-groups
$env:PYTHONPATH="$PWD\src"
.venv\Scripts\python.exe -m worldstate.cli migrate
.venv\Scripts\python.exe -m worldstate.cli bootstrap
.venv\Scripts\python.exe -m worldstate.cli serve
```

The public contract is `/v2`; interactive documentation is available at
`/docs`. The default SQLite database can be replaced with PostgreSQL through
`WORLDSTATE_DATABASE_URL`.
