"""Planning-domain binding to the existing Production Execution Plane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable

from novel_forge.modules.capability_pack_authority import (
    CapabilityPackAttemptSnapshot,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.book_design_authority import BookDesignAuthorityQuery
from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetReservationRequest,
    reserve_provider_budget,
    resolve_provider_budget_failure,
    settle_provider_budget,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    dispatch_external_effect,
    plan_external_effect,
    read_external_effect_intent,
    read_succeeded_external_effect,
)
from novel_forge.modules.hierarchical_planning.domain import (
    CHAPTER_EXECUTION_STATE_KINDS,
    HORIZON_REALIZATION_LEVELS,
    PLAN_HORIZON,
    PLAN_REALIZATION,
    TYPE_FIELDS,
    PlanContractType,
    RealizationLevel,
)
from novel_forge.modules.production_execution import (
    ArtifactPointer,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionRuntimeClass,
    FallbackPolicy,
    InputManifest,
    ModelProfile,
    RoutePolicy,
    RouteSnapshot,
    TargetScope,
    default_capability_registry,
)
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCandidate,
    DomainExecutionCommand,
    DomainExecutionEvidence,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
)
from novel_forge.modules.story_design_authority import (
    GeneratorDefinition,
    required_qualification_profiles,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)
from novel_forge.storage.database_runtime import get_database_runtime

from .binder import PreparedPlanningExecution
from .domain import (
    FrozenPlanningInput,
    STORY_PLANNING_MAX_ATTEMPTS,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    StoryPlanningGenerationCommand,
    build_planning_constraint_envelope,
    canonical_hash,
)


_PLANNING_STAGES = frozenset(
    {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
)

# Planning has one retry owner: every Operation Attempt may advance the same
# ExternalEffect by at most one dispatch generation. Sharing the bound keeps
# the Effect from terminalizing while the Operation still has retry budget and
# prevents nested retry amplification.
PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS = STORY_PLANNING_MAX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class PlanningExecutionRoute:
    """Authority-selected Planning route carried into each frozen attempt."""

    model_profile: ModelProfile
    route_policy: RoutePolicy
    fallback_policy: FallbackPolicy
    backend_version: str
    runtime_host_id: str
    auth_profile_ref: str
    release_sha: str

    def __post_init__(self) -> None:
        if (
            self.model_profile.profile_id
            not in self.route_policy.allowed_model_profile_ids
        ):
            raise ValueError("Planning RoutePolicy does not allow its ModelProfile")
        if (
            self.route_policy.fallback_policy_ref != self.fallback_policy.policy_id
            or self.route_policy.fallback_policy_version
            != self.fallback_policy.policy_version
            or self.route_policy.fallback_policy != self.fallback_policy.mode.value
        ):
            raise ValueError("Planning RoutePolicy does not bind its FallbackPolicy")
        if not all(
            (
                self.backend_version,
                self.runtime_host_id,
                self.auth_profile_ref,
            )
        ):
            raise ValueError("Planning execution route is incomplete")
        if len(self.release_sha) != 40:
            raise ValueError("Planning execution route requires a full release SHA")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _chapter_function_row(
    chapter: int,
    function: str,
    hook: str,
    arc_plan_version_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    arc_ids = arc_plan_version_ids[:3] or ("arc:primary",)
    return {
        "chapter_number": chapter,
        "primary_function": function,
        "secondary_functions": ["character pressure"],
        "required_state_delta": {"summary": "commitment advances"},
        "required_arc_contributions": [
            {"arc_plan_version_id": arc_id, "contribution": "advance"}
            for arc_id in arc_ids
        ],
        "promise_action": "advance",
        "foreshadow_action": "plant",
        "reward_action": "partial payoff",
        "ending_hook": hook,
        "prohibited_outcomes": ["silent reset"],
        "narrative_density": (
            "HIGH" if function in {"reversal", "payoff"} else "MEDIUM"
        ),
        "reader_experience": {
            "target_emotion": (
                "costly relief" if function == "payoff" else "rising pressure"
            ),
            "reward_mode": "PAYOFF" if function == "payoff" else "DISCOVERY",
        },
        "arc_cadence": [
            {
                "arc_plan_version_id": arc_id,
                "action": (
                    "PAYOFF"
                    if function == "payoff" and index == 0
                    else "ADVANCE"
                    if index == 0
                    else "TOUCH"
                ),
            }
            for index, arc_id in enumerate(arc_ids)
        ],
        "obligation_actions": [
            {
                "obligation_id": "promise:choice",
                "action": "PAYOFF" if function == "payoff" else "ADVANCE",
                "due_chapter": chapter if function == "payoff" else chapter + 2,
            }
        ],
    }


def _logical_chapter_number(logical_key: str) -> int:
    parts = logical_key.split(":")
    if len(parts) >= 2 and parts[0] == "chapter":
        try:
            chapter = int(parts[1])
        except ValueError:
            chapter = 0
        if chapter > 0:
            return chapter
    if len(parts) >= 2 and parts[0] == "chapter-group":
        candidate = parts[-1] if parts[1] == "containing" else parts[1].split("-", 1)[0]
        try:
            chapter = int(candidate)
        except ValueError:
            chapter = 0
        if chapter > 0:
            return chapter
    return 1


def _fixture_chapter_shape(chapter_number: int) -> tuple[str, str]:
    return {
        1: ("setup", "door closes"),
        2: ("reversal", "ally defects"),
        3: ("payoff", "cost arrives"),
    }[((chapter_number - 1) % 3) + 1]


def planning_fixture_response(stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Explicit deterministic response for SCRIPTED_FIXTURE routes only."""

    if stage not in _PLANNING_STAGES:
        raise ValueError(f"unsupported Planning fixture stage: {stage}")
    command = inputs.get("planning_command")
    if not isinstance(command, Mapping):
        raise ValueError("Planning fixture requires its frozen command")
    frozen_values = inputs.get("frozen_inputs")
    frozen_inputs = [
        dict(item) for item in frozen_values or () if isinstance(item, Mapping)
    ]
    frozen_by_role = {str(item.get("role") or ""): item for item in frozen_inputs}
    project_id = str(command.get("project_id") or "project-1")
    book_id = str(command.get("book_id") or "book-1")
    generation_operation_id = str(
        command.get("generation_operation_id") or "operation:fixture-generation"
    )

    def authority_ref(
        *, roles: tuple[str, ...], domain_type: str, fallback: str
    ) -> dict[str, str]:
        source = next(
            (frozen_by_role[role] for role in roles if role in frozen_by_role),
            None,
        )
        if source is None:
            version_id = fallback
            asset_type = roles[0]
            content_hash = (
                "sha256:" + hashlib.sha256(fallback.encode("utf-8")).hexdigest()
            )
            role = roles[0]
        else:
            version_id = str(source.get("asset_version_id") or "")
            asset_type = str(source.get("asset_type") or "")
            content_hash = str(source.get("content_hash") or "")
            role = str(source.get("role") or "")
        return {
            "project_id": project_id,
            "book_id": book_id,
            "authority_role": role,
            "asset_version_id": version_id,
            "asset_type": asset_type,
            "content_hash": content_hash,
            "domain_type": domain_type,
            "freshness": "CURRENT",
            "frozen_by_operation_id": generation_operation_id,
        }

    logical_key = str(command.get("logical_key") or "")
    fixture_book_volume_count = 2 if logical_key.endswith(":portfolio-2") else 1
    fixture_book_target_chapters = fixture_book_volume_count * 3
    logical_ordinal = 1
    if stage == "volume_plan.generate":
        try:
            logical_ordinal = max(1, int(logical_key.rsplit(":", 1)[-1]))
        except ValueError:
            logical_ordinal = 1
    chapter_number = _logical_chapter_number(logical_key)
    arc_entry_state = _fixture_character_arc_stage(max(0, chapter_number - 1))
    arc_exit_state = _fixture_character_arc_stage(max(1, chapter_number))
    disclosure_mode = "HINT" if chapter_number <= 1 else "CONFIRM"
    reader_knowledge_status = "HINTED" if chapter_number <= 1 else "KNOWN"
    chapter_function, chapter_hook = _fixture_chapter_shape(chapter_number)
    parent_version_id = str(command.get("parent_version_id") or "")
    input_versions = command.get("input_versions")
    versions = dict(input_versions) if isinstance(input_versions, Mapping) else {}
    arc_plan_ids = tuple(
        item
        for item in (
            str(versions.get("arc_plans") or ""),
            *(str(item) for item in command.get("related_arc_plan_version_ids") or ()),
        )
        if item
    )
    arc_scope = [
        str(versions.get("volume_plan") or parent_version_id),
        *(str(item) for item in command.get("arc_scope_volume_plan_version_ids") or ()),
    ]
    contract_type = {
        "book_plan.generate": PlanContractType.BOOK,
        "volume_plan.generate": PlanContractType.VOLUME,
        "arc_plan.generate": PlanContractType.ARC,
        "chapter_group_plan.generate": PlanContractType.CHAPTER_GROUP,
        "chapter_plan.generate": PlanContractType.CHAPTER,
    }[stage]
    payload: dict[str, Any] = {
        "contract_id": f"contract:{logical_key}",
        "logical_key": logical_key,
        "objective": f"Governed objective for {logical_key}",
        "entry_state_ref": "story-state:entry",
        "exit_state_spec": {"summary": "the governed objective advances"},
        "hard_constraints": [],
        "soft_constraints": [],
        "required_events": [],
        "forbidden_events": [],
        "required_payoffs": [],
        "forbidden_payoffs": [],
        "character_deltas": [],
        "world_deltas": [],
        "relationship_deltas": [],
        "arc_contributions": [],
        "canon_dependencies": [],
        "quality_targets": {"minimum": 80},
        "budget_policy_ref": "planning-budget:v1",
        "context_profile_ref": "planning-context:v1",
        "planning_horizon": PLAN_HORIZON[contract_type].value,
        "realization_level": PLAN_REALIZATION[contract_type].value,
        "commitment_contract": [
            {
                "commitment_id": f"commitment:{logical_key}:causal-anchor",
                "level": "HARD_CONSTRAINT",
                "statement": "preserve the accepted causal spine",
            },
            {
                "commitment_id": f"commitment:{logical_key}:elaboration",
                "level": (
                    "SOFT_INTENT"
                    if contract_type is PlanContractType.CHAPTER
                    else "OPEN_DESIGN_SPACE"
                ),
                "statement": "elaborate only at the current narrative horizon",
            },
        ],
        "world_realization": [
            {
                "world_id": "world:primary",
                "invariant_refs": [
                    authority_ref(
                        roles=("world_bible", "book_plan", "story_state"),
                        domain_type="WORLD_INVARIANT",
                        fallback="world-invariant:causality",
                    )
                ],
                "structure_refs": [
                    authority_ref(
                        roles=("world_bible", "book_plan", "canon_snapshot"),
                        domain_type="WORLD_STRUCTURE",
                        fallback="world-structure:institution",
                    )
                ],
                "state_ref": authority_ref(
                    roles=(
                        "story_state",
                        "canon_snapshot",
                        "world_bible",
                        "book_plan",
                    ),
                    domain_type="WORLD_STATE",
                    fallback="world-state:current",
                ),
                "realization_level": PLAN_REALIZATION[contract_type].value,
                "narrative_relevance": "CURRENT",
                "visibility": (
                    "HIDDEN"
                    if contract_type is PlanContractType.BOOK
                    else "PARTIAL"
                    if contract_type is not PlanContractType.CHAPTER
                    else "SCENE_VISIBLE"
                ),
                "accessibility": (
                    "CLOSED"
                    if contract_type is PlanContractType.BOOK
                    else "RESTRICTED"
                    if contract_type is not PlanContractType.CHAPTER
                    else "ACCESSIBLE"
                ),
            }
        ],
        "character_realization": [
            {
                "character_id": "protagonist",
                "identity_ref": authority_ref(
                    roles=(
                        "character_cast",
                        "character_arc_portfolio",
                        "book_plan",
                    ),
                    domain_type="CHARACTER_IDENTITY",
                    fallback="character-identity:protagonist",
                ),
                "state_ref": authority_ref(
                    roles=("story_state", "character_cast", "book_plan"),
                    domain_type="CHARACTER_STATE",
                    fallback="character-state:protagonist:current",
                ),
                "trajectory_ref": authority_ref(
                    roles=(
                        "character_arc_portfolio",
                        "character_cast",
                        "book_plan",
                    ),
                    domain_type="CHARACTER_TRAJECTORY",
                    fallback="character-arc:accountability",
                ),
                "scope": contract_type.value,
                "reach": {
                    PlanContractType.BOOK: "DISTANT",
                    PlanContractType.VOLUME: "CURRENT_VOLUME",
                    PlanContractType.ARC: "CURRENT_VOLUME",
                    PlanContractType.CHAPTER_GROUP: "CURRENT_SEGMENT",
                    PlanContractType.CHAPTER: "CURRENT_CHAPTER",
                }[contract_type],
                "realization_level": PLAN_REALIZATION[contract_type].value,
                "narrative_relevance": "CURRENT",
            }
        ],
    }
    if command.get("change_evidence_version_ids"):
        payload["objective"] = (
            f"{payload['objective']} adjusted by governed change evidence"
        )
    by_type: dict[PlanContractType, dict[str, Any]] = {
        PlanContractType.BOOK: {
            "reader_promise": "Escalation with earned payoff",
            "central_conflict_engine": "Goal versus irreversible cost",
            "protagonist_transformation": "Avoidance to accountable choice",
            "antagonist_escalation": ["pressure", "constraint", "collision"],
            "world_evolution": ["scarcity", "revelation"],
            "relationship_evolution": ["distrust", "alliance"],
            "theme_evolution": ["freedom", "responsibility"],
            "ending_contract": {"outcome": "costly agency"},
            "volume_skeleton": [
                {"volume": ordinal, "function": "commitment"}
                for ordinal in range(1, fixture_book_volume_count + 1)
            ],
            "major_turns": ["irreversible choice"],
            "climax_distribution": [1],
            "long_promise_payoff": ["central promise settled"],
            "length_strategy": {"target_chapters": fixture_book_target_chapters},
            "risk_register": [],
            "narrative_architecture_version": "canonical-narrative-v1",
            "character_development": [
                {
                    "character_id": "protagonist",
                    "entry_belief": "silence preserves safety",
                    "target_belief": "agency requires accountable witness",
                    "causal_triggers": ["a delayed choice exposes the witness"],
                    "power_progression": ["private knowledge", "public agency"],
                    "relationship_progression": ["distrust", "conditional trust"],
                    "ending_state": "accepts visible responsibility",
                }
            ],
            "knowledge_disclosure_obligations": {
                "story_truth_ids": ["fact:hidden-cost"],
                "mystery_ids": ["mystery:archive-bargain"],
                "promise_ids": ["promise:choice"],
                "foreshadow_ids": ["setup:consequence"],
                "obligation_windows": [
                    {
                        "obligation_id": "promise:choice",
                        "setup_chapter": 1,
                        "payoff_not_before": 2,
                        "payoff_due_by": 3,
                    }
                ],
            },
        },
        PlanContractType.VOLUME: {
            "volume_function": "force commitment",
            "stage_conflict": "safety versus truth",
            "stage_antagonist": "institutional resistance",
            "irreversible_change": "public commitment",
            "midpoint": "false victory",
            "climax": "costly revelation",
            "settlement": "new obligation",
            "next_volume_bridge": "wider threat",
            "chapter_range": [
                (logical_ordinal - 1) * 3 + 1,
                logical_ordinal * 3,
            ],
            "narrative_architecture_version": "canonical-narrative-v1",
            "narrative_segments": [
                {
                    "segment_id": "narrative-segment:1",
                    "objective": "Turn private doubt into public commitment",
                    "chapter_range": [
                        (logical_ordinal - 1) * 3 + 1,
                        logical_ordinal * 3,
                    ],
                    "entry_state_ref": str(
                        versions.get("story_state") or "story:entry"
                    ),
                    "exit_state_spec": {"summary": "commitment creates a wider threat"},
                    "arc_checkpoint_refs": [
                        str(versions.get("arc_plans") or "arc:primary")
                    ],
                }
            ],
        },
        PlanContractType.ARC: {
            "arc_type": "character-conflict",
            "resistance": "denial",
            "escalation": "public consequences",
            "turn": "truth exposed",
            "choice": "accept responsibility",
            "cost": "loss of safety",
            "result": "earned agency",
            "consequence": "new opposition",
            "dependencies": [],
            "closure_conditions": ["choice demonstrated"],
            "cross_volume_scope": arc_scope,
            "narrative_architecture_version": "canonical-narrative-v1",
            "thread_id": "thread:central-conflict",
            "arc_segments": [
                {
                    "segment_id": f"arc-segment:{index}",
                    "volume_plan_version_id": volume_plan_version_id,
                    "narrative_segment_id": "narrative-segment:1",
                    "objective": "denial becomes an accountable choice",
                    "entry_state_ref": "arc-state:denial",
                    "exit_state_spec": {"summary": "the choice has a visible cost"},
                    "status": "PLANNED",
                }
                for index, volume_plan_version_id in enumerate(arc_scope, start=1)
            ],
            "arc_relations": [
                {
                    "relation_id": f"relation:incoming:{logical_key}:{index}",
                    "relation_type": "ENABLES",
                    "source_arc_ref": related_arc_id,
                    "target_arc_ref": logical_key,
                    "trigger_or_condition": (
                        "the related Arc enables the candidate Arc"
                    ),
                }
                for index, related_arc_id in enumerate(
                    command.get("related_arc_plan_version_ids") or (), start=1
                )
            ]
            + [
                {
                    "relation_id": f"relation:outgoing:{logical_key}:{index}",
                    "relation_type": "ENABLES",
                    "source_arc_ref": logical_key,
                    "target_arc_ref": dependent_arc_id,
                    "trigger_or_condition": (
                        "the candidate Arc enables the dependent Arc"
                    ),
                }
                for index, dependent_arc_id in enumerate(
                    command.get("dependent_arc_plan_version_ids") or (), start=1
                )
            ],
        },
        PlanContractType.CHAPTER_GROUP: {
            "local_objective": "Turn private doubt into public commitment",
            "trigger": "evidence arrives",
            "resistance_escalation": ["denial", "countermove"],
            "turn": "ally defects",
            "local_climax": "public choice",
            "information_release": ["hidden cost"],
            "emotion_curve": ["doubt", "pressure", "resolve"],
            "antagonist_actions": ["isolate", "expose"],
            "chapter_function_matrix": [
                _chapter_function_row(
                    group_chapter,
                    *_fixture_chapter_shape(group_chapter),
                    arc_plan_ids,
                )
                for group_chapter in range(chapter_number, chapter_number + 3)
            ],
            "chapter_range": [chapter_number, chapter_number + 2],
            "cost_range": ["social", "material"],
            "primary_arc_ids": [(arc_plan_ids or ("arc:primary",))[0]],
            "secondary_arc_ids": list((arc_plan_ids or ())[1:]),
            "required_arc_contributions": list(arc_plan_ids or ("arc:primary",)),
            "arc_checkpoint_expectations": [
                {
                    "arc_plan_version_id": arc_id,
                    "expectation": "choice advances",
                }
                for arc_id in arc_plan_ids or ("arc:primary",)
            ],
            "narrative_architecture_version": "canonical-narrative-v1",
            "narrative_segment_ref": {
                "volume_plan_version_id": str(
                    versions.get("volume_plan") or parent_version_id
                ),
                "segment_id": "narrative-segment:1",
            },
        },
        PlanContractType.CHAPTER: {
            **_chapter_function_row(
                chapter_number, chapter_function, chapter_hook, arc_plan_ids
            ),
            "actual_arc_contributions": [],
            "title": f"Chapter {chapter_number}: The Door Closes",
            "premise": (
                f"Chapter {chapter_number} forces the protagonist into a witnessed choice."
            ),
            "narrative_architecture_version": "canonical-narrative-v1",
            "narrative_segment_ref": {
                "volume_plan_version_id": str(
                    versions.get("volume_plan") or "volume:1"
                ),
                "segment_id": "narrative-segment:1",
            },
            "chapter_intent": "Force a witnessed choice that advances the central conflict.",
            "arc_schedule": [
                {
                    "arc_plan_version_id": arc_id,
                    "role": "PRIMARY" if index == 0 else "SECONDARY",
                    "segment_id": f"arc-segment:{index + 1}",
                    "expected_movement": (
                        f"{arc_entry_state} becomes {arc_exit_state}"
                    ),
                }
                for index, arc_id in enumerate(arc_plan_ids or ("arc:primary",))
            ],
            "setups": [{"obligation_id": "setup:consequence", "action": "PLANT"}],
            "payoffs": [
                {
                    "obligation_id": "promise:choice",
                    "action": "ADVANCE",
                    "opened_chapter": 1,
                    "due_chapter": max(1, chapter_number + 2),
                }
            ],
            "character_participation": [
                {
                    "character_id": "protagonist",
                    "goal": "preserve agency while protecting the witness",
                    "trajectory_refs": ["character-arc:accountability"],
                    "known_fact_ids": [],
                    "unknown_fact_ids": ["fact:hidden-cost"],
                    "belief_refs": ["belief:safety-through-silence"],
                    "expected_change": "accept a public cost",
                    "causal_trigger": "the witness is exposed by the delayed choice",
                    "entry_emotion": "defensive fear",
                    "exit_emotion": "costly resolve",
                    "resource_changes": ["safety decreases; agency increases"],
                    "relationship_changes": ["the witness gains conditional trust"],
                    "reachable_location_ids": ["location:witness-room"],
                }
            ],
            "knowledge_boundaries": [
                {
                    "layer": "READER_KNOWLEDGE",
                    "subject_id": "reader",
                    "fact_id": "fact:hidden-cost",
                    "status": reader_knowledge_status,
                    "available_from_chapter": chapter_number,
                }
            ],
            "disclosures": [
                {
                    "disclosure_id": f"disclosure:hidden-cost:chapter:{chapter_number}",
                    "fact_id": "fact:hidden-cost",
                    "audience": "READER",
                    "mode": disclosure_mode,
                    "presentation_channel": "CONSEQUENCE",
                    "earliest_chapter": chapter_number,
                }
            ],
            "required_state_transitions": [
                {
                    "state_kind": "character_arc",
                    "entity_key": "protagonist:accountability",
                    "from_state": arc_entry_state,
                    "to_state": arc_exit_state,
                }
            ],
            "reader_experience": {
                **_chapter_function_row(chapter_number, chapter_function, chapter_hook)[
                    "reader_experience"
                ],
                "entry_question": "Will the protagonist stay silent?",
                "exit_question": "Who will exploit the public choice?",
            },
            "scene_plan": [
                {
                    "scene_id": f"chapter:{chapter_number}:scene:1",
                    "scene_version": 1,
                    "scene_group_id": f"chapter:{chapter_number}:group:1",
                    "goal": "make the choice unavoidable",
                    "conflict": "resistance turns private risk into public cost",
                    "participants": ["protagonist"],
                    "pov_character_id": "protagonist",
                    "focalization": "INTERNAL",
                    "story_time": {
                        "timeline_id": "story-time:primary",
                        "start_ordinal": chapter_number * 100,
                        "end_ordinal": chapter_number * 100 + 1,
                        "precision": "ORDERED",
                    },
                    "location_id": "location:witness-room",
                    "narrative_time_relation": "ESTABLISHES",
                    "accessible_knowledge": [],
                    "arc_progress": [str(versions.get("arc_plans") or "arc:primary")],
                    "information_gain": ["fact:hidden-cost"],
                    "state_transitions": ["protagonist:accountability"],
                    "entry_state": arc_entry_state,
                    "exit_state": arc_exit_state,
                    "reader_effect": "relief converts to anticipation",
                    "beats": [
                        {
                            "beat_id": f"chapter:{chapter_number}:scene:1:beat:{index}",
                            "ordinal": index,
                            "function": function,
                            "expected_reader_effect": "rising irreversible pressure",
                        }
                        for index, function in enumerate(
                            ("pressure", "choice", "consequence"), start=1
                        )
                    ],
                }
            ],
            "expected_exit_state": {
                "summary": f"character arc reaches {arc_exit_state}"
            },
        },
    }
    payload.update(by_type[contract_type])
    if parent_version_id:
        payload["parent_version_id"] = parent_version_id
    return payload


