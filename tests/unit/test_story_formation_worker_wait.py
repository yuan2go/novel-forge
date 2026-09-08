from __future__ import annotations

from types import SimpleNamespace

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority.formation_generation import (
    FormationApprovalRequired,
)
from novel_forge.workers.book_authority import execute_story_formation_claim


def test_manual_approval_completes_technical_job_without_retry_or_failure() -> None:
    principal = Principal(
        principal_id="formation-worker",
        principal_type=PrincipalType.WORKER,
        permissions=frozenset({"book.authority.execute"}),
        project_scope=frozenset({"project-1"}),
        authentication_source="book_formation_worker_configuration",
    )
    claim = SimpleNamespace(
        job_kind="STORY_FORMATION_ADVANCE",
        runtime_group="story_formation",
        subject_kind="STORY_FORMATION_RUN",
        subject_id="story-formation:1",
        attempt_id="runtime-attempt:1",
        input_snapshot={"observed_stage": "THEME_CONTRACT", "observed_version": 4},
    )

    class Jobs:
        def __init__(self) -> None:
            self.completed = None
            self.failed = None
            self.checkpoints: list[dict[str, object]] = []

        def start(self, _claim: object) -> None:
            pass

        def heartbeat(self, _claim: object, *, lease_seconds: int) -> None:
            assert lease_seconds == 30

        def checkpoint(self, _claim: object, value: dict[str, object]) -> None:
            self.checkpoints.append(value)

        def complete(self, _claim: object, value: dict[str, object]) -> None:
            self.completed = value

        def fail(self, _claim: object, value: dict[str, object]) -> None:
            self.failed = value

    class Formation:
        failure_recorded = False

        def advance_expected(self, *_args: object, **kwargs: object) -> None:
            assert kwargs["principal"] is principal
            raise FormationApprovalRequired(
                stage="THEME_CONTRACT",
                authority="STORY_PLANNING_AUTHORITY",
                candidate_asset_version_id="asset-version:theme",
                candidate_content_hash="sha256:" + "a" * 64,
                candidate_asset_version_ids=("asset-version:theme",),
            )

        def wait_for_approval(self, *_args: object, **kwargs: object):
            assert kwargs["principal"] is principal
            assert kwargs["runtime_attempt_id"] == claim.attempt_id
            return {
                "formation_run_id": claim.subject_id,
                "current_stage": "THEME_CONTRACT",
                "lifecycle": "WAITING_APPROVAL",
                "version": 5,
            }

        def record_failure(self, *_args: object, **_kwargs: object) -> None:
            self.failure_recorded = True

    jobs = Jobs()
    formation = Formation()
    result = execute_story_formation_claim(
        jobs,  # type: ignore[arg-type]
        formation,  # type: ignore[arg-type]
        principal,
        claim,  # type: ignore[arg-type]
        lease_seconds=30,
    )

    assert result["lifecycle"] == "WAITING_APPROVAL"
    assert jobs.completed == result
    assert jobs.failed is None
    assert not formation.failure_recorded
    assert jobs.checkpoints[-1]["stage"] == "STORY_FORMATION_WAITING_APPROVAL"
