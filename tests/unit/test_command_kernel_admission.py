from __future__ import annotations

import unittest
from unittest.mock import patch

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import admit_command


class CommandKernelAdmissionTests(unittest.TestCase):
    def test_missing_command_identity_is_rejected_before_uow(self) -> None:
        with self.assertRaisesRegex(KernelError, "ADMISSION_CONTEXT_REQUIRED"):
            admit_command("postgresql://unit", {})
