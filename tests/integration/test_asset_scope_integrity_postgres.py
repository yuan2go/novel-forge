from __future__ import annotations

import unittest

import psycopg

from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    seed_authority_project_book,
    transaction,
)


class AssetScopeIntegrityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def setUp(self) -> None:
        self.project_a = identifier("scope-project-a")
        self.project_b = identifier("scope-project-b")
        self.book_a = identifier("scope-book-a")
        self.book_b = identifier("scope-book-b")
        seed_authority_project_book(project_id=self.project_a, book_id=self.book_a)
        seed_authority_project_book(project_id=self.project_b, book_id=self.book_b)

    def test_schema_version_has_no_default_and_omission_is_rejected(self) -> None:
        asset_id = identifier("schema-required-asset")
        with self.assertRaises(psycopg.errors.NotNullViolation):
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s, %s, 'test')",
                    [asset_id, self.project_a],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR', '{}'::jsonb, 'sha256:test')
                    """,
                    [identifier("missing-schema-version"), asset_id],
                )

        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name='authority_asset_version'
                  AND column_name='schema_version'
                """
            )
            self.assertIsNone(cursor.fetchone()[0])

    def test_cross_project_plan_asset_is_rejected_by_database(self) -> None:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_book_asset_version_id, created_by_operation_id
                FROM authority_book WHERE book_id=%s
                """,
                [self.book_b],
            )
            foreign_version_id, operation_id = cursor.fetchone()

        with self.assertRaises(psycopg.errors.CheckViolation) as caught:
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO story_plan_binding(
                        binding_id, project_id, book_id, contract_type, logical_key,
                        asset_version_id, execution_scope, freshness,
                        created_by_operation_id
                    ) VALUES (%s, %s, %s, 'BOOK', 'book:cross-scope', %s,
                              'PLANNED', 'CURRENT', %s)
                    """,
                    [identifier("cross-binding"), self.project_a, self.book_a,
                     foreign_version_id, operation_id],
                )
        self.assertEqual(
            caught.exception.diag.constraint_name,
            "authority_asset_version_project_scope_check",
        )

    def test_workspace_and_book_cross_scope_is_rejected_by_database(self) -> None:
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT created_by_operation_id FROM authority_book WHERE book_id=%s",
                [self.book_a],
            )
            operation_id = cursor.fetchone()[0]
        book_asset_id = identifier("cross-book-asset")

        with self.assertRaises(psycopg.errors.CheckViolation) as caught:
            with transaction() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id, project_id, asset_type) VALUES (%s, %s, 'book')",
                    [book_asset_id, self.project_a],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR',
                              '{}'::jsonb, 'sha256:cross-book', 'book-authority.v1')
                    """,
                    [f"{book_asset_id}:v1", book_asset_id],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_book(
                        book_id, project_id, workspace_id, principal_id, service_identity,
                        book_scope, production_profile, runtime_policy, release_identity,
                        status, current_book_asset_version_id,
                        created_by_operation_id, last_operation_id
                    ) VALUES (%s, %s, %s, 'operator', 'service', '{}'::jsonb,
                              '{}'::jsonb, '{}'::jsonb, 'release', 'DESIGN_PENDING',
                              %s, %s, %s)
                    """,
                    [identifier("cross-book"), self.project_a,
                     f"workspace:{self.project_b}", f"{book_asset_id}:v1",
                     operation_id, operation_id],
                )
        self.assertEqual(
            caught.exception.diag.constraint_name,
            "authority_book_workspace_project_check",
        )


if __name__ == "__main__":
    unittest.main()
