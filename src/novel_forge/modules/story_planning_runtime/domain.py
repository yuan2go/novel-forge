from __future__ import annotations

from .foundation_generation import FOUNDATION_GENERATORS, FOUNDATION_INPUT_ROLES, foundation_envelope, normalize_foundation_payload

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from novel_forge.modules.story_design_authority import PlanningScope
from novel_forge.modules.narrative_state.measurements import project_narrative_load


_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


STORY_PLANNING_OPERATION_DEFINITION_REF = "story_planning.generate@1.14.0"
STORY_PLANNING_WORKFLOW_DEFINITION_REF = "story_planning_generators@1.12.0"
STORY_PLANNING_OPERATION_TIMEOUT_SECONDS = 1_800
STORY_PLANNING_MAX_ATTEMPTS = 3

CHAPTER_SCHEDULE_FIELDS = (
    "primary_function",
    "secondary_functions",
    "required_state_delta",
    "promise_action",
    "foreshadow_action",
    "reward_action",
    "ending_hook",
    "prohibited_outcomes",
    "narrative_density",
)
CHAPTER_READER_SCHEDULE_FIELDS = ("target_emotion", "reward_mode")

NARRATIVE_LOAD_LIMIT_FIELDS = (
    "max_active_arcs",
    "max_dormant_arc_age",
    "max_open_obligations",
    "max_overdue_obligations",
    "max_payoff_congestion",
    "max_character_appearance_gap",
    "max_new_concepts",
    "max_major_state_transitions",
)
DEFAULT_NARRATIVE_LOAD_LIMITS: Mapping[str, int] = MappingProxyType(
    {
        "max_active_arcs": 3,
        "max_dormant_arc_age": 30,
        "max_open_obligations": 12,
        "max_overdue_obligations": 0,
        "max_payoff_congestion": 3,
        "max_character_appearance_gap": 10,
        "max_new_concepts": 4,
        "max_major_state_transitions": 8,
    }
)


def canonical_book_volume_allocation(
    book_plan: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], ...], int]:

    raw = book_plan.get("volume_skeleton")
    target_value = (book_plan.get("length_strategy") or {}).get("target_chapters")
    if (
        not isinstance(raw, list)
        or not raw
        or not isinstance(target_value, int)
        or isinstance(target_value, bool)
        or target_value <= 0
    ):
        raise ValueError("Book Plan requires a Volume skeleton and chapter target")
    target = int(target_value)
    skeleton: list[dict[str, Any]] = []
    for ordinal, item in enumerate(raw, start=1):
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("volume"), int)
            or isinstance(item.get("volume"), bool)
            or int(item["volume"]) != ordinal
        ):
            raise ValueError("Volume skeleton ordinals must be contiguous")
        skeleton.append(dict(item))
    if target < len(skeleton):
        raise ValueError("Book target cannot be shorter than its Volume skeleton")

    supplied_ranges = [item.get("chapter_range") for item in skeleton]
    if any(value is not None for value in supplied_ranges):
        if not all(value is not None for value in supplied_ranges):
            raise ValueError("Volume skeleton ranges must be complete")
        previous_end = 0
        for item in skeleton:
            value = item["chapter_range"]
            if (
                not isinstance(value, list)
                or len(value) != 2
                or any(
                    not isinstance(chapter, int) or isinstance(chapter, bool)
                    for chapter in value
                )
                or value[0] != previous_end + 1
                or value[1] < value[0]
            ):
                raise ValueError("Volume skeleton ranges must be contiguous")
            item["chapter_range"] = [int(value[0]), int(value[1])]
            previous_end = int(value[1])
        if previous_end != target:
            raise ValueError("Volume skeleton must exactly cover the Book target")
        return tuple(skeleton), target

    base_size, larger_prefix = divmod(target, len(skeleton))
    next_chapter = 1
    for ordinal, item in enumerate(skeleton, start=1):
        volume_size = base_size + (1 if ordinal <= larger_prefix else 0)
        final_chapter = next_chapter + volume_size - 1
        item["chapter_range"] = [next_chapter, final_chapter]
        next_chapter = final_chapter + 1
    return tuple(skeleton), target


class PlanningGenerationStatus(StrEnum):
    ADMITTED = "ADMITTED"
    EXECUTING = "EXECUTING"
    CANDIDATE_MATERIALIZED = "CANDIDATE_MATERIALIZED"
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    EVALUATION_PENDING = "EVALUATION_PENDING"
    SEMANTICALLY_VALID = "SEMANTICALLY_VALID"
    QUALIFIED = "QUALIFIED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REJECTED = "REJECTED"




