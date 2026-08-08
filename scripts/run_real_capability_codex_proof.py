#!/usr/bin/env python3
"""Run one exact-SHA real Codex Chapter through the PostgreSQL Authority runtime."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from novel_forge.api.authority_dependencies import (
    build_chapter_authority_application,
    build_content_authority_application,
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
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_design_authority import (
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
)
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
    CapabilityPackAuthorityCommand,
)
from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.capability_packs.artifacts import (
    default_chapter_artifact_resolver,
)
from novel_forge.modules.chapter_authority import SingleChapterRequest
from novel_forge.modules.chapter_authority.contracts import ChapterNode
from novel_forge.modules.content_authority import ContentOperationRequest
from novel_forge.modules.canon_graph.approval_authority import (
    CanonApprovalContext,
    decide_canon_approval,
    list_canon_approvals,
)
from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.modules.production_preparation import (
    PostgresProductionAssetResolver,
    ProductionPreparationRequest,
    ProductionPreparationService,
)
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import run_migrations
from novel_forge.storage.object_store import MinioObjectStore


ROOT = Path(__file__).resolve().parents[1]
PACK_PATH = ROOT / "config/capability_packs/chapter_generation_pack.json"
PACK_ID = "chapter_generation_pack"
PACK_VERSION = "1.0.0"
WORKFLOW_REF = "chapter_authority_slice@2.2.0"
MODEL_STAGES = (
    "draft",
    "review",
    "revision",
    "rereview",
    "canon_extraction",
    "quality_structural",
    "quality_commercial",
    "quality_source_originality",
    "quality_longform",
    "quality_platform",
)
PACK_PERMISSIONS = frozenset(
    {
        "capability_pack.authority.register",
        "capability_pack.authority.compile",
        "capability_pack.authority.approve",
        "capability_pack.authority.deploy",
        "capability_pack.authority.activate",
    }
)


class SimulatedWorkerInterruption(BaseException):
    """Escape normal worker failure handling to model abrupt process loss."""


class OneShotProviderSuccessCrash:
    def __init__(self) -> None:
        self.triggered = False

    def __call__(self, checkpoint: str) -> None:
        if checkpoint == "after_provider_success" and not self.triggered:
            self.triggered = True
            raise SimulatedWorkerInterruption(
                "proof injection: worker stopped after durable provider success"
            )


def _git(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return value


def _principal(
    identity: str,
    project_id: str,
    *permissions: str,
    worker: bool = False,
) -> Principal:
    return Principal(
        principal_id=identity,
        principal_type=(
            PrincipalType.WORKER if worker else PrincipalType.LOCAL_OPERATOR
        ),
        permissions=frozenset(permissions),
        project_scope=frozenset({project_id}),
        authentication_source="real-codex-provider-proof",
    )


def _pack_command(
    app: CapabilityPackAuthorityApplication,
    principal: Principal,
    *,
    action: str,
    project_id: str,
    workspace_id: str,
    payload: Mapping[str, Any],
    pack_version: str = "",
    compilation_id: str = "",
    deployment_id: str = "",
    expected_activation_version: int = 0,
) -> dict[str, Any]:
    token = uuid4().hex
    return app.execute(
        CapabilityPackAuthorityCommand(
            definition_name=action,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            pack_id=PACK_ID,
            pack_version=pack_version,
            compilation_id=compilation_id,
            deployment_id=deployment_id,
            expected_activation_version=expected_activation_version,
            idempotency_key=f"{project_id}:{action}:{token}",
            trace_id=f"trace:{project_id}:{token}",
            correlation_id=f"correlation:{project_id}",
            payload=dict(payload),
        ),
        principal=principal,
    )


def _register_agents(
    database_url: str,
    *,
    compiled: Mapping[str, Any],
    project_id: str,
    workspace_id: str,
    build_id: str,
    commit_sha: str,
    principal: Principal,
) -> None:
    artifacts = list(compiled["resolved_artifacts"])
    prompt = next(
        item for item in artifacts if item["kind"] == "PROMPT_SYSTEM_INSTRUCTION"
    )
    prompt_ref = f"{prompt['ref']}@{prompt['version']}"
    tool = dict(compiled["tool_permission_snapshot"])
    context = dict(compiled["context_source_snapshot"])
    runtime = AgentRuntimeAuthorityApplication(
        database_url,
        application_build_id=build_id,
        commit_sha=commit_sha,
        runtime_environment="provider-validation",
        release_channel="VALIDATION",
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
        agent_id, separator, raw_version = agent_ref.rpartition("@")
        if not separator or not raw_version.isdigit():
            raise RuntimeError(f"invalid compiled Agent ref: {agent_ref}")
        definition_version = int(raw_version)
        capability_definition = default_capability_registry().resolve(
            str(node["capability_id"])
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
            qualification_status="QUALIFIED_REAL_RUNTIME",
        )
        definition = AgentDefinition(
            agent_id=agent_id,
            version=definition_version,
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
        base = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "actor_id": principal.principal_id,
            "correlation_id": f"correlation:{project_id}",
        }
        runtime.execute_admin(
            AgentRuntimeAdminCommand(
                definition_name="agent.definition.register",
                idempotency_key=f"{project_id}:{agent_ref}:register",
                trace_id=f"trace:{project_id}:{agent_ref}:register",
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
                        "capability_version": 1,
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
                **base,
            ),
            principal=principal,
        )
        runtime.execute_admin(
            AgentRuntimeAdminCommand(
                definition_name="agent.definition.activate",
                idempotency_key=f"{project_id}:{agent_ref}:activate",
                trace_id=f"trace:{project_id}:{agent_ref}:activate",
                expected_activation_version=max(0, definition_version - 1),
                payload={
                    "definition_version": definition_version,
                    "reason": "real Codex Capability Runtime proof",
                },
                **base,
            ),
            principal=principal,
        )


def _install_pack(
    database_url: str,
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    compiler: Principal,
    approver: Principal,
    agent_admin: Principal,
) -> dict[str, Any]:
    manifest = json.loads(PACK_PATH.read_text(encoding="utf-8"))
    resolver = default_chapter_artifact_resolver(ROOT)
    catalog = {
        "schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": [item.to_dict() for item in resolver.artifacts()],
    }
    app = CapabilityPackAuthorityApplication(
        database_url, application_build_id=build_id, commit_sha=commit_sha
    )
    registered = _pack_command(
        app,
        compiler,
        action="capability_pack.manifest.register",
        project_id=project_id,
        workspace_id=workspace_id,
        payload={
            "manifest": manifest,
            "artifact_catalog": catalog,
            "release_channel": "VALIDATION",
            "owner_scope_type": "PROJECT",
            "owner_project_id": project_id,
            "dependencies": [],
        },
    )
    compilation_id = f"compilation:real-codex:{commit_sha[:12]}"
    compilation = _pack_command(
        app,
        compiler,
        action="capability_pack.compile",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_version=PACK_VERSION,
        compilation_id=compilation_id,
        payload={
            "target_runtime_profile": "provider-validation",
            "novel_forge_version": "6.0.0",
            "release_sha": commit_sha,
            "release_channel": "VALIDATION",
        },
    )
    compiled = dict(compilation["compiled"])
    _register_agents(
        database_url,
        compiled=compiled,
        project_id=project_id,
        workspace_id=workspace_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=agent_admin,
    )
    approval = _pack_command(
        app,
        approver,
        action="capability_pack.approval.decide",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_version=PACK_VERSION,
        compilation_id=compilation_id,
        payload={
            "compilation_hash": compilation["compilation_hash"],
            "decision": "APPROVED",
            "approval_policy_ref": "capability-pack-approval-scope:v1",
            "scope": {
                "schema_version": "CapabilityPackApprovalScope.v1",
                "allowed_environments": ["provider-validation"],
                "allowed_runtime_profiles": ["provider-validation"],
                "allowed_release_channels": ["VALIDATION"],
                "allowed_scope_types": ["BOOK"],
                "allowed_project_ids": [project_id],
                "allowed_workspace_ids": [workspace_id],
                "allowed_book_ids": [book_id],
                "allowed_workflow_definition_refs": [WORKFLOW_REF],
                "allow_canary": False,
                "allow_percentage_rollout": False,
                "allow_full_rollout": True,
                "maximum_rollout_percentage": 100,
            },
            "limitations": [],
            "reason": "exact-SHA real Codex provider validation",
            "evidence_refs": [f"runtime-proof:{commit_sha}"],
            "enforce_duties_separation": True,
        },
    )
    deployment_id = f"deployment:real-codex:{commit_sha[:12]}"
    deployment = _pack_command(
        app,
        compiler,
        action="capability_pack.deployment.create",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_version=PACK_VERSION,
        compilation_id=compilation_id,
        deployment_id=deployment_id,
        payload={
            "target_scope_type": "BOOK",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "environment": "provider-validation",
            "rollout_policy_ref": "rollout:stable-sha256:v1",
        },
    )
    activation = _pack_command(
        app,
        compiler,
        action="capability_pack.deployment.activate",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_version=PACK_VERSION,
        deployment_id=deployment_id,
        expected_activation_version=0,
        payload={
            "environment": "provider-validation",
            "reason": "activate exact-SHA real Codex proof",
        },
    )
    return {
        "registration": registered,
        "compilation": compilation,
        "approval": approval,
        "deployment": deployment,
        "activation": activation,
    }


def _author_inputs(
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str],
    project_id: str,
    workspace_id: str,
    principal: Principal,
) -> dict[str, str]:
    app = build_content_authority_application(settings, env=env)
    common = {
        "raw_source": False,
        "source_expression_included": False,
        "allowed_use": "generation",
        "source_use_mode": "generation",
        "estimated_tokens": 180,
    }
    specifications = {
        "chapter.plan.author": {
            **common,
            "type": "chapter_plan",
            "chapter": 1,
            "title": "The Ledger Under Rain",
            "premise": (
                "A junior flood-control clerk discovers that a celebrated rescue "
                "report erased the district that paid the real cost."
            ),
            "chapter_objective": (
                "Force Lin Qiao to choose between a safe promotion and preserving "
                "the only auditable copy of the erased casualty ledger."
            ),
            "scene_sequence": [
                {
                    "scene_id": "scene-1",
                    "goal": "verify the mismatch before the archive closes",
                    "conflict": "her supervisor orders the old files pulped",
                    "turn": "a water stain reveals a second ink layer",
                },
                {
                    "scene_id": "scene-2",
                    "goal": "copy the hidden entries without exposing the witness",
                    "conflict": "the promotion interview begins in the next room",
                    "turn": "the erased witness signs the margin in fresh ink",
                },
            ],
            "chapter_hook": (
                "The signature belongs to a woman officially listed among the dead."
            ),
            "conflict_chain": [
                {
                    "pressure": "the archive purge destroys the only auditable copy",
                    "choice": "attend the promotion interview or preserve the ledger",
                    "cost": "preserving truth exposes Lin Qiao as the disobedient clerk",
                }
            ],
            "reader_promise_actions": [
                {
                    "promise": "institutional lies leave physical evidence",
                    "action": "the water stain reveals an erased accounting layer",
                }
            ],
            "protagonist_charm_mechanism": (
                "Lin Qiao protects a vulnerable witness even when accuracy costs her safety."
            ),
            "information_reveals": [
                {
                    "fact": "the official rescue report reassigned casualties",
                    "consequence": "the living witness is legally recorded as dead",
                }
            ],
            "next_chapter_bridge": (
                "Lin Qiao must find why the living witness signed a ledger scheduled for destruction."
            ),
            "safe_summary": (
                "An original civic-fantasy chapter about evidence, complicity, and "
                "the immediate cost of preserving truth."
            ),
            "structured_facts": [
                {"kind": "protagonist", "value": "Lin Qiao, junior archive clerk"},
                {"kind": "setting", "value": "municipal flood archive during rain"},
                {
                    "kind": "required_cost",
                    "value": "promotion or evidence must be lost",
                },
            ],
        },
        "chapter.style_policy.author": {
            **common,
            "type": "style_policy",
            "profile_id": "style:codex-proof",
            "constraints": [
                "close third-person through Lin Qiao",
                "concrete physical action before explanation",
                "no imitation of any named author or work",
                "end on a causally earned identity hook",
            ],
            "safe_summary": "Close, concrete, original commercial prose policy.",
            "structured_facts": [
                {"kind": "viewpoint", "value": "close third-person"},
                {"kind": "originality", "value": "no named-work imitation"},
            ],
        },
        "chapter.quality_rubric.author": {
            **common,
            "type": "quality_rubric",
            "profile_id": "quality:codex-proof",
            "dimensions": [
                "causal continuity",
                "character cost",
                "scene escalation",
                "commercial hook",
                "source originality",
            ],
            "safe_summary": "Rubric for causality, cost, escalation, hook, and originality.",
            "structured_facts": [
                {"kind": "minimum_dimension_score", "value": "0.72"},
            ],
        },
        "chapter.platform_profile.author": {
            **common,
            "type": "platform_profile",
            "profile_id": "platform:codex-proof",
            "constraints": [
                "open with an observable anomaly",
                "maintain short scene-level pressure cycles",
                "close with a new question grounded in evidence",
            ],
            "safe_summary": "Web-serial readability constraints with an evidence hook.",
            "structured_facts": [
                {
                    "key": "platform_rules",
                    "value": {
                        "chapter_length": {"minimum": 1_500, "maximum": 5_000},
                        "format": {"paragraph_max": 500},
                        "sensitive_content": ["no prohibited sensitive content"],
                        "ai_content": {"release_mode": "internal_review_only"},
                        "opening": ["open with an observable anomaly"],
                        "rhythm": ["maintain short scene-level pressure cycles"],
                        "publish_metadata": {
                            "required": ["chapter", "title", "summary"],
                        },
                    },
                },
                {"kind": "reader_promise", "value": "truth has escalating social cost"},
            ],
        },
        "chapter.operator_checklist.author": {
            **common,
            "type": "operator_checklist",
            "chapter": 1,
            "completed": True,
            "contract_version": "internal-release-checklist-v1",
            "safe_summary": (
                "Operator verified source isolation, internal-only release scope, "
                "and required production inputs for this provider-validation run."
            ),
            "structured_facts": [
                {"key": "source_isolation_reviewed", "value": True},
                {"key": "release_scope", "value": "INTERNAL_REVIEW_ONLY"},
            ],
        },
    }
    versions: dict[str, str] = {}
    for name, content in specifications.items():
        result = app.execute(
            ContentOperationRequest(
                definition_name=name,
                project_id=project_id,
                workspace_id=workspace_id,
                actor_id=principal.principal_id,
                trace_id=f"trace:{project_id}:inputs",
                correlation_id=f"correlation:{project_id}",
                idempotency_key=f"{project_id}:{name}",
                payload={"content": content},
            ),
            principal=principal,
        )
        versions[name] = result.asset_version_id
    return versions


def _runtime_env(
    *,
    commit_sha: str,
    codex_executable: str,
    runtime_root: Path,
    worker_id: str,
    model: str,
    reasoning_effort: str,
) -> dict[str, str]:
    workspace = runtime_root / "isolated-codex-workspace"
    executions = runtime_root / "codex-executions"
    objects = runtime_root / "object-store-locators"
    workspace.mkdir(parents=True, exist_ok=False)
    executions.mkdir(parents=True, exist_ok=True)
    objects.mkdir(parents=True, exist_ok=True)
    return {
        "NOVEL_FORGE_ENVIRONMENT": "provider-validation",
        "NOVEL_FORGE_APPLICATION_BUILD_ID": "real-capability-codex-proof",
        "NOVEL_FORGE_COMMIT_SHA": commit_sha,
        "NOVEL_FORGE_RELEASE_CHANNEL": "VALIDATION",
        "NOVEL_FORGE_MODEL_PROVIDER": "codex-cli",
        "NOVEL_FORGE_DRAFT_MODEL": model,
        "NOVEL_FORGE_REVIEW_MODEL": model,
        "NOVEL_FORGE_REVISION_MODEL": model,
        "NOVEL_FORGE_REREVIEW_MODEL": model,
        "NOVEL_FORGE_CANON_EXTRACTION_MODEL": model,
        "NOVEL_FORGE_QUALITY_MODEL": model,
        "NOVEL_FORGE_READER_OUTCOME_MODEL": model,
        "NOVEL_FORGE_REASONING_EFFORT": reasoning_effort,
        "NOVEL_FORGE_RUNTIME_HOST_ID": f"host:local-codex-proof:{commit_sha[:12]}",
        "NOVEL_FORGE_PROVIDER_AUTH_PROFILE": "auth:chatgpt-codex-cli",
        "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": PACK_ID,
        "NOVEL_FORGE_AUTHORITY_WORKER_ID": worker_id,
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_BACKEND": "minio",
        "NOVEL_FORGE_AUTHORITY_OBJECT_STORE_ROOT": str(objects),
        "NOVEL_FORGE_CODEX_EXECUTABLE": codex_executable,
        "NOVEL_FORGE_CODEX_WORKSPACE": str(workspace),
        "NOVEL_FORGE_CODEX_EXECUTION_ROOT": str(executions),
        "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": "2.00",
        "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": "30.00",
        "NOVEL_FORGE_OPERATION_PROVIDER_CAP": "5.00",
        "NOVEL_FORGE_PROVIDER_DAILY_CAP": "30.00",
        "NOVEL_FORGE_DAILY_PROVIDER_CAP": "30.00",
        "NOVEL_FORGE_CHAPTER_PROVIDER_CAP": "20.00",
        "NOVEL_FORGE_CODEX_PRICING_REF": (
            "https://developers.openai.com/api/docs/models/gpt-5.4@2026-08-08"
        ),
        "NOVEL_FORGE_CODEX_PRICING_CURRENCY": "USD",
        "NOVEL_FORGE_CODEX_INPUT_PER_MILLION": "2.50",
        "NOVEL_FORGE_CODEX_CACHED_INPUT_PER_MILLION": "0.25",
        "NOVEL_FORGE_CODEX_OUTPUT_PER_MILLION": "15.00",
    }


def _seed_authorities(
    database_url: str,
    settings: IndustrialSettings,
    *,
    env: Mapping[str, str],
    project_id: str,
    workspace_id: str,
    book_id: str,
    build_id: str,
    commit_sha: str,
    principal: Principal,
) -> tuple[dict[str, str], Any]:
    ProjectAuthorityApplication(
        database_url, application_build_id=build_id, commit_sha=commit_sha
    ).execute(
        ProjectAuthorityCommand(
            definition_name="project_lifecycle.create",
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            idempotency_key=f"project:create:{project_id}",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            payload={"title": "Real Capability Codex Proof", "stage": "PRODUCTION"},
        ),
        principal=principal,
    )
    BookDesignAuthorityApplication(
        database_url, application_build_id=build_id, commit_sha=commit_sha
    ).execute(
        BookDesignAuthorityCommand(
            definition_name="book.create",
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            actor_id=principal.principal_id,
            service_identity="real-capability-codex-proof",
            idempotency_key=f"book:create:{book_id}",
            trace_id=f"trace:{project_id}",
            correlation_id=f"correlation:{project_id}",
            payload={
                "schema_version": "book-authority.v1",
                "title": "The Ledger Under Rain",
                "production_profile": {
                    "environment": "provider-validation",
                    "provider": "codex-cli",
                },
                "runtime_policy": {
                    "legacy_write": False,
                    "silent_fallback": False,
                },
                "release_identity": f"{build_id}@{commit_sha}",
            },
        ),
        principal=principal,
    )
    inputs = _author_inputs(
        settings,
        env=env,
        project_id=project_id,
        workspace_id=workspace_id,
        principal=principal,
    )
    prepared = ProductionPreparationService(
        PostgresProductionAssetResolver(database_url)
    ).prepare(
        ProductionPreparationRequest(
            project_id=project_id,
            workspace_id=workspace_id,
            chapter=1,
            idempotency_key=f"{project_id}:chapter:1",
            explicit_asset_version_overrides={
                "chapter_plan": inputs["chapter.plan.author"],
                "style_policy": inputs["chapter.style_policy.author"],
                "quality_rubric": inputs["chapter.quality_rubric.author"],
                "platform_profile": inputs["chapter.platform_profile.author"],
                "operator_checklist": inputs[
                    "chapter.operator_checklist.author"
                ],
            },
            requested_quality_profile="quality:codex-proof",
            requested_platform_profile="platform:codex-proof",
            context_token_budget=16_000,
            stage="draft",
        )
    )
    if prepared.report.decision != "READY" or prepared.command is None:
        raise RuntimeError(
            "Production Preparation did not reach READY: "
            + json.dumps(_jsonable(asdict(prepared.report)), ensure_ascii=False)
        )
    return inputs, prepared.command


def _query_rows(
    database_url: str, sql: str, parameters: Sequence[Any]
) -> list[dict[str, Any]]:
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(sql, list(parameters))
        names = [str(item.name) for item in uow.cursor.description or ()]
        return [dict(zip(names, row, strict=True)) for row in uow.cursor.fetchall()]


def _collect_evidence(
    database_url: str,
    *,
    project_id: str,
    root_operation_id: str,
) -> dict[str, Any]:
    operations = _query_rows(
        database_url,
        """
        SELECT operation_id, definition_name, definition_version, status,
               root_operation_id, trace_id, span_id, created_at, updated_at
        FROM authority_operation
        WHERE project_id=%s AND (
            operation_id=%s OR root_operation_id=%s
        )
        ORDER BY created_at, operation_id
        """,
        (project_id, root_operation_id, root_operation_id),
    )
    attempts = _query_rows(
        database_url,
        """
        SELECT attempt.*
        FROM authority_attempt AS attempt
        JOIN authority_operation AS operation
          ON operation.operation_id=attempt.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY attempt.created_at, attempt.attempt_id
        """,
        (project_id, root_operation_id),
    )
    snapshots = _query_rows(
        database_url,
        """
        SELECT snapshot.*
        FROM authority_attempt_capability_pack_snapshot AS snapshot
        JOIN authority_operation AS operation
          ON operation.operation_id=snapshot.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY snapshot.created_at, snapshot.snapshot_id
        """,
        (project_id, root_operation_id),
    )
    agent_bindings = _query_rows(
        database_url,
        """
        SELECT binding.*
        FROM authority_agent_runtime_binding AS binding
        JOIN authority_operation AS operation
          ON operation.operation_id=binding.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY binding.created_at, binding.binding_id
        """,
        (project_id, root_operation_id),
    )
    leases = _query_rows(
        database_url,
        """
        SELECT lease.*
        FROM authority_lease_acquisition AS lease
        JOIN authority_attempt AS attempt ON attempt.attempt_id=lease.attempt_id
        JOIN authority_operation AS operation
          ON operation.operation_id=attempt.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY lease.acquired_at, lease.fencing_token
        """,
        (project_id, root_operation_id),
    )
    effects = _query_rows(
        database_url,
        """
        SELECT effect.*
        FROM authority_external_effect AS effect
        JOIN authority_operation AS operation
          ON operation.operation_id=effect.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY effect.created_at, effect.external_effect_id
        """,
        (project_id, root_operation_id),
    )
    dispatches = _query_rows(
        database_url,
        """
        SELECT dispatch.*
        FROM authority_external_effect_dispatch AS dispatch
        JOIN authority_external_effect AS effect
          ON effect.external_effect_id=dispatch.external_effect_id
        JOIN authority_operation AS operation
          ON operation.operation_id=effect.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY dispatch.created_at, dispatch.dispatch_id
        """,
        (project_id, root_operation_id),
    )
    receipts = _query_rows(
        database_url,
        """
        SELECT receipt.*
        FROM authority_external_receipt AS receipt
        JOIN authority_external_effect_dispatch AS dispatch
          ON dispatch.dispatch_id=receipt.dispatch_id
        JOIN authority_external_effect AS effect
          ON effect.external_effect_id=dispatch.external_effect_id
        JOIN authority_operation AS operation
          ON operation.operation_id=effect.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY receipt.received_at, receipt.receipt_id
        """,
        (project_id, root_operation_id),
    )
    assets = _query_rows(
        database_url,
        """
        SELECT DISTINCT version.asset_version_id, asset.asset_id, asset.asset_type,
               version.content_hash, version.content, version.schema_version,
               version.lifecycle, version.eligibility, version.governance,
               version.created_at, binding.operation_id, binding.output_key,
               binding.role
        FROM authority_asset AS asset
        JOIN authority_asset_version AS version ON version.asset_id=asset.asset_id
        JOIN authority_operation_output_asset AS binding
          ON binding.asset_version_id=version.asset_version_id
        JOIN authority_operation AS operation
          ON operation.operation_id=binding.operation_id
        WHERE asset.project_id=%s AND operation.root_operation_id=%s
        ORDER BY version.created_at, version.asset_version_id, binding.output_key
        """,
        (project_id, root_operation_id),
    )
    sagas = _query_rows(
        database_url,
        """
        SELECT * FROM authority_saga
        WHERE project_id=%s AND root_operation_id=%s
        """,
        (project_id, root_operation_id),
    )
    recovery_authorizations = _query_rows(
        database_url,
        """
        SELECT authorization.*
        FROM authority_execution_recovery_authorization AS authorization
        JOIN authority_operation AS operation
          ON operation.operation_id=authorization.operation_id
        WHERE operation.project_id=%s AND operation.root_operation_id=%s
        ORDER BY authorization.created_at
        """,
        (project_id, root_operation_id),
    )
    return _jsonable(
        {
            "operations": operations,
            "attempts": attempts,
            "capability_snapshots": snapshots,
            "agent_bindings": agent_bindings,
            "leases": leases,
            "external_effects": effects,
            "external_effect_dispatches": dispatches,
            "external_receipts": receipts,
            "authority_assets": assets,
            "sagas": sagas,
            "recovery_authorizations": recovery_authorizations,
        }
    )


def _asset_contents(
    evidence: Mapping[str, Any], asset_type: str
) -> list[dict[str, Any]]:
    values = []
    for asset in evidence.get("authority_assets") or ():
        if asset.get("asset_type") != asset_type:
            continue
        content = asset.get("content")
        if isinstance(content, Mapping):
            values.append(dict(content))
    return values


def _evaluate_proof(
    evidence: Mapping[str, Any], *, commit_sha: str, model: str
) -> dict[str, bool]:
    model_logs = _asset_contents(evidence, "model_call_log")
    cost_ledgers = _asset_contents(evidence, "cost_ledger")
    materializations = _asset_contents(evidence, "capability_materialization_manifest")
    stages = {str(item.get("stage") or "") for item in model_logs}

    def provider(item: Mapping[str, Any]) -> Mapping[str, Any]:
        value = item.get("provider_evidence")
        return value if isinstance(value, Mapping) else {}

    real_provider = len(model_logs) == len(MODEL_STAGES) and stages == set(MODEL_STAGES)
    real_provider = real_provider and all(
        provider(item).get("real_model_call") is True
        and provider(item).get("provider_id") == "codex-cli"
        and provider(item).get("model_id") == model
        for item in model_logs
    )
    structured = real_provider and all(
        isinstance(
            (
                (provider(item).get("production_execution") or {}).get(
                    "validation_manifest"
                )
                if isinstance(provider(item).get("production_execution"), Mapping)
                else None
            ),
            Mapping,
        )
        and (
            (provider(item)["production_execution"]["execution_result"] or {}).get(
                "outcome"
            )
            == "SUCCEEDED"
        )
        for item in model_logs
    )
    usage_tracking = len(cost_ledgers) == len(MODEL_STAGES) and all(
        int(item.get("total_tokens") or 0) > 0
        and (item.get("usage") or {}).get("measurement") == "MEASURED"
        and item.get("estimated") is True
        and item.get("provider_billed") is False
        and bool(item.get("pricing_ref"))
        and bool(item.get("pricing_snapshot_hash"))
        and bool(item.get("calculation_basis"))
        for item in cost_ledgers
    )
    capability_trace = len(model_logs) == len(MODEL_STAGES) and all(
        bool(
            (provider(item).get("capability_runtime") or {}).get("materialization_hash")
        )
        and bool(
            (provider(item).get("capability_runtime") or {}).get(
                "fully_rendered_prompt_hash"
            )
        )
        and bool((provider(item).get("capability_runtime") or {}).get("skill"))
        and bool(
            (provider(item).get("capability_runtime") or {}).get(
                "context_asset_version_ids"
            )
        )
        and bool(
            (provider(item).get("capability_runtime") or {}).get(
                "knowledge_content_hashes"
            )
        )
        and (provider(item).get("tools") or {}).get("allowed")
        == ["model.provider.invoke"]
        and "storage.object.put"
        in (provider(item).get("tools") or {}).get("denied", [])
        and (provider(item).get("tools") or {}).get("invoked")
        == ["model.provider.invoke"]
        for item in model_logs
    )
    snapshots = list(evidence.get("capability_snapshots") or ())
    effects = list(evidence.get("external_effects") or ())
    snapshot_by_attempt = {str(item.get("attempt_id")): item for item in snapshots}
    snapshot_precedes_effect = True
    for effect in effects:
        payload = effect.get("request_payload")
        metadata = (
            payload.get("_production_execution")
            if isinstance(payload, Mapping)
            else None
        )
        runtime = (
            metadata.get("capability_runtime")
            if isinstance(metadata, Mapping)
            else None
        )
        if not isinstance(runtime, Mapping):
            continue
        attempt_id = (
            str(metadata.get("attempt_id") or "")
            if isinstance(metadata, Mapping)
            else ""
        )
        snapshot = snapshot_by_attempt.get(attempt_id)
        if (
            snapshot is None
            or runtime.get("snapshot_id") != snapshot.get("snapshot_id")
            or runtime.get("snapshot_hash") != snapshot.get("snapshot_hash")
            or str(snapshot.get("created_at")) > str(effect.get("created_at"))
        ):
            snapshot_precedes_effect = False
            break
    capability_runtime = (
        len(snapshots) == len(MODEL_STAGES)
        and len(materializations) == len(MODEL_STAGES)
        and all(int(item.get("resolution_count") or 0) == 1 for item in snapshots)
        and snapshot_precedes_effect
        and capability_trace
    )
    operations = list(evidence.get("operations") or ())
    chapter_definitions = {node.definition_name for node in ChapterNode}
    chapter_operations = [
        item
        for item in operations
        if item.get("definition_name") in chapter_definitions
    ]
    saga_succeeded = any(
        item.get("status") == "SUCCEEDED" for item in evidence.get("sagas") or ()
    )
    single_chapter = (
        saga_succeeded
        and len(chapter_operations) == len(ChapterNode)
        and all(item.get("status") == "SUCCEEDED" for item in chapter_operations)
        and bool(_asset_contents(evidence, "canon_patch"))
        and bool(_asset_contents(evidence, "quality_score_report"))
    )
    draft_log = next((item for item in model_logs if item.get("stage") == "draft"), {})
    draft_provider = provider(draft_log)
    draft_execution = draft_provider.get("production_execution")
    draft_request = (
        draft_execution.get("execution_request")
        if isinstance(draft_execution, Mapping)
        else {}
    )
    draft_effect_id = str(
        draft_request.get("external_effect_id")
        if isinstance(draft_request, Mapping)
        else ""
    )
    draft_operation_id = str(draft_log.get("operation_id") or "")
    draft_attempts = [
        item
        for item in evidence.get("attempts") or ()
        if item.get("operation_id") == draft_operation_id
    ]
    draft_attempt_ids = {str(item.get("attempt_id") or "") for item in draft_attempts}
    draft_leases = [
        item
        for item in evidence.get("leases") or ()
        if str(item.get("attempt_id") or "") in draft_attempt_ids
    ]
    draft_snapshots = [
        item
        for item in snapshots
        if str(item.get("attempt_id") or "") in draft_attempt_ids
    ]
    draft_dispatches = [
        item
        for item in evidence.get("external_effect_dispatches") or ()
        if item.get("external_effect_id") == draft_effect_id
    ]
    draft_outputs = [
        item
        for item in evidence.get("authority_assets") or ()
        if item.get("operation_id") == draft_operation_id
        and item.get("asset_type") == "draft_chapter"
    ]
    recovery = (
        bool(draft_effect_id)
        and len(draft_attempts) == 1
        and len(draft_snapshots) == 1
        and int(draft_snapshots[0].get("resolution_count") or 0) == 1
        and len(draft_leases) >= 2
        and len(draft_dispatches) == 1
        and len(draft_outputs) == 1
        and bool(evidence.get("recovery_authorizations"))
    )
    result = {
        "capability_runtime_proven": capability_runtime,
        "real_provider_proven": real_provider,
        "single_chapter_proven": single_chapter,
        "structured_output_proven": structured,
        "usage_tracking_proven": usage_tracking,
        "capability_trace_proven": capability_trace,
        "recovery_proven": recovery,
        "reader_outcome_proven": False,
        "production_verified": False,
        "exact_release_sha_proven": all(
            item.get("release_sha") == commit_sha for item in snapshots
        )
        if snapshots
        else False,
    }
    result["REAL_PROVIDER_CAPABILITY_RUNTIME_PROVEN"] = all(
        result[key]
        for key in (
            "capability_runtime_proven",
            "real_provider_proven",
            "single_chapter_proven",
            "structured_output_proven",
            "usage_tracking_proven",
            "capability_trace_proven",
            "recovery_proven",
        )
    )
    return result


def _await_draft_lease_expiry(
    database_url: str, *, project_id: str, root_operation_id: str
) -> dict[str, Any]:
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        rows = _query_rows(
            database_url,
            """
            SELECT attempt.attempt_id, operation.operation_id,
                   lease.fencing_token, lease.owner, lease.expires_at,
                   lease.released_at, lease.expires_at <= NOW() AS expired
            FROM authority_operation AS operation
            JOIN authority_attempt AS attempt
              ON attempt.operation_id=operation.operation_id
            JOIN authority_lease_acquisition AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE operation.project_id=%s
              AND operation.root_operation_id=%s
              AND operation.definition_name='chapter.draft.generate'
            ORDER BY lease.fencing_token DESC
            LIMIT 1
            """,
            (project_id, root_operation_id),
        )
        if rows and rows[0].get("expired") is True:
            return rows[0]
        time.sleep(1)
    raise TimeoutError("simulated worker lease did not expire within 50 seconds")


def _run(args: argparse.Namespace) -> dict[str, Any]:
    commit_sha = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    dirty = _git("status", "--porcelain", "--untracked-files=normal")
    if branch != "feat/v7-content-intelligence-and-longform-proof":
        raise RuntimeError(f"unexpected proof branch: {branch}")
    if dirty and not args.allow_dirty:
        raise RuntimeError("exact-SHA proof requires a clean Git worktree")
    executable = str(Path(args.codex_executable).expanduser().resolve())
    if not Path(executable).is_file():
        raise RuntimeError(f"Codex executable does not exist: {executable}")
    login = subprocess.run(
        (executable, "login", "status"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=False)
    env = _runtime_env(
        commit_sha=commit_sha,
        codex_executable=executable,
        runtime_root=runtime_root,
        worker_id="chapter-worker:real-codex:interrupted",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
    )
    settings = IndustrialSettings(
        root=ROOT,
        environment="production",
        storage_authority="postgresql",
        database_url=args.database_url,
        minio_endpoint=args.minio_endpoint,
        minio_access_key=args.minio_access_key,
        minio_secret_key=args.minio_secret_key,
        minio_secure=args.minio_secure,
    )
    migration = run_migrations(args.database_url)
    MinioObjectStore(settings).ensure_buckets()
    suffix = uuid4().hex[:12]
    project_id = f"real-codex-proof:{commit_sha[:8]}:{suffix}"
    workspace_id = f"workspace:{project_id}"
    book_id = f"book:{project_id}"
    build_id = env["NOVEL_FORGE_APPLICATION_BUILD_ID"]
    operator = _principal(
        f"operator:{project_id}",
        project_id,
        "project.authority.execute",
        "book_design.authority.execute",
        "content.authority.execute",
        "content.operation:chapter.plan.author",
        "content.operation:chapter.style_policy.author",
        "content.operation:chapter.quality_rubric.author",
        "content.operation:chapter.platform_profile.author",
        "content.operation:chapter.operator_checklist.author",
        "chapter.authority.execute",
    )
    compiler = _principal(
        f"compiler:{project_id}", project_id, *sorted(PACK_PERMISSIONS)
    )
    approver = _principal(
        f"approver:{project_id}", project_id, *sorted(PACK_PERMISSIONS)
    )
    agent_admin = _principal(
        f"agent-admin:{project_id}", project_id, "agent.authority.admin"
    )
    worker_interrupted = _principal(
        env["NOVEL_FORGE_AUTHORITY_WORKER_ID"],
        project_id,
        "chapter.authority.execute",
        worker=True,
    )
    print(
        json.dumps(
            {
                "phase": "authority_setup",
                "commit_sha": commit_sha,
                "project_id": project_id,
            }
        ),
        flush=True,
    )
    inputs, command = _seed_authorities(
        args.database_url,
        settings,
        env=env,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        principal=operator,
    )
    crash = OneShotProviderSuccessCrash()
    chapter = build_chapter_authority_application(
        settings, env=env, runtime_fault_injector=crash
    )
    admission = chapter.admit(
        SingleChapterRequest(
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            actor_id=operator.principal_id,
            chapter=command.chapter,
            title=command.title,
            premise=command.premise,
            trace_id=f"trace:{project_id}:chapter:1",
            correlation_id=f"correlation:{project_id}",
            application_build_id=build_id,
            commit_sha=commit_sha,
            chapter_plan_asset_version_id=command.chapter_plan_asset_version_id,
            chapter_plan_content_hash=command.chapter_plan_content_hash,
            context_candidates=command.context_candidates,
            context_version_refs=command.context_version_refs,
            context_token_budget=command.context_token_budget,
            preparation_report=command.preparation_report,
            idempotency_key=command.idempotency_key,
        ),
        principal=operator,
    )
    pack = _install_pack(
        args.database_url,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        build_id=build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
    )
    ticks: list[dict[str, Any]] = []
    scheduler = chapter.scheduler(principal=worker_interrupted)
    interrupted = False
    try:
        for _ in range(6):
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            ticks.append(_jsonable(asdict(tick)))
            print(json.dumps(ticks[-1], ensure_ascii=False), flush=True)
    except SimulatedWorkerInterruption as exc:
        interrupted = True
        ticks.append({"injected_interruption": str(exc)})
        print(json.dumps(ticks[-1]), flush=True)
    finally:
        chapter.close()
    if not interrupted or not crash.triggered:
        raise RuntimeError("recovery proof did not reach the injected crash point")
    expired_lease = _await_draft_lease_expiry(
        args.database_url,
        project_id=project_id,
        root_operation_id=admission.root_operation_id,
    )
    print(
        json.dumps(
            {"phase": "lease_expired", **_jsonable(expired_lease)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    recovered_env = dict(env)
    recovered_env["NOVEL_FORGE_AUTHORITY_WORKER_ID"] = (
        "chapter-worker:real-codex:recovered"
    )
    worker_recovered = _principal(
        recovered_env["NOVEL_FORGE_AUTHORITY_WORKER_ID"],
        project_id,
        "chapter.authority.execute",
        worker=True,
    )
    recovered = build_chapter_authority_application(settings, env=recovered_env)
    scheduler = recovered.scheduler(principal=worker_recovered)
    terminal = None
    try:
        for _ in range(80):
            tick = scheduler.tick(
                project_id=project_id,
                root_operation_id=admission.root_operation_id,
            )
            terminal = tick
            row = _jsonable(asdict(tick))
            ticks.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if tick.saga_status == "WAITING_GATE":
                pending = [
                    item
                    for item in list_canon_approvals(
                        args.database_url, project_id=project_id
                    )
                    if item["root_operation_id"] == admission.root_operation_id
                    and item["status"]
                    not in {
                        "APPROVED",
                        "REJECTED",
                        "EDITED_AND_APPROVED",
                        "INVALIDATED",
                        "EXPIRED",
                    }
                ]
                for item in pending:
                    decision = decide_canon_approval(
                        args.database_url,
                        CanonApprovalContext(
                            project_id=project_id,
                            principal_id=operator.principal_id,
                            trace_id=f"trace:{project_id}:canon-approval",
                            correlation_id=f"correlation:{project_id}",
                        ),
                        approval_request_id=str(item["approval_request_id"]),
                        expected_version=int(item["version"]),
                        decision="APPROVE",
                        reason="real provider proof reviewed exact extracted evidence",
                        evidence={
                            "evidence_level": "OPERATOR_REVIEWED_REAL_PROVIDER",
                            "release_sha": commit_sha,
                        },
                        edited_payload=None,
                        idempotency_key=(
                            f"{project_id}:approve:{item['approval_request_id']}"
                        ),
                    )
                    print(
                        json.dumps(
                            {"phase": "canon_approved", **_jsonable(decision)},
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            if tick.saga_status in {
                "SUCCEEDED",
                "FAILED_FINAL",
                "DEAD_LETTER",
                "CANCELLED",
                "COMPENSATION_FAILED",
            }:
                break
    finally:
        recovered.close()
    if terminal is None:
        raise RuntimeError("Chapter scheduler produced no recovered tick")
    evidence = _collect_evidence(
        args.database_url,
        project_id=project_id,
        root_operation_id=admission.root_operation_id,
    )
    flags = _evaluate_proof(evidence, commit_sha=commit_sha, model=args.model)
    return {
        "schema_version": "novel-forge.real-capability-codex-proof.v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "release": {
            "branch": branch,
            "commit_sha": commit_sha,
            "worktree_clean": not bool(dirty),
            "allow_dirty": bool(args.allow_dirty),
        },
        "runtime": {
            "environment": "provider-validation",
            "storage_authority": "postgresql",
            "provider": "codex-cli",
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "codex_login_status": (login.stdout or login.stderr).strip(),
            "runtime_root": str(runtime_root),
            "pricing_reference": env["NOVEL_FORGE_CODEX_PRICING_REF"],
            "cost_semantics": "MEASURED usage, ESTIMATED cost, not provider billed",
        },
        "authority": {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "root_operation_id": admission.root_operation_id,
            "saga_id": admission.saga_id,
            "input_asset_version_ids": inputs,
            "migration": _jsonable(migration),
            "capability_pack": _jsonable(pack),
        },
        "recovery_injection": {
            "checkpoint": "after_provider_success",
            "triggered": crash.triggered,
            "expired_lease": _jsonable(expired_lease),
            "remote_inference_cancel_claimed": False,
        },
        "ticks": ticks,
        "proof_flags": flags,
        "evidence": evidence,
        "non_claims": {
            "reader_outcome": (
                "not in chapter_generation_pack workflow; no parallel bypass was used"
            ),
            "longform_proven": False,
            "multi_book_proven": False,
            "production_verified": False,
            "provider_billed_cost": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--codex-executable",
        default="/Applications/ChatGPT.app/Contents/Resources/codex",
    )
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--minio-endpoint", default="127.0.0.1:59039")
    parser.add_argument("--minio-access-key", default="novel_forge")
    parser.add_argument("--minio-secret-key", default="novel_forge_secret")
    parser.add_argument("--minio-secure", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = _run(args)
    except BaseException as exc:
        failure = {
            "schema_version": "novel-forge.real-capability-codex-proof.v1",
            "created_at": datetime.now().astimezone().isoformat(),
            "proof_flags": {
                "capability_runtime_proven": False,
                "real_provider_proven": False,
                "single_chapter_proven": False,
                "structured_output_proven": False,
                "usage_tracking_proven": False,
                "capability_trace_proven": False,
                "recovery_proven": False,
                "REAL_PROVIDER_CAPABILITY_RUNTIME_PROVEN": False,
            },
            "failure": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
        output.write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(failure, ensure_ascii=False), flush=True)
        return 1
    output.write_text(
        json.dumps(_jsonable(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "proof_output": str(output),
                "proof_flags": result["proof_flags"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0 if result["proof_flags"]["REAL_PROVIDER_CAPABILITY_RUNTIME_PROVEN"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
