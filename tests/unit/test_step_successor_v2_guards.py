from unittest.mock import Mock
from datetime import datetime, timedelta, timezone

import pytest

from novel_forge.modules.command_kernel import step_successor_v2 as recovery
from novel_forge.modules.command_kernel.errors import KernelError


@pytest.mark.parametrize("facts", [(True, False, False), (False, True, False), (False, False, True)])
def test_unknown_accounting_lease_or_cancellation_prevents_successor_mutation(facts):
    cursor = Mock()
    cursor.fetchone.side_effect = [("project",), ("root", ""), facts]
    cursor.fetchall.return_value = []
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_GRAPH_UNRECONCILED"):
        recovery._require_reconciled_graph(cursor, root_id="root", predecessor_id="source")


def test_old_settled_local_timeout_cannot_enable_a_pure_host_successor():
    cursor = Mock()
    cursor.fetchone.side_effect = [("project",), ("root", "original-book"), None, None]
    cursor.fetchall.return_value = [("old-effect", "old-operation", "FAILED_RETRYABLE", "old-process")]
    with pytest.raises(KernelError, match="EFFECT_CLI_OUTCOME_RECONCILIATION_REQUIRED"):
        recovery._require_reconciled_graph(cursor, root_id="root", predecessor_id="source")


@pytest.mark.parametrize("budget", [None, "RESERVED", "HELD_UNKNOWN"])
def test_raw_success_is_not_a_settled_verified_receipt(monkeypatch, budget):
    repository = Mock()
    repository.get_for_update.return_value = {"operation_id": "source", "request_hash": "request"}
    monkeypatch.setattr(recovery, "ExternalEffectRepository", lambda _: repository)
    monkeypatch.setattr(recovery, "_read_verified_success", lambda *_: None if budget is None else {"budget_reservation_status": budget})
    source = dict(operation_id="source", project_id="project", actor_id="actor", trace_id="trace", correlation_id="correlation")
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_RECEIPT_UNSETTLED"):
        recovery._require_verified_receipts(Mock(), source=source, expected=[("effect", "request")])


def test_foreign_success_cannot_authorize_this_successor(monkeypatch):
    repository = Mock()
    repository.get_for_update.return_value = {"operation_id": "foreign", "request_hash": "request"}
    reader = Mock()
    monkeypatch.setattr(recovery, "ExternalEffectRepository", lambda _: repository)
    monkeypatch.setattr(recovery, "_read_verified_success", reader)
    source = dict(operation_id="source", project_id="project", actor_id="actor", trace_id="trace", correlation_id="correlation")
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_RECEIPT_DRIFT"):
        recovery._require_verified_receipts(Mock(), source=source, expected=[("effect", "request")])
    reader.assert_not_called()


@pytest.mark.parametrize("explicit_deadline", [None, "business_deadline_at", "author_deadline_at"])
def test_unsent_transport_window_preserves_explicit_deadlines(explicit_deadline):
    cursor = Mock()
    cursor.fetchone.return_value = (False, False)
    deadline = datetime.now(timezone.utc) - timedelta(hours=2)
    root = {"operation_id": "root", "definition_snapshot": {"timeout_policy": {"operation_timeout_seconds": 3600}},
            "command_payload": {} if explicit_deadline is None else {explicit_deadline: deadline.isoformat()}}
    transport = {"contract_version": "chapter-unsent-context-transport.v1", "target_deployment_id": "pack", "release_sha": "sha"}
    policy = {**transport, "contract_version": "kernel-unsent-transport-window.v1"}
    if explicit_deadline:
        with pytest.raises(KernelError, match="STEP_SUCCESSOR_WINDOW_INVALID"):
            recovery._corrected_contract_window(cursor, root, {}, {}, deadline, policy, transport_policy=transport)
        cursor.execute.assert_not_called()
    else:
        result = recovery._corrected_contract_window(cursor, root, {}, {}, deadline, policy, transport_policy=transport)
        assert result["original_deadline"] == deadline.isoformat()
        assert datetime.fromisoformat(result["new_deadline"]) > datetime.now(timezone.utc)
        assert result["duration_seconds"] == 3600
        assert result["resource_authorization"] == "UNCHANGED"


