from __future__ import annotations

import unittest

from novel_forge.modules.production_execution import (
    CandidateKind,
    DomainExecutionCommand,
    DomainModelOperation,
    execute_domain_candidate,
)


class _GatewayPort:
    def __init__(self) -> None:
        self.command: DomainExecutionCommand | None = None

    def execute(self, command: DomainExecutionCommand):
        from novel_forge.modules.production_execution import (
            DomainExecutionCandidate,
            DomainExecutionEvidence,
        )

        self.command = command
        return DomainExecutionCandidate(
            command.candidate_kind,
            {"title": "candidate"},
            DomainExecutionEvidence(
                execution_id="execution-1",
                operation_id="operation-1",
                attempt_id="attempt-1",
                fencing_token=1,
                capability=command.capability,
                backend_id="scripted-fixture",
                route_snapshot_id="route-1",
                input_manifest_ref="input-1",
                output_manifest_ref="output-1",
                validation_manifest_ref="validation-1",
                usage_receipt_ref="usage-1",
                cost_receipt_ref="cost-1",
                fixture_protocol_only=True,
                real_model_call=False,
                production_verified=False,
            ),
        )


class DomainExecutionPortTests(unittest.TestCase):
    def test_domain_receives_candidate_and_cannot_receive_committed_asset(self) -> None:
        port = _GatewayPort()
        candidate = execute_domain_candidate(
            capability="planning.chapter.generate",
            operation=DomainModelOperation.GENERATE,
            candidate_kind=CandidateKind.GENERATION,
            prompt="Compile the frozen chapter plan candidate.",
            context={"input_manifest_ref": "input-1"},
            execution_port=port,
        )

        self.assertEqual(candidate.raw_output, {"title": "candidate"})
        self.assertEqual(candidate.evidence.validation_manifest_ref, "validation-1")
        self.assertFalse(hasattr(candidate, "active_asset_version_id"))
        self.assertEqual(port.command.capability, "planning.chapter.generate")

if __name__ == "__main__":
    unittest.main()
