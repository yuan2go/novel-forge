from __future__ import annotations

import unittest

from novel_forge.agents.runtime import agent_runtime_profile
from novel_forge.modules.production_execution import (
    AgentResultKind,
    AgentWorkspaceExecutionBackend,
    AgentWorkspaceExecutionContract,
    AgentWorkspaceResultCandidate,
    DomainExecutionCandidate,
    DomainExecutionEvidence,
    execute_agent_workspace_candidate,
)


def _evidence() -> DomainExecutionEvidence:
    return DomainExecutionEvidence(
        execution_id="agent-execution-1",
        operation_id="agent-operation-1",
        attempt_id="agent-attempt-1",
        fencing_token=1,
        capability="agent.workspace.execute",
        backend_id="agent-workspace",
        route_snapshot_id="agent-route-1",
        input_manifest_ref="agent-input-1",
        output_manifest_ref="agent-output-1",
        validation_manifest_ref="agent-validation-1",
        usage_receipt_ref="agent-usage-unavailable",
        cost_receipt_ref="agent-cost-unavailable",
        fixture_protocol_only=True,
        real_model_call=False,
        production_verified=False,
    )


class _AgentFixturePort:
    def __init__(self) -> None:
        self.capability = ""

    def execute(self, command):
        self.capability = command.capability
        return DomainExecutionCandidate(
            command.candidate_kind,
            {
                "result_kind": "workspace_manifest",
                "workspace_manifest": {
                    "workspace_snapshot_ref": "workspace-snapshot-1",
                    "files_changed": ["src/example.py"],
                    "proposed_only": True,
                },
            },
            _evidence(),
        )


class AgentWorkspaceExecutionMigrationTests(unittest.TestCase):
    def test_agent_profiles_request_execution_without_selecting_model_adapter(
        self,
    ) -> None:
        for key in ("analysis", "topic", "outline", "chapter_plan", "draft", "review", "ai_editor", "model_evaluation"):
            tools = agent_runtime_profile(key)["allowed_tools"]
            self.assertIn("request_production_execution", tools)
            self.assertNotIn("call_model_adapter", tools)

    def test_workspace_result_is_candidate_not_commit(self) -> None:
        port = _AgentFixturePort()
        candidate = execute_agent_workspace_candidate(
            instruction="Prepare a bounded patch candidate.",
            workspace_contract={
                "workspace_snapshot_ref": "workspace-snapshot-1",
                "read_set": ["src"],
                "write_set": ["src/example.py"],
                "allowed_tools": ["rg", "apply_patch"],
                "allowed_commands": [["git", "diff", "--check"]],
                "network_policy": "DENY",
                "git_base_sha": "a" * 40,
                "expected_output_contract": "workspace-manifest.v1",
                "maximum_agent_hops": 1,
                "maximum_files_changed": 2,
                "maximum_cost": "1.00",
                "approval_policy": "AUTHORITY_REVIEW_REQUIRED",
            },
            execution_port=port,
        )

        self.assertEqual(port.capability, "agent.workspace.execute")
        self.assertEqual(candidate.result_kind, AgentResultKind.WORKSPACE_MANIFEST)
        self.assertEqual(candidate.commit_status, "NOT_COMMITTED")
        self.assertTrue(candidate.result["workspace_manifest"]["proposed_only"])

    def test_agent_candidate_rejects_commit_activation_or_route_claim(self) -> None:
        for forbidden in ("git_commit_accepted", "active_asset_version_id", "provider_id"):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(
                    ValueError,
                    "forbidden commit or route claim",
                ):
                    AgentWorkspaceResultCandidate(
                        result_kind=AgentResultKind.PATCH_CANDIDATE,
                        result={"patch": "candidate", forbidden: True},
                        evidence=_evidence(),
                    )

    def test_workspace_contract_is_validated_before_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "contract is incomplete"):
            execute_agent_workspace_candidate(
                instruction="Prepare a bounded patch candidate.",
                workspace_contract={
                    "workspace_snapshot_ref": "workspace-snapshot-1",
                    "read_set": ["src"],
                    "write_set": ["src"],
                },
                execution_port=_AgentFixturePort(),
            )

    def test_backend_enforces_tool_command_network_and_cost_evidence(self) -> None:
        contract = AgentWorkspaceExecutionContract(
            workspace_snapshot_ref="workspace-snapshot-1",
            read_set=("src",),
            write_set=("src",),
            allowed_tools=("rg", "apply_patch"),
            allowed_commands=(("rg", "--files"),),
            network_policy="DENY",
            git_base_sha="a" * 40,
            expected_output_contract="workspace-manifest.v1",
            maximum_agent_hops=1,
            maximum_files_changed=2,
            maximum_cost="1.00",
            approval_policy="AUTHORITY_REVIEW_REQUIRED",
        )
        for evidence, message in (
            ({"tools_used": ["curl"]}, "tool outside allowlist"),
            ({"commands_run": [["git", "push"]]}, "command outside allowlist"),
            ({"network_accesses": ["https://example.invalid"]}, "network DENY"),
            ({"cost_amount": "1.01"}, "maximum cost"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    AgentWorkspaceExecutionBackend._validate_runner_evidence(
                        evidence,
                        contract,
                    )


if __name__ == "__main__":
    unittest.main()
