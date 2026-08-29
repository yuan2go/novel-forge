from __future__ import annotations

from dataclasses import replace

import pytest

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.book_followup_authority.handlers import ReaderOutcomeHandler
from novel_forge.modules.chapter_authority.model_effects import ModelProviderResult
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration import (
    JudgeMode,
    ReaderJudgeQualificationStatus,
)
from novel_forge.modules.reader_judge_authority import (
    ReaderJudgeDefinition,
    ReaderJudgeExecutionSnapshot,
    ReaderJudgeResolutionScope,
)
from novel_forge.modules.reader_judge_authority.domain import (
    require_mode_status,
    safe_shadow_snapshot,
    validate_qualification_transition,
)


class _Resolver:
    def __init__(self, snapshot: ReaderJudgeExecutionSnapshot) -> None:
        self.snapshot = snapshot

    def resolve(self, _scope):
        return self.snapshot


class _ModelPort:
    external_effect_backed = True

    def invoke(self, _request, *, stage, payload, reservation_tokens=None):
        assert stage == "reader_outcome"
        assert payload["reader_judge_execution_snapshot"]["snapshot_id"]
        assert reservation_tokens == 8_000
        return ModelProviderResult(
            output={
                "reader_state": {
                    "continue_intent": 0.2,
                    "confusion": 0.9,
                    "drop_risk": 0.9,
                    "repetition_fatigue": 0.2,
                    "trust": 0.7,
                    "character_attachment": 0.7,
                    "antagonist_pressure": 0.7,
                    "payoff_satisfaction": 0.7,
                    "curiosity": 0.7,
                    "satisfaction": 0.7,
                    "promise_expectation": 0.7,
                },
                "evidence": [{"span": "fixture:1", "reason": "bounded test"}],
            },
            provider_id="scripted-fixture",
            model_id="reader-judge-fixture",
            prompt_version="prompt:v1",
            skill_version="skill:v1",
            input_tokens=0,
            output_tokens=0,
            cost_amount="0",
            currency="USD",
            real_model_call=False,
            execution_evidence={
                "execution_result": {
                    "usage_receipt_ref": "usage:1",
                    "cost_receipt_ref": "cost:1",
                },
                "route_snapshot": {"route_snapshot_id": "route:1"},
            },
        )


def _scope() -> ReaderJudgeResolutionScope:
    return ReaderJudgeResolutionScope(
        project_id="project-1",
        book_id="book-1",
        platform="platform-1",
        genre="genre-1",
        subgenre="subgenre-1",
        chapter_type="STANDARD",
        reader_segment="segment-1",
        model_version="model-v1",
    )


def _qualified_snapshot(mode: JudgeMode) -> ReaderJudgeExecutionSnapshot:
    return ReaderJudgeExecutionSnapshot(
        snapshot_id=f"snapshot:{mode.value}",
        project_id="project-1",
        book_id="book-1",
        judge_id="judge-1",
        judge_version_id="judge-version-1",
        definition_hash="sha256:" + "a" * 64,
        qualification_decision_id="decision-1",
        calibration_profile_id="profile-1",
        mode=mode,
        calibration_status=(
            ReaderJudgeQualificationStatus.QUALIFIED
            if mode is JudgeMode.BOUNDED_PRODUCTION
            else ReaderJudgeQualificationStatus.CALIBRATED
        ),
        score_semantics="CALIBRATED_PROBABILITY",
        publish_blocking=False,
        authority_commit_allowed=mode is JudgeMode.BOUNDED_PRODUCTION,
        human_review_recommended=True,
        plan_adjustment_candidate_allowed=mode is JudgeMode.BOUNDED_PRODUCTION,
        maximum_adjustment_chapters=(3 if mode is JudgeMode.BOUNDED_PRODUCTION else 0),
        capability_pack_ref="deployment-1",
        prompt_ref="prompt-1",
        skill_ref="skill-1",
        model_profile_ref="profile-1",
        model_version="model-v1",
    )


