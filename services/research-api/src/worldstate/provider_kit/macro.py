"""Uniform asynchronous provider contract."""

from collections.abc import AsyncIterator, Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from worldstate.macro_core.models import (
    ObservationRecord,
    ProviderHealth,
    ReleaseRecord,
    SeriesMetadata,
    SeriesSearchResult,
)


@runtime_checkable
class MacroProvider(Protocol):
    """Provider boundary; third-party response shapes must not cross it."""

    key: str

    async def search_series(
        self, query: str, *, limit: int = 25
    ) -> Sequence[SeriesSearchResult]: ...

    async def fetch_metadata(self, native_id: str) -> SeriesMetadata: ...

    def fetch_observations(
        self,
        native_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> AsyncIterator[ObservationRecord]: ...

    async def fetch_vintages(self, native_id: str) -> Sequence[date]: ...

    async def fetch_releases(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> Sequence[ReleaseRecord]: ...

    async def healthcheck(self) -> ProviderHealth: ...
