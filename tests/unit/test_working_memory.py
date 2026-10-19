from copy import deepcopy
import json

import pytest

from novel_forge.modules.book_authority.working_prose import project_working_sources, validate_working_projection, working_instruction
from novel_forge.modules.chapter_authority.author_editor import text_hash
from novel_forge.modules.chapter_authority.execution_gateway import PostgresChapterExecutionContractBinder
from novel_forge.modules.chapter_authority.model_effects import normalize_model_output
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.working_memory import (
    bind_packet_coverage, compile_working_memory, normalize_observations, optional_draft_memory,
    validate_memory_packet, validate_observations,
)
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def note(**overrides):
    return {"kind": "PROMISE", "subject": "Mira", "state_key": "bridge", "claim": "Mira promises to repair the bridge.",
            "perspective": "OBSERVED", "knowledge_owner": "", "quote": "Mira promised to repair the bridge.", "causes": [], **overrides}


def source(number, text, observations=None):
    return {"chapter": number, "asset_version_id": f"draft:{number}", "content_hash": f"content:{number}",
            "text_hash": text_hash(text), "text": text, "observations": observations,
            "memory_provenance": {"kind": "WRITER_SELF_OBSERVATION", "asset_version_id": f"draft:{number}"}}


def policy(**overrides):
    return {"version": "working-prose-projection.v3", "history_chapters": 40, "recent_complete_chapters": 1,
            "max_characters": 5000, "queries": ["bridge"], "guidance_mode": "COMBINED", **overrides}


def test_old_promise_is_retrieved_beyond_thirty_two_chapters_with_exact_evidence():
    text = "Mira promised to repair the bridge.\n\nA quiet afternoon."
    memory = normalize_observations([note()], text)
    sources = [source(1, text, memory)] + [source(n, f"Evening {n}.") for n in range(2, 41)]
    packet = compile_working_memory(sources, queries=["bridge"], max_characters=2000)
    rows = project_working_sources(sources, target_chapter=41, policy=policy(), memory=packet)
    packet = bind_packet_coverage(packet, rows)
    snapshot = {"version": "working-manuscript-context.v1", "book_run_id": "r", "project_id": "p", "book_id": "b",
                "target_chapter": 41, "accepted_through_chapter": 0, "authority": "AUTHOR_WORKING_PROSE_ONLY", "structured_facts": [],
                "projection_policy": policy(), "sources": rows, "working_memory": packet, "instruction": working_instruction(policy())}
    snapshot["snapshot_hash"] = canonical_hash(snapshot)
    validate_working_projection(snapshot, project_id="p", book_id="b")
    assert packet["candidate_count"] == 1 and packet["entries"][0]["source"]["chapter"] == 1
    assert rows[0]["passages"][0]["text"].startswith(note()["quote"])
    assert rows[-1]["omitted_ranges"] == []


@pytest.mark.parametrize("override", [{"perspective": "READER_ONLY", "knowledge_owner": "Mira"},
    {"kind": "CANON"}, {"kind": "KNOWLEDGE", "knowledge_owner": ""}, {"causes": ["future:invented"]},
    {"perspective": "BELIEF", "knowledge_owner": ""}, {"quote": "This is not the source."}, {"kind": []}, {"perspective": {}}])
def test_observations_cannot_grant_canon_or_unattributed_knowledge(override):
    with pytest.raises(KernelError):
        normalize_observations([note(**override)], note()["quote"])


@pytest.mark.parametrize("raw", ["bad JSON", '{"kind":"CANON"}', '[{"quote":"missing"}]'])
def test_invalid_optional_memory_preserves_prose(raw):
    value = optional_draft_memory(raw, "Complete prose.")
    assert value["status"] == "UNAVAILABLE" and value["prose_preserved"]


