import json
from pathlib import Path
from typing import cast

import pytest

from macro_engine import cli
from macro_engine.config import default_catalog_root


def output_json(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    return cast(dict[str, object], json.loads(capsys.readouterr().out))


def test_catalog_validate_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MACRO_CATALOG_ROOT", str(default_catalog_root()))

    assert cli.run(["catalog", "validate"]) == cli.EXIT_OK
    output = output_json(capsys)
    assert output["status"] == "valid"
    assert output["series"] == 8


def test_data_health_is_honestly_unavailable(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run(["data-health"]) == cli.EXIT_OK
    output = output_json(capsys)
    assert output["status"] == "unavailable"
    assert output["database"] == "not_checked"


@pytest.mark.parametrize(
    ("arguments", "phase"),
    [
        (["sync", "--all"], "Phase 2"),
        (["backfill", "--from", "1990-01-01"], "Phase 2"),
        (["rebuild-state", "--from", "2000-01-01"], "Phase 2"),
        (["export-series", "US.GROWTH.TEST"], "Phase 2"),
        (["generate-brief"], "Phase 6"),
    ],
)
def test_future_commands_return_explicit_unsupported(
    arguments: list[str],
    phase: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.run(arguments)

    assert raised.value.code == cli.EXIT_UNSUPPORTED
    assert output_json(capsys)["available_in"] == phase


def test_serve_delegates_to_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        called.update({"app": app, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)

    host = "0.0.0.0"  # noqa: S104 - container binding is intentional
    assert cli.run(["serve", "--host", host, "--port", "9000"]) == cli.EXIT_OK
    assert called == {
        "app": "macro_engine.main:app",
        "host": host,
        "port": 9000,
        "factory": False,
    }


def test_migrate_delegates_to_alembic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called: list[str] = []

    def fake_upgrade(_config: object, revision: str) -> None:
        called.append(revision)

    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)

    assert cli.run(["migrate"]) == cli.EXIT_OK
    assert called == ["head"]
    assert output_json(capsys)["revision"] == "head"


def test_every_command_has_help() -> None:
    parser = cli.build_parser()
    help_text = parser.format_help()

    for command in [
        "serve",
        "migrate",
        "catalog",
        "sync",
        "backfill",
        "rebuild-state",
        "data-health",
        "export-series",
        "generate-brief",
    ]:
        assert command in help_text


def test_catalog_invalid_returns_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MACRO_CATALOG_ROOT", str(tmp_path))

    assert cli.run(["catalog", "validate"]) == cli.EXIT_ERROR
    assert output_json(capsys)["status"] == "invalid"
