"""AI Researcher that may only summarize an already-built EvidencePack."""

from __future__ import annotations

import json
from typing import Any

import httpx

from worldstate.ai_researcher.evidence import validate_ai_output, validate_evidence_pack
from worldstate.config import Settings


def _deterministic_answer(question: str, pack: dict[str, Any]) -> str:
    release = pack["release"]
    research = pack.get("research") or {}
    explanations = research.get("explanations") or []
    primary = explanations[0] if explanations else {}
    historical = pack.get("historical") or {}
    source = release.get("source") or {}
    return "\n".join(
        (
            f"问题：{question}",
            "",
            "已确认事实",
            str(research.get("report") or "当前没有完成的结构化复盘。"),
            "",
            "历史关系",
            (
                f"历史模块为 {historical.get('mode', 'insufficient')} 模式，"
                f"过滤前 {historical.get('pre_filter_count', 0)} 个、"
                f"过滤后 {historical.get('post_filter_count', 0)} 个样本。"
            ),
            "",
            "当前推断",
            str(primary.get("summary") or "数据不足，无法形成有证据约束的主要推断。"),
            "",
            "竞争性解释",
            (
                "；".join(
                    str(item.get("title")) for item in explanations[1:] if isinstance(item, dict)
                )
                or "当前结构化规则没有产生额外竞争性解释。"
            ),
            "",
            "无法确认",
            "；".join(str(item) for item in research.get("data_gaps", []))
            or "没有登记数据缺口，但这不等于证明了唯一因果。",
            "",
            f"来源：{source.get('url', '未登记')}",
        )
    )


def _system_prompt() -> str:
    return (
        "你是WorldState宏观研究助手。只能使用用户消息中的EvidencePack。"
        "必须按“已确认事实、历史关系、当前推断、竞争性解释、无法确认”五个标题回答。"
        "不得创造数据、新闻或来源；不得把相关性写成确定因果；"
        "代理资产和fixture必须明确披露。只引用EvidencePack已有URL。"
    )


async def answer_question(
    *,
    question: str,
    pack: dict[str, Any],
    settings: Settings,
) -> dict[str, object]:
    pack_validation = validate_evidence_pack(pack)
    if not pack_validation.valid:
        raise ValueError(f"invalid EvidencePack: {', '.join(pack_validation.errors)}")
    fallback = _deterministic_answer(question, pack)
    provider: str = settings.resolved_ai_provider
    if provider == "none":
        output_validation = validate_ai_output(fallback, pack)
        return {
            "mode": "deterministic",
            "provider": "none",
            "answer": fallback,
            "evidence_pack_hash": pack["evidence_pack_hash"],
            "validation": {
                "valid": output_validation.valid,
                "errors": list(output_validation.errors),
                "warnings": [*pack_validation.warnings, *output_validation.warnings],
            },
        }

    if provider in {"openai", "compatible"}:
        secret = settings.openai_api_key if provider == "openai" else settings.ai_compatible_api_key
        api_key = secret.get_secret_value() if secret else ""
        base_url = str(settings.ai_base_url).rstrip("/")
        model = settings.ai_model
    else:
        api_key = ""
        base_url = str(settings.ollama_base_url).rstrip("/")
        model = settings.ollama_model
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": (
                    f"问题：{question}\n\nEvidencePack:\n"
                    f"{json.dumps(pack, ensure_ascii=False, default=str)}"
                ),
            },
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds) as client:
            response = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            text = str(response.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        text = fallback
        provider = "deterministic_fallback"
    output_validation = validate_ai_output(text, pack)
    if not output_validation.valid:
        text = fallback
        provider = "validation_fallback"
        output_validation = validate_ai_output(text, pack)
    return {
        "mode": (
            "ai"
            if provider not in {"deterministic_fallback", "validation_fallback"}
            else "deterministic"
        ),
        "provider": provider,
        "model": model,
        "answer": text,
        "evidence_pack_hash": pack["evidence_pack_hash"],
        "validation": {
            "valid": output_validation.valid,
            "errors": list(output_validation.errors),
            "warnings": [*pack_validation.warnings, *output_validation.warnings],
        },
    }
