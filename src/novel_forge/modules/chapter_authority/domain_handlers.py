from __future__ import annotations

import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.longform_narrative import normalize_frozen_arc_plan
from novel_forge.modules.mkaos_authority.domain import (
    resolve_book_knowledge_access_policy,
    validate_book_knowledge_access_policy,
)
from novel_forge.modules.context_builder.domain import (
    ContextCandidate,
    build_authority_context_bundle,
    validate_task_context_sources,
)
from novel_forge.modules.review.domain import (
    evaluate_rereview_result,
    evaluate_review_result,
)
from novel_forge.modules.revision.domain import apply_revision_result
from novel_forge.modules.canon_graph.domain import (
    build_canon_update,
    extract_canon_candidates,
)
from novel_forge.modules.content_quality_loop.domain import evaluate_quality_evidence
from novel_forge.modules.chapter_quality_authority import build_chapter_quality_evidence
from novel_forge.modules.publishing.domain import (
    build_export_blob_manifest,
    finalize_blob_verified_release,
    prepare_internal_release,
)
from novel_forge.modules.chapter_authority.provider_views import (
    build_task_narrative_projection,
)
from novel_forge.modules.chapter_authority.execution_artifacts import (
    validate_chapter_execution_intent,
    validate_chapter_memo,
)

from novel_forge.modules.canon_graph.background import world_observation_constraints
from novel_forge.modules.narrative_state.information import disclosed_fact_projection


def build_chapter_plan(
    *,
    chapter: int,
    title: str,
    premise: str,
    trace_id: str,
) -> dict[str, Any]:
    if chapter <= 0 or not premise.strip():
        raise KernelError(
            "CHAPTER_PLAN_INPUT_INVALID", "chapter and premise are required"
        )
    return {
        "chapter": chapter,
        "title": title.strip() or f"Chapter {chapter}",
        "premise": premise.strip(),
        "objective": "force a consequential choice and preserve continuity",
        "beats": ["promise tested", "public choice", "visible cost"],
        "closing_hook": "the cost creates a new obligation",
        "trace_id": trace_id,
        "blueprint_version": "chapter-blueprint-v1",
    }


def _retrieval_result_context_reference(content: dict[str, Any]) -> dict[str, Any]:
    """INVARIANT: Render replay identity without duplicating retrieved text in the prompt.

    The immutable RetrievalResult remains a frozen Operation input. Context Build
    consumes its full content to materialize exact source candidates, while this
    protected reference preserves replay identity and ranking evidence without
    spending the Draft token budget on a second copy of selected/rejected payloads.
    """
    return {
        "type": content.get("type"),
        "contract_version": content.get("contract_version"),
        "accepted_boundary": dict(content.get("accepted_boundary") or {}),
        "intent_asset_version_id": content.get("intent_asset_version_id"),
        "intent_fingerprint": content.get("intent_fingerprint"),
        "memo_asset_version_id": content.get("memo_asset_version_id"),
        "memo_fingerprint": content.get("memo_fingerprint"),
        "query_plan": dict(content.get("query_plan") or {}),
        "query_plan_fingerprint": content.get("query_plan_fingerprint"),
        "retrieval_policy": dict(content.get("retrieval_policy") or {}),
        "semantic_status": dict(content.get("semantic_status") or {}),
        "selected_documents": [
            {
                "retrieval_document_id": item.get("retrieval_document_id"),
                "source_asset_version_id": item.get("source_asset_version_id"),
                "source_content_hash": item.get("source_content_hash"),
                "projection_hash": item.get("projection_hash"),
                "retrieval_score": item.get("retrieval_score"),
                "retrieval_reasons": list(item.get("retrieval_reasons") or ()),
            }
            for item in content.get("selected_documents") or ()
            if isinstance(item, dict)
        ],
        "result_fingerprint": content.get("result_fingerprint"),
    }


