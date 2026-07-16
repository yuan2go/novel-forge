from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery, AuthorityAssetWriter
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class AuthorityAssetStorePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def _operation(self, project_id: str) -> str:
        operation_id = identifier("asset-operation")
        definition_name = identifier("asset-definition")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=project_id,
                status="EXECUTING",
            )
        return operation_id

    def _command(
        self,
        *,
        operation_id: str,
        project_id: str,
        asset_id: str,
        logical_ref: str,
        revision: int,
        expected_version_id: str | None,
        references: tuple[str, ...] = (),
    ) -> AuthorityAssetWriteCommand:
        return AuthorityAssetWriteCommand(
            operation_id=operation_id,
            project_id=project_id,
            asset_id=asset_id,
            asset_type="chapter_plan",
            logical_ref=logical_ref,
            category="chapter_plans",
            output_key="chapter.plan",
            role="primary",
            content={
                "id": asset_id,
                "type": "chapter_plan",
                "metadata": {"project_id": project_id},
                "content": {"chapter": 1, "revision": revision},
            },
            expected_current_asset_version_id=expected_version_id,
            reference_asset_ids=references,
            qualification_policy="chapter-plan-v1",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
            causation_id="",
        )

    def test_materialize_query_update_and_stale_write_rejection(self) -> None:
        project_id = identifier("project")
        asset_id = identifier("asset")
        logical_ref = "chapter_plans/chapter-1.json"
        writer = AuthorityAssetWriter(DATABASE_URL)
        query = AuthorityAssetQuery(DATABASE_URL)

        first = writer.materialize_output(
            self._command(
                operation_id=self._operation(project_id),
                project_id=project_id,
                asset_id=asset_id,
                logical_ref=logical_ref,
                revision=1,
                expected_version_id=None,
            )
        )
        loaded = query.require(project_id=project_id, logical_ref=logical_ref)

        self.assertEqual(loaded.asset_version_id, first.asset_version_id)
        self.assertEqual(loaded.ref.asset_id, asset_id)
        self.assertEqual(loaded.content["content"]["revision"], 1)
        self.assertEqual(query.latest(project_id=project_id, category="chapter_plans"), loaded)
        self.assertEqual(query.count(project_id=project_id, category="chapter_plans"), 1)

        second = writer.materialize_output(
            self._command(
                operation_id=self._operation(project_id),
                project_id=project_id,
                asset_id=asset_id,
                logical_ref=logical_ref,
                revision=2,
                expected_version_id=first.asset_version_id,
            )
        )
        self.assertNotEqual(first.asset_version_id, second.asset_version_id)
        self.assertEqual(second.version_number, 2)
        self.assertEqual(query.require(project_id=project_id, asset_id=asset_id), second)
        historical = query.require(
            project_id=project_id,
            asset_version_id=first.asset_version_id,
        )
        self.assertEqual(historical.lifecycle, "SUPERSEDED")
        self.assertEqual(historical.content["content"]["revision"], 1)

        with self.assertRaisesRegex(KernelError, "AUTHORITY_ASSET_VERSION_CONFLICT"):
            writer.materialize_output(
                self._command(
                    operation_id=self._operation(project_id),
                    project_id=project_id,
                    asset_id=asset_id,
                    logical_ref=logical_ref,
                    revision=3,
                    expected_version_id=first.asset_version_id,
                )
            )

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT lifecycle, COUNT(*) FROM authority_asset_version WHERE asset_id = %s GROUP BY lifecycle",
                [asset_id],
            )
            self.assertEqual(dict(cursor.fetchall()), {"ACTIVE": 1, "SUPERSEDED": 1})
            cursor.execute(
                "SELECT COUNT(*) FROM audit_log WHERE project_id = %s AND action = 'authority.asset.materialized'",
                [project_id],
            )
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_logical_ref_and_references_are_project_scoped(self) -> None:
        project_a = identifier("project-a")
        project_b = identifier("project-b")
        writer = AuthorityAssetWriter(DATABASE_URL)
        source_id = identifier("asset-source")
        writer.materialize_output(
            self._command(
                operation_id=self._operation(project_a),
                project_id=project_a,
                asset_id=source_id,
                logical_ref="chapter_plans/source.json",
                revision=1,
                expected_version_id=None,
            )
        )

        with self.assertRaisesRegex(KernelError, "CROSS_PROJECT_REFERENCE"):
            writer.materialize_output(
                self._command(
                    operation_id=self._operation(project_b),
                    project_id=project_b,
                    asset_id=identifier("asset-target"),
                    logical_ref="chapter_plans/target.json",
                    revision=1,
                    expected_version_id=None,
                    references=(source_id,),
                )
            )

        with self.assertRaisesRegex(KernelError, "AUTHORITY_ASSET_LOCATOR_CONFLICT"):
            writer.materialize_output(
                self._command(
                    operation_id=self._operation(project_a),
                    project_id=project_a,
                    asset_id=identifier("asset-other"),
                    logical_ref="chapter_plans/source.json",
                    revision=1,
                    expected_version_id=None,
                )
            )

    def test_concurrent_first_writers_cannot_split_one_logical_identity(self) -> None:
        project_id = identifier("project-concurrent")
        logical_ref = "chapter_plans/concurrent.json"
        commands = [
            self._command(
                operation_id=self._operation(project_id),
                project_id=project_id,
                asset_id=identifier("asset-concurrent"),
                logical_ref=logical_ref,
                revision=index,
                expected_version_id=None,
            )
            for index in (1, 2)
        ]

        def write(command: AuthorityAssetWriteCommand) -> str:
            try:
                return AuthorityAssetWriter(DATABASE_URL).materialize_output(command).asset_id
            except KernelError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, commands))

        self.assertEqual(sum(item.startswith("asset-concurrent") for item in outcomes), 1)
        self.assertIn("AUTHORITY_ASSET_LOCATOR_CONFLICT", outcomes)
        self.assertEqual(
            AuthorityAssetQuery(DATABASE_URL).count(
                project_id=project_id,
                category="chapter_plans",
            ),
            1,
        )

if __name__ == "__main__":
    unittest.main()
