from __future__ import annotations

import pytest

from novel_forge.modules.chapter_authority.orchestrator import (
    SingleChapterRequest,
    _bind_context_candidate_scope,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _request(*candidates: dict[str, object], chapter: int = 1) -> SingleChapterRequest:
    return SingleChapterRequest(
        project_id="project-1",
        workspace_id="workspace-1",
        actor_id="worker-1",
        chapter=chapter,
        title="Chapter",
        premise="A governed premise",
        trace_id="trace-1",
        correlation_id="correlation-1",
        application_build_id="unit-test",
        commit_sha="a" * 40,
        context_candidates=tuple(candidates),
    )


def test_direct_request_admission_binds_scope_before_context_assembly() -> None:
    request = _bind_context_candidate_scope(
        _request(
            {
                "asset_version_id": "plan-v1",
                "asset_type": "chapter_plan",
                "content_hash": "sha256:" + "1" * 64,
            },
            {
                "asset_version_id": "rubric-v1",
                "asset_type": "quality_rubric",
                "content_hash": "sha256:" + "2" * 64,
            },
        )
    )

    assert request.book_id == "book:project-1"
    assert {item["book_id"] for item in request.context_candidates} == {
        "book:project-1"
    }
    assert {str(item["accepted_boundary"]) for item in request.context_candidates} == {
        str(
            {
                "accepted_through_chapter": 0,
                "story_state_snapshot_version": "",
                "canon_snapshot_version": "",
            }
        )
    }


def test_request_admission_rejects_cross_book_or_wrong_boundary() -> None:
    with pytest.raises(KernelError, match="disagree on their Book scope"):
        _bind_context_candidate_scope(
            _request(
                {"book_id": "book-1"},
                {"book_id": "book-2"},
            )
        )
    with pytest.raises(KernelError, match="differs from the requested chapter"):
        _bind_context_candidate_scope(
            _request(
                {
                    "book_id": "book-1",
                    "accepted_boundary": {"accepted_through_chapter": 0},
                },
                chapter=2,
            )
        )
