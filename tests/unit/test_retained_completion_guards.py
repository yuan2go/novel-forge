from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.retained_completion import (
    KNOWN_RECEIPT, _validate_proof, retained_completion_evidence,
)


def identities():
    proof = {
        "contract_version": KNOWN_RECEIPT, "source_operation_id": "original",
        "source_effect_id": "effect", "source_dispatch_id": "dispatch",
        "source_output_hash": "sha256:output", "source_request_hash": "request",
        "provider_invoked": False, "strict_certification_eligible": False,
        "cost_authorization_ref": "original-grant",
    }
    current = dict(definition_name="chapter.canon.extract", project_id="project",
        workspace_id="workspace", actor_id="author")
    source = {**current, "operation_id": "original", "status": "FAILED_FINAL"}
    output = {key: value for key, value in proof.items() if key != "cost_authorization_ref"}
    return proof, output, source, current


def test_exact_reference_does_not_claim_another_provider_call_or_certification():
    _validate_proof(*identities())


def test_historical_paid_draft_cannot_imply_current_actor_and_continuous_scene_proof():
    proof, output, source, current = identities()
    source["definition_name"] = current["definition_name"] = "chapter.draft.generate"
    source["definition_version"] = "3.9.1"
    with pytest.raises(KernelError, match="RETAINED_COMPLETION_EVIDENCE_INVALID"):
        _validate_proof(proof, output, source, current)
    source["definition_version"] = "3.10.0"
    _validate_proof(proof, output, source, current)


@pytest.mark.parametrize("field,value", [
    ("provider_invoked", True), ("strict_certification_eligible", True),
    ("source_operation_id", "unrelated"), ("source_effect_id", "replacement-effect"),
    ("source_dispatch_id", "another-dispatch"), ("source_output_hash", "sha256:changed"),
    ("source_request_hash", "changed-request"),
])
def test_materialized_reference_cannot_change_original_receipt_or_evidence_ceiling(field, value):
    proof, output, source, current = identities()
    output[field] = value
    with pytest.raises(KernelError, match="RETAINED_COMPLETION_EVIDENCE_INVALID"):
        _validate_proof(proof, output, source, current)


@pytest.mark.parametrize("field,value", [
    ("project_id", "other"), ("workspace_id", "other"), ("actor_id", "other"),
    ("actor_id", ""), ("definition_name", "chapter.draft.generate"),
    ("status", "WAITING_EXTERNAL_RESULT"), ("status", "RECONCILIATION_REQUIRED"),
    ("status", "RUNNING"), ("status", "SUCCEEDED"),
])
def test_source_must_be_the_exact_stopped_owner(field, value):
    proof, output, source, current = identities()
    source[field] = value
    with pytest.raises(KernelError, match="RETAINED_COMPLETION_EVIDENCE_INVALID"):
        _validate_proof(proof, output, source, current)


def test_new_operation_with_its_own_effect_cannot_mask_it_with_an_old_success():
    operation = {"definition_name": "chapter.canon.extract", "definition_snapshot": {
        "definition_version": "3.10.0", "policy": {"known_receipt_recovery": KNOWN_RECEIPT},
    }}
    for state in ("UNKNOWN", "RECONCILIATION_REQUIRED", "FAILED_FINAL", "PENDING"):
        assert retained_completion_evidence(None, operation, [("model.invoke", state)]) == []


def test_historical_definition_or_undeclared_current_policy_cannot_inherit_receipts():
    operation = {"definition_name": "chapter.canon.extract", "definition_snapshot": {
        "definition_version": "3.9.5", "policy": {"known_receipt_recovery": KNOWN_RECEIPT},
    }}
    assert retained_completion_evidence(None, operation, []) == []
    operation = deepcopy(operation)
    operation["definition_snapshot"] = {"definition_version": "3.10.0", "policy": {}}
    assert retained_completion_evidence(None, operation, []) == []
