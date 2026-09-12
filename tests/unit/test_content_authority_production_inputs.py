from __future__ import annotations

import pytest

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerRequest,
    AuthorityInputAsset,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority import CONTENT_CODECS
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS


def _request(name: str, content: dict) -> AuthorityHandlerRequest:
    return AuthorityHandlerRequest(
        operation_id="operation:input",
        project_id="project:input",
        workspace_id="workspace:input",
        actor_id="operator:input",
        trace_id="trace:input",
        correlation_id="correlation:input",
        definition_name=name,
        definition_version="2.1.1",
        command={
            "project_id": "project:input",
            "input_asset_version_ids": [],
            "payload": {"content": content},
        },
        inputs=(),
    )


def test_operator_future_change_is_native_content_evidence_only():
    name = "planning.change_request.author"
    content = {
        "book_id": "book:input", "target_plan_version_id": "plan:future",
        "directive": "Change the rescue route after the flood; retain the water cost.",
        "preserved_invariants": ["Chapters 1–3 remain accepted history"],
        "affected_scope": "CHAPTER_GROUP", "accepted_through_chapter": 3,
        "safe_summary": "Future route change", "structured_facts": [],
    }
    output = CONTENT_CODECS[name].execute(_request(name, content))
    assert output.asset_type == "replan_request"
    assert output.content["directive"] == content["directive"]
    assert output.content["authority_boundary"] == "FUTURE_PLAN_PROPOSAL_ONLY"
    assert output.content["evidence_level"] == "OPERATOR_AUTHORED"
    with pytest.raises(ValueError, match="boundary"):
        CONTENT_CODECS[name].execute(_request(name, {**content, "accepted_through_chapter": -1}))


@pytest.mark.parametrize(
    ("name", "asset_type", "specific"),
    (
        (
            "chapter.plan.author",
            "chapter_plan",
            {
                "chapter": 1,
                "title": "The Cost of Memory",
                "premise": "A clerk must expose a falsified public record.",
                "chapter_objective": "Make the clerk choose proof over safety.",
                "scene_sequence": [{"scene_id": "s1", "goal": "find proof"}],
                "chapter_hook": "The erased witness returns.",
            },
        ),
        (
            "chapter.style_policy.author",
            "style_policy",
            {"profile_id": "style:proof", "constraints": ["close third person"]},
        ),
        (
            "chapter.quality_rubric.author",
            "quality_rubric",
            {"profile_id": "quality:proof", "dimensions": ["continuity"]},
        ),
        (
            "chapter.platform_profile.author",
            "platform_profile",
            {"profile_id": "platform:proof", "constraints": ["strong hook"]},
        ),
        (
            "chapter.operator_checklist.author",
            "operator_checklist",
            {
                "chapter": 1,
                "completed": True,
                "contract_version": "internal-release-checklist-v1",
            },
        ),
    ),
)
def test_operator_authored_production_input_is_typed_and_source_safe(
    name: str,
    asset_type: str,
    specific: dict,
) -> None:
    output = CONTENT_CODECS[name].execute(
        _request(
            name,
            {
                **specific,
                "type": asset_type,
                "safe_summary": f"Safe {asset_type} production input.",
                "structured_facts": [{"kind": asset_type, "value": "proof"}],
            },
        )
    )

    assert output.asset_type == asset_type
    assert output.content["evidence_level"] == "OPERATOR_AUTHORED"
    assert output.content["raw_source"] is False
    assert output.content["source_expression_included"] is False
    if asset_type == "operator_checklist":
        assert output.content["allowed_use"] == "evidence_only"


def test_operator_authored_input_rejects_raw_source() -> None:
    with pytest.raises(KernelError, match="cannot contain raw source"):
        CONTENT_CODECS["chapter.style_policy.author"].execute(
            _request(
                "chapter.style_policy.author",
                {
                    "type": "style_policy",
                    "profile_id": "style:proof",
                    "constraints": ["concise"],
                    "safe_summary": "Safe policy.",
                    "structured_facts": [],
                    "raw_source": True,
                },
            )
        )


