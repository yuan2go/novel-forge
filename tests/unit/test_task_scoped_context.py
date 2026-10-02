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


def background_reality(unrelated_count=0):
    def background(identity, chapter, key="world_state_id=inquiry", causes=()):
        row = event(identity, "world_state", {"fact_origin": {"kind": "GOVERNED_BACKGROUND"}, "status": "OPEN"}, chapter)
        row["identity"]["entity_key"] = key
        row["mutation"]["payload"]["world_transition"] = {"payload_json": __import__("json").dumps({"cause_refs": list(causes)})}
        return row
    events = [background("plant", 1, causes=["cause"]), background("middle", 10), background("latest", 20), event("cause", "resource_state", {"condition": "only after payment"}, 1)]
    events += [background(f"irrelevant:{index}", 19, f"world_state_id=other:{index}") for index in range(unrelated_count)]
    return {"project_id": "project", "book_id": "book", "revision_id": "revision:20", "chapter_number": 20, "events": events, "foundation_cause_refs": [], "current_state": {"world_state": [{"entity_key": row["identity"]["entity_key"], "source_event_id": row["event_id"], "state": row["mutation"]["payload"]} for row in events if row["state_kind"] == "world_state" and row["event_id"] not in {"plant", "middle"}]}}


def test_required_entity_retains_unrevealed_planting_without_restoring_all_history():
    source = background_reality(3000)
    rows, receipt = task_reality_workset(source, task={"chapter": 21, "state_entity_refs": ["world_state_id=inquiry"]}, role_kinds=("world_state", "resource_state"), auxiliary_limit=0)
    assert {row[2]["source_event_id"] for row in rows} == {"plant", "latest", "cause"}
    assert receipt["required_event_ids"] == ["cause", "latest", "plant"]
    assert source["events"][0]["coordinate"]["source_chapter"] == 1
    unrelated, receipt = task_reality_workset(source, task={"chapter": 21}, role_kinds=("world_state", "resource_state"), auxiliary_limit=1)
    assert len(unrelated) == 1 and not receipt["required_event_ids"]
    assert all(row[3] != "UNDISCLOSED_BACKGROUND_PLANTING_OR_ADVANCE" for row in unrelated)


@pytest.mark.parametrize("mode,retained", [("CONFIRM", False), ("HINT", True), ("PARTIAL", True), ("MISDIRECT", True), ("WITHHOLD", True)])
def test_only_reader_confirmation_releases_historical_disclosure_requirement(mode, retained):
    source = background_reality()
    source["current_state"]["reader_knowledge"] = [{"entity_key": "fact_id=plant", "source_event_id": "knowledge", "state": {"fact_id": "plant", "status": "KNOWN"}}]
    source["current_state"]["disclosure_event"] = [{"entity_key": "disclosure_id=plant", "source_event_id": "disclosure", "state": {"fact_id": "plant", "audience": "READER", "disclosure_mode": mode}}]
    rows, receipt = task_reality_workset(source, task={"state_entity_refs": ["world_state_id=inquiry"]}, role_kinds=("world_state", "resource_state"), auxiliary_limit=0)
    assert ("plant" in receipt["required_event_ids"]) is retained
    assert "middle" not in receipt["required_event_ids"] if retained else "middle" in receipt["required_event_ids"]
    assert all(row[0] not in {"reader_knowledge", "disclosure_event"} for row in rows)


@pytest.mark.parametrize("status,mode", [("SUSPECTED", "CONFIRM"), ("MISDIRECTED", "CONFIRM"), ("KNOWN", "HINT"), ("KNOWN", "MISDIRECT")])
def test_past_confirmation_cannot_override_current_reader_uncertainty(status, mode):
    source = background_reality()
    source["current_state"]["reader_knowledge"] = [{"entity_key": "fact_id=plant", "source_event_id": "knowledge", "state": {"fact_id": "plant", "status": status}}]
    source["current_state"]["disclosure_event"] = [{"entity_key": f"disclosure_id={index}", "source_event_id": f"disclosure:{index}", "state": {"fact_id": "plant", "audience": "READER", "disclosure_mode": value}} for index, value in enumerate(("CONFIRM", mode))]
    _, receipt = task_reality_workset(source, task={"state_entity_refs": ["world_state_id=inquiry"]}, role_kinds=("world_state", "resource_state"), auxiliary_limit=0)
    assert "plant" in receipt["required_event_ids"]


def test_historical_entity_closure_respects_role_and_future_boundary():
    source = background_reality()
    with pytest.raises(KernelError, match="outside the role"):
        task_reality_workset(source, task={"state_entity_refs": ["world_state_id=inquiry"]}, role_kinds=("world_state",), auxiliary_limit=0)
    source["events"][3]["coordinate"]["source_chapter"] = 21
    with pytest.raises(KernelError, match="accepted boundary"):
        task_reality_workset(source, task={"state_entity_refs": ["world_state_id=inquiry"]}, role_kinds=("world_state", "resource_state"), auxiliary_limit=0)


