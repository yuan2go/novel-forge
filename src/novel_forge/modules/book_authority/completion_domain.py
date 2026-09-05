from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import _validate_json_schema


COMPLETION_SCHEMA = "book-completion-case.v1"
COMPLETION_REVIEW_SCHEMA = "whole-book-closure-review.v1"
CLOSURE_DIMENSIONS = ("ending", "reader_promise", "theme", "character", "relationship")
EVIDENCE_DIMENSIONS = (
    "ENGINEERING",
    "NARRATIVE_CORRECTNESS",
    "HUMAN_EDITORIAL",
    "READER_EVIDENCE",
    "LONGITUDINAL_STABILITY",
    "PRODUCTION_EVIDENCE",
)


def validate_completion_contract(schema: dict[str, Any], value: Any, path: str) -> None:
    _validate_json_schema(schema, value, path)
    invalid = (
        (schema.get("type") == "integer" and type(value) is not int)
        or ("enum" in schema and value not in schema["enum"])
        or ("minimum" in schema and value < schema["minimum"])
        or ("minLength" in schema and len(value.strip()) < schema["minLength"])
        or ("pattern" in schema and re.fullmatch(schema["pattern"], value) is None)
    )
    if invalid:
        raise KernelError(
            "BOOK_COMPLETION_SCHEMA_INVALID", f"{path} violates the completion contract"
        )
    if schema.get("type") == "object":
        for key, item in value.items():
            validate_completion_contract(
                schema["properties"][key], item, path + "." + key
            )
    if schema.get("type") == "array":
        if schema.get("uniqueItems") and len(
            {completion_digest(item) for item in value}
        ) != len(value):
            raise KernelError(
                "BOOK_COMPLETION_SCHEMA_INVALID", f"{path} requires distinct references"
            )
        for index, item in enumerate(value):
            validate_completion_contract(schema["items"], item, f"{path}[{index}]")


def completion_result_schema(action: str) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    references = {"type": "array", "items": text, "uniqueItems": True}
    dimensions = {
        "type": "object",
        "properties": {
            name: {
                "type": "string",
                "enum": ["SUPPORTING_ONLY", "FAIL"]
                if name == "NARRATIVE_CORRECTNESS"
                else ["WAITING_EVIDENCE"]
                if name == "HUMAN_EDITORIAL"
                else ["NOT_PROVEN"],
            }
            for name in EVIDENCE_DIMENSIONS
        },
        "required": list(EVIDENCE_DIMENSIONS),
        "additionalProperties": False,
    }
    properties = {
        "case_id": text,
        "book_run_id": text,
        "source_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "blockers": references,
        "evidence_dimensions": dimensions,
        "accepted_history_mutation_allowed": {"type": "boolean", "enum": [False]},
    }
    if action == "assess":
        properties.update(
            {
                "schema_version": {"type": "string", "enum": [COMPLETION_SCHEMA]},
                "case_version": {"type": "integer", "minimum": 1},
                "accepted_through": {"type": "integer", "minimum": 0},
                "status": {
                    "type": "string",
                    "enum": ["NEEDS_REMEDIATION", "READY_FOR_EDITORIAL"],
                },
                **{
                    name: references
                    for name in (
                        "acceptance_ids",
                        "outcome_version_ids",
                        "arc_ids",
                        "obligation_ids",
                    )
                },
                "proof_ceiling": {
                    "type": "string",
                    "enum": ["ACCEPTED_HISTORY_CLOSURE_CONTRACT"],
                },
                "acceptance_policy_status": {
                    "type": "string",
                    "enum": ["DESIGN_REVIEW_REQUIRED"],
                },
            }
        )
    elif action == "decide":
        properties.update(
            {
                "schema_version": {
                    "type": "string",
                    "enum": ["book-completion-decision.v1"],
                },
                "decision_id": text,
                "decision_version": {"type": "integer", "minimum": 1},
                "requested_decision": {
                    "type": "string",
                    "enum": ["ACCEPTED", "REJECTED"],
                },
                "status": {"type": "string", "enum": ["BLOCKED", "REJECTED"]},
                "rationale": text,
                "recovery_instruction": text,
            }
        )
    else:
        raise ValueError("unsupported completion action")
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def completion_digest(value: Any) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CompletionAssessment:
    source_digest: str
    accepted_through: int
    blockers: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    outcome_version_ids: tuple[str, ...]
    arc_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMPLETION_SCHEMA,
            "source_digest": self.source_digest,
            "accepted_through": self.accepted_through,
            "status": "NEEDS_REMEDIATION" if self.blockers else "READY_FOR_EDITORIAL",
            "blockers": list(self.blockers),
            "acceptance_ids": list(self.acceptance_ids),
            "outcome_version_ids": list(self.outcome_version_ids),
            "arc_ids": list(self.arc_ids),
            "obligation_ids": list(self.obligation_ids),
            "evidence_dimensions": {
                name: ("FAIL" if self.blockers else "SUPPORTING_ONLY")
                if name == "NARRATIVE_CORRECTNESS"
                else ("WAITING_EVIDENCE" if name == "HUMAN_EDITORIAL" else "NOT_PROVEN")
                for name in EVIDENCE_DIMENSIONS
            },
            "accepted_history_mutation_allowed": False,
            "proof_ceiling": "ACCEPTED_HISTORY_CLOSURE_CONTRACT",
            "acceptance_policy_status": "DESIGN_REVIEW_REQUIRED",
        }


