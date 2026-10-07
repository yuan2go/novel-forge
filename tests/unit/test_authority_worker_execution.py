from __future__ import annotations

import unittest

from psycopg.errors import DeadlockDetected, SerializationFailure, UndefinedColumn
from datetime import datetime, timezone

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.worker_execution import (
    AuthorityWorkerExecutionBoundary,
    WorkerFailureClass,
    WorkerFailureClassifier,
    WorkerHealthStatus,
    WorkerProgrammingError,
    WorkerSupervisor,
)


class AuthorityWorkerExecutionTests(unittest.TestCase):
    def test_classifier_covers_runtime_failure_classes(self) -> None:
        cases = (
            (
                KernelError("TEMPORARY_PROVIDER_FAILURE", "retry"),
                WorkerFailureClass.RETRYABLE,
            ),
            (KernelError("INPUT_INVALID", "bad"), WorkerFailureClass.FINAL_FAILURE),
            (
                KernelError(
                    "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "frozen capacity"
                ),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            (
                KernelError(
                    "SOURCE_PROVIDER_SCHEMA_REJECTED", "frozen schema rejected"
                ),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            (
                KernelError("CHAPTER_PROVIDER_CONTEXT_PROJECTION_TOO_BROAD", "replan"),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            (
                KernelError("EFFECT_STATE_UNKNOWN", "unknown"),
                WorkerFailureClass.UNKNOWN_EXTERNAL_STATE,
            ),
            (
                KernelError("LEASE_NOT_AVAILABLE", "leased"),
                WorkerFailureClass.LEASE_CONFLICT,
            ),
            (
                KernelError("ATTEMPT_FENCING_TOKEN_STALE", "stale"),
                WorkerFailureClass.FENCING_CONFLICT,
            ),
            (
                KernelError("OPERATION_CANCELLED", "cancelled"),
                WorkerFailureClass.CANCELLATION,
            ),
            (
                KernelError("ATTEMPT_RETRY_EXHAUSTED", "dead"),
                WorkerFailureClass.DEAD_LETTER,
            ),
            (
                KernelError("WAITING_GATE", "human"),
                WorkerFailureClass.MANUAL_INTERVENTION,
            ),
            (
                KernelError("CHAPTER_QUALITY_GATE_BLOCKED", "quality evidence failed"),
                WorkerFailureClass.MANUAL_INTERVENTION,
            ),
            (
                KernelError("CHAPTER_QUALITY_GATE_FAILED", "deterministic gate failed"),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            (
                KernelError(
                    "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
                    "replacement owner is terminally lost",
                ),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            (
                KernelError(
                    "NARRATIVE_EVALUATION_BOOK_OPENING_EXECUTION_GATE_CLOSED",
                    "original Opening owner was aborted",
                ),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            *(
                (
                    KernelError(code, "frozen Provider authorization is closed"),
                    WorkerFailureClass.FINAL_FAILURE,
                )
                for code in (
                    "BUDGET_SCOPE_CONFLICT",
                    "BUDGET_SCOPE_NOT_FOUND",
                    "BOOK_OPENING_BUDGET_EFFECT_BINDING_REQUIRED",
                    "BOOK_OPENING_PROVIDER_EXECUTION_NOT_AUTHORIZED",
                    "BOOK_OPENING_PROVIDER_EXECUTION_NOT_LIVE",
                )
            ),
            (
                KernelError("MODEL_EFFECT_TIMEOUT", "provider timed out"),
                WorkerFailureClass.RETRYABLE,
            ),
            (
                KernelError(
                    "MODEL_EFFECT_RETRYABLE_OUTPUT_SCHEMA_FAILURE",
                    "retry structured output",
                ),
                WorkerFailureClass.RETRYABLE,
            ),
            (
                KernelError(
                    "MODEL_EFFECT_FINAL_UNAUTHORIZED_TOOL_INVOCATION",
                    "tool denied",
                ),
                WorkerFailureClass.FINAL_FAILURE,
            ),
            (TypeError("bug"), WorkerFailureClass.PROGRAMMING_BUG),
        )
        for error, expected in cases:
            with self.subTest(error=error):
                self.assertEqual(WorkerFailureClassifier.classify(error), expected)

    def test_only_known_aborted_database_transactions_are_retryable(self) -> None:
        for error in (DeadlockDetected("deadlock"), SerializationFailure("conflict")):
            self.assertEqual(WorkerFailureClassifier.classify(error), WorkerFailureClass.RETRYABLE)
            failures = AuthorityWorkerExecutionBoundary(worker_kind="chapter").execute_batch(
                (("p", "op"),), identity=lambda item: item,
                execute=lambda item: (_ for _ in ()).throw(error),
            )
            self.assertEqual(failures[0].error_code, "POSTGRES_TRANSACTION_RETRY")
        self.assertEqual(WorkerFailureClassifier.classify(UndefinedColumn("schema bug")), WorkerFailureClass.PROGRAMMING_BUG)

    def test_batch_continues_after_known_task_failure(self) -> None:
        visited: list[str] = []

        def execute(item: tuple[str, str]) -> None:
            visited.append(item[1])
            if item[1] == "first":
                raise KernelError("INPUT_INVALID", "isolated")

        failures = AuthorityWorkerExecutionBoundary(worker_kind="unit").execute_batch(
            (("project-a", "first"), ("project-a", "second")),
            identity=lambda item: item,
            execute=execute,
        )
        self.assertEqual(visited, ["first", "second"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].classification, WorkerFailureClass.FINAL_FAILURE)

    def test_supervision_snapshot_exposes_restart_and_fatal_contract(self) -> None:
        observed = []
        supervisor = WorkerSupervisor(
            worker_kind="chapter",
            worker_id="configured-worker",
            observer=observed.append,
            clock=lambda: datetime(2026, 7, 18, tzinfo=timezone.utc),
        )
        supervisor.polled(idle=False)
        supervisor.batch_completed(())
        fatal = supervisor.fatal(RuntimeError("broken invariant"))
        self.assertEqual(fatal.status, WorkerHealthStatus.FATAL)
        self.assertEqual(fatal.exit_code, 70)
        self.assertIn("broken invariant", fatal.last_fatal_error)
        self.assertEqual(
            fatal.restart_policy_expectation,
            "restart_on_nonzero_exit_with_backoff",
        )
        self.assertEqual(observed[-1], fatal)

    def test_programming_bug_is_raised_after_rest_of_batch(self) -> None:
        visited: list[str] = []

        def execute(item: tuple[str, str]) -> None:
            visited.append(item[1])
            if item[1] == "first":
                raise TypeError("bug")

        with self.assertRaises(WorkerProgrammingError):
            AuthorityWorkerExecutionBoundary(worker_kind="unit").execute_batch(
                (("project-a", "first"), ("project-a", "second")),
                identity=lambda item: item,
                execute=execute,
            )
        self.assertEqual(visited, ["first", "second"])


if __name__ == "__main__":
    unittest.main()
