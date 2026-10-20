from copy import deepcopy
import json

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.context_builder import semantic_units
from novel_forge.modules.context_builder.source_batches import BATCH_VERSION, current_batching_version
from novel_forge.modules.context_builder.task_compression import compile_task_context
from novel_forge.modules.chapter_authority.context_compression_provider import context_compression_task_view


def test_only_explicit_current_packet_locations_enable_versioned_batching():
    packet = {"retrieval_task": {"contract_version": "working-retrieval-task.v6"}}
    for data in [{"context_bundle": {"working_manuscript": packet}},
                 {"input_manifest": {"frozen_intent": {"working_manuscript": packet}}},
                 {"input_manifest": {"arc_working_set": {"working_manuscript": packet}}}]:
        assert current_batching_version(data) == BATCH_VERSION
    assert not current_batching_version({"context_bundle": {"segments": [{"historical_producer": packet}]}})
    assert not current_batching_version({"context_bundle": {"working_manuscript": {"retrieval_task": {"contract_version": "working-retrieval-task.v5"}}}})


def compile_batch(*, verdict=None, bad_identity=False, max_units=256, version=True):
    binding = {"asset_version_id": "context:frozen", "content_hash": "sha256:source"}
    boundary = {"kind": "FROZEN_STAGE_INPUTS", "project_id": "p", "book_id": "b", "sources": [binding]}
    candidates = [ContextCandidate(asset_version_id=f"expression:{index}", project_id="p", book_id="b",
        asset_type="historical_expression_projection", estimated_tokens=1, relevance_score=1,
        safe_summary=f"Source {index} exact necessary quotation.\n\n" + f"Source {index} unrelated background. " * 30,
        content_digest=f"sha256:expression:{index}",
        provenance={"frozen_input_boundary": boundary, "source_binding": binding,
            "source_expression": {"asset_version_id": f"chapter:{index}", "content_hash": f"sha256:chapter:{index}", "chapter": index + 1}})
        for index in range(3)]
    task = {"stage": "draft", "frozen_input_boundary": boundary, "source_projection_hash": "sha256:task",
        "semantic_contract": semantic_units.SEMANTIC_CONTRACT, "capacity_policy": "complete-request-capacity.v1",
        "preserve_quotes": [f"Source {index} exact necessary quotation." for index in range(3)],
        **({"source_batching_version": BATCH_VERSION} if version else {})}
    calls = []
    def call(stage, chunk):
        view = context_compression_task_view(stage, {"context_compression_task": chunk})
        calls.append((stage, deepcopy(view)))
        evidence = {"external_effect_id": f"effect:{len(calls)}", "receipt_id": f"receipt:{len(calls)}"}
        if stage == "context_compress":
            return {"selected_unit_ids": ["another-source"] if bad_identity else chunk["required_unit_ids"], "_execution_evidence": evidence}
        if isinstance(verdict, Exception):
            raise verdict
        value = verdict(stage, chunk, len(calls)) if callable(verdict) else verdict
        return {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": [],
            **(value or {}), "_execution_evidence": evidence}
    result, receipt = compile_task_context(candidates, task=task, token_budget=2000, required_asset_types=(),
        model_call=call, compression_input_tokens=512000, chunk_fits=lambda chunk: len(chunk["units"]) <= max_units,
        token_counter=lambda value: len(json.dumps(value, ensure_ascii=False).encode()), allow_restored_overflow=True)
    return candidates, result, receipt, calls


def test_shared_batch_preserves_each_original_source_and_native_receipt_identity():
    originals, results, receipt, calls = compile_batch()
    assert [stage for stage, _ in calls] == ["context_compress", "context_fidelity"]
    assert len(calls[0][1]["units"]) == 6
    for index, (original, result) in enumerate(zip(originals, results, strict=True)):
        assert f"Source {index} exact necessary quotation." in result.safe_summary
        assert "unrelated background" not in result.safe_summary
        assert result.asset_version_id == original.asset_version_id
        trace = result.compression_trace[0]
        assert [row["external_effect_id"] for row in trace["model_execution_evidence"]] == ["effect:1", "effect:2"]
        assert trace["source_batch"]["provider_execution_scope"] == "SHARED_BATCH_NOT_PER_SOURCE_CALL"
        assert trace["source_binding"] == original.provenance["source_binding"]
        assert {u["unit_id"] for u in trace["source_catalog"]} == {"text:0", "text:1"}
    assert len(receipt["compression_trace"]) == 3
    assert {unit["attribution"]["source_expression"]["asset_version_id"] for unit in calls[0][1]["units"]} == {"chapter:0", "chapter:1", "chapter:2"}


