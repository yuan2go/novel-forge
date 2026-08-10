from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from novel_forge.api.authority_dependencies import build_chapter_authority_application
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.agent_collaboration.domain import (
    AgentCapability,
    AgentDefinition,
    AgentMessageType,
)
from novel_forge.modules.agent_runtime.application import (
    AgentRuntimeAdminCommand,
    AgentRuntimeAuthorityApplication,
)
from novel_forge.modules.agent_runtime.queries import AgentRuntimeQuery
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.capability_packs.compiler import (
    CompiledCapabilityPack,
    CompiledWorkflowNode,
)
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    connect,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration import test_chapter_authority_scheduler_postgres as chapter_scheduler_fixtures


RELEASE_SHA = "a" * 40


def _hash(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class UnifiedAgentRuntimePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_runtime_projection_reuses_kernel_attempt_and_lease_tables(self) -> None:
        with connect() as connection:
            tables = connection.execute(
                """
                SELECT
                    to_regclass('authority_agent_definition_activation'),
                    to_regclass('authority_chapter_node_agent_binding'),
                    to_regclass('authority_agent_runtime_binding'),
                    to_regclass('authority_attempt'),
                    to_regclass('authority_lease_acquisition'),
                    to_regclass('authority_agent_attempt'),
                    to_regclass('authority_agent_lease')
                """
            ).fetchone()

        self.assertEqual(
            tuple("" if value is None else str(value) for value in tables),
            (
                "authority_agent_definition_activation",
                "authority_chapter_node_agent_binding",
                "authority_agent_runtime_binding",
                "authority_attempt",
                "authority_lease_acquisition",
                "",
                "",
            ),
        )

    def test_runtime_binding_has_no_duplicate_status_column(self) -> None:
        with connect() as connection:
            columns = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='authority_agent_runtime_binding'
                    """
                ).fetchall()
            }

        self.assertIn("operation_id", columns)
        self.assertIn("attempt_id", columns)
        self.assertIn("fencing_token", columns)
        self.assertNotIn("run_status", columns)
        self.assertNotIn("attempt_status", columns)

    def test_draft_agent_runs_one_chapter_attempt_to_exact_domain_commit(self) -> None:
        project_id = identifier("unified-agent-draft")
        workspace_id = f"workspace:{project_id}"
        actor = "unified-agent-operator"
        worker = "unified-agent-worker"
        with tempfile.TemporaryDirectory(prefix="novel-forge-agent-") as object_root:
            settings = IndustrialSettings(
                root=Path.cwd(), environment="test", database_url=DATABASE_URL
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "test",
                "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": object_root,
            }
            chapter = build_chapter_authority_application(settings, env=env)
            principal = Principal(
                principal_id=actor,
                principal_type=PrincipalType.LOCAL_OPERATOR,
                permissions=frozenset({
                    "chapter.authority.execute", "agent.authority.admin"
                }),
                project_scope=frozenset({project_id}),
                authentication_source="integration-fixture",
            )
            request = SingleChapterRequest(
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=actor,
                chapter=1,
                title="One Fenced Draft",
                premise="A promise creates a visible irreversible cost.",
                trace_id=identifier("agent-draft-trace"),
                correlation_id=identifier("agent-draft-correlation"),
                application_build_id="unified-agent-integration",
                commit_sha=RELEASE_SHA,
                idempotency_key=f"{project_id}:chapter:1",
                preparation_report={"decision": "READY", "fixture": True},
                context_candidates=tuple(
                    chapter_scheduler_fixtures.ChapterAuthoritySchedulerPostgresTests._release_evidence(
                        project_id
                    )
                ),
            )
            seed_authority_project_book(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=f"book:{project_id}",
            )
            admission = chapter.admit(request, principal=principal)
            self._register_draft_agent(
                project_id=project_id,
                workspace_id=workspace_id,
                actor=actor,
                principal=principal,
            )
            scheduler = chapter.scheduler(
                principal=Principal(
                    principal_id=worker,
                    principal_type=PrincipalType.WORKER,
                    permissions=frozenset({"chapter.authority.execute"}),
                    project_scope=frozenset({project_id}),
                    authentication_source="integration-fixture",
                )
            )
            self.assertEqual(
                scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                ).node,
                "plan",
            )
            self.assertEqual(
                scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                ).node,
                "context",
            )
            draft = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            self.assertEqual(draft.node, "draft")
            self.assertEqual(draft.operation_status, "SUCCEEDED")

        with connect() as connection:
            row = connection.execute(
                """
                SELECT operation.operation_id,
                       COUNT(DISTINCT attempt.attempt_id),
                       COUNT(DISTINCT binding.binding_id),
                       COUNT(DISTINCT candidate.candidate_version_id),
                       COUNT(DISTINCT decision.decision_id),
                       COUNT(DISTINCT commit.commit_id),
                       COUNT(DISTINCT output.asset_version_id),
                       MAX(commit.asset_version_id),
                       MAX(output.asset_version_id)
                FROM authority_operation AS operation
                JOIN authority_attempt AS attempt
                  ON attempt.operation_id=operation.operation_id
                JOIN authority_agent_runtime_binding AS binding
                  ON binding.operation_id=operation.operation_id
                JOIN authority_agent_work_order AS work_order
                  ON work_order.work_order_id=binding.work_order_id
                JOIN authority_agent_candidate_version AS candidate
                  ON candidate.originating_turn_id=work_order.turn_id
                JOIN authority_agent_collaboration_decision AS decision
                  ON decision.candidate_version_id=candidate.candidate_version_id
                JOIN authority_agent_collaboration_commit AS commit
                  ON commit.candidate_version_id=candidate.candidate_version_id
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                 AND output.role='primary'
                WHERE operation.project_id=%s
                  AND operation.definition_name='chapter.draft.generate'
                GROUP BY operation.operation_id
                """,
                [project_id],
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(tuple(row[1:7]), (1, 1, 1, 1, 1, 1))
        self.assertEqual(row[7], row[8])
        query = AgentRuntimeQuery(DATABASE_URL)
        run = query.require_run(project_id=project_id, agent_run_id=str(row[0]))
        self.assertEqual(run["candidate_status"], "CANDIDATE_READY")
        self.assertEqual(run["domain_commit_status"], "DOMAIN_COMMITTED")
        lineage = query.require_asset_lineage(
            project_id=project_id, asset_version_id=str(row[7])
        )
        self.assertEqual(lineage["lineage_strength"], "EXACT_COLLABORATION_COMMIT")

    @staticmethod
    def _register_draft_agent(
        *, project_id: str, workspace_id: str, actor: str, principal: Principal
    ) -> None:
        identity_suffix = project_id.rsplit("-", maxsplit=1)[-1]
        capability_id = f"prose.chapter.draft.{identity_suffix}"
        agent_id = f"chapter-draft-agent-{identity_suffix}"
        with connect() as connection:
            authority = connection.execute(
                """
                SELECT definition_hash, handler_key, handler_contract_version,
                       retry_policy, timeout_policy, approval_policy,
                       compensation_policy, completion_contract
                FROM authority_operation_definition
                WHERE name='chapter.draft.generate' AND definition_version='2.3.1'
                """
            ).fetchone()
        assert authority is not None
        capability = AgentCapability(
            capability_id=capability_id,
            version=1,
            domain="chapter",
            input_schema_ref="schema:chapter-draft-input@1",
            output_schema_ref="schema:chapter-draft-candidate@1",
            supported_message_types=(AgentMessageType.PROPOSAL,),
            supported_scope_types=("CHAPTER",),
            risk_class="HIGH",
            execution_requirements={"production_execution_gateway_required": True},
            qualification_status="QUALIFIED_FIXTURE",
        )
        definition = AgentDefinition(
            agent_id=agent_id,
            version=1,
            agent_type="DRAFT",
            domain="chapter",
            role="DRAFT_AGENT",
            capability_refs=(f"{capability_id}@1",),
            input_contract_ref=capability.input_schema_ref,
            output_contract_ref=capability.output_schema_ref,
            authority_scope_ref="scope:chapter@1",
            default_scope_policy_ref="scope:chapter-frozen@1",
            allowed_tools=("request_production_execution",),
            allowed_context_types=("context_bundle",),
            execution_policy_ref="execution:pep@1",
            approval_policy_ref="approval:chapter-authority@1",
            quality_policy_ref="quality:chapter-domain-handler@1",
            status="ACTIVE",
        )
        runtime = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id="unified-agent-integration",
            commit_sha=RELEASE_SHA,
        )
        hash_a, hash_b, hash_c = _hash("a"), _hash("b"), _hash("c")
        commands = [
            AgentRuntimeAdminCommand(
                definition_name="agent.definition.register",
                project_id=project_id, workspace_id=workspace_id,
                agent_id=definition.agent_id, actor_id=actor,
                idempotency_key=f"{project_id}:agent:register",
                trace_id=f"trace:{project_id}:agent-register",
                correlation_id=f"correlation:{project_id}",
                payload={
                    "capability": {
                        "capability_id": capability.capability_id,
                        "version": capability.version,
                        "domain": capability.domain,
                        "input_schema_ref": capability.input_schema_ref,
                        "output_schema_ref": capability.output_schema_ref,
                        "supported_message_types": ["PROPOSAL"],
                        "supported_scope_types": ["CHAPTER"],
                        "risk_class": capability.risk_class,
                        "execution_requirements": dict(
                            capability.execution_requirements
                        ),
                        "qualification_status": capability.qualification_status,
                    },
                    "definition": {
                        "agent_id": definition.agent_id,
                        "version": definition.version,
                        "agent_type": definition.agent_type,
                        "domain": definition.domain,
                        "role": definition.role,
                        "capability_refs": list(definition.capability_refs),
                        "input_contract_ref": definition.input_contract_ref,
                        "output_contract_ref": definition.output_contract_ref,
                        "authority_scope_ref": definition.authority_scope_ref,
                        "default_scope_policy_ref": definition.default_scope_policy_ref,
                        "allowed_tools": list(definition.allowed_tools),
                        "allowed_context_types": list(
                            definition.allowed_context_types
                        ),
                        "execution_policy_ref": definition.execution_policy_ref,
                        "approval_policy_ref": definition.approval_policy_ref,
                        "quality_policy_ref": definition.quality_policy_ref,
                        "status": definition.status,
                    },
                    "execution_mapping": {
                        "capability_id": capability.capability_id,
                        "capability_version": 1,
                        "execution_capability_id": "prose.chapter.draft",
                        "execution_capability_hash": hash_a,
                    },
                    "runtime_contract": {
                        "agent_id": definition.agent_id,
                        "definition_version": 1,
                        "capability_pack_ref": "chapter_generation_pack@1.1.0",
                        "prompt_bundle_ref": "prompt:chapter:draft@1",
                        "prompt_bundle_hash": hash_a,
                        "skill_bundle_ref": "skill:chapter:draft@1",
                        "skill_bundle_hash": hash_b,
                        "tool_policy_ref": "tools:chapter:draft@1",
                        "tool_policy_hash": hash_c,
                        "context_policy_ref": "context:chapter:draft@1",
                        "context_policy_hash": hash_a,
                        "definition_source": "POSTGRES_AUTHORITY",
                    },
                },
            ),
            AgentRuntimeAdminCommand(
                definition_name="agent.definition.activate",
                project_id=project_id, workspace_id=workspace_id,
                agent_id=definition.agent_id, actor_id=actor,
                idempotency_key=f"{project_id}:agent:activate",
                trace_id=f"trace:{project_id}:agent-activate",
                correlation_id=f"correlation:{project_id}",
                payload={"definition_version": 1, "reason": "fixture activation"},
            ),
        ]
        for command in commands:
            runtime.execute_admin(command, principal=principal)

        node = CompiledWorkflowNode(
            ordinal=3, node_id="draft",
            definition_name="chapter.draft.generate", definition_version="2.3.1",
            definition_hash=str(authority[0]), handler_key=str(authority[1]),
            handler_contract_version=str(authority[2]),
            capability_id=capability.capability_id,
            capability_contract_hash=capability.capability_hash,
            agent_definition_ref=f"{definition.agent_id}@1", depends_on=("context",),
            authoritative_retry_policy_json=json.dumps(authority[3]),
            authoritative_timeout_policy_json=json.dumps(authority[4]),
            authoritative_approval_policy_json=json.dumps(authority[5]),
            authoritative_compensation_policy_json=json.dumps(authority[6]),
            authoritative_completion_contract_json=json.dumps(authority[7]),
        )
        compiled = CompiledCapabilityPack(
            schema_version="novelos.capability_pack.compiled.v1",
            pack_id="chapter_generation_pack", pack_version="1.1.0",
            manifest_hash=hash_a, protocol_version="novelos.capability_pack.v1",
            target_runtime_profile="fixture", novel_forge_version="7.0.0",
            release_channel="fixture", release_sha=RELEASE_SHA,
            catalog_snapshot_hash=hash_b, compilation_hash="",
            capability_type_policy_json="{}", resolved_capabilities_json="[]",
            resolved_operations_json="[]", resolved_artifacts_json="[]",
            workflow_nodes=(node,), external_input_asset_contract=("context_bundle",),
            completion_contract_json="{}", tool_permission_snapshot_json="{}",
            context_source_snapshot_json="{}", evaluation_gate_snapshot_json="{}",
            audit_requirement_snapshot_json="{}", version_resolution_snapshot_json="{}",
        )
        compiled_payload = compiled.to_dict()
        compiled_payload.pop("compilation_hash")
        compiled_payload["compilation_hash"] = _hash(compiled_payload)
        binding_id = f"chapter-draft-binding:{project_id}"
        with connect() as connection:
            binding_version = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(binding_version), 0) + 1
                    FROM authority_chapter_node_agent_binding
                    WHERE workflow_definition_ref='chapter_authority_slice@2.3.1'
                      AND workflow_node_id='draft'
                    """
                ).fetchone()[0]
            )
            activation_row = connection.execute(
                """
                SELECT activation_version
                FROM authority_chapter_node_agent_binding_activation
                WHERE workflow_definition_ref='chapter_authority_slice@2.3.1'
                  AND workflow_node_id='draft'
                """
            ).fetchone()
            expected_activation_version = (
                int(activation_row[0]) if activation_row is not None else 0
            )
        runtime.execute_admin(
            AgentRuntimeAdminCommand(
                definition_name="agent.chapter_binding.register",
                project_id=project_id, workspace_id=workspace_id,
                agent_id=definition.agent_id, actor_id=actor,
                idempotency_key=f"{project_id}:binding:register",
                trace_id=f"trace:{project_id}:binding-register",
                correlation_id=f"correlation:{project_id}",
                payload={
                    "authority_mode": "DEVELOPMENT_FIXTURE",
                    "binding_id": binding_id, "binding_version": binding_version,
                    "workflow_definition_ref": "chapter_authority_slice@2.3.1",
                    "workflow_node_id": "draft",
                    "operation_definition_ref": "chapter.draft.generate@2.3.1",
                    "operation_definition_hash": str(authority[0]),
                    "agent_definition_ref": f"{definition.agent_id}@1",
                    "agent_definition_hash": definition.definition_hash,
                    "capability_ref": f"{capability.capability_id}@1",
                    "capability_hash": capability.capability_hash,
                    "execution_capability_id": "prose.chapter.draft",
                    "capability_pack_ref": "chapter_generation_pack@1.1.0",
                    "capability_pack_compilation_hash": compiled_payload["compilation_hash"],
                    "input_contract_ref": capability.input_schema_ref,
                    "output_contract_ref": capability.output_schema_ref,
                    "domain_acceptance_policy_ref": "acceptance:chapter-draft@1",
                    "commit_authority": "CHAPTER_AUTHORITY", "status": "ACTIVE",
                    "release_sha": RELEASE_SHA,
                    "compiled_capability_pack": compiled_payload,
                },
            ),
            principal=principal,
        )
        runtime.execute_admin(
            AgentRuntimeAdminCommand(
                definition_name="agent.chapter_binding.activate",
                project_id=project_id, workspace_id=workspace_id,
                agent_id=definition.agent_id, actor_id=actor,
                idempotency_key=f"{project_id}:binding:activate",
                trace_id=f"trace:{project_id}:binding-activate",
                correlation_id=f"correlation:{project_id}",
                expected_activation_version=expected_activation_version,
                payload={
                    "authority_mode": "DEVELOPMENT_FIXTURE",
                    "workflow_definition_ref": "chapter_authority_slice@2.3.1",
                    "workflow_node_id": "draft", "binding_id": binding_id,
                    "binding_version": binding_version, "status": "ACTIVE",
                    "reason": "fixture activation",
                },
            ),
            principal=principal,
        )


if __name__ == "__main__":
    unittest.main()
