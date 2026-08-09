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
    if contract_type in {
        PlanContractType.VOLUME,
        PlanContractType.CHAPTER_GROUP,
        PlanContractType.CHAPTER,
    } and not parent_version_id:
        raise KernelError(
            "PLANNING_PARENT_VERSION_REQUIRED",
            f"{contract_type.value} requires a frozen parent version",
        )
    if contract_type is PlanContractType.BOOK and parent_version_id:
        raise KernelError(
            "PLANNING_PARENT_VERSION_INVALID",
            "BookPlan cannot have a containment parent",
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


def _validate_chapter_arc_contributions(value: Any) -> None:
    if not isinstance(value, (list, tuple)) or not value:
        raise KernelError(
            "PLANNING_ARC_CONTRIBUTION_INVALID",
            "Chapter required Arc contributions must be a non-empty list",
        )
    seen: set[str] = set()
    for contribution in value:
        if not isinstance(contribution, dict):
            raise KernelError(
                "PLANNING_ARC_CONTRIBUTION_INVALID",
                "Chapter required Arc contribution must be an object",
            )
        arc_version = str(
            contribution.get("arc_plan_version_id")
            or contribution.get("arc_id")
            or ""
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
                    "chapters": [
                        item.get("chapter_number") for item in window
                    ],
                }
            )
        if len({item.get("ending_hook") for item in window}) == 1:
            issues.append(
                {
                    "code": "ENDING_HOOK_HOMOGENEITY",
                    "chapters": [
                        item.get("chapter_number") for item in window
                    ],
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
    "COMMON_FIELDS",
    "PlanContractType",
    "PlanExecutionScope",
    "PlanningContract",
    "TYPE_FIELDS",
    "validate_chapter_function_matrix",
    "validate_planning_contract",
]
