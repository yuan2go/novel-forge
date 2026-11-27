import pytest

from novel_forge.modules.story_planning_runtime.gateway_result_recovery import (
    RELEASE_FAILURE_MESSAGE, RETRYABLE_RELEASE_VERSION, VERSION,
    gateway_result_revalidation_definition, retryable_release_failure,
)


@pytest.mark.parametrize("status,result,allowed", [
    ("FAILED_RETRYABLE", {"error_code": "CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT", "error_message": RELEASE_FAILURE_MESSAGE}, True),
    ("FAILED_RETRYABLE", {"error_code": "CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT", "error_message": RELEASE_FAILURE_MESSAGE + ", skill_bundle_hash"}, False),
    ("FAILED_RETRYABLE", {"error_code": "PROVIDER_MODEL_CAPACITY_UNAVAILABLE", "error_message": RELEASE_FAILURE_MESSAGE}, False),
    ("CANCELLED", {"error_code": "CAPABILITY_PACK_RUNTIME_ADMISSION_DRIFT", "error_message": RELEASE_FAILURE_MESSAGE}, False),
    ("FAILED_RETRYABLE", None, False),
])
def test_retryable_recovery_requires_the_exact_release_only_failed_attempt(status, result, allowed):
    assert retryable_release_failure(status, ("attempt", 1, "FAILED_RETRYABLE", result)) is allowed


def test_release_recovery_has_a_new_contract_and_preserves_the_old_definition():
    values = {"application_build_id": "test", "commit_sha": "a" * 40}
    old = gateway_result_revalidation_definition(**values)
    current = gateway_result_revalidation_definition(**values, contract_version=RETRYABLE_RELEASE_VERSION)
    assert (old["definition_version"], old["handler_contract_version"]) == ("1.0.0", VERSION)
    assert (current["definition_version"], current["handler_contract_version"]) == ("1.1.0", RETRYABLE_RELEASE_VERSION)
    assert current["policy"]["provider_dispatch_allowed"] is False


def test_context_chunk_logs_and_costs_have_distinct_effect_identities():
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.execution import _PlanningPepPort
    writes = []
    port = object.__new__(_PlanningPepPort)
    port.writer = SimpleNamespace(materialize_output=writes.append)
    request = SimpleNamespace(operation_id="operation", attempt_id="attempt", project_id="project",
        fencing_token=1, trace_id="trace", correlation_id="correlation")
    port.binding = SimpleNamespace(request=request)
    for stage, effect in (("context_compress", "chunk-one"), ("context_fidelity", "check-one"), ("context_compress", "chunk-two")):
        request.stage = stage
        port.effect_id = effect
        for asset_type in ("model_call_log", "cost_ledger"):
            port._record_evidence(asset_type, {})
    assert len({write.asset_id for write in writes}) == 6
    assert len({write.logical_ref for write in writes}) == 6
    assert len({write.output_key for write in writes}) == 6
    assert [write.content["source_external_effect_id"] for write in writes] == ["chunk-one", "chunk-one", "check-one", "check-one", "chunk-two", "chunk-two"]
    request.stage = "chapter_plan.generate"
    port._record_evidence("model_call_log", {})
    assert writes[-1].asset_id == "model_call_log:operation:attempt"
