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
    monkeypatch.setattr(manuscript, "require_prose_propagation", lambda *_: None)
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
    assert policy["version"] == LONGFORM_POLICY_VERSION and policy["history_chapters"] == 128


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
