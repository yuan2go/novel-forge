from __future__ import annotations

from typing import cast

import pytest

from novel_forge.modules.agent_runtime.application import (
    AgentRunAdmissionRequest,
    AgentRuntimeAdminCommand,
    AgentRuntimeAuthorityApplication,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError


def _application() -> AgentRuntimeAuthorityApplication:
    return AgentRuntimeAuthorityApplication(
        "postgresql://unused",
        application_build_id="agent-taxonomy-test",
        commit_sha="a" * 40,
    )


def test_legacy_per_stage_agent_run_cannot_be_admitted() -> None:
    with pytest.raises(KernelError) as retired:
        _application().admit_run(
            cast(AgentRunAdmissionRequest, object()),
            principal=cast(Principal, object()),
        )

    assert retired.value.code == "LEGACY_AGENT_RUN_ADMISSION_RETIRED"


@pytest.mark.parametrize(
    "definition_name",
    ("agent.chapter_binding.register", "agent.chapter_binding.activate"),
)
def test_legacy_per_stage_agent_binding_cannot_be_created(
    definition_name: str,
) -> None:
    command = AgentRuntimeAdminCommand(
        definition_name=definition_name,
        project_id="project-1",
        workspace_id="workspace-1",
        agent_id="legacy-stage-agent",
        actor_id="operator-1",
        idempotency_key=f"retired:{definition_name}",
        trace_id="trace-1",
        correlation_id="correlation-1",
        payload={},
    )

    with pytest.raises(KernelError) as retired:
        _application().execute_admin(
            command,
            principal=cast(Principal, object()),
        )

    assert retired.value.code == "LEGACY_AGENT_BINDING_CREATE_RETIRED"
