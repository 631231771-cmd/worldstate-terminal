"""Research-source workflow and deterministic competing-mechanism assessment."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from worldstate.application.market_research_service import build_market_dashboard
from worldstate.application.world_state_service import build_world_state
from worldstate.db.models import AuthorClaim, MechanismAssessment, ResearchSource
from worldstate.reasoning.loader import load_playbook
from worldstate.reasoning.schema import (
    EvidenceRule,
    MechanismDefinition,
    MechanismPlaybook,
    MechanismStep,
)

DataMode = Literal["observed", "fixture"]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_payload(row: ResearchSource) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "author": row.author,
        "source_type": row.source_type,
        "source_url": row.source_url,
        "published_at": _iso(row.published_at),
        "retrieved_at": _iso(row.retrieved_at),
        "content_text": row.content_text,
        "content_hash": row.content_hash,
        "notes": row.notes,
        "provenance": row.provenance_json,
        "data_mode": row.data_mode,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _claim_payload(row: AuthorClaim) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "source_id": str(row.source_id),
        "statement": row.statement,
        "exact_quote": row.exact_quote,
        "extraction_method": row.extraction_method,
        "extractor_model": row.extractor_model,
        "status": row.status,
        "mechanism_key": row.mechanism_key,
        "mechanism_version": row.mechanism_version,
        "confirmed_at": _iso(row.confirmed_at),
        "confirmed_by": row.confirmed_by,
        "review_notes": row.review_notes,
        "data_mode": row.data_mode,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _assessment_payload(row: MechanismAssessment) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "claim_id": str(row.claim_id),
        "playbook_key": row.playbook_key,
        "playbook_version": row.playbook_version,
        "playbook_hash": row.playbook_hash,
        "primary_mechanism_key": row.primary_mechanism_key,
        "as_of": _iso(row.as_of),
        "evaluated_at": _iso(row.evaluated_at),
        "data_mode": row.data_mode,
        "input_snapshot_hash": row.input_snapshot_hash,
        "result": row.result_json,
        "output_hash": row.output_hash,
    }


def list_playbooks() -> dict[str, Any]:
    playbook, digest = load_playbook()
    return {
        "items": [
            {
                "playbook_key": playbook.playbook_key,
                "version": playbook.version,
                "title": playbook.title,
                "source_framework": playbook.source_framework,
                "description": playbook.description,
                "hash": digest,
                "mechanisms": [
                    {
                        "key": item.key,
                        "title": item.title,
                        "summary": item.summary,
                        "chain": [step.label for step in item.causal_chain],
                        "falsifiers": item.falsifiers,
                        "limitations": item.limitations,
                        "competing_mechanisms": item.competing_mechanisms,
                    }
                    for item in playbook.mechanisms
                ],
            }
        ],
        "policy": (
            "Playbooks define hypotheses and observable checks. They do not prove causality "
            "or turn an author claim into a system fact."
        ),
    }


async def create_research_source(
    engine: AsyncEngine,
    *,
    title: str,
    author: str,
    source_type: str,
    content_text: str,
    source_url: str | None,
    published_at: datetime | None,
    notes: str,
    data_mode: DataMode,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    normalized = content_text.strip()
    row = ResearchSource(
        title=title.strip(),
        author=author.strip(),
        source_type=source_type,
        source_url=source_url,
        published_at=published_at,
        retrieved_at=now,
        content_text=normalized,
        content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        notes=notes.strip(),
        provenance_json={
            "capture_method": "user_supplied_text",
            "manual_user_entry": True,
            "source_url": source_url,
            "retrieved_at": now.isoformat(),
        },
        data_mode=data_mode,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        session.add(row)
        await session.flush()
        return _source_payload(row)


async def extract_author_claim(
    engine: AsyncEngine,
    source_id: str,
    *,
    statement: str,
    exact_quote: str,
    extraction_method: Literal["manual", "ai"],
    extractor_model: str | None,
) -> dict[str, Any] | None:
    identifier = uuid.UUID(source_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        source = await session.get(ResearchSource, identifier)
        if source is None:
            return None
        quote = exact_quote.strip()
        if quote not in source.content_text:
            raise ValueError("exact_quote must be an exact excerpt from the saved source")
        if extraction_method == "ai" and not extractor_model:
            raise ValueError("AI extraction requires extractor_model provenance")
        row = AuthorClaim(
            source_id=source.id,
            statement=statement.strip(),
            exact_quote=quote,
            extraction_method=extraction_method,
            extractor_model=extractor_model,
            status="draft",
            data_mode=source.data_mode,
        )
        session.add(row)
        await session.flush()
        return _claim_payload(row)


def _mechanism(playbook: MechanismPlaybook, key: str) -> MechanismDefinition:
    match = next((item for item in playbook.mechanisms if item.key == key), None)
    if match is None:
        raise ValueError(f"unknown mechanism_key: {key}")
    return match


async def review_author_claim(
    engine: AsyncEngine,
    claim_id: str,
    *,
    decision: Literal["confirmed", "rejected"],
    mechanism_key: str | None,
    review_notes: str,
) -> dict[str, Any] | None:
    if decision == "confirmed" and not mechanism_key:
        raise ValueError("confirmed claims require a mechanism_key")
    playbook, _ = load_playbook()
    if mechanism_key:
        _mechanism(playbook, mechanism_key)
    identifier = uuid.UUID(claim_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        row = await session.get(AuthorClaim, identifier)
        if row is None:
            return None
        row.status = decision
        row.mechanism_key = mechanism_key if decision == "confirmed" else None
        row.mechanism_version = playbook.version if decision == "confirmed" else None
        row.confirmed_at = datetime.now(UTC)
        row.confirmed_by = "local_user"
        row.review_notes = review_notes.strip()
        await session.flush()
        await session.refresh(row)
        return _claim_payload(row)


def _market_rule(
    rule: EvidenceRule,
    markets: dict[str, dict[str, Any]],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    item = next((markets[key] for key in rule.market_keys if key in markets), None)
    if item is None:
        return {
            "rule_key": rule.key,
            "label": rule.label,
            "state": "missing",
            "statement": "本地没有匹配的 observed 市场序列。",
            "evidence_ids": [],
            "missing_reason": "market_series_missing",
        }
    timestamp = datetime.fromisoformat(str(item["timestamp"]).replace("Z", "+00:00"))
    age_days = max(0.0, (cutoff - _aware(timestamp)).total_seconds() / 86400)
    raw_value = item.get("change_value") if item.get("change_unit") == "bp" else item.get(
        "change_percent"
    )
    observed = float(raw_value) if raw_value is not None else None
    base = {
        "rule_key": rule.key,
        "label": rule.label,
        "instrument_key": item.get("instrument_key"),
        "observed_value": observed,
        "unit": "bp" if item.get("change_unit") == "bp" else "%",
        "observed_at": _aware(timestamp).isoformat(),
        "age_days": round(age_days, 2),
        "provider": item.get("provider"),
        "quality": item.get("quality_grade"),
        "proxy": bool(item.get("is_proxy")),
        "evidence_ids": list(item.get("evidence_ids") or []),
    }
    if age_days > rule.max_age_days:
        return {
            **base,
            "state": "missing",
            "statement": f"数据距检查时点 {age_days:.1f} 天，超过 {rule.max_age_days} 天限制。",
            "missing_reason": "market_data_stale",
        }
    if observed is None:
        return {
            **base,
            "state": "missing",
            "statement": "缺少可比较的最近有效交易日变化。",
            "missing_reason": "market_change_missing",
        }
    if abs(observed) < rule.minimum_absolute:
        state = "neutral"
        statement = f"变化 {observed:+.2f} {base['unit']} 未达到预设显著阈值。"
    else:
        actual = "up" if observed > 0 else "down"
        state = "supporting" if actual == rule.expected_direction else "contradicting"
        statement = (
            f"变化 {observed:+.2f} {base['unit']}，"
            f"{'符合' if state == 'supporting' else '反对'}预设方向。"
        )
    return {**base, "state": state, "statement": statement, "missing_reason": None}


def _macro_rule(
    rule: EvidenceRule,
    dimensions: dict[str, dict[str, Any]],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    dimension = dimensions.get(str(rule.dimension))
    if not dimension or dimension.get("score") is None:
        return {
            "rule_key": rule.key,
            "label": rule.label,
            "dimension": rule.dimension,
            "state": "missing",
            "statement": "该宏观维度没有可计算的 observed 状态。",
            "evidence_ids": [],
            "missing_reason": "macro_dimension_missing",
        }
    drivers = list(dimension.get("top_drivers") or [])
    dates = [
        datetime.fromisoformat(str(item["period_start"]))
        for item in drivers
        if item.get("period_start")
    ]
    latest_period = max(dates) if dates else None
    age_days = (cutoff.date() - latest_period.date()).days if latest_period else None
    score = float(dimension["score"])
    evidence_ids = [
        str(evidence_id)
        for driver in drivers
        for evidence_id in list(driver.get("evidence_ids") or [])
    ]
    base = {
        "rule_key": rule.key,
        "label": rule.label,
        "dimension": rule.dimension,
        "observed_value": score,
        "unit": "state_score",
        "observed_at": latest_period.date().isoformat() if latest_period else None,
        "age_days": age_days,
        "quality": [driver.get("quality") for driver in drivers],
        "evidence_ids": evidence_ids,
        "drivers": [
            {
                "series_key": driver.get("series_key"),
                "title": driver.get("title"),
                "score": driver.get("score"),
                "source_url": driver.get("source_url"),
            }
            for driver in drivers
        ],
    }
    if latest_period is None or (age_days is not None and age_days > rule.max_age_days):
        return {
            **base,
            "state": "missing",
            "statement": "宏观输入超过预设时效或缺少发布日期。",
            "missing_reason": "macro_data_stale",
        }
    if abs(score) < rule.minimum_absolute:
        state = "neutral"
        statement = f"状态分数 {score:+.2f}，尚未达到预设方向阈值。"
    else:
        actual = "up" if score > 0 else "down"
        state = "supporting" if actual == rule.expected_direction else "contradicting"
        statement = (
            f"状态分数 {score:+.2f}，"
            f"{'符合' if state == 'supporting' else '反对'}预设方向。"
        )
    return {**base, "state": state, "statement": statement, "missing_reason": None}


def _step_result(
    step: MechanismStep,
    markets: dict[str, dict[str, Any]],
    dimensions: dict[str, dict[str, Any]],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    checks = [
        _market_rule(rule, markets, cutoff=cutoff)
        if rule.kind == "market"
        else _macro_rule(rule, dimensions, cutoff=cutoff)
        for rule in step.evidence_rules
    ]
    states = {str(item["state"]) for item in checks}
    if "supporting" in states and "contradicting" in states:
        state = "mixed"
    elif "contradicting" in states:
        state = "contradicting"
    elif states == {"supporting"} or (
        "supporting" in states and states <= {"supporting", "neutral"}
    ):
        state = "supporting"
    elif states == {"neutral"}:
        state = "neutral"
    else:
        state = "missing"
    return {
        "key": step.key,
        "label": step.label,
        "mechanism": step.mechanism,
        "state": state,
        "checks": checks,
    }


def _evaluate_mechanism(
    definition: MechanismDefinition,
    markets: dict[str, dict[str, Any]],
    dimensions: dict[str, dict[str, Any]],
    *,
    cutoff: datetime,
) -> dict[str, Any]:
    steps = [
        _step_result(step, markets, dimensions, cutoff=cutoff)
        for step in definition.causal_chain
    ]
    supporting = sum(item["state"] == "supporting" for item in steps)
    contradicting = sum(item["state"] in {"contradicting", "mixed"} for item in steps)
    missing = sum(item["state"] == "missing" for item in steps)
    tested = len(steps) - missing
    supported_through = 0
    for step in steps:
        if step["state"] != "supporting":
            break
        supported_through += 1
    if tested == 0:
        status = "insufficient_data"
    elif supporting and contradicting:
        status = "mixed"
    elif contradicting >= max(1, tested / 2):
        status = "contradicted"
    elif supporting >= max(1, tested * 0.7) and missing == 0:
        status = "supported"
    elif missing:
        status = "incomplete"
    else:
        status = "unconfirmed"
    wording = {
        "insufficient_data": "当前没有足够的 observed 数据检查这条机制。",
        "mixed": "支持与反对证据同时存在，不能给出单一解释。",
        "contradicted": "当前多数可检验证据与这条机制的预设方向相反。",
        "supported": "当前 observed 数据与这条机制广泛一致，但不构成因果证明。",
        "incomplete": "部分环节得到支持，但关键证据缺失或过期。",
        "unconfirmed": "现有变化不足以确认或否定这条机制。",
    }[status]
    return {
        "key": definition.key,
        "title": definition.title,
        "summary": definition.summary,
        "status": status,
        "system_assessment": wording,
        "chain_progress": {
            "supported_through": supported_through,
            "total_steps": len(steps),
            "supporting_steps": supporting,
            "contradicting_steps": contradicting,
            "missing_steps": missing,
        },
        "steps": steps,
        "falsifiers": definition.falsifiers,
        "limitations": definition.limitations,
    }


async def assess_author_claim(
    engine: AsyncEngine,
    claim_id: str,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any] | None:
    identifier = uuid.UUID(claim_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        claim = await session.get(AuthorClaim, identifier)
        if claim is None:
            return None
        source = await session.get(ResearchSource, claim.source_id)
        if source is None:
            return None
        claim_payload = _claim_payload(claim)
        source_payload = _source_payload(source)
    if claim.status != "confirmed" or not claim.mechanism_key:
        raise PermissionError("only a human-confirmed claim can be assessed")
    cutoff = _aware(as_of or datetime.now(UTC))
    playbook, playbook_hash = load_playbook()
    if claim.mechanism_version != playbook.version:
        raise ValueError("the claim references a playbook version unavailable in this build")
    primary = _mechanism(playbook, claim.mechanism_key)
    mode = cast(DataMode, claim.data_mode)
    market_payload = await build_market_dashboard(
        engine, data_mode=mode, horizon="1d", as_of=cutoff
    )
    state_payload = await build_world_state(engine, data_mode=mode, as_of=cutoff)
    market_map = {
        str(item["instrument_key"]): item for item in list(market_payload.get("items") or [])
    }
    dimensions = dict(state_payload.get("dimensions") or {})
    selected = [primary, *[_mechanism(playbook, key) for key in primary.competing_mechanisms]]
    evaluations = [
        _evaluate_mechanism(item, market_map, dimensions, cutoff=cutoff) for item in selected
    ]
    relevant_market_keys = {
        key
        for mechanism in selected
        for step in mechanism.causal_chain
        for rule in step.evidence_rules
        for key in rule.market_keys
    }
    relevant_dimensions = {
        str(rule.dimension)
        for mechanism in selected
        for step in mechanism.causal_chain
        for rule in step.evidence_rules
        if rule.dimension
    }
    input_snapshot = {
        "claim": claim_payload,
        "source": {
            key: source_payload[key]
            for key in ("id", "title", "author", "source_url", "content_hash", "data_mode")
        },
        "as_of": cutoff.isoformat(),
        "markets": {
            key: market_map[key]
            for key in sorted(relevant_market_keys)
            if key in market_map
        },
        "macro_dimensions": {
            key: dimensions[key] for key in sorted(relevant_dimensions) if key in dimensions
        },
        "market_methodology": market_payload.get("methodology_version"),
        "state_methodology": state_payload.get("methodology_version"),
    }
    result = {
        "author_claim": {
            "statement": claim.statement,
            "exact_quote": claim.exact_quote,
            "author": source.author,
            "source_title": source.title,
            "source_url": source.source_url,
        },
        "system_assessment": {
            "primary_mechanism_key": primary.key,
            "as_of": cutoff.isoformat(),
            "data_mode": claim.data_mode,
            "mechanisms": evaluations,
            "truthfulness_note": (
                "状态表示证据与预设机制的一致性，不是因果证明，也不是概率。"
            ),
        },
    }
    now = datetime.now(UTC)
    row = MechanismAssessment(
        claim_id=claim.id,
        playbook_key=playbook.playbook_key,
        playbook_version=playbook.version,
        playbook_hash=playbook_hash,
        primary_mechanism_key=primary.key,
        as_of=cutoff,
        evaluated_at=now,
        data_mode=claim.data_mode,
        input_snapshot_json=input_snapshot,
        input_snapshot_hash=_hash(input_snapshot),
        result_json=result,
        output_hash=_hash(result),
    )
    async with factory() as session, session.begin():
        session.add(row)
        await session.flush()
        return _assessment_payload(row)


async def list_reasoning_cases(
    engine: AsyncEngine, *, data_mode: DataMode = "observed"
) -> list[dict[str, Any]]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        sources = list(
            (
                await session.scalars(
                    select(ResearchSource)
                    .where(ResearchSource.data_mode == data_mode)
                    .order_by(ResearchSource.updated_at.desc())
                )
            ).all()
        )
        output: list[dict[str, Any]] = []
        for source in sources:
            claims = list(
                (
                    await session.scalars(
                        select(AuthorClaim)
                        .where(AuthorClaim.source_id == source.id)
                        .order_by(AuthorClaim.created_at.desc())
                    )
                ).all()
            )
            claim_items: list[dict[str, Any]] = []
            for claim in claims:
                assessment = await session.scalar(
                    select(MechanismAssessment)
                    .where(MechanismAssessment.claim_id == claim.id)
                    .order_by(MechanismAssessment.evaluated_at.desc())
                    .limit(1)
                )
                claim_items.append(
                    {
                        **_claim_payload(claim),
                        "latest_assessment": _assessment_payload(assessment)
                        if assessment
                        else None,
                    }
                )
            output.append({"source": _source_payload(source), "claims": claim_items})
        return output
