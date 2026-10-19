from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.book_authority import manuscript
from novel_forge.modules.book_authority.working_prose import (
    LONGFORM_POLICY_VERSION,
    PROGRESSION_POLICY_VERSION,
    project_working_history_for_provider,
    validate_working_projection,
    working_source_rows,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.narrative_state.working_memory import normalize_observations
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


def _policy(**overrides):
    return {"version": LONGFORM_POLICY_VERSION, "history_chapters": 128,
        "recent_complete_chapters": 2, "max_characters": 24000, "queries": [],
        "guidance_mode": "COMBINED", **overrides}


def _rehash(snapshot):
    snapshot["snapshot_hash"] = canonical_hash({key: value for key, value in snapshot.items() if key != "snapshot_hash"})


def _native_history(monkeypatch, target, *, tiny=False):
    documents = {}
    for number in range(1, target):
        text = f"第{number}次已有经历。" if tiny else f"第{number}章。" + "他已完成当时的选择，后面的处境承接这次经历。" * 180
        documents[number] = SimpleNamespace(asset_version_id=f"native:{number}",
            content_hash=f"hash:{number}", asset_type="draft_chapter", content={"chapter": number, "title": "", "text": text})
    book = {"project_id": "project", "book_id": "book", "book_run_id": "run", "workspace_id": "workspace", "accepted_through_chapter": 0}
    uow = MagicMock()

    def resolve(_uow, _book, number):
        if number not in documents:
            raise KernelError("MANUSCRIPT_CHAPTER_MISSING", "Native predecessor is missing")
        source = documents[number]
        pointer = {key: getattr(source, key) for key in ("asset_version_id", "content_hash")}
        return source, {"native_source": pointer, "effective_source": pointer,
            "native_basis": "NATIVE_DRAFT_OUTPUT", "overrides": []}

    monkeypatch.setattr(manuscript, "resolve_working_source", resolve)
    monkeypatch.setattr(manuscript, "selected_source", lambda *args: resolve(*args)[0])
    monkeypatch.setattr(manuscript, "require_prose_propagation_batch", lambda *_: None)
    monkeypatch.setattr(manuscript, "working_dependency_changes", lambda *_: ([], {}))
    monkeypatch.setattr("novel_forge.modules.book_authority.manuscript_memory.source_memory", lambda *_: (None, {"status": "MISSING"}))
    uow.repositories.asset_documents.require.side_effect = lambda **kwargs: next(
        source for source in documents.values() if source.asset_version_id == kwargs["asset_version_id"])
    return uow, book, documents


@pytest.mark.parametrize("target", [130, 600])
def test_native_longform_freeze_keeps_complete_versions_and_bounded_literal_input(monkeypatch, target):
    uow, book, _ = _native_history(monkeypatch, target)
    snapshot = manuscript.freeze_working_context(uow, book, target, projection_policy=_policy())
    validate_working_projection(snapshot, project_id="project", book_id="book", target_chapter=target)
    manuscript.verify_working_context(uow, book, snapshot)
    manifest = snapshot["source_history"]
    assert manifest["source_count"] == target - 1
    assert [row["chapter"] for row in working_source_rows(snapshot)] == list(range(1, target))
    assert len(snapshot["sources"]) <= 128
    assert sum(len(p["text"]) for row in snapshot["sources"] for p in row["passages"]) <= 24000
    assert all(not row["omitted_ranges"] for row in snapshot["sources"] if row["chapter"] >= target - 2)
    assert snapshot["accepted_through_chapter"] == 0 and snapshot["structured_facts"] == []
    before = deepcopy(snapshot)
    view = project_working_history_for_provider(snapshot)
    assert snapshot == before
    assert view["source_history"]["source_history_hash"] == manifest["content_hash"]
    assert view["source_history"]["source_snapshot_hash"] == snapshot["snapshot_hash"]
    assert view["source_history"]["source_count"] == target - 1
    assert "sources" not in view["source_history"]
    assert view["sources"] == snapshot["sources"]
    assert len(json.dumps(view)) < len(json.dumps(snapshot))
    assert project_working_history_for_provider(view) == view
    with pytest.raises(KernelError, match="WORKING_PROSE_HISTORY_INVALID"):
        manuscript.verify_working_context(uow, book, view)


@pytest.mark.parametrize("target", [21, 130, 600])
def test_retrieval_freeze_scales_source_manifest_without_resending_missing_memory_as_full_prose(monkeypatch, target):
    uow, book, documents = _native_history(monkeypatch, target)
    snapshot = manuscript.freeze_working_context(uow, book, target,
        projection_policy=_policy(version="working-prose-projection.v8", max_characters=None))
    validate_working_projection(snapshot, project_id="project", book_id="book", target_chapter=target)
    manuscript.verify_working_context(uow, book, snapshot)
    assert len(working_source_rows(snapshot)) == target - 1
    assert [row["chapter"] for row in snapshot["sources"]] == [target - 2, target - 1]
    assert ["".join(p["text"] for p in row["passages"]) for row in snapshot["sources"]] == [documents[number].content["text"] for number in (target - 2, target - 1)]
    assert len(snapshot["working_memory"]["source_coverage"]) == target - 1
    assert {row["status"] for row in snapshot["working_memory"]["source_coverage"]} == {"MISSING"}
    assert snapshot["working_memory"]["entries"] == []
    provider = project_working_history_for_provider(snapshot)
    validate_working_projection(provider, project_id="project", book_id="book", target_chapter=target)
    assert provider["source_history"]["boundary"] == "OMITTED_PROSE_UNKNOWN_NO_ACCEPTED_FACTS"
    assert len(provider["working_memory"]["source_coverage"]) == 2


def test_longform_bounds_source_rows_and_recalls_old_located_annotation(monkeypatch):
    uow, book, documents = _native_history(monkeypatch, 600, tiny=True)
    quote = documents[1].content["text"]
    observations = normalize_observations([{"kind": "PROMISE", "subject": "主角", "state_key": "返乡",
        "claim": "已留下返乡的约定。", "perspective": "OBSERVED", "knowledge_owner": "", "quote": quote, "causes": []}], quote)
    monkeypatch.setattr("novel_forge.modules.book_authority.manuscript_memory.source_memory",
        lambda _uow, _book, source: (observations, {"kind": "WRITER_SELF_OBSERVATION"})
        if source.asset_version_id == "native:1" else (None, {"status": "MISSING"}))
    snapshot = manuscript.freeze_working_context(uow, book, 600, projection_policy=_policy())
    assert len(snapshot["sources"]) == 128
    assert snapshot["sources"][0]["chapter"] == 1
    assert [row["chapter"] for row in snapshot["sources"][-2:]] == [598, 599]
    assert snapshot["working_memory"]["entries"][0]["source"]["asset_version_id"] == "native:1"
    validate_working_projection(project_working_history_for_provider(snapshot), project_id="project", book_id="book")


def test_frozen_v1_transport_keeps_original_packet_while_v2_bounds_metadata(monkeypatch):
    from novel_forge.modules.chapter_authority.provider_views import compile_working_history_transport
    uow, book, _ = _native_history(monkeypatch, 130, tiny=True)
    snapshot = manuscript.freeze_working_context(uow, book, 130, projection_policy=_policy())
    before = deepcopy(snapshot)
    legacy, old_receipt = compile_working_history_transport({"working": snapshot}, contract_version="working-history-provider-transport.v1")
    current, new_receipt = compile_working_history_transport({"working": snapshot})
    assert old_receipt["contract_version"] == "working-history-provider-transport.v1"
    assert new_receipt["contract_version"] == "working-history-provider-transport.v2"
    assert legacy["working"]["working_memory"]["version"] == "working-observations.v1"
    assert legacy["working"]["working_memory"]["omitted_observation_ids"] == snapshot["working_memory"]["omitted_observation_ids"]
    assert current["working"]["working_memory"]["version"] == "working-observations-provider.v1"
    assert snapshot == before
    assert compile_working_history_transport(legacy, contract_version="working-history-provider-transport.v1")[0] == legacy
    with pytest.raises(KernelError, match="WORKING_PROSE_HISTORY_INVALID"):
        compile_working_history_transport({"working": snapshot}, contract_version="unknown")


def test_v4_keeps_historical_130_rejection_and_rendering(monkeypatch):
    uow, book, _ = _native_history(monkeypatch, 130)
    with pytest.raises(KernelError, match="WORKING_PROSE_HISTORY_INCOMPLETE"):
        manuscript.freeze_working_context(uow, book, 130, projection_policy=_policy(version=PROGRESSION_POLICY_VERSION))
    historical = {"projection_policy": {"version": PROGRESSION_POLICY_VERSION}, "frozen_schema": "v4"}
    assert project_working_history_for_provider(historical) == historical


@pytest.mark.parametrize("mutation", ["foreign_book", "missing_version", "source_hash", "selected_lineage", "selection_receipt"])
def test_longform_complete_host_manifest_guards_early_sources(monkeypatch, mutation):
    uow, book, documents = _native_history(monkeypatch, 600)
    snapshot = manuscript.freeze_working_context(uow, book, 600, projection_policy=_policy())
    assert 1 not in {row["chapter"] for row in snapshot["sources"]}
    if mutation == "foreign_book":
        with pytest.raises(KernelError, match="WORKING_PROSE_PROJECTION_INVALID"):
            manuscript.verify_working_context(uow, {**book, "book_id": "foreign"}, snapshot)
    elif mutation == "missing_version":
        del documents[1]
        with pytest.raises(KernelError, match="MANUSCRIPT_CHAPTER_MISSING"):
            manuscript.verify_working_context(uow, book, snapshot)
    elif mutation == "source_hash":
        documents[1].content_hash = "changed-hash"
        with pytest.raises(KernelError, match="MANUSCRIPT_SOURCE_HASH_INVALID|MANUSCRIPT_DEPENDENCY_CHANGED"):
            manuscript.verify_working_context(uow, book, snapshot)
    elif mutation == "selected_lineage":
        documents[1].asset_version_id = "new-selected:1"
        with pytest.raises(KernelError, match="MANUSCRIPT_DEPENDENCY_CHANGED"):
            manuscript.verify_working_context(uow, book, snapshot)
    else:
        original = manuscript.resolve_working_source
        def changed_selection(*args):
            source, resolution = original(*args)
            if args[-1] == 1:
                resolution["overrides"] = [{"asset_version_id": "new-selection-receipt", "content_hash": "new-selection-hash"}]
            return source, resolution
        monkeypatch.setattr(manuscript, "resolve_working_source", changed_selection)
        with pytest.raises(KernelError, match="MANUSCRIPT_DEPENDENCY_CHANGED"):
            manuscript.verify_working_context(uow, book, snapshot)


def test_longform_rejects_rehashed_missing_history_and_mandatory_capacity_overflow(monkeypatch):
    uow, book, documents = _native_history(monkeypatch, 130)
    snapshot = manuscript.freeze_working_context(uow, book, 130, projection_policy=_policy())
    snapshot["source_history"]["sources"].pop(0)
    history = snapshot["source_history"]
    history["content_hash"] = canonical_hash({key: value for key, value in history.items() if key != "content_hash"})
    _rehash(snapshot)
    with pytest.raises(KernelError, match="WORKING_PROSE_HISTORY_INVALID"):
        validate_working_projection(snapshot, project_id="project", book_id="book")
    with pytest.raises(KernelError, match="WORKING_PROSE_REQUIRED_INPUT_OVERFLOW"):
        manuscript.freeze_working_context(uow, book, 130,
            projection_policy=_policy(max_characters=len(documents[129].content["text"])))


def test_longform_neutral_guidance_preserves_author_scope():
    from novel_forge.modules.book_authority.working_prose import working_instruction
    instruction = working_instruction(_policy())
    assert "author's declared chapter length" in instruction
    assert "Source receipts and workflow status impose no duties" in instruction
    assert "omitted prose remains unknown" in instruction
    for historical_requirement in ("Use three connected", "Dialogue must change", "ending an irreversible", "4000–5000"):
        assert historical_requirement not in instruction
    template = json.loads((Path(__file__).resolve().parents[2] / "config/execution_templates/creation_inputs.json").read_text())
    policy = template["profiles"]["production_profile"]["content"]["working_prose_policy"]
    assert policy["version"] == "working-prose-projection.v9" and policy["history_chapters"] == 10000
    assert policy["recent_complete_chapters"] == 0 and policy["recent_tail_paragraphs"] == 4
    assert policy["max_characters"] is None


@pytest.mark.parametrize("change", ["draft", "selection_receipt"])
def test_earlier_unrendered_selection_change_invalidates_downstream_dependencies(monkeypatch, change):
    dependency_changes = manuscript.working_dependency_changes
    uow, book, documents = _native_history(monkeypatch, 132)
    frozen = manuscript.freeze_working_context(uow, book, 130, projection_policy=_policy())
    assert 1 not in {row["chapter"] for row in frozen["sources"]}
    deliveries = [(number, f"native:{number}", {"sources": []}) for number in range(1, 132)]
    deliveries[129] = (130, "native:130", frozen)
    deliveries[130] = (131, "native:131", {"sources": [{"chapter": 130, "asset_version_id": "native:130"}]})
    uow.cursor.fetchall.side_effect = [deliveries, []]
    monkeypatch.setattr(manuscript, "_selected_working_dependencies", lambda *_: None)
    if change == "draft":
        documents[1].asset_version_id = "replacement:1"
        expected = {"chapter": 1, "source_asset_version_id": "native:1", "current_asset_version_id": "replacement:1"}
    else:
        original = manuscript.resolve_working_source
        def changed_selection(*args):
            source, resolution = original(*args)
            if args[-1] == 1:
                resolution["overrides"] = [{"asset_version_id": "new-selection-receipt", "content_hash": "new-selection-hash"}]
            return source, resolution
        monkeypatch.setattr(manuscript, "resolve_working_source", changed_selection)
        expected = {"chapter": 1, "source_asset_version_id": "native:1", "current_asset_version_id": "native:1", "source_resolution_changed": True}
    _, changed = dependency_changes(uow, book)
    assert changed[130] == [expected]
    assert changed[131] == [{**expected, "via_chapter": 130}]


def test_capacity_policy_keeps_native_source_lineage_and_uses_existing_lossless_transport(monkeypatch):
    from novel_forge.modules.chapter_authority.provider_views import compile_working_history_transport
    uow, book, _ = _native_history(monkeypatch, 130, tiny=True)
    snapshot = manuscript.freeze_working_context(uow, book, 130,
        projection_policy=_policy(version="working-prose-projection.v6", max_characters=None))
    delivered, receipt = compile_working_history_transport(snapshot)
    assert snapshot["source_history"]["source_count"] == 129
    assert delivered["source_history"]["contract_version"] == "working-source-history-reference.v1"
    assert receipt["projections"] and delivered["sources"] == snapshot["sources"]


def _task_memory_source(chapter, observations, *, available_causes=None):
    from novel_forge.modules.review.diagnostics import prose_hash
    text = "\n\n".join(row["quote"] for row in observations)
    return {"chapter": chapter, "asset_version_id": f"task-draft:{chapter}", "content_hash": f"content:{chapter}",
        "text_hash": prose_hash(text), "text": text,
        "observations": normalize_observations(observations, text, available_causes=available_causes),
        "memory_provenance": {"kind": "WRITER_SELF_OBSERVATION", "asset_version_id": f"task-draft:{chapter}"}}


def _task_note(quote, **overrides):
    return {"kind": "CHARACTER_STATE", "subject": "林舟", "state_key": "location", "claim": quote,
        "perspective": "OBSERVED", "knowledge_owner": "", "quote": quote, "causes": [], **overrides}


def _scoped_memory_history():
    first = _task_memory_source(1, [
        _task_note("林舟守在桥边。"),
        _task_note("守桥人拆去了支柱。", kind="EVENT", subject="守桥人", state_key="拆除"),
        _task_note("林舟答应带回欠条。", kind="PROMISE", state_key="欠条"),
        _task_note("卖茶人许诺给城北送茶。", kind="PROMISE", subject="卖茶人", state_key="送茶"),
    ])
    original_cause = first["observations"]["entries"][1]["observation_id"]
    second = _task_memory_source(2, [
        _task_note("暴雨冲塌了旧桥。", kind="CONSEQUENCE", subject="暴雨", state_key="坍塌", causes=[original_cause]),
        _task_note("林舟以为旧桥尚可通行。", kind="KNOWLEDGE", subject="旧桥", state_key="安全", perspective="BELIEF", knowledge_owner="林舟"),
    ], available_causes={original_cause})
    immediate_cause = second["observations"]["entries"][0]["observation_id"]
    last = _task_memory_source(599, [
        _task_note("林舟绕行渡口。", causes=[immediate_cause]),
        _task_note("林舟亲眼看见旧桥已经坍塌。", kind="KNOWLEDGE", subject="旧桥", state_key="安全", knowledge_owner="林舟"),
        _task_note("乔婆听说旧桥已经坍塌。", kind="KNOWLEDGE", subject="旧桥", state_key="安全", perspective="HEARSAY", knowledge_owner="乔婆"),
        _task_note("林岚留在城北。", subject="林岚"),
        _task_note("卖茶人仍许诺送茶。", kind="PROMISE", subject="卖茶人", state_key="送茶"),
        _task_note("只有读者看见桥底的银匣。", kind="EVENT", subject="银匣", state_key="隐藏", perspective="READER_ONLY"),
    ], available_causes={immediate_cause})
    return [first, second, last]


def test_task_memory_scopes_latest_knowledge_and_promises_without_cutting_old_causes():
    from novel_forge.modules.narrative_state.working_memory import bind_packet_coverage, compile_working_memory, validate_memory_packet
    sources = _scoped_memory_history()
    packet = compile_working_memory(sources, queries=["林舟"], max_characters=None, dependency_closed=True,
        recent_complete_from=598, task={"goal": "林舟前往渡口", "subjects": ["林舟"]}, selected_ranges={})
    quotes = {row["quote"] for row in packet["entries"]}
    assert quotes == {"守桥人拆去了支柱。", "暴雨冲塌了旧桥。", "林舟答应带回欠条。",
        "林舟以为旧桥尚可通行。", "林舟绕行渡口。", "林舟亲眼看见旧桥已经坍塌。"}
    assert {row["perspective"] for row in packet["entries"] if row["kind"] == "KNOWLEDGE"} == {"BELIEF", "OBSERVED"}
    assert {row["knowledge_owner"] for row in packet["entries"] if row["kind"] == "KNOWLEDGE"} == {"林舟"}
    assert packet["candidate_count"] == 12
    assert len(packet["omitted_observation_ids"]) == 6
    projected = [{**source, "passages": [{"start": 0, "end": len(source["text"]), "text": source["text"]}]} for source in sources]
    bound = bind_packet_coverage(packet, projected)
    validate_memory_packet(bound, projected)
    assert bound["retrieval_omissions"] == [] and bound["authority"] == "UNREVIEWED_WORKING_OBSERVATIONS"


def test_task_selected_unicode_passages_recover_old_state_and_reader_only_evidence():
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory
    sources = _scoped_memory_history()
    selected = {}
    for source, quote in ((sources[0], "林舟守在桥边。"), (sources[-1], "只有读者看见桥底的银匣。")):
        start = source["text"].index(quote)
        selected[source["asset_version_id"]] = [{"start": start, "end": start + len(quote)}]
    packet = compile_working_memory(sources, queries=[], max_characters=None, dependency_closed=True,
        recent_complete_from=598, task={"goal": "林舟将在未来找到银匣", "subjects": []}, selected_ranges=selected)
    assert [row["quote"] for row in packet["entries"]] == ["林舟守在桥边。", "只有读者看见桥底的银匣。"]
    assert packet["entries"][0]["state_role"] == "HISTORICAL_OBSERVATION"
    assert packet["entries"][1]["perspective"] == "READER_ONLY" and packet["entries"][1]["knowledge_owner"] == ""
    assert packet["entries"][1]["source"]["asset_version_id"] == "task-draft:599"
    assert all(row["claim"] != "林舟将在未来找到银匣" for row in packet["entries"])


@pytest.mark.parametrize("task, selected_ranges", [({}, None), ({}, {}), ({"subjects": [], "queries": [], "event_refs": [], "object_refs": [], "place_refs": []}, {})])
def test_explicit_empty_memory_task_preserves_missing_and_stale_coverage_without_selecting_everything(task, selected_ranges):
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory
    sources = _scoped_memory_history()
    stale = _task_memory_source(600, [_task_note("旧稿上的位置。")])
    stale["text"] = "改稿后的位置已经改变。"
    missing = {**_task_memory_source(601, [_task_note("正文仍然完整。")]), "observations": None,
        "memory_provenance": {"status": "NOT_REQUESTED"}}
    sources += [stale, missing]
    before = deepcopy(sources)
    packet = compile_working_memory(sources, queries=[], max_characters=None, dependency_closed=True,
        recent_complete_from=1, task=task, selected_ranges=selected_ranges)
    assert packet["entries"] == [] and len(packet["omitted_observation_ids"]) == 12
    assert packet["source_coverage"][-2:] == [
        {"chapter": 600, "asset_version_id": "task-draft:600", "status": "WORKING_MEMORY_STALE"},
        {"chapter": 601, "asset_version_id": "task-draft:601", "status": "NOT_REQUESTED"},
    ]
    assert sources == before


def test_task_memory_references_do_not_merge_names_or_substrings_and_keep_latest_state():
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory
    first = _task_memory_source(1, [
        _task_note("Lina was waiting.", subject="Lina"),
        _task_note("The sealed door remained shut.", subject="doorkeeper"),
        _task_note("The seal was broken.", subject="seal", state_key="condition"),
    ])
    second = _task_memory_source(2, [_task_note("The seal was repaired.", subject="seal", state_key="condition")])
    packet = compile_working_memory([first, second], queries=["Li"], max_characters=None, dependency_closed=True,
        recent_complete_from=1, task={"subjects": ["Li"], "object_refs": ["seal"]}, selected_ranges={})
    assert [row["quote"] for row in packet["entries"]] == ["The seal was repaired."]
    historical_id = first["observations"]["entries"][2]["observation_id"]
    explicit = compile_working_memory([first, second], queries=[], max_characters=None, dependency_closed=True,
        recent_complete_from=1, task={"event_refs": [historical_id]}, selected_ranges={})
    assert [row["observation_id"] for row in explicit["entries"]] == [historical_id]


@pytest.mark.parametrize("selected_ranges", [{"foreign:1": [{"start": 0, "end": 1}]},
    {"task-draft:1": [{"start": 0, "end": 100000}]}, {"task-draft:1": [{"start": True, "end": 2}]}])
def test_task_memory_rejects_ranges_without_exact_source_coordinates(selected_ranges):
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory
    with pytest.raises(KernelError, match="WORKING_MEMORY_SELECTION_POLICY_INVALID"):
        compile_working_memory(_scoped_memory_history(), queries=[], max_characters=None, dependency_closed=True,
            recent_complete_from=598, task={}, selected_ranges=selected_ranges)


@pytest.mark.parametrize("options, expected_hash", [
    ({"queries": [], "max_characters": None, "dependency_closed": True, "recent_complete_from": 598},
        "sha256:633c68a0e4874da5620cc977ea36554d6f09e27865c623509e99191066932305"),
    ({"queries": ["旧桥"], "max_characters": 6000, "dependency_closed": True},
        "sha256:1d4f90f31d024df89cc1c78ec8fe87b1d1e11037a6781fdef102cf3cba927933"),
])
def test_unscoped_working_memory_keeps_frozen_packet_identity(options, expected_hash):
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory
    packet = compile_working_memory(_scoped_memory_history(), **options)
    assert packet["packet_hash"] == expected_hash


def _task_selection_snapshot():
    from novel_forge.modules.book_authority.working_prose import freeze_source_history, project_working_sources, working_instruction
    from novel_forge.modules.book_authority.working_selection import select_working_context
    from novel_forge.modules.book_authority.working_task import build_working_task
    from novel_forge.modules.narrative_state.working_memory import bind_packet_coverage, compile_working_memory
    from novel_forge.modules.review.diagnostics import prose_hash
    book = {"project_id": "selection-project", "book_id": "selection-book", "book_run_id": "selection-run"}
    content = {"chapter_number": 3, "chapter_intent": "寻找铜钥匙"}
    task = build_working_task(sources=[{"asset_type": "chapter_plan", "asset_version_id": "plan:3",
        "content_hash": canonical_hash(content), "content": content}], book=book, chapter=3, stage="CHAPTER")
    policy = {"version": "working-prose-projection.v9", "history_chapters": 10000, "recent_complete_chapters": 0,
        "max_characters": None, "queries": [], "guidance_mode": "COMBINED", "recent_tail_paragraphs": 4,
        "retrieval_passages": 12, "retrieval_per_chapter": 3, "neighbor_paragraphs": 1, "passage_characters": 512}
    sources = []
    for chapter, text in enumerate(("铜钥匙藏在窗下。\n\n这间屋子很安静。\n\n木匣留在后院。\n\n另一句未被选中的旧闻。",
        "他整夜没有说话。\n\n黎明时他推开了房门。"), 1):
        pointer = {"asset_version_id": f"selection-draft:{chapter}", "content_hash": canonical_hash({"chapter": chapter, "text": text})}
        sources.append({"chapter": chapter, **pointer, "text": text, "text_hash": prose_hash(text),
            "source_resolution": {"native_source": pointer, "effective_source": pointer, "native_basis": "NATIVE_DRAFT_OUTPUT", "overrides": []}})
    selection = select_working_context(sources, target_chapter=3, policy=policy, task=task)
    memory = compile_working_memory(sources, queries=[], max_characters=None, dependency_closed=True, recent_complete_from=3, task=task)
    projected = project_working_sources(sources, target_chapter=3, policy=policy, task=task, memory=memory)
    memory = bind_packet_coverage(memory, projected)
    snapshot = {"version": "working-manuscript-context.v1", **book, "target_chapter": 3, "accepted_through_chapter": 0,
        "authority": "AUTHOR_WORKING_PROSE_ONLY", "structured_facts": [], "projection_policy": policy,
        "instruction": working_instruction(policy), "retrieval_task": task, "context_selection": selection,
        "working_memory": memory, "source_history": freeze_source_history(projected, book=book, target_chapter=3),
        "sources": [row for row in projected if row["passages"]]}
    _rehash(snapshot)
    return snapshot


def _rehash_selection(snapshot, *, inner=True):
    selection = snapshot["context_selection"]
    if inner:
        retrieval = selection["retrieval"]
        retrieval["selection_hash"] = canonical_hash({key: value for key, value in retrieval.items() if key != "selection_hash"})
    selection["selection_hash"] = canonical_hash({key: value for key, value in selection.items() if key != "selection_hash"})
    _rehash(snapshot)


def test_working_selection_validates_inner_receipt_before_accepting_rehashed_outer_snapshot():
    from novel_forge.modules.book_authority.working_selection import validate_working_selection
    snapshot = _task_selection_snapshot()
    validate_working_projection(snapshot, project_id=snapshot["project_id"], book_id=snapshot["book_id"])
    snapshot["context_selection"]["retrieval"]["candidate_count"] += 1
    _rehash_selection(snapshot, inner=False)
    with pytest.raises(KernelError, match="WORKING_SELECTION_INVALID"):
        validate_working_selection(snapshot)


@pytest.mark.parametrize("mutation", ["contract", "count", "policy", "source", "query", "terms", "rank", "reason", "query_text"])
def test_rehashed_retrieval_receipt_cannot_change_its_contract_or_delivered_evidence(mutation):
    from novel_forge.modules.book_authority.working_selection import validate_working_selection
    snapshot = _task_selection_snapshot()
    selection = snapshot["context_selection"]
    retrieval = selection["retrieval"]
    hit = retrieval["selected"][0]
    if mutation == "contract":
        retrieval["contract_version"] = "invented-contract"
    elif mutation == "count":
        retrieval["candidate_count"] = retrieval["input_unit_count"] + 1
        retrieval["omitted_candidate_count"] = retrieval["candidate_count"] - len(retrieval["selected"])
    elif mutation == "policy":
        retrieval["selection_policy"]["per_chapter"] += 1
    elif mutation == "source":
        hit["text_hash"] = "sha256:" + "f" * 64
    elif mutation == "query":
        hit["matched_queries"] = ["queries/99"]
    elif mutation == "terms":
        hit["matched_terms"] = ["虚构"]
    elif mutation == "rank":
        hit["selection_rank"] = len(retrieval["selected"]) + 1
    elif mutation == "reason":
        passage = next(row for row in selection["passages"] if "TASK_RETRIEVAL" in row["reasons"])
        passage["reasons"] = ["SUPPORTING_NEIGHBOR"]
    else:
        retrieval["queries"][0]["text"] = "未冻结的另一项任务"
    _rehash_selection(snapshot)
    with pytest.raises(KernelError, match="WORKING_SELECTION_INVALID"):
        validate_working_selection(snapshot)


def test_working_selection_preserves_receipt_through_coalesced_and_provider_prose_projection():
    from novel_forge.modules.book_authority.working_prose import complete_prose_delivery
    from novel_forge.modules.book_authority.working_selection import validate_working_selection
    snapshot = _task_selection_snapshot()
    before = deepcopy(snapshot)
    delivered, receipt = complete_prose_delivery(snapshot)
    assert [source["chapter"] for source in receipt["coalesced_sources"]] == [2]
    assert len(delivered["sources"][1]["passages"]) == 1
    assert len(snapshot["sources"][1]["passages"]) == 2
    provider = project_working_history_for_provider(delivered)
    validate_working_selection(provider)
    assert provider["context_selection"] == delivered["context_selection"] == snapshot["context_selection"]
    assert provider["source_history"]["contract_version"] == "working-source-history-reference.v1"
    assert snapshot == before


def _current_task_policy():
    template = json.loads((Path(__file__).resolve().parents[2] / "config/execution_templates/creation_inputs.json").read_text())
    return deepcopy(template["profiles"]["production_profile"]["content"]["working_prose_policy"])


def _native_task_history(monkeypatch, target):
    uow, book, documents = _native_history(monkeypatch, target, tiny=True)
    book["input_snapshot_id"] = "task-input-snapshot"
    paragraphs = ["沈砚踏上石阶。", "两侧屋檐挡住了风。", "他把空碗摆回灶边。", "暮色落在门槛上。",
        "窗外有人挑着菜筐经过。", "脚步声渐渐远去。", "他掩住窗扇。", "屋内安静下来。"]
    for document in documents.values():
        document.content["text"] = "\n\n".join(paragraphs)
    clue = "沈砚把铜钥匙藏在东城水闸的石缝里。"
    documents[1].content["text"] = "\n\n".join([*paragraphs[:3], clue, *paragraphs[4:]])
    plans = {}

    def plan(kind, identity, content):
        value = SimpleNamespace(asset_type=kind, asset_version_id=identity, content_hash=canonical_hash(content),
            content=content, lifecycle="ACTIVE", eligibility="ELIGIBLE", governance="CLEAR")
        plans[identity] = value
        return value

    chapter_plan = plan("chapter_plan", f"task-plan:{target}", {"chapter_number": target, "chapter_intent": "沈砚寻找铜钥匙",
        "character_participation": [{"character_id": "actor:shen"}],
        "scene_plan": [{"scene_id": f"task-scene:{target}", "goal": "从东城水闸取回铜钥匙",
            "participants": ["actor:shen"], "pov_character_id": "actor:shen", "object_refs": ["铜钥匙"], "location_id": "东城水闸"}]})
    cast = plan("character_cast", "task-cast:1", {"book_id": book["book_id"], "characters": [
        {"character_id": "actor:shen", "name": "沈砚", "aliases": ["砚子"]},
        {"character_id": "actor:other", "name": "林岚", "aliases": []}]})
    arc = plan("arc_plan", "task-arc:1", {"target_window": {"from_chapter": 1, "to_chapter": 1000}, "objective": "查明旧案"})
    group = plan("chapter_group_plan", f"task-group:{target}", {"chapter_range": [target, target],
        "chapter_function_matrix": [{"chapter_number": target, "required_state_delta": {"summary": "取回铜钥匙"}}],
        "narrative_event_chain": [{"chapter_number": target, "event_id": f"planned:{target}", "actor_ref": "actor:shen", "action": "找到东城水闸"}]})
    state = {"sql": "", "parameters": [], "cast": {"role": "CHARACTER_CAST", "asset_version_id": cast.asset_version_id, "content_hash": cast.content_hash},
        "active_group": group, "denied": set(), "inactive_plans": set(), "memory_sidecars": {}}

    def execute(sql, parameters=None):
        state["sql"], state["parameters"] = sql, parameters or []

    def fetchone():
        if "SELECT foundation_set" in state["sql"]:
            return ({"bindings": [state["cast"]]},)
        if "SELECT EXISTS" in state["sql"]:
            denied = state["denied"] | (state["inactive_plans"] if any(value is True for value in state["parameters"]) else set())
            return (not any(value in denied for value in state["parameters"] if isinstance(value, str)),)
        raise AssertionError(f"Unscripted read-only query: {state['sql']}")

    def fetchall():
        if "active_story_plan_version" in state["sql"] and "CHAPTER_GROUP" in state["sql"]:
            active = state["active_group"]
            return [(active.asset_version_id, active.content_hash)]
        raise AssertionError(f"Unscripted read-only query: {state['sql']}")

    def require(**kwargs):
        if "logical_ref" in kwargs:
            sidecar = state["memory_sidecars"].get(kwargs["logical_ref"])
            if sidecar is None:
                raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "No optional memory annotation exists")
            return sidecar
        identity = kwargs["asset_version_id"]
        if identity in plans:
            return plans[identity]
        return next(document for document in documents.values() if document.asset_version_id == identity)

    uow.cursor.execute.side_effect = execute
    uow.cursor.fetchone.side_effect = fetchone
    uow.cursor.fetchall.side_effect = fetchall
    uow.repositories.asset_documents.require.side_effect = require
    return uow, book, documents, plans, state, chapter_plan, arc


