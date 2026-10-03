from __future__ import annotations

import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import (
    build_expanded_retrieval_query_plan,
    build_retrieval_query_plan,
    build_retrieval_result,
    build_task_dependency_refs,
)
from novel_forge.modules.chapter_authority.handlers import deterministic_retrieval_coverage_fast_path


def _intent() -> dict[str, object]:
    return {
        "chapter": 9,
        "intent_fingerprint": "sha256:" + "1" * 64,
        "accepted_boundary": {"accepted_through_chapter": 8},
        "required_arc_contributions": [{"arc_plan_version_id": "arc:trust:v3"}],
        "active_obligations": [{"state": {"obligation_id": "promise:return-key"}}],
        "retrieval_graph": {
            "entity_ids": ["key:red"],
            "character_ids": ["character:mei"],
            "relationship_ids": ["relationship:mei-ren"],
        },
    }


def _memo() -> dict[str, object]:
    return {
        "chapter": 9,
        "qualification": "QUALIFIED",
        "memo_fingerprint": "sha256:" + "2" * 64,
        "accepted_boundary": {"accepted_through_chapter": 8},
        "retrieval_queries": ["red key promise", "Mei and Ren trust"],
        "arc_actions": [{"arc_plan_version_id": "arc:trust:v3"}],
        "obligation_actions": [{"obligation_id": "promise:return-key"}],
    }


def _document() -> dict[str, object]:
    return {
        "retrieval_document_id": "retrieval:accepted:7",
        "source_asset_version_id": "draft:accepted:7:v1",
        "source_artifact_type": "best_draft_candidate",
        "source_content_hash": "sha256:" + "3" * 64,
        "projection_hash": "sha256:" + "4" * 64,
        "accepted_from_chapter": 7,
        "accepted_to_chapter": None,
        "memory_layer": "L0",
        "content_text": json.dumps({"text": "Mei returns the red key but Ren no longer trusts the promise."}),
        "postgresql_fts_rank": 0.8,
        "entity_ids": ["key:red"],
        "character_ids": ["character:mei"],
        "relationship_ids": ["relationship:mei-ren"],
        "arc_plan_version_ids": ["arc:trust:v3"],
        "obligation_ids": ["promise:return-key"],
        "temporal_coordinate": {"accepted_chapter": 7},
        "metadata": {"projection_kind": "recent_accepted_prose"},
        "embedding": [1.0, 0.0],
        "embedding_model": "embedding-production-v1",
        "embedding_provider": "production-provider",
        "embedding_dimensions": 2,
        "embedding_route_snapshot_id": "route:embedding:v1",
        "embedding_receipt_id": "receipt:embedding:7",
        "embedding_projection_version": "accepted-retrieval-embedding-v1",
        "candidate_channels": ["FTS", "VECTOR"],
    }


def test_deterministic_fast_path_requires_coverage_and_leaves_budget_to_admission() -> None:
    plan = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    arguments = dict(project_id="project:novel", book_id="book:novel",
                     intent_asset_version_id="intent:v1", memo_asset_version_id="memo:v1",
                     query_plan=plan, documents=[_document()], semantic_status={})
    assert deterministic_retrieval_coverage_fast_path(**arguments, context_token_budget=6000)
    assert deterministic_retrieval_coverage_fast_path(**arguments, context_token_budget=10)
    assert not deterministic_retrieval_coverage_fast_path(**{**arguments, "documents": []}, context_token_budget=6000)
    assert not deterministic_retrieval_coverage_fast_path(**{**arguments, "query_plan": {**plan, "semantic_policy": "REQUIRED"}}, context_token_budget=6000)


