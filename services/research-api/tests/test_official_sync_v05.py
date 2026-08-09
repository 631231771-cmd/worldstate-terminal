from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application import official_sync_service
from worldstate.application.analysis_orchestrator import _ensure_catalog, list_releases
from worldstate.application.official_sync_service import sync_fomc_materials
from worldstate.config import Settings
from worldstate.db import models as _models  # noqa: F401
from worldstate.db.base import Base
from worldstate.db.models import MacroRelease, ReleaseStage, ReleaseValue, SourceArtifact
from worldstate.db.session import create_engine
from worldstate.provider_kit import (
    FederalReserveFomcProvider,
    FomcMaterialType,
    ProviderError,
    ProviderErrorCode,
)


@pytest.fixture
async def official_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'official.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def test_fomc_future_calendar_creates_scheduled_release_and_verified_stages(
    official_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FederalReserveFomcProvider()
    batch = adapter.adapt_calendar_html(
        """
        <div class="panel panel-default">
          <div class="panel-heading"><h4>2027 FOMC Meetings</h4><br></div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month"><strong>March</strong></div>
            <div class="fomc-meeting__date">16-17*</div>
            <div class="fomc-meeting__minutes"><br></div>
          </div>
        </div>
        """,
        retrieved_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        year=2027,
    )

    class FakeFed:
        key = adapter.key
        terms = adapter.terms

        async def fetch_calendar(self, *, year: int | None = None) -> object:
            assert year is None
            return batch

        async def fetch_material(self, url: str, material_type: object) -> object:
            raise AssertionError("future meetings must not request unpublished materials")

    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(federal_reserve=FakeFed()),
    )
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        ai_provider="none",
        scheduler_enabled=False,
    )
    result = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
    )
    assert result["status"] == "completed"
    repeated = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
    )
    assert repeated["status"] == "completed"

    factory = async_sessionmaker(official_engine, expire_on_commit=False)
    async with factory() as session:
        release = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_type == "FOMC")
        )
        assert release is not None
        stages = (
            await session.scalars(
                select(ReleaseStage)
                .where(ReleaseStage.macro_release_id == release.id)
                .order_by(ReleaseStage.sequence)
            )
        ).all()
        values = (
            await session.scalars(
                select(ReleaseValue).where(ReleaseValue.macro_release_id == release.id)
            )
        ).all()
        release_count = await session.scalar(select(func.count(MacroRelease.id)))

    assert release.status == "scheduled"
    assert release.released_at is None
    assert release.scheduled_at == datetime(2027, 3, 17, 18, 0)
    assert [(item.stage_key, item.status) for item in stages] == [
        ("statement", "scheduled"),
        ("press_conference", "scheduled"),
    ]
    assert stages[1].scheduled_at == datetime(2027, 3, 17, 18, 30)
    assert values == []
    assert release_count == 1
    assert release.metadata_json["unresolved_stages"] == ["key_qa", "press_end"]


