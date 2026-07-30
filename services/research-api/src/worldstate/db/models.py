"""Database v3 persistence models for the WorldState research terminal.

The schema deliberately separates releases, point-in-time values, consensus
snapshots, market observations, analysis runs, and explanations.  No table in
this module represents a news or geopolitical event.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from worldstate.db.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
DECIMAL_VALUE = Numeric(precision=30, scale=12)
IDENTITY_INTEGER = BigInteger().with_variant(Integer(), "sqlite")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# Retained point-in-time macro-series infrastructure.  These are not event
# models and remain useful for regime construction and official data vintages.
class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(IDENTITY_INTEGER, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    terms_url: Mapped[str | None] = mapped_column(String(2048))


class EconomicEntity(Base):
    __tablename__ = "economic_entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('country','economic_area','global','region')",
            name="ck_economic_entities_type",
        ),
    )

    id: Mapped[int] = mapped_column(IDENTITY_INTEGER, primary_key=True, autoincrement=True)
    iso2: Mapped[str | None] = mapped_column(String(2), unique=True)
    iso3: Mapped[str | None] = mapped_column(String(3), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("economic_entities.id"))
    currency: Mapped[str | None] = mapped_column(String(3))
    timezone: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class Series(TimestampMixin, Base):
    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("provider_id", "native_id", name="uq_series_provider_native"),
        Index("ix_series_entity_active", "entity_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    native_id: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    entity_id: Mapped[int] = mapped_column(ForeignKey("economic_entities.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(128), nullable=False)
    seasonal_adjustment: Mapped[str | None] = mapped_column(String(128))
    observation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    release_key: Mapped[str | None] = mapped_column(String(255))
    availability_method: Mapped[str] = mapped_column(String(64), nullable=False)
    availability_precision: Mapped[str] = mapped_column(String(32), nullable=False)
    default_transform: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint(
            "series_id",
            "period_start",
            "vintage_date",
            name="uq_observations_series_period_vintage",
        ),
        Index("ix_observations_series_period", "series_id", "period_start"),
        Index("ix_observations_series_available", "series_id", "available_at"),
    )

    id: Mapped[int] = mapped_column(IDENTITY_INTEGER, primary_key=True, autoincrement=True)
    series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("series.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    raw_value: Mapped[str | None] = mapped_column(Text)
    vintage_date: Mapped[date] = mapped_column(Date, nullable=False)
    realtime_start: Mapped[date | None] = mapped_column(Date)
    realtime_end: Mapped[date | None] = mapped_column(Date)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability_method: Mapped[str] = mapped_column(String(64), nullable=False)
    availability_precision: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_preliminary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_revised: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceArtifact(TimestampMixin, Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (
        UniqueConstraint("provider_key", "content_hash", name="uq_source_artifact_hash"),
        Index("ix_source_artifacts_published", "published_at", "provider_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    license_name: Mapped[str | None] = mapped_column(String(128))
    citation_text: Mapped[str | None] = mapped_column(Text)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class Indicator(TimestampMixin, Base):
    __tablename__ = "indicators"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    indicator_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    family: Mapped[str] = mapped_column(String(64), nullable=False)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    periodicity: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    hotter_when_higher: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bundle_weight: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class MacroRelease(TimestampMixin, Base):
    __tablename__ = "macro_releases"
    __table_args__ = (
        UniqueConstraint("release_type", "released_at", name="uq_macro_release_type_time"),
        Index("ix_macro_releases_released", "released_at", "release_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    release_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    period_label: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    primary_quality_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("data_quality_records.id")
    )
    contamination_level: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    clean_window: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    overlapping_events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    confounding_notes: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ReleaseStage(TimestampMixin, Base):
    __tablename__ = "release_stages"
    __table_args__ = (
        UniqueConstraint("macro_release_id", "stage_key", name="uq_release_stage_key"),
        Index("ix_release_stages_release_sequence", "macro_release_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    macro_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("macro_releases.id", ondelete="CASCADE"), nullable=False
    )
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ReleaseValue(Base):
    """Append-only actual/previous/revised values as known at a point in time."""

    __tablename__ = "release_values"
    __table_args__ = (
        UniqueConstraint(
            "macro_release_id",
            "indicator_id",
            "value_kind",
            "data_version",
            "captured_at",
            name="uq_release_value_vintage",
        ),
        Index(
            "ix_release_values_point_in_time",
            "macro_release_id",
            "indicator_id",
            "captured_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    macro_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("macro_releases.id", ondelete="CASCADE"), nullable=False
    )
    release_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("release_stages.id", ondelete="CASCADE")
    )
    indicator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("indicators.id"), nullable=False)
    value_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    raw_value: Mapped[str | None] = mapped_column(Text)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_initial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    quality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("data_quality_records.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ConsensusSnapshot(Base):
    __tablename__ = "consensus_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "macro_release_id",
            "indicator_id",
            "captured_at",
            "source_name",
            name="uq_consensus_snapshot",
        ),
        Index(
            "ix_consensus_release_indicator_time",
            "macro_release_id",
            "indicator_id",
            "captured_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    macro_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("macro_releases.id", ondelete="CASCADE"), nullable=False
    )
    indicator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("indicators.id"), nullable=False)
    consensus_value: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    quality_grade: Mapped[str] = mapped_column(String(16), nullable=False)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    quality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("data_quality_records.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketInstrument(TimestampMixin, Base):
    __tablename__ = "market_instruments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    canonical_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(64))
    quote_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    measurement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    proxy_for: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class FuturesContract(TimestampMixin, Base):
    __tablename__ = "futures_contracts"
    __table_args__ = (
        UniqueConstraint("instrument_id", "contract_code", name="uq_futures_contract"),
        Index("ix_futures_contract_dates", "instrument_id", "first_trade_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_instruments.id", ondelete="CASCADE"), nullable=False
    )
    contract_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    first_trade_date: Mapped[date | None] = mapped_column(Date)
    last_trade_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    roll_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    roll_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timestamp",
            "interval_seconds",
            "provider_key",
            "contract_code",
            name="uq_market_bar_provider_time",
        ),
        Index(
            "ix_market_bars_instrument_time",
            "instrument_id",
            "timestamp",
            "interval_seconds",
        ),
    )

    id: Mapped[int] = mapped_column(IDENTITY_INTEGER, primary_key=True, autoincrement=True)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_instruments.id"), nullable=False
    )
    futures_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("futures_contracts.id")
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    open_value: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, nullable=False)
    high_value: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, nullable=False)
    low_value: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, nullable=False)
    close_value: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_regular_session: Mapped[bool | None] = mapped_column(Boolean)
    quality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("data_quality_records.id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class RegimeSnapshot(Base):
    __tablename__ = "regime_snapshots"
    __table_args__ = (Index("ix_regime_snapshots_as_of", "as_of"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    labels_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    data_gaps_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_runs_release_started", "macro_release_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    macro_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("macro_releases.id", ondelete="CASCADE"), nullable=False
    )
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    regime_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("regime_snapshots.id"))
    composite_classification: Mapped[str] = mapped_column(String(128), nullable=False)
    composite_surprise_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    facts_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    earliest_reactions_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    data_gaps_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class EventWindowDefinition(Base):
    __tablename__ = "event_window_definitions"

    id: Mapped[int] = mapped_column(IDENTITY_INTEGER, primary_key=True, autoincrement=True)
    window_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    start_offset_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset_seconds: Mapped[int | None] = mapped_column(Integer)
    close_rule: Mapped[str | None] = mapped_column(String(64))
    anchor_stage_key: Mapped[str] = mapped_column(String(64), default="release", nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    methodology_notes: Mapped[str | None] = mapped_column(Text)


class EventWindowResult(Base):
    __tablename__ = "event_window_results"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "release_stage_id",
            "instrument_id",
            "window_definition_id",
            name="uq_event_window_result",
        ),
        Index("ix_event_window_results_analysis", "analysis_run_id", "instrument_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    release_stage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("release_stages.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_instruments.id"), nullable=False
    )
    window_definition_id: Mapped[int] = mapped_column(
        ForeignKey("event_window_definitions.id"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_value: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    end_value: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    change_absolute: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    return_percent: Mapped[float | None] = mapped_column(Float)
    change_basis_points: Mapped[float | None] = mapped_column(Float)
    max_up_percent: Mapped[float | None] = mapped_column(Float)
    max_down_percent: Mapped[float | None] = mapped_column(Float)
    realized_volatility: Mapped[float | None] = mapped_column(Float)
    volume_change_percent: Mapped[float | None] = mapped_column(Float)
    coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    spike_fade: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dip_recovery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    direction_reversal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    granularity_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_grade: Mapped[str] = mapped_column(String(16), nullable=False)
    missing_reason: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class MarketReaction(Base):
    __tablename__ = "market_reactions"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "release_stage_id",
            "instrument_id",
            name="uq_market_reaction",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    release_stage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("release_stages.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_instruments.id"), nullable=False
    )
    earliest_significant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_seconds: Mapped[int | None] = mapped_column(Integer)
    pre_event_volatility: Mapped[float | None] = mapped_column(Float)
    significance_threshold: Mapped[float | None] = mapped_column(Float)
    confirmation_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    strongest_window_key: Mapped[str | None] = mapped_column(String(64))
    reaction_strength: Mapped[float | None] = mapped_column(Float)
    lead_rank: Mapped[int | None] = mapped_column(Integer)
    spike_fade: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dip_recovery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    direction_reversal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    granularity_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    limitations_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)


class HistoricalMatch(Base):
    __tablename__ = "historical_matches"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "matched_release_id", name="uq_historical_match"),
        Index("ix_historical_matches_rank", "analysis_run_id", "rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    matched_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("macro_releases.id"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    filters_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    comparable_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class Explanation(Base):
    __tablename__ = "explanations"
    __table_args__ = (UniqueConstraint("analysis_run_id", "rank", name="uq_explanation_rank"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    explanation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    causal_language: Mapped[str] = mapped_column(String(32), nullable=False)
    mechanism_steps_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    confirming_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    contradicting_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    unresolved_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    rule_key: Mapped[str | None] = mapped_column(String(128))


class DataQualityRecord(Base):
    __tablename__ = "data_quality_records"
    __table_args__ = (
        CheckConstraint(
            "quality_grade IN ('A','B','C','D','UNKNOWN')",
            name="ck_data_quality_grade",
        ),
        Index("ix_data_quality_source_acquired", "source_name", "acquired_at"),
        Index("ix_data_quality_subject", "subject_type", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_type: Mapped[str] = mapped_column(String(64), default="unassigned", nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_seconds: Mapped[int | None] = mapped_column(Integer)
    granularity_seconds: Mapped[int | None] = mapped_column(Integer)
    missing_reason: Mapped[str | None] = mapped_column(Text)
    quality_grade: Mapped[str] = mapped_column(String(16), nullable=False)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReportArtifact(Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "format", "generator", name="uq_report_artifact"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_pack_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generator: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ProviderRun(Base):
    __tablename__ = "provider_runs"
    __table_args__ = (Index("ix_provider_runs_provider_started", "provider_key", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    quality_grade: Mapped[str] = mapped_column(String(16), default="UNKNOWN", nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
