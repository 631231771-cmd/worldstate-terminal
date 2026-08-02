"""Command line entry point for the WorldState research service."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from worldstate import __version__
from worldstate.application.analysis_orchestrator import analyze_release
from worldstate.application.bootstrap_service import bootstrap_research_data
from worldstate.application.evidence_service import get_evidence_pack
from worldstate.application.release_queries import get_quality_overview
from worldstate.config import Settings
from worldstate.db.session import create_engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worldstate-research", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run API v2")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("migrate", help="apply database migrations")
    commands.add_parser("bootstrap", help="seed visible CPI/NFP/FOMC research demos")
    analyze = commands.add_parser("analyze", help="append an analysis run")
    analyze.add_argument("release_id")
    health = commands.add_parser("data-health", help="summarize data provenance")
    health.add_argument("--output", type=Path)
    evidence = commands.add_parser("export-evidence", help="export one EvidencePack")
    evidence.add_argument("release_id")
    evidence.add_argument("--output", type=Path, required=True)
    return parser


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


async def _run_async(args: argparse.Namespace, settings: Settings) -> int:
    engine = create_engine(settings.database_url)
    try:
        if args.command == "bootstrap":
            _emit(await bootstrap_research_data(engine))
            return 0
        if args.command == "analyze":
            run_id = await analyze_release(engine, args.release_id)
            _emit({"status": "completed", "analysis_run_id": run_id})
            return 0
        if args.command == "data-health":
            health_payload = await get_quality_overview(engine)
            if args.output:
                args.output.write_text(
                    json.dumps(health_payload, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
            _emit(health_payload)
            return 0
        if args.command == "export-evidence":
            evidence_payload = await get_evidence_pack(engine, args.release_id)
            if evidence_payload is None:
                _emit({"status": "error", "message": "macro release not found"})
                return 1
            args.output.write_text(
                json.dumps(evidence_payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            _emit({"status": "ok", "output": str(args.output)})
            return 0
    finally:
        await engine.dispose()
    return 2


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("worldstate.main:app", host=args.host, port=args.port, factory=False)
        return 0
    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        service_root = Path(__file__).resolve().parents[2]
        command.upgrade(Config(service_root / "alembic.ini"), "head")
        _emit({"status": "ok", "revision": "head"})
        return 0
    return asyncio.run(_run_async(args, settings))


def main() -> None:
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        _emit({"status": "cancelled"})
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
