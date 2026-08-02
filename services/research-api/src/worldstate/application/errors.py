"""Application-layer errors independent from HTTP transport."""


class AnalysisConflictError(RuntimeError):
    """Raised when a run cannot be created without violating run invariants."""


class ReproducibilityError(RuntimeError):
    """Raised when an immutable run cannot be replayed faithfully."""