def _freeze_native_task(uow, book, target, source, *, stage="CHAPTER", extra_sources=()):
    return manuscript.freeze_working_context(uow, book, target, projection_policy=_current_task_policy(),
        task_source_refs=[{"asset_version_id": item.asset_version_id, "content_hash": item.content_hash}
            for item in (source, *extra_sources)], task_stage=stage)


@pytest.mark.parametrize("target", [21, 130, 600])
def test_native_v9_task_freeze_recalls_old_evidence_with_empty_queries_and_missing_memory(monkeypatch, target):
    uow, book, documents, _, _, chapter_plan, _ = _native_task_history(monkeypatch, target)
    snapshot = _freeze_native_task(uow, book, target, chapter_plan)
    manuscript.verify_working_context(uow, book, snapshot)
    assert len(working_source_rows(snapshot)) == target - 1
    assert [source["asset_version_id"] for source in working_source_rows(snapshot)] == [f"native:{number}" for number in range(1, target)]
    assert snapshot["projection_policy"]["queries"] == [] and snapshot["working_memory"]["entries"] == []
    assert len(snapshot["working_memory"]["source_coverage"]) == target - 1
    assert {row["status"] for row in snapshot["working_memory"]["source_coverage"]} == {"MISSING"}
    assert [source["chapter"] for source in snapshot["sources"]] == [1, target - 1]
    assert {"actor:shen", "沈砚", "砚子"}.issubset(snapshot["retrieval_task"]["subjects"])
    assert "林岚" not in snapshot["retrieval_task"]["subjects"]
    literal = "".join(passage["text"] for source in snapshot["sources"] for passage in source["passages"])
    assert "沈砚把铜钥匙藏在东城水闸的石缝里。" in literal
    assert len(literal) < 150
    assert all(source["omitted_ranges"] for source in snapshot["sources"])
    for source in snapshot["sources"]:
        original = documents[source["chapter"]].content["text"]
        assert all(original[passage["start"]:passage["end"]] == passage["text"] for passage in source["passages"])
    validate_working_projection(project_working_history_for_provider(snapshot), project_id=book["project_id"], book_id=book["book_id"])


