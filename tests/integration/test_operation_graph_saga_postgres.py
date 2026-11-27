from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    add_operation_dependency,
    coordinate_saga,
    operation_graph,
    register_saga_step,
    start_saga,
    terminalize_saga_from_extension,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    transaction,
)
from tests.integration.test_command_kernel_definition_postgres import definition_payload


class OperationGraphSagaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_linear_branch_and_join_graph_discovers_only_satisfied_children(
        self,
    ) -> None:
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
        add_operation_dependency(
            DATABASE_URL, context, target, compensated, "ON_COMPENSATED"
        )
        add_operation_dependency(DATABASE_URL, context, target, manual, "MANUAL_GATE")
        self.assertIn(
            target, operation_graph(DATABASE_URL, context.project_id, root)["blocked"]
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_completion_gate (
                    gate_id, operation_id, gate_key, status, evidence
                ) VALUES (%s, %s, %s, 'PASSED', '{}'::jsonb)
                """,
                [identifier("gate"), target, f"dependency:{manual}"],
            )
        self.assertIn(
            target, operation_graph(DATABASE_URL, context.project_id, root)["ready"]
        )
        with self.assertRaises(KernelError) as cycle:
            add_operation_dependency(
                DATABASE_URL, context, success, target, "ON_SUCCESS"
            )
        self.assertEqual(cycle.exception.code, "DEPENDENCY_CYCLE")

    def test_saga_forward_completion_is_idempotent_under_concurrent_ticks(self) -> None:
        context, root, children = self._graph_fixture(2, root_status="EXECUTING")
        first, second = children
        saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)["saga_id"]
        register_saga_step(
            DATABASE_URL, context, saga_id, first, "first", 1, "comp.first"
        )
        register_saga_step(
            DATABASE_URL, context, saga_id, second, "second", 2, "comp.second"
        )
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
            cursor.execute(
                "SELECT status FROM authority_operation WHERE operation_id = %s", [root]
            )
            self.assertEqual(cursor.fetchone()[0], "SUCCEEDED")

    def test_extension_terminalization_rejects_immutable_saga_outcomes(self) -> None:
        for saga_status, root_status in (
            ("SUCCEEDED", "SUCCEEDED"),
            ("COMPENSATED", "COMPENSATED"),
            ("COMPENSATION_FAILED", "COMPENSATION_FAILED"),
        ):
            with self.subTest(saga_status=saga_status):
                context, root, children = self._graph_fixture(
                    1, root_status="EXECUTING"
                )
                extension = children[0]
                saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)[
                    "saga_id"
                ]
                with transaction() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE authority_operation SET status=%s WHERE operation_id=%s",
                        [root_status, root],
                    )
                    cursor.execute(
                        "UPDATE authority_operation SET status='FAILED_FINAL' WHERE operation_id=%s",
                        [extension],
                    )
                    cursor.execute(
                        "UPDATE authority_saga SET status=%s WHERE saga_id=%s",
                        [saga_status, saga_id],
                    )
                with self.assertRaises(KernelError) as caught:
                    terminalize_saga_from_extension(
                        DATABASE_URL,
                        context,
                        saga_id,
                        operation_id=extension,
                    )
                self.assertEqual(
                    caught.exception.code, "SAGA_EXTENSION_TERMINAL_CONFLICT"
                )

    def test_extension_terminalization_replays_only_the_same_outcome(self) -> None:
        context, root, children = self._graph_fixture(2, root_status="EXECUTING")
        failed_extension, cancelled_extension = children
        saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)["saga_id"]
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE authority_operation
                SET status=CASE
                    WHEN operation_id=%s THEN 'FAILED_FINAL'
                    ELSE 'CANCELLED'
                END
                WHERE operation_id IN (%s, %s)
                """,
                [failed_extension, failed_extension, cancelled_extension],
            )
        first = terminalize_saga_from_extension(
            DATABASE_URL, context, saga_id, operation_id=failed_extension
        )
        replay = terminalize_saga_from_extension(
            DATABASE_URL, context, saga_id, operation_id=failed_extension
        )
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        with self.assertRaises(KernelError) as caught:
            terminalize_saga_from_extension(
                DATABASE_URL, context, saga_id, operation_id=cancelled_extension
            )
        self.assertEqual(caught.exception.code, "SAGA_EXTENSION_TERMINAL_CONFLICT")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, saga.status
                FROM authority_operation AS operation
                JOIN authority_saga AS saga
                  ON saga.root_operation_id=operation.operation_id
                WHERE operation.operation_id=%s
                """,
                [root],
            )
            self.assertEqual(cursor.fetchone(), ("FAILED_FINAL", "MANUAL_INTERVENTION"))

    def test_saga_failure_plans_reverse_compensation_and_distinguishes_partial_failure(
        self,
    ) -> None:
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

    def test_retryable_child_uses_forward_recovery_with_fenced_evidence(self) -> None:
        context, root, children = self._graph_fixture(1, root_status="EXECUTING")
        child = children[0]
        saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)["saga_id"]
        register_saga_step(DATABASE_URL, context, saga_id, child, "retryable", 1, "")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'FAILED_RETRYABLE' WHERE operation_id = %s",
                [child],
            )
        recovered = coordinate_saga(DATABASE_URL, context, saga_id)
        self.assertEqual(recovered["status"], "FORWARD_RECOVERY")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation.status, saga.forward_recovery_attempts,
                       saga.coordinator_fencing_token,
                       COUNT(event.event_id)
                FROM authority_operation AS operation
                JOIN authority_saga AS saga ON saga.saga_id = %s
                LEFT JOIN state_event AS event
                  ON event.aggregate_type = 'authority_operation'
                 AND event.aggregate_id = operation.operation_id
                 AND event.event_type = 'authority.operation.saga_transitioned'
                WHERE operation.operation_id = %s
                GROUP BY operation.status, saga.forward_recovery_attempts,
                         saga.coordinator_fencing_token
                """,
                [saga_id, child],
            )
            status, attempts, token, event_count = cursor.fetchone()
            self.assertEqual(status, "READY")
            self.assertEqual(attempts, 1)
            self.assertGreaterEqual(token, 1)
            self.assertEqual(event_count, 1)

    def test_saga_child_uses_standard_admission_attempt_and_completion_path(
        self,
    ) -> None:
        project_id = identifier("project")
        root_definition = definition_payload(identifier("saga-root-definition"))
        child_definition = definition_payload(identifier("saga-child-definition"))
        root_definition["completion_contract"] = {}
        child_definition["completion_contract"] = {}
        root_definition["concurrency_key_template"] = "project:{project_id}:saga-root"
        child_definition["concurrency_key_template"] = "project:{project_id}:saga-child"
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(root_definition)
            uow.repositories.definitions.register(child_definition)
            uow.commit()
        admission = AdmissionContext(
            actor_id="saga-runtime",
            permissions=frozenset({"ops.echo"}),
            available_handlers=frozenset({root_definition["handler_key"]}),
            application_build_id="saga-standard-path-test",
            commit_sha="f" * 40,
        )

        def command(definition: dict, key: str, **relations: str) -> dict:
            return {
                "definition_name": definition["name"],
                "definition_version": definition["definition_version"],
                "project_id": project_id,
                "workspace_id": f"workspace:{project_id}",
                "actor_id": admission.actor_id,
                "idempotency_scope": definition["idempotency_scope"],
                "idempotency_key": key,
                "trace_id": identifier("trace"),
                "span_id": identifier("span"),
                "correlation_id": identifier("correlation"),
                "causation_id": "",
                "input": {"value": key},
                "input_assets": [],
                **relations,
            }

        root = admit_command(
            DATABASE_URL,
            command(root_definition, identifier("root-command")),
            context=admission,
        )["operation_id"]
        for version, current, target in (
            (0, "ADMITTED", "READY"),
            (1, "READY", "EXECUTING"),
        ):
            transition_operation(
                DATABASE_URL,
                OperationTransitionCommand(
                    operation_id=root,
                    project_id=project_id,
                    expected_version=version,
                    expected_status=current,
                    target_status=target,
                    actor_id="saga-runtime",
                    reason="standard saga root lifecycle",
                    trace_id=identifier("trace"),
                    correlation_id=identifier("correlation"),
                    causation_id="",
                ),
            )
        child = admit_command(
            DATABASE_URL,
            command(
                child_definition,
                identifier("child-command"),
                root_operation_id=root,
                parent_operation_id=root,
                causation_operation_id=root,
            ),
            context=admission,
        )["operation_id"]
        graph_context = GraphCommandContext(
            project_id=project_id,
            actor_id="saga-runtime",
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        saga_id = start_saga(DATABASE_URL, graph_context, root_operation_id=root)[
            "saga_id"
        ]
        register_saga_step(
            DATABASE_URL,
            graph_context,
            saga_id,
            child,
            "child",
            1,
            "",
        )
        self.assertEqual(
            coordinate_saga(DATABASE_URL, graph_context, saga_id)["ready"], [child]
        )

        attempt_id = create_attempt(
            DATABASE_URL,
            operation_id=child,
            project_id=project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )["attempt_id"]
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="saga-child-worker",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id="saga-child-worker",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, worker)
        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **worker.__dict__,
                expected_operation_version=2,
                expected_operation_status="EXECUTING",
            ),
            outcome="success",
            result={"completed": True},
        )
        self.assertEqual(
            coordinate_saga(DATABASE_URL, graph_context, saga_id)["status"], "SUCCEEDED"
        )

    def test_saga_admits_and_completes_compensation_child_through_kernel(self) -> None:
        context, root, children = self._graph_fixture(2, root_status="EXECUTING")
        completed_step, failed_step = children
        compensation = definition_payload(identifier("saga-compensation-definition"))
        compensation["completion_contract"] = {}
        compensation["idempotency_scope"] = "operation:compensation"
        compensation["concurrency_key_template"] = (
            "operation:{parent_operation_id}:compensation"
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.repositories.definitions.register(compensation)
            uow.commit()
        admission = AdmissionContext(
            actor_id="saga-compensator",
            permissions=frozenset(compensation["permissions"]),
            available_handlers=frozenset({compensation["handler_key"]}),
            application_build_id="saga-compensation-test",
            commit_sha="c" * 40,
        )
        saga_id = start_saga(DATABASE_URL, context, root_operation_id=root)["saga_id"]
        register_saga_step(
            DATABASE_URL,
            context,
            saga_id,
            completed_step,
            "completed",
            1,
            compensation["name"],
        )
        register_saga_step(
            DATABASE_URL,
            context,
            saga_id,
            failed_step,
            "failed",
            2,
            "",
        )
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE authority_operation SET status = 'SUCCEEDED' WHERE operation_id = %s",
                [completed_step],
            )
            cursor.execute(
                "UPDATE authority_operation SET status = 'FAILED_FINAL' WHERE operation_id = %s",
                [failed_step],
            )
        planned = coordinate_saga(
            DATABASE_URL,
            context,
            saga_id,
            admission_context=admission,
        )
        self.assertEqual(planned["status"], "COMPENSATING")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT compensation_operation_id
                FROM authority_saga_step WHERE operation_id = %s
                """,
                [completed_step],
            )
            compensation_operation_id = cursor.fetchone()[0]
            self.assertTrue(compensation_operation_id)
        coordinate_saga(
            DATABASE_URL,
            context,
            saga_id,
            admission_context=admission,
        )
        attempt_id = create_attempt(
            DATABASE_URL,
            operation_id=compensation_operation_id,
            project_id=context.project_id,
            max_attempts=1,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )["attempt_id"]
        queue_attempt(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=context.project_id,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        lease = acquire_attempt_lease(
            DATABASE_URL,
            attempt_id=attempt_id,
            project_id=context.project_id,
            worker_id="saga-compensation-worker",
            lease_seconds=30,
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=context.project_id,
            worker_id="saga-compensation-worker",
            fencing_token=lease["fencing_token"],
            trace_id=identifier("trace"),
            correlation_id=identifier("correlation"),
        )
        start_attempt(DATABASE_URL, worker)
        submit_attempt_result(
            DATABASE_URL,
            WorkerResultCommand(
                **worker.__dict__,
                expected_operation_version=2,
                expected_operation_status="EXECUTING",
            ),
            outcome="success",
            result={"compensated": True},
        )
        result = coordinate_saga(
            DATABASE_URL,
            context,
            saga_id,
            admission_context=admission,
        )
        self.assertEqual(result["status"], "COMPENSATED")

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
