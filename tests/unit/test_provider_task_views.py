from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.provider_views import (
    build_provider_context_view,
    build_provider_knowledge_view,
    build_provider_task_view,
    project_reader_outcome_context_input,
)
from novel_forge.modules.chapter_authority.execution_gateway import (
    PostgresChapterExecutionContractBinder,
    PostgresRetrievalProjectionExecutionContractBinder,
    _materialize_chapter_codex_prompt,
    _provider_context_selection,
    _stage_tool_permissions,
)
from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    default_chapter_artifact_resolver,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution import ExecutionRuntimeClass
from tests.unit.test_production_execution_gateway import contracts


def _authoritative_load() -> dict[str, object]:
    return {
        "narrative_load_policy": {"policy_hash": "sha256:" + "c" * 64},
        "narrative_load_policy_lineage": {
            "frozen_by_generation_operation_id": "operation:planning"
        },
        "narrative_load_projection": {"status": "MEASURED", "metrics": {}},
    }


def _arc_working_set() -> dict[str, object]:
    return {
        "schema_version": "novelos.arc_working_set.v1",
        "selected_contributions": [],
    }


def _narrative_intelligence() -> dict[str, object]:
    return {
        "schema_version": "mkaos-narrative-intelligence-selection.v1",
        "selection_status": "NO_ELIGIBLE_MATCH",
        "selected": [],
        "authority_boundary": {
            "semantic_role": "POSSIBILITY_ONLY",
            "may_mutate_story_authority": False,
        },
    }


def test_retrieval_expansion_view_exposes_only_frozen_query_scope() -> None:
    view = build_provider_task_view(
        "retrieval_query_expansion",
        {
            "accepted_boundary": {"accepted_through_chapter": 40},
            "intent_fingerprint": "sha256:" + "1" * 64,
            "memo_fingerprint": "sha256:" + "2" * 64,
            "mission": {"objective": "pay the accepted oath"},
            "memo": {"retrieval_queries": ["accepted oath"]},
            "coverage": {
                "sufficient": False,
                "missing": {"fact_ids": ["fact:oath"]},
            },
            "policy": {"total_round_limit": 3},
            "prior_rounds": [{"round_number": 0}],
            "allowed_retrieval_dimensions": ["entity_ids"],
            "allowed_retrieval_selectors": {
                "entity_ids": ["entity:oath"],
            },
            "coverage_contract": {"database_url": "must-not-cross-view"},
            "candidate_asset_versions": ["asset-version:must-not-cross-view"],
        },
    )

    assert view["accepted_boundary"] == {"accepted_through_chapter": 40}
    assert view["allowed_retrieval_selectors"] == {"entity_ids": ["entity:oath"]}
    assert "coverage_contract" not in view
    assert "candidate_asset_versions" not in view
    assert "database_url" not in json.dumps(view, sort_keys=True)


def _plan() -> dict:
    return {
        "chapter": 31,
        "chapter_intent": "Make Lin expose the ledger while protecting Mei.",
        "character_participation": [
            {
                "character_id": "character:lin",
                "goal": "protect Mei",
                "trajectory_refs": ["arc:accountability"],
                "known_fact_ids": ["fact:ledger"],
                "unknown_fact_ids": ["fact:traitor"],
                "belief_refs": ["proposition:silence-is-safe"],
                "expected_change": "choose public accountability",
            }
        ],
        "arc_schedule": [
            {
                "arc_plan_version_id": "arc:v1",
                "role": "PRIMARY",
                "segment_id": "arc-segment:3",
                "expected_movement": "doubt to commitment",
            }
        ],
        "knowledge_boundaries": [
            {
                "layer": "CHARACTER_KNOWLEDGE",
                "subject_id": "character:lin",
                "fact_id": "fact:ledger",
                "status": "KNOWN",
            }
        ],
        "disclosures": [
            {
                "disclosure_id": "disclosure:traitor",
                "fact_id": "fact:traitor",
                "audience": "READER",
                "mode": "HINT",
                "presentation_channel": "OBJECT_DETAIL",
            }
        ],
        "scene_plan": [{"scene_id": "scene:31:1", "participants": ["character:lin"]}],
    }