GENERATOR_SCOPE: Mapping[str, PlanningScope] = MappingProxyType(
    {
        **{name: PlanningScope.NOT_APPLICABLE for name in FOUNDATION_GENERATORS},
        "book_plan.generate": PlanningScope.BOOK,
        "volume_plan.generate": PlanningScope.VOLUME,
        "arc_plan.generate": PlanningScope.ARC,
        "chapter_group_plan.generate": PlanningScope.CHAPTER_GROUP,
        "chapter_plan.generate": PlanningScope.CHAPTER,
    }
)


GENERATOR_INPUT_ROLES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        **FOUNDATION_INPUT_ROLES,
        "book_plan.generate": (
            "creative_foundation",
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


def _json_object_snapshot(
    value: Mapping[str, Any] | None, label: str
) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        snapshot = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a JSON object") from exc
    if not isinstance(snapshot, dict):
        raise ValueError(f"{label} must be a JSON object")
    return snapshot


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
    arc_scope_volume_plan_version_ids: tuple[str, ...] = ()
    related_arc_plan_version_ids: tuple[str, ...] = ()
    dependent_arc_plan_version_ids: tuple[str, ...] = ()
    change_evidence_version_ids: tuple[str, ...] = ()
    governance_action_version_ids: tuple[str, ...] = ()
    repair_of_candidate_id: str = ""
    repair_reason: str = ""
    repair_number: int = 0
    auto_approve_low_risk: bool = False
    parent_agent_session_operation_id: str = ""
    arc_working_set: Mapping[str, Any] | None = None
    narrative_search_id: str = ""
    narrative_search_branch_key: str = ""
    narrative_search_parent_state_asset_version_id: str = ""
    narrative_search_accepted_through_chapter: int = 0
    narrative_search_strategy_directive: str = ""
    narrative_search_planning_horizon: Mapping[str, Any] | None = None
    narrative_search_desired_transformation: Mapping[str, Any] | None = None
    narrative_search_hard_constraints: tuple[str, ...] = ()
    narrative_realization: Mapping[str, Any] | None = None
    opening_execution_binding: Mapping[str, Any] | None = None
    world_preparation_request: Mapping[str, Any] | None = None
    execution_contract_version: str = "1.14.0"

    def __post_init__(self) -> None:
        if self.execution_contract_version not in {"1.11.0", "1.12.0", "1.13.0", "1.14.0"} or (
            self.execution_contract_version == "1.11.0"
            and self.world_preparation_request
        ):
            raise ValueError(
                "historical Planning commands cannot acquire new world stages"
            )
        if self.generator_operation_name in FOUNDATION_GENERATORS and self.execution_contract_version != "1.14.0":
            raise ValueError("Foundation generation requires its current frozen execution contract")
        if self.world_preparation_request:
            from novel_forge.modules.worldbuilding.dynamics import (
                require_contract_fields,
            )

            require_contract_fields(
                self.world_preparation_request,
                required={
                    "book_run_id",
                    "input_snapshot_id",
                    "accepted_through_chapter",
                    "story_state_version_id",
                    "canon_version_id",
                },
                optional={"planning_input_refs"},
            )
            if (
                self.generator_operation_name != "chapter_plan.generate"
                or not self.world_preparation_request["book_run_id"]
                or not self.world_preparation_request["input_snapshot_id"]
            ):
                raise ValueError(
                    "world preparation belongs to native Book Chapter planning"
                )
            object.__setattr__(
                self,
                "world_preparation_request",
                _json_object_snapshot(
                    self.world_preparation_request, "world_preparation_request"
                ),
            )
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
        realization = dict(self.narrative_realization or {})
        if self.generator_operation_name == "chapter_plan.generate":
            expected_realization_fields = {
                "realization_id",
                "contract_digest",
                "chapter_group_plan_version_id",
                "chapter_group_content_hash",
                "slice_id",
                "chapter_number",
                "event_ids",
                "events",
                "foundation_set_digest",
                "accepted_through_chapter",
                "arc_working_set_digest",
                "proof_asset_version_id",
                "proof_hash",
            }
            if (
                set(realization) != expected_realization_fields
                or int(realization.get("chapter_number") or 0) <= 0
                or (
                    not isinstance(realization.get("accepted_through_chapter"), int)
                    or isinstance(realization.get("accepted_through_chapter"), bool)
                    or int(realization["accepted_through_chapter"]) < 0
                )
                or any(
                    not str(realization.get(field) or "").startswith("sha256:")
                    for field in (
                        "contract_digest",
                        "chapter_group_content_hash",
                        "foundation_set_digest",
                        "arc_working_set_digest",
                        "proof_hash",
                    )
                )
                or not isinstance(realization.get("event_ids"), list)
                or not realization.get("event_ids")
                or not isinstance(realization.get("events"), list)
                or len(realization["events"]) != len(realization["event_ids"])
            ):
                raise ValueError(
                    "ChapterPlan Generation requires one exact Frozen Narrative Realization slice"
                )
        elif realization:
            raise ValueError(
                "Narrative Realization is a Chapter elaboration contract, not a Planning scale"
            )
        opening_binding = dict(self.opening_execution_binding or {})
        if opening_binding:
            expected_binding_fields = {
                "opening_run_id",
                "opening_execution_id",
                "opening_execution_generation",
                "runtime_job_id",
                "runtime_attempt_id",
                "runtime_lease_id",
                "runtime_worker_id",
                "runtime_fencing_token",
            }
            if (
                set(opening_binding) != expected_binding_fields
                or any(
                    not str(opening_binding.get(field) or "").strip()
                    for field in expected_binding_fields
                    if field
                    not in {
                        "opening_execution_generation",
                        "runtime_fencing_token",
                    }
                )
                or int(opening_binding.get("opening_execution_generation") or 0) <= 0
                or int(opening_binding.get("runtime_fencing_token") or 0) <= 0
            ):
                raise ValueError(
                    "Opening Planning Generation requires one exact execution fence"
                )
            object.__setattr__(self, "opening_execution_binding", opening_binding)
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
        governance_actions = tuple(
            str(asset_version_id).strip()
            for asset_version_id in self.governance_action_version_ids
        )
        if (
            any(not asset_version_id for asset_version_id in governance_actions)
            or len(set(governance_actions)) != len(governance_actions)
            or set(governance_actions) & set(normalized.values())
            or set(governance_actions) & set(change_evidence)
        ):
            raise ValueError("Narrative governance action identity is invalid")
        arc_scope = tuple(
            str(asset_version_id).strip()
            for asset_version_id in self.arc_scope_volume_plan_version_ids
        )
        if self.generator_operation_name != "arc_plan.generate" and arc_scope:
            raise ValueError("only Arc generation may freeze a cross-Volume scope")
        primary_volume = normalized.get("volume_plan", "")
        if (
            any(not asset_version_id for asset_version_id in arc_scope)
            or len(set(arc_scope)) != len(arc_scope)
            or primary_volume in arc_scope
            or set(arc_scope) & set(normalized.values())
        ):
            raise ValueError("Arc cross-Volume scope identity is invalid")
        related_arcs = tuple(
            str(asset_version_id).strip()
            for asset_version_id in self.related_arc_plan_version_ids
        )
        if (
            self.generator_operation_name
            not in {
                "arc_plan.generate",
                "chapter_group_plan.generate",
                "chapter_plan.generate",
            }
            and related_arcs
        ):
            raise ValueError(
                "only Arc, Scheduling, or Chapter generation may freeze related Arcs"
            )
        primary_arc = normalized.get("arc_plans", "")
        if (
            any(not asset_version_id for asset_version_id in related_arcs)
            or len(set(related_arcs)) != len(related_arcs)
            or primary_arc in related_arcs
            or set(related_arcs) & set(normalized.values())
            or set(related_arcs) & set(arc_scope)
        ):
            raise ValueError("related Arc portfolio identity is invalid")
        dependent_arcs = tuple(
            str(asset_version_id).strip()
            for asset_version_id in self.dependent_arc_plan_version_ids
        )
        if self.generator_operation_name != "arc_plan.generate" and dependent_arcs:
            raise ValueError("only Arc generation may freeze dependent Arcs")
        if (
            any(not asset_version_id for asset_version_id in dependent_arcs)
            or len(set(dependent_arcs)) != len(dependent_arcs)
            or set(dependent_arcs) & set(normalized.values())
            or set(dependent_arcs) & set(arc_scope)
            or set(dependent_arcs) & set(related_arcs)
        ):
            raise ValueError("dependent Arc portfolio identity is invalid")
        object.__setattr__(self, "input_versions", MappingProxyType(normalized))
        object.__setattr__(self, "arc_scope_volume_plan_version_ids", arc_scope)
        object.__setattr__(self, "related_arc_plan_version_ids", related_arcs)
        object.__setattr__(self, "dependent_arc_plan_version_ids", dependent_arcs)
        object.__setattr__(self, "change_evidence_version_ids", change_evidence)
        object.__setattr__(self, "governance_action_version_ids", governance_actions)
        working_set = dict(self.arc_working_set or {})
        if working_set:
            body = {
                key: value
                for key, value in working_set.items()
                if key != "working_set_digest"
            }
            selected = [
                str(item.get("arc_plan_version_id") or "")
                for item in working_set.get("selected_contributions") or ()
                if isinstance(item, Mapping)
            ]
            frozen_arcs = [primary_arc, *related_arcs]
            if (
                self.generator_operation_name
                not in {"chapter_group_plan.generate", "chapter_plan.generate"}
                or working_set.get("contract_version") != "arc-working-set-v1"
                or working_set.get("project_id") != self.project_id
                or working_set.get("book_id") != self.book_id
                or int(working_set.get("target_chapter") or 0) <= 0
                or working_set.get("working_set_digest") != canonical_hash(body)
                or not selected
                or selected != frozen_arcs
            ):
                raise ValueError(
                    "Planning Arc Working Set must exactly bind the frozen bounded Arc portfolio"
                )
        object.__setattr__(
            self,
            "arc_working_set",
            MappingProxyType(working_set) if working_set else None,
        )
        if self.parent_agent_session_operation_id and self.repair_of_candidate_id:
            raise ValueError(
                "Planning generation cannot have both repair and Agent parent causation"
            )
        search_values = (
            self.narrative_search_id,
            self.narrative_search_branch_key,
            self.narrative_search_strategy_directive,
        )
        search_horizon = _json_object_snapshot(
            self.narrative_search_planning_horizon,
            "Narrative Search planning horizon",
        )
        desired_transformation = _json_object_snapshot(
            self.narrative_search_desired_transformation,
            "Narrative Search desired transformation",
        )
        hard_constraints = tuple(
            str(item).strip() for item in self.narrative_search_hard_constraints
        )
        if any(not item for item in hard_constraints) or len(
            set(hard_constraints)
        ) != len(hard_constraints):
            raise ValueError("Narrative Search hard constraints are invalid")
        if any(search_values) and not all(str(item).strip() for item in search_values):
            raise ValueError("Narrative Search identity and strategy must be complete")
        if self.narrative_search_id:
            if self.generator_operation_name == "chapter_plan.generate":
                raise ValueError("Chapter planning is operational, not a Search scope")
            if self.auto_approve_low_risk:
                raise ValueError(
                    "Narrative Search candidates must stop before approval/activation"
                )
            if self.narrative_search_accepted_through_chapter < 0:
                raise ValueError(
                    "Narrative Search accepted boundary cannot be negative"
                )
            if (
                self.narrative_search_accepted_through_chapter > 0
                and not self.narrative_search_parent_state_asset_version_id
            ):
                raise ValueError(
                    "continuing Narrative Search requires exact accepted parent state"
                )
            if not search_horizon or not desired_transformation or not hard_constraints:
                raise ValueError(
                    "Narrative Search command requires its complete frozen request"
                )
            if self.generator_operation_name == "chapter_group_plan.generate":
                chapter_range = search_horizon.get("chapter_range")
                if (
                    search_horizon.get("level") != "CHAPTER_GROUP"
                    or not isinstance(chapter_range, list)
                    or len(chapter_range) != 2
                    or any(
                        not isinstance(item, int) or isinstance(item, bool)
                        for item in chapter_range
                    )
                ):
                    raise ValueError(
                        "ChapterGroup Narrative Search requires an exact frozen chapter range"
                    )
                start, end = chapter_range
                if (
                    start <= self.narrative_search_accepted_through_chapter
                    or start <= 0
                    or end < start
                    or search_horizon.get("starts_at_chapter") != start
                    or search_horizon.get("ends_at_chapter") != end
                ):
                    raise ValueError(
                        "ChapterGroup Narrative Search horizon is inconsistent"
                    )
            if self.generator_operation_name == "volume_plan.generate":
                chapter_range = search_horizon.get("chapter_range")
                if chapter_range is not None and (
                    search_horizon.get("level") != "VOLUME"
                    or not isinstance(chapter_range, list)
                    or len(chapter_range) != 2
                    or any(
                        not isinstance(item, int) or isinstance(item, bool)
                        for item in chapter_range
                    )
                ):
                    raise ValueError(
                        "Volume Narrative Search requires an exact frozen chapter range"
                    )
                if chapter_range is not None:
                    start, end = chapter_range
                    if (
                        start <= 0
                        or end < start
                        or self.narrative_search_accepted_through_chapter != 0
                        or search_horizon.get("starts_at_chapter") != start
                        or search_horizon.get("ends_at_chapter") != end
                    ):
                        raise ValueError(
                            "Volume Narrative Search horizon is inconsistent"
                        )
            if self.generator_operation_name == "book_plan.generate":
                target_chapters = search_horizon.get("target_chapters")
                if target_chapters is not None and (
                    search_horizon.get("level") != "BOOK"
                    or not isinstance(target_chapters, int)
                    or isinstance(target_chapters, bool)
                    or target_chapters <= 0
                ):
                    raise ValueError(
                        "Book Narrative Search frozen chapter target is invalid"
                    )
        elif (
            self.narrative_search_parent_state_asset_version_id
            or self.narrative_search_accepted_through_chapter
            or search_horizon
            or desired_transformation
            or hard_constraints
        ):
            raise ValueError(
                "Narrative Search request cannot be supplied without identity"
            )
        object.__setattr__(
            self,
            "narrative_search_planning_horizon",
            MappingProxyType(search_horizon) if search_horizon else None,
        )
        object.__setattr__(
            self,
            "narrative_search_desired_transformation",
            MappingProxyType(desired_transformation)
            if desired_transformation
            else None,
        )
        object.__setattr__(self, "narrative_search_hard_constraints", hard_constraints)

    @property
    def planning_scope(self) -> PlanningScope:
        return GENERATOR_SCOPE[self.generator_operation_name]

    @property
    def narrative_search_snapshot(self) -> dict[str, Any]:
        if not self.narrative_search_id:
            return {}
        return {
            "search_id": self.narrative_search_id,
            "branch_key": self.narrative_search_branch_key,
            "parent_state_asset_version_id": (
                self.narrative_search_parent_state_asset_version_id
            ),
            "accepted_through_chapter": (
                self.narrative_search_accepted_through_chapter
            ),
            "strategy_directive": self.narrative_search_strategy_directive,
            "planning_horizon": dict(self.narrative_search_planning_horizon or {}),
            "desired_transformation": dict(
                self.narrative_search_desired_transformation or {}
            ),
            "hard_constraints": list(self.narrative_search_hard_constraints),
        }

    @property
    def narrative_search_chapter_range(self) -> tuple[int, int] | None:
        if (
            self.generator_operation_name
            not in {"chapter_group_plan.generate", "volume_plan.generate"}
            or not self.narrative_search_id
        ):
            return None
        chapter_range = dict(self.narrative_search_planning_horizon or {}).get(
            "chapter_range"
        )
        if chapter_range is None:
            return None
        return int(chapter_range[0]), int(chapter_range[1])


@dataclass(frozen=True, slots=True)
class StoryPlanningEvaluationCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    candidate_asset_version_id: str
    generation_operation_id: str
    generator_operation_name: str
    candidate_content_hash: str
    evaluator_execution_class: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    evaluation: Mapping[str, Any] | None = None
    evidence_asset_version_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.candidate_asset_version_id,
            self.generation_operation_id,
            self.generator_operation_name,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Planning Evaluation command is incomplete")
        if self.generator_operation_name not in GENERATOR_SCOPE:
            raise ValueError("Planning Evaluation generator is not supported")
        if not _CONTENT_HASH.fullmatch(self.candidate_content_hash):
            raise ValueError("Planning Evaluation requires the exact candidate hash")
        if self.evaluator_execution_class not in {
            "MODEL_PROVIDER",
            "SCRIPTED_FIXTURE",
            "OPERATOR_REVIEW",
        }:
            raise ValueError("Planning evaluator execution class is unsupported")
        evidence_ids = tuple(
            str(item).strip() for item in self.evidence_asset_version_ids
        )
        if any(not item for item in evidence_ids) or len(set(evidence_ids)) != len(
            evidence_ids
        ):
            raise ValueError("Planning Evaluation evidence identity is invalid")
        if self.evaluator_execution_class == "MODEL_PROVIDER":
            if self.evaluation is not None or evidence_ids:
                raise ValueError(
                    "Model-provider evaluation result is owned by the governed runtime"
                )
        elif not isinstance(self.evaluation, Mapping) or not self.evaluation:
            raise ValueError(
                "Fixture or operator Planning Evaluation payload is required"
            )
        object.__setattr__(
            self,
            "evaluation",
            None
            if self.evaluation is None
            else MappingProxyType(dict(self.evaluation)),
        )
        object.__setattr__(self, "evidence_asset_version_ids", evidence_ids)


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
    capability_execution_ref: str
    capability_execution_hash: str
    capability_runtime_binding_ref: str
    capability_runtime_binding_hash: str
    commit_authority: str
    fixture_protocol_only: bool
    real_provider_proven: bool = False
    production_verified: bool = False
    context_bundle_asset_version_id: str = ""
    context_bundle_hash: str = ""
    narrative_intelligence_selection_digest: str = ""

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
                "context_bundle_asset_version_id",
                "context_bundle_hash",
                "narrative_intelligence_selection_digest",
            }
            and not name.endswith("_hash")
        )
        if self.fencing_token <= 0 or any(not str(value).strip() for value in required):
            raise ValueError("Planning execution evidence is incomplete")
        for name in (
            "capability_pack_attempt_snapshot_hash",
            "capability_execution_hash",
            "capability_runtime_binding_hash",
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
        lineage = (
            self.context_bundle_asset_version_id,
            self.context_bundle_hash,
            self.narrative_intelligence_selection_digest,
        )
        if any(lineage) and (
            not all(lineage)
            or not _CONTENT_HASH.fullmatch(self.context_bundle_hash)
            or not _CONTENT_HASH.fullmatch(self.narrative_intelligence_selection_digest)
        ):
            raise ValueError(
                "Planning Context / Narrative Intelligence lineage is invalid"
            )

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
        extra = roles - expected
        if (
            not expected.issubset(roles)
            or len(roles) != len(self.frozen_inputs)
            or not _extra_roles_are_allowed(self.generator_operation_name, extra)
        ):
            raise ValueError("Planning candidate input snapshot is incomplete")
        object.__setattr__(
            self,
            "candidate_payload",
            MappingProxyType(normalize_foundation_payload(self.generator_operation_name, self.candidate_payload) if self.generator_operation_name in FOUNDATION_GENERATORS else dict(self.candidate_payload)),
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
        if self.generator_operation_name in FOUNDATION_GENERATORS:
            payload["foundation_parent_bindings"] = dict(envelope["foundation_parent_bindings"])
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
    project_id: str,
    book_id: str,
    generation_operation_id: str,
    generator_operation_name: str,
    frozen_inputs: tuple[FrozenPlanningInput, ...],
    input_contents: Mapping[str, Mapping[str, Any]],
    candidate_payload: Mapping[str, Any],
    arc_working_set: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if generator_operation_name not in GENERATOR_SCOPE:
        raise ValueError("Planning Generator is not supported")
    from novel_forge.modules.story_design_authority.author_input import author_binding_from_inputs
    author_design = author_binding_from_inputs([
        {"role": item.role, "asset_version_id": item.asset_version_id,
         "content_hash": item.content_hash, "content": input_contents[item.role]}
        for item in frozen_inputs
    ], project_id=project_id, book_id=book_id)
    if generator_operation_name in FOUNDATION_GENERATORS:
        return {**foundation_envelope(generator=generator_operation_name, inputs=frozen_inputs), **({"author_design": author_design} if author_design else {})}
    expected_roles = set(GENERATOR_INPUT_ROLES[generator_operation_name])
    actual_roles = set(input_contents)
    extra_roles = actual_roles - expected_roles
    if not expected_roles.issubset(actual_roles) or not _extra_roles_are_allowed(
        generator_operation_name, extra_roles
    ):
        raise ValueError("Planning constraint inputs must match frozen Authority roles")
    by_role = {item.role: item for item in frozen_inputs}
    if set(by_role) != actual_roles:
        raise ValueError("Planning constraint input versions are incomplete")

    inherited: list[dict[str, Any]] = []
    prohibited: list[dict[str, Any]] = []
    obligations: list[dict[str, Any]] = []
    accepted_through = 0
    narrative_load_projection: dict[str, Any] | None = None
    inherited_load_policies: list[tuple[str, str, dict[str, Any]]] = []
    for role in sorted(actual_roles):
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
        if role == "story_state":
            narrative_load_projection = project_narrative_load(story_state=content)
        inherited_policy = _read_inherited_narrative_load_policy(content)
        if inherited_policy is not None:
            inherited_load_policies.append((role, source_version, inherited_policy))

    policy, policy_lineage = _resolve_narrative_load_policy(
        project_id=project_id,
        book_id=book_id,
        generation_operation_id=generation_operation_id,
        frozen_inputs=by_role,
        input_contents=input_contents,
        inherited_policies=inherited_load_policies,
    )

    local_prohibited = _constraint_records(
        candidate_payload.get("prohibited_outcomes"),
        "candidate",
        "UNMATERIALIZED_CANDIDATE",
        "prohibited_outcomes",
    )
    body = {
        "type": "PlanningConstraintEnvelope",
        "contract_version": "planning-constraint-envelope-v2",
        "project_id": project_id,
        "book_id": book_id,
        "generation_operation_id": generation_operation_id,
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
                "asset_type": by_role[role].asset_type,
            }
            for role in sorted(by_role)
        ],
        "inherited_invariants": inherited,
        "prohibited_outcomes": [*prohibited, *local_prohibited],
        "required_obligations": obligations,
        **({"author_design": author_design} if author_design else {}),
        "narrative_load_projection": narrative_load_projection
        or {
            "type": "NarrativeLoadProjection",
            "contract_version": "narrative-load-projection-v2",
            "accepted_through_chapter": accepted_through,
            "status": "NOT_OBSERVED",
            "metrics": {},
            "open_obligation_ids": [],
            "overdue_obligation_ids": [],
        },
        "narrative_load_policy": policy,
        "narrative_load_policy_lineage": policy_lineage,
        "change_governance": {
            "requires_evidence": True,
            "wider_scope_requires_new_plan_change": True,
            "preserve_executed_history": True,
        },
        **({"arc_working_set": dict(arc_working_set)} if arc_working_set else {}),
    }
    return {**body, "envelope_digest": canonical_hash(body)}


