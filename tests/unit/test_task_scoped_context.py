from dataclasses import replace

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate
from novel_forge.modules.context_builder.reality_projection import project_role_context
from novel_forge.modules.context_builder.task_compression import compile_task_context
from novel_forge.modules.context_builder.task_context import task_reality_workset
from novel_forge.modules.chapter_authority.provider_views import build_task_narrative_projection, project_narrative_state_facts

BOUNDARY = {"accepted_through_chapter": 20, "story_state_snapshot_version": "state:20", "canon_snapshot_version": "canon:20"}
TASK = {"stage": "draft", "chapter": 21, "accepted_boundary": BOUNDARY, "character_ids": ["hero"], "memo_fingerprint": "sha256:" + "b" * 64, "preserve_quotes": ["You owe me one joke."]}


def candidate(kind="chapter_episodic_summary", text="You owe me one joke.\n\nAn unrelated old banquet.\n\nAnother irrelevant old banquet.", **kw):
    return ContextCandidate("source:1", kind, "project", 1, retrieval_reasons=kw.pop("retrieval_reasons", ("required_task_related_history",)), book_id="book", content_digest="sha256:" + "a" * 64, accepted_boundary=BOUNDARY, safe_summary=text, compression_method="none", provenance={"authority_asset_version_id": "source:1"}, **kw)


def compile_one(source, *, budget=512000, model_call=None):
    return compile_task_context([source], task=TASK, token_budget=budget, required_asset_types=(), model_call=model_call, compression_input_tokens=2048)


def test_fast_path_never_calls_semantic_model_and_retains_exact_sources():
    original = candidate()
    result, receipt = compile_one(original, model_call=lambda *args: pytest.fail("fast path called a model"))
    assert result[0].safe_summary == original.safe_summary
    assert receipt["fast_path"] and receipt["system_context_window_tokens"] == 512000
    assert receipt["token_accounting"] == "utf8-byte-upper-bound.v1"
    assert receipt["source_bindings"][0]["content_hash"] == original.content_digest


def test_independent_missing_voice_restores_original_local_unit_once():
    calls = []
    source = candidate(text="A relevant consequence.\n\nYou owe me one joke.\n\n" + "The unrelated banquet. " * 30)

    def model(stage, task):
        from novel_forge.modules.chapter_authority.context_compression_provider import context_compression_task_view
        view = context_compression_task_view(stage, {"context_compression_task": task})
        assert view["memo_fingerprint"] == TASK["memo_fingerprint"]
        calls.append((stage, task))
        if stage == "context_compress":
            return {"selected_unit_ids": ["text:0"]}
        return {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}

    result, receipt = compile_one(source, budget=180, model_call=model)
    assert result[0].safe_summary == "A relevant consequence.\n\nYou owe me one joke."
    assert [stage for stage, _ in calls] == ["context_compress", "context_fidelity"]
    assert receipt["compression_trace"][0]["forward_check"] == "EXACT_HOST_SOURCE_UNITS"
    assert "text:1" in calls[1][1]["selected_unit_ids"]
    assert source.safe_summary.endswith("The unrelated banquet. " * 30)


def test_missing_causal_unit_backfill_and_failed_judge_fail_closed():
    source = candidate(text="The promise remained unmet.\n\nShe did not know the condition.\n\n" + "Banquet. " * 100)
    checks = []

    def model(stage, task):
        if stage == "context_compress":
            return {"selected_unit_ids": ["text:0"]}
        checks.append(task)
        return {"supported": True, "coverage_complete": "text:1" in task["selected_unit_ids"], "missing_unit_ids": [] if "text:1" in task["selected_unit_ids"] else ["text:1"], "distorted_unit_ids": []}

    result, receipt = compile_one(source, budget=160, model_call=model)
    assert result[0].safe_summary == "The promise remained unmet.\n\nShe did not know the condition."
    assert len(checks) == 2
    assert receipt["compression_trace"][0]["restored_unit_ids"] == ["text:1"]

    def unconfirmed(stage, task):
        return {"selected_unit_ids": ["text:0"]} if stage == "context_compress" else {"supported": False, "coverage_complete": False, "missing_unit_ids": [], "distorted_unit_ids": []}

    with pytest.raises(KernelError, match="Fidelity|faithful restored"):
        compile_one(source, budget=160, model_call=unconfirmed)


