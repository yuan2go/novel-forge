from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    operation_graph,
    register_saga_step,
    start_saga,
)
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)


class OperationGraphSagaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_linear_branch_and_join_graph_discovers_only_satisfied_children(self) -> None:
        context, root, children = self._graph_fixture(4)
        a, b, c, join = children
        add_operation_dependency(DATABASE_URL, context, b, a, "ON_SUCCESS")
        add_operation_dependency(DATABASE_URL, context, c, a, "ON_SUCCESS")
        add_operation_dependency(DATABASE_URL, context, join, b, "ON_COMPLETION")
        add_operation_dependency(DATABASE_URL, context, join, c, "ON_SUCCESS")

        initial = operation_graph(DATABASE_URL, context.project_id, root)
        self.assertEqual(initial["ready"], [a])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'SUCCEEDED' WHERE operation_id = %s",
                [a],
            )
        branched = operation_graph(DATABASE_URL, context.project_id, root)
        self.assertEqual(set(branched["ready"]), {b, c})
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'FAILED_FINAL' WHERE operation_id = %s",
                [b],
            )
            cursor.execute(
                "UPDATE authority_operation SET status = 'SUCCEEDED' WHERE operation_id = %s",
                [c],
            )
        joined = operation_graph(DATABASE_URL, context.project_id, root)
        self.assertEqual(joined["ready"], [join])

    def test_dependency_conditions_and_cycle_are_enforced(self) -> None:
        context, root, children = self._graph_fixture(5)
        success, failure, compensated, manual, target = children
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'SUCCEEDED' WHERE operation_id = %s",
                [success],
            )
            cursor.execute(
                "UPDATE authority_operation SET status = 'FAILED_FINAL' WHERE operation_id = %s",
                [failure],
            )
            cursor.execute(
                "UPDATE authority_operation SET status = 'COMPENSATED' WHERE operation_id = %s",
                [compensated],
            )
        add_operation_dependency(DATABASE_URL, context, target, success, "ON_SUCCESS")
        add_operation_dependency(DATABASE_URL, context, target, failure, "ON_FAILURE")
        add_operation_dependency(DATABASE_URL, context, target, compensated, "ON_COMPENSATED")
        add_operation_dependency(DATABASE_URL, context, target, manual, "MANUAL_GATE")
        self.assertIn(target, operation_graph(DATABASE_URL, context.project_id, root)["blocked"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_completion_gate (
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (%s, %s, %s, 'PASSED', '{}'::jsonb)
                """,
                [identifier("gate"), target, f"dependency:{manual}"],
            )
        self.assertIn(target, operation_graph(DATABASE_URL, context.project_id, root)["ready"])
        with self.assertRaises(KernelError) as cycle:
            add_operation_dependency(DATABASE_URL, context, success, target, "ON_SUCCESS")
        self.assertEqual(cycle.exception.code, "DEPENDENCY_CYCLE")

    def test_saga_forward_completion_is_idempotent_under_concurrent_ticks(self) -> None:
        context, root, children = self._graph_fixture(2, root_status="EXECUTING")
        first, second = children
        saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)["saga_id"]
        register_saga_step(DATABASE_URL, context, saga_id, first, "first", 1, "comp.first")
        register_saga_step(DATABASE_URL, context, saga_id, second, "second", 2, "comp.second")
        add_operation_dependency(DATABASE_URL, context, second, first, "ON_SUCCESS")
        tick = coordinate_saga(DATABASE_URL, context, saga_id)
        self.assertEqual(tick["ready"], [first])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'SUCCEEDED' WHERE operation_id IN (%s, %s)",
                [first, second],
            )
        barrier = Barrier(2)

        def coordinate() -> str:
            barrier.wait(timeout=5)
            return coordinate_saga(DATABASE_URL, context, saga_id)["status"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: coordinate(), range(2)))
        self.assertEqual(statuses, ["SUCCEEDED", "SUCCEEDED"])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT status FROM authority_operation WHERE operation_id = %s", [root])
            self.assertEqual(cursor.fetchone()[0], "SUCCEEDED")

    def test_saga_failure_plans_reverse_compensation_and_distinguishes_partial_failure(self) -> None:
        context, root, children = self._graph_fixture(3, root_status="EXECUTING")
        first, second, third = children
        saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)["saga_id"]
        for ordinal, operation_id in enumerate(children, start=1):
            register_saga_step(
                DATABASE_URL,
                context,
                saga_id,
                operation_id,
                f"step-{ordinal}",
                ordinal,
                f"comp.step-{ordinal}",
            )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'SUCCEEDED' WHERE operation_id IN (%s, %s)",
                [first, second],
            )
            cursor.execute(
                "UPDATE authority_operation SET status = 'FAILED_FINAL' WHERE operation_id = %s",
                [third],
            )
        failed = coordinate_saga(DATABASE_URL, context, saga_id)
        self.assertEqual(failed["status"], "COMPENSATING")
        self.assertEqual(failed["compensation_order"], [second, first])
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_saga_step SET compensation_status = 'COMPENSATED' WHERE operation_id = %s",
                [second],
            )
            cursor.execute(
                "UPDATE authority_saga_step SET compensation_status = 'COMPENSATION_FAILED' WHERE operation_id = %s",
                [first],
            )
        partial = coordinate_saga(DATABASE_URL, context, saga_id)
        self.assertEqual(partial["status"], "COMPENSATION_FAILED")
        self.assertEqual(partial["manual_intervention"], [first])

    def _graph_fixture(
        self,
        child_count: int,
        *,
        root_status: str = "ADMITTED",
    ) -> tuple[GraphCommandContext, str, list[str]]:
        project_id = identifier("project")
        definition = identifier("graph-definition")
        root = identifier("root")
        children = [identifier("child") for _ in range(child_count)]
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition)
            insert_operation(
                cursor,
                operation_id=root,
                definition_name=definition,
                project_id=project_id,
                status=root_status,
            )
            for child in children:
                insert_operation(
                    cursor,
                    operation_id=child,
                    definition_name=definition,
                    project_id=project_id,
                    root_operation_id=root,
                    parent_operation_id=root,
                )
        return (
            GraphCommandContext(
                project_id=project_id,
                actor_id="saga-coordinator",
                trace_id=identifier("trace"),
                correlation_id=identifier("correlation"),
            ),
            root,
            children,
        )


if __name__ == "__main__":
    unittest.main()