def _read_inherited_narrative_load_policy(
    content: Mapping[str, Any],
) -> dict[str, Any] | None:
    envelope = content.get("constraint_envelope")
    if not isinstance(envelope, Mapping):
        candidate = content.get("candidate_payload")
        if isinstance(candidate, Mapping):
            envelope = candidate.get("constraint_envelope")
    if not isinstance(envelope, Mapping):
        return None
    policy = envelope.get("narrative_load_policy")
    if not isinstance(policy, Mapping):
        return None
    result = dict(policy)
    supplied_hash = str(result.pop("policy_hash", ""))
    if (
        not _CONTENT_HASH.fullmatch(supplied_hash)
        or canonical_hash(result) != supplied_hash
    ):
        raise ValueError("inherited Narrative Load Policy hash is invalid")
    result["policy_hash"] = supplied_hash
    return result


def _resolve_narrative_load_policy(
    *,
    project_id: str,
    book_id: str,
    generation_operation_id: str,
    frozen_inputs: Mapping[str, FrozenPlanningInput],
    input_contents: Mapping[str, Mapping[str, Any]],
    inherited_policies: list[tuple[str, str, dict[str, Any]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if inherited_policies:
        hashes = {str(item[2]["policy_hash"]) for item in inherited_policies}
        if len(hashes) != 1:
            raise ValueError(
                "frozen Planning parents disagree on Narrative Load Policy"
            )
        policy = dict(inherited_policies[0][2])
        if (
            str(policy.get("project_id") or "") != project_id
            or str(policy.get("book_id") or "") != book_id
        ):
            raise ValueError("inherited Narrative Load Policy scope differs")
        inherited_from = [
            {
                "role": role,
                "asset_version_id": version_id,
                "content_hash": frozen_inputs[role].content_hash,
            }
            for role, version_id, _policy in inherited_policies
        ]
    else:
        profile_input = frozen_inputs.get("production_profile")
        profile_content = input_contents.get("production_profile")
        if profile_input is None or not isinstance(profile_content, Mapping):
            raise ValueError(
                "Planning requires an inherited or Production Profile Narrative Load Policy"
            )
        configured = profile_content.get("narrative_load_policy")
        configured_policy = dict(configured) if isinstance(configured, Mapping) else {}
        configured_limits = configured_policy.get("limits")
        limits = {
            **DEFAULT_NARRATIVE_LOAD_LIMITS,
            **(
                dict(configured_limits)
                if isinstance(configured_limits, Mapping)
                else {}
            ),
        }
        _validate_narrative_load_limits(limits)
        overrides = _validate_governed_load_overrides(
            configured_policy.get("governed_overrides") or (),
            project_id=project_id,
            book_id=book_id,
        )
        body = {
            "type": "NarrativeLoadPolicy",
            "contract_version": "narrative-load-policy-v1",
            "project_id": project_id,
            "book_id": book_id,
            "policy_id": str(
                configured_policy.get("policy_id")
                or "canonical-production-narrative-load"
            ),
            "policy_version": int(configured_policy.get("policy_version") or 1),
            "source_role": "production_profile",
            "source_asset_version_id": profile_input.asset_version_id,
            "source_content_hash": profile_input.content_hash,
            "limits": limits,
            "governed_overrides": overrides,
        }
        policy = {**body, "policy_hash": canonical_hash(body)}
        inherited_from = [
            {
                "role": "production_profile",
                "asset_version_id": profile_input.asset_version_id,
                "content_hash": profile_input.content_hash,
            }
        ]
    return policy, {
        "type": "NarrativeLoadPolicyLineage",
        "contract_version": "narrative-load-policy-lineage-v1",
        "frozen_by_generation_operation_id": generation_operation_id,
        "inherited_from": inherited_from,
        "policy_hash": policy["policy_hash"],
    }


def _validate_narrative_load_limits(limits: Mapping[str, Any]) -> None:
    if set(limits) != set(NARRATIVE_LOAD_LIMIT_FIELDS) or any(
        not isinstance(limits.get(key), int) or int(limits[key]) < 0
        for key in NARRATIVE_LOAD_LIMIT_FIELDS
    ):
        raise ValueError("Narrative Load Policy requires exact non-negative limits")


def _validate_governed_load_overrides(
    value: Any, *, project_id: str, book_id: str
) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("Narrative Load governed overrides must be an array")
    result: list[dict[str, Any]] = []
    identities: set[str] = set()
    for raw in value:
        item = dict(raw) if isinstance(raw, Mapping) else {}
        override_id = str(item.get("override_id") or "")
        limits = item.get("limits")
        if (
            not override_id
            or override_id in identities
            or str(item.get("project_id") or "") != project_id
            or str(item.get("book_id") or "") != book_id
            or str(item.get("scope_type") or "")
            not in {"BOOK", "VOLUME", "ARC", "CHAPTER_GROUP", "CHAPTER"}
            or not str(item.get("scope_key") or "")
            or not str(item.get("governance_action_asset_version_id") or "")
            or not _CONTENT_HASH.fullmatch(
                str(item.get("governance_action_content_hash") or "")
            )
            or not isinstance(limits, Mapping)
            or not limits
            or any(key not in NARRATIVE_LOAD_LIMIT_FIELDS for key in limits)
            or any(
                not isinstance(number, int) or number < 0 for number in limits.values()
            )
        ):
            raise ValueError(
                "Narrative Load override requires exact scope and governance evidence"
            )
        identities.add(override_id)
        result.append(item)
    return result


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


def require_chapter_schedule_row(
    source_content: Mapping[str, Any], *, chapter_number: int
) -> dict[str, Any]:

    if chapter_number <= 0:
        raise ValueError("Chapter schedule binding requires a positive Chapter number")
    matrix = source_content.get("chapter_function_matrix")
    if isinstance(matrix, list):
        candidates = [
            item
            for item in matrix
            if isinstance(item, Mapping)
            and item.get("chapter_number") == chapter_number
            and not isinstance(item.get("chapter_number"), bool)
        ]
    else:
        nested = source_content.get("chapter_function_matrix_row")
        candidate = nested if isinstance(nested, Mapping) else source_content
        candidates = (
            [candidate]
            if candidate.get("chapter_number") == chapter_number
            and not isinstance(candidate.get("chapter_number"), bool)
            else []
        )
    if len(candidates) != 1:
        raise ValueError(
            "Scheduling source must contain exactly one row for the requested Chapter"
        )
    row = dict(candidates[0])
    missing = [field for field in CHAPTER_SCHEDULE_FIELDS if field not in row]
    reader = row.get("reader_experience")
    if not isinstance(reader, Mapping):
        missing.append("reader_experience")
    else:
        missing.extend(
            f"reader_experience.{field}"
            for field in CHAPTER_READER_SCHEDULE_FIELDS
            if field not in reader
        )
    if missing:
        raise ValueError(
            "Chapter schedule row is incomplete: " + ", ".join(sorted(missing))
        )
    return row


def _extra_roles_are_allowed(generator: str, roles: set[str]) -> bool:
    planning_roles = {
        role
        for role in roles
        if not role.startswith("narrative_governance_action:")
        and role != "narrative_search_parent_state"
    }
    if not planning_roles:
        return True
    if generator == "arc_plan.generate":
        return all(
            role.startswith("arc_scope_volume:")
            or role.startswith("related_arc:")
            or role.startswith("dependent_arc:")
            for role in planning_roles
        )
    if generator in {"chapter_group_plan.generate", "chapter_plan.generate"}:
        return all(role.startswith("related_arc:") for role in planning_roles)
    return False


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
    "CHAPTER_READER_SCHEDULE_FIELDS",
    "CHAPTER_SCHEDULE_FIELDS",
    "GENERATOR_INPUT_ROLES",
    "GENERATOR_SCOPE",
    "FrozenPlanningInput",
    "PlanningExecutionEvidence",
    "PlanningGenerationCandidate",
    "PlanningGenerationResult",
    "PlanningGenerationStatus",
    "PlanningRepairRequest",
    "PlanningValidationReport",
    "StoryPlanningEvaluationCommand",
    "StoryPlanningGenerationCommand",
    "build_planning_constraint_envelope",
    "canonical_hash",
    "require_chapter_schedule_row",
]
