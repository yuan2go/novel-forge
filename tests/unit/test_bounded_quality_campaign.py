from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from novel_forge.modules.runtime_proof import quality_campaign as campaign_module
from novel_forge.modules.runtime_proof.quality_campaign import (
    BoundedQualityCampaignProfile,
    BoundedQualityCampaignRunner,
    CampaignExecutionCheckpoint,
    QualityCampaignTerminalError,
    bounded_quality_chapter_fixture_response,
    bounded_quality_planning_fixture_response,
    classify_campaign_recovery_exhaustion,
    load_quality_campaign_profile,
    semantic_quality_evidence_identity,
)


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "config/proof_campaigns/quality_qualification_v1.json"


def _profile_payload() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_repository_profile_is_exactly_two_by_four_and_hash_frozen() -> None:
    profile = load_quality_campaign_profile(PROFILE_PATH, repository_root=ROOT)

    assert profile.chapter_group_ranges == ((1, 4), (5, 8))
    assert profile.chapter_limit == 8
    assert profile.required_evaluator_count == 2
    assert profile.chapter_pairs_per_evaluator == 8
    assert profile.arc_pairs_per_evaluator == 1
    assert profile.digest.startswith("sha256:")
    assert profile.allows_chapter(8) is True
    assert profile.allows_chapter(9) is False
    assert profile.provider_routes["real"]["generator"]["silent_fallback"] is False
    assert (
        profile.provider_routes["real"]["judge"]["independence_relationship"]
        == "DEPENDENT_SAME_MODEL"
    )
    budget = profile.to_dict()["budget_policy"]
    assert budget["token_limit"] == 6_600_000
    assert budget["cost_limit_per_call_usd"] == "4.00"
    assert budget["cost_limit_per_operation_usd"] == "8.00"
    assert budget["cost_limit_per_chapter_usd"] == "20.00"
    assert budget["freeze_headroom_policy"] == {
        "minimum_remaining_provider_calls": 80,
        "minimum_remaining_tokens": 4_800_000,
        "minimum_remaining_cost_usd": "60.00",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"chapter_group_ranges": [[1, 4], [5, 9]]}, "exactly"),
        ({"human_protocol": {"required_evaluator_count": 1}}, "two evaluators"),
        ({"stop_policy": {"chapter_9_allowed": True}}, "Chapter 9"),
        ({"budget_policy": {"chapter_limit": 9}}, "chapter_limit"),
        (
            {"budget_policy": {"cost_limit_per_call_usd": "90.00"}},
            "monotonic",
        ),
        (
            {"budget_policy": {"cost_limit_per_operation_usd": "3.00"}},
            "monotonic",
        ),
        (
            {
                "budget_policy": {
                    "freeze_headroom_policy": {
                        "minimum_remaining_provider_calls": 121,
                    }
                }
            },
            "freeze headroom",
        ),
    ],
)
def test_profile_rejects_scope_budget_or_human_protocol_drift(
    mutation: dict, message: str
) -> None:
    payload = _profile_payload()
    for key, value in mutation.items():
        if isinstance(value, dict):
            payload[key].update(value)
        else:
            payload[key] = value

    with pytest.raises(ValueError, match=message):
        BoundedQualityCampaignProfile.from_mapping(payload)


def test_profile_rejects_strawman_baseline_and_hash_drift(tmp_path: Path) -> None:
    payload = _profile_payload()
    payload["baseline_protocol"]["provider_model_parity"] = False
    with pytest.raises(ValueError, match="comparable baseline"):
        BoundedQualityCampaignProfile.from_mapping(payload)

    copied = deepcopy(_profile_payload())
    source = tmp_path / "skill.md"
    source.write_text("changed", encoding="utf-8")
    copied["prompt_skill_lineage"] = {
        "skill.md": "sha256:" + "0" * 64,
    }
    profile = BoundedQualityCampaignProfile.from_mapping(copied)
    with pytest.raises(ValueError, match="hash drift"):
        profile.verify_repository_hashes(tmp_path)


