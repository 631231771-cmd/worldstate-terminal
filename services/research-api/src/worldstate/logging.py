"""Structured logging with recursive secret redaction."""

import logging
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|bearer|password|secret|token|database[_-]?url|connection)", re.I
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]+@", re.I)
REDACTED = "[REDACTED]"


def redact_value(value: Any) -> Any:
    """Recursively redact secret-looking keys and credential-bearing strings."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _SENSITIVE_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", _BEARER.sub(REDACTED, value))
    return value


def redact_event(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Structlog processor that redacts the complete event mapping."""

    return dict(redact_value(event_dict))


def configure_logging(level: str = "INFO") -> None:
    """Configure standard logging and JSON structlog output."""

    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