def test_memo_is_the_authoritative_retrieval_query_input() -> None:
    plan = build_retrieval_query_plan(intent=_intent(), memo=_memo())

    assert plan["queries"] == ["red key promise", "Mei and Ren trust"]
    assert plan["accepted_boundary"] == {"accepted_through_chapter": 8}
    assert plan["arc_plan_version_ids"] == ["arc:trust:v3"]
    assert plan["obligation_ids"] == ["promise:return-key"]
    assert plan["semantic_policy"] == "FALLBACK_ALLOWED"
    assert plan["contract_version"] == "retrieval-query-plan-v5"
    assert plan["ranking_policy_version"] == "accepted-lexical-first-ranking-v4"
    assert "semantic_rerank_limit" in plan
    assert "semantic_candidate_limit" not in plan
    assert sum(plan["ranking_weights"].values()) == 1.0
    assert plan["result_limit"] == 24
    assert plan["campaign_policy"]["total_round_limit"] == 3
    assert plan["coverage_contract"]["accepted_boundary"] == {
        "accepted_through_chapter": 8
    }


def test_expanded_query_plan_preserves_boundary_cutoff_and_result_limit() -> None:
    base = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    base["candidate_projection_cutoff"] = "2026-09-03T00:00:00+00:00"
    base.pop("query_plan_fingerprint")
    base["query_plan_fingerprint"] = "sha256:" + "a" * 64
    expanded = build_expanded_retrieval_query_plan(
        base_query_plan=base,
        expansion_plan={
            "accepted_boundary": {"accepted_through_chapter": 8},
            "round_number": 1,
            "expansion_plan_fingerprint": "sha256:" + "b" * 64,
            "queries": [
                {
                    "text": "oath under old bridge",
                    "selectors": {"character_ids": ["character:mei"]},
                    "temporal_range": {"from_chapter": 1, "to_chapter": 4},
                }
            ],
        },
    )

    assert expanded["accepted_boundary"] == base["accepted_boundary"]
    assert expanded["candidate_projection_cutoff"] == ("2026-09-03T00:00:00+00:00")
    assert expanded["result_limit"] == 24
    assert expanded["temporal_range"] == {"from_chapter": 1, "to_chapter": 4}
    assert expanded["query_plan_fingerprint"].startswith("sha256:")


def test_task_dependency_refs_bind_fact_aliases_causes_and_foundation_sources() -> None:
    dependencies = build_task_dependency_refs(
        plan={"required_long_distance_fact_ids": ["fact:hook"]},
        current_candidates=[
            {"asset_type": "story_state_snapshot", "asset_version_id": "state:v8",
             "content_hash": "sha256:" + "a" * 64,
             "structured_facts": [{"source_event_id": "event:advance", "entity_key": "fact_id=fact:hook",
                "state": {"proposition_id": "proposition:hook", "world_transition": {"cause_refs": ["event:planting", "foundation:world:v1"]}}},
                {"source_event_id": "quality:internal", "provider_visibility": "INTERNAL_QUALITY_ONLY",
                 "state": {"world_transition": {"cause_refs": ["denied:feedback"]}}}]},
            {"asset_type": "world_bible", "asset_version_id": "world:v1",
             "content_hash": "sha256:" + "b" * 64},
        ],
    )
    assert dependencies["required_refs"] == ["event:planting", "fact:hook", "foundation:world:v1"]
    assert dependencies["protected_fact_aliases"] == ["event:advance", "fact:hook", "foundation:world:v1", "proposition:hook"]
    plan = build_retrieval_query_plan(intent={**_intent(), "active_obligations": []}, memo={**_memo(), "obligation_actions": []}, task_dependency_refs=dependencies)
    assert plan["contract_version"] == "retrieval-query-plan-v6"
    assert plan["task_dependency_refs"] == dependencies
    assert plan["candidate_limit"] == 256 and plan["result_limit"] == 24
    assert "task_dependency_refs" not in build_retrieval_query_plan(intent=_intent(), memo=_memo())


