from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.book_authority.retained_working import require_empty_discovery_trace
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration.manuscript_blind import extract_manuscript_chapter
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from tests.unit.test_author_length_binding import context as length_context
from tests.unit.test_converged_provider_inputs import _materialize
from tests.unit.test_longform_working_history import _policy


def trace():
    events = [{"type": "thread.started"}, {"type": "turn.started"}]
    for index, (tool, result) in enumerate([("list_mcp_resources", {"resources": []}),
                                           ("list_mcp_resource_templates", {"resourceTemplates": []})]):
        item = {"id": str(index), "type": "mcp_tool_call", "server": "codex", "tool": tool,
                "arguments": {}, "result": None, "error": None, "status": "in_progress"}
        events.append({"type": "item.started", "item": deepcopy(item)})
        item.update(status="completed", result={"content": [{"type": "text", "text": json.dumps(result)}], "structured_content": None})
        events.append({"type": "item.completed", "item": item})
    return [*events, {"type": "turn.completed"}]


def encode(events):
    return "\n".join(json.dumps(event) for event in events)


def test_empty_discovery_is_only_a_working_use_observation_not_permission_success():
    proof = require_empty_discovery_trace(encode(trace()))
    assert proof["external_resource_count"] == 0 and len(proof["calls"]) == 2
    assert proof["permission_gate"] == "VIOLATED_UNCHANGED"


@pytest.mark.parametrize("mutation", ["resource", "another_tool", "unknown_tool", "error", "incomplete", "duplicate", "extra_result", "late_failure"])
def test_other_tools_resources_and_incomplete_discovery_remain_ineligible(mutation):
    events = trace()
    if mutation == "resource":
        events[3]["item"]["result"]["content"][0]["text"] = '{"resources":[{"uri":"private-source"}]}'
    elif mutation == "another_tool":
        events[3]["item"]["tool"] = "read_mcp_resource"
    elif mutation == "unknown_tool":
        events.insert(-1, {"type": "item.completed", "item": {"type": "future_external_tool"}})
    elif mutation == "error":
        events[3]["item"]["error"] = "unknown remote result"
    elif mutation == "incomplete":
        events.pop(3)
    elif mutation == "duplicate":
        events.insert(4, deepcopy(events[3]))
    elif mutation == "extra_result":
        events[3]["item"]["result"]["other_source"] = "untracked evidence"
    else:
        events.append({"type": "turn.failed"})
    with pytest.raises(KernelError, match="RETAINED_WORKING_TOOL_TRACE_UNSAFE"):
        require_empty_discovery_trace(encode(events))


def test_retained_reading_preserves_text_without_claiming_a_compliant_writer_result():
    source = {"contract_version": "retained-working-continuation.v1", "chapter": 1,
              "title": "第一章", "text": "未接纳的原稿仍然保留。",
              "retained_working_provenance": {"source_permission_gate": "FAILED_FINAL"}}
    row = extract_manuscript_chapter(asset_type="retained_working_prose", content=source, chapter_number=1, selector="/text")
    assert row["text"] == source["text"]
    source["retained_working_provenance"]["source_permission_gate"] = "SUCCEEDED"
    with pytest.raises(ValueError, match="MANUSCRIPT_RETAINED_SOURCE_INVALID"):
        extract_manuscript_chapter(asset_type="retained_working_prose", content=source, chapter_number=1, selector="/text")


@pytest.mark.parametrize("field,value", [("governance", "BLOCKED"), ("eligibility", "INELIGIBLE"),
                                          ("lifecycle", "RETIRED"), ("content_hash", "sha256:changed")])
def test_withdrawn_original_inputs_cannot_be_laundered_as_new_working_prose(field, value):
    from types import SimpleNamespace
    from novel_forge.modules.book_authority.retained_working import _require_governed
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash

    content = {"text": "原始正文"}
    document = SimpleNamespace(content=content, content_hash=canonical_hash(content), governance="CLEAR",
                               eligibility="ELIGIBLE", lifecycle="ACTIVE")
    setattr(document, field, value)
    with pytest.raises(KernelError, match="RETAINED_WORKING_INPUT_CHANGED"):
        _require_governed(document)


