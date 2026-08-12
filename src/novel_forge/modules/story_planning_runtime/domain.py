"""Pure contracts for Capability-Pack-backed Story Planning generation.

The module owns no scheduler, provider, persistence, or activation state.  It
describes the immutable inputs and candidate evidence handed between the
Command Kernel, Agent Runtime, PEP, Story Design Authority, and Hierarchical
Planning Authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from novel_forge.modules.story_design_authority import PlanningScope


_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


STORY_PLANNING_OPERATION_DEFINITION_REF = "story_planning.generate@1.1.0"
STORY_PLANNING_WORKFLOW_DEFINITION_REF = "story_planning_generators@1.1.0"
STORY_PLANNING_OPERATION_TIMEOUT_SECONDS = 600


class PlanningGenerationStatus(StrEnum):
    ADMITTED = "ADMITTED"
    EXECUTING = "EXECUTING"
    CANDIDATE_MATERIALIZED = "CANDIDATE_MATERIALIZED"
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    SEMANTICALLY_VALID = "SEMANTICALLY_VALID"
    QUALIFIED = "QUALIFIED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REJECTED = "REJECTED"


GENERATOR_SCOPE: Mapping[str, PlanningScope] = MappingProxyType(
    {
        "book_plan.generate": PlanningScope.BOOK,
        "volume_plan.generate": PlanningScope.VOLUME,
        "arc_plan.generate": PlanningScope.ARC,
        "chapter_group_plan.generate": PlanningScope.CHAPTER_GROUP,
        "chapter_plan.generate": PlanningScope.CHAPTER,
    }
)


GENERATOR_INPUT_ROLES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "book_plan.generate": (
            "book_design",
            "world_bible",
            "character_cast",
            "theme_contract",
            "ending_intent",
            "reader_promise",
            "platform_profile",
            "production_profile",
        ),
        "volume_plan.generate": (
            "book_plan",
            "previous_volume_outcome",
            "story_state",
            "canon_snapshot",
            "arc_portfolio",
            "ending_reachability",
        ),
        "arc_plan.generate": (
            "book_plan",
            "volume_plan",
            "character_arc_portfolio",
            "conflict_state",
            "promise_ledger",
            "foreshadowing_ledger",
        ),
        "chapter_group_plan.generate": (
            "book_plan",
            "volume_plan",
            "arc_plans",
            "story_state",
            "canon_snapshot",
            "previous_chapter_group_outcome",
            "quality_trend",
            "reader_state",
        ),
        "chapter_plan.generate": (
            "book_plan",
            "volume_plan",
            "arc_plans",
            "chapter_group_plan",
            "chapter_function_matrix_row",
            "previous_chapter_outcome",
            "story_state",
            "canon_snapshot",
            "quality_trend",
            "reader_state",
        ),
    }
)


@dataclass(frozen=True, slots=True)
class FrozenPlanningInput:
    role: str
    asset_version_id: str
    content_hash: str
    asset_type: str

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (self.role, self.asset_version_id, self.asset_type)
        ):
            raise ValueError("Frozen Planning input identity is incomplete")
        if not _CONTENT_HASH.fullmatch(self.content_hash):
            raise ValueError("Frozen Planning input requires a SHA-256 hash")


@dataclass(frozen=True, slots=True)
class StoryPlanningGenerationCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    generator_operation_name: str
    logical_key: str
    input_versions: Mapping[str, str]
    idempotency_key: str
    trace_id: str
    correlation_id: str
    parent_version_id: str = ""
    change_evidence_version_ids: tuple[str, ...] = ()
    repair_of_candidate_id: str = ""
    repair_reason: str = ""
    repair_number: int = 0
    auto_approve_low_risk: bool = False

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.generator_operation_name,
            self.logical_key,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Planning Generation command is incomplete")
        if self.generator_operation_name not in GENERATOR_SCOPE:
            raise ValueError("Planning Generator is not supported")
        normalized = {
            str(role): str(version)
            for role, version in dict(self.input_versions).items()
        }
        expected = set(GENERATOR_INPUT_ROLES[self.generator_operation_name])
        if set(normalized) != expected or any(not item for item in normalized.values()):
            missing = sorted(expected - set(normalized))
            extra = sorted(set(normalized) - expected)
            raise ValueError(
                "Planning Generation inputs must match the Authority role set; "
                f"missing={missing}, extra={extra}"
            )
        if bool(self.repair_of_candidate_id) != bool(self.repair_reason):
            raise ValueError("Planning repair identity and reason must be paired")
        if self.repair_number < 0 or bool(self.repair_number) != bool(
            self.repair_of_candidate_id
        ):
            raise ValueError("Planning repair number must match repair identity")
        change_evidence = tuple(
            str(asset_version_id).strip()
            for asset_version_id in self.change_evidence_version_ids
        )
        if (
            any(not asset_version_id for asset_version_id in change_evidence)
            or len(set(change_evidence)) != len(change_evidence)
            or set(change_evidence) & set(normalized.values())
        ):
            raise ValueError("Planning change evidence identity is invalid")
        object.__setattr__(self, "input_versions", MappingProxyType(normalized))
        object.__setattr__(self, "change_evidence_version_ids", change_evidence)

    @property
    def planning_scope(self) -> PlanningScope:
        return GENERATOR_SCOPE[self.generator_operation_name]


@dataclass(frozen=True, slots=True)
class PlanningExecutionEvidence:
    operation_id: str
    attempt_id: str
    fencing_token: int
    route_snapshot_id: str
    input_manifest_ref: str
    output_manifest_ref: str
    validation_manifest_ref: str
    usage_receipt_ref: str
    cost_receipt_ref: str
    external_receipt_ref: str
    capability_pack_attempt_snapshot_id: str
    capability_pack_attempt_snapshot_hash: str
    agent_work_order_ref: str
    agent_work_order_hash: str
    agent_runtime_binding_ref: str
    agent_runtime_binding_hash: str
    commit_authority: str
    fixture_protocol_only: bool
    real_provider_proven: bool = False
    production_verified: bool = False

    def __post_init__(self) -> None:
        required = tuple(
            value
            for name, value in asdict(self).items()
            if name
            not in {
                "fencing_token",
                "fixture_protocol_only",
                "real_provider_proven",
                "production_verified",
            }
            and not name.endswith("_hash")
        )
        if self.fencing_token <= 0 or any(not str(value).strip() for value in required):
            raise ValueError("Planning execution evidence is incomplete")
        for name in (
            "capability_pack_attempt_snapshot_hash",
            "agent_work_order_hash",
            "agent_runtime_binding_hash",
        ):
            if not _CONTENT_HASH.fullmatch(str(getattr(self, name))):
                raise ValueError(f"{name} must be a SHA-256 content hash")
        if self.commit_authority not in {
            "BOOK_DESIGN_AUTHORITY",
            "STORY_DESIGN_AUTHORITY",
            "HIERARCHICAL_PLANNING_AUTHORITY",
            "CHAPTER_AUTHORITY",
            "READER_JUDGE_AUTHORITY",
            "PLAN_CHANGE_AUTHORITY",
        }:
            raise ValueError("Planning execution commit authority is not allowed")
        if self.production_verified and not self.real_provider_proven:
            raise ValueError("production verification cannot exceed provider evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "production_execution_gateway_backed": True,
            "external_effect_backed": True,
        }


@dataclass(frozen=True, slots=True)
class PlanningGenerationCandidate:
    generator_operation_name: str
    planning_scope: PlanningScope
    logical_key: str
    candidate_payload: Mapping[str, Any]
    frozen_inputs: tuple[FrozenPlanningInput, ...]
    evidence: PlanningExecutionEvidence

    def __post_init__(self) -> None:
        scope = PlanningScope(self.planning_scope)
        object.__setattr__(self, "planning_scope", scope)
        if GENERATOR_SCOPE.get(self.generator_operation_name) is not scope:
            raise ValueError(
                "Planning candidate scope differs from GeneratorDefinition"
            )
        if not self.logical_key.strip() or not dict(self.candidate_payload):
            raise ValueError("Planning candidate content is empty")
        if not str(self.candidate_payload.get("objective") or "").strip():
            raise ValueError("Planning candidate requires an objective")
        expected = set(GENERATOR_INPUT_ROLES[self.generator_operation_name])
        roles = {item.role for item in self.frozen_inputs}
        if roles != expected or len(roles) != len(self.frozen_inputs):
            raise ValueError("Planning candidate input snapshot is incomplete")
        object.__setattr__(
            self,
            "candidate_payload",
            MappingProxyType(dict(self.candidate_payload)),
        )

    def authority_content(
        self,
        *,
        project_id: str,
        book_id: str,
        constraint_envelope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(self.candidate_payload)
        envelope = dict(constraint_envelope or {})
        if envelope:
            payload["constraint_envelope"] = envelope
        return {
            **payload,
            "schema_version": "story_design.authority.v1",
            "type": "PlanningGenerationCandidate",
            "project_id": project_id,
            "book_id": book_id,
            "generator_operation_name": self.generator_operation_name,
            "planning_scope": self.planning_scope.value,
            "logical_key": self.logical_key,
            "candidate_payload": payload,
            "frozen_inputs": [asdict(item) for item in self.frozen_inputs],
            "constraint_envelope": envelope,
            "execution_evidence": self.evidence.to_dict(),
        }


def build_planning_constraint_envelope(
    *,
    generator_operation_name: str,
    frozen_inputs: tuple[FrozenPlanningInput, ...],
    input_contents: Mapping[str, Mapping[str, Any]],
    candidate_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile immutable parent constraints for validation and downstream execution."""
    if generator_operation_name not in GENERATOR_SCOPE:
        raise ValueError("Planning Generator is not supported")
    expected_roles = set(GENERATOR_INPUT_ROLES[generator_operation_name])
    if set(input_contents) != expected_roles:
        raise ValueError("Planning constraint inputs must match frozen Authority roles")
    by_role = {item.role: item for item in frozen_inputs}
    if set(by_role) != expected_roles:
        raise ValueError("Planning constraint input versions are incomplete")

    inherited: list[dict[str, Any]] = []
    prohibited: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    accepted_through = 0
    for role in sorted(expected_roles):
        content = dict(input_contents[role])
        source_version = by_role[role].asset_version_id
        for field in ("invariants", "story_constraints", "constraints"):
            inherited.extend(
                _constraint_records(content.get(field), role, source_version, field)
            )
        prohibited.extend(
            _constraint_records(
                content.get("prohibited_outcomes"),
                role,
                source_version,
                "prohibited_outcomes",
            )
        )
        obligations.extend(
            _constraint_records(
                content.get("required_obligation_ids")
                or content.get("unresolved_obligation_ids"),
                role,
                source_version,
                "required_obligation_ids",
            )
        )
        boundary = content.get("authority_state_boundary")
        accepted_through = max(
            accepted_through,
            int(content.get("accepted_through_chapter") or 0),
            int(boundary.get("accepted_through_chapter") or 0)
            if isinstance(boundary, dict)
            else 0,
        )

    local_prohibited = _constraint_records(
        candidate_payload.get("prohibited_outcomes"),
        "candidate",
        "UNMATERIALIZED_CANDIDATE",
        "prohibited_outcomes",
    )
    body = {
        "type": "PlanningConstraintEnvelope",
        "contract_version": "planning-constraint-envelope-v1",
        "generator_operation_name": generator_operation_name,
        "planning_scope": GENERATOR_SCOPE[generator_operation_name].value,
        "permitted_change_scope": GENERATOR_SCOPE[generator_operation_name].value,
        "accepted_state_boundary": {
            "accepted_through_chapter": accepted_through,
            "future_plan_only": True,
        },
        "parent_versions": [
            {
                "role": role,
                "asset_version_id": by_role[role].asset_version_id,
                "content_hash": by_role[role].content_hash,
            }
            for role in sorted(by_role)
        ],
        "inherited_invariants": inherited,
        "prohibited_outcomes": [*prohibited, *local_prohibited],
        "required_obligations": obligations,
        "change_governance": {
            "requires_evidence": True,
            "wider_scope_requires_new_plan_change": True,
            "preserve_executed_history": True,
        },
    }
    return {**body, "envelope_digest": canonical_hash(body)}