@pytest.mark.parametrize("verdict", [
    {"supported": False}, {"coverage_complete": False}, {"missing_unit_ids": ["unknown-source"]},
    {"distorted_unit_ids": ["unknown-source"]}, {"missing_unit_ids": "invalid"}])
def test_uncertain_shared_fidelity_restores_all_originals_without_extra_send(verdict):
    originals, results, _, calls = compile_batch(verdict=verdict)
    assert len(calls) == 2
    assert [item.safe_summary for item in originals] == [item.safe_summary for item in results]
    assert all(item.compression_trace[0]["source_batch"]["restoration"] == "EXACT_ORIGINAL_BATCH" for item in results)


def test_unknown_batch_selection_fails_closed():
    with pytest.raises(KernelError, match="Batch selection"):
        compile_batch(bad_identity=True)


def test_single_source_capacity_fallback_and_old_version_retain_original_algorithm():
    observations = []
    for options in [{"max_units": 2}, {"version": False}]:
        originals, results, _, calls = compile_batch(**options)
        assert all(not item.compression_trace or "source_batch" not in item.compression_trace[0] for item in results)
        assert all(original.asset_version_id == result.asset_version_id for original, result in zip(originals, results, strict=True))
        observations.append(([item.safe_summary for item in results], [stage for stage, _ in calls]))
    assert observations[0] == observations[1]


def test_actual_capacity_preparation_batches_then_checks_final_provider_composition():
    from tests.unit.test_semantic_context_units import semantic_preparation
    from novel_forge.modules.context_builder.request_capacity import apply_capacity_projection
    data = {"input_manifest": {"goal": "Honor each attributed earlier event."},
        "context_bundle": {"working_manuscript": {"retrieval_task": {"contract_version": "working-retrieval-task.v6"}},
            "segments": [{"asset_type": "chapter_episodic_summary", "asset_version_id": f"chapter:{index}",
                "content_hash": f"hash:{index}", "safe_summary": json.dumps({"subject": f"actor:{index}",
                    "perspective": "HEARSAY", "knowledge_owner": f"actor:{index}",
                    "summary": "\n\n".join(f"Incident {part}. " + "Background description. " * 40 for part in range(2))}),
                "structured_facts": []} for index in range(3)]}}
    def select(stage, task):
        if stage == "context_compress":
            first_per_source = {}
            for unit in task["units"]:
                source = unit["attribution"]["source_expression"]["asset_version_id"]
                first_per_source.setdefault(source, unit["unit_id"])
            return {"selected_unit_ids": list(dict.fromkeys([*task["required_unit_ids"], *first_per_source.values()]))}
    original, projection, calls = semantic_preparation(data, limit=5000, callback=select)
    assert projection["compression_receipt"]["compression_trace"]
    assert all(trace["source_batch"]["version"] == BATCH_VERSION for trace in projection["compression_receipt"]["compression_trace"])
    assert len([call for call in calls if call["stage"] == "context_compress"]) == 1
    assert any(call.get("composition_check", {}).get("phase") == "FINAL_PROVIDER_COMPOSITION" for call in calls)
    decoded = apply_capacity_projection(original, projection)
    for index, segment in enumerate(decoded["context_bundle"]["segments"]):
        summary = segment["safe_summary"]
        if isinstance(summary, str):
            summary = json.loads(summary)
        assert summary["subject"] == summary["knowledge_owner"] == f"actor:{index}"
        assert summary["perspective"] == "HEARSAY"
    assert projection["measurement"]["after_reserved"] <= 5000


def test_located_batch_omission_is_restored_and_rechecked_under_distinct_native_evidence():
    def verdict(stage, chunk, count):
        if count == 2:
            missing = next(unit["unit_id"] for unit in chunk["units"] if unit["unit_id"] not in chunk["selected_unit_ids"])
            return {"missing_unit_ids": [missing], "coverage_complete": False}
    originals, results, _, calls = compile_batch(verdict=verdict)
    assert [stage for stage, _ in calls] == ["context_compress", "context_fidelity", "context_fidelity"]
    assert results[0].safe_summary == originals[0].safe_summary
    assert all("unrelated background" not in item.safe_summary for item in results[1:])
    assert all(len(item.compression_trace[0]["model_execution_evidence"]) == 3 for item in results)


def test_batch_provider_cancellation_propagates_without_legacy_resend():
    with pytest.raises(KernelError, match="CANCELLED_BY_OWNER"):
        compile_batch(verdict=KernelError("CANCELLED_BY_OWNER", "Native cancellation retains the original invocation"))
