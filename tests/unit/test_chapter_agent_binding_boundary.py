from __future__ import annotations

from unittest.mock import Mock

import pytest

from novel_forge.modules.agent_runtime.chapter_binding import (
    AGENT_BOUND_CHAPTER_STAGES,
    PostgresChapterAgentBindingRecorder,
)
from novel_forge.modules.chapter_authority.contracts import ChapterHandlerRequest
from novel_forge.modules.command_kernel.errors import KernelError


def _request() -> ChapterHandlerRequest:
    return ChapterHandlerRequest(
        operation_id="operation:chapter:1",
        project_id="project:1",
        workspace_id="workspace:1",
        trace_id="trace:1",
        correlation_id="correlation:1",
        command={},
        inputs=(),
        attempt_id="attempt:1",
        fencing_token=1,
        worker_id="worker:1",
    )


def test_controlled_unmigrated_stage_fails_closed_before_pep_dispatch() -> None:
    recorder = PostgresChapterAgentBindingRecorder(
        "postgresql://unused",
        bound_stages=frozenset({"draft"}),
        required_stages=frozenset({"draft"}),
        compatibility_allowed=False,
    )

    with pytest.raises(KernelError) as raised:
        recorder.freeze(_request(), stage="review", execution_binding=Mock())

    assert raised.value.code == "CHAPTER_AGENT_STAGE_NOT_MIGRATED"


def test_development_compatibility_is_explicitly_recorded() -> None:
    recorder = PostgresChapterAgentBindingRecorder(
        "postgresql://unused",
        bound_stages=frozenset({"draft"}),
        compatibility_allowed=True,
    )
    recorder.record_compatibility_usage = Mock()  # type: ignore[method-assign]

    result = recorder.freeze(
        _request(), stage="review", execution_binding=Mock()
    )

    assert result is None
    recorder.record_compatibility_usage.assert_called_once_with(  # type: ignore[attr-defined]
        _request(), stage="review"
    )


def test_model_backed_chapter_stages_share_the_agent_binding_boundary() -> None:
    assert AGENT_BOUND_CHAPTER_STAGES == {
        "draft",
        "review",
        "revision",
        "rereview",
        "canon_extraction",
        "quality_structural",
        "quality_commercial",
        "quality_source_originality",
        "quality_longform",
        "quality_platform",
    }
