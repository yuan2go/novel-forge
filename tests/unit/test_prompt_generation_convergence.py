from __future__ import annotations

import hashlib
import json

import pytest

from novel_forge.modules.canon_graph.grounding import _bind_claim_location
from novel_forge.modules.chapter_authority.provider_output_contracts import (
    chapter_provider_output_schema,
    chapter_provider_output_schema_ref,
    validate_chapter_provider_output_against_schema,
)
from novel_forge.modules.chapter_authority.handlers import bind_quality_prose_evidence
from novel_forge.modules.chapter_authority.execution_gateway import _stage_semantic_contract_v3
from novel_forge.modules.chapter_authority.realization_composition import prose_from_output
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import validate_location


def test_single_scene_body_and_legacy_mismatch() -> None:
    result = {"scene_artifacts": [
        {"slot_id": "s1", "text": "她说：🌙", "used_fact_ids": []},
        {"slot_id": "s2", "text": "第二行。", "used_fact_ids": []},
    ]}
    validate_chapter_provider_output_against_schema(
        "draft", chapter_provider_output_schema("draft"), result,
    )
    assert prose_from_output(result) == "她说：🌙\n\n第二行。"
    with pytest.raises(KernelError, match="REALIZATION_INTEGRATION_DRIFT"):
        prose_from_output({**result, "text": "旧稿"})


def test_quote_binding_is_exact_and_ambiguous_quotes_fail_closed() -> None:
    text = "开头\n🌙她来了。\n尾声"
    quote = "🌙她来了。"
    located = validate_location({"quote": quote}, text)
    assert (located["start"], located["end"]) == (3, 8)
    claim = {"evidence_quote": quote}
    _bind_claim_location(claim, text)
    assert (claim["evidence_start"], claim["evidence_end"]) == (3, 8)
    with pytest.raises(KernelError, match="REVIEW_EVIDENCE_AMBIGUOUS"):
        validate_location({"quote": "重复"}, "重复\n重复")
    with pytest.raises(KernelError, match="REVIEW_EVIDENCE_INVALID"):
        validate_location({"quote": "旧稿"}, text)


def test_frozen_legacy_schema_keeps_old_body_and_location_contract() -> None:
    assert chapter_provider_output_schema_ref("draft", legacy_contract=True).endswith(":v2")
    assert chapter_provider_output_schema_ref("draft").endswith(":v3")
    old = chapter_provider_output_schema("draft", legacy_contract=True)
    new = chapter_provider_output_schema("draft")
    assert old["required"] == ["text", "scene_artifacts"]
    assert new["required"] == ["scene_artifacts"]
    old_location = chapter_provider_output_schema("review", legacy_contract=True)["properties"]["issues"]["items"]["properties"]["evidence"]
    new_location = chapter_provider_output_schema("review")["properties"]["issues"]["items"]["properties"]["evidence"]
    assert old_location["required"] == ["start", "end", "quote"]
    assert new_location["required"] == ["quote"]
    old_hashes = {
        "memo": "c3b8a7b5757bcff02134becf3885f2b4aa17d6bf6e0432a3a874012d2799d9c2",
        "draft": "5414ab021abdcffb7174743dd989ea78d9a069221bb13b1dcf6a84603f1db2ba",
        "review": "63119fdfd4c13fb0a5d6d9ec2b02726c996a02af859a481c58cf6ce6bae26b15",
        "revision": "ba2a7eb7c626758fa3685cc2007a43a89746bf55fb1d11507e892367c81cce64",
        "canon_extraction": "ccc587d49e56c3840b8bd3a8d3c71c8a1c61f9f47134bfbe7603aee40b637c50",
    }
    for stage, digest in old_hashes.items():
        encoded = json.dumps(chapter_provider_output_schema(stage, legacy_contract=True), sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == digest


def test_quality_evidence_uses_same_candidate_and_unique_quote() -> None:
    current = chapter_provider_output_schema("quality_longform")
    location_schema = current["properties"]["dimensions"]["items"]["properties"]["evidence_locations"]["items"]
    assert location_schema["required"] == ["quote", "claim"]
    bound = bind_quality_prose_evidence(
        [{"quote": "🌙照亮门边。", "claim": "The location is visible."}],
        text="第一行\n🌙照亮门边。", target_asset_version_id="candidate:v2",
    )
    assert (bound[0]["start"], bound[0]["end"]) == (4, 10)
    assert bound[0]["target_asset_version_id"] == "candidate:v2"
    with pytest.raises(KernelError, match="REVIEW_EVIDENCE_AMBIGUOUS"):
        bind_quality_prose_evidence(
            [{"quote": "重复", "claim": "Ambiguous."}],
            text="重复\n重复", target_asset_version_id="candidate:v2",
        )


def test_current_canon_instruction_matches_host_bound_payoff_and_quotes() -> None:
    contract = _stage_semantic_contract_v3("canon_extraction")
    assert "FULFILLED requires a typed payoff_evidence object" not in contract
    assert "set payoff_evidence to null" in contract
    assert "accepted revision visibly executes" not in contract
    assert "selected candidate visibly executes" in contract
    assert "chars:<start>-<end>" not in contract
