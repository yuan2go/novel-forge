from unittest.mock import Mock

import pytest

from novel_forge.modules.chapter_authority.canon_output_recovery import retained_canon_output
from novel_forge.modules.chapter_authority.canon_support_coverage import retained_support_output
from novel_forge.modules.chapter_authority.quality_review_recovery import retained_quality_review
from novel_forge.modules.chapter_authority.quality_revision_recovery import retained_quality_revision
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.retained_graph import acknowledge_retained_result
from novel_forge.modules.review.cross_chapter import apply_targeted_edits
from novel_forge.modules.review.diagnostics import prose_hash


@pytest.mark.parametrize("reader,name,version", [
    (retained_quality_revision, "chapter.revision.apply", "3.9.4"),
    (retained_quality_review, "chapter.revision.review", "3.9.3"),
    (retained_canon_output, "chapter.canon.extract", "3.9.7"),
    (retained_support_output, "chapter.canon.propose_changes", "3.9.8"),
])
@pytest.mark.parametrize("mutation", ["future_version", "cancelled", "accepted_output"])
def test_historical_result_readers_do_not_gain_current_or_cancelled_permissions(reader, name, version, mutation):
    cursor = Mock()
    cursor.fetchall.return_value = [("draft_version", "primary")] if mutation == "accepted_output" else []
    source = {"operation_id": "original", "project_id": "project", "definition_name": name,
              "definition_version": "3.10.1" if mutation == "future_version" else version,
              "status": "CANCELLED" if mutation == "cancelled" else "FAILED_FINAL"}
    with pytest.raises(KernelError):
        reader(cursor, source)
    assert cursor.fetchall.call_count == (1 if mutation == "accepted_output" else 0)


@pytest.mark.parametrize("version,actor", [("3.9.0", "original"), ("3.10.1", "original"), ("3.10.0", "foreign")])
def test_current_graph_journal_rejects_reused_or_unknown_identity_before_acknowledgement(version, actor):
    cursor = Mock()
    proof = {"contract_version": "chapter-current-semantic-repair.v2"}
    frozen = {"root": {"actor_id": "original", "project_id": "project"}, "retained_result": proof}
    cursor.fetchone.return_value = ("kernel-retained-graph-continuation.v2", {"retained_result": proof}, "source", frozen,
                                    {"definition_version": version, "actor_id": actor, "project_id": "project"})
    effects = [{"status": "UNKNOWN"}]
    with pytest.raises(KernelError, match="RETAINED_GRAPH_CONTRACT_INVALID"):
        acknowledge_retained_result(cursor, effects, "current")
    assert effects == [{"status": "UNKNOWN"}]
    assert not cursor.fetchall.called


@pytest.mark.parametrize("status,expected", [("FAILED_RETRYABLE", True), ("FAILED_FINAL", False), ("UNKNOWN", False)])
def test_current_semantic_acknowledgement_preserves_exact_failed_attempt_status(status, expected):
    proof = {"contract_version": "chapter-current-semantic-repair.v2", "source_operation_id": "review",
             "source_effect_id": "effect", "source_dispatch_id": "dispatch", "source_output_hash": "hash",
             "source_request_hash": "request", "provider_invoked": True, "strict_certification_eligible": False,
             "source_attempt": {"attempt_id": "attempt", "status": "FAILED_RETRYABLE"}}
    marker = {key: value for key, value in proof.items() if key != "source_attempt"}
    root = {"definition_version": "3.10.0", "actor_id": "original", "project_id": "project"}
    frozen = {"root": root, "retained_result": proof}
    cursor = Mock()
    cursor.fetchone.return_value = ("kernel-retained-graph-continuation.v2", {"retained_result": proof}, "source", frozen, root)
    cursor.fetchall.return_value = [("successor", {"retained_result_repair": marker})]
    effect = {"external_effect_id": "effect", "operation_id": "review", "status": "SUCCEEDED",
              "attempt_id": "attempt", "attempt_status": status}
    acknowledge_retained_result(cursor, [effect], "current")
    assert bool(effect.get("settled_candidate_superseded")) == expected
    assert effect["attempt_status"] == status


@pytest.mark.parametrize("second,edit_end,accepted", [(4, 8, True), (6, 10, False)])
def test_named_diagnosis_union_covers_every_changed_codepoint_without_bridging_gaps(second, edit_end, accepted):
    text = "0123456789AB"
    review = {"target_text_hash": prose_hash(text), "issues": [
        {"code": "a", "severity": "blocking", "evidence_locator": {"start": 0, "end": 4, "quote": text[:4], "text_hash": prose_hash(text)}},
        {"code": "b", "severity": "blocking", "evidence_locator": {"start": second, "end": edit_end, "quote": text[second:edit_end], "text_hash": prose_hash(text)}},
    ]}
    result = {"edits": [{"start": 0, "end": edit_end, "quote": text[:edit_end], "replacement": "X", "issue_codes": ["a", "b"]}],
              "text": "X" + text[edit_end:]}
    if accepted:
        actual = apply_targeted_edits(draft={"text": text}, review=review, result=result, range_policy="NAMED_DIAGNOSIS_UNION_V1")
        assert actual["repaired_text"] == result["text"]
        with pytest.raises(KernelError, match="outside diagnosed"):
            apply_targeted_edits(draft={"text": text}, review=review, result=result)
    else:
        with pytest.raises(KernelError, match="connected named frozen scope"):
            apply_targeted_edits(draft={"text": text}, review=review, result=result, range_policy="NAMED_DIAGNOSIS_UNION_V1")
