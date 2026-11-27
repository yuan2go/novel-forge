from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.book_followup_authority.execution import PostgresReaderOutcomeExecutionContractBinder
from novel_forge.modules.book_followup_authority.prose_execution import PostgresLongformProseReviewExecutionContractBinder
from novel_forge.modules.book_followup_authority.screenplay_execution import PostgresScreenplayExecutionContractBinder
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.chapter_quality_authority.model_reference_execution import ModelReferenceExecutionContractBinder
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority.evaluation_execution import PostgresNarrativeEvaluationExecutionContractBinder


OWNERS = [
    (PostgresReaderOutcomeExecutionContractBinder, "reader_outcome"),
    (PostgresLongformProseReviewExecutionContractBinder, "longform_prose_review"),
    (PostgresScreenplayExecutionContractBinder, "screenplay_revision"),
    (PostgresNarrativeEvaluationExecutionContractBinder, "narrative_semantic_evaluation"),
    (ModelReferenceExecutionContractBinder, "model_reference_evaluate"),
]


def owner_request(stage):
    pointer = {"asset_version_id": "context:owner", "content_hash": "sha256:" + "a" * 64, "artifact_type": "context_bundle",
               "artifact_ref": "asset-version:context:owner", "schema_version": "owner-context.v1", "source_eligibility": "PRODUCTION_ELIGIBLE"}
    return {"stage": "context_compress", "input": {"context_compression_task": {
        "contract_version": "task-context-compression.v2", "source_binding": {"asset_version_id": "context:owner", "content_hash": "sha256:" + "a" * 64},
        "task": {"stage": stage, "capacity_policy": "complete-request-capacity.v1"}}},
        "_production_execution": {"project_id": "project", "operation_id": "operation", "attempt_id": "attempt",
                                  "context_capacity_owner_stage": stage, "input_artifacts": [pointer], "model_reference": {"source": "exact"}}}


def binder_fixture(cls):
    binder = object.__new__(cls)
    binder.database_url = "fixture"
    binder.query = SimpleNamespace(require=lambda **_: SimpleNamespace(content_hash="sha256:" + "a" * 64,
        content={"operation_id": "operation", "attempt_id": "attempt"}))
    binder.assert_before_provider_send = lambda **_: {"command": {"generator_operation_name": "model_reference_evaluate"}, "frozen": {"source": "exact"}}
    return binder


@pytest.mark.parametrize("cls,stage", OWNERS)
def test_context_substage_retains_owner_validation_and_forwards_capacity_contract(monkeypatch, cls, stage):
    binder = binder_fixture(cls)
    binder.stage_name = stage
    request = owner_request(stage)
    callback = object()
    captured = []
    monkeypatch.setattr(PostgresChapterExecutionContractBinder, "freeze_before_external_effect",
                        lambda self, **values: captured.append(values) or "owner-preflight")
    assert binder.freeze_before_external_effect(capability="model.context_compress", request_payload=request,
        snapshot_fencing_token=7, snapshot_worker_id="worker", context_model_call=callback, capacity_probe=True) == "owner-preflight"
    assert captured == [{"capability": "model.context_compress", "request_payload": request,
        "snapshot_fencing_token": 7, "snapshot_worker_id": "worker", "context_model_call": callback, "capacity_probe": True}]


@pytest.mark.parametrize("change,error", [
    ("owner", "CONTEXT_COMPRESSION_OWNER_DRIFT"),
    ("source", "CONTEXT_COMPRESSION_SOURCE_DRIFT"),
    ("attempt", "CONTEXT_COMPRESSION_OWNER_DRIFT"),
])
def test_context_substage_rejects_foreign_owner_source_and_attempt(monkeypatch, change, error):
    from novel_forge.modules.chapter_authority import receipt_recovery
    monkeypatch.setattr(receipt_recovery, "_owner_context_sources", lambda *_a, **_kw: ())
    binder = binder_fixture(PostgresReaderOutcomeExecutionContractBinder)
    request = deepcopy(owner_request("reader_outcome"))
    if change == "owner":
        request["input"]["context_compression_task"]["task"]["stage"] = "draft"
    elif change == "source":
        request["input"]["context_compression_task"]["source_binding"]["content_hash"] = "sha256:another"
    else:
        request["_production_execution"]["attempt_id"] = "another-attempt"
    with pytest.raises(KernelError, match=error):
        binder._require_capacity_context_owner(request, owner_stage="reader_outcome")


@pytest.mark.parametrize("cls,stage", OWNERS)
def test_owner_uses_context_schema_without_admitting_its_main_output_shape(cls, stage):
    binder = binder_fixture(cls)
    payload = owner_request(stage)
    actual = binder._provider_output_contract(stage="context_compress", request_payload=payload)
    assert actual == PostgresChapterExecutionContractBinder._provider_output_contract(stage="context_compress", request_payload=payload)
    assert "selected_unit_ids" in actual[0]["properties"]


