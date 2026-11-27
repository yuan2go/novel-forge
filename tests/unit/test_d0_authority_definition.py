from __future__ import annotations

import unittest
from types import ModuleType
from unittest.mock import patch
import sys

from novel_forge.modules.provider_qualification.definitions import d0_operation_definition
from novel_forge.modules.provider_control.openai_v2 import build_openai_provider_adapter


class D0AuthorityDefinitionTests(unittest.TestCase):
    def test_d0_is_a_worker_durable_job_with_receipt_policy(self) -> None:
        definition = d0_operation_definition(
            application_build_id="test", commit_sha="a" * 40
        )
        self.assertEqual(definition["execution_mode"], "worker")
        self.assertEqual(
            definition["policy"]["execution_classification"], "durable_job"
        )
        self.assertEqual(definition["policy"]["sdk_max_retries"], 0)
        self.assertTrue(
            definition["irreversible_effect_policy"]["receipt_required"]
        )

    def test_openai_composition_disables_sdk_retries(self) -> None:
        captured: dict[str, object] = {}
        module = ModuleType("openai")

        def client(**kwargs: object) -> object:
            captured.update(kwargs)
            return object()

        module.OpenAI = client  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"openai": module}):
            adapter = build_openai_provider_adapter("injected-only-for-construction-test")

        self.assertEqual(captured["max_retries"], 0)
        self.assertNotIn("api_key", adapter.capability_profile.to_dict())


if __name__ == "__main__":
    unittest.main()
