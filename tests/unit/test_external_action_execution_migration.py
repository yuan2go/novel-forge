from __future__ import annotations

import unittest

from novel_forge.modules.publishing_feedback_adapters import (
    fetch_platform_feedback_candidate,
    query_platform_release_candidate,
    withdraw_platform_release_candidate,
)
from novel_forge.modules.production_execution import (
    ExternalActionCandidate,
    ExternalActionCommand,
    ExternalActionExecutionEvidence,
    ExternalActionKind,
    execute_external_action,
)
from novel_forge.modules.source_intake import fetch_remote_source_candidate


class _ExternalFixturePort:
    def __init__(self) -> None:
        self.commands: list[ExternalActionCommand] = []

    def execute(self, command: ExternalActionCommand) -> ExternalActionCandidate:
        self.commands.append(command)
        return ExternalActionCandidate(
            raw_output={
                "status": "fixture",
                "fixture_protocol_only": True,
                "real_model_call": False,
                "production_verified": False,
            },
            evidence=_fixture_evidence(command.capability),
        )


def _fixture_evidence(capability: str) -> ExternalActionExecutionEvidence:
    return ExternalActionExecutionEvidence(
        execution_id="external-fixture-execution",
        operation_id="external-fixture-operation",
        attempt_id="external-fixture-attempt",
        fencing_token=1,
        capability=capability,
        backend_id="remote-external-action",
        route_snapshot_id="external-fixture-route",
        input_manifest_ref="external-fixture-input",
        output_manifest_ref="external-fixture-output",
        validation_manifest_ref="external-fixture-validation",
        external_receipt_ref="external-fixture-receipt",
        usage_receipt_ref="external-fixture-usage-unavailable",
        cost_receipt_ref="external-fixture-cost-unavailable",
        external_request_id="external-fixture-request",
        query_supported=True,
        cancel_supported=True,
        callback_supported=True,
        fixture_protocol_only=True,
    )


class ExternalActionExecutionMigrationTests(unittest.TestCase):
    def test_all_external_domains_use_registered_capabilities(self) -> None:
        port = _ExternalFixturePort()

        for capability in ExternalActionKind:
            with self.subTest(capability=capability.value):
                candidate = execute_external_action(
                    capability=capability,
                    request_payload={"target_ref": f"asset:{capability.value}"},
                    stable_idempotency_key=f"{capability.value}:fixture:1",
                    data_classification="INTERNAL",
                    privacy_policy_ref="privacy-policy:fixture:v1",
                    rate_limit_policy_ref="rate-limit-policy:fixture:v1",
                    quota_policy_ref="quota-policy:fixture:v1",
                    execution_port=port,
                )
                self.assertEqual(
                    candidate.evidence.capability,
                    capability.value,
                )
                self.assertTrue(candidate.evidence.fixture_protocol_only)
                self.assertFalse(candidate.evidence.real_model_call)
                self.assertFalse(candidate.evidence.real_external_action)
                self.assertFalse(candidate.evidence.production_verified)

        self.assertEqual(
            [command.capability for command in port.commands],
            [capability.value for capability in ExternalActionKind],
        )

    def test_external_command_requires_governance_and_stable_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "governance contract"):
            ExternalActionCommand(
                capability=ExternalActionKind.SOURCE_FETCH,
                request_payload={"source_ref": "source:1"},
                stable_idempotency_key="",
                data_classification="PUBLIC",
                privacy_policy_ref="",
                rate_limit_policy_ref="",
                quota_policy_ref="",
            )
        command = ExternalActionCommand(
            capability=ExternalActionKind.SOURCE_FETCH,
            request_payload={"source_ref": "source:1"},
            stable_idempotency_key="source.fetch:1",
            data_classification="PUBLIC",
            privacy_policy_ref="privacy-policy:source:v1",
            rate_limit_policy_ref="rate-limit-policy:source:v1",
            quota_policy_ref="quota-policy:source:v1",
        )
        self.assertEqual(command.contract_hash, command.contract_hash)
        self.assertNotEqual(
            command.contract_hash,
            ExternalActionCommand(
                **{
                    **command.to_dict(),
                    "request_payload": {"source_ref": "source:2"},
                }
            ).contract_hash,
        )

    def test_fixture_evidence_cannot_claim_real_or_production_status(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot claim real evidence"):
            ExternalActionExecutionEvidence(
                **{
                    **_fixture_evidence(
                        ExternalActionKind.NOTIFICATION_SEND.value
                    ).to_dict(),
                    "real_external_action": True,
                }
            )

    def test_external_evidence_cannot_claim_model_call(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot claim a model call"):
            ExternalActionExecutionEvidence(
                **{
                    **_fixture_evidence(
                        ExternalActionKind.FEEDBACK_FETCH.value
                    ).to_dict(),
                    "fixture_protocol_only": False,
                    "real_model_call": True,
                }
            )

    def test_domain_facades_return_candidates_without_domain_commit(self) -> None:
        port = _ExternalFixturePort()

        query = query_platform_release_candidate(
            platform_id="fixture-platform",
            external_release_ref="release:1",
            stable_idempotency_key="publishing.query:1",
            execution_port=port,
        )
        withdraw = withdraw_platform_release_candidate(
            platform_id="fixture-platform",
            external_release_ref="release:1",
            reason="superseded",
            stable_idempotency_key="publishing.withdraw:1",
            execution_port=port,
        )
        feedback = fetch_platform_feedback_candidate(
            platform_id="fixture-platform",
            cursor_ref="cursor:1",
            stable_idempotency_key="feedback.fetch:1",
            execution_port=port,
        )
        source = fetch_remote_source_candidate(
            source_ref="source:1",
            connector_id="rss",
            source_policy_ref="source-policy:1",
            stable_idempotency_key="source.fetch:1",
            execution_port=port,
        )

        self.assertFalse(query["domain_status_committed"])
        self.assertFalse(withdraw["withdrawal_committed"])
        self.assertFalse(feedback["feedback_imported"])
        self.assertFalse(feedback["reader_outcome_calibrated"])
        self.assertFalse(source["source_eligibility_decided"])
        self.assertFalse(source["asset_committed"])
        self.assertEqual(
            [command.capability for command in port.commands],
            [
                ExternalActionKind.PUBLISH_QUERY.value,
                ExternalActionKind.PUBLISH_WITHDRAW.value,
                ExternalActionKind.FEEDBACK_FETCH.value,
                ExternalActionKind.SOURCE_FETCH.value,
            ],
        )


if __name__ == "__main__":
    unittest.main()