@pytest.mark.parametrize("kind", ["draft_chapter", "draft_version", "review_issue", "story_state_snapshot"])
def test_precise_review_revision_and_required_state_never_compress(kind):
    with pytest.raises(KernelError, match="necessary exact task content"):
        compile_one(candidate(kind, text="Exact original revision " * 100), budget=100, model_call=lambda *args: pytest.fail("protected source compressed"))


def test_compressor_cannot_invent_identity_and_never_recompresses_a_summary():
    source = candidate(text="Original source " * 50)
    with pytest.raises(KernelError, match="only distinct host-bound"):
        compile_one(source, budget=100, model_call=lambda *args: {"selected_unit_ids": ["invented"]})
    compressed = replace(source, context_class="COMPRESSIBLE", compression_trace=({"method": "old-compressor", "source_asset_version_id": "source:1", "source_content_hash": source.content_digest},))
    with pytest.raises(KernelError, match="qualified controlled compressor"):
        compile_one(compressed, budget=100, model_call=lambda *args: pytest.fail("summary of summary"))


def test_source_version_or_accepted_boundary_invalidates_reuse():
    source = candidate()
    _, first = compile_one(source)
    _, newer = compile_one(replace(source, source_revision="source-revision:2", content_digest="sha256:" + "b" * 64))
    assert first["receipt_hash"] != newer["receipt_hash"]
    with pytest.raises(KernelError, match="frozen task boundary"):
        compile_one(replace(source, accepted_boundary={**BOUNDARY, "accepted_through_chapter": 19}))


def event(identity, kind, state, chapter, causes=()):
    return {"event_id": identity, "state_kind": kind, "identity": {"entity_key": state.get("obligation_id", identity)}, "coordinate": {"source_chapter": chapter}, "mutation": {"payload": {**state, **({"world_transition": {"cause_refs": list(causes)}} if causes else {})}}}


def reality(history_count=0):
    events = [event("cause", "resource_state", {"balance": 1, "condition": "only if the debt is repaid"}, 1), event("plant", "narrative_obligation", {"obligation_id": "old-promise", "status": "OPEN"}, 2, ["cause"]), event("advance", "narrative_obligation", {"obligation_id": "old-promise", "status": "OPEN", "priority": "LOW"}, 19)]
    unrelated = [event(f"unrelated:{i}", "canon_fact", {"predicate": "accepted_revision_digest", "value": str(i)}, 10) for i in range(history_count)]
    return {"project_id": "project", "book_id": "book", "revision_id": "revision:20", "chapter_number": 20, "events": events + unrelated, "foundation_cause_refs": [], "current_state": {"narrative_obligation": [{"entity_key": "old-promise", "source_event_id": "advance", "state": events[2]["mutation"]["payload"]}], "canon_fact": [{"entity_key": e["identity"]["entity_key"], "source_event_id": e["event_id"], "state": e["mutation"]["payload"]} for e in unrelated]}}


def test_far_referenced_promise_includes_planting_latest_advance_and_causal_predecessor():
    rows, receipt = task_reality_workset(reality(2000), task={"chapter": 21, "obligation_refs": ["old-promise"]}, role_kinds=("narrative_obligation", "resource_state", "canon_fact"))
    assert {row[2]["source_event_id"] for row in rows} == {"cause", "plant", "advance"}
    assert receipt["required_event_ids"] == ["advance", "cause", "plant"]


def test_role_projection_does_not_promote_all_readable_state_to_required():
    view = project_role_context(reality=reality(2000), role="DIRECTOR", token_budget=4096, task={"chapter": 21, "obligation_refs": ["old-promise"]})
    assert len(view["selection"]) == 3
    assert view["task_workset"]["full_current_state_count"] == 2001
    changed = project_role_context(reality=reality(3000), role="DIRECTOR", token_budget=4096, task={"chapter": 21, "obligation_refs": ["unrelated-promise"]})
    assert not changed["task_workset"]["required_event_ids"]
    with pytest.raises(KernelError, match="cannot be omitted"):
        project_role_context(reality=reality(), role="DIRECTOR", token_budget=10, task={"chapter": 21, "obligation_refs": ["old-promise"]})


def test_required_missing_or_future_dependency_blocks_before_model():
    state = reality()
    with pytest.raises(KernelError, match="unavailable"):
        task_reality_workset(state, task={"chapter": 21}, required_event_ids=("missing",), role_kinds=("resource_state",))
    state["events"][0]["coordinate"]["source_chapter"] = 22
    with pytest.raises(KernelError, match="accepted boundary"):
        task_reality_workset(state, task={"obligation_refs": ["old-promise"]}, role_kinds=("narrative_obligation", "resource_state"))


