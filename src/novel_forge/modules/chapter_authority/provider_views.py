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
    "frozen_inputs",
    "model_call_log_refs",
    "normalized_digest",
    "provider_evidence",
    "provider_receipt_refs",
    "qualification",
    "runtime_result",
    "reducer_applications",
    "source_chapter_plan_asset_version_id",
    "source_chapter_plan_content_hash",
    "source_extensions",
    "stage_context_view",
    "trace_id",
}


def _project_empty_world_selection(selection: Any) -> Any:
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
    return result if _serialized_character_count(result) < _serialized_character_count(selection) else deepcopy(selection)


def build_provider_task_view(stage: str, inputs: Mapping[str, Any]) -> dict[str, Any]:

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
    if stage in {"world_candidates.generate", "world_candidates.evaluate"}:
        task = inputs.get("world_preparation")
        if not isinstance(task, Mapping) or task.get("contract_version") != "world-provider-task.v1" or task.get("fact_mutation_allowed") is not False:
            raise KernelError("WORLD_PROVIDER_TASK_INVALID", "world stages require their exact frozen role projection")
        expected_role = "WORLD_REASONER" if stage == "world_candidates.generate" else "DIRECTOR"
        if task.get("role") != expected_role:
            raise KernelError("WORLD_PROVIDER_ROLE_INVALID", "world stage cannot consume another role's context")
        projected_task = deepcopy(dict(task))
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
        if "narrative_intelligence" in projected_task:
            projected_task["narrative_intelligence"] = _project_empty_world_selection(projected_task["narrative_intelligence"])
        return _task(stage, world_preparation=_compact(projected_task))
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS, FOUNDATION_INPUT_ROLES, foundation_task

    if stage in FOUNDATION_GENERATORS:
        command = inputs.get("planning_command")
        frozen = inputs.get("frozen_inputs")
        task = inputs.get("foundation_task")
        if not isinstance(command, Mapping) or command.get("planning_scope") != "NOT_APPLICABLE" or not isinstance(frozen, list) or {item.get("role") for item in frozen if isinstance(item, Mapping)} != set(FOUNDATION_INPUT_ROLES[stage]) or task != foundation_task(stage):
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
        return _task(
            stage,
            planning_command=_compact(command),
            world_preparation=_compact(inputs.get("world_preparation") or {}),
            frozen_inputs=_compact(frozen_inputs),
            authoritative_narrative_load=_compact(authoritative_load),
            arc_working_set=_compact(arc_working_set),
            narrative_intelligence=_compact(narrative_intelligence),
        )
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
        intent = {key: source[key] for key in (
            "project_id", "chapter", "contract_version", "intent_fingerprint", "source_chapter_plan",
            "accepted_boundary", "chapter_objective", "required_arc_contributions",
            "previous_ending", "scene_plans", "chapter_mission", "required_beats",
        ) if key in source}
        return _task(stage, frozen_intent=without_private_world(intent), authority="CREATIVE_SUGGESTION_ONLY",
                     source_layers={"accepted_facts": "REFERENCED_BY_ACCEPTED_BOUNDARY",
                                    "character_knowledge": "SCENE_KNOWLEDGE_BOUNDARIES",
                                    "planned_outcomes": "INTENT_ONLY_NOT_OBSERVED",
                                    "creative_guidance": "CANDIDATE_SUGGESTIONS"})
    if stage == "draft":
        from novel_forge.modules.canon_graph.background import without_private_world
        from novel_forge.modules.story_design_authority.author_input import without_author_private
        return _task(
            stage,
            chapter_plan=_compact(without_private_world(without_author_private(inputs.get("plan")))),
            style=_compact(inputs.get("style")),
            creative_memo={
                "guidance": deepcopy((inputs.get("chapter_memo") or {}).get("creative_guidance") or {}),
                "scene_directives": deepcopy((inputs.get("chapter_memo") or {}).get("scene_directives") or []),
                "source_memo_fingerprint": str((inputs.get("chapter_memo") or {}).get("memo_fingerprint") or ""),
                "authority": "CREATIVE_SUGGESTION_ONLY",
            },
            realization_contract=deepcopy(inputs.get("realization_contract")),
        )
    if stage == "review":
        return _task(stage, chapter=_prose(inputs.get("draft")), creative_execution=deepcopy((inputs.get("draft") or {}).get("creative_execution") or {}), knowledge_review_targets=deepcopy(inputs.get("knowledge_review_targets") or []), author_design_review_targets=deepcopy(inputs.get("author_design_review_targets") or {}))
    if stage == "revision":
        source = dict(inputs.get("draft") or {})
        payload: dict[str, Any] = {"chapter": _prose(source), "creative_execution": deepcopy(source.get("creative_execution") or {}), "knowledge_checks": deepcopy((inputs.get("review") or {}).get("knowledge_checks") or [])}
        if source.get("author_design_guidance"):
            payload["author_design_review_targets"] = deepcopy(source["author_design_guidance"])
        if source.get("realization_contract"):
            payload["chapter"].pop("text", None)
            payload["realization_contract"] = deepcopy(source["realization_contract"])
            payload["scene_artifacts"] = deepcopy(source["scene_artifacts"])
            payload["composition_digest"] = source["composition_digest"]
        if inputs.get("required_actions") is not None:
            payload["required_actions"] = _compact(inputs.get("required_actions"))
            payload["quality_decision"] = _compact(inputs.get("quality"))
        else:
            from novel_forge.modules.review.diagnostics import open_diagnoses
            payload["review_issues"] = _compact(open_diagnoses(dict(inputs.get("review") or {})))
            if (source.get("realization_contract") or {}).get("contract_version") == "scene-realization-composition.v2":
                payload["targeted_editing"] = {
                    "mode": "DIAGNOSIS_DIRECTED_ONLY",
                    "tasks": [{key: issue[key] for key in ("code", "category", "judgment_kind", "evidence_locator", "revision_goal", "preserve", "acceptance_criteria") if key in issue} for issue in open_diagnoses(dict(inputs.get("review") or {}))],
                    "instructions": "Repair each evidenced problem using its stated criterion. Keep unaffected choices, information boundaries, and voice. An aesthetic suggestion is optional; unknown or unresolved blockers remain open. Read adjacent passages for continuity after a local edit.",
                }
        return _task(stage, **payload)
    if stage == "rereview":
        from novel_forge.modules.review.diagnostics import open_diagnoses
        revision = inputs.get("revision") or inputs.get("draft")
        issues = [
            _compact(item)
            for item in open_diagnoses(dict(inputs.get("review") or {}))
        ]
        return _task(
            stage,
            revised_chapter=_prose(revision),
            creative_execution=deepcopy((revision or {}).get("creative_execution") or {}),
            prior_diagnoses=issues,
            knowledge_review_targets=deepcopy(inputs.get("knowledge_review_targets") or []),
            author_design_review_targets=deepcopy(inputs.get("author_design_review_targets") or {}),
        )
    if stage == "canon_support":
        return _task(stage, final_candidate=_prose(inputs.get("revision")),
                     grounding=deepcopy(inputs.get("grounding")), claims=deepcopy(inputs.get("claims")))
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


