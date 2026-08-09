"""Typed settings for the local-first WorldState research service."""

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def repository_root() -> Path:
    override = os.getenv("WORLDSTATE_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "data").is_dir() and (
            (parent / "services" / "research-api").is_dir() or (parent / "pyproject.toml").is_file()
        ):
            return parent
    return Path.cwd().resolve()


def default_catalog_root() -> Path:
    return repository_root() / "data" / "macro"


def default_runtime_root() -> Path:
    return repository_root() / ".runtime"


def default_database_url() -> str:
    runtime_root = default_runtime_root()
    runtime_root.mkdir(parents=True, exist_ok=True)
    database_path = (runtime_root / "worldstate.db").resolve()
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
        populate_by_name=True,
    )

    database_url: str = Field(
        default_factory=default_database_url,
        validation_alias=AliasChoices("WORLDSTATE_DATABASE_URL", "MACRO_DATABASE_URL"),
    )
    api_url: HttpUrl = Field(
        default=HttpUrl("http://127.0.0.1:8000"),
        validation_alias=AliasChoices("WORLDSTATE_API_URL", "MACRO_ENGINE_URL"),
    )
    write_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("WORLDSTATE_WRITE_TOKEN", "MACRO_WRITE_TOKEN"),
    )
    enable_writes: bool = Field(
        default=False,
        validation_alias=AliasChoices("WORLDSTATE_ENABLE_WRITES", "MACRO_ENABLE_WRITES"),
    )
    default_locale: str = Field(default="zh-CN", validation_alias="WORLDSTATE_DEFAULT_LOCALE")
    default_timezone: str = Field(
        default="Asia/Shanghai", validation_alias="WORLDSTATE_DEFAULT_TIMEZONE"
    )
    strict_point_in_time: bool = Field(
        default=True, validation_alias="WORLDSTATE_STRICT_POINT_IN_TIME"
    )
    catalog_root: Path = Field(
        default_factory=default_catalog_root,
        validation_alias="WORLDSTATE_CATALOG_ROOT",
    )
    log_level: str = Field(default="INFO", validation_alias="WORLDSTATE_LOG_LEVEL")
    health_timeout_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        validation_alias="WORLDSTATE_HEALTH_TIMEOUT_SECONDS",
    )
    fred_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FRED_API_KEY", "WORLDSTATE_FRED_API_KEY"),
    )
    bls_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("BLS_API_KEY", "WORLDSTATE_BLS_API_KEY"),
    )
    trading_economics_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TRADING_ECONOMICS_API_KEY",
            "WORLDSTATE_TRADING_ECONOMICS_API_KEY",
        ),
    )
    databento_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABENTO_API_KEY", "WORLDSTATE_DATABENTO_API_KEY"),
    )
    data_start_date: date = Field(
        default=date(2015, 1, 1),
        validation_alias="WORLDSTATE_DATA_START_DATE",
    )
    market_intraday_pre_minutes: int = Field(
        default=90,
        ge=1,
        le=24 * 60,
        validation_alias="WORLDSTATE_MARKET_INTRADAY_PRE_MINUTES",
    )
    market_intraday_post_minutes: int = Field(
        default=240,
        ge=1,
        le=24 * 60,
        validation_alias="WORLDSTATE_MARKET_INTRADAY_POST_MINUTES",
    )
    market_daily_pre_days: int = Field(
        default=5,
        ge=0,
        le=30,
        validation_alias="WORLDSTATE_MARKET_DAILY_PRE_DAYS",
    )
    market_daily_post_days: int = Field(
        default=5,
        ge=0,
        le=30,
        validation_alias="WORLDSTATE_MARKET_DAILY_POST_DAYS",
    )
    databento_max_estimated_cost_usd: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        validation_alias="WORLDSTATE_DATABENTO_MAX_ESTIMATED_COST_USD",
    )
    allow_paid_download: bool = Field(
        default=False,
        validation_alias="WORLDSTATE_ALLOW_PAID_DOWNLOAD",
    )
    demo_mode: bool = Field(default=False, validation_alias="WORLDSTATE_DEMO_MODE")
    scheduler_enabled: bool = Field(
        default=True,
        validation_alias="WORLDSTATE_SCHEDULER_ENABLED",
    )
    provider_timeout_seconds: float = Field(
        default=20.0,
        ge=1.0,
        le=120.0,
        validation_alias="WORLDSTATE_PROVIDER_TIMEOUT_SECONDS",
    )
    provider_retry_attempts: int = Field(
        default=3,
        ge=1,
        le=8,
        validation_alias="WORLDSTATE_PROVIDER_RETRY_ATTEMPTS",
    )
    trading_economics_monthly_quota: int | None = Field(
        default=None,
        ge=1,
        validation_alias="WORLDSTATE_TRADING_ECONOMICS_MONTHLY_QUOTA",
    )
    trading_economics_pit_entitled: bool = Field(
        default=False,
        validation_alias="WORLDSTATE_TRADING_ECONOMICS_PIT_ENTITLED",
    )
    openbb_enabled: bool = Field(default=False, validation_alias="WORLDSTATE_OPENBB_ENABLED")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    ai_provider: Literal["auto", "none", "openai", "ollama", "compatible"] = Field(
        default="auto", validation_alias="WORLDSTATE_AI_PROVIDER"
    )
    ai_model: str = Field(default="gpt-5.6-sol", validation_alias="WORLDSTATE_AI_MODEL")
    ai_base_url: HttpUrl = Field(
        default=HttpUrl("https://api.openai.com/v1"),
        validation_alias="WORLDSTATE_AI_BASE_URL",
    )
    ai_compatible_api_key: SecretStr | None = Field(
        default=None, validation_alias="WORLDSTATE_AI_COMPATIBLE_API_KEY"
    )
    ollama_base_url: HttpUrl | None = Field(default=None, validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3:8b", validation_alias="WORLDSTATE_OLLAMA_MODEL")
    ai_timeout_seconds: float = Field(
        default=45.0,
        ge=2.0,
        le=180.0,
        validation_alias="WORLDSTATE_AI_TIMEOUT_SECONDS",
    )

    @property
    def writes_available(self) -> bool:
        return self.enable_writes and self.write_token is not None

    @property
    def resolved_ai_provider(self) -> Literal["none", "openai", "ollama", "compatible"]:
        if self.ai_provider != "auto":
            return self.ai_provider
        if self.openai_api_key is not None:
            return "openai"
        if self.ollama_base_url is not None:
            return "ollama"
        if self.ai_compatible_api_key is not None:
            return "compatible"
        return "none"
