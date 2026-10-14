"""SECURITY: only task-specific projections may expose frozen Chapter inputs to a Provider; audit and duplicate representations stay excluded."""

from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from typing import Any, Iterable, Mapping
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state import (
    compact_canon_facts,
    compact_current_state_facts,
)

_MAX_SEGMENTS = 24
_MAX_FACTS_PER_SEGMENT = 32
_MAX_PROVIDER_CONTEXT_CHARACTERS = 65_536
_TASK_PROVIDER_SERIALIZATION_BYTES = 8_388_608
_PLANNING_TASK_CAPACITY_POLICY = "context-policy:chapter-generation-pack:v2"
_MAX_FOUNDATION_EVALUATION_CONTEXT_CHARACTERS = 131_072
_MAX_PROVIDER_KNOWLEDGE_CHARACTERS = 65_536
_STATE_ASSET_TYPES = {"story_state_snapshot", "canon_snapshot"}


_PLANNING_STAGES = frozenset(
    {
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "chapter_group_plan.generate",
        "chapter_plan.generate",
    }
)
_NARRATIVE_FOUNDATION_DEPENDENCY_TYPES = {
    "CREATIVE_FOUNDATION": "creative_foundation",
    "THEME_CONTRACT": "theme_contract",
    "ENDING_INTENT": "ending_intent",
    "READER_PROMISE": "reader_promise",
    "WORLD_BIBLE": "world_bible",
    "CHARACTER_CAST": "character_cast",
}
_NARRATIVE_FOUNDATION_GENERATORS = {
    "CREATIVE_FOUNDATION": "creative.candidates.generate",
    "THEME_CONTRACT": "theme.candidates.generate",
    "ENDING_INTENT": "ending.intent.generate",
    "READER_PROMISE": "reader.promise.generate",
    "WORLD_BIBLE": "world.design.generate",
    "CHARACTER_CAST": "character.cast.generate",
}
_REFERENCE_FIELD_SUFFIXES = ("_id", "_ids", "_ref", "_refs")
_OPTIONAL_PLANNING_FIELDS = frozenset({
    "soft_suggestions", "optional_guidance", "style_suggestions", "inspiration",
})
_REQUIRED_PLANNING_FIELDS = {
    "hard_constraints": "HARD_CONSTRAINT",
    "invariants": "HARD_CONSTRAINT",
    "story_constraints": "HARD_CONSTRAINT",
    "constraints": "HARD_CONSTRAINT",
    "forbidden_events": "PROHIBITION",
    "forbidden_payoffs": "PROHIBITION",
    "prohibited_outcomes": "PROHIBITION",
    "required_facts": "REQUIRED_FACT",
    "required_fact_ids": "REQUIRED_FACT",
    "required_payoffs": "DUE_OBLIGATION",
    "due_obligations": "DUE_OBLIGATION",
    "required_obligation_ids": "DUE_OBLIGATION",
    "unresolved_obligation_ids": "DUE_OBLIGATION",
    "knowledge_boundaries": "CHARACTER_KNOWLEDGE_SCOPE",
    "character_participation": "CHARACTER_KNOWLEDGE_SCOPE",
    "knowledge_translations": "KNOWLEDGE_TRANSLATION",
}
_RETRIEVAL_SELECTOR_KEYS = frozenset(
    {
        "entity_ids",
        "character_ids",
        "relationship_ids",
        "arc_plan_version_ids",
        "obligation_ids",
    }
)
_PLANNING_ROLE_FIELDS: dict[str, tuple[str, ...]] = {
    "book_plan": (
        "objective",
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
        "hard_constraints",
        "required_payoffs",
        "forbidden_events",
        "forbidden_payoffs",
    ),
    "volume_plan": (
        "objective",
        "volume_function",
        "stage_conflict",
        "stage_antagonist",
        "irreversible_change",
        "midpoint",
        "climax",
        "settlement",
        "next_volume_bridge",
        "chapter_range",
        "narrative_segments",
        "hard_constraints",
        "required_payoffs",
        "forbidden_events",
        "forbidden_payoffs",
    ),
    "arc_plans": (
        "thread_id",
        "arc_type",
        "objective",
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
        "arc_segments",
        "arc_relations",
        "hard_constraints",
        "forbidden_events",
        "forbidden_payoffs",
    ),
    "chapter_group_plan": (
        "objective",
        "local_objective",
        "trigger",
        "resistance_escalation",
        "turn",
        "local_climax",
        "information_release",
        "emotion_curve",
        "antagonist_actions",
        "chapter_range",
        "cost_range",
        "narrative_segment_ref",
        "chapter_function_matrix",
        "hard_constraints",
        "required_payoffs",
        "forbidden_events",
        "forbidden_payoffs",
    ),
}
_OPERATIONAL_KEYS = {
    "actual_context",
    "actual_context_digest",
    "candidate_payload",
    "constraint_envelope",
    "context",
    "context_digest",
    "context_manifest",
    "cost_ledger_refs",
    "cost_receipt_refs",
    "created_by_operation_id",
    "evidence_level",
    "execution_evidence",
    "execution_window",
    "frozen_inputs",
    "model_call_log_refs",
    "normalized_digest",
    "provider_evidence",
    "provider_receipt_refs",
    "qualification",
    "routing_bootstrap_authorization",
    "reference_predecessor_operation_id",
    "reference_evaluation",
    "routing_eligibility",
    "routing_decision",
    "runtime_result",
    "reducer_applications",
    "source_chapter_plan_asset_version_id",
    "source_chapter_plan_content_hash",
    "source_extensions",
    "result_admission_recovery",
    "stage_context_view",
    "trace_id",
}


def _project_empty_world_selection(selection: Any, *, project_query_directory: bool = True) -> Any:
    from novel_forge.modules.mkaos_authority.domain import validate_book_knowledge_access_policy

    if not isinstance(selection, Mapping) or not isinstance(selection.get("need"), Mapping):
        return deepcopy(selection)
    result = deepcopy(dict(selection))
    need = result["need"]
    receipt = need.get("condition_sources_receipt")
    policy = result.get("knowledge_access_policy")
    eligible = (
        result.get("schema_version") == "mkaos-narrative-intelligence-selection.v1"
        and result.get("selected") == []
        and result.get("selection_status") == "NO_ELIGIBLE_MATCH"
        and need.get("required_card_asset_version_ids") == []
        and _is_exact_sha256(result.get("selection_digest"))
        and _is_exact_sha256(need.get("need_digest"))
        and isinstance(policy, Mapping)
    )
    if eligible:
        try:
            validate_book_knowledge_access_policy(policy, project_id=str(result.get("project_id") or ""), book_id=str(policy.get("book_id") or ""))
        except (KernelError, ValueError):
            eligible = False
    if receipt is not None:
        if (not eligible or "condition_sources" in need or not isinstance(receipt, Mapping)
            or receipt.get("contract_version") != "world-selection-source-receipt.v1"
            or receipt.get("frozen_context_pointer") != "/narrative_intelligence/need/condition_sources"
            or receipt.get("selection_digest") != result["selection_digest"]
            or receipt.get("need_digest") != need["need_digest"]):
            raise KernelError("WORLD_SELECTION_RECEIPT_INVALID", "World source omission differs from its frozen empty selection")
        query_receipt = need.get("query_directory_receipt")
        if query_receipt is not None and (
            not isinstance(query_receipt, Mapping)
            or query_receipt.get("contract_version") != "world-empty-selection-query-receipt.v1"
            or query_receipt.get("selection_digest") != result["selection_digest"]
            or query_receipt.get("need_digest") != need["need_digest"]
            or query_receipt.get("frozen_context_pointer") != "/narrative_intelligence/need"
            or any(key in need for key in query_receipt.get("omitted_fields", []))
        ):
            raise KernelError("WORLD_SELECTION_RECEIPT_INVALID", "World retrieval query omission differs from its frozen empty selection")
        return result
    sources = need.get("condition_sources")
    if (not eligible or not isinstance(sources, Mapping) or not sources
        or need["need_digest"] != _projection_hash({key: value for key, value in need.items() if key != "need_digest"})
        or not all(isinstance(item, Mapping) and set(item) == {"asset_version_id", "content_hash"}
                   and isinstance(item["asset_version_id"], str) and bool(item["asset_version_id"])
                   and _is_exact_sha256(item["content_hash"]) for item in sources.values())):
        return result
    need["condition_sources_receipt"] = {
        "contract_version": "world-selection-source-receipt.v1",
        "frozen_context_pointer": "/narrative_intelligence/need/condition_sources",
        "selection_digest": result["selection_digest"], "need_digest": need["need_digest"],
        "omitted_value_hash": _projection_hash(sources),
        "omitted_source_count": len(sources),
        "omitted_serialized_characters": _serialized_character_count(sources),
        "reason": "EMPTY_SELECTION_SOURCE_VERSION_DIRECTORY_ONLY",
    }
    del need["condition_sources"]
    if project_query_directory:
        result = _project_empty_world_query_directory(result)
    return result if _serialized_character_count(result) < _serialized_character_count(selection) else deepcopy(selection)


