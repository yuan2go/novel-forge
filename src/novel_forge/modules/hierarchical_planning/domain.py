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


class PlanningHorizon(StrEnum):
    STRATEGIC = "STRATEGIC"
    TACTICAL = "TACTICAL"
    OPERATIONAL = "OPERATIONAL"


class RealizationLevel(StrEnum):
    ANCHOR = "ANCHOR"
    DEFINED = "DEFINED"
    DETAILED = "DETAILED"
    ACTIVE = "ACTIVE"


class CommitmentLevel(StrEnum):
    HARD_CONSTRAINT = "HARD_CONSTRAINT"
    SOFT_INTENT = "SOFT_INTENT"
    OPEN_DESIGN_SPACE = "OPEN_DESIGN_SPACE"


PLAN_HORIZON = {
    PlanContractType.BOOK: PlanningHorizon.STRATEGIC,
    PlanContractType.VOLUME: PlanningHorizon.STRATEGIC,
    PlanContractType.ARC: PlanningHorizon.STRATEGIC,
    PlanContractType.CHAPTER_GROUP: PlanningHorizon.TACTICAL,
    PlanContractType.CHAPTER: PlanningHorizon.OPERATIONAL,
}

PLAN_REALIZATION = {
    PlanContractType.BOOK: RealizationLevel.ANCHOR,
    PlanContractType.VOLUME: RealizationLevel.DEFINED,
    PlanContractType.ARC: RealizationLevel.DEFINED,
    PlanContractType.CHAPTER_GROUP: RealizationLevel.DETAILED,
    PlanContractType.CHAPTER: RealizationLevel.ACTIVE,
}

HORIZON_REALIZATION_LEVELS = {
    PlanningHorizon.STRATEGIC: frozenset(RealizationLevel),
    PlanningHorizon.TACTICAL: frozenset(
        {RealizationLevel.DEFINED, RealizationLevel.DETAILED, RealizationLevel.ACTIVE}
    ),
    PlanningHorizon.OPERATIONAL: frozenset(
        {RealizationLevel.DETAILED, RealizationLevel.ACTIVE}
    ),
}


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
    "WITHHOLD": "WITHHELD",
}

ARC_RELATION_TYPES = frozenset(
    {"CAUSES", "ENABLES", "BLOCKS", "REVEALS", "PAYS_OFF"}
)


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
    _validate_progressive_planning_contract(contract_type, content)
    if contract_type is PlanContractType.BOOK:
        _validate_book_design_layers(content)
        return
    if contract_type is PlanContractType.VOLUME:
        segments = content.get("narrative_segments")
        if not isinstance(segments, list) or not segments:
            raise KernelError(
                "NARRATIVE_SEGMENT_REQUIRED",
                "canonical VolumePlan requires at least one Narrative Segment",
            )
        seen: set[str] = set()
        covered_ranges: list[tuple[int, int]] = []
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
            covered_ranges.append((start, end))
        covered_ranges.sort()
        if (
            covered_ranges[0][0] != volume_start
            or covered_ranges[-1][1] != volume_end
            or any(
                current[1] + 1 != following[0]
                for current, following in zip(
                    covered_ranges, covered_ranges[1:], strict=False
                )
            )
        ):
            raise KernelError(
                "NARRATIVE_SEGMENT_COVERAGE_INVALID",
                "Narrative Segments must cover the Volume exactly without gaps or overlaps",
            )
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
        segment_ids = [
            str(item.get("segment_id") or "")
            for item in segments
            if isinstance(item, dict)
        ]
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
        if (
            len(segment_ids) != len(segments)
            or "" in segment_ids
            or len(set(segment_ids)) != len(segment_ids)
        ):
            raise KernelError(
                "NARRATIVE_ARC_SEGMENT_IDENTITY_INVALID",
                "Arc Segments require unique stable identities",
            )
        _validate_arc_relations(content.get("arc_relations"))
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
    transition_keys: set[tuple[str, str]] = set()
    for transition in transitions:
        identity = (
            str(transition.get("state_kind") or ""),
            str(transition.get("entity_key") or ""),
        )
        if (
            not identity[1]
            or identity in transition_keys
            or str(transition.get("from_state") or "")
            == str(transition.get("to_state") or "")
        ):
            code = (
                "CHAPTER_STATE_TRANSITION_NOOP"
                if str(transition.get("from_state") or "")
                == str(transition.get("to_state") or "")
                else "CHAPTER_STATE_TRANSITION_IDENTITY_INVALID"
            )
            raise KernelError(
                code,
                "Chapter state transitions must be unique, causal state changes",
            )
        transition_keys.add(identity)
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
    _validate_chapter_temporal_boundaries(content)
    _validate_scene_architecture(content, transition_keys)
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


