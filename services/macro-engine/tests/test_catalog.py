from pathlib import Path

from macro_engine.config import default_catalog_root
from macro_engine.ingestion.catalog import load_catalog, validate_catalog


def test_repository_catalog_is_structurally_valid() -> None:
    result = validate_catalog(default_catalog_root())

    assert result.status == "valid"
    assert result.files == 4
    assert result.series == 8
    assert result.errors == []
    assert result.warnings


def test_loader_rejects_duplicate_canonical_keys(tmp_path: Path) -> None:
    catalogs = tmp_path / "catalogs"
    catalogs.mkdir()
    item = """
canonical_key: US.GROWTH.TEST
provider: fixture
native_id: TEST
entity: US
title: Test
frequency: monthly
unit: index
transform: level
orientation: 1
state_dimensions: [growth]
weight: 1
freshness_half_life_days: 30
minimum_history: 12
availability: {method: unknown, precision: unknown}
tags: [fixture]
source_url: https://example.test/series/TEST
"""
    indented_item = item.strip().replace("\n", "\n    ")
    (catalogs / "duplicate.yaml").write_text(
        f"version: 1\nseries:\n  - {indented_item}\n  - {indented_item}\n",
        encoding="utf-8",
    )

    result = validate_catalog(tmp_path)

    assert result.status == "invalid"
    assert any("duplicate canonical_key" in error for error in result.errors)


def test_loader_reports_missing_catalog_directory(tmp_path: Path) -> None:
    result = validate_catalog(tmp_path)

    assert result.status == "invalid"
    assert result.files == 0
    assert result.errors == ["No catalog files found"]


def test_loaded_records_are_normalized() -> None:
    records = load_catalog(default_catalog_root())

    assert {record.provider for record in records} == {"fred_alfred"}
    assert all(record.orientation in {-1, 1} for record in records)
