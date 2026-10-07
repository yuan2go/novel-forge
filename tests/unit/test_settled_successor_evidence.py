from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.settled_successor_evidence import _require_binding, _require_rejection


def binding():
    source = {'operation_id': 'old', 'definition_name': 'chapter.canon.extract', 'status': 'FAILED_FINAL',
        'project_id': 'p', 'workspace_id': 'w', 'actor_id': 'author', 'root_operation_id': 'root',
        'saga_id': 'saga', 'step_key': 'canon_extraction', 'command_payload': {'chapter': 1}, 'input_asset_snapshot': [{'hash': 'frozen'}]}
    current = {**deepcopy(source), 'operation_id': 'new', 'status': 'SUCCEEDED',
        'definition_version': '3.10.0', 'causation_operation_id': 'old'}
    return source, current, deepcopy(source), {'contract_version': 'chapter-known-receipt.v2'}


def test_current_acknowledgement_retains_exact_native_source():
    _require_binding(*binding())


@pytest.mark.parametrize('field,value', [('project_id', 'other'), ('workspace_id', 'other'), ('actor_id', 'other'),
    ('root_operation_id', 'other'), ('saga_id', 'other'), ('step_key', 'other'), ('input_asset_snapshot', []),
    ('definition_version', '3.10.1'), ('status', 'FAILED_FINAL'), ('causation_operation_id', 'other')])
def test_current_acknowledgement_rejects_cross_scope_or_incomplete_successor(field, value):
    source, current, frozen, policy = binding()
    current[field] = value
    with pytest.raises(KernelError, match='SETTLED_SUCCESSOR_EVIDENCE_DRIFT'):
        _require_binding(source, current, frozen, policy)


def rejection():
    effect = {'external_effect_id': 'effect', 'operation_id': 'old', 'request_hash': 'request', 'status': 'FAILED_FINAL',
        'last_error': {'production_execution': {'execution_result': {'process_receipt_ref': 'authority-asset-version:receipt'}}}}
    budget = {'status': 'SETTLED', 'accounting_basis': 'ACCOUNT_ENTITLEMENT', 'evidence': {'cost_authorization_ref': 'member'}}
    proof = {'request_hash': 'request', 'effect_status': 'FAILED_FINAL', 'reservation_status': 'SETTLED',
        'accounting_basis': 'ACCOUNT_ENTITLEMENT', 'process_receipt_asset_version_id': 'receipt',
        'process_receipt_hash': 'receipt-hash', 'outcome': 'COMPLETED_OUTPUT_SCHEMA_FAILURE'}
    receipt = ('receipt-hash', {'kind': 'process-receipt', 'contract_version': 'authority-execution-evidence.v1',
        'payload': {'operation_id': 'old', 'execution_id': 'chapter-execution:effect', 'status': 'SUCCEEDED'}})
    return effect, budget, proof, receipt


def test_completed_nonproducing_effect_preserves_terminal_status_and_accounting():
    values = rejection()
    before = deepcopy(values)
    _require_rejection(*values)
    assert values == before


@pytest.mark.parametrize('part,field,value', [(0, 'request_hash', 'foreign'), (0, 'status', 'UNKNOWN'),
    (1, 'status', 'HELD_UNKNOWN'), (1, 'accounting_basis', 'PRICED'), (2, 'process_receipt_hash', 'drift'),
    (2, 'reservation_status', 'RESERVED'), (2, 'request_hash', 'borrowed')])
def test_nonproducing_acknowledgement_rejects_unknown_borrowed_or_hash_drift(part, field, value):
    values = list(rejection())
    values[part][field] = value
    with pytest.raises(KernelError, match='SETTLED_SUCCESSOR_REJECTION_DRIFT'):
        _require_rejection(*values)


def test_nonproducing_acknowledgement_rejects_foreign_process_owner():
    effect, budget, proof, receipt = rejection()
    receipt[1]['payload']['operation_id'] = 'foreign'
    with pytest.raises(KernelError, match='SETTLED_SUCCESSOR_REJECTION_DRIFT'):
        _require_rejection(effect, budget, proof, receipt)