def _validate_progressive_planning_contract(
    contract_type: PlanContractType, content: dict[str, Any]
) -> None:
    expected_horizon = PLAN_HORIZON[contract_type]
    try:
        selected_realization = RealizationLevel(
            str(content.get("realization_level") or "")
        )
    except ValueError as exc:
        raise KernelError(
            "PLANNING_REALIZATION_LEVEL_INVALID",
            "Planning realization level is unsupported",
        ) from exc
    if str(content.get("planning_horizon") or "") != expected_horizon.value:
        raise KernelError(
            "PLANNING_HORIZON_INVALID",
            f"{contract_type.value} requires {expected_horizon.value} horizon",
        )
    if selected_realization not in HORIZON_REALIZATION_LEVELS[expected_horizon]:
        raise KernelError(
            "PLANNING_REALIZATION_LEVEL_INVALID",
            f"{contract_type.value} realization is too abstract for its horizon",
        )
    commitments = content.get("commitment_contract")
    if not isinstance(commitments, list) or not commitments:
        raise KernelError(
            "PLANNING_COMMITMENT_CONTRACT_REQUIRED",
            "canonical Planning requires explicit frozen and open design commitments",
        )
    commitment_ids: set[str] = set()
    for item in commitments:
        commitment_id = str((item or {}).get("commitment_id") or "")
        try:
            level = CommitmentLevel(str((item or {}).get("level") or ""))
        except ValueError as exc:
            raise KernelError(
                "PLANNING_COMMITMENT_LEVEL_INVALID",
                "Planning commitment uses an unsupported level",
            ) from exc
        if (
            not commitment_id
            or commitment_id in commitment_ids
            or not str((item or {}).get("statement") or "")
        ):
            raise KernelError(
                "PLANNING_COMMITMENT_IDENTITY_INVALID",
                "Planning commitments require unique identities and statements",
            )
        if (
            expected_horizon is PlanningHorizon.OPERATIONAL
            and level is CommitmentLevel.OPEN_DESIGN_SPACE
        ):
            raise KernelError(
                "PLANNING_OPERATIONAL_COMMITMENT_OPEN",
                "Operational planning cannot leave execution-critical design space open",
            )
        commitment_ids.add(commitment_id)
    _validate_realization_manifest(
        content.get("world_realization"),
        identity_key="world_id",
        required_keys=(
            "invariant_refs",
            "structure_refs",
            "state_ref",
            "visibility",
            "accessibility",
        ),
        expected_level=selected_realization,
        error_prefix="WORLD",
    )
    _validate_realization_manifest(
        content.get("character_realization"),
        identity_key="character_id",
        required_keys=("identity_ref", "state_ref", "trajectory_ref", "scope", "reach"),
        expected_level=selected_realization,
        error_prefix="CHARACTER",
    )
    budget = content.get("narrative_load_budget")
    required_limits = (
        "max_active_arcs",
        "max_dormant_arc_age",
        "max_open_obligations",
        "max_payoff_congestion",
        "max_character_appearance_gap",
        "max_new_concepts",
        "max_state_transitions",
    )
    if not isinstance(budget, dict) or any(
        not isinstance(budget.get(key), int) or int(budget[key]) < 0
        for key in required_limits
    ):
        raise KernelError(
            "NARRATIVE_LOAD_BUDGET_INVALID",
            "Planning requires non-negative canonical Narrative Load limits",
        )
    if contract_type is PlanContractType.CHAPTER:
        observed = {
            "max_active_arcs": len(content.get("arc_schedule") or ()),
            "max_payoff_congestion": len(content.get("payoffs") or ()),
            "max_new_concepts": len(
                {
                    str(fact)
                    for scene in content.get("scene_plan") or ()
                    for fact in (scene or {}).get("information_gain") or ()
                }
            ),
            "max_state_transitions": len(
                content.get("required_state_transitions") or ()
            ),
        }
        exceeded = [
            key for key, count in observed.items() if count > int(budget[key])
        ]
        if exceeded:
            raise KernelError(
                "NARRATIVE_LOAD_BUDGET_EXCEEDED",
                "Chapter execution exceeds: " + ", ".join(sorted(exceeded)),
            )
        projection = dict(
            (content.get("constraint_envelope") or {}).get(
                "narrative_load_projection"
            )
            or {}
        )
        metrics = dict(projection.get("metrics") or {})
        if projection.get("status") == "MEASURED":
            inherited_limits = {
                "active_arc_count": "max_active_arcs",
                "dormant_arc_max_age": "max_dormant_arc_age",
                "open_obligation_count": "max_open_obligations",
                "payoff_congestion_count": "max_payoff_congestion",
                "character_appearance_max_gap": "max_character_appearance_gap",
            }
            inherited_exceeded = [
                metric
                for metric, limit in inherited_limits.items()
                if int(metrics.get(metric) or 0) > int(budget[limit])
            ]
            if inherited_exceeded:
                raise KernelError(
                    "NARRATIVE_DEBT_GUARDRAIL_BLOCKED",
                    "accepted-state load exceeds: "
                    + ", ".join(sorted(inherited_exceeded)),
                )
            if int(metrics.get("overdue_obligation_count") or 0) > 0 and not any(
                str(item.get("action") or "").upper() == "PAYOFF"
                for item in content.get("payoffs") or ()
                if isinstance(item, dict)
            ):
                raise KernelError(
                    "NARRATIVE_DEBT_PAYDOWN_REQUIRED",
                    "overdue accepted obligations require an explicit payoff action",
                )