def test_required_task_documents_survive_optional_rank_limit_without_text_truncation() -> None:
    dependencies = build_task_dependency_refs(plan={"required_long_distance_fact_ids": ["fact:hook"]}, current_candidates=[])
    plan = build_retrieval_query_plan(intent={**_intent(), "active_obligations": []}, memo={**_memo(), "obligation_actions": []}, task_dependency_refs=dependencies)
    required = {**_document(), "retrieval_document_id": "required:planting",
                "source_asset_version_id": "required:planting:v1", "accepted_from_chapter": 1,
                "content_text": json.dumps({"text": "A precise planting survives. " * 250}),
                "candidate_channels": ["TASK_DEPENDENCY"],
                "task_dependency_matched_refs": ["fact:hook"],
                "retrieval_reasons": ["required_dependency_planting"],
                "metadata": {"structured_facts": [{"fact_id": "fact:hook"}]}}
    optional = [{**_document(), "retrieval_document_id": f"optional:{index:02d}",
                 "source_asset_version_id": f"optional:{index}:v1"} for index in range(30)]
    result = build_retrieval_result(
        project_id="project:novel", book_id="book:novel", intent_asset_version_id="intent:v1",
        memo_asset_version_id="memo:v1", query_plan=plan, documents=[required, *optional],
        discovery_rejections=[], semantic_status={},
    )
    assert result["contract_version"] == "chapter-retrieval-result-v6"
    assert len(result["selected_documents"]) == 25
    selected = next(item for item in result["selected_documents"] if item["retrieval_document_id"] == "required:planting")
    assert json.loads(selected["safe_summary"]) == json.loads(required["content_text"])
    assert selected["compression_method"] == "none"
    assert "required_task_dependency" in selected["retrieval_reasons"]
    assert "required_dependency_planting" in selected["retrieval_reasons"]


def test_task_dependency_ref_limit_fails_closed() -> None:
    with pytest.raises(KernelError) as failure:
        build_task_dependency_refs(plan={"required_long_distance_fact_ids": [f"fact:{index}" for index in range(2049)]}, current_candidates=[])
    assert failure.value.code == "RETRIEVAL_TASK_DEPENDENCY_LIMIT"


def test_task_obligation_dependencies_select_explicit_due_and_participating_states_only() -> None:
    def obligation(identity, *, status="OPEN", priority="LOW", window=None, linked=(), visibility=""):
        return {"state_kind": "narrative_obligation", "entity_key": f"obligation_id={identity}", "source_event_id": f"event:{identity}",
                "provider_visibility": visibility, "state": {"obligation_id": identity, "status": status, "priority": priority,
                "target_window": window or {"status": "UNSCHEDULED"}, "linked_character_ids": list(linked)}}
    dependencies = build_task_dependency_refs(
        plan={"chapter": 21, "obligation_refs": ["explicit"], "required_obligation_ids": ["required"], "cast": ["character:mei"]},
        current_candidates=[{"asset_type": "story_state_snapshot", "asset_version_id": "state:20", "content_hash": "sha256:" + "a" * 64,
                             "structured_facts": [obligation("explicit"), obligation("due", window={"status": "SCHEDULED", "to_chapter": 21}),
                                                  obligation("high", priority="HIGH"), obligation("related", linked=("character:mei",)),
                                                  obligation("unrelated"), obligation("finished", status="FULFILLED", priority="HIGH"),
                                                  obligation("internal", priority="HIGH", visibility="INTERNAL_QUALITY_ONLY")]}],
    )
    assert dependencies["required_obligation_ids"] == ["due", "explicit", "high", "related", "required"]
    assert dependencies["required_refs"] == []
    assert dependencies["source_bindings"] == [{"asset_version_id": "state:20", "content_hash": "sha256:" + "a" * 64}]
    switched = build_task_dependency_refs(plan={"chapter": 21}, current_candidates=[
        {"asset_type": "story_state_snapshot", "asset_version_id": "state:20", "content_hash": "sha256:" + "a" * 64,
         "structured_facts": [obligation("related", linked=("character:mei",))]},
    ])
    assert switched["required_obligation_ids"] == []
    with pytest.raises(KernelError) as unbounded:
        build_task_dependency_refs(plan={"required_obligation_ids": [f"obligation:{index}" for index in range(2049)]}, current_candidates=[])
    assert unbounded.value.code == "RETRIEVAL_TASK_DEPENDENCY_LIMIT"