def test_freeze_materializes_exact_quality_manifest() -> None:
    profile = load_quality_campaign_profile(PROFILE_PATH, repository_root=ROOT)
    manifest = profile.freeze_manifest(
        campaign_id="quality-campaign:test:v1",
        exact_release_sha="a" * 40,
        migration_head="20260826_0101_quality_qualification",
        mode="scripted",
        project_id="project:test",
        workspace_id="workspace:project:test",
        book_id="book:project:test",
        capability_pack_manifest={
            "planning": {"deployment_id": "planning:v1", "hash": "sha256:" + "1" * 64},
            "chapter": {"deployment_id": "chapter:v1", "hash": "sha256:" + "2" * 64},
            "reader_proxy": {
                "deployment_id": "reader:v1",
                "hash": "sha256:" + "3" * 64,
            },
            "narrative_evaluation": {
                "deployment_id": "evaluation:v1",
                "hash": "sha256:" + "4" * 64,
            },
        },
        foundation_lineage={"qualified_foundation_set": "foundation:v1"},
        planning_lineage={"book_plan": "book-plan:v1", "arcs": ["arc:v1"]},
        realization_lineage={"groups": ["realization:1-4", "realization:5-8"]},
    )
    frozen = manifest.to_dict()

    assert frozen["chapter_group_ranges"] == [[1, 4], [5, 8]]
    assert frozen["exact_release_sha"] == "a" * 40
    assert frozen["provider_route_manifest"]["generator"]["execution_class"] == (
        "SCRIPTED_FIXTURE"
    )
    assert frozen["baseline_protocol"]["kind"] == ("FIRST_DRAFT_VS_ACCEPTED_REVISION")
    assert frozen["budget_policy"]["chapter_limit"] == 8


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.provider_effects: list[str] = []
        self.fail_once_after_group: tuple[int, int] | None = None

    def run_group(self, chapter_range: tuple[int, int]) -> dict:
        self.calls.append(chapter_range)
        effects = [f"provider-effect:{chapter}" for chapter in range(*chapter_range)]
        effects.append(f"provider-effect:{chapter_range[1]}")
        self.provider_effects.extend(
            effect for effect in effects if effect not in self.provider_effects
        )
        if self.fail_once_after_group == chapter_range:
            self.fail_once_after_group = None
            raise RuntimeError("injected after group commit")
        return {
            "chapter_range": list(chapter_range),
            "accepted_chapters": list(range(chapter_range[0], chapter_range[1] + 1)),
            "provider_effect_ids": effects,
            "group_run_id": f"group:{chapter_range[0]}-{chapter_range[1]}",
            "reader_state_asset_version_id": f"reader:{chapter_range[1]}:v1",
            "recap_asset_version_id": f"recap:{chapter_range[1]}:v1",
        }

    def final_evidence(self) -> dict:
        return {
            "accepted_through_chapter": 8,
            "arc_evaluations": [{"arc_plan_version_id": "arc:primary:v1"}],
            "volume_evaluation": {"scope": "volume:1:chapters:1-8"},
            "blind_pack_ids": ["pack:reviewer-1", "pack:reviewer-2"],
            "semantic_evidence_hash": "sha256:" + "7" * 64,
            "provider_runtime_evidence_asset_version_id": "provider-evidence:v1",
            "provider_runtime_evidence_content_hash": "sha256:" + "8" * 64,
            "provider_runtime_evidence": {
                "provider_dispatch_count": 8,
                "real_provider_call_count": 0,
                "provider_failure_count": 0,
                "provider_retry_count": 0,
                "measured_input_tokens": 0,
                "measured_output_tokens": 0,
                "measured_total_tokens": 0,
                "settled_cost_amount": "0",
                "currency": "USD",
                "capability_pack_snapshots": [],
            },
        }


def test_runner_executes_only_two_consecutive_groups_and_stops_at_eight() -> None:
    profile = load_quality_campaign_profile(PROFILE_PATH, repository_root=ROOT)
    runtime = _Runtime()
    result = BoundedQualityCampaignRunner(profile).run(runtime)

    assert runtime.calls == [(1, 4), (5, 8)]
    assert result.accepted_chapters == tuple(range(1, 9))
    assert result.accepted_through_chapter == 8
    assert result.chapter_group_ranges == ((1, 4), (5, 8))
    assert result.duplicate_provider_effect_ids == ()
    assert result.blind_pack_count == 2
    assert result.semantic_evidence_hash == "sha256:" + "7" * 64
    assert result.provider_dispatch_count == 8
    assert result.qualification_boundary == "SCRIPTED_PROTOCOL_ONLY"