@pytest.mark.parametrize("field", ["required_event_ids", "required_event_refs", "required_source_event_ids"])
def test_typed_required_events_fail_closed_when_omitted_or_denied(field):
    source = background_reality(300)
    task = {"planning_window": [{"content": {field: ["cause"]}}]}
    rows, receipt = task_reality_workset(source, task=task, role_kinds=("resource_state",), auxiliary_limit=0)
    assert [row[2]["source_event_id"] for row in rows] == ["cause"]
    assert receipt["required_event_ids"] == ["cause"]
    with pytest.raises(KernelError, match="outside the role"):
        task_reality_workset(source, task=task, role_kinds=("world_state",), auxiliary_limit=0)
    source["events"] = [row for row in source["events"] if row["event_id"] != "cause"]
    with pytest.raises(KernelError, match="unavailable"):
        task_reality_workset(source, task=task, role_kinds=("resource_state",), auxiliary_limit=0)


@pytest.mark.parametrize("malformed", [{"x": "cause"}, [{}], [None], [""], [["cause"]], 1, "cause"])
def test_typed_required_event_shape_cannot_silently_erase_dependencies(malformed):
    from novel_forge.modules.context_builder.task_context import required_task_event_ids
    with pytest.raises(KernelError, match="collection of exact"):
        required_task_event_ids({"planning_window": [{"content": {"required_event_refs": malformed}}]})
    assert required_task_event_ids({"required_event_refs": []}) == set()


def test_world_task_selectors_use_frozen_hard_predicates_and_preserve_legacy():
    from novel_forge.modules.context_builder.task_context import world_task_scope
    task = world_task_scope(chapter=21, intent={}, planning_window=[], world_foundation={"rules": [
        {"enforcement": "HARD", "predicate": {"entity_key": "world_state_id=inquiry"}},
        {"enforcement": "SOFT_CAUSAL", "predicate": {"entity_key": "world_state_id=other:0"}},
    ]})
    rows, receipt = task_reality_workset(background_reality(1), task=task, role_kinds=("world_state", "resource_state"), auxiliary_limit=0)
    assert receipt["required_event_ids"] == ["cause", "latest", "plant"]
    assert {row[2]["source_event_id"] for row in rows} == {"cause", "latest", "plant"}


def test_directed_world_sources_fetch_explicit_cause_outside_recent_history(monkeypatch):
    from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
    from novel_forge.modules.context_builder.task_context import required_task_event_ids

    source = background_reality(300)
    source["book_run_id"] = "book-run"
    original = source["events"]
    source["events"] = original[-128:]
    assert all(row["event_id"] != "cause" for row in source["events"])
    class Cursor:
        def execute(self, query, parameters):
            assert "authority_book_acceptance_lineage" in query
            assert parameters[2:4] == ["book-run", 20]
        def fetchall(self):
            return []
    repository = NarrativeRealityRepository(Cursor())
    calls = []
    def exact_sources(**scope):
        assert scope["book_run_id"] == "book-run" and scope["through_chapter"] == 20
        calls.append(scope["event_ids"])
        return [row for row in original if row["event_id"] in scope["event_ids"]]
    monkeypatch.setattr(repository, "event_sources", exact_sources)
    requested = tuple(required_task_event_ids({"planning_window": [{"content": {"required_event_refs": ["cause"]}}]}))
    result = repository.task_background_sources(reality=source, entity_keys=(), required_event_ids=requested)
    assert [row["event_id"] for row in result] == ["cause"]
    assert calls == [("cause",)]
    with pytest.raises(KernelError, match="unavailable"):
        repository.task_background_sources(reality=source, entity_keys=(), required_event_ids=("missing",))


def test_necessary_world_closure_host_bound_blocks_instead_of_truncating():
    source = background_reality()
    source["events"] = [event(f"depth:{index}", "resource_state", {}, 1, [f"depth:{index - 1}"] if index else ()) for index in range(33)]
    source["current_state"] = {}
    with pytest.raises(KernelError, match="explicit host bound"):
        task_reality_workset(source, task={"required_event_refs": ["depth:32"]}, role_kinds=("resource_state",), auxiliary_limit=0)
    from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
    with pytest.raises(KernelError, match="explicit host bound"):
        NarrativeRealityRepository(None).task_background_sources(reality=source, entity_keys=tuple(("world_state", f"world:{index}") for index in range(2049)), required_event_ids=())


