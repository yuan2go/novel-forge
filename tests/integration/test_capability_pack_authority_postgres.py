from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from novel_forge.modules.agent_collaboration.domain import (
    AgentCapability,
    AgentDefinition,
    AgentMessageType,
)
from novel_forge.modules.agent_runtime.application import (
    AgentRuntimeAdminCommand,
    AgentRuntimeAuthorityApplication,
)
from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
    CapabilityPackAuthorityCommand,
)
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.capability_pack_authority.query import (
    CapabilityPackAuthorityQuery,
)
from novel_forge.modules.capability_packs.artifacts import (
    default_chapter_artifact_resolver,
)
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    seed_authority_project_book,
)
from tests.integration import (
    test_chapter_authority_scheduler_postgres as chapter_scheduler_fixtures,
)


ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "config/capability_packs/chapter_generation_pack.json"
# Match the canonical Chapter Authority integration release so this lifecycle
# remains composable with the full PostgreSQL authority suite.
RELEASE_SHA = "e" * 40
PACK_PERMISSIONS = (
    "capability_pack.authority.register",
    "capability_pack.authority.compile",
    "capability_pack.authority.approve",
    "capability_pack.authority.deploy",
    "capability_pack.authority.activate",
    "capability_pack.authority.rollback",
    "capability_pack.authority.retire",
)


class CapabilityPackAuthorityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_migrated()

    def test_trusted_lifecycle_canary_rollback_and_revocation(self) -> None:
        project_id = identifier("pack-authority")
        workspace_id = f"workspace:{project_id}"
        book_id = f"book:{project_id}"
        seed_authority_project_book(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for definition in chapter_operation_definitions(
                application_build_id="capability-pack-authority-integration",
                commit_sha=RELEASE_SHA,
                model_effects_required=True,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

        compiler = self._principal("pack-compiler", project_id, *PACK_PERMISSIONS)
        approver = self._principal("pack-approver", project_id, *PACK_PERMISSIONS)
        agent_admin = self._principal(
            "agent-admin", project_id, "agent.authority.admin"
        )
        application = CapabilityPackAuthorityApplication(
            DATABASE_URL,
            application_build_id="capability-pack-authority-integration",
            commit_sha=RELEASE_SHA,
        )
        manifest = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        artifacts = default_chapter_artifact_resolver(ROOT).artifacts()
        artifact_catalog = {
            "schema_version": "novelos.capability_pack.artifact_catalog.v1",
            "artifacts": [
                {
                    "kind": artifact.kind.value,
                    "ref": artifact.ref,
                    "version": artifact.version,
                    "content": json.loads(artifact.content_json),
                    "content_hash": artifact.content_hash,
                    "source_identity": artifact.source_identity,
                }
                for artifact in artifacts
            ],
        }
        registration_payload = {
            "manifest": manifest,
            "artifact_catalog": artifact_catalog,
            "release_channel": "VALIDATION",
        }
        for checkpoint in ("after_manifest_asset", "after_version_registry"):
            self._assert_fault_rolls_back(
                checkpoint,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.manifest.register",
                payload=registration_payload,
            )
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "SELECT COUNT(*) FROM authority_capability_pack_version "
                    "WHERE pack_id='chapter_generation_pack'"
                )
                self.assertEqual(int(uow.cursor.fetchone()[0]), 0)
                uow.commit()
        register = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.manifest.register",
            payload=registration_payload,
            idempotency_key=f"{project_id}:capability-pack-register",
        )
        register_replay = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.manifest.register",
            payload=registration_payload,
            idempotency_key=f"{project_id}:capability-pack-register",
        )
        self.assertEqual(register_replay["operation_id"], register["operation_id"])
        pack_id = str(register["pack_id"])
        pack_version = str(register["pack_version"])
        conflicting_manifest = json.loads(json.dumps(manifest))
        conflicting_manifest["identity"]["description"] = (
            "same immutable version with different content"
        )
        with self.assertRaises(KernelError) as version_conflict:
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.manifest.register",
                payload={
                    **registration_payload,
                    "manifest": conflicting_manifest,
                },
            )
        self.assertEqual(
            version_conflict.exception.code,
            "CAPABILITY_PACK_VERSION_CONFLICT",
        )
        compile_payload = {
            "target_runtime_profile": "development",
            "novel_forge_version": "6.0.0",
            "release_sha": RELEASE_SHA,
            "release_channel": "VALIDATION",
        }
        validation = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.manifest.validate",
            pack_id=pack_id,
            pack_version=pack_version,
            payload=compile_payload,
        )
        self.assertEqual(validation["validation_status"], "VALID")
        compilation_id = identifier("trusted-compilation")
        for checkpoint in (
            "after_compilation_asset",
            "after_compilation_registry",
        ):
            self._assert_fault_rolls_back(
                checkpoint,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.compile",
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                payload=compile_payload,
            )
            with AuthorityUnitOfWork(DATABASE_URL) as uow:
                uow.cursor.execute(
                    "SELECT COUNT(*) FROM authority_capability_pack_compilation "
                    "WHERE compilation_id=%s",
                    [compilation_id],
                )
                self.assertEqual(int(uow.cursor.fetchone()[0]), 0)
                uow.commit()
        compilation = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.compile",
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_id=compilation_id,
            payload=compile_payload,
        )
        compilation_id = str(compilation["compilation_id"])
        self._register_agents(
            project_id=project_id,
            workspace_id=workspace_id,
            principal=agent_admin,
            compiled=dict(compilation["compiled"]),
        )
        deployment_payload = {
            "target_scope_type": "BOOK",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "environment": "development",
            "rollout_policy_ref": "rollout:book-stable:v1",
        }
        with self.assertRaises(KernelError) as unapproved:
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.deployment.create",
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                deployment_id=identifier("unapproved-deployment"),
                payload=deployment_payload,
            )
        self.assertEqual(
            unapproved.exception.code,
            "CAPABILITY_PACK_COMPILATION_NOT_APPROVED",
        )
        with self.assertRaises(KernelError) as tampered_approval:
            self._execute(
                application,
                approver,
                project_id,
                workspace_id,
                "capability_pack.approval.decide",
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                payload={
                    "compilation_hash": "sha256:" + "f" * 64,
                    "decision": "APPROVED",
                    "approval_policy_ref": "domain-decision-record:v1",
                    "scope": {"environment": "development"},
                    "reason": "tampered compilation",
                    "enforce_duties_separation": True,
                },
            )
        self.assertEqual(
            tampered_approval.exception.code,
            "CAPABILITY_PACK_APPROVAL_HASH_DRIFT",
        )
        with self.assertRaises(KernelError) as duties:
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.approval.decide",
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                payload={
                    "compilation_hash": compilation["compilation_hash"],
                    "decision": "APPROVED",
                    "approval_policy_ref": "domain-decision-record:v1",
                    "scope": {"environment": "development"},
                    "reason": "must be rejected",
                    "enforce_duties_separation": True,
                },
            )
        self.assertEqual(
            duties.exception.code, "CAPABILITY_PACK_DUTIES_SEPARATION_REQUIRED"
        )
        self._assert_fault_rolls_back(
            "after_approval_decision",
            approver,
            project_id,
            workspace_id,
            "capability_pack.approval.decide",
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_id=compilation_id,
            payload={
                "compilation_hash": compilation["compilation_hash"],
                "decision": "APPROVED",
                "approval_policy_ref": "domain-decision-record:v1",
                "scope": {"environment": "development"},
                "reason": "fault injection",
                "enforce_duties_separation": True,
            },
        )
        approval = self._execute(
            application,
            approver,
            project_id,
            workspace_id,
            "capability_pack.approval.decide",
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_id=compilation_id,
            payload={
                "compilation_hash": compilation["compilation_hash"],
                "decision": "APPROVED",
                "approval_policy_ref": "domain-decision-record:v1",
                "scope": {"environment": "development"},
                "reason": "integration qualification",
                "evidence_refs": ["test:postgres-lifecycle"],
                "enforce_duties_separation": True,
            },
        )
        self.assertEqual(approval["decision"], "APPROVED")

        baseline_id = identifier("baseline-deployment")
        candidate_id = identifier("candidate-deployment")
        self._assert_fault_rolls_back(
            "after_binding_set_materialized",
            compiler,
            project_id,
            workspace_id,
            "capability_pack.deployment.create",
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_id=compilation_id,
            deployment_id=baseline_id,
            payload=deployment_payload,
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                "SELECT COUNT(*) FROM authority_capability_pack_binding_set "
                "WHERE compilation_id=%s",
                [compilation_id],
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 0)
            uow.commit()
        for deployment_id in (baseline_id, candidate_id):
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.deployment.create",
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                deployment_id=deployment_id,
                payload=deployment_payload,
            )
        self._assert_fault_rolls_back(
            "before_activation_cas",
            compiler,
            project_id,
            workspace_id,
            "capability_pack.deployment.activate",
            pack_id=pack_id,
            pack_version=pack_version,
            deployment_id=baseline_id,
            payload={"environment": "development", "reason": "fault injection"},
        )
        activation = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.deployment.activate",
            pack_id=pack_id,
            pack_version=pack_version,
            deployment_id=baseline_id,
            payload={"environment": "development", "reason": "baseline"},
        )
        self.assertEqual(activation["activation_version"], 1)
        with self.assertRaises(KernelError) as wrong_pack_identity:
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.deployment.disable",
                pack_id="different_pack",
                pack_version=pack_version,
                deployment_id=baseline_id,
                payload={"environment": "development", "reason": "forbidden"},
            )
        self.assertEqual(
            wrong_pack_identity.exception.code,
            "CAPABILITY_PACK_TARGET_IDENTITY_CONFLICT",
        )
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT COUNT(*)
                FROM authority_chapter_node_agent_binding_activation
                WHERE workflow_definition_ref='chapter_authority_slice@2.2.0'
                  AND workflow_node_id='draft'
                """
            )
            self.assertEqual(int(uow.cursor.fetchone()[0]), 0)
            uow.commit()

        rollout_id = identifier("pack-rollout")
        rollout = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.rollout.start",
            pack_id=pack_id,
            pack_version=pack_version,
            rollout_id=rollout_id,
            payload={
                "environment": "development",
                "baseline_deployment_id": baseline_id,
                "candidate_deployment_id": candidate_id,
                "mode": "PERCENTAGE",
                "percentage": 100,
                "assignment_key_policy": "BOOK",
            },
        )
        self.assertEqual(rollout["status"], "PERCENTAGE")
        request = CapabilityPackResolutionRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            workflow_definition_ref="chapter_authority_slice@2.2.0",
            workflow_node_id="draft",
            environment="development",
            runtime_profile="development",
            release_channel="VALIDATION",
            release_sha=RELEASE_SHA,
            operation_definition_ref="chapter.draft.generate@2.2.0",
            pack_id=pack_id,
        )
        resolver = CapabilityPackRuntimeResolver(DATABASE_URL)
        first = resolver.resolve_active_deployment(request)
        second = resolver.resolve_active_deployment(request)
        self.assertEqual(first.assignment_ref, second.assignment_ref)
        self.assertEqual(first.deployment_id, second.deployment_id)
        self.assertEqual(first.binding_set_hash, second.binding_set_hash)
        paused = self._assert_fault_rolls_back(
            "before_outbox",
            compiler,
            project_id,
            workspace_id,
            "capability_pack.rollout.pause",
            pack_id=pack_id,
            pack_version=pack_version,
            rollout_id=rollout_id,
            payload={"environment": "development", "reason": "fault injection"},
            replay=True,
        )
        assert paused is not None
        self.assertEqual(paused["status"], "PAUSED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM audit_log
                   WHERE operation_id=%s
                     AND action='authority.capability_pack.rollout.pause.committed'),
                  (SELECT COUNT(*) FROM state_event
                   WHERE payload->>'operation_id'=%s
                     AND event_type=
                         'authority.capability_pack.rollout.pause.committed'),
                  (SELECT COUNT(*) FROM outbox_event
                   WHERE payload->>'operation_id'=%s
                     AND topic='authority.capability_pack.rollout.pause.committed')
                """,
                [paused["operation_id"]] * 3,
            )
            audit_count, event_count, outbox_count = uow.cursor.fetchone()
            uow.commit()
        self.assertEqual(
            (int(audit_count), int(event_count), int(outbox_count)),
            (1, 1, 1),
        )
        self.assertEqual(
            resolver.resolve_active_deployment(request).deployment_id,
            baseline_id,
        )
        resumed = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.rollout.resume",
            pack_id=pack_id,
            pack_version=pack_version,
            rollout_id=rollout_id,
            payload={"environment": "development", "reason": "operator resume"},
        )
        self.assertEqual(resumed["status"], "PERCENTAGE")
        resumed_snapshot = resolver.resolve_active_deployment(request)
        self.assertEqual(resumed_snapshot.assignment_ref, first.assignment_ref)
        self.assertEqual(resumed_snapshot.deployment_id, first.deployment_id)
        completed = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.rollout.complete",
            pack_id=pack_id,
            pack_version=pack_version,
            rollout_id=rollout_id,
            payload={"environment": "development", "reason": "qualified"},
        )
        self.assertEqual(completed["status"], "COMPLETED")
        completed_snapshot = resolver.resolve_active_deployment(request)
        self.assertEqual(completed_snapshot.deployment_id, candidate_id)
        self.assertEqual(
            completed_snapshot.assignment_ref,
            f"rollout:{rollout_id}:completed-candidate",
        )

        with tempfile.TemporaryDirectory(prefix="novel-forge-pack-runtime-") as root:
            settings = IndustrialSettings(
                root=Path(root),
                environment="development",
                storage_authority="postgresql",
                database_url=DATABASE_URL,
            )
            chapter = build_chapter_authority_application(
                settings,
                env={
                    "NOVEL_FORGE_ENVIRONMENT": "development",
                    "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                    "NOVEL_FORGE_COMMIT_SHA": RELEASE_SHA,
                    "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
                },
            )
            chapter_principal = self._principal(
                "pack-chapter-operator", project_id, "chapter.authority.execute"
            )
            admission = chapter.admit(
                SingleChapterRequest(
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id=chapter_principal.principal_id,
                    chapter=1,
                    title="Pack-bound Draft",
                    premise="A promise creates a visible irreversible cost.",
                    trace_id=identifier("pack-draft-trace"),
                    correlation_id=identifier("pack-draft-correlation"),
                    application_build_id="capability-pack-authority-integration",
                    commit_sha=RELEASE_SHA,
                    idempotency_key=f"{project_id}:pack-bound-chapter:1",
                    preparation_report={"decision": "READY", "fixture": True},
                    context_candidates=tuple(
                        chapter_scheduler_fixtures.ChapterAuthoritySchedulerPostgresTests._release_evidence(
                            project_id
                        )
                    ),
                ),
                principal=chapter_principal,
            )
            scheduler = chapter.scheduler(
                principal=Principal(
                    principal_id="pack-chapter-worker",
                    principal_type=PrincipalType.WORKER,
                    permissions=frozenset({"chapter.authority.execute"}),
                    project_scope=frozenset({project_id}),
                    authentication_source="integration-fixture",
                )
            )
            for expected_node in ("plan", "context", "draft"):
                tick = scheduler.tick(
                    project_id=project_id,
                    root_operation_id=admission.root_operation_id,
                )
                self.assertEqual(tick.node, expected_node)
                self.assertEqual(tick.operation_status, "SUCCEEDED")
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT capability_pack_deployment_id,
                       capability_pack_activation_version,
                       capability_pack_binding_set_id,
                       capability_pack_binding_set_hash,
                       chapter_node_binding_id, chapter_node_binding_version
                FROM authority_agent_runtime_binding
                WHERE project_id=%s AND workflow_node_id='draft'
                """,
                [project_id],
            )
            runtime_row = uow.cursor.fetchone()
            uow.commit()
        self.assertIsNotNone(runtime_row)
        self.assertEqual(str(runtime_row[0]), first.deployment_id)
        self.assertEqual(int(runtime_row[1]), first.activation_version)
        self.assertEqual(str(runtime_row[2]), first.binding_set_id)
        self.assertEqual(str(runtime_row[3]), first.binding_set_hash)
        self.assertIsNone(runtime_row[4])
        self.assertIsNone(runtime_row[5])

        def crash_after_activation(checkpoint: str) -> None:
            if checkpoint == "after_activation_pointer":
                raise RuntimeError("simulated activation crash")

        faulting_application = CapabilityPackAuthorityApplication(
            DATABASE_URL,
            application_build_id="capability-pack-authority-integration",
            commit_sha=RELEASE_SHA,
            fault_injector=crash_after_activation,
        )
        with self.assertRaisesRegex(RuntimeError, "simulated activation crash"):
            self._execute(
                faulting_application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.deployment.activate",
                pack_id=pack_id,
                pack_version=pack_version,
                deployment_id=candidate_id,
                expected_activation_version=1,
                payload={"environment": "development", "reason": "crash"},
            )
        self.assertEqual(
            resolver.resolve_active_deployment(request).activation_version, 1
        )

        promoted = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.deployment.activate",
            pack_id=pack_id,
            pack_version=pack_version,
            deployment_id=candidate_id,
            expected_activation_version=1,
            payload={"environment": "development", "reason": "promote candidate"},
        )
        self.assertEqual(promoted["activation_version"], 2)
        with self.assertRaises(KernelError) as stale_cas:
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.rollback",
                pack_id=pack_id,
                pack_version=pack_version,
                deployment_id=baseline_id,
                expected_activation_version=1,
                payload={"environment": "development", "reason": "stale CAS"},
            )
        self.assertEqual(
            stale_cas.exception.code, "CAPABILITY_PACK_ACTIVATION_CONFLICT"
        )
        rolled_back = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.rollback",
            pack_id=pack_id,
            pack_version=pack_version,
            deployment_id=baseline_id,
            expected_activation_version=2,
            payload={"environment": "development", "reason": "rollback"},
        )
        self.assertEqual(rolled_back["activation_version"], 3)
        self.assertEqual(rolled_back["active_deployment_id"], baseline_id)
        post_rollback = resolver.resolve_active_deployment(request)
        self.assertEqual(post_rollback.deployment_id, baseline_id)
        self.assertNotEqual(post_rollback.deployment_id, runtime_row[0])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT capability_pack_deployment_id,
                       capability_pack_binding_set_hash
                FROM authority_agent_runtime_binding
                WHERE project_id=%s AND workflow_node_id='draft'
                """,
                [project_id],
            )
            historical_runtime_row = uow.cursor.fetchone()
            uow.commit()
        self.assertEqual(historical_runtime_row[0], runtime_row[0])
        self.assertEqual(historical_runtime_row[1], runtime_row[3])
        query = CapabilityPackAuthorityQuery(
            DATABASE_URL, current_release_sha=RELEASE_SHA
        )
        self.assertEqual(
            query.drift_report(baseline_id, project_id=project_id)[
                "classification"
            ],
            "CLEAN",
        )
        self.assertEqual(
            query.usage_metrics(first.deployment_id, project_id=project_id)[
                "runtime_binding_count"
            ],
            1,
        )
        usage_by_pack = query.usage_metrics_by_dimensions(
            project_id=project_id,
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_hash=compilation["compilation_hash"],
            binding_set_hash=first.binding_set_hash,
        )
        self.assertEqual(usage_by_pack["deployment_count"], 2)
        self.assertEqual(
            usage_by_pack["aggregate"]["runtime_binding_count"], 1
        )
        self.assertEqual(
            usage_by_pack["aggregate"]["fixture_provider_call_count"], 1
        )
        self.assertFalse(usage_by_pack["aggregate"]["real_provider_proven"])
        self.assertEqual(
            query.deployment_detail(baseline_id, project_id=project_id)[
                "binding_set_hash"
            ],
            first.binding_set_hash,
        )

        other_project_id = identifier("other-pack-project")
        other_workspace_id = f"workspace:{other_project_id}"
        seed_authority_project_book(
            project_id=other_project_id,
            workspace_id=other_workspace_id,
            book_id=f"book:{other_project_id}",
        )
        other_principal = self._principal(
            "other-pack-admin", other_project_id, *PACK_PERMISSIONS
        )
        with self.assertRaises(KernelError) as cross_project_command:
            self._execute(
                application,
                other_principal,
                other_project_id,
                other_workspace_id,
                "capability_pack.deployment.disable",
                pack_id=pack_id,
                pack_version=pack_version,
                deployment_id=baseline_id,
                payload={"environment": "development", "reason": "forbidden"},
            )
        self.assertEqual(
            cross_project_command.exception.code,
            "CAPABILITY_PACK_PROJECT_SCOPE_MISMATCH",
        )
        with self.assertRaises(KernelError) as cross_project_query:
            query.deployment_detail(baseline_id, project_id=other_project_id)
        self.assertEqual(
            cross_project_query.exception.code,
            "CAPABILITY_PACK_PROJECT_SCOPE_MISMATCH",
        )
        self.assertEqual(
            query.list_versions(project_id=other_project_id, pack_id=pack_id), []
        )

        retired = self._execute(
            application,
            compiler,
            project_id,
            workspace_id,
            "capability_pack.retire",
            pack_id=pack_id,
            pack_version=pack_version,
            payload={
                "environment": "development",
                "reason": "end-of-life qualification",
                "migration_required": True,
                "migration_policy_ref": "migration:pack-retirement:v1",
            },
        )
        self.assertTrue(retired["retired"])
        with self.assertRaises(KernelError) as retired_deployment:
            self._execute(
                application,
                compiler,
                project_id,
                workspace_id,
                "capability_pack.deployment.create",
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                deployment_id=identifier("retired-deployment"),
                payload=deployment_payload,
            )
        self.assertEqual(
            retired_deployment.exception.code, "CAPABILITY_PACK_VERSION_RETIRED"
        )

        self._execute(
            application,
            approver,
            project_id,
            workspace_id,
            "capability_pack.revoke",
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_id=compilation_id,
            payload={
                "environment": "development",
                "reason": "integration security revocation",
            },
        )
        with self.assertRaises(KernelError) as raised:
            resolver.resolve_active_deployment(request)
        self.assertIn(
            raised.exception.code,
            {"CAPABILITY_PACK_DEPLOYMENT_BLOCKED", "CAPABILITY_PACK_APPROVAL_INVALID"},
        )
        self.assertEqual(
            query.drift_report(baseline_id, project_id=project_id)[
                "classification"
            ],
            "REVOKED",
        )

    @staticmethod
    def _principal(
        identity: str, project_id: str, *permissions: str
    ) -> Principal:
        return Principal(
            principal_id=identity,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(permissions),
            project_scope=frozenset({project_id}),
            authentication_source="integration-fixture",
        )

    @staticmethod
    def _execute(
        application: CapabilityPackAuthorityApplication,
        principal: Principal,
        project_id: str,
        workspace_id: str,
        action: str,
        *,
        pack_id: str = "chapter_generation_pack",
        pack_version: str = "",
        compilation_id: str = "",
        deployment_id: str = "",
        rollout_id: str = "",
        expected_activation_version: int = 0,
        payload: dict,
        idempotency_key: str = "",
    ) -> dict:
        return application.execute(
            CapabilityPackAuthorityCommand(
                definition_name=action,
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=principal.principal_id,
                pack_id=pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                deployment_id=deployment_id,
                rollout_id=rollout_id,
                expected_activation_version=expected_activation_version,
                idempotency_key=(
                    idempotency_key or f"{project_id}:{action}:{uuid4()}"
                ),
                trace_id=f"trace:{project_id}:{uuid4()}",
                correlation_id=f"correlation:{project_id}",
                payload=payload,
            ),
            principal=principal,
        )

    def _assert_fault_rolls_back(
        self,
        checkpoint_name: str,
        principal: Principal,
        project_id: str,
        workspace_id: str,
        action: str,
        replay: bool = False,
        **kwargs: object,
    ) -> dict | None:
        triggered = False

        def inject(checkpoint: str) -> None:
            nonlocal triggered
            if checkpoint == checkpoint_name and not triggered:
                triggered = True
                raise RuntimeError(f"simulated fault at {checkpoint_name}")

        faulting = CapabilityPackAuthorityApplication(
            DATABASE_URL,
            application_build_id="capability-pack-authority-integration",
            commit_sha=RELEASE_SHA,
            fault_injector=inject,
        )
        replay_key = f"{project_id}:{action}:fault-replay:{uuid4()}"
        call_kwargs = dict(kwargs)
        if replay:
            call_kwargs["idempotency_key"] = replay_key
        with self.assertRaisesRegex(
            RuntimeError, f"simulated fault at {checkpoint_name}"
        ):
            self._execute(
                faulting,
                principal,
                project_id,
                workspace_id,
                action,
                **call_kwargs,
            )
        if not replay:
            return None
        return self._execute(
            faulting,
            principal,
            project_id,
            workspace_id,
            action,
            **call_kwargs,
        )

    @staticmethod
    def _register_agents(
        *,
        project_id: str,
        workspace_id: str,
        principal: Principal,
        compiled: dict,
    ) -> None:
        artifacts = list(compiled["resolved_artifacts"])
        prompt = next(
            item for item in artifacts if item["kind"] == "PROMPT_SYSTEM_INSTRUCTION"
        )
        prompt_ref = f"{prompt['ref']}@{prompt['version']}"
        tool = dict(compiled["tool_permission_snapshot"])
        context = dict(compiled["context_source_snapshot"])
        runtime = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id="capability-pack-authority-integration",
            commit_sha=RELEASE_SHA,
        )
        registered: set[str] = set()
        for node in compiled["workflow_nodes"]:
            agent_ref = str(node.get("agent_definition_ref") or "")
            if not agent_ref or agent_ref in registered:
                continue
            registered.add(agent_ref)
            stage = str(node["node_id"])
            skill_name = (
                "prose-generation"
                if stage in {"draft", "revision"}
                else "canon-continuity-graph"
                if stage == "canon_extraction"
                else "quality-review"
            )
            skill = next(
                item
                for item in artifacts
                if item["kind"] == "SKILL" and item["ref"] == skill_name
            )
            skill_ref = f"{skill['ref']}@{skill['version']}"
            agent_id, _, raw_version = agent_ref.rpartition("@")
            capability_definition = default_capability_registry().resolve(
                node["capability_id"]
            )
            capability = AgentCapability(
                capability_id=str(node["capability_id"]),
                version=1,
                domain=capability_definition.domain.value,
                input_schema_ref=capability_definition.input_schema_ref,
                output_schema_ref=capability_definition.output_schema_ref,
                supported_message_types=(AgentMessageType.PROPOSAL,),
                supported_scope_types=("CHAPTER",),
                risk_class=capability_definition.risk_class.value.upper(),
                execution_requirements={"production_execution_gateway_required": True},
                qualification_status="QUALIFIED_FIXTURE",
            )
            definition = AgentDefinition(
                agent_id=agent_id,
                version=int(raw_version),
                agent_type="CHAPTER_STAGE",
                domain="chapter",
                role="CHAPTER_STAGE_AGENT",
                capability_refs=(f"{capability.capability_id}@1",),
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
            register = AgentRuntimeAdminCommand(
                definition_name="agent.definition.register",
                project_id=project_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                actor_id=principal.principal_id,
                idempotency_key=f"{project_id}:{agent_id}:register",
                trace_id=f"trace:{project_id}:{agent_id}:register",
                correlation_id=f"correlation:{project_id}",
                payload={
                    "capability": {
                        "capability_id": capability.capability_id,
                        "version": 1,
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
                        "execution_capability_id": node["capability_id"],
                        "execution_capability_hash": node[
                            "capability_contract_hash"
                        ],
                    },
                    "runtime_contract": {
                        "agent_id": agent_id,
                        "definition_version": int(raw_version),
                        "capability_pack_ref": (
                            f"{compiled['pack_id']}@{compiled['pack_version']}"
                        ),
                        "prompt_bundle_ref": prompt_ref,
                        "prompt_bundle_hash": prompt["content_hash"],
                        "skill_bundle_ref": skill_ref,
                        "skill_bundle_hash": skill["content_hash"],
                        "tool_policy_ref": tool["policy_id"],
                        "tool_policy_hash": _canonical_hash(tool),
                        "context_policy_ref": context["policy_id"],
                        "context_policy_hash": _canonical_hash(context),
                        "definition_source": "POSTGRES_AUTHORITY",
                    },
                },
            )
            activate = AgentRuntimeAdminCommand(
                definition_name="agent.definition.activate",
                project_id=project_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                actor_id=principal.principal_id,
                idempotency_key=f"{project_id}:{agent_id}:activate",
                trace_id=f"trace:{project_id}:{agent_id}:activate",
                correlation_id=f"correlation:{project_id}",
                payload={"definition_version": int(raw_version), "reason": "Pack test"},
            )
            runtime.execute_admin(register, principal=principal)
            runtime.execute_admin(activate, principal=principal)


def _canonical_hash(value: object) -> str:
    import hashlib

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    unittest.main()
