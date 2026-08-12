from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier


def definition_payload(name: str) -> dict:
    return {
        "name": name,
        "definition_version": "1.0.0",
        "family": "ops",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
            "additionalProperties": False,
        },
        "result_schema": {"type": "object"},
        "handler_key": "novel_forge.command_handlers.ops.echo",
        "handler_contract_version": "1.0.0",
        "application_build_id": "test-build-1",
        "commit_sha": "a" * 40,
        "execution_mode": "transactional",
        "permissions": ["ops.echo"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:operation",
        "concurrency_key_template": "project:{project_id}:ops.echo",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 10},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {"supported": False},
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {"source_policy": "project-default"},
        "completion_contract": {
            "version": "ops.echo.completion.v1",
            "required_outbox_events": ["ops.echo.admitted"],
        },
    }


class CommandKernelDefinitionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_same_name_version_and_hash_registers_idempotently(self) -> None:
        definition = definition_payload(identifier("definition"))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            first = uow.repositories.definitions.register(definition)
            uow.commit()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            second = uow.repositories.definitions.register(definition)
            uow.commit()

        self.assertTrue(first["registered"])
        self.assertFalse(second["registered"])
        self.assertEqual(first["definition_hash"], second["definition_hash"])

    def test_same_semantic_definition_binds_multiple_releases(self) -> None:
        definition = definition_payload(identifier("definition"))
        next_release = {
            **definition,
            "application_build_id": "test-build-2",
            "commit_sha": "b" * 40,
        }
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            second = uow.repositories.definitions.register(next_release)
            first_release = uow.repositories.definitions.get_release(
                definition["name"],
                definition["definition_version"],
                application_build_id=definition["application_build_id"],
                commit_sha=definition["commit_sha"],
            )
            second_release = uow.repositories.definitions.get_release(
                definition["name"],
                definition["definition_version"],
                application_build_id=next_release["application_build_id"],
                commit_sha=next_release["commit_sha"],
            )
            uow.commit()

        self.assertFalse(second["registered"])
        self.assertEqual(first_release["commit_sha"], "a" * 40)
        self.assertEqual(second_release["commit_sha"], "b" * 40)
        self.assertEqual(
            first_release["definition_hash"], second_release["definition_hash"]
        )

    def test_same_name_version_with_different_definition_hash_fails_closed(self) -> None:
        definition = definition_payload(identifier("definition"))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()

        mutated = {
            **definition,
            "handler_contract_version": "2.0.0",
        }
        with self.assertRaises(KernelError) as caught:
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.repositories.definitions.register(mutated)
                uow.commit()
        self.assertEqual(caught.exception.code, "OPERATION_DEFINITION_VERSION_CONFLICT")

    def test_registered_definition_exposes_frozen_runtime_contract(self) -> None:
        definition = definition_payload(identifier("definition"))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            registered = uow.repositories.definitions.register(definition)
            uow.commit()
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            stored = uow.repositories.definitions.get(
                definition["name"],
                definition["definition_version"],
            )

        self.assertEqual(stored["definition_hash"], registered["definition_hash"])
        self.assertEqual(stored["handler_key"], definition["handler_key"])
        self.assertEqual(
            stored["handler_contract_version"],
            definition["handler_contract_version"],
        )
        self.assertEqual(stored["application_build_id"], definition["application_build_id"])
        self.assertEqual(stored["commit_sha"], definition["commit_sha"])
        self.assertEqual(stored["command_schema"], definition["command_schema"])
        self.assertEqual(stored["result_schema"], definition["result_schema"])
        self.assertEqual(stored["approval_policy"], definition["approval_policy"])
        self.assertEqual(stored["completion_contract"], definition["completion_contract"])


if __name__ == "__main__":
    unittest.main()