@pytest.mark.parametrize("mutation", ["source_hash", "cast_hash", "plan_hash", "task_fields", "score"])
def test_native_v9_verify_rejects_source_task_and_locally_rehashed_selection_drift(monkeypatch, mutation):
    uow, book, documents, plans, _, chapter_plan, _ = _native_task_history(monkeypatch, 21)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    if mutation == "source_hash":
        documents[1].content_hash = "changed-source"
    elif mutation == "cast_hash":
        plans["task-cast:1"].content_hash = "changed-cast"
    elif mutation == "plan_hash":
        chapter_plan.content_hash = "changed-plan"
    elif mutation == "task_fields":
        original = deepcopy(chapter_plan.content)
        chapter_plan.content["chapter_intent"] = "改去青石阁探访另一条线索"
        snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
        chapter_plan.content = original
    else:
        snapshot["context_selection"]["retrieval"]["selected"][0]["score"] += 1
        _rehash_selection(snapshot)
    with pytest.raises(KernelError, match="MANUSCRIPT_SOURCE_HASH_INVALID|MANUSCRIPT_DEPENDENCY_CHANGED|WORKING_TASK_SOURCE_CHANGED|WORKING_TASK_INVALID|WORKING_SELECTION_CHANGED"):
        manuscript.verify_working_context(uow, book, snapshot)


