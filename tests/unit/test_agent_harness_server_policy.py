from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_forge.modules.agent_runtime.harness import (
    AcceptedBoundaryRef,
    AgentHarnessBudget,
    AgentHarnessSession,
    AgentHarnessStatus,
    AgentToolCall,
    AgentToolKind,
    AgentToolObservation,
    AgentToolSpec,
    AutonomousAgentRole,
)
from novel_forge.modules.agent_runtime.harness_runtime import BoundAgentToolRouter
from novel_forge.modules.agent_runtime.policy import (
    SERVER_AGENT_TOOL_CATALOG,
    ServerAgentHarnessPolicyResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError


def _definition(*, tools: tuple[str, ...]) -> dict[str, object]:
    return {
        "agent_id": "studio-director",
        "definition_version": 7,
        "definition_hash": "sha256:" + "1" * 64,
        "activation_version": 3,
        "runtime_contract_hash": "sha256:" + "4" * 64,
        "role": "STUDIO_DIRECTOR",
        "allowed_tools": list(tools),
        "capability_pack_ref": "agent_session_pack@1.0.0",
        "prompt_bundle_ref": "prompt-bundle:studio:v1",
        "prompt_bundle_hash": "sha256:" + "5" * 64,
        "tool_policy_ref": "tool-policy:studio:v1",
        "tool_policy_hash": "sha256:" + "2" * 64,
        "skill_bundle_ref": "skill-bundle:studio:v1",
        "skill_bundle_hash": "sha256:" + "3" * 64,
        "context_policy_ref": "context-policy:studio:v1",
        "context_policy_hash": "sha256:" + "6" * 64,
    }


def _uow(definition: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        repositories=SimpleNamespace(
            agent_runtime=SimpleNamespace(
                lock_active_definition=lambda agent_id: (
                    definition
                    if agent_id == definition["agent_id"]
                    else pytest.fail("wrong Agent Definition identity")
                )
            )
        )
    )


def test_controlled_policy_fails_closed_without_model_binding() -> None:
    resolver = ServerAgentHarnessPolicyResolver(
        "postgresql://authority", production_model_binding=None
    )
    with pytest.raises(KernelError, match="production model binding") as caught:
        resolver.resolve_in_uow(
            _uow(_definition(tools=("narrative.query_accepted",))),
            agent_id="studio-director",
            role=AutonomousAgentRole.STUDIO_DIRECTOR,
            caller_tools=(SERVER_AGENT_TOOL_CATALOG["narrative.query_accepted"],),
            caller_skills=(),
        )
    assert caught.value.code == "AGENT_HARNESS_PRODUCTION_MODEL_UNBOUND"


def test_server_definition_is_the_only_tool_authority() -> None:
    resolver = ServerAgentHarnessPolicyResolver(
        "postgresql://authority",
        production_model_binding={
            "gateway": "PRODUCTION_EXECUTION_GATEWAY",
            "model_id": "provider-model",
        },
    )
    malicious = AgentToolSpec(
        tool_name="plan_change.submit",
        kind=AgentToolKind.AUTHORITY_COMMAND,
        input_schema_ref="caller:input",
        output_schema_ref="caller:output",
        allowed_roles=(AutonomousAgentRole.STUDIO_DIRECTOR,),
        authority_command_type="plan_change.propose",
    )
    with pytest.raises(KernelError, match="not identical") as caught:
        resolver.resolve_in_uow(
            _uow(_definition(tools=("narrative.query_accepted",))),
            agent_id="studio-director",
            role=AutonomousAgentRole.STUDIO_DIRECTOR,
            caller_tools=(malicious,),
            caller_skills=(),
        )
    assert caught.value.code == "AGENT_CALLER_TOOL_POLICY_MISMATCH"


def test_server_snapshot_freezes_definition_pack_skill_and_authority_policy() -> None:
    resolver = ServerAgentHarnessPolicyResolver(
        "postgresql://authority",
        production_model_binding={
            "gateway": "PRODUCTION_EXECUTION_GATEWAY",
            "model_id": "provider-model",
        },
    )
    names = (
        "narrative.query_accepted",
        "story_planning.generate_candidate",
        "plan_change.submit",
    )
    caller = tuple(SERVER_AGENT_TOOL_CATALOG[name] for name in names)
    tools, skills, snapshot = resolver.resolve_in_uow(
        _uow(_definition(tools=names)),
        agent_id="studio-director",
        role=AutonomousAgentRole.STUDIO_DIRECTOR,
        caller_tools=caller,
        caller_skills=(),
    )

    assert tools == caller
    assert skills == (
        {
            "skill_id": "skill-bundle:studio:v1",
            "skill_version": "definition:7",
            "skill_hash": "sha256:" + "3" * 64,
        },
    )
    assert snapshot["authority_policy"] == "SUBMIT_ONLY_NO_DIRECT_MUTATION"
    assert snapshot["skills_do_not_grant_authority"] is True
    assert str(snapshot["policy_hash"]).startswith("sha256:")


def test_authority_command_binding_rejects_hidden_direct_mutation_claim() -> None:
    spec = SERVER_AGENT_TOOL_CATALOG["plan_change.submit"]
    session = AgentHarnessSession(
        agent_session_id="session",
        project_id="project",
        workspace_id="workspace",
        operation_id="operation",
        role=AutonomousAgentRole.STUDIO_DIRECTOR,
        status=AgentHarnessStatus.RUNNING,
        accepted_boundary=AcceptedBoundaryRef("book", "run", 0, "", ""),
        tool_policy=(spec,),
        skill_bindings=(),
        budget=AgentHarnessBudget(2, 1, 2, 10, 10, "1"),
    )

    def bypass(*_args: object) -> AgentToolObservation:
        return AgentToolObservation(
            tool_name="plan_change.submit",
            result={"submitted": True, "plan_activated": True},
            operation_id="operation",
            attempt_id="attempt",
            authority_command_id="command",
        )

    with pytest.raises(KernelError, match="business mutation") as caught:
        BoundAgentToolRouter({"plan_change.submit": bypass}).invoke(
            spec=spec,
            call=AgentToolCall("plan_change.submit", {}, "submit proposal"),
            session=session,
            request_id="request",
            turn_number=1,
        )
    assert caught.value.code == "AGENT_HARNESS_AUTHORITY_BYPASS"
