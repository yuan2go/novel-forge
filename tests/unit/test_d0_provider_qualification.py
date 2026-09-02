from __future__ import annotations

import json
from pathlib import Path
import unittest

from novel_forge.modules.provider_qualification import (
    D0LiveQualificationEvidence,
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

    def test_live_config_freezes_current_route_prompt_and_skill_identity(self) -> None:
        config = D0ProbeConfig.from_mapping(
            json.loads(
                (ROOT / "config/provider/d0-codex-cli-probe.json").read_text(
                    encoding="utf-8"
                )
            )
        )

        self.assertEqual(config.route_policy_version, "chapter.retrieval.route@1")
        self.assertEqual(config.timeout_seconds, 600)
        self.assertEqual(
            config.prompt_version, "prompt-system:chapter-generation-pack@v1"
        )
        self.assertRegex(config.prompt_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(config.instruction_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(config.skill_hash, r"^sha256:[0-9a-f]{64}$")

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

    def test_credentials_cannot_enable_the_non_authority_contract_probe(self) -> None:
        report = run_d0_probe(
            self.config,
            env={
                "OPENAI_API_KEY": "credential-presence-only",
                "NOVEL_FORGE_D0_MODEL": "must-not-be-called",
                "NOVEL_FORGE_D0_MODEL_VERSION": "test",
            },
        )

        self.assertEqual(report.status, "BLOCKED_CONFIGURATION")
        self.assertIn("Authority", report.blocker)
        self.assertTrue(report.fixture_protocol_only)
        self.assertFalse(any(report.gates.values()))

    def test_live_evidence_requires_exact_identity_and_zero_duplicate_send(self) -> None:
        evidence = D0LiveQualificationEvidence.from_mapping(
            {
                "schema_version": "d0-live-qualification-evidence.v1",
                "release_sha": "a" * 40,
                "implementation_identity": "sha256:" + "b" * 64,
                "source_operation_id": "operation:provider-runtime",
                "external_effect_id": "effect:provider-runtime",
                "request_object_ref": "s3://evidence/d0/request.json",
                "response_object_ref": "s3://evidence/d0/response.json",
                "auth_profile_ref": "auth:chatgpt-codex-cli",
                "provider": "codex-cli",
                "backend_id": "codex-cli",
                "model": "gpt-5.6-sol",
                "model_version": "gpt-5.6-sol",
                "route_snapshot_id": "route:retrieval@1",
                "route_snapshot_hash": "sha256:" + "c" * 64,
                "prompt_version": "prompt:retrieval@1",
                "prompt_hash": "sha256:" + "d" * 64,
                "instruction_version": "instruction:retrieval@1",
                "instruction_hash": "sha256:" + "e" * 64,
                "skill_version": "skill:retrieval@1",
                "skill_hash": "sha256:" + "f" * 64,
                "request_hash": "sha256:" + "1" * 64,
                "response_hash": "sha256:" + "2" * 64,
                "provider_execution_id": "chapter-execution:effect:provider-runtime",
                "provider_request_identity": "process-receipt:provider-runtime",
                "usage": {
                    "measurement": "MEASURED",
                    "input_tokens": 11,
                    "output_tokens": 3,
                    "total_tokens": 14,
                },
                "cost": {
                    "amount": "0.0001",
                    "currency": "USD",
                    "estimated": True,
                    "provider_billed": False,
                    "pricing_snapshot_hash": "sha256:" + "3" * 64,
                },
                "latency": {"duration_ms": 42},
                "controlled_failure": {
                    "checkpoint": "after_provider_response_before_effect_receipt",
                    "failure_kind": "response_loss",
                    "request_sent": True,
                },
                "recovery": {
                    "external_state_was_ambiguous": True,
                    "recovered_without_resend": True,
                    "replayed": True,
                },
                "fixture_protocol_only": False,
                "real_model_call": True,
            }
        )

        self.assertEqual(evidence.provider, "codex-cli")
        self.assertEqual(evidence.usage["total_tokens"], 14)
        self.assertTrue(evidence.recovery["recovered_without_resend"])

        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            D0LiveQualificationEvidence.from_mapping(
                {**evidence.to_dict(), "provider_execution_count": 1}
            )

    def test_fixture_cannot_be_parsed_as_live_qualification_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixture"):
            D0LiveQualificationEvidence.from_mapping(
                {
                    "schema_version": "d0-live-qualification-evidence.v1",
                    "fixture_protocol_only": True,
                    "real_model_call": False,
                }
            )


if __name__ == "__main__":
    unittest.main()
