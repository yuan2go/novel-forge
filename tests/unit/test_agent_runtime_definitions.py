from __future__ import annotations

from novel_forge.modules.agent_runtime.definitions import (
    AGENT_RUNTIME_ADMIN_HANDLER_KEY,
    AGENT_RUNTIME_DEFINITION_VERSION,
    AGENT_RUNTIME_EXECUTION_HANDLER_KEY,
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
        "agent.chapter_binding.register",
        "agent.chapter_binding.activate",
        "agent.candidate.execute",
    }
    for name, definition in definitions.items():
        assert definition["definition_version"] == AGENT_RUNTIME_DEFINITION_VERSION
        assert definition["policy"]["authority"] == "postgresql"
        assert definition["policy"]["agent_run_status_owner"] == "projection"
        assert definition["policy"]["attempt_owner"] == "command_kernel"
        assert definition["policy"]["capability_pack_controls_operation"] is False
        if name == "agent.candidate.execute":
            assert definition["execution_mode"] == "worker"
            assert definition["handler_key"] == AGENT_RUNTIME_EXECUTION_HANDLER_KEY
        else:
            assert definition["execution_mode"] == "transactional"
            assert definition["handler_key"] == AGENT_RUNTIME_ADMIN_HANDLER_KEY


def test_agent_run_admission_requires_frozen_versions_and_asset_inputs() -> None:
    definition = next(
        item
        for item in agent_runtime_operation_definitions(
            application_build_id="agent-runtime-test",
            commit_sha="b" * 40,
        )
        if item["name"] == "agent.candidate.execute"
    )
    schema = definition["command_schema"]

    assert "model.draft" in definition["external_capabilities"]
    assert "model.reader_outcome" in definition["external_capabilities"]

    for field in (
        "agent_id",
        "agent_definition_version",
        "agent_definition_hash",
        "capability_id",
        "capability_version",
        "capability_hash",
        "capability_pack_ref",
        "capability_pack_compilation_hash",
        "context_bundle_asset_version_id",
        "context_bundle_hash",
        "prompt_bundle_ref",
        "prompt_bundle_hash",
        "skill_bundle_ref",
        "skill_bundle_hash",
        "tool_policy_ref",
        "tool_policy_hash",
        "context_policy_ref",
        "context_policy_hash",
        "evaluation_policy_ref",
        "evaluation_policy_hash",
        "route_policy_ref",
        "model_profile_ref",
        "release_sha",
    ):
        assert field in schema["required"]
