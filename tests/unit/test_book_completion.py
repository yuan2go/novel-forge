from __future__ import annotations

from copy import deepcopy

import pytest

from novel_forge.modules.book_authority.completion import book_completion_definitions
from novel_forge.modules.book_authority.completion_domain import (
    CLOSURE_DIMENSIONS,
    EVIDENCE_DIMENSIONS,
    assess_completion,
    completion_result_schema,
    require_completion_review,
    validate_completion_contract,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _source() -> tuple[dict, list[dict]]:
    book = {
        "state": "COMPLETED",
        "target_chapter_count": 1,
        "accepted_through_chapter": 1,
        "required_arc_plan_version_ids": ["arc:v1"],
    }
    row = {
        "source_eligible": True,
        "chapter_number": 1,
        "acceptance_id": "accepted:1",
        "acceptance_status": "COMMITTED",
        "projection_status": "COMPLETE",
        "projection_set_id": "projection:1",
        "acceptance_projection_set_id": "projection:1",
        "projection_hash": "sha256:" + "1" * 64,
        "arc_state": [
            {
                "arc_plan_version_id": "arc:v1",
                "observation_status": "OBSERVED",
                "lifecycle_status": "COMPLETED",
            }
        ],
        "obligation_state": [
            {
                "entity_key": "promise:1",
                "state": {
                    "status": "FULFILLED",
                    "payoff_evidence": {"acceptance_id": "accepted:1"},
                },
            }
        ],
    }
    for kind in ("outcome", "story_state", "canon"):
        row[kind + "_version_id"] = kind + ":1"
        row["projection_" + kind + "_version_id"] = kind + ":1"
        row[kind + "_hash"] = "sha256:" + "2" * 64
    return book, [row]


def test_terminal_cursor_and_observed_closure_only_prepare_editorial_case() -> None:
    book, accepted = _source()
    result = assess_completion(book, accepted).to_dict()
    assert result["status"] == "READY_FOR_EDITORIAL"
    assert result["acceptance_policy_status"] == "DESIGN_REVIEW_REQUIRED"
    assert result["evidence_dimensions"]["HUMAN_EDITORIAL"] == "WAITING_EVIDENCE"
    assert result["evidence_dimensions"]["NARRATIVE_CORRECTNESS"] == "SUPPORTING_ONLY"
    assert set(result["evidence_dimensions"]) == set(EVIDENCE_DIMENSIONS)
    assert result["accepted_history_mutation_allowed"] is False
    assert assess_completion(book, accepted).to_dict() == result


@pytest.mark.parametrize(
    "change,blocker",
    [
        (lambda b, a: b.update(state="READY"), "PRODUCTION_CURSOR_NOT_TERMINAL"),
        (lambda b, a: a.clear(), "ACCEPTED_HISTORY_INCOMPLETE"),
        (
            lambda b, a: a[0].update(source_eligible=False),
            "ACCEPTED_SOURCE_NOT_ELIGIBLE",
        ),
        (
            lambda b, a: a[0].update(projection_status=None),
            "ACCEPTED_PROJECTION_INCOMPLETE",
        ),
        (
            lambda b, a: a[0].update(projection_outcome_version_id="other"),
            "ACCEPTED_SOURCE_IDENTITY_DRIFT",
        ),
        (lambda b, a: a[0].update(arc_state=[]), "TRAJECTORY_CLOSURE_NOT_OBSERVED"),
        (
            lambda b, a: b.update(required_arc_plan_version_ids=["unseen:arc"]),
            "REQUIRED_TRAJECTORY_NOT_OBSERVED:unseen:arc",
        ),
        (
            lambda b, a: a[0]["arc_state"][0].update(observation_status="UNKNOWN"),
            "TRAJECTORY_NOT_CLOSED:arc:v1",
        ),
        (
            lambda b, a: a[0]["obligation_state"][0]["state"].update(
                payoff_evidence={}
            ),
            "OBLIGATION_NOT_RESOLVED:promise:1",
        ),
    ],
)
def test_accepted_boundary_defects_cannot_become_completion(
    change, blocker: str
) -> None:
    book, accepted = _source()
    change(book, accepted)
    result = assess_completion(book, accepted).to_dict()
    assert result["status"] == "NEEDS_REMEDIATION"
    assert blocker in result["blockers"]


def test_typed_review_binds_complete_exact_accepted_history_and_each_dimension() -> (
    None
):
    book, accepted = _source()
    assessment = assess_completion(book, accepted).to_dict()
    review = {
        "schema_version": "whole-book-closure-review.v1",
        "source_digest": assessment["source_digest"],
        "source_acceptance_ids": assessment["acceptance_ids"],
        "blocking_issues": [],
        "findings": {
            dimension: {
                "status": "SATISFIED",
                "rationale": "Accepted consequence closes this obligation.",
                "acceptance_refs": ["accepted:1"],
            }
            for dimension in CLOSURE_DIMENSIONS
        },
    }
    require_completion_review(assessment, review)
    wrong = deepcopy(review)
    wrong["source_acceptance_ids"].append("accepted:1")
    with pytest.raises(KernelError, match="complete frozen accepted history"):
        require_completion_review(assessment, wrong)
    wrong = deepcopy(review)
    wrong["findings"]["theme"]["acceptance_refs"] = ["future:1"]
    with pytest.raises(KernelError, match="accepted closure evidence"):
        require_completion_review(assessment, wrong)
    wrong = deepcopy(review)
    del wrong["findings"]["relationship"]
    with pytest.raises(KernelError, match="every whole-book closure dimension"):
        require_completion_review(assessment, wrong)


def test_completion_commands_use_atomic_kernel_and_have_typed_mutation_inputs() -> None:
    definitions = book_completion_definitions(
        application_build_id="test", commit_sha="a" * 40
    )
    assert {item["name"] for item in definitions} == {
        "book.completion.assess",
        "book.completion.decide",
    }
    for definition in definitions:
        assert definition["execution_mode"] == "transactional"
        assert definition["policy"]["execution_classification"] == "transaction_command"
        assert definition["external_capabilities"] == []
        assert definition["command_schema"]["additionalProperties"] is False
    decision = definitions[1]["command_schema"]["required"]
    assert {
        "source_digest",
        "expected_case_version",
        "expected_decision_version",
    } <= set(decision)


def test_completion_kernel_result_schema_rejects_false_qualification_and_total_score() -> (
    None
):
    book, accepted = _source()
    result = {
        **assess_completion(book, accepted).to_dict(),
        "case_id": "case:1",
        "book_run_id": "book-run:1",
        "case_version": 1,
    }
    schema = completion_result_schema("assess")
    validate_completion_contract(schema, result, "result")
    for dimension in EVIDENCE_DIMENSIONS:
        invalid = deepcopy(result)
        invalid["evidence_dimensions"][dimension] = "QUALIFIED"
        with pytest.raises(KernelError):
            validate_completion_contract(schema, invalid, "result")
    invalid = deepcopy(result)
    invalid["evidence_dimensions"]["NARRATIVE_CORRECTNESS"] = "PASS"
    with pytest.raises(KernelError):
        validate_completion_contract(schema, invalid, "result")
    with pytest.raises(KernelError):
        validate_completion_contract(schema, {**result, "total_score": 100}, "result")
    with pytest.raises(KernelError):
        validate_completion_contract(
            schema, {**result, "accepted_history_mutation_allowed": True}, "result"
        )
