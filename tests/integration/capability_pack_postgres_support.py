from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_production_execution_composition,
)
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
from novel_forge.modules.agent_runtime.definitions import (
    agent_runtime_operation_definitions,
)
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
    CapabilityPackAuthorityCommand,
)
from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
)
from novel_forge.modules.capability_packs.artifacts import (
    default_chapter_artifact_resolver,
)
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
)
from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.production_execution.capability_registry import (
    capability_contract_version,
    default_capability_registry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from tests.integration.authority_postgres_support import (
    DATABASE_URL,
    ensure_migrated,
    identifier,
    insert_definition,
    insert_operation,
    seed_authority_project_book,
    transaction,
)


ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = ROOT / "config/capability_packs/chapter_generation_pack.json"
RELEASE_SHA = "e" * 40
APP_BUILD_ID = "capability-pack-integrity-hardening"
PACK_PERMISSIONS = (
    "capability_pack.authority.register",
    "capability_pack.authority.compile",
    "capability_pack.authority.approve",
    "capability_pack.authority.deploy",
    "capability_pack.authority.activate",
    "capability_pack.authority.rollback",
    "capability_pack.authority.retire",
)


@dataclass(frozen=True, slots=True)
class PackVersionProof:
    pack_id: str
    pack_version: str
    manifest_hash: str
    compilation_id: str
    compilation_hash: str
    catalog_snapshot_hash: str
    compiled: dict[str, Any]
    prompt_hash: str
    skill_hash: str
    agent_definition_version: int


@dataclass(frozen=True, slots=True)
class DeploymentProof:
    deployment_id: str
    binding_set_id: str
    binding_set_hash: str
    pack: PackVersionProof


class CapabilityPackPostgresHarness:
    def __init__(
        self,
        label: str,
        *,
        book_count: int = 1,
        application_build_id: str = APP_BUILD_ID,
        release_sha: str = RELEASE_SHA,
    ) -> None:
        ensure_migrated()
        self.application_build_id = application_build_id
        self.release_sha = release_sha
        suffix = uuid4().hex
        self.pack_id = f"{label.replace('_', '-').lower()}-{suffix}"
        self.project_id = f"project-{suffix}"
        self.workspace_id = f"workspace-{suffix}"
        self.book_ids = (
            f"book:{self.project_id}",
            *tuple(f"book-{index:03d}-{suffix}" for index in range(1, book_count)),
        )
        seed_authority_project_book(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_ids[0],
        )
        if len(self.book_ids) > 1:
            self._seed_additional_books(self.book_ids[1:])
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            for definition in chapter_operation_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.release_sha,
                model_effects_required=True,
            ):
                uow.repositories.definitions.register(definition)
            for definition in agent_runtime_operation_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.release_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()
        self.application = CapabilityPackAuthorityApplication(
            DATABASE_URL,
            application_build_id=self.application_build_id,
            commit_sha=self.release_sha,
        )
        self.compiler = self.principal("compiler", *PACK_PERMISSIONS)
        self.approver = self.principal("approver", *PACK_PERMISSIONS)
        self.agent_admin = self.principal("agent-admin", "agent.authority.admin")
        self._base_manifest = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        workflow = self._base_manifest["workflow_template"]
        self.workflow_definition_ref = (
            f"{workflow['workflow_id']}@{workflow['workflow_version']}"
        )
        self._base_catalog = {
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
                for artifact in default_chapter_artifact_resolver(ROOT).artifacts()
            ],
        }

    def principal(self, identity: str, *permissions: str) -> Principal:
        return Principal(
            principal_id=f"{identity}:{self.project_id}",
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(permissions),
            project_scope=frozenset({self.project_id}),
            authentication_source="integration-fixture",
        )

    def approval_scope(
        self,
        *,
        environments: Sequence[str] = ("development",),
        runtime_profiles: Sequence[str] = ("development",),
        release_channels: Sequence[str] = ("VALIDATION",),
        scope_types: Sequence[str] = ("SYSTEM", "PROJECT", "WORKSPACE", "BOOK"),
        project_ids: Sequence[str] | None = None,
        workspace_ids: Sequence[str] | None = None,
        book_ids: Sequence[str] | None = None,
        allow_canary: bool = True,
        allow_percentage_rollout: bool = True,
        allow_full_rollout: bool = True,
        maximum_rollout_percentage: float = 100,
    ) -> dict[str, Any]:
        return {
            "schema_version": "CapabilityPackApprovalScope.v1",
            "allowed_environments": list(environments),
            "allowed_runtime_profiles": list(runtime_profiles),
            "allowed_release_channels": list(release_channels),
            "allowed_scope_types": list(scope_types),
            "allowed_project_ids": list(
                project_ids if project_ids is not None else (self.project_id,)
            ),
            "allowed_workspace_ids": list(
                workspace_ids if workspace_ids is not None else (self.workspace_id,)
            ),
            "allowed_book_ids": list(
                book_ids if book_ids is not None else self.book_ids
            ),
            "allowed_workflow_definition_refs": [self.workflow_definition_ref],
            "allow_canary": allow_canary,
            "allow_percentage_rollout": allow_percentage_rollout,
            "allow_full_rollout": allow_full_rollout,
            "maximum_rollout_percentage": maximum_rollout_percentage,
        }

    def build_version_payload(
        self,
        version: str,
        *,
        generation: int,
        dependencies: Sequence[Mapping[str, str]] = (),
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        manifest = deepcopy(self._base_manifest)
        catalog = deepcopy(self._base_catalog)
        manifest["identity"]["pack_id"] = self.pack_id
        manifest["identity"]["version"] = version
        manifest["identity"]["description"] = (
            f"PostgreSQL integrity fixture generation {generation}."
        )
        agent_namespace = self.pack_id.rsplit("-", 1)[-1][:12]
        for node in manifest["workflow_template"]["nodes"]:
            agent_ref = str(node.get("agent_definition_ref") or "")
            if agent_ref:
                agent_id, _, _ = agent_ref.rpartition("@")
                node["agent_definition_ref"] = f"{agent_id}-{agent_namespace}@1"
        manifest["role"]["upstream_packs"] = [
            str(item["pack_id"]) for item in dependencies
        ]
        if generation > 1:
            self._make_distinct_generation(manifest, catalog, generation)
        return manifest, catalog

    def register_compile_approve(
        self,
        version: str,
        *,
        generation: int,
        approval_scope: Mapping[str, Any] | None = None,
        limitations: Sequence[Mapping[str, Any] | str] = (),
        dependencies: Sequence[Mapping[str, str]] = (),
        owner_scope_type: str = "PROJECT",
        proof_skill_ref: str = "prose-generation",
        release_sha: str = RELEASE_SHA,
        target_runtime_profile: str = "development",
    ) -> PackVersionProof:
        manifest, catalog = self.build_version_payload(
            version, generation=generation, dependencies=dependencies
        )
        registration = self.execute(
            "capability_pack.manifest.register",
            principal=self.compiler,
            pack_version=version,
            payload={
                "manifest": manifest,
                "artifact_catalog": catalog,
                "release_channel": "VALIDATION",
                "owner_scope_type": owner_scope_type,
                "owner_project_id": (
                    self.project_id if owner_scope_type == "PROJECT" else ""
                ),
                "dependencies": [dict(item) for item in dependencies],
            },
        )
        compilation_id = identifier(f"compilation-{generation}")
        compilation = self.execute(
            "capability_pack.compile",
            principal=self.compiler,
            pack_version=version,
            compilation_id=compilation_id,
            payload={
                "target_runtime_profile": target_runtime_profile,
                "novel_forge_version": "6.0.0",
                "release_sha": release_sha,
                "release_channel": "VALIDATION",
            },
        )
        compiled = dict(compilation["compiled"])
        self.register_agents(compiled)
        self.execute(
            "capability_pack.approval.decide",
            principal=self.approver,
            pack_version=version,
            compilation_id=compilation_id,
            payload={
                "compilation_hash": compilation["compilation_hash"],
                "decision": "APPROVED",
                "approval_policy_ref": "capability-pack-approval-scope:v1",
                "scope": dict(approval_scope or self.approval_scope()),
                "limitations": list(limitations),
                "reason": f"PostgreSQL fixture approval for {version}",
                "evidence_refs": ["test:postgres-capability-pack-hardening"],
                "enforce_duties_separation": True,
            },
        )
        prompt = next(
            item
            for item in compiled["resolved_artifacts"]
            if item["kind"] == "PROMPT_TEMPLATE"
        )
        skill = next(
            item
            for item in compiled["resolved_artifacts"]
            if item["kind"] == "SKILL" and item["ref"] == proof_skill_ref
        )
        agent_version = max(
            (
                int(str(node["agent_definition_ref"]).rpartition("@")[2])
                for node in compiled["workflow_nodes"]
                if node.get("agent_definition_ref")
            ),
            default=0,
        )
        return PackVersionProof(
            pack_id=self.pack_id,
            pack_version=version,
            manifest_hash=str(registration["manifest_hash"]),
            compilation_id=compilation_id,
            compilation_hash=str(compilation["compilation_hash"]),
            catalog_snapshot_hash=str(compiled["catalog_snapshot_hash"]),
            compiled=compiled,
            prompt_hash=str(prompt["content_hash"]),
            skill_hash=str(skill["content_hash"]),
            agent_definition_version=agent_version,
        )

    def deploy(
        self,
        pack: PackVersionProof,
        *,
        principal: Principal | None = None,
        scope_type: str = "BOOK",
        project_id: str | None = None,
        workspace_id: str | None = None,
        book_id: str | None = None,
        environment: str = "development",
        runtime_profile: str = "development",
    ) -> DeploymentProof:
        deployment_id = identifier(f"deployment-{pack.pack_version.replace('.', '-')}")
        payload = {
            "target_scope_type": scope_type,
            "project_id": project_id if project_id is not None else self.project_id,
            "workspace_id": (
                workspace_id if workspace_id is not None else self.workspace_id
            ),
            "book_id": book_id if book_id is not None else self.book_ids[0],
            "environment": environment,
            "runtime_profile": runtime_profile,
            "rollout_policy_ref": "rollout:stable-sha256:v1",
        }
        if scope_type == "SYSTEM":
            payload.update(project_id="", workspace_id="", book_id="")
        elif scope_type == "PROJECT":
            payload.update(workspace_id="", book_id="")
        elif scope_type == "WORKSPACE":
            payload.update(book_id="")
        deployment = self.execute(
            "capability_pack.deployment.create",
            principal=principal or self.compiler,
            pack_version=pack.pack_version,
            compilation_id=pack.compilation_id,
            deployment_id=deployment_id,
            payload=payload,
        )
        return DeploymentProof(
            deployment_id=deployment_id,
            binding_set_id=str(deployment["binding_set_id"]),
            binding_set_hash=str(deployment["binding_set_hash"]),
            pack=pack,
        )

    def activate(
        self,
        deployment: DeploymentProof,
        *,
        expected_activation_version: int = 0,
        principal: Principal | None = None,
        environment: str = "development",
    ) -> dict[str, Any]:
        return self.execute(
            "capability_pack.deployment.activate",
            principal=principal or self.compiler,
            pack_version=deployment.pack.pack_version,
            deployment_id=deployment.deployment_id,
            expected_activation_version=expected_activation_version,
            payload={"environment": environment, "reason": "fixture activation"},
        )

    def resolution_request(
        self, *, book_id: str | None = None, workflow_node_id: str = "draft"
    ) -> CapabilityPackResolutionRequest:
        operation_refs = {
            str(node["node_id"]): str(node["operation_definition_ref"])
            for node in self._base_manifest["workflow_template"]["nodes"]
        }
        return CapabilityPackResolutionRequest(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=book_id if book_id is not None else self.book_ids[0],
            workflow_definition_ref=self.workflow_definition_ref,
            workflow_node_id=workflow_node_id,
            environment="development",
            runtime_profile="development",
            release_channel="VALIDATION",
            release_sha=RELEASE_SHA,
            operation_definition_ref=operation_refs[workflow_node_id],
            pack_id=self.pack_id,
        )

    def execute(
        self,
        action: str,
        *,
        principal: Principal,
        pack_id: str | None = None,
        pack_version: str = "",
        compilation_id: str = "",
        deployment_id: str = "",
        rollout_id: str = "",
        expected_activation_version: int = 0,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        token = uuid4().hex
        return self.application.execute(
            CapabilityPackAuthorityCommand(
                definition_name=action,
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=principal.principal_id,
                pack_id=pack_id or self.pack_id,
                pack_version=pack_version,
                compilation_id=compilation_id,
                deployment_id=deployment_id,
                rollout_id=rollout_id,
                expected_activation_version=expected_activation_version,
                idempotency_key=f"{self.project_id}:{action}:{token}",
                trace_id=f"trace:{self.project_id}:{token}",
                correlation_id=f"correlation:{self.project_id}",
                payload=dict(payload),
            ),
            principal=principal,
        )

    def register_agents(self, compiled: Mapping[str, Any]) -> None:
        artifacts = list(compiled["resolved_artifacts"])
        prompt = next(
            item for item in artifacts if item["kind"] == "PROMPT_SYSTEM_INSTRUCTION"
        )
        prompt_ref = f"{prompt['ref']}@{prompt['version']}"
        tool = dict(compiled["tool_permission_snapshot"])
        context = dict(compiled["context_source_snapshot"])
        runtime = AgentRuntimeAuthorityApplication(
            DATABASE_URL,
            application_build_id=self.application_build_id,
            commit_sha=self.release_sha,
        )
        registered: set[str] = set()
        for node in compiled["workflow_nodes"]:
            agent_ref = str(node.get("agent_definition_ref") or "")
            if not agent_ref or agent_ref in registered:
                continue
            registered.add(agent_ref)
            stage = str(node["node_id"])
            skill_name = (
                "agent-loop-governance"
                if stage == "agent_session"
                else "prose-generation"
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
            definition_version = int(raw_version)
            capability_definition = default_capability_registry().resolve(
                str(node["capability_id"])
            )
            capability_version = capability_contract_version(
                capability_definition.capability_id
            )
            capability = AgentCapability(
                capability_id=str(node["capability_id"]),
                version=capability_version,
                domain=capability_definition.domain.value,
                input_schema_ref=capability_definition.input_schema_ref,
                output_schema_ref=capability_definition.output_schema_ref,
                supported_message_types=(AgentMessageType.PROPOSAL,),
                supported_scope_types=(
                    ("BOOK",) if stage == "agent_session" else ("CHAPTER",)
                ),
                risk_class=capability_definition.risk_class.value.upper(),
                execution_requirements={"production_execution_gateway_required": True},
                qualification_status="QUALIFIED_FIXTURE",
            )
            is_agent_session = stage == "agent_session"
            definition = AgentDefinition(
                agent_id=agent_id,
                version=definition_version,
                agent_type=(
                    "AUTONOMOUS_SESSION" if is_agent_session else "CHAPTER_STAGE"
                ),
                domain=("agent_runtime" if is_agent_session else "chapter"),
                role=("STUDIO_DIRECTOR" if is_agent_session else "CHAPTER_STAGE_AGENT"),
                capability_refs=(f"{capability.capability_id}@{capability_version}",),
                input_contract_ref=capability.input_schema_ref,
                output_contract_ref=capability.output_schema_ref,
                authority_scope_ref=(
                    "scope:book@1" if is_agent_session else "scope:chapter@1"
                ),
                default_scope_policy_ref=(
                    "scope:accepted-book-boundary@1"
                    if is_agent_session
                    else "scope:chapter-frozen@1"
                ),
                allowed_tools=(
                    (
                        "narrative.query_accepted",
                        "story_planning.generate_candidate",
                        "plan_change.submit",
                    )
                    if is_agent_session
                    else ("request_production_execution",)
                ),
                allowed_context_types=("context_bundle",),
                execution_policy_ref="execution:pep@1",
                approval_policy_ref=(
                    "approval:agent-submit-only@1"
                    if is_agent_session
                    else "approval:chapter-authority@1"
                ),
                quality_policy_ref=(
                    "quality:agent-transcript-gate@1"
                    if is_agent_session
                    else "quality:chapter-domain-handler@1"
                ),
                status="ACTIVE",
            )
            command_base = {
                "project_id": self.project_id,
                "workspace_id": self.workspace_id,
                "agent_id": agent_id,
                "actor_id": self.agent_admin.principal_id,
                "correlation_id": f"correlation:{self.project_id}",
            }
            register = AgentRuntimeAdminCommand(
                definition_name="agent.definition.register",
                idempotency_key=(
                    f"{self.project_id}:{agent_id}:{definition_version}:register"
                ),
                trace_id=(
                    f"trace:{self.project_id}:{agent_id}:{definition_version}:register"
                ),
                payload={
                    "capability": {
                        "capability_id": capability.capability_id,
                        "version": capability.version,
                        "domain": capability.domain,
                        "input_schema_ref": capability.input_schema_ref,
                        "output_schema_ref": capability.output_schema_ref,
                        "supported_message_types": ["PROPOSAL"],
                        "supported_scope_types": list(capability.supported_scope_types),
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
                        "default_scope_policy_ref": (
                            definition.default_scope_policy_ref
                        ),
                        "allowed_tools": list(definition.allowed_tools),
                        "allowed_context_types": list(definition.allowed_context_types),
                        "execution_policy_ref": definition.execution_policy_ref,
                        "approval_policy_ref": definition.approval_policy_ref,
                        "quality_policy_ref": definition.quality_policy_ref,
                        "status": definition.status,
                    },
                    "execution_mapping": {
                        "capability_id": capability.capability_id,
                        "capability_version": capability_version,
                        "execution_capability_id": node["capability_id"],
                        "execution_capability_hash": node["capability_contract_hash"],
                    },
                    "runtime_contract": {
                        "agent_id": agent_id,
                        "definition_version": definition_version,
                        "capability_pack_ref": (
                            f"{compiled['pack_id']}@{compiled['pack_version']}"
                        ),
                        "prompt_bundle_ref": prompt_ref,
                        "prompt_bundle_hash": prompt["content_hash"],
                        "skill_bundle_ref": skill_ref,
                        "skill_bundle_hash": skill["content_hash"],
                        "tool_policy_ref": tool["policy_id"],
                        "tool_policy_hash": canonical_hash(tool),
                        "context_policy_ref": context["policy_id"],
                        "context_policy_hash": canonical_hash(context),
                        "definition_source": "POSTGRES_AUTHORITY",
                    },
                },
                **command_base,
            )
            activate = AgentRuntimeAdminCommand(
                definition_name="agent.definition.activate",
                idempotency_key=(
                    f"{self.project_id}:{agent_id}:{definition_version}:activate"
                ),
                trace_id=(
                    f"trace:{self.project_id}:{agent_id}:{definition_version}:activate"
                ),
                payload={
                    "definition_version": definition_version,
                    "reason": "Capability Pack PostgreSQL fixture",
                },
                expected_activation_version=max(0, definition_version - 1),
                **command_base,
            )
            runtime.execute_admin(register, principal=self.agent_admin)
            runtime.execute_admin(activate, principal=self.agent_admin)

    def run_draft_attempt(self, *, chapter_number: int = 1) -> dict[str, Any]:
        chapter_plan = self._chapter_plan_candidate(chapter_number)
        with tempfile.TemporaryDirectory(prefix="novel-forge-pack-snapshot-") as root:
            settings = IndustrialSettings(
                root=Path(root),
                environment="development",
                storage_authority="postgresql",
                database_url=DATABASE_URL,
            )
            env = {
                "NOVEL_FORGE_ENVIRONMENT": "development",
                "NOVEL_FORGE_MODEL_PROVIDER": "scripted_provider_v2",
                "NOVEL_FORGE_COMMIT_SHA": self.release_sha,
                "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": self.pack_id,
                "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": root,
            }
            execution = build_production_execution_composition(settings, env=env)
            chapter = build_chapter_authority_application(
                settings,
                execution=execution,
                env=env,
            )
            operator = self.principal("chapter-operator", "chapter.authority.execute")
            admission = chapter.admit(
                SingleChapterRequest(
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    actor_id=operator.principal_id,
                    chapter=chapter_number,
                    title=f"Pack Snapshot Fixture {chapter_number}",
                    premise="A frozen choice must survive runtime recovery.",
                    trace_id=identifier("pack-snapshot-trace"),
                    correlation_id=identifier("pack-snapshot-correlation"),
                    application_build_id=self.application_build_id,
                    commit_sha=self.release_sha,
                    idempotency_key=(
                        f"{self.project_id}:capability-pack-snapshot:"
                        f"chapter-{chapter_number}"
                    ),
                    preparation_report={"decision": "READY", "fixture": True},
                    context_candidates=(chapter_plan,),
                ),
                principal=operator,
            )
            worker = Principal(
                principal_id=f"chapter-worker:{self.project_id}",
                principal_type=PrincipalType.WORKER,
                permissions=frozenset({"chapter.authority.execute"}),
                project_scope=frozenset({self.project_id}),
                authentication_source="integration-fixture",
            )
            scheduler = chapter.scheduler(principal=worker)
            ticks = []
            for expected_node in (
                "plan",
                "execution_intent",
                "memo",
                "retrieval",
                "context",
                "draft",
            ):
                tick = scheduler.tick(
                    project_id=self.project_id,
                    root_operation_id=admission.root_operation_id,
                )
                if tick.node != expected_node or tick.operation_status != "SUCCEEDED":
                    raise AssertionError(
                        f"Chapter fixture failed at {expected_node}: {tick}"
                    )
                ticks.append(tick)
        with AuthorityUnitOfWork(DATABASE_URL) as uow:
            uow.cursor.execute(
                """
                SELECT snapshot.snapshot_id, snapshot.operation_id,
                       snapshot.attempt_id, snapshot.execution_fencing_token,
                       snapshot.snapshot_creation_fencing_token,
                       snapshot.snapshot_hash, snapshot.snapshot_payload,
                       snapshot.trace_id, snapshot.span_id,
                       snapshot.deployment_id, snapshot.binding_set_id,
                       snapshot.binding_set_hash,
                       effect.external_effect_id,
                       effect.request_payload,
                       dispatch.receipt_id,
                       dispatch.evidence
                FROM authority_attempt_capability_pack_snapshot AS snapshot
                JOIN authority_operation AS operation
                  ON operation.operation_id=snapshot.operation_id
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=snapshot.operation_id
                JOIN authority_external_effect_dispatch AS dispatch
                  ON dispatch.external_effect_id=effect.external_effect_id
                WHERE operation.root_operation_id=%s
                  AND snapshot.workflow_node_id='draft'
                """,
                [admission.root_operation_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise AssertionError("draft Attempt did not freeze a Pack Snapshot")
            fields = (
                "snapshot_id",
                "operation_id",
                "attempt_id",
                "execution_fencing_token",
                "snapshot_creation_fencing_token",
                "snapshot_hash",
                "snapshot_payload",
                "trace_id",
                "span_id",
                "deployment_id",
                "binding_set_id",
                "binding_set_hash",
                "external_effect_id",
                "effect_request_payload",
                "receipt_id",
                "dispatch_evidence",
            )
            result = dict(zip(fields, row, strict=True))
            result["root_operation_id"] = admission.root_operation_id
            result["ticks"] = ticks
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_operation AS operation
                JOIN authority_operation_output_asset AS output
                  ON output.operation_id=operation.operation_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=output.asset_version_id
                WHERE operation.root_operation_id=%s
                  AND operation.definition_name='chapter.draft.generate'
                  AND output.output_key='chapter.draft'
                """,
                [admission.root_operation_id],
            )
            draft_row = uow.cursor.fetchone()
            result["draft_content"] = dict(draft_row[0]) if draft_row else {}
            uow.commit()
            return result

    def _make_distinct_generation(
        self,
        manifest: dict[str, Any],
        catalog: dict[str, Any],
        generation: int,
    ) -> None:
        by_identity = {
            (str(item["kind"]), str(item["ref"]), str(item["version"])): item
            for item in catalog["artifacts"]
        }
        prompt = manifest["prompt_binding"]
        for kind, ref_key, version_key, hash_key in (
            (
                "PROMPT_SYSTEM_INSTRUCTION",
                "system_instruction_ref",
                "system_instruction_version",
                "system_instruction_hash",
            ),
            ("PROMPT_TEMPLATE", "template_ref", "template_version", "template_hash"),
        ):
            original = by_identity[(kind, prompt[ref_key], prompt[version_key])]
            new_version = f"v{generation}"
            original["version"] = new_version
            original["content"]["text"] += f"\nFixture generation {generation}."
            original["content_hash"] = canonical_hash(original["content"])
            prompt[version_key] = new_version
            prompt[hash_key] = original["content_hash"]
        for binding in manifest["skill_binding"]["skills"]:
            original = by_identity[("SKILL", binding["skill_ref"], binding["version"])]
            new_version = f"{binding['skill_ref']}-v{generation}"
            original["version"] = new_version
            original["content"]["text"] += f"\nFixture generation {generation}."
            original["content_hash"] = canonical_hash(original["content"])
            binding["version"] = new_version
            binding["content_hash"] = original["content_hash"]
        for node in manifest["workflow_template"]["nodes"]:
            agent_ref = str(node.get("agent_definition_ref") or "")
            if agent_ref:
                agent_id, _, _ = agent_ref.rpartition("@")
                node["agent_definition_ref"] = f"{agent_id}@{generation}"

    def _seed_additional_books(self, book_ids: Sequence[str]) -> None:
        definition_name = identifier("multi-book-fixture-definition")
        operation_id = identifier("multi-book-fixture-operation")
        with transaction() as connection, connection.cursor() as cursor:
            insert_definition(cursor, definition_name)
            insert_operation(
                cursor,
                operation_id=operation_id,
                definition_name=definition_name,
                project_id=self.project_id,
                status="SUCCEEDED",
            )
            for book_id in book_ids:
                asset_id = f"scope-fixture:book:{book_id}"
                cursor.execute(
                    "INSERT INTO authority_asset(asset_id, project_id, asset_type) "
                    "VALUES (%s, %s, 'book')",
                    [asset_id, self.project_id],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_asset_version(
                        asset_version_id, asset_id, version_number, lifecycle,
                        eligibility, governance, content, content_hash, schema_version
                    ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR',
                              %s, %s, 'book-authority.v1')
                    """,
                    [
                        f"{asset_id}:v1",
                        asset_id,
                        Jsonb({"project_id": self.project_id, "book_id": book_id}),
                        "sha256:" + hashlib.sha256(book_id.encode()).hexdigest(),
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO authority_book(
                        book_id, project_id, workspace_id, principal_id,
                        service_identity, book_scope, production_profile,
                        runtime_policy, release_identity, status,
                        current_book_asset_version_id, created_by_operation_id,
                        last_operation_id
                    ) VALUES (%s, %s, %s, 'integration-operator',
                              'integration-service', %s, '{}'::jsonb, '{}'::jsonb,
                              'integration-release', 'DESIGN_PENDING', %s, %s, %s)
                    """,
                    [
                        book_id,
                        self.project_id,
                        self.workspace_id,
                        Jsonb({"book_id": book_id}),
                        f"{asset_id}:v1",
                        operation_id,
                        operation_id,
                    ],
                )

    def _chapter_plan_candidate(self, chapter_number: int) -> dict[str, Any]:
        content = {
            "project_id": self.project_id,
            "chapter": chapter_number,
            "title": f"Pack Snapshot Fixture {chapter_number}",
            "premise": "A frozen choice must survive runtime recovery.",
            "chapter_objective": "Make one irreversible public choice.",
            "scene_sequence": [
                {"scene_id": "scene-1", "goal": "preserve the frozen choice"}
            ],
            "chapter_hook": "Recovery proves the choice was not re-resolved.",
        }
        content_hash = canonical_hash(content)
        asset_id = identifier("pack-snapshot-chapter-plan-asset")
        asset_version_id = identifier("pack-snapshot-chapter-plan")
        with transaction() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO authority_asset(asset_id, project_id, asset_type)
                VALUES (%s, %s, 'chapter_plan')
                """,
                [asset_id, self.project_id],
            )
            cursor.execute(
                """
                INSERT INTO authority_asset_version(
                    asset_version_id, asset_id, version_number, lifecycle,
                    eligibility, governance, content, content_hash, schema_version
                ) VALUES (%s, %s, 1, 'ACTIVE', 'ELIGIBLE', 'CLEAR',
                          %s, %s, 'chapter-plan-authority.v1')
                """,
                [asset_version_id, asset_id, Jsonb(content), content_hash],
            )
        return {
            "asset_version_id": asset_version_id,
            "asset_type": "chapter_plan",
            "project_id": self.project_id,
            "content_hash": content_hash,
            "estimated_tokens": 50,
            "allowed_use": "generation",
            "source_use_mode": "generation",
            **content,
            "narrative_function": "chapter_plan",
        }


__all__ = [
    "APP_BUILD_ID",
    "DATABASE_URL",
    "DeploymentProof",
    "CapabilityPackPostgresHarness",
    "PackVersionProof",
    "RELEASE_SHA",
]