def _validate_realization_manifest(
    value: Any,
    *,
    identity_key: str,
    required_keys: tuple[str, ...],
    expected_level: RealizationLevel,
    error_prefix: str,
) -> None:
    if not isinstance(value, list) or not value:
        raise KernelError(
            f"{error_prefix}_REALIZATION_REQUIRED",
            f"canonical Planning requires progressive {error_prefix.title()} realization",
        )
    seen: set[str] = set()
    for item in value:
        identity = str((item or {}).get(identity_key) or "")
        if (
            not isinstance(item, dict)
            or not identity
            or identity in seen
            or any(item.get(key) in (None, "") for key in required_keys)
            or str(item.get("realization_level") or "") != expected_level.value
        ):
            raise KernelError(
                f"{error_prefix}_REALIZATION_INVALID",
                f"{error_prefix.title()} realization requires unique identity, typed dimensions, and horizon level",
            )
        seen.add(identity)


def _validate_book_design_layers(content: dict[str, Any]) -> None:
    trajectories = content.get("character_development")
    obligations = content.get("knowledge_disclosure_obligations")
    if not isinstance(trajectories, list) or not trajectories:
        raise KernelError(
            "CHARACTER_DEVELOPMENT_REQUIRED",
            "canonical BookPlan requires long-form Character Development",
        )
    character_ids = [
        str(item.get("character_id") or "")
        for item in trajectories
        if isinstance(item, dict)
    ]
    if (
        len(character_ids) != len(trajectories)
        or "" in character_ids
        or len(character_ids) != len(set(character_ids))
        or any(not item.get("causal_triggers") for item in trajectories)
    ):
        raise KernelError(
            "CHARACTER_DEVELOPMENT_IDENTITY_INVALID",
            "Character trajectories require unique identities and causal triggers",
        )
    if not isinstance(obligations, dict):
        raise KernelError(
            "DISCLOSURE_OBLIGATION_DESIGN_REQUIRED",
            "canonical BookPlan requires Disclosure and Obligation design",
        )
    declared_ids = {
        str(item)
        for field in (
            "mystery_ids",
            "promise_ids",
            "foreshadow_ids",
        )
        for item in obligations.get(field) or ()
        if str(item)
    }
    windows = obligations.get("obligation_windows")
    if not isinstance(windows, list):
        raise KernelError(
            "NARRATIVE_OBLIGATION_WINDOW_INVALID",
            "Narrative Obligation windows must be an array",
        )
    seen: set[str] = set()
    for window in windows:
        if not isinstance(window, dict):
            raise KernelError(
                "NARRATIVE_OBLIGATION_WINDOW_INVALID",
                "Narrative Obligation windows must be typed objects",
            )
        obligation_id = str(window.get("obligation_id") or "")
        try:
            setup = int(window.get("setup_chapter"))
            not_before = int(window.get("payoff_not_before"))
            due = int(window.get("payoff_due_by"))
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "NARRATIVE_OBLIGATION_WINDOW_INVALID",
                "Narrative Obligation windows require integer boundaries",
            ) from exc
        if (
            not obligation_id
            or obligation_id in seen
            or obligation_id not in declared_ids
            or setup <= 0
            or not setup <= not_before <= due
        ):
            raise KernelError(
                "NARRATIVE_OBLIGATION_WINDOW_INVALID",
                "Narrative Obligation windows require declared identities and ordered boundaries",
            )
        seen.add(obligation_id)


