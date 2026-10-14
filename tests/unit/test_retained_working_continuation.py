from copy import deepcopy
import json

import pytest

from novel_forge.modules.book_authority.retained_working import require_empty_discovery_trace
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.reader_calibration.manuscript_blind import extract_manuscript_chapter


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
