from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lifecycle import (
    ATTEMPT_TRANSITIONS,
    OPERATION_TRANSITIONS,
    AttemptStatus,
    OperationStatus,
    require_attempt_transition,
    require_transition,
)


class CommandKernelLifecycleTests(unittest.TestCase):
    def test_every_nonterminal_operation_state_has_the_designed_outgoing_rules(self) -> None:
        self.assertEqual(
            set(OPERATION_TRANSITIONS),
            {
                OperationStatus.ADMITTED,
                OperationStatus.WAITING_APPROVAL,
                OperationStatus.READY,
                OperationStatus.EXECUTING,
                OperationStatus.WAITING_CHILDREN,
                OperationStatus.WAITING_EXTERNAL_RESULT,
                OperationStatus.WAITING_GATE,
                OperationStatus.FAILED_RETRYABLE,
                OperationStatus.CANCELLATION_REQUESTED,
                OperationStatus.RECONCILIATION_REQUIRED,
                OperationStatus.COMPENSATION_REQUIRED,
                OperationStatus.COMPENSATING,
            },
        )
        require_transition("WAITING_CHILDREN", "WAITING_GATE")
        require_transition("WAITING_GATE", "SUCCEEDED")
        require_transition("RECONCILIATION_REQUIRED", "COMPENSATION_REQUIRED")

    def test_every_nonterminal_attempt_state_has_the_designed_outgoing_rules(self) -> None:
        self.assertEqual(
            set(ATTEMPT_TRANSITIONS),
            {
                AttemptStatus.CREATED,
                AttemptStatus.QUEUED,
                AttemptStatus.LEASED,
                AttemptStatus.RUNNING,
                AttemptStatus.CHECKPOINTED,
                AttemptStatus.RESULT_SUBMITTED,
            },
        )
        require_attempt_transition("CHECKPOINTED", "RUNNING")
        require_attempt_transition("RESULT_SUBMITTED", "LATE_RESULT_REJECTED")

    def test_cancel_requires_reconciliation_or_compensation_before_terminal_state(self) -> None:
        require_transition("CANCELLATION_REQUESTED", "RECONCILIATION_REQUIRED")
        with self.assertRaises(KernelError) as caught:
            require_transition("CANCELLATION_REQUESTED", "SUCCEEDED")
        self.assertEqual(caught.exception.code, "OPERATION_TRANSITION_INVALID")
