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


def _task_book():
    return {"project_id": "project:1", "book_id": "book:1", "book_run_id": "run:1"}


def _task_source(kind, content, version="plan:5"):
    return {"asset_version_id": version, "content_hash": canonical_hash(content), "asset_type": kind, "content": content}


def test_working_task_extracts_current_mission_scene_and_scoped_refs_without_governance_text():
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task

    content = {"chapter_number": 5, "chapter_intent": "夺回渡桥的通行权", "objective": "Make the bridge promise costly.",
        "scene_plan": [{"scene_id": "scene:5:1", "goal": "修复旧桥", "conflict": "守桥人拒绝交出绳索", "stakes": "药物必须在天黑前送达",
            "participants": ["Mira", "guard"], "pov_character_id": "Mira", "location_id": "north-bridge",
            "object_refs": ["copper-key"], "realization_event_ids": ["planned:bridge-repair"]}],
        "narrative_realization_slice": {"chapter_number": 5, "events": [
            {"event_id": "planned:bridge-repair", "chapter_number": 5, "actor_ref": {"character_id": "Mira"},
                "action": "用钥匙打开绳索仓库", "causes": ["earlier:key-given"]}]},
        "constraint_envelope": {"objective": "PRIVATE-ADMINISTRATION", "character_id": "UNRELATED-ROLE"},
        "execution_evidence": {"text": "WHOLE-GOVERNANCE-PAYLOAD"}}
    sources = [_task_source("chapter_plan", content)]
    task = build_working_task(sources=sources, book=_task_book(), chapter=5, stage="CHAPTER", extra_queries=["铜钥匙", "铜钥匙"])
    validate_working_task(task, sources=sources, book=_task_book(), chapter=5, stage="CHAPTER", extra_queries=["铜钥匙"])
    assert task["goal"] == "夺回渡桥的通行权\nMake the bridge promise costly."
    assert task["explicit_queries"] == ["铜钥匙"] and "用钥匙打开绳索仓库" in task["queries"]
    scene = task["scenes"][0]
    assert scene["subjects"] == ["Mira", "guard"] and "Mira" not in scene["queries"]
    assert scene["goal"] == "修复旧桥" and "药物必须在天黑前送达" in scene["queries"]
    assert scene["place_refs"] == ["north-bridge"] and scene["object_refs"] == ["copper-key"]
    assert task["event_refs"] == ["planned:bridge-repair", "earlier:key-given"]
    assert task["authority"] == "FROZEN_PLAN_RETRIEVAL_ONLY" and "structured_facts" not in task
    assert all(word not in json.dumps(task) for word in ("PRIVATE-ADMINISTRATION", "UNRELATED-ROLE", "WHOLE-GOVERNANCE-PAYLOAD"))
    action = next(row for row in task["field_sources"] if row["text"] == "用钥匙打开绳索仓库")
    assert action["pointer"] == "/narrative_realization_slice/events/0/action"


def test_planning_working_task_uses_current_matrix_row_events_and_exact_arc_segment():
    from novel_forge.modules.book_authority.working_task import build_working_task

    group = {"chapter_range": [5, 7], "objective": "ENTIRE-GROUP-OBJECTIVE", "narrative_segment_ref": {"volume_plan_version_id": "volume:1", "segment_id": "segment:bridge"},
        "chapter_function_matrix": [
            {"chapter_number": 5, "ending_hook": "渡桥上的灯突然熄灭", "required_state_delta": {"summary": "夺回通行权"}},
            {"chapter_number": 6, "ending_hook": "FUTURE-MATRIX-SECRET"}],
        "narrative_event_chain": [
            {"chapter_number": 5, "event_id": "event:5", "action": "带药穿过封锁"},
            {"chapter_number": 6, "event_id": "event:6", "action": "FUTURE-EVENT-SECRET"}]}
    arc = {"objective": "WHOLE-ARC-PAYOFF", "arc_segments": [
        {"volume_plan_version_id": "volume:1", "narrative_segment_id": "segment:bridge", "objective": "兑现修桥的承诺"},
        {"volume_plan_version_id": "volume:2", "narrative_segment_id": "segment:bridge", "objective": "FUTURE-VOLUME-PAYOFF"}]}
    task = build_working_task(sources=[_task_source("chapter_group_plan", group, "group:5"), _task_source("arc_plan", arc, "arc:1")], book=_task_book(), chapter=5, stage="PLANNING")
    assert task["goal"] == "兑现修桥的承诺"
    assert task["queries"] == ["渡桥上的灯突然熄灭", "夺回通行权", "带药穿过封锁"]
    assert task["event_refs"] == ["event:5"]
    assert all(word not in json.dumps(task) for word in ("ENTIRE-GROUP-OBJECTIVE", "FUTURE-MATRIX-SECRET", "FUTURE-EVENT-SECRET", "WHOLE-ARC-PAYOFF", "FUTURE-VOLUME-PAYOFF"))
    assert any(row["pointer"] == "/chapter_function_matrix/0/ending_hook" for row in task["field_sources"])


