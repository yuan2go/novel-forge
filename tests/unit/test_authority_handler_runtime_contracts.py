from __future__ import annotations

import unittest

from novel_forge.modules.authority_handler_runtime.contracts import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
)
from novel_forge.modules.authority_handler_runtime.runtime import _validate_output
from novel_forge.modules.command_kernel.errors import KernelError


class AuthorityHandlerRuntimeContractTests(unittest.TestCase):
    def test_malformed_auxiliary_output_uses_stable_kernel_error(self) -> None:
        registration = AuthorityHandlerRegistration(
            definition_name="test.operation",
            definition_version="1.0.0",
            handler_key="test.handler",
            handler_contract_version="1.0.0",
            output_asset_type="primary_asset",
            output_key="primary",
            role="primary",
            completion_topic="test.materialized",
            handler=object(),  # type: ignore[arg-type]
        )
        output = AuthorityHandlerOutput(
            asset_type="primary_asset",
            output_key="primary",
            role="primary",
            content={},
            qualification_policy="test-policy-v1",
            auxiliary_outputs=(object(),),  # type: ignore[arg-type]
        )

        with self.assertRaises(KernelError) as raised:
            _validate_output(registration, output)

        self.assertEqual(raised.exception.code, "AUTHORITY_HANDLER_OUTPUT_INVALID")


if __name__ == "__main__":
    unittest.main()
