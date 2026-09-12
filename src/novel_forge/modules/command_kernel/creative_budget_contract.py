from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from .errors import KernelError


PHASES = ("SOURCE", "CREATION", "REPAIR")
_ALLOCATIONS = dict(zip(PHASES, ("source_allocation", "creation_allocation", "repair_allocation"), strict=True))
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_UNKNOWN = {"UNKNOWN", "NOT_REPORTED", "UNSPECIFIED", "UNAVAILABLE"}


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_TEXT_SCHEMA = {"type": "string", "minLength": 1, "pattern": r"\S"}
_ALLOCATION_SCHEMA = _object_schema({key: {"type": "integer", "minimum": 0} for key in ("calls", "tokens")})
_ARM_SCHEMA = _object_schema({
    "arm": {"type": "string", "enum": ["A", "B"]},
    "project_id": _TEXT_SCHEMA,
    "book_id": _TEXT_SCHEMA,
    **{key: _ALLOCATION_SCHEMA for key in ("project_total", *_ALLOCATIONS.values())},
})
POLICY_SCHEMA = _object_schema({
    "policy_version": _TEXT_SCHEMA,
    "comparison_budget": _object_schema({
        "contract_version": {"type": "string", "const": "creative-experiment-budget.v1"},
        "experiment_id": _TEXT_SCHEMA,
        "accounting_basis": {"type": "string", "const": "ACCOUNT_ENTITLEMENT"},
        "shared_total": _ALLOCATION_SCHEMA,
        "arms": {"type": "array", "minItems": 1, "maxItems": 2, "items": _ARM_SCHEMA},
    }),
    "authorization": _object_schema({
        "authorization_ref": _TEXT_SCHEMA,
        "evidence_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        "project_id": _TEXT_SCHEMA,
        "book_id": _TEXT_SCHEMA,
        "authorized_cumulative_caps": _object_schema({phase: _ALLOCATION_SCHEMA for phase in PHASES}),
    }),
})


def _invalid(message: str) -> KernelError:
    return KernelError("CREATIVE_BUDGET_CONTRACT_INVALID", message)


def _object(value: Any, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"Comparison requires {label} object")
    if set(value) != fields:
        raise _invalid(f"Comparison {label} has missing or unknown fields")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in _UNKNOWN:
        raise _invalid(f"Comparison requires known {label}")
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise _invalid(f"Comparison requires finite integer {label} >= {minimum}")
    return value


def _allocation(value: Any, label: str, *, positive: bool = False, paired: bool = True) -> dict[str, int]:
    result = _object(value, label, {"calls", "tokens"})
    for key, amount in result.items():
        _integer(amount, f"{label}.{key}", int(positive))
    if paired and bool(result["calls"]) != bool(result["tokens"]):
        raise _invalid(f"Comparison {label} must allocate calls and tokens together")
    return result