async def test_fomc_retry_cannot_downgrade_released_document_provenance(
    official_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FederalReserveFomcProvider()
    source_url = (
        "https://www.federalreserve.gov/newsevents/pressreleases/"
        "monetary20250618a.htm"
    )
    batch = adapter.adapt_calendar_html(
        f"""
        <div class="panel panel-default">
          <div class="panel-heading"><h4>2025 FOMC Meetings</h4><br></div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month"><strong>June</strong></div>
            <div class="fomc-meeting__date">17-18*</div>
            <a href="{source_url}">Statement</a>
          </div>
        </div>
        """,
        retrieved_at=datetime(2025, 6, 18, 18, 1, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        year=2025,
    )
    document = adapter.adapt_material_html(
        """
        <html><head><title>Federal Reserve issues FOMC statement</title></head>
        <body><main>For release at 2:00 p.m. EDT. The Federal Open Market Committee
        decided to maintain the target range for the federal funds rate at 5.25 to
        5.50 percent. Additional official policy text makes this release complete.
        </main></body></html>
        """,
        material_type=FomcMaterialType.STATEMENT,
        retrieved_at=datetime(2025, 6, 18, 18, 1, tzinfo=UTC),
        source_url=source_url,
    )

    class FakeFed:
        key = adapter.key
        terms = adapter.terms
        fail_material = False

        async def fetch_calendar(self, *, year: int | None = None) -> object:
            assert year is None
            return batch

        async def fetch_material(self, url: str, material_type: object) -> object:
            assert url == source_url
            if self.fail_material:
                raise ProviderError(
                    self.key,
                    ProviderErrorCode.TRANSPORT,
                    "simulated transient failure",
                    retryable=True,
                )
            return document

    fake = FakeFed()
    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(federal_reserve=fake),
    )
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        ai_provider="none",
        scheduler_enabled=False,
    )
    first = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2025, 6, 1),
        end_date=date(2025, 6, 30),
    )
    assert first["status"] == "completed"

    factory = async_sessionmaker(official_engine, expire_on_commit=False)
    async with factory() as session:
        release = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_type == "FOMC")
        )
        assert release is not None
        statement_stage = await session.scalar(
            select(ReleaseStage).where(
                ReleaseStage.macro_release_id == release.id,
                ReleaseStage.stage_key == "statement",
            )
        )
        assert statement_stage is not None
        original_value_count = await session.scalar(select(func.count(ReleaseValue.id)))
        original = {
            "release_source": release.source_artifact_id,
            "release_version": release.data_version,
            "released_at": release.released_at,
            "stage_source": statement_stage.source_artifact_id,
            "stage_released_at": statement_stage.released_at,
            "materials": release.metadata_json["materials"],
            "value_count": original_value_count,
        }

    fake.fail_material = True
    retry = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2025, 6, 1),
        end_date=date(2025, 6, 30),
    )
    assert retry["status"] == "completed"
    assert retry["warnings"]

    async with factory() as session:
        release = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_type == "FOMC")
        )
        assert release is not None
        statement_stage = await session.scalar(
            select(ReleaseStage).where(
                ReleaseStage.macro_release_id == release.id,
                ReleaseStage.stage_key == "statement",
            )
        )
        assert statement_stage is not None
        release_count = await session.scalar(select(func.count(MacroRelease.id)))
        value_count = await session.scalar(select(func.count(ReleaseValue.id)))

    assert release.status == "released"
    assert release.source_artifact_id == original["release_source"]
    assert release.data_version == original["release_version"]
    assert release.released_at == original["released_at"]
    assert release.metadata_json["materials"] == original["materials"]
    assert len(release.metadata_json["calendar_artifact_ids"]) == 1
    assert statement_stage.status == "released"
    assert statement_stage.source_artifact_id == original["stage_source"]
    assert statement_stage.released_at == original["stage_released_at"]
    assert release_count == 1
    assert value_count == original["value_count"]


async def test_fomc_dynamic_raw_html_does_not_duplicate_target_values(
    official_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FederalReserveFomcProvider()
    source_url = (
        "https://www.federalreserve.gov/newsevents/pressreleases/"
        "monetary20251029a.htm"
    )
    batch = adapter.adapt_calendar_html(
        f"""
        <div class="panel panel-default">
          <div class="panel-heading"><h4>2025 FOMC Meetings</h4></div>
          <div class="row fomc-meeting">
            <div class="fomc-meeting__month">October</div>
            <div class="fomc-meeting__date">28-29</div>
            <a href="{source_url}">Statement</a>
          </div>
        </div>
        """,
        retrieved_at=datetime(2025, 10, 29, 18, 1, tzinfo=UTC),
        source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        year=2025,
    )
    statement_payload = """
        <html><head><title>Federal Reserve issues FOMC statement</title>
        <script>window.dynamicNonce = %s;</script></head>
        <body><main>For release at 2:00 p.m. EDT. The Federal Open Market Committee
        decided to maintain the target range for the federal funds rate at 3-3/4 to
        4 percent. Additional official policy text makes this release complete.
        </main></body></html>
    """
    documents = [
        adapter.adapt_material_html(
            statement_payload % "'first'",
            material_type=FomcMaterialType.STATEMENT,
            retrieved_at=datetime(2025, 10, 29, 18, 1, tzinfo=UTC),
            source_url=source_url,
        ),
        adapter.adapt_material_html(
            statement_payload % "'second'",
            material_type=FomcMaterialType.STATEMENT,
            retrieved_at=datetime(2025, 10, 29, 18, 2, tzinfo=UTC),
            source_url=source_url,
        ),
    ]

    class FakeFed:
        key = adapter.key
        terms = adapter.terms
        capture_index = 0

        async def fetch_calendar(self, *, year: int | None = None) -> object:
            assert year is None
            return batch

        async def fetch_material(self, url: str, material_type: object) -> object:
            assert url == source_url
            document = documents[min(self.capture_index, len(documents) - 1)]
            self.capture_index += 1
            return document

    fake = FakeFed()
    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(federal_reserve=fake),
    )
    factory = async_sessionmaker(official_engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        await _ensure_catalog(session)
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        ai_provider="none",
        scheduler_enabled=False,
    )
    first = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2025, 10, 1),
        end_date=date(2025, 10, 31),
    )
    async with factory() as session, session.begin():
        release = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_type == "FOMC")
        )
        assert release is not None
        canonical_values = (
            await session.scalars(
                select(ReleaseValue).where(ReleaseValue.macro_release_id == release.id)
            )
        ).all()
        assert len(canonical_values) == 2
        for canonical in canonical_values:
            canonical.value = Decimal("4")
            canonical.raw_value = "4"
            canonical.data_version = f"fed-legacy-initial-{canonical.indicator_id}"
            canonical.metadata_json = {"official_statement_parse": True}
            for index in range(3):
                session.add(
                    ReleaseValue(
                        id=uuid.uuid4(),
                        macro_release_id=release.id,
                        release_stage_id=canonical.release_stage_id,
                        indicator_id=canonical.indicator_id,
                        value_kind="actual",
                        value=4,
                        raw_value="4",
                        data_version=f"fed-legacy-raw-hash-{index}",
                        valid_from=canonical.valid_from,
                        captured_at=canonical.captured_at + timedelta(minutes=index + 1),
                        is_initial=True,
                        data_mode="observed",
                        source_artifact_id=canonical.source_artifact_id,
                        quality_id=canonical.quality_id,
                        metadata_json={"official_statement_parse": True},
                    )
                )
    second = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2025, 10, 1),
        end_date=date(2025, 10, 31),
    )
    assert first["records_written"] == 3
    assert second["records_written"] == 2

    async with factory() as session:
        release = await session.scalar(
            select(MacroRelease).where(MacroRelease.release_type == "FOMC")
        )
        assert release is not None
        values = (
            await session.scalars(
                select(ReleaseValue)
                .where(ReleaseValue.macro_release_id == release.id)
                .order_by(ReleaseValue.raw_value)
            )
        ).all()
        artifact_count = await session.scalar(
            select(func.count(SourceArtifact.id)).where(SourceArtifact.source_url == source_url)
        )

    active_values = [item for item in values if not item.metadata_json.get("superseded")]
    superseded_values = [item for item in values if item.metadata_json.get("superseded")]
    assert [(str(item.value), item.raw_value) for item in active_values] == [
        ("3.750000000000", "3.75"),
        ("4.000000000000", "4"),
    ]
    assert all(
        item.metadata_json["parser_version"] == "fomc-target-range-v2"
        for item in active_values
    )
    assert len(superseded_values) == 8
    assert artifact_count == 2


