from macro_engine.logging import REDACTED, redact_event, redact_value


def test_recursive_redaction() -> None:
    value = {
        "api_key": "secret",
        "nested": {"password": "secret", "ok": "value"},
        "items": ["Bearer abc.def", "postgresql://user:pass@example.test/db"],
    }

    redacted = redact_value(value)

    assert redacted["api_key"] == REDACTED
    assert redacted["nested"]["password"] == REDACTED
    assert redacted["nested"]["ok"] == "value"
    assert redacted["items"][0] == REDACTED
    assert "user:pass" not in redacted["items"][1]


def test_structlog_processor_returns_sanitized_mapping() -> None:
    result = redact_event(None, "info", {"event": "ok", "authorization": "Bearer abc"})

    assert result == {"event": "ok", "authorization": REDACTED}
