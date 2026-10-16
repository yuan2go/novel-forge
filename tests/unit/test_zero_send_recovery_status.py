from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_planning_runtime import runtime_continuation as runtime


@pytest.mark.parametrize("operation_status", ["FAILED_FINAL", "FAILED_RETRYABLE"])
def test_chapter_capacity_uses_attempt_failure_without_relabeling_terminal_operation(monkeypatch, operation_status):
    frozen = {"project_id": "project", "workspace_id": "workspace", "book_id": "book",
              "execution_contract_version": "1.21.0", "generator_operation_name": "chapter_plan.generate",
              "world_preparation_request": {"source": "world"}, "runtime_continuation_id": "prior"}
    failure = {"error_code": "CONTEXT_CAPACITY_EXCEEDED", "failure_class": "retryable",
               "error_message": "CONTEXT_CAPACITY_EXCEEDED: Complete input leaves no model context for generation"}
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(operation_status, 9, "workspace", frozen, "book", None), None,
                                   ("FAILED_RETRYABLE", {}, failure)]
    captured = []
    monkeypatch.setattr(runtime, "_pre_send_capacity_source", lambda *args, **kwargs: captured.append(kwargs) or {"source": "exact"})
    assert runtime.require_source(SimpleNamespace(cursor=cursor), source_operation_id="source", project_id="project") == {"source": "exact"}
    assert captured[0]["row"][0] == operation_status
    assert captured[0]["attempt"][0] == "FAILED_RETRYABLE"
    assert captured[0]["rendered_chapter_capacity_failure"] is True


def test_unknown_operation_cannot_enter_zero_send_capacity_recovery():
    cursor = MagicMock()
    cursor.fetchone.return_value = ("UNKNOWN", 9, "workspace", {}, "book", None)
    with pytest.raises(KernelError, match="SOURCE_INVALID"):
        runtime.require_source(SimpleNamespace(cursor=cursor), source_operation_id="source", project_id="project")
