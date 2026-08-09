"""Select event-linked market evidence without crossing providers or contracts."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worldstate.application.data_foundation_service import json_safe
from worldstate.db.models import MacroRelease, MarketBar, MarketDataManifest, ReleaseStage


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _contract_identity(manifest: MarketDataManifest) -> str:
    if manifest.futures_contract_id is not None:
        return f"contract-id:{manifest.futures_contract_id}"
    if manifest.contract_code:
        return f"contract-code:{manifest.contract_code}"
    return f"source-symbol:{manifest.source_symbol}"


def _quality_rank(grade: str) -> int:
    return {"A": 5, "B": 4, "C": 3, "D": 2, "UNKNOWN": 1}.get(grade.upper(), 0)


def _bar_matches_manifest(bar: MarketBar, manifest: MarketDataManifest) -> bool:
    if not (
        bar.instrument_id == manifest.instrument_id
        and bar.provider_key == manifest.provider_key
        and bar.interval_seconds == manifest.interval_seconds
        and bar.data_mode == manifest.data_mode
        and _aware(manifest.start_at) <= _aware(bar.timestamp) <= _aware(manifest.end_at)
    ):
        return False
    if manifest.futures_contract_id is not None:
        return (
            bar.futures_contract_id == manifest.futures_contract_id
            and bar.contract_code == (manifest.contract_code or bar.contract_code)
        )
    if manifest.contract_code:
        return bar.contract_code == manifest.contract_code
    return bar.source_symbol == manifest.source_symbol


def _deduplicate_bars(rows: list[MarketBar]) -> tuple[tuple[MarketBar, ...], int]:
    """Keep one deterministic revision per timestamp within one selected series."""

    selected: dict[datetime, MarketBar] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            _aware(item.timestamp),
            _aware(item.fetched_at),
            int(item.id or 0),
        ),
    ):
        selected[_aware(row.timestamp)] = row
    ordered = tuple(selected[key] for key in sorted(selected))
    return ordered, max(0, len(rows) - len(ordered))


@dataclass(frozen=True, slots=True)
class SelectedMarketSeries:
    instrument_id: uuid.UUID
    interval_seconds: int
    provider_key: str
    futures_contract_id: uuid.UUID | None
    contract_code: str | None
    source_symbol: str
    dataset: str
    schema_name: str
    manifests: tuple[MarketDataManifest, ...]
    bars: tuple[MarketBar, ...]
    candidate_group_count: int
    duplicates_dropped: int
    limitations: tuple[str, ...]

    @property
    def manifest_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(row.id for row in self.manifests)

    @property
    def quality_grade(self) -> str:
        return max(
            (row.quality_grade for row in self.manifests),
            key=_quality_rank,
            default="UNKNOWN",
        )

    @property
    def daily_boundary(self) -> str | None:
        values = {
            str(row.metadata_json.get("daily_boundary"))
            for row in self.manifests
            if row.metadata_json.get("daily_boundary")
        }
        if len(values) == 1:
            return next(iter(values))
        return ",".join(sorted(values)) if values else None

    @property
    def session_close_semantics(self) -> str:
        if self.interval_seconds != 86_400:
            return "intraday"
        declared = {
            str(row.metadata_json.get("daily_boundary", "")).lower()
            for row in self.manifests
        }
        supported = any(
            row.metadata_json.get("session_close_semantics_supported") is True
            or str(row.metadata_json.get("daily_boundary", "")).lower()
            in {"session_close", "exchange_session_close", "settlement"}
            for row in self.manifests
        )
        if supported:
            return "exchange_session_close"
        if "utc" in declared:
            return "utc_day"
        return "unknown_daily_boundary"

    def snapshot(self, *, instrument_key: str) -> dict[str, object]:
        return {
            "selection_version": "release-manifest-series-v1",
            "instrument_id": str(self.instrument_id),
            "instrument_key": instrument_key,
            "interval_seconds": self.interval_seconds,
            "provider_key": self.provider_key,
            "dataset": self.dataset,
            "schema_name": self.schema_name,
            "futures_contract_id": (
                str(self.futures_contract_id) if self.futures_contract_id else None
            ),
            "contract_code": self.contract_code,
            "source_symbol": self.source_symbol,
            "candidate_group_count": self.candidate_group_count,
            "duplicates_dropped": self.duplicates_dropped,
            "daily_boundary": self.daily_boundary,
            "session_close_semantics": self.session_close_semantics,
            "limitations": list(self.limitations),
            "manifests": [
                {
                    "manifest_id": str(row.id),
                    "manifest_hash": row.manifest_hash,
                    "provider_run_id": (
                        str(row.provider_run_id) if row.provider_run_id else None
                    ),
                    "source_artifact_id": (
                        str(row.source_artifact_id) if row.source_artifact_id else None
                    ),
                    "release_stage_id": (
                        str(row.release_stage_id) if row.release_stage_id else None
                    ),
                    "start_at": _aware(row.start_at).isoformat(),
                    "end_at": _aware(row.end_at).isoformat(),
                    "row_count": row.row_count,
                    "quality_grade": row.quality_grade,
                    "metadata": json_safe(row.metadata_json),
                }
                for row in self.manifests
            ],
            "selected_bars": [
                {
                    "market_bar_id": row.id,
                    "timestamp": _aware(row.timestamp).isoformat(),
                    "instrument_id": str(row.instrument_id),
                    "futures_contract_id": (
                        str(row.futures_contract_id) if row.futures_contract_id else None
                    ),
                    "provider_key": row.provider_key,
                    "source_symbol": row.source_symbol,
                    "contract_code": row.contract_code,
                    "interval_seconds": row.interval_seconds,
                    "open": str(row.open_value),
                    "high": str(row.high_value),
                    "low": str(row.low_value),
                    "close": str(row.close_value),
                    "volume": str(row.volume) if row.volume is not None else None,
                    "quality_id": str(row.quality_id) if row.quality_id else None,
                    "fetched_at": _aware(row.fetched_at).isoformat(),
                    "metadata": json_safe(row.metadata_json),
                }
                for row in self.bars
            ],
        }


@dataclass(frozen=True, slots=True)
class ReleaseMarketSelection:
    release_id: uuid.UUID
    series: dict[tuple[uuid.UUID, int], SelectedMarketSeries]
    rejected_manifest_ids: tuple[uuid.UUID, ...]

    def get(
        self, instrument_id: uuid.UUID, interval_seconds: int
    ) -> SelectedMarketSeries | None:
        return self.series.get((instrument_id, interval_seconds))

    @property
    def selected_manifest_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(
            manifest_id
            for key in sorted(self.series, key=lambda item: (str(item[0]), item[1]))
            for manifest_id in self.series[key].manifest_ids
        )


async def select_release_market_data(
    session: AsyncSession,
    release: MacroRelease,
    stages: list[ReleaseStage],
) -> ReleaseMarketSelection:
    """Choose one provider/contract/dataset series per instrument and granularity."""

    manifests = list(
        (
            await session.scalars(
                select(MarketDataManifest)
                .where(
                    MarketDataManifest.macro_release_id == release.id,
                    MarketDataManifest.data_mode == release.data_mode,
                    MarketDataManifest.interval_seconds.in_((60, 86_400)),
                    MarketDataManifest.row_count > 0,
                )
                .order_by(
                    MarketDataManifest.instrument_id,
                    MarketDataManifest.interval_seconds,
                    MarketDataManifest.created_at,
                    MarketDataManifest.id,
                )
            )
        ).all()
    )
    grouped: dict[
        tuple[uuid.UUID, int, str, str, str, str], list[MarketDataManifest]
    ] = defaultdict(list)
    for manifest in manifests:
        grouped[
            (
                manifest.instrument_id,
                manifest.interval_seconds,
                manifest.provider_key,
                _contract_identity(manifest),
                manifest.dataset,
                manifest.schema_name,
            )
        ].append(manifest)

    stage_times = [_aware(stage.released_at or stage.scheduled_at) for stage in stages]
    release_at = _aware(release.released_at or release.scheduled_at)
    minute_lower = min(stage_times, default=release_at) - timedelta(minutes=60)
    minute_upper = max(stage_times, default=release_at) + timedelta(hours=4)
    daily_lower = release_at - timedelta(days=10)
    daily_upper = release_at + timedelta(days=12)
    candidates: dict[
        tuple[uuid.UUID, int],
        list[tuple[SelectedMarketSeries, tuple[int, float, int, float, str]]],
    ] = defaultdict(list)
    for group_key, group_manifests in grouped.items():
        instrument_id, interval, provider_key, _contract, dataset, schema = group_key
        lower, upper = (
            (minute_lower, minute_upper) if interval == 60 else (daily_lower, daily_upper)
        )
        relevant_manifests = tuple(
            row
            for row in group_manifests
            if _aware(row.end_at) >= lower and _aware(row.start_at) <= upper
        )
        if not relevant_manifests:
            continue
        query_lower = max(lower, min(_aware(row.start_at) for row in relevant_manifests))
        query_upper = min(upper, max(_aware(row.end_at) for row in relevant_manifests))
        rows = list(
            (
                await session.scalars(
                    select(MarketBar)
                    .where(
                        MarketBar.instrument_id == instrument_id,
                        MarketBar.provider_key == provider_key,
                        MarketBar.interval_seconds == interval,
                        MarketBar.data_mode == release.data_mode,
                        MarketBar.timestamp >= query_lower,
                        MarketBar.timestamp <= query_upper,
                    )
                    .order_by(MarketBar.timestamp, MarketBar.fetched_at, MarketBar.id)
                )
            ).all()
        )
        matched = [
            row
            for row in rows
            if any(_bar_matches_manifest(row, manifest) for manifest in relevant_manifests)
        ]
        deduplicated, duplicates_dropped = _deduplicate_bars(matched)
        first = relevant_manifests[0]
        limitations: list[str] = []
        if len(grouped[group_key]) > 1:
            limitations.append(
                "Multiple compatible event-linked manifests were merged only within the "
                "same provider, contract, dataset and schema."
            )
        if duplicates_dropped:
            limitations.append(
                f"{duplicates_dropped} duplicate timestamp revision(s) were deterministically "
                "removed within the selected series."
            )
        daily_boundaries = {
            str(row.metadata_json.get("daily_boundary", "")).upper()
            for row in relevant_manifests
        }
        if interval == 86_400 and "UTC" in daily_boundaries:
            limitations.append(
                "Daily bars use UTC-day boundaries and are not exchange settlement or "
                "session-close observations."
            )
        selected = SelectedMarketSeries(
            instrument_id=instrument_id,
            interval_seconds=interval,
            provider_key=provider_key,
            futures_contract_id=first.futures_contract_id,
            contract_code=first.contract_code,
            source_symbol=first.source_symbol,
            dataset=dataset,
            schema_name=schema,
            manifests=relevant_manifests,
            bars=deduplicated,
            candidate_group_count=0,
            duplicates_dropped=duplicates_dropped,
            limitations=tuple(limitations),
        )
        covered_seconds = sum(
            max(
                0.0,
                (
                    min(upper, _aware(row.end_at))
                    - max(lower, _aware(row.start_at))
                ).total_seconds(),
            )
            for row in relevant_manifests
        )
        score = (
            len(deduplicated),
            covered_seconds,
            max(_quality_rank(row.quality_grade) for row in relevant_manifests),
            max(_aware(row.created_at).timestamp() for row in relevant_manifests),
            "|".join(str(item) for item in group_key[2:]),
        )
        candidates[(instrument_id, interval)].append((selected, score))

    selected_series: dict[tuple[uuid.UUID, int], SelectedMarketSeries] = {}
    selected_manifest_ids: set[uuid.UUID] = set()
    for identity, options in candidates.items():
        chosen, _score = max(options, key=lambda item: item[1])
        chosen = SelectedMarketSeries(
            instrument_id=chosen.instrument_id,
            interval_seconds=chosen.interval_seconds,
            provider_key=chosen.provider_key,
            futures_contract_id=chosen.futures_contract_id,
            contract_code=chosen.contract_code,
            source_symbol=chosen.source_symbol,
            dataset=chosen.dataset,
            schema_name=chosen.schema_name,
            manifests=chosen.manifests,
            bars=chosen.bars,
            candidate_group_count=len(options),
            duplicates_dropped=chosen.duplicates_dropped,
            limitations=(
                chosen.limitations
                + (
                    (
                        f"Selected one of {len(options)} event-linked provider/contract "
                        "candidate series; candidates were never mixed.",
                    )
                    if len(options) > 1
                    else ()
                )
            ),
        )
        selected_series[identity] = chosen
        selected_manifest_ids.update(chosen.manifest_ids)

    return ReleaseMarketSelection(
        release_id=release.id,
        series=selected_series,
        rejected_manifest_ids=tuple(
            row.id for row in manifests if row.id not in selected_manifest_ids
        ),
    )


__all__ = [
    "ReleaseMarketSelection",
    "SelectedMarketSeries",
    "select_release_market_data",
]
