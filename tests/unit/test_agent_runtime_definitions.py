from __future__ import annotations

from novel_forge.modules.agent_runtime.definitions import (
    AGENT_RUNTIME_ADMIN_HANDLER_KEY,
    AGENT_RUNTIME_DEFINITION_VERSION,
    AGENT_RUNTIME_HARNESS_HANDLER_KEY,
    AGENT_SESSION_DEFINITION_VERSION,
    agent_runtime_operation_definitions,
)


def test_agent_runtime_definitions_use_shared_kernel_execution_classes() -> None:
    definitions = {
        item["name"]: item
        for item in agent_runtime_operation_definitions(
            application_build_id="agent-runtime-test",
            commit_sha="a" * 40,
        )
    }

    assert set(definitions) == {
        "agent.definition.register",
        "agent.definition.activate",
        "agent.definition.disable",
        "agent.session.execute",
    }
    for name, definition in definitions.items():
        assert definition["definition_version"] == (
            AGENT_SESSION_DEFINITION_VERSION
            if name == "agent.session.execute"
            else AGENT_RUNTIME_DEFINITION_VERSION
        )
        assert definition["policy"]["authority"] == "postgresql"
        assert definition["policy"]["agent_run_status_owner"] == "projection"
        assert definition["policy"]["attempt_owner"] == "command_kernel"
        assert definition["policy"]["capability_pack_controls_operation"] is (
            name == "agent.session.execute"
        )
        if name == "agent.session.execute":
            assert definition["execution_mode"] == "worker"
            assert definition["handler_key"] == AGENT_RUNTIME_HARNESS_HANDLER_KEY
            assert definition["policy"]["agent_session_provenance_only"] is True
            assert definition["policy"]["authority_commands_submit_only"] is True
        else:
            assert definition["execution_mode"] == "transactional"
            assert definition["handler_key"] == AGENT_RUNTIME_ADMIN_HANDLER_KEY


def test_agent_session_admission_freezes_requested_skill_selection() -> None:
    definition = next(
        item
        for item in agent_runtime_operation_definitions(
            application_build_id="agent-runtime-test",
            commit_sha="b" * 40,
        )
        if item["name"] == "agent.session.execute"
    )
    schema = definition["command_schema"]

    assert "requested_skill_ids" in schema["required"]
    assert schema["properties"]["requested_skill_ids"]["uniqueItems"] is True
    assert definition["external_capabilities"] == [
        "model.agent_session",
        "tool.remote.invoke",
    ]