def _validate_arc_relations(value: Any) -> None:
    if not isinstance(value, list):
        raise KernelError(
            "NARRATIVE_ARC_RELATION_INVALID",
            "Arc relations must be a typed array",
        )
    seen: set[str] = set()
    for relation in value:
        if not isinstance(relation, dict):
            raise KernelError(
                "NARRATIVE_ARC_RELATION_INVALID",
                "Arc relations must be typed objects",
            )
        relation_id = str(relation.get("relation_id") or "")
        source = str(relation.get("source_arc_ref") or "")
        target = str(relation.get("target_arc_ref") or "")
        if (
            not relation_id
            or relation_id in seen
            or str(relation.get("relation_type") or "") not in ARC_RELATION_TYPES
            or not source
            or not target
            or source == target
            or not str(relation.get("trigger_or_condition") or "")
        ):
            raise KernelError(
                "NARRATIVE_ARC_RELATION_INVALID",
                "Arc relations require unique identities, supported causal types, and distinct endpoints",
            )
        seen.add(relation_id)


def _validate_chapter_temporal_boundaries(content: dict[str, Any]) -> None:
    chapter = int(content["chapter_number"])
    seen_boundaries: set[tuple[str, str, str]] = set()
    for boundary in content["knowledge_boundaries"]:
        identity = (
            str(boundary.get("layer") or ""),
            str(boundary.get("subject_id") or ""),
            str(boundary.get("fact_id") or ""),
        )
        if not all(identity) or identity in seen_boundaries:
            raise KernelError(
                "CHAPTER_KNOWLEDGE_IDENTITY_INVALID",
                "Knowledge boundaries require unique layer, subject, and fact identities",
            )
        seen_boundaries.add(identity)
        if (
            str(boundary.get("status") or "") != "WITHHELD"
            and int(boundary.get("available_from_chapter") or 0) > chapter
        ):
            raise KernelError(
                "CHAPTER_KNOWLEDGE_FUTURE_LEAK",
                "ChapterPlan cannot expose knowledge before its available chapter",
            )
    seen_disclosures: set[str] = set()
    for disclosure in content["disclosures"]:
        disclosure_id = str(disclosure.get("disclosure_id") or "")
        if not disclosure_id or disclosure_id in seen_disclosures:
            raise KernelError(
                "CHAPTER_DISCLOSURE_IDENTITY_INVALID",
                "Disclosures require unique identities",
            )
        seen_disclosures.add(disclosure_id)
        if (
            str(disclosure.get("mode") or "") != "WITHHOLD"
            and int(disclosure.get("earliest_chapter") or 0) > chapter
        ):
            raise KernelError(
                "CHAPTER_DISCLOSURE_FUTURE_LEAK",
                "ChapterPlan cannot disclose a fact before its earliest chapter",
            )
    seen_payoffs: set[str] = set()
    for payoff in content.get("payoffs") or ():
        obligation_id = str(payoff.get("obligation_id") or "")
        opened = int(payoff.get("opened_chapter") or 0)
        due = int(payoff.get("due_chapter") or 0)
        if (
            not obligation_id
            or obligation_id in seen_payoffs
            or opened <= 0
            or due < opened
            or opened > chapter
            or (chapter > due and str(payoff.get("action") or "") != "PAYOFF")
        ):
            raise KernelError(
                "CHAPTER_PAYOFF_WINDOW_INVALID",
                "Chapter payoff actions require one open, ordered, non-expired window",
            )
        seen_payoffs.add(obligation_id)