def _fixture_character_arc_stage(boundary: int) -> str:
    """Return a deterministic causal stage for scripted multi-chapter fixtures."""

    named = {
        0: "DENIAL",
        1: "COMMITTED",
        2: "CONSEQUENT",
        3: "OWNED",
    }
    return named.get(boundary, f"INTEGRATED_{boundary}")


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _canonical_narrative_provider_properties(
    contract_type: PlanContractType,
    *,
    arc_plan_version_ids: tuple[str, ...] = (),
    arc_relation_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    string = {"type": "string", "minLength": 1}
    string_array = {"type": "array", "items": string}
    state_spec = _strict_object({"summary": string})
    allowed_realization_levels = {
        level.value for level in HORIZON_REALIZATION_LEVELS[PLAN_HORIZON[contract_type]]
    }
    entity_realization_levels = [level.value for level in RealizationLevel]
    authority_ref = _strict_object(
        {
            "project_id": string,
            "book_id": string,
            "authority_role": string,
            "asset_version_id": string,
            "asset_type": string,
            "content_hash": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "domain_type": {
                "type": "string",
                "enum": [
                    "WORLD_INVARIANT",
                    "WORLD_STRUCTURE",
                    "WORLD_STATE",
                    "CHARACTER_IDENTITY",
                    "CHARACTER_STATE",
                    "CHARACTER_TRAJECTORY",
                ],
            },
            "freshness": {"type": "string", "const": "CURRENT"},
            "frozen_by_operation_id": string,
        }
    )
    architecture = {
        "narrative_architecture_version": {
            "type": "string",
            "const": "canonical-narrative-v1",
        },
        "planning_horizon": {
            "type": "string",
            "const": PLAN_HORIZON[contract_type].value,
        },
        "realization_level": {
            "type": "string",
            "enum": sorted(allowed_realization_levels),
        },
        "commitment_contract": {
            "type": "array",
            "minItems": 1,
            "items": _strict_object(
                {
                    "commitment_id": string,
                    "level": {
                        "type": "string",
                        "enum": [
                            "HARD_CONSTRAINT",
                            "SOFT_INTENT",
                            "OPEN_DESIGN_SPACE",
                        ],
                    },
                    "statement": string,
                }
            ),
        },
        "world_realization": {
            "type": "array",
            "minItems": 1,
            "items": _strict_object(
                {
                    "world_id": string,
                    "invariant_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": authority_ref,
                    },
                    "structure_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": authority_ref,
                    },
                    "state_ref": authority_ref,
                    "realization_level": {
                        "type": "string",
                        "enum": entity_realization_levels,
                    },
                    "narrative_relevance": {
                        "type": "string",
                        "enum": ["CURRENT", "NEAR_FUTURE", "FUTURE"],
                    },
                    "visibility": {
                        "type": "string",
                        "enum": ["HIDDEN", "PARTIAL", "VISIBLE", "SCENE_VISIBLE"],
                    },
                    "accessibility": {
                        "type": "string",
                        "enum": ["CLOSED", "RESTRICTED", "ACCESSIBLE"],
                    },
                }
            ),
        },
        "character_realization": {
            "type": "array",
            "minItems": 1,
            "items": _strict_object(
                {
                    "character_id": string,
                    "identity_ref": authority_ref,
                    "state_ref": authority_ref,
                    "trajectory_ref": authority_ref,
                    "scope": {
                        "type": "string",
                        "enum": [item.value for item in PlanContractType],
                    },
                    "reach": {
                        "type": "string",
                        "enum": [
                            "DISTANT",
                            "FUTURE_VOLUME",
                            "CURRENT_VOLUME",
                            "CURRENT_SEGMENT",
                            "CURRENT_CHAPTER",
                            "CURRENT_SCENE",
                        ],
                    },
                    "realization_level": {
                        "type": "string",
                        "enum": entity_realization_levels,
                    },
                    "narrative_relevance": {
                        "type": "string",
                        "enum": ["CURRENT", "NEAR_FUTURE", "FUTURE"],
                    },
                }
            ),
        },
    }
    segment_ref = _strict_object(
        {"volume_plan_version_id": string, "segment_id": string}
    )
    if contract_type is PlanContractType.VOLUME:
        return {
            **architecture,
            "narrative_segments": {
                "type": "array",
                "minItems": 1,
                "items": _strict_object(
                    {
                        "segment_id": string,
                        "objective": string,
                        "chapter_range": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 2,
                            "items": {"type": "integer", "minimum": 1},
                        },
                        "entry_state_ref": string,
                        "exit_state_spec": state_spec,
                        "arc_checkpoint_refs": string_array,
                    }
                ),
            },
        }
    if contract_type is PlanContractType.BOOK:
        character_trajectory = _strict_object(
            {
                "character_id": string,
                "entry_belief": string,
                "target_belief": string,
                "causal_triggers": string_array,
                "power_progression": string_array,
                "relationship_progression": string_array,
                "ending_state": string,
            }
        )
        obligation_window = _strict_object(
            {
                "obligation_id": string,
                "setup_chapter": {"type": "integer", "minimum": 1},
                "payoff_not_before": {"type": "integer", "minimum": 1},
                "payoff_due_by": {"type": "integer", "minimum": 1},
            }
        )
        return {
            **architecture,
            "character_development": {
                "type": "array",
                "minItems": 1,
                "items": character_trajectory,
            },
            "knowledge_disclosure_obligations": _strict_object(
                {
                    "story_truth_ids": string_array,
                    "mystery_ids": string_array,
                    "promise_ids": string_array,
                    "foreshadow_ids": string_array,
                    "obligation_windows": {
                        "type": "array",
                        "items": obligation_window,
                    },
                }
            ),
        }
    if contract_type is PlanContractType.ARC:
        arc_relation_ref = _frozen_arc_ref_schema(arc_relation_refs, string)
        arc_relation = _strict_object(
            {
                "relation_id": string,
                "relation_type": {
                    "type": "string",
                    "enum": ["CAUSES", "ENABLES", "BLOCKS", "REVEALS", "PAYS_OFF"],
                },
                "source_arc_ref": arc_relation_ref,
                "target_arc_ref": arc_relation_ref,
                "trigger_or_condition": string,
            }
        )
        return {
            **architecture,
            "thread_id": string,
            "arc_segments": {
                "type": "array",
                "minItems": 1,
                "items": _strict_object(
                    {
                        "segment_id": string,
                        "volume_plan_version_id": string,
                        "narrative_segment_id": string,
                        "objective": string,
                        "entry_state_ref": string,
                        "exit_state_spec": state_spec,
                        "status": {
                            "type": "string",
                            "enum": ["PLANNED", "ACTIVE", "HELD", "CLOSED"],
                        },
                    }
                ),
            },
            "arc_relations": {"type": "array", "items": arc_relation},
        }
    if contract_type is PlanContractType.CHAPTER_GROUP:
        return {**architecture, "narrative_segment_ref": segment_ref}
    if contract_type is not PlanContractType.CHAPTER:
        return {}
    setup = _strict_object({"obligation_id": string, "action": string})
    payoff = _strict_object(
        {
            "obligation_id": string,
            "action": string,
            "opened_chapter": {"type": "integer", "minimum": 1},
            "due_chapter": {"type": "integer", "minimum": 1},
        }
    )
    scheduled_arc_ref = _frozen_arc_ref_schema(arc_plan_version_ids, string)
    return {
        **architecture,
        "narrative_segment_ref": segment_ref,
        "chapter_intent": string,
        "arc_schedule": {
            "type": "array",
            "minItems": 1,
            "maxItems": min(3, len(arc_plan_version_ids))
            if arc_plan_version_ids
            else 8,
            "items": _strict_object(
                {
                    "arc_plan_version_id": scheduled_arc_ref,
                    "role": {
                        "type": "string",
                        "enum": [
                            "PRIMARY",
                            "SECONDARY",
                            "TOUCH",
                            "SETUP",
                            "PAYOFF",
                            "HOLD",
                        ],
                        "description": (
                            "Choose one dominant role per frozen Arc for the chapter; "
                            "never repeat one Arc for multiple segments or functions."
                        ),
                    },
                    "segment_id": string,
                    "expected_movement": string,
                }
            ),
        },
        "setups": {"type": "array", "items": setup},
        "payoffs": {"type": "array", "items": payoff},
        "character_participation": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": _strict_object(
                {
                    "character_id": string,
                    "goal": string,
                    "trajectory_refs": string_array,
                    "known_fact_ids": string_array,
                    "unknown_fact_ids": string_array,
                    "belief_refs": string_array,
                    "expected_change": string,
                    "causal_trigger": string,
                    "entry_emotion": string,
                    "exit_emotion": string,
                    "resource_changes": string_array,
                    "relationship_changes": string_array,
                    "reachable_location_ids": string_array,
                }
            ),
        },
        "knowledge_boundaries": {
            "type": "array",
            "maxItems": 12,
            "items": _strict_object(
                {
                    "layer": {
                        "type": "string",
                        "enum": [
                            "STORY_TRUTH",
                            "CHARACTER_KNOWLEDGE",
                            "CHARACTER_BELIEF",
                            "READER_KNOWLEDGE",
                        ],
                    },
                    "subject_id": string,
                    "fact_id": string,
                    "status": {
                        "type": "string",
                        "enum": [
                            "TRUE",
                            "FALSE",
                            "UNKNOWN",
                            "HINTED",
                            "SUSPECTED",
                            "KNOWN",
                            "MISDIRECTED",
                            "WITHHELD",
                            "FORGOTTEN",
                            "BELIEVES",
                            "DOUBTS",
                            "DISBELIEVES",
                            "UNCERTAIN",
                        ],
                        "description": (
                            "Typed epistemic status. Reader Knowledge must use: "
                            "HINTED for HINT, SUSPECTED for PARTIAL, MISDIRECTED "
                            "for MISDIRECT, KNOWN for CONFIRM, or WITHHELD for "
                            "WITHHOLD."
                        ),
                    },
                    "available_from_chapter": {
                        "type": "integer",
                        "minimum": 1,
                    },
                }
            ),
        },
        "disclosures": {
            "type": "array",
            "maxItems": 12,
            "items": _strict_object(
                {
                    "disclosure_id": string,
                    "fact_id": string,
                    "audience": {
                        **string,
                        "description": (
                            "Use READER or ALL for a reader-facing Disclosure, or one "
                            "exact character_id for character presentation. Create "
                            "separate Disclosure events for mixed audiences."
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["HINT", "PARTIAL", "MISDIRECT", "CONFIRM", "WITHHOLD"],
                    },
                    "presentation_channel": string,
                    "earliest_chapter": {"type": "integer", "minimum": 1},
                }
            ),
        },
        "required_state_transitions": {
            "type": "array",
            "maxItems": 8,
            "items": _strict_object(
                {
                    "state_kind": {
                        "type": "string",
                        "enum": sorted(CHAPTER_EXECUTION_STATE_KINDS),
                        "description": (
                            "Canonical Narrative State kind accepted by the Chapter "
                            "execution reconciler; never invent a domain-local kind."
                        ),
                    },
                    "entity_key": {
                        **string,
                        "description": (
                            "Exact canonical identity used by extraction: character_id; "
                            "source_id:target_id for relationships; character_id:arc_id "
                            "for character arcs; character_id:fact_id for knowledge; "
                            "otherwise the state kind's "
                            "stable Authority identifier."
                        ),
                    },
                    "from_state": string,
                    "to_state": string,
                }
            ),
        },
        "reader_experience": _strict_object(
            {
                "entry_question": string,
                "target_emotion": string,
                "reward_mode": string,
                "exit_question": string,
            }
        ),
        "scene_plan": {
            "type": "array",
            "minItems": 1,
            "items": _strict_object(
                {
                    "scene_id": string,
                    "scene_version": {"type": "integer", "minimum": 1},
                    "scene_group_id": string,
                    "goal": string,
                    "conflict": string,
                    "participants": string_array,
                    "pov_character_id": string,
                    "focalization": {
                        "type": "string",
                        "enum": ["INTERNAL", "EXTERNAL", "OMNISCIENT"],
                    },
                    "story_time": _strict_object(
                        {
                            "timeline_id": string,
                            "start_ordinal": {"type": "integer", "minimum": 1},
                            "end_ordinal": {"type": "integer", "minimum": 1},
                            "precision": {
                                "type": "string",
                                "enum": ["EXACT", "ORDERED", "RANGE"],
                            },
                        }
                    ),
                    "location_id": string,
                    "narrative_time_relation": {
                        "type": "string",
                        "enum": [
                            "ESTABLISHES",
                            "ADVANCES",
                            "FLASHBACK",
                            "FLASHFORWARD",
                            "PARALLEL",
                            "ELLIPSIS",
                        ],
                    },
                    "accessible_knowledge": string_array,
                    "arc_progress": string_array,
                    "information_gain": string_array,
                    "state_transitions": string_array,
                    "entry_state": string,
                    "exit_state": string,
                    "reader_effect": string,
                    "beats": {
                        "type": "array",
                        "minItems": 1,
                        "items": _strict_object(
                            {
                                "beat_id": string,
                                "ordinal": {"type": "integer", "minimum": 1},
                                "function": string,
                                "expected_reader_effect": string,
                            }
                        ),
                    },
                }
            ),
        },
        "expected_exit_state": state_spec,
    }


