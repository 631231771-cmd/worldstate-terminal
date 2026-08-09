from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "worldstate"

FORBIDDEN_DEPENDENCIES = {
    "macro_core": {
        "event_engine",
        "research_engine",
        "ai_researcher",
        "application",
        "api",
        "provider_kit",
        "db",
    },
    "market_core": {
        "event_engine",
        "research_engine",
        "ai_researcher",
        "application",
        "api",
        "provider_kit",
        "db",
    },
    "event_engine": {"research_engine", "ai_researcher", "application", "api", "db"},
    "research_engine": {"ai_researcher", "application", "api", "db"},
    "ai_researcher": {"application", "api", "db"},
}


def imported_worldstate_domains(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    domains: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        for name in names:
            parts = name.split(".")
            if len(parts) >= 2 and parts[0] == "worldstate":
                domains.add(parts[1])
    return domains


def test_domain_dependency_direction_is_enforced() -> None:
    violations: list[str] = []
    for domain, forbidden in FORBIDDEN_DEPENDENCIES.items():
        for path in (PACKAGE_ROOT / domain).rglob("*.py"):
            invalid = imported_worldstate_domains(path) & forbidden
            if invalid:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT)} imports {', '.join(sorted(invalid))}"
                )
    assert violations == [], "\n".join(violations)


def test_legacy_world_monitor_domains_are_absent() -> None:
    forbidden_names = {
        "news",
        "geopolitics",
        "map",
        "conflict",
        "military",
        "aviation",
        "maritime",
    }
    present = {path.name for path in PACKAGE_ROOT.iterdir() if path.is_dir()}
    assert present.isdisjoint(forbidden_names)


def test_application_router_uses_focused_services_and_legacy_facade_stays_small() -> None:
    router = PACKAGE_ROOT / "api" / "v2" / "router.py"
    source = router.read_text(encoding="utf-8")
    assert "worldstate.application.events" not in source
    required = {
        "bootstrap_service.py",
        "release_commands.py",
        "consensus_service.py",
        "market_import_service.py",
        "analysis_orchestrator.py",
        "analysis_persistence.py",
        "release_queries.py",
        "evidence_service.py",
        "report_service.py",
    }
    present = {path.name for path in (PACKAGE_ROOT / "application").glob("*.py")}
    assert required <= present
    facade = (PACKAGE_ROOT / "application" / "events.py").read_text(encoding="utf-8")
    assert len(facade.splitlines()) < 80
    assert "Compatibility facade" in facade