def test_native_v9_frozen_task_replays_historical_plan_version_without_admitting_it_as_current(monkeypatch):
    uow, book, _, _, _, chapter_plan, _ = _native_task_history(monkeypatch, 21)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    chapter_plan.lifecycle = "RETIRED"
    manuscript.verify_working_context(uow, book, snapshot, require_current=False)
    with pytest.raises(KernelError, match="WORKING_TASK_SOURCE_CHANGED"):
        manuscript.verify_working_context(uow, book, snapshot)


def test_native_v9_planning_freezes_current_group_and_cast_for_the_same_task(monkeypatch):
    uow, book, _, _, state, _, arc = _native_task_history(monkeypatch, 21)
    snapshot = _freeze_native_task(uow, book, 21, arc, stage="PLANNING", extra_sources=(state["active_group"],))
    manuscript.verify_working_context(uow, book, snapshot)
    task = snapshot["retrieval_task"]
    assert task["stage"] == "PLANNING"
    assert {source["asset_version_id"] for source in task["sources"]} == {arc.asset_version_id, "task-cast:1", state["active_group"].asset_version_id}
    assert "取回铜钥匙" in task["queries"]
    assert {"actor:shen", "沈砚"}.issubset(task["subjects"])
    assert 1 in {source["chapter"] for source in snapshot["sources"]}