def assess_completion(
    book: Mapping[str, Any], accepted: Sequence[Mapping[str, Any]]
) -> CompletionAssessment:
    target = int(book["target_chapter_count"])
    if target <= 0:
        raise KernelError(
            "BOOK_COMPLETION_SCOPE_INVALID",
            "completion requires a positive terminal boundary",
        )
    blockers: list[str] = []
    if book["state"] != "COMPLETED" or int(book["accepted_through_chapter"]) != target:
        blockers.append("PRODUCTION_CURSOR_NOT_TERMINAL")
    numbers = [int(row["chapter_number"]) for row in accepted]
    if numbers != list(range(1, target + 1)):
        blockers.append("ACCEPTED_HISTORY_INCOMPLETE")
    arcs: dict[str, dict[str, Any]] = {}
    obligations: dict[str, dict[str, Any]] = {}
    identities: list[dict[str, Any]] = []
    for row in accepted:
        if row.get("source_eligible") is not True:
            blockers.append("ACCEPTED_SOURCE_NOT_ELIGIBLE")
        if (
            row["acceptance_status"] != "COMMITTED"
            or row["projection_status"] != "COMPLETE"
        ):
            blockers.append("ACCEPTED_PROJECTION_INCOMPLETE")
        if row["projection_set_id"] != row["acceptance_projection_set_id"]:
            blockers.append("ACCEPTED_PROJECTION_IDENTITY_DRIFT")
        for name in ("outcome", "story_state", "canon"):
            if row[f"{name}_version_id"] != row[f"projection_{name}_version_id"]:
                blockers.append("ACCEPTED_SOURCE_IDENTITY_DRIFT")
        if any(
            not row.get(name)
            for name in (
                "projection_hash",
                "outcome_hash",
                "story_state_hash",
                "canon_hash",
            )
        ):
            blockers.append("ACCEPTED_SOURCE_DIGEST_MISSING")
        for state in row.get("arc_state") or ():
            arcs[str(state["arc_plan_version_id"])] = dict(state)
        for entry in row.get("obligation_state") or ():
            state = dict(entry.get("state") or entry)
            obligation_id = str(
                state.get("obligation_id") or entry.get("entity_key") or ""
            )
            if not obligation_id:
                blockers.append("OBLIGATION_IDENTITY_MISSING")
            else:
                obligations[obligation_id] = state
        identities.append(dict(row))
    if not arcs:
        blockers.append("TRAJECTORY_CLOSURE_NOT_OBSERVED")
    for arc_id in book.get("required_arc_plan_version_ids") or ():
        if arc_id not in arcs:
            blockers.append("REQUIRED_TRAJECTORY_NOT_OBSERVED:" + arc_id)
    for arc_id, state in sorted(arcs.items()):
        if (
            state.get("observation_status") != "OBSERVED"
            or state.get("lifecycle_status") != "COMPLETED"
        ):
            blockers.append("TRAJECTORY_NOT_CLOSED:" + arc_id)
    for obligation_id, state in sorted(obligations.items()):
        if state.get("status") != "FULFILLED" or not (
            state.get("payoff_evidence")
            or state.get("actual_payoff")
            or state.get("resolution_evidence")
        ):
            blockers.append("OBLIGATION_NOT_RESOLVED:" + obligation_id)
    return CompletionAssessment(
        source_digest=completion_digest({"book": dict(book), "accepted": identities}),
        accepted_through=int(book["accepted_through_chapter"]),
        blockers=tuple(sorted(set(blockers))),
        acceptance_ids=tuple(str(row["acceptance_id"]) for row in accepted),
        outcome_version_ids=tuple(str(row["outcome_version_id"]) for row in accepted),
        arc_ids=tuple(sorted(arcs)),
        obligation_ids=tuple(sorted(obligations)),
    )


def require_completion_review(
    assessment: Mapping[str, Any], review: Mapping[str, Any]
) -> None:
    if assessment["status"] != "READY_FOR_EDITORIAL":
        raise KernelError(
            "BOOK_COMPLETION_BLOCKED",
            "unresolved accepted-history defects block completion",
        )
    if review.get("schema_version") != COMPLETION_REVIEW_SCHEMA:
        raise KernelError(
            "BOOK_COMPLETION_REVIEW_REQUIRED",
            "whole-book closure requires typed independent review",
        )
    if (
        review.get("source_digest") != assessment["source_digest"]
        or review.get("source_acceptance_ids") != assessment["acceptance_ids"]
    ):
        raise KernelError(
            "BOOK_COMPLETION_REVIEW_STALE",
            "review must bind the complete frozen accepted history",
        )
    if review.get("blocking_issues") != []:
        raise KernelError(
            "BOOK_COMPLETION_REVIEW_BLOCKED",
            "unresolved review issues block whole-book acceptance",
        )
    findings = review.get("findings")
    if not isinstance(findings, dict) or set(findings) != set(CLOSURE_DIMENSIONS):
        raise KernelError(
            "BOOK_COMPLETION_REVIEW_INCOMPLETE",
            "review must cover every whole-book closure dimension",
        )
    sources = set(assessment["acceptance_ids"])
    for dimension, finding in findings.items():
        if (
            not isinstance(finding, dict)
            or finding.get("status") != "SATISFIED"
            or not finding.get("acceptance_refs")
            or not set(finding["acceptance_refs"]) <= sources
            or not str(finding.get("rationale") or "").strip()
        ):
            raise KernelError(
                "BOOK_COMPLETION_DIMENSION_UNPROVEN",
                dimension + " lacks accepted closure evidence",
            )