def test_serialized_local_world_cause_binds_exact_same_chapter_batch():
    source = background_reality()
    predecessor = event("local:accepted", "resource_state", {"causal_batch": {"local_id": "paid"}}, 20)
    unrelated_prior = event("local:old", "resource_state", {"causal_batch": {"local_id": "paid"}}, 1)
    source["events"][2]["mutation"]["payload"]["world_transition"] = {"payload_json": __import__("json").dumps({"cause_refs": ["local:paid"]})}
    source["events"] = [source["events"][2], predecessor, unrelated_prior]
    source["current_state"] = {}
    rows, receipt = task_reality_workset(source, task={"required_event_refs": ["latest"]}, role_kinds=("world_state", "resource_state"), auxiliary_limit=0)
    assert receipt["required_event_ids"] == ["latest", "local:accepted"]
    assert {row[2]["source_event_id"] for row in rows} == {"latest", "local:accepted"}


@pytest.mark.parametrize("kind", ["world_state", "narrative_obligation"])
@pytest.mark.parametrize("ordered", [True, False])
def test_same_chapter_history_uses_frozen_entity_versions_and_retains_ambiguous_originals(kind, ordered):
    source = background_reality()
    records = []
    for identity, version in [("z:plant", 1), ("a:middle", 2), ("m:latest", 3)]:
        row = event(identity, kind, {"fact_origin": {"kind": "GOVERNED_BACKGROUND"}, "obligation_id": "old-promise", "status": "OPEN"}, 20)
        row["identity"]["entity_key"] = "old-promise" if kind == "narrative_obligation" else "world_state_id=inquiry"
        row["version"] = {"event": 3, "entity": version if ordered else 1}
        records.append(row)
    source["events"] = [records[2], records[0], records[1]]
    source["current_state"] = {kind: [{"entity_key": records[2]["identity"]["entity_key"], "source_event_id": "m:latest", "state": records[2]["mutation"]["payload"]}]}
    task = {"obligation_refs": ["old-promise"]} if kind == "narrative_obligation" else {"state_entity_refs": ["world_state_id=inquiry"]}
    rows, receipt = task_reality_workset(source, task=task, role_kinds=(kind,), auxiliary_limit=0)
    assert set(receipt["required_event_ids"]) == ({"z:plant", "m:latest"} if ordered else {"z:plant", "a:middle", "m:latest"})
    assert {row[2]["source_event_id"] for row in rows} == set(receipt["required_event_ids"])


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


@pytest.mark.parametrize("task,state,selected", [
    ({"obligation_refs": ["old-promise"]}, {"status": "OPEN", "priority": "LOW"}, True),
    ({"required_event_refs": ["advance"]}, {"status": "OPEN", "priority": "LOW"}, True),
    ({"character_ids": ["hero"]}, {"status": "OPEN", "priority": "LOW", "linked_character_ids": ["hero"]}, True),
    ({"arc_refs": ["arc:1"]}, {"status": "OPEN", "priority": "LOW", "linked_arc_ids": ["arc:1"]}, True),
    ({}, {"status": "OPEN", "priority": "HIGH"}, True),
    ({}, {"status": "OPEN", "target_window": {"status": "SCHEDULED", "to_chapter": 21}}, True),
    ({}, {"status": "OPEN", "priority": "LOW"}, False),
    ({}, {"status": "FULFILLED", "priority": "HIGH"}, False),
])
def test_required_source_entities_match_projection_for_referenced_and_due_obligations(task, state, selected):
    from novel_forge.modules.context_builder.task_context import required_background_entities
    source = reality()
    source["current_state"]["narrative_obligation"][0]["state"] = {"obligation_id": "old-promise", **state}
    scope = {"chapter": 21, **task}
    assert (("narrative_obligation", "old-promise") in required_background_entities(source, scope, ("narrative_obligation",))) is selected
    assert not required_background_entities(source, scope, ("canon_fact",))


def initial_alias_reality():
    from novel_forge.modules.narrative_state.reality import narrative_hash
    source = background_reality()
    source["events"][2]["mutation"]["payload"]["world_transition"] = {"cause_refs": ["original-observation"]}
    state = {"character_id": "hero", "fact_id": "inquiry", "status": "KNOWN", "condition": "only after payment"}
    source["events"] = [source["events"][2]]
    source["current_state"] = {}
    source["initial_state_sources"] = [{"state_kind": "character_knowledge", "entity_key": "character_id=hero|fact_id=inquiry", "source_event_id": "original-observation", "state": state, "state_hash": narrative_hash(state), "source_binding": {"asset_version_id": "approved-initial:1", "content_hash": "sha256:" + "c" * 64}}]
    return source