def _constraint_records(
    value: Any,
    source_role: str,
    source_version: str,
    field: str,
) -> list[dict[str, Any]]:
    if value in (None, "", [], {}):
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    return [
        {
            "source_role": source_role,
            "source_asset_version_id": source_version,
            "source_field": field,
            "constraint": item,
        }
        for item in items
    ]


@dataclass(frozen=True, slots=True)
class PlanningValidationReport:
    candidate_asset_version_id: str
    validation_kind: str
    status: str
    report: Mapping[str, Any]

    @property
    def report_hash(self) -> str:
        return _hash(
            {
                "candidate_asset_version_id": self.candidate_asset_version_id,
                "validation_kind": self.validation_kind,
                "status": self.status,
                "report": dict(self.report),
            }
        )


@dataclass(frozen=True, slots=True)
class PlanningRepairRequest:
    original_candidate_asset_version_id: str
    validation_report_hash: str
    reason: str
    repair_number: int

    def __post_init__(self) -> None:
        if (
            not self.original_candidate_asset_version_id
            or not _CONTENT_HASH.fullmatch(self.validation_report_hash)
            or not self.reason.strip()
            or self.repair_number <= 0
        ):
            raise ValueError("Planning repair request is incomplete")


@dataclass(frozen=True, slots=True)
class PlanningGenerationResult:
    generation_operation_id: str
    candidate_asset_version_id: str
    status: PlanningGenerationStatus
    story_design_state: Mapping[str, Any]
    planning_binding: Mapping[str, Any] | None = None
    replayed: bool = False


def canonical_hash(value: Any) -> str:
    return _hash(value)


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "GENERATOR_INPUT_ROLES",
    "GENERATOR_SCOPE",
    "FrozenPlanningInput",
    "PlanningExecutionEvidence",
    "PlanningGenerationCandidate",
    "PlanningGenerationResult",
    "PlanningGenerationStatus",
    "PlanningRepairRequest",
    "PlanningValidationReport",
    "StoryPlanningGenerationCommand",
    "build_planning_constraint_envelope",
    "canonical_hash",
]
