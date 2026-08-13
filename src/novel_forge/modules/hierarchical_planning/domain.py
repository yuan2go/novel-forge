"""Pure contracts and validators for hierarchical story planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


class PlanContractType(StrEnum):
    BOOK = "BOOK"
    VOLUME = "VOLUME"
    ARC = "ARC"
    CHAPTER_GROUP = "CHAPTER_GROUP"
    CHAPTER = "CHAPTER"


class PlanExecutionScope(StrEnum):
    EXECUTED = "EXECUTED"
    FROZEN = "FROZEN"
    PLANNED = "PLANNED"
    SPECULATIVE = "SPECULATIVE"


COMMON_FIELDS = (
    "contract_id",
    "logical_key",
    "objective",
    "entry_state_ref",
    "exit_state_spec",
    "hard_constraints",
    "soft_constraints",
    "required_events",
    "forbidden_events",
    "required_payoffs",
    "forbidden_payoffs",
    "character_deltas",
    "world_deltas",
    "relationship_deltas",
    "arc_contributions",
    "canon_dependencies",
    "quality_targets",
    "budget_policy_ref",
    "context_profile_ref",
)

TYPE_FIELDS = {
    PlanContractType.BOOK: (
        "reader_promise",
        "central_conflict_engine",
        "protagonist_transformation",
        "antagonist_escalation",
        "world_evolution",
        "relationship_evolution",
        "theme_evolution",
        "ending_contract",
        "volume_skeleton",
        "major_turns",
        "climax_distribution",
        "long_promise_payoff",
        "length_strategy",
        "risk_register",
    ),
    PlanContractType.VOLUME: (
        "volume_function",
        "stage_conflict",
        "stage_antagonist",
        "irreversible_change",
        "midpoint",
        "climax",
        "settlement",
        "next_volume_bridge",
        "chapter_range",
    ),
    PlanContractType.ARC: (
        "arc_type",
        "resistance",
        "escalation",
        "turn",
        "choice",
        "cost",
        "result",
        "consequence",
        "dependencies",
        "closure_conditions",
        "cross_volume_scope",
    ),
    PlanContractType.CHAPTER_GROUP: (
        "local_objective",
        "trigger",
        "resistance_escalation",
        "turn",
        "local_climax",
        "information_release",
        "emotion_curve",
        "antagonist_actions",
        "chapter_function_matrix",
        "chapter_range",
        "cost_range",
    ),
    PlanContractType.CHAPTER: (
        "chapter_number",
        "primary_function",
        "secondary_functions",
        "required_state_delta",
        "required_arc_contributions",
        "promise_action",
        "foreshadow_action",
        "reward_action",
        "ending_hook",
        "prohibited_outcomes",
    ),
}

# Only state kinds that the Canon extraction boundary can materialize and the
# deterministic execution reconciler can identify are valid Chapter commitments.
CHAPTER_EXECUTION_STATE_KINDS = frozenset(
    {
        "character_state",
        "relationship_state",
        "foreshadow_state",
        "reader_promise",
        "world_rule",
        "power_state",
        "plot_thread",
        "resource_state",
        "character_knowledge",
        "character_belief",
        "character_arc",
        "arc_state",
        "antagonist_state",
    }
)

READER_DISCLOSURE_STATUS = {
    "HINT": "HINTED",
    "PARTIAL": "SUSPECTED",
    "MISDIRECT": "MISDIRECTED",
    "CONFIRM": "KNOWN",
}


@dataclass(frozen=True, slots=True)
class PlanningContract:
    project_id: str
    book_id: str
    contract_type: PlanContractType
    asset_version_id: str
    parent_version_id: str
    logical_key: str
    objective: str
    execution_scope: PlanExecutionScope
    content: dict[str, Any]


def validate_planning_contract(
    *,
    project_id: str,
    book_id: str,
    contract_type: PlanContractType,
    asset_version_id: str,
    parent_version_id: str,
    execution_scope: PlanExecutionScope,
    content: dict[str, Any],
) -> PlanningContract:
    missing = [
        field
        for field in (*COMMON_FIELDS, *TYPE_FIELDS[contract_type])
        if field not in content or content.get(field) in (None, "")
    ]
    if missing:
        raise KernelError(
            "PLANNING_CONTRACT_INCOMPLETE",
            f"{contract_type.value} contract missing: {', '.join(missing)}",
        )
    if (
        contract_type
        in {
            PlanContractType.VOLUME,
            PlanContractType.CHAPTER_GROUP,
            PlanContractType.CHAPTER,
        }
        and not parent_version_id
    ):
        raise KernelError(
            "PLANNING_PARENT_VERSION_REQUIRED",
            f"{contract_type.value} requires a frozen parent version",
        )
    if (
        contract_type in {PlanContractType.BOOK, PlanContractType.ARC}
        and parent_version_id
    ):
        raise KernelError(
            "PLANNING_PARENT_VERSION_INVALID",
            f"{contract_type.value} cannot have a containment parent",
        )
    if (
        content.get("project_id", project_id) != project_id
        or content.get("book_id", book_id) != book_id
    ):
        raise KernelError(
            "PLANNING_CONTRACT_SCOPE_MISMATCH",
            "planning content belongs to another Project or Book",
        )
    declared_parent = str(content.get("parent_version_id") or "")
    if declared_parent and declared_parent != parent_version_id:
        raise KernelError(
            "PLANNING_PARENT_VERSION_MISMATCH",
            "planning content does not bind the supplied parent version",
        )
    if contract_type is PlanContractType.CHAPTER_GROUP:
        chapter_range = content["chapter_range"]
        if not isinstance(chapter_range, (list, tuple)) or len(chapter_range) != 2:
            raise KernelError(
                "CHAPTER_GROUP_RANGE_INVALID",
                "ChapterGroup chapter_range must contain exactly start and end",
            )
        try:
            start, end = map(int, chapter_range)
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "CHAPTER_GROUP_RANGE_INVALID",
                "ChapterGroup chapter_range must contain integer boundaries",
            ) from exc
        if start <= 0 or end < start or not 3 <= end - start + 1 <= 8:
            raise KernelError(
                "CHAPTER_GROUP_RANGE_INVALID",
                "ChapterGroup must contain three to eight Chapters",
            )
        validate_chapter_function_matrix(
            list(content["chapter_function_matrix"]),
            group_objective=str(content["local_objective"]),
        )
    if contract_type is PlanContractType.CHAPTER:
        _validate_chapter_arc_contributions(content["required_arc_contributions"])
    if content.get("narrative_architecture_version") == "canonical-narrative-v1":
        _validate_canonical_narrative_contract(contract_type, content)
    return PlanningContract(
        project_id=project_id,
        book_id=book_id,
        contract_type=contract_type,
        asset_version_id=asset_version_id,
        parent_version_id=parent_version_id,
        logical_key=str(content["logical_key"]),
        objective=str(content["objective"]),
        execution_scope=execution_scope,
        content=dict(content),
    )


def _validate_canonical_narrative_contract(
    contract_type: PlanContractType, content: dict[str, Any]
) -> None:
    if contract_type is PlanContractType.VOLUME:
        segments = content.get("narrative_segments")
        if not isinstance(segments, list) or not segments:
            raise KernelError(
                "NARRATIVE_SEGMENT_REQUIRED",
                "canonical VolumePlan requires at least one Narrative Segment",
            )
        seen: set[str] = set()
        volume_start, volume_end = map(int, content["chapter_range"])
        for segment in segments:
            segment_id = str((segment or {}).get("segment_id") or "")
            chapter_range = (segment or {}).get("chapter_range")
            if (
                not segment_id
                or segment_id in seen
                or not isinstance(chapter_range, list)
                or len(chapter_range) != 2
            ):
                raise KernelError(
                    "NARRATIVE_SEGMENT_INVALID",
                    "Narrative Segment identity and two-boundary chapter range are required",
                )
            start, end = map(int, chapter_range)
            if start < volume_start or end > volume_end or end < start:
                raise KernelError(
                    "NARRATIVE_SEGMENT_RANGE_INVALID",
                    "Narrative Segment range must be contained by its Volume",
                )
            seen.add(segment_id)
        return
    if contract_type is PlanContractType.ARC:
        thread_id = str(content.get("thread_id") or "")
        segments = content.get("arc_segments")
        if not thread_id or not isinstance(segments, list) or not segments:
            raise KernelError(
                "NARRATIVE_ARC_GRAPH_INVALID",
                "canonical ArcPlan requires a Thread identity and Arc Segments",
            )
        volume_scope = {str(item) for item in content.get("cross_volume_scope") or ()}
        declared = {
            str(item.get("volume_plan_version_id") or "")
            for item in segments
            if isinstance(item, dict)
        }
        if "" in declared or not declared.issubset(volume_scope):
            raise KernelError(
                "NARRATIVE_ARC_SEGMENT_SCOPE_INVALID",
                "every Arc Segment must bind a Volume in cross_volume_scope",
            )
        return
    if contract_type in {PlanContractType.CHAPTER_GROUP, PlanContractType.CHAPTER}:
        segment_ref = content.get("narrative_segment_ref")
        if not isinstance(segment_ref, dict) or not all(
            str(segment_ref.get(key) or "")
            for key in ("volume_plan_version_id", "segment_id")
        ):
            raise KernelError(
                "NARRATIVE_SEGMENT_REFERENCE_INVALID",
                f"canonical {contract_type.value} must bind one Narrative Segment",
            )
    if contract_type is not PlanContractType.CHAPTER:
        return
    required = (
        "chapter_intent",
        "arc_schedule",
        "character_participation",
        "knowledge_boundaries",
        "disclosures",
        "required_state_transitions",
        "reader_experience",
        "scene_plan",
        "expected_exit_state",
    )
    missing = [field for field in required if not content.get(field)]
    if missing:
        raise KernelError(
            "CHAPTER_EXECUTION_PLAN_INCOMPLETE",
            "canonical ChapterPlan missing: " + ", ".join(missing),
        )
    transitions = content["required_state_transitions"]
    if not isinstance(transitions, list) or any(
        not isinstance(item, dict)
        or str(item.get("state_kind") or "") not in CHAPTER_EXECUTION_STATE_KINDS
        for item in transitions
    ):
        raise KernelError(
            "CHAPTER_STATE_TRANSITION_KIND_INVALID",
            "Chapter execution transitions must use the canonical Narrative State vocabulary",
        )
    allowed_roles = {"PRIMARY", "SECONDARY", "TOUCH", "SETUP", "PAYOFF", "HOLD"}
    schedule = [item for item in content["arc_schedule"] if isinstance(item, dict)]
    if len(schedule) != len(content["arc_schedule"]) or any(
        str(item.get("role") or "") not in allowed_roles for item in schedule
    ):
        raise KernelError(
            "CHAPTER_ARC_SCHEDULE_INVALID",
            "Chapter Arc schedule uses an unsupported role",
        )
    if sum(str(item.get("role") or "") == "PRIMARY" for item in schedule) != 1:
        raise KernelError(
            "CHAPTER_PRIMARY_ARC_INVALID",
            "canonical ChapterPlan requires exactly one Primary Arc",
        )
    disclosures = [
        item for item in content["disclosures"] if isinstance(item, dict)
    ]
    reader_boundaries = [
        item
        for item in content["knowledge_boundaries"]
        if isinstance(item, dict)
        and str(item.get("layer") or "").upper() == "READER_KNOWLEDGE"
    ]
    for boundary in reader_boundaries:
        fact_id = str(boundary.get("fact_id") or "")
        expected_status = str(boundary.get("status") or "").upper()
        matching_statuses = {
            READER_DISCLOSURE_STATUS.get(str(item.get("mode") or "").upper())
            for item in disclosures
            if str(item.get("fact_id") or "") == fact_id
            and str(item.get("audience") or "").upper() in {"READER", "ALL"}
        }
        if not fact_id or expected_status not in matching_statuses:
            raise KernelError(
                "CHAPTER_READER_KNOWLEDGE_DERIVATION_INVALID",
                "Reader Knowledge must match the status derived from one reader-facing Disclosure",
            )
    scheduled_arcs = [str(item.get("arc_plan_version_id") or "") for item in schedule]
    contribution_arcs = {
        str(item.get("arc_plan_version_id") or "")
        for item in content.get("required_arc_contributions") or ()
        if isinstance(item, dict)
    }
    if (
        any(not item for item in scheduled_arcs)
        or len(set(scheduled_arcs)) != len(scheduled_arcs)
        or not set(scheduled_arcs).issubset(contribution_arcs)
    ):
        raise KernelError(
            "CHAPTER_ARC_REFERENCE_INVALID",
            "Chapter Arc schedule must uniquely reference frozen required Arc contributions",
        )


def _validate_chapter_arc_contributions(value: Any) -> None:
    if not isinstance(value, (list, tuple)):
        raise KernelError(
            "PLANNING_ARC_CONTRIBUTION_INVALID",
            "Chapter required Arc contributions must be a list",
        )
    seen: set[str] = set()
    for contribution in value:
        if not isinstance(contribution, dict):
            raise KernelError(
                "PLANNING_ARC_CONTRIBUTION_INVALID",
                "Chapter required Arc contribution must be an object",
            )
        arc_version = str(
            contribution.get("arc_plan_version_id") or contribution.get("arc_id") or ""
        )
        if not arc_version:
            raise KernelError(
                "PLANNING_ARC_CONTRIBUTION_INVALID",
                "Chapter required Arc contribution must bind an Arc identity",
            )
        if arc_version in seen:
            raise KernelError(
                "PLANNING_ARC_CONTRIBUTION_IDENTITY_DUPLICATE",
                "Chapter may declare at most one required contribution per Arc",
            )
        seen.add(arc_version)


def validate_chapter_function_matrix(
    rows: list[dict[str, Any]], *, group_objective: str
) -> dict[str, Any]:
    if not rows or not group_objective:
        raise KernelError(
            "CHAPTER_FUNCTION_MATRIX_INVALID",
            "Chapter Function Matrix and Group objective are required",
        )
    required = (
        "chapter_number",
        "primary_function",
        "secondary_functions",
        "required_state_delta",
        "required_arc_contributions",
        "promise_action",
        "foreshadow_action",
        "reward_action",
        "ending_hook",
        "prohibited_outcomes",
    )
    issues: list[dict[str, Any]] = []
    for row in rows:
        missing = [field for field in required if field not in row]
        if missing:
            issues.append(
                {
                    "code": "CHAPTER_FUNCTION_FIELDS_MISSING",
                    "chapter": row.get("chapter_number"),
                    "fields": missing,
                }
            )
        if not row.get("required_arc_contributions"):
            issues.append(
                {
                    "code": "ARC_CONTRIBUTION_MISSING",
                    "chapter": row.get("chapter_number"),
                }
            )
        if not row.get("required_state_delta"):
            issues.append(
                {
                    "code": "GROUP_OBJECTIVE_NO_PROGRESS",
                    "chapter": row.get("chapter_number"),
                }
            )
    for index in range(max(0, len(rows) - 2)):
        window = rows[index : index + 3]
        if len({item.get("primary_function") for item in window}) == 1:
            issues.append(
                {
                    "code": "PRIMARY_FUNCTION_REPETITION",
                    "chapters": [item.get("chapter_number") for item in window],
                }
            )
        if len({item.get("ending_hook") for item in window}) == 1:
            issues.append(
                {
                    "code": "ENDING_HOOK_HOMOGENEITY",
                    "chapters": [item.get("chapter_number") for item in window],
                }
            )
    blocking = bool(issues)
    if blocking:
        raise KernelError(
            "CHAPTER_FUNCTION_MATRIX_BLOCKED",
            ", ".join(sorted({item["code"] for item in issues})),
        )
    return {
        "status": "PASSED",
        "chapter_count": len(rows),
        "group_objective": group_objective,
        "issues": [],
    }


__all__ = [
    "CHAPTER_EXECUTION_STATE_KINDS",
    "READER_DISCLOSURE_STATUS",
    "COMMON_FIELDS",
    "PlanContractType",
    "PlanExecutionScope",
    "PlanningContract",
    "TYPE_FIELDS",
    "validate_chapter_function_matrix",
    "validate_planning_contract",
]
