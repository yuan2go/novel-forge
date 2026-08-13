"""Shared lifecycle and generator contracts for authoritative story design."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DesignLifecycle(StrEnum):
    CANDIDATE = "CANDIDATE"
    MATERIALIZED = "MATERIALIZED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class DesignQualification(StrEnum):
    PENDING = "PENDING"
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    SEMANTICALLY_VALID = "SEMANTICALLY_VALID"
    QUALIFIED = "QUALIFIED"
    FAILED = "FAILED"


class DesignApproval(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DesignFreshness(StrEnum):
    CURRENT = "CURRENT"
    IMPACTED = "IMPACTED"
    STALE = "STALE"


class PlanningScope(StrEnum):
    BOOK = "BOOK"
    VOLUME = "VOLUME"
    ARC = "ARC"
    CHAPTER_GROUP = "CHAPTER_GROUP"
    CHAPTER = "CHAPTER"


class DesignTransition(StrEnum):
    ENROLL = "ENROLL"
    MATERIALIZE = "MATERIALIZE"
    STRUCTURAL_VALIDATE = "STRUCTURAL_VALIDATE"
    SEMANTIC_VALIDATE = "SEMANTIC_VALIDATE"
    QUALIFY = "QUALIFY"
    SUBMIT_APPROVAL = "SUBMIT_APPROVAL"
    APPROVE = "APPROVE"
    ACTIVATE = "ACTIVATE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class GeneratorDefinition:
    operation_name: str
    capability: str
    input_contract_version: str
    output_candidate_type: str
    output_schema_version: str
    prompt_contract_version: str
    skill_version: str
    route_policy_ref: str
    materializer_key: str
    structural_validator_keys: tuple[str, ...]
    semantic_validator_keys: tuple[str, ...]
    repair_policy_key: str
    approval_policy_key: str
    activation_policy_key: str
    maximum_semantic_repairs: int
    maximum_structural_regenerations: int
    risk_class: str
    definition_version: str = "1.0.0"

    def __post_init__(self) -> None:
        required = (
            self.operation_name,
            self.capability,
            self.input_contract_version,
            self.output_candidate_type,
            self.output_schema_version,
            self.prompt_contract_version,
            self.skill_version,
            self.route_policy_ref,
            self.materializer_key,
            self.repair_policy_key,
            self.approval_policy_key,
            self.activation_policy_key,
        )
        if not all(required) or not self.structural_validator_keys:
            raise ValueError("GeneratorDefinition is incomplete")
        if not self.semantic_validator_keys:
            raise ValueError("GeneratorDefinition requires semantic validators")
        if (
            self.maximum_semantic_repairs < 0
            or self.maximum_structural_regenerations < 0
        ):
            raise ValueError("Generator repair bounds cannot be negative")


def _generator(
    operation_name: str,
    capability: str,
    output_type: str,
    *,
    risk: str,
    definition_version: str = "1.0.0",
    output_schema_version: str = "",
    prompt_contract_version: str = "",
) -> GeneratorDefinition:
    key = operation_name.replace(".", "-")
    return GeneratorDefinition(
        operation_name=operation_name,
        capability=capability,
        input_contract_version=f"{key}-input-v1",
        output_candidate_type=output_type,
        output_schema_version=(output_schema_version or f"{key}-output-v1"),
        prompt_contract_version=(prompt_contract_version or f"{key}-prompt-v1"),
        skill_version=f"{key}-skill-v1",
        route_policy_ref=f"route-policy:{capability}:v1",
        materializer_key=f"story-design:{key}:materialize",
        structural_validator_keys=(f"{key}:schema", f"{key}:lineage"),
        semantic_validator_keys=(f"{key}:semantic",),
        repair_policy_key=f"{key}:bounded-repair",
        approval_policy_key=(
            "human-high-risk-v1" if risk == "HIGH" else "domain-authority-v1"
        ),
        activation_policy_key="single-active-logical-key-v1",
        maximum_semantic_repairs=2,
        maximum_structural_regenerations=1,
        risk_class=risk,
        definition_version=definition_version,
    )


GENERATOR_DEFINITIONS = (
    _generator(
        "creative.candidates.generate",
        "creative.proposal.generate",
        "creative_candidate_pool",
        risk="MEDIUM",
    ),
    _generator(
        "theme.candidates.generate",
        "theme.question.generate",
        "theme_candidate_pool",
        risk="MEDIUM",
    ),
    _generator(
        "ending.intent.generate",
        "ending.intent.generate",
        "ending_intent_candidate",
        risk="HIGH",
    ),
    _generator(
        "world.design.generate",
        "world.design.generate",
        "world_bible_candidate",
        risk="HIGH",
    ),
    _generator(
        "character.cast.generate",
        "character.cast.generate",
        "character_cast_candidate",
        risk="HIGH",
    ),
    _generator(
        "book_plan.generate",
        "planning.book.generate",
        "book_plan_candidate",
        risk="HIGH",
    ),
    _generator(
        "volume_plan.generate",
        "planning.volume.generate",
        "volume_plan_candidate",
        risk="HIGH",
    ),
    _generator(
        "arc_plan.generate",
        "planning.arc.generate",
        "arc_plan_candidate",
        risk="HIGH",
    ),
    _generator(
        "chapter_group_plan.generate",
        "planning.chapter_group.generate",
        "chapter_group_plan_candidate",
        risk="MEDIUM",
    ),
    _generator(
        "chapter_plan.generate",
        "planning.story_chapter.generate",
        "chapter_plan_candidate",
        risk="MEDIUM",
        definition_version="1.4.0",
        output_schema_version="chapter-plan-generate-output-v4",
        prompt_contract_version="chapter-plan-generate-prompt-v3",
    ),
)

GENERATOR_CATALOG = {item.operation_name: item for item in GENERATOR_DEFINITIONS}


__all__ = [
    "DesignApproval",
    "DesignFreshness",
    "DesignLifecycle",
    "DesignQualification",
    "DesignTransition",
    "GENERATOR_CATALOG",
    "GENERATOR_DEFINITIONS",
    "GeneratorDefinition",
    "PlanningScope",
]
