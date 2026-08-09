"""Structured service errors."""

from typing import Any


class MacroEngineError(Exception):
    """Base error carrying a stable code and non-secret context."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class CatalogValidationError(MacroEngineError):
    """Raised when a catalog cannot be loaded safely."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__("catalog_invalid", message, details=details)


class ProviderError(MacroEngineError):
    """Normalized provider failure."""
