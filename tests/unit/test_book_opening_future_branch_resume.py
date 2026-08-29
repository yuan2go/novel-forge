from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from novel_forge.modules.book_authority.opening import (
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.runtime_job import RuntimeJobClaim
from novel_forge.modules.story_planning_runtime.domain import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationResult,
    PlanningGenerationStatus,
)


class _Search:
    def __init__(self) -> None:
        self.register_uows: list[object] = []
        self.reconcile_uows: list[object] = []
        self.selected_options: list[dict[str, Any]] = []

    def require_qualified_branches(self, search_id: str, **_: Any):
        return tuple(
            SimpleNamespace(
                branch_key=f"future-{ordinal}",
                result=PlanningGenerationResult(
                    generation_operation_id=f"operation:future-{ordinal}",
                    candidate_asset_version_id=f"candidate:future-{ordinal}",
                    status=PlanningGenerationStatus.ACTIVE,
                    story_design_state={"lifecycle": "ACTIVE"},
                    replayed=True,
                ),
                evidence_type="NARRATIVE_SEARCH_BRANCH",
                evidence_id=(
                    f"narrative-search-candidate:{search_id}:future-{ordinal}"
                ),
                evidence_version=1,
                evidence_hash="sha256:" + str(ordinal) * 64,
            )
            for ordinal in (1, 2, 3)
        )

    def register_qualified_branch_in_uow(self, uow: object, **_: Any):
        self.register_uows.append(uow)
        raise KernelError(
            "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED",
            "legacy membership",
        )

    def reconcile_legacy_qualified_branch_in_uow(
        self,
        uow: object,
        *,
        search_id: str,
        branch_key: str,
        result: PlanningGenerationResult,
        opening_run_id: str,
        opening_execution_id: str,
        execution_generation: int,
    ):
        self.reconcile_uows.append(uow)
        return SimpleNamespace(
            reconciliation_evidence_id=f"reconciliation:{branch_key}",
            evidence_id=f"reconciliation:{branch_key}",
            evidence_type="NARRATIVE_SEARCH_BRANCH_RECONCILIATION",
            membership_id=f"narrative-search-candidate:{search_id}:{branch_key}",
            search_id=search_id,
            branch_key=branch_key,
            candidate_asset_version_id=result.candidate_asset_version_id,
            generation_operation_id=result.generation_operation_id,
            opening_run_id=opening_run_id,
            opening_execution_id=opening_execution_id,
            execution_generation=execution_generation,
            evidence_version=1,
            evidence_hash="sha256:" + "a" * 64,
        )

    def require_selected(self, request: object, **options: Any):
        del request
        self.selected_options.append(dict(options))
        return SimpleNamespace(search_id="search:test")


class _Recovery:
    def __init__(self) -> None:
        self.uows: list[object] = []

    def commit_execution_narrative_search_branch(
        self,
        opening_run_id: str,
        *,
        branch_committer: Any,
        **_: Any,
    ):
        assert opening_run_id == "opening:test"
        uow = object()
        self.uows.append(uow)
        return branch_committer(uow)


def _request() -> OpenBookProductionRequest:
    return OpenBookProductionRequest(
        project_id="project:test",
        workspace_id="workspace:test",
        book_id="book:test",
        actor_id="operator:test",
        expected_book_version=1,
        production_profile="quality-proof",
        planning_input_versions={"topic": "asset:topic:v1"},
        arc_logical_keys=("arc:1",),
        idempotency_key="opening:test",
        trace_id="trace:test",
        correlation_id="correlation:test",
        initial_story_state_version="story-state:v1",
        initial_canon_snapshot_version="canon:v1",
    )


def _claim() -> RuntimeJobClaim:
    return RuntimeJobClaim(
        runtime_job_id="runtime-job:test",
        job_kind="BOOK_OPENING",
        runtime_group="book-opening",
        subject_kind="BOOK_OPENING",
        subject_id="opening:test",
        project_id="project:test",
        attempt_id="runtime-attempt:test",
        attempt_number=1,
        worker_id="worker:test",
        lease_id="runtime-lease:test",
        fencing_token=1,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        input_snapshot={
            "opening_run_id": "opening:test",
            "opening_execution_id": "opening-execution:test:1",
            "execution_generation": 1,
        },
    )


