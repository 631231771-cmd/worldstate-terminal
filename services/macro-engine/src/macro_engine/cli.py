"""Automation-safe Macro Engine command line interface."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
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

    print(
        json.dumps(
            {"status": status, "command": command, **details},
            default=str,
            sort_keys=True,
        )
    )


def unsupported(command: str, phase: str) -> NoReturn:
    emit(
        "unsupported", command, available_in=phase, message="command is not implemented in Phase 1"
    )
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
    sync.add_argument(
        "--recent-days",
        type=int,
        default=None,
        help="limit observation retrieval to the most recent number of days",
    )

    backfill = subparsers.add_parser("backfill", help="backfill historical observations")
    backfill.add_argument("--from", dest="from_date", required=True)

    rebuild = subparsers.add_parser("rebuild-state", help="rebuild deterministic state snapshots")
    rebuild.add_argument("--from", dest="from_date", required=True)

    history = subparsers.add_parser("sync-history", help="synchronize revision history")
    history.add_argument("--series")

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
        catalog_result = validate_catalog(settings.catalog_root)
        emit(
            catalog_result.status,
            "catalog validate",
            **catalog_result.model_dump(exclude={"status"}),
        )
        return EXIT_OK if catalog_result.status == "valid" else EXIT_ERROR

    if args.command == "data-health":
        from macro_engine.db.session import create_engine
        from macro_engine.services.terminal import data_health

        engine = create_engine(settings.database_url)

        async def inspect_health() -> dict[str, Any]:
            try:
                return await data_health(engine, settings)
            finally:
                await engine.dispose()

        health_result = asyncio.run(inspect_health())
        emit("ok", "data-health", **health_result)
        return EXIT_OK

    if args.command == "sync":
        from macro_engine.db.session import create_engine
        from macro_engine.services.terminal import synchronize

        engine = create_engine(settings.database_url)
        start = (
            date.today() - timedelta(days=args.recent_days)
            if args.recent_days is not None
            else None
        )
        selected = [args.series] if args.series else None

        async def run_sync() -> Any:
            try:
                return await synchronize(
                    engine,
                    settings,
                    canonical_keys=selected,
                    start=start,
                )
            finally:
                await engine.dispose()

        sync_result = asyncio.run(run_sync())
        emit(
            "ok",
            "sync",
            mode=sync_result.mode,
            inserted=sync_result.inserted,
            updated=sync_result.updated,
            skipped=sync_result.skipped,
            warnings=sync_result.warnings,
        )
        return EXIT_OK
    if args.command == "backfill":
        from macro_engine.db.session import create_engine
        from macro_engine.services.terminal import synchronize

        engine = create_engine(settings.database_url)

        async def run_backfill() -> Any:
            try:
                return await synchronize(
                    engine,
                    settings,
                    start=date.fromisoformat(args.from_date),
                )
            finally:
                await engine.dispose()

        backfill_result = asyncio.run(run_backfill())
        emit(
            "ok",
            "backfill",
            mode=backfill_result.mode,
            inserted=backfill_result.inserted,
            updated=backfill_result.updated,
            skipped=backfill_result.skipped,
            warnings=backfill_result.warnings,
        )
        return EXIT_OK
    if args.command == "rebuild-state":
        from macro_engine.db.session import create_engine
        from macro_engine.services.terminal import build_snapshot

        engine = create_engine(settings.database_url)

        async def rebuild() -> dict[str, Any]:
            try:
                return await build_snapshot(
                    engine,
                    settings,
                    as_of=datetime.combine(
                        date.fromisoformat(args.from_date),
                        datetime.min.time(),
                        tzinfo=UTC,
                    ),
                )
            finally:
                await engine.dispose()

        state_result = asyncio.run(rebuild())
        emit(
            "ok",
            "rebuild-state",
            methodology=state_result["methodology_version"],
            states=len(state_result["states"]),
        )
        return EXIT_OK
    if args.command == "sync-history":
        from macro_engine.db.session import create_engine
        from macro_engine.services.terminal import synchronize

        engine = create_engine(settings.database_url)

        async def run_history() -> Any:
            try:
                return await synchronize(
                    engine,
                    settings,
                    canonical_keys=[args.series] if args.series else None,
                )
            finally:
                await engine.dispose()

        history_result = asyncio.run(run_history())
        emit(
            "ok",
            "sync-history",
            mode=history_result.mode,
            inserted=history_result.inserted,
            updated=history_result.updated,
            skipped=history_result.skipped,
            warnings=history_result.warnings,
        )
        return EXIT_OK
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
