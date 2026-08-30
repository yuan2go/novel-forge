from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from novel_forge.modules.agent_collaboration.domain import (
    AgentCapability,
    AgentDefinition,
    AgentMessageType,
)
from novel_forge.modules.agent_runtime.application import (
    AgentRuntimeAdminCommand,
    AgentRuntimeAuthorityApplication,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.definitions import (
    book_followup_operation_definitions,
)
from novel_forge.modules.capability_pack_authority.application import (
    CapabilityPackAuthorityApplication,
    CapabilityPackAuthorityCommand,
)
from novel_forge.modules.capability_pack_authority.domain import canonical_hash
from novel_forge.modules.capability_packs.artifacts import (
    default_chapter_artifact_resolver,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    LongformCapabilityPackProfile,
)
from novel_forge.modules.chapter_authority.definitions import (
    chapter_operation_definitions,
)
from novel_forge.modules.production_execution.capability_registry import (
    capability_contract_version,
    default_capability_registry,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
    narrative_semantic_evaluation_definition,
)
from novel_forge.modules.story_planning_runtime.application import (
    story_planning_generation_definition,
)
from novel_forge.storage.authority_repositories import definition_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


VALIDATION_PACK_PERMISSIONS = frozenset(
    {
        "capability_pack.authority.register",
        "capability_pack.authority.compile",
        "capability_pack.authority.approve",
        "capability_pack.authority.deploy",
        "capability_pack.authority.activate",
    }
)


def register_validation_runtime_definitions(
    database_url: str,
    *,
    application_build_id: str,
    commit_sha: str,
) -> dict[str, str]:

    planning = story_planning_generation_definition(
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )
    reader = next(
        item
        for item in book_followup_operation_definitions(
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )
        if item["name"] == "reader_outcome.evaluate"
    )
    narrative_evaluation = narrative_semantic_evaluation_definition(
        application_build_id=NARRATIVE_EVALUATION_APPLICATION_BUILD_ID,
        commit_sha=commit_sha,
    )
    chapter = tuple(
        chapter_operation_definitions(
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            model_effects_required=True,
        )
    )
    with AuthorityUnitOfWork(database_url) as uow:
        for item in (planning, reader, narrative_evaluation, *chapter):
            uow.repositories.definitions.register(item)
        uow.commit()
    return {
        "planning": definition_hash(planning),
        "reader_proxy": definition_hash(reader),
        "narrative_evaluation": definition_hash(narrative_evaluation),
    }


def install_chapter_validation_pack(
    database_url: str,
    *,
    repository_root: str | Path,
    project_id: str,
    workspace_id: str,
    book_id: str,
    application_build_id: str,
    commit_sha: str,
    compiler: Principal,
    approver: Principal,
    agent_admin: Principal,
    pack_path: str | Path = "config/capability_packs/chapter_generation_pack.json",
    pack_id_override: str = "",
    pack_version_override: str = "",
    runtime_environment: str = "validation",
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    source = (root / pack_path).resolve()
    if root not in source.parents or not source.is_file():
        raise ValueError("chapter Capability Pack path is outside the repository")
    manifest = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("chapter Capability Pack manifest must be an object")
    if pack_id_override:
        manifest["identity"]["pack_id"] = pack_id_override
    if pack_version_override:
        manifest["identity"]["version"] = pack_version_override
    resolver = default_chapter_artifact_resolver(root)
    catalog = {
        "schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": [item.to_dict() for item in resolver.artifacts()],
    }
    workflow = dict(manifest.get("workflow_template") or {})
    return _install_validation_manifest(
        database_url,
        manifest=manifest,
        artifact_catalog=catalog,
        workflow_ref=f"{workflow['workflow_id']}@{workflow['workflow_version']}",
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        application_build_id=application_build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
        agent_skill_ref=None,
        agent_domain="chapter",
        agent_scope_type="CHAPTER",
        agent_generation=1,
        expected_activation_version=0,
        runtime_environment=runtime_environment,
    )


def install_longform_validation_pack(
    database_url: str,
    *,
    profile: LongformCapabilityPackProfile,
    pack_version: str,
    agent_generation: int,
    expected_activation_version: int,
    project_id: str,
    workspace_id: str,
    book_id: str,
    application_build_id: str,
    commit_sha: str,
    compiler: Principal,
    approver: Principal,
    agent_admin: Principal,
    agent_domain: str,
    agent_scope_type: str,
    runtime_environment: str = "validation",
) -> dict[str, Any]:
    if not pack_version.strip() or agent_generation <= 0:
        raise ValueError("long-form Pack version and Agent generation are required")
    manifest = deepcopy(profile.manifest)
    manifest["identity"]["version"] = pack_version
    for node in manifest["workflow_template"]["nodes"]:
        agent_ref = str(node.get("agent_definition_ref") or "")
        if agent_ref:
            node["agent_definition_ref"] = (
                f"{agent_ref.rpartition('@')[0]}@{agent_generation}"
            )
    return _install_validation_manifest(
        database_url,
        manifest=manifest,
        artifact_catalog=profile.artifact_catalog,
        workflow_ref=profile.workflow_ref,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        application_build_id=application_build_id,
        commit_sha=commit_sha,
        compiler=compiler,
        approver=approver,
        agent_admin=agent_admin,
        agent_skill_ref=profile.agent_skill_ref,
        agent_domain=agent_domain,
        agent_scope_type=agent_scope_type,
        agent_generation=agent_generation,
        expected_activation_version=expected_activation_version,
        runtime_environment=runtime_environment,
    )


def _install_validation_manifest(
    database_url: str,
    *,
    manifest: dict[str, Any],
    artifact_catalog: Mapping[str, Any],
    workflow_ref: str,
    project_id: str,
    workspace_id: str,
    book_id: str,
    application_build_id: str,
    commit_sha: str,
    compiler: Principal,
    approver: Principal,
    agent_admin: Principal,
    agent_skill_ref: str | None,
    agent_domain: str,
    agent_scope_type: str,
    agent_generation: int,
    expected_activation_version: int,
    runtime_environment: str,
) -> dict[str, Any]:
    identity = dict(manifest.get("identity") or {})
    pack_id = str(identity.get("pack_id") or "")
    pack_version = str(identity.get("version") or "")
    if (
        not pack_id
        or not pack_version
        or not workflow_ref
        or runtime_environment not in {"test", "validation"}
    ):
        raise ValueError("Capability Pack manifest identity is incomplete")
    if compiler.principal_id == approver.principal_id:
        raise PermissionError("Pack compiler and approver must be independent")
    scope_identity = _scope_identity(
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        pack_id=pack_id,
        pack_version=pack_version,
        commit_sha=commit_sha,
    )
    app = CapabilityPackAuthorityApplication(
        database_url,
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )
    registration = _pack_command(
        app,
        compiler,
        action="capability_pack.manifest.register",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=pack_id,
        pack_version="",
        stable_suffix=scope_identity,
        payload={
            "manifest": manifest,
            "artifact_catalog": dict(artifact_catalog),
            "release_channel": "VALIDATION",
            "owner_scope_type": "PROJECT",
            "owner_project_id": project_id,
            "dependencies": [],
        },
    )
    compilation_id = f"compilation:quality:{pack_id}:{scope_identity}"
    compilation = _pack_command(
        app,
        compiler,
        action="capability_pack.compile",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=pack_id,
        pack_version=pack_version,
        compilation_id=compilation_id,
        stable_suffix=scope_identity,
        payload={
            "target_runtime_profile": runtime_environment,
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
        application_build_id=application_build_id,
        commit_sha=commit_sha,
        principal=agent_admin,
        agent_skill_ref=agent_skill_ref,
        agent_domain=agent_domain,
        agent_scope_type=agent_scope_type,
        agent_generation=agent_generation,
        runtime_environment=runtime_environment,
    )
    approval = _pack_command(
        app,
        approver,
        action="capability_pack.approval.decide",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=pack_id,
        pack_version=pack_version,
        compilation_id=compilation_id,
        stable_suffix=scope_identity,
        payload={
            "compilation_hash": compilation["compilation_hash"],
            "decision": "APPROVED",
            "approval_policy_ref": "capability-pack-approval-scope:v1",
            "scope": {
                "schema_version": "CapabilityPackApprovalScope.v1",
                "allowed_environments": [runtime_environment],
                "allowed_runtime_profiles": [runtime_environment],
                "allowed_release_channels": ["VALIDATION"],
                "allowed_scope_types": ["BOOK"],
                "allowed_project_ids": [project_id],
                "allowed_workspace_ids": [workspace_id],
                "allowed_book_ids": [book_id],
                "allowed_workflow_definition_refs": [workflow_ref],
                "allow_canary": False,
                "allow_percentage_rollout": False,
                "allow_full_rollout": True,
                "maximum_rollout_percentage": 100,
            },
            "limitations": ["BOUNDED_QUALITY_QUALIFICATION_ONLY"],
            "reason": "exact-SHA bounded Quality qualification",
            "evidence_refs": [f"quality-qualification:{commit_sha}"],
            "enforce_duties_separation": True,
        },
    )
    deployment_id = f"deployment:quality:{pack_id}:{scope_identity}"
    deployment = _pack_command(
        app,
        compiler,
        action="capability_pack.deployment.create",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=pack_id,
        pack_version=pack_version,
        compilation_id=compilation_id,
        deployment_id=deployment_id,
        stable_suffix=scope_identity,
        payload={
            "target_scope_type": "BOOK",
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "environment": runtime_environment,
            "rollout_policy_ref": "rollout:stable-sha256:v1",
        },
    )
    activation = _pack_command(
        app,
        compiler,
        action="capability_pack.deployment.activate",
        project_id=project_id,
        workspace_id=workspace_id,
        pack_id=pack_id,
        pack_version=pack_version,
        deployment_id=deployment_id,
        expected_activation_version=expected_activation_version,
        stable_suffix=scope_identity,
        payload={
            "environment": runtime_environment,
            "reason": "activate exact-SHA bounded Quality qualification Pack",
        },
    )
    return {
        "pack_id": pack_id,
        "pack_version": pack_version,
        "manifest_hash": registration["manifest_hash"],
        "compilation_id": compilation_id,
        "compilation_hash": compilation["compilation_hash"],
        "deployment_id": deployment_id,
        "registration": registration,
        "compilation": compilation,
        "approval": approval,
        "deployment": deployment,
        "activation": activation,
    }


def _pack_command(
    app: CapabilityPackAuthorityApplication,
    principal: Principal,
    *,
    action: str,
    project_id: str,
    workspace_id: str,
    pack_id: str,
    stable_suffix: str,
    payload: Mapping[str, Any],
    pack_version: str = "",
    compilation_id: str = "",
    deployment_id: str = "",
    expected_activation_version: int = 0,
) -> dict[str, Any]:
    identity = ":".join(
        item
        for item in (
            project_id,
            pack_id,
            pack_version or "registration",
            action,
            stable_suffix,
        )
        if item
    )
    return app.execute(
        CapabilityPackAuthorityCommand(
            definition_name=action,
            project_id=project_id,
            workspace_id=workspace_id,
            actor_id=principal.principal_id,
            pack_id=pack_id,
            pack_version=pack_version,
            compilation_id=compilation_id,
            deployment_id=deployment_id,
            expected_activation_version=expected_activation_version,
            idempotency_key=identity,
            trace_id=f"trace:{identity}",
            correlation_id=f"correlation:{project_id}:quality-packs",
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
    application_build_id: str,
    commit_sha: str,
    principal: Principal,
    agent_skill_ref: str | None,
    agent_domain: str,
    agent_scope_type: str,
    agent_generation: int,
    runtime_environment: str,
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
        application_build_id=application_build_id,
        commit_sha=commit_sha,
        runtime_environment=runtime_environment,
        release_channel="VALIDATION",
    )
    registered: set[str] = set()
    for node in compiled["workflow_nodes"]:
        agent_ref = str(node.get("agent_definition_ref") or "")
        if not agent_ref or agent_ref in registered:
            continue
        registered.add(agent_ref)
        stage = str(node["node_id"])
        skill_name = agent_skill_ref or (
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
        agent_id, separator, raw_version = agent_ref.rpartition("@")
        if not separator or not raw_version.isdigit():
            raise RuntimeError(f"invalid compiled Agent ref: {agent_ref}")
        definition_version = int(raw_version)
        if definition_version != agent_generation:
            raise RuntimeError("compiled Agent generation differs from requested Pack")
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
            supported_scope_types=(agent_scope_type,),
            risk_class=capability_definition.risk_class.value.upper(),
            execution_requirements={"production_execution_gateway_required": True},
            qualification_status="QUALIFIED_REAL_RUNTIME",
        )
        definition = AgentDefinition(
            agent_id=agent_id,
            version=definition_version,
            agent_type=f"{agent_domain.upper()}_STAGE",
            domain=agent_domain,
            role=f"{agent_domain.upper()}_STAGE_AGENT",
            capability_refs=(f"{capability.capability_id}@{capability_version}",),
            input_contract_ref=capability.input_schema_ref,
            output_contract_ref=capability.output_schema_ref,
            authority_scope_ref="scope:bounded-quality@1",
            default_scope_policy_ref="scope:bounded-quality-frozen@1",
            allowed_tools=("request_production_execution",),
            allowed_context_types=("context_bundle",),
            execution_policy_ref="execution:pep@1",
            approval_policy_ref="approval:canonical-authority@1",
            quality_policy_ref="quality:bounded-qualification@1",
            status="ACTIVE",
        )
        base = {
            "project_id": project_id,
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "actor_id": principal.principal_id,
            "correlation_id": f"correlation:{project_id}:quality-packs",
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
                        "supported_scope_types": [agent_scope_type],
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
                        "skill_bundle_ref": f"{skill['ref']}@{skill['version']}",
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
                    "reason": "bounded Quality qualification Pack activation",
                },
                **base,
            ),
            principal=principal,
        )


def _scope_identity(
    *,
    project_id: str,
    workspace_id: str,
    book_id: str,
    pack_id: str,
    pack_version: str,
    commit_sha: str,
) -> str:
    values = (project_id, workspace_id, book_id, pack_id, pack_version, commit_sha)
    if any(not str(item).strip() for item in values) or len(commit_sha) != 40:
        raise ValueError("validation Pack scope identity is incomplete")
    return hashlib.sha256("\x00".join(values).encode("utf-8")).hexdigest()[:20]


__all__ = [
    "VALIDATION_PACK_PERMISSIONS",
    "install_chapter_validation_pack",
    "install_longform_validation_pack",
    "register_validation_runtime_definitions",
]
