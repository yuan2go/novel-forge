from __future__ import annotations

from novel_forge.logging.execution import execution_step
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from novel_forge.modules.production_execution.cost_routing import producer_contract_identity
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
    resolve_provider_token_reservation_contract,
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
from novel_forge.modules.chapter_authority.execution_gateway import (
    _materialize_production_codex_prompt,
    _provider_effective_context_policy,
    _provider_process_timeout_seconds,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    compile_planning_provider_context,
    planning_context_source_hash,
)
from novel_forge.modules.context_builder.domain import (
    ContextProfile,
    select_context_candidates,
)
from novel_forge.modules.context_builder.governance import (
    ContextBudgetLimits,
    ContextPolicySnapshot,
    PolicyIdentity,
    compile_effective_context_policy,
)
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.hierarchical_planning.domain import (
    CHAPTER_EXECUTION_STATE_KINDS,
    HORIZON_REALIZATION_LEVELS,
    PLAN_HORIZON,
    PLAN_REALIZATION,
    REALIZATION_AUTHORITY_ROLE_TYPES,
    TYPE_FIELDS,
    PlanContractType,
    RealizationLevel,
)
from novel_forge.modules.mkaos_authority import MkaosAuthorityQuery
from novel_forge.modules.mkaos_authority.domain import (
    NarrativeIntelligenceNeed,
    resolve_book_knowledge_access_policy,
    validate_book_knowledge_access_policy,
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
from novel_forge.modules.production_execution.provider_admission import (
    ProviderRequestEnvelope,
    build_route_token_accounting_contract,
    prepare_provider_admission,
    provider_request_protocol,
    provider_request_token_components,
)
from novel_forge.modules.provider_control.contracts import (
    ProviderCapabilityProfile,
    capability_profile_from_dict,
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
    CHAPTER_READER_SCHEDULE_FIELDS,
    CHAPTER_SCHEDULE_FIELDS,
    STORY_PLANNING_MAX_ATTEMPTS,
    STORY_PLANNING_OPERATION_DEFINITION_REF,
    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
    FrozenPlanningInput,
    StoryPlanningGenerationCommand,
    build_planning_constraint_envelope,
    canonical_hash,
    require_chapter_schedule_row,
)
from .narrative_search import (
    CREATIVE_INTELLIGENCE_DIMENSIONS,
    NARRATIVE_SEARCH_PROJECTION_VERSION,
    narrative_search_projection_schema,
)
from .foundation_generation import (
    FOUNDATION_GENERATORS,
    foundation_output_schema,
    foundation_output_schema_ref,
    foundation_task,
)

_PLANNING_STAGES = frozenset(
    {
        *FOUNDATION_GENERATORS,
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
)

# INVARIANT: Planning has one retry owner: every Operation Attempt may advance the same
# ExternalEffect by at most one dispatch generation. Sharing the bound keeps
# the Effect from terminalizing while the Operation still has retry budget and
# prevents nested retry amplification.
PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS = STORY_PLANNING_MAX_ATTEMPTS
PLANNING_ROUTING_LINEAGE_MAX_OPERATIONS = 8


def require_candidate_repair_operation(
    cursor: Any, *, candidate_asset_version_id: str, project_id: str,
    book_id: str, generator_operation_name: str, logical_key: str,
) -> str:
    cursor.execute(
        """SELECT generation.operation_id,candidate.content_hash,version.content_hash,version.content,operation.status
           FROM authority_story_planning_candidate candidate
           JOIN authority_story_planning_generation generation USING(generation_id)
           JOIN authority_asset_version version ON version.asset_version_id=candidate.candidate_asset_version_id
           JOIN authority_asset asset ON asset.asset_id=version.asset_id
           JOIN authority_operation operation ON operation.operation_id=generation.operation_id
           WHERE candidate.candidate_asset_version_id=%s AND candidate.project_id=%s
             AND generation.project_id=candidate.project_id AND generation.book_id=%s
             AND candidate.book_id=generation.book_id AND generation.generator_operation_name=%s
             AND generation.logical_key=%s AND asset.project_id=candidate.project_id
             AND asset.asset_type='planning_generation_candidate'
             AND operation.project_id=generation.project_id
             AND operation.command_payload #>> '{payload,book_id}'=generation.book_id
             AND operation.definition_name='story_planning.generate'""",
        [candidate_asset_version_id, project_id, book_id, generator_operation_name, logical_key],
    )
    row = cursor.fetchone()
    content = dict(row[3]) if row and isinstance(row[3], Mapping) else {}
    if row and row[4] not in {"WAITING_GATE","SUCCEEDED"}:
        from novel_forge.modules.story_design_authority.creative_validation import candidate_validation
        recovered = candidate_validation(cursor,project_id=project_id,asset_version_id=candidate_asset_version_id)
        if not recovered or recovered["generation_operation_id"] != row[0] or recovered["book_id"] != book_id:
            raise KernelError("PLANNING_REPAIR_SOURCE_OPERATION_INVALID", "Repair requires an admissible source or its native validation result recovery")
    if (
        not row or row[1] != row[2] or row[2] != canonical_hash(content)
        or content.get("project_id") != project_id or content.get("book_id") != book_id
        or content.get("logical_key") != logical_key
        or content.get("generator_operation_name") != generator_operation_name
        or (content.get("execution_evidence") or {}).get("operation_id") != row[0]
    ):
        raise KernelError(
            "PLANNING_ROUTING_LINEAGE_INVALID",
            "repair candidate must retain its exact materialized generation Operation and immutable content",
        )
    return str(row[0])


def _planning_repair_routing_lineage(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    generator_operation_name: str,
    operation_id: str,
    repair_of_operation_id: str,
    repair_of_candidate_id: str = "",
) -> tuple[str, ...]:
    if not repair_of_operation_id and not repair_of_candidate_id:
        runtime = get_database_runtime(database_url)
        with runtime.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s AND project_id=%s AND book_id=%s", [operation_id, project_id, book_id])
            if cursor.fetchone() is None:
                return (operation_id,)
    definition_name = STORY_PLANNING_OPERATION_DEFINITION_REF.split("@", 1)[0]
    runtime = get_database_runtime(database_url)
    lineage: list[str] = []
    seen: set[str] = set()
    current_id = operation_id
    expected_logical_key = ""
    expected_repair_number: int | None = None
    expected_repair_delta = 1
    with runtime.connection() as connection, connection.cursor() as cursor:
        while True:
            if current_id in seen:
                raise KernelError(
                    "PLANNING_ROUTING_LINEAGE_CYCLE",
                    "Planning repair routing lineage contains a cycle",
                )
            if len(lineage) >= PLANNING_ROUTING_LINEAGE_MAX_OPERATIONS:
                raise KernelError(
                    "PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED",
                    "Planning repair routing lineage exceeds its bounded depth",
                )
            seen.add(current_id)
            cursor.execute(
                """SELECT project_id,command_payload #>> '{payload,book_id}',definition_name,command_payload->'payload',
                          causation_operation_id
                   FROM authority_operation
                   WHERE operation_id=%s AND project_id=%s""",
                [current_id, project_id],
            )
            row = cursor.fetchone()
            if row is None or not isinstance(row[3], Mapping):
                raise KernelError(
                    "PLANNING_ROUTING_LINEAGE_INVALID",
                    "Planning repair routing lineage operation is unavailable",
                )
            payload = dict(row[3])
            logical_key = str(payload.get("logical_key") or "")
            try:
                repair_number = int(payload.get("repair_number") or 0)
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "PLANNING_ROUTING_LINEAGE_INVALID",
                    "Planning repair routing lineage has invalid repair identity",
                ) from exc
            predecessor = str(payload.get("repair_of_operation_id") or "")
            candidate_predecessor = str(payload.get("repair_of_candidate_id") or "")
            if not lineage and (
                predecessor != repair_of_operation_id
                or candidate_predecessor != repair_of_candidate_id
            ):
                raise KernelError("PLANNING_ROUTING_LINEAGE_INVALID", "repair references differ from the frozen command")
            if candidate_predecessor:
                if predecessor:
                    raise KernelError("PLANNING_ROUTING_LINEAGE_INVALID", "repair cannot mix raw-result and candidate predecessors")
                predecessor = require_candidate_repair_operation(
                    cursor, candidate_asset_version_id=candidate_predecessor,
                    project_id=project_id, book_id=book_id,
                    generator_operation_name=generator_operation_name, logical_key=logical_key,
                )
            allowed_causation = {predecessor}
            capacity_predecessor = ""
            if payload.get("runtime_continuation_id"):
                cursor.execute(
                    "SELECT r.source_operation_id,r.successor_command,r.source_command,source.command_payload->'payload' FROM authority_story_planning_runtime_continuation r JOIN authority_operation source ON source.operation_id=r.source_operation_id AND source.status IN ('CANCELLED','FAILED_FINAL','DEAD_LETTER') JOIN authority_operation registration ON registration.operation_id=r.registered_by_operation_id AND registration.status='SUCCEEDED' WHERE r.continuation_id=%s AND r.successor_operation_id=%s AND r.project_id=%s AND r.book_id=%s",
                    [
                        payload["runtime_continuation_id"],
                        current_id,
                        project_id,
                        book_id,
                    ],
                )
                binding = cursor.fetchone()
                if binding is None or binding[1] != payload or binding[2] != binding[3]:
                    raise KernelError(
                        "PLANNING_ROUTING_LINEAGE_INVALID",
                        "Runtime successor lacks its exact native continuation",
                    )
                capacity_predecessor = str(binding[0])
                allowed_causation.add(capacity_predecessor)
            if candidate_predecessor:
                allowed_causation.update({"", str(payload.get("parent_agent_session_operation_id") or "")})
            if (
                str(row[0]) != project_id
                or str(row[1]) != book_id
                or str(row[2]) != definition_name
                or str(payload.get("project_id") or "") != project_id
                or str(payload.get("book_id") or "") != book_id
                or str(payload.get("generator_operation_name") or "")
                != generator_operation_name
                or not logical_key
                or (expected_logical_key and logical_key != expected_logical_key)
                or (
                    expected_repair_number is not None
                    and repair_number != expected_repair_number - expected_repair_delta
                )
                or (predecessor and str(row[4] or "") not in allowed_causation)
            ):
                raise KernelError(
                    "PLANNING_ROUTING_LINEAGE_INVALID",
                    "Planning repair routing lineage crosses its frozen task scope",
                )
            if not lineage:
                expected_logical_key = logical_key
            lineage.append(current_id)
            if not predecessor and not capacity_predecessor:
                break
            expected_repair_number = repair_number
            expected_repair_delta = 0 if capacity_predecessor else 1
            current_id = capacity_predecessor or predecessor
    lineage.reverse()
    return tuple(lineage)


def planning_repair_route_receipt(
    database_url: str,
    *,
    project_id: str,
    book_id: str,
    operation_id: str,
    task_type: str,
    input_hash: str,
    lineage: tuple[str, ...],
) -> dict[str, Any] | None:
    from novel_forge.modules.story_design_authority import GENERATOR_CATALOG
    from .application import _command_from_payload
    from .result_recovery import require_result_repair_source
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    world_stage = task_type in {"world_candidates.generate", "world_candidates.evaluate"}
    owner_generator = "chapter_plan.generate" if world_stage else task_type
    if owner_generator not in GENERATOR_CATALOG:
        return None
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            "SELECT op.command_payload->'payload',g.repair_number,g.input_snapshot_hash,g.input_snapshot FROM authority_operation op JOIN authority_story_planning_generation g USING(operation_id) WHERE op.operation_id=%s AND op.project_id=%s AND g.book_id=%s AND g.generator_operation_name=%s",
            [operation_id, project_id, book_id, owner_generator],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        payload = row[0]
        contract_successor = bool(payload.get("runtime_continuation_id")) and payload.get("execution_contract_version") == "1.21.0" and payload.get("repair_reason") == "WORLD_AGENCY_CONTRACT_SUCCESSOR"
        if contract_successor:
            return _world_contract_route_receipt(database_url, command=_command_from_payload(payload), payload=payload, task_type=task_type, input_hash=input_hash, lineage=lineage)
        if not row[1]:
            return None
        command = _command_from_payload(payload)
        definition = GENERATOR_CATALOG[owner_generator]
        maximum = max(
            definition.maximum_semantic_repairs,
            definition.maximum_structural_regenerations,
        )
        from .stage_repairs import routing_repair_bound
        stage_bound = routing_repair_bound(uow.cursor, command=command, lineage=lineage, stage=task_type, maximum=maximum)
        ordinal = stage_bound["stage_repair_number"] if stage_bound else command.repair_number
        maximum = stage_bound["maximum_repairs"] if stage_bound else maximum
        if (
            command.repair_number != int(row[1])
            or not 0 < ordinal <= maximum
            or stage_bound is not None and command.repair_number > 4
        ):
            raise KernelError(
                "PLANNING_ROUTING_REPAIR_BOUND_EXCEEDED",
                "Routing cannot extend the owning Planning repair allowance",
            )
        if world_stage and not command.repair_of_operation_id:
            return None
        dependency = None
        if command.repair_of_candidate_id:
            source = require_candidate_repair_operation(
                uow.cursor,
                candidate_asset_version_id=command.repair_of_candidate_id,
                project_id=project_id,
                book_id=book_id,
                generator_operation_name=owner_generator,
                logical_key=command.logical_key,
            )
            _, _, report_hash = command.repair_reason.partition(":")
            uow.cursor.execute(
                "SELECT report_hash FROM authority_story_planning_validation_report WHERE project_id=%s AND candidate_asset_version_id=%s AND status='FAIL' AND report_hash=%s",
                [project_id, command.repair_of_candidate_id, report_hash],
            )
            report = uow.cursor.fetchone()
            if report is None:
                raise KernelError(
                    "PLANNING_ROUTING_REPAIR_EVIDENCE_MISSING",
                    "Repair requires the exact immutable failed diagnosis",
                )
            evidence_id = command.repair_of_candidate_id
            diagnosis_hash = report[0]
        elif command.repair_of_operation_id:
            source = command.repair_of_operation_id
            result = require_result_repair_source(
                database_url,
                command=command,
                operation_id=source,
                source_asset_version_id=command.repair_result_asset_version_id,
            )
            target_stage = result["diagnostic"].get("provider_stage", owner_generator)
            if target_stage != task_type:
                if (
                    task_type != "world_candidates.evaluate"
                    or target_stage != "world_candidates.generate"
                    or result["diagnostic"].get("validation_kind")
                    != "WORLD_CAUSAL_GATE"
                ):
                    return None
                query = AuthorityAssetQuery(database_url)
                previous = query.require(
                    project_id=project_id, asset_version_id=result["asset_version_id"]
                )
                current = query.require(
                    project_id=project_id,
                    logical_ref=f"world_preparation/{operation_id}/generation",
                )
                from .world_preparation import PlanningWorldPreparation

                if (
                    current.asset_type != "world_preparation_generation"
                    or PlanningWorldPreparation._source_operation(
                        database_url, project_id, current.asset_version_id
                    )
                    != operation_id
                ):
                    raise KernelError(
                        "PLANNING_ROUTING_DEPENDENCY_EVIDENCE_INVALID",
                        "Director repair must bind its current native World generation",
                    )
                current_contract = current.content["contract"]
                previous_contract = previous.content["contract"]
                if current_contract["source"] != previous_contract[
                    "source"
                ] or current_contract.get(
                    "knowledge_selection_digest"
                ) != previous_contract.get("knowledge_selection_digest"):
                    raise KernelError(
                        "PLANNING_ROUTING_DEPENDENCY_INPUT_DRIFT",
                        "Director repair must retain the rejected proposal's exact source and knowledge selection",
                    )
                receipt = read_succeeded_external_effect(
                    database_url,
                    EffectCommandContext(
                        operation_id=operation_id,
                        project_id=project_id,
                        actor_id=command.actor_id,
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                    ),
                    effect_id=str(
                        current_contract["evidence"].get("external_receipt_ref") or ""
                    ),
                )
                if (
                    receipt is None
                    or receipt["provider_evidence"].get("result")
                    != current_contract["output"]
                    or receipt["budget_reservation_status"] != "SETTLED"
                ):
                    raise KernelError(
                        "PLANNING_ROUTING_DEPENDENCY_UNSETTLED",
                        "Director repair requires its exact known World result and settled usage",
                    )
                dependency = {"stage": task_type, "repair_target_stage": target_stage, "generation": {"asset_version_id": current.asset_version_id, "content_hash": current.content_hash}, "external_effect_id": current_contract["evidence"]["external_receipt_ref"]}
            evidence_id = result["asset_version_id"]
            diagnosis_hash = canonical_hash(result["diagnostic"])
        else:
            return None
        scope_proof = {}
        if stage_bound:
            uow.cursor.execute("SELECT input_snapshot,input_snapshot_hash FROM authority_story_planning_generation WHERE operation_id=%s AND project_id=%s AND book_id=%s AND generator_operation_name=%s", [source, project_id, book_id, owner_generator])
            parent_inputs = uow.cursor.fetchone()
            if parent_inputs is None or canonical_hash(row[3]) != row[2]:
                raise KernelError("PLANNING_ROUTING_REPAIR_INPUT_DRIFT", "Repair must retain its exact frozen input identities")
            from .application import _replay_generation_input_snapshot
            frozen_inputs = _replay_generation_input_snapshot(row[3], parent_inputs[0], parent_inputs[1])
            scope_proof = {"parent_input_snapshot_hash": parent_inputs[1], "input_snapshot_hash": row[2], "input_scope_hash": canonical_hash({item["role"]: item for item in frozen_inputs})}
        uow.cursor.execute(
            "SELECT e.request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,input_hash}' FROM authority_external_effect e WHERE e.operation_id=%s AND e.project_id=%s AND (e.status='SUCCEEDED' OR (%s AND e.status='FAILED_FINAL' AND EXISTS(SELECT 1 FROM authority_planning_result_admission a JOIN authority_operation recovery ON recovery.operation_id=a.recovery_operation_id AND recovery.status='SUCCEEDED' WHERE a.source_operation_id=e.operation_id AND a.external_effect_id=e.external_effect_id AND a.candidate_asset_version_id=%s))) AND e.request_payload->>'stage'=%s ORDER BY e.created_at DESC LIMIT 1",
            [source, project_id, stage_bound is not None, command.repair_of_candidate_id, task_type],
        )
        source_input = uow.cursor.fetchone()
        if (
            not source_input
            or not source_input[0]
            or not input_hash
            or source_input[0] == input_hash
        ):
            raise KernelError(
                "PLANNING_ROUTING_REPAIR_INPUT_UNCHANGED",
                "A failed frozen request cannot be relabelled as a new repair",
            )
    authoritative = _planning_repair_routing_lineage(
        database_url,
        project_id=project_id,
        book_id=book_id,
        generator_operation_name=owner_generator,
        operation_id=operation_id,
        repair_of_operation_id=command.repair_of_operation_id,
        repair_of_candidate_id=command.repair_of_candidate_id,
    )
    if authoritative != lineage:
        raise KernelError(
            "PLANNING_ROUTING_LINEAGE_INVALID",
            "Repair receipt must cover the exact native lineage",
        )
    return {
        "contract_version": "planning-route-repair.v2" if stage_bound else "planning-route-repair.v1",
        **scope_proof,
        **({"repair_stage": task_type, "stage_repair_number": ordinal, "maximum_lineage_repairs": 4, "policy_admission": stage_bound["policy_admission"]} if stage_bound else {}),
        **({"dependent_evaluation": dependency} if dependency else {}),
        "operation_id": operation_id,
        "source_operation_id": source,
        "source_asset_version_id": evidence_id,
        "diagnosis_hash": diagnosis_hash,
        "repair_number": command.repair_number,
        "maximum_repairs": maximum,
        "source_input_hash": source_input[0],
        "input_hash": input_hash,
        "command_hash": canonical_hash(payload),
        "authorized_history_operation_ids": list(lineage[:-1]),
        "accepted_history_mutation_allowed": False,
    }


def _planning_narrative_intelligence_need(
    *,
    command: StoryPlanningGenerationCommand,
    selected_inputs: list[dict[str, Any]],
    production_profile: Mapping[str, Any],
    recent_repetition_keys: tuple[str, ...] = (),
    recent_craft_usage: tuple[Mapping[str, Any], ...] = (),
) -> NarrativeIntelligenceNeed:
    from novel_forge.modules.creative.editorial_learning import editorial_selection_inputs, required_editorial_knowledge
    selection_inputs = editorial_selection_inputs(selected_inputs, command=command)
    sources: list[Any] = [
        item.get("content")
        for item in selection_inputs
        if isinstance(item.get("content"), Mapping)
    ]
    sources.extend((production_profile, dict(command.arc_working_set or {})))
    craft_sources = _craft_context_sources([*sources, dict(command.narrative_realization or {})], chapter=int((command.narrative_realization or {}).get("chapter_number") or 0))
    stage = command.generator_operation_name
    scope = {
        **{name: "STORY" for name in FOUNDATION_GENERATORS},
        "book_plan.generate": "STORY",
        "volume_plan.generate": "STORY",
        "arc_plan.generate": "ARC",
        "chapter_group_plan.generate": "CHAPTER",
        "chapter_plan.generate": "SCENE",
    }[stage]
    families = {
        **{
            name: (
                "NARRATIVE_MECHANISM",
                "CHARACTER_TRANSFORMATION",
                "WORLD_CONSEQUENCE",
                "THEME_MORAL_DILEMMA",
            )
            for name in FOUNDATION_GENERATORS
        },
        "book_plan.generate": (
            "NARRATIVE_MECHANISM",
            "CHARACTER_TRANSFORMATION",
            "READER_EMOTIONAL_CURVE",
            "THEME_MORAL_DILEMMA",
            "PROFESSIONAL_CAUSAL_MECHANISM",
        ),
        "volume_plan.generate": (
            "ARC_BEAT_PATTERN",
            "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
            "WORLD_CONSEQUENCE",
            "FACTION_DYNAMICS",
            "READER_EMOTIONAL_CURVE",
        ),
        "arc_plan.generate": (
            "ARC_BEAT_PATTERN",
            "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
            "CHARACTER_TRANSFORMATION",
            "RELATIONSHIP",
            "MYSTERY_CLUE_REVEAL",
            "POWER_RESOURCE_PROGRESSION",
        ),
        "chapter_group_plan.generate": (
            "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
            "MYSTERY_CLUE_REVEAL",
            "WORLD_CONSEQUENCE",
            "READER_EMOTIONAL_CURVE",
            "ANTI_PATTERN_FAILURE",
        ),
        "chapter_plan.generate": (
            "NARRATIVE_PRIMITIVE",
            "SCENE_INTERACTION",
            "CONFLICT_ESCALATION_REVERSAL_PAYOFF",
            "RELATIONSHIP",
            "MYSTERY_CLUE_REVEAL",
            "READER_EMOTIONAL_CURVE",
            "ANTI_PATTERN_FAILURE",
            "PROFESSIONAL_CAUSAL_MECHANISM",
        ),
    }[stage]
    return NarrativeIntelligenceNeed(
        scope=scope,
        target_stage=stage,
        current_state_terms=_selection_terms(
            sources,
            {
                "current_state",
                "current_phase",
                "lifecycle",
                "status",
                "entry_state",
                "state_before",
                "obligation_status",
                "checkpoint_status",
            },
        ),
        desired_transformation_terms=_selection_terms(
            sources,
            {
                "objective",
                "purpose",
                "desired_transformation",
                "required_state_delta",
                "required_outcomes",
                "chapter_function",
                "exit_state",
                "expected_exit_state",
                "contribution_action",
                "action",
            },
        ),
        genre_tags=_selection_terms(sources, {"genre", "genre_tags"}),
        conflict_tags=_selection_terms(
            sources, {"conflict", "conflict_tags", "conflict_type"}
        ),
        reader_effect_tags=_selection_terms(
            sources,
            {
                "reader_effect",
                "reader_effect_tags",
                "intended_reader_effect",
                "reader_promise",
                "reader_intent",
            },
        ),
        theme_tags=_selection_terms(sources, {"theme", "theme_tags"}),
        hard_constraints=_required_selection_terms(
            sources,
            {
                "hard_constraints",
                "constraints",
                "forbidden_changes",
                "prohibited_changes",
                "forbidden_events",
                "prohibited_outcomes",
            },
        ),
        recently_used_repetition_keys=_merge_selection_terms(
            _selection_terms(
                sources,
                {
                    "recently_used_repetition_keys",
                    "repetition_keys",
                    "recent_patterns",
                },
            ),
            recent_repetition_keys,
        ),
        semantic_families=families,
        required_card_asset_version_ids=tuple(sorted(set(_inherited_knowledge_versions(
            selected_inputs, chapter=int((command.narrative_realization or {}).get("chapter_number") or 0)
        )) | set(required_editorial_knowledge(selected_inputs, command=command)))),
        craft_context={
            "task": [stage],
            "writing_problem": list(_selection_terms(craft_sources, {"writing_problem", "writing_problems", "craft_problem"})),
            "scene_demand": list(_selection_terms(craft_sources, {"scene_demand", "scene_needs"})),
            "scene_type": list(_selection_terms(craft_sources, {"scene_type"})),
            "chapter_function": list(_selection_terms(craft_sources, {"chapter_function", "primary_function", "objective", "purpose"})),
            "scene_goal": list(_selection_terms(craft_sources, {"scene_goal", "scene_goals", "goal", "required_outcomes", "action", "decision", "consequence"})),
            "reader_effect": list(_selection_terms(craft_sources, {"reader_effect", "reader_effect_tags", "intended_reader_effect", "reader_promise"})),
            "conflict": list(_selection_terms(craft_sources, {"conflict", "conflict_tags", "conflict_type", "conflict_chain"})),
            "pov": list(_selection_terms(craft_sources, {"point_of_view", "pov", "pov_character"})),
            "characters": list(_selection_terms(craft_sources, {"character_id", "character_role", "character_goals", "core_desire", "core_fear", "motivation", "actor_ref"})),
            "emotion": list(_selection_terms(craft_sources, {"emotional_curve", "emotion_curve", "emotion", "reader_emotional_curve", "target_emotion"})),
            "information": list(_selection_terms(craft_sources, {"knowledge_boundaries", "knowledge_boundary", "information_reveals", "disclosures", "information_state"})),
            "genre": list(_selection_terms(craft_sources, {"genre", "genre_tags"})),
            "pacing": list(_selection_terms(craft_sources, {"pacing", "platform_rhythm", "pacing_profile"})),
            "relationship": list(_selection_terms(craft_sources, {"relationships", "relationship_pairs", "relationship_state"})),
            "obligations": list(_selection_terms(craft_sources, {"active_obligations", "obligation_actions", "required_arc_contributions", "setups", "payoffs"})),
            "style": list(_selection_terms(craft_sources, {"style_constraints", "style_policy", "style_profile", "voice"})),
            "chapter_number": int((command.narrative_realization or {}).get("chapter_number") or 0),
            **({"usage_scope_context": {
                "project_id": command.project_id, "book_id": command.book_id,
                "chapter_number": int((command.narrative_realization or {}).get("chapter_number") or 0),
                **({"scope_transitions": []} if (production_profile.get("craft_budget_policy") or {}).get("schema_version") == "narrative-craft-budget.v4" else {}),
                "arc_plan_version_ids": list(dict.fromkeys([
                    *([str(command.input_versions["arc_plans"])] if command.input_versions.get("arc_plans") else []),
                    *command.related_arc_plan_version_ids,
                ])),
            }} if (production_profile.get("craft_budget_policy") or {}).get("schema_version") in {"narrative-craft-budget.v3", "narrative-craft-budget.v4"} else {}),
        },
        craft_policy=dict(production_profile.get("craft_budget_policy") or {}),
        recent_craft_usage=recent_craft_usage,
        condition_sources={
            str(item["role"]): item
            for item in selection_inputs
            if item.get("role") and isinstance(item.get("content"), Mapping)
        },
    )


def _craft_context_sources(sources: list[Any], *, chapter: int) -> list[Any]:
    from novel_forge.modules.story_design_authority.author_input import without_author_private

    excluded = {"original_examples", "voice_anchors", "raw_text", "raw_source_text", "source_text", "source_excerpt", "reference_text", "source_chunks", "chunk_text", "evidence_spans", "author_only", "private_planning"}
    scoped = {"chapter_function_matrix", "chapter_schedule", "chapter_slices"}

    def project(value: Any) -> Any:
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                if key in excluded:
                    continue
                if key in scoped and chapter and isinstance(item, (list, tuple)):
                    item = [row for row in item if not isinstance(row, Mapping) or int(row.get("chapter_number") or chapter) == chapter]
                result[key] = project(item)
            return result
        if isinstance(value, (list, tuple)):
            return [project(item) for item in value]
        return value

    return [project(without_author_private(source)) for source in sources]


def _inherited_knowledge_versions(selected_inputs: list[dict[str, Any]], *, chapter: int) -> tuple[str, ...]:
    from novel_forge.modules.mkaos_authority.applicability import resolve_pointer

    required: set[str] = set()
    for source in selected_inputs:
        content = source.get("content") or {}
        for translation in content.get("knowledge_translations") or ():
            if translation.get("decision") not in {"ADOPT", "ADAPT"} or translation.get("usage_role") not in {"MECHANISM", "CONSTRAINT", "REVIEW_CHECK"}:
                continue
            for site in translation.get("use_sites") or ():
                pointer = str(site.get("target_pointer") or "")
                in_scope = True
                tokens = pointer.split("/")
                if chapter:
                    for length in range(2, len(tokens)):
                        found, ancestor = resolve_pointer(content, "/".join(tokens[:length]))
                        if found and isinstance(ancestor, Mapping) and ancestor.get("chapter_number") is not None and int(ancestor["chapter_number"]) != chapter:
                            in_scope = False
                if in_scope:
                    required.add(translation["knowledge_card_asset_version_id"])
                    break
    return tuple(sorted(required))


def _planning_knowledge_access(*, production_profile, selected, project_id, book_id):
    policy = resolve_book_knowledge_access_policy(production_profile=production_profile, project_id=project_id, book_id=book_id)
    for item in selected:
        content = item.get("content") or {}
        if item.get("role") == "production_profile" and "knowledge_access_policy" in content:
            declared = resolve_book_knowledge_access_policy(production_profile=content, project_id=project_id, book_id=book_id)
            if declared != policy:
                raise KernelError("PLANNING_BOOK_KNOWLEDGE_POLICY_MISMATCH", "the frozen ProductionProfile and Book Authority declare different knowledge policies; reconcile the Book inputs before generation")
    return policy


def _required_selection_terms(sources: list[Any], keys: set[str]) -> tuple[str, ...]:
    values: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            values.add(value.strip())
        elif isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).casefold() in keys:
                    collect(item)
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for source in sources:
        visit(source)
    return tuple(sorted(values))


