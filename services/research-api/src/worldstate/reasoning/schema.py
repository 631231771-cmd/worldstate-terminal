"""Strict schemas for macro mechanism playbooks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    kind: Literal["market", "macro_dimension"]
    market_keys: list[str] = Field(default_factory=list)
    dimension: str | None = None
    expected_direction: Literal["up", "down"]
    horizon: Literal["1d", "1w", "1m", "3m"] = "1d"
    minimum_absolute: float = Field(default=0.0, ge=0)
    max_age_days: int = Field(default=10, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_target(self) -> EvidenceRule:
        if self.kind == "market" and not self.market_keys:
            raise ValueError("market evidence requires market_keys")
        if self.kind == "macro_dimension" and not self.dimension:
            raise ValueError("macro dimension evidence requires dimension")
        return self


class MechanismStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    evidence_rules: list[EvidenceRule] = Field(min_length=1)


class MechanismDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    causal_chain: list[MechanismStep] = Field(min_length=2)
    falsifiers: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    competing_mechanisms: list[str] = Field(default_factory=list)


class MechanismPlaybook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    playbook_key: str = Field(pattern=r"^[a-z0-9_]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    title: str = Field(min_length=1)
    source_framework: str = Field(min_length=1)
    description: str = Field(min_length=1)
    mechanisms: list[MechanismDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> MechanismPlaybook:
        keys = [item.key for item in self.mechanisms]
        if len(keys) != len(set(keys)):
            raise ValueError("mechanism keys must be unique")
        known = set(keys)
        for mechanism in self.mechanisms:
            unknown = set(mechanism.competing_mechanisms) - known
            if unknown:
                raise ValueError(
                    f"{mechanism.key} references unknown competitors: {sorted(unknown)}"
                )
        return self