async def test_fomc_sync_soft_invalidates_provider_owned_stale_meetings(
    official_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FederalReserveFomcProvider()

    def calendar(include_legacy_april: bool) -> object:
        april = (
            """
            <div class="row fomc-meeting">
              <div class="fomc-meeting__month">April</div>
              <div class="fomc-meeting__date">20</div>
            </div>
            """
            if include_legacy_april
            else ""
        )
        return adapter.adapt_calendar_html(
            f"""
            <div class="panel panel-default">
              <div class="panel-heading"><h4>2027 FOMC Meetings</h4></div>
              <div class="row fomc-meeting">
                <div class="fomc-meeting__month">March</div>
                <div class="fomc-meeting__date">16-17</div>
              </div>
              {april}
              <div class="row fomc-meeting">
                <div class="fomc-meeting__month">June</div>
                <div class="fomc-meeting__date">8-9</div>
              </div>
            </div>
            """,
            retrieved_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            source_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            year=2027,
        )

    class FakeFed:
        key = adapter.key
        terms = adapter.terms
        current_batch = calendar(True)

        async def fetch_calendar(self, *, year: int | None = None) -> object:
            assert year is None
            return self.current_batch

        async def fetch_material(self, url: str, material_type: object) -> object:
            raise AssertionError("future calendar rows have no materials")

    fake = FakeFed()
    monkeypatch.setattr(
        official_sync_service,
        "build_provider_clients",
        lambda settings: SimpleNamespace(federal_reserve=fake),
    )
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        ai_provider="none",
        scheduler_enabled=False,
    )
    first = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
    )
    assert first["invalidated_release_ids"] == []

    fake.current_batch = calendar(False)
    second = await sync_fomc_materials(
        official_engine,
        settings,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 12, 31),
    )
    invalidated_release_ids = second["invalidated_release_ids"]
    assert isinstance(invalidated_release_ids, list)
    assert len(invalidated_release_ids) == 1

    factory = async_sessionmaker(official_engine, expire_on_commit=False)
    async with factory() as session:
        stale = await session.scalar(
            select(MacroRelease).where(
                MacroRelease.release_key == "fomc-2027-04-20-observed"
            )
        )
        assert stale is not None

    assert stale.status == "invalidated"
    reconciliation = stale.metadata_json["provider_reconciliation"]
    assert reconciliation["state"] == "invalidated"
    assert reconciliation["reason"] == "not_present_in_authoritative_fomc_calendar"
    visible = await list_releases(official_engine, release_type="FOMC", data_mode="observed")
    assert {item["release_key"] for item in visible} == {
        "fomc-2027-03-17-observed",
        "fomc-2027-06-09-observed",
    }
