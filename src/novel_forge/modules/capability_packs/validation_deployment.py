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
    reader_outcome_definition,
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
    chapter_provider_sample_definitions,
    CHAPTER_SAMPLE_WORKFLOW_ID,
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
    current_reader = reader_outcome_definition(application_build_id=application_build_id, commit_sha=commit_sha)
    prose_review = next(item for item in book_followup_operation_definitions(application_build_id=application_build_id, commit_sha=commit_sha) if item["name"] == "longform.prose_review")
    from novel_forge.modules.book_followup_authority.prose_sampling import prose_sample_definition

    prose_sample = prose_sample_definition(application_build_id=application_build_id, commit_sha=commit_sha)
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
    current_chapter = tuple(chapter_operation_definitions(
        application_build_id=application_build_id, commit_sha=commit_sha,
        model_effects_required=True, coordinated_contract=True,
    ))
    from novel_forge.modules.story_planning_runtime.world_sampling import world_sample_definitions
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import model_reference_creation_definitions

    with AuthorityUnitOfWork(database_url) as uow:
        for item in (planning, reader, current_reader, prose_review, prose_sample, narrative_evaluation, *chapter, *current_chapter, *chapter_provider_sample_definitions(
            application_build_id=application_build_id, commit_sha=commit_sha,
        ), *chapter_provider_sample_definitions(
            application_build_id=application_build_id, commit_sha=commit_sha, reference_samples=True,
        ), *world_sample_definitions(
            application_build_id=application_build_id, commit_sha=commit_sha,
        ), *world_sample_definitions(
            application_build_id=application_build_id, commit_sha=commit_sha, reference_samples=True,
        ), *model_reference_creation_definitions(
            application_build_id=application_build_id, commit_sha=commit_sha,
        )):
            uow.repositories.definitions.register(item)
        uow.commit()
    return {
        "planning": definition_hash(planning),
        "reader_proxy": definition_hash(reader),
        "reader_proxy_current": definition_hash(current_reader),
        "prose_review": definition_hash(prose_review),
        "prose_sample": definition_hash(prose_sample),
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
    expected_activation_version: int = 0,
    agent_generation: int = 1,
    provider_sampling: bool = False,
    reference_sampling: bool = False,
    reference_samples: bool = False,
    model_reference_creation: bool = False,
    runtime_environment: str = "validation",
    prose_skill_version: str = "",
    prompt_template_version: str = "",
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    historical_capacity = ((root / pack_path).resolve() == (root / "config/capability_packs/chapter_generation_pack.json").resolve()
                           and pack_version_override in {"3.0.2", "3.0.3", "3.0.4"})
    if historical_capacity:
        pack_path = "config/capability_packs/historical/chapter_generation_pack_3_0_2.json"
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
    if reference_sampling and not provider_sampling:
        raise ValueError("Chapter reference evaluation requires provider sampling")
    if reference_samples and not reference_sampling:
        raise ValueError("Chapter sample targets require reference sampling")
    if model_reference_creation and (provider_sampling or reference_sampling or reference_samples):
        raise ValueError("model reference creation has its own diagnostic workflow")
    if model_reference_creation:
        if runtime_environment != "validation":
            raise ValueError("model reference creation packs require validation runtime")
        manifest = model_reference_creation_manifest(manifest,
            application_build_id=application_build_id, commit_sha=commit_sha)
    elif provider_sampling:
        if runtime_environment != "validation":
            raise ValueError("Chapter sampling packs are restricted to validation")
        manifest = chapter_provider_sampling_manifest(
            manifest, application_build_id=application_build_id, commit_sha=commit_sha,
            reference=reference_sampling, reference_samples=reference_samples,
        )
    resolver = default_chapter_artifact_resolver(root)
    if historical_capacity:
        from .artifacts import ExplicitArtifactResolver

        resolver = ExplicitArtifactResolver(item for item in resolver.artifacts()
            if item.ref != "context-policy:chapter-generation-pack:v3")
    if prose_skill_version:
        from .artifacts import ArtifactKind

        if not pack_id_override or not pack_version_override:
            raise ValueError("prospective prose Skill selection requires an explicit Pack identity")
        selected_skill = resolver.resolve(ArtifactKind.SKILL, "prose-generation", prose_skill_version)
        bindings = [item for item in manifest["skill_binding"]["skills"] if item["skill_ref"] == "prose-generation"]
        if len(bindings) != 1:
            raise ValueError("Chapter Pack must have one prose Skill binding")
        bindings[0].update(version=selected_skill.version, content_hash=selected_skill.content_hash)
    if prompt_template_version:
        from .artifacts import ArtifactKind

        if not pack_id_override or not pack_version_override:
            raise ValueError("prospective template selection requires an explicit Pack identity")
        selected_template = resolver.resolve(ArtifactKind.PROMPT_TEMPLATE, "prompt-template:chapter-generation-pack", prompt_template_version)
        manifest["prompt_binding"].update(template_version=selected_template.version,
            template_hash=selected_template.content_hash,
            compiler_version="chapter-prompt-compiler:" + selected_template.version)
    catalog = {
        "schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": [item.to_dict() for item in resolver.artifacts()],
    }
    if provider_sampling or model_reference_creation:
        from .artifacts import artifact_content_hash

        for artifact in catalog["artifacts"]:
            if artifact["ref"] == manifest["context_sources"]["policy_id"]:
                artifact["content"]["allowed_asset_types"] = manifest["context_sources"]["allowed_asset_types"]
                if model_reference_creation:
                    artifact["content"]["required_version_refs"] = manifest["context_sources"]["required_version_refs"]
                artifact["content_hash"] = artifact_content_hash(artifact["content"])
            elif artifact["ref"] == manifest["tool_permissions"]["policy_id"]:
                artifact["content"]["explicit_tool_refs"] = ["model.provider.invoke"]
                artifact["content_hash"] = artifact_content_hash(artifact["content"])
    for node in manifest["workflow_template"]["nodes"]:
        ref = str(node.get("agent_definition_ref") or "")
        if ref:
            node["agent_definition_ref"] = f"{ref.rpartition('@')[0]}@{agent_generation}"
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
        agent_scope_type="BOOK" if model_reference_creation else "CHAPTER",
        agent_generation=agent_generation,
        expected_activation_version=expected_activation_version,
        runtime_environment=runtime_environment,
    )