def test_editor_changed_text_invalidates_inherited_memory_and_keeps_archive():
    text = note()["quote"]
    memory = normalize_observations([note()], text)
    with pytest.raises(KernelError, match="another prose version"):
        validate_observations(memory, text + " Edited.")
    packet = compile_working_memory([source(1, text + " Edited.", memory)], queries=[], max_characters=5000)
    assert packet["entries"] == [] and packet["source_coverage"][0]["status"] == "WORKING_MEMORY_STALE"


def test_upstream_edit_invalidates_dependent_memory_and_explicitly_reports_gap():
    text = note()["quote"]
    row = source(1, text, normalize_observations([note()], text))
    row["dependency_changes"] = [{"chapter": 0}]
    assert compile_working_memory([row], queries=[], max_characters=5000)["source_coverage"][0]["status"] == "WORKING_MEMORY_DEPENDENCY_CHANGED"


def test_retrieval_memory_keeps_latest_scoped_states_promises_and_causal_closure():
    first_text = "Mira was waiting.\n\nThe bridge broke.\n\nShe promised to return.\n\nA bird flew away."
    old = normalize_observations([
        note(kind="CHARACTER_STATE", state_key="position", quote="Mira was waiting."),
        note(kind="EVENT", state_key="damage", quote="The bridge broke."),
        note(quote="She promised to return."),
        note(kind="EVENT", state_key="bird", quote="A bird flew away."),
    ], first_text)
    cause = old["entries"][1]["observation_id"]
    latest_text = "Mira left the bridge."
    new = normalize_observations([note(kind="CHARACTER_STATE", state_key="position", quote=latest_text, causes=[cause])], latest_text, available_causes={cause})
    rows = [source(1, first_text, old), source(20, latest_text, new)]
    packet = compile_working_memory(rows, queries=[], max_characters=None, dependency_closed=True, recent_complete_from=19)
    assert {entry["quote"] for entry in packet["entries"]} == {"The bridge broke.", "She promised to return.", latest_text}
    assert len(packet["omitted_observation_ids"]) == 2
    projected = project_working_sources(rows, target_chapter=21, policy=policy(version="working-prose-projection.v8", max_characters=None, recent_complete_chapters=2), memory=packet)
    bound = bind_packet_coverage(packet, projected)
    assert bound["entries"] == packet["entries"]
    assert bound["retrieval_omissions"] == []
    validate_memory_packet(bound, projected)


def test_beliefs_and_reader_disclosures_do_not_merge_with_character_knowledge():
    text = "Mira trusted the bridge. Only the reader saw its broken support."
    notes = [note(kind="KNOWLEDGE", state_key="safety", perspective="BELIEF", knowledge_owner="Mira", quote="Mira trusted the bridge."),
             note(kind="EVENT", perspective="READER_ONLY", knowledge_owner="", quote="Only the reader saw its broken support.")]
    packet = compile_working_memory([source(1, text, normalize_observations(notes, text))], queries=[], max_characters=5000)
    assert {row["perspective"] for row in packet["entries"]} == {"BELIEF", "READER_ONLY"}
    assert packet["semantic_support"] == "NOT_VERIFIED"


def test_memory_packet_does_not_silently_lose_retrieval_coverage():
    text = note()["quote"] + "\n\n" + "x" * 100
    rows = [source(1, text, normalize_observations([note()], text)), source(2, "Current scene.")]
    packet = compile_working_memory(rows, queries=[], max_characters=5000)
    projected = project_working_sources(rows, target_chapter=3, policy=policy(history_chapters=2, max_characters=15), memory=packet)
    packet = bind_packet_coverage(packet, projected)
    assert len(packet["retrieval_omissions"]) == 1 and packet["entries"] == []
    validate_memory_packet(packet, projected)


def test_quotes_across_retained_adjacent_paragraphs_remain_located():
    text = "Mira promised.\n\nThe bridge still needed repair."
    memory = normalize_observations([note(quote=text)], text)
    rows = [source(1, text, memory)]
    packet = compile_working_memory(rows, queries=[], max_characters=5000)
    projected = project_working_sources(rows, target_chapter=2, policy=policy(history_chapters=1), memory=packet)
    packet = bind_packet_coverage(packet, projected)
    assert len(packet["entries"]) == 1
    validate_memory_packet(packet, projected)