def validate_comparison_budget(value: Any, *, require_both_arms: bool = False) -> dict[str, Any]:
    contract = _object(value, "comparison_budget", {
        "contract_version", "experiment_id", "accounting_basis", "shared_total", "arms",
    })
    if contract["contract_version"] != "creative-experiment-budget.v1":
        raise _invalid("Comparison budget contract version is unsupported")
    _text(contract["experiment_id"], "experiment_id")
    if not isinstance(contract["accounting_basis"], str) or contract["accounting_basis"] not in {"ACCOUNT_ENTITLEMENT", "PRICED"}:
        raise _invalid("Comparison budget accounting basis is unsupported")
    shared = _allocation(contract["shared_total"], "shared_total", positive=True)
    arms = contract["arms"]
    if not isinstance(arms, list) or not 1 <= len(arms) <= 2:
        raise _invalid("Comparison budget requires the explicit A/B allocation")
    by_arm = {}
    for item in arms:
        arm = _object(item, "arm allocation", {
            "arm", "project_id", "book_id", "project_total", *_ALLOCATIONS.values(),
        })
        name = _text(arm["arm"], "arm")
        if name not in {"A", "B"} or name in by_arm:
            raise _invalid("Comparison budget arm identities must be unique A/B")
        by_arm[name] = arm
        for key in ("project_id", "book_id"):
            _text(arm[key], key)
        for key in ("project_total", *_ALLOCATIONS.values()):
            _allocation(arm[key], key, positive=key in {"project_total", "creation_allocation"})
        if name == "B" and arm["source_allocation"] != {"calls": 0, "tokens": 0}:
            raise _invalid("Comparison control cannot allocate external Source work")
        for key in shared:
            if arm["project_total"][key] != sum(arm[field][key] for field in _ALLOCATIONS.values()):
                raise _invalid("Comparison project total must equal its frozen phase allocations")
    if (require_both_arms and set(by_arm) != {"A", "B"}) or (len(arms) == 1 and set(by_arm) != {"A"}):
        raise _invalid("Comparison requires both A/B arms; only Source preparation may freeze A alone")
    for key in shared:
        if sum(arm["project_total"][key] for arm in arms) > shared[key]:
            raise _invalid("Comparison project allocations exceed the shared authorized ceiling")
    if len(arms) == 2:
        for key in ("project_id", "book_id"):
            if by_arm["A"][key] == by_arm["B"][key]:
                raise _invalid(f"Comparison arms must have independent {key}")
        for key in ("creation_allocation", "repair_allocation"):
            if by_arm["A"][key] != by_arm["B"][key]:
                raise _invalid(f"Comparison creative opportunity differs: {key}")
    return deepcopy(contract)


def arm_for_project(comparison_budget: dict[str, Any], project_id: str) -> dict[str, Any]:
    plan = validate_comparison_budget(comparison_budget)
    for arm in plan["arms"]:
        if arm["project_id"] == project_id:
            return arm
    raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "project does not belong to the frozen experiment")


def contract_hash(comparison_budget: dict[str, Any]) -> str:
    plan = validate_comparison_budget(comparison_budget)
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_policy(value: Any) -> dict[str, Any]:
    policy = _object(value, "policy", {"policy_version", "comparison_budget", "authorization"})
    _text(policy["policy_version"], "policy_version")
    plan = validate_comparison_budget(policy["comparison_budget"])
    if plan["accounting_basis"] != "ACCOUNT_ENTITLEMENT":
        raise _invalid("Native stage budget requires ACCOUNT_ENTITLEMENT; PRICED needs an explicit monetary phase contract")
    authorization = _object(policy["authorization"], "authorization", {
        "authorization_ref", "evidence_hash", "project_id", "book_id", "authorized_cumulative_caps",
    })
    for key in ("authorization_ref", "project_id", "book_id"):
        _text(authorization[key], key)
    digest = authorization["evidence_hash"]
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise _invalid("Comparison authorization requires an exact evidence_hash")
    arm = arm_for_project(plan, authorization["project_id"])
    if authorization["book_id"] != arm["book_id"]:
        raise KernelError("CREATIVE_BUDGET_SCOPE_MISMATCH", "authorization scope differs from the frozen Book")
    caps = _object(authorization["authorized_cumulative_caps"], "authorized cumulative caps", set(PHASES))
    for phase, cap in caps.items():
        amounts = _allocation(cap, "authorized " + phase, paired=False)
        if any(amounts[key] > arm[_ALLOCATIONS[phase]][key] for key in amounts):
            raise _invalid("Comparison authorization exceeds the immutable phase opportunity")
    return deepcopy(policy)