def planning_provider_output_schema(
    contract_type: PlanContractType,
    *,
    logical_key: str = "",
    parent_version_id: str = "",
    arc_plan_version_id: str = "",
    related_arc_plan_version_ids: tuple[str, ...] = (),
    dependent_arc_plan_version_ids: tuple[str, ...] = (),
    dependency_version_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """OpenAI-strict provider schema; Planning validation stays authoritative."""

    string = {"type": "string", "minLength": 1}
    string_array = {"type": "array", "items": {"type": "string"}}
    delta = _strict_object({"subject": string, "change": string})
    object_array = {"type": "array", "items": delta}
    dependency_items = (
        {"type": "string", "enum": list(dependency_version_ids)}
        if dependency_version_ids
        else string
    )
    arc_plan_version_ids = tuple(
        dict.fromkeys(
            item
            for item in (arc_plan_version_id, *related_arc_plan_version_ids)
            if item
        )
    )
    canon_dependencies: dict[str, Any] = {
        "type": "array",
        "items": dependency_items,
    }
    if not dependency_version_ids:
        canon_dependencies["maxItems"] = 0
    properties: dict[str, Any] = {
        "contract_id": string,
        "logical_key": (
            {"type": "string", "const": logical_key} if logical_key else string
        ),
        "objective": string,
        "entry_state_ref": string,
        "exit_state_spec": _strict_object({"summary": string}),
        "hard_constraints": string_array,
        "soft_constraints": string_array,
        "required_events": string_array,
        "forbidden_events": string_array,
        "required_payoffs": string_array,
        "forbidden_payoffs": string_array,
        "character_deltas": object_array,
        "world_deltas": object_array,
        "relationship_deltas": object_array,
        "arc_contributions": object_array,
        "canon_dependencies": canon_dependencies,
        "quality_targets": _strict_object(
            {"minimum": {"type": "integer", "minimum": 0, "maximum": 100}}
        ),
        "budget_policy_ref": string,
        "context_profile_ref": string,
    }
    strings = {
        "reader_promise",
        "central_conflict_engine",
        "protagonist_transformation",
        "volume_function",
        "stage_conflict",
        "stage_antagonist",
        "irreversible_change",
        "midpoint",
        "climax",
        "settlement",
        "next_volume_bridge",
        "arc_type",
        "resistance",
        "escalation",
        "turn",
        "choice",
        "cost",
        "result",
        "consequence",
        "local_objective",
        "trigger",
        "local_climax",
        "primary_function",
        "promise_action",
        "foreshadow_action",
        "reward_action",
        "ending_hook",
        "title",
        "premise",
    }
    arrays = {
        "antagonist_escalation",
        "world_evolution",
        "relationship_evolution",
        "theme_evolution",
        "major_turns",
        "long_promise_payoff",
        "risk_register",
        "dependencies",
        "closure_conditions",
        "cross_volume_scope",
        "resistance_escalation",
        "information_release",
        "emotion_curve",
        "antagonist_actions",
        "cost_range",
        "secondary_functions",
        "prohibited_outcomes",
        "primary_arc_ids",
        "secondary_arc_ids",
    }
    integer_arrays = {"climax_distribution", "chapter_range"}
    for field in TYPE_FIELDS[contract_type]:
        if field in strings:
            properties[field] = string
        elif field in arrays:
            properties[field] = string_array
        elif field == "ending_contract":
            properties[field] = _strict_object({"outcome": string})
        elif field == "length_strategy":
            properties[field] = _strict_object(
                {"target_chapters": {"type": "integer", "minimum": 1}}
            )
        elif field == "required_state_delta":
            properties[field] = _strict_object({"summary": string})
        elif field == "volume_skeleton":
            properties[field] = {
                "type": "array",
                "items": _strict_object(
                    {
                        "volume": {"type": "integer", "minimum": 1},
                        "function": string,
                    }
                ),
            }
        elif field == "required_arc_contributions":
            arc_ref = _frozen_arc_ref_schema(arc_plan_version_ids, string)
            properties[field] = {
                "type": "array",
                "minItems": 1,
                "items": _strict_object(
                    {"arc_plan_version_id": arc_ref, "contribution": string}
                ),
            }
            if arc_plan_version_ids:
                properties[field]["maxItems"] = min(3, len(arc_plan_version_ids))
        elif field in integer_arrays:
            properties[field] = {
                "type": "array",
                "items": {"type": "integer"},
            }
            if field == "chapter_range":
                properties[field].update({"minItems": 2, "maxItems": 2})
        elif field == "chapter_number":
            properties[field] = {"type": "integer", "minimum": 1}
        elif field == "chapter_function_matrix":
            properties[field] = {
                "type": "array",
                "minItems": 3,
                "maxItems": 8,
                "items": _strict_object(
                    {
                        "chapter_number": {"type": "integer", "minimum": 1},
                        "primary_function": string,
                        "secondary_functions": string_array,
                        "required_state_delta": _strict_object({"summary": string}),
                        "required_arc_contributions": {
                            "type": "array",
                            "minItems": 1,
                            "items": _strict_object(
                                {
                                    "arc_plan_version_id": string,
                                    "contribution": string,
                                }
                            ),
                        },
                        "promise_action": string,
                        "foreshadow_action": string,
                        "reward_action": string,
                        "ending_hook": string,
                        "prohibited_outcomes": string_array,
                        "narrative_density": {
                            "type": "string",
                            "enum": ["LOW", "MEDIUM", "HIGH"],
                        },
                        "reader_experience": _strict_object(
                            {
                                "target_emotion": string,
                                "reward_mode": string,
                            }
                        ),
                        "arc_cadence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 3,
                            "items": _strict_object(
                                {
                                    "arc_plan_version_id": string,
                                    "action": {
                                        "type": "string",
                                        "enum": [
                                            "ADVANCE",
                                            "TOUCH",
                                            "DORMANT",
                                            "REACTIVATE",
                                            "SETUP",
                                            "PAYOFF",
                                        ],
                                    },
                                }
                            ),
                        },
                        "obligation_actions": {
                            "type": "array",
                            "items": _strict_object(
                                {
                                    "obligation_id": string,
                                    "action": {
                                        "type": "string",
                                        "enum": ["SETUP", "ADVANCE", "PAYOFF"],
                                    },
                                    "due_chapter": {
                                        "type": "integer",
                                        "minimum": 1,
                                    },
                                }
                            ),
                        },
                    }
                ),
            }
        else:
            raise ValueError(f"Planning Provider schema missing field: {field}")
    properties.update(
        _canonical_narrative_provider_properties(
            contract_type,
            arc_plan_version_ids=arc_plan_version_ids,
            arc_relation_refs=(
                tuple(
                    dict.fromkeys(
                        item
                        for item in (
                            logical_key,
                            *related_arc_plan_version_ids,
                            *dependent_arc_plan_version_ids,
                        )
                        if item
                    )
                )
                if contract_type is PlanContractType.ARC
                else ()
            ),
        )
    )
    if contract_type not in {PlanContractType.BOOK, PlanContractType.ARC}:
        properties["parent_version_id"] = (
            {"type": "string", "const": parent_version_id}
            if parent_version_id
            else string
        )
    if contract_type is PlanContractType.CHAPTER:
        properties["title"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 120,
            "description": (
                "Concise reader-facing chapter title; never a planning instruction."
            ),
        }
        properties["premise"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 320,
            "description": (
                "Concise reader-facing chapter synopsis; never a planning, review, "
                "or Authority instruction."
            ),
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _frozen_arc_ref_schema(
    arc_plan_version_ids: tuple[str, ...], fallback: dict[str, Any]
) -> dict[str, Any]:
    if len(arc_plan_version_ids) == 1:
        return {"type": "string", "const": arc_plan_version_ids[0]}
    if arc_plan_version_ids:
        return {"type": "string", "enum": list(arc_plan_version_ids)}
    return fallback


@dataclass(frozen=True, slots=True)
class _PlanningExecutionBinding:
    request: ExecutionRequest
    route_snapshot: RouteSnapshot
    input_manifest: InputManifest


class _PlanningGatewayEffectAdapter:
    """Pure execution bridge for one already-frozen Planning request."""

    production_execution_gateway_backed = True

    def __init__(
        self,
        *,
        transport: Any,
        session: Any,
        binding: _PlanningExecutionBinding,
    ) -> None:
        self.transport = transport
        self.session = session
        self.binding = binding
        self.provider = str(transport.provider)
        self.reconciliation_mode = str(transport.reconciliation_mode)
        self.capability_profile: ProviderCapabilityProfile = (
            transport.capability_profile
        )

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        request = self.binding.request
        if (
            stable_idempotency_key != request.stable_idempotency_key
            or capability != request.capability
            or str(request_payload.get("external_effect_id") or "")
            != request.external_effect_id
        ):
            raise ExternalEffectAdapterError(
                "Planning execution differs from its frozen request",
                request_sent=False,
            )
        request_sent = False
        try:
            handle = self.session.gateway.submit(request)
            request_sent = True
            result = self.session.gateway.reconcile(handle)
        except Exception as exc:
            raise ExternalEffectAdapterError(
                f"Planning gateway execution failed: {type(exc).__name__}: {exc}",
                request_sent=request_sent,
            ) from exc
        record = self.session.evidence_store.get_record(request.execution_id)
        evidence: dict[str, Any] = {
            "provider_id": self.binding.route_snapshot.model_provider,
            "model_id": self.binding.route_snapshot.model_id,
            "prompt_version": self.binding.input_manifest.prompt_bundle_version,
            "skill_version": self.binding.input_manifest.skill_bundle_version,
            "real_model_call": handle.transport
            in {
                ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            },
            "fixture_protocol_only": (
                handle.transport is ExecutionRuntimeClass.SCRIPTED_FIXTURE
            ),
            "production_verified": False,
            "production_execution": {
                "execution_request": request.to_dict(),
                "execution_handle": handle.to_dict(),
                "execution_result": result.to_dict(),
                "route_snapshot": self.binding.route_snapshot.to_dict(),
                "input_manifest": self.binding.input_manifest.to_dict(),
                "process_evidence": dict(record.raw_evidence),
            },
        }
        capability_evidence = record.raw_evidence.get("capability_evidence")
        if isinstance(capability_evidence, Mapping):
            evidence["capability_runtime"] = dict(capability_evidence)
        if result.normalized_output_ref:
            evidence["result"] = self.session.evidence_store.read_evidence(
                str(result.normalized_output_ref)
            )
        if result.usage_receipt_ref:
            evidence["usage"] = self.session.evidence_store.read_evidence(
                str(result.usage_receipt_ref)
            )
        if result.cost_receipt_ref:
            evidence["cost"] = self.session.evidence_store.read_evidence(
                str(result.cost_receipt_ref)
            )
        outcome = {
            ExecutionOutcome.SUCCEEDED: "success",
            ExecutionOutcome.RETRYABLE_FAILURE: "retryable_failure",
            ExecutionOutcome.TIMED_OUT: "retryable_failure",
            ExecutionOutcome.CORRUPT_RESULT: "retryable_failure",
            ExecutionOutcome.FINAL_FAILURE: "final_failure",
            ExecutionOutcome.CANCELLED: "cancelled",
        }.get(result.outcome, "unknown")
        return ProviderResult(
            outcome,
            handle.backend_execution_id,
            evidence,
            handle.provider_request_id or "",
        )

    def query(self, **kwargs: Any) -> ProviderResult:
        return self.execute(**kwargs)

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        request = self.binding.request
        handle = self.session.gateway.submit(request)
        cancellation = self.session.gateway.cancel(handle, "Planning cancellation")
        return ProviderResult(
            "cancelled",
            handle.backend_execution_id,
            {"production_execution_cancellation": cancellation.to_dict()},
            provider_request_id,
        )


@dataclass(slots=True)
class _PlanningPepPort:
    database_url: str
    worker_id: str
    lease_seconds: int
    context: EffectCommandContext
    effect_id: str
    stable_key: str
    reservation_id: str
    binding: _PlanningExecutionBinding
    adapter: _PlanningGatewayEffectAdapter
    recovered_completion: dict[str, Any] | None
    writer: AuthorityAssetWriter
    post_provider_fault_injector: Callable[[str], None]

    external_effect_backed = True
    production_execution_gateway_backed = True

    def execute(self, command: DomainExecutionCommand) -> DomainExecutionCandidate:
        if command.capability != self.binding.request.capability:
            raise KernelError(
                "PLANNING_PEP_CAPABILITY_DRIFT",
                "Planning command differs from the frozen execution capability",
            )
        dispatched = self.recovered_completion or dispatch_external_effect(
            self.database_url,
            self.context,
            effect_id=self.effect_id,
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            adapter=self.adapter,
        )
        recovered_completion = self.recovered_completion is not None
        if recovered_completion:
            dispatched = {**dispatched, "outcome": "success"}
        if dispatched["outcome"] != "success":
            resolve_provider_budget_failure(
                self.database_url,
                reservation_id=self.reservation_id,
                project_id=self.context.project_id,
            )
            outcome = str(dispatched.get("outcome") or "unknown")
            code = (
                "MODEL_EFFECT_RETRYABLE_PLANNING"
                if outcome in {"retryable_failure", "not_found"}
                else "MODEL_EFFECT_FINAL_PLANNING"
            )
            raise KernelError(code, f"Planning provider outcome was {outcome}")
        evidence = dispatched.get("provider_evidence")
        if not isinstance(evidence, Mapping):
            raise KernelError(
                "PLANNING_MODEL_EVIDENCE_INVALID",
                "Planning provider returned no evidence",
            )
        raw = evidence.get("result")
        usage = evidence.get("usage")
        cost = evidence.get("cost")
        production = evidence.get("production_execution")
        if not all(
            (
                isinstance(raw, Mapping),
                isinstance(usage, Mapping),
                isinstance(cost, Mapping),
                isinstance(production, Mapping),
            )
        ):
            raise KernelError(
                "PLANNING_MODEL_EVIDENCE_INVALID",
                "Planning provider evidence lacks result, usage, cost, or receipt",
            )
        amount = str(cost.get("amount") or "0")
        total_tokens = int(usage.get("total_tokens") or 0)
        settle_provider_budget(
            self.database_url,
            reservation_id=self.reservation_id,
            project_id=self.context.project_id,
            actual_amount=amount,
            actual_tokens=total_tokens,
            evidence={
                "provider_id": str(evidence.get("provider_id") or ""),
                "model_id": str(evidence.get("model_id") or ""),
                "real_model_call": bool(evidence.get("real_model_call")),
                "fixture": bool(evidence.get("fixture_protocol_only")),
            },
        )
        try:
            self.post_provider_fault_injector(
                "after_measured_usage_before_candidate_acceptance"
            )
        except KernelError as exc:
            self._record_model_evidence(
                evidence=evidence,
                usage=usage,
                cost=cost,
                amount=amount,
                total_tokens=total_tokens,
                accepted_candidate=False,
                recovered_completion=recovered_completion,
                failure={"code": exc.code, "message": str(exc)},
            )
            raise
        self._record_model_evidence(
            evidence=evidence,
            usage=usage,
            cost=cost,
            amount=amount,
            total_tokens=total_tokens,
            accepted_candidate=True,
            recovered_completion=recovered_completion,
        )
        execution_result = production.get("execution_result")
        if not isinstance(execution_result, Mapping):
            raise KernelError(
                "PLANNING_PEP_EVIDENCE_INCOMPLETE",
                "Planning PEP result lacks an execution result",
            )
        required = {
            "output": execution_result.get("output_manifest_ref"),
            "validation": execution_result.get("validation_report_ref"),
            "usage": execution_result.get("usage_receipt_ref"),
            "cost": execution_result.get("cost_receipt_ref"),
        }
        if any(not value for value in required.values()):
            raise KernelError(
                "PLANNING_PEP_EVIDENCE_INCOMPLETE",
                "Planning PEP result lacks required manifests",
            )
        request = self.binding.request
        handle = production.get("execution_handle")
        backend_id = (
            str(handle.get("backend_id") or "") if isinstance(handle, Mapping) else ""
        )
        return DomainExecutionCandidate(
            candidate_kind=CandidateKind.GENERATION,
            raw_output=dict(raw),
            evidence=DomainExecutionEvidence(
                execution_id=request.execution_id,
                operation_id=request.operation_id,
                attempt_id=request.attempt_id,
                fencing_token=request.fencing_token,
                capability=request.capability,
                backend_id=backend_id,
                route_snapshot_id=request.route_snapshot_id,
                input_manifest_ref=request.input_manifest_ref,
                output_manifest_ref=str(required["output"]),
                validation_manifest_ref=str(required["validation"]),
                usage_receipt_ref=str(required["usage"]),
                cost_receipt_ref=str(required["cost"]),
                fixture_protocol_only=bool(evidence.get("fixture_protocol_only")),
                real_model_call=bool(evidence.get("real_model_call")),
                production_verified=False,
                provider_id=str(evidence.get("provider_id") or ""),
                model_id=str(evidence.get("model_id") or ""),
                external_receipt_ref=self.effect_id,
            ),
        )

    def _record_model_evidence(
        self,
        *,
        evidence: Mapping[str, Any],
        usage: Mapping[str, Any],
        cost: Mapping[str, Any],
        amount: str,
        total_tokens: int,
        accepted_candidate: bool,
        recovered_completion: bool,
        failure: Mapping[str, Any] | None = None,
    ) -> None:
        self._record_evidence(
            "model_call_log",
            {
                **dict(evidence),
                "candidate_accepted": accepted_candidate,
                "provider_invoked_this_attempt": not recovered_completion,
                "recovered_external_effect_success": recovered_completion,
                "post_provider_failure": dict(failure or {}),
            },
        )
        if recovered_completion:
            return
        self._record_evidence(
            "cost_ledger",
            {
                "availability": "AVAILABLE",
                "amount": amount,
                "currency": str(cost.get("currency") or "USD"),
                "total_tokens": total_tokens,
                "usage": dict(usage),
                "cost": dict(cost),
                "candidate_accepted": accepted_candidate,
                "provider_invoked_this_attempt": True,
                "recovered_external_effect_success": False,
                "post_provider_failure": dict(failure or {}),
            },
        )

    def _record_evidence(self, asset_type: str, content: dict[str, Any]) -> None:
        request = self.binding.request
        logical_ref = (
            f"runs/{asset_type}s/{request.operation_id}-{request.attempt_id}-"
            f"{request.stage}.json"
        )
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=request.project_id,
                asset_id=f"{asset_type}:{request.operation_id}:{request.attempt_id}",
                asset_type=asset_type,
                schema_version=f"{asset_type}.v1",
                logical_ref=logical_ref,
                category="runs",
                output_key=f"{asset_type}.{request.stage}",
                role="model_evidence"
                if asset_type == "model_call_log"
                else "cost_evidence",
                content={
                    "type": asset_type,
                    "operation_id": request.operation_id,
                    "project_id": request.project_id,
                    "stage": request.stage,
                    **content,
                },
                qualification_policy=f"{asset_type}-evidence-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
            )
        )


