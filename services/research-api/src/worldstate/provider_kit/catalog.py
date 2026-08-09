"""YAML catalog loading and offline structural validation."""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from worldstate.macro_core.enums import AvailabilityMethod, AvailabilityPrecision
from worldstate.macro_core.errors import CatalogValidationError

_CANONICAL_KEY = re.compile(r"^[A-Z0-9]+(?:\.[A-Z0-9_]+){2,}$")


class AvailabilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: AvailabilityMethod
    precision: AvailabilityPrecision
    release_lag_days: int | None = Field(default=None, ge=0)


class CatalogSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_key: str
    provider: str
    native_id: str
    entity: str
    title: str
    frequency: str
    unit: str
    transform: str
    orientation: int
    state_dimensions: list[str]
    weight: float = Field(gt=0)
    freshness_half_life_days: float = Field(gt=0)
    minimum_history: int = Field(gt=0)
    availability: AvailabilityPolicy
    tags: list[str]
    source_url: str

    @field_validator("canonical_key")
    @classmethod
    def validate_canonical_key(cls, value: str) -> str:
        if not _CANONICAL_KEY.fullmatch(value):
            raise ValueError("must be uppercase and contain at least three dot-separated segments")
        return value

    @field_validator("orientation")
    @classmethod
    def validate_orientation(cls, value: int) -> int:
        if value not in {-1, 1}:
            raise ValueError("must be -1 or 1")
        return value


class CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    series: list[CatalogSeries]


class CatalogValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    files: int
    series: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogValidationError(
            f"Unable to read catalog file {path.name}",
            details={"path": str(path), "reason": type(exc).__name__},
        ) from exc


def load_catalog(catalog_root: Path) -> list[CatalogSeries]:
    """Load all catalog files and reject duplicates or malformed entries."""

    catalog_dir = catalog_root / "catalogs"
    paths = sorted(catalog_dir.glob("*.yaml"))
    if not paths:
        raise CatalogValidationError(
            "No catalog files found",
            details={"catalog_dir": str(catalog_dir)},
        )

    records: list[CatalogSeries] = []
    errors: list[str] = []
    for path in paths:
        try:
            document = CatalogFile.model_validate(_read_yaml(path))
            records.extend(document.series)
        except ValidationError as exc:
            errors.append(f"{path.name}: {exc}")

    canonical_seen: set[str] = set()
    native_seen: set[tuple[str, str]] = set()
    for item in records:
        if item.canonical_key in canonical_seen:
            errors.append(f"duplicate canonical_key: {item.canonical_key}")
        canonical_seen.add(item.canonical_key)
        native_key = (item.provider, item.native_id)
        if native_key in native_seen:
            errors.append(f"duplicate provider/native_id: {item.provider}/{item.native_id}")
        native_seen.add(native_key)

    if errors:
        raise CatalogValidationError("Catalog validation failed", details={"errors": errors})
    return records


def validate_catalog(catalog_root: Path) -> CatalogValidationResult:
    """Return a structured offline validation summary."""

    try:
        series = load_catalog(catalog_root)
    except CatalogValidationError as exc:
        errors = exc.details.get("errors")
        return CatalogValidationResult(
            status="invalid",
            files=len(list((catalog_root / "catalogs").glob("*.yaml"))),
            series=0,
            errors=list(errors) if isinstance(errors, list) else [exc.message],
        )
    return CatalogValidationResult(
        status="valid",
        files=len(list((catalog_root / "catalogs").glob("*.yaml"))),
        series=len(series),
        warnings=["live provider metadata is checked during synchronization"],
    )