def test_optional_corrupt_observations_are_reported_without_stopping_retrieval():
    row = source(1, "Complete source.", {"text_hash": text_hash("Complete source."), "entries": [{"kind": []}]})
    packet = compile_working_memory([row], queries=[], max_characters=5000)
    assert packet["entries"] == [] and packet["source_coverage"][0]["status"] == "WORKING_MEMORY_INVALID"


def test_v3_memo_uses_existing_exact_pack_prompt_materialization(monkeypatch):
    from tests.unit import test_working_prose_projection as existing
    frozen = existing.snapshot()
    frozen["projection_policy"]["version"] = "working-prose-projection.v3"
    frozen["instruction"] = working_instruction(frozen["projection_policy"])
    rows = [{**row, "text": "".join(p["text"] for p in row["passages"])} for row in frozen["sources"]]
    rows[0]["observations"] = normalize_observations([note(subject="actor", quote="An old promise.")], rows[0]["text"])
    rows[0]["memory_provenance"] = {"kind": "WRITER_SELF_OBSERVATION", "asset_version_id": rows[0]["asset_version_id"]}
    frozen["working_memory"] = bind_packet_coverage(compile_working_memory(rows, queries=[], max_characters=5000), frozen["sources"])
    frozen["snapshot_hash"] = canonical_hash({k: v for k, v in frozen.items() if k != "snapshot_hash"})
    monkeypatch.setattr(existing, "snapshot", lambda: deepcopy(frozen))
    existing.test_enhanced_memo_reaches_final_provider_prompt_and_preserves_legacy_skill()


def test_provider_contract_is_opt_in_and_optional_annotation_survives_normalization():
    inputs = {"execution_intent": {"working_manuscript": {"projection_policy": policy()}}}
    schema, ref = PostgresChapterExecutionContractBinder._provider_output_contract(stage="draft", request_payload={"input": inputs})
    assert "working_memory_json" in schema["properties"] and "working_memory_json" not in schema["required"]
    assert ref.endswith(":working-memory-v1")
    old, _ = PostgresChapterExecutionContractBinder._provider_output_contract(stage="draft", request_payload={"input": {}})
    assert "working_memory_json" not in old["properties"]
    value = normalize_model_output("draft", {"scene_artifacts": [{"text": "Prose"}], "working_memory_json": json.dumps([])})
    assert value["working_memory_json"] == "[]"


def test_rehashed_packet_cannot_promote_working_observations():
    text = note()["quote"]
    rows = [source(1, text, normalize_observations([note()], text))]
    packet = compile_working_memory(rows, queries=[], max_characters=5000)
    projected = project_working_sources(rows, target_chapter=2, policy=policy(history_chapters=1), memory=packet)
    packet = bind_packet_coverage(packet, projected)
    attacked = deepcopy(packet)
    attacked["authority"] = "CANON"
    attacked["packet_hash"] = canonical_hash({k: v for k, v in attacked.items() if k != "packet_hash"})
    with pytest.raises(KernelError):
        validate_memory_packet(attacked, projected)


def test_bad_optional_metadata_never_invalidates_structurally_complete_prose():
    from novel_forge.modules.chapter_authority.provider_output_contracts import validate_chapter_provider_output_against_schema
    schema, _ = PostgresChapterExecutionContractBinder._provider_output_contract(stage="draft", request_payload={"input": {
        "execution_intent": {"working_manuscript": {"projection_policy": policy()}}}})
    raw = {"scene_artifacts": [{"slot_id": "s", "text": "Complete prose.", "used_fact_ids": []}], "working_memory_json": {"broken": True}}
    validate_chapter_provider_output_against_schema("draft", schema, raw)
    assert optional_draft_memory(raw["working_memory_json"], "Complete prose.")["prose_preserved"]
    with pytest.raises(KernelError):
        validate_chapter_provider_output_against_schema("draft", schema, {**raw, "scene_artifacts": []})