@pytest.mark.parametrize("window", [{"from_chapter": 4, "to_chapter": 6}, {"start_chapter": 4, "end_chapter": 6}])
def test_working_task_respects_arc_windows_and_retains_unscoped_source_receipts(window):
    from novel_forge.modules.book_authority.working_task import build_working_task

    sources = [_task_source("arc_plan", {"target_window": window, "objective": "repair the bridge"}, "arc:current"),
        _task_source("arc_plan", {"target_window": {"from_chapter": 7, "to_chapter": 9}, "objective": "FUTURE-ARC"}, "arc:future"),
        _task_source("arc_plan", {"objective": "UNSCOPED-ARC"}, "arc:unknown")]
    task = build_working_task(sources=sources, book=_task_book(), chapter=5, stage="PLANNING")
    assert task["goal"] == "repair the bridge" and len(task["sources"]) == 3
    assert {row["asset_version_id"] for row in task["field_sources"]} == {"arc:current"}
    assert "FUTURE-ARC" not in json.dumps(task) and "UNSCOPED-ARC" not in json.dumps(task)


def test_working_task_binds_candidate_payload_pointer_and_deterministic_source_identity():
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task

    source_a = _task_source("planning_generation_candidate", {"generator_operation_name": "chapter_plan.generate",
        "candidate_payload": {"chapter_number": 5, "chapter_intent": "Find the missing copper key"}}, "candidate:5")
    source_b = _task_source("arc_plan", {"objective": "unknown scope"}, "arc:1")
    kwargs = {"book": _task_book(), "chapter": 5, "stage": "CHAPTER"}
    task = build_working_task(sources=[source_a, source_b], **kwargs)
    assert task == build_working_task(sources=[source_b, source_a], **kwargs)
    assert task["field_sources"][0]["pointer"] == "/candidate_payload/chapter_intent"
    assert task["sources"][1]["asset_type"] == "planning_generation_candidate" and task["sources"][1]["plan_kind"] == "chapter_plan"
    validate_working_task(task, sources=[source_a, source_b], **kwargs)
    changed_identity = {**source_b, "content_hash": "sha256:" + "f" * 64}
    assert task["task_hash"] != build_working_task(sources=[source_a, changed_identity], **kwargs)["task_hash"]
    before = deepcopy(task)
    source_a["content"]["candidate_payload"]["chapter_intent"] = "Different goal"
    assert task == before
    with pytest.raises(KernelError, match="exact frozen Plan source fields"):
        validate_working_task(task, sources=[source_a, source_b], **kwargs)


@pytest.mark.parametrize("field,value", [("goal", "INVENTED-RECALL"), ("queries", ["INVENTED-RECALL"]), ("explicit_queries", ["INVENTED-POLICY"])])
def test_rehashed_working_task_cannot_invent_source_fields_or_policy_queries(field, value):
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task

    sources = [_task_source("chapter_plan", {"chapter_number": 5, "chapter_intent": "Repair the bridge"})]
    kwargs = {"book": _task_book(), "chapter": 5, "stage": "CHAPTER"}
    task = build_working_task(sources=sources, extra_queries=["lost key"], **kwargs)
    task[field] = value
    task["task_hash"] = canonical_hash({key: item for key, item in task.items() if key != "task_hash"})
    with pytest.raises(KernelError):
        validate_working_task(task, sources=sources, extra_queries=["lost key"], **kwargs)