def _context(unrelated_count: int) -> dict:
    unrelated = [
        {
            "state_kind": "character_state",
            "entity_key": f"character_id=character:extra:{index}",
            "state": {
                "character_id": f"character:extra:{index}",
                "location": "elsewhere",
            },
        }
        for index in range(unrelated_count)
    ]
    relevant = [
        {
            "state_kind": "character_state",
            "entity_key": "character_id=character:lin",
            "state": {"character_id": "character:lin", "location": "archive"},
        },
        {
            "state_kind": "reader_knowledge",
            "entity_key": "fact_id=fact:traitor",
            "state": {"fact_id": "fact:traitor", "status": "UNKNOWN"},
        },
    ]
    segments = [
        {
            "asset_version_id": "story-state:v30",
            "asset_type": "story_state_snapshot",
            "narrative_function": "authoritative_story_state",
            "safe_summary": "Current state through Chapter 30.",
            "structured_facts": [*unrelated, *relevant],
            "allowed_use": "generation",
            "content_digest": "sha256:state",
        },
        {
            "asset_version_id": "style:v1",
            "asset_type": "style_policy",
            "narrative_function": "style",
            "safe_summary": "Use concise Chinese scene prose.",
            "structured_facts": [],
            "allowed_use": "generation",
            "content_digest": "sha256:style",
        },
    ]
    duplicate = {"segments": segments, "rendered_safe_context": "duplicated" * 500}
    correctness = {
        "type": "ContextCorrectnessReceipt",
        "contract_version": "context-correctness-receipt-v1",
        "overall_status": "PASS",
        "checks": {
            name: {
                "status": (
                    "NOT_APPLICABLE"
                    if name == "REQUIRED_LONG_DISTANCE_FACT_PRESENT"
                    else "PASS"
                ),
                "violations": [],
            }
            for name in (
                "NO_FUTURE_FACT",
                "NO_HIDDEN_KNOWLEDGE_LEAK",
                "NO_STALE_VERSION",
                "NO_DUPLICATE_SEMANTIC_REPRESENTATION",
                "NO_IRRELEVANT_FULL_ASSET",
                "REQUIRED_LONG_DISTANCE_FACT_PRESENT",
            )
        },
        "selected_asset_version_ids": ["story-state:v30", "style:v1"],
        "narrative_position": {"book_id": "book:1", "chapter": 31},
    }
    correctness["receipt_hash"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(correctness, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return {
        "context_contract_version": "authority-context-bundle-v5",
        "context_correctness": correctness,
        "context_manifest": {
            "narrative_position": {"book_id": "book:1", "chapter": 31},
            "authority_state_boundary": {"accepted_through_chapter": 30},
            "selected_inputs": [{"asset_version_id": "story-state:v30"}],
            "rejected_inputs": [{"reason": "irrelevant", "blob": "x" * 20000}],
        },
        "context_segments": segments,
        "stage_context_view": duplicate,
        "actual_context": {"stage_context_view": duplicate},
        "task_narrative_projection": {
            "character_ids": ["character:lin"],
            "arc_refs": ["arc:v1", "arc:accountability"],
            "fact_refs": ["fact:ledger", "fact:traitor"],
            "belief_refs": ["proposition:silence-is-safe"],
            "disclosure_refs": ["disclosure:traitor"],
            "state_entity_refs": [],
        },
    }


def test_provider_context_is_one_bounded_representation_not_authority_bundle() -> None:
    task = build_provider_task_view("draft", {"plan": _plan(), "context": _context(1)})
    light = build_provider_context_view("draft", _context(1), task)
    heavy = build_provider_context_view("draft", _context(1000), task)

    serialized = json.dumps(heavy, ensure_ascii=False, sort_keys=True)
    assert "context_manifest" not in serialized
    assert "stage_context_view" not in serialized
    assert "actual_context" not in serialized
    assert "character:extra" not in serialized
    assert "character:lin" in serialized
    assert "fact:traitor" in serialized
    assert (
        len(json.dumps(heavy, ensure_ascii=False))
        - len(json.dumps(light, ensure_ascii=False))
        < 128
    )
    assert heavy["selection_explanation"]["omitted_fact_count"] == 1000


def test_agent_provider_task_distinguishes_catalog_from_explicit_activation() -> None:
    task = build_provider_task_view(
        "agent_session",
        {
            "agent_session_id": "session:1",
            "operation_id": "operation:1",
            "instruction": "Propose without mutating truth.",
            "accepted_boundary": {"book_id": "book:1", "accepted_through_chapter": 3},
            "execution_contract_hash": "sha256:" + "1" * 64,
            "execution_contract_summary": {"authority_policy": "SUBMIT_ONLY"},
            "tools": [{"tool_name": "skill.activate"}],
            "skills": [
                {
                    "skill_id": "studio-direction",
                    "skill_version": "1.0.0",
                    "skill_hash": "sha256:" + "2" * 64,
                }
            ],
            "active_skill_activations": [
                {
                    "skill_id": "studio-direction",
                    "skill_version": "1.0.0",
                    "skill_hash": "sha256:" + "2" * 64,
                    "additional_tool_permissions": [],
                    "additional_authority_permissions": [],
                }
            ],
            "committed_transcript": [],
            "observations": [],
            "turn_number": 1,
        },
    )

    assert task["skills"][0]["skill_id"] == "studio-direction"
    assert task["active_skill_activations"][0]["skill_hash"] == ("sha256:" + "2" * 64)
    assert task["active_skill_activations"][0]["additional_tool_permissions"] == []


def test_provider_admission_rejects_tampered_context_correctness_receipt() -> None:
    context = _context(1)
    context["context_correctness"]["checks"]["NO_FUTURE_FACT"]["status"] = "FAIL"
    task = build_provider_task_view("draft", {"plan": _plan(), "context": context})

    with pytest.raises(KernelError, match="CONTEXT_CORRECTNESS_BLOCKED"):
        build_provider_context_view("draft", context, task)


def test_provider_cannot_silently_drop_relevant_accepted_facts_after_context_gate() -> None:
    context = _context(0)
    context["context_segments"][0]["structured_facts"] = [
        {
            "state_kind": "character_knowledge",
            "entity_key": f"character_id=character:lin|fact_id=fact:required-{index}",
            "state": {
                "character_id": "character:lin",
                "fact_id": f"fact:required-{index}",
                "status": "KNOWN",
            },
        }
        for index in range(33)
    ]
    context["task_narrative_projection"]["fact_refs"] = [
        f"fact:required-{index}" for index in range(33)
    ]

    with pytest.raises(KernelError, match="CONTEXT_PROJECTION_TOO_BROAD"):
        build_provider_context_view(
            "draft", context, build_provider_task_view("draft", {"plan": _plan()})
        )


def test_provider_cannot_silently_drop_eligible_context_segments() -> None:
    context = _context(0)
    context["context_segments"] = [
        {
            "asset_version_id": f"material:{index}",
            "asset_type": "material_card",
            "safe_summary": f"Required causal preparation {index}.",
            "structured_facts": [],
            "allowed_use": "generation",
        }
        for index in range(25)
    ]

    with pytest.raises(KernelError, match="CONTEXT_PROJECTION_TOO_BROAD"):
        build_provider_context_view(
            "draft", context, build_provider_task_view("draft", {"plan": _plan()})
        )


def test_reader_outcome_uses_its_own_bounded_task_and_context_views() -> None:
    task = build_provider_task_view(
        "reader_outcome",
        {
            "chapter": 31,
            "book_id": "book:1",
            "reader_contract_version": "reader-contract:v1",
            "evaluation_profile_version": "evaluation:v1",
            "reader_judge_execution_snapshot": {
                "snapshot_id": "reader-snapshot:1",
                "mode": "SHADOW",
                "provider_evidence": {"authority_only": "x" * 100_000},
            },
            "assets": {"story_state_snapshot": {"history": "x" * 100_000}},
        },
    )
    context = {
        "schema_version": "novelos.reader_outcome_context_bundle.v2",
        "selected_inputs": [
            {
                "asset_version_id": "draft:v31",
                "asset_type": "draft_version",
                "content_hash": "sha256:draft",
                "projection": {
                    "chapter": 31,
                    "title": "The ledger opens",
                    "text": "Lin shows the altered entry to the witness.",
                },
            },
            {
                "asset_version_id": "reader-contract:v1",
                "asset_type": "reader_contract",
                "content_hash": "sha256:reader",
                "projection": {"safe_summary": "Clarity before surprise."},
            },
            {
                "asset_version_id": "outcome:v31",
                "asset_type": "chapter_outcome",
                "content_hash": "sha256:outcome",
                "projection": {},
            },
        ],
    }

    view = build_provider_context_view("reader_outcome", context, task)
    serialized = json.dumps({"task": task, "context": view}, ensure_ascii=False)

    assert task["chapter"] == 31
    assert "assets" not in task
    assert "provider_evidence" not in serialized
    assert "authority_only" not in serialized
    assert [item["asset_type"] for item in view["segments"]] == [
        "draft_version",
        "reader_contract",
    ]
    assert view["selection_explanation"]["omitted_segment_count"] == 1
    assert len(serialized) < 65_536


def test_reader_outcome_reads_selected_accepted_prose_without_comparison_envelope() -> None:
    content = {"text": "The adopted revision keeps her unanswered question.",
               "selected_source_asset_version_id": "revision:chosen",
               "comparison_evidence": {"operator_detail": "omit"}}
    selected = project_reader_outcome_context_input("best_draft_candidate", content)
    assert selected == project_reader_outcome_context_input("draft_version", content)
    assert selected["text"] == content["text"]
    assert "comparison_evidence" not in selected
    context = {"schema_version": "novelos.reader_outcome_context_bundle.v2",
               "selected_inputs": [{"asset_version_id": "best:adopted",
                   "asset_type": "best_draft_candidate", "projection": selected}]}
    view = build_provider_context_view("reader_outcome", context, {})
    assert view["segments"][0]["content"]["text"] == content["text"]
    assert view["segments"][0]["asset_version_id"] == "best:adopted"


def test_reader_outcome_state_projection_does_not_grow_with_unrelated_history() -> None:
    def state(extra: int) -> dict:
        return {
            "contract_version": "story-state-snapshot-v2",
            "accepted_through_chapter": 31,
            "current_state": {
                "character_state": [
                    {
                        "entity_key": f"character_id=extra:{index}",
                        "entity_version": 1,
                        "state": {"character_id": f"extra:{index}"},
                        "source_event_id": f"event:extra:{index}",
                        "source_chapter": index,
                        "effective_from_chapter": index,
                        "confidence": 1.0,
                        "coverage": "EXPLICIT",
                        "evidence": {},
                    }
                    for index in range(extra)
                ],
                "reader_knowledge": [
                    {
                        "entity_key": "fact_id=fact:ledger",
                        "entity_version": 1,
                        "state": {"fact_id": "fact:ledger", "status": "KNOWN"},
                        "source_event_id": "event:reader:ledger",
                        "source_chapter": 31,
                        "effective_from_chapter": 31,
                        "confidence": 1.0,
                        "coverage": "EXPLICIT",
                        "evidence": {},
                    }
                ],
            },
        }

    light = project_reader_outcome_context_input("story_state_snapshot", state(1))
    heavy = project_reader_outcome_context_input("story_state_snapshot", state(3_000))

    assert heavy == light
    assert heavy["reader_facing_state"][0]["state"]["status"] == "KNOWN"


def test_reader_outcome_v1_context_replays_through_deterministic_read_upgrade() -> None:
    legacy = {
        "schema_version": "novelos.reader_outcome_context_bundle.v1",
        "selected_inputs": [
            {
                "asset_version_id": "draft:v1",
                "asset_type": "draft_version",
                "content_hash": "sha256:draft",
                "content": {
                    "chapter": 1,
                    "text": "The accepted reader-facing chapter.",
                    "provider_evidence": {"authority_only": "x" * 10_000},
                },
            },
            {
                "asset_version_id": "outcome:v1",
                "asset_type": "chapter_outcome",
                "content_hash": "sha256:outcome",
                "content": {"state_events": [{"payload": "x" * 10_000}]},
            },
        ],
    }

    view = build_provider_context_view(
        "reader_outcome",
        legacy,
        build_provider_task_view("reader_outcome", {"chapter": 1}),
    )
    serialized = json.dumps(view, ensure_ascii=False)

    assert "The accepted reader-facing chapter." in serialized
    assert "provider_evidence" not in serialized
    assert "state_events" not in serialized
    assert view["selection_explanation"]["omitted_segment_count"] == 1


def test_narrative_evaluator_projects_exact_canonical_foundation_closure() -> None:
    dependency_types = {
        "CREATIVE_FOUNDATION": "creative_foundation",
        "THEME_CONTRACT": "theme_contract",
        "ENDING_INTENT": "ending_intent",
        "READER_PROMISE": "reader_promise",
        "WORLD_BIBLE": "world_bible",
        "CHARACTER_CAST": "character_cast",
    }
    selected = [
        {
            "asset_version_id": "book-design:v5",
            "asset_type": "book_design",
            "content_hash": "sha256:" + "a" * 64,
            "candidate": {"schema_version": "book-design.v5"},
        }
    ]
    lineage = []
    for index, (role, asset_type) in enumerate(dependency_types.items(), start=1):
        selected.append(
            {
                "asset_version_id": f"foundation:{index}",
                "asset_type": asset_type,
                "content_hash": "sha256:" + str(index) * 64,
                "dependency_role": role,
                "candidate": {
                    "schema_version": "story_design.authority.v1",
                    "generator_operation_name": {
                        "CREATIVE_FOUNDATION": "creative.candidates.generate",
                        "THEME_CONTRACT": "theme.candidates.generate",
                        "ENDING_INTENT": "ending.intent.generate",
                        "READER_PROMISE": "reader.promise.generate",
                        "WORLD_BIBLE": "world.design.generate",
                        "CHARACTER_CAST": "character.cast.generate",
                    }[role],
                    "candidate_payload": {
                        "role": role,
                        "semantic_evidence": f"evidence-{index}",
                    },
                    "provider_evidence": {"must_not_leak": True},
                },
            }
        )
        lineage.append(
            {
                "role": role,
                "asset_version_id": f"foundation:{index}",
                "content_hash": "sha256:" + str(index) * 64,
                "qualification_evidence_asset_version_id": f"qualification:{index}",
                "qualification_hash": "sha256:" + format(index + 6, "x") * 64,
            }
        )

    view = build_provider_context_view(
        "narrative_semantic_evaluation",
        {
            "source_isolation": "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES",
            "dependency_resolution": "EVALUATOR_RESOLVED_FROM_CANDIDATE_LINEAGE",
            "selected_inputs": selected,
            "dependency_lineage": lineage,
        },
        {},
    )

    assert len(view["selected_inputs"]) == 7
    assert view["selection_explanation"]["policy"] == (
        "exact-candidate-and-canonical-foundation-semantic-closure-v2"
    )
    assert view["schema_version"] == "novelos.narrative_evaluation_context_view.v2"
    for index, item in enumerate(view["selected_inputs"][1:], start=1):
        assert item["semantic_payload"]["semantic_evidence"] == f"evidence-{index}"
        assert "candidate" not in item
    serialized = json.dumps(view, ensure_ascii=False)
    assert "candidate_payload" not in serialized
    assert "provider_evidence" not in serialized
    assert "qualification" not in serialized


def test_narrative_evaluator_rejects_unbound_dependency_projection() -> None:
    with pytest.raises(KernelError, match="PROVIDER_CONTEXT_INVALID"):
        build_provider_context_view(
            "narrative_semantic_evaluation",
            {
                "source_isolation": "EXACT_CANDIDATE_AND_CANONICAL_DEPENDENCIES",
                "dependency_resolution": "EVALUATOR_RESOLVED_FROM_CANDIDATE_LINEAGE",
                "selected_inputs": [
                    {
                        "asset_version_id": "book-design:v5",
                        "asset_type": "book_design",
                        "content_hash": "sha256:" + "a" * 64,
                        "candidate": {},
                    },
                    {
                        "asset_version_id": "unbound:v1",
                        "asset_type": "world_bible",
                        "content_hash": "sha256:" + "b" * 64,
                        "dependency_role": "WORLD_BIBLE",
                        "candidate": {},
                    },
                ],
                "dependency_lineage": [],
            },
            {},
        )


def test_planning_provider_view_uses_command_and_projected_inputs_only() -> None:
    task = build_provider_task_view(
        "book_plan.generate",
        {
            "planning_command": {
                "logical_key": "book:main",
                "planning_scope": "BOOK",
                "input_versions": {"book_design": "book-design:v1"},
                "trace_id": "trace:authority-only",
            },
            "frozen_inputs": [{"content_hash": "sha256:authority-evidence"}],
            "authoritative_narrative_load": _authoritative_load(),
            "arc_working_set": _arc_working_set(),
            "narrative_intelligence": _narrative_intelligence(),
        },
    )
    view = build_provider_context_view(
        "book_plan.generate",
        {
            "schema_version": "novelos.planning_context_bundle.v1",
            "book_id": "book-1",
            "logical_key": "book:main",
            "planning_scope": "BOOK",
            "realization_reference_contract": {
                "contract_version": "planning-realization-reference-contract-v1",
                "references_by_domain": {
                    "WORLD_STATE": [
                        {
                            "authority_role": "world_bible",
                            "asset_version_id": "world:v1",
                            "content_hash": "sha256:" + "d" * 64,
                        }
                    ]
                },
            },
            "input_versions": [
                {
                    "role": "book_design",
                    "asset_version_id": "book-design:v1",
                    "asset_type": "book_design",
                    "content_hash": "sha256:authority-evidence",
                    "content": {
                        "premise": "Truth requires a visible cost.",
                        "candidate_payload": {
                            "premise": "duplicated Provider candidate"
                        },
                        "constraint_envelope": {"envelope_digest": "sha256:audit"},
                        "execution_evidence": {"attempt_id": "attempt:audit"},
                        "frozen_inputs": [{"asset_version_id": "authority:audit"}],
                        "trace_id": "trace:authority-only",
                        "evidence_level": "CONTROLLED_PROOF_BOOTSTRAP",
                        "runtime_result": False,
                    },
                }
            ],
        },
        task,
    )

    serialized = json.dumps({"task": task, "context": view}, sort_keys=True)
    assert task["planning_command"]["logical_key"] == "book:main"
    assert task["frozen_inputs"] == [{"content_hash": "sha256:authority-evidence"}]
    assert "authority-only" not in serialized
    assert "CONTROLLED_PROOF_BOOTSTRAP" not in serialized
    assert view["segments"][0]["content"] == {
        "premise": "Truth requires a visible cost."
    }
    assert (
        view["realization_reference_contract"]["references_by_domain"]["WORLD_STATE"][
            0
        ]["authority_role"]
        == "world_bible"
    )
    assert view["selection_explanation"]["policy"] == (
        "minimum-sufficient-planning-context-v2"
    )


def test_planning_provider_context_blocks_oversized_required_semantics() -> None:
    with pytest.raises(KernelError, match="required Planning Provider Context exceeds its budget"):
        build_provider_context_view(
            "book_plan.generate",
            {
                "schema_version": "novelos.planning_context_bundle.v1",
                "input_versions": [{
                    "role": "book_design",
                    "asset_version_id": "book-design:v1",
                    "asset_type": "book_design",
                    "content": {"premise": "x" * 70_000},
                }],
            },
            {},
        )


def test_new_planning_capacity_preserves_large_required_sources_and_freezes_policy() -> None:
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.provider_views import compile_planning_provider_context, planning_context_source_hash, _projection_hash
    from novel_forge.modules.worldbuilding.foundation_schema import world_foundation_example

    world = world_foundation_example(compiled_scope="BOOK")
    world["rules"][0]["statement"] = "Required condition, exception and consequence. " * 1800
    context = {"schema_version": "novelos.planning_context_bundle.v1", "book_id": "book:capacity",
               "logical_key": "book:capacity", "planning_scope": "BOOK", "token_budget": 200_000,
               "input_versions": [{"role": "world_bible", "asset_version_id": "world:capacity:v1",
                   "asset_type": "world_bible", "content_hash": "sha256:" + "a" * 64,
                   "content": {"world_foundation": world}}]}
    with pytest.raises(KernelError) as legacy:
        compile_planning_provider_context("book_plan.generate", context)
    assert legacy.value.code == "WORLD_FOUNDATION_SCOPE_TOO_BROAD"
    current = {**context, "planning_context_policy_version": "context-policy:chapter-generation-pack:v2"}
    view, audit = compile_planning_provider_context("book_plan.generate", current)
    assert len(json.dumps(view, ensure_ascii=False)) > 65_536
    assert view["segments"][0]["content"]["world_foundation"] == world
    assert view["contract_version"] == "provider-context-view-v4"
    assert view["selection_explanation"]["maximum_serialized_bytes"] == 8_388_608
    assert "maximum_serialized_characters" not in view["selection_explanation"]
    frozen = {**current, "context_manifest": {"projection_audit": audit, "provider_context_view": {
        "compiled_view": view, "content_hash": _projection_hash(view), "source_input_hash": planning_context_source_hash(current)}}}
    assert compile_planning_provider_context("book_plan.generate", frozen)[0] == view
    changed = deepcopy(frozen)
    changed.pop("planning_context_policy_version")
    with pytest.raises(KernelError) as drift:
        compile_planning_provider_context("book_plan.generate", changed)
    assert drift.value.code == "PROVIDER_CONTEXT_VIEW_IDENTITY_MISMATCH"
    with pytest.raises(KernelError) as overflow:
        compile_planning_provider_context("book_plan.generate", {**current, "token_budget": 70_000})
    assert overflow.value.code == "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"


def test_new_planning_capacity_keeps_legacy_replay_and_independent_utf8_guard() -> None:
    from novel_forge.modules.chapter_authority.provider_views import compile_planning_provider_context, project_world_planning_window
    from novel_forge.modules.worldbuilding.foundation_schema import world_foundation_example

    source = {"role": "book_design", "asset_version_id": "design:capacity", "asset_type": "book_design",
              "content": {"premise": "界" * 70_000}}
    context = {"schema_version": "novelos.planning_context_bundle.v1", "token_budget": 200_000,
               "input_versions": [source], "planning_context_policy_version": "context-policy:chapter-generation-pack:v2"}
    with pytest.raises(KernelError) as overflow:
        compile_planning_provider_context("book_plan.generate", context)
    assert overflow.value.code == "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"
    world = world_foundation_example(compiled_scope="BOOK")
    world["rules"][0]["statement"] = "界" * 2_800_000
    source = {"role": "world_bible", "asset_version_id": "world:large", "content_hash": "sha256:" + "b" * 64,
              "content": {"world_foundation": world}}
    with pytest.raises(KernelError) as guard:
        project_world_planning_window([source], chapter=1, window=1, context_policy_version="world-production-policy.v4")
    assert guard.value.code == "WORLD_FOUNDATION_SCOPE_TOO_BROAD"


def test_world_v4_author_view_preserves_large_mandatory_text_and_blocks_task_overflow() -> None:
    from copy import deepcopy
    from novel_forge.modules.story_design_authority.author_input import bind_author_design, project_author_design
    from tests.unit.test_author_design_adoption import _world_author_context, design, digest

    stage_name = "world_candidates.generate"
    _, _, content = _world_author_context(stage_name)
    source = design()
    text = "Mandatory current action with exception and timing. " * 1600
    source["documents"][0].update(content=text, content_hash=digest(text))
    source["fragments"] = [{**source["fragments"][0], "start": 0, "end": len(text), "content_hash": digest(text)}]
    projection = project_author_design(bind_author_design(source, asset_version_id="brief:capacity", content_hash=digest("brief:capacity")), target="CHAPTER", chapter=1)
    task = deepcopy(content["world_preparation"])
    task["policy"] = {"version": "world-production-policy.v4", "context_token_budget": 200_000}
    current = {**content, "world_preparation": task, "token_budget": 200_000, "author_design_projection": projection}
    view = build_provider_context_view(stage_name, current, {"world_preparation": task})
    assert len(json.dumps(view, ensure_ascii=False)) > 65_536
    assert view["author_design_projection"]["fragments"][0]["text"] == text
    assert view["capacity_policy"]["token_accounting"] == "utf8-byte-upper-bound.v1"
    legacy_task = {**task, "policy": {"version": "world-production-policy.v3", "context_token_budget": 200_000}}
    with pytest.raises(KernelError) as legacy:
        build_provider_context_view(stage_name, {**current, "world_preparation": legacy_task}, {"world_preparation": legacy_task})
    assert legacy.value.code == "WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED"
    too_small = {**task, "policy": {"version": "world-production-policy.v4", "context_token_budget": 70_000}}
    with pytest.raises(KernelError) as overflow:
        build_provider_context_view(stage_name, {**current, "world_preparation": too_small, "token_budget": 70_000}, {"world_preparation": too_small})
    assert overflow.value.code == "WORLD_PROVIDER_CONTEXT_BUDGET_EXCEEDED"


def test_planning_provider_context_projects_frozen_accepted_boundary() -> None:
    view = build_provider_context_view(
        "chapter_plan.generate",
        {
            "schema_version": "novelos.planning_context_bundle.v1",
            "book_id": "book-1",
            "logical_key": "chapter:12",
            "planning_scope": "CHAPTER",
            "input_versions": [
                {
                    "role": "story_state",
                    "asset_version_id": "story-state:v11",
                    "asset_type": "story_state_snapshot",
                    "content": {"accepted_through_chapter": 11},
                },
                {
                    "role": "canon_snapshot",
                    "asset_version_id": "canon:v11",
                    "asset_type": "canon_snapshot",
                    "content": {
                        "authority_state_boundary": {
                            "accepted_through_chapter": 11
                        }
                    },
                },
            ],
        },
        {},
    )

    assert view["accepted_state_boundary"] == {
        "accepted_through_chapter": 11
    }


def test_planning_provider_context_rejects_conflicting_authority_boundaries() -> None:
    with pytest.raises(
        KernelError, match="Authority inputs disagree on the accepted boundary"
    ):
        build_provider_context_view(
            "chapter_plan.generate",
            {
                "schema_version": "novelos.planning_context_bundle.v1",
                "book_id": "book-1",
                "logical_key": "chapter:12",
                "planning_scope": "CHAPTER",
                "input_versions": [
                    {
                        "role": "story_state",
                        "asset_version_id": "story-state:v11",
                        "asset_type": "story_state_snapshot",
                        "content": {"accepted_through_chapter": 11},
                    },
                    {
                        "role": "canon_snapshot",
                        "asset_version_id": "canon:v10",
                        "asset_type": "canon_snapshot",
                        "content": {
                            "authority_state_boundary": {
                                "accepted_through_chapter": 10
                            }
                        },
                    },
                ],
            },
            {},
        )


def test_planning_repair_view_projects_source_and_failed_criteria() -> None:
    view = build_provider_context_view(
        "book_plan.generate",
        {
            "schema_version": "novelos.planning_context_bundle.v1",
            "book_id": "book-1",
            "logical_key": "book:main",
            "planning_scope": "BOOK",
            "input_versions": [
                {
                    "role": "book_design",
                    "asset_version_id": "book-design:v1",
                    "asset_type": "book_design",
                    "content": {"premise": "Expose the concealed audit."},
                }
            ],
            "repair_context": {
                "contract_version": "planning-repair-context-v1",
                "source_candidate": {
                    "asset_version_id": "candidate:v1",
                    "content_hash": "sha256:" + "a" * 64,
                    "content": {
                        "objective": "Expose the concealed audit.",
                        "character_arcs": [{"character_id": "director-wu"}],
                        "execution_evidence": {"receipt": "audit-only"},
                    },
                },
                "validation_failure": {
                    "validation_kind": "SEMANTIC",
                    "status": "FAIL",
                    "report_hash": "sha256:" + "b" * 64,
                },
                "failed_narrative_qualifications": [
                    {
                        "design_layer": "CHARACTER_DEVELOPMENT",
                        "qualification_status": "FAIL",
                        "evaluation": {
                            "criteria": [
                                {
                                    "criterion": "BELIEF_CHANGE_CAUSALITY",
                                    "verdict": "FAIL",
                                    "repair_directive": (
                                        "Align the antagonist target belief with the ending."
                                    ),
                                }
                            ]
                        },
                    }
                ],
            },
        },
        build_provider_task_view(
            "book_plan.generate",
            {
                "planning_command": {
                    "logical_key": "book:main",
                    "repair_number": 1,
                },
                "frozen_inputs": [
                    {
                        "role": "book_design",
                        "asset_version_id": "book-design:v1",
                        "asset_type": "book_design",
                        "content_hash": "sha256:" + "c" * 64,
                    }
                ],
                "authoritative_narrative_load": _authoritative_load(),
                "arc_working_set": _arc_working_set(),
                "narrative_intelligence": _narrative_intelligence(),
            },
        ),
    )

    repair = view["repair_context"]
    assert view["segments"][0]["asset_version_id"] == "book-design:v1"
    assert view["segments"][0]["content"] == {"premise": "Expose the concealed audit."}
    assert view["selection_explanation"]["omitted_segment_count"] == 0
    assert view["selection_explanation"]["policy"] == (
        "minimum-sufficient-planning-repair-context-v1"
    )
    assert repair["source_candidate"]["content"]["objective"] == (
        "Expose the concealed audit."
    )
    assert "execution_evidence" not in repair["source_candidate"]["content"]
    assert (
        repair["failed_narrative_qualifications"][0]["evaluation"]["criteria"][0][
            "repair_directive"
        ]
        == "Align the antagonist target belief with the ending."
    )


def test_chapter_planning_projects_local_plan_and_long_state_before_provider() -> None:
    current_state = {
        "character_state": [
            {
                "entity_key": f"character_id={character_id}",
                "entity_version": 1,
                "state": {"character_id": character_id, "location": "Hangzhou"},
                "source_event_id": f"event:{character_id}",
                "source_chapter": 30,
                "effective_from_chapter": 30,
                "confidence": 1.0,
                "coverage": "EXPLICIT",
                "evidence": {},
            }
            for character_id in (
                "hero",
                *(f"irrelevant-{index}" for index in range(3_000)),
            )
        ]
    }
    task = build_provider_task_view(
        "chapter_plan.generate",
        {
            "planning_command": {"logical_key": "chapter:31"},
            "frozen_inputs": [
                {
                    "role": "story_state",
                    "asset_version_id": "story-state:v30",
                    "asset_type": "story_state_snapshot",
                    "content_hash": "sha256:" + "b" * 64,
                }
            ],
            "authoritative_narrative_load": _authoritative_load(),
            "arc_working_set": _arc_working_set(),
            "narrative_intelligence": _narrative_intelligence(),
        },
    )
    view = build_provider_context_view(
        "chapter_plan.generate",
        {
            "schema_version": "novelos.planning_context_bundle.v1",
            "logical_key": "chapter:31",
            "input_versions": [
                {
                    "role": "book_plan",
                    "asset_version_id": "book:v1",
                    "asset_type": "planning_generation_candidate",
                    "content": {
                        "objective": "Preserve accountable truth.",
                        "candidate_payload": {"duplicate": "x" * 100_000},
                    },
                },
                {
                    "role": "chapter_group_plan",
                    "asset_version_id": "group:v1",
                    "asset_type": "planning_generation_candidate",
                    "content": {
                        "objective": "Force a public choice.",
                        "chapter_function_matrix": [
                            {
                                "chapter_number": number,
                                "character_id": "hero" if number == 31 else "extra",
                                "primary_function": "advance",
                            }
                            for number in range(28, 36)
                        ],
                    },
                },
                {
                    "role": "story_state",
                    "asset_version_id": "state:v30",
                    "asset_type": "story_state_snapshot",
                    "content": {
                        "contract_version": "story-state-snapshot-v2",
                        "accepted_through_chapter": 30,
                        "current_state": current_state,
                    },
                },
            ],
        },
        task,
    )

    serialized = json.dumps(view, ensure_ascii=False)
    group = next(
        item for item in view["segments"] if item["role"] == "chapter_group_plan"
    )
    state = next(item for item in view["segments"] if item["role"] == "story_state")
    assert [
        item["chapter_number"] for item in group["content"]["chapter_function_matrix"]
    ] == [31]
    assert len(state["content"]["facts"]) == 1
    assert state["content"]["facts"][0]["state"]["character_id"] == "hero"
    assert "irrelevant-2999" not in serialized
    assert "candidate_payload" not in serialized
    assert len(serialized) < 65_536


def test_state_context_without_task_projection_fails_closed() -> None:
    context = _context(1)
    context.pop("task_narrative_projection")

    try:
        build_provider_context_view(
            "review",
            context,
            build_provider_task_view("review", {"draft": {"text": "prose"}}),
        )
    except Exception as exc:
        assert getattr(exc, "code", "") == (
            "CHAPTER_PROVIDER_CONTEXT_PROJECTION_REQUIRED"
        )
    else:
        raise AssertionError("state-bearing context bypassed task projection")


def test_provider_context_matches_typed_references_not_substrings() -> None:
    context = _context(0)
    context["context_segments"][0]["structured_facts"] = [
        {
            "state_kind": "character_state",
            "entity_key": "character_id=character:linette",
            "state": {"character_id": "character:linette", "location": "archive"},
        }
    ]

    view = build_provider_context_view(
        "draft",
        context,
        build_provider_task_view("draft", {"plan": _plan()}),
    )

    assert "character:linette" not in json.dumps(view, ensure_ascii=False)


def test_oversized_projected_context_fails_closed() -> None:
    context = _context(0)
    context["context_segments"][0]["structured_facts"][0]["state"]["notes"] = (
        "x" * 70_000
    )

    with pytest.raises(Exception) as raised:
        build_provider_context_view(
            "draft",
            context,
            build_provider_task_view("draft", {"plan": _plan()}),
        )

    assert getattr(raised.value, "code", "") == (
        "CHAPTER_PROVIDER_CONTEXT_BUDGET_EXCEEDED"
    )


def test_rereview_task_does_not_repeat_revision_or_authority_context() -> None:
    revision = {
        "chapter": 2,
        "text": "Revised prose",
        "provider_evidence": {"large": "x" * 5000},
    }
    view = build_provider_task_view(
        "rereview",
        {
            "draft": revision,
            "revision": revision,
            "original_draft": {"chapter": 2, "text": "Old prose"},
            "review": {
                "issues": [{"code": "C1", "severity": "blocking", "message": "fix"}]
            },
            "context": _context(10),
        },
    )

    assert view == {
        "contract_version": "provider-task-view-v1",
        "stage": "rereview",
        "revised_chapter": {"chapter": 2, "text": "Revised prose"},
        "prior_diagnoses": [
            {"code": "C1", "severity": "blocking", "message": "fix"}
        ],
    }


def test_provider_knowledge_deduplicates_and_strips_materialization_metadata() -> None:
    knowledge = [
        {
            "ref": "knowledge:one",
            "content_hash": "sha256:same",
            "version": "v1",
            "content": {"principles": ["preserve causal continuity"]},
            "deployment": {"audit": "not prompt context"},
        },
        {
            "artifact_ref": "knowledge:duplicate",
            "content_hash": "sha256:same",
            "content": {"principles": ["preserve causal continuity"]},
        },
    ]

    assert build_provider_knowledge_view(knowledge) == [
        {
            "ref": "knowledge:one",
            "version": "v1",
            "content": {"principles": ["preserve causal continuity"]},
        }
    ]


def test_agent_codex_prompt_accepts_query_tool_without_required_knowledge() -> None:
    *_, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )
    boundary = {
        "book_id": "book:1",
        "book_run_id": "book-run:1",
        "accepted_through_chapter": 0,
        "acceptance_id": "",
        "projection_set_id": "",
    }
    prompt, evidence = _materialize_chapter_codex_prompt(
        request=request,
        stage="agent_session",
        inputs={
            "instruction": "Query accepted evidence first.",
            "accepted_boundary": boundary,
            "tools": [
                {
                    "tool_name": "narrative.query_accepted",
                    "kind": "READ_ONLY_QUERY",
                }
            ],
            "skills": [],
            "committed_transcript": [],
            "observations": [],
            "turn_number": 1,
        },
        materialization={
            "materialization_hash": "sha256:" + "a" * 64,
            "pack_artifacts": {
                "system_instruction": {
                    "ref": "system",
                    "version": "v1",
                    "content_hash": "sha256:" + "b" * 64,
                    "content": {"text": "Operate inside the accepted boundary."},
                },
                "prompt_template": {
                    "ref": "template",
                    "version": "v1",
                    "content_hash": "sha256:" + "c" * 64,
                    "content": {
                        "text": (
                            "{{stage}} {{target_scope}} {{input_manifest}} "
                            "{{context_bundle}} {{output_schema_ref}}"
                        )
                    },
                },
                "skill": {
                    "ref": "skill",
                    "version": "v1",
                    "content_hash": "sha256:" + "d" * 64,
                    "content": {"text": "Use governed Tools only."},
                },
            },
            "context_selection": [
                {
                    "asset_version_id": "context:agent",
                    "content": {
                        "protected": True,
                        "source_authority": "POSTGRESQL_ACCEPTED_BOUNDARY",
                        "accepted_boundary": boundary,
                        "estimated_tokens": 100,
                    },
                }
            ],
            "knowledge_selection": [],
            "tool_permissions": {
                "allowed": [
                    "model.provider.invoke",
                    "narrative.query_accepted",
                ],
                "denied": [],
            },
            "output_schema": {
                "ref": "schema:agent-output:v1",
                "content_hash": "sha256:" + "e" * 64,
                "content": {"type": "object"},
            },
        },
    )

    assert "narrative.query_accepted" in prompt
    assert "first ungrounded Agent turn" in prompt
    assert "Returning FINAL" in prompt
    assert evidence["allowed_tools"] == [
        "model.provider.invoke",
        "narrative.query_accepted",
    ]
    assert evidence["knowledge_content_hashes"] == []


def test_stage_tool_permissions_preserve_governed_query_tools() -> None:
    allowed, denied = _stage_tool_permissions(
        {
            "default": "DENY",
            "tools": [
                {
                    "tool_ref": "model.provider.invoke",
                    "permission": "EXECUTE",
                    "allowed_operations": ["agent_session"],
                },
                {
                    "tool_ref": "narrative.query_accepted",
                    "permission": "QUERY",
                    "allowed_operations": ["agent_session"],
                },
            ],
        },
        "agent_session",
    )

    assert allowed == ("model.provider.invoke", "narrative.query_accepted")
    assert denied == ()


def test_oversized_task_knowledge_fails_closed() -> None:
    with pytest.raises(Exception) as raised:
        build_provider_knowledge_view(
            [
                {
                    "ref": "knowledge:oversized",
                    "content_hash": "sha256:oversized",
                    "content": {"text": "x" * 70_000},
                }
            ]
        )

    assert getattr(raised.value, "code", "") == (
        "CHAPTER_PROVIDER_KNOWLEDGE_BUDGET_EXCEEDED"
    )


def test_fully_rendered_provider_prompt_is_bounded_against_long_history() -> None:
    *_, request = contracts(
        backend_id="codex-cli",
        runtime=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    )

    def render(unrelated_count: int) -> tuple[str, dict]:
        return _materialize_chapter_codex_prompt(
            request=request,
            stage="draft",
            inputs={"plan": _plan()},
            materialization={
                "materialization_hash": "sha256:" + "a" * 64,
                "pack_artifacts": {
                    "system_instruction": {
                        "ref": "system",
                        "version": "v1",
                        "content_hash": "sha256:" + "b" * 64,
                        "content": {"text": "Draft the governed chapter."},
                    },
                    "prompt_template": {
                        "ref": "template",
                        "version": "v2",
                        "content_hash": "sha256:" + "c" * 64,
                        "content": {
                            "text": (
                                "{{stage}} {{target_scope}} {{input_manifest}} "
                                "{{context_bundle}} {{output_schema_ref}}"
                            )
                        },
                    },
                    "skill": {
                        "ref": "skill",
                        "version": "v1",
                        "content_hash": "sha256:" + "d" * 64,
                        "content": {
                            "text": "Preserve causality and knowledge boundaries."
                        },
                    },
                },
                "context_selection": [
                    {
                        "asset_version_id": "context:v31",
                        "content": _context(unrelated_count),
                    }
                ],
                "knowledge_selection": [
                    {
                        "ref": "knowledge:chapter",
                        "version": "v1",
                        "content_hash": "sha256:" + "e" * 64,
                        "content": {"principles": ["causal continuity"]},
                    }
                ],
                "tool_permissions": {
                    "allowed": ["model.provider.invoke"],
                    "denied": [],
                },
                "output_schema": {
                    "ref": "schema:draft:v1",
                    "content_hash": "sha256:" + "f" * 64,
                    "content": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                },
            },
        )

    light_prompt, light_evidence = render(1)
    heavy_prompt, heavy_evidence = render(3000)

    assert len(heavy_prompt) - len(light_prompt) < 160
    assert "character:extra:2999" not in heavy_prompt
    assert "rejected_inputs" not in heavy_prompt
    assert (
        heavy_evidence["provider_view"]["selection_explanation"]["omitted_fact_count"]
        == 3000
    )
    assert heavy_evidence["provider_view"]["provider_context_estimated_tokens"] <= (
        light_evidence["provider_view"]["provider_context_estimated_tokens"] + 40
    )


def test_retrieval_projection_binds_source_asset_scope_without_chapter_zero() -> None:
    binder = object.__new__(PostgresChapterExecutionContractBinder)
    metadata = {
        "execution_binding_domain": "retrieval_projection",
        "source_asset_version_id": "asset-version:accepted-input",
    }

    scope = binder._target_scope(  # noqa: SLF001
        metadata=metadata,
        project_id="project:1",
        book_id="book:1",
        chapter=0,
    )
    claims = binder._resource_claims(  # noqa: SLF001
        metadata=metadata,
        chapter=0,
        stage="retrieval",
    )

    assert scope == {
        "scope_kind": "asset_version",
        "scope_id": "asset-version:accepted-input",
        "project_id": "project:1",
        "book_id": "book:1",
        "asset_version_id": "asset-version:accepted-input",
    }
    assert claims == (
        "asset-version:accepted-input",
        "stage:retrieval",
    )


def test_chapter_retrieval_uses_only_frozen_memo_as_provider_context() -> None:
    selected = [
        {"artifact_type": "chapter_plan", "asset_version_id": "plan:v1"},
        {"artifact_type": "chapter_execution_intent", "asset_version_id": "intent:v1"},
        {"artifact_type": "chapter_memo", "asset_version_id": "memo:v1"},
    ]

    assert _provider_context_selection(
        "retrieval", selected, retrieval_projection=False
    ) == [{"artifact_type": "chapter_memo", "asset_version_id": "memo:v1"}]


def test_chapter_retrieval_rejects_ambiguous_memo_context() -> None:
    with pytest.raises(KernelError) as raised:
        _provider_context_selection(
            "retrieval",
            [
                {"artifact_type": "chapter_memo", "asset_version_id": "memo:v1"},
                {"artifact_type": "chapter_memo", "asset_version_id": "memo:v2"},
            ],
            retrieval_projection=False,
        )

    assert raised.value.code == "CHAPTER_CAPABILITY_CONTEXT_INVALID"


def test_retrieval_projection_scope_requires_frozen_source_asset() -> None:
    binder = object.__new__(PostgresChapterExecutionContractBinder)

    with pytest.raises(KernelError) as raised:
        binder._target_scope(  # noqa: SLF001
            metadata={"execution_binding_domain": "retrieval_projection"},
            project_id="project:1",
            book_id="book:1",
            chapter=0,
        )

    assert raised.value.code == "RETRIEVAL_PROJECTION_SCOPE_MISSING"


def test_retrieval_projection_freezes_domain_materialization_before_effect() -> None:
    root = Path(__file__).resolve().parents[2]
    artifacts = default_chapter_artifact_resolver(root)
    system = artifacts.resolve(
        ArtifactKind.PROMPT_SYSTEM_INSTRUCTION,
        "prompt-system:chapter-generation-pack",
        "v1",
    )
    template = artifacts.resolve(
        ArtifactKind.PROMPT_TEMPLATE,
        "prompt-template:chapter-generation-pack",
        "v2",
    )
    skill = artifacts.resolve(
        ArtifactKind.SKILL,
        "context-builder-source-isolation",
        "context-builder-source-isolation-v1",
    )
    binder = object.__new__(PostgresRetrievalProjectionExecutionContractBinder)
    binder.routes = {
        "retrieval": SimpleNamespace(
            stage="retrieval",
            release_sha="a" * 40,
            embedding_dimensions=8,
            system_instruction_hash=system.content_hash,
            template_hash=template.content_hash,
            skill_content_hash=skill.content_hash,
            model_profile=SimpleNamespace(
                contract_hash="model-profile-hash",
                model_id="gpt-semantic-test",
                model_provider="scripted_provider_v2",
            ),
            route_policy=SimpleNamespace(contract_hash="route-policy-hash"),
            token_accounting_method="",
            token_accounting_evidence_ref="",
            model_context_limit=65_536,
            token_safety_margin=256,
            token_framing_overhead=16,
        )
    }
    binder.frozen_artifacts = {
        "system_instruction": system,
        "prompt_template": template,
        "skill": skill,
    }
    binder._artifacts = lambda _metadata: ()  # type: ignore[method-assign] # noqa: SLF001
    binder._materialize_selected_inputs = (  # type: ignore[method-assign] # noqa: SLF001
        lambda **_values: [
            {
                "asset_version_id": "asset-version:accepted",
                "artifact_type": "best_draft_candidate",
                "content_hash": "sha256:" + "b" * 64,
                "content": {"text": "accepted-only text"},
            }
        ]
    )
    captured: dict[str, object] = {}

    def persist(**values: object) -> SimpleNamespace:
        asset_type = str(values["asset_type"])
        captured[
            "materialization"
            if asset_type == "capability_materialization_manifest"
            else "admission"
        ] = values["contract"]
        return SimpleNamespace(
            asset_version_id=f"asset-version:{asset_type}",
            asset_type=asset_type,
            content_hash="sha256:" + "c" * 64,
        )

    binder._ensure_contract = persist  # type: ignore[method-assign] # noqa: SLF001

    preflight = binder.freeze_before_external_effect(
        capability="model.retrieval",
        request_payload={
            "stage": "retrieval",
            "max_output_tokens": 512,
            "stable_idempotency_key": "retrieval:stable:1",
            "input": {"texts": ["accepted-only text"], "purpose": "INDEX"},
            "trace_id": "trace:1",
            "correlation_id": "correlation:1",
            "_production_execution": {
                "operation_id": "operation:1",
                "attempt_id": "attempt:1",
                "project_id": "project:1",
                "fencing_token": 3,
                "provider_request_timeout_seconds": 30,
                "source_asset_version_id": "asset-version:accepted",
                "source_content_hash": "sha256:" + "b" * 64,
            },
        },
        snapshot_fencing_token=3,
        snapshot_worker_id="worker:1",
    )

    contract = captured["materialization"]
    assert isinstance(contract, dict)
    assert contract["runtime_kind"] == "FROZEN_RETRIEVAL_PROJECTION_CONTRACT"
    assert contract["source_asset_version_id"] == "asset-version:accepted"
    assert contract["route_identity"]["release_sha"] == "a" * 40
    assert contract["embedding_output_contract"] == {
        "contract_version": "retrieval-embedding-output-v1",
        "embedding_model": "gpt-semantic-test",
        "embedding_dimensions": 8,
        "vector_normalization": "L2_UNIT",
        "placeholder_vectors_allowed": False,
    }
    assert preflight.effect_binding["runtime_kind"] == (
        "FROZEN_RETRIEVAL_PROJECTION_CONTRACT"
    )
    assert (
        preflight.effect_binding["materialization_hash"]
        == contract["materialization_hash"]
    )

    first_contract = dict(contract)
    binder.freeze_before_external_effect(
        capability="model.retrieval",
        request_payload={
            "stage": "retrieval",
            "max_output_tokens": 512,
            "stable_idempotency_key": "retrieval:stable:1",
            "input": {"texts": ["accepted-only text"], "purpose": "INDEX"},
            "trace_id": "trace:1",
            "correlation_id": "correlation:1",
            "_production_execution": {
                "operation_id": "operation:1",
                "attempt_id": "attempt:1",
                "project_id": "project:1",
                "fencing_token": 3,
                "provider_request_timeout_seconds": 30,
                "source_asset_version_id": "asset-version:accepted",
                "source_content_hash": "sha256:" + "b" * 64,
            },
        },
        snapshot_fencing_token=4,
        snapshot_worker_id="worker:recovery",
    )
    assert captured["materialization"] == first_contract


def test_structured_revision_projects_slot_prose_once_with_exact_contract():
    source = {
        "chapter": 2, "title": "The choice", "text": "One immutable prose fragment.",
        "realization_contract": {"contract_digest": "sha256:frozen-scene"},
        "scene_artifacts": [{"slot_id": "scene:skeleton", "text": "One immutable prose fragment.", "used_fact_ids": []}],
        "composition_digest": "sha256:frozen-composition",
    }
    view = build_provider_task_view("revision", {"draft": source, "review": {"issues": []}})
    assert "text" not in view["chapter"]
    assert view["scene_artifacts"] == source["scene_artifacts"]
    assert view["realization_contract"] == source["realization_contract"]
    assert json.dumps(view).count("One immutable prose fragment.") == 1
    assert source["text"] == "One immutable prose fragment."


def test_planning_invalid_result_repair_view_preserves_raw_shape_without_candidate_claim():
    raw = {"objective": "Build the world", "world_foundation_json": '{"compiled_scope":["BOOK","VOLUME","ARC"]}'}
    repair = {
        "contract_version": "planning-result-repair-context.v1",
        "source_result": {"asset_version_id": "failure:v1", "content_hash": "sha256:" + "a" * 64, "content": raw, "operation_id": "failed:operation"},
        "validation_failure": {"error_code": "WORLD_FOUNDATION_SCHEMA_INVALID", "fields": [{"field_path": "$.compiled_scope", "expected_type": "string", "actual_type": "array"}]},
        "instruction": "Return the whole valid result against the frozen task.",
    }
    view = build_provider_context_view("book_plan.generate", {
        "schema_version": "novelos.planning_context_bundle.v1", "book_id": "book-1", "logical_key": "book:main", "planning_scope": "BOOK",
        "input_versions": [{"role": "book_design", "asset_version_id": "book:v1", "asset_type": "book_design", "content": {"premise": "An apprentice earns his first sword."}}],
        "repair_context": repair,
    }, {})
    assert view["repair_context"] == repair
    assert "source_candidate" not in view["repair_context"]
    assert view["repair_context"]["source_result"]["content"] == raw
    assert all(item["asset_version_id"] != "failure:v1" for item in view["segments"])


def test_benchmark_authorization_and_model_cost_do_not_leak_to_semantic_judge():
    frozen = {
        "schema_version": "story_design.authority.v1",
        "objective": "救人必须付出代价；人物声音与因果仍供审稿。",
        "routing_eligibility": "BENCHMARK_ONLY",
        "reference_predecessor_operation_id": "private-reference-predecessor",
        "routing_bootstrap_authorization": {
            "candidate_id": "deepseek:flash", "maximum_amount": "1.00",
            "campaign": {"partition": "HOLDOUT", "sample_id": "private-order-1"},
        },
        "routing_decision": {"selected": {"provider": "deepseek", "expected_quality": .99}},
        "execution_evidence": {"provider_id": "deepseek"},
    }
    view = build_provider_context_view("narrative_semantic_evaluation", {
        "source_isolation": "EXACT_CANDIDATE_ONLY",
        "selected_inputs": [{"asset_version_id": "candidate:test",
                             "asset_type": "planning_generation_candidate",
                             "content_hash": "sha256:" + "a" * 64,
                             "candidate": frozen}],
    }, {})
    encoded = json.dumps(view, ensure_ascii=False)
    for private in ("deepseek", "HOLDOUT", "BENCHMARK_ONLY", "1.00", "private-order-1", "expected_quality", "private-reference-predecessor"):
        assert private not in encoded
    assert view["selected_inputs"][0]["candidate"]["objective"] == frozen["objective"]
    assert frozen["routing_eligibility"] == "BENCHMARK_ONLY"



def test_world_v2_operational_receipts_preserve_semantics_and_legacy_replay():
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    task = {"contract_version": "world-provider-task.v2", "role": "WORLD_REASONER", "fact_mutation_allowed": False,
        "source_ref": {"asset_version_id": "source:1", "content_hash": "sha256:source"},
        "projection_identity": "sha256:projection", "context_projection": {"policy": {"token_budget": 8192},
            "selection": [{"source_event_id": "event:1", "state": {"model_id": "producer", "provider_id": "provider",
                "prompt_version": "prompt:1", "approval_resolution": {"decision": "APPROVE"},
                "fact_origin": {"kind": "GOVERNED_BACKGROUND"}, "status": "OPEN", "summary": "The witness promise remains open.",
                "claim_kind": "OBJECTIVE_EVENT", "evidence_quote": "The witness promise remains open.",
                "evidence_start": 2, "evidence_end": 40, "reader_visibility": "HIDDEN"}}], "rejections": []}}
    before = deepcopy(task)
    current = build_provider_task_view("world_candidates.generate", {"world_preparation": task})["world_preparation"]
    state = current["context_projection"]["selection"][0]["state"]
    assert state == {key: value for key, value in before["context_projection"]["selection"][0]["state"].items()
                     if key not in {"model_id", "provider_id", "prompt_version", "approval_resolution"}}
    assert current["context_projection"]["state_provenance_receipt"]["omitted_fields_by_index"] == {"0": ["approval_resolution", "model_id", "prompt_version", "provider_id"]}
    assert task == before
    assert build_provider_task_view("world_candidates.generate", {"world_preparation": current})["world_preparation"] == current
    legacy = {**before, "contract_version": "world-provider-task.v1"}
    assert build_provider_task_view("world_candidates.generate", {"world_preparation": legacy})["world_preparation"] == legacy


def test_selected_world_craft_projection_retains_cards_and_binds_omitted_history():
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.provider_views import _project_selected_world_selection, _projection_hash
    need = {"target_stage": "chapter_plan.generate", "required_card_asset_version_ids": ["card:1"],
            "condition_sources": {"plan": {"asset_version_id": "plan:1", "content_hash": "sha256:" + "a" * 64}},
            "craft_context": {"characters": ["小岑"], "obligations": ["归还剑谱"], "usage_scope_context": {"scope_transitions": ["accepted:1"]}},
            "recent_craft_usage": [{"use_id": "use:1", "phase": "SETUP", "phase_observation": "未兑现"}]}
    need["need_digest"] = _projection_hash(need)
    selection = {"need": need, "craft_policy": {"schema_version": "narrative-craft-budget.v4"},
                 "selected": [{"knowledge_card_asset_version_id": "card:1", "content_hash": "sha256:" + "b" * 64,
                               "selected_content": {"prerequisites": ["人物已有承诺"], "craft_mechanism": {"phases": ["SETUP", "PAYOFF"]}},
                               "applicability_assessment": {"status": "APPLICABLE"}}]}
    selection["selected"][0]["craft_assessment"] = {"applicability_judgment": "CONTEXTUAL_ADAPTATION_REQUIRED",
        "budget_assessment": {"accepted_usage_history": [{"acceptance_id": "accepted:1", "phase": "SETUP"}]}}
    selection["rejected"] = [{"knowledge_card_asset_version_id": "not-selected", "reason": "EXCLUDED_FOR_THIS_SCENE"}]
    selection["selection_digest"] = _projection_hash(selection)
    original = deepcopy(selection)
    projected = _project_selected_world_selection(selection)
    expected = deepcopy(original["selected"])
    expected[0]["craft_assessment"].pop("budget_assessment")
    assert projected["selected"] == expected
    assert "rejected" not in projected
    assert "/selected/0/craft_assessment/budget_assessment" in projected["world_selection_receipt"]["omitted_fields"]
    assert projected["need"] == {key: original["need"][key] for key in ("need_digest", "target_stage", "required_card_asset_version_ids")}
    assert "/need/craft_context" in projected["world_selection_receipt"]["omitted_fields"]
    assert "recent_craft_usage" not in projected["need"]
    assert projected["world_selection_receipt"]["selection_digest"] == original["selection_digest"]
    assert _project_selected_world_selection(projected) == projected
    assert selection == original
    altered = deepcopy(selection)
    altered["need"]["recent_craft_usage"].append({"use_id": "forged"})
    with pytest.raises(KernelError, match="WORLD_SELECTION_RECEIPT_INVALID"):
        _project_selected_world_selection(altered)


def test_edition_context_uses_exact_scope_position_separate_from_identity():
    from novel_forge.modules.chapter_authority.provider_views import _planning_chapter
    assert _planning_chapter({"logical_key": "edition:run:chapter:irrelevant", "edition_execution": {"chapter": 7}}) == 7
    assert _planning_chapter({"logical_key": "chapter:3"}) == 3
    with pytest.raises(KernelError, match="EDITION_PLANNING_SCOPE_INVALID"):
        _planning_chapter({"edition_execution": {"chapter": 0}})


def test_draft_provider_context_v3_preserves_full_semantics_with_explicit_larger_budget():
    from copy import deepcopy
    context = _context(0)
    context["context_segments"].append({"asset_version_id": "intent:v1", "asset_type": "chapter_execution_intent",
        "safe_summary": "必需行动与承诺" * 9_800, "structured_facts": [], "allowed_use": "generation"})
    before = deepcopy(context)
    task = build_provider_task_view("draft", {"plan": _plan()})
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        build_provider_context_view("draft", context, task)
    context.update(context_profile_version="draft-context-profile-v3", token_budget=20_000)
    view = build_provider_context_view("draft", context, task)
    assert view["contract_version"] == "provider-context-view-v3"
    assert view["selection_explanation"]["maximum_serialized_characters"] == 80_000
    assert view["segments"][-1]["safe_summary"] == before["context_segments"][-1]["safe_summary"]
    context["token_budget"] = 16_000
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        build_provider_context_view("draft", context, task)
    context["context_profile_version"] = "draft-context-profile-v2"
    context["token_budget"] = 20_000
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_CONTEXT_BUDGET_EXCEEDED"):
        build_provider_context_view("draft", context, task)


@pytest.mark.parametrize("budget", [None, 0, 24_001, True, "20000"])
def test_draft_provider_context_v3_rejects_unbounded_or_unfrozen_budget(budget):
    context = _context(0)
    context.update(context_profile_version="draft-context-profile-v3", token_budget=budget)
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_CONTEXT_BUDGET_INVALID"):
        build_provider_context_view("draft", context, {})


def test_draft_provider_context_v3_omits_only_duplicate_generated_state_summary():
    from copy import deepcopy
    context = _context(0)
    context["task_narrative_projection"]["disclosure_field_projections"] = []
    task = build_provider_task_view("draft", {"plan": _plan()})
    legacy = build_provider_context_view("draft", context, task)
    assert legacy["segments"][0]["safe_summary"]
    current = deepcopy(context)
    current.update(context_profile_version="draft-context-profile-v3", token_budget=20_000)
    view = build_provider_context_view("draft", current, task)
    assert view["segments"][0]["safe_summary"] == ""
    assert view["segments"][0]["structured_facts"] == legacy["segments"][0]["structured_facts"]
    assert view["context_correctness_receipt_hash"] == legacy["context_correctness_receipt_hash"]
    assert view["selection_explanation"]["duplicate_state_summary_count"] == 1
    assert build_provider_context_view("draft", context, task) == legacy


def _planning_history_inputs():
    from copy import deepcopy
    from novel_forge.modules.mkaos_authority.craft_selection import _hash
    observations = [{"use_id": "use:" + str(n), "acceptance_id": "accepted:" + str(n),
        "effect_status": "ACHIEVED" if n == 0 else "UNCERTAIN", "phase_transition": {"status": "SUPPORTED" if n == 0 else "UNCERTAIN"},
        "evidence": [{"quote": "证人尚未越过城门，承诺未完成。" * 80}], "execution_evidence": {"trace_id": "operational-secret"}}
        for n in range(2)]
    selection = {**_narrative_intelligence(), "selection_status": "SELECTED", "craft_policy": {"schema_version": "narrative-craft-budget.v4"},
        "need": {"recent_craft_usage": observations, "required_card_asset_version_ids": ["card:v1"], "craft_context": {"reselection": {"excluded": ["prior:card"]}}},
        "selected": [{"knowledge_card_asset_version_id": "card:v1", "craft_assessment": {"budget_assessment": {
            "recent_usage": deepcopy(observations), "accepted_usage_history": deepcopy([observations[1], observations[0], observations[1]]),
            "realization_cautions": [{"use_id": "not-in-pool", "reason": "preserve this distinct unresolved observation"}]}}}]}
    selection["need"]["need_digest"] = _hash(selection["need"])
    selection["selection_digest"] = _hash(selection)
    return {"planning_command": {"logical_key": "book:main", "planning_scope": "BOOK"},
        "frozen_inputs": [{"role": "book_design", "asset_version_id": "design:v1"}],
        "authoritative_narrative_load": _authoritative_load(), "arc_working_set": _arc_working_set(), "narrative_intelligence": selection}


def test_planning_history_projection_keeps_all_observations_order_and_legacy_view():
    from copy import deepcopy
    from novel_forge.modules.mkaos_authority.craft_context_projection import resolve_planning_craft_histories
    inputs = _planning_history_inputs()
    original = deepcopy(inputs)
    legacy = build_provider_task_view("book_plan.generate", inputs)
    assert legacy["contract_version"] == "provider-task-view-v1"
    assert "recent_usage" in legacy["narrative_intelligence"]["selected"][0]["craft_assessment"]["budget_assessment"]
    task = build_provider_task_view("book_plan.generate", {**inputs, "craft_history_projection_version": "planning-craft-history-projection.v1"})
    assert inputs == original
    assert task["contract_version"] == "provider-task-view-v2"
    projected = task["narrative_intelligence"]
    assert resolve_planning_craft_histories(projected) == legacy["narrative_intelligence"]
    budget = projected["selected"][0]["craft_assessment"]["budget_assessment"]
    assert budget["accepted_usage_history_reference"]["indices"] == [1, 0, 1]
    assert budget["realization_cautions"] == inputs["narrative_intelligence"]["selected"][0]["craft_assessment"]["budget_assessment"]["realization_cautions"]
    assert "operational-secret" not in json.dumps(task)
    assert len(json.dumps(task)) < len(json.dumps(legacy))


@pytest.mark.parametrize("drift", ["missing_version", "wrong_source", "index", "hash", "pointer", "observation"])
def test_planning_history_projection_requires_exact_frozen_context(drift):
    from copy import deepcopy
    inputs = _planning_history_inputs()
    version = "planning-craft-history-projection.v1"
    task = build_provider_task_view("book_plan.generate", {**inputs, "craft_history_projection_version": version})
    context = {"schema_version": "novelos.planning_context_bundle.v1", "book_id": "book:main", "planning_scope": "BOOK",
        "logical_key": "book:main", "craft_history_projection_version": version, "narrative_intelligence": deepcopy(inputs["narrative_intelligence"]),
        "input_versions": [{"role": "book_design", "asset_version_id": "design:v1", "content": {"premise": "保护证人与公开证词相互牵制。"}}]}
    assert build_provider_context_view("book_plan.generate", context, task)["stage"] == "book_plan.generate"
    reference = task["narrative_intelligence"]["selected"][0]["craft_assessment"]["budget_assessment"]["recent_usage_reference"]
    if drift == "missing_version":
        context.pop("craft_history_projection_version")
    elif drift == "wrong_source":
        context["narrative_intelligence"]["need"]["required_card_asset_version_ids"] = ["different:card"]
    elif drift == "observation":
        task["narrative_intelligence"]["need"]["recent_craft_usage"][1]["effect_status"] = "ACHIEVED"
    else:
        reference[{"index": "indices", "hash": "content_hash", "pointer": "json_pointer"}[drift]] = {
            "index": [0, 0], "hash": "sha256:" + "0" * 64, "pointer": "/different/book/history"}[drift]
    with pytest.raises(KernelError, match="CRAFT_CONTEXT_PROJECTION_DRIFT"):
        build_provider_context_view("book_plan.generate", context, task)


def test_actor_step_support_has_distinct_producer_task_and_keeps_observation_independent():
    from tests.unit.test_world_actor_execution import execution, observation
    from novel_forge.modules.canon_graph.grounding import grounded_claims
    _, binding, event = execution()
    revision, extraction = observation(binding, event)
    claims = grounded_claims(extraction)
    task = build_provider_task_view('canon_support', {'revision': revision, 'grounding': extraction['grounding'], 'claims': claims})
    assert task['contract_version'] == 'provider-task-view-v2'
    assert task['claims'] == claims
    comparison = task['claims'][0]['claim']['actor_step_execution']
    assert comparison['approved_target']['action'] != comparison['observed_action'] == revision['text']
    assert task['actor_step_support_contract'] == 'actor-step-execution-comparison.v1'
    legacy = build_provider_task_view('canon_support', {'revision': revision, 'claims': [{'claim': {'claim_kind': 'OBJECTIVE_EVENT'}}]})
    assert legacy['contract_version'] == 'provider-task-view-v1'
    assert 'actor_step_support_contract' not in legacy
    claims[0]['claim']['actor_step_execution']['contract_version'] = 'latest'
    with pytest.raises(KernelError, match='WORLD_ACTOR_EXECUTION_CONTRACT_INVALID'):
        build_provider_task_view('canon_support', {'revision': revision, 'claims': claims})


def _matrix_alias_context():
    from copy import deepcopy
    source = {'role': 'chapter_group_plan', 'asset_version_id': 'group:exact:v1', 'content_hash': 'sha256:' + 'e' * 64,
        'content': {'objective': '保留证词，护送承诺尚未完成。', 'hard_constraints': ['不得把未来送达写成既成事实。'],
            'chapter_function_matrix': [{'chapter_number': 2, 'objective': '已接纳的交付。'},
                {'chapter_number': 3, 'objective': '开始护送，尚未越关。', 'required_facts': ['证人在关内。']}],
            'narrative_segments': [{'chapter_range': [1, 2], 'private_preparation_notes': '历史目录' * 4000},
                                   {'chapter_range': [3, 3], 'purpose': '保留当前窗口依赖。'}],
            'audit_directory': {'duplicate_only': 'historical-directory' * 300}}}
    alias = {**deepcopy(source), 'role': 'chapter_function_matrix_row'}
    return {'schema_version': 'novelos.planning_context_bundle.v1', 'logical_key': 'chapter:3', 'planning_scope': 'CHAPTER',
        'planning_input_projection_version': 'planning-input-role-references.v1', 'input_versions': [source, alias]}


def test_matrix_alias_references_exact_current_row_and_all_shared_constraints():
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.provider_views import compile_planning_provider_context, _projection_hash
    context = _matrix_alias_context()
    original = deepcopy(context)
    view, _ = compile_planning_provider_context('chapter_plan.generate', context)
    assert context == original
    assert view['contract_version'] == 'provider-context-view-v3'
    group = view['segments'][0]['content']
    reference = view['segments'][1]['content']
    assert reference['json_pointer'] == '/segments/0/content/chapter_function_matrix/0'
    assert reference['row_content_hash'] == _projection_hash(group['chapter_function_matrix'][0])
    assert reference['group_constraints_pointer'] == '/segments/0/content'
    assert group['hard_constraints'] == context['input_versions'][0]['content']['hard_constraints']
    assert group['chapter_function_matrix'] == [context['input_versions'][0]['content']['chapter_function_matrix'][1]]
    legacy = deepcopy(context)
    legacy.pop('planning_input_projection_version')
    old, _ = compile_planning_provider_context('chapter_plan.generate', legacy)
    assert old['contract_version'] == 'provider-context-view-v2'
    assert 'audit_directory' in old['segments'][1]['content']


@pytest.mark.parametrize('field', ['asset_version_id', 'content_hash', 'content'])
def test_matrix_alias_never_references_a_different_frozen_group(field):
    from novel_forge.modules.chapter_authority.provider_views import compile_planning_provider_context
    context = _matrix_alias_context()
    alias = context['input_versions'][1]
    if field == 'content':
        alias[field]['hard_constraints'] = ['另一版本的约束不能被父组覆盖。']
    else:
        alias[field] = 'different-source'
    view, _ = compile_planning_provider_context('chapter_plan.generate', context)
    assert 'json_pointer' not in view['segments'][1]['content']
    assert view['segments'][1]['content']['hard_constraints'] == alias['content']['hard_constraints']


def test_related_arc_projection_retains_semantic_constraints_and_audits_host_fields():
    from copy import deepcopy
    from novel_forge.modules.chapter_authority.provider_views import compile_planning_provider_context

    semantic = {'thread_id': 'arc:truth', 'required_events': ['witness must choose'],
        'world_realization': {'knowledge_boundary': 'private oath remains private'},
        'character_realization': {'motivation': 'protect witness'},
        'commitment_contract': {'payoff': 'future only'},
        'canon_dependencies': ['accepted:oath'], 'hard_constraints': ['no omniscience'],
        'soft_constraints': ['preserve silence']}
    source = {**semantic, 'generator_operation_name': 'arc_plan.generate',
        'narrative_search_projection': {'scores': {'style': .99}},
        'operation_id': 'host-operation'}
    context = {'schema_version': 'novelos.planning_context_bundle.v1',
        'logical_key': 'chapter:2', 'planning_scope': 'CHAPTER', 'input_versions': [
            {'role': role, 'asset_type': 'arc_plan', 'asset_version_id': role,
             'content_hash': 'sha256:' + 'a' * 64, 'content': deepcopy(source)}
            for role in ['arc_plans', 'related_arc:1', 'dependent_arc:1']]}
    frozen = deepcopy(context)
    view, audit = compile_planning_provider_context('chapter_plan.generate', context)
    assert context == frozen
    contents = [segment['content'] for segment in view['segments']]
    assert contents[0] == contents[1] == contents[2]
    for content in contents:
        for key, value in semantic.items():
            assert content[key] == value
        assert 'narrative_search_projection' not in content
        assert 'operation_id' not in content
    assert 'narrative_search_projection' in json.dumps(audit)
