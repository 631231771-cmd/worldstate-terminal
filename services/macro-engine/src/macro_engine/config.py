"""Typed environment configuration for the Macro Engine."""

from pathlib import Path

from pydantic import AliasChoices, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_catalog_root() -> Path:
    """Return the repository catalog path for an editable source checkout."""

    return Path(__file__).resolve().parents[4] / "data" / "macro"


def default_runtime_root() -> Path:
    """Return the repository-local runtime directory used by desktop mode."""

    return Path(__file__).resolve().parents[4] / ".runtime"


def default_database_url() -> str:
    """Return a portable async SQLite URL for zero-configuration desktop use."""

    runtime_root = default_runtime_root()
    runtime_root.mkdir(parents=True, exist_ok=True)
    database_path = (runtime_root / "worldstate.db").resolve()
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


class Settings(BaseSettings):
    """Validated settings sourced from explicit Macro Engine environment keys."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
        populate_by_name=True,
    )

    database_url: str = Field(
        default_factory=default_database_url,
        validation_alias="MACRO_DATABASE_URL",
    )
    engine_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8000"),
        validation_alias="MACRO_ENGINE_URL",
    )
    write_token: SecretStr | None = Field(default=None, validation_alias="MACRO_WRITE_TOKEN")
    default_locale: str = Field(default="zh-CN", validation_alias="MACRO_DEFAULT_LOCALE")
    default_timezone: str = Field(
        default="Asia/Taipei",
        validation_alias="MACRO_DEFAULT_TIMEZONE",
    )
    strict_point_in_time: bool = Field(
        default=True,
        validation_alias="MACRO_STRICT_POINT_IN_TIME",
    )
    enable_writes: bool = Field(default=False, validation_alias="MACRO_ENABLE_WRITES")
    catalog_root: Path = Field(
        default_factory=default_catalog_root, validation_alias="MACRO_CATALOG_ROOT"
    )
    log_level: str = Field(default="INFO", validation_alias="MACRO_LOG_LEVEL")
    health_timeout_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        validation_alias="MACRO_HEALTH_TIMEOUT_SECONDS",
    )
    stale_after_hours: int = Field(
        default=72,
        ge=1,
        le=8760,
        validation_alias="MACRO_STALE_AFTER_HOURS",
    )

    fred_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FRED_API_KEY", "MACRO_FRED_API_KEY"),
    )
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    ollama_base_url: HttpUrl | None = Field(default=None, validation_alias="OLLAMA_BASE_URL")
    dbnomics_base_url: HttpUrl = Field(
        default=HttpUrl("https://api.db.nomics.world/v22"),
        validation_alias="DBNOMICS_BASE_URL",
    )

    @property
    def writes_available(self) -> bool:
        """Return whether write routes can be enabled safely."""

        return self.enable_writes and self.write_token is not None
