from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.completion import assess_whole_book_completion
from novel_forge.modules.book_followup_authority.domain import evaluate_reader_outcome
from novel_forge.modules.reader_calibration.proxy_policy import (
    READER_PROXY_POLICY_V1,
    resolve_reader_proxy_policy,
)


def _terminal_snapshot() -> dict:
    return {
        "target_chapter_count": 12,
        "accepted_boundary": {
            "chapter_number": 12,
            "acceptance_id": "acceptance:12",
            "projection_set_id": "projection:12",
            "chapter_outcome_asset_version_id": "outcome:12",
            "story_state_asset_version_id": "state:12",
            "canon_snapshot_asset_version_id": "canon:12",
            "projection_hash": "sha256:" + "a" * 64,
        },
        "arc_state": [
            {
                "arc_plan_version_id": "arc:1",
                "lifecycle_status": "COMPLETED",
                "observation_status": "OBSERVED",
            }
        ],
        "obligation_state": [
            {
                "state": {
                    "obligation_id": "obligation:1",
                    "status": "FULFILLED",
                    "payoff_evidence": {"source_chapter": 12},
                    "accepted_evaluation": {"dependency_state": "SATISFIED"},
                }
            }
        ],
        "chapter_gate_evidence": {"quality": "PASSED"},
    }


def test_cursor_exhaustion_and_closed_arcs_do_not_claim_whole_book_acceptance() -> None:
    report = assess_whole_book_completion(_terminal_snapshot())
    assert report["cursor_exhausted"] is True
    assert report["decision"] == "BLOCKED"
    assert report["whole_book_accepted"] is False
    assert report["accepted_actual_mutation_allowed"] is False
    assert report["evidence_dimensions"]["human_editorial"] == "WAITING_EVIDENCE"
    assert {item["status"] for item in report["blockers"]} == {
        "WAITING_EVIDENCE",
        "DESIGN_REVIEW_REQUIRED",
    }


def test_completion_rejects_nonterminal_boundary_and_records_unsettled_debt() -> None:
    snapshot = _terminal_snapshot()
    snapshot["accepted_boundary"]["chapter_number"] = 11
    with pytest.raises(ValueError, match="terminal accepted boundary"):
        assess_whole_book_completion(snapshot)
    snapshot["accepted_boundary"]["chapter_number"] = 12
    snapshot["obligation_state"][0]["state"]["payoff_evidence"] = {}
    snapshot["arc_state"][0]["lifecycle_status"] = "ABANDONED"
    report = assess_whole_book_completion(snapshot)
    assert {item["code"] for item in report["blockers"]} >= {
        "TRAJECTORY_CLOSURE_NOT_PROVEN",
        "OBLIGATION_SETTLEMENT_NOT_PROVEN",
    }


def test_reader_proxy_policy_rejects_tampered_thresholds_or_calibration_claims() -> (
    None
):
    snapshot = READER_PROXY_POLICY_V1.snapshot()
    assert resolve_reader_proxy_policy(snapshot) is READER_PROXY_POLICY_V1
    for key, value in (
        ("trend_delta_threshold", 0.99),
        ("calibration_status", "HUMAN_CALIBRATED"),
        ("content_hash", "sha256:" + "0" * 64),
        ("version", "reader-proxy-policy-v999"),
    ):
        changed = deepcopy(snapshot)
        changed[key] = value
        with pytest.raises(ValueError, match="not registered"):
            resolve_reader_proxy_policy(changed)


def test_frozen_reader_proxy_policy_replays_identical_decision_with_proof_ceiling() -> (
    None
):
    state = {
        "continue_intent": 0.8,
        "curiosity": 0.8,
        "satisfaction": 0.8,
        "confusion": 0.76,
        "trust": 0.8,
        "character_attachment": 0.8,
        "antagonist_pressure": 0.8,
        "promise_expectation": 0.8,
        "payoff_satisfaction": 0.8,
        "drop_risk": 0.1,
        "repetition_fatigue": 0.1,
    }
    evidence = [{"source": "fixture", "position": "paragraph:1"}]
    first = evaluate_reader_outcome(state, evidence=evidence)
    policy = resolve_reader_proxy_policy(first["reader_proxy_policy"])
    replay = evaluate_reader_outcome(state, evidence=evidence, policy=policy)
    assert first == replay
    assert first["gate"] == "REVISION_RECOMMENDED"
    assert first["reader_proxy_policy"]["human_editorial_proof"] is False
    assert first["reader_proxy_policy"]["calibration_status"] == "UNCALIBRATED_POLICY"