def _project_empty_world_query_directory(selection: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(selection)
    need = result["need"]
    fields = {
        "semantic_families", "theme_tags", "genre_tags", "reader_effect_tags", "conflict_tags",
        "current_state_terms", "desired_transformation_terms", "craft_context", "craft_policy",
        "recent_craft_usage", "recently_used_repetition_keys",
    }
    directory = {key: need[key] for key in sorted(fields) if key in need}
    if not directory:
        return selection
    for key in directory:
        del need[key]
    need["query_directory_receipt"] = {
        "contract_version": "world-empty-selection-query-receipt.v1",
        "frozen_context_pointer": "/narrative_intelligence/need",
        "selection_digest": result["selection_digest"], "need_digest": need["need_digest"],
        "omitted_fields": list(directory), "omitted_value_hash": _projection_hash(directory),
        "omitted_entry_count": sum(len(value) if isinstance(value, (Mapping, list, tuple)) else 1 for value in directory.values()),
        "omitted_serialized_characters": _serialized_character_count(directory),
        "reason": "NO_SELECTED_KNOWLEDGE_RETRIEVAL_QUERY_ONLY",
    }
    return result if _serialized_character_count(result) < _serialized_character_count(selection) else selection


def _project_selected_world_selection(selection: Any) -> Any:
    if not isinstance(selection, Mapping) or not selection.get("selected") or selection.get("craft_policy", {}).get("schema_version") != "narrative-craft-budget.v4":
        return _project_empty_world_selection(selection)
    result = deepcopy(dict(selection))
    receipt = result.get("world_selection_receipt")
    if receipt is not None:
        if (not isinstance(receipt, Mapping) or receipt.get("contract_version") != "world-selected-knowledge-projection.v1"
            or receipt.get("selection_digest") != result.get("selection_digest")
            or receipt.get("need_digest") != result.get("need", {}).get("need_digest")):
            raise KernelError("WORLD_SELECTION_RECEIPT_INVALID", "Selected World knowledge must preserve exact selection identity")
        return result
    need = result.get("need", {})
    if (need.get("need_digest") != _projection_hash({key: value for key, value in need.items() if key != "need_digest"})
        or result.get("selection_digest") != _projection_hash({key: value for key, value in result.items() if key != "selection_digest"})):
        raise KernelError("WORLD_SELECTION_RECEIPT_INVALID", "World knowledge projection requires the complete frozen selection")
    omitted = {}
    # WHY: World adjudicates legal actions; Chapter Planning alone locates Craft uses and advances planned phases.
    for key in ("condition_sources", "recent_craft_usage", "recently_used_repetition_keys"):
        if key in need:
            omitted["/need/" + key] = need.pop(key)
    context = need.get("craft_context", {})
    for key in ("usage_scope_context", "reselection"):
        if key in context:
            omitted["/need/craft_context/" + key] = context.pop(key)
    for key in ("craft_history", "recent_craft_usage", "rejected"):
        if key in result:
            omitted["/" + key] = result.pop(key)
    if need.get("craft_policy") == result.get("craft_policy") and "craft_policy" in need:
        omitted["/need/craft_policy"] = need.pop("craft_policy")
    for index, card in enumerate(result["selected"]):
        assessment = card.get("craft_assessment", {})
        if "budget_assessment" in assessment:
            omitted[f"/selected/{index}/craft_assessment/budget_assessment"] = assessment.pop("budget_assessment")
    # WHY: Retrieval terms are a search query, not additional facts; World consumes its exact role projection and parent plans.
    for key in tuple(need):
        if key not in {"need_digest", "target_stage", "hard_constraints", "required_card_asset_version_ids"}:
            omitted["/need/" + key] = need.pop(key)
    result["world_selection_receipt"] = {
        "contract_version": "world-selected-knowledge-projection.v1",
        "selection_digest": result["selection_digest"], "need_digest": need["need_digest"],
        "frozen_context_pointer": "/narrative_intelligence",
        "omitted_fields": sorted(omitted), "omitted_value_hash": _projection_hash(omitted),
        "authority": "WORLD_ACTIONS_ONLY_CHAPTER_CRAFT_PLACEMENT_REQUIRES_FULL_SELECTION",
    }
    return result


def _project_denied_planning_selection(selection: Mapping[str, Any], *, empty_query: bool = False) -> Mapping[str, Any]:
    from novel_forge.modules.mkaos_authority.domain import validate_book_knowledge_access_policy

    policy = selection.get("knowledge_access_policy")
    need = selection.get("need")
    if not isinstance(policy, Mapping) or (policy.get("mode") != "DENY_ALL" and not empty_query):
        return selection
    if empty_query and selection.get("selected"):
        return selection
    validate_book_knowledge_access_policy(policy, project_id=str(selection.get("project_id") or ""), book_id=str(policy.get("book_id") or ""))
    if (
        selection.get("selected") != []
        or selection.get("selection_status") != "NO_ELIGIBLE_MATCH"
        or not isinstance(need, Mapping)
        or need.get("required_card_asset_version_ids") != []
        or need.get("need_digest") != _projection_hash({key: value for key, value in need.items() if key != "need_digest"})
        or selection.get("selection_digest") != _projection_hash({key: value for key, value in selection.items() if key != "selection_digest"})
    ):
        raise KernelError("PLANNING_EMPTY_SELECTION_DRIFT", "DENY_ALL selection does not bind its exact empty search result")
    return {
        **{key: value for key, value in selection.items() if key != "need"},
        "need_receipt": {
            "need_digest": need["need_digest"],
            "selection_digest": selection["selection_digest"],
            "frozen_context_pointer": "/narrative_intelligence/need",
            "reason": ("NO_ELIGIBLE_EMPTY_RETRIEVAL_QUERY_IS_NOT_STORY_INPUT" if empty_query else "DENY_ALL_EMPTY_RETRIEVAL_QUERY_IS_NOT_STORY_INPUT"),
        },
    }


def build_provider_task_view(
    stage: str,
    inputs: Mapping[str, Any],
    *,
    compact_contract: bool = False,
    targeted_edits_only: bool = False,
    project_methods: bool = False,
    instruction_cleanup: bool = False,
    work_requirements: bool = False,
) -> dict[str, Any]:
    if stage in {"model_reference_evaluate", "model_reference_adjudicate"}:
        from novel_forge.modules.command_kernel.routing_bootstrap import validate_model_reference_creation_binding

        frozen = inputs.get("model_reference")
        validate_model_reference_creation_binding(frozen)
        expected = "BLIND_EVALUATION" if stage == "model_reference_evaluate" else "ADJUDICATION"
        if frozen["role"] != expected:
            raise KernelError("MODEL_REFERENCE_ROLE_INVALID", "Provider task role differs from its formal stage")
        return _task(stage, model_reference=deepcopy(frozen),
                     subject=deepcopy(inputs.get("subject")),
                     author_baseline=deepcopy(inputs.get("author_baseline")),
                     **({"source_evaluations": deepcopy(inputs.get("source_evaluations"))}
                        if expected == "ADJUDICATION" else {}))
    if work_requirements and stage in {"review", "revision", "rereview"}:
        from .chapter_plan_views import validate_creative_baseline

        source = inputs.get("revision") if stage == "rereview" else inputs.get("draft")
        validate_creative_baseline((source or {}).get("creative_baseline"))
    if stage in {"context_compress", "context_fidelity"}:
        from .context_compression_provider import context_compression_task_view

        return context_compression_task_view(stage, inputs)
    if stage == "retrieval_query_expansion":
        boundary = inputs.get("accepted_boundary")
        coverage = inputs.get("coverage")
        policy = inputs.get("policy")
        prior_rounds = inputs.get("prior_rounds")
        allowed_selectors = inputs.get("allowed_retrieval_selectors")
        if (
            not isinstance(boundary, Mapping)
            or not isinstance(coverage, Mapping)
            or coverage.get("sufficient") is not False
            or not isinstance(policy, Mapping)
            or not isinstance(prior_rounds, list)
            or len(prior_rounds) > 3
            or not isinstance(allowed_selectors, Mapping)
            or any(key not in _RETRIEVAL_SELECTOR_KEYS for key in allowed_selectors)
            or any(
                not isinstance(values, list) or len(values) > 256
                for values in allowed_selectors.values()
            )
        ):
            raise KernelError(
                "RETRIEVAL_EXPANSION_PROVIDER_TASK_INVALID",
                "query expansion requires bounded frozen coverage and campaign policy",
            )
        return _task(
            stage,
            accepted_boundary=_compact(boundary),
            intent_fingerprint=str(inputs.get("intent_fingerprint") or ""),
            memo_fingerprint=str(inputs.get("memo_fingerprint") or ""),
            mission=_compact(inputs.get("mission") or {}),
            memo=_compact(inputs.get("memo") or {}),
            coverage=_compact(coverage),
            policy=_compact(policy),
            prior_rounds=_compact(prior_rounds),
            allowed_retrieval_dimensions=_compact(
                inputs.get("allowed_retrieval_dimensions") or []
            ),
            allowed_retrieval_selectors=_compact(allowed_selectors),
        )
    if stage == "retrieval":
        texts = inputs.get("texts")
        if (
            not isinstance(texts, list)
            or not texts
            or len(texts) > 32
            or any(not isinstance(item, str) or not item.strip() for item in texts)
        ):
            raise KernelError(
                "RETRIEVAL_PROVIDER_TASK_INVALID",
                "retrieval embedding requires a bounded non-empty text batch",
            )
        return _task(
            stage,
            texts=_compact(texts),
            purpose=str(inputs.get("purpose") or ""),
            query_plan_fingerprint=str(inputs.get("query_plan_fingerprint") or ""),
        )
    if stage in {"world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"}:
        from novel_forge.modules.worldbuilding.actor_isolation import validate_actor_task
        task = inputs.get("world_preparation")
        if not isinstance(task, Mapping):
            raise KernelError("WORLD_ACTOR_CONTEXT_LEAK", "exact actor projection required")
        validate_actor_task(task)
        return _task(stage, world_preparation=deepcopy(dict(task)))
    if stage in {"world_candidates.generate", "world_candidates.evaluate"}:
        task = inputs.get("world_preparation")
        if not isinstance(task, Mapping) or task.get("contract_version") not in {"world-provider-task.v1", "world-provider-task.v2", "world-provider-task.v3", "world-provider-task.v4"} or task.get("fact_mutation_allowed") is not False:
            raise KernelError("WORLD_PROVIDER_TASK_INVALID", "world stages require their exact frozen role projection")
        expected_role = "WORLD_REASONER" if stage == "world_candidates.generate" else "DIRECTOR"
        if task.get("role") != expected_role:
            raise KernelError("WORLD_PROVIDER_ROLE_INVALID", "world stage cannot consume another role's context")
        projected_task = deepcopy(dict(task))
        if task["contract_version"] == "world-provider-task.v4":
            from novel_forge.modules.book_authority.working_prose import validate_working_projection
            working = task.get("working_manuscript")
            if not isinstance(working, Mapping):
                raise KernelError("WORLD_WORKING_SOURCE_REQUIRED", "Working World tasks require their frozen selected-source packet")
            validate_working_projection(working, project_id=working.get("project_id"),
                book_id=working.get("book_id"), target_chapter=task.get("target_chapter"),
                accepted_through_chapter=task.get("accepted_through_chapter"))
        for index, segment in enumerate(projected_task.get("planning_window") or []):
            if "loss_records" not in segment:
                continue
            source_ref = projected_task.get("source_ref")
            if not isinstance(source_ref, Mapping) or not source_ref.get("asset_version_id") or not source_ref.get("content_hash"):
                raise KernelError("WORLD_PROVIDER_LOSS_SOURCE_REQUIRED", "World projection loss records require their frozen source asset")
            audit = {key: segment.pop(key) for key in ("loss_records", "loss_sources") if key in segment}
            segment["selection_loss_receipt"] = {
                "source_ref": deepcopy(dict(source_ref)),
                "json_pointer": f"/contract/planning_window/{index}",
                "audit_hash": _projection_hash(audit),
                "loss_record_count": len(audit["loss_records"]),
            }
        if projected_task["contract_version"] in {"world-provider-task.v2", "world-provider-task.v3", "world-provider-task.v4"}:
            projection = projected_task["context_projection"]
            audit = {key: projection.pop(key) for key in ("policy", "rejections", "estimated_tokens", "token_accounting", "provider_admission", "task_workset") if key in projection}
            state_provenance = {}
            for index, item in enumerate(projection.get("selection", [])):
                state = item.get("state")
                if not isinstance(state, dict):
                    continue
                provenance = {key: state.pop(key) for key in (
                    "model_id", "provider_id", "extractor_type", "prompt_version",
                    "approval_resolution", "approval_requirement", "lifecycle_migration",
                ) if key in state}
                if provenance:
                    state_provenance[str(index)] = provenance
            if state_provenance:
                projection["state_provenance_receipt"] = {
                    "frozen_source_pointer": "/contract/context_projection/selection",
                    "audit_hash": _projection_hash(state_provenance),
                    "omitted_fields_by_index": {index: sorted(values) for index, values in state_provenance.items()},
                }
            if audit:
                projection["governance_receipt"] = {
                    "contract_version": "world-role-governance-receipt.v1",
                    "source_ref": projected_task["source_ref"], "audit_hash": _projection_hash(audit),
                    "context_digest": projected_task["projection_identity"],
                    "omitted_fields": sorted(audit),
                    "rejected_source_count": len(audit.get("rejections", [])),
                }
        for proposal in projected_task.get("actor_proposals", []):
            if "intent_plan" not in proposal or "intent_state" not in proposal:
                continue
            # WHY: The validated state contains the complete private plan plus acceptance status; deliver it once.
            plan = proposal.pop("intent_plan")
            state = proposal["intent_state"]
            if any(state.get(key) != value for key, value in plan.items() if key != "steps") or any(
                any(actual.get(key) != value and not (key in {"decision", "reason"} and expected.get("decision") == "PRESERVE" and actual.get("status") in {"COMPLETED", "ABANDONED"})
                    for key, value in expected.items())
                for expected, actual in zip(plan["steps"], state["steps"], strict=True)
            ):
                raise KernelError("WORLD_ACTOR_INTENT_PROJECTION_DRIFT", "Validated intent state must retain every field of its proposed plan")
            proposal["intent_plan_receipt"] = {"contract_version": "world-actor-intent-plan-reference.v1",
                "proposal_hash": proposal["proposal_hash"], "plan_hash": _projection_hash(plan),
                "equivalent_state_pointer": "/intent_state", "authority": "PROPOSAL_NOT_ACCEPTANCE",
                "proposed_step_dispositions": {step["step_id"]: {"decision": step["decision"], "reason": step["reason"]} for step in plan["steps"]}}
        if "narrative_intelligence" in projected_task:
            projected_task["narrative_intelligence"] = _project_selected_world_selection(projected_task["narrative_intelligence"])
        return _task(stage, world_preparation=_compact(projected_task))
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS, FOUNDATION_INPUT_ROLES, foundation_task

    if stage in FOUNDATION_GENERATORS:
        command = inputs.get("planning_command")
        frozen = inputs.get("frozen_inputs")
        task = inputs.get("foundation_task")
        if not isinstance(command, Mapping) or command.get("planning_scope") != "NOT_APPLICABLE" or not isinstance(frozen, list) or {item.get("role") for item in frozen if isinstance(item, Mapping)} != set(FOUNDATION_INPUT_ROLES[stage]) or task != foundation_task(stage, work_requirements=command.get("creative_requirements_contract") in {"work-requirements.v1", "work-requirements.v2"}, aligned_methods=command.get("creative_requirements_contract") == "work-requirements.v2", rfc6901_paths=command.get("execution_contract_version") in {"1.19.0", "1.21.0"}, narrative_search=command.get("execution_contract_version") == "1.21.0" and bool(command.get("narrative_search_id")), generated_title=command.get("generated_title_contract") == "generated-book-title.v1"):
            raise KernelError("FOUNDATION_PROVIDER_TASK_INVALID", "Foundation Provider task requires exact frozen roles and stage instructions")
        return _task(stage, planning_command=_compact(command), frozen_inputs=_compact(frozen), foundation_task=_compact(task), narrative_intelligence=_compact(inputs.get("narrative_intelligence")))
    if stage in _PLANNING_STAGES:
        command = inputs.get("planning_command")
        if not isinstance(command, Mapping):
            raise KernelError(
                "PLANNING_PROVIDER_TASK_VIEW_INVALID",
                "Planning Provider Task View requires the frozen planning command",
            )
        frozen_inputs = inputs.get("frozen_inputs")
        authoritative_load = inputs.get("authoritative_narrative_load")
        arc_working_set = inputs.get("arc_working_set")
        narrative_intelligence = inputs.get("narrative_intelligence")
        if not isinstance(frozen_inputs, list) or not frozen_inputs:
            raise KernelError(
                "PLANNING_PROVIDER_TASK_VIEW_INVALID",
                "Planning Provider Task View requires frozen input lineage",
            )
        if (
            not isinstance(authoritative_load, Mapping)
            or not isinstance(authoritative_load.get("narrative_load_policy"), Mapping)
            or not isinstance(
                authoritative_load.get("narrative_load_projection"), Mapping
            )
        ):
            raise KernelError(
                "PLANNING_PROVIDER_TASK_VIEW_INVALID",
                "Planning Provider Task View requires authoritative Narrative Load constraints",
            )
        if not isinstance(arc_working_set, Mapping):
            raise KernelError(
                "PLANNING_PROVIDER_TASK_VIEW_INVALID",
                "Planning Provider Task View requires the governed Arc Working Set",
            )
        selected_intelligence = (
            narrative_intelligence.get("selected")
            if isinstance(narrative_intelligence, Mapping)
            else None
        )
        intelligence_boundary = (
            narrative_intelligence.get("authority_boundary")
            if isinstance(narrative_intelligence, Mapping)
            else None
        )
        if (
            not isinstance(narrative_intelligence, Mapping)
            or narrative_intelligence.get("schema_version")
            != "mkaos-narrative-intelligence-selection.v1"
            or not isinstance(selected_intelligence, list)
            or len(selected_intelligence) > 12
            or not isinstance(intelligence_boundary, Mapping)
            or intelligence_boundary.get("semantic_role") != "POSSIBILITY_ONLY"
            or intelligence_boundary.get("may_mutate_story_authority") is not False
        ):
            raise KernelError(
                "PLANNING_PROVIDER_TASK_VIEW_INVALID",
                "Planning Provider Task View requires governed Narrative Intelligence possibilities",
            )
        from novel_forge.modules.mkaos_authority.craft_context_projection import project_planning_craft_histories
        projection_version = inputs.get("craft_history_projection_version")
        if projection_version not in (None, "planning-craft-history-projection.v1"):
            raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning history projection requires an explicitly supported frozen version")
        empty_query_version = inputs.get("planning_empty_query_projection_version")
        if empty_query_version not in (None, "planning-empty-query-projection.v1"):
            raise KernelError("PLANNING_EMPTY_SELECTION_DRIFT", "Empty Planning query projection requires its frozen version")
        projected_selection = _compact(_project_denied_planning_selection(
            narrative_intelligence, empty_query=empty_query_version is not None,
        ))
        if projection_version:
            projected_selection = project_planning_craft_histories(projected_selection)
        task = _task(
            stage,
            planning_command=_compact(command),
            world_preparation=_compact(inputs.get("world_preparation") or {}),
            frozen_inputs=_compact(frozen_inputs),
            authoritative_narrative_load=_compact(authoritative_load),
            arc_working_set=_compact(arc_working_set),
            narrative_intelligence=projected_selection,
        )
        if projection_version:
            task["contract_version"] = "provider-task-view-v2"
            task["craft_history_projection_version"] = projection_version
        continuity = _planning_working_continuity(inputs, command)
        if continuity is not None:
            task["working_continuity"] = continuity
        return task
    if stage == "narrative_semantic_evaluation":
        profiles = inputs.get("qualification_profiles")
        target = inputs.get("evaluation_target")
        if (
            not isinstance(profiles, list)
            or not profiles
            or not isinstance(target, Mapping)
        ):
            raise KernelError(
                "NARRATIVE_EVALUATION_PROVIDER_TASK_INVALID",
                "Semantic Evaluation requires frozen profiles and target lineage",
            )
        return _task(
            stage,
            evaluation_target=_compact(target),
            qualification_profiles=_compact(profiles),
        )
    if stage == "agent_session":
        boundary = inputs.get("accepted_boundary")
        tools = inputs.get("tools")
        if (
            not isinstance(boundary, Mapping)
            or not isinstance(tools, list)
            or not tools
        ):
            raise KernelError(
                "AGENT_PROVIDER_TASK_INVALID",
                "Agent turn requires a frozen accepted boundary and Tool snapshot",
            )
        return _task(
            stage,
            agent_session_id=str(inputs.get("agent_session_id") or ""),
            operation_id=str(inputs.get("operation_id") or ""),
            instruction=str(inputs.get("instruction") or ""),
            accepted_boundary=_compact(boundary),
            execution_contract_hash=str(inputs.get("execution_contract_hash") or ""),
            execution_contract_summary=_compact(
                inputs.get("execution_contract_summary")
            ),
            tools=_compact(tools),
            skills=_compact(inputs.get("skills")),
            active_skill_activations=_compact(inputs.get("active_skill_activations")),
            committed_transcript=_compact(inputs.get("committed_transcript")),
            observations=_compact(inputs.get("observations")),
            turn_number=int(inputs.get("turn_number") or 0),
        )
    if stage == "memo":
        from novel_forge.modules.canon_graph.background import without_private_world

        source = dict(inputs.get("execution_intent") or {})
        intent = {
            key: source[key]
            for key in (
                "project_id",
                "chapter",
                "contract_version",
                "intent_fingerprint",
                "source_chapter_plan",
                "accepted_boundary",
                "chapter_objective",
                "required_arc_contributions",
                "previous_ending",
                "scene_plans",
                "chapter_mission",
                "character_reference_contract",
                "working_manuscript",
                "character_situation",
                "required_beats",
                "craft_strategy",
                *(["creative_requirements"] if work_requirements else []),
            )
            if key in source
        }
        return _task(
            stage,
            frozen_intent=without_private_world(intent),
            authority="CREATIVE_SUGGESTION_ONLY",
            source_layers={
                "accepted_facts": "REFERENCED_BY_ACCEPTED_BOUNDARY",
                "character_knowledge": "SCENE_KNOWLEDGE_BOUNDARIES",
                "planned_outcomes": "INTENT_ONLY_NOT_OBSERVED",
                "creative_guidance": "CANDIDATE_SUGGESTIONS",
            },
        )
    if stage == "draft":
        from novel_forge.modules.canon_graph.background import without_private_world
        from novel_forge.modules.story_design_authority.author_input import without_author_private
        memo_view = {
            "guidance": deepcopy((inputs.get("chapter_memo") or {}).get("creative_guidance") or {}),
            "scene_directives": deepcopy((inputs.get("chapter_memo") or {}).get("scene_directives") or []),
            **({} if compact_contract else {
                "source_memo_fingerprint": str((inputs.get("chapter_memo") or {}).get("memo_fingerprint") or ""),
                **({"craft_strategy_digest": inputs["chapter_memo"]["craft_strategy"]["strategy_digest"]} if (inputs.get("chapter_memo") or {}).get("craft_strategy") else {}),
                "authority": "CREATIVE_SUGGESTION_ONLY",
            }),
        }
        realization = deepcopy(inputs.get("realization_contract"))
        return _task(
            stage,
            chapter_plan=_compact(without_private_world(without_author_private(inputs.get("plan")))),
            style=_compact(inputs.get("style")),
            creative_memo=memo_view,
            realization_contract=realization,
            **({"candidate_repair": deepcopy(inputs["candidate_repair"])} if inputs.get("candidate_repair") else {}),
        )
    if stage == "review":
        from novel_forge.modules.review.craft import craft_provider_task

        return _task(
            stage,
            **({"working_revision_request": deepcopy(inputs["working_revision_request"])} if inputs.get("working_revision_request") else {}),
            **craft_provider_task(inputs.get("draft") or {}),
            **_cross_chapter_task(inputs),
            chapter=_prose(inputs.get("draft")),
            **_realization_source_review(inputs.get("draft") or {}),
            creative_execution=deepcopy(
                (inputs.get("draft") or {}).get("creative_execution") or {}
            ),
            knowledge_review_targets=deepcopy(
                inputs.get("knowledge_review_targets") or []
            ),
            **({"review_knowledge_scope_contract": inputs["review_knowledge_scope_contract"]} if inputs.get("review_knowledge_scope_contract") else {}),
            **({"candidate_repair": deepcopy(inputs["candidate_repair"])} if inputs.get("candidate_repair") else {}),
            author_design_review_targets=deepcopy(
                inputs.get("author_design_review_targets") or {}
            ),
            **(
                {
                    "creative_baseline": deepcopy(
                        (inputs.get("draft") or {}).get("creative_baseline")
                    )
                }
                if work_requirements
                else {}
            ),
        )
    if stage == "revision":
        source = dict(inputs.get("draft") or {})
        payload: dict[str, Any] = {
            **({"working_revision_request": deepcopy(inputs["review"]["working_revision_request"])} if (inputs.get("review") or {}).get("working_revision_request") else {}),
            **({"chapter_length_repair_scope": {**deepcopy(inputs["chapter_length_repair_scope"]), "planning_target_han_characters":(inputs["chapter_length_repair_scope"]["minimum"]+inputs["chapter_length_repair_scope"]["maximum"])//2, "objective":"Aim within the range with margin rather than estimating a boundary. Correct measured length across the frozen scenes to the original bounds through consequential actions, interaction and sensory feedback. Preserve facts, voice and scene coverage. No padding, repetition, new plot or fabricated resolution."}} if inputs.get("chapter_length_repair_scope") else {}),
            **({"candidate_repair": deepcopy(inputs["candidate_repair"])} if inputs.get("candidate_repair") else {}),
            "chapter": _prose(source),
            "creative_execution": deepcopy(source.get("creative_execution") or {}),
            "knowledge_checks": deepcopy(
                (inputs.get("review") or {}).get("knowledge_checks") or []
            ),
        }
        if work_requirements:
            payload["creative_baseline"] = deepcopy(source.get("creative_baseline"))
        if source.get("author_design_guidance"):
            payload["author_design_review_targets"] = deepcopy(
                source["author_design_guidance"]
            )
        if source.get("realization_contract"):
            payload["chapter"].pop("text", None)
            payload["realization_contract"] = deepcopy(source["realization_contract"])
            payload["scene_artifacts"] = deepcopy(source["scene_artifacts"])
            if "scene_separators" in source:
                payload["scene_separators"] = list(source["scene_separators"])
            if not compact_contract:
                payload["composition_digest"] = source["composition_digest"]
        if inputs.get("required_actions") is not None:
            payload["required_actions"] = _compact(inputs.get("required_actions"))
            payload["quality_decision"] = _compact(inputs.get("quality"))
            if inputs.get("quality_edit_contract") is not None:
                observations = {
                    item.get("observation") for item in inputs["required_actions"]
                }
                decision = inputs.get("quality") or {}
                payload["quality_decision"] = {
                    "gate": decision.get("gate"),
                    "blocking_dimensions": decision.get("blocking_dimensions", []),
                    "required_actions": deepcopy(decision.get("required_actions", [])),
                    "evidence_reports": [
                        deepcopy(item)
                        for item in decision.get("evidence_reports", [])
                        if item.get("dimension") in observations
                    ],
                }
                payload["quality_targeted_repair"] = deepcopy(
                    inputs["quality_edit_contract"]
                )
                if not compact_contract:
                    payload["chapter"]["text"] = str(source.get("text") or "")
        else:
            from novel_forge.modules.review.diagnostics import prose_repair_diagnoses

            diagnoses = prose_repair_diagnoses(dict(inputs.get("review") or {}), work_requirements=work_requirements)
            payload["review_issues"] = (
                [
                    {
                        key: issue[key]
                        for key in (
                            "code",
                            "severity",
                            "category",
                            "judgment_kind",
                            "revision_goal",
                            "preserve",
                            "acceptance_criteria",
                        )
                        if key in issue
                    }
                    | {
                        "evidence_quote": str(
                            (issue.get("evidence_locator") or {}).get("quote") or ""
                        )
                    }
                    for issue in diagnoses
                ]
                if compact_contract
                else _compact(diagnoses)
            )
            if (source.get("realization_contract") or {}).get(
                "contract_version"
            ) in {"scene-realization-composition.v2", "scene-realization-composition.v3"}:
                payload["targeted_editing"] = {
                    "mode": "DIAGNOSIS_DIRECTED_ONLY",
                    "tasks": [
                        {
                            key: issue[key]
                            for key in (
                                "code",
                                "category",
                                "judgment_kind",
                                "evidence_locator",
                                "revision_goal",
                                "preserve",
                                "acceptance_criteria",
                            )
                            if key in issue
                        }
                        for issue in diagnoses
                    ],
                    "instructions": "Repair each evidenced problem using its stated criterion. Keep unaffected choices, information boundaries, and voice. An aesthetic suggestion is optional; unknown or unresolved blockers remain open. Read adjacent passages for continuity after a local edit.",
                }
        review = dict(inputs.get("review") or {})
        if inputs.get("required_actions") is not None and review:
            payload["review_preservation_context"] = {
                "contract_version": "quality-correction-review-preservation.v1",
                "cross_chapter_window": deepcopy(review.get("cross_chapter_window")),
                "prior_diagnoses": deepcopy(
                    review.get("issues", []) + review.get("unresolved_issues", [])
                ),
                "craft_targets": deepcopy(review.get("craft_targets", [])),
                "craft_checks": deepcopy(review.get("craft_checks", [])),
                "knowledge_checks": deepcopy(review.get("knowledge_checks", [])),
                "instructions": (
                    "Correct only the frozen Quality tasks. Return exact old quotes, replacements and issue codes; the host derives Slot prose. Accepted history is read-only. Preserve adopted Craft, resolved diagnoses, voice, facts and information boundaries. The same historical window and before/after comparison are reviewed again before any acceptance."
                    if targeted_edits_only
                    else "Correct only the frozen Quality tasks. Accepted history is read-only. Preserve adopted Craft, resolved diagnoses, voice, facts and information boundaries. Return exact scene artifacts consistent with prose; the same historical window and before/after comparison are reviewed again before any acceptance."
                ),
            }
        if (
            review.get("cross_chapter_window")
            and inputs.get("required_actions") is None
        ):
            payload["targeted_repair"] = {
                "contract_version": "cross-chapter-targeted-repair.v1",
                "source_window_hash": review["cross_chapter_window"][
                    "source_window_hash"
                ],
                ("selected_source_window" if review["cross_chapter_window"].get("source_isolation") == "SELECTED_PROSE_NO_CANON_AUTHORITY" else "accepted_source_window"): deepcopy(review["cross_chapter_window"]),
                "preservation_requirements": deepcopy(
                    review["cross_chapter_window"]["preservation_requirements"]
                ),
                "instructions": (
                    "Return ordered non-overlapping edits inside diagnosed target spans, their exact old quote, replacement and issue_codes. The host verifies that the joined Scene Slot prose equals applying those edits. Historical support is read-only. Keep other prose byte-for-byte. Do not mechanically paraphrase intentional repetition."
                    if compact_contract and not targeted_edits_only
                    else "Return ordered non-overlapping edits inside diagnosed target spans, their exact old quote, replacement and issue_codes. The host derives revised Slot prose from these edits. Historical support is read-only. Keep other prose byte-for-byte. Do not mechanically paraphrase intentional repetition."
                    if targeted_edits_only
                    else "Return ordered non-overlapping edits inside diagnosed target spans, their exact old quote, replacement and issue_codes. Return text equal to applying those edits only. Historical support is read-only. Keep other prose byte-for-byte. Do not mechanically paraphrase intentional repetition."
                ),
            }
            requested = review.get("working_revision_request") or {}
            if (work_requirements and requested.get("contract_version") == "chapter-working-revision.v1"
                    and isinstance(requested.get("reason"), str) and bool(requested["reason"].strip())
                    and requested.get("source_asset_version_id") == review.get("target_asset_version_id")):
                payload["targeted_repair"]["scope_policy"] = "ANCHORED_SCOPE_PROPOSAL_V1"
                payload["targeted_repair"]["instructions"] = (
                    "Return ordered non-overlapping edits with exact old quotes, replacements and issue_codes. "
                    "Each edit must intersect every named prose diagnosis anchor. A wider local edit is a scope proposal, "
                    "not validated permission: preserve unrelated paragraphs and frozen commitments. The host derives "
                    "the complete text and requires exact-source ReReview preservation before downstream use. "
                    "Plan-owned investigations do not authorize prose edits. Keep all other text byte-for-byte."
                )
            if not compact_contract:
                payload["chapter"]["text"] = str(source.get("text") or "")
        if review.get("craft_targets") and inputs.get("required_actions") is None:
            from novel_forge.modules.review.craft import craft_revision_contract

            payload["craft_targeted_repair"] = craft_revision_contract(
                source,
                review,
                compact_contract=compact_contract,
                targeted_edits_only=targeted_edits_only and project_methods,
            )
            payload["craft_checks"] = deepcopy(review["craft_checks"])
            if not compact_contract:
                payload["chapter"]["text"] = str(source.get("text") or "")
        if instruction_cleanup:
            if payload.get("targeted_editing"):
                fields = (
                    "code",
                    "severity",
                    "category",
                    "judgment_kind",
                    "evidence_locator",
                    "revision_goal",
                    "preserve",
                    "acceptance_criteria",
                )
                payload["review_issues"] = [
                    {key: issue[key] for key in fields if key in issue}
                    for issue in diagnoses
                ]
                payload["targeted_editing"].pop("tasks", None)
                payload["targeted_editing"]["diagnosis_codes"] = [
                    issue["code"] for issue in diagnoses
                ]
            decision = payload.get("quality_decision")
            if isinstance(decision, dict) and decision.get(
                "required_actions"
            ) == payload.get("required_actions"):
                decision.pop("required_actions", None)
                decision["required_action_source"] = "required_actions"
            preservation = payload.get("review_preservation_context")
            if isinstance(preservation, dict) and preservation.get(
                "knowledge_checks"
            ) == payload.get("knowledge_checks"):
                preservation.pop("knowledge_checks", None)
                preservation["knowledge_check_source"] = "knowledge_checks"
        return _task(stage, **payload)
    if stage == "rereview":
        from novel_forge.modules.review.craft import craft_provider_task
        from novel_forge.modules.review.diagnostics import open_diagnoses
        from novel_forge.modules.review.prose_comparison import prose_comparison, prose_comparison_view

        revision = inputs.get("revision") or inputs.get("draft")
        issues = [
            _compact(item) for item in open_diagnoses(dict(inputs.get("review") or {}))
        ]
        return _task(
            stage,
            **({"working_revision_request": deepcopy(inputs["working_revision_request"])} if inputs.get("working_revision_request") else {}),
            **craft_provider_task(revision or {}, inputs.get("review") or {}),
            **_cross_chapter_task(inputs),
            revised_chapter=_prose(revision),
            **({"prose_scope_reassessment": {"proposal": deepcopy(revision["prose_scope_proposal"]),
                "instructions": "Assess each proposed expanded finding against the complete before/after prose. "
                    "Verify unrelated paragraphs, frozen commitments and character/knowledge/voice boundaries. "
                    "Preservation is not the same as complete resolution: keep partial or uncertain issues explicit. "
                    "Uncertainty in unchanged prose remains unresolved; it is not by itself a new preservation regression."}}
               if (revision or {}).get("prose_scope_proposal") else {}),
            **_realization_source_review(revision or {}),
            **(
                {
                    "creative_baseline": deepcopy(
                        (revision or {}).get("creative_baseline")
                    )
                }
                if work_requirements
                else {}
            ),
            **(
                {
                    "quality_action_reassessment": {
                        "source_edit_contract": deepcopy(
                            revision["quality_edit_contract"]
                        ),
                        "observations": deepcopy(
                            revision["quality_action_observations"]
                        ),
                        "instructions": "Return a separate quality_resolution_checks entry for every frozen Quality observation. Cite exact revised prose and explicitly assess preservation. Do not fabricate a Review issue or treat an increased score as resolving Quality. This is model evidence; native Quality gates must reevaluate before acceptance.",
                    }
                }
                if (revision or {}).get("quality_edit_contract")
                else {}
            ),
            **(
                {
                    "prose_comparison": (prose_comparison_view if compact_contract else prose_comparison)(
                        inputs["original_draft"],
                        revision or {},
                        original_id=str(
                            inputs.get("original_draft_asset_version_id")
                            or (inputs.get("review") or {}).get(
                                "target_asset_version_id"
                            )
                            or ""
                        ),
                        revised_id=str(
                            inputs.get("target_candidate_asset_version_id")
                            or (revision or {}).get("asset_version_id")
                            or ""
                        ),
                    )
                }
                if "original_draft_asset_version_id" in inputs
                else {}
            ),
            creative_execution=deepcopy(
                (revision or {}).get("creative_execution") or {}
            ),
            prior_diagnoses=issues,
            knowledge_review_targets=deepcopy(
                inputs.get("knowledge_review_targets") or []
            ),
            **({"review_knowledge_scope_contract": inputs["review_knowledge_scope_contract"]} if inputs.get("review_knowledge_scope_contract") else {}),
            **({"candidate_repair": deepcopy(inputs["candidate_repair"])} if inputs.get("candidate_repair") else {}),
            author_design_review_targets=deepcopy(
                inputs.get("author_design_review_targets") or {}
            ),
        )
    if stage == "canon_support":
        task = _task(stage, final_candidate=_prose(inputs.get("revision")),
                     grounding=deepcopy(inputs.get("grounding")), claims=deepcopy(inputs.get("claims")))
        if inputs.get("realization_comparison") is not None:
            task["realization_comparison"] = deepcopy(inputs["realization_comparison"])
        comparisons = [item["claim"]["actor_step_execution"] for item in inputs.get("claims") or []
                       if isinstance(item, Mapping) and isinstance(item.get("claim"), Mapping) and "actor_step_execution" in item["claim"]]
        if comparisons:
            if any(not isinstance(item, Mapping) or item.get("contract_version") != "actor-step-execution-comparison.v1" for item in comparisons):
                raise KernelError("WORLD_ACTOR_EXECUTION_CONTRACT_INVALID", "Canon support requires an explicit current-step comparison contract")
            task["contract_version"] = "provider-task-view-v2"
            task["actor_step_support_contract"] = "actor-step-execution-comparison.v1"
        return task
    if stage == "canon_extraction":
        from novel_forge.modules.canon_graph.background import without_private_world
        return _task(
            stage,
            final_candidate=_prose(inputs.get("revision")),
            execution_expectations=_compact(without_private_world(inputs.get("execution_expectations"))),
        )
    if stage.startswith("quality_"):
        return _task(
            stage,
            chapter=_prose(inputs.get("revision")),
            quality_context=_compact(inputs.get("quality_context")),
            dimensions=_compact(inputs.get("dimensions")),
        )
    if stage in {"screenplay_generate", "screenplay_review", "screenplay_revision"}:
        return _task(stage, source_digest=inputs.get("source_digest"), candidate_digest=inputs.get("candidate_digest", ""),
                     **({"screenplay_source_contract": inputs["screenplay_source_contract"]} if inputs.get("screenplay_source_contract") else {}))
    if stage == "longform_prose_review":
        return _task(stage, manifest_digest=inputs.get("manifest_digest"), window_id=inputs.get("window_id"),
                     **({"prose_diagnosis_contract": inputs["prose_diagnosis_contract"]} if inputs.get("prose_diagnosis_contract") else {}))
    if stage == "reader_outcome":
        return _task(
            stage,
            chapter=int(inputs.get("chapter") or 0),
            book_id=str(inputs.get("book_id") or ""),
            reader_contract_version=str(inputs.get("reader_contract_version") or ""),
            evaluation_profile_version=str(
                inputs.get("evaluation_profile_version") or ""
            ),
            reader_judge_execution_snapshot=_compact(
                inputs.get("reader_judge_execution_snapshot")
            ),
        )
    raise KernelError(
        "CHAPTER_PROVIDER_TASK_VIEW_UNSUPPORTED",
        f"Provider Task View is not defined for stage {stage}",
    )


def build_task_narrative_projection(plan: Mapping[str, Any], *, task_scoped: bool = False) -> dict[str, Any]:

    characters: set[str] = set()
    arcs: set[str] = set()
    facts: set[str] = set()
    beliefs: set[str] = set()
    disclosures: set[str] = set()
    state_entities: set[str] = set()
    obligations: set[str] = set()
    world_rules: set[str] = set()
    character_development: list[dict[str, Any]] = []
    for item in plan.get("character_participation") or ():
        if not isinstance(item, Mapping):
            continue
        characters.add(str(item.get("character_id") or ""))
        arcs.update(str(value) for value in item.get("trajectory_refs") or ())
        facts.update(str(value) for value in item.get("known_fact_ids") or ())
        facts.update(str(value) for value in item.get("unknown_fact_ids") or ())
        beliefs.update(str(value) for value in item.get("belief_refs") or ())
        character_development.append(
            {
                key: deepcopy(item.get(key))
                for key in (
                    "character_id",
                    "trajectory_refs",
                    "causal_trigger",
                    "entry_emotion",
                    "exit_emotion",
                    "resource_changes",
                    "relationship_changes",
                    "expected_change",
                )
                if item.get(key) not in (None, "", [])
            }
        )
    for item in plan.get("cast") or ():
        characters.add(
            str(item.get("character_id") or item.get("id") or "")
            if isinstance(item, Mapping)
            else str(item)
        )
    for item in plan.get("arc_schedule") or ():
        if isinstance(item, Mapping):
            arcs.update(
                str(item.get(key) or "")
                for key in ("arc_plan_version_id", "segment_id")
            )
    for item in plan.get("knowledge_boundaries") or ():
        if isinstance(item, Mapping):
            if str(item.get("layer") or "").upper() in {
                "CHARACTER_KNOWLEDGE",
                "CHARACTER_BELIEF",
            }:
                characters.add(str(item.get("subject_id") or ""))
            facts.add(str(item.get("fact_id") or item.get("proposition_id") or ""))
    for item in plan.get("disclosures") or ():
        if isinstance(item, Mapping):
            disclosures.add(str(item.get("disclosure_id") or ""))
            facts.add(str(item.get("fact_id") or item.get("proposition_id") or ""))
    for item in plan.get("required_state_transitions") or ():
        if isinstance(item, Mapping):
            state_entities.add(str(item.get("entity_key") or ""))
    for field in ("setups", "payoffs"):
        for item in plan.get(field) or ():
            if isinstance(item, Mapping):
                obligations.add(str(item.get("obligation_id") or ""))
    for item in plan.get("world_rule_usages") or ():
        if isinstance(item, Mapping):
            world_rules.add(str(item.get("rule_id") or ""))
    segment_ref = dict(plan.get("narrative_segment_ref") or {})

    def clean(values: set[str]) -> list[str]:
        return sorted(value for value in values if value)

    scoped_world = (plan.get("constraint_envelope") or {}).get(
        "world_preparation", {}
    ).get("action", {}).get("contract_version") == "world-production-action.v2"
    return {
        "contract_version": "chapter-task-narrative-projection-v2" if task_scoped else "chapter-task-narrative-projection-v1",
        **({"required_event_refs": sorted(str(value) for value in plan.get("required_long_distance_fact_ids") or ()), "policy_version": "task-scoped-context.v1"} if task_scoped else {}),
        "chapter": int(plan["chapter"]),
        "narrative_segment_ref": {
            key: str(segment_ref.get(key) or "")
            for key in ("volume_plan_version_id", "segment_id")
            if segment_ref.get(key)
        },
        "authorized_epistemic_fact_refs": []
        if scoped_world
        else sorted(provider_accessible_fact_ids(plan)),
        **(
            {"scene_epistemic_scopes": _scene_epistemic_scopes(plan)}
            if scoped_world
            else {}
        ),
        "character_ids": clean(characters),
        "arc_refs": clean(arcs),
        "fact_refs": clean(facts),
        "belief_refs": clean(beliefs),
        "disclosure_refs": clean(disclosures),
        **(
            {"disclosure_field_projections": _world_disclosure_field_projections(plan)}
            if (plan.get("constraint_envelope") or {})
            .get("world_preparation", {})
            .get("action", {})
            .get("contract_version")
            == "world-production-action.v2"
            else {}
        ),
        "authorized_disclosure_fact_refs": sorted(
            {
                str(item["fact_id"])
                for item in plan.get("disclosures") or ()
                if isinstance(item, Mapping)
                and item.get("fact_id")
                and str(item.get("audience") or "").upper() in {"READER", "ALL"}
                and str(item.get("mode") or "").upper()
                in {"HINT", "PARTIAL", "MISDIRECT", "CONFIRM"}
            }
        ),
        "state_entity_refs": clean(state_entities),
        "obligation_refs": clean(obligations),
        "world_rule_refs": clean(world_rules),
        "character_development": character_development,
    }


def _world_disclosure_field_projections(plan: Mapping[str, Any]) -> dict[str, Any]:
    binding = (plan.get("constraint_envelope") or {}).get("world_preparation") or {}
    action = binding.get("action") or {}
    if action.get("contract_version") != "world-production-action.v2":
        return {}
    result = {}
    for disclosure in action["world_plan"].get("disclosure_projection", []):
        if disclosure["audience"] != "READER" or disclosure["mode"] == "WITHHOLD":
            continue
        entry = result.setdefault(disclosure["fact_id"], {"state": {}})
        entry["state"].update(disclosure["source"]["state"])
    return result


def provider_accessible_fact_ids(plan: Mapping[str, Any]) -> set[str]:
    boundaries = [{str(fact) for fact in scene.get("accessible_knowledge") or () if str(fact)} for scene in plan.get("scene_plan") or () if isinstance(scene, Mapping) and str(scene.get("focalization") or "") != "OMNISCIENT"]
    accessible = set.intersection(*boundaries) if boundaries else set()
    accessible.update(str(item["fact_id"]) for item in plan.get("disclosures") or () if isinstance(item, Mapping) and item.get("fact_id") and str(item.get("audience") or "").upper() in {"READER", "ALL"} and str(item.get("mode") or "").upper() != "WITHHOLD")
    return accessible


def project_narrative_state_facts(
    facts: Iterable[Mapping[str, Any]],
    *,
    projection: Mapping[str, Any],
    chapter: int,
) -> list[dict[str, Any]]:

    authorized_disclosures = set(
        projection.get("authorized_disclosure_fact_refs") or ()
    )
    from novel_forge.modules.narrative_state.information import (
        disclosed_fact_projection,
    )

    materialized = [
        disclosed_fact_projection(item)
        for item in facts
        if not (
            ((item.get("state") or {}).get("fact_origin") or {}).get("kind")
            in {"GOVERNED_BACKGROUND", "GOVERNED_PREPARATION"}
            and str(item.get("source_event_id") or "") not in authorized_disclosures
        )
    ]
    field_projections = projection.get("disclosure_field_projections") or {}
    materialized = [
        {**item, "state": deepcopy(field_projections[item["source_event_id"]]["state"])}
        if item.get("source_event_id") in field_projections
        else item
        for item in materialized
    ]
    if projection.get("contract_version") in {"chapter-task-narrative-projection-v1", "chapter-task-narrative-projection-v2"}:
        accessible = set(projection.get("authorized_epistemic_fact_refs") or ())
        scoped = projection.get("scene_epistemic_scopes")
        projected = []
        for item in materialized:
            if item.get("state_kind") not in {
                "character_knowledge",
                "character_belief",
            }:
                projected.append(item)
                continue
            fact = str(
                (item.get("state") or {}).get("fact_id")
                or (item.get("state") or {}).get("proposition_id")
                or ""
            )
            actor = str((item.get("state") or {}).get("character_id") or "")
            if scoped is None:
                if fact in accessible:
                    projected.append(item)
                continue
            scenes = sorted(
                row["scene_id"]
                for row in scoped
                if fact in row["character_fact_refs"].get(actor, [])
            )
            if scenes:
                projected.append(
                    {
                        **item,
                        "presentation_scope": {
                            "scene_ids": scenes,
                            "character_id": actor,
                        },
                    }
                )
        materialized = projected
    selectors = _selectors(projection, {})
    if projection.get("contract_version") == "chapter-task-narrative-projection-v2":
        from novel_forge.modules.context_builder.task_context import project_task_state_facts
        return project_task_state_facts(materialized, projection=projection, chapter=chapter)
    if not selectors:
        if len(materialized) <= _MAX_FACTS_PER_SEGMENT:
            return deepcopy(materialized)
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_PROJECTION_REQUIRED",
            "long-history Narrative State requires typed Chapter execution selectors",
        )
    selected = [
        item for item in materialized if _state_fact_relevant(item, selectors, chapter)
    ]
    if projection.get("contract_version") != "chapter-task-narrative-projection-v2" and len(selected) > _MAX_FACTS_PER_SEGMENT:
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
            "Chapter execution selectors resolve more than the bounded fact limit",
        )
    return deepcopy(selected)


def project_retrieved_state_context(content: Mapping[str, Any], *, projection: Mapping[str, Any], chapter: int) -> dict[str, Any]:
    facts = list(content.get("structured_facts") or [])
    if not any(isinstance(item, Mapping) and item.get("state_kind") for item in facts):
        return dict(content)
    state_facts = [item for item in facts if item.get("state_kind")]
    metadata = [item for item in facts if not item.get("state_kind")]
    filtered = project_narrative_state_facts(state_facts, projection=projection, chapter=chapter)
    return {**content, "structured_facts": [*filtered, *metadata], "safe_summary": "Governed accepted state projection at the frozen chapter boundary.", "omitted_state_fact_count": len(state_facts) - len(filtered)}


def _validate_memo_realization_reference(raw, segments):
    from novel_forge.modules.narrative_state.reality import narrative_hash

    try:
        memo = json.loads(raw.get("safe_summary") or "{}")
    except (ValueError, TypeError):
        return
    reference = memo.get("narrative_realization_reference") if isinstance(memo, dict) else None
    if reference is None:
        return
    if not isinstance(reference, Mapping):
        raise KernelError("MEMO_REALIZATION_REFERENCE_DRIFT", "Realization reference must be an exact source binding")
    sources = [item for item in segments if isinstance(item, Mapping)
               and item.get("asset_type") == "chapter_execution_intent"
               and item.get("asset_version_id") == reference.get("asset_version_id")]
    if len(sources) != 1 or reference.get("json_pointer") != "/chapter_mission/narrative_realization":
        raise KernelError("MEMO_REALIZATION_REFERENCE_DRIFT", "Require one exact protected Intent source")
    try:
        source = json.loads(sources[0].get("safe_summary") or "{}")
        realization = source["chapter_mission"]["narrative_realization"]
    except (ValueError, TypeError, KeyError) as exc:
        raise KernelError("MEMO_REALIZATION_REFERENCE_DRIFT", "Referenced Mission is missing") from exc
    if reference.get("content_hash") != narrative_hash(realization):
        raise KernelError("MEMO_REALIZATION_REFERENCE_DRIFT", "Referenced Mission content changed")


def build_provider_context_view(
    stage: str,
    context_bundle: Mapping[str, Any],
    task_view: Mapping[str, Any],
    *, clean_writer_context: bool = False, writer_projection_version: str = "",
) -> dict[str, Any]:

    if stage in {"model_reference_evaluate", "model_reference_adjudicate"}:
        from novel_forge.modules.command_kernel.routing_bootstrap import validate_model_reference_creation_binding

        frozen = task_view.get("model_reference")
        validate_model_reference_creation_binding(frozen)
        if (context_bundle.get("model_reference") != frozen
            or context_bundle.get("source_isolation") != "FROZEN_MODEL_REFERENCE_ONLY"):
            raise KernelError("MODEL_REFERENCE_CONTEXT_DRIFT", "Provider Context differs from frozen reference task")
        view = context_bundle.get("provider_context_view")
        if not isinstance(view, Mapping) or view.get("source_isolation") != "FROZEN_MODEL_REFERENCE_ONLY":
            raise KernelError("MODEL_REFERENCE_CONTEXT_DRIFT", "Provider Context projection is missing")
        return deepcopy(dict(view))

    if stage in {"context_compress", "context_fidelity"}:
        from .context_compression_provider import compression_boundary_identity

        if (
            compression_boundary_identity(context_bundle.get("accepted_boundary") or {})
            != compression_boundary_identity(task_view.get("accepted_boundary") or {})
            or str(context_bundle.get("memo_fingerprint") or "") != str(task_view.get("memo_fingerprint") or "")
        ):
            raise KernelError("CONTEXT_COMPRESSION_BOUNDARY_DRIFT", "compression must use the frozen Memo boundary")
        return {
            "contract_version": "provider-context-view-v4", "stage": stage,
            "accepted_boundary": deepcopy(context_bundle["accepted_boundary"]),
            "memo_fingerprint": context_bundle["memo_fingerprint"],
            "source_isolation": "FROZEN_TASK_CHUNK_ONLY", "protected": True,
        }
    if stage == "memo":
        intent = task_view.get("frozen_intent") or {}
        if intent.get("intent_fingerprint") != context_bundle.get("intent_fingerprint"):
            raise KernelError("CHAPTER_MEMO_INTENT_DRIFT", "Memo Context differs from frozen Intent")
        if context_bundle.get("working_manuscript") is not None:
            from novel_forge.modules.book_authority.working_prose import validate_working_projection
            validate_working_projection(context_bundle["working_manuscript"], project_id=context_bundle["project_id"],
                book_id=context_bundle.get("book_id"), target_chapter=context_bundle["chapter"],
                accepted_through_chapter=context_bundle["accepted_boundary"]["accepted_through_chapter"])
            if intent.get("working_manuscript") != context_bundle["working_manuscript"] or intent.get("character_situation") != context_bundle.get("character_situation"):
                raise KernelError("CHAPTER_MEMO_INTENT_DRIFT", "Memo must consume the exact working projection and character situation")
        return {"contract_version": "provider-context-view-v2", "stage": stage,
                "accepted_boundary": deepcopy(context_bundle.get("accepted_boundary")),
                "source_isolation": "FROZEN_INTENT_ONLY", "protected": True}
    if stage == "retrieval_query_expansion":
        boundary = context_bundle.get("accepted_boundary")
        if (
            not isinstance(boundary, Mapping)
            or dict(boundary) != dict(task_view.get("accepted_boundary") or {})
            or str(context_bundle.get("memo_fingerprint") or "")
            != str(task_view.get("memo_fingerprint") or "")
        ):
            raise KernelError(
                "RETRIEVAL_EXPANSION_PROVIDER_CONTEXT_INVALID",
                "query expansion context must be the exact frozen ChapterMemo boundary",
            )
        return {
            "contract_version": "provider-context-view-v2",
            "schema_version": "novelos.retrieval_expansion_context.v1",
            "stage": stage,
            "source_isolation": "FROZEN_MISSION_MEMO_COVERAGE_ONLY",
            "accepted_boundary": _compact(boundary),
            "memo_fingerprint": str(context_bundle.get("memo_fingerprint") or ""),
            "protected": True,
        }
    if stage == "retrieval":
        return {
            "contract_version": "provider-context-view-v2",
            "schema_version": "novelos.retrieval_input_context.v1",
            "stage": stage,
            "source_isolation": "FROZEN_RETRIEVAL_TEXT_ONLY",
            "protected": True,
            "query_plan_fingerprint": str(
                task_view.get("query_plan_fingerprint") or ""
            ),
        }
    if stage in {"world_candidates.generate", "world_candidates.evaluate", "world_candidates.actor_0", "world_candidates.actor_1", "world_candidates.actor_2"}:
        task = task_view.get("world_preparation") or {}
        task_capacity = dict(task.get("policy") or {}).get("version") == "world-production-policy.v4"
        if context_bundle.get("world_preparation") != task:
            raise KernelError(
                "WORLD_CONTEXT_IDENTITY_MISMATCH",
                "world task differs from its frozen role Context",
            )
        selection = task.get("narrative_intelligence") or {}
        if selection.get("world_selection_receipt") is not None:
            original = context_bundle.get("narrative_intelligence")
            if not isinstance(original, Mapping) or selection != _compact(_project_selected_world_selection(original)):
                raise KernelError("WORLD_SELECTION_RECEIPT_DRIFT", "Selected World knowledge must resolve to the complete immutable selection")
        if (selection.get("need") or {}).get("condition_sources_receipt") is not None:
            original = context_bundle.get("narrative_intelligence")
            policy = original.get("knowledge_access_policy") if isinstance(original, Mapping) else None
            if (not isinstance(original, Mapping) or not isinstance(policy, Mapping)
                or policy.get("project_id") != context_bundle["project_id"]
                or policy.get("book_id") != context_bundle["book_id"]
                or selection != _compact(_project_empty_world_selection(original,
                    project_query_directory=(selection.get("need") or {}).get("query_directory_receipt") is not None))):
                raise KernelError("WORLD_SELECTION_RECEIPT_DRIFT", "World source omission must resolve to its exact complete selection in the frozen Context")
        view = {
            "contract_version": "provider-context-view-v2",
            "stage": stage,
            "source_isolation": "FROZEN_WORLD_ROLE_PROJECTION_ONLY",
            "protected": True,
            "accepted_state_boundary": {
                "project_id": context_bundle["project_id"],
                "book_id": context_bundle["book_id"],
                "accepted_through_chapter": task["accepted_through_chapter"],
                "baseline_id": task["baseline_id"],
                "baseline_kind": task["baseline_kind"],
            },
            "segments": [
                {
                    "asset_version_id": task["source_ref"]["asset_version_id"],
                    "role": task["role"],
                    "content": {
                        "source_ref": task["source_ref"],
                        "context_projection_hash": task["projection_identity"],
                    },
                }
            ],
        }
        author = context_bundle.get("author_design_projection") if task.get("role") != "ACTOR" else None
        if author is not None:
            chapter = _planning_chapter(context_bundle)
            fragments = author.get("fragments") if isinstance(author, Mapping) else None
            if (
                not isinstance(author, Mapping)
                or set(author) != {"contract_version", "target", "brief_asset_version_id", "brief_content_hash", "design_version", "binding_digest", "evidence_class", "authority", "chapter_range", "fragments", "exclusions"}
                or author.get("contract_version") != "author-design-projection.v1"
                or author.get("target") != "CHAPTER"
                or author.get("authority") != "AUTHOR_INTENT_NOT_CANON"
                or chapter != int(task["accepted_through_chapter"]) + 1
                or author.get("chapter_range") != [chapter, chapter]
                or not isinstance(fragments, list)
                or not all(
                    isinstance(item, Mapping)
                    and set(item) == {"fragment_id", "source_path", "start", "end", "content_hash", "targets", "chapter_range", "visibility", "strength", "text", "source_document_hash"}
                    and item.get("visibility") == "SCENE_INTENT"
                    and "CHAPTER" in (item.get("targets") or [])
                    and isinstance(item.get("chapter_range"), list)
                    and len(item["chapter_range"]) == 2
                    and all(type(value) is int for value in item["chapter_range"])
                    and item["chapter_range"][0] <= chapter <= item["chapter_range"][1]
                    and isinstance(item.get("text"), str)
                    and "sha256:" + hashlib.sha256(item["text"].encode("utf-8")).hexdigest() == item.get("content_hash")
                    for item in fragments
                )
                or not isinstance(author.get("exclusions"), list)
                or not all(isinstance(item, Mapping) and set(item) == {"fragment_id", "content_hash", "reason"} for item in author["exclusions"])
            ):
                raise KernelError(
                    "WORLD_AUTHOR_CONTEXT_INVALID",
                    "World preparation requires exact current-chapter scene intent, without private author sources",
                )
            from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
            view["author_design_projection"] = compile_provider_author_projection(author)
            token_budget = context_bundle.get("token_budget")
            if type(token_budget) is not int or token_budget <= 0:
                raise KernelError("WORLD_PROVIDER_CONTEXT_BUDGET_INVALID", "World author context requires its frozen token budget")
            if not task_capacity and _serialized_character_count(view) > min(_MAX_PROVIDER_CONTEXT_CHARACTERS, token_budget * 4):
                raise KernelError("WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "Protected World author context exceeds its frozen budget; narrow the governed scope")
        if task_capacity:
            token_budget = context_bundle.get("token_budget")
            if type(token_budget) is not int or not 0 < token_budget <= 512_000 or token_budget != task["policy"].get("context_token_budget"):
                raise KernelError("WORLD_PROVIDER_CONTEXT_BUDGET_INVALID", "World task capacity requires its exact frozen token budget")
            view["contract_version"] = "provider-context-view-v4"
            view["capacity_policy"] = {"version": "world-production-policy.v4", "task_target_tokens": token_budget,
                                       "token_accounting": "utf8-byte-upper-bound.v1", "maximum_serialized_bytes": _TASK_PROVIDER_SERIALIZATION_BYTES}
            measured = _serialized_byte_count(view)
            if measured > _TASK_PROVIDER_SERIALIZATION_BYTES or measured > token_budget:
                raise KernelError("WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "Required World Provider view exceeds its serialized byte guard or conservative task token budget")
        frozen = (context_bundle.get("context_manifest") or {}).get("provider_context_view")
        if isinstance(frozen, Mapping) and isinstance(frozen.get("compiled_view"), Mapping) and frozen["compiled_view"].get("stage") == stage:
            if frozen["compiled_view"] != view or frozen.get("content_hash") != _projection_hash(view) or frozen.get("source_input_hash") != planning_context_source_hash(context_bundle):
                raise KernelError("WORLD_CONTEXT_IDENTITY_MISMATCH", "World Provider view differs from its frozen semantic inputs and projection receipt")
        return view
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS

    if stage in _PLANNING_STAGES or stage in FOUNDATION_GENERATORS:
        continuity = _planning_working_continuity(context_bundle, context_bundle)
        if task_view.get("working_continuity") != continuity:
            raise KernelError("PLANNING_WORKING_CONTINUITY_DRIFT", "Planning task and Context must bind the same selected working prefix")
        projected_selection = task_view.get("narrative_intelligence", {})
        projection_version = context_bundle.get("craft_history_projection_version")
        if projection_version or task_view.get("craft_history_projection_version") or "planning_history_projection" in projected_selection:
            from novel_forge.modules.mkaos_authority.craft_context_projection import project_planning_craft_histories
            expected = project_planning_craft_histories(_compact(_project_denied_planning_selection(context_bundle.get("narrative_intelligence", {}))))
            if (projection_version != "planning-craft-history-projection.v1"
                or task_view.get("craft_history_projection_version") != projection_version
                or projected_selection != expected):
                raise KernelError("CRAFT_CONTEXT_PROJECTION_DRIFT", "Planning task history must match its exact frozen Context selection")
        return _build_planning_context_view(stage, context_bundle)
    if stage == "narrative_semantic_evaluation":
        return _build_narrative_evaluation_context_view(context_bundle)
    if stage == "agent_session":
        boundary = context_bundle.get("accepted_boundary")
        if (
            context_bundle.get("protected") is not True
            or context_bundle.get("source_authority") != "POSTGRESQL_ACCEPTED_BOUNDARY"
            or not isinstance(boundary, Mapping)
            or dict(boundary) != dict(task_view.get("accepted_boundary") or {})
        ):
            raise KernelError(
                "AGENT_PROVIDER_CONTEXT_INVALID",
                "Agent context must preserve the exact accepted boundary",
            )
        return {
            "contract_version": "provider-context-view-v2",
            "schema_version": "novelos.agent_harness_context_view.v1",
            "stage": stage,
            "source_isolation": "ACCEPTED_BOUNDARY_ONLY",
            "accepted_boundary": _compact(boundary),
            "protected": True,
        }
    if stage == "longform_prose_review":
        return _build_longform_prose_review_context_view(context_bundle)
    if stage in {"screenplay_generate", "screenplay_review", "screenplay_revision"}:
        from novel_forge.modules.book_followup_authority.screenplay_execution import screenplay_context_view
        return screenplay_context_view(stage, context_bundle)
    if stage == "reader_outcome":
        return _build_reader_outcome_context_view(context_bundle)
    correctness = context_bundle.get("context_correctness")
    if context_bundle.get("context_contract_version") in {
        "authority-context-bundle-v5",
        "authority-context-bundle-v6",
        "authority-context-bundle-v7",
        "authority-context-bundle-v8",
    }:
        if not isinstance(correctness, Mapping):
            raise KernelError(
                "CHAPTER_PROVIDER_CONTEXT_CORRECTNESS_REQUIRED",
                "Authority ContextBundle requires a Context Correctness receipt",
            )
        checks = correctness.get("checks")
        required_checks = {
            "NO_FUTURE_FACT",
            "NO_HIDDEN_KNOWLEDGE_LEAK",
            "NO_STALE_VERSION",
            "NO_DUPLICATE_SEMANTIC_REPRESENTATION",
            "NO_IRRELEVANT_FULL_ASSET",
            "REQUIRED_LONG_DISTANCE_FACT_PRESENT",
        }
        if (
            correctness.get("contract_version") != "context-correctness-receipt-v1"
            or correctness.get("overall_status") != "PASS"
            or not isinstance(checks, Mapping)
            or set(checks) != required_checks
            or any(
                not isinstance(item, Mapping)
                or item.get("status") not in {"PASS", "NOT_APPLICABLE"}
                for item in checks.values()
            )
            or str(correctness.get("receipt_hash") or "")
            != "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in correctness.items()
                        if key != "receipt_hash"
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        ):
            raise KernelError(
                "CHAPTER_PROVIDER_CONTEXT_CORRECTNESS_BLOCKED",
                "Provider admission requires all six Context Correctness checks",
            )
    segments = context_bundle.get("context_segments")
    if not isinstance(segments, list):
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_VIEW_INVALID",
            "ContextBundle requires canonical context_segments",
        )
    projection = context_bundle.get("task_narrative_projection") or {}
    if not isinstance(projection, Mapping):
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_VIEW_INVALID",
            "task_narrative_projection must be an object",
        )
    selectors = _selectors(projection, task_view)
    if (
        not projection
        and any(
            isinstance(item, Mapping)
            and str(item.get("asset_type") or "") in _STATE_ASSET_TYPES
            and list(item.get("structured_facts") or ())
            for item in segments
        )
        and not selectors
    ):
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_PROJECTION_REQUIRED",
            "state-bearing ContextBundle requires a task narrative projection; "
            "rebuild Context from the accepted checkpoint",
        )
    task_scoped_context = context_bundle.get("context_profile_version") == "draft-context-profile-v4"
    extended_context = task_scoped_context or context_bundle.get("context_profile_version") == "draft-context-profile-v3"
    maximum_characters = _MAX_PROVIDER_CONTEXT_CHARACTERS
    if extended_context:
        budget = context_bundle.get("token_budget")
        if type(budget) is not int or not 0 < budget <= (512_000 if task_scoped_context else 24_000):
            raise KernelError("CHAPTER_PROVIDER_CONTEXT_BUDGET_INVALID", "Draft Context v3 requires its exact bounded frozen token budget")
        maximum_characters = 8_192_000 if task_scoped_context else budget * 4
    rendered: list[dict[str, Any]] = []
    omitted_facts = 0
    omitted_segments = 0
    duplicate_state_summaries = 0
    working_intent = None
    for raw in segments:
        if not isinstance(raw, Mapping) or raw.get("allowed_use") == "evidence_only":
            omitted_segments += 1
            continue
        asset_type = str(raw.get("asset_type") or "")
        if stage in {"review", "revision", "rereview"} and task_view.get("creative_baseline") and asset_type in {
                "chapter_memo", "chapter_execution_intent"}:
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        if stage == "canon_extraction" and task_view.get("canon_context_projection") == "canon-source-context.v1" and asset_type in {
            "chapter_execution_intent", "chapter_memo", "retrieval_result", "style_policy"}:
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        if stage == "draft" and asset_type in {"chapter_plan", "style_policy"}:
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        if stage.startswith("quality_"):
            # WHY: QualityContext already bounds each dimension; rendering Context again duplicates its evidence.
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        facts = [
            item
            for item in raw.get("structured_facts") or []
            if isinstance(item, Mapping)
        ]
        consumption_stage = "review" if stage == "revision" and asset_type in {"review_report", "review_issue"} else stage
        if writer_projection_version == "accepted-writer-history.v2":
            from novel_forge.modules.context_builder.story_projection import visible_business_data
            facts = visible_business_data(facts, stage=consumption_stage, history=True)
        if clean_writer_context:
            from novel_forge.modules.context_builder.writer_projection import provider_visible_data
            visible = provider_visible_data(facts)
            omitted_facts += len(facts) - len(visible)
            facts = visible
        selected_facts = facts
        if asset_type in _STATE_ASSET_TYPES:
            bounded_facts = (
                project_narrative_state_facts(
                    facts,
                    projection=projection,
                    chapter=int(
                        (context_bundle.get("context_manifest") or {})
                        .get("narrative_position", {})
                        .get("chapter")
                        or 0
                    ),
                )
                if task_scoped_context or "disclosure_field_projections" in projection
                else facts
            )
            selected_facts = [
                item
                for item in bounded_facts
                if (writer_projection_version and stage in {"review", "rereview"}) or item.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"
                if task_scoped_context or _state_fact_relevant(
                    item,
                    selectors,
                    int(
                        dict(context_bundle.get("context_manifest") or {})
                        .get("narrative_position", {})
                        .get("chapter", 0)
                        or 0
                    ),
                )
            ]
        if not task_scoped_context and len(selected_facts) > _MAX_FACTS_PER_SEGMENT:
            raise KernelError(
                "CHAPTER_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
                "relevant accepted facts exceed the Provider segment budget; "
                "rebuild the governed task projection before dispatch",
            )
        omitted_facts += len(facts) - len(selected_facts)
        if stage in {"draft", "revision"} and asset_type == "chapter_memo":
            _validate_memo_realization_reference(raw, segments)
        summary = str(raw.get("safe_summary") or "").strip()
        if writer_projection_version == "accepted-writer-history.v2":
            from novel_forge.modules.context_builder.story_projection import story_history
            physical_type = str(raw.get("physical_asset_type") or asset_type)
            if raw.get("narrative_function") == "recent_accepted_prose":
                physical_type = "best_draft_candidate"
            if raw.get("compression_method") == "host-bound-extractive-semantic.v2":
                from novel_forge.modules.context_builder.writer_projection import project_writer_context_summary
                summary = project_writer_context_summary(raw, context_bundle.get("context_manifest") or {}, projection_version=writer_projection_version)
            else:
                summary = story_history(summary, physical_type=physical_type, stage=consumption_stage)
        if clean_writer_context:
            from novel_forge.modules.context_builder.writer_projection import project_writer_context_summary
            summary = project_writer_context_summary(raw, context_bundle.get("context_manifest") or {})
        if (stage in {"draft", "revision"} and asset_type == "chapter_execution_intent"
            and (context_bundle.get("working_manuscript") or {}).get("projection_policy") is not None):
            try:
                intent_data = json.loads(summary)
            except (ValueError, TypeError) as exc:
                raise KernelError("WORKING_PROSE_INTENT_DRIFT", "Working Intent must retain its structured source") from exc
            if (not isinstance(intent_data, dict) or working_intent is not None or selected_facts
                or intent_data.get("working_manuscript") != context_bundle["working_manuscript"]):
                raise KernelError("WORKING_PROSE_INTENT_DRIFT", "Writer must consume one exactly bound working Intent")
            working_intent = {key: value for key, value in intent_data.items() if key != "working_manuscript"}
            continue
        if (
            asset_type in _STATE_ASSET_TYPES
            and "disclosure_field_projections" in projection
        ):
            # WHY: v3 carries projected facts once; their generated JSON summary duplicates the same evidence.
            if extended_context:
                summary = ""
                duplicate_state_summaries += bool(selected_facts)
            else:
                summary = (
                    json.dumps(selected_facts, ensure_ascii=False, sort_keys=True)
                    if selected_facts
                    else ""
                )
        if not summary and not selected_facts:
            omitted_segments += 1
            continue
        if not task_scoped_context and len(rendered) >= _MAX_SEGMENTS:
            raise KernelError(
                "CHAPTER_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
                "eligible Context segments exceed the Provider budget; "
                "rebuild the governed selection before dispatch",
            )
        rendered.append(
            {
                "asset_version_id": str(raw.get("asset_version_id") or ""),
                "asset_type": asset_type,
                "narrative_function": str(raw.get("narrative_function") or ""),
                "safe_summary": summary,
                "structured_facts": [deepcopy(dict(item)) for item in selected_facts],
            }
        )
    manifest = context_bundle.get("context_manifest") or {}
    position = (
        dict(manifest.get("narrative_position") or {})
        if isinstance(manifest, Mapping)
        else {}
    )
    boundary = (
        dict(manifest.get("authority_state_boundary") or {})
        if isinstance(manifest, Mapping)
        else {}
    )
    view = {
        "contract_version": "provider-context-view-v6" if writer_projection_version else "provider-context-view-v5" if clean_writer_context else "provider-context-view-v4" if task_scoped_context else "provider-context-view-v3" if extended_context else "provider-context-view-v2",
        "stage": stage,
        "narrative_position": {
            key: position[key]
            for key in (
                "book_id",
                "volume_id",
                "chapter",
                "sequence_id",
                "sequence_ordinal",
            )
            if key in position
        },
        "accepted_state_boundary": {
            "accepted_through_chapter": int(
                boundary.get("accepted_through_chapter") or 0
            )
        },
        "task_narrative_projection": _compact(dict(projection)),
        "segments": rendered,
        "selection_explanation": {
            "policy": "task-scoped-context.v1" if task_scoped_context else "minimum-sufficient-context-v4" if extended_context else "minimum-sufficient-context-v3",
            "included_segment_count": len(rendered),
            "included_fact_count": sum(
                len(item["structured_facts"]) for item in rendered
            ),
            "omitted_segment_count": omitted_segments,
            "omitted_fact_count": omitted_facts,
            "maximum_segments": None if task_scoped_context else _MAX_SEGMENTS,
            "maximum_facts_per_segment": None if task_scoped_context else _MAX_FACTS_PER_SEGMENT,
            **({"maximum_serialized_bytes": 8_388_608} if task_scoped_context else {"maximum_serialized_characters": maximum_characters}),
            **({"context_profile_version": context_bundle["context_profile_version"],
                "frozen_context_token_budget": context_bundle["token_budget"],
                "duplicate_state_summary_count": duplicate_state_summaries} if extended_context else {}),
        },
        "context_correctness_receipt_hash": str(
            (correctness or {}).get("receipt_hash") or ""
        ),
    }
    if context_bundle.get("chapter_generation_length") is not None:
        from .quality_length_requirement import require_generation_binding
        view["chapter_generation_length"] = deepcopy(require_generation_binding(context_bundle))
    review_source_window = (task_view.get("cross_chapter_window") or task_view.get("source_window")
        or (task_view.get("targeted_repair") or {}).get("selected_source_window")
        or (task_view.get("targeted_repair") or {}).get("accepted_source_window"))
    if context_bundle.get("working_manuscript") is not None and stage in {"draft", "memo", "revision"} and not review_source_window:
        if context_bundle["working_manuscript"].get("projection_policy") is not None:
            from novel_forge.modules.book_authority.working_prose import validate_working_projection
            validate_working_projection(context_bundle["working_manuscript"],
                project_id=context_bundle["project_id"], book_id=position.get("book_id"),
                target_chapter=position.get("chapter"),
                accepted_through_chapter=view["accepted_state_boundary"]["accepted_through_chapter"])
        view["working_manuscript"] = deepcopy(context_bundle["working_manuscript"])
    if working_intent is not None:
        view["contract_version"] = "provider-context-view-v7"
        view["frozen_intent"] = working_intent
    serialized_size = len(json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) if task_scoped_context else _serialized_character_count(view)
    serialization_limit = 8_388_608 if task_scoped_context else maximum_characters
    if serialized_size > serialization_limit:
        raise KernelError(
            "CHAPTER_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
            "projected Provider Context exceeds its deterministic size boundary; "
            "rebuild the task projection with fewer accepted facts",
        )
    return view


def _build_narrative_evaluation_context_view(
    context_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    selected = context_bundle.get("selected_inputs")
    isolation = str(context_bundle.get("source_isolation") or "")
    dependency_resolution = str(context_bundle.get("dependency_resolution") or "")
    lineage = context_bundle.get("dependency_lineage")
    if not isinstance(selected, list) or not selected:
        raise KernelError(
            "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID",
            "Semantic Evaluation requires a frozen candidate projection",
        )
    candidate = selected[0] if isinstance(selected[0], Mapping) else {}
    candidate_content = candidate.get("candidate")
    candidate_valid = (
        candidate.get("asset_type") in {"book_design", "planning_generation_candidate"}
        and bool(candidate.get("asset_version_id"))
        and _is_exact_sha256(candidate.get("content_hash"))
        and isinstance(candidate_content, Mapping)
        and "dependency_role" not in candidate
    )
    projected_selected: list[dict[str, Any]] | None = None
    if isolation == "EXACT_CANDIDATE_ONLY":
        valid = (
            candidate_valid
            and len(selected) == 1
            and dependency_resolution in {"", "NOT_APPLICABLE"}
        )
        policy = "exact-immutable-candidate-only"
    elif isolation == "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES":
        valid = (
            candidate_valid
            and candidate.get("asset_type") == "book_design"
            and candidate_content.get("schema_version")
            in {"book-design.v5", "book-design.v6", "book-design.v7"}
            and dependency_resolution == "EVALUATOR_RESOLVED_FROM_CANDIDATE_LINEAGE"
            and len(selected) == 1 + len(_NARRATIVE_FOUNDATION_DEPENDENCY_TYPES)
            and isinstance(lineage, list)
            and len(lineage) == len(_NARRATIVE_FOUNDATION_DEPENDENCY_TYPES)
        )
        selected_by_role = {
            str(item.get("dependency_role") or ""): item
            for item in selected[1:]
            if isinstance(item, Mapping)
        }
        lineage_by_role = {
            str(item.get("role") or ""): item
            for item in lineage
            if isinstance(item, Mapping)
        }
        valid = valid and (
            set(selected_by_role) == set(_NARRATIVE_FOUNDATION_DEPENDENCY_TYPES)
            and set(lineage_by_role) == set(_NARRATIVE_FOUNDATION_DEPENDENCY_TYPES)
            and len(selected_by_role) == len(selected) - 1
            and len(lineage_by_role) == len(lineage)
        )
        if valid:
            projected_selected = [
                {
                    "asset_version_id": candidate["asset_version_id"],
                    "asset_type": candidate["asset_type"],
                    "content_hash": candidate["content_hash"],
                    "candidate": _compact(candidate_content),
                }
            ]
            for (
                role,
                expected_asset_type,
            ) in _NARRATIVE_FOUNDATION_DEPENDENCY_TYPES.items():
                item = selected_by_role[role]
                binding = lineage_by_role[role]
                qualification_hash = str(binding.get("qualification_hash") or "")
                source_content = item.get("candidate")
                semantic_payload = (
                    source_content.get("candidate_payload")
                    if isinstance(source_content, Mapping)
                    else None
                )
                from novel_forge.modules.story_design_authority.domain import (
                    matches_generated_foundation_source,
                )

                source_kind_matches = item.get("asset_type") == expected_asset_type
                if item.get("asset_type") == "planning_generation_candidate":
                    source_kind_matches = isinstance(
                        source_content, Mapping
                    ) and matches_generated_foundation_source(
                        source_content,
                        role=role,
                        project_id=context_bundle.get("project_id"),
                        book_id=context_bundle.get("book_id"),
                    )
                valid = valid and (
                    source_kind_matches
                    and isinstance(source_content, Mapping)
                    and source_content.get("schema_version")
                    == "story_design.authority.v1"
                    and source_content.get("generator_operation_name")
                    == _NARRATIVE_FOUNDATION_GENERATORS[role]
                    and isinstance(semantic_payload, Mapping)
                    and bool(semantic_payload)
                    and item.get("asset_version_id") == binding.get("asset_version_id")
                    and item.get("content_hash") == binding.get("content_hash")
                    and _is_exact_sha256(item.get("content_hash"))
                    and bool(binding.get("qualification_evidence_asset_version_id"))
                    and _is_exact_sha256(qualification_hash)
                )
                if valid:
                    projected_selected.append(
                        {
                            "asset_version_id": item["asset_version_id"],
                            "asset_type": item["asset_type"],
                            "content_hash": item["content_hash"],
                            "dependency_role": role,
                            "semantic_payload": _compact(semantic_payload),
                        }
                    )
        policy = "exact-candidate-and-canonical-foundation-semantic-closure-v2"
    else:
        valid = False
        policy = "invalid"
    if not valid:
        raise KernelError(
            "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_INVALID",
            "Semantic Evaluation context is outside its exact source-isolation contract",
        )
    if projected_selected is None:
        projected_selected = _compact(selected)
    from novel_forge.modules.story_design_authority.author_input import evaluation_author_view, compile_provider_author_projection

    exact_sources = {item["asset_version_id"]: (index, item["candidate"]) for index, item in enumerate(selected)}
    for item in projected_selected:
        key = "semantic_payload" if "semantic_payload" in item else "candidate"
        source_index, source = exact_sources[item["asset_version_id"]]
        source_pointer = f"/selected_inputs/{source_index}/candidate"
        if isinstance(source.get("candidate_payload"), Mapping):
            source_pointer += "/candidate_payload"
        if key == "semantic_payload":
            source = source["candidate_payload"]
        author_view = evaluation_author_view(source, generator=_NARRATIVE_FOUNDATION_GENERATORS.get(str(item.get("dependency_role") or ""), ""))
        if author_view.get("author_design_projection"):
            author_view["author_design_projection"] = compile_provider_author_projection(author_view["author_design_projection"], frozen_context_pointer=source_pointer + "/constraint_envelope/author_design_projection")
        item[key] = _compact(author_view)
    view = {
        "contract_version": "provider-context-view-v2",
        "schema_version": "novelos.narrative_evaluation_context_view.v2",
        "stage": "narrative_semantic_evaluation",
        "source_isolation": isolation,
        "selected_inputs": projected_selected,
        "selection_explanation": {
            "policy": policy,
            "selected_count": len(selected),
            "omitted_count": 0,
        },
    }
    maximum_characters = (
        _MAX_FOUNDATION_EVALUATION_CONTEXT_CHARACTERS
        if isolation == "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES"
        else _MAX_PROVIDER_CONTEXT_CHARACTERS
    )
    if _serialized_character_count(view) > maximum_characters:
        raise KernelError(
            "NARRATIVE_EVALUATION_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
            "Semantic Evaluation context exceeds the bounded Provider projection",
        )
    return view


def _is_exact_sha256(value: Any) -> bool:
    normalized = str(value or "")
    digest = normalized.removeprefix("sha256:")
    return (
        normalized.startswith("sha256:")
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def project_reader_outcome_context_input(
    asset_type: str,
    content: Mapping[str, Any],
    *, coordinated_contract: bool = False,
) -> dict[str, Any]:
    """INVARIANT: Project one accepted Reader Outcome input without Authority envelopes.

    The Book follow-up command binds a broad recovery lineage, but a Reader judge
    needs only the accepted prose, audience contract, intended experience, and a
    bounded view of current reader-facing state.  Empty projections preserve the
    immutable input reference without sending that asset to the Provider.
    """
    if asset_type == "draft_version" or coordinated_contract and asset_type == "best_draft_candidate":
        return _prose(content)
    if asset_type == "reader_contract":
        return _pick(content, "contract_id", "safe_summary")
    if asset_type == "reader_segment_profile":
        return _pick(content, "segment_id", "safe_summary")
    if asset_type == "platform_profile":
        return _pick(
            content,
            "profile_id",
            "reader_expectation",
            "genre_fit",
            "chapter_length_range",
            "review_risks",
            "safe_summary",
        )
    if asset_type == "book_design":
        return _pick(content, "genre", "premise", "reader_promise")
    if asset_type == "planning_generation_candidate":
        if content.get("chapter_intent") or content.get("chapter_number"):
            return _pick(
                content,
                "chapter_number",
                "chapter_intent",
                "reader_experience",
                "ending_hook",
                "setups",
                "payoffs",
            )
        if content.get("reader_promise"):
            return _pick(content, "reader_promise", "ending_contract")
        return {}
    if asset_type == "quality_score_report":
        return _pick(
            content,
            "gate",
            "aggregate_score",
            "blocking_dimensions",
            "uncalibrated_dimensions",
            "required_actions",
        )
    if asset_type == "story_state_snapshot":
        chapter = int(content.get("accepted_through_chapter") or 0)
        current = [
            item
            for item in compact_current_state_facts(content)
            if str(item.get("state_kind") or "")
            in {"reader_knowledge", "disclosure_event", "reader_promise"}
            and int(item.get("effective_from_chapter") or 0) >= chapter
        ]
        current.sort(
            key=lambda item: (
                -int(item.get("effective_from_chapter") or 0),
                str(item.get("entity_key") or ""),
            )
        )
        return {
            "accepted_through_chapter": chapter,
            "reader_facing_state": [
                _compact(item) for item in current[:_MAX_FACTS_PER_SEGMENT]
            ],
        }
    if asset_type == "reader_state_transition":
        return _pick(content, "reader_state", "gate", "candidate_status")
    return {}


def _build_reader_outcome_context_view(
    context_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    schema_version = str(context_bundle.get("schema_version") or "")
    if schema_version not in {
        "novelos.reader_outcome_context_bundle.v1",
        "novelos.reader_outcome_context_bundle.v2",
        "novelos.reader_outcome_context_bundle.v3",
    }:
        raise KernelError(
            "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
            "Reader Outcome requires its governed ContextBundle",
        )
    selected = context_bundle.get("selected_inputs")
    if not isinstance(selected, list) or not selected:
        raise KernelError(
            "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
            "Reader Outcome ContextBundle requires frozen inputs",
        )
    if len(selected) > _MAX_SEGMENTS:
        raise KernelError(
            "READER_OUTCOME_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
            "Reader Outcome frozen inputs exceed the bounded segment limit",
        )
    segments: list[dict[str, Any]] = []
    omitted = 0
    for raw in selected:
        if not isinstance(raw, Mapping):
            raise KernelError(
                "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
                "Reader Outcome frozen input must be an object",
            )
        asset_type = str(raw.get("asset_type") or "")
        projection = raw.get("projection")
        if not isinstance(projection, Mapping):
            legacy_content = raw.get("content")
            if not isinstance(legacy_content, Mapping):
                raise KernelError(
                    "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
                    "Reader Outcome frozen input has no typed projection",
                )
            projection = project_reader_outcome_context_input(
                asset_type, legacy_content,
                coordinated_contract=schema_version == "novelos.reader_outcome_context_bundle.v3",
            )
        projected = _compact(projection)
        if not projected:
            omitted += 1
            continue
        segments.append(
            {
                "asset_version_id": str(raw.get("asset_version_id") or ""),
                "asset_type": asset_type,
                "content": projected,
            }
        )
    prose_type = "best_draft_candidate" if schema_version == "novelos.reader_outcome_context_bundle.v3" else "draft_version"
    if not any(item["asset_type"] == prose_type for item in segments):
        raise KernelError(
            "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
            "Reader Outcome Provider View requires accepted chapter prose",
        )
    view = {
        "contract_version": "provider-context-view-v3" if schema_version == "novelos.reader_outcome_context_bundle.v3" else "provider-context-view-v2",
        "stage": "reader_outcome",
        "accepted_state_boundary": {
            "accepted_through_chapter": max(
                (
                    int(item["content"].get("accepted_through_chapter") or 0)
                    for item in segments
                    if isinstance(item.get("content"), Mapping)
                ),
                default=0,
            )
        },
        "segments": segments,
        "selection_explanation": {
            "policy": "accepted-best-candidate-reader-outcome-context-v2" if schema_version == "novelos.reader_outcome_context_bundle.v3" else "minimum-sufficient-reader-outcome-context-v1",
            "included_segment_count": len(segments),
            "omitted_segment_count": omitted,
            "maximum_segments": _MAX_SEGMENTS,
            "maximum_facts_per_segment": _MAX_FACTS_PER_SEGMENT,
            "maximum_serialized_characters": _MAX_PROVIDER_CONTEXT_CHARACTERS,
        },
    }
    if _serialized_character_count(view) > _MAX_PROVIDER_CONTEXT_CHARACTERS:
        raise KernelError(
            "READER_OUTCOME_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
            "Reader Outcome Provider Context exceeds its deterministic size boundary",
        )
    return view


def compile_planning_provider_context(stage: str, context_bundle: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    audit: dict[str, Any] = {}
    return _build_planning_context_view(stage, context_bundle, projection_audit=audit), audit


def _build_planning_context_view(
    stage: str, context_bundle: Mapping[str, Any], *, projection_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:

    from novel_forge.modules.story_design_authority.author_input import compile_provider_author_projection
    if context_bundle.get("schema_version") != "novelos.planning_context_bundle.v1":
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
            "Planning Provider Context requires the canonical Planning ContextBundle",
        )
    capacity_policy = context_bundle.get("planning_context_policy_version")
    if capacity_policy is not None and capacity_policy != _PLANNING_TASK_CAPACITY_POLICY:
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_INVALID", "Planning capacity requires a supported frozen policy version")
    task_capacity = capacity_policy == _PLANNING_TASK_CAPACITY_POLICY
    foundation_projection = context_bundle.get("foundation_input_projection_version")
    if foundation_projection not in (None, "foundation-stage-input.v1"):
        raise KernelError("FOUNDATION_PROVIDER_CONTEXT_INVALID", "Unsupported frozen Foundation input projection")
    if foundation_projection is not None:
        from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS
        if stage not in FOUNDATION_GENERATORS:
            raise KernelError("FOUNDATION_PROVIDER_CONTEXT_INVALID", "Foundation projection cannot change Planning inputs")
    typed_arc_sources = context_bundle.get("planning_contract_version") == "1.21.0"
    typed_volume_sources = context_bundle.get("typed_volume_projection_version") == "typed-volume-context-projection.v1"
    planning_window = None
    if context_bundle.get("typed_window_projection_version") == "typed-planning-window-projection.v1":
        horizon = (context_bundle.get("narrative_search") or {}).get("planning_horizon") or {}
        planning_window = horizon.get("chapter_range")
        if (stage != "chapter_group_plan.generate" or horizon.get("level") != "CHAPTER_GROUP"
                or not isinstance(planning_window, list) or len(planning_window) != 2
                or any(type(value) is not int for value in planning_window)
                or not 0 < planning_window[0] <= planning_window[1]):
            raise KernelError("PLANNING_PROVIDER_CONTEXT_VIEW_INVALID", "Group projection requires its exact frozen positive planning horizon")
    frozen = (context_bundle.get("context_manifest") or {}).get("provider_context_view")
    if isinstance(frozen, Mapping) and "compiled_view" in frozen:
        view = frozen["compiled_view"]
        loss_receipt = view.get("selection_explanation", {}).get("loss_receipt") if isinstance(view, Mapping) else None
        audit = (context_bundle.get("context_manifest") or {}).get("projection_audit")
        if (
            not isinstance(view, Mapping)
            or view.get("stage") != stage
            or _projection_hash(view) != frozen.get("content_hash")
            or planning_context_source_hash(context_bundle) != frozen.get("source_input_hash")
            or (loss_receipt is not None and (
                not isinstance(audit, Mapping)
                or _projection_hash(audit) != loss_receipt.get("audit_hash")
                or loss_receipt.get("source_input_hash") != frozen.get("source_input_hash")
                or loss_receipt.get("json_pointer") != "/context_manifest/projection_audit"
            ))
        ):
            raise KernelError(
                "PROVIDER_CONTEXT_VIEW_IDENTITY_MISMATCH",
                "frozen Planning projection or its semantic inputs changed",
            )
        if context_bundle.get("author_design_projection"):
            compile_provider_author_projection(view.get("author_design_projection") or {}, source_projection=context_bundle["author_design_projection"])
        return deepcopy(dict(view))
    raw_inputs = context_bundle.get("input_versions")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
            "Planning Provider Context requires frozen input versions",
        )
    if any(isinstance(raw, Mapping) and raw.get("role") == "creative_brief" and (raw.get("content") or {}).get("editorial_learning") for raw in raw_inputs) and not context_bundle.get("author_design_projection"):
        raise KernelError("EDITORIAL_LEARNING_PROJECTION_MISSING", "Editorial learning requires its scoped author intent before Provider compilation")
    if len(raw_inputs) > _MAX_SEGMENTS:
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
            "Planning frozen inputs exceed the bounded segment limit",
        )
    chapter = _planning_chapter(context_bundle)
    selectors = _planning_selectors(raw_inputs, chapter=chapter, stage=stage, task_capacity=task_capacity)
    repair_context = context_bundle.get("repair_context")
    if repair_context is not None and not isinstance(repair_context, Mapping):
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
            "Planning repair context must be an object",
        )
    projected: list[dict[str, Any]] = []
    omitted_items = 0
    truncated_characters = 0
    losses: list[dict[str, Any]] = []
    for raw in raw_inputs:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("content"), Mapping):
            raise KernelError(
                "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
                "Planning frozen inputs require typed provider-safe content",
            )
        content, omitted, truncated = _project_planning_content(
            stage=stage,
            role=str(raw.get("role") or ""),
            content=raw["content"],
            chapter=chapter,
            selectors=selectors,
            loss_records=losses,
            source=raw,
            task_capacity=task_capacity,
            typed_arc_sources=typed_arc_sources,
            typed_volume_sources=typed_volume_sources,
            planning_window=planning_window,
            foundation_projection=foundation_projection == "foundation-stage-input.v1",
        )
        omitted_items += omitted
        truncated_characters += truncated
        projected.append(
            {
                "role": str(raw.get("role") or ""),
                "asset_version_id": str(raw.get("asset_version_id") or ""),
                "asset_type": str(raw.get("asset_type") or ""),
                "content_hash": str(raw.get("content_hash") or ""),
                "content": content,
            }
        )
    accepted_through_chapter = _planning_accepted_through_chapter(
        context_bundle, raw_inputs
    )
    view = {
        "contract_version": "provider-context-view-v4" if task_capacity else "provider-context-view-v2",
        "stage": stage,
        **({"typed_arc_projection_version": "typed-arc-context-projection.v2"} if typed_arc_sources else {}),
        **({"typed_volume_projection_version": "typed-volume-context-projection.v1"} if typed_volume_sources else {}),
        **({"typed_window_projection_version": "typed-planning-window-projection.v1"} if planning_window else {}),
        "narrative_position": {
            "book_id": str(context_bundle.get("book_id") or ""),
            "logical_key": str(context_bundle.get("logical_key") or ""),
            "planning_scope": str(context_bundle.get("planning_scope") or ""),
        },
        "accepted_state_boundary": {
            "accepted_through_chapter": accepted_through_chapter
        },
        "segments": projected,
        "selection_explanation": {
            "policy": (
                "minimum-sufficient-planning-repair-context-v1"
                if repair_context is not None
                else "minimum-sufficient-planning-context-v2"
            ),
            "included_segment_count": len(projected),
            "included_fact_count": 0,
            "omitted_segment_count": (
                len(raw_inputs) - len(projected)
            ),
            "omitted_fact_count": 0,
            "omitted_item_count": omitted_items,
            "truncated_character_count": truncated_characters,
            "compiler_version": "scope-preserving-planning-context-v1",
            "field_classes": {**_REQUIRED_PLANNING_FIELDS, **{field: "OPTIONAL_GUIDANCE" for field in sorted(_OPTIONAL_PLANNING_FIELDS)}},
            "loss_records": losses,
            "maximum_segments": _MAX_SEGMENTS,
            "maximum_facts_per_segment": None if task_capacity else _MAX_FACTS_PER_SEGMENT,
            **({"capacity_policy_version": capacity_policy, "maximum_serialized_bytes": _TASK_PROVIDER_SERIALIZATION_BYTES,
                "token_accounting": "utf8-byte-upper-bound.v1"} if task_capacity else {"maximum_serialized_characters": _MAX_PROVIDER_CONTEXT_CHARACTERS}),
        },
    }
    if context_bundle.get("author_length_source") is not None:
        from .quality_length_requirement import compile_planning_length
        view["chapter_planning_length"] = compile_planning_length(context_bundle["author_length_source"])
    if context_bundle.get("author_design_projection"):
        view["author_design_projection"] = compile_provider_author_projection(context_bundle["author_design_projection"])
    continuity = _planning_working_continuity(context_bundle, context_bundle)
    if continuity is not None:
        if continuity["accepted_through_chapter"] != accepted_through_chapter:
            raise KernelError("PLANNING_WORKING_CONTINUITY_DRIFT", "Working continuity must retain the actual accepted State boundary")
        view["working_continuity"] = continuity
    input_projection = context_bundle.get("planning_input_projection_version")
    if input_projection is not None:
        if input_projection != "planning-input-role-references.v1":
            raise KernelError("PLANNING_PROVIDER_CONTEXT_VIEW_INVALID", "Planning input references require an explicit supported frozen version")
        _reference_planning_matrix_source(view, sources=raw_inputs, chapter=chapter)
        view["contract_version"] = "provider-context-view-v4" if task_capacity else "provider-context-view-v3"
        view["selection_explanation"]["compiler_version"] = "scope-preserving-planning-context-v2"
    if context_bundle.get("edition_execution"):
        view["edition_execution"] = deepcopy(context_bundle["edition_execution"])
        view["edition_execution_instruction"] = "This is a new manuscript edition, not a mutation of its source. Implement the exact target_scene_ids and order where supplied; source_scene_plan is provenance, and source_ranges retain the original mapping for splits, merges and reorder; bind new World and accepted-state evidence in this run. Source plans remain plans, not proof that edited prose realized them. Return a failed qualification when source structure cannot satisfy the current world or mission."
    reference_contract = context_bundle.get("realization_reference_contract")
    if reference_contract is not None:
        if not isinstance(reference_contract, Mapping):
            raise KernelError(
                "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
                "Planning realization reference contract must be an object",
            )
        view["realization_reference_contract"] = _compact(reference_contract)
    if repair_context is not None and repair_context.get("contract_version") == "planning-result-repair-context.v1":
        source = repair_context.get("source_result")
        if not isinstance(source, Mapping) or "content" not in source or not source.get("operation_id"):
            raise KernelError("PLANNING_PROVIDER_CONTEXT_VIEW_INVALID", "result repair context requires its immutable raw result and failed Operation")
        view["repair_context"] = dict(repair_context)
    elif repair_context is not None:
        source = repair_context.get("source_candidate")
        if not isinstance(source, Mapping) or not isinstance(
            source.get("content"), Mapping
        ):
            raise KernelError(
                "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
                "Planning repair context requires its immutable source candidate",
            )
        projected_source, omitted, truncated = _project_planning_content(
            stage=stage,
            role="repair_source_candidate",
            content=source["content"],
            chapter=chapter,
            selectors=selectors,
            loss_records=losses,
            source=source,
            task_capacity=task_capacity,
            typed_arc_sources=typed_arc_sources,
        )
        repair_view = {
            "contract_version": str(repair_context.get("contract_version") or ""),
            "source_candidate": {
                "asset_version_id": str(source.get("asset_version_id") or ""),
                "content_hash": str(source.get("content_hash") or ""),
                "content": projected_source,
            },
            "validation_failure": _compact(
                repair_context.get("validation_failure") or {}
            ),
            "failed_narrative_qualifications": _compact(
                repair_context.get("failed_narrative_qualifications") or []
            ),
        }
        view["repair_context"] = repair_view
        view["selection_explanation"]["omitted_item_count"] += omitted
        view["selection_explanation"]["truncated_character_count"] += truncated
    token_budget = context_bundle.get("token_budget")
    if token_budget is not None and (not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget <= 0):
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_INVALID", "Planning token budget must be a positive integer")
    if task_capacity and (type(token_budget) is not int or not 0 < token_budget <= 512_000):
        raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_INVALID", "Planning task capacity requires a frozen target within system support")
    if task_capacity:
        view["selection_explanation"]["task_target_tokens"] = token_budget
    character_budget = min(_MAX_PROVIDER_CONTEXT_CHARACTERS, token_budget * 4) if token_budget is not None else _MAX_PROVIDER_CONTEXT_CHARACTERS
    _compact_qualified_foundation_planning(view, sources=raw_inputs, stage=stage, project_id=str(context_bundle.get("project_id") or ""))
    _compact_planning_loss_sources(view)
    source_hash = planning_context_source_hash(context_bundle) if projection_audit is not None else ""
    _prune_optional_planning_context(view, sources=raw_inputs, character_budget=character_budget,
                                    task_token_budget=token_budget if task_capacity else None, audit_source_hash=source_hash)
    if input_projection:
        _reference_planning_matrix_source(view, sources=raw_inputs, chapter=chapter)
    if projection_audit is not None:
        view, audit = _planning_view_with_audit_receipt(view, source_input_hash=source_hash)
        projection_audit.update(audit)
    if task_capacity:
        measured = _serialized_byte_count(view)
        if measured > _TASK_PROVIDER_SERIALIZATION_BYTES or measured > token_budget:
            raise KernelError("PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "required Planning Provider Context exceeds its conservative task token budget or serialized byte guard",
                details={"required_serialized_bytes":measured,"task_token_upper_bound":token_budget,
                    "serialization_byte_limit":_TASK_PROVIDER_SERIALIZATION_BYTES})
    elif _serialized_character_count(view) > character_budget:
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
            "required Planning Provider Context exceeds its budget boundary; narrow the governed scope before sending: "
            + json.dumps({"total": _serialized_character_count(view), "segments": [{"role": item["role"], "characters": _serialized_character_count(item)} for item in projected], "repair": _serialized_character_count(view.get("repair_context", {})), "references": _serialized_character_count(view.get("realization_reference_contract", {}))}, sort_keys=True),
        )
    return view