def test_native_v9_rehashed_task_cannot_change_its_chapter_stage(monkeypatch):
    uow, book, _, _, _, chapter_plan, _ = _native_task_history(monkeypatch, 21)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    task = snapshot["retrieval_task"]
    task["stage"] = "PLANNING"
    task["task_hash"] = canonical_hash({key: value for key, value in task.items() if key != "task_hash"})
    snapshot["context_selection"]["task_hash"] = task["task_hash"]
    snapshot["context_selection"]["retrieval"]["task_hash"] = task["task_hash"]
    _rehash_selection(snapshot)
    with pytest.raises(KernelError, match="WORKING_TASK_INVALID|WORKING_TASK_STAGE_INVALID"):
        manuscript.verify_working_context(uow, book, snapshot)


@pytest.mark.parametrize("separator", ["\n", "\r\n\r\n", ""])
def test_native_v9_tail_uses_located_units_for_single_line_crlf_and_unbroken_long_prose(monkeypatch, separator):
    uow, book, documents, _, _, chapter_plan, _ = _native_task_history(monkeypatch, 21)
    paragraph = "沈砚望着窗外的长街，街上车马的声音逐渐安静下来。他收拾屋里的桌椅，让晚风带走屋内的烟气。" * 3
    original = separator.join(paragraph for _ in range(60))
    assert len(original) >= 5000
    documents[20].content["text"] = original
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    manuscript.verify_working_context(uow, book, snapshot)
    predecessor = next(source for source in snapshot["sources"] if source["chapter"] == 20)
    retained = "".join(passage["text"] for passage in predecessor["passages"])
    policy = snapshot["projection_policy"]
    assert len(retained) < len(original)
    assert len(retained) <= (policy["recent_tail_paragraphs"] + policy["neighbor_paragraphs"]) * policy["passage_characters"]
    assert retained.endswith(original[-20:]) and predecessor["omitted_ranges"]
    assert all(original[passage["start"]:passage["end"]] == passage["text"] for passage in predecessor["passages"])


