from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.realization_composition import (
    compile_realization_contract, integrate_realization, scoped_realization_schema,
    resolve_accepted_realization_sources,
)
from novel_forge.modules.chapter_authority.provider_output_contracts import chapter_provider_output_schema
from novel_forge.modules.command_kernel.errors import KernelError


def contract():
    plan = {"chapter": 2, "scene_plan": [
        {"scene_id": "one", "beats": [], "participants": ["a", "b"], "realization_capabilities": ["DIALOGUE", "ACTION"],
         "accessible_knowledge": [], "information_gain": ["local:seen"],
         "story_time": {"precision": "ORDERED", "timeline_id": "book", "start_ordinal": 4, "end_ordinal": 6}},
        {"scene_id": "two", "beats": [], "participants": ["a", "b"], "realization_capabilities": ["DIALOGUE"],
         "accessible_knowledge": ["local:seen"], "information_gain": ["local:future"]}],
        "character_participation": [{"character_id": "a", "known_fact_ids": []}, {"character_id": "b", "known_fact_ids": []}],
        "knowledge_boundaries": [{"layer": "CHARACTER_KNOWLEDGE", "subject_id": "a", "status": "KNOWN", "fact_id": "local:seen", "available_from_chapter": 2}],
        "disclosures": []}
    accepted = {"asset_version_id": "state:exact", "content_hash": "hash:exact", "facts": [
        {"source_ref": "accepted:observation", "actor_id": "a", "source_class": "ACCEPTED_ENTRY_KNOWLEDGE"},
        {"source_ref": "local:private_note", "actor_id": "a", "source_class": "ACCEPTED_OWN_STATE_EVIDENCE"}]}
    world = {"action": {"world_plan": {"preparation_schedule": [{"chapter_number": 2, "transition": {
        "actor_id": "b", "transition_id": "seen", "camera": "ON_CAMERA",
        "story_time": {"precision": "ORDERED", "timeline_id": "book", "start_ordinal": 5, "end_ordinal": 5}}}]}}}
    return compile_realization_contract(plan, {}, core_policy="continuous-scene.v1", information_policy="actor-source-scope.v1", accepted_sources=accepted, world_preparation=world)


def artifacts(c):
    return [{"slot_id": s["slot_id"], "text": "完整连续场景。", "used_fact_ids": [], "character_source_uses": []} for s in c["slots"]]


def test_continuous_scenes_preserve_accepted_actor_sources_and_own_action():
    c = contract()
    assert [s["slot_id"] for s in c["slots"]] == ["one:skeleton", "two:skeleton"]
    scope = c["slots"][0]["character_source_scopes"]
    assert scope["a"]["accepted_entry_refs"] == ["accepted:observation", "local:private_note"]
    assert "accepted:observation" not in scope["b"]["source_refs"]
    assert scope["b"]["own_planned_action_refs"] == ["local:seen"]
    assert "local:future" not in c["slots"][0]["accessible_knowledge"]
    assert "local:seen" in c["slots"][1]["character_source_scopes"]["a"]["source_refs"]
    assert c["accepted_sources"]["facts"][1]["source_class"] == "ACCEPTED_OWN_STATE_EVIDENCE"


@pytest.mark.parametrize("ref,actor", [("accepted:observation", "b"), ("local:private_note", "b"), ("local:future", "a"), ("invented:fact", "a")])
def test_foreign_private_future_or_invented_actor_sources_are_rejected(ref, actor):
    c = contract()
    rows = artifacts(c)
    rows[0]["used_fact_ids"] = [ref]
    rows[0]["character_source_uses"] = [{"character_id": actor, "used_fact_ids": [ref]}]
    with pytest.raises(KernelError, match="REALIZATION_EPISTEMIC_SCOPE_VIOLATION"):
        integrate_realization(contract=c, artifacts=rows, text="\n\n".join(r["text"] for r in rows))


def test_diagnostics_report_all_reference_and_type_defects_together():
    c = contract()
    rows = artifacts(c)
    rows[0]["used_fact_ids"] = ["future:one"]
    rows[1]["used_fact_ids"] = [1]
    rows[1]["character_source_uses"] = [{"character_id": "b", "used_fact_ids": ["accepted:observation"]}]
    with pytest.raises(KernelError) as error:
        integrate_realization(contract=c, artifacts=rows, text="\n\n".join(r["text"] for r in rows))
    assert all(code in str(error.value) for code in ["OUTSIDE_SCENE_SCOPE", "FACT_REFERENCE_TYPE_OR_DUPLICATE", "CHARACTER_SOURCE_SCOPE"])


def test_dynamic_schema_matches_host_contract_and_preserves_original():
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    c = contract()
    source = chapter_provider_output_schema("draft")
    old = deepcopy(source)
    schema = scoped_realization_schema(source, c)
    rows = artifacts(c)
    rows[0]["used_fact_ids"] = ["accepted:observation", "local:seen"]
    rows[0]["character_source_uses"] = [{"character_id": "a", "used_fact_ids": ["accepted:observation"]}, {"character_id": "b", "used_fact_ids": ["local:seen"]}]
    validate_chapter_provider_output_against_schema("draft", schema, {"scene_artifacts": rows})
    integrate_realization(contract=c, artifacts=rows, text="\n\n".join(r["text"] for r in rows))
    assert source == old
    rows[0]["character_source_uses"][1]["used_fact_ids"] = ["accepted:observation"]
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema("draft", schema, {"scene_artifacts": rows})


