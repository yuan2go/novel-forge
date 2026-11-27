from __future__ import annotations

from unittest.mock import Mock
import pytest

from novel_forge.api import authority_dependencies  # noqa: F401
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.retained_graph import source_graph


@pytest.mark.parametrize(
    "actor,status,version,saga",
    [
        ("another-actor", "FAILED_FINAL", "3.9.0", "MANUAL_INTERVENTION"),
        ("original", "SUCCEEDED", "3.9.0", "MANUAL_INTERVENTION"),
        ("original", "CANCELLED", "3.9.0", "MANUAL_INTERVENTION"),
        ("original", "FAILED_FINAL", "3.8.0", "MANUAL_INTERVENTION"),
        ("original", "FAILED_FINAL", "3.9.0", "SUCCEEDED"),
    ],
)
def test_terminal_graph_recovery_cannot_reopen_or_borrow_other_authorities(
    actor, status, version, saga
):
    cursor = Mock()
    cursor.fetchone.side_effect = [
        (
            {
                "definition_name": "chapter.slice.run",
                "root_operation_id": "source",
                "actor_id": actor,
                "status": status,
                "definition_version": version,
            },
        ),
        ({"status": saga, "project_id": "project"},),
    ]
    with pytest.raises(KernelError, match="RETAINED_GRAPH_SOURCE_INVALID"):
        source_graph(
            cursor, root_id="source", project_id="project", actor_id="original"
        )
    assert not cursor.fetchall.called


def test_missing_project_root_fails_before_reading_foreign_execution_evidence():
    cursor = Mock()
    cursor.fetchone.return_value = None
    with pytest.raises(KernelError, match="RETAINED_GRAPH_SOURCE_INVALID"):
        source_graph(
            cursor, root_id="foreign", project_id="project", actor_id="original"
        )
    assert cursor.execute.call_count == 1


def test_retained_correction_references_cannot_replace_missing_initial_completion_steps():
    from novel_forge.modules.command_kernel.operation_graph import initial_graph_complete

    base = [{"step_key": str(i), "status": "SUCCEEDED"} for i in range(19)]
    corrections = [
        {
            "step_key": "correction:" + str(i),
            "status": "SUCCEEDED",
            "initial_completion_member": False,
        }
        for i in range(3)
    ]
    assert not initial_graph_complete(base + corrections, 22)
    assert not initial_graph_complete(base + base[:3] + corrections, 22)
    complete = base + [{"step_key": str(i), "status": "SUCCEEDED"} for i in range(19, 22)]
    assert initial_graph_complete(complete + corrections, 22)
    corrections[0]["status"] = "UNKNOWN"
    assert not initial_graph_complete(complete + corrections, 22)


@pytest.mark.parametrize('attempt_status,expected', [('FAILED_RETRYABLE', True), ('UNKNOWN', False), ('FAILED_FINAL', False)])
def test_semantic_successor_acknowledges_only_the_preserved_known_failed_attempt(attempt_status, expected):
    from novel_forge.modules.command_kernel.retained_graph import _acknowledge_legacy_result as acknowledge_retained_result

    proof = {'contract_version': 'chapter-current-semantic-repair.v1', 'source_operation_id': 'review',
             'source_effect_id': 'effect', 'source_dispatch_id': 'dispatch', 'source_request_hash': 'request-hash',
             'source_output_hash': 'output-hash', 'source_attempt': {'attempt_id': 'attempt'},
             'quality_generation': 2, 'provider_invoked': True}
    cursor = Mock()
    cursor.fetchone.side_effect = [({'retained_result': proof},), ('predecessor',), None]
    cursor.fetchall.return_value = [('successor', {'retained_result_repair': proof})]
    effect = {'external_effect_id': 'effect', 'operation_id': 'review', 'status': 'SUCCEEDED',
              'attempt_id': 'attempt', 'attempt_status': attempt_status}
    acknowledge_retained_result(cursor, [effect], 'root')
    assert bool(effect.get('settled_candidate_superseded')) == expected
    assert effect['attempt_status'] == attempt_status


