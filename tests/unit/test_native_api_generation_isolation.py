from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.generation_isolation import require_native_api_isolation_record
from novel_forge.modules.production_execution.backends import ResolvedExecutionPayload, _freeze_output_contract
from novel_forge.modules.production_execution.contracts import ExecutionRuntimeClass
from tests.unit.test_production_execution_gateway import contracts


@pytest.fixture
def retained(tmp_path):
    request = contracts(backend_id="remote-provider", runtime=ExecutionRuntimeClass.REMOTE_PROVIDER_API)[5]
    payload = ResolvedExecutionPayload(request_payload={"input": "frozen"}, input_text="original", working_directory=str(tmp_path), timeout_seconds=30,
        output_schema_version="schema:v1", output_schema={"type": "object"})
    content = {"request_contract_hash": request.contract_hash, "record": {
        "request": request.to_dict(), "handle": {"transport": "REMOTE_PROVIDER_API"},
        "frozen_output_contract": _freeze_output_contract(request, payload, "sha256:original-envelope"),
        "raw_evidence": {"submission_phase": "PROVIDER_OUTCOME_UNKNOWN"}}}
    scope = dict(project_id=request.project_id, book_id=request.book_id, operation_id=request.operation_id,
        effect_id=request.external_effect_id, capability={"provider_request_envelope_hash": "sha256:original-envelope"})
    return request, content, scope


def test_lost_remote_receipt_does_not_require_fabricating_a_process_receipt(retained):
    request, content, scope = retained
    original, record = require_native_api_isolation_record(content, **scope)
    assert original == request
    assert record.get("provider_result") is None
    assert record.get("process_receipt") is None


@pytest.mark.parametrize("change", ["book", "operation", "envelope", "schema", "transport", "phase"])
def test_durable_invocation_cannot_authorize_another_identity_or_unadmitted_boundary(retained, change):
    _, content, scope = retained
    content, scope = deepcopy(content), deepcopy(scope)
    if change in {"book", "operation"}:
        scope[change + "_id"] = "another"
    elif change == "envelope":
        scope["capability"]["provider_request_envelope_hash"] = "another"
    elif change == "schema":
        content["record"]["frozen_output_contract"]["output_schema"] = {"type": "string"}
    elif change == "transport":
        content["record"]["handle"]["transport"] = "LOCAL_PROCESS"
    else:
        content["record"]["raw_evidence"]["submission_phase"] = "NOT_ADMITTED"
    with pytest.raises(KernelError, match="GENERATION_ISOLATION_"):
        require_native_api_isolation_record(content, **scope)


@pytest.mark.parametrize("completion", ["normalized", "raw_complete"])
def test_complete_content_must_be_reused_even_when_usage_is_missing(retained, completion):
    _, content, scope = retained
    if completion == "normalized":
        content["record"]["result"] = {"normalized_output_ref": "authority-asset-version:saved"}
    else:
        content["record"]["provider_result"] = {"outcome": "success"}
    with pytest.raises(KernelError, match="GENERATION_ISOLATION_RESULT_RECOVERABLE"):
        require_native_api_isolation_record(content, **scope)