def _native_causal_task(monkeypatch):
    uow, book, documents, plans, state, chapter_plan, arc = _native_task_history(monkeypatch, 21)
    quote = "守桥人抽掉了桥柱。" + "木梁在石壁间缓慢地摇晃，零落的瓦片沿着斜坡向下滑去。" * 40 + "那根桥柱再也没有装回去。"
    documents[1].content["text"] = "🙂天还没有亮。\n\n" + quote + "\n\n" + "院墙外的风一直没有停。" * 300
    first = normalize_observations([_task_note(quote, kind="EVENT", subject="守桥人", state_key="桥柱", claim="桥柱被移走。")], documents[1].content["text"])
    cause = first["entries"][0]["observation_id"]
    documents[1].content["working_memory"] = {"status": "LOCATED_UNREVIEWED", "observations": first}
    documents[2].content["text"] = "残余的支撑在暴雨里倒塌了。"
    second = normalize_observations([_task_note(documents[2].content["text"], kind="CONSEQUENCE", subject="旧桥", state_key="坍塌", causes=[cause])],
        documents[2].content["text"], available_causes={cause})
    documents[2].content["working_memory"] = {"status": "LOCATED_UNREVIEWED", "observations": second}
    consequence = second["entries"][0]["observation_id"]
    documents[20].content["text"] = "沈砚绕到了渡口。"
    last = normalize_observations([_task_note(documents[20].content["text"], subject="沈砚", causes=[consequence])],
        documents[20].content["text"], available_causes={consequence})
    documents[20].content["working_memory"] = {"status": "LOCATED_UNREVIEWED", "observations": last}
    return uow, book, documents, plans, state, chapter_plan, arc, quote, cause


