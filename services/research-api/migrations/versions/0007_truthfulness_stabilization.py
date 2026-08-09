"""Make observed/fixture parent-child links truthful and deterministic.

The v0.5 audit found four pre-release consensus snapshots marked observed while
their CPI release was fixture data.  They remain available for provenance, but
are downgraded to fixture in place.  The migration is deliberately idempotent
and adds SQLite write guards for the relationships that are most likely to be
written by local tooling; application guards cover PostgreSQL and service paths.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_truthfulness_stabilization"
down_revision: str | None = "0006_data_mode_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RELATIONSHIPS = (
    ("release_values", "macro_release_id"),
    ("consensus_snapshots", "macro_release_id"),
    ("analysis_runs", "macro_release_id"),
    ("market_data_manifests", "macro_release_id"),
)


def _normalize_consensus_modes() -> None:
    # Mark only quality records belonging to the mismatched rows.  Existing
    # fixture consensus records may have their own verified/quality policy and
    # must not be downgraded merely because they are fixture data.
    op.execute(
        sa.text(
            """
            UPDATE data_quality_records
            SET is_fixture = 1,
                is_verified = 0,
                quality_grade = 'C',
                verification_notes = CASE
                    WHEN verification_notes IS NULL OR verification_notes = ''
                    THEN 'Reclassified to fixture because its parent release is fixture data.'
                    ELSE verification_notes || ' Reclassified to fixture because its parent release is fixture data.'
                END
            WHERE id IN (
                SELECT child.quality_id
                FROM consensus_snapshots child
                JOIN macro_releases parent ON parent.id = child.macro_release_id
                WHERE child.data_mode <> parent.data_mode
                  AND child.quality_id IS NOT NULL
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE consensus_snapshots
            SET data_mode = (
                SELECT data_mode FROM macro_releases
                WHERE macro_releases.id = consensus_snapshots.macro_release_id
            )
            WHERE data_mode <> (
                SELECT data_mode FROM macro_releases
                WHERE macro_releases.id = consensus_snapshots.macro_release_id
            )
            """
        )
    )
def _assert_no_mismatch() -> None:
    bind = op.get_bind()
    for table, foreign_key in _RELATIONSHIPS:
        count = bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*) FROM {table} child
                JOIN macro_releases parent ON parent.id = child.{foreign_key}
                WHERE child.data_mode <> parent.data_mode
                """
            )
        ).scalar_one()
        if int(count) != 0:
            raise RuntimeError(f"data_mode mismatch remains in {table}: {count}")


def _reclassify_legacy_scheduler_noise() -> None:
    """Keep old provider blockers visible without counting them as failures."""

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, error_type, error_message FROM sync_job_runs WHERE status = 'failed'"
        )
    ).mappings()
    expected_fragments = (
        "not configured",
        "finished as blocked",
        "finished as partial",
    )
    for row in rows:
        message = str(row["error_message"] or "")
        if not any(fragment in message.lower() for fragment in expected_fragments):
            continue
        outcome = "partial" if "partial" in message.lower() else "blocked"
        payload = json.dumps(
            {
                "status": outcome,
                "legacy_scheduler_status": "failed",
                "legacy_error_type": row["error_type"],
                "legacy_error_message": message,
                "reclassified_by": revision,
            },
            separators=(",", ":"),
        )
        bind.execute(
            sa.text(
                """
                UPDATE sync_job_runs
                SET status = 'completed', output_json = :output_json,
                    error_type = NULL, error_message = NULL,
                    completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
                WHERE id = :run_id
                """
            ),
            {"output_json": payload, "run_id": row["id"]},
        )


def _sqlite_guards() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table, foreign_key in _RELATIONSHIPS:
        stem = table.replace("_", "")
        for action in ("insert", "update"):
            update_of = f" OF data_mode, {foreign_key}" if action == "update" else ""
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER IF NOT EXISTS ws_{stem}_mode_{action}
                    BEFORE {action.upper()}{update_of} ON {table}
                    FOR EACH ROW
                    WHEN (SELECT data_mode FROM macro_releases WHERE id = NEW.{foreign_key}) IS NOT NULL
                     AND (SELECT data_mode FROM macro_releases WHERE id = NEW.{foreign_key}) <> NEW.data_mode
                    BEGIN
                        SELECT RAISE(ABORT, 'data_mode must match macro_release');
                    END
                    """
                )
            )


def upgrade() -> None:
    _normalize_consensus_modes()
    _assert_no_mismatch()
    _reclassify_legacy_scheduler_noise()
    _sqlite_guards()


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for table, _foreign_key in _RELATIONSHIPS:
            stem = table.replace("_", "")
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS ws_{stem}_mode_insert"))
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS ws_{stem}_mode_update"))
    raise RuntimeError("truthfulness stabilization downgrade is unsupported; restore a backup")