def test_fixture_waiver_approval_is_explicitly_nonproduction_and_nonhuman() -> None:
    name = "chapter.fixture_waiver_approval.author"
    output = CONTENT_CODECS[name].execute(
        _request(
            name,
            {
                "type": "operator_approval",
                "book_id": "book:input",
                "decision": "APPROVED",
                "contract_version": "fixture-waiver-approval-v1",
                "fixture_protocol_only": True,
                "production_verified": False,
                "waiver_reason": "Exercise only the bounded scripted protocol.",
                "waived_dimensions": list(QUALITY_DIMENSIONS),
                "scope": {
                    "project_id": "project:input",
                    "scope_type": "PROJECT_FIXTURE",
                    "release_readiness": "INTERNAL_REVIEW_RELEASE",
                },
                "expiry": "2099-01-01T00:00:00Z",
                "safe_summary": "Fixture-only approval evidence.",
                "structured_facts": [],
            },
        )
    )

    facts = {
        item["key"]: item["value"] for item in output.content["structured_facts"]
    }
    assert output.asset_type == "operator_approval"
    assert output.content["allowed_use"] == "evidence_only"
    assert output.content["production_verified"] is False
    assert output.content["human_preference_evidence"] is False
    assert facts["fixture_protocol_only"] is True
    assert facts["human_preference_evidence"] is False


def test_fixture_waiver_approval_rejects_production_claim() -> None:
    name = "chapter.fixture_waiver_approval.author"
    with pytest.raises(KernelError, match="fixture-only"):
        CONTENT_CODECS[name].execute(
            _request(
                name,
                {
                    "type": "operator_approval",
                    "book_id": "book:input",
                    "decision": "APPROVED",
                    "contract_version": "fixture-waiver-approval-v1",
                    "fixture_protocol_only": True,
                    "production_verified": True,
                    "waiver_reason": "Invalid production claim.",
                    "waived_dimensions": list(QUALITY_DIMENSIONS),
                    "scope": {
                        "project_id": "project:input",
                        "scope_type": "PROJECT_FIXTURE",
                        "release_readiness": "INTERNAL_REVIEW_RELEASE",
                    },
                    "expiry": "2099-01-01T00:00:00Z",
                    "safe_summary": "Invalid fixture approval.",
                    "structured_facts": [],
                },
            )
        )


def test_operator_authored_story_design_is_candidate_only_and_source_safe() -> None:
    name = "story_design.creative_foundation.author"
    content = {
        "schema_version": "story_design.authority.v1",
        "project_id": "project:input",
        "generator_operation_name": "creative.candidates.generate",
        "planning_scope": "NOT_APPLICABLE",
        "logical_key": "foundation:creative:operator-v1",
        "operator_authored": True,
        "provider_generated": False,
        "candidate_payload": {
            "objective": "Establish a costly public-truth mystery engine",
            "target_reader": "adult speculative mystery readers",
        },
    }

    output = CONTENT_CODECS[name].execute(_request(name, content))

    assert output.asset_type == "creative_foundation"
    assert output.content == content
    assert output.evidence["codec"] == name


def test_operator_story_design_review_binds_exact_candidate_and_is_not_human() -> None:
    name = "story_design.review.author"
    candidate = AuthorityInputAsset(
        asset_version_id="asset:story-design:v1",
        asset_type="creative_foundation",
        content_hash="sha256:" + "a" * 64,
        content={"schema_version": "story_design.authority.v1"},
    )
    evaluation = {"schema_version": "progressive-narrative-qualification.v1"}
    request = AuthorityHandlerRequest(
        operation_id="operation:review",
        project_id="project:input",
        workspace_id="workspace:input",
        actor_id="operator:reviewer",
        trace_id="trace:review",
        correlation_id="correlation:review",
        definition_name=name,
        definition_version="2.1.1",
        command={
            "project_id": "project:input",
            "input_asset_version_ids": [candidate.asset_version_id],
            "payload": {
                "candidate_asset_version_id": candidate.asset_version_id,
                "candidate_content_hash": candidate.content_hash,
                "evaluation": evaluation,
                "review_rationale": "Each criterion is bound to the curated design.",
            },
        },
        inputs=(candidate,),
    )

    output = CONTENT_CODECS[name].execute(request)

    assert output.asset_type == "narrative_design_operator_review"
    assert output.content["evaluation"] == evaluation
    assert output.content["human_preference_evidence"] is False
    assert output.content["provider_evidence_claimed"] is False


