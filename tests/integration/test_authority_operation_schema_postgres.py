from __future__ import annotations

import unittest

import psycopg

from tests.integration.authority_postgres_support import (
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class AuthorityOperationSchemaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_invalid_operation_status_is_rejected(self) -> None:
        definition = identifier("definition")
        operation = identifier("operation")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_definition(cursor, definition)
                insert_operation(
                    cursor,
                    operation_id=operation,
                    definition_name=definition,
                    project_id=identifier("project"),
                    status="NOT_A_KERNEL_STATE",
                )

    def test_operation_cannot_depend_on_itself(self) -> None:
        definition = identifier("definition")
        operation = identifier("operation")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_definition(cursor, definition)
                insert_operation(
                    cursor,
                    operation_id=operation,
                    definition_name=definition,
                    project_id=identifier("project"),
                )
                cursor.execute(
                    """
                    INSERT INTO authority_operation_dependency (
                        operation_id,
                        depends_on_operation_id,
                        dependency_condition
                    )
                    VALUES (%s, %s, 'SUCCEEDED')
                    """,
                    [operation, operation],
                )

    def test_parent_root_and_causation_are_foreign_keys(self) -> None:
        for relation in (
            "parent_operation_id",
            "root_operation_id",
            "causation_operation_id",
        ):
            with self.subTest(relation=relation):
                definition = identifier("definition")
                operation = identifier("operation")
                missing = identifier("missing")
                with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        insert_definition(cursor, definition)
                        insert_operation(
                            cursor,
                            operation_id=operation,
                            definition_name=definition,
                            project_id=identifier("project"),
                            **{relation: missing},
                        )

    def test_parent_and_root_must_share_the_child_project(self) -> None:
        for relation in (
            "parent_operation_id",
            "root_operation_id",
            "causation_operation_id",
        ):
            with self.subTest(relation=relation):
                definition = identifier("definition")
                referenced = identifier("referenced")
                child = identifier("child")
                with self.assertRaises(psycopg.errors.CheckViolation):
                    with transaction() as connection, connection.cursor() as cursor:
                        insert_definition(cursor, definition)
                        insert_operation(
                            cursor,
                            operation_id=referenced,
                            definition_name=definition,
                            project_id=identifier("project-a"),
                        )
                        insert_operation(
                            cursor,
                            operation_id=child,
                            definition_name=definition,
                            project_id=identifier("project-b"),
                            **{relation: referenced},
                        )

    def test_dependency_cycle_is_rejected(self) -> None:
        definition = identifier("definition")
        project = identifier("project")
        first = identifier("operation-a")
        second = identifier("operation-b")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with transaction() as connection, connection.cursor() as cursor:
                insert_definition(cursor, definition)
                insert_operation(
                    cursor,
                    operation_id=first,
                    definition_name=definition,
                    project_id=project,
                )
                insert_operation(
                    cursor,
                    operation_id=second,
                    definition_name=definition,
                    project_id=project,
                )
                cursor.execute(
                    """
                    INSERT INTO authority_operation_dependency (
                        operation_id,
                        depends_on_operation_id,
                        dependency_condition
                    )
                    VALUES (%s, %s, 'SUCCEEDED')
                    """,
                    [first, second],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_operation_dependency (
                        operation_id,
                        depends_on_operation_id,
                        dependency_condition
                    )
                    VALUES (%s, %s, 'SUCCEEDED')
                    """,
                    [second, first],
                )


if __name__ == "__main__":
    unittest.main()
