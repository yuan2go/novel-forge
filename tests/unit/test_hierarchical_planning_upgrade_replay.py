from __future__ import annotations

from typing import Any

import novel_forge.modules.hierarchical_planning.application as planning_application
from novel_forge.modules.hierarchical_planning import (
    PlanContractType,
    PostgresHierarchicalPlanningAuthority,
)
from novel_forge.storage.authority_repositories import IdempotencyConflictError


class _Principal:
    principal_id = "planning-operator"

    def require(self, permission: str, project_id: str) -> None:
        assert (permission, project_id) == ("book.authority.execute", "project-1")


def _authority(*, replay_versions: list[str | None]) -> Any:
    authority = object.__new__(PostgresHierarchicalPlanningAuthority)
    authority.database_url = "postgresql://unit-test/not-used"
    authority.application_build_id = "planning-upgrade-unit"
    authority.commit_sha = "a" * 40
    authority.fault_injector = None
    authority._register_definitions = lambda: None
    authority._input_assets = lambda _project_id, _asset_ids: (
        {
            "asset_version_id": "candidate:v1",
            "content_hash": "sha256:" + "b" * 64,
        },
    )
    versions = iter(replay_versions)
    authority._binding_definition_version_for_replay = lambda **_identity: next(
        versions
    )
    authority.require_binding = lambda **_identity: {
        "binding_id": "binding:candidate:v1",
        "asset_version_id": "candidate:v1",
    }
    return authority


def _bind(authority: Any) -> dict[str, Any]:
    return authority.bind_active_contract(
        project_id="project-1",
        workspace_id="workspace-1",
        book_id="book-1",
        actor_id="planning-operator",
        asset_version_id="candidate:v1",
        contract_type=PlanContractType.BOOK,
        idempotency_key="activate:1:planning-binding",
        trace_id="trace:1",
        correlation_id="correlation:1",
        story_design_transition_operation_id="story-transition:activate:v7",
        principal=_Principal(),  # type: ignore[arg-type]
    )


def test_v1_replay_uses_the_frozen_legacy_command_shape(monkeypatch: Any) -> None:
    authority = _authority(replay_versions=["1.0.0"])
    commands: list[dict[str, Any]] = []

    def execute(
        _database_url: str,
        command: dict[str, Any],
        **_options: Any,
    ) -> dict[str, Any]:
        commands.append(command)
        return {"operation_id": "planning-binding:v1", "replayed": True}

    monkeypatch.setattr(planning_application, "execute_transaction_command", execute)

    result = _bind(authority)

    assert result["operation_id"] == "planning-binding:v1"
    assert result["replayed"] is True
    assert commands[0]["definition_version"] == "1.0.0"
    assert "story_design_transition_operation_id" not in commands[0]["input"]


def test_v1_worker_race_is_reread_once_and_replayed_as_v1(monkeypatch: Any) -> None:
    authority = _authority(replay_versions=[None, "1.0.0"])
    commands: list[dict[str, Any]] = []

    def execute(
        _database_url: str,
        command: dict[str, Any],
        **_options: Any,
    ) -> dict[str, Any]:
        commands.append(command)
        if command["definition_version"] == "1.1.0":
            raise IdempotencyConflictError("v1 worker won the stable key")
        return {"operation_id": "planning-binding:v1", "replayed": True}

    monkeypatch.setattr(planning_application, "execute_transaction_command", execute)

    result = _bind(authority)

    assert result["operation_id"] == "planning-binding:v1"
    assert [command["definition_version"] for command in commands] == [
        "1.1.0",
        "1.0.0",
    ]
    assert "story_design_transition_operation_id" not in commands[1]["input"]