def chapter_provider_sampling_manifest(
    source: Mapping[str, Any], *, application_build_id: str, commit_sha: str, reference: bool = False,
    reference_samples: bool = False,
) -> dict[str, Any]:
    from novel_forge.modules.command_kernel.routing_bootstrap import (
        CHAPTER_SAMPLE_DEFINITION_VERSION, CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE,
        CHAPTER_GENERATOR_TASKS, CHAPTER_REFERENCE_TASKS,
        CHAPTER_REFERENCE_SAMPLE_VERSION,
    )
    from novel_forge.modules.chapter_authority.definitions import CHAPTER_REFERENCE_WORKFLOW_ID

    if reference_samples and not reference:
        raise ValueError("Chapter sample targets require reference sampling")
    version = CHAPTER_REFERENCE_SAMPLE_VERSION if reference_samples else CHAPTER_SAMPLE_DEFINITION_VERSION
    manifest = deepcopy(dict(source))
    source_version = str(manifest["identity"]["version"]).split(".")
    sampling_pack_version = ".".join([str(int(source_version[0]) + 1), *source_version[1:]])
    manifest["identity"].update({
        "pack_id": str(manifest["identity"]["pack_id"]) + (".reference_samples" if reference_samples else ".reference_sampling" if reference else ".provider_sampling"),
        "version": sampling_pack_version,
        "name": "Chapter Provider Sampling Pack",
        "description": "Governed isolated samples using the frozen Chapter generation contracts.",
    })
    tasks = CHAPTER_REFERENCE_TASKS if reference else CHAPTER_GENERATOR_TASKS
    definitions = {item["policy"]["source_definition_name"]: item for item in
                   chapter_provider_sample_definitions(application_build_id=application_build_id, commit_sha=commit_sha, reference_samples=reference_samples)
                   if item["policy"]["source_definition_name"] in tasks}
    workflow = manifest["workflow_template"]
    workflow.update({"workflow_id": CHAPTER_REFERENCE_WORKFLOW_ID if reference else CHAPTER_SAMPLE_WORKFLOW_ID,
                     "workflow_version": version,
                     "idempotency_scope": CHAPTER_SAMPLE_IDEMPOTENCY_SCOPE})
    nodes = []
    for node in workflow["nodes"]:
        definition = definitions.get(node["operation_name"])
        if definition is None:
            continue
        node.update({
            "operation_name": definition["name"],
            "operation_definition_ref": definition["name"] + "@" + version,
            "operation_definition_hash": definition_hash(definition),
            "handler_key": definition["handler_key"], "depends_on": [],
            "output_asset_types": ["chapter_provider_sample"],
            "retry_policy": {**definition["retry_policy"], "retryable_errors": []},
        })
        if reference_samples:
            target_type = "draft_chapter" if node["node_id"] == "review" else "draft_version"
            node["input_asset_types"] = ["chapter_provider_sample" if value == target_type else value for value in node["input_asset_types"]]
        nodes.append(node)
    workflow["nodes"] = nodes
    workflow["completion"] = {
        "required_terminal_nodes": [node["node_id"] for node in nodes],
        "required_evidence": ["trace", "audit"],
        "required_output_asset_types": ["chapter_provider_sample"],
    }
    manifest["context_sources"]["allowed_asset_types"] = sorted({
        *manifest["context_sources"]["allowed_asset_types"],
        *(item for node in nodes for item in node["input_asset_types"]),
    })
    model_tool = next(item for item in manifest["tool_permissions"]["tools"] if item["tool_ref"] == "model.provider.invoke")
    model_tool["allowed_operations"] = [node["node_id"] for node in nodes]
    manifest["tool_permissions"]["tools"] = [model_tool]
    manifest["evaluation"]["required_gates"] = [{
        "gate_id": "sample_source_isolation", "judge_capability_id": "quality.originality.judge",
        "blocking": True, "threshold": 1, "required_evidence": ["chapter_provider_sample"],
    }]
    manifest["evaluation"]["metrics"] = []
    return manifest


