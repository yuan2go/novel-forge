from __future__ import annotations

import json
from pathlib import Path
import unittest

from novel_forge.modules.provider_qualification import (
    D0ProbeConfig,
    run_d0_probe,
    run_fixture_protocol_probe,
)


ROOT = Path(__file__).resolve().parents[2]


class D0ProviderQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = D0ProbeConfig.from_mapping(
            json.loads(
                (ROOT / "config/provider/d0-openai-probe.json").read_text(
                    encoding="utf-8"
                )
            )
        )

    def test_secret_is_a_reference_not_a_credential(self) -> None:
        self.assertEqual(self.config.auth_secret_ref, "env://OPENAI_API_KEY")
        self.assertEqual(self.config.auth_environment_name, "OPENAI_API_KEY")
        with self.assertRaisesRegex(ValueError, "Secret Reference"):
            D0ProbeConfig.from_mapping(
                {
                    **json.loads(
                        (ROOT / "config/provider/d0-openai-probe.json").read_text()
                    ),
                    "auth_secret_ref": "secret-value-must-not-be-stored",
                }
            )

    def test_fixture_probe_covers_protocol_but_cannot_pass_real_gates(self) -> None:
        report = run_fixture_protocol_probe(self.config)

        self.assertEqual(report.status, "BLOCKED_MISSING_CREDENTIALS")
        self.assertTrue(all(report.contract_checks.values()))
        self.assertFalse(any(report.gates.values()))
        self.assertTrue(report.fixture_protocol_only)
        self.assertFalse(report.external_execution_proven)
        self.assertEqual(report.normalized_usage["total_tokens"], 15)

    def test_missing_credentials_fails_closed_without_a_network_call(self) -> None:
        report = run_d0_probe(
            self.config,
            env={
                "NOVEL_FORGE_D0_MODEL": "configured-but-not-called",
                "NOVEL_FORGE_D0_MODEL_VERSION": "test",
            },
        )

        self.assertEqual(report.status, "BLOCKED_MISSING_CREDENTIALS")
        self.assertFalse(any(report.gates.values()))
        self.assertTrue(report.provider_request_id.startswith("scripted-request:"))


if __name__ == "__main__":
    unittest.main()
