from __future__ import annotations

from copy import deepcopy

from novel_forge.modules.runtime_proof import (
    CHAPTER_REAL_PROVIDER_STAGES,
    CONTINUITY_STATE_TYPES,
    PLANNING_STAGES,
    evaluate_short_longform_evidence,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _model_authority(*, effort: str) -> dict[str, object]:
    return {
        "policy_requested_model": "gpt-5.6-sol",
        "frozen_route_model": "gpt-5.6-sol",
        "invocation_model": "gpt-5.6-sol",
        "provider_observed_model": "unavailable",
        "policy_requested_reasoning_effort": effort,
        "frozen_route_reasoning_effort": effort,
        "invocation_reasoning_effort": effort,
        "provider_observed_reasoning_effort": "unavailable",
        "model_profile_id": "profile:proof",
        "model_profile_version": 1,
        "model_profile_hash": HASH_A,
        "route_policy_id": "route:proof",
        "route_policy_version": 1,
        "route_policy_hash": HASH_B,
        "route_snapshot_id": "route-snapshot:proof",
        "route_snapshot_hash": HASH_A,
        "local_user_config_ignored": True,
        "local_user_config_is_model_authority": False,
    }


def _provider_evidence(*, effort: str) -> dict[str, object]:
    return {
        "real_provider_call": True,
        "fixture_protocol_only": False,
        "usage": {
            "availability": "AVAILABLE",
            "measurement": "MEASURED",
            "total_tokens": 100,
        },
        "cost": {
            "availability": "AVAILABLE",
            "measurement": "ESTIMATED",
            "estimated": True,
            "provider_billed": False,
        },
        "model_authority": _model_authority(effort=effort),
    }


def _complete_evidence() -> dict[str, object]:
    planning = []
    for index, stage in enumerate(sorted(PLANNING_STAGES), start=1):
        planning.append(
            {
                "stage": stage,
                "operation_status": "SUCCEEDED",
                "attempt_status": "SUCCEEDED",
                "lease_id": f"lease:planning:{index}",
                "fencing_token": 1,
                "capability_pack_snapshot_ref": f"pack-snapshot:{index}",
                "active_deployment_id": "deployment:planning",
                "agent_runtime_qualification": "QUALIFIED_REAL_RUNTIME",
                "work_order_id": f"work-order:{index}",
                "runtime_binding_id": f"runtime-binding:{index}",
                "external_effect_id": f"effect:{index}",
                "provider_receipt_id": f"receipt:{index}",
                "candidate_asset_version_id": f"candidate:{index}",
                "candidate_accepted": True,
                "commit_authority": "STORY_DESIGN_AUTHORITY",
                "evidence_refs": [f"operation:{index}"],
                **_provider_evidence(effort="xhigh"),
            }
        )
    readers = []
    for chapter in (1, 2, 3):
        readers.append(
            {
                "chapter_number": chapter,
                "capability_pack_id": "reader_outcome_pack",
                "external_effect_id": f"reader-effect:{chapter}",
                "provider_receipt_id": f"reader-receipt:{chapter}",
                "report_asset_version_id": f"reader-report:{chapter}",
                "state_transition_asset_version_id": f"reader-state:{chapter}",
                "issue_set_asset_version_id": f"reader-issues:{chapter}",
                "evidence_refs": [f"reader-operation:{chapter}"],
                **_provider_evidence(effort="high"),
            }
        )
    chapters = []
    previous_outputs: dict[str, str] = {}
    for chapter in (1, 2, 3):
        outputs = {
            state_type: f"asset:{state_type}:chapter:{chapter}"
            for state_type in CONTINUITY_STATE_TYPES
        }
        chapters.append(
            {
                "chapter_number": chapter,
                "accepted": True,
                "input_state_refs": dict(previous_outputs),
                "output_state_refs": outputs,
                "provider_calls": [
                    {
                        "stage": stage,
                        "evidence_refs": [f"chapter-provider:{chapter}:{stage}"],
                        **_provider_evidence(effort="high"),
                    }
                    for stage in sorted(CHAPTER_REAL_PROVIDER_STAGES)
                ],
                "evidence_refs": [f"chapter-acceptance:{chapter}"],
            }
        )
        previous_outputs = outputs
    attempt_one = {
        "operation_id": "operation:retry",
        "attempt_id": "attempt:1",
        "lease_id": "lease:1",
        "fencing_token": 1,
        "fence_identity": "attempt:1:1",
        "evidence_refs": ["attempt:1"],
        **_provider_evidence(effort="xhigh"),
    }
    attempt_two = {
        "operation_id": "operation:retry",
        "attempt_id": "attempt:2",
        "lease_id": "lease:2",
        "fencing_token": 2,
        "fence_identity": "attempt:2:2",
        "evidence_refs": ["attempt:2"],
        **_provider_evidence(effort="xhigh"),
    }
    return {
        "release": {
            "commit_sha": "c" * 40,
            "worktree_clean": True,
            "evidence_refs": ["release:c"],
        },
        "environment": {
            "postgresql": "REAL",
            "object_storage": "MINIO_REAL",
            "provider": "CODEX_CLI_REAL",
            "evidence_refs": ["environment:proof"],
        },
        "planning": {"generators": planning},
        "reader_outcome": {
            "chapter_pack_id": "chapter_generation_pack",
            "reports": readers,
            "judge": {
                "mode": "SHADOW",
                "publish_blocking": False,
                "authority_commit_allowed": False,
                "direct_plan_mutation_allowed": False,
                "evidence_refs": ["reader-judge:shadow"],
            },
        },
        "retry": {
            "fault_injection": "after_measured_usage_before_candidate_acceptance",
            "attempt_1": attempt_one,
            "attempt_2": attempt_two,
            "frozen_governance_identity_equal": True,
            "frozen_materialization_equal": True,
            "stale_fence_commit_rejected": True,
            "accepted_candidate_count": 1,
            "provider_execution_count": 1,
            "recovered_provider_result": True,
            "evidence_refs": ["retry:operation"],
        },
        "book_authority": {
            "state": "COMPLETED",
            "accepted_through_chapter": 3,
            "mutations": [
                {
                    "command_name": name,
                    "transaction_command": True,
                    "state_event_id": f"event:{name}",
                    "audit_log_id": f"audit:{name}",
                    "outbox_id": f"outbox:{name}",
                    "evidence_refs": [f"command:{name}"],
                }
                for name in ("start", "accept_chapter", "resume")
            ],
        },
        "continuity": {"chapters": chapters},
        "longform_recap": {
            "accepted_chapter_request_id": "chapter-request:2",
            "reader_outcome_asset_version_id": "reader-report:2",
            "checkpoint_operation_id": "recap-operation:1",
            "recap_asset_version_id": "recap:1",
            "immutable": True,
            "deviation_asset_version_id": "deviation:1",
            "replan_request_asset_version_id": "replan-request:1",
            "control_flow_proof": True,
            "reader_intelligence_effectiveness_proven": False,
            "evidence_refs": ["recap-operation:1"],
        },
        "replan": {
            "source_recap_asset_version_id": "recap:1",
            "replan_request_asset_version_id": "replan-request:1",
            "replacement_candidate_asset_version_id": "chapter-plan:3:new",
            "plan_change_proposal_id": "proposal:1",
            "approval_decision_id": "decision:1",
            "status": "RESUMED",
            "future_only": True,
            "executed_plan_preserved": True,
            "future_plan_superseded": True,
            "old_input_snapshot_id": "snapshot:1",
            "new_input_snapshot_id": "snapshot:2",
            "resumed_chapter_plan_version": "chapter-plan:3:new",
            "evidence_refs": ["replan:1"],
        },
        "resume": {
            "planning_process_id": "process:planning",
            "book_process_id": "process:book",
            "fresh_composition_root": True,
            "persisted_state_only": True,
            "checkpoint_business_state_used": False,
            "object_storage_namespace_preserved": True,
            "planning_checkpoint_ref": "checkpoint:planning",
            "book_phase_resumed": True,
            "duplicate_provider_effect_count": 0,
            "duplicate_chapter_count": 0,
            "duplicate_canon_commit_count": 0,
            "duplicate_reader_sidecar_count": 0,
            "evidence_refs": ["resume:process-boundary"],
        },
    }


def test_all_nine_flags_are_derived_from_complete_evidence() -> None:
    evidence = _complete_evidence()
    before = deepcopy(evidence)

    evaluation = evaluate_short_longform_evidence(evidence)

    assert all(evaluation.proof_flags.values())
    assert evidence == before
    assert evaluation.checks["planning_real_provider_proven"].limitations == (
        "Codex did not independently report provider model identity; invocation is proven from frozen argv only.",
    )


def test_model_authority_mismatch_fails_planning_and_aggregate_closed() -> None:
    evidence = _complete_evidence()
    generator = evidence["planning"]["generators"][0]  # type: ignore[index]
    generator["model_authority"]["invocation_model"] = "local-default"  # type: ignore[index]

    evaluation = evaluate_short_longform_evidence(evidence)

    assert evaluation.proof_flags["planning_real_provider_proven"] is False
    assert evaluation.proof_flags["short_longform_runtime_proven"] is False
    assert any(
        "model_authority" in reason
        for reason in evaluation.checks["planning_real_provider_proven"].failure_reasons
    )


def test_continuity_requires_all_ten_previous_chapter_state_refs() -> None:
    evidence = _complete_evidence()
    chapter_two = evidence["continuity"]["chapters"][1]  # type: ignore[index]
    del chapter_two["input_state_refs"]["story_state_snapshot"]  # type: ignore[index]

    evaluation = evaluate_short_longform_evidence(evidence)

    assert evaluation.proof_flags["three_chapter_continuity_proven"] is False
    assert any(
        "story_state_snapshot" in reason
        for reason in evaluation.checks[
            "three_chapter_continuity_proven"
        ].failure_reasons
    )


def test_continuity_requires_the_real_chapter_provider_chain() -> None:
    evidence = _complete_evidence()
    chapter_two = evidence["continuity"]["chapters"][1]  # type: ignore[index]
    chapter_two["provider_calls"] = [  # type: ignore[index]
        call
        for call in chapter_two["provider_calls"]  # type: ignore[index]
        if call["stage"] != "quality_longform"
    ]

    evaluation = evaluate_short_longform_evidence(evidence)

    assert evaluation.proof_flags["three_chapter_continuity_proven"] is False
    assert any(
        "quality_longform" in reason
        for reason in evaluation.checks[
            "three_chapter_continuity_proven"
        ].failure_reasons
    )
