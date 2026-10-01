from __future__ import annotations

import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from tests.unit.test_context_retrieval_v2 import _intent, _memo


def test_task_dependency_admission_is_wired_only_for_the_frozen_v4_profile(monkeypatch) -> None:
    from novel_forge.modules.chapter_authority import orchestrator
    from novel_forge.modules.context_builder.production_retrieval import RetrievalDiscovery

    boundary = {"accepted_through_chapter": 8}
    contents = {"plan:v1": {"book_id": "book:novel", "required_long_distance_fact_ids": ["fact:hook"]},
                "intent:v1": _intent(), "memo:v1": _memo()}
    monkeypatch.setattr(orchestrator, "_asset_content", lambda _url, **values: contents[values["asset_version_id"]])
    source_rows = [["sha256:" + "a" * 64, "ACTIVE", "ELIGIBLE", "CLEAR"]]

    class Cursor:
        def execute(self, query, params):
            assert params == ["state:v8", "project:novel"]

        def fetchone(self):
            return source_rows[0]

    class Uow:
        cursor = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(orchestrator, "AuthorityUnitOfWork", lambda _url: Uow())
    observed = []

    def discover(_url, **values):
        observed.append(values["query_plan"])
        return RetrievalDiscovery((), (), (), values["query_plan"], {})

    monkeypatch.setattr(orchestrator, "discover_accepted_retrieval_candidates", discover)
    request_args = dict(project_id="project:novel", workspace_id="workspace:novel", actor_id="author:novel",
        chapter=9, title="Title", premise="Premise", trace_id="trace:novel", correlation_id="correlation:novel",
        application_build_id="build:novel", commit_sha="a" * 40, book_id="book:novel",
        context_candidates=({"asset_type": "story_state_snapshot", "asset_version_id": "state:v8",
            "content_hash": "sha256:" + "a" * 64, "project_id": "project:novel", "book_id": "book:novel",
            "accepted_boundary": boundary, "structured_facts": [{"source_event_id": "event:current", "state": {"fact_id": "fact:hook", "world_transition": {"cause_refs": ["event:causal"]}}}]},))
    snapshot_args = dict(plan_asset_version_id="plan:v1", intent_asset_version_id="intent:v1", memo_asset_version_id="memo:v1")
    v4 = orchestrator.SingleChapterRequest(**request_args, preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v4"}})
    orchestrator._retrieval_admission_snapshot("fixture", request=v4, **snapshot_args)
    assert observed[-1]["task_dependency_refs"]["required_refs"] == ["event:causal", "fact:hook"]
    assert observed[-1]["task_dependency_refs"]["protected_fact_aliases"] == ["event:current", "fact:hook"]
    legacy = orchestrator.SingleChapterRequest(**request_args, preparation_report={"stage_context_profile_versions": {"draft": "draft-context-profile-v3"}})
    orchestrator._retrieval_admission_snapshot("fixture", request=legacy, **snapshot_args)
    assert "task_dependency_refs" not in observed[-1]
    source_rows[0] = None
    with pytest.raises(KernelError) as failure:
        orchestrator._retrieval_admission_snapshot("fixture", request=v4, **snapshot_args)
    assert failure.value.code == "RETRIEVAL_TASK_SOURCE_BINDING_INVALID"