def _validate_scene_architecture(
    content: dict[str, Any], transition_keys: set[tuple[str, str]]
) -> None:
    scenes = content["scene_plan"]
    scene_ids = [
        str(scene.get("scene_id") or "")
        for scene in scenes
        if isinstance(scene, dict)
    ]
    if (
        len(scene_ids) != len(scenes)
        or "" in scene_ids
        or len(scene_ids) != len(set(scene_ids))
    ):
        raise KernelError(
            "SCENE_ARCHITECTURE_IDENTITY_DUPLICATE",
            "Scene Architecture requires unique Scene identities",
        )
    known_by_character = {
        str(item.get("character_id") or ""): {
            str(fact) for fact in item.get("known_fact_ids") or () if str(fact)
        }
        for item in content.get("character_participation") or ()
        if isinstance(item, dict) and str(item.get("character_id") or "")
    }
    previous_story_time: dict[str, tuple[int, int]] = {}
    for scene in scenes:
        participants = {str(item) for item in scene.get("participants") or ()}
        pov = str(scene.get("pov_character_id") or "")
        focalization = str(scene.get("focalization") or "")
        story_time = scene.get("story_time")
        relation = str(scene.get("narrative_time_relation") or "")
        if (
            not pov
            or focalization not in {"INTERNAL", "EXTERNAL", "OMNISCIENT"}
            or (focalization != "OMNISCIENT" and pov not in participants)
            or not str(scene.get("location_id") or "")
            or not isinstance(story_time, dict)
            or relation not in {
                "ESTABLISHES", "ADVANCES", "FLASHBACK", "FLASHFORWARD",
                "PARALLEL", "ELLIPSIS",
            }
        ):
            raise KernelError(
                "SCENE_POV_SPACE_CONTRACT_INVALID",
                "Scene requires POV, focalization, participants, and location",
            )
        timeline_id = str(story_time.get("timeline_id") or "")
        start = int(story_time.get("start_ordinal") or 0)
        end = int(story_time.get("end_ordinal") or 0)
        if (
            not timeline_id
            or str(story_time.get("precision") or "")
            not in {"EXACT", "ORDERED", "RANGE"}
            or start <= 0
            or end < start
        ):
            raise KernelError(
                "SCENE_STORY_TIME_INVALID",
                "Scene Story Time must be explicit and valid independently from narrative position",
            )
        previous = previous_story_time.get(timeline_id)
        if previous is None and relation != "ESTABLISHES":
            raise KernelError(
                "SCENE_STORY_TIME_INVALID",
                "the first Scene on a timeline must establish Story Time",
            )
        if previous is not None:
            previous_start, previous_end = previous
            relation_valid = (
                (relation == "FLASHBACK" and end < previous_start)
                or (relation == "PARALLEL" and start <= previous_end and end >= previous_start)
                or (
                    relation in {"ADVANCES", "FLASHFORWARD", "ELLIPSIS"}
                    and start > previous_end
                )
            )
            if not relation_valid:
                raise KernelError(
                    "SCENE_STORY_TIME_INVALID",
                    "Scene Story Time conflicts with its explicit narrative-time relation",
                )
        previous_story_time[timeline_id] = (start, end)
        reachable_by_character = {
            str(item.get("character_id") or ""): {
                str(location)
                for location in item.get("reachable_location_ids") or ()
                if str(location)
            }
            for item in content.get("character_participation") or ()
            if isinstance(item, dict) and str(item.get("character_id") or "")
        }
        location_id = str(scene.get("location_id") or "")
        if any(
            location_id not in reachable_by_character.get(participant, set())
            for participant in participants
        ):
            raise KernelError(
                "SCENE_SPATIAL_ACCESS_INVALID",
                "Scene participants must be reachable at the frozen Scene location",
            )
        accessible = {
            str(fact) for fact in scene.get("accessible_knowledge") or () if str(fact)
        }
        if not accessible.issubset(known_by_character.get(pov, set())):
            raise KernelError(
                "SCENE_HIDDEN_KNOWLEDGE_LEAK",
                "Scene accessible knowledge exceeds the POV character's accepted boundary",
            )
    for current, following in zip(scenes, scenes[1:], strict=False):
        if str(current.get("exit_state") or "") != str(
            following.get("entry_state") or ""
        ):
            raise KernelError(
                "SCENE_ARCHITECTURE_STATE_CHAIN_INVALID",
                "adjacent Scenes must form one explicit state chain",
            )
    transition_entities = {identity[1] for identity in transition_keys}
    if any(
        not set(str(item) for item in scene.get("state_transitions") or ()).issubset(
            transition_entities
        )
        for scene in scenes
    ):
        raise KernelError(
            "SCENE_ARCHITECTURE_TRANSITION_REFERENCE_INVALID",
            "Scene state-transition references must resolve to Chapter transitions",
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
    if any("narrative_density" in row for row in rows):
        progressive_fields = (
            "narrative_density",
            "reader_experience",
            "arc_cadence",
            "obligation_actions",
        )
        for row in rows:
            missing = [field for field in progressive_fields if field not in row]
            if missing:
                issues.append(
                    {
                        "code": "PROGRESSIVE_SCHEDULING_FIELDS_MISSING",
                        "chapter": row.get("chapter_number"),
                        "fields": missing,
                    }
                )
            if row.get("narrative_density") not in {"LOW", "MEDIUM", "HIGH"}:
                issues.append(
                    {
                        "code": "NARRATIVE_DENSITY_INVALID",
                        "chapter": row.get("chapter_number"),
                    }
                )
            cadence = row.get("arc_cadence")
            if not isinstance(cadence, list) or not cadence or len(cadence) > 3:
                issues.append(
                    {
                        "code": "ARC_DENSITY_INVALID",
                        "chapter": row.get("chapter_number"),
                    }
                )
        emotions = [
            str((row.get("reader_experience") or {}).get("target_emotion") or "")
            for row in rows
        ]
        reward_modes = [
            str((row.get("reader_experience") or {}).get("reward_mode") or "")
            for row in rows
        ]
        if len(set(emotions)) == 1 or len(set(reward_modes)) == 1:
            issues.append({"code": "READER_EXPERIENCE_HOMOGENEITY"})
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
    "ARC_RELATION_TYPES",
    "CHAPTER_EXECUTION_STATE_KINDS",
    "READER_DISCLOSURE_STATUS",
    "COMMON_FIELDS",
    "CommitmentLevel",
    "PLAN_HORIZON",
    "PLAN_REALIZATION",
    "PlanContractType",
    "PlanExecutionScope",
    "PlanningHorizon",
    "PlanningContract",
    "RealizationLevel",
    "TYPE_FIELDS",
    "validate_chapter_function_matrix",
    "validate_planning_contract",
]
