"""EvidencePack integrity and AI-output validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

URL_PATTERN = re.compile(r"https?://[^\s)\]>\"']+")
REQUIRED_SECTIONS = ("已确认事实", "历史关系", "当前推断", "竞争性解释", "无法确认")


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def evidence_hash(pack: dict[str, Any]) -> str:
    payload = {key: value for key, value in pack.items() if key != "evidence_pack_hash"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def allowed_source_urls(pack: dict[str, Any]) -> set[str]:
    urls: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"url", "source_url"} and isinstance(item, str):
                    urls.add(item.rstrip(".,"))
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(pack)
    return urls


def validate_evidence_pack(pack: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if pack.get("schema_version") != "evidence-pack-v1":
        errors.append("unsupported_evidence_pack_schema")
    if pack.get("evidence_pack_hash") != evidence_hash(pack):
        errors.append("evidence_pack_hash_mismatch")
    release = pack.get("release")
    if not isinstance(release, dict) or not release.get("source"):
        errors.append("release_source_missing")
    constraints = pack.get("constraints")
    if not isinstance(constraints, dict):
        errors.append("constraints_missing")
    else:
        for key in (
            "facts_and_inferences_separated",
            "no_unique_causality_claim",
            "proxy_assets_labelled",
            "fixture_data_labelled",
        ):
            if constraints.get(key) is not True:
                errors.append(f"constraint_not_satisfied:{key}")
    quality = release.get("data_quality", []) if isinstance(release, dict) else []
    if any(item.get("is_fixture") for item in quality if isinstance(item, dict)):
        warnings.append("evidence_contains_fixture_data")
    if any(item.get("is_proxy") for item in quality if isinstance(item, dict)):
        warnings.append("evidence_contains_proxy_assets")
    return ValidationResult(not errors, tuple(errors), tuple(warnings))


def validate_ai_output(text: str, pack: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    for section in REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"required_section_missing:{section}")
    allowed_urls = allowed_source_urls(pack)
    for url in URL_PATTERN.findall(text):
        if url.rstrip(".,") not in allowed_urls:
            errors.append(f"unsupported_citation:{url}")
    for phrase in ("必然导致", "唯一原因", "可以确定是", "百分之百因为"):
        if phrase in text:
            errors.append(f"strong_causality_language:{phrase}")
    if "fixture" in json.dumps(pack, ensure_ascii=False).lower() and "fixture" not in text.lower():
        warnings.append("fixture_disclosure_not_explicit")
    return ValidationResult(not errors, tuple(errors), tuple(warnings))
