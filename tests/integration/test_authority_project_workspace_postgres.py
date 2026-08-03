from __future__ import annotations

import unittest

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
    ProjectAuthorityQuery,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
)


class ProjectWorkspaceAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_id = identifier("project-authority")
        self.workspace_id = identifier("workspace-authority")
        self.application = ProjectAuthorityApplication(
            DATABASE_URL,
            application_build_id="project-authority-integration",
            commit_sha="a" * 40,
        )
        self.query = ProjectAuthorityQuery(DATABASE_URL)
        self.principal = Principal(
            principal_id="project-authority-operator",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset({"project.authority.execute", "project.authority.query"}),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-test",
        )

    def test_create_update_replay_and_lifecycle_use_one_authority_chain(self) -> None:
        create = self._execute(
            "project_lifecycle.create",
            payload={"title": "PostgreSQL Project", "book_number": 1},
            idempotency_key=f"create:{self.project_id}",
        )
        replay = self._execute(
            "project_lifecycle.create",
            payload={"title": "PostgreSQL Project", "book_number": 1},
            idempotency_key=f"create:{self.project_id}",
        )
        project = self.query.require_project(self.project_id)
        update = self._execute(
            "project_lifecycle.update",
            payload={"stage": "PLANNING", "config": {"genre": "mystery"}},
            idempotency_key=f"update:{self.project_id}:2",
            expected_version=project["version"],
            expected_asset_version_id=project["asset_version_id"],
        )
        project = self.query.require_project(self.project_id)
        paused = self._execute(
            "project_lifecycle.transition",
            payload={"target_status": "PAUSED"},
            idempotency_key=f"pause:{self.project_id}:3",
            expected_version=project["version"],
            expected_asset_version_id=project["asset_version_id"],
        )

        self.assertEqual(create["status"], "SUCCEEDED")
        self.assertEqual(replay["operation_id"], create["operation_id"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(update["version"], 2)
        self.assertEqual(paused["version"], 3)
        detail = self.query.require_project(self.project_id)
        self.assertEqual(detail["status"], "PAUSED")
        self.assertEqual(detail["stage"], "PLANNING")
        self.assertEqual(detail["asset_count"], 2)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(DISTINCT operation.operation_id),
                       COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT event.event_id),
                       COUNT(DISTINCT audit.audit_id),
                       COUNT(DISTINCT outbox.outbox_id)
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id = operation.operation_id
                JOIN state_event AS event
                  ON event.payload->>'operation_id' = operation.operation_id
                JOIN audit_log AS audit
                  ON audit.operation_id = operation.operation_id
                JOIN outbox_event AS outbox
                  ON outbox.payload->>'operation_id' = operation.operation_id
                WHERE operation.project_id = %s
                  AND operation.definition_name LIKE 'project_lifecycle.%%'
                """,
                [self.project_id],
            )
            counts = tuple(int(value) for value in uow.cursor.fetchone())
        self.assertEqual(counts[0], 3)
        self.assertEqual(counts[1], 3)
        self.assertGreaterEqual(counts[2], 3)
        self.assertGreaterEqual(counts[3], 3)
        self.assertGreaterEqual(counts[4], 3)

    def test_stale_version_and_path_identity_fail_closed(self) -> None:
        self._execute(
            "project_lifecycle.create",
            payload={"title": "Bound Project"},
            idempotency_key=f"create:{self.project_id}",
        )
        current = self.query.require_project(self.project_id)
        with self.assertRaisesRegex(KernelError, "FILESYSTEM_AUTHORITY_FORBIDDEN"):
            self._execute(
                "project_lifecycle.update",
                payload={"config": {"style_profile_path": "data/styles/legacy.json"}},
                idempotency_key=f"unsafe:{self.project_id}",
                expected_version=current["version"],
                expected_asset_version_id=current["asset_version_id"],
            )
        with self.assertRaisesRegex(KernelError, "PROJECT_VERSION_CONFLICT"):
            self._execute(
                "project_lifecycle.update",
                payload={"health": "HEALTHY"},
                idempotency_key=f"stale:{self.project_id}",
                expected_version=current["version"] + 1,
                expected_asset_version_id=current["asset_version_id"],
            )

    def test_binding_assign_replay_remove_and_scope_use_versioned_decisions(self) -> None:
        self._execute(
            "project_lifecycle.create",
            payload={"title": "Binding Authority Project"},
            idempotency_key=f"create:{self.project_id}",
        )
        target_version_id = self._insert_target("style_profile")
        current = self.query.require_project(self.project_id)
        assigned = self._execute(
            "project_binding.assign",
            payload={
                "binding_type": "STYLE_PROFILE",
                "target_asset_version_id": target_version_id,
                "expected_binding_asset_version_id": "",
            },
            idempotency_key=f"bind:{self.project_id}:style",
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
        )
        replay = self._execute(
            "project_binding.assign",
            payload={
                "binding_type": "STYLE_PROFILE",
                "target_asset_version_id": target_version_id,
                "expected_binding_asset_version_id": "",
            },
            idempotency_key=f"bind:{self.project_id}:style",
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
        )
        bindings = self.query.list_bindings(project_id=self.project_id)

        self.assertEqual(assigned["version"], 2)
        self.assertEqual(replay["operation_id"], assigned["operation_id"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(bindings), 1)
        self.assertTrue(bindings[0]["active"])
        self.assertEqual(bindings[0]["status"], "BOUND")
        self.assertEqual(bindings[0]["target_asset_version_id"], target_version_id)
        binding_version_id = bindings[0]["binding_asset_version_id"]

        current = self.query.require_project(self.project_id)
        removed = self._execute(
            "project_binding.remove",
            payload={
                "binding_type": "STYLE_PROFILE",
                "expected_binding_asset_version_id": binding_version_id,
            },
            idempotency_key=f"unbind:{self.project_id}:style",
            expected_version=current["version"],
            expected_asset_version_id=current["asset_version_id"],
        )
        bindings = self.query.list_bindings(project_id=self.project_id)

        self.assertEqual(removed["version"], 3)
        self.assertEqual(len(bindings), 1)
        self.assertFalse(bindings[0]["active"])
        self.assertEqual(bindings[0]["status"], "REMOVED")
        detail = self.query.require_project(self.project_id)
        self.assertNotIn("STYLE_PROFILE", detail["content"]["bindings"])
        self.assertEqual(
            detail["content"]["binding_decisions"]["STYLE_PROFILE"],
            bindings[0]["binding_asset_version_id"],
        )

    def _insert_target(self, asset_type: str) -> str:
        asset_id = identifier(asset_type)
        version_id = identifier(f"{asset_type}-version")
        logical_ref = f"profiles/{asset_id}"
        content = {"schema_version": "test-fixture.v1", "title": "Profile"}
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                INSERT INTO authority_asset (asset_id, project_id, asset_type)
                VALUES (%s, %s, %s)
                """,
                [asset_id, self.project_id, asset_type],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_version (
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', %s, %s)
                """,
                [version_id, asset_id, Jsonb(content), f"sha256:{version_id}"],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_qualification (
                    qualification_id, asset_version_id, policy_version,
                    decision, evidence
                ) VALUES (%s, %s, 'integration-fixture-v1', 'ELIGIBLE', %s)
                """,
                [identifier("qualification"), version_id, Jsonb({"fixture": True})],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_asset_locator (
                    project_id, logical_ref, category, asset_id,
                    current_asset_version_id
                ) VALUES (%s, %s, 'profiles', %s, %s)
                """,
                [self.project_id, logical_ref, asset_id, version_id],
            )
            uow.commit()
        return version_id

    def _execute(
        self,
        definition_name: str,
        *,
        payload: dict,
        idempotency_key: str,
        expected_version: int = 0,
        expected_asset_version_id: str = "",
    ) -> dict:
        return self.application.execute(
            ProjectAuthorityCommand(
                definition_name=definition_name,
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.principal.principal_id,
                idempotency_key=idempotency_key,
                trace_id=f"trace:{self.project_id}",
                correlation_id=f"correlation:{self.project_id}",
                payload=payload,
                expected_version=expected_version,
                expected_current_asset_version_id=expected_asset_version_id,
            ),
            principal=self.principal,
        )


if __name__ == "__main__":
    unittest.main()