@pytest.mark.parametrize("change", ["hash", "book", "cursor", "permission", "revoked"])
def test_exact_accepted_source_binding_fails_closed(monkeypatch, change):
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    snapshot = {"contract_version": "story-state-snapshot-v2", "accepted_state_only": True, "project_id": "project", "book_id": "book", "accepted_through_chapter": 1, "current_state": {}}
    asset = SimpleNamespace(content=snapshot, content_hash="hash", asset_type="story_state_snapshot", lifecycle="ACTIVE", eligibility="ELIGIBLE", governance="CLEAR")
    context = {"context_manifest": {"accepted_boundary": {"story_state_snapshot_version": "state", "accepted_through_chapter": 1},
        "selected_inputs": [{"asset_version_id": "state", "allowed_use": "generation", "content_digest": "hash"}]},
        "production_input_manifest": {"selected_asset_versions": [{"asset_version_id": "state", "asset_type": "story_state_snapshot", "content_hash": "hash"}]}}
    request = SimpleNamespace(project_id="project", command={"book_id": "book"}, database_url="unused", require_input=lambda k: SimpleNamespace(content=context if k == "context_bundle" else {"chapter": 2, "character_participation": []}))
    monkeypatch.setattr(AuthorityAssetQuery, "require", lambda *a, **k: asset)
    assert resolve_accepted_realization_sources(request)["facts"] == []
    if change == "hash":
        asset.content_hash = "stale"
    elif change == "book":
        snapshot["book_id"] = "other"
    elif change == "cursor":
        snapshot["accepted_through_chapter"] = 2
    elif change == "permission":
        context["context_manifest"]["selected_inputs"][0]["allowed_use"] = "analysis"
    else:
        asset.lifecycle = "REVOKED"
    with pytest.raises(KernelError):
        resolve_accepted_realization_sources(request)


def test_scene_evidence_union_uses_only_declared_legal_actor_refs():
    from novel_forge.modules.chapter_authority.realization_composition import normalize_scene_source_union
    c, rows = contract(), artifacts(contract())
    rows[0]["character_source_uses"] = [{"character_id": "a", "used_fact_ids": ["accepted:observation"]}]
    original = deepcopy(rows)
    normalized, changes = normalize_scene_source_union(c, rows)
    assert rows == original
    assert normalized[0]["used_fact_ids"] == ["accepted:observation"]
    assert normalized[0]["text"] == rows[0]["text"]
    assert changes == [{"slot_id": "one:skeleton", "added_scene_refs": ["accepted:observation"]}]
    proof = integrate_realization(contract=c, artifacts=rows, text="\n\n".join(r["text"] for r in rows))
    assert proof["scene_artifacts"] == normalized
    assert proof["source_declaration_normalization"]["fact_mutation_allowed"] is False
    assert normalize_scene_source_union(c, normalized) == (normalized, [])


@pytest.mark.parametrize("change", ["actor", "private", "future", "duplicate_ref", "duplicate_actor", "illegal_scene", "slot_order"])
def test_union_never_repairs_illegal_or_ambiguous_identity_or_evidence(change):
    from novel_forge.modules.chapter_authority.realization_composition import normalize_scene_source_union
    c, rows = contract(), artifacts(contract())
    use = {"character_id": "a", "used_fact_ids": ["accepted:observation"]}
    rows[0]["character_source_uses"] = [use]
    if change == "actor":
        use["character_id"] = "foreign-book:a"
    elif change == "private":
        use["character_id"] = "b"
    elif change == "future":
        use["used_fact_ids"] = ["local:future"]
    elif change == "duplicate_ref":
        use["used_fact_ids"] *= 2
    elif change == "duplicate_actor":
        rows[0]["character_source_uses"].append(deepcopy(use))
    elif change == "illegal_scene":
        rows[0]["used_fact_ids"] = ["invented:fact"]
    else:
        rows.reverse()
    assert normalize_scene_source_union(c, rows) == (rows, [])
    with pytest.raises(KernelError):
        integrate_realization(contract=c, artifacts=rows, text="\n\n".join(r["text"] for r in rows))


def test_receipt_only_draft_definition_cannot_dispatch_without_journal(monkeypatch):
    from novel_forge.modules.chapter_authority.handlers import _invoke_with_known_receipt
    from novel_forge.modules.chapter_authority import receipt_recovery
    monkeypatch.setattr(receipt_recovery, "consume_known_draft_receipt", lambda request: None)
    provider = SimpleNamespace(invoke=lambda *a, **k: pytest.fail("fresh dispatch from receipt-only successor"))
    request = SimpleNamespace(effective_definition_version="3.10.1", database_url="unused")
    with pytest.raises(KernelError, match="DRAFT_RECOVERY_JOURNAL_REQUIRED"):
        _invoke_with_known_receipt(provider, request, stage="draft", payload={})
