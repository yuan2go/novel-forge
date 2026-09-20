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
    for private in ("deepseek", "HOLDOUT", "BENCHMARK_ONLY", "1.00", "private-order-1", "expected_quality"):
        assert private not in encoded
    assert view["selected_inputs"][0]["candidate"]["objective"] == frozen["objective"]
    assert frozen["routing_eligibility"] == "BENCHMARK_ONLY"