def test_native_v9_closes_memory_causes_and_retains_exact_quotes_across_multiple_source_units(monkeypatch):
    uow, book, documents, _, _, chapter_plan, _, quote, _ = _native_causal_task(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    manuscript.verify_working_context(uow, book, snapshot)
    entries = snapshot["working_memory"]["entries"]
    assert {row["source"]["chapter"] for row in entries} == {1, 2, 20}
    cause_entry = next(row for row in entries if row["source"]["chapter"] == 1)
    assert cause_entry["quote"] == quote
    source = next(row for row in snapshot["sources"] if row["chapter"] == 1)
    overlaps = [passage for passage in source["passages"] if passage["start"] < cause_entry["location"]["end"] and cause_entry["location"]["start"] < passage["end"]]
    assert len(overlaps) >= 2
    reproduced = "".join(passage["text"][max(cause_entry["location"]["start"], passage["start"])-passage["start"]:
        min(cause_entry["location"]["end"], passage["end"])-passage["start"]] for passage in overlaps)
    assert reproduced == quote and quote in documents[1].content["text"]
    assert snapshot["working_memory"]["retrieval_omissions"] == []
    assert snapshot["working_memory"]["authority"] == "UNREVIEWED_WORKING_OBSERVATIONS"


def test_native_v9_rehashed_memory_cannot_remove_a_selected_cause_and_its_prose(monkeypatch):
    from novel_forge.modules.book_authority.working_prose import project_working_sources
    from novel_forge.modules.book_authority.working_selection import select_working_context
    from novel_forge.modules.narrative_state.working_memory import bind_packet_coverage
    uow, book, documents, _, _, chapter_plan, _, _, cause = _native_causal_task(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    packet = snapshot["working_memory"]
    packet["entries"] = [row for row in packet["entries"] if row["observation_id"] != cause]
    packet["omitted_observation_ids"].append(cause)
    raw = [{**source, "text": documents[source["chapter"]].content["text"]} for source in working_source_rows(snapshot)]
    policy, task = snapshot["projection_policy"], snapshot["retrieval_task"]
    snapshot["context_selection"] = select_working_context(raw, target_chapter=21, policy=policy, task=task, memory=packet)
    projected = project_working_sources(raw, target_chapter=21, policy=policy, task=task, memory=packet)
    snapshot["working_memory"] = bind_packet_coverage(packet, projected)
    snapshot["sources"] = [source for source in projected if source["passages"]]
    _rehash(snapshot)
    with pytest.raises(KernelError, match="WORKING_MEMORY_CAUSE_UNAVAILABLE"):
        manuscript.verify_working_context(uow, book, snapshot)


def test_scene_only_subject_selectors_recall_current_state_and_attributed_knowledge():
    from novel_forge.modules.narrative_state.working_memory import compile_working_memory
    sources = _scoped_memory_history()
    sources.append(_task_memory_source(600, [_task_note("林岚亲眼看见桥墩已经断裂。", kind="KNOWLEDGE", subject="桥墩", state_key="完整性", knowledge_owner="林岚")]))
    task = {"subjects": [], "scenes": [{"scene_id": "scene:linlan", "subjects": ["actor:linlan", "林岚"]}]}
    packet = compile_working_memory(sources, queries=[], max_characters=None, dependency_closed=True,
        recent_complete_from=599, task=task, selected_ranges={})
    assert {row["quote"] for row in packet["entries"]} == {"林岚留在城北。", "林岚亲眼看见桥墩已经断裂。"}
    knowledge = next(row for row in packet["entries"] if row["kind"] == "KNOWLEDGE")
    assert knowledge["perspective"] == "OBSERVED" and knowledge["knowledge_owner"] == "林岚"


def test_native_v9_planning_replay_obeys_current_group_binding_result_without_erasing_history(monkeypatch):
    uow, book, _, _, state, _, arc = _native_task_history(monkeypatch, 21)
    snapshot = _freeze_native_task(uow, book, 21, arc, stage="PLANNING", extra_sources=(state["active_group"],))
    state["inactive_plans"].add(state["active_group"].asset_version_id)
    with pytest.raises(KernelError, match="WORKING_TASK_SOURCE_SCOPE_INVALID"):
        manuscript.verify_working_context(uow, book, snapshot)
    manuscript.verify_working_context(uow, book, snapshot, require_current=False)


def _reproject_native_task_memory(snapshot, documents):
    from novel_forge.modules.book_authority.working_prose import project_working_sources
    from novel_forge.modules.book_authority.working_selection import select_working_context
    from novel_forge.modules.narrative_state.working_memory import bind_packet_coverage
    raw = [{**source, "text": documents[source["chapter"]].content["text"]} for source in working_source_rows(snapshot)]
    policy, task, packet = snapshot["projection_policy"], snapshot["retrieval_task"], snapshot["working_memory"]
    snapshot["context_selection"] = select_working_context(raw, target_chapter=snapshot["target_chapter"], policy=policy, task=task, memory=packet)
    projected = project_working_sources(raw, target_chapter=snapshot["target_chapter"], policy=policy, task=task, memory=packet)
    snapshot["working_memory"] = bind_packet_coverage(packet, projected)
    snapshot["sources"] = [source for source in projected if source["passages"]]
    _rehash(snapshot)


@pytest.mark.parametrize("require_current", [True, False])
def test_native_v9_replay_rejects_omitting_every_memory_seed_after_rehashing_all_packets(monkeypatch, require_current):
    uow, book, documents, _, _, chapter_plan, _, _, _ = _native_causal_task(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    packet = snapshot["working_memory"]
    assert len(packet["entries"]) == 3
    packet["omitted_observation_ids"].extend(row["observation_id"] for row in packet["entries"])
    packet["entries"] = []
    _reproject_native_task_memory(snapshot, documents)
    validate_working_projection(snapshot, project_id=book["project_id"], book_id=book["book_id"])
    with pytest.raises(KernelError, match="WORKING_MEMORY_SELECTION_CHANGED"):
        manuscript.verify_working_context(uow, book, snapshot, require_current=require_current)


def _native_memory_sidecar(book, source, identity, notes):
    from novel_forge.modules.book_authority.manuscript_memory import memory_ref
    observations = normalize_observations(notes, source.content["text"])
    content = {"version": "manuscript-memory-sidecar.v1", "book_run_id": book["book_run_id"],
        "project_id": book["project_id"], "book_id": book["book_id"], "chapter": source.content["chapter"],
        "source_asset_version_id": source.asset_version_id, "source_content_hash": source.content_hash,
        "observations": observations, "source_kind": "AUTHOR_ANNOTATION", "actor_id": "test-author",
        "formal_acceptance": "NOT_GRANTED"}
    return SimpleNamespace(asset_type="manuscript_memory", asset_version_id=identity,
        logical_ref=memory_ref(book, source.asset_version_id), content_hash=canonical_hash(content), content=content)


def _native_omitted_memory_sidecar(monkeypatch):
    uow, book, documents, plans, state, chapter_plan, _ = _native_task_history(monkeypatch, 21)
    quote = documents[3].content["text"].split("\n\n")[2]
    sidecar = _native_memory_sidecar(book, documents[3], "annotation:3:old",
        [_task_note(quote, kind="EVENT", subject="林岚", state_key="空碗", claim="她把空碗摆回灶边。")])
    plans[sidecar.asset_version_id] = sidecar
    state["memory_sidecars"][sidecar.logical_ref] = sidecar
    return uow, book, documents, plans, state, chapter_plan, sidecar


def test_native_v9_replays_entirely_omitted_sidecar_version_without_reading_its_replacement(monkeypatch):
    uow, book, documents, plans, state, chapter_plan, sidecar = _native_omitted_memory_sidecar(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    packet = snapshot["working_memory"]
    assert packet["entries"] == [] and packet["candidate_count"] == 1
    assert packet["omitted_observation_ids"] == [sidecar.content["observations"]["entries"][0]["observation_id"]]
    assert 3 not in {row["chapter"] for row in snapshot["sources"]}
    coverage = next(row for row in packet["source_coverage"] if row["chapter"] == 3)
    assert coverage["memory_source"] == {"version": "working-memory-source.v1", "kind": "MANUSCRIPT_MEMORY",
        "asset_version_id": sidecar.asset_version_id, "content_hash": sidecar.content_hash,
        "observations_hash": canonical_hash(sidecar.content["observations"])}
    replacement = _native_memory_sidecar(book, documents[3], "annotation:3:new",
        [_task_note(documents[3].content["text"].split("\n\n")[2], subject="沈砚")])
    plans[replacement.asset_version_id] = replacement
    state["memory_sidecars"][sidecar.logical_ref] = replacement
    uow.repositories.asset_documents.require.reset_mock()
    manuscript.verify_working_context(uow, book, snapshot, require_current=False)
    reads = [call.kwargs for call in uow.repositories.asset_documents.require.call_args_list]
    assert any(row.get("asset_version_id") == sidecar.asset_version_id for row in reads)
    assert all("logical_ref" not in row and row.get("asset_version_id") != replacement.asset_version_id for row in reads)
    updated = _freeze_native_task(uow, book, 21, chapter_plan)
    assert [row["provenance"]["asset_version_id"] for row in updated["working_memory"]["entries"]] == [replacement.asset_version_id]
    assert updated["snapshot_hash"] != snapshot["snapshot_hash"]


@pytest.mark.parametrize("mutation", ["reference_removed", "content_hash", "observations_hash", "status", "source_binding"])
def test_native_v9_replay_validates_even_a_sidecar_with_no_selected_entries(monkeypatch, mutation):
    uow, book, documents, _, _, chapter_plan, sidecar = _native_omitted_memory_sidecar(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    assert snapshot["working_memory"]["entries"] == []
    coverage = next(row for row in snapshot["working_memory"]["source_coverage"] if row["chapter"] == 3)
    if mutation == "reference_removed":
        del coverage["memory_source"]
    elif mutation == "content_hash":
        coverage["memory_source"]["content_hash"] = "sha256:" + "0" * 64
    elif mutation == "observations_hash":
        coverage["memory_source"]["observations_hash"] = canonical_hash(None)
    elif mutation == "status":
        coverage["status"] = "MISSING"
    else:
        sidecar.content["source_asset_version_id"] = documents[4].asset_version_id
    _reproject_native_task_memory(snapshot, documents)
    with pytest.raises(KernelError, match="WORKING_MEMORY_SOURCE_INVALID|WORKING_MEMORY_SELECTION_CHANGED"):
        manuscript.verify_working_context(uow, book, snapshot, require_current=False)


@pytest.mark.parametrize("status", ["MISSING", "UNAVAILABLE", "NOT_REQUESTED"])
def test_native_v9_freezes_absent_or_unavailable_draft_memory_without_changing_prose(monkeypatch, status):
    uow, book, documents, _, _, chapter_plan, _ = _native_task_history(monkeypatch, 21)
    baseline = _freeze_native_task(uow, book, 21, chapter_plan)
    documents[3].content["working_memory"] = {"status": status}
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    coverage = next(row for row in snapshot["working_memory"]["source_coverage"] if row["chapter"] == 3)
    assert coverage["status"] == status
    assert coverage["memory_source"] == {"version": "working-memory-source.v1", "kind": "WRITER_SELF_OBSERVATION",
        "asset_version_id": documents[3].asset_version_id, "content_hash": documents[3].content_hash,
        "observations_hash": canonical_hash(None)}
    assert snapshot["sources"] == baseline["sources"] and snapshot["context_selection"] == baseline["context_selection"]
    uow.repositories.asset_documents.require.reset_mock()
    manuscript.verify_working_context(uow, book, snapshot, require_current=False)
    assert all("logical_ref" not in call.kwargs for call in uow.repositories.asset_documents.require.call_args_list)


def test_v9_auxiliary_refs_include_fully_omitted_sidecar_without_duplicating_writer_sources(monkeypatch):
    from novel_forge.modules.book_authority.working_prose import working_auxiliary_source_refs
    uow, book, documents, _, _, chapter_plan, sidecar = _native_omitted_memory_sidecar(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    before = deepcopy(snapshot)
    assert snapshot["working_memory"]["entries"] == [] and 3 not in {row["chapter"] for row in snapshot["sources"]}
    expected = [{key: source[key] for key in ("asset_version_id", "content_hash")} for source in snapshot["retrieval_task"]["sources"]]
    expected.append({"asset_version_id": sidecar.asset_version_id, "content_hash": sidecar.content_hash})
    assert working_auxiliary_source_refs(snapshot) == expected
    assert not {source["asset_version_id"] for source in expected}.intersection(document.asset_version_id for document in documents.values())
    assert snapshot == before
    snapshot["retrieval_task"]["sources"].append(deepcopy(snapshot["retrieval_task"]["sources"][0]))
    snapshot["working_memory"]["source_coverage"].append(deepcopy(next(
        row for row in snapshot["working_memory"]["source_coverage"] if row["chapter"] == 3)))
    assert working_auxiliary_source_refs(snapshot) == expected


def test_v9_auxiliary_refs_reject_conflicting_hashes_for_the_same_version(monkeypatch):
    from novel_forge.modules.book_authority.working_prose import working_auxiliary_source_refs
    uow, book, _, _, _, chapter_plan, sidecar = _native_omitted_memory_sidecar(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    snapshot["retrieval_task"]["sources"].append({"asset_version_id": sidecar.asset_version_id, "content_hash": "conflicting-hash"})
    with pytest.raises(KernelError, match="WORKING_AUXILIARY_SOURCE_CONFLICT"):
        working_auxiliary_source_refs(snapshot)


@pytest.mark.parametrize("version", [None, *[f"working-prose-projection.v{number}" for number in range(2, 9)]])
def test_legacy_auxiliary_refs_preserve_the_existing_input_contract(version):
    from novel_forge.modules.book_authority.working_prose import working_auxiliary_source_refs
    assert working_auxiliary_source_refs(None) == []
    snapshot = {"projection_policy": {"version": version}, "retrieval_task": {"sources": [
        {"asset_version_id": "should-not-be-admitted", "content_hash": "legacy"}]}}
    assert working_auxiliary_source_refs(snapshot) == []


def _native_v9_context_role_request(monkeypatch):
    from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest, ChapterInputAsset
    uow, book, _, plans, _, chapter_plan, sidecar = _native_omitted_memory_sidecar(monkeypatch)
    snapshot = _freeze_native_task(uow, book, 21, chapter_plan)
    normalized = {"type": "AuthoritativeChapterPlan", "contract_version": "authoritative-chapter-plan-v4",
        "project_id": book["project_id"], "book_id": book["book_id"], "chapter": 21,
        "source_chapter_plan_asset_version_id": chapter_plan.asset_version_id,
        "source_chapter_plan_content_hash": chapter_plan.content_hash}
    cast = plans["task-cast:1"]
    inputs = (ChapterInputAsset(chapter_plan.asset_version_id, chapter_plan.asset_type, chapter_plan.content_hash, chapter_plan.content),
        ChapterInputAsset("normalized-plan:21", "chapter_plan", canonical_hash(normalized), normalized),
        ChapterInputAsset(cast.asset_version_id, cast.asset_type, cast.content_hash, cast.content),
        ChapterInputAsset(sidecar.asset_version_id, sidecar.asset_type, sidecar.content_hash, sidecar.content))
    return ChapterHandlerRequest(operation_id="role-test", project_id=book["project_id"], workspace_id=book["workspace_id"],
        trace_id="role-trace", correlation_id="role-correlation", inputs=inputs,
        command={"chapter": 21, "book_id": book["book_id"], "preparation_report": {"working_manuscript": snapshot},
            "context_candidates": [{"asset_version_id": item.asset_version_id, "asset_type": item.asset_type,
                "content_hash": item.content_hash} for item in (inputs[0], inputs[2])]})


@pytest.mark.parametrize("node_name", ["CONTEXT", "EXECUTION_INTENT"])
def test_v9_auxiliary_roles_select_normalized_plan_after_original_and_preserve_cast_candidate(monkeypatch, node_name):
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.chapter_authority.runtime import bind_working_context_sources
    request = _native_v9_context_role_request(monkeypatch)
    before = deepcopy(request)
    rebound = bind_working_context_sources(request, ChapterNode[node_name])
    assert rebound.require_input("chapter_plan") == request.inputs[1]
    assert [item.input_type for item in rebound.inputs] == [
        "working_context_source", "chapter_plan", "character_cast", "working_context_source"]
    assert [(item.asset_type, item.asset_version_id, item.content_hash, item.content) for item in rebound.inputs] == [
        (item.asset_type, item.asset_version_id, item.content_hash, item.content) for item in before.inputs]
    assert request == before and bind_working_context_sources(rebound, ChapterNode[node_name]) == rebound


@pytest.mark.parametrize("field", ["source_chapter_plan_asset_version_id", "source_chapter_plan_content_hash"])
def test_v9_auxiliary_roles_reject_normalization_from_a_different_frozen_plan(monkeypatch, field):
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.chapter_authority.runtime import bind_working_context_sources
    request = _native_v9_context_role_request(monkeypatch)
    request.inputs[1].content[field] = "different-plan-source"
    with pytest.raises(KernelError, match="WORKING_TASK_SOURCE_SCOPE_INVALID"):
        bind_working_context_sources(request, ChapterNode.CONTEXT)


def test_v9_auxiliary_role_binding_leaves_other_nodes_and_legacy_requests_unchanged(monkeypatch):
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    from novel_forge.modules.chapter_authority.runtime import bind_working_context_sources
    request = _native_v9_context_role_request(monkeypatch)
    assert bind_working_context_sources(request, ChapterNode.DRAFT) is request
    request.command["preparation_report"]["working_manuscript"]["projection_policy"]["version"] = "working-prose-projection.v8"
    assert bind_working_context_sources(request, ChapterNode.CONTEXT) is request


def test_v9_capacity_rebuild_binds_auxiliary_roles_before_direct_context_execution(monkeypatch):
    from dataclasses import replace
    from novel_forge.modules.chapter_authority import capacity_continuation
    from novel_forge.modules.chapter_authority.contracts import ChapterNode
    request = _native_v9_context_role_request(monkeypatch)
    references = [{"asset_version_id": item.asset_version_id, "content_hash": item.content_hash} for item in request.inputs]
    proof = {"source_operation_id": "frozen-context-producer", "command_hash": canonical_hash(request.command), "input_snapshot": references}
    upgrade = {"context_source": proof, "successor_operation_id": "capacity-successor", "policy_hash": "frozen-capacity-policy"}
    request = replace(request, capacity_upgrade=upgrade)
    before = deepcopy(request)
    uow = MagicMock()
    uow.cursor.execute.return_value = uow.cursor
    uow.cursor.fetchone.side_effect = [(deepcopy(request.command), references),
        *[(item.asset_type, deepcopy(item.content)) for item in request.inputs]]
    manager = MagicMock()
    manager.__enter__.return_value = uow
    monkeypatch.setattr("novel_forge.storage.authority_uow.AuthorityUnitOfWork", lambda _: manager)
    monkeypatch.setattr(capacity_continuation, "_verify_context_sources", lambda *_: None)
    registry = MagicMock()

    def execute(frozen):
        assert frozen.operation_id == upgrade["successor_operation_id"]
        assert frozen.require_input("chapter_plan").asset_version_id == "normalized-plan:21"
        assert [item.input_type for item in frozen.inputs] == [
            "working_context_source", "chapter_plan", "character_cast", "working_context_source"]
        return SimpleNamespace(content={"context_manifest": {"task_context_receipt": {}}, "selected_plan": "normalized-plan:21"})

    registry.require.return_value.execute.side_effect = execute
    rebound = capacity_continuation.rebuild_frozen_capacity_context(request, registry)
    registry.require.assert_called_once_with(ChapterNode.CONTEXT)
    assert rebound.capacity_context_derivation["content"]["selected_plan"] == "normalized-plan:21"
    assert rebound.capacity_context_derivation["source"] == proof and request == before
