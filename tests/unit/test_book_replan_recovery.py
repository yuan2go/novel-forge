from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_forge.modules.book_authority.production import BookProductionState
from novel_forge.modules.book_authority.input_resolver import (
    BookProductionInputResolver,
)
from novel_forge.modules.book_replan.coordinator import (
    BookReplanCoordinator,
    CoordinateBookReplanCommand,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    PlanningGenerationResult,
    PlanningGenerationStatus,
    STORY_PLANNING_OPERATION_DEFINITION_REF,
)


def test_crash_after_plan_change_proposal_replays_same_identity() -> None:
    generated = PlanningGenerationResult(
        generation_operation_id="operation:replacement",
        candidate_asset_version_id="asset-version:replacement",
        status=PlanningGenerationStatus.APPROVAL_PENDING,
        story_design_state={},
    )
    planning_commands: list[object] = []
    search_requests: list[object] = []
    proposal_commands: list[object] = []
    durable_proposals: dict[str, dict[str, str]] = {}
    checkpoint_payloads: list[dict[str, object]] = []
    state: dict[str, object] = {}
    crash_pending = True

    def generate(command: object, *, principal: object) -> PlanningGenerationResult:
        planning_commands.append(command)
        return generated

    def propose(command: object, *, principal: object) -> dict[str, str]:
        proposal_commands.append(command)
        stable_key = str(getattr(command, "stable_idempotency_key"))
        return durable_proposals.setdefault(
            stable_key,
            {
                "proposal_id": "plan-change:stable",
                "status": "PENDING_APPROVAL",
            },
        )

    def inject(checkpoint: str) -> None:
        nonlocal crash_pending
        if (
            checkpoint == "after_plan_change_proposal_before_replan_checkpoint"
            and crash_pending
        ):
            crash_pending = False
            raise RuntimeError("injected post-proposal crash")

    coordinator = BookReplanCoordinator(
        "postgresql://unused",
        book_authority=SimpleNamespace(
            require=lambda _book_run_id: {
                "project_id": "project:1",
                "workspace_id": "workspace:1",
                "book_id": "book:1",
                "input_mode": "RESOLVED_AUTHORITY_INPUT",
                "input_snapshot_id": "snapshot:1",
                "accepted_through_chapter": 20,
                "active_story_state_version_id": "asset-version:story-state:20",
                "state": BookProductionState.REPLAN_REQUIRED.value,
            }
        ),
        planning=SimpleNamespace(generate=generate),
        plan_change=SimpleNamespace(propose=propose),
        input_resolver=SimpleNamespace(),
        principal=SimpleNamespace(
            principal_id="operator:1",
            require=lambda _permission, _project_id: None,
        ),
        fault_injector=inject,
        narrative_search=SimpleNamespace(
            explore=lambda request, *, principal, activate_selected: (
                search_requests.append(request)
                or SimpleNamespace(selected_generation=generated)
            )
        ),
    )
    coordinator._find_by_idempotency = lambda _project_id, _key: state.get(  # type: ignore[method-assign,assignment]
        "result"
    )
    coordinator._require_recap_lineage = lambda _command: {  # type: ignore[method-assign]
        "operation_id": "operation:recap",
        "replan_request": {
            "type": "ArcRevisionCandidate",
            "affected_scope": "BOOK",
            "impact_scope": {},
            "preserved_invariants": [],
            "decision_evidence": [],
        },
    }
    coordinator._target_plan = lambda _command, _chapter: {  # type: ignore[method-assign]
        "asset_version_id": "asset-version:target",
        "logical_key": "book:main",
        "parent_version_id": "",
        "execution_scope": "PLANNED",
        "content": {},
    }
    coordinator._replacement_inputs = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        {
            role: f"asset-version:{role}"
            for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
        },
        (),
        (),
    )

    def checkpoint(**kwargs: object) -> dict[str, object]:
        payload = dict(kwargs["payload"])  # type: ignore[arg-type]
        checkpoint_payloads.append(payload)
        state["result"] = {
            "replan_id": payload["replan_id"],
            "status": "APPROVAL_PENDING",
            "plan_change_proposal_id": payload["plan_change_proposal_id"],
        }
        return dict(state["result"])  # type: ignore[arg-type]

    coordinator._run_checkpoint = checkpoint  # type: ignore[method-assign]
    coordinator.require = lambda _replan_id: dict(state["result"])  # type: ignore[method-assign,arg-type]
    command = CoordinateBookReplanCommand(
        project_id="project:1",
        workspace_id="workspace:1",
        book_id="book:1",
        book_run_id="book-run:1",
        source_recap_asset_version_id="asset-version:recap",
        replan_request_asset_version_id="asset-version:arc-revision",
        affected_scope="BOOK",
        idempotency_key="book:1:replan:20",
        trace_id="trace:replan",
        correlation_id="operation:recap",
    )

    with pytest.raises(RuntimeError, match="post-proposal crash"):
        coordinator.start(command)
    assert state == {}
    assert len(durable_proposals) == 1

    recovered = coordinator.start(command)

    assert recovered["status"] == "APPROVAL_PENDING"
    assert recovered["plan_change_proposal_id"] == "plan-change:stable"
    assert planning_commands == []
    assert len(search_requests) == 2
    assert len(proposal_commands) == 2
    assert len(durable_proposals) == 1
    assert len(checkpoint_payloads) == 1


def test_planning_pack_accepts_typed_capabilities_without_legacy_agent_ref() -> None:
    capabilities = {
        "book_plan.generate": "planning.book.generate",
        "volume_plan.generate": "planning.volume.generate",
        "arc_plan.generate": "planning.arc.generate",
        "chapter_group_plan.generate": "planning.chapter_group.generate",
        "chapter_plan.generate": "planning.story_chapter.generate",
    }
    bindings = [
        {
            "workflow_node_id": node_id,
            "execution_capability_id": capability,
            "operation_definition_ref": STORY_PLANNING_OPERATION_DEFINITION_REF,
            "commit_authority": "STORY_DESIGN_AUTHORITY",
            "agent_definition_ref": "",
        }
        for node_id, capability in capabilities.items()
    ]

    class Cursor:
        def execute(self, _query: str, _parameters: object) -> None:
            return None

        def fetchall(self) -> list[tuple[str, list[dict[str, str]]]]:
            return [("deployment:typed-planning", bindings)]

    deployments = BookProductionInputResolver._planning_deployments(
        Cursor(),
        SimpleNamespace(
            project_id="project:1",
            workspace_id="workspace:1",
            book_id="book:1",
        ),
    )

    assert deployments == ["deployment:typed-planning"]