def model_reference_creation_manifest(source: Mapping[str, Any], *,
                                      application_build_id: str,
                                      commit_sha: str) -> dict[str, Any]:
    """INVARIANT: a diagnostic derivative retains the root Pack's governed dependencies."""
    from novel_forge.modules.chapter_quality_authority.model_reference_execution import (
        MODEL_REFERENCE_STAGE, MODEL_REFERENCE_OUTPUT, model_reference_creation_definitions,
    )
    from .artifacts import artifact_content_hash

    manifest = deepcopy(dict(source))
    manifest.setdefault("ext", {}).setdefault("experiments", {})["model_reference_source_pack"] = {
        "pack_id": str(source["identity"]["pack_id"]),
        "version": str(source["identity"]["version"]),
        "manifest_hash": canonical_hash(dict(source)),
    }
    identity = manifest["identity"]
    identity.update({"pack_id": str(identity["pack_id"]) + ".model_reference_creation",
        "version": "3.0.0", "name": "Model Reference Creation Diagnostic Pack",
        "description": "Two blind independent evaluations and an adjudication of frozen native candidates.",
        "domain": "chapter_quality"})
    definitions = {item["name"]: item for item in model_reference_creation_definitions(
        application_build_id=application_build_id, commit_sha=commit_sha)}
    prototype = next(node for node in manifest["workflow_template"]["nodes"]
        if node["capability_id"] == "quality.intrinsic.judge")
    nodes = []
    for name, stage in MODEL_REFERENCE_STAGE.items():
        definition = definitions[name]
        node = deepcopy(prototype)
        node.update({"node_id": stage, "operation_name": name,
            "operation_definition_ref": name + "@1.0.0",
            "operation_definition_hash": definition_hash(definition),
            "handler_key": definition["handler_key"], "stage": stage,
            "agent_definition_ref": ("model-reference-evaluator@1" if stage == "model_reference_evaluate"
                else "model-reference-adjudicator@1"),
            "input_asset_types": ["chapter_provider_sample", "world_provider_sample",
                "planning_generation_candidate", "creative_brief", "model_reference_evaluation"],
            "output_asset_types": [MODEL_REFERENCE_OUTPUT], "depends_on": [],
            "retry_policy": {**definition["retry_policy"], "retryable_errors": []}})
        nodes.append(node)
    workflow = manifest["workflow_template"]
    workflow.update({"workflow_id": "model_reference_creation",
        "workflow_version": "1.0.0", "execution_mode": "SAGA",
        "idempotency_scope": "book:model-reference-creation", "nodes": nodes,
        "completion": {"required_terminal_nodes": [item["node_id"] for item in nodes],
            "required_evidence": ["trace", "audit"],
            "required_output_asset_types": [MODEL_REFERENCE_OUTPUT]}})
    manifest["context_sources"].update({"allowed_asset_types": sorted({*manifest["context_sources"]["allowed_asset_types"],
            "chapter_provider_sample", "world_provider_sample", "planning_generation_candidate",
            "creative_brief", "model_reference_evaluation", "context_bundle"}),
        "required_version_refs": ["model_reference.subject.asset_version_id",
            "model_reference.author_baseline.asset_version_id"]})
    manifest["assets"]["knowledge"]["required_packs"] = []
    model_tool = next(item for item in manifest["tool_permissions"]["tools"]
        if item["tool_ref"] == "model.provider.invoke")
    model_tool["allowed_operations"] = list(MODEL_REFERENCE_STAGE.values())
    manifest["tool_permissions"]["tools"] = [model_tool]
    manifest["evaluation"].update({"evaluation_id": "model-reference-creation-diagnostic.v1",
        "required_gates": [{"gate_id": "model_reference_source_isolation",
            "judge_capability_id": "quality.originality.judge", "blocking": True,
            "threshold": 1, "required_evidence": [MODEL_REFERENCE_OUTPUT]}], "metrics": []})
    for key, ref, version, filename in (
        ("system_instruction", "prompt-system:model-reference-creation", "v1",
         "config/capability_packs/artifacts/model_reference_system_instruction_v1.md"),
        ("template", "prompt-template:model-reference-creation", "v1",
         "config/capability_packs/artifacts/model_reference_template_v1.md")):
        from pathlib import Path
        content = {"text": (Path(__file__).resolve().parents[4] / filename).read_text(encoding="utf-8")}
        binding = manifest["prompt_binding"]
        binding[key + "_ref"] = ref
        binding[key + "_version"] = version
        binding[key + "_hash"] = artifact_content_hash(content)
    manifest["prompt_binding"].update({"compiler_version": "model-reference-prompt-compiler:v1",
        "input_schema_ref": "schema:model-reference-creation-input:v1",
        "output_schema_ref": "schema:model-reference-creation-output:v1"})
    return manifest


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