def test_new_draft_projection_removes_old_fact_count_cap_but_preserves_epistemic_scope():
    projection = build_task_narrative_projection({"chapter": 21, "cast": ["hero"], "scene_plan": [{"focalization": "hero", "accessible_knowledge": ["known"]}]}, task_scoped=True)
    facts = [{"state_kind": "character_state", "source_event_id": f"state:{i}", "entity_key": f"hero:{i}", "state": {"character_id": "hero", "condition": "not yet", "value": i}} for i in range(80)]
    facts += [{"state_kind": "character_knowledge", "source_event_id": "secret", "entity_key": "hero:secret", "state": {"character_id": "hero", "fact_id": "secret", "status": "KNOWN"}}]
    assert len(project_narrative_state_facts(facts, projection=projection, chapter=21)) == 80
    assert len(project_narrative_state_facts(facts, projection=build_task_narrative_projection({"chapter": 21, "cast": ["other"]}, task_scoped=True), chapter=21)) == 0


def test_frozen_initial_state_has_source_binding_without_fabricated_accepted_event():
    state = reality()
    state.update(chapter_number=0, baseline_kind="APPROVED_FOUNDATION", revision_id="foundation:hash", events=[], initial_state_binding={"asset_version_id": "initial:1", "content_hash": "original-hash"})
    state["current_state"] = {"narrative_obligation": [{"entity_key": "obligation_id=initial-promise", "state": {"status": "OPEN", "priority": "HIGH", "condition": "only if approved"}}]}
    view = project_role_context(reality=state, role="DIRECTOR", token_budget=4096, task={"chapter": 1})
    fact = view["selection"][0]
    assert fact["source_event_id"] == ""
    assert fact["evidence_role"] == "FROZEN_INITIAL_STATE"
    assert fact["source_binding"]["content_hash"] == "original-hash"
    assert fact["state"]["condition"] == "only if approved"
    assert view["task_workset"]["selected_event_ids"] == []
    assert state["events"] == [] and "source_identity" not in state["current_state"]["narrative_obligation"][0]


def test_task_fact_projection_preserves_explicit_fact_alias_and_cross_source_cause():
    from novel_forge.modules.context_builder.task_context import project_task_state_facts
    from novel_forge.modules.context_builder.task_compression import validate_task_dependencies
    consequence = {"state_kind": "canon_fact", "source_event_id": "event:2", "state": {"fact_id": "explicit:fact", "world_transition": {"cause_refs": ["event:1"]}}}
    predecessor = {"state_kind": "resource_state", "source_event_id": "event:1", "state": {"condition": "only if repaid"}}
    projection = {"required_event_refs": ["explicit:fact"], "contract_version": "chapter-task-narrative-projection-v2"}
    selected = project_task_state_facts([consequence], projection=projection, chapter=21)
    assert selected == [consequence]
    first = candidate(structured_facts=tuple(selected))
    second = replace(candidate(structured_facts=(predecessor,)), asset_version_id="source:2")
    assert validate_task_dependencies([first, second], task=TASK)["coverage"] == "COMPLETE"
    with pytest.raises(KernelError, match="event:1"):
        compile_one(first, model_call=lambda *args: pytest.fail("missing dependency reached model"))


def test_compressor_does_not_disclose_internal_quality_only_fact():
    internal = {"provider_visibility": "INTERNAL_QUALITY_ONLY", "secret": "host diagnostic"}
    source = candidate(text="Necessary voice.\n\n" + "Unrelated banquet. " * 60, structured_facts=(internal,))
    def model(stage, chunk):
        assert "host diagnostic" not in str(chunk)
        return {"selected_unit_ids": ["text:0"]} if stage == "context_compress" else {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}
    result, _ = compile_one(source, budget=180, model_call=model)
    assert internal in result[0].structured_facts


def test_duplicate_representations_take_deterministic_fast_path_before_budget():
    source = candidate(text="Required shared history. " * 30)
    duplicate = replace(source, asset_version_id="source:2", source_identity=source.asset_version_id)
    source = replace(source, source_identity=source.asset_version_id)
    result, receipt = compile_task_context([duplicate, source], task=TASK, token_budget=1000, required_asset_types=(), model_call=lambda *args: pytest.fail("duplicate triggered compressor"), compression_input_tokens=2048)
    assert receipt["fast_path"] and len(receipt["deduplications"]) == 1
    assert len([item for item in result if not (item.provenance or {}).get("task_excluded")]) == 1


