"""Automation-safe Macro Engine command line interface."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from macro_engine import __version__
from macro_engine.config import Settings
from macro_engine.ingestion.catalog import validate_catalog
from macro_engine.logging import REDACTED

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3


def emit(status: str, command: str, **details: Any) -> None:
    """Write one structured JSON summary to stdout."""

    print(json.dumps({"status": status, "command": command, **details}, sort_keys=True))


def unsupported(command: str, phase: str) -> NoReturn:
    emit("unsupported", command, available_in=phase, message="command is not implemented in Phase 1")
    raise SystemExit(EXIT_UNSUPPORTED)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="macro-engine", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the versioned FastAPI service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    subparsers.add_parser("migrate", help="apply Alembic migrations")

    catalog = subparsers.add_parser("catalog", help="catalog operations")
    catalog_subparsers = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_subparsers.add_parser("validate", help="validate local YAML catalog structure")

    sync = subparsers.add_parser("sync", help="synchronize provider observations")
    sync_group = sync.add_mutually_exclusive_group(required=True)
    sync_group.add_argument("--all", action="store_true")
    sync_group.add_argument("--provider")
    sync_group.add_argument("--series")

    backfill = subparsers.add_parser("backfill", help="backfill historical observations")
    backfill.add_argument("--from", dest="from_date", required=True)

    rebuild = subparsers.add_parser("rebuild-state", help="rebuild deterministic state snapshots")
    rebuild.add_argument("--from", dest="from_date", required=True)

    subparsers.add_parser("data-health", help="summarize local data health")

    export = subparsers.add_parser("export-series", help="export one canonical series")
    export.add_argument("series")
    export.add_argument("--output", type=Path)

    subparsers.add_parser("generate-brief", help="generate a deterministic daily brief")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()

    if args.command == "serve":
        import uvicorn

        uvicorn.run("macro_engine.main:app", host=args.host, port=args.port, factory=False)
        return EXIT_OK

    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        service_root = Path(__file__).resolve().parents[2]
        config = Config(service_root / "alembic.ini")
        command.upgrade(config, "head")
        emit("ok", "migrate", revision="head")
        return EXIT_OK

    if args.command == "catalog" and args.catalog_command == "validate":
        result = validate_catalog(settings.catalog_root)
        emit(result.status, "catalog validate", **result.model_dump(exclude={"status"}))
        return EXIT_OK if result.status == "valid" else EXIT_ERROR

    if args.command == "data-health":
        emit(
            "unavailable",
            "data-health",
            database="not_checked",
            providers={"fred_alfred": "not_configured" if not settings.fred_api_key else "unsupported"},
            message="no observations exist in the Phase 1 skeleton",
        )
        return EXIT_OK

    if args.command == "sync":
        unsupported("sync", "Phase 2")
    if args.command == "backfill":
        unsupported("backfill", "Phase 2")
    if args.command == "rebuild-state":
        unsupported("rebuild-state", "Phase 2")
    if args.command == "export-series":
        unsupported("export-series", "Phase 2")
    if args.command == "generate-brief":
        unsupported("generate-brief", "Phase 6")

    emit("error", str(args.command), message=REDACTED)
    return EXIT_USAGE


def main() -> None:
    """Console-script entry point."""

    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        emit("cancelled", "unknown")
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()