@pytest.mark.parametrize("pair,version", [( ("chapter-current-semantic-repair.v1", "chapter-canon-reference-contract-repair.v1"), "3.9.30"), (("chapter-canon-reference-contract-repair.v1", "chapter-canon-reference-resolution-revalidation.v1"), "3.9.31")])
@pytest.mark.parametrize("source_status", ["FAILED_FINAL", "UNKNOWN"])
def test_reference_descendant_preserves_semantic_failure_without_claiming_old_extraction_success(source_status, pair, version):
    from novel_forge.modules.command_kernel.retained_graph import _reference_descendant
    proof = {"contract_version": pair[0],
             "target_asset_version_id": "candidate", "quality_generation": 2,
             "source_operation_id": "negative-review"}
    repair = {"contract_version": pair[1],
              "source_operation_id": "failed-extraction",
              "target_asset_version_id": "candidate", "quality_generation": 2}
    cursor = Mock()
    cursor.fetchone.return_value = ({"preparation_report": {"retained_graph_continuation": {"retained_result": proof}}},
                                   version, source_status, "previous-root")
    result = _reference_descendant(cursor, "previous-root", proof, ("new-extraction", repair))
    assert result == ("new-extraction" if source_status == "FAILED_FINAL" else None)
    if source_status == "FAILED_FINAL":
        with pytest.raises(KernelError, match="RETAINED_GRAPH_EVIDENCE_DRIFT"):
            _reference_descendant(cursor, "previous-root", proof, ("new-extraction", {**repair, "target_asset_version_id": "other-candidate"}))


def test_reference_repair_acknowledges_chained_settled_failures_without_rewriting_history():
    from novel_forge.modules.command_kernel.retained_graph import _acknowledge_legacy_result as acknowledge_retained_result
    def proof(contract, operation, effect, attempt):
        return {"contract_version": contract, "source_operation_id": operation,
                "source_effect_id": effect, "source_dispatch_id": "dispatch-" + effect,
                "source_request_hash": "request-" + effect, "source_output_hash": "output-" + effect,
                "source_attempt": {"attempt_id": attempt}, "target_asset_version_id": "candidate",
                "quality_generation": 2, "provider_invoked": True}
    semantic = proof("chapter-current-semantic-repair.v1", "review", "review-effect", "review-attempt")
    semantic["source_extraction_operation_id"] = "original-extraction"
    reference = proof("chapter-canon-reference-contract-repair.v1", "failed-extraction", "quote-effect", "quote-attempt")
    cursor = Mock()
    cursor.fetchone.side_effect = [
        ({"retained_result": reference},), ("semantic-root",),
        ({"retained_result": semantic},), ("previous-root",), ("3.9.29",),
        ({"preparation_report": {"retained_graph_continuation": {"retained_result": semantic}}},
         "3.9.30", "FAILED_FINAL", "semantic-root"), None,
    ]
    cursor.fetchall.side_effect = [[("reference-extraction", {"retained_result_repair": reference})], []]
    effects = [{"external_effect_id": effect, "operation_id": operation, "status": "SUCCEEDED",
                "attempt_id": attempt, "attempt_status": status}
               for effect, operation, attempt, status in [
                   ("review-effect", "review", "review-attempt", "FAILED_RETRYABLE"),
                   ("quote-effect", "failed-extraction", "quote-attempt", "FAILED_FINAL")]]
    acknowledge_retained_result(cursor, effects, "reference-root")
    assert all(effect["settled_candidate_superseded"] for effect in effects)
    assert all(effect["successor_operation_id"] == "reference-extraction" for effect in effects)
    assert [effect["attempt_status"] for effect in effects] == ["FAILED_RETRYABLE", "FAILED_FINAL"]
