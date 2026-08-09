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
    LargeBinary,
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
            "data_mode",
            name="uq_observations_series_period_vintage_mode",
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
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceArtifact(TimestampMixin, Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "provider_key", "content_hash", "data_mode", name="uq_source_artifact_hash_mode"
        ),
        Index("ix_source_artifacts_published", "published_at", "provider_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_runs.id"))
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    byte_length: Mapped[int | None] = mapped_column(BigInteger)
    content_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    license_name: Mapped[str | None] = mapped_column(String(128))
    citation_text: Mapped[str | None] = mapped_column(Text)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
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
        UniqueConstraint(
            "release_type", "released_at", "data_mode", name="uq_macro_release_type_time_mode"
        ),
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
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
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
            "data_mode",
            name="uq_release_value_vintage_mode",
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
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
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
            "data_mode",
            name="uq_consensus_snapshot_mode",
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
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    quality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("data_quality_records.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
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
            "data_mode",
            name="uq_market_bar_provider_time_mode",
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
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
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
    dimensions_json: Mapped[dict[str, str]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    data_gaps_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Thesis(TimestampMixin, Base):
    """A user's durable research thesis, kept separate from generated claims."""

    __tablename__ = "theses"
    __table_args__ = (
        Index("ix_theses_status_updated", "status", "updated_at"),
        CheckConstraint(
            "status IN ('active','paused','falsified','confirmed','archived')",
            name="ck_theses_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    entities_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    related_states_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    supporting_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    contradicting_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    confirmation_conditions_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    falsification_conditions_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    watch_variables_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    history_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)


class WorldStateSnapshot(Base):
    """Immutable daily world-state output for history and reproducible briefs."""

    __tablename__ = "world_state_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "data_mode", name="uq_world_state_snapshot_day_mode"),
        Index("ix_world_state_snapshots_date", "snapshot_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="observed")
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    regime_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    top_changes_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    data_gaps_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WatchlistItem(TimestampMixin, Base):
    """User-owned watchlist entry; it stores intent, not generated signals."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("item_type", "item_key", name="uq_watchlist_item_type_key"),
        Index("ix_watchlist_items_updated", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    item_key: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)


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
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    # Immutable v0.4 manifests.  Existing v3 runs are explicitly marked legacy.
    input_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    config_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    release_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    release_value_ids_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    consensus_snapshot_ids_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    release_stage_ids_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    market_dataset_manifest_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    market_dataset_hash: Mapped[str | None] = mapped_column(String(64))
    historical_sample_manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    historical_sample_hash: Mapped[str | None] = mapped_column(String(64))
    provider_manifest_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    source_artifact_ids_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    algorithm_versions_json: Mapped[dict[str, str]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    rule_versions_json: Mapped[dict[str, str]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    analysis_parameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    reproducibility_status: Mapped[str] = mapped_column(
        String(32), default="legacy_incomplete", nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    failure_stage: Mapped[str | None] = mapped_column(String(64))
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)


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
    matched_analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_runs.id")
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


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (Index("ix_evidence_items_run", "analysis_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_grade: Mapped[str] = mapped_column(String(16), default="UNKNOWN", nullable=False)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    limitations_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ResearchClaim(Base):
    __tablename__ = "research_claims"
    __table_args__ = (Index("ix_research_claims_run", "analysis_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    claim_type: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    is_inference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    causal_language: Mapped[str] = mapped_column(String(32), default="qualified", nullable=False)
    limitations_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    falsifier: Mapped[str | None] = mapped_column(Text)
    contradicting_evidence_ids_json: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    validation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


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
    __table_args__ = (
        Index("ix_provider_runs_provider_started", "provider_key", "started_at"),
        UniqueConstraint(
            "provider_key",
            "operation",
            "idempotency_key",
            "data_mode",
            name="uq_provider_run_idempotency_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    terms_url: Mapped[str | None] = mapped_column(String(2048))
    quality_grade: Mapped[str] = mapped_column(String(16), default="UNKNOWN", nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class ProviderEntitlement(TimestampMixin, Base):
    """Latest known provider capability, including explicit access failures."""

    __tablename__ = "provider_entitlements"
    __table_args__ = (
        UniqueConstraint("provider_key", "capability", name="uq_provider_entitlement"),
        Index("ix_provider_entitlements_status", "provider_key", "status"),
        CheckConstraint(
            "status IN ('unknown','granted','denied','expired','not_configured')",
            name="ck_provider_entitlement_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_runs.id"))
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(String(2048))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ProviderQuota(TimestampMixin, Base):
    """Point-in-time quota/cost allowance for a provider billing period."""

    __tablename__ = "provider_quotas"
    __table_args__ = (
        UniqueConstraint(
            "provider_key", "quota_key", "period_start", name="uq_provider_quota_period"
        ),
        Index("ix_provider_quotas_period", "provider_key", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quota_key: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    limit_value: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    used_value: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, default=0, nullable=False)
    remaining_value: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    warning_threshold: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_runs.id"))
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class SyncJob(TimestampMixin, Base):
    """Durable local schedule definition; it contains no API credentials."""

    __tablename__ = "sync_jobs"
    __table_args__ = (
        UniqueConstraint("job_key", name="uq_sync_job_key"),
        Index("ix_sync_jobs_due", "enabled", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    schedule_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    retry_backoff_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)


class SyncJobRun(Base):
    """One recoverable execution attempt of a sync definition."""

    __tablename__ = "sync_job_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_sync_job_run_idempotency"),
        Index("ix_sync_job_runs_status_schedule", "status", "scheduled_for"),
        Index("ix_sync_job_runs_job_started", "sync_job_id", "started_at"),
        CheckConstraint(
            "status IN ('pending','running','retry_wait','completed','failed','cancelled')",
            name="ck_sync_job_run_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sync_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sync_jobs.id", ondelete="CASCADE"), nullable=False
    )
    provider_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_runs.id"))
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sync_job_runs.id"))
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)


class DataReconciliationRecord(TimestampMixin, Base):
    """Non-destructive comparison between authoritative and secondary observations."""

    __tablename__ = "data_reconciliation_records"
    __table_args__ = (
        UniqueConstraint("reconciliation_key", name="uq_data_reconciliation_key"),
        Index("ix_data_reconciliation_status", "status", "detected_at"),
        Index("ix_data_reconciliation_subject", "subject_type", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reconciliation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reconciliation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    authoritative_provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    comparison_provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    authoritative_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_artifacts.id")
    )
    comparison_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_artifacts.id")
    )
    sync_job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sync_job_runs.id"))
    authoritative_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    comparison_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    difference_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_action: Mapped[str | None] = mapped_column(String(64))
    resolution_notes: Mapped[str | None] = mapped_column(Text)


class MarketDataManifest(Base):
    """Immutable description of one downloaded or derived market dataset slice."""

    __tablename__ = "market_data_manifests"
    __table_args__ = (
        UniqueConstraint("manifest_hash", name="uq_market_data_manifest_hash"),
        Index(
            "ix_market_data_manifest_coverage",
            "macro_release_id",
            "instrument_id",
            "interval_seconds",
            "start_at",
            "end_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    macro_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("macro_releases.id", ondelete="CASCADE"), nullable=False
    )
    release_stage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("release_stages.id"))
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_instruments.id"), nullable=False
    )
    futures_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("futures_contracts.id")
    )
    source_symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_code: Mapped[str | None] = mapped_column(String(64))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    quality_grade: Mapped[str] = mapped_column(String(16), default="UNKNOWN", nullable=False)
    is_aggregated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    aggregation_method: Mapped[str | None] = mapped_column(String(128))
    aggregation_version: Mapped[str | None] = mapped_column(String(64))
    contract_selection_rule: Mapped[str | None] = mapped_column(Text)
    continuous_resolution_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    roll_status: Mapped[str | None] = mapped_column(String(32))
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(DECIMAL_VALUE)
    provider_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_runs.id"))
    sync_job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sync_job_runs.id"))
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class BackfillJob(TimestampMixin, Base):
    """Persisted cost estimate and execution state for a bounded backfill."""

    __tablename__ = "backfill_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_backfill_job_idempotency"),
        Index("ix_backfill_jobs_status", "status", "requested_at"),
        CheckConstraint(
            "status IN ('estimated','pending','running','completed',"
            "'failed','cancelled','rejected')",
            name="ck_backfill_job_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_types_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    instruments_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    datasets_json: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    estimated_event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, default=0, nullable=False)
    budget_limit_usd: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, default=0, nullable=False)
    paid_download_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    execution_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    existing_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    downloaded_record_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_job_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sync_job_runs.id"))
    estimate_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class CalendarSnapshot(Base):
    """Traceable provider calendar payload used to schedule event-time work."""

    __tablename__ = "calendar_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "provider_key",
            "calendar_kind",
            "captured_at",
            "content_hash",
            "data_mode",
            name="uq_calendar_snapshot_mode",
        ),
        Index("ix_calendar_snapshots_range", "calendar_kind", "period_start", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    calendar_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    data_mode: Mapped[str] = mapped_column(String(16), default="observed", nullable=False)
    is_point_in_time: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    provider_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_runs.id"))
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    payload_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