def _request() -> AuthorityHandlerRequest:
    asset = AuthorityInputAsset(
        asset_version_id="asset-1",
        asset_type="draft_chapter",
        content_hash="sha256:" + "b" * 64,
        content={"text": "fixture"},
    )
    payload = {
        "book_id": "book-1",
        "chapter_id": "chapter:4",
        "chapter_number": 4,
        "final_draft_asset_version": "asset-1",
        "chapter_plan_asset_version": "chapter-plan-1",
        "book_design_version": "book-design-1",
        "book_plan_version": "book-plan-1",
        "parent_plan_versions": {"volume": "volume-1"},
        "reader_segment_version": "segment-1",
        "reader_contract_version": "reader-contract-1",
        "platform_profile_version": "platform-1",
        "canon_snapshot_version": "canon-1",
        "chapter_outcome_version": "outcome-1",
        "story_state_version": "state-1",
        "quality_evidence_version": "quality-1",
        "input_manifest_ref": "manifest-1",
        "previous_reader_state_version": "reader-state-3",
        "evaluation_profile_version": "evaluation-1",
        "model_strategy_version": "model-v1",
        "context_token_budget": 8_000,
        "genre": "genre-1",
        "subgenre": "subgenre-1",
        "chapter_type": "STANDARD",
        "reader_segment": "segment-1",
        "platform": "platform-1",
    }
    return AuthorityHandlerRequest(
        operation_id="operation-1",
        project_id="project-1",
        workspace_id="workspace-1",
        actor_id="worker-1",
        trace_id="trace-1",
        correlation_id="correlation-1",
        definition_name="reader_outcome.evaluate",
        definition_version="1.0.0",
        command={"payload": payload, "input_asset_version_ids": ["asset-1"]},
        inputs=(asset,),
        attempt_id="attempt-1",
        fencing_token=1,
        worker_id="worker-1",
    )


def test_no_active_judge_resolves_to_non_blocking_uncalibrated_shadow() -> None:
    snapshot = safe_shadow_snapshot(_scope(), reason="NO_ACTIVE_QUALIFIED_JUDGE")
    assert snapshot.mode is JudgeMode.SHADOW
    assert snapshot.calibration_status is ReaderJudgeQualificationStatus.UNQUALIFIED
    assert snapshot.score_semantics == "RAW_SCORE"
    assert snapshot.publish_blocking is False
    assert snapshot.authority_commit_allowed is False
    assert snapshot.plan_adjustment_candidate_allowed is False


def test_fixture_evidence_cannot_calibrate_or_qualify_judge() -> None:
    with pytest.raises(KernelError, match="Fixture evidence"):
        validate_qualification_transition(
            ReaderJudgeQualificationStatus.CALIBRATION_PENDING,
            ReaderJudgeQualificationStatus.CALIBRATED,
            evidence_level="FIXTURE",
            sample_size=1000,
            minimum_sample_size=100,
            drift_detected=False,
        )


def test_bounded_definition_freezes_range_but_activation_requires_qualification() -> (
    None
):
    base = ReaderJudgeDefinition(
        judge_id="judge-1",
        definition_version=1,
        model_profile_ref="model-profile-1",
        model_version="model-v1",
        capability_pack_ref="deployment-1",
        prompt_ref="prompt-1",
        skill_ref="skill-1",
        reader_segment_scope="*",
        platform_scope="*",
        genre_scope="*",
        subgenre_scope="*",
        chapter_type_scope="*",
        evaluation_contract_ref="evaluation-1",
        calibration_policy_ref="calibration-1",
        decision_policy_ref="decision-1",
        mode=JudgeMode.SHADOW,
        status=ReaderJudgeQualificationStatus.UNQUALIFIED,
    )
    definition = replace(
        base,
        mode=JudgeMode.BOUNDED_PRODUCTION,
        status=ReaderJudgeQualificationStatus.CALIBRATED,
        maximum_adjustment_chapters=3,
    )
    assert definition.maximum_adjustment_chapters == 3
    with pytest.raises(KernelError, match="Bounded Production"):
        require_mode_status(definition.mode, definition.status)
    with pytest.raises(ValueError, match="positive Chapter bound"):
        replace(base, mode=JudgeMode.BOUNDED_PRODUCTION)


def test_advisory_report_recommends_human_review_but_creates_no_plan_candidate() -> (
    None
):
    output = ReaderOutcomeHandler(
        _ModelPort(), _Resolver(_qualified_snapshot(JudgeMode.ADVISORY))
    ).execute(_request())
    assert output.content["mode"] == "ADVISORY"
    assert output.content["publish_blocking"] is False
    assert all(
        item.asset_type != "reader_plan_adjustment_candidate"
        for item in output.auxiliary_outputs
    )


def test_bounded_mode_only_creates_future_limited_plan_adjustment_candidate() -> None:
    output = ReaderOutcomeHandler(
        _ModelPort(), _Resolver(_qualified_snapshot(JudgeMode.BOUNDED_PRODUCTION))
    ).execute(_request())
    candidate = next(
        item
        for item in output.auxiliary_outputs
        if item.asset_type == "reader_plan_adjustment_candidate"
    )
    assert candidate.content["affected_chapter_range"] == [5, 7]
    assert candidate.content["candidate_only"] is True
    assert candidate.content["plan_change_activation_required"] is True
    assert candidate.content["body_mutation_allowed"] is False
    assert candidate.content["ending_mutation_allowed"] is False