def build_task_narrative_projection(plan: Mapping[str, Any]) -> dict[str, Any]:

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
        "contract_version": "chapter-task-narrative-projection-v1",
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
    if projection.get("contract_version") == "chapter-task-narrative-projection-v1":
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
    if len(selected) > _MAX_FACTS_PER_SEGMENT:
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


def build_provider_context_view(
    stage: str,
    context_bundle: Mapping[str, Any],
    task_view: Mapping[str, Any],
) -> dict[str, Any]:

    if stage == "memo":
        intent = task_view.get("frozen_intent") or {}
        if intent.get("intent_fingerprint") != context_bundle.get("intent_fingerprint"):
            raise KernelError("CHAPTER_MEMO_INTENT_DRIFT", "Memo Context differs from frozen Intent")
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
    if stage in {"world_candidates.generate", "world_candidates.evaluate"}:
        task = task_view.get("world_preparation") or {}
        if context_bundle.get("world_preparation") != task:
            raise KernelError(
                "WORLD_CONTEXT_IDENTITY_MISMATCH",
                "world task differs from its frozen role Context",
            )
        selection = task.get("narrative_intelligence") or {}
        if (selection.get("need") or {}).get("condition_sources_receipt") is not None:
            original = context_bundle.get("narrative_intelligence")
            policy = original.get("knowledge_access_policy") if isinstance(original, Mapping) else None
            if (not isinstance(original, Mapping) or not isinstance(policy, Mapping)
                or policy.get("project_id") != context_bundle["project_id"]
                or policy.get("book_id") != context_bundle["book_id"]
                or selection != _compact(_project_empty_world_selection(original))):
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
        author = context_bundle.get("author_design_projection")
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
            if _serialized_character_count(view) > min(_MAX_PROVIDER_CONTEXT_CHARACTERS, token_budget * 4):
                raise KernelError("WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "Protected World author context exceeds its frozen budget; narrow the governed scope")
        frozen = (context_bundle.get("context_manifest") or {}).get("provider_context_view")
        if isinstance(frozen, Mapping) and isinstance(frozen.get("compiled_view"), Mapping) and frozen["compiled_view"].get("stage") == stage:
            if frozen["compiled_view"] != view or frozen.get("content_hash") != _projection_hash(view) or frozen.get("source_input_hash") != planning_context_source_hash(context_bundle):
                raise KernelError("WORLD_CONTEXT_IDENTITY_MISMATCH", "World Provider view differs from its frozen semantic inputs and projection receipt")
        return view
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS

    if stage in _PLANNING_STAGES or stage in FOUNDATION_GENERATORS:
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
    rendered: list[dict[str, Any]] = []
    omitted_facts = 0
    omitted_segments = 0
    for raw in segments:
        if not isinstance(raw, Mapping) or raw.get("allowed_use") == "evidence_only":
            omitted_segments += 1
            continue
        asset_type = str(raw.get("asset_type") or "")
        if stage == "draft" and asset_type in {"chapter_plan", "style_policy"}:
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        if stage.startswith("quality_"):
            # WHY: QualityContext is already a bounded, dimension-specific projection.
            # Rendering Context segments again would duplicate the same semantics.
            omitted_segments += 1
            omitted_facts += len(raw.get("structured_facts") or ())
            continue
        facts = [
            item
            for item in raw.get("structured_facts") or []
            if isinstance(item, Mapping)
        ]
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
                if "disclosure_field_projections" in projection
                else facts
            )
            selected_facts = [
                item
                for item in bounded_facts
                if item.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"
                if _state_fact_relevant(
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
        if len(selected_facts) > _MAX_FACTS_PER_SEGMENT:
            raise KernelError(
                "CHAPTER_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
                "relevant accepted facts exceed the Provider segment budget; "
                "rebuild the governed task projection before dispatch",
            )
        omitted_facts += len(facts) - len(selected_facts)
        summary = str(raw.get("safe_summary") or "").strip()
        if (
            asset_type in _STATE_ASSET_TYPES
            and "disclosure_field_projections" in projection
        ):
            summary = (
                json.dumps(selected_facts, ensure_ascii=False, sort_keys=True)
                if selected_facts
                else ""
            )
        if not summary and not selected_facts:
            omitted_segments += 1
            continue
        if len(rendered) >= _MAX_SEGMENTS:
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
        "contract_version": "provider-context-view-v2",
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
            "policy": "minimum-sufficient-context-v3",
            "included_segment_count": len(rendered),
            "included_fact_count": sum(
                len(item["structured_facts"]) for item in rendered
            ),
            "omitted_segment_count": omitted_segments,
            "omitted_fact_count": omitted_facts,
            "maximum_segments": _MAX_SEGMENTS,
            "maximum_facts_per_segment": _MAX_FACTS_PER_SEGMENT,
            "maximum_serialized_characters": _MAX_PROVIDER_CONTEXT_CHARACTERS,
        },
        "context_correctness_receipt_hash": str(
            (correctness or {}).get("receipt_hash") or ""
        ),
    }
    if _serialized_character_count(view) > _MAX_PROVIDER_CONTEXT_CHARACTERS:
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
            and candidate_content.get("schema_version") == "book-design.v5"
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
                valid = valid and (
                    item.get("asset_type") == expected_asset_type
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
    if _serialized_character_count(view) > _MAX_PROVIDER_CONTEXT_CHARACTERS:
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
) -> dict[str, Any]:
    """INVARIANT: Project one accepted Reader Outcome input without Authority envelopes.

    The Book follow-up command binds a broad recovery lineage, but a Reader judge
    needs only the accepted prose, audience contract, intended experience, and a
    bounded view of current reader-facing state.  Empty projections preserve the
    immutable input reference without sending that asset to the Provider.
    """
    if asset_type == "draft_version":
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
                asset_type, legacy_content
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
    if not any(item["asset_type"] == "draft_version" for item in segments):
        raise KernelError(
            "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID",
            "Reader Outcome Provider View requires accepted chapter prose",
        )
    view = {
        "contract_version": "provider-context-view-v2",
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
            "policy": "minimum-sufficient-reader-outcome-context-v1",
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
    if len(raw_inputs) > _MAX_SEGMENTS:
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD",
            "Planning frozen inputs exceed the bounded segment limit",
        )
    chapter = _planning_chapter(context_bundle)
    selectors = _planning_selectors(raw_inputs, chapter=chapter, stage=stage)
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
        "contract_version": "provider-context-view-v2",
        "stage": stage,
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
            "maximum_facts_per_segment": _MAX_FACTS_PER_SEGMENT,
            "maximum_serialized_characters": _MAX_PROVIDER_CONTEXT_CHARACTERS,
        },
    }
    if context_bundle.get("author_design_projection"):
        view["author_design_projection"] = compile_provider_author_projection(context_bundle["author_design_projection"])
    reference_contract = context_bundle.get("realization_reference_contract")
    if reference_contract is not None:
        if not isinstance(reference_contract, Mapping):
            raise KernelError(
                "PLANNING_PROVIDER_CONTEXT_VIEW_INVALID",
                "Planning realization reference contract must be an object",
            )
        view["realization_reference_contract"] = _compact(reference_contract)
    if repair_context is not None:
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
    character_budget = min(_MAX_PROVIDER_CONTEXT_CHARACTERS, token_budget * 4) if token_budget is not None else _MAX_PROVIDER_CONTEXT_CHARACTERS
    _compact_planning_loss_sources(view)
    source_hash = planning_context_source_hash(context_bundle) if projection_audit is not None else ""
    _prune_optional_planning_context(view, sources=raw_inputs, character_budget=character_budget, audit_source_hash=source_hash)
    if projection_audit is not None:
        view, audit = _planning_view_with_audit_receipt(view, source_input_hash=source_hash)
        projection_audit.update(audit)
    if _serialized_character_count(view) > character_budget:
        raise KernelError(
            "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED",
            "required Planning Provider Context exceeds its budget boundary; narrow the governed scope before sending: "
            + json.dumps({"total": _serialized_character_count(view), "segments": [{"role": item["role"], "characters": _serialized_character_count(item)} for item in projected], "repair": _serialized_character_count(view.get("repair_context", {})), "references": _serialized_character_count(view.get("realization_reference_contract", {}))}, sort_keys=True),
        )
    return view


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