def test_only_established_planned_or_memo_obligations_become_historical_dependencies() -> None:
    dependencies = build_task_dependency_refs(plan={"chapter": 9, "obligation_refs": ["new:setup", "promise:return-key"]}, current_candidates=[])
    assert dependencies["required_obligation_ids"] == []
    query = build_retrieval_query_plan(intent=_intent(), memo=_memo(), task_dependency_refs=dependencies)
    assert query["task_dependency_refs"]["required_obligation_ids"] == ["promise:return-key"]
    legacy = {key: value for key, value in dependencies.items() if key not in {"required_obligation_ids", "referenced_obligation_ids"}}
    assert build_retrieval_query_plan(intent=_intent(), memo=_memo(), task_dependency_refs=legacy)["task_dependency_refs"] == legacy


def test_frozen_task_result_rejects_omitted_dependency_documents_and_aliases() -> None:
    dependencies = build_task_dependency_refs(plan={"required_long_distance_fact_ids": ["fact:missing"]}, current_candidates=[])
    plan = build_retrieval_query_plan(intent=_intent(), memo=_memo(), task_dependency_refs=dependencies)
    arguments = dict(project_id="project:novel", book_id="book:novel", intent_asset_version_id="intent:v1",
        memo_asset_version_id="memo:v1", documents=[_document()], discovery_rejections=[], semantic_status={})
    with pytest.raises(KernelError) as alias_failure:
        build_retrieval_result(**arguments, query_plan=plan)
    assert alias_failure.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"
    with pytest.raises(KernelError) as document_failure:
        build_retrieval_result(**arguments, query_plan={**plan, "task_dependency_discovery": {
            "matched_documents_by_ref": {"fact:missing": ["missing:document"]},
        }})
    assert document_failure.value.code == "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"



def test_retrieval_result_is_reproducible_and_records_all_ranking_provenance() -> None:
    plan = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    arguments = {
        "project_id": "project:novel",
        "book_id": "book:novel",
        "intent_asset_version_id": "intent:v1",
        "memo_asset_version_id": "memo:v1",
        "query_plan": plan,
        "documents": [_document()],
        "discovery_rejections": [
            {
                "retrieval_document_id": "retrieval:future:10",
                "source_asset_version_id": "draft:future:10",
                "source_content_hash": "sha256:" + "5" * 64,
                "accepted_from_chapter": 10,
                "accepted_to_chapter": None,
                "reason": "FUTURE_ACCEPTED_BOUNDARY",
            }
        ],
        "semantic_status": {
            "policy": "FALLBACK_ALLOWED",
            "status": "RETRIEVAL_SEMANTIC_PROJECTION_READY",
        },
        "query_embedding": [1.0, 0.0],
        "query_embedding_evidence": {
            "provider_id": "production-provider",
            "model_id": "embedding-production-v1",
            "receipt_id": "receipt:query:9",
        },
    }

    first = build_retrieval_result(**arguments)
    second = build_retrieval_result(**arguments)

    assert first == second
    assert first["result_fingerprint"].startswith("sha256:")
    assert first["candidate_channels"] == ["FTS", "VECTOR"]
    assert first["ranking"]["ranking_policy_version"] == (
        "accepted-lexical-first-ranking-v4"
    )
    assert first["ranking"]["candidate_discovery"] == (
        "LEXICAL_AND_EXACT_STRUCTURED_ONLY"
    )
    assert first["ranking"]["semantic_candidate_expansion"] is False
    selected = first["selected_documents"][0]
    assert {
        "postgresql_fts",
        "embedding",
        "entity",
        "relationship",
        "character_timeline",
        "temporal",
        "arc",
        "obligation",
    }.issubset(selected["retrieval_scores"])
    assert selected["compression_provenance"]["source_content_hash"] == (
        "sha256:" + "3" * 64
    )
    assert first["rejected_documents"][0]["reason"] == ("FUTURE_ACCEPTED_BOUNDARY")


