from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, transaction
from tests.integration.test_authority_asset_blob_schema_postgres import (
    insert_asset,
    insert_asset_version,
)
from tests.integration.test_command_kernel_definition_postgres import definition_payload


class CommandKernelAdmissionValidationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def _register(self, **overrides: object) -> dict:
        definition = {
            **definition_payload(identifier("definition")),
            **overrides,
        }
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        return definition

    def _context(self, definition: dict, **overrides: object) -> AdmissionContext:
        values = {
            "actor_id": "actor-1",
            "permissions": frozenset(definition["permissions"]),
            "available_handlers": frozenset({definition["handler_key"]}),
            "application_build_id": "admission-build-1",
            "commit_sha": "b" * 40,
        }
        values.update(overrides)
        return AdmissionContext(**values)

    def _command(self, definition: dict, **overrides: object) -> dict:
        project_id = str(overrides.get("project_id") or identifier("project"))
        values = {
            "definition_name": definition["name"],
            "definition_version": definition["definition_version"],
            "project_id": project_id,
            "workspace_id": f"workspace:{project_id}",
            "actor_id": "actor-1",
            "idempotency_scope": "project:operation",
            "idempotency_key": identifier("idempotency"),
            "trace_id": identifier("trace"),
            "span_id": identifier("span"),
            "correlation_id": identifier("correlation"),
            "causation_id": "",
            "input": {"value": "accepted"},
            "input_assets": [],
        }
        values.update(overrides)
        return values

    def assert_admission_error(
        self,
        expected_code: str,
        *,
        definition: dict,
        command: dict,
        context: AdmissionContext,
    ) -> None:
        with self.assertRaises(KernelError) as caught:
            admit_command(DATABASE_URL, command, context=context)
        self.assertEqual(caught.exception.code, expected_code)

    def test_definition_must_exist_and_be_enabled(self) -> None:
        missing = definition_payload(identifier("missing-definition"))
        self.assert_admission_error(
            "OPERATION_DEFINITION_NOT_FOUND",
            definition=missing,
            command=self._command(missing),
            context=self._context(missing),
        )

        disabled = self._register(enabled=False)
        self.assert_admission_error(
            "OPERATION_DEFINITION_DISABLED",
            definition=disabled,
            command=self._command(disabled),
            context=self._context(disabled),
        )

    def test_command_schema_and_actor_identity_fail_closed(self) -> None:
        definition = self._register()
        cases = (
            ("COMMAND_SCHEMA_INVALID", {"input": {}}),
            ("ACTOR_IDENTITY_INVALID", {"actor_id": "another-actor"}),
            ("COMMAND_SCHEMA_INVALID", {"workspace_id": ""}),
        )
        for expected_code, overrides in cases:
            with self.subTest(expected_code=expected_code, overrides=overrides):
                self.assert_admission_error(
                    expected_code,
                    definition=definition,
                    command=self._command(definition, **overrides),
                    context=self._context(definition),
                )

    def test_handler_permission_and_approval_are_required(self) -> None:
        definition = self._register()
        self.assert_admission_error(
            "HANDLER_NOT_AVAILABLE",
            definition=definition,
            command=self._command(definition),
            context=self._context(definition, available_handlers=frozenset()),
        )
        self.assert_admission_error(
            "PERMISSION_DENIED",
            definition=definition,
            command=self._command(definition),
            context=self._context(definition, permissions=frozenset()),
        )

        approval_definition = self._register(
            approval_policy={"required": True, "policy_key": "ops.approval.v1"}
        )
        self.assert_admission_error(
            "APPROVAL_REQUIRED",
            definition=approval_definition,
            command=self._command(approval_definition),
            context=self._context(approval_definition),
        )

    def test_input_asset_hash_and_project_scope_are_validated(self) -> None:
        definition = self._register()
        owning_project = identifier("owning-project")
        other_project = identifier("other-project")
        asset = identifier("asset")
        version = identifier("version")
        with transaction() as connection, connection.cursor() as cursor:
            insert_asset(cursor, asset_id=asset, project_id=owning_project)
            insert_asset_version(cursor, asset_version_id=version, asset_id=asset)

        for expected_code, project_id, content_hash in (
            ("CROSS_PROJECT_REFERENCE", other_project, f"hash:{version}"),
            ("INPUT_ASSET_HASH_MISMATCH", owning_project, "hash:wrong"),
        ):
            with self.subTest(expected_code=expected_code):
                command = self._command(
                    definition,
                    project_id=project_id,
                    input_assets=[
                        {
                            "asset_version_id": version,
                            "content_hash": content_hash,
                        }
                    ],
                )
                self.assert_admission_error(
                    expected_code,
                    definition=definition,
                    command=command,
                    context=self._context(definition),
                )


if __name__ == "__main__":
    unittest.main()