def test_whole_search_resume_reconciles_every_missing_branch_in_same_uow() -> None:
    application = PostgresBookOpeningApplication.__new__(
        PostgresBookOpeningApplication
    )
    search = _Search()
    recovery = _Recovery()
    application.narrative_search = search
    application.recovery = recovery

    result = application._search(  # noqa: SLF001
        request=_request(),
        principal=SimpleNamespace(),
        generator="book_plan.generate",
        logical_key="book:main",
        input_versions={
            role: f"asset:{role}:v1"
            for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        parent_version_id="",
        accepted_state="story-state:v1",
        horizon={"level": "BOOK"},
        transformation={"goal": "durable future"},
        opening_run_id="opening:test",
        runtime_claim=_claim(),
        progress={
            "book_plan.generate:book:main": {
                "owning_authority": "STORY_PLANNING",
                "evidence_type": "NARRATIVE_SEARCH",
                "evidence_id": "search:test",
            }
        },
    )

    assert result.search_id == "search:test"
    assert len(recovery.uows) == 3
    assert search.register_uows == recovery.uows
    assert search.reconcile_uows == recovery.uows
    assert search.selected_options == [
        {
            "activate_selected": True,
            "allow_reconciled_branches": True,
            "opening_run_id": "opening:test",
        }
    ]


def test_whole_search_resume_accepts_only_explicit_branch_checkpoint_types() -> None:
    application = PostgresBookOpeningApplication.__new__(
        PostgresBookOpeningApplication
    )
    search = _Search()
    recovery = _Recovery()
    application.narrative_search = search
    application.recovery = recovery
    progress: dict[str, dict[str, Any]] = {
        "book_plan.generate:book:main": {
            "owning_authority": "STORY_PLANNING",
            "evidence_type": "NARRATIVE_SEARCH",
            "evidence_id": "search:test",
        }
    }
    for ordinal in (1, 2, 3):
        progress[f"narrative-search-branch:search:test:future-{ordinal}"] = {
            "owning_authority": "STORY_PLANNING",
            "evidence_type": (
                "NARRATIVE_SEARCH_BRANCH"
            ),
            "evidence_id": (
                f"narrative-search-candidate:search:test:future-{ordinal}"
            ),
            "evidence_version": 1,
            "evidence_hash": "sha256:" + str(ordinal) * 64,
        }

    application._search(  # noqa: SLF001
        request=_request(),
        principal=SimpleNamespace(),
        generator="book_plan.generate",
        logical_key="book:main",
        input_versions={
            role: f"asset:{role}:v1"
            for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        parent_version_id="",
        accepted_state="story-state:v1",
        horizon={"level": "BOOK"},
        transformation={"goal": "durable future"},
        opening_run_id="opening:test",
        runtime_claim=_claim(),
        progress=progress,
    )

    assert recovery.uows == []
    assert search.selected_options[-1]["allow_reconciled_branches"] is True


def test_whole_search_resume_rejects_branch_checkpoint_evidence_drift() -> None:
    application = PostgresBookOpeningApplication.__new__(
        PostgresBookOpeningApplication
    )
    search = _Search()
    recovery = _Recovery()
    application.narrative_search = search
    application.recovery = recovery
    progress: dict[str, dict[str, Any]] = {
        "book_plan.generate:book:main": {
            "owning_authority": "STORY_PLANNING",
            "evidence_type": "NARRATIVE_SEARCH",
            "evidence_id": "search:test",
        }
    }
    for ordinal in (1, 2, 3):
        progress[f"narrative-search-branch:search:test:future-{ordinal}"] = {
            "owning_authority": "STORY_PLANNING",
            "evidence_type": "NARRATIVE_SEARCH_BRANCH",
            "evidence_id": (
                f"narrative-search-candidate:search:test:future-{ordinal}"
            ),
            "evidence_version": 1,
            "evidence_hash": "sha256:" + str(ordinal) * 64,
        }
    progress["narrative-search-branch:search:test:future-2"]["evidence_hash"] = (
        "sha256:" + "f" * 64
    )

    with pytest.raises(KernelError) as drift:
        application._search(  # noqa: SLF001
            request=_request(),
            principal=SimpleNamespace(),
            generator="book_plan.generate",
            logical_key="book:main",
            input_versions={
                role: f"asset:{role}:v1"
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            parent_version_id="",
            accepted_state="story-state:v1",
            horizon={"level": "BOOK"},
            transformation={"goal": "durable future"},
            opening_run_id="opening:test",
            runtime_claim=_claim(),
            progress=progress,
        )
    assert drift.value.code == "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT"

    assert recovery.uows == []
    assert search.selected_options == []
