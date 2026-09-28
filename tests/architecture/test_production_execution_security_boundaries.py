from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_forge.modules.production_execution.backends import (
    InMemoryExecutionRecordStore,
    LocalProcessExecutionPolicy,
    ResolvedExecutionPayload,
)
from novel_forge.modules.production_execution.contracts import RouteSnapshot
from novel_forge.modules.production_execution.external_execution import (
    ExternalActionCommand,
)
from novel_forge.modules.production_execution.process_supervisor import (
    EnvironmentAllowlist,
    ProcessLaunchRequest,
    ProcessTimeout,
)
from novel_forge.modules.production_execution.security import (
    LegacyUsageEvent,
    assert_legacy_execution_allowed,
    assert_no_inline_secrets,
    redact_secret_text,
)


class ProductionExecutionSecurityBoundaryTests(unittest.TestCase):
    def test_credential_references_and_usage_counts_are_safe(self) -> None:
        assert_no_inline_secrets(
            {
                "auth_profile_ref": "auth-profile:provider-default",
                "credential_scope": "provider:model-inference",
                "secret_version_ref": "secret-version:provider-default:7",
                "fencing_token": 7,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            }
        )

    def test_inline_secret_keys_and_values_fail_closed(self) -> None:
        unsafe_payloads = (
            {"api_key": "opaque-value"},
            {"nested": {"access_token": "opaque-value"}},
            {"header": "Bearer abcdefghijklmnop"},
            {"instruction": "api_key=abcdefghijklmnop"},
            {"private": "-----BEGIN PRIVATE KEY-----"},
            {"database": "postgresql://operator:secret-value@db/runtime"},
        )
        for payload in unsafe_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "inline secret material"):
                    assert_no_inline_secrets(payload)

    def test_failure_text_redacts_connection_and_credential_material(self) -> None:
        raw = (
            "connection failed for postgresql://operator:database-secret@db/runtime "
            "with api_key=provider-secret-value"
        )

        redacted = redact_secret_text(raw)

        self.assertNotIn("database-secret", redacted)
        self.assertNotIn("provider-secret-value", redacted)
        self.assertIn("[REDACTED", redacted)

    def test_keyword_dsns_are_rejected_and_redacted_without_echoing_values(self) -> None:
        for assignment in ("password=short", "password='two words'", r"password='escaped\'word'", 'PASSWORD="quoted word"'):
            raw = f"connection: host=localhost dbname=fixture {assignment} user=operator"
            with self.subTest(assignment=assignment):
                with self.assertRaisesRegex(ValueError, "inline secret material") as caught:
                    assert_no_inline_secrets({"deployment": {"database_name": raw}})
                self.assertNotIn(assignment, str(caught.exception))
                redacted = redact_secret_text(raw)
                self.assertNotIn(assignment, redacted)
                self.assertIn("[REDACTED_SECRET]", redacted)
                self.assertIn("user=operator", redacted)

    def test_contract_hash_and_evidence_persistence_reject_secrets(self) -> None:
        route = RouteSnapshot(
            route_snapshot_id="route:security:1",
            route_decision_id="route-decision:security:1",
            operation_id="operation:security:1",
            attempt_id="attempt:security:1",
            policy_id="route.policy.security",
            policy_version=1,
            backend_id="remote-provider",
            backend_version="1.0.0",
            runtime_host_id="worker:security:1",
            auth_profile_ref="Bearer abcdefghijklmnop",
            model_profile_id="model.profile.security",
            model_profile_version=1,
            model_profile_hash="a" * 64,
            route_policy_hash="b" * 64,
            model_provider="fixture-provider",
            model_id="fixture-model",
            requested_reasoning_effort="medium",
            reasoning_effort="medium",
            prompt_bundle_ref="prompt-bundle:security:1",
            skill_bundle_ref="skill-bundle:security:1",
            context_bundle_ref="context-bundle:security:1",
            output_schema_ref="schema:security:1",
            release_sha="a" * 40,
            fallback_policy_ref="fallback-policy:fail-closed",
            fallback_policy_version=1,
        )
        with self.assertRaisesRegex(ValueError, "inline secret material"):
            _ = route.contract_hash

        store = InMemoryExecutionRecordStore()
        with self.assertRaisesRegex(ValueError, "inline secret material"):
            store.put_evidence(
                "unsafe",
                "execution:security:1",
                {"client_secret": "opaque-value"},
            )

    def test_external_and_process_requests_cannot_carry_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "inline secret material"):
            ExternalActionCommand(
                capability="notification.send",
                request_payload={"notification": {"authorization": "opaque-value"}},
                stable_idempotency_key="notification:security:1",
                data_classification="INTERNAL",
                privacy_policy_ref="privacy-policy:internal:1",
                rate_limit_policy_ref="rate-limit:notification:1",
                quota_policy_ref="quota:notification:1",
            )
        with self.assertRaisesRegex(ValueError, "inline secret material"):
            ResolvedExecutionPayload(
                request_payload={"input": "bounded"},
                input_text="bounded",
                working_directory=".",
                timeout_seconds=10,
                output_schema_version="result.v1",
                command=("codex", "exec"),
                environment_overrides={"OPENAI_API_KEY": "opaque-value"},
            )
        with self.assertRaisesRegex(ValueError, "inline secret material"):
            ProcessLaunchRequest(
                execution_id="execution:security:1",
                command=("codex", "exec"),
                cwd=".",
                input_text="Bearer abcdefghijklmnop",
                timeout=ProcessTimeout(10),
            )

    def test_process_environment_is_allowlisted_and_result_size_is_bounded(
        self,
    ) -> None:
        environment = EnvironmentAllowlist.codex_default().build(
            {
                "PATH": "/usr/bin",
                "LANG": "C",
                "OPENAI_API_KEY": "must-not-propagate",
            }
        )
        self.assertEqual(environment, {"PATH": "/usr/bin", "LANG": "C"})
        with self.assertRaisesRegex(ValueError, "not allowlisted"):
            EnvironmentAllowlist.codex_default().build(
                {},
                overrides={"OPENAI_API_KEY": "must-not-propagate"},
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            result_path = Path(temporary_directory) / "result.json"
            result_path.write_bytes(b"12345")
            policy = LocalProcessExecutionPolicy(
                fixed_working_directory=temporary_directory,
                allowed_command_prefixes=(("codex", "exec"),),
                maximum_result_bytes=4,
            )
            with self.assertRaisesRegex(ValueError, "size limit"):
                policy.assert_result(str(result_path))

    def test_legacy_usage_event_records_allowed_and_blocked_attempts(self) -> None:
        events: list[LegacyUsageEvent] = []
        allowed = assert_legacy_execution_allowed(
            component="fixture legacy adapter",
            gateway_backed=False,
            environment="development",
            recorder=events.append,
        )
        with self.assertRaisesRegex(RuntimeError, "blocked and disabled"):
            assert_legacy_execution_allowed(
                component="fixture legacy adapter",
                gateway_backed=False,
                environment="production",
                recorder=events.append,
            )

        self.assertEqual(
            [event.decision for event in events],
            ["ALLOWED_DEVELOPMENT_ONLY", "BLOCKED_CONTROLLED"],
        )
        self.assertEqual(allowed.schema_version, "legacy-usage-event.v1")
        self.assertFalse(allowed.production_proof_eligible)
        self.assertFalse(allowed.production_verified)


if __name__ == "__main__":
    unittest.main()
