from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from novel_forge.modules.story_design_authority import DesignTransition
from novel_forge.modules.hierarchical_planning.definitions import (
    PLAN_BINDING_DEFINITION_VERSION,
    plan_binding_definitions,
)
from novel_forge.modules.story_planning_runtime.application import (
    StoryPlanningGenerationApplication,
)


class _Principal:
    principal_id = "planning-operator"

    def require(self, permission: str, project_id: str) -> None:
        assert permission == "story_planning.authority.activate"
        assert project_id == "project-1"


class _StoryDesignCapture:
    def __init__(self) -> None:
        self.require_count = 0
        self.prepared: list[tuple[object, object]] = []

    def require(self, *, project_id: str, asset_version_id: str) -> dict[str, Any]:
        assert (project_id, asset_version_id) == ("project-1", "candidate:v1")
        self.require_count += 1
        if self.require_count == 1:
            return {
                "lifecycle": "MATERIALIZED",
                "approval": "APPROVED",
                "version": 7,
            }
        return {
            "lifecycle": "ACTIVE",
            "approval": "APPROVED",
            "version": 8,
        }

    def prepare_transition(
        self, command: object, *, principal: object
    ) -> dict[str, object]:
        self.prepared.append((command, principal))
        return {
            "operation_id": "story-transition:activate:v7",
            "replayed": False,
        }

    def transition(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("ACTIVATE must not commit through the standalone seam")


class _PlanningCapture:
    def __init__(self) -> None:
        self.commands: list[dict[str, object]] = []

    def bind_active_contract(self, **command: object) -> dict[str, object]:
        self.commands.append(command)
        return {
            "binding_id": "binding:candidate:v1",
            "asset_version_id": "candidate:v1",
        }


def test_activation_commits_story_design_and_typed_binding_through_one_command() -> (
    None
):
    generation = {
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "book_id": "book-1",
        "generation_operation_id": "generation:book-plan:1",
        "generator_operation_name": "book_plan.generate",
        "content_hash": "sha256:" + "a" * 64,
        "logical_key": "book:main",
        "planning_scope": SimpleNamespace(value="BOOK"),
        "parent_version_id": "",
        "activation_policy_key": "planning-activation-v1",
    }
    story_design = _StoryDesignCapture()
    planning = _PlanningCapture()
    application = object.__new__(StoryPlanningGenerationApplication)
    application.story_design = story_design
    application.planning = planning
    application.require_candidate = lambda _candidate: generation
    application.require_generation = lambda _operation: {
        "status": "APPROVAL_PENDING",
        "narrative_search_id": "",
    }
    application._generation_command = lambda _operation: SimpleNamespace(
        generator_operation_name="book_plan.generate"
    )
    application._require_generation_inputs_current = lambda **_kwargs: None
    application._require_narrative_qualification_summary = lambda **_kwargs: None
    generation_statuses: list[tuple[str, str]] = []
    application._update_generation_status = lambda operation_id, status: (
        generation_statuses.append((operation_id, status))
    )

    result = application.activate_candidate(
        "candidate:v1",
        principal=_Principal(),  # type: ignore[arg-type]
        idempotency_key="activation:1",
        trace_id="trace:1",
        correlation_id="correlation:1",
    )

    assert len(story_design.prepared) == 1
    transition = story_design.prepared[0][0]
    assert transition.transition is DesignTransition.ACTIVATE  # type: ignore[attr-defined]
    assert transition.expected_version == 7  # type: ignore[attr-defined]
    assert planning.commands[0]["story_design_transition_operation_id"] == (
        "story-transition:activate:v7"
    )
    assert result["story_design"]["lifecycle"] == "ACTIVE"
    assert result["planning_binding"]["binding_id"] == "binding:candidate:v1"
    assert generation_statuses == [("generation:book-plan:1", "ACTIVE")]


def test_planning_binding_definition_persists_atomic_transition_identity() -> None:
    definition = plan_binding_definitions(
        application_build_id="atomic-activation-unit",
        commit_sha="a" * 40,
    )[0]

    assert PLAN_BINDING_DEFINITION_VERSION == "1.1.0"
    assert (
        "story_design_transition_operation_id"
        in definition["command_schema"]["required"]
    )
    assert definition["policy"]["atomic_story_design_activation"] is True


def test_activation_replay_reuses_the_original_transition_operation_identity() -> None:
    generation = {
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "book_id": "book-1",
        "generation_operation_id": "generation:book-plan:1",
        "generator_operation_name": "book_plan.generate",
        "content_hash": "sha256:" + "a" * 64,
        "logical_key": "book:main",
        "planning_scope": SimpleNamespace(value="BOOK"),
        "parent_version_id": "",
        "activation_policy_key": "planning-activation-v1",
    }

    class AlreadyActiveStoryDesign:
        def require(self, **_identity: str) -> dict[str, object]:
            return {
                "lifecycle": "ACTIVE",
                "approval": "APPROVED",
                "version": 8,
                "updated_by_operation_id": "story-transition:activate:v7",
            }

        def prepare_transition(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError(
                "an active candidate must reuse its transition receipt"
            )

    planning = _PlanningCapture()
    application = object.__new__(StoryPlanningGenerationApplication)
    application.story_design = AlreadyActiveStoryDesign()
    application.planning = planning
    application.require_candidate = lambda _candidate: generation
    application.require_generation = lambda _operation: {
        "status": "ACTIVE",
        "narrative_search_id": "",
    }
    application._generation_command = lambda _operation: SimpleNamespace(
        generator_operation_name="book_plan.generate"
    )
    application._require_narrative_qualification_summary = lambda **_kwargs: None
    application._update_generation_status = lambda *_args: None

    application.activate_candidate(
        "candidate:v1",
        principal=_Principal(),  # type: ignore[arg-type]
        idempotency_key="activation:1",
        trace_id="trace:1",
        correlation_id="correlation:1",
    )

    assert planning.commands[0]["story_design_transition_operation_id"] == (
        "story-transition:activate:v7"
    )
