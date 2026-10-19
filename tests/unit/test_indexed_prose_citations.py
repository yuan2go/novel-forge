from copy import deepcopy

import pytest

from novel_forge.modules.book_followup_authority.prose_review import (
    aggregate_reports,
    freeze_manifest,
    prose_review_invoke_payload,
    validate_window_report,
)
from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_longform_prose_editorial import chapter_literal_report_case


CONTRACT = "indexed-prose-citation.v1"
BODY = "他合上账本。\r\n\r\n她说：\n“这笔工钱还未挣到。”\n他合上账本。"


def indexed_case():
    prior, _, raw = chapter_literal_report_case()
    frozen = freeze_manifest(project_id="p", workspace_id="w", book_run_id="b", sources=[{
        "chapter_number": 17, "acceptance_id": "", "asset_version_id": "selected-17", "asset_hash": "asset-hash",
        "text": BODY, "source_isolation": "AUTHOR_SELECTED_UNREVIEWED_PROSE",
    }], policy={**prior["policy"], "citation_locator_contract": CONTRACT, "reading_mode": "BODY_FIRST",
               "window_codepoints": 1000, "overlap_codepoints": 0, "maximum_windows": 1}, work_intent=False)
    window = frozen["windows"][0]
    raw.update(schema_version="longform-prose-review.v5", manifest_digest=frozen["manifest_digest"], window_id=window["window_id"])
    raw["findings"][0]["evidence"] = [{"citation_id": "P0001"}]
    return frozen, window, raw


def test_model_selects_frozen_passage_without_retyping_quotation_or_coordinates():
    frozen, window, raw = indexed_case()
    original = deepcopy((frozen, raw))
    resolved = validate_window_report(raw, manifest=frozen, window=window)
    evidence = resolved["findings"][0]["evidence"][0]
    assert evidence == {"citation_id": "P0001", "chapter_number": 17, "asset_version_id": "selected-17",
                        "text_hash": window["spans"][0]["text_hash"], "start": 0, "end": len("他合上账本。\r\n"), "quote": "他合上账本。\r\n"}
    assert validate_window_report(resolved, manifest=frozen, window=window) == resolved
    assert (frozen, raw) == original
    assert resolved["findings"][0]["claim"] == raw["findings"][0]["claim"]
    assert resolved["findings"][0]["repair"] == raw["findings"][0]["repair"]
    assert aggregate_reports(frozen, [raw])["findings"][0]["members"][0]["evidence"] == resolved["findings"][0]["evidence"]


@pytest.mark.parametrize("tamper", ["citation_id", "asset_version_id", "text_hash", "chapter_number", "quote", "start", "end"])
def test_indexed_citation_rejects_unknown_ids_and_tampered_persisted_bindings(tamper):
    frozen, window, raw = indexed_case()
    if tamper != "citation_id":
        raw = validate_window_report(raw, manifest=frozen, window=window)
    evidence = raw["findings"][0]["evidence"][0]
    evidence[tamper] = 999 if tamper in {"chapter_number", "start", "end"} else "changed"
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION"):
        validate_window_report(raw, manifest=frozen, window=window)


def test_indexed_schema_forbids_model_generated_quote_or_partial_host_identity():
    frozen, window, raw = indexed_case()
    raw["findings"][0]["evidence"][0]["quote"] = "他合上账本。她说：这笔工钱还未挣到。"
    with pytest.raises(KernelError, match="CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID"):
        validate_window_report(raw, manifest=frozen, window=window)


def test_repeated_text_has_distinct_exact_locations_without_relaxing_legacy_uniqueness():
    frozen, window, raw = indexed_case()
    raw["findings"][0]["evidence"] = [{"citation_id": "P0004"}]
    resolved = validate_window_report(raw, manifest=frozen, window=window)
    evidence = resolved["findings"][0]["evidence"][0]
    assert evidence["quote"] == "他合上账本。"
    assert evidence["start"] == BODY.rindex("他合上账本。")
    assert BODY[evidence["start"]:evidence["end"]] == evidence["quote"]
    legacy = deepcopy(raw)
    legacy["schema_version"] = "longform-prose-review.v4"
    legacy["findings"][0]["evidence"] = [{"chapter_number": 17, "quote": "他合上账本。"}]
    frozen["policy"]["citation_locator_contract"] = "chapter-literal-prose-citation.v1"
    with pytest.raises(KernelError, match="LONGFORM_PROSE_CITATION_NOT_UNIQUE"):
        validate_window_report(legacy, manifest=frozen, window=window)


def test_indexed_provider_view_supplies_ids_beside_complete_unchanged_prose_and_binds_schema():
    from novel_forge.modules.book_followup_authority.prose_sampling import prose_sample_invoke_payload
    from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
    from novel_forge.modules.chapter_authority.provider_views import build_provider_context_view

    frozen, window, _ = indexed_case()
    content = dict(schema_version="longform-prose-window.v3", manifest_digest=frozen["manifest_digest"], policy=frozen["policy"],
                   window=window, source_isolation="AUTHOR_SELECTED_UNREVIEWED_PROSE")
    invocation = prose_review_invoke_payload(content)
    assert invocation == prose_sample_invoke_payload(content)
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage="longform_prose_review", request_payload={"input": invocation})
    assert ref == "schema:chapter-provider-output:longform_prose_review:v5"
    citation = schema["properties"]["findings"]["items"]["anyOf"][0]["properties"]["evidence"]["items"]
    assert set(citation["properties"]) == {"citation_id"}
    context = dict(schema_version="novelos.longform_prose_review_context_bundle.v2",
                   selected_inputs=[dict(asset_type="longform_prose_review_window", projection=content)])
    before = deepcopy(context)
    view = build_provider_context_view("longform_prose_review", context, invocation)
    span = view["frozen_prose"]["window"]["spans"][0]
    assert "text" not in span
    assert "asset_version_id" not in span
    assert "text_hash" not in span
    assert "citation_id" in view["instruction"]
    assert "".join(p["text"] for p in span["passages"]) == BODY
    assert [p["citation_id"] for p in span["passages"] if "citation_id" in p] == ["P0001", "P0002", "P0003", "P0004"]
    assert context == before


def test_indexed_contract_never_reinterprets_a_historical_invalid_literal_report():
    frozen, window, raw = indexed_case()
    raw["schema_version"] = "longform-prose-review.v4"
    raw["findings"][0]["evidence"] = [{"chapter_number": 17, "quote": "他合上账本。她说：这笔工钱还未挣到。"}]
    with pytest.raises(KernelError, match="LONGFORM_PROSE_REPORT_CONTRACT_DRIFT"):
        validate_window_report(raw, manifest=frozen, window=window)


def test_unknown_passage_id_is_local_output_failure_while_remote_outcome_remains_unknown():
    from novel_forge.modules.command_kernel.worker_execution import WorkerFailureClass, WorkerFailureClassifier

    assert WorkerFailureClassifier.classify(KernelError("LONGFORM_PROSE_CITATION_ID_UNKNOWN", "Unprovided passage ID")) is WorkerFailureClass.RETRYABLE
    assert WorkerFailureClassifier.classify(KernelError("MODEL_EFFECT_EXTERNAL_STATE_UNKNOWN", "Remote result uncertain")) is WorkerFailureClass.UNKNOWN_EXTERNAL_STATE
