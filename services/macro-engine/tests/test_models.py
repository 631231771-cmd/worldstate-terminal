from pathlib import Path

from macro_engine.db.base import Base
from macro_engine.db import models as _models  # noqa: F401


def test_initial_schema_contains_required_entities_and_indexes() -> None:
    required = {
        "providers",
        "economic_entities",
        "series",
        "observations",
        "releases",
        "release_series",
        "sync_runs",
        "state_definitions",
        "state_components",
        "state_snapshots",
        "causal_nodes",
        "causal_edges",
        "theses",
        "thesis_conditions",
        "thesis_evidence",
        "thesis_snapshots",
    }

    assert required == set(Base.metadata.tables)
    observation_indexes = {index.name for index in Base.metadata.tables["observations"].indexes}
    assert "ix_observations_as_of" in observation_indexes
    assert "ix_observations_latest" in observation_indexes


def test_production_code_never_uses_create_all() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))

    assert "create_all" not in sources