@pytest.mark.parametrize(
    ("name", "asset_type", "boundary", "specific"),
    (
        (
            "book.production_profile.author",
            "production_profile",
            "FUTURE_INTENT",
            {
                "profile_id": "bounded-quality-v1",
                "target_chapter_count": 8,
                "language_contract": {"language": "zh-CN"},
            },
        ),
        (
            "book.previous_volume_outcome.author",
            "previous_volume_outcome",
            "PRE_CHAPTER_0",
            {"contract_version": "previous-volume-outcome-v1", "status": "NONE"},
        ),
        (
            "book.previous_chapter_group_outcome.author",
            "previous_chapter_group_outcome",
            "PRE_CHAPTER_0",
            {
                "contract_version": "previous-chapter-group-outcome-v1",
                "status": "NO_PREVIOUS_CHAPTER_GROUP",
                "actual_outcomes": [],
            },
        ),
        (
            "book.previous_chapter_outcome.author",
            "previous_chapter_outcome",
            "PRE_CHAPTER_0",
            {
                "contract_version": "previous-chapter-outcome-v1",
                "status": "NO_PREVIOUS_CHAPTER",
                "actual_outcomes": [],
            },
        ),
        (
            "book.arc_portfolio.author",
            "arc_portfolio",
            "FUTURE_INTENT",
            {"portfolio_id": "arc-portfolio:initial", "contract_version": "v1"},
        ),
        (
            "book.ending_reachability.author",
            "ending_reachability",
            "ADVISORY",
            {"contract_version": "v1", "status": "PLANNED"},
        ),
        (
            "book.character_arc_portfolio.author",
            "character_arc_portfolio",
            "FUTURE_INTENT",
            {"portfolio_id": "character-arcs:initial", "contract_version": "v1"},
        ),
        (
            "book.conflict_state.author",
            "conflict_state",
            "PRE_CHAPTER_0",
            {"contract_version": "v1", "active_conflicts": []},
        ),
        (
            "book.foreshadowing_ledger.author",
            "foreshadowing_ledger",
            "PRE_CHAPTER_0",
            {"contract_version": "v1", "entries": []},
        ),
        (
            "book.reader_segment.author",
            "reader_segment_profile",
            "ADVISORY",
            {"profile_id": "reader:bounded", "profile_version": "reader-outcome-v3"},
        ),
        (
            "book.reader_contract.author",
            "reader_contract",
            "ADVISORY",
            {"profile_id": "reader:bounded", "profile_version": "reader-outcome-v3"},
        ),
        (
            "book.reader_state.author",
            "reader_state",
            "ADVISORY",
            {
                "contract_version": "reader-state-genesis-v1",
                "profile_version": "reader-outcome-v3",
                "status": "NOT_OBSERVED",
                "accepted_through_chapter": 0,
                "observations": [],
                "evidence_class": "READER_PROXY_ADVISORY",
            },
        ),
        (
            "book.character_state.author",
            "character_state_snapshot",
            "PRE_CHAPTER_0",
            {"contract_version": "v1", "entries": []},
        ),
        (
            "book.foreshadowing_state.author",
            "foreshadow_snapshot",
            "PRE_CHAPTER_0",
            {"contract_version": "v1", "entries": []},
        ),
        (
            "book.quality_trend.author",
            "quality_trend",
            "ADVISORY",
            {"contract_version": "v1", "status": "NO_ACCEPTED_CHAPTERS"},
        ),
        (
            "book.reward_ledger.author",
            "reward_ledger_snapshot",
            "PRE_CHAPTER_0",
            {"contract_version": "v1", "entries": []},
        ),
        (
            "book.promise_ledger.author",
            "promise_ledger_snapshot",
            "PRE_CHAPTER_0",
            {"contract_version": "v1", "entries": []},
        ),
    ),
)
def test_operator_book_bootstrap_inputs_preserve_authority_boundary(
    name: str,
    asset_type: str,
    boundary: str,
    specific: dict,
) -> None:
    output = CONTENT_CODECS[name].execute(
        _request(
            name,
            {
                "type": asset_type,
                "book_id": "book:bounded",
                "authority_boundary": boundary,
                "safe_summary": f"Bounded {asset_type} input.",
                "structured_facts": [{"key": "boundary", "value": boundary}],
                **specific,
            },
        )
    )

    assert output.asset_type == asset_type
    assert output.content["operator_authored"] is True
    assert output.content["provider_generated"] is False
    assert output.content["human_preference_evidence"] is False
    assert output.content["ground_truth_claimed"] is False
    assert output.content["narrative_truth_mutation_allowed"] is False