class PostgresPlanningExecutionPreparer:
    """Freeze Planning-domain PEP contracts on the current Authority Attempt."""

    production_execution_gateway_backed = True

    def __init__(
        self,
        database_url: str,
        *,
        execution_transport: Any,
        planning_route: PlanningExecutionRoute,
        worker_id: str,
        max_cost_per_call: str = "0",
        budget_caps: Mapping[str, str] | None = None,
        lease_seconds: int = 60,
        post_provider_fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not worker_id or lease_seconds <= 0:
            raise ValueError(
                "Planning execution requires PostgreSQL and worker identity"
            )
        if not getattr(
            execution_transport, "production_execution_gateway_backed", False
        ):
            raise ValueError("Planning execution requires the Production Gateway")
        self.database_url = database_url
        self.execution_transport = execution_transport
        self.planning_route = planning_route
        self.worker_id = worker_id
        self.max_cost_per_call = max_cost_per_call
        self.budget_caps = dict(budget_caps or {})
        self.lease_seconds = lease_seconds
        self.post_provider_fault_injector = post_provider_fault_injector or (
            lambda _checkpoint: None
        )
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)
        self.pack_runtime = CapabilityPackRuntimeResolver(database_url)

    def prepare(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
        attempt_snapshot: CapabilityPackAttemptSnapshot,
    ) -> PreparedPlanningExecution:
        if worker_id != self.worker_id:
            raise KernelError(
                "PLANNING_WORKER_IDENTITY_DRIFT",
                "Planning preparer belongs to another worker",
            )
        if command.generator_operation_name not in _PLANNING_STAGES:
            raise KernelError(
                "PLANNING_STAGE_UNSUPPORTED", "Planning stage is not governed"
            )
        capability = default_capability_registry().resolve(definition.capability)
        frozen = attempt_snapshot.execution_snapshot
        if frozen.execution_capability_id != capability.capability_id.value:
            raise KernelError(
                "PLANNING_CAPABILITY_PACK_NODE_INVALID",
                "Planning Pack capability differs from the Generator",
            )
        context_document, input_documents = self._context_bundle(
            operation_id=operation_id,
            attempt_id=attempt_id,
            command=command,
            inputs=inputs,
        )
        pack_materialization = self.pack_runtime.materialize_attempt_artifacts(
            attempt_snapshot
        )
        tools = json.loads(frozen.tool_policy_payload_json)
        allowed_tools = self._allowed_tools(tools, command.generator_operation_name)
        if allowed_tools != ("model.provider.invoke",):
            raise KernelError(
                "PLANNING_CAPABILITY_TOOL_UNAUTHORIZED",
                "Planning Codex execution permits only model.provider.invoke",
            )
        output_schema = planning_provider_output_schema(
            PlanContractType(command.planning_scope.value),
            logical_key=command.logical_key,
            parent_version_id=command.parent_version_id,
            arc_plan_version_id=str(command.input_versions.get("arc_plans") or ""),
            related_arc_plan_version_ids=command.related_arc_plan_version_ids,
            dependent_arc_plan_version_ids=command.dependent_arc_plan_version_ids,
            dependency_version_ids=(
                *tuple(command.input_versions.values()),
                *command.related_arc_plan_version_ids,
                *command.dependent_arc_plan_version_ids,
            ),
        )
        output_schema_ref = (
            "schema:planning-provider-output:"
            + command.planning_scope.value.lower()
            + (
                ":v4"
                if command.planning_scope.value == PlanContractType.CHAPTER.value
                else ":v2"
                if command.planning_scope.value == PlanContractType.CHAPTER_GROUP.value
                else ":v1"
            )
        )
        materialization = {
            "schema_version": "novelos.planning_capability_materialization.v1",
            "stage": command.generator_operation_name,
            "capability_requirement": definition.capability,
            "attempt_snapshot": {
                "snapshot_id": attempt_snapshot.snapshot_id,
                "snapshot_hash": attempt_snapshot.snapshot_hash,
                "operation_id": operation_id,
                "attempt_id": attempt_id,
                "execution_fencing_token": fencing_token,
            },
            "pack_identity": {
                "pack_id": frozen.pack_id,
                "pack_version": frozen.pack_version,
                "manifest_hash": frozen.manifest_hash,
                "compilation_hash": frozen.compilation_hash,
                "catalog_snapshot_hash": frozen.catalog_snapshot_hash,
                "binding_set_id": frozen.binding_set_id,
                "binding_set_hash": frozen.binding_set_hash,
            },
            "pack_artifacts": pack_materialization.to_dict(include_content=True),
            "pack_artifact_materialization_hash": (
                pack_materialization.materialization_hash
            ),
            "context_selection": [
                {
                    "artifact_ref": f"asset-version:{context_document.asset_version_id}",
                    "asset_version_id": context_document.asset_version_id,
                    "artifact_type": "context_bundle",
                    "content_hash": context_document.content_hash,
                    "schema_version": "novelos.planning_context_bundle.v1",
                    "source_eligibility": "PRODUCTION_ELIGIBLE",
                    "content": context_document.content,
                }
            ],
            "knowledge_selection": [
                item.to_dict(include_content=True)
                for item in pack_materialization.required_knowledge
            ],
            "tool_permissions": {
                "default": str(tools.get("default") or ""),
                "allowed": list(allowed_tools),
                "denied": [],
                "invoked": ["model.provider.invoke"],
                "governing_policy_ref": frozen.tool_policy_ref,
                "governing_policy_hash": frozen.tool_policy_hash,
            },
            "output_schema": {
                "ref": output_schema_ref,
                "content_hash": canonical_hash(output_schema),
                "content": output_schema,
            },
        }
        materialization["materialization_hash"] = canonical_hash(materialization)
        materialization_ref = (
            "production_execution/capability_materializations/"
            + _token(f"{command.project_id}:{operation_id}:{attempt_id}:planning")
        )
        effect_context = EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=worker_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        stable_key = f"{operation_id}:{definition.capability}:planning-pep-v2"
        planning_route = self.planning_route
        authoritative_envelope = build_planning_constraint_envelope(
            project_id=command.project_id,
            book_id=command.book_id,
            generation_operation_id=operation_id,
            generator_operation_name=command.generator_operation_name,
            frozen_inputs=inputs,
            input_contents={
                item.role: dict(document.content)
                for item, document in zip(
                    inputs, input_documents[: len(inputs)], strict=True
                )
            },
            candidate_payload={},
        )
        stable_request_payload = {
            "stage": command.generator_operation_name,
            "input": {
                "planning_command": {
                    "project_id": command.project_id,
                    "book_id": command.book_id,
                    "generation_operation_id": operation_id,
                    "logical_key": command.logical_key,
                    "planning_scope": command.planning_scope.value,
                    "parent_version_id": command.parent_version_id,
                    "input_versions": dict(command.input_versions),
                    "arc_scope_volume_plan_version_ids": list(
                        command.arc_scope_volume_plan_version_ids
                    ),
                    "related_arc_plan_version_ids": list(
                        command.related_arc_plan_version_ids
                    ),
                    "dependent_arc_plan_version_ids": list(
                        command.dependent_arc_plan_version_ids
                    ),
                    "change_evidence_version_ids": list(
                        command.change_evidence_version_ids
                    ),
                    "governance_action_version_ids": list(
                        command.governance_action_version_ids
                    ),
                    "repair_number": command.repair_number,
                    "repair_reason": command.repair_reason,
                },
                "frozen_inputs": [
                    {
                        "role": item.role,
                        "asset_version_id": item.asset_version_id,
                        "content_hash": item.content_hash,
                        "asset_type": item.asset_type,
                    }
                    for item in inputs
                ],
                "authoritative_narrative_load": {
                    "narrative_load_policy": authoritative_envelope[
                        "narrative_load_policy"
                    ],
                    "narrative_load_policy_lineage": authoritative_envelope[
                        "narrative_load_policy_lineage"
                    ],
                    "narrative_load_projection": authoritative_envelope[
                        "narrative_load_projection"
                    ],
                },
            },
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
            "operation_id": operation_id,
        }
        existing_intent = read_external_effect_intent(
            self.database_url,
            effect_context,
            effect_type="model.invoke",
            stable_idempotency_key=stable_key,
        )
        if existing_intent is None:
            materialization_document = self._ensure_contract(
                operation_id=operation_id,
                project_id=command.project_id,
                logical_ref=materialization_ref,
                asset_type="capability_materialization_manifest",
                contract=materialization,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            request_payload = {
                **stable_request_payload,
                "_production_execution": {
                    "capability_runtime": {
                        "snapshot_id": attempt_snapshot.snapshot_id,
                        "snapshot_hash": attempt_snapshot.snapshot_hash,
                        "materialization_asset_version_id": (
                            materialization_document.asset_version_id
                        ),
                        "materialization_content_hash": (
                            materialization_document.content_hash
                        ),
                        "materialization_hash": materialization["materialization_hash"],
                    }
                },
            }
        else:
            request_payload = dict(existing_intent["request_payload"])
            frozen_request = {
                key: value
                for key, value in request_payload.items()
                if key != "_production_execution"
            }
            metadata = request_payload.get("_production_execution")
            capability_runtime = (
                metadata.get("capability_runtime")
                if isinstance(metadata, Mapping)
                else None
            )
            if (
                frozen_request != stable_request_payload
                or existing_intent["provider"] != self.execution_transport.provider
                or existing_intent["capability"] != definition.capability
                or int(existing_intent["max_attempts"])
                != PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS
                or not isinstance(capability_runtime, Mapping)
                or str(capability_runtime.get("snapshot_hash") or "")
                != attempt_snapshot.snapshot_hash
            ):
                raise KernelError(
                    "PLANNING_EFFECT_INTENT_DRIFT",
                    "Planning retry differs from the first frozen Provider intent",
                )
            materialization_document = self.query.require(
                project_id=command.project_id,
                asset_version_id=str(
                    capability_runtime.get("materialization_asset_version_id") or ""
                ),
            )
            materialization = materialization_document.content.get(
                "contract", materialization_document.content
            )
            if (
                materialization_document.asset_type
                != "capability_materialization_manifest"
                or materialization_document.content_hash
                != str(capability_runtime.get("materialization_content_hash") or "")
                or not isinstance(materialization, Mapping)
                or str(materialization.get("materialization_hash") or "")
                != str(capability_runtime.get("materialization_hash") or "")
            ):
                raise KernelError(
                    "CAPABILITY_PACK_SNAPSHOT_INCONSISTENT",
                    "Planning retry materialization differs from the frozen Effect",
                )
        effect = plan_external_effect(
            self.database_url,
            effect_context,
            effect_type="model.invoke",
            provider=self.execution_transport.provider,
            capability=definition.capability,
            stable_idempotency_key=stable_key,
            request_payload=request_payload,
            max_attempts=PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS,
            reversible=False,
            completion_policy="synchronous_final",
            model_id=planning_route.model_profile.model_id,
            request_timeout_seconds=STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
            reconciliation_mode=self.execution_transport.reconciliation_mode,
            provider_capability_profile=(
                self.execution_transport.capability_profile.to_dict()
            ),
        )
        effect_id = str(effect["external_effect_id"])
        effect_context = EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=worker_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        recovered_completion = read_succeeded_external_effect(
            self.database_url,
            effect_context,
            effect_id=effect_id,
        )
        if recovered_completion is None:
            reservation = reserve_provider_budget(
                self.database_url,
                BudgetReservationRequest(
                    operation_id=operation_id,
                    external_effect_id=effect_id,
                    project_id=command.project_id,
                    stable_idempotency_key=(
                        f"budget:{stable_key}:attempt:{attempt_id}"
                    ),
                    provider=self.execution_transport.provider,
                    currency="USD",
                    estimated_amount=self.max_cost_per_call,
                    estimated_tokens=0,
                    caps=self.budget_caps,
                ),
            )
            reservation_id = str(reservation["reservation_id"])
        else:
            reservation_id = str(recovered_completion["budget_reservation_id"])
        binding, contract_documents = self._execution_binding(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            command=command,
            definition=definition,
            capability=capability,
            planning_route=planning_route,
            context_document=context_document,
            input_documents=input_documents,
            effect_id=effect_id,
            stable_key=stable_key,
            reservation_id=reservation_id,
            output_schema_ref=output_schema_ref,
            frozen=frozen,
        )
        session = self.execution_transport.session_for_project(command.project_id)
        adapter = _PlanningGatewayEffectAdapter(
            transport=self.execution_transport,
            session=session,
            binding=binding,
        )
        return PreparedPlanningExecution(
            execution_port=_PlanningPepPort(
                database_url=self.database_url,
                worker_id=worker_id,
                lease_seconds=self.lease_seconds,
                context=effect_context,
                effect_id=effect_id,
                stable_key=stable_key,
                reservation_id=reservation_id,
                binding=binding,
                adapter=adapter,
                recovered_completion=recovered_completion,
                writer=self.writer,
                post_provider_fault_injector=self.post_provider_fault_injector,
            ),
            context_bundle_asset_version_id=context_document.asset_version_id,
            context_bundle_hash=context_document.content_hash,
            route_snapshot_ref=binding.route_snapshot.route_snapshot_id,
            route_snapshot_hash=contract_documents["route"].content_hash,
            input_manifest_ref=binding.input_manifest.manifest_id,
            input_manifest_hash=contract_documents["input"].content_hash,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            prompt_bundle_hash=frozen.prompt_bundle_hash,
            skill_bundle_ref=frozen.skill_bundle_ref,
            skill_bundle_hash=frozen.skill_bundle_hash,
            tool_permission_snapshot_ref=frozen.tool_policy_ref,
            tool_permission_snapshot_hash=frozen.tool_policy_hash,
            context_policy_ref=frozen.context_policy_ref,
            context_policy_hash=frozen.context_policy_hash,
            validation_policy_ref=frozen.evaluation_policy_ref,
            commit_policy_ref=capability.commit_policy_ref,
            timeout_policy_ref=capability.timeout_policy_ref,
        )

    def _execution_binding(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        command: StoryPlanningGenerationCommand,
        definition: GeneratorDefinition,
        capability: Any,
        planning_route: PlanningExecutionRoute,
        context_document: AuthorityAssetDocument,
        input_documents: tuple[AuthorityAssetDocument, ...],
        effect_id: str,
        stable_key: str,
        reservation_id: str,
        output_schema_ref: str,
        frozen: Any,
    ) -> tuple[_PlanningExecutionBinding, dict[str, AuthorityAssetDocument]]:
        graph = self._operation_graph(operation_id, command.project_id)
        suffix = command.planning_scope.value.lower()
        profile_id = f"planning.{suffix}.default"
        profile = ModelProfile(
            profile_id=profile_id,
            profile_version=1,
            backend_id=planning_route.model_profile.backend_id,
            runtime_class=planning_route.model_profile.runtime_class,
            model_provider=planning_route.model_profile.model_provider,
            model_id=planning_route.model_profile.model_id,
            reasoning_effort=planning_route.model_profile.reasoning_effort,
            timeout_policy_ref=capability.timeout_policy_ref,
            workspace_policy_ref="workspace:story-planning:v1",
            output_policy_ref=output_schema_ref,
            fallback_policy="FAIL_CLOSED",
            status=planning_route.model_profile.status,
            capability_probe_ref=planning_route.model_profile.capability_probe_ref,
        )
        policy = RoutePolicy(
            policy_id=f"planning.{suffix}.route",
            policy_version=1,
            default_model_profile_id=profile_id,
            allowed_model_profile_ids=(profile_id,),
            rule_set_ref=f"route-rules:planning:{suffix}:v1",
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=f"planning.{suffix}.fail-closed",
            fallback_policy_version=1,
            reasoning_downgrade_policy="PROHIBITED",
            status="ACTIVE",
        )
        fallback = FallbackPolicy.fail_closed(
            policy.fallback_policy_ref, policy.fallback_policy_version
        )
        target = TargetScope(
            scope_kind=command.planning_scope.value.lower(),
            scope_id=command.logical_key,
            project_id=command.project_id,
            book_id=command.book_id,
        )
        context_ref = f"asset-version:{context_document.asset_version_id}"
        route_ref = "production_execution/routes/" + _token(
            f"{command.project_id}:{operation_id}:{attempt_id}:planning"
        )
        input_ref = "production_execution/inputs/" + _token(
            f"{command.project_id}:{operation_id}:{attempt_id}:planning"
        )
        pointers = (
            ArtifactPointer(
                artifact_ref=context_ref,
                asset_version_id=context_document.asset_version_id,
                artifact_type="context_bundle",
                content_hash=context_document.content_hash,
                schema_version="novelos.planning_context_bundle.v1",
                source_eligibility="PRODUCTION_ELIGIBLE",
            ),
            *tuple(
                ArtifactPointer(
                    artifact_ref=f"asset-version:{document.asset_version_id}",
                    asset_version_id=document.asset_version_id,
                    artifact_type=document.asset_type,
                    content_hash=document.content_hash,
                    schema_version=f"{document.asset_type}.v1",
                    source_eligibility="PRODUCTION_ELIGIBLE",
                )
                for document in input_documents
            ),
        )
        manifest = InputManifest(
            manifest_id=input_ref,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=command.project_id,
            book_id=command.book_id,
            target_scope=target,
            context_bundle_ref=context_ref,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            skill_bundle_ref=frozen.skill_bundle_ref,
            context_bundle_version=context_document.asset_version_id,
            prompt_bundle_version=frozen.prompt_bundle_ref,
            skill_bundle_version=frozen.skill_bundle_ref,
            canon_snapshot_version=str(
                command.input_versions.get("canon_snapshot") or "none"
            ),
            story_state_version=str(
                command.input_versions.get("story_state") or "none"
            ),
            planning_version=command.parent_version_id or command.logical_key,
            quality_profile_version=str(
                command.input_versions.get("quality_trend") or "none"
            ),
            source_policy_ref=capability.source_policy_ref,
            source_eligibility="PRODUCTION_ELIGIBLE",
            canon_version_refs=tuple(
                f"asset-version:{document.asset_version_id}"
                for document in input_documents
                if "canon" in document.asset_type
            ),
            arc_version_refs=tuple(
                f"asset-version:{document.asset_version_id}"
                for document in input_documents
                if "arc" in document.asset_type
            ),
            input_artifacts=pointers,
            read_set=tuple(item.artifact_ref for item in pointers),
        )
        route = RouteSnapshot(
            route_snapshot_id=route_ref,
            route_decision_id=f"route-decision:{_token(route_ref)}",
            operation_id=operation_id,
            attempt_id=attempt_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            backend_id=profile.backend_id,
            backend_version=planning_route.backend_version,
            runtime_host_id=planning_route.runtime_host_id,
            auth_profile_ref=planning_route.auth_profile_ref,
            model_profile_id=profile.profile_id,
            model_profile_version=profile.profile_version,
            model_profile_hash=profile.contract_hash,
            route_policy_hash=policy.contract_hash,
            model_provider=profile.model_provider,
            model_id=profile.model_id,
            requested_reasoning_effort=profile.reasoning_effort,
            reasoning_effort=profile.reasoning_effort,
            prompt_bundle_ref=frozen.prompt_bundle_ref,
            skill_bundle_ref=frozen.skill_bundle_ref,
            context_bundle_ref=context_ref,
            output_schema_ref=output_schema_ref,
            release_sha=planning_route.release_sha,
            fallback_policy_ref=fallback.policy_id,
            fallback_policy_version=fallback.policy_version,
        )
        profile_doc = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=f"production_execution/model_profiles/{profile_id}/v1",
            asset_type="model_profile",
            contract=profile.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        del profile_doc
        self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=f"production_execution/route_policies/{policy.policy_id}/v1",
            asset_type="route_policy",
            contract=policy.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=(
                f"production_execution/fallback_policies/{fallback.policy_id}/v1"
            ),
            asset_type="fallback_policy",
            contract=fallback.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        input_doc = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=input_ref,
            asset_type="input_manifest",
            contract=manifest.to_dict(),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        route_doc = self._ensure_contract(
            operation_id=operation_id,
            project_id=command.project_id,
            logical_ref=route_ref,
            asset_type="route_snapshot",
            contract={
                **route.to_dict(),
                "capability_pack_attempt_snapshot_id": frozen.snapshot_id
                if hasattr(frozen, "snapshot_id")
                else "",
            },
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        request = ExecutionRequest(
            # The ExternalEffect owns the stable Provider idempotency identity;
            # each Operation Attempt owns one gateway execution record.  Reusing
            # the execution_id would conflict with the new Attempt fence and
            # budget reservation even though the Effect itself is unchanged.
            execution_id=f"planning-execution:{effect_id}:{attempt_id}",
            operation_id=operation_id,
            root_operation_id=graph["root_operation_id"],
            saga_id=graph["saga_id"],
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            target_scope=target,
            domain=capability.domain.value,
            task_kind=graph["definition_name"],
            stage=command.generator_operation_name,
            capability=definition.capability,
            importance_class="HIGH",
            risk_class=capability.risk_class.value,
            route_snapshot_id=route_ref,
            workspace_snapshot_ref=command.workspace_id,
            input_manifest_ref=input_ref,
            resource_claims=(
                f"book:{command.book_id}",
                f"planning:{command.logical_key}",
            ),
            timeout_policy_ref=capability.timeout_policy_ref,
            budget_policy_ref=capability.budget_policy_ref,
            permission_policy_ref=capability.permission_policy_ref,
            validation_policy_ref=capability.validation_policy_ref,
            commit_policy_ref=capability.commit_policy_ref,
            stable_idempotency_key=stable_key,
            origin_chain=("story_planning.generate", command.generator_operation_name),
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            external_effect_id=effect_id,
            budget_reservation_id=reservation_id,
        )
        return _PlanningExecutionBinding(request, route, manifest), {
            "input": input_doc,
            "route": route_doc,
        }

    def _context_bundle(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
    ) -> tuple[AuthorityAssetDocument, tuple[AuthorityAssetDocument, ...]]:
        documents: list[AuthorityAssetDocument] = []
        selected: list[dict[str, Any]] = []
        for item in inputs:
            document = self.query.require(
                project_id=command.project_id,
                asset_version_id=item.asset_version_id,
            )
            if (
                document.asset_type != item.asset_type
                or document.content_hash != item.content_hash
                or document.governance != "CLEAR"
                or document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            ):
                raise KernelError(
                    "PLANNING_CONTEXT_INPUT_DRIFT",
                    "Planning input differs from its frozen Authority version",
                )
            documents.append(document)
            selected.append(
                {
                    "role": item.role,
                    "asset_version_id": document.asset_version_id,
                    "asset_type": document.asset_type,
                    "content_hash": document.content_hash,
                    "content": document.content,
                }
            )
        for ordinal, asset_version_id in enumerate(
            command.change_evidence_version_ids, start=1
        ):
            document = self.query.require(
                project_id=command.project_id,
                asset_version_id=asset_version_id,
            )
            if (
                document.asset_type not in {"longform_recap", "replan_request"}
                or document.governance != "CLEAR"
                or document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            ):
                raise KernelError(
                    "PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID",
                    "Planning change evidence drifted after admission",
                )
            documents.append(document)
            selected.append(
                {
                    "role": f"change_evidence:{ordinal}",
                    "asset_version_id": document.asset_version_id,
                    "asset_type": document.asset_type,
                    "content_hash": document.content_hash,
                    "content": document.content,
                }
            )
        book = BookDesignAuthorityQuery(self.database_url).require_book(
            project_id=command.project_id,
            book_id=command.book_id,
        )
        if str(book["workspace_id"]) != command.workspace_id:
            raise KernelError(
                "PLANNING_BOOK_SCOPE_DRIFT",
                "Planning command differs from the authoritative Book workspace",
            )
        production_profile = book.get("production_profile")
        if not isinstance(production_profile, Mapping):
            raise KernelError(
                "PLANNING_BOOK_PRODUCTION_PROFILE_INVALID",
                "Planning requires an object-valued Book production profile",
            )
        language_contract = production_profile.get("language_contract")
        if language_contract is not None and not isinstance(language_contract, Mapping):
            raise KernelError(
                "PLANNING_LANGUAGE_CONTRACT_INVALID",
                "Book Authority language contract must be an object",
            )
        content = {
            "schema_version": "novelos.planning_context_bundle.v1",
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "planning_scope": command.planning_scope.value,
            "logical_key": command.logical_key,
            "input_versions": selected,
            "token_budget": 16000,
            "source_isolation": "ABSTRACT_ASSETS_ONLY",
            "narrative_qualification_profiles": [
                {
                    "layer": profile.layer.value,
                    "profile_id": profile.profile_id,
                    "profile_version": profile.profile_version,
                    "profile_hash": profile.profile_hash,
                    "capability_id": profile.capability_id,
                    "skill_ref": profile.skill_ref,
                    "criteria": list(profile.criteria),
                }
                for profile in required_qualification_profiles(
                    command.generator_operation_name
                )
            ],
            "trace_id": command.trace_id,
            **(
                {"language_contract": dict(language_contract)}
                if isinstance(language_contract, Mapping)
                else {}
            ),
        }
        logical_ref = f"planning/context_bundles/{operation_id}-{attempt_id}.json"
        try:
            context = self.query.require(
                project_id=command.project_id, logical_ref=logical_ref
            )
            if context.content != content:
                raise KernelError(
                    "PLANNING_CONTEXT_BUNDLE_CONFLICT",
                    "Planning Attempt context changed after freeze",
                )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            context = self.writer.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    asset_id=f"planning-context:{attempt_id}",
                    asset_type="context_bundle",
                    schema_version="novelos.planning_context_bundle.v1",
                    logical_ref=logical_ref,
                    category="planning_context",
                    output_key="planning.context_bundle",
                    role="context_bundle",
                    content=content,
                    qualification_policy="planning-context-source-isolation-v1",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    reference_asset_ids=tuple(
                        document.asset_id for document in documents
                    ),
                )
            )
        return context, tuple(documents)

    @staticmethod
    def _allowed_tools(policy: Mapping[str, Any], stage: str) -> tuple[str, ...]:
        if str(policy.get("default") or "").upper() != "DENY":
            raise KernelError(
                "PLANNING_CAPABILITY_TOOL_POLICY_INVALID",
                "Planning Tool policy must default deny",
            )
        allowed = {
            str(item.get("tool_ref") or "")
            for item in policy.get("tools") or ()
            if isinstance(item, Mapping)
            and str(item.get("permission") or "").upper() == "EXECUTE"
            and stage in {str(value) for value in item.get("allowed_operations") or ()}
        }
        return tuple(sorted(item for item in allowed if item))

    def _operation_graph(self, operation_id: str, project_id: str) -> dict[str, str]:
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT operation.definition_name, operation.root_operation_id,
                           saga.saga_id
                    FROM authority_operation AS operation
                    JOIN authority_saga AS saga
                      ON saga.root_operation_id=operation.root_operation_id
                     AND saga.project_id=operation.project_id
                    WHERE operation.operation_id=%s AND operation.project_id=%s
                    """,
                    [operation_id, project_id],
                )
                row = cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_OPERATION_GRAPH_MISSING",
                "Planning execution has no admitted Saga",
            )
        return {
            "definition_name": str(row[0]),
            "root_operation_id": str(row[1]),
            "saga_id": str(row[2]),
        }

    def _ensure_contract(
        self,
        *,
        operation_id: str,
        project_id: str,
        logical_ref: str,
        asset_type: str,
        contract: dict[str, Any],
        trace_id: str,
        correlation_id: str,
    ) -> AuthorityAssetDocument:
        try:
            existing = self.query.require(
                project_id=project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            if (
                existing.asset_type != asset_type
                or existing.content.get("contract", existing.content) != contract
            ):
                raise KernelError(
                    "EXECUTION_CONTRACT_FROZEN_CONFLICT",
                    "Planning execution contract changed inside one identity",
                )
            return existing
        token = _token(f"{project_id}:{logical_ref}")
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=project_id,
                asset_id=f"production-execution-contract:{token}",
                asset_type=asset_type,
                schema_version="production-execution-contract.v1",
                logical_ref=logical_ref,
                category="production_execution_contracts",
                output_key=f"production_execution.contract.{asset_type}.{token}",
                role="execution_contract",
                content={"contract": contract},
                qualification_policy="production-execution-contract-v1",
                trace_id=trace_id,
                correlation_id=correlation_id,
            )
        )


__all__ = [
    "PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS",
    "PostgresPlanningExecutionPreparer",
    "planning_fixture_response",
    "planning_provider_output_schema",
]