def test_initial_observation_dependency_retains_exact_original_binding_without_faking_acceptance():
    source = initial_alias_reality()
    rows, receipt = task_reality_workset(source, task={"required_event_refs": ["latest"]}, role_kinds=("world_state", "character_knowledge"), auxiliary_limit=0)
    original = next(row for row in rows if row[2]["source_event_id"] == "original-observation")
    assert original[0] == "character_knowledge" and original[3] == "FROZEN_INITIAL_STATE"
    assert original[2]["state"] == source["initial_state_sources"][0]["state"]
    assert original[2]["source_binding"] == source["initial_state_sources"][0]["source_binding"]
    assert receipt["required_event_ids"] == ["latest", "original-observation"]
    assert not any(event["event_id"] == "original-observation" for event in source["events"])
    view = project_role_context(reality=source, role="DIRECTOR", token_budget=4096, task={"required_event_refs": ["latest"]})
    fact = next(item for item in view["selection"] if item["source_event_id"] == "original-observation")
    assert fact["source_binding"] == original[2]["source_binding"]
    assert fact["evidence_role"] == "FROZEN_INITIAL_STATE"
    assert view["task_workset"]["selected_event_ids"] == ["latest"]
    assert view["task_workset"]["initial_source_ids"] == ["original-observation"]
    with pytest.raises(KernelError, match="outside the role"):
        task_reality_workset(source, task={"required_event_refs": ["latest"]}, role_kinds=("world_state",), auxiliary_limit=0)


@pytest.mark.parametrize("fault", ["hash", "binding", "ambiguous", "unknown_alias"])
def test_initial_observation_does_not_bypass_exact_identity_or_state_validation(fault):
    source = initial_alias_reality()
    original = source["initial_state_sources"][0]
    if fault == "hash":
        original["state"]["condition"] = "without payment"
    elif fault == "binding":
        original["source_binding"] = {}
    elif fault == "ambiguous":
        source["initial_state_sources"].append({**original, "entity_key": "another-entity"})
    else:
        source["events"][0]["mutation"]["payload"]["world_transition"]["cause_refs"] = ["original-observation:unknown"]
    with pytest.raises(KernelError):
        task_reality_workset(source, task={"required_event_refs": ["latest"]}, role_kinds=("world_state", "character_knowledge"), auxiliary_limit=0)


@pytest.mark.parametrize("location", ["entry", "state", "event", "event_state"])
def test_task_workset_never_promotes_internal_quality_to_story_input(location):
    source = reality()
    entry = source["current_state"]["narrative_obligation"][0]
    if location in {"entry", "state"}:
        (entry if location == "entry" else entry["state"])["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
        rows, receipt = task_reality_workset(source, task={"obligation_refs": ["old-promise"]}, role_kinds=("narrative_obligation", "resource_state"), auxiliary_limit=0)
        assert not rows and not receipt["required_event_ids"]
    else:
        plant = source["events"][1]
        (plant if location == "event" else plant["mutation"]["payload"])["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
        with pytest.raises(KernelError, match="outside the role"):
            task_reality_workset(source, task={"obligation_refs": ["old-promise"]}, role_kinds=("narrative_obligation", "resource_state"), auxiliary_limit=0)


def test_task_fact_projection_rejects_exact_private_alias_and_omits_optional_private_fact():
    from novel_forge.modules.context_builder.task_context import project_task_state_facts
    fact = {"state_kind": "world_rule", "source_event_id": "private", "state": {"provider_visibility": "INTERNAL_QUALITY_ONLY", "condition": "private evaluator guidance"}}
    assert project_task_state_facts([fact], projection={"contract_version": "chapter-task-narrative-projection-v2"}, chapter=21) == []
    with pytest.raises(KernelError, match="Provider read scope"):
        project_task_state_facts([fact], projection={"required_event_refs": ["private"], "contract_version": "chapter-task-narrative-projection-v2"}, chapter=21)


def test_initial_dependency_cannot_erase_original_private_scope():
    source = initial_alias_reality()
    source["initial_state_sources"][0]["provider_visibility"] = "INTERNAL_QUALITY_ONLY"
    with pytest.raises(KernelError, match="outside the role"):
        task_reality_workset(source, task={"required_event_refs": ["latest"]}, role_kinds=("world_state", "character_knowledge"), auxiliary_limit=0)


def test_compression_groups_share_one_candidate_allocation():
    source = candidate(text="\n\n".join(f"Optional occurrence {index}." for index in range(300)))
    budgets = []
    def select(stage, chunk):
        if stage == "context_compress":
            budgets.append((chunk["target_tokens"], chunk["candidate_target_tokens"]))
            return {"selected_unit_ids": [chunk["units"][0]["unit_id"]]}
        return {"supported": True, "coverage_complete": True, "missing_unit_ids": [], "distorted_unit_ids": []}
    result, receipt = compile_task_context([source], task=TASK, token_budget=1000, required_asset_types=(), model_call=select, compression_input_tokens=4000, maximum_chunks=32)
    assert len(budgets) > 1
    assert len({total for _, total in budgets}) == 1
    assert sum(part for part, _ in budgets) <= budgets[0][1] <= 1000
    assert receipt["after_estimated_tokens"] <= 1000