def _prune_optional_planning_context(view: dict[str, Any], *, sources: Iterable[Mapping[str, Any]], character_budget: int, audit_source_hash: str = "") -> None:
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
        if _serialized_character_count(measured_view) <= character_budget:
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
    logical_key = str(context_bundle.get("logical_key") or "")
    parts = logical_key.split(":")
    if len(parts) >= 2 and parts[0] == "chapter" and parts[1].isdigit():
        return int(parts[1])
    return 0


def _planning_selectors(
    raw_inputs: Iterable[Mapping[str, Any]], *, chapter: int, stage: str
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
        projected, _, _ = _project_planning_content(stage=stage, role=role, content=content, chapter=chapter, selectors=frozenset())
        visit(projected)
    return frozenset(references)


def project_world_planning_window(inputs: Iterable[Mapping[str, Any]], *, chapter: int, window: int) -> list[dict[str, Any]]:
    result = []
    for item in inputs:
        content = deepcopy(item["content"])
        if item["role"] == "chapter_group_plan":
            content["chapter_function_matrix"] = [row for row in content.get("chapter_function_matrix", []) if chapter <= int(row["chapter_number"]) < chapter + window]
        losses: list[dict[str, Any]] = []
        projected, omitted, truncated = _project_planning_content(stage="chapter_plan.generate", role=item["role"], content=content, chapter=0 if item["role"] == "chapter_group_plan" else chapter, selectors=frozenset(), loss_records=losses, source=item)
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
) -> tuple[dict[str, Any], int, int]:
    from novel_forge.modules.story_design_authority.author_input import without_author_private
    content = without_author_private(content)
    if role == "previous_chapter_outcome":
        return _compact(_pick(content, "chapter_number", "scene_outcomes", "arc_evidence", "realization_evidence", "reader_state_observations")), 0, 0
    from novel_forge.modules.story_planning_runtime.foundation_generation import FOUNDATION_GENERATORS

    payload = content.get("candidate_payload", content)
    if stage in FOUNDATION_GENERATORS:
        if not isinstance(payload, Mapping):
            raise KernelError("FOUNDATION_PROVIDER_CONTEXT_INVALID", "Foundation context must be structured")
        return _compact({key: value for key, value in payload.items() if key not in {"constraint_envelope", "foundation_parent_bindings", "execution_evidence"}}), 0, 0
    if role == "creative_foundation" and isinstance(payload, Mapping) and "narrative_intent" in payload:
        from novel_forge.modules.story_design_authority.intent import NarrativeIntent
        target = {"book_plan.generate": "BOOK", "volume_plan.generate": "VOLUME", "arc_plan.generate": "ARC", "chapter_group_plan.generate": "NEAR_TERM", "chapter_plan.generate": "CHAPTER"}[stage]
        return NarrativeIntent.from_mapping(payload["narrative_intent"]).route(target=target), 0, 0
    if role == "world_bible" and isinstance(payload, Mapping) and "world_foundation" in payload:
        from novel_forge.modules.worldbuilding.foundation import WorldFoundation
        WorldFoundation.from_mapping(payload["world_foundation"])
        world = deepcopy(payload["world_foundation"])
        if _serialized_character_count(world) > _MAX_PROVIDER_CONTEXT_CHARACTERS:
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
            projection={"state_entity_refs": sorted(selectors)},
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
            projection={"state_entity_refs": sorted(selectors)},
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

    allowed_fields = _PLANNING_ROLE_FIELDS.get(role)
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
        if chapter and isinstance(values, list):
            local = [
                item
                for item in values
                if isinstance(item, Mapping)
                and _chapter_in_range(chapter, item.get("chapter_range"))
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