def test_runner_resumes_from_immutable_checkpoint_without_duplicate_effects() -> None:
    profile = load_quality_campaign_profile(PROFILE_PATH, repository_root=ROOT)
    runtime = _Runtime()
    runtime.fail_once_after_group = (1, 4)
    runner = BoundedQualityCampaignRunner(profile)

    with pytest.raises(RuntimeError, match="after group commit"):
        runner.run(runtime)
    checkpoint = CampaignExecutionCheckpoint(
        profile_digest=profile.digest,
        accepted_through_chapter=4,
        completed_group_ranges=((1, 4),),
        accepted_chapters=(1, 2, 3, 4),
        provider_effect_ids=tuple(runtime.provider_effects),
    )
    recovered = runner.run(runtime, checkpoint=checkpoint)

    assert recovered.accepted_through_chapter == 8
    assert recovered.duplicate_provider_effect_ids == ()
    assert runtime.calls == [(1, 4), (5, 8)]


def test_runner_fails_closed_when_wall_clock_budget_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _profile_payload()
    payload["budget_policy"]["wall_clock_seconds"] = 1
    profile = BoundedQualityCampaignProfile.from_mapping(payload)
    clock = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(campaign_module, "monotonic", lambda: next(clock))

    with pytest.raises(
        QualityCampaignTerminalError,
        match="wall-clock budget expired",
    ) as raised:
        BoundedQualityCampaignRunner(profile).run(_Runtime())
    assert raised.value.failure_code == "CAMPAIGN_WALL_CLOCK_BUDGET_EXPIRED"


def test_runtime_recovery_becomes_terminal_only_after_attempts_are_exhausted() -> (
    None
):
    retryable = {
        "operation_id": "operation:canon",
        "status": "FAILED_RETRYABLE",
        "attempt_count": 1,
        "max_attempts": 2,
    }
    assert (
        classify_campaign_recovery_exhaustion(
            [retryable],
            root_operation_id="operation:chapter-root",
            error_code="CHAPTER_PROVIDER_OUTPUT_SEMANTIC_INVALID",
        )
        is None
    )

    terminal = classify_campaign_recovery_exhaustion(
        [{**retryable, "attempt_count": 2}],
        root_operation_id="operation:chapter-root",
        error_code="BUDGET_CAP_EXCEEDED",
    )

    assert terminal is not None
    assert terminal.failure_code == "CAMPAIGN_RUNTIME_RECOVERY_EXHAUSTED"
    assert terminal.measurements["kernel_error_code"] == "BUDGET_CAP_EXCEEDED"
    assert terminal.measurements["exhausted_operations"] == [
        {
            **retryable,
            "attempt_count": 2,
        }
    ]


def test_checkpoint_rejects_profile_drift_or_chapter_nine() -> None:
    profile = load_quality_campaign_profile(PROFILE_PATH, repository_root=ROOT)

    with pytest.raises(ValueError, match="profile digest"):
        CampaignExecutionCheckpoint(
            profile_digest="sha256:" + "0" * 64,
            accepted_through_chapter=4,
            completed_group_ranges=((1, 4),),
            accepted_chapters=(1, 2, 3, 4),
            provider_effect_ids=(),
        ).validate(profile)
    with pytest.raises(ValueError, match="Chapter 9"):
        CampaignExecutionCheckpoint(
            profile_digest=profile.digest,
            accepted_through_chapter=9,
            completed_group_ranges=((1, 4), (5, 8)),
            accepted_chapters=tuple(range(1, 10)),
            provider_effect_ids=(),
        ).validate(profile)


