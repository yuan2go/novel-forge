from __future__ import annotations

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority.formation_domain import (
    StoryFormationInput,
    build_formation_auto_decision_evidence,
    deterministic_story_formation_run_id,
    require_worker_formation_auto_decision,
)


PROJECT_ID = "project-1"
WORKSPACE_ID = "workspace-1"
BOOK_ID = "book-1"
RUN_KEY = "run-1:formation"
FORMATION_RUN_ID = deterministic_story_formation_run_id(
    project_id=PROJECT_ID,
    book_id=BOOK_ID,
    stable_idempotency_key=RUN_KEY,
)


def _authorization() -> dict[str, object]:
    return {
        "contract_version": "formation-auto-authorization.v1",
        "policy_version": "formation-auto-policy.v1",
        "authorization_ref": "task-authorization:classical-corpus-20260908",
        "authorized_by_principal_id": "trusted-local",
        "project_id": PROJECT_ID,
        "workspace_id": WORKSPACE_ID,
        "book_id": BOOK_ID,
        "formation_run_id": FORMATION_RUN_ID,
        "allowed_actions": [
            "book_design.candidate.activate",
            "book_design.candidate.decide",
            "story_planning.candidate.activate",
            "story_planning.candidate.approve",
        ],
    }


def _input() -> StoryFormationInput:
    return StoryFormationInput(
        creative_brief_asset_version_id="asset-version:brief",
        creative_brief_content_hash="sha256:" + "a" * 64,
        generation_policy={
            "contract_version": "formation-generation.v2",
            "approval_mode": "AUTO",
            "creative_candidates": 2,
            "target_chapters": 3,
            "title": "Original title",
            "auto_authorization": _authorization(),
        },
    )


def test_auto_formation_authorization_is_exactly_scope_bound() -> None:
    frozen = _input()
    frozen.require_admission_scope(
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        book_id=BOOK_ID,
        formation_run_id=FORMATION_RUN_ID,
        admitted_by_principal_id="trusted-local",
        admitted_by_principal_type=PrincipalType.LOCAL_OPERATOR,
    )

    with pytest.raises(ValueError, match="Formation scope"):
        frozen.require_admission_scope(
            project_id="another-project",
            workspace_id=WORKSPACE_ID,
            book_id=BOOK_ID,
            formation_run_id=FORMATION_RUN_ID,
            admitted_by_principal_id="trusted-local",
            admitted_by_principal_type=PrincipalType.LOCAL_OPERATOR,
        )


def test_auto_worker_decision_binds_exact_candidate_and_action() -> None:
    frozen = _input()
    worker = Principal(
        principal_id="book-worker",
        principal_type=PrincipalType.WORKER,
        permissions=frozenset({"story_planning.authority.approve"}),
        project_scope=frozenset({PROJECT_ID}),
        authentication_source="worker_configuration",
    )
    evidence = build_formation_auto_decision_evidence(
        frozen=frozen,
        action="story_planning.candidate.approve",
        candidate_asset_version_id="asset-version:candidate",
        candidate_content_hash="sha256:" + "b" * 64,
        executed_by_principal_id=worker.principal_id,
    )
    require_worker_formation_auto_decision(
        principal=worker,
        evidence=evidence,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        book_id=BOOK_ID,
        action="story_planning.candidate.approve",
        candidate_asset_version_id="asset-version:candidate",
        candidate_content_hash="sha256:" + "b" * 64,
    )

    with pytest.raises(PermissionError, match="exact candidate"):
        require_worker_formation_auto_decision(
            principal=worker,
            evidence=evidence,
            project_id=PROJECT_ID,
            workspace_id=WORKSPACE_ID,
            book_id=BOOK_ID,
            action="story_planning.candidate.approve",
            candidate_asset_version_id="asset-version:different",
            candidate_content_hash="sha256:" + "b" * 64,
        )


def test_legacy_auto_policy_cannot_execute_without_scoped_authorization() -> None:
    frozen = StoryFormationInput(
        creative_brief_asset_version_id="asset-version:brief",
        creative_brief_content_hash="sha256:" + "a" * 64,
        generation_policy={
            "contract_version": "formation-generation.v1",
            "approval_mode": "AUTO",
            "creative_candidates": 2,
            "target_chapters": 3,
            "title": "Legacy",
        },
    )

    with pytest.raises(ValueError, match="scoped authorization"):
        frozen.require_admission_scope(
            project_id=PROJECT_ID,
            workspace_id=WORKSPACE_ID,
            book_id=BOOK_ID,
            formation_run_id=FORMATION_RUN_ID,
            admitted_by_principal_id="trusted-local",
            admitted_by_principal_type=PrincipalType.LOCAL_OPERATOR,
        )