def test_real_recursive_model_envelope_carries_owner_created_context_and_reference(monkeypatch):
    from novel_forge.modules.chapter_authority import model_effects
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset
    from novel_forge.modules.command_kernel import deadline_runtime

    frozen = {"subject": {"asset_version_id": "original", "content_hash": "sha256:" + "b" * 64}}
    document = SimpleNamespace(asset_version_id="context:owner", asset_type="context_bundle", content_hash="sha256:" + "a" * 64,
                               content={"operation_id": "operation", "attempt_id": "attempt"})
    captured = {}

    class OwnerBinder:
        supports_request_capacity = True

        def freeze_before_external_effect(self, *, request_payload, context_model_call, **_):
            if request_payload["stage"] == "model_reference_evaluate":
                request_payload["_production_execution"]["input_artifacts"] = owner_request("model_reference_evaluate")["_production_execution"]["input_artifacts"]
                return context_model_call("context_compress", owner_request("model_reference_evaluate")["input"]["context_compression_task"])
            captured.update(request_payload)
            raise KernelError("CAPTURED_BEFORE_SEND", "Inspect native envelope construction without external I/O")

    route = SimpleNamespace(model_context_limit=512000, model_output_limit=32000, model_profile=SimpleNamespace(model_provider="scripted_provider_v2", backend_id="fixture"))
    adapter = SimpleNamespace(provider="scripted_provider_v2", routes={"model_reference_evaluate": route, "context_compress": route})
    port = model_effects.ExternalEffectChapterModelPort("postgresql://unit-not-connected", adapter=adapter, worker_id="worker",
        capability_binder=OwnerBinder(), execution_binding_domain="model_reference")
    port.query = SimpleNamespace(require=lambda **_: document)
    monkeypatch.setattr(port, "_execution_identity", lambda *_a, **_kw: (1, "worker"))
    monkeypatch.setattr(port, "_request_timeout_seconds", lambda _: 30)
    monkeypatch.setattr(model_effects, "read_external_effect_intent", lambda *_a, **_kw: None)
    monkeypatch.setattr(deadline_runtime, "probe_operation_execution", lambda *_a, **_kw: None)
    monkeypatch.setattr(model_effects, "resolve_provider_token_reservation_contract", lambda *_a, **_kw: {
        "source": "FROZEN_REQUEST_INPUT_PLUS_OUTPUT_CEILING", "estimated_total_tokens": 512000, "max_output_tokens": 32000})
    request = ChapterHandlerRequest(operation_id="operation", project_id="project", workspace_id="workspace", trace_id="trace", correlation_id="correlation",
        command={"context_token_budget": 512000, "generator_operation_name": "model_reference_evaluate", "model_reference": frozen},
        inputs=(ChapterInputAsset("original", "draft_version", "sha256:" + "b" * 64, {}),), attempt_id="attempt", fencing_token=1, worker_id="worker")
    with pytest.raises(KernelError, match="CAPTURED_BEFORE_SEND"):
        port.invoke(request, stage="model_reference_evaluate", payload={})
    assert captured["_production_execution"]["model_reference"] == frozen
    assert captured["_production_execution"]["context_capacity_owner_stage"] == "model_reference_evaluate"
    assert [row["asset_version_id"] for row in captured["_production_execution"]["input_artifacts"]] == [document.asset_version_id]


@pytest.mark.parametrize("changed", [None, "source", "condition", "time", "knowledge_owner", "schema_version", "bool_to_int", "int_to_float"])
def test_new_attempt_retains_only_the_exact_original_owner_context(monkeypatch, changed):
    from novel_forge.modules.chapter_authority import receipt_recovery
    from novel_forge.storage import authority_asset_store
    content = {"operation_id": "operation", "attempt_id": "original-attempt", "schema_version": "owner.v1", "confirmed": True, "count": 1,
        "selected_inputs": [{"source": "version:1", "condition": "only below the water mark",
                             "time": "day ten", "knowledge_owner": "witness"}]}
    document = SimpleNamespace(asset_type="context_bundle", content_hash="sha256:" + "a" * 64,
        content=deepcopy(content), governance="CLEAR", eligibility="PRODUCTION_ELIGIBLE")
    monkeypatch.setattr(receipt_recovery, "_owner_context_sources", lambda *_a, **_kw:
        ({"asset_version_id": "original-context", "content_hash": document.content_hash},))
    monkeypatch.setattr(authority_asset_store, "AuthorityAssetQuery", lambda _: SimpleNamespace(require=lambda **_: document))
    content["attempt_id"] = "new-attempt"
    if changed == "bool_to_int":
        content["confirmed"] = 1
    elif changed == "int_to_float":
        content["count"] = 1.0
    elif changed == "schema_version":
        content[changed] = "owner.v2"
    elif changed:
        content["selected_inputs"][0][changed] = "changed"
    if changed:
        with pytest.raises(KernelError, match="CONTEXT_CAPACITY_SOURCE_DRIFT"):
            receipt_recovery.retained_owner_context("fixture", project_id="project", operation_id="operation",
                owner_stage="reader_outcome", current_content=content)
    else:
        retained = receipt_recovery.retained_owner_context("fixture", project_id="project", operation_id="operation",
            owner_stage="reader_outcome", current_content=content)
        assert retained is document and retained.content["attempt_id"] == "original-attempt"
    assert content["attempt_id"] == "new-attempt"


def test_an_old_attempt_requires_the_original_durable_source_binding(monkeypatch):
    from novel_forge.modules.chapter_authority import receipt_recovery
    binder = binder_fixture(PostgresReaderOutcomeExecutionContractBinder)
    payload = owner_request("reader_outcome")
    payload["_production_execution"]["attempt_id"] = "new-attempt"
    source = payload["input"]["context_compression_task"]["source_binding"]
    monkeypatch.setattr(receipt_recovery, "_owner_context_sources", lambda *_a, **_kw: (source,))
    assert binder._require_capacity_context_owner(payload, owner_stage="reader_outcome") is True
