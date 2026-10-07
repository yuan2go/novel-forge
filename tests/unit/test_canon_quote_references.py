from __future__ import annotations

import pytest

from novel_forge.modules.chapter_authority.canon_quote_references import (
    build_references,
    bind_reference_schema,
    resolve_references,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
from novel_forge.modules.production_execution.codex_configuration import (
    codex_output_schema,
    decode_codex_output,
)


def test_reference_resolution_preserves_exact_source_and_keeps_semantic_review_unrun():
    text = "陆圆翻到新页，写下记录。\n\n他合上第一份供餐记录。"
    corpus = build_references(text, target_asset_version_id="candidate-v1")
    reference = corpus["references"][0]["reference_id"]
    raw = {"claims": [{"evidence_quote": reference}], "observations": [{"quote": None}]}
    resolved, evidence = resolve_references(
        raw, text=text, target_asset_version_id="candidate-v1", corpus=corpus
    )
    assert resolved["claims"][0]["evidence_quote"] == text.split("\n")[0]
    assert raw["claims"][0]["evidence_quote"] == reference
    assert evidence["semantic_support"] == "NOT_RUN"
    for quote in ("他翻到新页，写下记录。", "foreign-reference"):
        with pytest.raises(KernelError, match="CANON_REFERENCE_INVALID"):
            resolve_references(
                {"quote": quote},
                text=text,
                target_asset_version_id="candidate-v1",
                corpus=corpus,
            )
    with pytest.raises(KernelError, match="CANON_REFERENCE_SOURCE_DRIFT"):
        resolve_references(
            raw, text=text, target_asset_version_id="candidate-v2", corpus=corpus
        )
    with pytest.raises(KernelError, match="CANON_REFERENCE_OFFSET_INVALID"):
        resolve_references(
            {"quote": reference, "start": 1, "end": 2},
            text=text,
            target_asset_version_id="candidate-v1",
            corpus=corpus,
        )


def test_wire_reference_contract_preserves_nullable_observations_and_requires_real_ids():
    corpus = build_references("原始正文。", target_asset_version_id="candidate-v1")
    schema = bind_reference_schema(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "quote": {"type": "string"},
                "evidence_quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["quote", "evidence_quote"],
            "additionalProperties": False,
        },
        corpus,
    )
    valid = {"quote": corpus["references"][0]["reference_id"], "evidence_quote": None}
    validate_chapter_provider_output_against_schema('canon_extraction', schema, valid)
    with pytest.raises(KernelError, match='CHAPTER_PROVIDER_OUTPUT_SCHEMA_INVALID'):
        validate_chapter_provider_output_against_schema('canon_extraction', schema, {'quote': '伪造文字', 'evidence_quote': None})
    import json

    envelope = {"output_json": json.dumps(valid, ensure_ascii=False)}
    assert (
        decode_codex_output(
            envelope, schema_ref="schema:chapter-provider-output:canon_extraction:v27"
        )[0]
        == valid
    )
    assert codex_output_schema(
        schema, schema_ref="schema:chapter-provider-output:canon_extraction:v27"
    )["properties"] == {"output_json": {"type": "string"}}


def test_duplicate_paragraphs_resolve_to_the_selected_original_interval():
    text = "同一句话。\n\n同一句话。"
    corpus = build_references(text, target_asset_version_id="candidate-v1")
    selected = corpus["references"][1]
    resolved, evidence = resolve_references(
        {"evidence_quote": selected["reference_id"]},
        text=text, target_asset_version_id="candidate-v1", corpus=corpus,
    )
    assert resolved == {"evidence_quote": "同一句话。",
                        "evidence_start": selected["start"],
                        "evidence_end": len(text)}
    assert evidence["mappings"][0]["start"] == selected["start"]


def test_provider_view_retains_all_prose_without_duplicating_host_interval_directory():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    text = "第一段正文。\n\n第二段正文。"
    corpus = build_references(text, target_asset_version_id="candidate-v1")
    view = build_provider_task_view("canon_extraction", {
        "revision": {"text": text}, "canon_quote_references": corpus})
    assert view["final_candidate"]["text"] == corpus["rendered_text"]
    assert "references" not in view["canon_quote_references"]
    assert view["canon_quote_references"]["reference_corpus_hash"] == snapshot_hash(corpus)
    assert view["canon_quote_references"]["reference_count"] == 2