def test_semantic_evidence_identity_ignores_runtime_ids_but_not_story_change() -> None:
    left = {
        "project_id": "project:left",
        "source_acceptance_ids": ["acceptance:left"],
        "arc": {
            "arc_plan_version_id": "arc:left:v1",
            "status": "COMPLETED",
        },
        "candidate": {"text": "The choice closes the safe route."},
        "reader": {"continue_intent": [[1, 0.7], [2, 0.8]]},
    }
    right = deepcopy(left)
    right["project_id"] = "project:right"
    right["source_acceptance_ids"] = ["acceptance:right"]
    right["arc"]["arc_plan_version_id"] = "arc:right:v9"

    assert semantic_quality_evidence_identity(left) == (
        semantic_quality_evidence_identity(right)
    )
    right["candidate"]["text"] = "The choice leaves the safe route open."
    assert semantic_quality_evidence_identity(left) != (
        semantic_quality_evidence_identity(right)
    )


def test_bounded_planning_fixture_materializes_only_two_four_chapter_groups() -> None:
    first = bounded_quality_planning_fixture_response(
        "chapter_group_plan.generate",
        {
            "planning_command": {
                "project_id": "project:test",
                "book_id": "book:test",
                "logical_key": "chapter-group:containing:1",
                "input_versions": {"arc_plans": "arc:primary:v1"},
                "narrative_search_accepted_through_chapter": 0,
            },
            "frozen_inputs": [],
        },
    )
    second = bounded_quality_planning_fixture_response(
        "chapter_group_plan.generate",
        {
            "planning_command": {
                "project_id": "project:test",
                "book_id": "book:test",
                "logical_key": "chapter-group:containing:5",
                "input_versions": {"arc_plans": "arc:primary:v1"},
                "narrative_search_accepted_through_chapter": 4,
            },
            "frozen_inputs": [],
        },
    )

    assert first["chapter_range"] == [1, 4]
    assert second["chapter_range"] == [5, 8]
    assert [row["chapter_number"] for row in first["chapter_function_matrix"]] == [
        1,
        2,
        3,
        4,
    ]
    assert [item["chapter_number"] for item in second["narrative_event_chain"]] == [
        5,
        6,
        7,
        8,
    ]
    with pytest.raises(ValueError, match="only permits"):
        bounded_quality_planning_fixture_response(
            "chapter_group_plan.generate",
            {
                "planning_command": {
                    "project_id": "project:test",
                    "book_id": "book:test",
                    "logical_key": "chapter-group:containing:9",
                    "input_versions": {"arc_plans": "arc:primary:v1"},
                    "narrative_search_accepted_through_chapter": 8,
                },
                "frozen_inputs": [],
            },
        )


def test_bounded_chapter_fixture_carries_arc_payoff_and_reader_evidence() -> None:
    reader = bounded_quality_chapter_fixture_response(
        "reader_outcome", {"chapter": 8, "assets": {"draft:v1": {}}}
    )
    canon = bounded_quality_chapter_fixture_response(
        "canon_extraction",
        {
            "revision": {"chapter": 4, "text": "accepted bounded prose"},
            "execution_expectations": {
                "frozen_arc_plans": [
                    {
                        "arc_plan_version_id": "arc:primary:v1",
                        "completion_criteria": [
                            {"criterion_id": f"criterion:{chapter}"}
                            for chapter in range(1, 9)
                        ],
                    }
                ],
                "narrative_realization": {
                    "events": [
                        {
                            "event_id": "event:chapter:4",
                            "decision": "accept cost four",
                            "action": "publish the witness record",
                            "consequence": "the safe route closes",
                            "state_deltas": [
                                {
                                    "state_kind": "character_arc",
                                    "entity_id": "protagonist:accountability",
                                    "from_state": "INTEGRATED_3",
                                    "to_state": "INTEGRATED_4",
                                }
                            ],
                        }
                    ]
                },
            },
        },
    )

    assert reader["reader_state"]["continue_intent"] > 0.8
    assert reader["reader_state"]["confusion"] < 0.2
    assert canon["arc_evidence"][0]["progress_units"] == 1
    assert canon["arc_evidence"][0]["completion_criterion_ids"] == ["criterion:4"]
    assert canon["obligation_changes"][0]["status"] == "FULFILLED"
    assert canon["obligation_changes"][0]["payoff_evidence"] is not None