def _selection_terms(
    sources: list[Any], keys: set[str], *, limit: int = 32
) -> tuple[str, ...]:
    values: list[str] = []

    def visit(value: Any) -> None:
        if len(values) >= limit:
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).strip().casefold() in keys:
                    collect(item)
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    def collect(value: Any) -> None:
        if len(values) >= limit:
            return
        if isinstance(value, str) and value.strip():
            values.append(value.strip()[:500])
        elif isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    normalized_keys = {key.casefold() for key in keys}
    keys.clear()
    keys.update(normalized_keys)
    for source in sources:
        visit(source)
    return tuple(sorted(set(values))[:limit])


def _narrative_intelligence_limit(stage: str) -> int:
    return 4 if stage in {"book_plan.generate", "volume_plan.generate"} else 6


def _merge_selection_terms(*values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({item for group in values for item in group if item}))[:32]


def _recent_activated_repetition_keys(
    usage_records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:

    return tuple(
        dict.fromkeys(
            str(item.get("repetition_key") or "")
            for item in usage_records
            if str(item.get("repetition_key") or "")
            and str(item.get("plan_binding_id") or "")
            and str(item.get("plan_freshness") or "") == "CURRENT"
            and (
                "usage_states" not in item
                or bool((item.get("usage_states") or {}).get("claimed_adoption"))
            )
        )
    )[:32]


def _realization_reference_contract(
    *,
    project_id: str,
    book_id: str,
    frozen_by_operation_id: str,
    inputs: tuple[FrozenPlanningInput, ...],
    selectors_only: bool = False,
    character_references=None,
) -> dict[str, Any]:

    references: dict[str, list[dict[str, str]]] = {}
    for domain_type, role_types in REALIZATION_AUTHORITY_ROLE_TYPES.items():
        eligible = []
        for item in inputs:
            if (
                item.role not in role_types
                or item.asset_type not in role_types[item.role]
            ):
                continue
            eligible.append(
                {
                    "project_id": project_id,
                    "book_id": book_id,
                    "authority_role": item.role,
                    "asset_version_id": item.asset_version_id,
                    "asset_type": item.asset_type,
                    "content_hash": item.content_hash,
                    "domain_type": domain_type,
                    "freshness": "CURRENT",
                    "frozen_by_operation_id": frozen_by_operation_id,
                }
            )
        if not eligible:
            raise KernelError(
                "PLANNING_REALIZATION_REFERENCE_SOURCE_MISSING",
                f"Planning frozen inputs cannot support {domain_type}",
            )
        references[domain_type] = eligible
    return {
        "contract_version": "planning-realization-reference-contract-v2" if character_references is not None else "planning-realization-reference-contract-v1",
        **({"character_references": character_references} if character_references is not None else {}),
        "instruction": "Select only asset_version_id from the matching frozen domain list; host binds scope, type, hash and Operation identity." if selectors_only else (
            "Copy one complete reference object from the matching domain list; "
            "never invent or reinterpret authority_role, asset_type, identity, "
            "or lineage."
        ),
        "references_by_domain": references,
    }


@dataclass(frozen=True, slots=True)
class PlanningExecutionRoute:
    model_profile: ModelProfile
    route_policy: RoutePolicy
    fallback_policy: FallbackPolicy
    backend_version: str
    runtime_host_id: str
    auth_profile_ref: str
    release_sha: str
    model_context_limit: int = 0
    model_output_limit: int = 0
    token_accounting_method: str = ""
    token_accounting_evidence_ref: str = ""
    token_safety_margin: int = 256
    token_framing_overhead: int = 16
    task_reasoning_authorization: tuple[str, str] | None = None

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
        if (
            min(
                self.model_context_limit,
                self.model_output_limit,
                self.token_safety_margin,
                self.token_framing_overhead,
            )
            < 0
        ):
            raise ValueError("Planning route Token Accounting limits are invalid")


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
    search_horizon = command.get("narrative_search_planning_horizon")
    frozen_book_target = (
        search_horizon.get("target_chapters")
        if isinstance(search_horizon, Mapping)
        else None
    )
    fixture_book_target_chapters = (
        int(frozen_book_target)
        if isinstance(frozen_book_target, int)
        and not isinstance(frozen_book_target, bool)
        and frozen_book_target > 0
        else 6
        if logical_key.endswith(":portfolio-2")
        else 3
    )
    fixture_book_volume_count = max(1, (fixture_book_target_chapters + 2) // 3)
    logical_ordinal = 1
    if stage == "volume_plan.generate":
        try:
            logical_ordinal = max(1, int(logical_key.rsplit(":", 1)[-1]))
        except ValueError:
            logical_ordinal = 1
    edition_scope = command.get("edition_execution") or {}
    chapter_number = int(edition_scope["chapter"]) if edition_scope else _logical_chapter_number(logical_key)
    if stage == "chapter_group_plan.generate":
        chapter_number = max(
            chapter_number,
            int(command.get("narrative_search_accepted_through_chapter") or 0) + 1,
        )
    group_start = chapter_number
    group_end = chapter_number + 2
    if stage == "chapter_group_plan.generate" and isinstance(search_horizon, Mapping):
        frozen_range = search_horizon.get("chapter_range")
        if isinstance(frozen_range, list) and len(frozen_range) == 2:
            group_start, group_end = map(int, frozen_range)
            chapter_number = group_start
    volume_chapter_range = [
        (logical_ordinal - 1) * 3 + 1,
        logical_ordinal * 3,
    ]
    if stage == "volume_plan.generate" and isinstance(search_horizon, Mapping):
        frozen_range = search_horizon.get("chapter_range")
        if isinstance(frozen_range, list) and len(frozen_range) == 2:
            volume_chapter_range = [int(frozen_range[0]), int(frozen_range[1])]
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
    search_id = str(command.get("narrative_search_id") or "")
    branch_key = str(command.get("narrative_search_branch_key") or "")
    if search_id:
        try:
            branch_number = max(1, int(branch_key.rsplit("-", 1)[-1]))
        except ValueError:
            branch_number = 1
        branch_bias = min(0.12, (branch_number - 1) * 0.04)
        payload["narrative_search_projection"] = {
            "contract_version": NARRATIVE_SEARCH_PROJECTION_VERSION,
            "strategy_fingerprint": (
                f"{stage}:{logical_key}:causal-strategy-{branch_number}"
            ),
            "assumptions": [
                f"branch {branch_number} preserves the frozen parent boundary"
            ],
            "projected_consequences": [
                f"branch {branch_number} turns pressure into an accepted-state choice"
            ],
            "narrative_opportunities": [
                f"branch {branch_number} opens a distinct convergence path"
            ],
            "narrative_risks": [
                f"branch {branch_number} may compress one later payoff window"
            ],
            "irreversible_decisions": (
                [f"branch {branch_number} commits the public cost"]
                if branch_number == 3
                else []
            ),
            "future_options": [
                f"branch {branch_number} can escalate through relationship pressure",
                f"branch {branch_number} can pivot through world consequence",
            ],
            "repetition_keys": [f"fixture-causal-strategy-{branch_number}"],
            "creative_intelligence": {
                dimension: round(
                    min(
                        0.95,
                        0.68
                        + branch_bias
                        + (
                            0.04
                            if dimension
                            in {
                                "character_agency",
                                "choice_cost_consequence",
                                "future_optionality",
                            }
                            else 0.0
                        ),
                    ),
                    3,
                )
                for dimension in CREATIVE_INTELLIGENCE_DIMENSIONS
            },
            "selection_summary": (
                f"fixture branch {branch_number} balances causal pressure and optionality"
            ),
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
            "chapter_range": volume_chapter_range,
            "narrative_architecture_version": "canonical-narrative-v1",
            "narrative_segments": [
                {
                    "segment_id": "narrative-segment:1",
                    "objective": "Turn private doubt into public commitment",
                    "chapter_range": volume_chapter_range,
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
                for group_chapter in range(group_start, group_end + 1)
            ],
            "chapter_range": [group_start, group_end],
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
            "narrative_event_chain": _fixture_narrative_event_chain(
                chapter_start=group_start,
                chapter_end=group_end,
                arc_plan_ids=arc_plan_ids or ("arc:primary",),
            ),
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
            "narrative_realization_slice": dict(
                command.get("narrative_realization") or {}
            ),
            "narrative_architecture_version": "canonical-narrative-v1",
            "narrative_segment_ref": {
                "volume_plan_version_id": str(
                    versions.get("volume_plan") or "volume:1"
                ),
                "segment_id": "narrative-segment:1",
            },
            "chapter_intent": "Force a witnessed choice that advances the central conflict.",
            "chapter_contract_schema_version": "chapter-mission-scene.v2",
            "arc_schedule": [
                {
                    "arc_plan_version_id": arc_id,
                    "role": (
                        "PRIMARY"
                        if index == 0
                        else "SECONDARY"
                        if index == 1
                        else "TOUCH"
                    ),
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
                    "realization_capabilities": [
                        "SKELETON",
                        "ACTION",
                        "INTERIOR",
                        "INTEGRATION",
                    ],
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
                    "arc_progress": list(arc_plan_ids or ("arc:primary",)),
                    "trajectory_refs": ["character-arc:accountability"],
                    "obligation_refs": ["promise:choice"],
                    "realization_event_ids": [
                        str(event["event_id"])
                        for event in (command.get("narrative_realization") or {}).get(
                            "events"
                        )
                        or ()
                    ],
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

    named = {
        0: "DENIAL",
        1: "COMMITTED",
        2: "CONSEQUENT",
        3: "OWNED",
    }
    return named.get(boundary, f"INTEGRATED_{boundary}")


def _fixture_narrative_event_chain(
    *, chapter_start: int, chapter_end: int, arc_plan_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    event_ids = [
        f"realization:chapter-group:{chapter_start}:event:{offset}"
        for offset in range(1, chapter_end - chapter_start + 2)
    ]
    result: list[dict[str, Any]] = []
    for offset, event_id in enumerate(event_ids):
        chapter = chapter_start + offset
        result.append(
            {
                "event_id": event_id,
                "slice_id": f"realization:chapter:{chapter}",
                "chapter_number": chapter,
                "causes": [] if offset == 0 else [event_ids[offset - 1]],
                "actor_ref": "protagonist",
                "motivation": "preserve agency while protecting the witness",
                "preconditions": ["the preceding pressure remains unresolved"],
                "knowledge_boundary": {
                    "actor_knows": ["fact:public-risk"],
                    "reader_may_learn": ["fact:hidden-cost"],
                    "forbidden_disclosures": ["fact:future-antagonist-plan"],
                },
                "action": "confront the institutional resistance",
                "decision": "accept a visible cost instead of retreating",
                "resistance": "the opposition converts private risk into public loss",
                "consequence": "the decision creates the next irreversible pressure",
                "state_deltas": [
                    {
                        "state_kind": "character_arc",
                        "entity_id": "protagonist:accountability",
                        "from_state": _fixture_character_arc_stage(offset),
                        "to_state": _fixture_character_arc_stage(offset + 1),
                    }
                ],
                "disclosures": ["fact:hidden-cost"],
                "obligation_actions": ["promise:choice:ADVANCE"],
                "arc_contributions": list(arc_plan_ids),
                "irreversible_change": "the choice becomes witnessed and costly",
                "next_event_ids": (
                    [] if offset == len(event_ids) - 1 else [event_ids[offset + 1]]
                ),
                "required": True,
            }
        )
    return result


def _strict_object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _frozen_provider_value_schema(
    values: Sequence[Any], *, work_requirements: bool = False
) -> dict[str, Any]:
    """CONSTRAINT: Project frozen JSON values into the Provider's strict-schema dialect.

    OpenAI Structured Outputs does not accept object- or array-valued ``const``
    nodes.  This projection freezes object shape, array cardinality, and scalar
    vocabulary without creating a second semantic authority.  Planning
    Authority still compares the returned value with the complete frozen value,
    including array order and multiplicity, before activation.
    """
    if not values:
        raise ValueError("Frozen Provider schema requires at least one value")

    if (
        work_requirements
        and any(value is None for value in values)
        and any(value is not None for value in values)
    ):
        present = _frozen_provider_value_schema(
            [value for value in values if value is not None], work_requirements=True
        )
        if present["type"] not in {"string", "boolean", "integer", "number"}:
            raise ValueError("Nullable frozen values must be scalar")
        return {"type": [present["type"], "null"], "enum": list(dict.fromkeys(values))}

    if all(isinstance(value, Mapping) for value in values):
        mappings = [dict(value) for value in values]
        keys = list(mappings[0])
        expected_keys = set(keys)
        if any(set(value) != expected_keys for value in mappings[1:]):
            raise ValueError(
                "Frozen Provider object arrays require one canonical object shape"
            )
        return _strict_object(
            {
                key: _frozen_provider_value_schema(
                    [value[key] for value in mappings],
                    work_requirements=work_requirements,
                )
                for key in keys
            }
        )

    if all(isinstance(value, list) for value in values):
        sequences = [list(value) for value in values]
        lengths = [len(value) for value in sequences]
        members = [member for value in sequences for member in value]
        return {
            "type": "array",
            "minItems": min(lengths),
            "maxItems": max(lengths),
            # COMPATIBILITY: ``items`` remains mandatory in the Provider dialect even when
            # every frozen array is empty and maxItems therefore forbids data.
            "items": (
                _frozen_provider_value_schema(
                    members, work_requirements=work_requirements
                )
                if members
                else {"type": "string"}
            ),
        }

    if all(isinstance(value, bool) for value in values):
        scalar_type = "boolean"
    elif all(
        isinstance(value, int) and not isinstance(value, bool) for value in values
    ):
        scalar_type = "integer"
    elif all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in values
    ):
        scalar_type = "number"
    elif all(isinstance(value, str) for value in values):
        scalar_type = "string"
    elif all(value is None for value in values):
        scalar_type = "null"
    else:
        raise ValueError("Frozen Provider schema contains mixed JSON value types")

    distinct: list[Any] = []
    for value in values:
        if value not in distinct:
            distinct.append(value)
    constraint = "const" if len(distinct) == 1 else "enum"
    return {
        "type": scalar_type,
        constraint: distinct[0] if constraint == "const" else distinct,
    }


def _realization_authority_ref_schema(domain_type: str) -> dict[str, Any]:

    role_types = REALIZATION_AUTHORITY_ROLE_TYPES[domain_type]
    string = {"type": "string", "minLength": 1}
    return _strict_object(
        {
            "project_id": string,
            "book_id": string,
            "authority_role": {
                "type": "string",
                "enum": sorted(role_types),
            },
            "asset_version_id": string,
            "asset_type": {
                "type": "string",
                "enum": sorted(
                    {
                        asset_type
                        for asset_types in role_types.values()
                        for asset_type in asset_types
                    }
                ),
            },
            "content_hash": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "domain_type": {"type": "string", "const": domain_type},
            "freshness": {"type": "string", "const": "CURRENT"},
            "frozen_by_operation_id": string,
        }
    )


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
    world_invariant_ref = _realization_authority_ref_schema("WORLD_INVARIANT")
    world_structure_ref = _realization_authority_ref_schema("WORLD_STRUCTURE")
    world_state_ref = _realization_authority_ref_schema("WORLD_STATE")
    character_identity_ref = _realization_authority_ref_schema("CHARACTER_IDENTITY")
    character_state_ref = _realization_authority_ref_schema("CHARACTER_STATE")
    character_trajectory_ref = _realization_authority_ref_schema("CHARACTER_TRAJECTORY")
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
                        "items": world_invariant_ref,
                    },
                    "structure_refs": {
                        "type": "array",
                        "minItems": 1,
                        "items": world_structure_ref,
                    },
                    "state_ref": world_state_ref,
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
                    "identity_ref": character_identity_ref,
                    "state_ref": character_state_ref,
                    "trajectory_ref": character_trajectory_ref,
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
            "arc_relations": {
                "type": "array",
                **({"maxItems": 0} if len(set(arc_relation_refs)) < 2 else {}),
                "items": arc_relation,
            },
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
        "chapter_intent": {
            **string,
            "description": "Chapter Mission: the semantic purpose the Scene Architecture must realize.",
        },
        "chapter_contract_schema_version": {
            "type": "string",
            "const": "chapter-mission-scene.v2",
        },
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
                    "known_fact_ids": {
                        **string_array,
                        "description": (
                            "Facts known at chapter entry. Do not include facts first "
                            "learned by this character during the planned chapter."
                        ),
                    },
                    "unknown_fact_ids": {
                        **string_array,
                        "description": (
                            "Facts unknown at chapter entry, including facts the "
                            "character may learn in a later Scene."
                        ),
                    },
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
                    "realization_capabilities": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "string",
                            "enum": [
                                "SKELETON",
                                "DIALOGUE",
                                "ACTION",
                                "INTERIOR",
                                "DESCRIPTION",
                                "TRANSITION",
                                "INTEGRATION",
                            ],
                        },
                    },
                    "scene_group_id": string,
                    "goal": string,
                    "conflict": string,
                    "participants": {
                        **string_array,
                        "description": (
                            "Character identities present in the Scene. Every listed "
                            "character must declare this Scene's location_id in its "
                            "reachable_location_ids."
                        ),
                    },
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
                    "accessible_knowledge": {
                        **string_array,
                        "description": (
                            "Facts known by the POV character at Scene entry. A fact "
                            "learned earlier in this chapter is eligible only after an "
                            "earlier Scene lists it as information_gain while the "
                            "character participates and CHARACTER_KNOWLEDGE declares "
                            "the fact KNOWN."
                        ),
                    },
                    "arc_progress": {
                        "type": "array",
                        "minItems": 1,
                        "items": scheduled_arc_ref,
                        "description": (
                            "Exact frozen Arc plan version identities advanced in "
                            "this Scene; never prose or an Arc label."
                        ),
                    },
                    "trajectory_refs": {
                        **string_array,
                        "description": "Exact character_participation.trajectory_refs realized in this Scene; all Mission trajectories must be covered.",
                    },
                    "obligation_refs": {
                        **string_array,
                        "description": "Exact obligation_actions.obligation_id values realized in this Scene; cover every Mission obligation without inventing one.",
                    },
                    "realization_event_ids": {
                        **string_array,
                        "description": "Exact frozen narrative_realization_slice event identities realized in this Scene; cover all events. These are planned execution commitments, never accepted facts.",
                    },
                    "information_gain": {
                        **string_array,
                        "description": (
                            "Facts established during this Scene, never facts merely "
                            "assumed at Scene entry."
                        ),
                    },
                    "state_transitions": {
                        **string_array,
                        "description": (
                            "Only exact entity_key values declared in "
                            "required_state_transitions; never prose descriptions."
                        ),
                    },
                    "entry_state": {
                        **string,
                        "description": (
                            "Explicit Scene-entry state. After the first Scene this "
                            "must copy the preceding Scene's exit_state verbatim."
                        ),
                    },
                    "exit_state": {
                        **string,
                        "description": (
                            "Explicit Scene-exit state which the next Scene must copy "
                            "verbatim as its entry_state."
                        ),
                    },
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


def planning_schema_evidence_identity(
    schema: Mapping[str, Any], schema_ref: str
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    sources = sorted((root / "story_planning_runtime").glob("*.py")) + [
        root / "story_design_authority" / "author_input.py",
        root / "hierarchical_planning" / "domain.py",
        root / "chapter_authority" / "execution_gateway.py",
        root / "chapter_authority" / "provider_views.py",
    ]

    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == "const":
                    result[key] = {"binding_type": type(item).__name__}
                elif key == "enum":
                    result[key] = {"binding_types": [type(part).__name__ for part in item]}
                else:
                    result[key] = shape(item)
            return result
        if isinstance(value, list):
            return [shape(item) for item in value]
        return value

    return {
        "ref": schema_ref, "identity_version": "planning-schema-factory-and-shape.v1",
        "factory_hash": canonical_hash({
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        }),
        "shape_hash": canonical_hash(shape(dict(schema))),
        "binding_policy": "CONST_AND_ENUM_VALUES_ARE_FROZEN_PER_REQUEST;_TYPES_CARDINALITY_AND_FACTORY_ARE_SHARED",
    }


def world_schema_evidence_identity(
    schema: Mapping[str, Any], schema_ref: str
) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    sources = sorted((root / "worldbuilding").glob("*.py")) + [
        Path(__file__).resolve(),
        root / "story_planning_runtime" / "world_preparation.py",
        root / "chapter_authority" / "provider_views.py",
    ]
    bound_paths = {
        ("properties", "candidates", "items", "properties", "arc_refs", "items", "enum"),
        ("properties", "candidates", "items", "properties", "obligation_refs", "items", "enum"),
        ("properties", "actor_id", "enum"),
        ("properties", "basis_refs", "items", "enum"),
        ("properties", "actor_adjudications", "items", "properties", "actor_id", "enum"),
        ("properties", "actor_adjudications", "items", "properties", "proposal_hash", "enum"),
        ("properties", "evaluations", "items", "properties", "transition_id", "enum"),
    }

    def shape(value: Any, path: tuple[str, ...] = ()) -> Any:
        if path in bound_paths and isinstance(value, list):
            return {"binding_types": [type(part).__name__ for part in value]}
        if isinstance(value, dict):
            return {key: shape(item, (*path, key)) for key, item in value.items()}
        if isinstance(value, list):
            return [shape(item, (*path, str(index))) for index, item in enumerate(value)]
        return value

    return {
        "ref": schema_ref,
        "identity_version": "world-schema-factory-and-bound-id-shape.v1",
        "factory_hash": canonical_hash({
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        }),
        "shape_hash": canonical_hash(shape(dict(schema))),
        "binding_policy": "EXACT_WORLD_INSTANCE_ID_ENUM_VALUES_ARE_FROZEN_PER_REQUEST;_SEMANTICS_TYPES_CARDINALITY_AND_FACTORY_ARE_SHARED",
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
    narrative_search: bool = False,
    narrative_search_horizon: Mapping[str, Any] | None = None,
    narrative_realization: Mapping[str, Any] | None = None,
    chapter_schedule_row: Mapping[str, Any] | None = None,
    arc_working_set: Mapping[str, Any] | None = None,
    work_requirements: bool = False,
    aligned_methods: bool = False,
    serialization_contract: bool = False,
    typed_volume_allocation: bool = False,
    operational_commitments: bool = False,
) -> dict[str, Any]:
    """CONSTRAINT: OpenAI-strict provider schema; Planning validation stays authoritative."""
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
    exact_group_range: tuple[int, int] | None = None
    exact_group_chapters: list[int] = []
    if contract_type is PlanContractType.CHAPTER_GROUP and narrative_search:
        horizon = dict(narrative_search_horizon or {})
        raw_range = horizon.get("chapter_range")
        if (
            horizon.get("level") != "CHAPTER_GROUP"
            or not isinstance(raw_range, list)
            or len(raw_range) != 2
            or any(
                not isinstance(item, int) or isinstance(item, bool)
                for item in raw_range
            )
        ):
            raise ValueError(
                "ChapterGroup Search provider schema requires an exact frozen horizon"
            )
        exact_group_range = (raw_range[0], raw_range[1])
        if exact_group_range[0] <= 0 or exact_group_range[1] < exact_group_range[0]:
            raise ValueError(
                "ChapterGroup Search provider schema requires a positive ordered range"
            )
        exact_group_chapters = list(
            range(exact_group_range[0], exact_group_range[1] + 1)
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
        elif field in {"primary_arc_ids", "secondary_arc_ids"}:
            properties[field] = {
                "type": "array",
                "items": _frozen_arc_ref_schema(arc_plan_version_ids, string),
            }
            if field == "primary_arc_ids":
                properties[field]["minItems"] = 1
            if arc_plan_version_ids:
                properties[field]["maxItems"] = len(arc_plan_version_ids)
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
            volume_fields = {
                "volume": {"type": "integer", "minimum": 1},
                "function": string,
            }
            if serialization_contract and typed_volume_allocation:
                volume_fields["chapter_range"] = {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Inclusive chapter bounds for this Volume. All Volumes must form one contiguous allocation of the Book target, matching their story functions.",
                }
            properties[field] = {
                "type": "array",
                "items": _strict_object(volume_fields),
            }
        elif field == "required_arc_contributions":
            arc_ref = _frozen_arc_ref_schema(arc_plan_version_ids, string)
            properties[field] = (
                {
                    "type": "array",
                    "minItems": 1,
                    "items": arc_ref,
                }
                if contract_type is PlanContractType.CHAPTER_GROUP
                else {
                    "type": "array",
                    "minItems": 1,
                    "items": _strict_object(
                        {"arc_plan_version_id": arc_ref, "contribution": string}
                    ),
                }
            )
            if arc_plan_version_ids:
                properties[field]["maxItems"] = min(3, len(arc_plan_version_ids))
        elif field == "arc_checkpoint_expectations":
            properties[field] = {
                "type": "array",
                "minItems": 1,
                "items": _strict_object(
                    {
                        "arc_plan_version_id": _frozen_arc_ref_schema(
                            arc_plan_version_ids, string
                        ),
                        "expectation": string,
                    }
                ),
            }
            if arc_plan_version_ids:
                properties[field]["maxItems"] = len(arc_plan_version_ids)
        elif field == "narrative_event_chain":
            arc_ref = _frozen_arc_ref_schema(arc_plan_version_ids, string)
            properties[field] = {
                "type": "array",
                "minItems": len(exact_group_chapters) or 1,
                "items": _strict_object(
                    {
                        "event_id": string,
                        "slice_id": string,
                        "chapter_number": (
                            {"type": "integer", "enum": exact_group_chapters}
                            if exact_group_chapters
                            else {"type": "integer", "minimum": 1}
                        ),
                        "causes": {"type": "array", "items": string, "description": "Only earlier event_id values in this exact narrative_event_chain. Every edge A -> B must appear both as A.next_event_ids containing B and B.causes containing A. No external, later or self event references."},
                        "actor_ref": string,
                        "motivation": string,
                        "preconditions": {
                            "type": "array",
                            "minItems": 1,
                            "items": string,
                        },
                        "knowledge_boundary": _strict_object(
                            {
                                "actor_knows": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": string,
                                },
                                "reader_may_learn": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": string,
                                },
                                "forbidden_disclosures": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": string,
                                },
                            }
                        ),
                        "action": string,
                        "decision": string,
                        "resistance": string,
                        "consequence": string,
                        "state_deltas": {
                            "type": "array",
                            "minItems": 1,
                            "items": _strict_object(
                                {
                                    "state_kind": string,
                                    "entity_id": string,
                                    "from_state": string,
                                    "to_state": string,
                                }
                            ),
                        },
                        "disclosures": {
                            "type": "array",
                            "minItems": 1,
                            "items": string,
                        },
                        "obligation_actions": {
                            "type": "array",
                            "minItems": 1,
                            "items": string,
                        },
                        "arc_contributions": {
                            "type": "array",
                            "minItems": 1,
                            "items": arc_ref,
                        },
                        "irreversible_change": string,
                        "next_event_ids": {"type": "array", "items": string, "description": "Only later event_id values in this exact narrative_event_chain. Include every event that names this event in causes; each outgoing edge must be reciprocated in the target's causes. The final event has no later edge."},
                        "required": {"type": "boolean"},
                    }
                ),
            }
        elif field in integer_arrays:
            properties[field] = {
                "type": "array",
                "items": {"type": "integer"},
            }
            if field == "chapter_range":
                properties[field].update({"minItems": 2, "maxItems": 2})
                if exact_group_range is not None:
                    # COMPATIBILITY: OpenAI Structured Outputs rejects non-scalar ``const``
                    # values. Bound each member to the frozen endpoints here;
                    # Planning Authority still validates the exact ordered pair
                    # before the candidate can be persisted or activated.
                    properties[field]["items"]["enum"] = list(exact_group_range)
        elif field == "chapter_number":
            properties[field] = {"type": "integer", "minimum": 1}
        elif field == "chapter_function_matrix":
            arc_ref = _frozen_arc_ref_schema(arc_plan_version_ids, string)
            properties[field] = {
                "type": "array",
                "minItems": len(exact_group_chapters) or 1,
                **(
                    {"maxItems": len(exact_group_chapters)}
                    if exact_group_chapters
                    else {}
                ),
                "items": _strict_object(
                    {
                        "chapter_number": (
                            {"type": "integer", "enum": exact_group_chapters}
                            if exact_group_chapters
                            else {"type": "integer", "minimum": 1}
                        ),
                        "primary_function": string,
                        "secondary_functions": string_array,
                        "required_state_delta": _strict_object({"summary": string}),
                        "required_arc_contributions": {
                            "type": "array",
                            "minItems": 1,
                            "items": _strict_object(
                                {
                                    "arc_plan_version_id": arc_ref,
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
                                    "arc_plan_version_id": arc_ref,
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
        elif field == "narrative_density":
            properties[field] = {
                "type": "string",
                "enum": ["LOW", "MEDIUM", "HIGH"],
            }
        elif field == "arc_cadence":
            properties[field] = {
                "type": "array",
                "minItems": 1,
                "maxItems": min(3, len(arc_plan_version_ids))
                if arc_plan_version_ids
                else 3,
                "items": _strict_object(
                    {
                        "arc_plan_version_id": _frozen_arc_ref_schema(
                            arc_plan_version_ids, string
                        ),
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
            }
        elif field == "obligation_actions":
            properties[field] = {
                "type": "array",
                "items": _strict_object(
                    {
                        "obligation_id": string,
                        "action": {
                            "type": "string",
                            "enum": ["SETUP", "ADVANCE", "PAYOFF"],
                        },
                        "due_chapter": {"type": "integer", "minimum": 1},
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
    if work_requirements:
        _apply_work_planning_schema(properties, isolated=aligned_methods)
    if serialization_contract and contract_type is PlanContractType.CHAPTER:
        properties["serialization_function"] = {
            "type": ["string", "null"], "minLength": 1,
            "description": "Explicit selected serialization realization for this Chapter under the frozen Book work requirement; null only when that requirement is not applicable.",
        }
        properties["chapter_contract_schema_version"]["const"] = "chapter-mission-scene.v4"
    if contract_type is PlanContractType.CHAPTER:
        realization = dict(narrative_realization or {})
        if not realization:
            raise KernelError(
                "NARRATIVE_REALIZATION_REQUIRED",
                "Chapter provider schema requires a Frozen Narrative Realization slice",
            )
        try:
            schedule_row = require_chapter_schedule_row(
                dict(chapter_schedule_row or {}),
                chapter_number=int(realization.get("chapter_number") or 0),
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "CHAPTER_SCHEDULE_BINDING_REQUIRED",
                "Chapter provider schema requires one complete frozen Scheduling row",
            ) from exc
        for field in CHAPTER_SCHEDULE_FIELDS:
            properties[field] = _frozen_provider_value_schema(
                [schedule_row[field]], work_requirements=work_requirements
            )
        scheduled_arc_ids = sorted({item["arc_plan_version_id"] for item in (arc_working_set or {}).get("selected_contributions", ())}) if arc_working_set else sorted({item["arc_plan_version_id"] for item in schedule_row["required_arc_contributions"]})
        scheduled_arc_reference = {"type": "string", **({"const": scheduled_arc_ids[0]} if len(scheduled_arc_ids) == 1 else {"enum": scheduled_arc_ids} if scheduled_arc_ids else {})}
        schedule_schema = properties["arc_schedule"]
        schedule_schema["minItems"] = len(scheduled_arc_ids) if arc_working_set else 1 if scheduled_arc_ids else 0
        schedule_schema["maxItems"] = len(scheduled_arc_ids)
        schedule_schema["items"]["properties"]["arc_plan_version_id"] = {
            **scheduled_arc_reference,
            "description": "Cover each selected frozen Working Set Arc once when supplied; otherwise use only the Chapter row's required contributions. Unselected related context does not require scheduling or movement.",
        }
        schedule_schema["items"]["properties"]["role"]["description"] = "Preserve each selected Working Set Arc's frozen role exactly; otherwise choose one dominant role per Chapter row contribution; never repeat one Arc or promote unselected related context."
        if arc_working_set:
            selected = arc_working_set["selected_contributions"]
            if not scheduled_arc_ids or not set(scheduled_arc_ids) <= set(arc_plan_version_ids) or len(selected) != len(scheduled_arc_ids):
                raise KernelError("CHAPTER_ARC_WORKING_SET_SCOPE_INVALID", "Provider Arc scope must retain the selected unique frozen portfolio")
            alternatives = []
            for item in selected:
                alternative = json.loads(json.dumps(schedule_schema["items"]))
                alternative["properties"]["arc_plan_version_id"] = {"type": "string", "const": item["arc_plan_version_id"]}
                alternative["properties"]["role"] = {"type": "string", "const": item["role"]}
                alternatives.append(alternative)
            schedule_schema["items"] = {"anyOf": alternatives}
        contributions = properties["required_arc_contributions"]
        contributions["minItems"] = len(scheduled_arc_ids) if arc_working_set else 1 if scheduled_arc_ids else 0
        contributions["maxItems"] = len(scheduled_arc_ids)
        contributions["items"]["properties"]["arc_plan_version_id"] = dict(scheduled_arc_reference)
        progress = properties["scene_plan"]["items"]["properties"]["arc_progress"]
        progress["items"] = dict(scheduled_arc_reference)
        progress["maxItems"] = len(scheduled_arc_ids)
        scheduled_reader = dict(schedule_row["reader_experience"])
        reader_schema = dict(properties["reader_experience"])
        reader_properties = dict(reader_schema["properties"])
        for field in CHAPTER_READER_SCHEDULE_FIELDS:
            reader_properties[field] = _frozen_provider_value_schema(
                [scheduled_reader[field]], work_requirements=work_requirements
            )
        reader_schema["properties"] = reader_properties
        properties["reader_experience"] = reader_schema
        properties["narrative_realization_slice"] = _frozen_provider_value_schema(
            [realization], work_requirements=work_requirements
        )
        scene_properties = properties["scene_plan"]["items"]["properties"]
        event_ids = [str(event["event_id"]) for event in realization["events"]]
        scene_properties["realization_event_ids"]["items"] = {
            "type": "string",
            "enum": event_ids,
        }
        obligation_ids = [
            str(item["obligation_id"]) for item in schedule_row["obligation_actions"]
        ]
        if obligation_ids:
            scene_properties["obligation_refs"]["items"] = {
                "type": "string",
                "enum": obligation_ids,
            }
        else:
            scene_properties["obligation_refs"]["maxItems"] = 0
    if narrative_search:
        if contract_type is PlanContractType.CHAPTER:
            raise ValueError("Chapter planning is operational, not a search portfolio")
        properties["narrative_search_projection"] = narrative_search_projection_schema()
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
    if operational_commitments:
        if contract_type is not PlanContractType.CHAPTER:
            raise KernelError("PLANNING_OPERATIONAL_SCOPE_INVALID", "Operational commitment projection applies only to Chapter execution")
        properties["commitment_contract"]["items"]["properties"]["level"]["enum"] = ["HARD_CONSTRAINT", "SOFT_INTENT"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _apply_work_planning_schema(properties: dict[str, Any], *, isolated: bool = False) -> None:
    optional_text = set(
        "central_conflict_engine protagonist_transformation antagonist_escalation stage_conflict stage_antagonist irreversible_change midpoint climax next_volume_bridge resistance escalation turn choice cost trigger resistance_escalation local_climax information_release antagonist_actions promise_action foreshadow_action reward_action ending_hook reward_mode expected_change".split()
    )
    zero_collections = set(
        "major_turns climax_distribution long_promise_payoff required_arc_contributions arc_checkpoint_expectations arc_cadence arc_schedule knowledge_boundaries disclosures required_state_transitions information_gain state_transitions arc_progress trajectory_refs obligation_refs causal_triggers antagonist_escalation resistance_escalation antagonist_actions information_release cost_range".split()
    )

    def visit(node: dict[str, Any]) -> None:
        for name, child in node.get("properties", {}).items():
            if name in optional_text and child.get("type") == "string":
                child["type"] = ["string", "null"]
            if name in zero_collections and child.get("type") == "array":
                child["minItems"] = 0
            if name == "required_state_delta":
                child.clear()
                child.update(
                    _strict_object(
                        {
                            "status": {
                                "type": "string",
                                "enum": ["CHANGED", "NO_INCREMENT", "UNDETERMINED"],
                            },
                            "summary": {"type": ["string", "null"], "minLength": 1},
                        }
                    )
                )
            visit(child)
        if isinstance(node.get("items"), dict):
            visit(node["items"])

    if isolated:
        # WHY: deepcopy retains aliases; rebuild each occurrence before nullable mutations.
        def detach(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: detach(child) for key, child in value.items()}
            if isinstance(value, list):
                return [detach(child) for child in value]
            return value

        detached = detach(properties)
        properties.clear()
        properties.update(detached)
        optional_text.add("conflict")
    visit({"properties": properties})
    if "chapter_contract_schema_version" in properties:
        properties["chapter_contract_schema_version"]["const"] = (
            "chapter-mission-scene.v3"
        )
    if "narrative_event_chain" in properties:
        event = properties["narrative_event_chain"]["items"]
        for name in (
            "state_deltas",
            "disclosures",
            "obligation_actions",
            "arc_contributions",
            "preconditions",
        ):
            event["properties"][name]["minItems"] = 0
        for child in event["properties"]["knowledge_boundary"]["properties"].values():
            child["minItems"] = 0
        for name in ("decision", "resistance", "irreversible_change"):
            event["properties"][name] = {"type": ["string", "null"], "minLength": 1}
        event["properties"]["feature_status"] = _strict_object(
            {
                name: _strict_object(
                    {
                        "status": {
                            "type": "string",
                            "enum": ["APPLICABLE", "NOT_APPLICABLE", "PROHIBITED"],
                        },
                        "rationale": {"type": "string", "minLength": 1},
                    }
                )
                for name in ("decision", "resistance", "irreversible_change")
            }
        )
        event["required"] = list(event["properties"])


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
        return self._invoke(stable_idempotency_key=stable_idempotency_key,
            capability=capability, request_payload=request_payload, reconciliation=False)

    @execution_step("story_planning_runtime._PlanningGatewayEffectAdapter._invoke")
    def _invoke(
        self, *, stable_idempotency_key: str, capability: str,
        request_payload: dict[str, Any], reconciliation: bool, authorization: Any = None,
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
            if reconciliation:
                handle = self._existing_handle()
                if handle is None:
                    return ProviderResult("ambiguous", "", {
                        "external_state_unknown": True,
                        "recovery_instruction": "Recover original execution evidence before reconciliation; query cannot submit",
                    }, "")
            else:
                handle = self.session.gateway.submit(request)
            request_sent = True
            result = (self.session.gateway.recover_existing_execution(request, handle, authorization)
                if authorization is not None else self.session.gateway.reconcile(handle))
        except ExternalEffectAdapterError:
            raise
        except Exception as exc:
            recovered = self.session.evidence_store.find_record(request.execution_id)
            submission_phase = (
                str(recovered.raw_evidence.get("submission_phase") or "")
                if recovered is not None
                else ""
            )
            request_sent = request_sent or submission_phase in {
                "PROVIDER_INVOKING",
                "PROVIDER_OUTCOME_UNKNOWN",
                "PROVIDER_RESULT_OBSERVED",
                "PROVIDER_RESULT_RECORDED",
                "PROCESS_STARTING",
                "PROCESS_OUTCOME_UNKNOWN",
                "PROCESS_RESULT_RECORDED",
            }
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
            ExecutionOutcome.TIMED_OUT: "unknown",
            ExecutionOutcome.CORRUPT_RESULT: "retryable_failure",
            ExecutionOutcome.FINAL_FAILURE: "final_failure",
            ExecutionOutcome.CANCELLED: "cancelled",
        }.get(result.outcome, "unknown")
        if reconciliation:
            outcome = {"success": "success", "final_failure": "failed_final"}.get(outcome, "ambiguous")
        return ProviderResult(
            outcome,
            handle.backend_execution_id,
            evidence,
            handle.provider_request_id or "",
        )

    def query(self, **kwargs: Any) -> ProviderResult:
        return self._invoke(**kwargs, reconciliation=True)

    def query_recovered(self, *, attempt_command, **kwargs):
        from novel_forge.modules.production_execution.contracts import ExecutionRecoveryAction, ExecutionRecoveryAuthorization

        request = self.binding.request
        if attempt_command.attempt_id != request.attempt_id or attempt_command.project_id != request.project_id:
            raise ExternalEffectAdapterError("Planning query requires the original Attempt", request_sent=False)
        authorization = ExecutionRecoveryAuthorization(
            authorization_id=f"planning-query:{request.execution_id}:{attempt_command.fencing_token}",
            execution_id=request.execution_id, external_effect_id=request.external_effect_id,
            operation_id=request.operation_id, attempt_id=request.attempt_id,
            execution_fencing_token=request.fencing_token, recovery_fencing_token=attempt_command.fencing_token,
            recovery_worker_id=attempt_command.worker_id, action=ExecutionRecoveryAction.QUERY,
            trace_id=request.trace_id, correlation_id=request.correlation_id,
        )
        return self._invoke(**kwargs, reconciliation=True, authorization=authorization)

    def _existing_handle(self) -> Any:
        record = self.session.evidence_store.find_record(self.binding.request.execution_id)
        if record is None:
            return None
        if record.request.contract_hash != self.binding.request.contract_hash:
            raise ExternalEffectAdapterError("Planning recovery differs from its original execution contract", request_sent=False)
        return record.handle

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        request = self.binding.request
        if (stable_idempotency_key != request.stable_idempotency_key or capability != request.capability
                or str(request_payload.get("external_effect_id") or "") != request.external_effect_id):
            raise ExternalEffectAdapterError("Planning cancellation differs from its frozen request", request_sent=False)
        handle = self._existing_handle()
        if handle is None:
            return ProviderResult("ambiguous", "", {"external_state_unknown": True}, provider_request_id)
        cancellation = self.session.gateway.cancel(handle, "Planning cancellation")
        cancelled = cancellation.outcome == "CANCELLED" and (
            handle.transport != ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE
            or cancellation.upstream_cancellation_outcome == "CANCELLED"
        )
        return ProviderResult(
            "cancelled" if cancelled else "ambiguous",
            handle.backend_execution_id,
            {"production_execution_cancellation": cancellation.to_dict()},
            provider_request_id,
        )


def _nonnegative_usage_value(value: Any) -> tuple[int, bool]:
    if value in {None, ""}:
        return 0, True
    if isinstance(value, bool):
        return 0, False
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0, False
    return (normalized, True) if normalized >= 0 else (0, False)


def _is_nonnegative_decimal(value: str) -> bool:
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    return amount.is_finite() and amount >= 0


def _planning_budget_settlement(
    *,
    usage: Mapping[str, Any],
    cost: Mapping[str, Any],
    fixture: bool,
    supports_usage_receipt: bool,
    supports_cost_receipt: bool,
    reserved_amount: str | None,
    reserved_tokens: int,
) -> dict[str, Any]:
    input_tokens, input_valid = _nonnegative_usage_value(usage.get("input_tokens"))
    output_tokens, output_valid = _nonnegative_usage_value(usage.get("output_tokens"))
    declared_total, total_valid = _nonnegative_usage_value(usage.get("total_tokens"))
    measured_total = max(declared_total, input_tokens + output_tokens)
    account_entitlement = reserved_amount is None
    reported_amount = None if account_entitlement else str(cost.get("amount") or "0")
    if account_entitlement:
        usage_authoritative = bool(
            supports_usage_receipt
            and input_valid
            and output_valid
            and total_valid
            and measured_total > 0
        )
        total_tokens = measured_total if usage_authoritative else reserved_tokens
        usage_basis = (
            "PROVIDER_USAGE_RECEIPT" if usage_authoritative else "RESERVATION_CEILING"
        )
        return {
            "amount": None,
            "total_tokens": total_tokens,
            "reported_amount": None,
            "usage_basis": usage_basis,
            "cost_basis": "ACCOUNT_ENTITLEMENT_UNKNOWN",
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "cost_status": "UNKNOWN",
            "usage": {
                **dict(usage),
                "total_tokens": measured_total if usage_authoritative else None,
                "conservative_reserved_tokens": total_tokens,
                "budget_settlement_basis": usage_basis,
            },
            "cost": {
                **dict(cost),
                "amount": None,
                "accounting_basis": "ACCOUNT_ENTITLEMENT",
                "cost_status": "UNKNOWN",
                "budget_settlement_basis": "ACCOUNT_ENTITLEMENT_UNKNOWN",
            },
        }
    assert reported_amount is not None
    if fixture:
        if (
            not input_valid
            or not output_valid
            or not total_valid
            or not _is_nonnegative_decimal(reported_amount)
        ):
            raise KernelError(
                "PLANNING_FIXTURE_BUDGET_EVIDENCE_INVALID",
                "scripted Planning budget evidence is malformed",
            )
        return {
            "amount": reported_amount,
            "total_tokens": measured_total,
            "reported_amount": reported_amount,
            "usage_basis": "FIXTURE_RECEIPT",
            "cost_basis": "FIXTURE_RECEIPT",
            "usage": {
                **dict(usage),
                "total_tokens": measured_total,
                "budget_settlement_basis": "FIXTURE_RECEIPT",
            },
            "cost": {
                **dict(cost),
                "provider_reported_amount": reported_amount,
                "amount": reported_amount,
                "budget_settlement_basis": "FIXTURE_RECEIPT",
            },
        }
    usage_authoritative = bool(
        supports_usage_receipt
        and input_valid
        and output_valid
        and total_valid
        and measured_total > 0
    )
    total_tokens = measured_total if usage_authoritative else reserved_tokens
    usage_basis = (
        "PROVIDER_USAGE_RECEIPT" if usage_authoritative else "RESERVATION_CEILING"
    )
    cost_authoritative = bool(
        supports_cost_receipt
        and str(cost.get("availability") or "").upper() == "AVAILABLE"
        and _is_nonnegative_decimal(reported_amount)
        and cost.get("source") not in {"usage_pricing", "usage_pricing_upper_bound"}
        and cost.get("provider_billed") is True
    )
    usage_priced = bool(
        usage_authoritative
        and cost.get("source") in {"usage_pricing", "usage_pricing_upper_bound"}
        and cost.get("measurement") in {"PRICED_FROM_PROVIDER_USAGE", "ESTIMATED_UPPER_BOUND"}
        and cost.get("pricing_version") and cost.get("pricing_snapshot")
        and _is_nonnegative_decimal(reported_amount)
    )
    legacy_pricing = bool(
        usage_authoritative and supports_cost_receipt
        and cost.get("measurement") == "ESTIMATED"
        and cost.get("pricing_ref") and cost.get("pricing_snapshot_hash")
        and cost.get("calculation_basis") and _is_nonnegative_decimal(reported_amount)
    )
    amount = reported_amount if cost_authoritative or usage_priced or legacy_pricing else reserved_amount
    cost_basis = (
        "PROVIDER_COST_RECEIPT" if cost_authoritative else "LEGACY_PRICING_ESTIMATE" if legacy_pricing else "FROZEN_USAGE_PRICING" if usage_priced else "RESERVATION_CEILING"
    )
    return {
        "amount": amount,
        "total_tokens": total_tokens,
        "reported_amount": reported_amount,
        "usage_basis": usage_basis,
        "cost_basis": cost_basis,
        "usage": {
            **dict(usage),
            "total_tokens": total_tokens,
            "budget_settlement_basis": usage_basis,
        },
        "cost": {
            **dict(cost),
            "provider_reported_amount": reported_amount,
            "amount": amount,
            "budget_settlement_basis": cost_basis,
        },
    }


_PLANNING_PROVIDER_RESULT_RECORDED_PHASES = frozenset(
    {"PROVIDER_RESULT_RECORDED", "PROCESS_RESULT_RECORDED"}
)
_PLANNING_PROVIDER_AMBIGUOUS_PHASES = frozenset(
    {
        "PROVIDER_INVOKING",
        "PROVIDER_OUTCOME_UNKNOWN",
        "PROCESS_STARTING",
        "PROCESS_OUTCOME_UNKNOWN",
    }
)


def _planning_failed_provider_submission_state(
    dispatched: Mapping[str, Any],
) -> str:

    outcome = str(dispatched.get("outcome") or "unknown").strip().lower()
    if outcome in {"unknown", "ambiguous"}:
        return "AMBIGUOUS"
    provider = dispatched.get("provider_evidence")
    provider = provider if isinstance(provider, Mapping) else {}
    production = provider.get("production_execution")
    process = (
        production.get("process_evidence") if isinstance(production, Mapping) else None
    )
    process = process if isinstance(process, Mapping) else {}
    if process.get("submission_phase") == "PROVIDER_RESULT_OBSERVED":
        return "AMBIGUOUS"
    declared = [
        value
        for value in (
            dispatched.get("request_sent"),
            provider.get("request_sent"),
            process.get("request_sent"),
        )
        if isinstance(value, bool)
    ]
    if declared:
        if any(value != declared[0] for value in declared[1:]):
            return "AMBIGUOUS"
        return "SENT" if declared[0] else "NOT_SENT"
    if any(
        str(value).strip().lower() in {"unknown", "not_established"}
        for value in (
            dispatched.get("request_sent"),
            provider.get("request_sent"),
            process.get("request_sent"),
        )
        if value is not None
    ):
        return "AMBIGUOUS"
    submission_phase = str(process.get("submission_phase") or "").strip().upper()
    if submission_phase in _PLANNING_PROVIDER_RESULT_RECORDED_PHASES:
        return "SENT"
    if submission_phase in _PLANNING_PROVIDER_AMBIGUOUS_PHASES:
        return "AMBIGUOUS"
    return "AMBIGUOUS"


def _planning_failed_provider_measurement(
    dispatched: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    provider = dispatched.get("provider_evidence")
    production = (
        provider.get("production_execution") if isinstance(provider, Mapping) else None
    )
    process = (
        production.get("process_evidence") if isinstance(production, Mapping) else None
    )
    usage = process.get("usage") if isinstance(process, Mapping) else None
    cost = process.get("cost") if isinstance(process, Mapping) else None
    if (
        not isinstance(usage, Mapping)
        or not isinstance(cost, Mapping)
        or str(usage.get("availability") or "").upper() != "AVAILABLE"
        or str(usage.get("measurement") or "").upper() not in {"MEASURED", "PROVIDER_REPORTED"}
        or str(cost.get("availability") or "").upper() != "AVAILABLE"
        or not _is_nonnegative_decimal(str(cost.get("amount") or ""))
    ):
        return None
    return usage, cost


def _planning_failed_provider_budget_decision(
    *,
    dispatched: Mapping[str, Any],
    capability_profile: ProviderCapabilityProfile,
    reserved_amount: str | None,
    reserved_tokens: int,
) -> dict[str, Any]:
    submission_state = _planning_failed_provider_submission_state(dispatched)
    if submission_state == "NOT_SENT":
        return {"disposition": "RELEASE", "submission_state": submission_state}
    if submission_state == "AMBIGUOUS":
        return {
            "disposition": "HOLD_UNKNOWN",
            "submission_state": submission_state,
        }
    provider = dispatched.get("provider_evidence")
    provider = provider if isinstance(provider, Mapping) else {}
    measurement = _planning_failed_provider_measurement(dispatched)
    usage, cost = measurement or ({}, {})
    settlement = _planning_budget_settlement(
        usage=usage,
        cost=cost,
        fixture=bool(provider.get("fixture_protocol_only")) if measurement else False,
        supports_usage_receipt=capability_profile.supports_usage_receipt,
        supports_cost_receipt=capability_profile.supports_cost_receipt,
        reserved_amount=reserved_amount,
        reserved_tokens=reserved_tokens,
    )
    return {
        "disposition": "SETTLE",
        "submission_state": submission_state,
        "measurement_available": measurement is not None,
        "settlement": settlement,
    }


def _planning_budget_capability_profile(
    *,
    adapter: _PlanningGatewayEffectAdapter,
    recovered_completion: Mapping[str, Any] | None,
) -> ProviderCapabilityProfile:
    if recovered_completion is not None:
        frozen = recovered_completion.get("provider_capability_profile")
        if not isinstance(frozen, Mapping) or not frozen:
            raise KernelError(
                "EFFECT_PROVIDER_CAPABILITY_MISSING",
                "durable Planning result has no first-send capability profile",
            )
        try:
            profile = capability_profile_from_dict(dict(frozen))
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "EFFECT_PROVIDER_CAPABILITY_INVALID",
                "durable Planning result capability profile is invalid",
            ) from exc
    else:
        profile = adapter.capability_profile
    if profile.provider != adapter.provider:
        raise KernelError(
            "EFFECT_PROVIDER_CAPABILITY_CONFLICT",
            "Planning budget capability profile belongs to another Provider",
        )
    return profile


@dataclass(slots=True)
class _PlanningPepPort:
    database_url: str
    worker_id: str
    lease_seconds: int
    context: EffectCommandContext
    effect_id: str
    stable_key: str
    reservation_id: str
    reserved_amount: str | None
    reserved_tokens: int
    binding: _PlanningExecutionBinding
    adapter: _PlanningGatewayEffectAdapter
    recovered_completion: dict[str, Any] | None
    writer: AuthorityAssetWriter
    post_provider_fault_injector: Callable[[str], None]
    realization_selector_catalog: dict[str, Any] | None = None

    @property
    def generated_title_contract(self) -> str | None:
        return "generated-book-title.v1" if "generated-title-v1" in self.binding.route_snapshot.output_schema_ref.split(":") else None

    external_effect_backed = True
    production_execution_gateway_backed = True

    @execution_step("story_planning_runtime._PlanningPepPort.execute")
    def execute(self, command: DomainExecutionCommand) -> DomainExecutionCandidate:
        if command.capability != self.binding.request.capability:
            raise KernelError(
                "PLANNING_PEP_CAPABILITY_DRIFT",
                "Planning command differs from the frozen execution capability",
            )
        if self.recovered_completion and self.recovered_completion.get("budget_usage_correction"):
            self.recovered_completion = self._verified_reconciled_completion()
        try:
            dispatched = self.recovered_completion or dispatch_external_effect(
                self.database_url,
                self.context,
                effect_id=self.effect_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                adapter=self.adapter,
                budget_reservation_id=self.reservation_id,
            )
        except Exception as exc:
            if getattr(exc, "code", "") != "RUNTIME_DISPATCH_PAUSED":
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=self.reservation_id,
                    project_id=self.context.project_id,
                )
            raise
        recovered_completion = self.recovered_completion is not None
        if recovered_completion:
            dispatched = {**dispatched, "outcome": "success"}
        capability_profile = _planning_budget_capability_profile(
            adapter=self.adapter,
            recovered_completion=self.recovered_completion,
        )
        if dispatched["outcome"] != "success":
            budget_decision = _planning_failed_provider_budget_decision(
                dispatched=dispatched,
                capability_profile=capability_profile,
                reserved_amount=self.reserved_amount,
                reserved_tokens=self.reserved_tokens,
            )
            outcome = str(dispatched.get("outcome") or "unknown")
            disposition = str(budget_decision["disposition"])
            if disposition == "RELEASE":
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=self.reservation_id,
                    project_id=self.context.project_id,
                )
            elif disposition == "HOLD_UNKNOWN":
                resolve_provider_budget_failure(
                    self.database_url,
                    reservation_id=self.reservation_id,
                    project_id=self.context.project_id,
                    external_state_unknown=True,
                )
            elif disposition == "SETTLE":
                settlement = dict(budget_decision["settlement"])
                amount_value = settlement["amount"]
                amount = str(amount_value) if amount_value is not None else None
                total_tokens = int(settlement["total_tokens"])
                usage = dict(settlement["usage"])
                cost = dict(settlement["cost"])
                evidence = dispatched.get("provider_evidence")
                provider_evidence = evidence if isinstance(evidence, Mapping) else {}
                settle_provider_budget(
                    self.database_url,
                    reservation_id=self.reservation_id,
                    project_id=self.context.project_id,
                    actual_amount=amount,
                    actual_tokens=total_tokens,
                    evidence={
                        "provider_id": str(provider_evidence.get("provider_id") or ""),
                        "model_id": str(provider_evidence.get("model_id") or ""),
                        "real_model_call": bool(
                            provider_evidence.get("real_model_call")
                        ),
                        "fixture": bool(provider_evidence.get("fixture_protocol_only")),
                        "execution_outcome": outcome.upper(),
                        "accepted_candidate": False,
                        "submission_state": str(budget_decision["submission_state"]),
                        "measurement_available": bool(
                            budget_decision["measurement_available"]
                        ),
                        "usage_settlement_basis": str(settlement["usage_basis"]),
                        "cost_settlement_basis": str(settlement["cost_basis"]),
                        "accounting_basis": str(
                            settlement.get("accounting_basis") or "PRICED"
                        ),
                        "cost_status": str(settlement.get("cost_status") or "KNOWN"),
                    },
                )
                self._record_model_evidence(
                    evidence=provider_evidence,
                    usage=usage,
                    cost=cost,
                    amount=amount,
                    total_tokens=total_tokens,
                    accepted_candidate=False,
                    recovered_completion=False,
                    failure={
                        "code": "PLANNING_PROVIDER_NON_SUCCESS",
                        "outcome": outcome,
                        "submission_state": str(budget_decision["submission_state"]),
                        "budget_disposition": "SETTLED",
                    },
                )
            else:  # pragma: no cover - the pure decision contract is exhaustive
                raise KernelError(
                    "PLANNING_BUDGET_FAILURE_DISPOSITION_INVALID",
                    "Planning Provider failure produced an unsupported budget action",
                )
            code = (
                "MODEL_EFFECT_RETRYABLE_PLANNING"
                if outcome in {"retryable_failure", "not_found"}
                else "MODEL_EFFECT_FINAL_PLANNING"
            )
            production_failure = (dispatched.get("provider_evidence") or {}).get("production_execution") or {}
            failure = (production_failure.get("execution_result") or {}).get("error") or (production_failure.get("process_evidence") or {}).get("failure") or {}
            if outcome in {"unknown", "ambiguous"}:
                code = "MODEL_EFFECT_OUTCOME_UNKNOWN_" + str(failure.get("cause_code") or failure.get("error_code") or "ORIGINAL_RESULT_UNRECOVERABLE")
            raise KernelError(code, f"Planning provider outcome was {outcome}; cause={failure.get('error_code', 'UNCLASSIFIED_PROVIDER_FAILURE')}", details=failure)
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
        self.post_provider_fault_injector(
            "after_provider_receipt_before_budget_settlement"
        )
        fixture = bool(evidence.get("fixture_protocol_only"))
        real_model_call = bool(evidence.get("real_model_call"))
        settlement = _planning_budget_settlement(
            usage=usage,
            cost=cost,
            fixture=fixture,
            supports_usage_receipt=capability_profile.supports_usage_receipt,
            supports_cost_receipt=capability_profile.supports_cost_receipt,
            reserved_amount=self.reserved_amount,
            reserved_tokens=self.reserved_tokens,
        )
        if self.recovered_completion and self.recovered_completion.get("budget_usage_correction"):
            correction = self.recovered_completion["budget_usage_correction"]
            settlement = {**settlement, "total_tokens": correction["actual_tokens"], "usage_basis": "ORIGINAL_RECEIPT_RECONCILIATION",
                "usage": {**dict(usage), "budget_settlement_basis": "ORIGINAL_RECEIPT_RECONCILIATION"}}
        amount_value = settlement["amount"]
        amount = str(amount_value) if amount_value is not None else None
        total_tokens = int(settlement["total_tokens"])
        usage_settlement_basis = str(settlement["usage_basis"])
        cost_settlement_basis = str(settlement["cost_basis"])
        reported_value = settlement["reported_amount"]
        reported_amount = str(reported_value) if reported_value is not None else None
        normalized_usage = dict(settlement["usage"])
        normalized_cost = dict(settlement["cost"])
        settle_provider_budget(
            self.database_url,
            reservation_id=self.reservation_id,
            project_id=self.context.project_id,
            actual_amount=amount,
            actual_tokens=total_tokens,
            evidence={
                "provider_id": str(evidence.get("provider_id") or ""),
                "model_id": str(evidence.get("model_id") or ""),
                "real_model_call": real_model_call,
                "fixture": fixture,
                "usage_settlement_basis": usage_settlement_basis,
                "cost_settlement_basis": cost_settlement_basis,
                "provider_reported_cost_amount": reported_amount,
                "accounting_basis": str(settlement.get("accounting_basis") or "PRICED"),
                "cost_status": str(settlement.get("cost_status") or "KNOWN"),
            },
        )
        try:
            self.post_provider_fault_injector(
                "after_measured_usage_before_candidate_acceptance"
            )
        except KernelError as exc:
            self._record_model_evidence(
                evidence=evidence,
                usage=normalized_usage,
                cost=normalized_cost,
                amount=amount,
                total_tokens=total_tokens,
                accepted_candidate=False,
                recovered_completion=recovered_completion,
                failure={"code": exc.code, "message": str(exc)},
            )
            raise
        self._record_model_evidence(
            evidence=evidence,
            usage=normalized_usage,
            cost=normalized_cost,
            amount=amount,
            total_tokens=total_tokens,
            accepted_candidate=False,
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
                execution_id=str(execution_result["execution_id"]) if dispatched.get("budget_usage_correction") else request.execution_id,
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

    def _verified_reconciled_completion(self):
        from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand

        request = self.binding.request
        if request.operation_id != self.context.operation_id or request.project_id != self.context.project_id:
            raise KernelError("PLANNING_RECOVERY_FENCE_DRIFT", "Recovery consumer differs from the original owner")
        verified = read_succeeded_external_effect(self.database_url, self.context, effect_id=self.effect_id,
            attempt_command=WorkerLeaseCommand(request.attempt_id, request.project_id, self.worker_id,
                request.fencing_token, request.trace_id, request.correlation_id))
        if verified is None or verified.get("budget_usage_correction") != self.recovered_completion.get("budget_usage_correction"):
            raise KernelError("PLANNING_RECOVERY_RECEIPT_DRIFT", "Consume only the current verified original reconciliation")
        production = verified["provider_evidence"]["production_execution"]
        if production["execution_request"].get("capability") != request.capability:
            raise KernelError("PLANNING_PEP_CAPABILITY_DRIFT", "Recovered capability differs from the original request")
        for original, current, identity_keys in (
            (production["input_manifest"], self.binding.input_manifest.to_dict(), {"manifest_id", "operation_id", "attempt_id", "fencing_token"}),
            (production["route_snapshot"], self.binding.route_snapshot.to_dict(), {"route_snapshot_id", "route_decision_id", "operation_id", "attempt_id"}),
        ):
            if ({k: v for k, v in original.items() if k not in identity_keys}
                    != {k: v for k, v in current.items() if k not in identity_keys}):
                raise KernelError("PLANNING_RECOVERY_INPUT_DRIFT", "Recovery must retain the original input hashes and frozen route")
        return verified

    @execution_step("story_planning_runtime._PlanningPepPort._record_model_evidence")
    def _record_model_evidence(
        self,
        *,
        evidence: Mapping[str, Any],
        usage: Mapping[str, Any],
        cost: Mapping[str, Any],
        amount: str | None,
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
                "candidate_validation_status": "FAILED" if failure else "PENDING_DOMAIN_VALIDATION",
            },
        )
        if recovered_completion:
            return
        self._record_evidence(
            "cost_ledger",
            {
                "availability": "UNAVAILABLE" if amount is None else "AVAILABLE",
                "measurement": "UNKNOWN" if amount is None else "MEASURED",
                "amount": amount,
                "currency": (
                    "UNKNOWN" if amount is None else str(cost.get("currency") or "USD")
                ),
                "accounting_basis": (
                    "ACCOUNT_ENTITLEMENT" if amount is None else "PRICED"
                ),
                "cost_status": "UNKNOWN" if amount is None else "KNOWN",
                "total_tokens": total_tokens,
                "usage": dict(usage),
                "cost": dict(cost),
                "candidate_accepted": accepted_candidate,
                "provider_invoked_this_attempt": True,
                "recovered_external_effect_success": False,
                "post_provider_failure": dict(failure or {}),
            },
        )

    @execution_step("story_planning_runtime._PlanningPepPort._record_evidence")
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
                asset_id=(
                    f"{asset_type}:{request.operation_id}:{request.attempt_id}"
                    + (
                        f":{request.stage}"
                        if request.stage.startswith("world_candidates.")
                        else ""
                    )
                ),
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
        self.cost_accounting_basis = str(
            getattr(execution_transport, "cost_accounting_basis", "PRICED") or "PRICED"
        ).upper()
        self.account_authorization_ref = str(
            getattr(execution_transport, "account_authorization_ref", "") or ""
        )
        self.provider_call_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(execution_transport, "provider_call_caps", {}) or {}
            ).items()
        }
        self.provider_token_caps = {
            str(key): int(value)
            for key, value in dict(
                getattr(execution_transport, "provider_token_caps", {}) or {}
            ).items()
        }
        if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT" and (
            not self.account_authorization_ref or self.budget_caps
        ):
            raise ValueError(
                "Planning account-entitlement execution requires authorization and no monetary caps"
            )
        self.lease_seconds = lease_seconds
        self.post_provider_fault_injector = post_provider_fault_injector or (
            lambda _checkpoint: None
        )
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)
        self.pack_runtime = CapabilityPackRuntimeResolver(database_url)
        self.mkaos = MkaosAuthorityQuery(database_url)

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
        from novel_forge.modules.production_execution.domain_execution import (
            DomainModelOperation,
        )

        from .world_preparation import PlanningWorldPreparation

        arguments = dict(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
            command=command,
            inputs=inputs,
            definition=definition,
            attempt_snapshot=attempt_snapshot,
        )
        action = None
        if command.world_preparation_request:
            context_policy_content = self.pack_runtime.materialize_attempt_artifacts(attempt_snapshot).context_policy.content
            knowledge_context, _ = self._context_bundle(
                operation_id=operation_id, attempt_id=attempt_id, command=command, inputs=inputs,
                context_policy_ref=attempt_snapshot.execution_snapshot.context_policy_ref,
                planning_task_token_budget=json.loads(attempt_snapshot.execution_snapshot.context_policy_payload_json).get("planning_task_token_budget", context_policy_content.get("planning_task_token_budget")),
            )

            def execute_stage(stage):
                prepared = self._prepare_stage(**arguments, provider_stage=stage)
                return prepared.execution_port.execute(
                    DomainExecutionCommand(
                        capability=definition.capability,
                        operation=DomainModelOperation.GENERATE,
                        candidate_kind=CandidateKind.GENERATION,
                        prompt=stage.name,
                        context=stage.task,
                    )
                )

            action = PlanningWorldPreparation(self).prepare(
                operation_id=operation_id, command=command, execute_stage=execute_stage,
                knowledge_selection=knowledge_context.content.get("narrative_intelligence") or {},
            )
        return self._prepare_stage(**arguments, world_action=action)

    def _prepare_stage(
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
        provider_stage: Any = None,
        world_action: AuthorityAssetDocument | None = None,
        frozen_world_sample: Any = None,
    ) -> PreparedPlanningExecution:
        stage_name = (
            provider_stage.name
            if provider_stage is not None
            else command.generator_operation_name
        )
        stage_identity = (
            provider_stage.name if provider_stage is not None else "planning"
        )
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
        pack_materialization = self.pack_runtime.materialize_attempt_artifacts(attempt_snapshot)
        if frozen_world_sample is not None:
            from .world_sampling import require_frozen_world_execution

            require_frozen_world_execution(self.database_url, operation_id=operation_id, command=command,
                inputs=inputs, provider_stage=provider_stage, frozen=frozen_world_sample)
            context_document = frozen_world_sample.context
            input_documents = (*frozen_world_sample.input_documents, frozen_world_sample.source)
            if frozen_world_sample.generation_sample is not None:
                context_document, _ = self._world_context_bundle(operation_id=operation_id, command=command,
                    base=context_document, stage=provider_stage, calibration_sample=True)
                if context_document.content != frozen_world_sample.derived_context:
                    raise KernelError("WORLD_SAMPLE_CONTEXT_DRIFT", "reference execution must retain its preflight Context hash")
        else:
            context_document, input_documents = self._context_bundle(
                operation_id=operation_id,
                attempt_id=attempt_id,
                command=command,
                inputs=inputs,
                context_policy_ref=frozen.context_policy_ref,
                planning_task_token_budget=json.loads(frozen.context_policy_payload_json).get("planning_task_token_budget", pack_materialization.context_policy.content.get("planning_task_token_budget")),
            )
        if provider_stage is not None and frozen_world_sample is None:
            context_document, source_document = self._world_context_bundle(
                operation_id=operation_id,
                command=command,
                base=context_document,
                stage=provider_stage,
            )
            input_documents = (*input_documents, source_document)
        chapter_schedule_row: dict[str, Any] | None = None
        if command.planning_scope.value == PlanContractType.CHAPTER.value:
            by_role = {
                item.role: document
                for item, document in zip(
                    inputs, input_documents[: len(inputs)], strict=True
                )
            }
            schedule_source = by_role.get("chapter_function_matrix_row")
            if schedule_source is None:
                raise KernelError(
                    "CHAPTER_SCHEDULE_BINDING_REQUIRED",
                    "Chapter generation lacks its frozen Scheduling input",
                )
            try:
                chapter_schedule_row = require_chapter_schedule_row(
                    schedule_source.content,
                    chapter_number=int(
                        (command.narrative_realization or {}).get("chapter_number") or 0
                    ),
                )
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "CHAPTER_SCHEDULE_BINDING_INVALID",
                    "Frozen Scheduling input does not contain one complete Chapter row",
                ) from exc
        tools = json.loads(frozen.tool_policy_payload_json)
        allowed_tools = self._allowed_tools(tools, stage_name if frozen_world_sample is not None else command.generator_operation_name)
        if allowed_tools != ("model.provider.invoke",):
            raise KernelError(
                "PLANNING_CAPABILITY_TOOL_UNAUTHORIZED",
                "Planning Codex execution permits only model.provider.invoke",
            )
        output_schema = (
            foundation_output_schema(
                command.generator_operation_name,
                generated_title=context_document.content.get("generated_title_contract") == "generated-book-title.v1",
                rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
                narrative_search=bool(command.narrative_search_id) and command.execution_contract_version == "1.21.0",
                work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
            )
            if command.generator_operation_name in FOUNDATION_GENERATORS
            else planning_provider_output_schema(
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
                narrative_search=bool(command.narrative_search_id),
                narrative_search_horizon=(command.narrative_search_planning_horizon),
                narrative_realization=command.narrative_realization,
                chapter_schedule_row=chapter_schedule_row,
                arc_working_set=command.arc_working_set,
                work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
                aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
                serialization_contract=command.execution_contract_version in {"1.19.0", "1.21.0"},
                typed_volume_allocation=command.execution_contract_version == "1.21.0",
                operational_commitments=command.execution_contract_version == "1.21.0" and command.planning_scope.value == PlanContractType.CHAPTER.value,
            )
        )
        if (
            world_action is not None
            and world_action.content["contract"].get("contract_version")
            == "world-production-action.v2"
        ):
            from novel_forge.modules.canon_graph.background import (
                public_world_direction,
            )

            direction = public_world_direction(
                {
                    "asset_version_id": world_action.asset_version_id,
                    "content_hash": world_action.content_hash,
                    "action": world_action.content["contract"],
                }
            )
            names = [event["transition_id"] for event in direction["on_camera_events"]]
            if names:
                scene = output_schema["properties"]["scene_plan"]["items"]
                scene["properties"]["world_event_ids"] = {
                    "type": "array",
                    "items": {"type": "string", "enum": names},
                    "description": "Assign each selected on-camera world event to exactly one Scene. Plans do not prove occurrence.",
                }
                scene["required"].append("world_event_ids")
        output_schema_ref = (
            "schema:planning-provider-output:"
            + command.planning_scope.value.lower()
            + (
                ":v5"
                if command.planning_scope.value == PlanContractType.CHAPTER.value
                else ":v3"
                if command.planning_scope.value == PlanContractType.CHAPTER_GROUP.value
                else ":v1"
            )
        )
        if command.generator_operation_name in FOUNDATION_GENERATORS:
            output_schema_ref = foundation_output_schema_ref(command.generator_operation_name, execution_contract_version=command.execution_contract_version, narrative_search=bool(command.narrative_search_id) and command.execution_contract_version == "1.21.0")
            if context_document.content.get("generated_title_contract") == "generated-book-title.v1":
                output_schema_ref += ":generated-title-v1"
        if command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"} and command.generator_operation_name not in FOUNDATION_GENERATORS:
            output_schema_ref += ":work-v4" if command.execution_contract_version in {"1.19.0", "1.21.0"} else ":work-v3" if command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"} else ":work-v2"
        if command.planning_scope.value == PlanContractType.BOOK.value and command.execution_contract_version == "1.21.0":
            output_schema_ref += ":volume-allocation-v2"
        if command.execution_contract_version == "1.21.0" and command.generator_operation_name not in FOUNDATION_GENERATORS and provider_stage is None:
            output_schema = bind_realization_selector_schema(
                output_schema, context_document.content["realization_reference_contract"],
                primary_arc_id=str(command.input_versions.get("arc_plans") or ""),
                related_arc_ids=command.related_arc_plan_version_ids,
            )
            output_schema_ref += ":host-selectors-v2"
            if context_document.content["realization_reference_contract"].get("character_references") is not None:
                output_schema_ref += ":frozen-character-references-v1"
            if context_document.content.get("planning_semantic_fields_version") in {"planning-semantic-fields.v1", "planning-semantic-fields.v2"}:
                from .semantic_fields import bind_semantic_fields
                version = context_document.content["planning_semantic_fields_version"]
                output_schema = bind_semantic_fields(output_schema, command.planning_scope,
                    story_state_version=command.input_versions.get("story_state") if version == "planning-semantic-fields.v2" else None)
                output_schema_ref += ":" + version.replace(".", "-")
        if provider_stage is None and command.repair_of_candidate_id and command.planning_scope.value == PlanContractType.CHAPTER.value:
            output_schema_ref += ":operational-commitments-v1"
        if provider_stage is not None:
            output_schema = dict(provider_stage.output_schema)
            output_schema_ref = provider_stage.output_schema_ref
        else:
            from .knowledge_translation import add_translation_contract

            if command.edition_execution:
                output_schema_ref += ":book-edition-planning-v1"
            output_schema = add_translation_contract(
                output_schema, context_document.content.get("narrative_intelligence") or {}
            )
            from novel_forge.modules.story_design_authority.author_input import add_author_decision_contract
            output_schema = add_author_decision_contract(output_schema, context_document.content.get("author_design_projection") or {})
            if (context_document.content.get("author_design_projection") or {}).get("fragments"):
                output_schema_ref += ":author-input-v1"
            if command.execution_contract_version == "1.21.0" and command.planning_scope.value == PlanContractType.CHAPTER.value:
                from novel_forge.modules.hierarchical_planning.epistemic_validation import bind_planned_knowledge_schema

                output_schema = bind_planned_knowledge_schema(output_schema, by_role["story_state"].content)
                output_schema_ref += ":accepted-knowledge-v1"
        if (pack_materialization.prompt_template.ref, pack_materialization.prompt_template.version) == ("prompt-template:story-planning-pack", "v3"):
            from novel_forge.modules.chapter_authority.provider_views import bind_narrative_intent_schema

            output_schema = bind_narrative_intent_schema(
                output_schema,
                event_first_planning=(pack_materialization.skill.ref, pack_materialization.skill.version)
                == ("long-outline", "long-outline-v5"),
            )
            output_schema_ref += ":narrative-intent-v1"
        context_selection = [
            {
                "artifact_ref": f"asset-version:{context_document.asset_version_id}",
                "asset_version_id": context_document.asset_version_id,
                "artifact_type": "context_bundle",
                "content_hash": context_document.content_hash,
                "schema_version": "novelos.planning_context_bundle.v1",
                "source_eligibility": "PRODUCTION_ELIGIBLE",
                "content": context_document.content,
            }
        ]
        frozen_context_policy = json.loads(frozen.context_policy_payload_json)
        route_identity = ":".join(
            (
                command.generator_operation_name,
                self.planning_route.model_profile.model_provider,
                self.planning_route.model_profile.model_id,
                self.planning_route.release_sha,
                attempt_snapshot.snapshot_hash,
            )
        )
        effective_context_policy = _provider_effective_context_policy(
            context_selection=context_selection,
            context_policy_payload=frozen_context_policy,
            context_policy_hash=frozen.context_policy_hash,
            context_policy_ref=frozen.context_policy_ref,
            route_identity=route_identity,
            route_allowed_physical_types=("context_bundle",),
        )
        materialization = {
            "schema_version": "novelos.planning_capability_materialization.v1",
            "stage": stage_name,
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
            "context_selection": context_selection,
            "effective_context_policy": effective_context_policy,
            "knowledge_selection": [
                item.to_dict(include_content=True)
                for item in pack_materialization.required_knowledge
            ],
            "narrative_intelligence_selection": context_document.content.get(
                "narrative_intelligence", {}
            ),
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
        if provider_stage is not None and provider_stage.task.get("role") == "ACTOR":
            materialization["knowledge_selection"] = []
            materialization["narrative_intelligence_selection"] = {}
            materialization["source_isolation"] = {"policy": "world-actor-private-projection.v1", "unscoped_knowledge": "EXCLUDED"}
        materialization["materialization_hash"] = canonical_hash(materialization)
        materialization_ref = (
            "production_execution/capability_materializations/"
            + _token(
                f"{command.project_id}:{operation_id}:{attempt_id}:{stage_identity}"
            )
        )
        effect_context = EffectCommandContext(
            operation_id=operation_id,
            project_id=command.project_id,
            actor_id=worker_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
        )
        stable_key = f"{operation_id}:{definition.capability}:planning-pep-v2"
        if provider_stage is not None:
            stable_key = f"{operation_id}:{definition.capability}:{stage_identity}:v1"
        if getattr(self.execution_transport, "resource_control_version", "") == "billing-channel-resources.v1":
            from novel_forge.modules.command_kernel.resource_route_recovery import next_resource_effect_key
            stable_key = next_resource_effect_key(self.database_url, project_id=command.project_id,
                operation_id=operation_id, stable_key=stable_key)
        planning_route = self.planning_route
        routing_decision = None
        provider_router = getattr(self.execution_transport, "provider_router", None)
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
            arc_working_set=command.arc_working_set,
            work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
            aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
            rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
        )
        try:
            context_policy = json.loads(frozen.context_policy_payload_json)
            frozen_request_token_ceiling = int(context_policy.get("max_tokens") or 0)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KernelError(
                "PLANNING_PROVIDER_TOKEN_CEILING_INVALID",
                "frozen Planning context policy has no valid token ceiling",
            ) from exc
        provider_token_contract = {"max_output_tokens": 1}
        stable_request_payload = {
            "stage": stage_name,
            "max_output_tokens": provider_token_contract["max_output_tokens"],
            "provider_token_contract": provider_token_contract,
            "input": {
                **(
                    {
                        "foundation_task": foundation_task(
                            command.generator_operation_name,
                            generated_title=context_document.content.get("generated_title_contract") == "generated-book-title.v1",
                            work_requirements=command.execution_contract_version
                            in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
                            aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
                            rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
                            narrative_search=command.execution_contract_version == "1.21.0" and bool(command.narrative_search_id),
                        )
                    }
                    if command.generator_operation_name in FOUNDATION_GENERATORS
                    else {}
                ),
                "planning_command": {
                    **({"generated_title_contract": context_document.content["generated_title_contract"]}
                        if context_document.content.get("generated_title_contract") else {}),
                    **({"execution_contract_version": command.execution_contract_version} if command.execution_contract_version in {"1.19.0", "1.21.0"} else {}),
                    **({"creative_requirements_contract": "work-requirements.v2" if command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"} else "work-requirements.v1"} if command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"} else {}),
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
                    "arc_working_set": dict(command.arc_working_set or {}),
                    "narrative_search_id": command.narrative_search_id,
                    "narrative_search_branch_key": (
                        command.narrative_search_branch_key
                    ),
                    "narrative_search_parent_state_asset_version_id": (
                        command.narrative_search_parent_state_asset_version_id
                    ),
                    "narrative_search_accepted_through_chapter": (
                        command.narrative_search_accepted_through_chapter
                    ),
                    "narrative_search_strategy_directive": (
                        command.narrative_search_strategy_directive
                    ),
                    "narrative_search_planning_horizon": dict(
                        command.narrative_search_planning_horizon or {}
                    ),
                    "narrative_search_desired_transformation": dict(
                        command.narrative_search_desired_transformation or {}
                    ),
                    "narrative_search_hard_constraints": list(
                        command.narrative_search_hard_constraints
                    ),
                    "narrative_realization": dict(command.narrative_realization or {}),
                    **(
                        {"edition_execution": dict(command.edition_execution)}
                        if command.edition_execution
                        else {}
                    ),
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
                **(
                    {
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
                        }
                    }
                    if command.generator_operation_name not in FOUNDATION_GENERATORS
                    else {}
                ),
                "arc_working_set": dict(command.arc_working_set or {}),
                "narrative_search": command.narrative_search_snapshot,
                **({"working_continuity_projection_version": context_document.content["working_continuity_projection_version"]}
                    if context_document.content.get("working_continuity_projection_version") else {}),
                **({"planning_empty_query_projection_version": context_document.content["planning_empty_query_projection_version"]} if context_document.content.get("planning_empty_query_projection_version") else {}),
                **({"planning_recall_query_projection_version": context_document.content["planning_recall_query_projection_version"]} if context_document.content.get("planning_recall_query_projection_version") else {}),
                **({"planning_method_scope_projection_version": context_document.content["planning_method_scope_projection_version"]} if context_document.content.get("planning_method_scope_projection_version") else {}),
                "narrative_intelligence": context_document.content.get(
                    "narrative_intelligence", {}
                ),
                **(
                    {
                        "craft_history_projection_version": context_document.content[
                            "craft_history_projection_version"
                        ]
                    }
                    if context_document.content.get("craft_history_projection_version")
                    else {}
                ),
            },
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
            "operation_id": operation_id,
        }
        if provider_stage is not None:
            stable_request_payload["input"] = {
                "world_preparation": dict(provider_stage.task)
            }
        elif world_action is not None:
            from novel_forge.modules.canon_graph.background import (
                public_world_direction,
            )

            stable_request_payload["input"]["world_preparation"] = (
                public_world_direction(
                    {
                        "asset_version_id": world_action.asset_version_id,
                        "content_hash": world_action.content_hash,
                        "action": world_action.content["contract"],
                    }
                )
            )
        existing_intent = read_external_effect_intent(
            self.database_url, effect_context, effect_type="model.invoke", stable_idempotency_key=stable_key,
        )
        requested_output_token_ceiling = None
        if existing_intent is None and frozen.context_policy_ref == "context-policy:chapter-generation-pack:v2":
            target_scope = TargetScope(
                scope_kind=command.planning_scope.value.lower(),
                scope_id=command.logical_key,
                project_id=command.project_id,
                book_id=command.book_id,
            )
            complete_prompt, _ = _materialize_production_codex_prompt(
                target_scope=target_scope.to_dict(), stage=stage_name,
                inputs=stable_request_payload["input"], materialization=materialization,
            )
            output_modes = dict(dict(context_policy.get("provider_output_modes") or {}).get(stage_name) or {})
            transport_schema = json.dumps(output_schema, sort_keys=True, ensure_ascii=False) if output_modes.get("deepseek") else ""
            components = provider_request_token_components(
                complete_prompt, output_schema_json=transport_schema,
                output_reserve=1, safety_margin=planning_route.token_safety_margin,
                framing_overhead=planning_route.token_framing_overhead,
            )
            frozen_request_token_ceiling = sum(components.values()) - 1
            if frozen_request_token_ceiling > int(context_policy["max_tokens"]):
                raise KernelError("PLANNING_PROVIDER_TOKEN_CEILING_INVALID", "complete Planning input exceeds the system support cap")
            from novel_forge.modules.chapter_authority.context_compression_provider import task_provider_output_reserve

            requested_output_token_ceiling = task_provider_output_reserve(
                stage_name, planning_route, router_binding_pending=provider_router is not None,
            )
        if existing_intent is not None:
            provider_token_contract = dict(existing_intent["request_payload"].get("provider_token_contract") or {})
            if int(provider_token_contract.get("max_output_tokens") or 0) <= 0:
                raise KernelError("PLANNING_EFFECT_INTENT_INVALID", "frozen Planning intent has no valid output reservation contract")
        else:
            provider_token_contract = resolve_provider_token_reservation_contract(
                self.database_url,
                operation_id=operation_id,
                project_id=command.project_id,
                currency=(
                    "UNKNOWN"
                    if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "USD"
                ),
                frozen_request_token_ceiling=frozen_request_token_ceiling,
                requested_output_token_ceiling=requested_output_token_ceiling,
                accounting_basis=self.cost_accounting_basis,
                cost_authorization_ref=self.account_authorization_ref,
            )
        if existing_intent is None and requested_output_token_ceiling is not None and int(provider_token_contract.get("max_output_tokens") or 0) < requested_output_token_ceiling:
            raise KernelError("PROVIDER_TOKEN_RESERVATION_INSUFFICIENT", "authorized Planning output reservation is smaller than the task Provider output requirement")
        contract_amount = provider_token_contract["estimated_cost_amount"]
        provider_reservation_amount = (
            None
            if self.cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
            else str(contract_amount or self.max_cost_per_call)
        )
        provider_reservation_tokens = int(
            provider_token_contract["estimated_total_tokens"]
        )
        stable_request_payload["max_output_tokens"] = provider_token_contract["max_output_tokens"]
        stable_request_payload["provider_token_contract"] = provider_token_contract
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
            target_scope = TargetScope(
                scope_kind=command.planning_scope.value.lower(),
                scope_id=command.logical_key,
                project_id=command.project_id,
                book_id=command.book_id,
            )
            prompt, prompt_evidence = _materialize_production_codex_prompt(
                target_scope=target_scope.to_dict(),
                stage=stage_name,
                inputs=stable_request_payload["input"],
                materialization=materialization,
            )
            output_reserve = int(stable_request_payload["max_output_tokens"])
            pack_artifacts = dict(materialization.get("pack_artifacts") or {})
            context_artifact = dict(pack_artifacts.get("context_policy") or {})
            context_policy = dict(context_artifact.get("content") or {})
            output_modes = dict(
                dict(context_policy.get("provider_output_modes") or {}).get(stage_name)
                or {}
            )
            deepseek_mode = str(output_modes.get("deepseek") or "")
            provider_request_protocol("deepseek", output_mode=deepseek_mode)
            transport_schema_json = (
                json.dumps(output_schema, sort_keys=True, ensure_ascii=False)
                if deepseek_mode
                else ""
            )
            token_components = provider_request_token_components(
                prompt,
                output_schema_json=transport_schema_json,
                output_reserve=output_reserve,
                safety_margin=planning_route.token_safety_margin,
                framing_overhead=planning_route.token_framing_overhead,
            )
            if provider_router is not None:
                if frozen_world_sample is not None:
                    from .world_sampling import world_sample_routing_lineage
                    routing_lineage = world_sample_routing_lineage(self.database_url, project_id=command.project_id, operation_id=operation_id)
                else:
                    routing_lineage = _planning_repair_routing_lineage(
                        self.database_url,
                        project_id=command.project_id,
                        book_id=command.book_id,
                        generator_operation_name=command.generator_operation_name,
                        operation_id=operation_id,
                        repair_of_operation_id=command.repair_of_operation_id,
                        repair_of_candidate_id=command.repair_of_candidate_id,
                    )
                planning_route, routing_decision = provider_router.select(
                    planning_route,
                    task_type=stage_name,
                    project_id=command.project_id,
                    work_id=command.book_id,
                    operation_id=operation_id,
                    attempt_id=attempt_id,
                    stable_key=stable_key,
                    input_tokens=sum(token_components.values()) - output_reserve,
                    output_tokens=output_reserve,
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    cache_prefix=prompt.encode()[
                        : prompt_evidence["reusable_prefix_bytes"]
                    ],
                    producer_contract=producer_contract_identity(
                        prompt_evidence,
                        materialization,
                        schema_identity=(
                            planning_schema_evidence_identity(
                                output_schema, output_schema_ref
                            )
                            if provider_stage is None
                            else world_schema_evidence_identity(
                                output_schema, output_schema_ref
                            )
                        ),
                    ),
                    request_input=stable_request_payload["input"],
                    input_hash="sha256:" + hashlib.sha256(prompt.encode()).hexdigest(),
                    lineage_operation_ids=routing_lineage,
                )
            if frozen.context_policy_ref == "context-policy:chapter-generation-pack:v2":
                from novel_forge.modules.chapter_authority.context_compression_provider import require_task_reasoning, require_task_output_reserve

                require_task_reasoning(planning_route, task_scoped=True)
                require_task_output_reserve(
                    stage_name, planning_route, output_reserve, capacity_error_code="TASK_CONTEXT_MODEL_OUTPUT_CAPACITY_EXCEEDED",
                )
            route_identity = ":".join(
                (
                    command.generator_operation_name,
                    planning_route.model_profile.model_provider,
                    planning_route.model_profile.model_id,
                    planning_route.release_sha,
                    attempt_snapshot.snapshot_hash,
                )
            )
            envelope = ProviderRequestEnvelope(
                provider=planning_route.model_profile.model_provider,
                reasoning_effort=planning_route.model_profile.reasoning_effort
                if planning_route.model_profile.model_provider in {"deepseek", "openai"}
                else "",
                pricing_policy_json=json.dumps(
                    routing_decision["selected"]["candidate"]["pricing"], sort_keys=True
                )
                if routing_decision
                else "",
                model=planning_route.model_profile.model_id,
                protocol=provider_request_protocol(
                    planning_route.model_profile.model_provider,
                    output_mode=deepseek_mode
                    if planning_route.model_profile.model_provider == "deepseek"
                    else "",
                ),
                output_schema_json=transport_schema_json
                if planning_route.model_profile.model_provider == "deepseek"
                else "",
                input_text=prompt,
                max_output_tokens=output_reserve,
                timeout_seconds=_provider_process_timeout_seconds(
                    STORY_PLANNING_OPERATION_TIMEOUT_SECONDS,
                    max_attempts=PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS,
                ),
                stable_idempotency_key=stable_key,
            )
            token_contract = build_route_token_accounting_contract(
                serialization_contract=envelope.protocol,
                provider=planning_route.model_profile.model_provider,
                model=planning_route.model_profile.model_id,
                route_identity=route_identity,
                accounting_method=planning_route.token_accounting_method,
                accounting_evidence_ref=(planning_route.token_accounting_evidence_ref),
                model_context_limit=planning_route.model_context_limit,
                execution_token_limit=(
                    provider_reservation_tokens
                    if provider_token_contract["source"]
                    == "BOOK_OPENING_IMMUTABLE_PER_CALL_POLICY"
                    else planning_route.model_context_limit
                ),
                output_reserve=output_reserve,
                safety_margin=planning_route.token_safety_margin,
                framing_overhead=planning_route.token_framing_overhead,
            )
            context_bundle_tokens = int(
                context_document.content.get("estimated_tokens") or 0
            )
            admission = prepare_provider_admission(
                envelope,
                token_contract,
                context_bundle_tokens=context_bundle_tokens,
                input_component_hashes=dict(
                    dict(prompt_evidence.get("provider_view") or {}).get(
                        "component_hashes"
                    )
                    or {}
                ),
                complete_request_coverage=(
                    "system_runtime_instructions",
                    "prompt_template",
                    "skill_instructions",
                    "tool_policy_and_schemas",
                    "structured_output_schema",
                    "context_bundle",
                    "knowledge_inputs",
                    "request_envelope_and_framing",
                    "output_reserve",
                    "safety_margin",
                ),
            )
            if admission.status != "ADMITTED":
                raise KernelError(
                    "PROVIDER_TOKEN_ADMISSION_REJECTED",
                    (
                        f"{admission.reason}: reserved={admission.total_reserved} "
                        f"limit={admission.applicable_limit}"
                    ),
                )
            if planning_route.model_profile.model_provider != "scripted_provider_v2":
                provider_reservation_tokens = admission.total_reserved
            admission_contract = {
                "schema_version": "novelos.provider_request_admission.v1",
                "provider_request_identity": envelope.to_identity_dict(),
                "provider_admission": admission.to_dict(),
                "effective_context_policy": effective_context_policy,
                "prompt_materialization": prompt_evidence,
                "capability_materialization_asset_version_id": (
                    materialization_document.asset_version_id
                ),
                "capability_materialization_content_hash": (
                    materialization_document.content_hash
                ),
            }
            admission_document = self._ensure_contract(
                operation_id=operation_id,
                project_id=command.project_id,
                logical_ref=(
                    "production_execution/provider_admissions/"
                    + _token(
                        f"{command.project_id}:{operation_id}:{attempt_id}:{stage_identity}"
                    )
                ),
                asset_type="provider_request_admission_manifest",
                contract=admission_contract,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
            )
            request_payload = {
                **stable_request_payload,
                "_production_execution": {
                    **({"book_id": command.book_id, "project_id": command.project_id,
                        "operation_id": operation_id, "attempt_id": attempt_id} if routing_decision else {}),
                    "capability_runtime": {
                        **({"routing_decision": routing_decision} if routing_decision else {}),
                        "snapshot_id": attempt_snapshot.snapshot_id,
                        "snapshot_hash": attempt_snapshot.snapshot_hash,
                        "materialization_asset_version_id": (
                            materialization_document.asset_version_id
                        ),
                        "materialization_content_hash": (
                            materialization_document.content_hash
                        ),
                        "materialization_hash": materialization["materialization_hash"],
                        "provider_admission_asset_version_id": (
                            admission_document.asset_version_id
                        ),
                        "provider_admission_content_hash": (
                            admission_document.content_hash
                        ),
                        "provider_request_envelope_hash": envelope.envelope_hash,
                        "provider_admission": admission.to_dict(),
                        "token_accounting_contract": token_contract.to_dict(),
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
            frozen_admission = capability_runtime.get("provider_admission")
            if (
                planning_route.model_profile.model_provider != "scripted_provider_v2"
                and isinstance(frozen_admission, Mapping)
            ):
                provider_reservation_tokens = int(
                    frozen_admission.get("total_reserved") or 0
                )
                if provider_reservation_tokens <= 0:
                    raise KernelError(
                        "PLANNING_PROVIDER_ADMISSION_INVALID",
                        "frozen Planning admission has no bounded request usage",
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
        cost_accounting_basis = str(provider_token_contract["accounting_basis"])
        account_authorization_ref = str(provider_token_contract["cost_authorization_ref"])
        if provider_router is not None:
            from novel_forge.modules.production_execution.routing_runtime import routed_reservation, validate_routed_reservation

            routing_decision = request_payload["_production_execution"]["capability_runtime"]["routing_decision"]
            planning_route, routing_decision = provider_router.select_for_payload(self.planning_route, request_payload)
            if frozen.context_policy_ref == "context-policy:chapter-generation-pack:v2":
                from novel_forge.modules.chapter_authority.context_compression_provider import require_task_reasoning

                require_task_reasoning(planning_route, task_scoped=True)
            selected = routing_decision["selected"]["candidate"]
            cost_accounting_basis = selected["pricing"]["accounting_basis"]
            account_authorization_ref = selected.get("authorization_ref", "")
            provider_reservation_amount = routed_reservation(routing_decision,
                input_tokens=max(0, provider_reservation_tokens - int(stable_request_payload["max_output_tokens"])),
                output_tokens=int(stable_request_payload["max_output_tokens"]))
            if existing_intent is None or existing_intent["status"] == "READY":
                validate_routed_reservation(
                    routing_decision, reserved_tokens=provider_reservation_tokens,
                    reserved_amount=provider_reservation_amount,
                )
            if (existing_intent is None or existing_intent["status"] != "SUCCEEDED") and provider_reservation_amount is not None and Decimal(provider_reservation_amount) > Decimal(self.max_cost_per_call):
                raise KernelError("BUDGET_HARD_LIMIT", "routed Planning call exceeds the per-call cap")
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
            model_id=str((existing_intent or {}).get("model_id") or planning_route.model_profile.model_id),
            request_timeout_seconds=int((existing_intent or {}).get("request_timeout_seconds") or STORY_PLANNING_OPERATION_TIMEOUT_SECONDS),
            reconciliation_mode=str((existing_intent or {}).get("reconciliation_mode") or self.execution_transport.reconciliation_mode),
            provider_capability_profile=(
                dict(existing_intent["provider_capability_profile"])
                if existing_intent is not None
                else self.execution_transport.capability_profile.to_dict()
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
            try:
                reservation = reserve_provider_budget(
                    self.database_url,
                    BudgetReservationRequest(
                        operation_id=operation_id,
                        external_effect_id=effect_id,
                        project_id=command.project_id,
                        stable_idempotency_key=(
                            f"budget:{stable_key}:attempt:{attempt_id}"
                        ),
                        provider=planning_route.model_profile.model_provider if routing_decision else self.execution_transport.provider,
                        model_id=planning_route.model_profile.model_id if routing_decision else "",
                        work_id=command.book_id if routing_decision else "",
                        currency=(
                            "UNKNOWN"
                            if cost_accounting_basis == "ACCOUNT_ENTITLEMENT"
                            else "USD"
                        ),
                        estimated_amount=provider_reservation_amount,
                        estimated_tokens=provider_reservation_tokens,
                        caps={} if cost_accounting_basis == "ACCOUNT_ENTITLEMENT" else self.budget_caps,
                        call_caps=self.provider_call_caps,
                        token_caps=self.provider_token_caps,
                        budget_scope_id=str(provider_token_contract["budget_scope_id"]),
                        expected_budget_scope_revision=(
                            int(provider_token_contract["budget_scope_revision"])
                            if provider_token_contract["budget_scope_revision"] is not None
                            else None
                        ),
                        accounting_basis=cost_accounting_basis,
                        cost_authorization_ref=account_authorization_ref,
                    ),
                )
            except KernelError as error:
                if error.code != "RESOURCE_ROUTE_RESELECT_REQUIRED":
                    raise
                return self._prepare_stage(operation_id=operation_id, attempt_id=attempt_id,
                    fencing_token=fencing_token, worker_id=worker_id, command=command, inputs=inputs,
                    definition=definition, attempt_snapshot=attempt_snapshot, provider_stage=provider_stage,
                    world_action=world_action, frozen_world_sample=frozen_world_sample)
            if not bool(reservation.get("execution_authorized")):
                raise KernelError(
                    "BUDGET_RESERVATION_EXECUTION_NOT_AUTHORIZED",
                    "Planning reservation replay cannot authorize dispatch: "
                    + str(reservation.get("replay_disposition") or "UNKNOWN"),
                )
            reservation_id = str(reservation["reservation_id"])
        else:
            reservation_id = str(recovered_completion["budget_reservation_id"])
            planning_route = self._recovered_planning_route(
                recovered_completion=recovered_completion,
                project_id=command.project_id,
                current_route=planning_route,
            )
            # INVARIANT: A durable Provider result must be settled against the original
            # Budget Authority contract.  Runtime configuration may have
            # changed since the first send, but it cannot rewrite the frozen
            # reservation ceiling on replay.
            recovered_amount = recovered_completion["budget_reserved_amount"]
            provider_reservation_amount = (
                str(recovered_amount) if recovered_amount is not None else None
            )
            provider_reservation_tokens = int(
                recovered_completion["budget_estimated_tokens"]
            )
        binding, contract_documents = self._execution_binding(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            command=command,
            definition=definition,
            capability=capability,
            planning_route=planning_route,
            routing_decision=routing_decision,
            context_document=context_document,
            input_documents=input_documents,
            effect_id=effect_id,
            stable_key=stable_key,
            reservation_id=reservation_id,
            output_schema_ref=output_schema_ref,
            frozen=frozen,
            stage_name=stage_name,
            stage_identity=stage_identity,
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
                reserved_amount=provider_reservation_amount,
                reserved_tokens=provider_reservation_tokens,
                binding=binding,
                adapter=adapter,
                recovered_completion=recovered_completion,
                realization_selector_catalog=context_document.content.get("realization_reference_contract") if command.execution_contract_version == "1.21.0" and provider_stage is None else None,
                writer=self.writer,
                post_provider_fault_injector=self.post_provider_fault_injector,
            ),
            context_bundle_asset_version_id=context_document.asset_version_id,
            context_bundle_hash=context_document.content_hash,
            narrative_intelligence_selection_digest=str(
                context_document.content["narrative_intelligence"]["selection_digest"]
            ),
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

    def _recovered_planning_route(
        self, *, recovered_completion: Mapping[str, Any], project_id: str,
        current_route: PlanningExecutionRoute,
    ) -> PlanningExecutionRoute:
        evidence = dict(recovered_completion.get("provider_evidence") or {})
        frozen = dict(evidence.get("production_execution") or {}).get("route_snapshot")
        if not isinstance(frozen, Mapping):
            raise KernelError("PLANNING_RECOVERY_ROUTE_MISSING", "successful Planning receipt must retain its original route")
        route = RouteSnapshot.from_dict(dict(frozen))
        profile_document = self.query.require(
            project_id=project_id,
            logical_ref=f"production_execution/model_profiles/{route.model_profile_id}/v{route.model_profile_version}",
        )
        policy_document = self.query.require(
            project_id=project_id,
            logical_ref=f"production_execution/route_policies/{route.policy_id}/v{route.policy_version}",
        )
        fallback_document = self.query.require(
            project_id=project_id,
            logical_ref=f"production_execution/fallback_policies/{route.fallback_policy_ref}/v{route.fallback_policy_version}",
        )
        profile = ModelProfile.from_dict(profile_document.content["contract"])
        policy = RoutePolicy.from_dict(policy_document.content["contract"])
        fallback = FallbackPolicy.from_dict(fallback_document.content["contract"])
        if (profile_document.asset_type != "model_profile" or policy_document.asset_type != "route_policy"
                or fallback_document.asset_type != "fallback_policy" or profile.contract_hash != route.model_profile_hash
                or policy.contract_hash != route.route_policy_hash or profile.model_id != evidence.get("model_id")
                or profile.model_provider != evidence.get("provider_id") or profile.reasoning_effort != route.reasoning_effort):
            raise KernelError("PLANNING_RECOVERY_ROUTE_DRIFT", "successful Planning route differs from its exact governed contracts")
        return replace(current_route, model_profile=profile, route_policy=policy, fallback_policy=fallback,
                       backend_version=route.backend_version, runtime_host_id=route.runtime_host_id,
                       auth_profile_ref=route.auth_profile_ref, release_sha=route.release_sha)

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
        stage_name: str,
        stage_identity: str,
        routing_decision: Mapping[str, Any] | None = None,
    ) -> tuple[_PlanningExecutionBinding, dict[str, AuthorityAssetDocument]]:
        graph = self._operation_graph(operation_id, command.project_id)
        suffix = (
            FOUNDATION_GENERATORS[command.generator_operation_name].value.lower()
            if command.generator_operation_name in FOUNDATION_GENERATORS
            else command.planning_scope.value.lower()
            if stage_identity == "planning"
            else stage_identity.replace(".", "_")
        )
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
        profile = self._select_model_profile(command.project_id, profile)
        identity_suffix = profile.profile_id.removeprefix(profile_id)
        profile_id = profile.profile_id
        policy = RoutePolicy(
            policy_id=f"planning.{suffix}.route{identity_suffix}",
            policy_version=1,
            default_model_profile_id=profile_id,
            allowed_model_profile_ids=(profile_id,),
            rule_set_ref=f"route-rules:planning:{suffix}:v1",
            fallback_policy="FAIL_CLOSED",
            fallback_policy_ref=f"planning.{suffix}.fail-closed{identity_suffix}",
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
        execution_identity = (
            f"{command.project_id}:{operation_id}:{attempt_id}:{stage_identity}"
        )
        if fencing_token > 1:
            execution_identity += f":fence:{fencing_token}"
        route_ref = "production_execution/routes/" + _token(execution_identity)
        input_ref = "production_execution/inputs/" + _token(execution_identity)
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
            route_decision_id=routing_decision["decision_id"] if routing_decision else f"route-decision:{_token(route_ref)}",
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
            # INVARIANT: The ExternalEffect owns the stable Provider idempotency identity;
            # each Operation Attempt owns one gateway execution record.  Reusing
            # the execution_id would conflict with the new Attempt fence and
            # budget reservation even though the Effect itself is unchanged.
            execution_id=(
                f"planning-execution:{effect_id}:{attempt_id}"
                + (f":fence:{fencing_token}" if fencing_token > 1 else "")
            ),
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
            stage=stage_name,
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
        context_policy_ref: str = "",
        planning_task_token_budget: int | None = None,
        preflight_only: bool = False,
    ) -> tuple[Any, tuple[AuthorityAssetDocument, ...]]:
        from .character_references import require_planning_character_references
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
            if item.role == "creative_brief" and document.content.get("creative_input_selection"):
                from novel_forge.modules.creative.input_selection import require_input_scope
                require_input_scope(document.content, project_id=command.project_id,
                    workspace_id=command.workspace_id, book_id=command.book_id)
            if document.content.get("book_id") and document.content["book_id"] != command.book_id:
                raise KernelError("PLANNING_CONTEXT_INPUT_BOOK_INVALID",
                    "Frozen Planning context belongs to another Book")
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
        repair_context: dict[str, Any] | None = None
        result_repair_source = None
        if command.repair_of_operation_id:
            from .result_recovery import require_result_repair_source

            source = require_result_repair_source(
                self.database_url,
                command=command,
                operation_id=command.repair_of_operation_id,
                source_asset_version_id=command.repair_result_asset_version_id,
            )
            if source["diagnostic"] != dict(command.repair_result_diagnostic or {}):
                raise KernelError(
                    "PLANNING_RESULT_REPAIR_DIAGNOSTIC_DRIFT",
                    "result repair context must use its frozen failure diagnosis",
                )
            result_repair_source = source
            if (
                source["diagnostic"].get("provider_stage")
                != "world_candidates.generate"
            ):
                documents.append(
                    self.query.require(
                        project_id=command.project_id,
                        asset_version_id=source["asset_version_id"],
                    )
                )
                repair_context = {
                    "contract_version": "planning-result-repair-context.v1",
                    "source_result": {
                        "asset_version_id": source["asset_version_id"],
                        "content_hash": source["content_hash"],
                        "content": source["raw_result"],
                        "operation_id": command.repair_of_operation_id,
                    },
                    "validation_failure": source["diagnostic"],
                    "instruction": "Repair this invalid raw Provider result against the frozen task and complete current Schema. It was never a Candidate or Canon. Preserve correct content, return the entire valid result; do not invent scope or omit fields.",
                }
        if command.repair_of_candidate_id:
            repair_document = self.query.require(
                project_id=command.project_id,
                asset_version_id=command.repair_of_candidate_id,
            )
            if repair_document.asset_type != "planning_generation_candidate":
                raise KernelError(
                    "PLANNING_REPAIR_SOURCE_INVALID",
                    "Planning repair source must be an immutable generated candidate",
                )
            documents.append(repair_document)
            repair_context = self._repair_context(
                command=command,
                source=repair_document,
            )
        for ordinal, asset_version_id in enumerate(
            command.change_evidence_version_ids, start=1
        ):
            document = self.query.require(
                project_id=command.project_id,
                asset_version_id=asset_version_id,
            )
            if (
                document.asset_type not in ({"longform_recap", "replan_request", "longform_prose_review_report", "arc_revision_candidate"} if command.execution_contract_version == "1.21.0" else {"longform_recap", "replan_request", "longform_prose_review_report"})
                or document.governance != "CLEAR"
                or document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            ):
                raise KernelError(
                    "PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID",
                    "Planning change evidence drifted after admission",
                )
            if document.asset_type == "arc_revision_candidate":
                from .recap_sources import require_arc_recap_change_evidence
                require_arc_recap_change_evidence(self.database_url, command, asset_version_id, dict(document.content))
            if document.asset_type == "longform_prose_review_report":
                from novel_forge.modules.book_followup_authority.prose_change_evidence import require_prose_planning_evidence
                require_prose_planning_evidence(self.database_url, command=command, asset_version_id=asset_version_id, commit_sha=self.planning_route.release_sha)
            if command.execution_contract_version == "1.21.0":
                retained = [item for item in selected if item["role"] == f"change_evidence:{ordinal}"]
                if retained:
                    if len(retained) != 1 or (retained[0]["asset_version_id"], retained[0]["content_hash"]) != (document.asset_version_id, document.content_hash):
                        raise KernelError("PLANNING_CONTEXT_CHANGE_EVIDENCE_INVALID", "Frozen change evidence role differs from exact command reference")
                    continue
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
        knowledge_access_policy = _planning_knowledge_access(
            production_profile=production_profile,
            selected=selected,
            project_id=command.project_id,
            book_id=command.book_id,
        )
        # INVARIANT: A technical retry may create a new Operation Attempt, but it must not
        # become a semantic replanning event. Freeze selection at the Planning
        # Operation identity so every retry reuses the exact same Authority
        # inputs and Narrative Intelligence card versions.
        logical_ref = f"planning/context_bundles/{operation_id}.json"
        try:
            frozen_context = self.query.require(
                project_id=command.project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            if command.runtime_continuation_id and command.execution_contract_version == "1.21.0" and not preflight_only:
                from .runtime_continuation import require_binding
                runtime = require_binding(self.database_url, command.runtime_continuation_id)["target_runtime"]
                proof = runtime.get("planning_capacity", {}).get("context_revalidation")
                if proof and (runtime.get("planning_reference_contract") or proof.get("contract_version") in {"typed-volume-context-projection.v1", "foundation-method-recall-projection.v1", "book-method-scope-projection.v1"}):
                    original = self.query.require(project_id=command.project_id, asset_version_id=proof["context_asset_version_id"])
                    if original.content_hash != proof["context_content_hash"]:
                        raise KernelError("PLANNING_CONTEXT_REVALIDATION_SOURCE_DRIFT", "Original Context must retain exact frozen content")
                    if proof.get("contract_version") == "typed-volume-context-projection.v1":
                        original_order = {item["role"]:index for index,item in enumerate(original.content["input_versions"])}
                        if len(original_order) != len(original.content["input_versions"]) or any(item["role"] not in original_order for item in selected):
                            raise KernelError("PLANNING_CONTEXT_REVALIDATION_SOURCE_DRIFT", "Context successor role identities changed")
                        selected = sorted(selected,key=lambda item:original_order[item["role"]])
                    self._validate_frozen_context_retry(context=original, command=command, selected_inputs=selected, context_policy_ref=context_policy_ref)
                    self._append_narrative_intelligence_documents(command=command, selection=original.content["narrative_intelligence"], documents=documents, knowledge_access_policy=knowledge_access_policy)
                    content = self._reproject_frozen_context(original.content, command=command, task_tokens=runtime["planning_capacity"]["allocated_task_tokens"], operation_id=operation_id)
                    return self._materialize_planning_context(operation_id=operation_id, command=command, logical_ref=logical_ref, documents=documents, content=content), tuple(documents)
        else:
            self._validate_frozen_context_retry(
                context=frozen_context,
                command=command,
                selected_inputs=selected,
                context_policy_ref=context_policy_ref,
            )
            selection = frozen_context.content.get("narrative_intelligence")
            if not isinstance(selection, Mapping):
                raise KernelError(
                    "PLANNING_CONTEXT_BUNDLE_INVALID",
                    "Frozen Planning Context lacks Narrative Intelligence selection",
                )
            if (
                frozen_context.content.get("knowledge_access_policy")
                != knowledge_access_policy
                or selection.get("knowledge_access_policy")
                != knowledge_access_policy
            ):
                raise KernelError(
                    "PLANNING_KNOWLEDGE_ACCESS_POLICY_DRIFT",
                    "frozen Planning Knowledge access differs from Book Authority",
                )
            self._append_narrative_intelligence_documents(
                command=command,
                selection=selection,
                documents=documents,
                knowledge_access_policy=knowledge_access_policy,
            )
            return frozen_context, tuple(documents)
        recent_craft_usage = []
        if hasattr(self.mkaos, "list_accepted_craft_usage"):
            history_options = {"include_continuing": True} if (production_profile.get("craft_budget_policy") or {}).get("schema_version") in {"narrative-craft-budget.v3", "narrative-craft-budget.v4"} else {}
            recent_craft_usage = self.mkaos.list_accepted_craft_usage(
                project_id=command.project_id, book_id=command.book_id, limit=100,
                **history_options,
                **({"book_run_id": str(command.world_preparation_request["book_run_id"])} if command.world_preparation_request else {}),
            )
        working_history = (command.arc_working_set or {}).get("working_manuscript")
        if working_history and production_profile.get("working_craft_history_policy"):
            from novel_forge.modules.book_authority.manuscript_memory import selected_working_craft_history
            recent_craft_usage.extend(selected_working_craft_history(self.database_url, snapshot=working_history,
                mkaos=self.mkaos, policy=production_profile["working_craft_history_policy"]))
        need = _planning_narrative_intelligence_need(
            command=command,
            selected_inputs=selected,
            production_profile=production_profile,
            recent_craft_usage=tuple(recent_craft_usage),
            recent_repetition_keys=_recent_activated_repetition_keys(
                self.mkaos.list_planning_usage(
                    project_id=command.project_id,
                    book_id=command.book_id,
                    limit=100,
                )
            ),
        )
        if need.craft_policy.get("schema_version") == "narrative-craft-budget.v4":
            from novel_forge.modules.mkaos_authority.craft_scope import approved_arc_scope_transitions
            scope_context = dict(need.craft_context["usage_scope_context"])
            scope_context["scope_transitions"] = approved_arc_scope_transitions(self.database_url,
                project_id=command.project_id, book_id=command.book_id,
                arc_plan_version_ids=scope_context["arc_plan_version_ids"])
            need = replace(need, craft_context={**need.craft_context, "usage_scope_context": scope_context})
        if result_repair_source and result_repair_source["diagnostic"].get("provider_stage") != "world_candidates.generate" and need.craft_policy.get("schema_version") == "narrative-craft-budget.v4":
            from novel_forge.modules.mkaos_authority.craft_reselection import next_reselection_context
            context_version = result_repair_source["execution_evidence"].get("context_bundle_asset_version_id")
            original = self.query.require(project_id=command.project_id,
                **({"asset_version_id": context_version} if context_version else {"logical_ref": f"planning/context_bundles/{result_repair_source['source_operation_id']}.json"}))
            previous_selection = original.content["narrative_intelligence"]
            from novel_forge.modules.mkaos_authority.craft_matching import inherit_reselection_contract
            need = inherit_reselection_contract(need, previous_selection)
            from novel_forge.modules.mkaos_authority.craft_selection import validate_craft_policy
            if previous_selection.get("craft_policy") and previous_selection["craft_policy"] != validate_craft_policy(need.craft_policy):
                raise KernelError("CRAFT_RESELECTION_POLICY_DRIFT", "Concrete repair cannot reinterpret its predecessor policy")
            task_identity = canonical_hash({"project_id": command.project_id, "book_id": command.book_id,
                "logical_key": command.logical_key, "generator_operation_name": command.generator_operation_name,
                "input_versions": dict(command.input_versions)})
            reselection = next_reselection_context(selection=previous_selection, source=result_repair_source, task_identity=task_identity)
            if reselection:
                need = replace(need, craft_context={**need.craft_context, "reselection": reselection})
                repair_context["instruction"] = "Create a new concrete translation for the newly selected exact Cards. Preserve scene identities and prior correct planning content. Respect every scoped rejection; do not invent replacements. Recompute roles, order, dependency placements, combined effect, interference and abstention reasons. Earlier requests and results remain immutable."
        if (
            result_repair_source
            and result_repair_source["diagnostic"].get("provider_stage")
            == "world_candidates.generate"
        ):
            from .world_preparation import PlanningWorldPreparation

            generation = self.query.require(
                project_id=command.project_id,
                asset_version_id=result_repair_source["asset_version_id"],
            ).content["contract"]
            source_operation = PlanningWorldPreparation._source_operation(
                self.database_url,
                command.project_id,
                generation["source"]["asset_version_id"],
            )
            frozen_context = self.query.require(
                project_id=command.project_id,
                logical_ref=f"planning/context_bundles/{source_operation}.json",
            )
            narrative_intelligence = frozen_context.content["narrative_intelligence"]
            if generation.get(
                "knowledge_selection_digest", ""
            ) != narrative_intelligence.get("selection_digest", ""):
                raise KernelError(
                    "WORLD_REPAIR_KNOWLEDGE_DRIFT",
                    "World repair must retain its original exact knowledge selection",
                )
        else:
            narrative_intelligence = self.mkaos.resolve_narrative_intelligence(
            project_id=command.project_id,
            book_id=command.book_id,
            need=need,
            limit=_narrative_intelligence_limit(command.generator_operation_name),
            knowledge_access_policy=knowledge_access_policy,
            )
        self._append_narrative_intelligence_documents(
            command=command,
            selection=narrative_intelligence,
            documents=documents,
            selected_inputs=selected,
            knowledge_access_policy=knowledge_access_policy,
        )
        if context_policy_ref == "context-policy:chapter-generation-pack:v2" and (
            isinstance(planning_task_token_budget, bool)
            or not isinstance(planning_task_token_budget, int)
            or not 0 < planning_task_token_budget <= 512_000
        ):
            raise KernelError("PLANNING_TASK_TOKEN_BUDGET_INVALID", "new Planning policy requires an explicit bounded task token target")
        if command.runtime_continuation_id and not preflight_only:
            from .runtime_continuation import require_binding

            runtime = require_binding(
                self.database_url, command.runtime_continuation_id
            )["target_runtime"]
            planning_task_token_budget = runtime.get("planning_capacity", {}).get(
                "allocated_task_tokens", planning_task_token_budget
            )
        content = {
            "schema_version": "novelos.planning_context_bundle.v1",
            **({"generated_title_contract": "generated-book-title.v1"}
                if command.generator_operation_name == "creative.candidates.generate"
                and production_profile.get("title_generation_contract") == "generated-book-title.v1" else {}),
            **({"planning_contract_version": "1.21.0"} if command.execution_contract_version == "1.21.0" else {}),
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "planning_scope": command.planning_scope.value,
            "logical_key": command.logical_key,
            "input_versions": selected,
            **({"typed_window_projection_version": "typed-planning-window-projection.v1"}
                if command.generator_operation_name == "chapter_group_plan.generate" and command.narrative_search_id else {}),
            **({"typed_volume_projection_version": "typed-volume-context-projection.v1"}
                if command.generator_operation_name == "arc_plan.generate" else {}),
            "planning_empty_query_projection_version": "planning-empty-query-projection.v1",
            **({"planning_exact_reference_projection_version": "planning-exact-value-reference.v1"}
                if command.generator_operation_name in {"book_plan.generate", "volume_plan.generate", "arc_plan.generate", "chapter_group_plan.generate", "chapter_plan.generate"} else {}),
            "arc_working_set": dict(command.arc_working_set or {}),
            "narrative_search": command.narrative_search_snapshot,
            **({"planning_semantic_fields_version": "planning-semantic-fields.v2"}
                if command.execution_contract_version == "1.21.0"
                and command.generator_operation_name not in FOUNDATION_GENERATORS else {}),
            **({"working_continuity_projection_version": "planning-working-continuity.v3" if ((command.arc_working_set or {}).get("working_manuscript") or {}).get("projection_policy") else "planning-working-continuity.v2"}
                if command.execution_contract_version == "1.21.0"
                and (command.arc_working_set or {}).get("working_manuscript") is not None else {}),
            **(
                {"edition_execution": dict(command.edition_execution)}
                if command.edition_execution
                else {}
            ),
            "narrative_intelligence": narrative_intelligence,
            **(
                {
                    "planning_input_projection_version": "planning-input-role-references.v1"
                }
                if command.generator_operation_name not in FOUNDATION_GENERATORS
                else {}
            ),
            **(
                {
                    "craft_history_projection_version": "planning-craft-history-projection.v1"
                }
                if command.generator_operation_name not in FOUNDATION_GENERATORS
                and narrative_intelligence.get("craft_policy", {}).get("schema_version")
                == "narrative-craft-budget.v4"
                else {}
            ),
            "knowledge_access_policy": knowledge_access_policy,
            **(
                {
                    "foundation_task": foundation_task(
                        command.generator_operation_name,
                        generated_title=command.generator_operation_name == "creative.candidates.generate"
                            and production_profile.get("title_generation_contract") == "generated-book-title.v1",
                        work_requirements=command.execution_contract_version
                        in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
                        aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
                        rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
                        narrative_search=command.execution_contract_version == "1.21.0" and bool(command.narrative_search_id),
                    )
                }
                if command.generator_operation_name in FOUNDATION_GENERATORS
                else {
                    "realization_reference_contract": _realization_reference_contract(
                        project_id=command.project_id,
                        book_id=command.book_id,
                        frozen_by_operation_id=operation_id,
                        inputs=inputs,
                        selectors_only=command.execution_contract_version == "1.21.0",
                        character_references=(
                            require_planning_character_references(self.database_url, command)
                            if command.execution_contract_version == "1.21.0" else None
                        ),
                    )
                }
            ),
            **({"repair_context": repair_context} if repair_context else {}),
            "token_budget": planning_task_token_budget
            if context_policy_ref == "context-policy:chapter-generation-pack:v2"
            else 16000,
            **(
                {"planning_context_policy_version": context_policy_ref}
                if context_policy_ref == "context-policy:chapter-generation-pack:v2"
                else {}
            ),
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
                    **({"criterion_semantics": profile.criterion_semantics} if profile.criterion_semantics else {}),
                }
                for profile in required_qualification_profiles(
                    command.generator_operation_name,
                    work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
                    profile_version="3.0.0" if command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"} else "2.0.0",
                )
            ],
            "trace_id": command.trace_id,
            **(
                {"language_contract": dict(language_contract)}
                if isinstance(language_contract, Mapping)
                else {}
            ),
        }
        from novel_forge.modules.story_design_authority.author_input import author_binding_from_inputs, compile_planning_author_projection

        author_design = author_binding_from_inputs(selected, project_id=command.project_id, book_id=command.book_id)
        if author_design:
            content["author_design_projection"] = compile_planning_author_projection(
                author_design, command=command, selected_inputs=selected,
            )
        content["context_manifest"] = self._planning_context_manifest(
            command=command,
            selected_inputs=selected,
            content=content,
        )
        content["estimated_tokens"] = int(
            content["context_manifest"]["token_accounting"]["accepted_tokens"]
        )
        if preflight_only:
            return content, tuple(documents)
        context = self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=command.project_id,
                asset_id=f"planning-context:{operation_id}",
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
                reference_asset_ids=tuple(document.asset_id for document in documents),
            )
        )
        return context, tuple(documents)



    def _reproject_frozen_context(self, source, *, command, task_tokens, operation_id=None):
        from copy import deepcopy

        content = deepcopy(dict(source))
        content["token_budget"] = task_tokens
        if (command.generator_operation_name == "book_plan.generate" and content.get("narrative_intelligence", {}).get("selected")
                and content.get("knowledge_access_policy", {}).get("mode") == "ALLOW_ONLY"
                and content.get("knowledge_access_policy", {}).get("usage_scope") == "EXPERIMENTAL_VALIDATION"
                and content.get("knowledge_access_policy", {}).get("craft_candidate_review_version") == "explicit-allowlist-craft-review.v1"):
            from novel_forge.modules.mkaos_authority.craft_context_projection import project_book_method_scope
            project_book_method_scope(content["narrative_intelligence"])
            content["planning_method_scope_projection_version"] = "book-method-scope-projection.v1"
        if (command.generator_operation_name == "character.cast.generate"
                and content.get("knowledge_access_policy", {}).get("craft_candidate_review_version")
                == "explicit-allowlist-craft-review.v1"
                and content.get("narrative_intelligence", {}).get("selected")):
            content["planning_recall_query_projection_version"] = "foundation-method-recall-projection.v1"
        if command.generator_operation_name == "arc_plan.generate":
            content["typed_volume_projection_version"] = "typed-volume-context-projection.v1"
        if command.generator_operation_name == "chapter_group_plan.generate" and command.narrative_search_id:
            content["typed_window_projection_version"] = "typed-planning-window-projection.v1"
        if command.execution_contract_version == "1.21.0":
            content["planning_contract_version"] = "1.21.0"
        if operation_id and "realization_reference_contract" in content:
            for rows in content["realization_reference_contract"][
                "references_by_domain"
            ].values():
                for ref in rows:
                    ref["frozen_by_operation_id"] = operation_id
        if (
            command.execution_contract_version == "1.21.0"
            and "realization_reference_contract" in content
        ):
            content["realization_reference_contract"]["instruction"] = (
                "Select only asset_version_id from the matching domain list. The host binds scope, type, hash and Operation identity."
            )
        content.pop("context_manifest", None)
        content["context_manifest"] = self._planning_context_manifest(
            command=command, selected_inputs=content["input_versions"], content=content
        )
        content["estimated_tokens"] = int(
            content["context_manifest"]["token_accounting"]["accepted_tokens"]
        )
        return content


    def _materialize_planning_context(
        self, *, operation_id, command, logical_ref, documents, content
    ):
        return self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=command.project_id,
                asset_id=f"planning-context:{operation_id}",
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
                reference_asset_ids=tuple(document.asset_id for document in documents),
            )
        )


    def _world_context_bundle(self, *, operation_id, command, base, stage, calibration_sample=False):
        source = self.query.require(
            project_id=command.project_id,
            asset_version_id=stage.task["source_ref"]["asset_version_id"],
        )
        if source.content_hash != stage.task["source_ref"]["content_hash"]:
            raise KernelError(
                "WORLD_CONTEXT_SOURCE_DRIFT",
                "world role projection must retain its exact source version",
            )
        content = self._world_context_content(command=command, base=base, stage=stage, source=source)
        prefix = "world_sampling" if calibration_sample else "world_preparation"
        logical_ref = f"{prefix}/context/{operation_id}/{stage.name}"
        try:
            frozen = self.query.require(
                project_id=command.project_id, logical_ref=logical_ref
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
        else:
            if frozen.content != content or frozen.eligibility != ("INELIGIBLE" if calibration_sample else "ELIGIBLE"):
                raise KernelError(
                    "WORLD_CONTEXT_FROZEN_CONFLICT",
                    "retry cannot replace the confirmed world stage Context",
                )
            return frozen, source
        document = self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=command.project_id,
                asset_id=f"world-context:{operation_id}:{stage.name}",
                asset_type="context_bundle",
                schema_version="novelos.planning_context_bundle.v1",
                logical_ref=logical_ref,
                category="planning_context",
                output_key=f"planning.context_bundle.{stage.name}",
                role="context_bundle",
                content=content,
                qualification_policy="world-reference-sample-context-v1" if calibration_sample else "world-role-context-v1",
                eligibility="INELIGIBLE" if calibration_sample else "ELIGIBLE",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                reference_asset_ids=(source.asset_id,),
            )
        )
        return document, source

    @classmethod
    def _world_context_content(cls, *, command, base, stage, source):
        if stage.task["source_ref"] != {"asset_version_id": source.asset_version_id, "content_hash": source.content_hash}:
            raise KernelError("WORLD_CONTEXT_SOURCE_DRIFT", "World Context must retain its exact source version")
        content = {**base.content, "world_preparation": dict(stage.task)}
        content["token_budget"] = stage.task["policy"]["context_token_budget"]
        selected = [{"role": stage.task["role"], "asset_version_id": source.asset_version_id,
                     "asset_type": source.asset_type, "content_hash": source.content_hash, "content": source.content}]
        content["input_versions"] = selected
        content["context_manifest"] = cls._planning_context_manifest(command=command, selected_inputs=selected,
            content=content, provider_stage=stage)
        content["estimated_tokens"] = content["context_manifest"]["token_accounting"]["accepted_tokens"]
        return content

    @staticmethod
    def _planning_context_manifest(
        *,
        command: StoryPlanningGenerationCommand,
        selected_inputs: list[dict[str, Any]],
        content: Mapping[str, Any],
        provider_stage: Any = None,
    ) -> dict[str, Any]:
        stage_name = (
            provider_stage.name
            if provider_stage is not None
            else command.generator_operation_name
        )
        token_budget = int(content.get("token_budget") or 0)
        task_byte_accounting = (
            dict(provider_stage.task.get("policy") or {}).get("version") == "world-production-policy.v4"
            if provider_stage is not None
            else content.get("planning_context_policy_version") == "context-policy:chapter-generation-pack:v2"
        )
        if provider_stage is None:
            provider_view, projection_audit = compile_planning_provider_context(stage_name, content)
        else:
            provider_view = build_provider_context_view(stage_name, content, {"world_preparation": dict(provider_stage.task)})
            projection_audit = {}
        accepted_state_boundary = provider_view.get("accepted_state_boundary")
        if not isinstance(accepted_state_boundary, Mapping):
            raise KernelError(
                "PLANNING_CONTEXT_BOUNDARY_INVALID",
                "Planning Provider Context lacks its frozen accepted boundary",
            )
        accepted_state_boundary = dict(accepted_state_boundary)
        sources = {
            str(item.get("asset_version_id") or ""): item for item in selected_inputs
        }
        candidates: list[ContextCandidate] = []

        def append_candidate(
            *,
            asset_version_id: str,
            logical_kind: str,
            physical_asset_type: str,
            value: Any,
            source_revision: str,
            source_identity: str,
            provenance: Mapping[str, Any],
            section: str,
            bucket: str,
        ) -> None:
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            projection_hash = canonical_hash(value)
            semantic_value = (
                value.get("content")
                if isinstance(value, Mapping) and "content" in value
                else value
            )
            semantic_hash = canonical_hash(semantic_value)
            candidates.append(
                ContextCandidate(
                    asset_version_id=asset_version_id,
                    asset_type=logical_kind,
                    physical_asset_type=physical_asset_type,
                    project_id=command.project_id,
                    book_id=command.book_id,
                    estimated_tokens=max(1, len(rendered.encode("utf-8")) if task_byte_accounting else (len(rendered) + 3) // 4),
                    content_digest=projection_hash,
                    source_revision=source_revision,
                    source_identity=source_identity,
                    logical_narrative_identity=(
                        f"{command.book_id}:{stage_name}:"
                        f"{logical_kind}:{source_identity}"
                    ),
                    semantic_representation_identity=(
                        f"provider-context-view-v2:{logical_kind}:{semantic_hash}"
                    ),
                    safe_summary=rendered,
                    compression_method="authority_projection",
                    context_class="PROTECTED",
                    required=True,
                    provenance=dict(provenance),
                    accepted_boundary=accepted_state_boundary,
                    section=section,
                    bucket=bucket,
                )
            )

        segments = provider_view.get("segments")
        if not isinstance(segments, list):
            raise KernelError(
                "PLANNING_CONTEXT_VIEW_INVALID",
                "Planning Provider Context view has no projected segments",
            )
        for segment in segments:
            if not isinstance(segment, Mapping):
                raise KernelError(
                    "PLANNING_CONTEXT_VIEW_INVALID",
                    "Planning Provider Context segment must be an object",
                )
            asset_version_id = str(segment.get("asset_version_id") or "")
            source = sources.get(asset_version_id)
            if source is None:
                raise KernelError(
                    "PLANNING_CONTEXT_VIEW_SOURCE_UNBOUND",
                    "Planning Provider Context segment has no frozen source",
                )
            role = str(segment.get("role") or "")
            source_revision = str(source.get("content_hash") or "")
            append_candidate(
                asset_version_id=asset_version_id,
                logical_kind=f"planning_segment:{role}",
                physical_asset_type=str(source.get("asset_type") or ""),
                value=segment,
                source_revision=source_revision,
                source_identity=asset_version_id,
                provenance={
                    "authority_asset_version_id": asset_version_id,
                    "source_content_hash": source_revision,
                    "planning_role": role,
                    "projection_contract": "provider-context-view-v2",
                },
                section="PLANNING_INPUTS",
                bucket=role or "INPUT",
            )

        envelope = {
            key: provider_view[key]
            for key in (
                "contract_version",
                "stage",
                "narrative_position",
                "accepted_state_boundary",
                "selection_explanation",
            )
            if key in provider_view
        }
        envelope_hash = canonical_hash(envelope)
        append_candidate(
            asset_version_id=f"planning-context-envelope:{envelope_hash}",
            logical_kind="planning_context_envelope",
            physical_asset_type="planning_context_projection",
            value=envelope,
            source_revision=envelope_hash,
            source_identity=(
                f"planning-context-envelope:{stage_name}:{command.logical_key}"
            ),
            provenance={
                "authority": "StoryPlanningRuntime",
                "projection_contract": "provider-context-view-v2",
                "frozen_component_hash": envelope_hash,
            },
            section="PLANNING_CONTRACT",
            bucket="planning_context_envelope",
        )
        for key in ("realization_reference_contract", "repair_context", "author_design_projection"):
            if key not in provider_view:
                continue
            value = provider_view[key]
            digest = canonical_hash(value)
            repair_source = (
                value.get("source_candidate")
                if key == "repair_context" and isinstance(value, Mapping)
                else None
            )
            repair_version_id = (
                str(repair_source.get("asset_version_id") or "")
                if isinstance(repair_source, Mapping)
                else ""
            )
            repair_revision = (
                str(repair_source.get("content_hash") or "")
                if isinstance(repair_source, Mapping)
                else ""
            )
            append_candidate(
                asset_version_id=repair_version_id or f"{key}:{digest}",
                logical_kind=f"planning_{key}",
                physical_asset_type=(
                    str(
                        repair_source.get("asset_type") or "planning_context_projection"
                    )
                    if isinstance(repair_source, Mapping)
                    else "planning_context_projection"
                ),
                value=value,
                source_revision=repair_revision or digest,
                source_identity=repair_version_id or f"{key}:{command.logical_key}",
                provenance={
                    "authority": "StoryPlanningRuntime",
                    "projection_contract": "provider-context-view-v2",
                    "frozen_component_hash": digest,
                    **(
                        {"author_projection_source_receipt": dict(value["source_receipt"])}
                        if key == "author_design_projection" and isinstance(value, Mapping) and isinstance(value.get("source_receipt"), Mapping)
                        else {}
                    ),
                    **(
                        {"authority_asset_version_id": repair_version_id}
                        if repair_version_id
                        else {}
                    ),
                },
                section="PLANNING_CONTRACT",
                bucket=key,
            )
        allowed = tuple(sorted({item.logical_context_kind for item in candidates}))
        if provider_stage is not None:
            source_ref = provider_stage.task["source_ref"]
            append_candidate(
                asset_version_id=source_ref["asset_version_id"],
                logical_kind="world_role_task",
                physical_asset_type="world_preparation_source",
                value=provider_stage.task,
                source_revision=source_ref["content_hash"],
                source_identity=f"world-task:{stage_name}:{source_ref['asset_version_id']}",
                provenance={
                    "authority_asset_version_id": source_ref["asset_version_id"],
                    "source_content_hash": source_ref["content_hash"],
                    "projection_contract": "world-provider-task.v1",
                },
                section="WORLD_TASK",
                bucket=provider_stage.task["role"],
            )
            allowed = tuple(sorted({item.logical_context_kind for item in candidates}))
        required = tuple(sorted({item.logical_context_kind for item in candidates}))
        common = {
            "allowed": list(allowed),
            "required": list(required),
            "token_budget": token_budget,
            **({"token_accounting": "utf8-byte-upper-bound.v1"} if task_byte_accounting else {}),
        }
        snapshots = (
            ContextPolicySnapshot(
                identity=PolicyIdentity(
                    policy_id="planning-context-profile",
                    version="context-profile-v1",
                    content_hash=canonical_hash({**common, "kind": "profile"}),
                    snapshot_ref="planning-context-profile:v1",
                ),
                allowed_logical_kinds=allowed,
                required_logical_kinds=required,
                limits=ContextBudgetLimits(total=token_budget),
                permitted_source_modes=("generation",),
                source_risk_threshold=0,
            ),
            ContextPolicySnapshot(
                identity=PolicyIdentity(
                    policy_id="planning-typed-stage:" + stage_name,
                    version="planning-context-contract-v1",
                    content_hash=canonical_hash({**common, "stage": stage_name}),
                    snapshot_ref="planning-context-contract:" + stage_name,
                ),
                allowed_logical_kinds=allowed,
                required_logical_kinds=required,
                limits=ContextBudgetLimits(total=token_budget),
                permitted_source_modes=("generation",),
                source_risk_threshold=0,
            ),
            ContextPolicySnapshot(
                identity=PolicyIdentity(
                    policy_id="planning-caller-context-limit",
                    version="caller-context-limit-v1",
                    content_hash=canonical_hash(
                        {"token_budget": token_budget, "required": list(required)}
                    ),
                    snapshot_ref="command:planning-context-token-budget",
                ),
                allowed_logical_kinds=allowed,
                required_logical_kinds=required,
                limits=ContextBudgetLimits(total=token_budget),
                permitted_source_modes=("generation",),
                source_risk_threshold=0,
            ),
        )
        compilation = compile_effective_context_policy(snapshots)
        profile = ContextProfile(
            name="planning",
            allowed_asset_types=frozenset(allowed),
            forbidden_asset_types=frozenset(),
            required_asset_types=frozenset(required),
            maximum_raw_source_ratio=0.0,
            maximum_token_budget=token_budget,
            source_risk_threshold=0,
            generation_allowed_requirement=True,
            copyright_mode="abstract_or_project_owned_only",
            priority_rules=("required_first", "stable_identity"),
        )
        selection = select_context_candidates(
            project_id=command.project_id,
            book_id=command.book_id,
            profile=profile,
            candidates=candidates,
            token_budget=token_budget,
            effective_policy=compilation.effective_policy,
            authority_state_boundary=accepted_state_boundary,
        )
        if len(selection.selected) != len(candidates):
            raise KernelError(
                "PLANNING_CONTEXT_GOVERNANCE_BLOCKED",
                "Planning typed Context cannot send a dropped or deduplicated input",
            )
        manifest = {
            "type": "NarrativeContextManifest",
            "contract_version": "planning-context-manifest-v1",
            "scope": {
                "project_id": command.project_id,
                "book_id": command.book_id,
                "planning_scope": command.planning_scope.value,
                "logical_key": command.logical_key,
            },
            "provider_context_view": {
                "contract_version": str(provider_view.get("contract_version") or ""),
                "content_hash": canonical_hash(provider_view),
                "compiled_view": provider_view,
                "source_input_hash": planning_context_source_hash(content),
            },
            "projection_audit": projection_audit,
            "effective_policy": compilation.effective_policy.to_dict(),
            "policy_compilation": dict(compilation.receipt),
            "selected_inputs": [
                {
                    "asset_version_id": item.asset_version_id,
                    "physical_asset_type": item.physical_asset_type,
                    "logical_context_kind": item.logical_context_kind,
                    "source_identity": item.source_identity,
                    "logical_narrative_identity": item.logical_narrative_identity,
                    "semantic_representation_identity": (
                        item.semantic_representation_identity
                    ),
                    "source_revision": item.source_revision,
                    "estimated_tokens": item.estimated_tokens,
                    "provenance": dict(item.provenance),
                }
                for item in selection.selected
            ],
            "candidate_decisions": [dict(item) for item in selection.decisions],
            "deduplication_decisions": [
                dict(item) for item in selection.deduplications
            ],
            "truncation_decisions": [dict(item) for item in selection.truncations],
            "token_accounting": {**dict(selection.token_accounting),
                                 **({"method": "utf8-byte-upper-bound.v1"} if task_byte_accounting else {})},
        }
        manifest["context_fingerprint"] = canonical_hash(manifest)
        return manifest

    def _append_narrative_intelligence_documents(
        self,
        *,
        command: StoryPlanningGenerationCommand,
        selection: Mapping[str, Any],
        documents: list[AuthorityAssetDocument],
        selected_inputs: list[dict[str, Any]] | None = None,
        knowledge_access_policy: Mapping[str, Any],
    ) -> None:
        access = validate_book_knowledge_access_policy(
            knowledge_access_policy,
            project_id=command.project_id,
            book_id=command.book_id,
        )
        if selection.get("knowledge_access_policy") != access:
            raise KernelError(
                "PLANNING_KNOWLEDGE_ACCESS_POLICY_DRIFT",
                "Narrative Intelligence selection differs from Book access policy",
            )
        selected = selection.get("selected")
        if not isinstance(selected, list):
            raise KernelError(
                "PLANNING_NARRATIVE_INTELLIGENCE_INVALID",
                "Narrative Intelligence selection must expose a bounded card list",
            )
        if len(selected) > 12:
            raise KernelError(
                "PLANNING_NARRATIVE_INTELLIGENCE_INVALID",
                "Narrative Intelligence selection exceeds Planning bandwidth",
            )
        selected_ids = {
            str(item.get("knowledge_card_asset_version_id") or "")
            for item in selected
            if isinstance(item, Mapping)
        }
        allowed_ids = set(access["allowed_knowledge_card_asset_version_ids"])
        if (
            (access["mode"] == "DENY_ALL" and selected_ids)
            or (access["mode"] == "ALLOW_ONLY" and not selected_ids.issubset(allowed_ids))
        ):
            raise KernelError(
                "PLANNING_KNOWLEDGE_ACCESS_SCOPE_VIOLATION",
                "selected Narrative Intelligence is outside the exact Book allow set",
            )
        for ordinal, item in enumerate(selected, start=1):
            if not isinstance(item, Mapping):
                raise KernelError(
                    "PLANNING_NARRATIVE_INTELLIGENCE_INVALID",
                    "Narrative Intelligence selection item is malformed",
                )
            asset_version_id = str(item.get("knowledge_card_asset_version_id") or "")
            content_hash = str(item.get("content_hash") or "")
            self.mkaos.require_planning_card_current(
                project_id=command.project_id,
                asset_version_id=asset_version_id,
                content_hash=content_hash,
                book_id=command.book_id,
                knowledge_access_policy=dict(access),
            )
            document = self.query.require(
                project_id=command.project_id,
                asset_version_id=asset_version_id,
            )
            if (
                document.asset_type != "knowledge_card"
                or document.content_hash != content_hash
                or document.lifecycle != "ACTIVE"
                or document.governance != "CLEAR"
                or document.eligibility not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            ):
                raise KernelError(
                    "PLANNING_NARRATIVE_INTELLIGENCE_DRIFT",
                    "Selected KnowledgeCard differs from its governed frozen version",
                )
            mechanism = (item.get("selected_content") or {}).get("craft_mechanism")
            if mechanism is not None and mechanism != (document.content.get("abstract_content") or {}).get("craft_mechanism"):
                raise KernelError("CRAFT_FROZEN_SELECTION_DRIFT", "Frozen Craft selection must retain the exact governed Card mechanism")
            documents.append(document)
            if selected_inputs is not None:
                selected_inputs.append(
                    {
                        "role": f"narrative_intelligence:{ordinal}",
                        "asset_version_id": document.asset_version_id,
                        "asset_type": document.asset_type,
                        "content_hash": document.content_hash,
                        "content": dict(item.get("selected_content") or {}),
                        "selection_score": int(item.get("score") or 0),
                        "selection_reasons": list(item.get("match_reasons") or ()),
                    }
                )

    @staticmethod
    def _validate_frozen_context_retry(
        *,
        context: AuthorityAssetDocument,
        command: StoryPlanningGenerationCommand,
        selected_inputs: list[dict[str, Any]],
        context_policy_ref: str = "",
    ) -> None:
        content = context.content
        frozen_inputs = content.get("input_versions")
        if (
            context.asset_type != "context_bundle"
            or context.lifecycle != "ACTIVE"
            or context.governance != "CLEAR"
            or content.get("schema_version") != "novelos.planning_context_bundle.v1"
            or content.get("project_id") != command.project_id
            or content.get("workspace_id") != command.workspace_id
            or content.get("book_id") != command.book_id
            or content.get("planning_scope") != command.planning_scope.value
            or content.get("logical_key") != command.logical_key
            or content.get("arc_working_set") != dict(command.arc_working_set or {})
            or content.get("narrative_search") != command.narrative_search_snapshot
            or str(content.get("planning_context_policy_version") or "") != (
                context_policy_ref if context_policy_ref == "context-policy:chapter-generation-pack:v2" else ""
            )
            or not isinstance(frozen_inputs, list)
            or frozen_inputs[: len(selected_inputs)] != selected_inputs
        ):
            raise KernelError(
                "PLANNING_CONTEXT_BUNDLE_CONFLICT",
                "Planning Attempt context changed after freeze",
            )

    def _repair_context(
        self,
        *,
        command: StoryPlanningGenerationCommand,
        source: AuthorityAssetDocument,
    ) -> dict[str, Any]:

        _, separator, report_hash = command.repair_reason.partition(":")
        if not separator or not report_hash.startswith("sha256:"):
            raise KernelError(
                "PLANNING_REPAIR_REASON_INVALID",
                "Planning repair requires a validation report hash",
            )
        runtime = get_database_runtime(self.database_url)
        with runtime.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT validation_kind, status, report, report_hash,
                           generation_operation_id
                    FROM authority_story_planning_validation_report
                    WHERE project_id=%s
                      AND candidate_asset_version_id=%s
                      AND report_hash=%s
                    """,
                    [
                        command.project_id,
                        command.repair_of_candidate_id,
                        report_hash,
                    ],
                )
                report_row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT design_layer, profile_id, profile_version, profile_hash,
                           capability_id, skill_ref, qualification_status,
                           evaluation, evaluation_hash, qualification_hash,
                           source_operation_id, evaluation_operation_id,
                           evaluation_attempt_id, evaluation_asset_version_id,
                           evaluation_evidence_hash
                    FROM authority_narrative_design_qualification
                    WHERE project_id=%s
                      AND asset_version_id=%s
                      AND qualification_status <> 'PASS'
                    ORDER BY design_layer, profile_id
                    """,
                    [command.project_id, command.repair_of_candidate_id],
                )
                qualification_rows = cursor.fetchall()
        if report_row is None or str(report_row[1]) != "FAIL":
            raise KernelError(
                "PLANNING_REPAIR_EVIDENCE_MISSING",
                "Planning repair validation evidence is absent or not failed",
            )
        failures = [
            {
                "design_layer": str(row[0]),
                "profile_id": str(row[1]),
                "profile_version": str(row[2]),
                "profile_hash": str(row[3]),
                "capability_id": str(row[4]),
                "skill_ref": str(row[5]),
                "qualification_status": str(row[6]),
                "evaluation": dict(row[7]),
                "evaluation_hash": str(row[8]),
                "qualification_hash": str(row[9]),
                "source_operation_id": str(row[10]),
                "evaluation_operation_id": str(row[11]),
                "evaluation_attempt_id": str(row[12]),
                "evaluation_asset_version_id": str(row[13]),
                "evaluation_evidence_hash": str(row[14]),
            }
            for row in qualification_rows
        ]
        if str(report_row[0]) == "SEMANTIC" and not failures:
            raise KernelError(
                "PLANNING_REPAIR_EVIDENCE_MISSING",
                "Semantic repair requires failed independent qualification evidence",
            )
        return {
            "contract_version": "planning-repair-context-v1",
            "source_candidate": {
                "asset_version_id": source.asset_version_id,
                "content_hash": source.content_hash,
                "asset_type": source.asset_type,
                "content": source.content,
            },
            "validation_failure": {
                "validation_kind": str(report_row[0]),
                "status": str(report_row[1]),
                "report": dict(report_row[2]),
                "report_hash": str(report_row[3]),
                "generation_operation_id": str(report_row[4]),
            },
            "failed_narrative_qualifications": failures,
        }

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

    def _select_model_profile(self, project_id: str, profile: ModelProfile) -> ModelProfile:
        logical_ref = f"production_execution/model_profiles/{profile.profile_id}/v{profile.profile_version}"
        try:
            existing = self.query.require(project_id=project_id, logical_ref=logical_ref)
        except KernelError as error:
            if error.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            return replace(profile, profile_id=f"{profile.profile_id}.sha256.{profile.contract_hash}")
        contract = existing.content.get("contract", existing.content)
        expected = profile.to_dict()
        if (
            existing.asset_type != "model_profile"
            or not isinstance(contract, Mapping)
            or set(contract) != set(expected)
            or any(type(contract[key]) is not type(value) for key, value in expected.items())
            or contract.get("profile_id") != profile.profile_id
            or contract.get("profile_version") != profile.profile_version
        ):
            raise KernelError("EXECUTION_CONTRACT_FROZEN_CONFLICT", "the retained model profile identity is not a valid typed contract")
        try:
            retained = ModelProfile.from_dict(contract)
        except ValueError as error:
            raise KernelError("EXECUTION_CONTRACT_FROZEN_CONFLICT", "the retained model profile contract is invalid") from error
        if retained.to_dict() != contract:
            raise KernelError("EXECUTION_CONTRACT_FROZEN_CONFLICT", "the retained model profile contract is not canonical")
        if contract == expected:
            return profile
        return replace(profile, profile_id=f"{profile.profile_id}.sha256.{profile.contract_hash}")

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
        try:
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
        except KernelError as error:
            if error.code != "AUTHORITY_ASSET_VERSION_CONFLICT":
                raise
            concurrent = self.query.require(project_id=project_id, logical_ref=logical_ref)
            if concurrent.asset_type != asset_type or concurrent.content.get("contract", concurrent.content) != contract:
                raise KernelError("EXECUTION_CONTRACT_FROZEN_CONFLICT", "concurrent Planning execution contract differs from its immutable identity") from error
            return concurrent


__all__ = [
    "PLANNING_EXTERNAL_EFFECT_MAX_ATTEMPTS",
    "PostgresPlanningExecutionPreparer",
    "planning_fixture_response",
    "planning_provider_output_schema",
]


def _world_contract_route_receipt(database_url, *, command, payload, task_type, input_hash, lineage):
    reference_contract = command.repair_reason == "PLANNING_REFERENCE_CONTRACT_SUCCESSOR" and task_type == "chapter_group_plan.generate"
    if task_type not in {"world_candidates.generate", "world_candidates.evaluate"} and not reference_contract:
        return None
    if not command.runtime_continuation_id or command.execution_contract_version != "1.21.0":
        return None
    from .runtime_continuation import require_binding, require_source
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    binding = require_binding(database_url, command.runtime_continuation_id)
    if binding["successor_command"] != payload or binding["target_runtime"].get("pack_snapshot") is None:
        raise KernelError("PLANNING_ROUTING_CONTRACT_DRIFT", "contract route must bind the registered immutable successor")
    source_id = binding["source_operation_id"]
    with AuthorityUnitOfWork(database_url) as uow:
        source = require_source(uow, source_operation_id=source_id, project_id=command.project_id, active_successor_operation_id=lineage[-1])
        if source.get("mode") != ("PLANNING_REFERENCE_CONTRACT" if reference_contract else "WORLD_AGENCY_CONTRACT") or source["command"].get("repair_number") != command.repair_number:
            raise KernelError("PLANNING_ROUTING_CONTRACT_DRIFT", "contract succession cannot reset content repair consumption")
        uow.cursor.execute("SELECT request_payload #>> '{_production_execution,capability_runtime,routing_decision,task,input_hash}' FROM authority_external_effect WHERE operation_id=%s AND status='SUCCEEDED' AND request_payload->>'stage'=%s", [source_id, task_type])
        previous = uow.cursor.fetchall()
        if len(previous) != 1 or not previous[0][0] or previous[0][0] == input_hash:
            raise KernelError("PLANNING_ROUTING_REPAIR_INPUT_UNCHANGED", "schema succession needs an actually changed stage request")
    authoritative = _planning_repair_routing_lineage(database_url, project_id=command.project_id, book_id=command.book_id, generator_operation_name=command.generator_operation_name, operation_id=lineage[-1], repair_of_operation_id="")
    if authoritative != lineage:
        raise KernelError("PLANNING_ROUTING_LINEAGE_INVALID", "contract successor must retain full native lineage")
    dependency = {}
    if task_type == "world_candidates.evaluate":
        current = AuthorityAssetQuery(database_url).require(project_id=command.project_id, logical_ref=f"world_preparation/{lineage[-1]}/generation")
        evidence = current.content["contract"]["evidence"]
        receipt = read_succeeded_external_effect(database_url, EffectCommandContext(operation_id=lineage[-1], project_id=command.project_id, actor_id=command.actor_id, trace_id=command.trace_id, correlation_id=command.correlation_id), effect_id=evidence["external_receipt_ref"])
        if receipt is None or receipt["budget_reservation_status"] != "SETTLED" or receipt["provider_evidence"].get("result") != current.content["contract"]["output"]:
            raise KernelError("PLANNING_ROUTING_DEPENDENCY_UNSETTLED", "new Director request requires current known settled generation")
        dependency = {"dependent_evaluation": {"generation": {"asset_version_id": current.asset_version_id, "content_hash": current.content_hash}, "external_effect_id": evidence["external_receipt_ref"]}}
    return {"contract_version": "planning-route-contract-successor.v2" if reference_contract else "planning-route-contract-successor.v1", **dependency, "operation_id": lineage[-1],
        "source_operation_id": source_id, "source_asset_version_id": source["evidence_asset_version_id"],
        "diagnosis_hash": canonical_hash(source["diagnostic"]), "repair_number": command.repair_number,
        "maximum_repairs": 4, "contract_chain_depth": source["depth"], "source_input_hash": previous[0][0], "input_hash": input_hash,
        "command_hash": canonical_hash(payload), "authorized_history_operation_ids": list(lineage[:-1]),
        "accepted_history_mutation_allowed": False, "changed_contract": "planning-host-source-selectors.v2" if reference_contract else "world-agency.v2"}

def bind_provider_realization_selectors(payload, catalog):
    from copy import deepcopy

    value = deepcopy(dict(payload))
    fields = {
        "world_realization": {
            "invariant_refs": "WORLD_INVARIANT",
            "structure_refs": "WORLD_STRUCTURE",
            "state_ref": "WORLD_STATE",
        },
        "character_realization": {
            "identity_ref": "CHARACTER_IDENTITY",
            "state_ref": "CHARACTER_STATE",
            "trajectory_ref": "CHARACTER_TRAJECTORY",
        },
    }
    for manifest, domains in fields.items():
        for entity in value.get(manifest, []):
            for field, domain in domains.items():
                raw = entity[field]
                selectors = raw if isinstance(raw, list) else [raw]
                references = []
                for selector in selectors:
                    if not isinstance(selector, dict) or set(selector) != {
                        "asset_version_id"
                    }:
                        raise KernelError(
                            "PLANNING_REALIZATION_SELECTOR_INVALID",
                            "Model selects a frozen source; host owns its identity, type, hash and lineage",
                        )
                    matches = [
                        ref
                        for ref in catalog["references_by_domain"][domain]
                        if ref["asset_version_id"] == selector["asset_version_id"]
                    ]
                    if len(matches) != 1:
                        raise KernelError(
                            "PLANNING_REALIZATION_SELECTOR_INVALID",
                            "Source must belong to the exact frozen domain catalogue",
                        )
                    references.append(deepcopy(matches[0]))
                entity[field] = references if isinstance(raw, list) else references[0]
    return value


def bind_realization_selector_schema(
    schema, catalog, *, primary_arc_id, related_arc_ids
):
    from copy import deepcopy

    value = deepcopy(schema)
    from .character_references import bind_character_schema
    bind_character_schema(value, catalog.get("character_references"))
    fields = {
        "world_realization": {
            "invariant_refs": "WORLD_INVARIANT",
            "structure_refs": "WORLD_STRUCTURE",
            "state_ref": "WORLD_STATE",
        },
        "character_realization": {
            "identity_ref": "CHARACTER_IDENTITY",
            "state_ref": "CHARACTER_STATE",
            "trajectory_ref": "CHARACTER_TRAJECTORY",
        },
    }
    for manifest, domains in fields.items():
        for field, domain in domains.items():
            refs = catalog["references_by_domain"][domain]
            selector = _strict_object(
                {
                    "asset_version_id": {
                        "type": "string",
                        "enum": [ref["asset_version_id"] for ref in refs],
                        "description": "Select one supplied source in this domain. The host binds all identity, hash, type and Operation fields.",
                    }
                }
            )
            properties = value["properties"][manifest]["items"]["properties"]
            if field.endswith("_refs"):
                properties[field]["items"] = selector
            else:
                properties[field] = selector
    if "primary_arc_ids" in value["properties"]:
        value["properties"]["primary_arc_ids"] = {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": {"type": "string", "const": primary_arc_id},
            "description": "The frozen primary Arc for this request.",
        }
        value["properties"]["secondary_arc_ids"] = {
            "type": "array",
            "minItems": len(related_arc_ids),
            "maxItems": len(related_arc_ids),
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": list(related_arc_ids) or ["NO_RELATED_ARC"],
            },
            "description": "Classify every frozen related Arc exactly once. Membership does not require movement in this chapter; HOLD and future setup remain possible.",
        }
    return value