_SOURCE_CAPABILITIES = {
    "source.content.classify": "source.content.classify",
    "deconstruction.observe": "source.deconstruction.observe",
    "mkaos.knowledge.extract": "source.mkaos.extract",
    "mkaos.rule.extract": "source.mkaos.extract",
    "mkaos.template.extract": "source.mkaos.extract",
}
_SOURCE_OPERATIONS = {
    "source.import.document.profile": {"source.content.classify"},
    "source.import.deconstruction.execute": {"deconstruction.observe"},
    "source.import.mkaos.extract": {"mkaos.knowledge.extract", "mkaos.rule.extract", "mkaos.template.extract"},
    "source.import.reprocessing.apply": {"deconstruction.observe", "mkaos.knowledge.extract", "mkaos.rule.extract", "mkaos.template.extract"},
}
_CHAPTER_STAGES = {
    "chapter.memo.generate": "memo",
    "chapter.context.retrieve": "retrieval",
    "chapter.draft.generate": "draft",
    "chapter.review.evaluate": "review",
    "chapter.revision.apply": "revision",
    "chapter.revision.review": "rereview",
    "chapter.canon.extract": "canon_extraction",
    "chapter.canon.propose_changes": "canon_support",
    "chapter.quality.structural.evaluate": "quality_structural",
    "chapter.quality.commercial.evaluate": "quality_commercial",
    "chapter.quality.source_originality.evaluate": "quality_source_originality",
    "chapter.quality.longform.evaluate": "quality_longform",
    "chapter.quality.platform.evaluate": "quality_platform",
    "reader_outcome.evaluate": "reader_outcome",
    "story_design.semantic_evaluate": "narrative_semantic_evaluation",
}
_PLANNING_CAPABILITIES = {
    "creative.candidates.generate": "creative.proposal.generate",
    "theme.candidates.generate": "theme.question.generate",
    "ending.intent.generate": "ending.intent.generate",
    "reader.promise.generate": "reader.promise.generate",
    "world.design.generate": "world.design.generate",
    "character.cast.generate": "character.cast.generate",
    "book_plan.generate": "planning.book.generate",
    "volume_plan.generate": "planning.volume.generate",
    "arc_plan.generate": "planning.arc.generate",
    "chapter_group_plan.generate": "planning.chapter_group.generate",
    "chapter_plan.generate": "planning.story_chapter.generate",
}


def classify_phase(operation_name: str, capability: str, request_payload: dict[str, Any], attempt_no: int) -> str:
    failure = KernelError("CREATIVE_BUDGET_PHASE_UNKNOWN", "Provider effect operation, capability, frozen stage or attempt is unknown or inconsistent")
    if not isinstance(operation_name, str) or not isinstance(capability, str) or not isinstance(request_payload, dict):
        raise failure
    if type(attempt_no) is not int or attempt_no < 1:
        raise failure
    stage = request_payload.get("stage")
    inputs = request_payload.get("input")
    if not isinstance(stage, str) or not isinstance(inputs, dict):
        raise failure
    if capability in _SOURCE_OPERATIONS.get(operation_name, set()):
        if stage != _SOURCE_CAPABILITIES[capability]:
            raise failure
        return "SOURCE"
    if operation_name == "provider.qualification.d0" and capability in _SOURCE_CAPABILITIES:
        if stage != "d0_qualification":
            raise failure
        return "SOURCE"
    expected_stage = _CHAPTER_STAGES.get(operation_name)
    if expected_stage:
        if stage != expected_stage or capability != "model." + expected_stage:
            raise failure
        return "REPAIR" if attempt_no > 1 or stage in {"revision", "rereview"} else "CREATION"
    if operation_name == "story_planning.generate":
        if stage in {"world_candidates.generate", "world_candidates.evaluate"}:
            if capability != "planning.story_chapter.generate" or not isinstance(inputs.get("world_preparation"), dict):
                raise failure
            return "REPAIR" if attempt_no > 1 else "CREATION"
        if capability != _PLANNING_CAPABILITIES.get(stage):
            raise failure
        command = inputs.get("planning_command")
        if not isinstance(command, dict):
            raise failure
        repair = command.get("repair_number")
        if type(repair) is not int or repair < 0:
            raise failure
        return "REPAIR" if repair > 0 or attempt_no > 1 else "CREATION"
    raise failure


__all__ = ["PHASES", "POLICY_SCHEMA", "arm_for_project", "classify_phase", "contract_hash", "validate_comparison_budget", "validate_policy"]