def _retained_store():
    book = {"project_id": "project", "workspace_id": "workspace", "book_id": "book",
            "book_run_id": "run", "accepted_through_chapter": 0}
    content = {"contract_version": "retained-working-continuation.v1", "project_id": "project",
               "book_id": "book", "chapter": 1, "title": "原始工作稿", "text": "她已经拒绝过这个条件，下一次选择须从后果开始。",
               "retained_working_provenance": {"source_permission_gate": "FAILED_FINAL",
                   "source_failure_code": "MODEL_EFFECT_FINAL_UNAUTHORIZED_TOOL_INVOCATION",
                   "formal_acceptance": "NOT_GRANTED", "author_acceptance": "NOT_GRANTED", "provider_calls": 0}}
    document = SimpleNamespace(asset_version_id="retained:1", content_hash=canonical_hash(content),
                               content=content, asset_type="retained_working_prose", governance="CLEAR", eligibility="ELIGIBLE")
    uow = MagicMock()

    def execute(statement, parameters):
        uow.cursor.fetchone.return_value = None
        uow.cursor.fetchall.return_value = []
        if "SELECT working_asset_version_id FROM authority_book_retained_working_continuation" in statement:
            assert parameters == [book["book_run_id"], 1]
            uow.cursor.fetchone.return_value = (document.asset_version_id,)
        elif "SELECT chapter_number,working_asset_version_id,context_snapshot" in statement:
            assert parameters == [book["book_run_id"]]
            uow.cursor.fetchall.return_value = [(1, document.asset_version_id, {"sources": []})]
        return uow.cursor

    def require(**arguments):
        assert arguments["project_id"] == book["project_id"]
        if arguments.get("asset_version_id") == document.asset_version_id:
            return document
        raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "No selection, editor or annotation overrides")

    uow.cursor.execute.side_effect = execute
    uow.repositories.asset_documents.require.side_effect = require
    return uow, book, document


@pytest.mark.parametrize("version", ["working-prose-projection.v4", "working-prose-projection.v5"])
def test_retained_native_source_freezes_and_reaches_writer_without_acceptance(monkeypatch, version):
    from novel_forge.modules.book_authority import manuscript

    def forbidden(*args, **kwargs):
        raise AssertionError("Retained source projection cannot invoke external I/O")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("psycopg.connect", forbidden)
    uow, book, document = _retained_store()
    original_content = deepcopy(document.content)
    source, resolution = manuscript.resolve_working_source(uow, book, 1)
    assert source is document and resolution["native_basis"] == "RETAINED_WORKING_CONTINUATION"
    snapshot = manuscript.freeze_working_context(uow, book, 2, projection_policy=_policy(version=version))
    manuscript.verify_working_context(uow, book, snapshot)
    context = length_context()
    context.update(project_id="project", book_id="book", chapter=2,
                   accepted_boundary={"accepted_through_chapter": 0}, working_manuscript=snapshot)
    _, evidence, envelope, _ = _materialize("draft", {"plan": {"chapter": 2}, "style": {},
        "chapter_memo": {}, "realization_contract": {}}, context, writer=True)
    delivered = envelope["context_bundle"]["working_manuscript"]
    assert delivered["sources"] == snapshot["sources"]
    assert delivered["sources"][0]["source_resolution"] == resolution
    assert delivered["sources"][0]["passages"][0]["text"] == document.content["text"]
    assert delivered["accepted_through_chapter"] == 0 and delivered["structured_facts"] == []
    assert document.content == original_content and source.content["retained_working_provenance"]["source_permission_gate"] == "FAILED_FINAL"
    if version.endswith(".v5"):
        assert evidence["provider_view"]["working_history_transport"]["projections"]
    else:
        assert "working_history_transport" not in evidence["provider_view"]
