"""Read-side deterministic report projection."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from worldstate.application.analysis_orchestrator import _factory, _latest_run
from worldstate.db.models import Explanation, ReportArtifact


async def get_release_explanations(
    engine: AsyncEngine,
    release_id: str,
) -> dict[str, object] | None:
    async with _factory(engine)() as session:
        try:
            release_uuid = uuid.UUID(release_id)
        except ValueError:
            return None
        run = await _latest_run(session, release_uuid)
        if run is None:
            return None
        explanations = (
            await session.scalars(
                select(Explanation)
                .where(Explanation.analysis_run_id == run.id)
                .order_by(Explanation.rank)
            )
        ).all()
        report = await session.scalar(
            select(ReportArtifact).where(
                ReportArtifact.analysis_run_id == run.id,
                ReportArtifact.generator == "worldstate_deterministic",
            )
        )
        return {
            "release_id": release_id,
            "analysis_run_id": str(run.id),
            "facts": run.facts_json,
            "explanations": [
                {
                    "id": str(item.id),
                    "type": item.explanation_type,
                    "rank": item.rank,
                    "title": item.title,
                    "summary": item.summary,
                    "confidence": item.confidence,
                    "causal_language": item.causal_language,
                    "mechanism_steps": item.mechanism_steps_json,
                    "confirming_evidence": item.confirming_evidence_json,
                    "contradicting_evidence": item.contradicting_evidence_json,
                    "unresolved": item.unresolved_json,
                    "rule_key": item.rule_key,
                }
                for item in explanations
            ],
            "confidence": run.confidence,
            "data_gaps": run.data_gaps_json,
            "report": report.content if report else None,
            "report_validation": report.validation_json if report else None,
        }


__all__ = ["get_release_explanations"]
