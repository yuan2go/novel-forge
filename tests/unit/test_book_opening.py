from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.opening import (
    OpenBookProductionRequest,
    PostgresBookOpeningApplication,
)
from novel_forge.modules.story_planning_runtime import GENERATOR_INPUT_ROLES


def test_book_opening_drives_foundation_through_searched_plan_baseline() -> None:
    search_requests: list[object] = []

    def explore(request, *, principal, activate_selected):  # type: ignore[no-untyped-def]
        search_requests.append(request)
        generation = request.generation
        return SimpleNamespace(
            search_id=f"search:{generation.generator_operation_name}:{generation.logical_key}",
            selected_generation=SimpleNamespace(
                candidate_asset_version_id=(
                    f"active:{generation.generator_operation_name}:{generation.logical_key}"
                )
            ),
        )

    resolved: list[object] = []
    opening = PostgresBookOpeningApplication(
        "postgresql://unused",
        narrative_search=SimpleNamespace(explore=explore),
        input_resolver=SimpleNamespace(
            resolve=lambda command, *, principal: (
                resolved.append(command)
                or SimpleNamespace(snapshot_id="snapshot:ready")
            )
        ),
    )
    opening._require_qualified_foundation = (  # type: ignore[method-assign]
        lambda _request: "foundation:v5"
    )
    opening_roles = {
        role
        for generator in (
            "book_plan.generate",
            "volume_plan.generate",
            "arc_plan.generate",
        )
        for role in GENERATOR_INPUT_ROLES[generator]
        if role not in {"book_plan", "volume_plan"}
    }
    generic = {
        role: "foundation:v5" if role == "book_design" else f"asset:{role}"
        for role in opening_roles
    }
    request = OpenBookProductionRequest(
        project_id="project:1",
        workspace_id="workspace:1",
        book_id="book:1",
        actor_id="operator:1",
        expected_book_version=2,
        production_profile="opening-profile",
        planning_input_versions=generic,
        arc_logical_keys=("arc:plot", "arc:relationship", "arc:mystery"),
        idempotency_key="book:1:opening",
        trace_id="trace:opening",
        correlation_id="correlation:opening",
        initial_story_state_version="story-state:initial",
        initial_canon_snapshot_version="canon:initial",
    )
    principal = SimpleNamespace(require=lambda _permission, _project_id: None)

    result = opening.open(request, principal=principal)

    assert [item.generation.generator_operation_name for item in search_requests] == [
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
        "arc_plan.generate",
        "arc_plan.generate",
    ]
    assert all(
        item.generation.auto_approve_low_risk is False for item in search_requests
    )
    assert search_requests[1].generation.parent_version_id == result.book_plan_version
    assert all(item.generation.parent_version_id == "" for item in search_requests[2:])
    assert len(result.arc_plan_versions) == 3
    assert result.input_snapshot.snapshot_id == "snapshot:ready"
    assert (
        dict(resolved[0].role_asset_version_overrides)["initial_story_state_version"]
        == "story-state:initial"
    )


def test_book_opening_rejects_missing_initial_accepted_boundary() -> None:
    with pytest.raises(ValueError, match="initial accepted Story State"):
        OpenBookProductionRequest(
            project_id="project:1",
            workspace_id="workspace:1",
            book_id="book:1",
            actor_id="operator:1",
            expected_book_version=1,
            production_profile="opening-profile",
            planning_input_versions={"book_design": "foundation:v5"},
            arc_logical_keys=("arc:plot",),
            idempotency_key="book:1:opening",
            trace_id="trace:opening",
            correlation_id="correlation:opening",
        )
