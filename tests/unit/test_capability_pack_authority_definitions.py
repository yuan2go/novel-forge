from __future__ import annotations

from novel_forge.modules.capability_pack_authority.definitions import (
    CAPABILITY_PACK_ADMIN_HANDLER_KEY,
    CAPABILITY_PACK_AUTHORITY_OPERATIONS,
    CAPABILITY_PACK_DEFINITION_VERSION,
    capability_pack_operation_definitions,
)


def test_capability_pack_operations_are_command_kernel_definitions() -> None:
    definitions = {
        item["name"]: item
        for item in capability_pack_operation_definitions(
            application_build_id="capability-pack-authority-test",
            commit_sha="a" * 40,
        )
    }
    assert set(definitions) == set(CAPABILITY_PACK_AUTHORITY_OPERATIONS)
    assert {
        "capability_pack.manifest.register",
        "capability_pack.manifest.validate",
        "capability_pack.compile",
        "capability_pack.approval.decide",
        "capability_pack.deployment.create",
        "capability_pack.deployment.activate",
        "capability_pack.deployment.disable",
        "capability_pack.rollout.start",
        "capability_pack.rollout.pause",
        "capability_pack.rollout.resume",
        "capability_pack.rollout.complete",
        "capability_pack.rollback",
        "capability_pack.deprecate",
        "capability_pack.retire",
        "capability_pack.revoke",
    } == set(definitions)
    for definition in definitions.values():
        assert definition["definition_version"] == CAPABILITY_PACK_DEFINITION_VERSION
        assert definition["handler_key"] == CAPABILITY_PACK_ADMIN_HANDLER_KEY
        assert definition["execution_mode"] == "transactional"
        assert definition["policy"]["authority"] == "postgresql"
        assert definition["policy"]["pack_run_state"] == "forbidden"
        assert definition["policy"]["operation_definition_override"] is False
        assert definition["retry_policy"]["max_attempts"] == 1
        assert definition["completion_contract"]["required_evidence"] == [
            "trace",
            "audit",
        ]


def test_permissions_separate_registration_compilation_and_activation() -> None:
    definitions = {
        item["name"]: item
        for item in capability_pack_operation_definitions(
            application_build_id="capability-pack-authority-test",
            commit_sha="b" * 40,
        )
    }
    assert definitions["capability_pack.manifest.register"]["permissions"] == [
        "capability_pack.authority.register"
    ]
    assert definitions["capability_pack.compile"]["permissions"] == [
        "capability_pack.authority.compile"
    ]
    assert definitions["capability_pack.approval.decide"]["permissions"] == [
        "capability_pack.authority.approve"
    ]
    assert definitions["capability_pack.deployment.activate"]["permissions"] == [
        "capability_pack.authority.activate"
    ]
    assert definitions["capability_pack.rollback"]["permissions"] == [
        "capability_pack.authority.rollback"
    ]


def test_command_schema_forbids_caller_compiled_payload() -> None:
    definition = next(
        item
        for item in capability_pack_operation_definitions(
            application_build_id="capability-pack-authority-test",
            commit_sha="c" * 40,
        )
        if item["name"] == "capability_pack.compile"
    )
    assert definition["command_schema"]["additionalProperties"] is False
    assert "compiled_capability_pack" not in definition["command_schema"][
        "properties"
    ]
    assert "compiled_payload" not in definition["command_schema"]["properties"]