def test_working_task_rejects_future_chapter_cross_book_and_stage_drift():
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task

    kwargs = {"book": _task_book(), "chapter": 5, "stage": "CHAPTER"}
    for content in ({"chapter_number": 6, "chapter_intent": "future"}, {"chapter_number": 5, "project_id": "other-project"}):
        with pytest.raises(KernelError):
            build_working_task(sources=[_task_source("chapter_plan", content)], **kwargs)
    source_row = _task_source("chapter_plan", {"chapter_number": 5, "chapter_intent": "Find the key"})
    task = build_working_task(sources=[source_row], **kwargs)
    with pytest.raises(KernelError, match="another Book, Chapter or stage"):
        validate_working_task(task, **{**kwargs, "stage": "PLANNING"})
    task["authority"] = "CANON"
    task["task_hash"] = canonical_hash({key: value for key, value in task.items() if key != "task_hash"})
    with pytest.raises(KernelError, match="retrieval-only"):
        validate_working_task(task, **kwargs)


def test_working_task_frozen_cast_expands_only_exact_current_character_names_and_unique_aliases():
    from novel_forge.modules.book_authority.working_task import build_working_task, validate_working_task
    from novel_forge.modules.hierarchical_planning.domain import character_planning_locator

    identity = "character:lin-shu"
    locator = character_planning_locator(identity)
    plan = {"chapter_number": 5, "chapter_intent": "找到铜钥匙", "scene_plan": [
        {"scene_id": "scene:5", "goal": "林殊履行修桥的承诺", "participants": [locator]}]}
    cast = {"book_id": "book:1", "characters": [
        {"character_id": identity, "name": "林殊", "aliases": ["小林", "先生"], "backstory": "CAST-BACKSTORY-MUST-NOT-BECOME-A-QUERY"},
        {"character_id": "character:other", "name": "王言", "aliases": ["先生", "老王"]}]}
    sources = [_task_source("chapter_plan", plan), _task_source("character_cast", cast, "cast:1")]
    book = {**_task_book(), "workspace_id": "workspace:1", "input_snapshot_id": "snapshot:1"}
    task = build_working_task(sources=sources, book=book, chapter=5, stage="CHAPTER")
    assert task["subjects"] == []
    assert task["scenes"][0]["subjects"] == [locator, identity, "林殊", "小林"]
    assert all(word not in json.dumps(task, ensure_ascii=False) for word in ("先生", "王言", "老王", "CAST-BACKSTORY-MUST-NOT-BECOME-A-QUERY"))
    cast_fields = [row for row in task["field_sources"] if row["asset_version_id"] == "cast:1"]
    assert {row["pointer"] for row in cast_fields} == {"/characters/0/character_id", "/characters/0/name", "/characters/0/aliases/0"}
    assert all(row["field"] == "subjects" and row["scene_id"] == "scene:5" for row in cast_fields)
    validate_working_task(task, book=_task_book(), chapter=5, stage="CHAPTER")
    validate_working_task(task, book=book, chapter=5, stage="CHAPTER", sources=sources)
    sources[1]["content"]["characters"][0]["name"] = "CHANGED-FROZEN-NAME"
    with pytest.raises(KernelError, match="exact frozen Plan source fields"):
        validate_working_task(task, book=book, chapter=5, stage="CHAPTER", sources=sources)


def test_working_task_to_passage_retrieval_uses_chinese_scene_need_with_frozen_name_scope():
    from novel_forge.modules.book_authority.task_retrieval import select_task_passages
    from novel_forge.modules.book_authority.working_task import build_working_task

    cast = {"book_id": "book:1", "generator_operation_name": "character.cast.generate", "characters": [
        {"character_id": "character:lin-shu", "name": "林殊", "aliases": ["小林"]}]}
    plan = {"chapter_number": 5, "scene_plan": [{"scene_id": "scene:5", "goal": "林殊要履行修桥的承诺", "participants": ["character:lin-shu"]}]}
    book = {**_task_book(), "workspace_id": "workspace:1", "input_snapshot_id": "snapshot:1"}
    task = build_working_task(sources=[_task_source("chapter_plan", plan), _task_source("planning_generation_candidate", cast, "cast:1")],
        book=book, chapter=5, stage="CHAPTER", extra_queries=[])
    old_promise, same_name_only = "桥头，林殊亲口许下修桥的承诺。", "林殊低头喝完了粥。"
    result = select_task_passages([(1, 0, len(old_promise), old_promise), (4, 0, len(same_name_only), same_name_only)], task=task)
    assert result["task_hash"] == task["task_hash"]
    assert [row["chapter"] for row in result["selected"]] == [1]
    assert result["selected"][0]["matched_queries"] == ["scenes/0/goal"]
