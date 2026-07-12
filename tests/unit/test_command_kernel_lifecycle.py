from __future__ import annotations

import unittest

from novel_forge.modules.command_kernel.lifecycle import require_transition


class CommandKernelLifecycleTests(unittest.TestCase):
    def test_cancel_requires_reconciliation_or_compensation_before_terminal_state(self) -> None:
        require_transition("CANCELLATION_REQUESTED", "RECONCILIATION_REQUIRED")
        with self.assertRaisesRegex(ValueError, "invalid operation transition"):
            require_transition("CANCELLATION_REQUESTED", "SUCCEEDED")
