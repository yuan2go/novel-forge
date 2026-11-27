from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier
from tests.integration.test_command_kernel_definition_postgres import definition_payload


class CommandKernelAdmissionIdempotencyPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_same_key_and_digest_replays_original_operation(self) -> None:
        command, context = self._registered_command()

        first = admit_command(DATABASE_URL, command, context=context)
        replay = admit_command(DATABASE_URL, command, context=context)

        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["operation_id"], first["operation_id"])

    def test_same_key_and_different_digest_conflicts(self) -> None:
        command, context = self._registered_command()
        admit_command(DATABASE_URL, command, context=context)

        with self.assertRaises(KernelError) as caught:
            admit_command(
                DATABASE_URL,
                {**command, "input": {"value": "different"}},
                context=context,
            )

        self.assertEqual(caught.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_two_concurrent_admissions_create_one_operation(self) -> None:
        command, context = self._registered_command()
        barrier = Barrier(2)

        def admit_after_barrier() -> dict:
            barrier.wait(timeout=5)
            return admit_command(DATABASE_URL, command, context=context)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: admit_after_barrier(), range(2)))

        self.assertEqual(
            {result["operation_id"] for result in results},
            {results[0]["operation_id"]},
        )
        self.assertEqual(sorted(result["replayed"] for result in results), [False, True])

    def _registered_command(self) -> tuple[dict, AdmissionContext]:
        definition = definition_payload(identifier("definition"))
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        project_id = identifier("project")
        command = {
            "definition_name": definition["name"],
            "definition_version": definition["definition_version"],
            "project_id": project_id,
            "workspace_id": f"workspace:{project_id}",
            "actor_id": "actor-idempotency",
            "idempotency_scope": definition["idempotency_scope"],
            "idempotency_key": identifier("idempotency"),
            "trace_id": identifier("trace"),
            "span_id": identifier("span"),
            "correlation_id": identifier("correlation"),
            "causation_id": "",
            "input": {"value": "same"},
            "input_assets": [],
        }
        context = AdmissionContext(
            actor_id=command["actor_id"],
            permissions=frozenset(definition["permissions"]),
            available_handlers=frozenset({definition["handler_key"]}),
            application_build_id="admission-idempotency-test",
            commit_sha="e" * 40,
        )
        return command, context


if __name__ == "__main__":
    unittest.main()