def test_unsent_transport_window_rejects_release_drift():
    root = {"definition_snapshot": {"timeout_policy": {"operation_timeout_seconds": 3600}}, "command_payload": {}}
    transport = {"contract_version": "chapter-unsent-context-transport.v1", "target_deployment_id": "pack", "release_sha": "sha"}
    with pytest.raises(KernelError, match="STEP_SUCCESSOR_WINDOW_INVALID"):
        recovery._corrected_contract_window(Mock(), root, {}, {}, datetime.now(timezone.utc),
            {**transport, "contract_version": "kernel-unsent-transport-window.v1", "release_sha": "foreign"}, transport_policy=transport)


@pytest.mark.parametrize('version,failures,schemas,valid', [
    ('3.10.0', ['MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED'], [('schema:chapter-provider-output:draft:v4:working-memory-v1', 'codex-structured-schema.v5')], True),
    ('3.10.0', ['MODEL_EFFECT_FINAL_PROVIDER_SCHEMA_REJECTED'], [('other-schema', 'codex-structured-schema.v5')], False),
    ('3.10.0', ['MODEL_EFFECT_FINAL_OUTPUT_SCHEMA_FAILURE'], [('schema:chapter-provider-output:draft:v4:working-memory-v1', 'codex-structured-schema.v5')], False),
    ('3.10.2', ['CAPABILITY_PACK_DEPLOYMENT_NOT_RESOLVED', 'CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT'], [], True),
    ('3.10.2', ['CAPABILITY_PACK_OPERATION_DEFINITION_DRIFT'], [], False),
])
def test_optional_memory_recovery_binds_exact_failure_family(version, failures, schemas, valid):
    from novel_forge.modules.chapter_authority.context_transport_recovery import require_optional_memory_transport
    cursor = Mock()
    cursor.fetchone.side_effect = [('deployment',), ('chapter-optional-memory-transport.v1',), (False,)]
    cursor.fetchall.side_effect = [[(code,) for code in failures], schemas]
    source = {'operation_id': 'operation', 'project_id': 'project', 'definition_name': 'chapter.draft.generate',
        'definition_version': version, 'command_payload': {'book_id': 'book'}, 'input_asset_snapshot': ['exact']}
    policy = {'contract_version': 'chapter-optional-memory-transport.v1', 'transport_projection': 'codex-optional-working-memory.v1',
        'input_snapshot': ['exact'], 'schema_rejection_receipts': [{}], 'target_deployment_id': 'deployment', 'release_sha': 'sha'}
    if valid:
        assert require_optional_memory_transport(cursor, source, policy, '3.10.0')
    else:
        with pytest.raises(KernelError, match='CHAPTER_MEMORY_TRANSPORT_INVALID'):
            require_optional_memory_transport(cursor, source, policy, '3.10.0')
    with pytest.raises(KernelError, match='CHAPTER_MEMORY_TRANSPORT_INVALID'):
        require_optional_memory_transport(cursor, source, {**policy, 'input_snapshot': ['foreign']}, '3.10.0')


@pytest.mark.parametrize('boundary', ['valid', 'effect', 'reservation', 'output', 'foreign_release', 'changed_input', 'changed_hash', 'provider_failure', 'missing_attempt'])
def test_local_context_accounting_successor_preserves_frozen_and_unsent_boundaries(boundary):
    from novel_forge.modules.command_kernel.context_transport_recovery import _require_local_context_accounting_source
    cursor = Mock()
    flags = tuple(boundary == key for key in ('effect', 'reservation', 'output'))
    cursor.fetchone.side_effect = [flags, ('changed' if boundary == 'changed_hash' else 'hash',)]
    failures = [] if boundary == 'missing_attempt' else ['PROVIDER_ROUTING_BLOCKED'] if boundary == 'provider_failure' else ['TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED', 'TASK_CONTEXT_COMPRESSION_NOT_AUTHORIZED']
    cursor.fetchall.return_value = [(code,) for code in failures]
    source = {'operation_id': 'source', 'definition_name': 'chapter.context.build', 'definition_version': '3.10.0',
              'input_asset_snapshot': [{'asset_version_id': 'input', 'content_hash': 'hash'}]}
    policy = {'release_sha': 'foreign' if boundary == 'foreign_release' else 'sha',
              'input_snapshot': [] if boundary == 'changed_input' else source['input_asset_snapshot'], 'completion_checks': 'UNCHANGED'}
    if boundary == 'valid':
        _require_local_context_accounting_source(cursor, source, policy, 'sha')
    else:
        with pytest.raises(KernelError, match='CHAPTER_UNSENT_TRANSPORT_SOURCE_UNSAFE'):
            _require_local_context_accounting_source(cursor, source, policy, 'sha')