def test_operator_book_bootstrap_rejects_accepted_or_human_claims() -> None:
    with pytest.raises(KernelError, match="pre-Chapter-1 boundary"):
        CONTENT_CODECS["book.promise_ledger.author"].execute(
            _request(
                "book.promise_ledger.author",
                {
                    "type": "promise_ledger_snapshot",
                    "book_id": "book:bounded",
                    "contract_version": "v1",
                    "authority_boundary": "PRE_CHAPTER_0",
                    "accepted_through_chapter": 1,
                    "entries": [],
                    "safe_summary": "Invalid accepted promise ledger.",
                    "structured_facts": [],
                },
            )
        )
    with pytest.raises(KernelError, match="cannot claim human"):
        CONTENT_CODECS["book.reader_contract.author"].execute(
            _request(
                "book.reader_contract.author",
                {
                    "type": "reader_contract",
                    "book_id": "book:bounded",
                    "profile_id": "reader:bounded",
                    "profile_version": "reader-outcome-v3",
                    "authority_boundary": "ADVISORY",
                    "safe_summary": "Invalid human claim.",
                    "structured_facts": [],
                    "human_verified": True,
                },
            )
        )


def test_operator_genesis_binds_empty_story_state_and_canon() -> None:
    identity = "sha256:" + "b" * 64
    story_name = "book.initial_story_state.author"
    story_request = AuthorityHandlerRequest(
        operation_id="operation:story-genesis",
        project_id="project:input",
        workspace_id="workspace:input",
        actor_id="operator:input",
        trace_id="trace:input",
        correlation_id="correlation:input",
        definition_name=story_name,
        definition_version="2.1.1",
        command={
            "project_id": "project:input",
            "input_asset_version_ids": [],
            "payload": {
                "book_id": "book:bounded",
                "campaign_contract_identity": identity,
            },
        },
        inputs=(),
    )
    story = CONTENT_CODECS[story_name].execute(story_request)
    story_input = AuthorityInputAsset(
        asset_version_id="asset:story-genesis:v1",
        asset_type="story_state_snapshot",
        content_hash="sha256:" + "c" * 64,
        content=story.content,
    )
    canon_name = "book.initial_canon.author"
    canon = CONTENT_CODECS[canon_name].execute(
        AuthorityHandlerRequest(
            operation_id="operation:canon-genesis",
            project_id="project:input",
            workspace_id="workspace:input",
            actor_id="operator:input",
            trace_id="trace:input",
            correlation_id="correlation:input",
            definition_name=canon_name,
            definition_version="2.1.1",
            command={
                "project_id": "project:input",
                "input_asset_version_ids": [story_input.asset_version_id],
                "payload": {
                    "book_id": "book:bounded",
                    "campaign_contract_identity": identity,
                },
            },
            inputs=(story_input,),
        )
    )

    assert story.content["current_state"] == {}
    assert story.content["actual_narrative_events"] == []
    assert story.content["accepted_through_chapter"] == 0
    assert canon.content["current_facts"] == []
    assert canon.content["story_state_hash"] == story.content["state_hash"]
    assert canon.reference_asset_version_ids == (story_input.asset_version_id,)
