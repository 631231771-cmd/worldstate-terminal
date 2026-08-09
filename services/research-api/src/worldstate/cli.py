"""Command line entry point for the WorldState research service."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate import __version__
from worldstate.api.v2.data_router import (
    DEFAULT_ASSETS,
    DEFAULT_EVENT_TYPES,
    _redact_provider_message,
    build_data_coverage,
    build_provider_status,
    estimate_backfill_payload,
    normalize_multi_operation_result,
    parse_csv_values,
    run_calendar_sync,
    run_data_reconciliation,
    serialize_backfill_job,
    start_backfill,
)
from worldstate.api.v2.schemas import BackfillRequestInput
from worldstate.application.analysis_orchestrator import analyze_release
from worldstate.application.bootstrap_service import bootstrap_research_data
from worldstate.application.evidence_service import get_evidence_pack
from worldstate.application.licensed_sync_service import (
    snapshot_trading_economics_consensus,
    sync_databento_release_market,
)
from worldstate.application.official_sync_service import sync_official_data
from worldstate.application.release_queries import get_quality_overview
from worldstate.config import Settings
from worldstate.db.models import BackfillJob, MacroRelease
from worldstate.db.session import create_engine
from worldstate.macro_core.errors import MacroEngineError


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

    doctor = commands.add_parser(
        "data-doctor", help="check the v0.5 data foundation without exposing credentials"
    )
    doctor.add_argument("--output", type=Path)

    official = commands.add_parser(
        "sync-official", help="synchronize official BLS/Federal Reserve releases"
    )
    _add_range_arguments(official)
    official.add_argument("--event-types", default=",".join(DEFAULT_EVENT_TYPES))

    calendar = commands.add_parser("sync-calendar", help="synchronize official event calendars")
    _add_range_arguments(calendar)

    consensus = commands.add_parser(
        "snapshot-consensus", help="capture a pre-release consensus snapshot"
    )
    _add_range_arguments(consensus)
    consensus.add_argument("--release-id")
    consensus.add_argument("--pit-at", type=_datetime_argument)

    estimate = commands.add_parser(
        "estimate-backfill", help="estimate records, bytes and cost before backfill"
    )
    _add_backfill_arguments(estimate)

    backfill = commands.add_parser("backfill", help="persist an approved bounded backfill job")
    _add_backfill_arguments(backfill)

    market = commands.add_parser(
        "sync-market", help="synchronize event-linked Databento market windows"
    )
    market.add_argument("--release-id", required=True)
    market.add_argument("--assets", default=",".join(DEFAULT_ASSETS))
    market.add_argument("--no-daily", action="store_true")

    reconcile = commands.add_parser(
        "reconcile-data", help="compare authoritative and secondary source values"
    )
    reconcile.add_argument("--release-id")

    status = commands.add_parser(
        "data-status", help="show providers, coverage and durable job status"
    )
    status.add_argument("--data-mode", choices=("observed", "fixture"), default="observed")
    status.add_argument("--output", type=Path)
    return parser


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _datetime_argument(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("datetime must use ISO-8601") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a timezone offset")
    return parsed


def _add_range_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-date", type=_date_argument)
    parser.add_argument("--end-date", type=_date_argument)


def _add_backfill_arguments(parser: argparse.ArgumentParser) -> None:
    _add_range_arguments(parser)
    parser.add_argument("--event-types", default=",".join(DEFAULT_EVENT_TYPES))
    parser.add_argument("--assets", default=",".join(DEFAULT_ASSETS))


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))


def _write_optional_output(payload: object, output: Path | None) -> None:
    if output is not None:
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def _backfill_input(args: argparse.Namespace, settings: Settings) -> BackfillRequestInput:
    return BackfillRequestInput(
        start_date=args.start_date or settings.data_start_date,
        end_date=args.end_date or date.today(),
        event_types=parse_csv_values(args.event_types, DEFAULT_EVENT_TYPES),
        assets=parse_csv_values(args.assets, DEFAULT_ASSETS),
    )


def _resolved_range(
    args: argparse.Namespace,
    settings: Settings,
    *,
    default_start: date | None = None,
    default_end: date | None = None,
) -> tuple[date, date]:
    start = args.start_date or default_start or settings.data_start_date
    end = args.end_date or default_end or date.today()
    if end < start:
        raise ValueError("end_date must not be before start_date")
    return start, end


def _service_failure(command: str, exc: Exception, settings: Settings) -> dict[str, object]:
    if isinstance(exc, MacroEngineError):
        status = (
            "error"
            if exc.code in {"provider_request_invalid", "provider_data_not_found"}
            else "blocked"
        )
        return {
            "status": status,
            "command": command,
            "code": exc.code,
            "reason": _redact_provider_message(exc.message, settings),
            "error_type": type(exc).__name__,
        }
    if isinstance(exc, LookupError | ValueError):
        return {
            "status": "error",
            "command": command,
            "code": "invalid_request",
            "reason": str(exc),
            "error_type": type(exc).__name__,
        }
    return {
        "status": "error",
        "command": command,
        "code": "operation_failed",
        "reason": "Provider operation failed; inspect the local provider run.",
        "error_type": type(exc).__name__,
    }


def _result_exit_code(result: dict[str, object]) -> int:
    status = str(result.get("status", "error"))
    if status in {"completed", "ok"}:
        return 0
    if status == "partial":
        return 4
    return 3 if status == "blocked" else 2


async def _consensus_range(
    engine: AsyncEngine,
    args: argparse.Namespace,
) -> tuple[date, date]:
    if args.release_id:
        try:
            release_id = uuid.UUID(args.release_id)
        except ValueError as exc:
            raise ValueError("release_id must be a UUID") from exc
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            release = await session.get(MacroRelease, release_id)
        if release is None:
            raise LookupError("macro release not found")
        release_date = release.scheduled_at.date()
        return args.start_date or release_date, args.end_date or release_date
    today = date.today()
    start = args.start_date or today
    end = args.end_date or (today + timedelta(days=7))
    if end < start:
        raise ValueError("end_date must not be before start_date")
    return start, end


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
        if args.command == "data-doctor":
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            providers = await build_provider_status(engine, settings, probe=True)
            configured = sum(item["configured"] for item in providers["items"])
            payload = {
                "status": "ok",
                "database": "reachable",
                "demo_mode": settings.demo_mode,
                "scheduler_enabled": settings.scheduler_enabled,
                "paid_download_enabled": settings.allow_paid_download,
                "databento_budget_limit_usd": float(settings.databento_max_estimated_cost_usd),
                "providers_configured_or_public": configured,
                "providers_total": len(providers["items"]),
                "providers": providers["items"],
                "credentials_exposed": False,
            }
            _write_optional_output(payload, args.output)
            _emit(payload)
            return 0
        if args.command == "data-status":
            providers = await build_provider_status(engine, settings)
            coverage = await build_data_coverage(engine, data_mode=args.data_mode)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                jobs = (
                    await session.scalars(
                        select(BackfillJob).order_by(BackfillJob.requested_at.desc()).limit(20)
                    )
                ).all()
            payload = {
                "status": "ok",
                "providers": providers,
                "coverage": coverage,
                "backfill_jobs": [serialize_backfill_job(item) for item in jobs],
            }
            _write_optional_output(payload, args.output)
            _emit(payload)
            return 0
        if args.command == "estimate-backfill":
            request = _backfill_input(args, settings)
            _, _, payload = await estimate_backfill_payload(engine, settings, request)
            _emit(payload)
            return 0
        if args.command == "backfill":
            request = _backfill_input(args, settings)
            _, payload = await start_backfill(engine, settings, request)
            _emit(payload)
            return 0 if payload["status"] == "pending" else 3
        if args.command == "sync-official":
            start, end = _resolved_range(args, settings)
            requested_event_types = parse_csv_values(args.event_types, DEFAULT_EVENT_TYPES)
            try:
                result = await sync_official_data(
                    engine,
                    settings,
                    start_date=start,
                    end_date=end,
                    event_types=requested_event_types,
                )
            except Exception as exc:
                failure = _service_failure(args.command, exc, settings)
                _emit(failure)
                return _result_exit_code(failure)
            result = normalize_multi_operation_result(result)
            failures = result.get("failures", {})
            if isinstance(failures, dict):
                result["failures"] = {
                    key: _redact_provider_message(value, settings)
                    for key, value in failures.items()
                }
            result["command"] = args.command
            result["requested_event_types"] = list(requested_event_types)
            _emit(result)
            return _result_exit_code(result)
        if args.command == "sync-calendar":
            start, end = _resolved_range(args, settings)
            result = await run_calendar_sync(
                engine,
                settings,
                start_date=start,
                end_date=end,
            )
            result["command"] = args.command
            _emit(result)
            return _result_exit_code(result)
        if args.command == "snapshot-consensus":
            try:
                start, end = await _consensus_range(engine, args)
                result = await snapshot_trading_economics_consensus(
                    engine,
                    settings,
                    start_date=start,
                    end_date=end,
                    pit_at=args.pit_at,
                )
            except Exception as exc:
                failure = _service_failure(args.command, exc, settings)
                _emit(failure)
                return _result_exit_code(failure)
            result["command"] = args.command
            _emit(result)
            return _result_exit_code(result)
        if args.command == "sync-market":
            try:
                release_id = uuid.UUID(args.release_id)
                roots = parse_csv_values(args.assets, DEFAULT_ASSETS)
                result = await sync_databento_release_market(
                    engine,
                    settings,
                    release_id=release_id,
                    roots=roots,
                    include_daily=not args.no_daily,
                )
            except Exception as exc:
                failure = _service_failure(args.command, exc, settings)
                _emit(failure)
                return _result_exit_code(failure)
            result["command"] = args.command
            _emit(result)
            return _result_exit_code(result)
        if args.command == "reconcile-data":
            try:
                reconcile_release_id = uuid.UUID(args.release_id) if args.release_id else None
                result = await run_data_reconciliation(engine, release_id=reconcile_release_id)
            except Exception as exc:
                failure = _service_failure(args.command, exc, settings)
                _emit(failure)
                return _result_exit_code(failure)
            result["command"] = args.command
            _emit(result)
            return _result_exit_code(result)
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
    except (LookupError, PermissionError, ValidationError, ValueError) as exc:
        _emit({"status": "error", "error_type": type(exc).__name__, "message": str(exc)})
        raise SystemExit(2) from None
    except Exception as exc:
        # Unexpected provider/database exceptions may contain request metadata.  Keep CLI
        # output useful without ever echoing a URL, header or credential value.
        _emit(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": "operation failed; inspect the local WorldState logs",
            }
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
