from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from novel_forge.modules.chapter_quality_authority.qualification import (
    CampaignLifecycle,
    EvidenceLayer,
    EvidenceSeverity,
    EvidenceStatus,
    HumanEvidenceStatus,
    QualityCampaignManifest,
    QualityEvidence,
    QualificationStatus,
    decide_quality_qualification,
    transition_campaign,
)


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "novel-forge.quality-qualification.v1",
        "campaign_id": "quality-proof-01-v1",
        "campaign_version": 1,
        "exact_release_sha": "a" * 40,
        "migration_head": "20260826_0101_quality_qualification",
        "protocol_version": "human-blind-comparison-v1",
        "evaluation_profile_version": "editorial-pairwise-v1",
        "quality_profile_version": "canonical-quality-v3",
        "reader_outcome_profile_version": "reader-outcome-v3",
        "project_id": "project:quality-proof",
        "workspace_id": "workspace:quality-proof",
        "book_id": "book:quality-proof",
        "chapter_group_ranges": [[1, 4], [5, 8]],
        "provider_route_manifest": {
            "generator": {"provider": "codex", "model": "frozen-generator"},
            "reviewer": {"provider": "codex", "model": "frozen-reviewer"},
            "judge": {"provider": "openai", "model": "frozen-judge"},
        },
        "capability_pack_manifest": {"draft": "sha256:" + "1" * 64},
        "prompt_skill_lineage": {"draft_prompt": "sha256:" + "2" * 64},
        "foundation_lineage": {"qualified_foundation_set": "foundation:v1"},
        "planning_lineage": {"book_plan": "book-plan:v1", "arcs": ["arc:v1"]},
        "realization_lineage": {"contract": "realization:v1"},
        "context_policy": {"contract": "context-manifest-v3"},
        "baseline_protocol": {"kind": "FIRST_DRAFT_VS_ACCEPTED_REVISION"},
        "budget_policy": {
            "chapter_limit": 8,
            "token_limit": 200_000,
            "cost_limit_usd": "100.00",
        },
        "required_evaluator_count": 2,
    }


def _evidence(
    layer: EvidenceLayer,
    *,
    status: EvidenceStatus = EvidenceStatus.PASS,
    severity: EvidenceSeverity = EvidenceSeverity.INFO,
) -> QualityEvidence:
    return QualityEvidence(
        evidence_id=f"evidence:{layer.value}",
        subject_id="subject:campaign",
        layer=layer,
        evidence_type=f"{layer.value}.SUMMARY",
        status=status,
        severity=severity,
        source_evidence_ids=(f"asset:{layer.value}:v1",),
    )


def _passing_evidence() -> tuple[QualityEvidence, ...]:
    return tuple(_evidence(layer) for layer in EvidenceLayer)


def test_manifest_freezes_exact_lineage_and_has_canonical_digest() -> None:
    raw = _manifest()
    manifest = QualityCampaignManifest.from_mapping(raw)
    reordered = QualityCampaignManifest.from_mapping(dict(reversed(list(raw.items()))))

    assert manifest.digest == reordered.digest
    assert manifest.digest.startswith("sha256:")
    assert manifest.chapter_group_ranges == ((1, 4), (5, 8))
    assert manifest.allows_chapter(8) is True
    assert manifest.allows_chapter(9) is False
    assert (
        manifest.to_dict()["provider_route_manifest"] == raw["provider_route_manifest"]
    )

    raw["provider_route_manifest"]["generator"]["model"] = "mutated"  # type: ignore[index]
    assert (
        manifest.to_dict()["provider_route_manifest"]["generator"]["model"]
        == "frozen-generator"
    )
    with pytest.raises(FrozenInstanceError):
        manifest.campaign_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            {"chapter_group_ranges": [[1, 4], [5, 9]]},
            r"exactly \[1,4\] and \[5,8\]",
        ),
        ({"required_evaluator_count": 1}, "at least two"),
        ({"foundation_lineage": {}}, "foundation_lineage"),
        ({"exact_release_sha": "main"}, "full Git SHA"),
    ],
)
def test_manifest_rejects_scope_or_lineage_drift(
    mutation: dict[str, object], message: str
) -> None:
    raw = _manifest()
    raw.update(mutation)

    with pytest.raises(ValueError, match=message):
        QualityCampaignManifest.from_mapping(raw)


def test_campaign_lifecycle_is_explicit_and_fail_closed() -> None:
    assert (
        transition_campaign(CampaignLifecycle.DRAFT, CampaignLifecycle.FROZEN)
        is CampaignLifecycle.FROZEN
    )
    assert (
        transition_campaign(CampaignLifecycle.FROZEN, CampaignLifecycle.RUNNING)
        is CampaignLifecycle.RUNNING
    )
    assert (
        transition_campaign(
            CampaignLifecycle.RUNNING,
            CampaignLifecycle.WAITING_HUMAN_EVIDENCE,
        )
        is CampaignLifecycle.WAITING_HUMAN_EVIDENCE
    )
    assert (
        transition_campaign(
            CampaignLifecycle.WAITING_HUMAN_EVIDENCE,
            CampaignLifecycle.EVALUATING,
        )
        is CampaignLifecycle.EVALUATING
    )
    assert (
        transition_campaign(CampaignLifecycle.EVALUATING, CampaignLifecycle.COMPLETE)
        is CampaignLifecycle.COMPLETE
    )

    with pytest.raises(ValueError, match="cannot transition"):
        transition_campaign(CampaignLifecycle.DRAFT, CampaignLifecycle.RUNNING)
    with pytest.raises(ValueError, match="terminal"):
        transition_campaign(CampaignLifecycle.COMPLETE, CampaignLifecycle.RUNNING)