def install_agent_validation_pack(database_url: str, *, repository_root: str | Path,
    project_id: str, workspace_id: str, book_id: str, application_build_id: str,
    commit_sha: str, compiler: Principal, approver: Principal, agent_admin: Principal,
    expected_activation_version: int = 0) -> dict[str, Any]:
    from novel_forge.modules.agent_runtime.definitions import agent_runtime_operation_definitions

    root = Path(repository_root).resolve()
    manifest = json.loads((root / "config/capability_packs/agent_session_pack.json").read_text(encoding="utf-8"))
    resolver = default_chapter_artifact_resolver(root)
    catalog = {"schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": [item.to_dict() for item in resolver.artifacts()]}
    with AuthorityUnitOfWork(database_url) as uow:
        for definition in agent_runtime_operation_definitions(application_build_id=application_build_id, commit_sha=commit_sha):
            uow.repositories.definitions.register(definition)
        uow.commit()
    return _install_validation_manifest(database_url, manifest=manifest, artifact_catalog=catalog,
        workflow_ref="agent_session_runtime@2.1.0", project_id=project_id, workspace_id=workspace_id,
        book_id=book_id, application_build_id=application_build_id, commit_sha=commit_sha,
        compiler=compiler, approver=approver, agent_admin=agent_admin,
        agent_skill_ref="agent-loop-governance", agent_domain="agent_runtime", agent_scope_type="BOOK",
        agent_generation=1, expected_activation_version=expected_activation_version, runtime_environment="validation")


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
        or runtime_environment not in {"development", "test", "validation", "production"}
    ):
        raise ValueError("Capability Pack manifest identity is incomplete")
    from novel_forge.modules.production_execution.execution_template import selected_book_template
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    with AuthorityUnitOfWork(database_url) as uow:
        creative = selected_book_template(uow.cursor, project_id=project_id, book_id=book_id, allow_literary_required=True)
    template = next((item for item in creative["policy_snapshot"]["policy"]["execution_templates"]
                     if item["book_id"] == book_id), None) if creative else None
    from novel_forge.modules.capability_pack_authority.validation_admission import _author_template
    automatic = bool(template and not template["require_pack_human_approval"]
                     and (runtime_environment == "validation" or _author_template(template)))
    if not automatic and compiler.principal_id == approver.principal_id:
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
    if not automatic and str(compilation["compilation_id"]) != compilation_id:
        from novel_forge.modules.command_kernel.errors import KernelError

        raise KernelError("CAPABILITY_PACK_SHARED_APPROVAL_SCOPE_REQUIRED",
            "Use the approval Authority for shared strict scopes before another Book deployment")
    compilation_id = str(compilation["compilation_id"])
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
    if automatic:
        scope = {"schema_version": "CapabilityPackApprovalScope.v1",
            "allowed_environments": [runtime_environment], "allowed_runtime_profiles": [runtime_environment],
            "allowed_release_channels": ["VALIDATION"], "allowed_scope_types": ["BOOK"],
            "allowed_project_ids": [project_id], "allowed_workspace_ids": [workspace_id], "allowed_book_ids": [book_id],
            "allowed_workflow_definition_refs": [workflow_ref], "allow_canary": False, "allow_percentage_rollout": False,
            "allow_full_rollout": True, "maximum_rollout_percentage": 100}
        approval = _pack_command(app, compiler, action="capability_pack.validation.admit", project_id=project_id,
            workspace_id=workspace_id, pack_id=pack_id, pack_version=pack_version, compilation_id=compilation_id,
            stable_suffix=scope_identity, payload={"book_id": book_id, "policy_snapshot": creative["policy_snapshot"],
                "compilation_hash": compilation["compilation_hash"], "scope": scope})
    else:
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
    expected_system_ref = ("prompt-system:model-reference-creation"
        if str(compiled.get("pack_id") or "").endswith(".model_reference_creation") else "")
    prompt = next(
        item for item in artifacts if item["kind"] == "PROMPT_SYSTEM_INSTRUCTION"
        and (not expected_system_ref or item["ref"] == expected_system_ref)
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
        agent_session = stage == "agent_session"
        definition = AgentDefinition(
            agent_id=agent_id,
            version=definition_version,
            agent_type="AUTONOMOUS_SESSION" if agent_session else f"{agent_domain.upper()}_STAGE",
            domain=agent_domain,
            role="STUDIO_DIRECTOR" if agent_session else f"{agent_domain.upper()}_STAGE_AGENT",
            capability_refs=(f"{capability.capability_id}@{capability_version}",),
            input_contract_ref=capability.input_schema_ref,
            output_contract_ref=capability.output_schema_ref,
            authority_scope_ref="scope:book@1" if agent_session else "scope:bounded-quality@1",
            default_scope_policy_ref="scope:accepted-book-boundary@1" if agent_session else "scope:bounded-quality-frozen@1",
            allowed_tools=("narrative.query_accepted", "story_planning.generate_candidate", "plan_change.submit")
                if agent_session else ("request_production_execution",),
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
    "install_agent_validation_pack",
    "model_reference_creation_manifest",
    "install_longform_validation_pack",
    "register_validation_runtime_definitions",
]
