"""Versioned, deterministic validators for Story Design candidates."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError

from .domain import GENERATOR_CATALOG, PlanningScope


STORY_DESIGN_VALIDATOR_VERSION = "1.0.0"
_GENERATOR_DEFINITION_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True, slots=True)
class StoryDesignValidatorReceipt:
    validation_kind: str
    validator_name: str
    validator_version: str
    status: str
    input_hash: str
    result_hash: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoryDesignValidationResult:
    status: str
    validator_version: str
    implementation_hash: str
    input_hash: str
    result_hash: str
    receipts: tuple[StoryDesignValidatorReceipt, ...]

    def to_evidence(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "validator": "StoryDesignValidatorSuite",
            "validator_version": self.validator_version,
            "validator_implementation_hash": self.implementation_hash,
            "input_hash": self.input_hash,
            "result_hash": self.result_hash,
            "receipts": [asdict(receipt) for receipt in self.receipts],
        }


_GENERATOR_SCOPE = {
    "creative.candidates.generate": PlanningScope.BOOK,
    "theme.candidates.generate": PlanningScope.BOOK,
    "ending.intent.generate": PlanningScope.BOOK,
    "world.design.generate": PlanningScope.BOOK,
    "character.cast.generate": PlanningScope.BOOK,
    "book_plan.generate": PlanningScope.BOOK,
    "volume_plan.generate": PlanningScope.VOLUME,
    "arc_plan.generate": PlanningScope.ARC,
    "chapter_group_plan.generate": PlanningScope.CHAPTER_GROUP,
    "chapter_plan.generate": PlanningScope.CHAPTER,
}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _receipt(
    *,
    validation_kind: str,
    validator_name: str,
    input_hash: str,
    evidence: dict[str, Any],
) -> StoryDesignValidatorReceipt:
    result = {
        "validation_kind": validation_kind,
        "validator_name": validator_name,
        "validator_version": STORY_DESIGN_VALIDATOR_VERSION,
        "status": "PASS",
        "input_hash": input_hash,
        "evidence": evidence,
    }
    return StoryDesignValidatorReceipt(
        validation_kind=validation_kind,
        validator_name=validator_name,
        validator_version=STORY_DESIGN_VALIDATOR_VERSION,
        status="PASS",
        input_hash=input_hash,
        result_hash=_canonical_hash(result),
        evidence=evidence,
    )


def validate_story_design_candidate(
    *,
    content: Mapping[str, Any],
    project_id: str,
    generator_operation_name: str,
    planning_scope: PlanningScope | str,
    logical_key: str,
) -> StoryDesignValidationResult:
    """Validate schema, structure, semantics, generator contract and scope."""

    scope = PlanningScope(planning_scope)
    frozen_content = dict(content)
    input_value = {
        "content": frozen_content,
        "project_id": project_id,
        "generator_operation_name": generator_operation_name,
        "planning_scope": scope.value,
        "logical_key": logical_key,
    }
    input_hash = _canonical_hash(input_value)
    schema_version = str(frozen_content.get("schema_version") or "")
    candidate_payload = frozen_content.get("candidate_payload")
    if (
        schema_version != "story_design.authority.v1"
        or str(frozen_content.get("project_id") or "") != project_id
        or not isinstance(candidate_payload, dict)
        or not candidate_payload
    ):
        raise KernelError(
            "STORY_DESIGN_SCHEMA_INVALID",
            "Story Design candidate must match its authority schema and Project scope",
        )
    schema = _receipt(
        validation_kind="SCHEMA",
        validator_name="story-design-schema-validator",
        input_hash=input_hash,
        evidence={
            "schema_version": schema_version,
            "candidate_field_count": len(candidate_payload),
            "project_scope_match": True,
        },
    )

    declared_identity = (
        str(frozen_content.get("generator_operation_name") or ""),
        str(frozen_content.get("planning_scope") or ""),
        str(frozen_content.get("logical_key") or ""),
    )
    if declared_identity != (generator_operation_name, scope.value, logical_key):
        raise KernelError(
            "STORY_DESIGN_STRUCTURAL_INVALID",
            "Story Design identity differs from the validated activation identity",
        )
    if (
        not logical_key
        or logical_key.strip() != logical_key
        or any(character.isspace() for character in logical_key)
    ):
        raise KernelError(
            "STORY_DESIGN_STRUCTURAL_INVALID",
            "Story Design logical key must be stable and whitespace-free",
        )
    structural = _receipt(
        validation_kind="STRUCTURAL",
        validator_name="story-design-structural-validator",
        input_hash=input_hash,
        evidence={
            "identity_bound": True,
            "logical_key": logical_key,
            "candidate_payload_hash": _canonical_hash(candidate_payload),
        },
    )

    generator = GENERATOR_CATALOG.get(generator_operation_name)
    if generator is None:
        raise KernelError(
            "GENERATOR_DEFINITION_NOT_FOUND",
            "Story Design generator is not registered",
        )
    if (
        not generator.structural_validator_keys
        or not generator.semantic_validator_keys
        or not generator.output_schema_version
        or not _GENERATOR_DEFINITION_VERSION.fullmatch(generator.definition_version)
    ):
        raise KernelError(
            "GENERATOR_CONTRACT_INVALID",
            "Story Design GeneratorDefinition is not validation-complete",
        )
    generator_receipt = _receipt(
        validation_kind="GENERATOR_CONTRACT",
        validator_name="story-design-generator-contract-validator",
        input_hash=input_hash,
        evidence={
            "generator_operation_name": generator.operation_name,
            "generator_definition_version": generator.definition_version,
            "candidate_type": generator.output_candidate_type,
            "structural_validator_keys": list(generator.structural_validator_keys),
            "semantic_validator_keys": list(generator.semantic_validator_keys),
        },
    )

    expected_scope = _GENERATOR_SCOPE[generator_operation_name]
    if scope is not expected_scope:
        raise KernelError(
            "STORY_DESIGN_SCOPE_INVALID",
            f"{generator_operation_name} requires {expected_scope.value} scope",
        )
    scope_receipt = _receipt(
        validation_kind="PLANNING_SCOPE",
        validator_name="story-design-planning-scope-validator",
        input_hash=input_hash,
        evidence={
            "planning_scope": scope.value,
            "generator_scope": expected_scope.value,
            "scope_match": True,
        },
    )

    objective = candidate_payload.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        raise KernelError(
            "STORY_DESIGN_SEMANTIC_INVALID",
            "Story Design candidate requires a non-empty objective",
        )
    semantic = _receipt(
        validation_kind="SEMANTIC",
        validator_name="story-design-semantic-validator",
        input_hash=input_hash,
        evidence={
            "objective_hash": _canonical_hash(objective.strip()),
            "objective_present": True,
            "planning_scope": scope.value,
        },
    )
    receipts = (
        schema,
        structural,
        semantic,
        generator_receipt,
        scope_receipt,
    )
    implementation_hash = (
        "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
    result_without_hash = {
        "status": "PASS",
        "validator_version": STORY_DESIGN_VALIDATOR_VERSION,
        "implementation_hash": implementation_hash,
        "input_hash": input_hash,
        "receipts": [asdict(receipt) for receipt in receipts],
    }
    return StoryDesignValidationResult(
        status="PASS",
        validator_version=STORY_DESIGN_VALIDATOR_VERSION,
        implementation_hash=implementation_hash,
        input_hash=input_hash,
        result_hash=_canonical_hash(result_without_hash),
        receipts=receipts,
    )


__all__ = [
    "STORY_DESIGN_VALIDATOR_VERSION",
    "StoryDesignValidationResult",
    "StoryDesignValidatorReceipt",
    "validate_story_design_candidate",
]