def test_unchanged_initial_fact_keeps_exact_source_identity_after_acceptance():
    from novel_forge.modules.narrative_state.reality import narrative_hash
    initial = {"status": "OPEN", "priority": "HIGH", "condition": "not before approval"}
    source = {"state_kind": "narrative_obligation", "entity_key": "initial-promise", "state_hash": narrative_hash(initial), "source_binding": {"asset_version_id": "initial:1", "content_hash": "original"}}
    state = reality()
    state.update(baseline_kind="ACCEPTED_REALITY", initial_state_sources=[source])
    state["current_state"] = {"narrative_obligation": [{"entity_key": "initial-promise", "state": initial}]}
    rows, _ = task_reality_workset(state, task={"chapter": 21}, role_kinds=("narrative_obligation",))
    assert rows[0][2]["source_binding"] == source["source_binding"]
    state["current_state"]["narrative_obligation"][0]["state"] = {**initial, "condition": "changed without source"}
    with pytest.raises(KernelError, match="exact frozen initial source"):
        task_reality_workset(state, task={"chapter": 21}, role_kinds=("narrative_obligation",))


def test_unmatched_auxiliary_overflow_is_removed_before_model():
    source = candidate(text="Unrelated banquet. " * 100, retrieval_reasons=())
    result, receipt = compile_one(source, budget=100, model_call=lambda *args: pytest.fail("unrelated history triggered paid call"))
    assert receipt["fast_path"] and receipt["after_estimated_tokens"] == 0
    assert result[0].provenance["task_excluded"]


def test_serialized_accepted_scenes_are_semantic_units_with_original_source_paths():
    import json
    original = {"chapter": 3, "scene_artifacts": [{"scene_id": "promise", "text": "You owe me one joke."}, {"scene_id": "banquet", "text": "Unrelated banquet. " * 200}], "provider_evidence": {"private_transport": "host-only"}}
    source = candidate(text=json.dumps(original, ensure_ascii=False))
    calls = []
    def model(stage, chunk):
        assert "private_transport" not in str(chunk["units"])
        calls.append(chunk)
        return {"selected_unit_ids": ["json:scene_artifacts:0"]} if stage == "context_compress" else {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}
    result, receipt = compile_task_context([source], task=TASK, token_budget=350, required_asset_types=(), model_call=model, compression_input_tokens=8192)
    assert "You owe me one joke." in result[0].safe_summary and "Unrelated banquet" not in result[0].safe_summary
    trace = receipt["compression_trace"][0]
    assert any(unit["source_path"] == ["scene_artifacts", 0] and unit["kind"] == "SOURCE_SCENE_OR_CAUSAL_UNIT" for unit in trace["source_units"])
    assert source.safe_summary == json.dumps(original, ensure_ascii=False)


def test_final_task_receipt_is_included_before_context_fingerprint_freezes():
    from novel_forge.modules.context_builder.domain import build_authority_context_bundle, replay_context_bundle
    source = candidate(kind="chapter_plan", text="Exact plan.", required=True)
    receipt = {"policy_version": "task-scoped-context.v1", "task_hash": "task:1"}
    bundle = build_authority_context_bundle(project_id="project", book_id="book", stage="draft", created_by_operation_id="operation", context_profile_version="draft-context-profile-v4", token_budget=1000, candidates=[replace(source, estimated_tokens=50)], task_context_receipt=receipt)
    assert replay_context_bundle(bundle)["status"] == "MATCH"
    bundle["context_manifest"]["task_context_receipt"]["task_hash"] = "mutated"
    with pytest.raises(ValueError, match="REPLAY_MISMATCH"):
        replay_context_bundle(bundle)


def test_same_source_required_projection_union_preserves_both_aliases():
    from novel_forge.modules.chapter_authority.handlers import merge_task_retrieval_projections
    documents = [{"retrieval_document_id": str(i), "source_content_hash": "original", "safe_summary": f"original scene {i}", "metadata": {"structured_facts": [{"source_event_id": f"event:{i}", "state": {"fact_id": f"fact:{i}"}}]}, "task_dependency_matched_refs": [f"fact:{i}"], "retrieval_reasons": ["required_task_dependency"]} for i in (1, 2)]
    merged = merge_task_retrieval_projections({"content_hash": "original", "structured_facts": [], "safe_summary": ""}, documents)
    assert len(merged["structured_facts"]) == 2 and merged["task_dependency_matched_refs"] == ["fact:1", "fact:2"]
    with pytest.raises(KernelError, match="exact frozen content hash"):
        merge_task_retrieval_projections({"content_hash": "changed"}, documents)
