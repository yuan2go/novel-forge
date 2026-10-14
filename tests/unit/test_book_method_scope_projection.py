from copy import deepcopy

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft_context_projection import project_book_method_scope
from novel_forge.modules.mkaos_authority.craft_selection import _hash
from novel_forge.modules.chapter_authority.provider_views import compile_exact_context_references, expand_exact_context_references


def selection():
    need = {"hard_constraints": ["Retain author commitments"], "craft_context": {"query": "recall only"},
            "recent_craft_usage": [{"evidence": "working original"}], "required_card_asset_version_ids": ["method:v1"]}
    need["need_digest"] = _hash(need)
    source = {"schema_version": "mkaos-narrative-intelligence-selection.v1", "need": need,
              "knowledge_access_policy": {"mode": "ALLOW_ONLY", "usage_scope": "EXPERIMENTAL_VALIDATION",
                                          "craft_candidate_review_version": "explicit-allowlist-craft-review.v1"},
              "selected": [{"selected_content": {"mechanism": "Purpose precedes choice", "exceptions": ["Intentional ambiguity"]},
                            "applicability_assessment": {"status": "UNKNOWN", "unmet_prerequisites": ["Current information"]},
                            "craft_assessment": {"matching_assessment": {"score": 0}, "budget_assessment": {"working_allocation_history": [{"draft": "original:v1"}]}}}]}
    source["selection_digest"] = _hash(source)
    return source


def test_book_scope_preserves_current_methods_constraints_and_working_history():
    source = selection()
    original = deepcopy(source)
    result = project_book_method_scope(source)
    assert source == original
    assert result["selected"][0]["selected_content"] == original["selected"][0]["selected_content"]
    assert result["selected"][0]["applicability_assessment"] == original["selected"][0]["applicability_assessment"]
    assert result["selected"][0]["craft_assessment"]["budget_assessment"] == original["selected"][0]["craft_assessment"]["budget_assessment"]
    assert result["need"]["hard_constraints"] == source["need"]["hard_constraints"]
    assert result["need"]["recent_craft_usage"] == source["need"]["recent_craft_usage"]
    assert "craft_context" not in result["need"]
    assert result["recall_query_receipt"]["source_selection_digest"] == source["selection_digest"]


@pytest.mark.parametrize("field,value", [("mode", "DENY_ALL"), ("usage_scope", "PRODUCTION"), ("craft_candidate_review_version", "different")])
def test_book_scope_cannot_leak_into_other_knowledge_policies(field, value):
    source = selection()
    source["knowledge_access_policy"][field] = value
    source["selection_digest"] = _hash({k:v for k,v in source.items() if k != "selection_digest"})
    with pytest.raises(KernelError, match="CRAFT_CONTEXT_PROJECTION_DRIFT"):
        project_book_method_scope(source)


def test_short_literal_transport_is_lossless_and_legacy_encoding_stays_separate():
    literal = "A repeated short narrative condition. " * 4
    data = {"a": literal, "b": literal, "c": {"long_pointer_name" * 9: literal}}
    legacy, old_proof = compile_exact_context_references(data, structured_transport=True)
    projected, proof = compile_exact_context_references(data, structured_transport=True, short_literals=True)
    assert expand_exact_context_references(projected) == data
    assert legacy == data
    assert projected != legacy
    assert old_proof["transport_version"] == "provider-structured-exact-reference.v1"
    assert proof["transport_version"] == "provider-structured-exact-reference.v3"