def test_evidence_layers_are_not_interchangeable() -> None:
    items = _passing_evidence()

    assert {item.layer for item in items} == set(EvidenceLayer)
    with pytest.raises(ValueError, match="source evidence"):
        QualityEvidence(
            evidence_id="evidence:empty",
            subject_id="subject:campaign",
            layer=EvidenceLayer.L2_EDITORIAL_QUALITY,
            evidence_type="EDITORIAL",
            status=EvidenceStatus.PASS,
            severity=EvidenceSeverity.INFO,
            source_evidence_ids=(),
        )


def test_severe_l1_failure_forces_fail_without_score_compensation() -> None:
    evidence = (
        _evidence(
            EvidenceLayer.L1_HARD_CORRECTNESS,
            status=EvidenceStatus.FAIL,
            severity=EvidenceSeverity.SEVERE,
        ),
        _evidence(EvidenceLayer.L2_EDITORIAL_QUALITY),
        _evidence(EvidenceLayer.L3_READER_LONGITUDINAL),
    )

    decision = decide_quality_qualification(
        evidence,
        valid_human_evaluator_ids=("reviewer-1", "reviewer-2"),
        human_collection_closed=True,
    )

    assert decision.status is QualificationStatus.FAIL
    assert (
        decision.layer_statuses[EvidenceLayer.L1_HARD_CORRECTNESS]
        is QualificationStatus.FAIL
    )
    assert "SEVERE_L1_FAILURE" in decision.diagnostics


def test_missing_required_layer_is_not_proven() -> None:
    decision = decide_quality_qualification(
        _passing_evidence()[:2],
        valid_human_evaluator_ids=("reviewer-1", "reviewer-2"),
        human_collection_closed=True,
    )

    assert decision.status is QualificationStatus.NOT_PROVEN
    assert decision.lifecycle is CampaignLifecycle.COMPLETE
    assert "MISSING_L3_READER_LONGITUDINAL" in decision.diagnostics


@pytest.mark.parametrize("human_collection_closed", [False, True])
def test_no_human_evidence_waits_and_cannot_pass(
    human_collection_closed: bool,
) -> None:
    decision = decide_quality_qualification(
        _passing_evidence(),
        valid_human_evaluator_ids=(),
        human_collection_closed=human_collection_closed,
    )

    assert decision.status is QualificationStatus.NOT_PROVEN
    assert decision.lifecycle is CampaignLifecycle.WAITING_HUMAN_EVIDENCE
    assert decision.human_evidence_status is HumanEvidenceStatus.WAITING_HUMAN_EVIDENCE
    assert "HUMAN_BLIND_EVIDENCE_MISSING" in decision.diagnostics


def test_one_human_is_limited_and_never_silent_full_pass() -> None:
    waiting = decide_quality_qualification(
        _passing_evidence(),
        valid_human_evaluator_ids=("reviewer-1",),
        human_collection_closed=False,
    )
    closed = decide_quality_qualification(
        _passing_evidence(),
        valid_human_evaluator_ids=("reviewer-1",),
        human_collection_closed=True,
    )

    assert waiting.status is QualificationStatus.NOT_PROVEN
    assert waiting.lifecycle is CampaignLifecycle.WAITING_HUMAN_EVIDENCE
    assert waiting.human_evidence_status is HumanEvidenceStatus.HUMAN_EVIDENCE_LIMITED
    assert closed.status is QualificationStatus.PASS_WITH_LIMITATIONS
    assert closed.lifecycle is CampaignLifecycle.COMPLETE
    assert closed.human_evidence_status is HumanEvidenceStatus.HUMAN_EVIDENCE_LIMITED
    assert "ONLY_ONE_VALID_HUMAN_EVALUATOR" in closed.limitations


def test_two_humans_are_bounded_evidence_not_statistical_calibration() -> None:
    decision = decide_quality_qualification(
        _passing_evidence(),
        valid_human_evaluator_ids=("reviewer-1", "reviewer-2"),
        human_collection_closed=True,
    )

    assert decision.status is QualificationStatus.PASS
    assert decision.lifecycle is CampaignLifecycle.COMPLETE
    assert decision.human_evidence_status is HumanEvidenceStatus.BOUNDED_HUMAN_EVIDENCE
    assert "STATISTICAL_JUDGE_CALIBRATION" in decision.unproven_claims
    assert "COMMERCIAL_SUCCESS" in decision.unproven_claims
