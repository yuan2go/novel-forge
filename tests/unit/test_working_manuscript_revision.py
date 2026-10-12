from copy import deepcopy
from types import SimpleNamespace

import pytest

from novel_forge.modules.chapter_authority.working_revision import (
    CONTRACT, NODES, ROOT_VERSION, require_working_revision_frontier, working_revision_definition,
)
from novel_forge.modules.command_kernel.errors import KernelError


def frontier(monkeypatch, *, cancelled=False, state="READY", workspace="workspace", selected="draft"):
    from novel_forge.modules.book_authority import manuscript
    book = {"book_run_id": "run", "project_id": "project", "workspace_id": workspace,
        "book_id": "book", "state": state, "current_chapter": 1, "accepted_through_chapter": 0}
    source = SimpleNamespace(asset_version_id=selected, content_hash="sha256:" + "a" * 64)
    monkeypatch.setattr(manuscript, "effective_workflow", lambda *args: manuscript.AUTHOR_WORKFLOW)
    monkeypatch.setattr(manuscript, "selected_source", lambda *args: source)
    inputs = {key: {"asset_version_id": key, "content_hash": source.content_hash} for key in ("draft", "context", "plan")}
    binding = {"contract_version": CONTRACT, "book_run_id": "run", "source_asset_version_id": "draft",
        "source_content_hash": source.content_hash, "source_inputs": inputs, "previous_sources": []}
    root = {"definition_name": "chapter.slice.run", "definition_version": ROOT_VERSION,
        "definition_snapshot": {"policy": {"working_revision_contract": CONTRACT}},
        "project_id": "project", "workspace_id": "workspace",
        "command_payload": {"chapter": 1, "book_id": "book", "preparation_report": {"working_revision": binding}},
        "input_asset_snapshot": list(inputs.values())}
    class Cursor:
        def execute(self, sql, params):
            assert params == ["run", "project"]
        def fetchone(self):
            return book, cancelled
    return SimpleNamespace(cursor=Cursor()), root, source


def test_revision_requires_current_same_book_source_without_granting_acceptance(monkeypatch):
    uow, root, source = frontier(monkeypatch)
    book, actual = require_working_revision_frontier(uow, root=root)
    assert actual is source and book["accepted_through_chapter"] == 0
    original = deepcopy(root)
    require_working_revision_frontier(uow, root=root)
    assert root == original


def test_completed_revision_cannot_activate_after_earlier_selection_changes(monkeypatch):
    from novel_forge.modules.book_authority import manuscript
    uow, root, source = frontier(monkeypatch)
    root["status"] = "SUCCEEDED"
    root["command_payload"]["preparation_report"]["working_revision"]["previous_sources"] = [
        {"chapter": 1, "asset_version_id": "previous-old", "content_hash": source.content_hash}]
    root["command_payload"]["chapter"] = 2
    book = uow.cursor.fetchone()[0]
    book["current_chapter"] = 2
    monkeypatch.setattr(manuscript, "selected_source", lambda uow, book, chapter:
        source if chapter == 2 else SimpleNamespace(asset_version_id="previous-new", content_hash=source.content_hash))
    with pytest.raises(KernelError, match="earlier prose changed"):
        require_working_revision_frontier(uow, root=root)


@pytest.mark.parametrize("kind,severity,status,blocked", [
    ("SEMANTIC_CONTRADICTION", "major", "OPEN", True),
    ("SEMANTIC_CONTRADICTION", "major", "RESOLVED", False),
    ("LIKELY_CONTINUITY_PROBLEM", "major", "OPEN", False),
    ("AESTHETIC_SUGGESTION", "major", "OPEN", False),
])
def test_only_unresolved_explicit_major_contradiction_blocks_propagation(kind, severity, status, blocked):
    from novel_forge.modules.book_authority.manuscript import require_prose_propagation
    from novel_forge.modules.review.diagnostics import prose_hash
    review = {"target_asset_version_id": "draft", "target_text_hash": prose_hash("真实正文"),
        "issues": [{"code": "problem", "judgment_kind": kind, "severity": severity, "status": status}]}
    class Cursor:
        def execute(self, sql, params):
            assert params == ["project", "draft"]
        def fetchall(self):
            return [(review,)]
    source = SimpleNamespace(asset_version_id="draft", asset_type="draft_chapter", content={"text": "真实正文"})
    if blocked:
        with pytest.raises(KernelError, match="Retain this complete candidate"):
            require_prose_propagation(SimpleNamespace(cursor=Cursor()), {"project_id": "project"}, source)
    else:
        require_prose_propagation(SimpleNamespace(cursor=Cursor()), {"project_id": "project"}, source)
    assert source.content == {"text": "真实正文"}


@pytest.mark.parametrize("change", [{"cancelled": True}, {"state": "PAUSED"}, {"state": "ABORTED"},
    {"workspace": "foreign"}, {"selected": "newer-draft"}])
def test_revision_does_not_cross_cancellation_scope_or_newer_selection(monkeypatch, change):
    uow, root, _ = frontier(monkeypatch, **change)
    with pytest.raises(KernelError):
        require_working_revision_frontier(uow, root=root)


def test_working_revision_is_existing_review_revision_selection_without_foundation_or_canon():
    definition = working_revision_definition(application_build_id="test", commit_sha="a" * 40)
    assert definition["policy"]["expected_saga_steps"] == 4
    assert [row["definition_name"] for row in definition["completion_contract"]["required_child_operations"]] == [node.definition_name for node in NODES]
    schema = definition["command_schema"]["properties"]["preparation_report"]["properties"]["working_revision"]
    assert schema["properties"]["formal_acceptance"] == {"const": "NOT_GRANTED"}


def test_working_review_window_keeps_actual_unaccepted_cursor_and_exact_text_support():
    from tests.unit.test_cross_chapter_prose_review import source_snapshot, SOURCE, TARGET
    from novel_forge.modules.review.prose_window import WORKING_WINDOW_POLICY, WORKING_WINDOW_CONTRACT, digest, freeze_review_window, validate_support
    value = source_snapshot()
    value.update(contract_version="selected-working-prose-snapshot.v1", accepted_through_chapter=0,
        working_through_chapter=1, source_isolation="SELECTED_PROSE_NO_CANON_AUTHORITY")
    value["window_policy"]["version"] = WORKING_WINDOW_POLICY
    source = value["sources"][0]
    source.pop("acceptance_operation_id")
    source.pop("acceptance_status")
    source["source_status"] = "SELECTED_WORKING_PROSE"
    value["snapshot_hash"] = digest({key: content for key, content in value.items() if key != "snapshot_hash"})
    window = freeze_review_window(value, candidate_id="current", text=TARGET,
        context_token_budget=16000, protected_context={})
    assert window["contract_version"] == WORKING_WINDOW_CONTRACT
    assert window["accepted_through_chapter"] == 0 and window["working_through_chapter"] == 1
    support = {"asset_version_id": source["asset_version_id"], "text_hash": source["text_hash"],
        "chapter_number": 1, "relation_to_issue": "Previous injury and spent resource constrain the current action",
        "start": 0, "end": len(SOURCE), "quote": SOURCE}
    assert validate_support([support], window)[0]["quote"] == SOURCE
    with pytest.raises(KernelError):
        validate_support([{**support, "quote": "forged earlier prose"}], window)