def project_planning_narrative_intent(
    task: Mapping[str, Any], context: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    original_task, original_context = deepcopy(dict(task)), deepcopy(dict(context))
    projected_task, projected_context = deepcopy(original_task), deepcopy(original_context)
    omissions: list[dict[str, str]] = []

    def omit(value: dict[str, Any], key: str, pointer: str) -> None:
        if key in value:
            removed = value.pop(key)
            omissions.append({"source_pointer": pointer + "/" + key, "content_hash": _projection_hash(removed)})

    command = projected_task.get("planning_command")
    narrative_command: dict[str, Any] = {}
    if isinstance(command, dict):
        for key in ("repair_number", "repair_reason", "narrative_search_branch_key"):
            omit(command, key, "/input_manifest/planning_command")
        for key, host_key in (("narrative_search_planning_horizon", "opening_topology_budget"),
                              ("narrative_search_desired_transformation", "selection_policy")):
            if isinstance(command.get(key), dict):
                omit(command[key], host_key, "/input_manifest/planning_command/" + key)
        for key in ("narrative_search_planning_horizon", "narrative_search_desired_transformation",
                    "narrative_search_strategy_directive", "narrative_search_hard_constraints",
                    "narrative_realization", "edition_execution"):
            if key in command:
                narrative_command[key] = command.pop(key)
    narrative_task = {key: projected_task.pop(key) for key in
                      ("narrative_intelligence", "working_continuity", "world_preparation") if key in projected_task}
    if narrative_command:
        narrative_task["planning_direction"] = narrative_command
    reading_contract = {key: projected_context.get("selection_explanation", {}).get(key)
                        for key in ("literal_references", "role_reference_contract")
                        if key in projected_context.get("selection_explanation", {})}
    omit(projected_context, "selection_explanation", "/context_bundle")
    if reading_contract:
        projected_context["projection_reading_contract"] = reading_contract
    result_task = {"contract_version": "provider-task-narrative-intent.v1", "stage": task.get("stage"),
                   "narrative_inputs": narrative_task, "output_protocol": projected_task}
    result_context = {**projected_context, "contract_version": "provider-context-narrative-intent.v1"}
    receipt = {"contract_version": "planning-narrative-intent-projection.v1",
               "source_task_hash": _projection_hash(original_task), "source_context_hash": _projection_hash(original_context),
               "projected_task_hash": _projection_hash(result_task), "projected_context_hash": _projection_hash(result_context),
               "omissions": omissions, "semantic_source_rewrite": False}
    return result_task, result_context, receipt


def bind_narrative_intent_schema(schema: Mapping[str, Any], *, event_first_planning: bool = False) -> dict[str, Any]:
    result = deepcopy(dict(schema))
    result["description"] = (str(result.get("description") or "") +
        " Narrative intent v1: author intent, fictional rules and selected design supply story meaning. "
        "Host identity, approval, validation, receipts, retries and evidence status are output protocol only. "
        "Quiet or procedural narrative is valid when supported by this work. Do not invent a plot to enact host governance.")
    meanings = {
        "constraints": "Story constraints grounded in the author brief or selected fictional design; no host execution constraints.",
        "book_invariants": "Invariants of this work's fictional design; no runtime acceptance, budget or delivery-window rules.",
        "prohibited_outcomes": "Fictional outcomes forbidden by this work; candidate and Canon mutation restrictions belong to output protocol.",
        "risk_register": "Risks to the selected narrative purpose; no Provider, retry, deployment or proof-status risks.",
        "scene_plan": "Realize the selected chapter purpose through its people, situation and POV. Knowledge limits do not require verification scenes.",
        "beats": "Scene-specific observation, action or experience; no mandatory conflict, reward, reversal or cost.",
    }
    if event_first_planning:
        meanings.update({
            "hard_constraints": "Fictional constraints grounded in author requirements, world rules or selected design. Preserve their actual scope and source. Candidate approval, accepted cursors, execution budgets and delivery windows remain host protocol, not duties for fictional people or reasons to postpone event results.",
            "required_events": "Required fictional actions and results of this selected complete event. Host approval, validation and receipt steps are not story events. Distribute by the event's causal turns, not by giving each procedural step a chapter.",
            "forbidden_events": "Fictional outcomes prohibited by author requirements, world rules or this selected scope. Do not turn historical candidate or activation restrictions into fictional prohibitions; active scope changes still require native Plan Change.",
        })

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in (node.get("properties") or {}).items():
                if key in meanings and isinstance(value, dict):
                    value["description"] = str(value.get("description") or "") + " " + meanings[key]
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


def _reference_planning_matrix_source(view: dict[str, Any], *, sources: list[Mapping[str, Any]], chapter: int) -> None:
    groups = [(index, source) for index, source in enumerate(sources) if source.get("role") == "chapter_group_plan"]
    if not chapter or len(groups) != 1:
        return
    group_index, group = groups[0]
    projected = view["segments"][group_index]["content"]
    rows = projected.get("chapter_function_matrix")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("chapter_number") != chapter:
        return
    for index, source in enumerate(sources):
        if (source.get("role") != "chapter_function_matrix_row"
            or not all(group.get(field) and source.get(field) == group[field] for field in ("asset_version_id", "content_hash"))
            or source.get("content") != group.get("content")):
            continue
        view["segments"][index]["content"] = {
            "contract_version": "planning-chapter-matrix-reference.v1", "chapter_number": chapter,
            "json_pointer": f"/segments/{group_index}/content/chapter_function_matrix/0",
            "row_content_hash": _projection_hash(rows[0]),
            "group_constraints_pointer": f"/segments/{group_index}/content",
            "instruction": "Read this exact current-chapter matrix row and all its group constraints at the referenced locations in this same Context view. Both input roles bind the same immutable group asset and hash; this reference does not remove or weaken any group constraint.",
        }
        view["selection_explanation"]["role_reference_contract"] = "planning-input-role-references.v1"


def _compact_qualified_foundation_planning(
    view: dict[str, Any],
    *,
    sources: list[Mapping[str, Any]],
    stage: str,
    project_id: str,
) -> None:
    from novel_forge.modules.book_design_authority.foundation import QualifiedFoundationSet
    from novel_forge.modules.story_design_authority.domain import matches_generated_foundation_source

    if stage not in {"book_plan.generate", "volume_plan.generate", "arc_plan.generate"}:
        return
    source_by_role = {item["role"]: item for item in sources}
    design_source = source_by_role.get("book_design", {})
    design = design_source.get("content", {})
    if design.get("schema_version") not in {"book-design.v5", "book-design.v6", "book-design.v7"}:
        return
    foundation = QualifiedFoundationSet.from_mapping(design["foundation_set"])
    segments = {item["role"]: item for item in view["segments"]}
    selected = {}
    for binding in foundation.bindings:
        role = _NARRATIVE_FOUNDATION_DEPENDENCY_TYPES[binding.role.value]
        source = source_by_role.get(role)
        if source is None:
            continue
        if (
            source["asset_version_id"] != binding.asset_version_id
            or source["content_hash"] != binding.content_hash
            or source["content"].get("project_id", project_id) != project_id
            or source["content"].get("book_id", view["narrative_position"]["book_id"]) != view["narrative_position"]["book_id"]
            or not (source.get("asset_type") == role or matches_generated_foundation_source(
                source["content"], role=binding.role.value,
                project_id=project_id,
                book_id=str(view["narrative_position"]["book_id"]),
            ))
        ):
            raise KernelError("PLANNING_FOUNDATION_PROJECTION_DRIFT", "Planning Foundation differs from its exact Book Design binding")
        selected[role] = segments[role]
    if not selected:
        return
    explanation = view["selection_explanation"]

    def remove(parent: dict[str, Any], key: str, source: Mapping[str, Any], path: str, reason: str) -> None:
        value = parent.pop(key)
        explanation["loss_records"].append(_loss_record(source, path=path, value=value, reason=reason))
        explanation["omitted_item_count"] += len(value) if isinstance(value, list) else 1

    constraints = {
        text for segment in selected.values()
        for text in segment["content"].get("constraints", [])
        if isinstance(text, str)
    }
    design_view = segments["book_design"]["content"]
    inherited = [text for text in design_view.get("book_invariants", []) if isinstance(text, str) and text in constraints]
    if inherited:
        explanation["loss_records"].append(_loss_record(design_source, path="/book_invariants", value=inherited, reason="EXACT_DUPLICATE_OF_SELECTED_FOUNDATION_CONSTRAINTS"))
        design_view["book_invariants"] = [text for text in design_view["book_invariants"] if not isinstance(text, str) or text not in constraints]
        explanation["inherited_invariants"] = "Selected Foundation constraints remain mandatory Book invariants; exact duplicate strings are represented once."
        explanation["omitted_item_count"] += len(inherited)
    remove(design_view, "foundation_set", design_source, "/foundation_set", "QUALIFICATION_DIRECTORY_RETAINED_IN_FROZEN_INPUT")
    for role, segment in selected.items():
        content = segment["content"]
        source = source_by_role[role]
        for field in ("type", "book_id", "project_id", "logical_key", "planning_scope", "schema_version", "generator_operation_name", "foundation_parent_bindings", "knowledge_translation_policy_version"):
            if field in content:
                remove(content, field, source, "/" + field, "CONTROL_METADATA_RETAINED_IN_FROZEN_INPUT")
        if role == "creative_foundation":
            style = content.get("style_profile", {})
            if "original_examples" in style:
                remove(style, "original_examples", source, "/style_profile/original_examples", "PROSE_EXAMPLE_OUTSIDE_LONG_HORIZON_PLANNING")
        if role == "theme_contract" and stage == "book_plan.generate" and "choice_tests" in content:
            remove(content, "choice_tests", source, "/choice_tests", "ILLUSTRATIVE_CHOICE_SCENARIOS_DEFERRED_TO_VOLUME_PLANNING")
        if role == "character_cast":
            for index, character in enumerate(content.get("characters", [])):
                if "voice_anchors" in character:
                    remove(character, "voice_anchors", source, f"/characters/{index}/voice_anchors", "PROSE_EXAMPLE_OUTSIDE_LONG_HORIZON_PLANNING")
    literals: dict[str, dict[str, str]] = {}

    def collect(value: Any, role: str, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                collect(child, role, path + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, role, path + "/" + str(index))
        elif isinstance(value, str) and len(value) > 100:
            literals.setdefault(value, {"literal_source_role": role, "json_pointer": path})

    for role, segment in selected.items():
        collect(segment["content"], role, "")

    def replace_literal(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            return {key: replace_literal(child, path + "/" + key) for key, child in value.items()}
        if isinstance(value, list):
            return [replace_literal(child, path + "/" + str(index)) for index, child in enumerate(value)]
        if isinstance(value, str) and value in literals and _serialized_character_count(literals[value]) < len(value):
            explanation["loss_records"].append({**_loss_record(design_source, path=path, value=value, reason="EXACT_LITERAL_RETAINED_IN_SELECTED_FOUNDATION"), **literals[value]})
            return dict(literals[value])
        return value

    for field in ("narrative_dna", "cross_layer_synthesis"):
        if field in design_view:
            design_view[field] = replace_literal(design_view[field], "/" + field)
    explanation["literal_references"] = "A literal_source_role/json_pointer object means the exact full string at that selected segment content path. It inherits the original Book Design requirement."


def _planning_working_continuity(source: Mapping[str, Any], scope: Mapping[str, Any]) -> dict[str, Any] | None:
    version = source.get("working_continuity_projection_version")
    if version is None:
        return None
    working = (source.get("arc_working_set") or {}).get("working_manuscript")
    if version == "planning-working-continuity.v3":
        from novel_forge.modules.book_authority.working_prose import validate_working_projection
        if not isinstance(working, Mapping):
            raise KernelError("PLANNING_WORKING_CONTINUITY_DRIFT", "Working continuity requires its frozen projection")
        validate_working_projection(working, project_id=scope["project_id"], book_id=scope["book_id"])
        return {"version": version, "book_run_id": working["book_run_id"],
            "snapshot_hash": working["snapshot_hash"], "target_chapter": working["target_chapter"],
            "accepted_through_chapter": working["accepted_through_chapter"],
            "source_location": "/arc_working_set/working_manuscript",
            "authority": "SELECTED_WORKING_VERSION_CONTINUITY_ONLY", "instruction": working["instruction"]}
    if (version not in {"planning-working-continuity.v1", "planning-working-continuity.v2"}
            or not isinstance(working, Mapping)
            or working.get("version") != "working-manuscript-context.v1"
            or working.get("book_id") != scope.get("book_id")
            or working.get("project_id") != scope.get("project_id")
            or working.get("authority") != "AUTHOR_WORKING_PROSE_ONLY"
            or working.get("structured_facts") != []
            or not isinstance(working.get("book_run_id"), str) or not working["book_run_id"]
            or not isinstance(working.get("sources"), list)
            or type(working.get("target_chapter")) is not int
            or type(working.get("accepted_through_chapter")) is not int
            or not 0 <= working["accepted_through_chapter"] < working["target_chapter"]
            or working.get("snapshot_hash") != _projection_hash({key: value for key, value in working.items() if key != "snapshot_hash"})):
        raise KernelError("PLANNING_WORKING_CONTINUITY_DRIFT", "Working continuity requires the exact scoped immutable manuscript snapshot")
    numbers = []
    for item in working["sources"]:
        if (not isinstance(item, Mapping)
                or type(item.get("chapter")) is not int
                or not 0 < item["chapter"] < working["target_chapter"]
                or item.get("status") != "UNREVIEWED_WORKING_PROSE"
                or item.get("character_knowledge") != "NOT_VERIFIED"
                or any(not isinstance(item.get(key), str) or not item[key] for key in ("asset_version_id", "content_hash", "text_hash", "excerpt"))):
            raise KernelError("PLANNING_WORKING_CONTINUITY_DRIFT", "Working continuity cannot relabel source observations as accepted knowledge")
        numbers.append(item["chapter"])
    if numbers != sorted(set(numbers)):
        raise KernelError("PLANNING_WORKING_CONTINUITY_DRIFT", "Working sources require a unique ordered predecessor sequence")
    return {
        "version": version,
        "book_run_id": working["book_run_id"],
        "snapshot_hash": working["snapshot_hash"],
        "target_chapter": working["target_chapter"],
        "accepted_through_chapter": working["accepted_through_chapter"],
        "source_location": "/arc_working_set/working_manuscript",
        "authority": "SELECTED_WORKING_VERSION_CONTINUITY_ONLY",
        "instruction": (
            "Continue this exact selected working version. Carry forward actions, witnessed responses and experiences "
            "actually realized in these source excerpts within that working story; lack of formal acceptance alone "
            "does not require characters to reapply, reverify, reperform or forget them. Preserve source uncertainty, "
            "unresolved dependency changes and POV restrictions: claims and beliefs need not be true, reader-only "
            "information is not character knowledge, and plans are not past events. Introduce subsequent events "
            "that use the progress already realized. This projection grants no accepted fact IDs, verified Character "
            "Knowledge, Canon mutation, author choice or formal acceptance. Keep accepted-state fields unchanged."
            + (" Describe selected working experiences in entry_state, causal_trigger, beats and actions. "
               "Do not turn their prose summaries into known_fact_ids or accessible_knowledge: those fields "
               "accept only eligible fact IDs under the unchanged accepted and earlier-scene disclosure rules."
               if version == "planning-working-continuity.v2" else "")
        ),
    }


def _projection_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def planning_context_source_hash(context_bundle: Mapping[str, Any]) -> str:
    return _projection_hash({key: value for key, value in context_bundle.items() if key not in {"context_manifest", "estimated_tokens"}})


def _loss_record(source: Mapping[str, Any], *, path: str, value: Any, reason: str) -> dict[str, Any]:
    return {
        "asset_version_id": str(source.get("asset_version_id") or ""),
        "source_content_hash": str(source.get("content_hash") or ""),
        "role": str(source.get("role") or ""),
        "path": path,
        "reason": reason,
        "removed_value_hash": _projection_hash(value),
        "removed_item_count": len(value) if isinstance(value, (list, tuple)) else 1,
        "removed_serialized_characters": _serialized_character_count(value),
    }


def _compact_planning_loss_sources(view: dict[str, Any]) -> None:
    explanation = view["selection_explanation"]
    sources = explanation.setdefault("loss_sources", [])
    for loss in explanation["loss_records"]:
        if "source_index" in loss:
            continue
        source = {key: loss.pop(key) for key in ("asset_version_id", "source_content_hash", "role")}
        if source not in sources:
            sources.append(source)
        loss["source_index"] = sources.index(source)


def _planning_view_with_audit_receipt(view: Mapping[str, Any], *, source_input_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    compiled = deepcopy(dict(view))
    explanation = compiled["selection_explanation"]
    audit = {key: explanation.pop(key) for key in ("loss_sources", "loss_records")}
    explanation["loss_receipt"] = {
        "source_input_hash": source_input_hash,
        "json_pointer": "/context_manifest/projection_audit",
        "audit_hash": _projection_hash(audit),
        "loss_record_count": len(audit["loss_records"]),
    }
    return compiled, audit


def _prune_optional_planning_context(view: dict[str, Any], *, sources: Iterable[Mapping[str, Any]], character_budget: int, audit_source_hash: str = "", task_token_budget: int | None = None) -> None:
    source_by_id = {str(source.get("asset_version_id") or ""): source for source in sources}
    optional: list[tuple[dict[str, Any], str, str, Mapping[str, Any]]] = []

    def visit(value: Any, path: str, source: Mapping[str, Any]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
                if key in _REQUIRED_PLANNING_FIELDS:
                    continue
                if key in _OPTIONAL_PLANNING_FIELDS:
                    optional.append((value, key, child_path, source))
                else:
                    visit(child, child_path, source)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}", source)

    for segment in view["segments"]:
        visit(segment["content"], "", source_by_id.get(segment["asset_version_id"], segment))
    for parent, key, path, source in reversed(optional):
        measured_view = _planning_view_with_audit_receipt(view, source_input_hash=audit_source_hash)[0] if audit_source_hash else view
        if (task_token_budget is not None and _serialized_byte_count(measured_view) <= min(task_token_budget, _TASK_PROVIDER_SERIALIZATION_BYTES)) or (task_token_budget is None and _serialized_character_count(measured_view) <= character_budget):
            break
        removed = parent.pop(key)
        loss = _loss_record(source, path=path, value=removed, reason="OPTIONAL_CONTEXT_BUDGET")
        view["selection_explanation"]["loss_records"].append(loss)
        _compact_planning_loss_sources(view)
        view["selection_explanation"]["omitted_item_count"] += loss["removed_item_count"]


def _planning_accepted_through_chapter(
    context_bundle: Mapping[str, Any], raw_inputs: Iterable[Mapping[str, Any]]
) -> int:
    observed: list[tuple[str, int]] = []

    def observe(source: str, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise KernelError(
                "PLANNING_PROVIDER_CONTEXT_BOUNDARY_INVALID",
                "Planning accepted boundary must be a non-negative integer",
            )
        observed.append((source, value))

    for raw in raw_inputs:
        role = str(raw.get("role") or "")
        if role not in {"story_state", "canon_snapshot"}:
            continue
        content = raw.get("content")
        if not isinstance(content, Mapping):
            continue
        if "accepted_through_chapter" in content:
            observe(role, content.get("accepted_through_chapter"))
        authority_boundary = content.get("authority_state_boundary")
        if isinstance(authority_boundary, Mapping) and (
            "accepted_through_chapter" in authority_boundary
        ):
            observe(
                role + ".authority_state_boundary",
                authority_boundary.get("accepted_through_chapter"),
            )
    search = context_bundle.get("narrative_search")
    if isinstance(search, Mapping) and search:
        observe("narrative_search", search.get("accepted_through_chapter"))
    realization = context_bundle.get("realization_reference_contract")
    if isinstance(realization, Mapping) and "accepted_through_chapter" in realization:
        observe(
            "realization_reference_contract",
            realization.get("accepted_through_chapter"),
        )
    boundaries = {boundary for _, boundary in observed}
    if len(boundaries) > 1:
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_BOUNDARY_CONFLICT",
            "Planning frozen Authority inputs disagree on the accepted boundary",
        )
    return next(iter(boundaries), 0)


def _planning_chapter(context_bundle: Mapping[str, Any]) -> int:
    edition_scope = context_bundle.get("edition_execution") or {}
    if edition_scope:
        chapter = edition_scope.get("chapter")
        if type(chapter) is not int or chapter < 1:
            raise KernelError("EDITION_PLANNING_SCOPE_INVALID", "Edition context requires its exact positive chapter position")
        return chapter
    logical_key = str(context_bundle.get("logical_key") or "")
    parts = logical_key.split(":")
    if len(parts) >= 2 and parts[0] == "chapter" and parts[1].isdigit():
        return int(parts[1])
    return 0


def _planning_selectors(
    raw_inputs: Iterable[Mapping[str, Any]], *, chapter: int, stage: str, task_capacity: bool = False,
) -> frozenset[str]:
    references: set[str] = set()

    def visit(value: Any, *, field: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, field=str(key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item, field=field)
            return
        if value in (None, ""):
            return
        text = str(value).strip()
        if field == "entity_key":
            references.add(text)
            for component in text.split("|"):
                _, separator, identity = component.partition("=")
                if separator and identity:
                    references.add(identity)
        elif field.endswith(_REFERENCE_FIELD_SUFFIXES):
            references.add(text)

    for raw in raw_inputs:
        role = str(raw.get("role") or "")
        if role in {"story_state", "canon_snapshot"}:
            continue
        content = raw.get("content")
        if not isinstance(content, Mapping):
            continue
        projected, _, _ = _project_planning_content(stage=stage, role=role, content=content, chapter=chapter, selectors=frozenset(), task_capacity=task_capacity)
        visit(projected)
    return frozenset(references)


def project_world_planning_window(inputs: Iterable[Mapping[str, Any]], *, chapter: int, window: int, context_policy_version: str = "") -> list[dict[str, Any]]:
    result = []
    for item in inputs:
        content = deepcopy(item["content"])
        if item["role"] == "chapter_group_plan":
            content["chapter_function_matrix"] = [row for row in content.get("chapter_function_matrix", []) if chapter <= int(row["chapter_number"]) < chapter + window]
        losses: list[dict[str, Any]] = []
        projected, omitted, truncated = _project_planning_content(stage="chapter_plan.generate", role=item["role"], content=content, chapter=0 if item["role"] == "chapter_group_plan" else chapter, selectors=frozenset(), loss_records=losses, source=item, task_capacity=context_policy_version == "world-production-policy.v4")
        explanation = {"loss_records": losses}
        _compact_planning_loss_sources({"selection_explanation": explanation})
        result.append({"role": item["role"], "asset_version_id": item["asset_version_id"], "content_hash": item["content_hash"], "content": projected, "omitted_items": omitted, "truncated_characters": truncated, **explanation})
    return result


def _project_planning_content(
    *,
    stage: str,
    role: str,
    content: Mapping[str, Any],
    chapter: int,
    selectors: frozenset[str],
    loss_records: list[dict[str, Any]] | None = None,
    source: Mapping[str, Any] | None = None,
    task_capacity: bool = False,
    typed_arc_sources: bool = False,
    typed_volume_sources: bool = False,
    planning_window: list[int] | None = None,
    foundation_projection: bool = False,
) -> tuple[dict[str, Any], int, int]:
    from novel_forge.modules.story_design_authority.author_input import without_author_private
    content = without_author_private(content)
    if role == "creative_brief":
        from novel_forge.modules.creative.input_selection import narrative_brief
        return narrative_brief(content), 0, 0
    if role == "previous_chapter_outcome":
        return _compact(_pick(content, "chapter_number", "scene_outcomes", "arc_evidence", "realization_evidence", "reader_state_observations")), 0, 0
    if role.startswith("change_evidence:") and content.get("schema_version") == "longform-prose-review.v1":
        return {"authority": "REVIEW_JUDGMENT_NOT_ACCEPTED_FACT", "report": deepcopy(dict(content)),
                "accepted_history_mutation_allowed": False, "plan_change_requires_authority_approval": True}, 0, 0
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS

    payload = content.get("candidate_payload", content)
    if stage in FOUNDATION_GENERATORS:
        if not isinstance(payload, Mapping):
            raise KernelError("FOUNDATION_PROVIDER_CONTEXT_INVALID", "Foundation context must be structured")
        if foundation_projection:
            projected = deepcopy(dict(payload))
            omitted = 0
            prefix = "/candidate_payload" if "candidate_payload" in content else ""
            def omit(parent: dict[str, Any], key: str, path: str, reason: str) -> None:
                nonlocal omitted
                if key not in parent:
                    return
                value = parent.pop(key)
                record = _loss_record(source or {}, path=prefix + path, value=value, reason=reason)
                omitted += record["removed_item_count"]
                if loss_records is not None:
                    loss_records.append(record)
            for key in ("constraint_envelope", "foundation_parent_bindings", "execution_evidence"):
                omit(projected, key, "/" + key, "HOST_PROTOCOL_RETAINED_IN_FROZEN_SOURCE")
            if role == "creative_foundation":
                search = projected.get("narrative_search_projection")
                if isinstance(search, dict):
                    for key in ("selection_summary", "strategy_fingerprint", "repetition_keys"):
                        omit(search, key, "/narrative_search_projection/" + key, "COMPARISON_METADATA_NOT_STORY_INPUT")
                style = projected.get("style_profile")
                if isinstance(style, dict):
                    omit(style, "original_examples", "/style_profile/original_examples", "PROSE_EXAMPLE_OUTSIDE_FOUNDATION_DESIGN")
            return _compact(projected), omitted, 0
        return _compact({key: value for key, value in payload.items() if key not in {"constraint_envelope", "foundation_parent_bindings", "execution_evidence"}}), 0, 0
    if role == "creative_foundation" and isinstance(payload, Mapping) and "narrative_intent" in payload:
        from novel_forge.modules.story_design_authority.intent import NarrativeIntent
        target = {"book_plan.generate": "BOOK", "volume_plan.generate": "VOLUME", "arc_plan.generate": "ARC", "chapter_group_plan.generate": "NEAR_TERM", "chapter_plan.generate": "CHAPTER"}[stage]
        return NarrativeIntent.from_mapping(payload["narrative_intent"]).route(target=target), 0, 0
    if role == "world_bible" and isinstance(payload, Mapping) and "world_foundation" in payload:
        from novel_forge.modules.worldbuilding.foundation import WorldFoundation
        WorldFoundation.from_mapping(payload["world_foundation"])
        world = deepcopy(payload["world_foundation"])
        if (_serialized_byte_count(world) > _TASK_PROVIDER_SERIALIZATION_BYTES if task_capacity else _serialized_character_count(world) > _MAX_PROVIDER_CONTEXT_CHARACTERS):
            raise KernelError("WORLD_FOUNDATION_SCOPE_TOO_BROAD", "compile a smaller world scope before Provider admission")
        return {"authority": "QUALIFIED_DESIGN_CONSTRAINTS", "world_foundation": world}, 0, 0
    if role.startswith("narrative_governance_action:") and content.get("contract_version") == "causal-planning-action.v1":
        plan = content["causal_plan"]
        selected_id = plan["selected_candidate_id"]
        selected = [item for item in plan["candidate_futures"] if item.get("candidate_id") == selected_id]
        return {
            "contract_version": "causal-direction-context.v1", "authority": "PLANNING_PROPOSAL",
            "reality_revision_id": plan["reality_revision_id"], "plan_digest": plan["plan_digest"],
            "selected_direction": selected,
            "preparation_required": [debt for debt in plan["causal_debts"] if debt["status"] == "PREPARATION_REQUIRED"],
            "preserve_accepted_history": True,
        }, 0, 0
    if role == "story_state" and content.get("contract_version") == (
        "story-state-snapshot-v2"
    ):
        facts = project_narrative_state_facts(
            compact_current_state_facts(dict(content)),
            projection={"state_entity_refs": sorted(selectors), **({"contract_version": "chapter-task-narrative-projection-v2"} if task_capacity else {})},
            chapter=chapter,
        )
        return (
            {
                "contract_version": "planning-state-projection-v1",
                "accepted_through_chapter": int(
                    content.get("accepted_through_chapter") or 0
                ),
                "facts": facts,
            },
            0,
            0,
        )
    if role == "canon_snapshot" and content.get("contract_version") == (
        "canon-snapshot-v2"
    ):
        facts = project_narrative_state_facts(
            compact_canon_facts(dict(content)),
            projection={"state_entity_refs": sorted(selectors), **({"contract_version": "chapter-task-narrative-projection-v2"} if task_capacity else {})},
            chapter=chapter,
        )
        return (
            {
                "contract_version": "planning-canon-projection-v1",
                "accepted_through_chapter": int(
                    content.get("accepted_through_chapter") or 0
                ),
                "facts": facts,
            },
            0,
            0,
        )

    compacted = _compact(content)
    omitted = 0

    def record_loss(field: str, value: Any, reason: str) -> None:
        nonlocal omitted
        if value is None or value == "" or value == [] or value == {}:
            return
        omitted += len(value) if isinstance(value, (list, tuple)) else 1
        if loss_records is not None:
            loss_records.append(_loss_record(source or {"role": role}, path="/" + field, value=value, reason=reason))

    typed_role = "arc_plans" if typed_arc_sources and role.startswith(("related_arc:", "dependent_arc:")) else role
    if typed_volume_sources and role.startswith("arc_scope_volume:"):
        if not isinstance(source, Mapping) or not (
            source.get("asset_type") == "volume_plan" or (
                source.get("asset_type") == "planning_generation_candidate"
                and content.get("planning_scope") == "VOLUME"
                and content.get("generator_operation_name") == "volume_plan.generate")):
            raise KernelError("PLANNING_PROVIDER_CONTEXT_VIEW_INVALID", "Arc volume source must retain its typed VolumePlan identity")
        typed_role = "volume_plan"
    allowed_fields = _PLANNING_ROLE_FIELDS.get(typed_role)
    if allowed_fields is not None:
        admitted_fields = {*allowed_fields, *_REQUIRED_PLANNING_FIELDS, *_OPTIONAL_PLANNING_FIELDS}
        for field, value in compacted.items():
            if field not in admitted_fields:
                record_loss(field, value, "OUTSIDE_TARGET_ROLE")
        compacted = {
            field: deepcopy(compacted[field])
            for field in sorted(admitted_fields)
            if field in compacted
        }
    if role == "chapter_group_plan" and chapter:
        matrix = compacted.get("chapter_function_matrix") or []
        compacted["chapter_function_matrix"] = [
            item
            for item in matrix
            if isinstance(item, Mapping)
            and int(item.get("chapter_number") or 0) == chapter
        ]
        record_loss("chapter_function_matrix", [item for item in matrix if item not in compacted["chapter_function_matrix"]], "OUTSIDE_NARRATIVE_SCOPE")
    for field in ("narrative_segments", "arc_segments"):
        values = compacted.get(field)
        if (chapter or planning_window) and isinstance(values, list):
            local = [
                item
                for item in values
                if isinstance(item, Mapping)
                and (_ranges_overlap(planning_window, item.get("chapter_range")) if planning_window
                     else _chapter_in_range(chapter, item.get("chapter_range")))
            ]
            record_loss(field, [item for item in values if item not in local], "OUTSIDE_NARRATIVE_SCOPE")
            compacted[field] = local
    return compacted, omitted, 0


def _chapter_in_range(chapter: int, value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and int(value[0]) <= chapter <= int(value[1])
    )


def _ranges_overlap(window: list[int], value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
        and all(type(item) is int for item in value)
        and value[0] <= value[1] and value[0] <= window[1] and window[0] <= value[1])


def build_provider_knowledge_view(
    knowledge: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in knowledge:
        content = item.get("content")
        if not isinstance(content, (Mapping, list, str)):
            raise KernelError(
                "CHAPTER_PROVIDER_KNOWLEDGE_VIEW_INVALID",
                "selected Knowledge requires provider-safe content",
            )
        identity = str(
            item.get("content_hash")
            or item.get("ref")
            or item.get("artifact_ref")
            or ""
        )
        if not identity:
            raise KernelError(
                "CHAPTER_PROVIDER_KNOWLEDGE_VIEW_INVALID",
                "selected Knowledge requires immutable identity",
            )
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(
            {
                "ref": str(item.get("ref") or item.get("artifact_ref") or ""),
                "version": str(item.get("version") or ""),
                "content": _compact(content),
            }
        )
        if _serialized_character_count(selected) > _MAX_PROVIDER_KNOWLEDGE_CHARACTERS:
            raise KernelError(
                "CHAPTER_PROVIDER_KNOWLEDGE_BUDGET_EXCEEDED",
                "task-selected Knowledge exceeds its deterministic size boundary; "
                "retrieve a smaller MKAOS projection",
            )
    return selected


def _task(stage: str, **values: Any) -> dict[str, Any]:
    return {
        "contract_version": "provider-task-view-v1",
        "stage": stage,
        **{key: value for key, value in values.items() if value not in (None, {}, [])},
    }


def _pick(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {
        key: _compact(value[key])
        for key in keys
        if value.get(key) not in (None, "", {}, [])
    }


def _prose(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, Mapping) else {}
    return {
        key: deepcopy(source[key])
        for key in ("chapter", "title", "text")
        if source.get(key) not in (None, "")
    }


def _compact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _compact(item)
            for key, item in value.items()
            if key not in _OPERATIONAL_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_compact(item) for item in value]
    return deepcopy(value)


def _serialized_character_count(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _serialized_byte_count(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _selectors(
    projection: Mapping[str, Any], task_view: Mapping[str, Any]
) -> frozenset[str]:
    values: set[str] = set()
    for key in (
        "character_ids",
        "arc_refs",
        "fact_refs",
        "belief_refs",
        "disclosure_refs",
        "state_entity_refs",
        "obligation_refs",
        "world_rule_refs",
    ):
        for item in projection.get(key) or ():
            text = str(item).strip()
            if text:
                values.add(text)
    plan = task_view.get("chapter_plan")
    if isinstance(plan, Mapping):
        for participant in plan.get("character_participation") or ():
            if isinstance(participant, Mapping):
                values.update(
                    str(item)
                    for key in (
                        "character_id",
                        "trajectory_refs",
                        "known_fact_ids",
                        "unknown_fact_ids",
                        "belief_refs",
                    )
                    for item in (
                        participant.get(key)
                        if isinstance(participant.get(key), list)
                        else [participant.get(key)]
                    )
                    if item
                )
    return frozenset(values)


def _state_fact_relevant(
    fact: Mapping[str, Any],
    selectors: frozenset[str],
    chapter: int,
) -> bool:
    state_kind = str(fact.get("state_kind") or "")
    state = fact.get("state") or {}
    if state_kind == "narrative_obligation" and isinstance(state, Mapping):
        status = str(state.get("status") or "").upper()
        priority = str(state.get("priority") or "").upper()
        window = state.get("target_window") or {}
        due = (
            isinstance(window, Mapping)
            and str(window.get("status") or "") == "SCHEDULED"
            and int(window.get("to_chapter") or 0) <= chapter
        )
        if status not in {"FULFILLED", "CANCELLED"} and (
            priority in {"HIGH", "CRITICAL"} or due
        ):
            return True
    if not selectors:
        return False
    return bool(selectors & _state_fact_references(fact))


def _state_fact_references(fact: Mapping[str, Any]) -> frozenset[str]:

    references: set[str] = set()

    def visit(value: Any, *, field: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                visit(item, field=str(key))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                visit(item, field=field)
            return
        if value in (None, ""):
            return
        text = str(value).strip()
        if not text:
            return
        if field == "entity_key":
            references.add(text)
            for component in text.split("|"):
                _, separator, identity = component.partition("=")
                if separator and identity:
                    references.add(identity)
            return
        if field.endswith(_REFERENCE_FIELD_SUFFIXES):
            references.add(text)

    visit(
        {
            "entity_key": fact.get("entity_key"),
            "source_event_id": fact.get("source_event_id"),
            "state": fact.get("state") or {},
        }
    )
    return frozenset(references)


__all__ = [
    "build_provider_context_view",
    "build_provider_knowledge_view",
    "build_provider_task_view",
    "build_task_narrative_projection",
    "project_narrative_state_facts",
]


def _scene_epistemic_scopes(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    known = {
        item["character_id"]: set(item.get("known_fact_ids", []))
        for item in plan.get("character_participation", [])
    }
    result = []
    for scene in plan.get("scene_plan", []):
        if not scene.get("scene_id"):
            continue
        actors = set(scene.get("participants", [])) | {
            scene.get("pov_character_id", "")
        }
        facts = set(scene.get("accessible_knowledge", []))
        result.append(
            {
                "scene_id": scene["scene_id"],
                "character_fact_refs": {
                    actor: sorted(facts & known.get(actor, set()))
                    for actor in sorted(actors)
                    if actor
                },
            }
        )
    return result


def _cross_chapter_task(inputs: Mapping[str, Any]) -> dict[str, Any]:
    window = inputs.get("cross_chapter_window")
    if window is None:
        return {}
    from novel_forge.modules.review.diagnostics import prose_hash
    from novel_forge.modules.review.prose_window import CROSS_CHAPTER_CATEGORIES, validate_window
    validate_window(window)
    candidate = inputs.get("revision") or inputs.get("draft") or {}
    source_kind = "selected working prose, which grants no Canon or formal acceptance" if window.get("source_isolation") == "SELECTED_PROSE_NO_CANON_AUTHORITY" else "accepted prose"
    return {
        "cross_chapter_window": deepcopy(window),
        "cross_chapter_categories": sorted(CROSS_CHAPTER_CATEGORIES),
        "target_identity": {"asset_version_id": inputs["target_candidate_asset_version_id"], "text_hash": prose_hash(str(candidate.get("text") or ""))},
        "review_objective": f"Diagnose cross-chapter continuity using only covered {source_kind}. Sources are read-only; never repair history or turn a Review into Canon. Locate literal target and source Unicode spans with exact identities. Assess retelling, action/space, causal cost, motivation, relationship and voice. Distinguish intentional recap, motif, reinterpretation, new POV, information gain and motivated change. Aesthetic or uncertain judgment cannot block. No issue is a valid result. Return structured evidence, not chain-of-thought. ReReview must disposition every prior code and preservation dimension; reuse lineage_code only for that same problem. No claims about excluded prose.",
    }


def project_longform_prose_review_context_input(asset_type: str, content: Mapping[str, Any]) -> dict[str, Any]:
    if asset_type != "longform_prose_review_window" or content.get("schema_version") not in {"longform-prose-window.v1", "longform-prose-window.v2", "longform-prose-window.v3"}:
        raise KernelError("LONGFORM_PROSE_CONTEXT_INVALID", "Only a frozen source-bound prose window may enter longform review")
    return {key: content[key] for key in ("schema_version", "manifest_digest", "window", "policy", "source_isolation")}


def _build_longform_prose_review_context_view(context_bundle: Mapping[str, Any]) -> dict[str, Any]:
    if context_bundle.get("schema_version") != "novelos.longform_prose_review_context_bundle.v2":
        raise KernelError("LONGFORM_PROSE_CONTEXT_INVALID", "typed longform prose context is required")
    inputs = context_bundle.get("selected_inputs") or []
    if len(inputs) != 1 or inputs[0].get("asset_type") != "longform_prose_review_window":
        raise KernelError("LONGFORM_PROSE_CONTEXT_INVALID", "exactly one bounded prose window is required")
    projection = inputs[0]["projection"]
    if projection["policy"].get("reading_mode") == "BODY_FIRST":
        if any("creative_baseline" in span or "work_intent_status" in span
               for span in projection["window"]["spans"]):
            raise KernelError("LONGFORM_PROSE_CONTEXT_INVALID", "Body-first reading cannot receive design inputs")
        return {
            "contract_version": "provider-context-view-v3", "stage": "longform_prose_review",
            "frozen_prose": projection,
            "instruction": "先阅读所提供的正文，不推定作者设计、题材或市场目标。记录正文呈现的目标、想跳读的具体段落、人物选择、处境变化与具体续读期待；用给定维度和精确Unicode引用记录观察。区分阅读感受、客观错误和证据不足，不能把个人偏好当成文学资格门禁。不能判断未提供的设计承诺是否兑现，也不能归因于未提供的计划或Writer输入。若返回repair，无法从正文确定的源头用UNKNOWN/INVESTIGATE，不为结构不足提出扩写。所有结果为模型审读意见，不是真人反馈、作者接纳或市场效果。不得修改正文、Canon或计划。",
        }
    if projection["schema_version"] == "longform-prose-window.v1":
        # COMPATIBILITY: queued v1 windows retain their original frozen request semantics.
        return {"contract_version": "provider-context-view-v2", "stage": "longform_prose_review", "frozen_prose": inputs[0]["projection"], "instruction": "审读实际提供的中文玄幻/武侠正文。逐项检查结构与冲突模式重复、人物目标和关系停滞、铺垫推进兑现、声线表达、弧级节奏、动机与代价。合理变化、有意重复、未到兑现期和证据不足必须区分。只引用给定原文 Unicode code-point 坐标和精确 quote；不把摘要或未提供正文视为已读。同一问题沿证据复用 lineage_id，不能按 category 合并。若窗口含 relation_hypothesis，它只是文本锚点检索得到的未核验关系假设；ISSUE 或 INTENTIONAL 关系判断必须分别引用两个给定片段，区分因果、人物认知、承诺、伏笔与偶然重词，无法核验时输出 INSUFFICIENT_EVIDENCE。所有结论只是待确认审稿意见。不得修改正文、Canon 或计划。"}
    diagnosis_instruction = ("Distinguish language, Scene organization, Chapter structure, character trajectory and upper plot root causes. "
        "Attribute a problem to prose, frozen plan commitments, or UNKNOWN. A plan defect requires FUTURE_REPLAN through native "
        "Plan Change/Book Replan, never rewriting delivered prose or inventing facts. Prose defects select the smallest justified "
        "local, Scene or Chapter repair. Uncertain causes require INVESTIGATE. State a concrete revision goal, preserve strengths "
        "and give observable resolution criteria; no universal conflict or genre formula. "
        if projection["policy"].get("diagnosis_contract") == "prose-root-cause.v1" else "")
    return {
        "contract_version": "provider-context-view-v3", "stage": "longform_prose_review",
        "frozen_prose": projection,
        **({"diagnosis_instruction": diagnosis_instruction} if diagnosis_instruction else {}),
        "instruction": "审读实际提供的原书正文，按每个来源章节冻结的 creative_baseline 检查题材、风格、受众、人物、结构与已选技法。作者有意的稳定、观察、开放结尾或重复不是默认缺陷；选择了变化、压力、伏笔或兑现时才检查相应承诺。UNKNOWN_LEGACY_BASELINE 表示作品目标未知，只判断可由原文证明的客观问题，不能推定玄幻、武侠、转化或商业节奏。逐项区分客观错误、作品目标偏差与审美建议；未到兑现期、合理变化及证据不足不能要求补写。只引用给定原文 Unicode code-point 坐标和精确 quote，不把摘要或未提供正文视为已读。同一问题沿证据复用 lineage_id，不能按 category 合并。relation_hypothesis 是未核验关系假设，ISSUE 或 INTENTIONAL 判断必须分别引用两个给定片段，无法核验时输出 INSUFFICIENT_EVIDENCE。所有结论只是待确认审稿意见，不得修改正文、Canon 或计划。",
    }


def _realization_source_review(draft):
    contract = draft.get("realization_contract") or {}
    if contract.get("contract_version") != "scene-realization-composition.v3":
        return {}
    return {"realization_source_evidence": {"accepted_sources": deepcopy(contract["accepted_sources"]),
        "information_flow": deepcopy(contract["information_flow"]),
        "candidate_uses": [{key: deepcopy(row[key]) for key in ("slot_id", "used_fact_ids", "character_source_uses")} for row in draft["scene_artifacts"]],
        "review_requirement": "Read the actual prose to check actor ownership, observation/communication before dependent use, future leakage and testimony versus objective fact. These declared references are evidence, not proof of occurrence or successful realization. Accepted source versions are read-only; planned sources are not accepted history."}}


def _pack_text_fragments(value):
    if not isinstance(value, list) or len(value) < 2:
        return None
    position, ends, texts = None, [], []
    for item in value:
        if (not isinstance(item, Mapping) or set(item) != {'start', 'end', 'text', 'text_hash'}
            or type(item['start']) is not int or type(item['end']) is not int or not isinstance(item['text'], str)
            or not 0 <= item['start'] < item['end'] or item['end'] - item['start'] != len(item['text'])
            or position is not None and item['start'] != position
            or item['text_hash'] != 'sha256:' + hashlib.sha256(item['text'].encode()).hexdigest()):
            return None
        position = item['end']
        ends.append(position)
        texts.append(item['text'])
    return {'start': value[0]['start'], 'ends': ends, 'text': ''.join(texts)}


def _expand_text_fragments(value):
    if (not isinstance(value, Mapping) or set(value) != {'start', 'ends', 'text'}
        or type(value['start']) is not int or value['start'] < 0 or not isinstance(value['text'], str)
        or not isinstance(value['ends'], list) or len(value['ends']) < 2):
        raise KernelError('PROVIDER_EXACT_REFERENCE_INVALID', 'Text fragments require an exact Unicode source and boundaries')
    position, result = value['start'], []
    for end in value['ends']:
        if type(end) is not int or not position < end <= value['start'] + len(value['text']):
            raise KernelError('PROVIDER_EXACT_REFERENCE_INVALID', 'Text fragment boundaries must be contiguous and ordered')
        text = value['text'][position-value['start']:end-value['start']]
        result.append({'start': position, 'end': end, 'text': text,
            'text_hash': 'sha256:' + hashlib.sha256(text.encode()).hexdigest()})
        position = end
    if position != value['start'] + len(value['text']):
        raise KernelError('PROVIDER_EXACT_REFERENCE_INVALID', 'Text fragments cannot discard trailing source characters')
    return result


def compile_exact_context_references(view, *, structured_transport=False):
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    marker = "__exact_value_ref__"
    overrides, removed, json_string = "__exact_value_overrides__", "__exact_value_removed_keys__", "__canonical_json_string__"
    fragments = '__text_fragments__'
    seen, dictionaries, count, delta_count, json_count, fragment_count = {}, [], 0, 0, 0, 0
    def encode(value, path):
        nonlocal count, delta_count, json_count, fragment_count
        if isinstance(value, Mapping) and any(key in value for key in (marker, overrides, removed, json_string, fragments)):
            raise KernelError("PROVIDER_EXACT_REFERENCE_COLLISION", "Reserved reference syntax occurs in source content")
        identity = _canonical_exact_reference_value(value)
        large = len(identity.encode("utf-8")) >= 256
        if large and identity in seen:
            count += 1
            return {marker: seen[identity]}
        if isinstance(value, Mapping):
            result = {key: encode(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1")) for key, item in sorted(value.items())}
            if structured_transport and large:
                best, size = result, len(_canonical_exact_reference_value(result).encode("utf-8"))
                for original, pointer in dictionaries:
                    if pointer.startswith(path + "/"):
                        continue
                    changes = {key: result[key] for key, item in sorted(value.items()) if key not in original or original[key] != item}
                    deletions = sorted(set(original) - set(value))
                    candidate = {marker: pointer, **({overrides: changes} if changes else {}), **({removed: deletions} if deletions else {})}
                    candidate_size = len(_canonical_exact_reference_value(candidate).encode("utf-8"))
                    if candidate_size < size:
                        best, size = candidate, candidate_size
                if best is not result:
                    delta_count += 1
                    result = best
                dictionaries.append((value, path))
        elif isinstance(value, list):
            packed = _pack_text_fragments(value) if structured_transport else None
            if packed is not None:
                result = {fragments: packed}
                fragment_count += 1
            else:
                result = [encode(item, path + "/" + str(index)) for index, item in enumerate(value)]
        elif structured_transport and isinstance(value, str) and path.endswith("/safe_summary"):
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            if isinstance(parsed, Mapping) and _canonical_exact_reference_value(parsed) == value:
                result = {json_string: encode(parsed, path + "/" + json_string)}
                json_count += 1
            else:
                result = value
        else:
            result = value
        if large:
            seen.setdefault(identity, path)
        return result
    encoded = encode(view, "")
    if expand_exact_context_references(encoded) != view:
        raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "Exact context references did not reconstruct the complete source")
    proof = {"contract_version": "planning-exact-value-reference.v1", "source_context_hash": canonical_hash(view),
        "encoded_context_hash": canonical_hash(encoded), "reference_count": count, "decoded_equal": True}
    if structured_transport:
        proof.update(transport_version="provider-structured-exact-reference.v2" if fragment_count else "provider-structured-exact-reference.v1",
            delta_reference_count=delta_count, canonical_json_string_count=json_count, text_fragment_group_count=fragment_count)
    return encoded, proof


def _canonical_exact_reference_value(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def expand_exact_context_references(encoded):
    decoded = {}
    marker, overrides, removed, json_string = "__exact_value_ref__", "__exact_value_overrides__", "__exact_value_removed_keys__", "__canonical_json_string__"
    fragments = '__text_fragments__'
    def remember(value, path):
        decoded[path] = value
        if isinstance(value, Mapping):
            for key, item in value.items():
                remember(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                remember(item, path + "/" + str(index))
    def expand(value, path):
        if isinstance(value, Mapping) and marker in value:
            target = value[marker]
            if not set(value).issubset({marker, overrides, removed}) or not isinstance(target, str) or target not in decoded:
                raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "References must identify an earlier complete value within the same Context; external, forward and cyclic references are forbidden")
            result = deepcopy(decoded[target])
            if overrides in value or removed in value:
                changes, deletions = value.get(overrides, {}), value.get(removed, [])
                if (not isinstance(result, dict) or not isinstance(changes, Mapping) or not isinstance(deletions, list)
                    or any(not isinstance(key, str) or key not in result for key in deletions) or len(set(deletions)) != len(deletions)):
                    raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "Exact object deltas require a complete earlier object and valid removed keys")
                for key in deletions:
                    del result[key]
                for key, item in result.items():
                    if key not in changes:
                        remember(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
                for key, item in changes.items():
                    result[key] = expand(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, Mapping) and fragments in value:
            if set(value) != {fragments}:
                raise KernelError('PROVIDER_EXACT_REFERENCE_INVALID', 'Text fragments cannot contain other protocol fields')
            result = _expand_text_fragments(value[fragments])
        elif isinstance(value, Mapping) and json_string in value:
            if set(value) != {json_string}:
                raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "Canonical JSON string encoding cannot contain extra fields")
            parsed = expand(value[json_string], path + "/" + json_string)
            if not isinstance(parsed, Mapping):
                raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "Canonical JSON string requires an object")
            result = _canonical_exact_reference_value(parsed)
        elif isinstance(value, Mapping):
            if overrides in value or removed in value:
                raise KernelError("PROVIDER_EXACT_REFERENCE_INVALID", "Exact object deltas require an earlier reference")
            result = {key: expand(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1")) for key, item in value.items()}
        elif isinstance(value, list):
            result = [expand(item, path + "/" + str(index)) for index, item in enumerate(value)]
        else:
            result = value
        remember(result, path)
        return result
    return expand(encoded, "")