def test_semantic_required_policy_is_explicit_not_a_silent_fallback() -> None:
    plan = build_retrieval_query_plan(
        intent=_intent(), memo=_memo(), semantic_policy="REQUIRED"
    )
    assert plan["semantic_policy"] == "REQUIRED"

    with pytest.raises(KernelError, match="semantic retrieval policy"):
        build_retrieval_query_plan(
            intent=_intent(), memo=_memo(), semantic_policy="BEST_EFFORT"
        )


@pytest.mark.parametrize("source_event_id", ["", "initial:original-promise"])
def test_initial_obligations_are_exact_protected_state_dependencies_not_accepted_planting(source_event_id) -> None:
    boundary = {"accepted_through_chapter": 0, "story_state_asset_version_id": "initial-state:1", "canon_snapshot_asset_version_id": "initial-canon:1"}
    state = {"obligation_id": "initial-promise", "status": "OPEN", "priority": "HIGH", "condition": "only if the key returns"}
    dependencies = build_task_dependency_refs(plan={"chapter": 1, "obligation_refs": ["initial-promise"]}, current_candidates=[
        {"asset_type": "story_state_snapshot", "asset_version_id": "initial-state:1", "content_hash": "sha256:" + "a" * 64,
         "accepted_boundary": boundary, "structured_facts": [{"state_kind": "narrative_obligation", "entity_key": "obligation_id=initial-promise", "source_event_id": source_event_id, "source_chapter": 0, "effective_from_chapter": 0, "state": state}]},
    ])
    assert dependencies["required_obligation_ids"] == ["initial-promise"]
    protected = dependencies["protected_initial_obligations"]
    assert len(protected) == 1 and protected[0]["obligation_id"] == "initial-promise"
    assert (protected[0]["asset_version_id"], protected[0]["content_hash"], protected[0]["source_event_id"]) == ("initial-state:1", "sha256:" + "a" * 64, source_event_id)
    from novel_forge.modules.narrative_state.reality import narrative_hash
    assert protected[0]["state_hash"] == narrative_hash(state)
    intent = {**_intent(), "chapter": 1, "accepted_boundary": boundary, "active_obligations": [{"state": state}]}
    memo = {**_memo(), "chapter": 1, "accepted_boundary": boundary, "obligation_actions": [{"obligation_id": "initial-promise"}]}
    query = build_retrieval_query_plan(intent=intent, memo=memo, semantic_policy="DISABLED", task_dependency_refs=dependencies)
    query["task_dependency_discovery"] = {"protected_initial_obligation_ids": ["initial-promise"], "protected_initial_obligation_sources": protected}
    result = build_retrieval_result(project_id="project", book_id="book", intent_asset_version_id="intent:1", memo_asset_version_id="memo:1", query_plan=query, documents=[], discovery_rejections=[], semantic_status={})
    assert result["selected_documents"] == []
    for changed in (
        {**dependencies, "source_bindings": []},
        {**dependencies, "source_bindings": [{"asset_version_id": "initial-state:1", "content_hash": "sha256:" + "b" * 64}]},
        {**dependencies, "required_obligation_ids": ["unknown-promise"]},
        {**dependencies, "protected_initial_obligations": []},
    ):
        with pytest.raises(KernelError) as missing:
            build_retrieval_result(project_id="project", book_id="book", intent_asset_version_id="intent:1", memo_asset_version_id="memo:1", query_plan={**query, "task_dependency_refs": changed}, documents=[], discovery_rejections=[], semantic_status={})
        assert missing.value.code in {"RETRIEVAL_TASK_SOURCE_BINDING_INVALID", "RETRIEVAL_TASK_DEPENDENCY_UNAVAILABLE"}
    with pytest.raises(KernelError) as later:
        build_retrieval_result(project_id="project", book_id="book", intent_asset_version_id="intent:1", memo_asset_version_id="memo:1", query_plan={**query, "accepted_boundary": {**boundary, "accepted_through_chapter": 1}}, documents=[], discovery_rejections=[], semantic_status={})
    assert later.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"