def build_context_bundle(
    *,
    plan: dict[str, Any],
    plan_asset_version_id: str,
    plan_content_hash: str,
    project_id: str = "local-system",
    created_by_operation_id: str = "legacy-direct-call",
    governed_candidates: list[dict[str, Any]] | None = None,
    version_refs: dict[str, Any] | None = None,
    token_budget: int = 6000,
    context_profile_version: str = "draft-context-profile-v2",
    required_asset_types: tuple[str, ...] = (),
    book_id: str = "",
    target_capability_id: str = "prose.chapter.draft",
    capability_pack_snapshot_ref: str = "",
    execution_intent: dict[str, Any] | None = None,
    execution_intent_asset_version_id: str = "",
    chapter_memo: dict[str, Any] | None = None,
    chapter_memo_asset_version_id: str = "",
    retrieval_result: dict[str, Any] | None = None,
    retrieval_result_asset_version_id: str = "",
    frozen_arc_plans: dict[str, dict[str, Any]] | None = None,
    knowledge_access_policy: dict[str, Any] | None = None,
    context_model_call: Any = None,
    compression_input_tokens: int = 0,
) -> dict[str, Any]:
    _require_keys(plan, "chapter", "premise")
    if context_profile_version not in {"draft-context-profile-v2", "draft-context-profile-v3", "draft-context-profile-v4"}:
        raise ValueError("unsupported frozen draft Context profile version")
    scoped_book_id = book_id or f"book:{project_id}"
    access = (
        validate_book_knowledge_access_policy(
            knowledge_access_policy,
            project_id=project_id,
            book_id=scoped_book_id,
        )
        if knowledge_access_policy
        else resolve_book_knowledge_access_policy(
            production_profile={},
            project_id=project_id,
            book_id=scoped_book_id,
        )
    )
    objective = str(
        plan.get("chapter_objective") or plan.get("objective") or ""
    ).strip()
    scene_sequence = list(plan.get("scene_sequence") or plan.get("beats") or [])
    if not objective or not scene_sequence:
        raise KernelError(
            "CHAPTER_HANDLER_INPUT_INVALID",
            "authoritative ChapterPlan objective and scene sequence are required",
        )
    if execution_intent:
        execution_intent = validate_chapter_execution_intent(
            execution_intent,
            expected_plan_asset_version_id=plan_asset_version_id,
            expected_plan_content_hash=plan_content_hash,
        )
    if chapter_memo:
        if not execution_intent:
            raise KernelError(
                "CHAPTER_EXECUTION_CONTEXT_INTENT_MISSING",
                "Draft Context cannot consume ChapterMemo without ExecutionIntent",
            )
        chapter_memo = validate_chapter_memo(
            chapter_memo,
            intent=execution_intent,
            intent_asset_version_id=execution_intent_asset_version_id,
        )
    refs = {**(version_refs or {}), "chapter_plan_version": plan_asset_version_id}
    ref_boundary = {
        "accepted_through_chapter": max(0, int(plan["chapter"]) - 1),
        "story_state_snapshot_version": refs.get(
            "story_state_snapshot_version",
            refs.get("story_state_snapshot_versions", ""),
        ),
        "canon_snapshot_version": refs.get("canon_snapshot_version", ""),
    }
    declared_boundaries = {
        json.dumps(
            dict(item.get("accepted_boundary") or {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        for item in (governed_candidates or [])
        if dict(item.get("accepted_boundary") or {})
    }
    if len(declared_boundaries) > 1:
        raise KernelError(
            "CHAPTER_CONTEXT_BOUNDARY_CONFLICT",
            "frozen Context candidates disagree on their accepted boundary",
        )
    assembly_boundary = (
        json.loads(next(iter(declared_boundaries)))
        if declared_boundaries
        else ref_boundary
    )
    if (
        assembly_boundary.get("accepted_through_chapter")
        != ref_boundary["accepted_through_chapter"]
    ):
        raise KernelError(
            "CHAPTER_CONTEXT_BOUNDARY_INVALID",
            "frozen Context boundary differs from the Chapter execution cursor",
        )
    for key in ("story_state_snapshot_version", "canon_snapshot_version"):
        if ref_boundary[key] and assembly_boundary.get(key) != ref_boundary[key]:
            raise KernelError(
                "CHAPTER_CONTEXT_BOUNDARY_INVALID",
                "frozen Context boundary differs from its version references",
            )
    candidates = [
        ContextCandidate(
            asset_version_id=str(item["asset_version_id"]),
            asset_type=str(item["asset_type"]),
            project_id=str(item["project_id"]),
            book_id=str(item.get("book_id") or ""),
            estimated_tokens=int(item.get("estimated_tokens", 0)),
            relevance_score=float(item.get("relevance_score", item.get("score", 0))),
            qualification=str(item.get("qualification", "ELIGIBLE")),
            governance_status=str(item.get("governance_status", "CLEAR")),
            source_use_mode=str(
                item.get("source_use_mode", item.get("allowed_use", "generation"))
            ),
            source_risk=int(item.get("source_risk", 0)),
            raw_source=bool(item.get("raw_source", False)),
            content_digest=str(item.get("content_digest", "")),
            policy_version=str(
                item.get("policy_version", item.get("source_policy_version", ""))
            ),
            invalidation_keys=tuple(item.get("invalidation_keys", [])),
            narrative_function=str(item.get("narrative_function", "")),
            safe_summary=str(item.get("safe_summary", "")),
            structured_facts=tuple(item.get("structured_facts", [])),
            allowed_use=str(item.get("allowed_use", "generation")),
            compression_method=str(item.get("compression_method", "safe_summary")),
            physical_asset_type=str(
                item.get("physical_asset_type") or item.get("asset_type") or ""
            ),
            authority_freshness=str(item.get("authority_freshness") or "CURRENT"),
            semantic_projection=bool(item.get("semantic_projection", True)),
            context_class=str(item.get("context_class") or "RETRIEVABLE"),
            memory_layer=str(item.get("memory_layer") or ""),
            retrieval_reasons=tuple(item.get("retrieval_reasons") or ()),
            retrieval_scores=dict(item.get("retrieval_scores") or {}),
            provenance=dict(
                item.get("provenance")
                or {
                    "authority_asset_version_id": str(item["asset_version_id"]),
                    "source_content_hash": str(item.get("content_digest") or ""),
                    "projection_source": "frozen_context_candidate",
                }
            ),
            compression_trace=tuple(item.get("compression_trace") or ()),
            logical_context_kind=str(
                item.get("logical_context_kind") or item.get("asset_type") or ""
            ),
            source_identity=str(
                item.get("source_identity") or item.get("asset_version_id") or ""
            ),
            logical_narrative_identity=str(
                item.get("logical_narrative_identity") or ""
            ),
            semantic_representation_identity=str(
                item.get("semantic_representation_identity") or ""
            ),
            source_revision=str(
                item.get("source_revision") or item.get("content_digest") or ""
            ),
            accepted_boundary=dict(item.get("accepted_boundary") or {}),
            section=str(item.get("section") or "NARRATIVE"),
            bucket=str(item.get("bucket") or item.get("asset_type") or "GENERAL"),
            required=bool(item.get("required", False)),
            representation_status=str(item.get("representation_status") or "ACTIVE"),
            read_generation_id=str(item.get("read_generation_id") or ""),
            active_read_generation_id=str(item.get("active_read_generation_id") or ""),
            truncation_strategy=str(item.get("truncation_strategy") or ""),
            truncation_version=str(item.get("truncation_version") or ""),
        )
        for item in (governed_candidates or [])
    ]
    plan_safe_summary = (
        f"Chapter {plan['chapter']} objective: {objective}. "
        f"Premise: {plan['premise']}. Scene sequence: {scene_sequence}."
    )
    plan_structured_facts = (
        {"kind": "chapter", "value": plan["chapter"]},
        {"kind": "objective", "value": objective},
    )
    rendered_plan_context = json.dumps(
        {
            "safe_summary": plan_safe_summary,
            "structured_facts": plan_structured_facts,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    candidates.insert(
        0,
        ContextCandidate(
            asset_version_id=plan_asset_version_id,
            asset_type="chapter_plan",
            project_id=project_id,
            book_id=book_id,
            estimated_tokens=max(1, len(rendered_plan_context) // 4),
            relevance_score=1.0,
            content_digest=plan_content_hash,
            invalidation_keys=(f"chapter-plan:{plan_asset_version_id}",),
            narrative_function="current_chapter_plan",
            safe_summary=plan_safe_summary,
            structured_facts=plan_structured_facts,
            context_class="PROTECTED",
            provenance={"authority": "PlanningAuthority"},
            accepted_boundary=dict(assembly_boundary),
        ),
    )
    for asset_type, asset_version_id, content in (
        (
            "chapter_execution_intent",
            execution_intent_asset_version_id,
            execution_intent,
        ),
        ("chapter_memo", chapter_memo_asset_version_id, chapter_memo),
        ("retrieval_result", retrieval_result_asset_version_id, retrieval_result),
    ):
        if bool(asset_version_id) != bool(content):
            raise KernelError(
                "CHAPTER_EXECUTION_CONTEXT_INCOMPLETE",
                "Context requires both execution artifact content and AssetVersion identity",
            )
        if not content:
            continue
        rendered_content = (
            _retrieval_result_context_reference(content)
            if asset_type == "retrieval_result"
            else {key: value for key, value in content.items() if key != "execution_evidence"}
        )
        if asset_type == "chapter_memo" and (content.get("craft_strategy") or {}).get("schema_version") in {"narrative-craft-strategy.v2", "narrative-craft-strategy.v3"}:
            strategy = content["craft_strategy"]
            if not execution_intent_asset_version_id or strategy != (execution_intent or {}).get("craft_strategy"):
                raise KernelError("CRAFT_STRATEGY_DRIFT", "Memo may reference only the identical protected execution-intent strategy")
            rendered_content.pop("craft_strategy")
            rendered_content["craft_strategy_reference"] = {
                "asset_version_id": execution_intent_asset_version_id,
                "json_pointer": "/craft_strategy", "strategy_digest": strategy["strategy_digest"],
                "projection": "EXACT_DUPLICATE_REPLACED_BY_PROTECTED_CONTEXT_REFERENCE",
            }
        if asset_type == "chapter_execution_intent":
            rendered_content["active_obligations"] = [
                disclosed_fact_projection(item)
                for item in content.get("active_obligations") or ()
            ]
        rendered = json.dumps(
            rendered_content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        candidates.insert(
            1,
            ContextCandidate(
                asset_version_id=asset_version_id,
                asset_type=asset_type,
                project_id=project_id,
                book_id=book_id,
                estimated_tokens=max(1, len(rendered) // 4),
                relevance_score=1.0,
                content_digest=str(
                    content.get("intent_fingerprint")
                    or content.get("memo_fingerprint")
                    or content.get("result_fingerprint")
                    or ""
                ),
                invalidation_keys=(f"{asset_type}:{asset_version_id}",),
                narrative_function=asset_type,
                safe_summary=rendered,
                structured_facts=(),
                context_class="PROTECTED",
                provenance={"authority": "ChapterWorkflow", "working_artifact": True},
                accepted_boundary=dict(assembly_boundary),
            ),
        )
    if execution_intent and execution_intent_asset_version_id:
        from novel_forge.modules.mkaos_authority.craft_context_projection import reference_duplicate_craft_uses
        candidates = reference_duplicate_craft_uses(candidates, intent=execution_intent, intent_asset_version_id=execution_intent_asset_version_id)
    clean_history = (retrieval_result or {}).get("query_plan", {}).get("writer_projection_version") == "accepted-writer-history.v2"
    if clean_history:
        from novel_forge.modules.context_builder.story_projection import clean_context_candidates
        candidates = clean_context_candidates(candidates, stage="draft")
    task_receipt = None
    if context_profile_version == "draft-context-profile-v4":
        from novel_forge.modules.context_builder.task_compression import compile_task_context, validate_task_dependencies
        task = {
            "stage": "draft", "chapter": int(plan["chapter"]),
            **({"writer_projection_version": "accepted-writer-history.v2"} if clean_history else {}),
            "plan": plan, "accepted_boundary": dict(assembly_boundary),
            "memo_fingerprint": str((chapter_memo or {}).get("memo_fingerprint") or ""),
            "preserve_quotes": list(plan.get("preserve_quotes") or ()),
        }
        admitted_source_ids = validate_task_context_sources(
            project_id=project_id, book_id=book_id, candidates=candidates,
            token_budget=token_budget, required_asset_types=tuple(required_asset_types),
            accepted_boundary=dict(assembly_boundary), knowledge_access_policy=access,
        )
        candidates, task_receipt = compile_task_context(
            candidates, task=task, token_budget=token_budget,
            required_asset_types=tuple(required_asset_types),
            model_call=context_model_call, compression_input_tokens=compression_input_tokens,
            admitted_source_ids=admitted_source_ids,
        )
    governed = build_authority_context_bundle(
        project_id=project_id,
        book_id=book_id,
        stage="draft",
        created_by_operation_id=created_by_operation_id,
        context_profile_version=context_profile_version,
        candidates=candidates,
        token_budget=token_budget,
        version_refs=refs,
        required_asset_types=required_asset_types,
        narrative_position={
            "book_id": book_id,
            "volume_id": str(plan.get("volume_id") or ""),
            "arc_id": str(plan.get("arc_id") or ""),
            "sequence_id": str(plan.get("sequence_id") or ""),
            "chapter": int(plan["chapter"]),
            "sequence_ordinal": int(plan.get("sequence_ordinal") or 0),
        },
        target_capability_id=target_capability_id,
        capability_pack_snapshot_ref=capability_pack_snapshot_ref,
        authority_state_boundary=assembly_boundary,
        accessible_knowledge_fact_ids=_provider_accessible_fact_ids(plan),
        required_long_distance_fact_ids=tuple(
            str(item)
            for item in plan.get("required_long_distance_fact_ids") or ()
            if str(item)
        ),
        knowledge_access_policy=access,
        task_context_receipt=task_receipt,
    )
    if task_receipt is not None:
        selected_ids = set(governed["selected_asset_version_ids"])
        validate_task_dependencies([candidate for candidate in candidates if candidate.asset_version_id in selected_ids], task=task)
        governed["task_context_receipt"] = task_receipt
    task_narrative_projection = build_task_narrative_projection(plan, task_scoped=context_profile_version == "draft-context-profile-v4")
    mission = dict((execution_intent or {}).get("chapter_mission") or {})
    if execution_intent and not mission:
        raise KernelError(
            "CHAPTER_EXECUTION_CONTEXT_MISSION_MISSING",
            "Draft Context requires the compiled Chapter Mission",
        )
    mission_outcomes = dict(mission.get("required_outcomes") or {})
    mission_boundaries = dict(mission.get("knowledge_and_disclosure_boundaries") or {})
    mission_locked = bool(execution_intent)
    return {
        **governed,
        "chapter": plan["chapter"],
        "goal": objective,
        "actual_context": {
            "premise": plan["premise"],
            "scene_sequence": scene_sequence,
            "beats": scene_sequence,
            "stage_context_view": governed["stage_context_view"],
            "copyright_boundary": "project-owned and abstract eligible context only",
        },
        "forbidden_source_count": 0,
        "task_narrative_projection": task_narrative_projection,
        "chapter_execution_expectations": {
            **(
                {
                    "world_observation_constraints": world_observation_constraints(
                        plan["constraint_envelope"]["world_preparation"]
                    )
                }
                if (plan.get("constraint_envelope") or {}).get("world_execution")
                else {}
            ),
            **(
                {
                    "world_execution": dict(
                        plan["constraint_envelope"]["world_execution"]
                    )
                }
                if (plan.get("constraint_envelope") or {}).get("world_execution")
                else {}
            ),
            **(
                {
                    "world_preparation": dict(
                        plan["constraint_envelope"]["world_preparation"]
                    )
                }
                if (plan.get("constraint_envelope") or {}).get("world_preparation")
                else {}
            ),
            "contract_version": "chapter-execution-expectations-v3",
            "chapter_plan_asset_version_id": plan_asset_version_id,
            "chapter_execution_intent_asset_version_id": (
                execution_intent_asset_version_id
            ),
            "mission_fingerprint": str(mission.get("mission_fingerprint") or ""),
            "why_this_chapter_exists": str(
                mission.get("why_this_chapter_exists") if mission_locked else objective
            ),
            "entry_state": dict(mission.get("entry_state") or {}),
            "required_beats": list(
                (execution_intent or {}).get("required_beats")
                or mission.get("required_beats")
                or ()
            ),
            "required_state_transitions": list(
                mission_outcomes.get("state_transitions", [])
                if mission_locked
                else plan.get("required_state_transitions") or []
            ),
            "disclosures": list(
                mission_boundaries.get("disclosures", [])
                if mission_locked
                else plan.get("disclosures") or []
            ),
            "knowledge_boundaries": list(
                mission_boundaries.get("knowledge_boundaries", [])
                if mission_locked
                else plan.get("knowledge_boundaries") or []
            ),
            "expected_exit_state": dict(
                mission.get("expected_exit_state", {})
                if mission_locked
                else plan.get("expected_exit_state") or {}
            ),
            "required_arc_contributions": list(
                mission.get("arc_contributions", [])
                if mission_locked
                else plan.get("required_arc_contributions") or []
            ),
            "forbidden_changes": dict(mission.get("forbidden_changes") or {}),
            "reader_effect": dict(mission.get("reader_effect") or {}),
            "hook_intent": dict(mission.get("hook_intent") or {}),
            "unresolved_obligation_intent": dict(
                mission.get("unresolved_obligation_intent") or {}
            ),
            "narrative_composition": dict(mission.get("narrative_composition") or {}),
            "arc_working_set": dict(mission.get("arc_working_set") or {}),
            "narrative_realization": dict(mission.get("narrative_realization") or {}),
            "frozen_arc_plans": [
                normalize_frozen_arc_plan(
                    arc_plan_version_id=arc_id,
                    content=content,
                )
                for arc_id, content in sorted((frozen_arc_plans or {}).items())
            ],
        },
        "provider_projection_contract_version": "minimum-sufficient-context-v3",
    }


def _provider_accessible_fact_ids(plan: dict[str, Any]) -> set[str]:
    from .provider_views import provider_accessible_fact_ids
    return provider_accessible_fact_ids(plan)


def normalize_draft_result(
    *,
    plan: dict[str, Any],
    context_asset_version_id: str,
    context_content_hash: str = "",
    context_content: dict[str, Any] | None = None,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    work_requirements: bool = False,
    core_policy: str = "EXPLICIT_SKELETON_V1", information_policy: str = "ENTRY_ONLY_V1",
    realization_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .realization_composition import prose_from_output

    text = prose_from_output(result, separators=result.get("scene_separators"))
    if not text.strip():
        raise KernelError("CHAPTER_MODEL_OUTPUT_INVALID", "draft result has no text")
    lineage: dict[str, Any] = {}
    if context_content is not None:
        manifest = context_content.get("context_manifest")
        execution = context_content.get("chapter_execution")
        context_fingerprint = (
            str(manifest.get("context_fingerprint") or "")
            if isinstance(manifest, dict)
            else ""
        )
        retrieval_result_asset_version_id = (
            str(execution.get("retrieval_result_asset_version_id") or "")
            if isinstance(execution, dict)
            else ""
        )
        retrieval_result_fingerprint = (
            str(execution.get("retrieval_result_fingerprint") or "")
            if isinstance(execution, dict)
            else ""
        )
        if not all(
            (
                context_content_hash,
                context_fingerprint,
                retrieval_result_asset_version_id,
                retrieval_result_fingerprint,
            )
        ):
            raise KernelError(
                "CHAPTER_DRAFT_CONTEXT_LINEAGE_INVALID",
                "draft requires exact ContextBundle and RetrievalResult fingerprints",
            )
        lineage = {
            "context_bundle_content_hash": context_content_hash,
            "context_fingerprint": context_fingerprint,
            "retrieval_result_asset_version_id": retrieval_result_asset_version_id,
            "retrieval_result_fingerprint": retrieval_result_fingerprint,
        }
    from .realization_composition import compile_realization_contract, integrate_realization
    from .chapter_plan_views import build_draft_style_view

    composition = integrate_realization(
        contract=realization_contract or compile_realization_contract(
            plan,
            build_draft_style_view(
                context_content or {}, work_requirements=work_requirements
            ),
            core_policy=core_policy,
            information_policy=information_policy,
        ),
        artifacts=result.get("scene_artifacts", []),
        text=text,
        separators=result.get("scene_separators"),
    )
    return {
        **composition,
        "chapter": plan["chapter"],
        "title": plan["title"],
        "text": text,
        "context_bundle_id": context_asset_version_id,
        **lineage,
        "provider_evidence": dict(provider_evidence),
    }


def normalize_review_result(
    *,
    draft: dict[str, Any],
    draft_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
    knowledge_targets: list[dict[str, Any]] | None = None,
    cross_chapter_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from novel_forge.modules.review.craft import craft_review_targets

    reviewed = evaluate_review_result(
        project_id=project_id,
        target_asset_version_id=draft_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        chapter=int(draft["chapter"]),
        result=result,
        provider_evidence=provider_evidence,
        prose_text=str(draft.get("text") or ""),
        knowledge_targets=knowledge_targets,
        cross_chapter_window=cross_chapter_window,
        craft_targets=craft_review_targets(draft),
    )
    if "creative_baseline" in draft:
        from .chapter_plan_views import validate_creative_baseline

        reviewed["creative_baseline_digest"] = validate_creative_baseline(
            draft["creative_baseline"]
        )["baseline_digest"]
    return reviewed


def normalize_revision_result(
    *,
    draft: dict[str, Any],
    review: dict[str, Any],
    draft_asset_version_id: str,
    review_asset_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
) -> dict[str, Any]:
    return apply_revision_result(
        project_id=project_id,
        draft=draft,
        review=review,
        draft_asset_version_id=draft_asset_version_id,
        review_asset_version_id=review_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        result=result,
        provider_evidence=provider_evidence,
    )


def normalize_rereview_result(
    *,
    draft_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    context_bundle_version_id: str,
    result: dict[str, Any],
    provider_evidence: dict[str, Any],
    project_id: str,
    knowledge_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reviewed = evaluate_rereview_result(
        project_id=project_id,
        original_draft_version_id=draft_asset_version_id,
        initial_review_version_id=review_asset_version_id,
        revision_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        initial_review=review,
        revision=revision,
        result=result,
        provider_evidence=provider_evidence,
        knowledge_targets=knowledge_targets,
    )
    if "creative_baseline" in revision:
        from .chapter_plan_views import validate_creative_baseline

        digest = validate_creative_baseline(revision["creative_baseline"])[
            "baseline_digest"
        ]
        if review.get("creative_baseline_digest") != digest:
            raise KernelError(
                "REVIEW_CREATIVE_BASELINE_DRIFT",
                "ReReview cannot reuse diagnoses under a different creative baseline",
            )
        reviewed["creative_baseline_digest"] = digest
    return reviewed


def build_canon_patch(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
    extraction: dict[str, Any] | None = None,
    context_bundle: dict[str, Any] | None = None,
    reader_observation_lineage: bool = False,
) -> dict[str, Any]:
    historical_state, identity_profiles = canon_history(context_bundle or {})
    work_extraction = (extraction or {}).get("canon_extraction_contract_version") in {
        "canon-semantic-extraction-v6", "canon-grounded-extraction-v2"
    }
    accepted_boundary = ((context_bundle or {}).get("chapter_execution") or {}).get("accepted_boundary") or {}
    confirmed_empty_baseline = (
        work_extraction
        and accepted_boundary.get("accepted_through_chapter") == int(revision.get("chapter", 0)) - 1
        and bool(accepted_boundary.get("canon_snapshot_asset_version_id"))
        and bool(accepted_boundary.get("story_state_asset_version_id"))
    )
    if int(revision.get("chapter", 0)) > 1 and not historical_state.get(
        "canon_snapshot"
    ) and not confirmed_empty_baseline:
        raise KernelError(
            "CANON_HISTORY_BASELINE_REQUIRED",
            "chapters after the first require an explicit CanonSnapshot baseline",
        )
    return build_canon_update(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        extraction=extraction,
        historical_state=historical_state,
        planned_execution=dict(
            (context_bundle or {}).get("chapter_execution_expectations") or {}
        ),
        identity_profiles=identity_profiles,
        reader_observation_lineage=reader_observation_lineage,
    )


def canon_history(context_bundle):
    historical_state: dict[str, list[dict[str, Any]]] = {}
    identity_profiles: list[dict[str, Any]] = []
    state_aliases = {
        "canon_snapshot": "canon_snapshot",
        "character_state": "character_state",
        "character_state_snapshot": "character_state",
        "relationship_state": "relationship_state",
        "relationship_state_snapshot": "relationship_state",
        "timeline_snapshot": "timeline_snapshot",
        "foreshadow_state": "foreshadow_state",
        "foreshadow_snapshot": "foreshadow_state",
        "reader_promise": "reader_promise",
        "promise_ledger_snapshot": "reader_promise",
        "reward_ledger": "reward_ledger",
        "reward_ledger_snapshot": "reward_ledger",
        "world_rule": "world_rule",
        "world_rule_snapshot": "world_rule",
        "power_state": "power_state",
        "power_state_snapshot": "power_state",
        "plot_thread": "plot_thread",
        "plot_thread_snapshot": "plot_thread",
        "resource_state": "resource_state",
        "resource_state_snapshot": "resource_state",
    }
    for segment in (context_bundle or {}).get("context_segments", []):
        asset_type = str(segment.get("asset_type") or "")
        facts = list(segment.get("structured_facts", []))
        if asset_type in {"character_cast", "character_card"}:
            identity_profiles.extend(
                dict(fact)
                for fact in facts
                if isinstance(fact, dict)
                and fact.get("kind") == "character_identity_contract"
            )
            continue
        if asset_type == "story_state_snapshot":
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                state_kind = {
                    "canon_fact": "canon_snapshot",
                    "timeline_event": "timeline_snapshot",
                    "reward_event": "reward_ledger",
                }.get(
                    str(fact.get("state_kind") or ""),
                    str(fact.get("state_kind") or ""),
                )
                state = fact.get("state")
                if not state_kind or not isinstance(state, dict):
                    continue
                identity = _entity_key_components(str(fact.get("entity_key") or ""))
                historical_state.setdefault(state_kind, []).append(
                    {
                        "asset_version_id": segment.get("asset_version_id", ""),
                        "source_event_id": fact.get("source_event_id", ""),
                        "entity_key": fact.get("entity_key", ""),
                        "entity_version": int(fact.get("entity_version") or 0),
                        **identity,
                        **state,
                    }
                )
            continue
        if asset_type == "canon_snapshot":
            historical_state.setdefault("canon_snapshot", []).extend(
                {
                    "asset_version_id": segment.get("asset_version_id", ""),
                    "source_event_id": fact.get("source_event_id", ""),
                        "entity_key": fact.get("entity_key", ""),
                    "entity_version": int(fact.get("entity_version") or 0),
                    **dict(fact.get("state") or {}),
                }
                for fact in facts
                if isinstance(fact, dict) and isinstance(fact.get("state"), dict)
            )
            continue
        state_kind = state_aliases.get(asset_type)
        if state_kind is None:
            continue
        historical_state.setdefault(state_kind, []).append(
            {
                "asset_version_id": segment.get("asset_version_id", ""),
                "facts": facts,
                **(facts[0] if len(facts) == 1 and isinstance(facts[0], dict) else {}),
            }
        )
    world_binding = ((context_bundle or {}).get("chapter_execution_expectations") or {}).get("world_preparation") or {}
    frozen_world = (world_binding.get("frozen_source") or {}).get("reality")
    if frozen_world:
        for kind, entries in frozen_world["current_state"].items():
            historical_kind = {"canon_fact": "canon_snapshot", "timeline_event": "timeline_snapshot", "reward_event": "reward_ledger"}.get(kind, kind)
            historical_state[historical_kind] = [
                {**entry, **entry["state"], **_entity_key_components(entry["entity_key"]), "asset_version_id": world_binding["action"]["source"]["asset_version_id"]}
                for entry in entries
            ]
    return historical_state, identity_profiles


def _entity_key_components(entity_key: str) -> dict[str, str]:

    components: dict[str, str] = {}
    for raw in entity_key.split("|"):
        key, separator, value = raw.partition("=")
        if separator and key and value:
            components[key] = value
    return components


def build_canon_extraction(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    project_id: str,
    context_bundle_version_id: str,
    provider_extraction: dict[str, Any] | None = None,
    work_requirements: bool = False,
) -> dict[str, Any]:
    return extract_canon_candidates(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        provider_extraction=provider_extraction,
        work_requirements=work_requirements,
    )


def build_quality_report(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    review: dict[str, Any] | None = None,
    review_asset_version_id: str = "legacy-review-version",
    project_id: str = "local-system",
    context_bundle_version_id: str = "legacy-context-bundle",
    context_bundle: dict[str, Any] | None = None,
    evidence_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    effective_review = review or {
        "issues": [
            {
                "code": code,
                "severity": "blocking",
                "status": "OPEN",
                "qualification": "ELIGIBLE",
            }
            for code in revision.get("resolved_issue_codes", [])
        ]
    }
    fixture = not bool(
        effective_review.get("provider_evidence", {}).get("real_model_call")
    )
    authority_reports = (
        build_chapter_quality_evidence(
            project_id=project_id,
            revision=revision,
            revision_asset_version_id=revision_asset_version_id,
            context_bundle=context_bundle or {},
            canon=canon,
            fixture=fixture,
        )
        if evidence_reports is None
        else list(evidence_reports)
    )
    aggregate = evaluate_quality_evidence(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        review=effective_review,
        review_asset_version_id=review_asset_version_id,
        canon=canon,
        canon_asset_version_id=canon_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
        evidence_reports=authority_reports,
    )
    return {**aggregate, "evidence_reports": authority_reports}


def build_publish_gate(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle: dict[str, Any],
    context_bundle_version_id: str,
    project_id: str,
    work_admission: bool = False,
) -> dict[str, Any]:
    return prepare_internal_release(
        project_id=project_id,
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        quality=quality,
        quality_asset_version_id=quality_asset_version_id,
        review=review,
        review_asset_version_id=review_asset_version_id,
        canon=canon,
        canon_asset_version_id=canon_asset_version_id,
        context_bundle=context_bundle,
        context_bundle_version_id=context_bundle_version_id,
        work_admission=work_admission,
    )


def build_export_package(
    *,
    revision: dict[str, Any],
    revision_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
) -> dict[str, Any]:
    return build_export_blob_manifest(
        revision=revision,
        revision_asset_version_id=revision_asset_version_id,
        publish_gate=quality,
        publish_gate_asset_version_id=quality_asset_version_id,
    )


def build_final_release_gate(
    *,
    project_id: str,
    export_package: dict[str, Any],
    export_asset_version_id: str,
    export_blobs: tuple[dict[str, Any], ...],
    publish_gate: dict[str, Any],
    publish_gate_asset_version_id: str,
    quality: dict[str, Any],
    quality_asset_version_id: str,
    review: dict[str, Any],
    review_asset_version_id: str,
    canon: dict[str, Any],
    canon_asset_version_id: str,
    context_bundle_version_id: str,
) -> dict[str, Any]:
    return finalize_blob_verified_release(
        project_id=project_id,
        export_package=export_package,
        export_asset_version_id=export_asset_version_id,
        export_blobs=export_blobs,
        publish_gate=publish_gate,
        publish_gate_asset_version_id=publish_gate_asset_version_id,
        quality=quality,
        quality_asset_version_id=quality_asset_version_id,
        review=review,
        review_asset_version_id=review_asset_version_id,
        canon=canon,
        canon_asset_version_id=canon_asset_version_id,
        context_bundle_version_id=context_bundle_version_id,
    )


def _require_keys(payload: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise KernelError(
            "CHAPTER_HANDLER_INPUT_INVALID",
            f"missing chapter fields: {', '.join(missing)}",
        )


__all__ = [
    "build_canon_patch",
    "build_canon_extraction",
    "build_chapter_plan",
    "build_context_bundle",
    "build_export_package",
    "build_final_release_gate",
    "build_publish_gate",
    "build_quality_report",
    "normalize_draft_result",
    "normalize_review_result",
    "normalize_rereview_result",
    "normalize_revision_result",
]
