from pathlib import Path

from pydantic import SecretStr

from macro_engine.config import Settings, default_catalog_root


def test_defaults_match_product_contract() -> None:
    settings = Settings()

    assert settings.default_locale == "zh-CN"
    assert settings.default_timezone == "Asia/Taipei"
    assert settings.strict_point_in_time is True
    assert settings.writes_available is False
    assert settings.database_url.startswith("sqlite+aiosqlite:///")
    assert Settings(clawfeed_base_url="").clawfeed_base_url is None
    assert default_catalog_root().name == "macro"


def test_explicit_environment_aliases(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setenv("MACRO_DEFAULT_LOCALE", "en")  # type: ignore[attr-defined]
    monkeypatch.setenv("MACRO_ENABLE_WRITES", "true")  # type: ignore[attr-defined]
    monkeypatch.setenv("MACRO_WRITE_TOKEN", "local-test-token")  # type: ignore[attr-defined]
    monkeypatch.setenv("FRED_API_KEY", "fred-test-key")  # type: ignore[attr-defined]
    monkeypatch.setenv("MACRO_X_BEARER_TOKEN", "x-read-token")  # type: ignore[attr-defined]
    monkeypatch.setenv("MACRO_CLAWFEED_URL", "http://127.0.0.1:8767")  # type: ignore[attr-defined]
    monkeypatch.setenv("MACRO_CATALOG_ROOT", str(tmp_path))  # type: ignore[attr-defined]

    settings = Settings()

    assert settings.default_locale == "en"
    assert settings.writes_available is True
    assert isinstance(settings.write_token, SecretStr)
    assert isinstance(settings.fred_api_key, SecretStr)
    assert isinstance(settings.x_bearer_token, SecretStr)
    assert settings.x_bearer_token.get_secret_value() == "x-read-token"
    assert str(settings.clawfeed_base_url) == "http://127.0.0.1:8767/"
    assert settings.catalog_root == tmp_path
