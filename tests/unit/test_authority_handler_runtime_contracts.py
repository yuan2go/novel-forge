from __future__ import annotations

import unittest

from novel_forge.modules.authority_handler_runtime.contracts import (
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
)
from novel_forge.modules.authority_handler_runtime.runtime import _validate_output
from novel_forge.modules.command_kernel.errors import KernelError


class AuthorityHandlerRuntimeContractTests(unittest.TestCase):
    def test_host_database_context_is_private_and_separate_from_command(self) -> None:
        from novel_forge.modules.authority_handler_runtime.contracts import AuthorityHandlerRequest
        request = AuthorityHandlerRequest(operation_id="o", project_id="p", workspace_id="w", actor_id="a",
            trace_id="t", correlation_id="c", definition_name="fixture", definition_version="1",
            command={"database_url": "untrusted-command"}, inputs=(), database_url="host=fixture password=PRIVATE_HOST_CONTEXT")
        self.assertEqual(request.database_url, "host=fixture password=PRIVATE_HOST_CONTEXT")
        self.assertNotIn("PRIVATE_HOST_CONTEXT", repr(request))
        self.assertEqual(request.command["database_url"], "untrusted-command")

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
