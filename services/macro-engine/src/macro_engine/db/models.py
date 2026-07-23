"""SQLAlchemy persistence model for the complete initial macro schema."""

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

from macro_engine.db.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
DECIMAL_VALUE = Numeric(precision=30, scale=12)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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
        Index("ix_observations_series_vintage", "series_id", "vintage_date"),
        Index(
            "ix_observations_as_of",
            "series_id",
            "available_at",
            "period_start",
            "vintage_date",
        ),
        Index("ix_observations_latest", "series_id", "period_start", "vintage_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (
        UniqueConstraint("provider_id", "native_id", "scheduled_at", name="uq_release_native_time"),
        Index("ix_releases_scheduled", "scheduled_at", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), nullable=False)
    native_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("economic_entities.id"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ReleaseSeries(Base):
    __tablename__ = "release_series"

    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("releases.id", ondelete="CASCADE"),
        primary_key=True,
    )
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"),
        primary_key=True,
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_runs_provider_started", "provider", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_series: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    inserted_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class StateDefinition(Base):
    __tablename__ = "state_definitions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    meaning_of_positive: Mapped[str] = mapped_column(Text, nullable=False)
    methodology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)


class StateComponent(Base):
    __tablename__ = "state_components"

    state_key: Mapped[str] = mapped_column(ForeignKey("state_definitions.key"), primary_key=True)
    series_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("series.id"), primary_key=True)
    transform: Mapped[str] = mapped_column(String(64), nullable=False)
    orientation: Mapped[int] = mapped_column(Integer, nullable=False)
    base_weight: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_half_life_days: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_history: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StateSnapshot(Base):
    __tablename__ = "state_snapshots"
    __table_args__ = (
        CheckConstraint("score >= -1 AND score <= 1", name="ck_state_snapshots_score"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_state_snapshots_confidence"
        ),
        Index("ix_state_snapshots_entity_as_of", "entity_id", "as_of"),
    )

    entity_id: Mapped[int] = mapped_column(ForeignKey("economic_entities.id"), primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    state_key: Mapped[str] = mapped_column(ForeignKey("state_definitions.key"), primary_key=True)
    methodology_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    momentum: Mapped[dict[str, float | None]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    agreement: Mapped[float] = mapped_column(Float, nullable=False)
    freshness: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    components_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class CausalNode(Base):
    __tablename__ = "causal_nodes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    linked_series: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class CausalEdge(Base):
    __tablename__ = "causal_edges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("causal_nodes.id"), nullable=False)
    target_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("causal_nodes.id"), nullable=False)
    sign: Mapped[int] = mapped_column(Integer, nullable=False)
    lag_min_days: Mapped[int] = mapped_column(Integer, nullable=False)
    lag_max_days: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    counterexamples: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Thesis(TimestampMixin, Base):
    __tablename__ = "theses"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','confirmed','invalidated','archived')",
            name="ck_theses_status",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_theses_confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon: Mapped[str] = mapped_column(String(128), nullable=False)
    base_case: Mapped[str] = mapped_column(Text, nullable=False)
    bull_case: Mapped[str] = mapped_column(Text, nullable=False)
    bear_case: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)


class ThesisCondition(Base):
    __tablename__ = "thesis_conditions"
    __table_args__ = (
        CheckConstraint(
            "condition_type IN ('confirm','invalidate','watch')",
            name="ck_thesis_conditions_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thesis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("theses.id", ondelete="CASCADE"),
        nullable=False,
    )
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    operator: Mapped[str] = mapped_column(String(16), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(DECIMAL_VALUE, nullable=False)
    evaluation_window: Mapped[str] = mapped_column(String(64), nullable=False)
    current_status: Mapped[str] = mapped_column(String(32), nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class ThesisEvidence(Base):
    __tablename__ = "thesis_evidence"
    __table_args__ = (
        CheckConstraint(
            "stance IN ('support','contradict','neutral')",
            name="ck_thesis_evidence_stance",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thesis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("theses.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stance: Mapped[str] = mapped_column(String(32), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, default=dict, nullable=False
    )


class ThesisSnapshot(Base):
    __tablename__ = "thesis_snapshots"
    __table_args__ = (Index("ix_thesis_snapshots_thesis_captured", "thesis_id", "captured_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thesis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("theses.id", ondelete="CASCADE"),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_state: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_DOCUMENT, default=list, nullable=False
    )
    world_state: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    source_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
