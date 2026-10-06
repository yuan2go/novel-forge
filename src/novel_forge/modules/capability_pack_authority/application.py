from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import uuid4
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.capability_packs.artifacts import (
    ArtifactKind,
    ExplicitArtifactResolver,
    ResolvedArtifact,
    artifact_content_hash,
    canonical_artifact_json,
)
from novel_forge.modules.capability_packs.compiler import CapabilityPackCompiler
from novel_forge.modules.capability_packs.loader import load_capability_pack_payload
from novel_forge.modules.capability_packs.operation_catalog import (
    RepositoryOperationDefinitionLoader,
    governed_workflow_binding_catalog,
)
from novel_forge.modules.capability_packs.type_catalog import (
    default_capability_type_catalog,
    default_tool_definition_catalog,
)
from novel_forge.modules.capability_packs.versioning import (
    PackCatalogEntry,
    PackDependency,
    ReadOnlyPackCatalog,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.production_execution.capability_registry import (
    default_capability_registry,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .definitions import (
    CAPABILITY_PACK_ADMIN_HANDLER_KEY,
    CAPABILITY_PACK_AUTHORITY_OPERATIONS,
    CAPABILITY_PACK_COMPILER_VERSION,
    CAPABILITY_PACK_DEFINITION_VERSION,
    capability_pack_operation_definitions,
)
from .domain import (
    ApprovalDecision,
    CapabilityPackScope,
    RolloutStatus,
    ScopeType,
    canonical_hash,
)
from .policy import CapabilityPackApprovalScope, normalize_limitations


_FORBIDDEN_COMPILED_INPUTS = {"compiled_payload", "compiled_capability_pack"}


@dataclass(frozen=True, slots=True)
class CapabilityPackAuthorityCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    actor_id: str
    pack_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    payload: Mapping[str, Any]
    pack_version: str = ""
    compilation_id: str = ""
    deployment_id: str = ""
    rollout_id: str = ""
    expected_activation_version: int = 0

    def __post_init__(self) -> None:
        if self.definition_name not in CAPABILITY_PACK_AUTHORITY_OPERATIONS:
            raise ValueError("unsupported Capability Pack Authority command")
        required = (
            self.project_id,
            self.workspace_id,
            self.actor_id,
            self.pack_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Capability Pack Authority command is incomplete")
        if (
            self.definition_name != "capability_pack.manifest.register"
            and not self.pack_version
        ):
            raise ValueError("pack_version is required for this Capability Pack action")
        if self.expected_activation_version < 0:
            raise ValueError("expected activation version cannot be negative")
        forbidden = sorted(_FORBIDDEN_COMPILED_INPUTS & set(self.payload))
        if forbidden:
            raise ValueError(
                "caller-supplied compiled Capability Pack payload is forbidden"
            )

    @property
    def environment(self) -> str:
        return str(self.payload.get("environment") or "validation")


def build_binding_set(
    *,
    compiled: Mapping[str, Any],
    manifest: Mapping[str, Any],
    agent_definitions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:

    artifacts = [dict(item) for item in compiled.get("resolved_artifacts") or ()]
    artifact_bindings = {
        "resolved_artifacts": artifacts,
        "prompt": dict(manifest.get("prompt_binding") or {}),
        "skills": list((manifest.get("skill_binding") or {}).get("skills") or ()),
    }
    tool = dict(compiled.get("tool_permission_snapshot") or {})
    context = dict(compiled.get("context_source_snapshot") or {})
    evaluation = dict(compiled.get("evaluation_gate_snapshot") or {})
    governance = dict(manifest.get("governance") or {})
    runtime = dict(manifest.get("runtime_contract") or {})
    prompt_binding = dict(manifest.get("prompt_binding") or {})
    skill_bindings = [
        dict(item) for item in (manifest.get("skill_binding") or {}).get("skills") or ()
    ]
    route_ref = str((tool.get("external_models") or {}).get("route_policy_ref") or "")
    approval_ref = str(governance.get("approval_policy_ref") or "")
    budget_ref = str(
        (governance.get("cost_tracking") or {}).get("budget_policy_ref") or ""
    )
    policy_bindings = {
        "tool_policy_ref": str(tool.get("policy_id") or ""),
        "tool_policy_hash": canonical_hash(tool),
        "context_policy_ref": str(context.get("policy_id") or ""),
        "context_policy_hash": canonical_hash(context),
        "evaluation_policy_ref": str(evaluation.get("evaluation_id") or ""),
        "evaluation_policy_hash": canonical_hash(evaluation),
        "route_policy_ref": route_ref,
        "route_policy_hash": _artifact_hash(artifacts, route_ref),
        "approval_policy_ref": approval_ref,
        "approval_policy_hash": _artifact_hash(artifacts, approval_ref),
        "budget_policy_ref": budget_ref,
        "budget_policy_hash": _artifact_hash(artifacts, budget_ref),
        "commit_policy_ref": str(runtime.get("commit_policy_ref") or ""),
        "validation_policy_ref": str(runtime.get("validation_policy_ref") or ""),
    }
    expected_pack_ref = f"{compiled['pack_id']}@{compiled['pack_version']}"
    nodes: list[dict[str, Any]] = []
    for raw in compiled.get("workflow_nodes") or ():
        node = dict(raw)
        capability_definition = default_capability_registry().resolve(
            str(node["capability_id"])
        )
        selected_skill = _select_capability_skill(
            skill_bindings,
            capability_id=str(node["capability_id"]),
            input_contract_ref=str(capability_definition.input_schema_ref),
            output_contract_ref=str(capability_definition.output_schema_ref),
        )
        prompt_system_ref = _versioned_ref(
            str(prompt_binding.get("system_instruction_ref") or ""),
            str(prompt_binding.get("system_instruction_version") or ""),
        )
        prompt_system_hash = str(
            prompt_binding.get("system_instruction_hash") or ""
        )
        _require_artifact_identity(artifacts, prompt_system_ref, prompt_system_hash)
        skill_ref = _versioned_ref(
            str(selected_skill.get("skill_ref") or ""),
            str(selected_skill.get("version") or ""),
        )
        skill_hash = str(selected_skill.get("content_hash") or "")
        _require_artifact_identity(artifacts, skill_ref, skill_hash)
        definition_ref = f"{node['definition_name']}@{node['definition_version']}"
        binding: dict[str, Any] = {
            "ordinal": int(node["ordinal"]),
            "workflow_node_id": str(node["node_id"]),
            "operation_definition_ref": definition_ref,
            "operation_definition_hash": str(node["definition_hash"]),
            "capability_ref": f"{node['capability_id']}@1",
            "capability_hash": str(node["capability_contract_hash"]),
            "agent_definition_ref": str(node.get("agent_definition_ref") or ""),
            "agent_definition_hash": "",
            "execution_capability_id": str(node["capability_id"]),
            "execution_capability_hash": str(node["capability_contract_hash"]),
            "prompt_bundle_ref": prompt_system_ref,
            "prompt_bundle_hash": prompt_system_hash,
            "skill_bundle_ref": skill_ref,
            "skill_bundle_hash": skill_hash,
            "prompt_system_instruction_ref": prompt_system_ref,
            "prompt_system_instruction_hash": prompt_system_hash,
            "prompt_template_ref": _versioned_ref(
                str(prompt_binding.get("template_ref") or ""),
                str(prompt_binding.get("template_version") or ""),
            ),
            "prompt_template_hash": str(prompt_binding.get("template_hash") or ""),
            "prompt_compiler_version": str(
                prompt_binding.get("compiler_version") or ""
            ),
            "skill_ref": str(selected_skill.get("skill_ref") or ""),
            "skill_version": str(selected_skill.get("version") or ""),
            "skill_content_hash": skill_hash,
            "context_policy_payload": context,
            "tool_policy_payload": tool,
            "evaluation_policy_payload": evaluation,
            "input_contract_ref": str(capability_definition.input_schema_ref),
            "output_contract_ref": str(capability_definition.output_schema_ref),
            "domain_acceptance_policy_ref": str(
                governance.get("approval_policy_ref")
                or "approval:chapter-domain-authority:v1"
            ),
            "commit_authority": str(
                node.get("commit_authority") or "CHAPTER_AUTHORITY"
            ),
            **policy_bindings,
        }
        agent_ref = binding["agent_definition_ref"]
        if agent_ref:
            agent = agent_definitions.get(agent_ref)
            if agent is None:
                raise KernelError(
                    "CAPABILITY_PACK_AGENT_DEFINITION_NOT_ACTIVE",
                    f"Binding Set requires active Agent Definition {agent_ref}",
                )
            if str(agent.get("capability_pack_ref")) != expected_pack_ref:
                raise KernelError(
                    "CAPABILITY_PACK_AGENT_CONTRACT_DRIFT",
                    "Agent Definition runtime contract references another Pack",
                )
            capability = next(
                (
                    dict(item)
                    for item in agent.get("capabilities") or ()
                    if str(item.get("capability_id")) == str(node["capability_id"])
                ),
                None,
            )
            if capability is None:
                raise KernelError(
                    "CAPABILITY_PACK_CAPABILITY_BINDING_DRIFT",
                    "Agent Definition lacks the compiled Capability mapping",
                )
            if str(capability.get("execution_capability_id")) != str(
                node["capability_id"]
            ) or str(capability.get("execution_capability_hash")) != str(
                node["capability_contract_hash"]
            ):
                raise KernelError(
                    "CAPABILITY_PACK_EXECUTION_CAPABILITY_DRIFT",
                    "Agent execution mapping differs from trusted Compilation",
                )
            _require_artifact_identity(
                artifacts,
                str(agent.get("prompt_bundle_ref") or ""),
                str(agent.get("prompt_bundle_hash") or ""),
            )
            _require_artifact_identity(
                artifacts,
                str(agent.get("skill_bundle_ref") or ""),
                str(agent.get("skill_bundle_hash") or ""),
            )
            prompt_system_ref = _versioned_ref(
                str(prompt_binding.get("system_instruction_ref") or ""),
                str(prompt_binding.get("system_instruction_version") or ""),
            )
            prompt_template_ref = _versioned_ref(
                str(prompt_binding.get("template_ref") or ""),
                str(prompt_binding.get("template_version") or ""),
            )
            _require_artifact_identity(
                artifacts,
                prompt_template_ref,
                str(prompt_binding.get("template_hash") or ""),
            )
            if str(agent.get("prompt_bundle_ref") or "") != prompt_system_ref or str(
                agent.get("prompt_bundle_hash") or ""
            ) != str(prompt_binding.get("system_instruction_hash") or ""):
                raise KernelError(
                    "CAPABILITY_PACK_PROMPT_BINDING_DRIFT",
                    "Agent Definition prompt source differs from Pack Prompt Binding",
                )
            agent_skill_ref = str(agent.get("skill_bundle_ref") or "")
            agent_skill_hash = str(agent.get("skill_bundle_hash") or "")
            selected_skills = [
                item
                for item in skill_bindings
                if _versioned_ref(
                    str(item.get("skill_ref") or ""),
                    str(item.get("version") or ""),
                )
                == agent_skill_ref
                and str(item.get("content_hash") or "") == agent_skill_hash
            ]
            if len(selected_skills) != 1:
                raise KernelError(
                    "CAPABILITY_PACK_SKILL_BINDING_DRIFT",
                    "Agent Definition skill source differs from Pack Skill Binding",
                )
            selected_skill = selected_skills[0]
            required_agent_contract = (
                "input_contract_ref",
                "output_contract_ref",
                "approval_policy_ref",
            )
            missing_agent_contract = [
                key for key in required_agent_contract if not str(agent.get(key) or "")
            ]
            if missing_agent_contract:
                raise KernelError(
                    "CAPABILITY_PACK_AGENT_CONTRACT_INCOMPLETE",
                    "Agent Definition lacks required binding fields: "
                    + ", ".join(missing_agent_contract),
                )
            expected_policies = {
                "tool_policy_ref": policy_bindings["tool_policy_ref"],
                "tool_policy_hash": policy_bindings["tool_policy_hash"],
                "context_policy_ref": policy_bindings["context_policy_ref"],
                "context_policy_hash": policy_bindings["context_policy_hash"],
            }
            drift = [
                key
                for key, value in expected_policies.items()
                if str(agent.get(key) or "") != str(value)
            ]
            if drift:
                raise KernelError(
                    "CAPABILITY_PACK_AGENT_POLICY_DRIFT",
                    "Agent Definition policy differs from Compilation: "
                    + ", ".join(drift),
                )
            binding.update(
                {
                    "agent_id": str(agent["agent_id"]),
                    "agent_definition_version": int(agent["definition_version"]),
                    "agent_definition_hash": str(agent["definition_hash"]),
                    "capability_id": str(capability["capability_id"]),
                    "capability_version": int(capability["capability_version"]),
                    "capability_ref": (
                        f"{capability['capability_id']}@"
                        f"{capability['capability_version']}"
                    ),
                    "capability_hash": str(capability["capability_hash"]),
                    "execution_capability_id": str(
                        capability["execution_capability_id"]
                    ),
                    "execution_capability_hash": str(
                        capability["execution_capability_hash"]
                    ),
                    "prompt_bundle_ref": str(agent["prompt_bundle_ref"]),
                    "prompt_bundle_hash": str(agent["prompt_bundle_hash"]),
                    "skill_bundle_ref": str(agent["skill_bundle_ref"]),
                    "skill_bundle_hash": str(agent["skill_bundle_hash"]),
                    "prompt_system_instruction_ref": prompt_system_ref,
                    "prompt_system_instruction_hash": str(
                        prompt_binding["system_instruction_hash"]
                    ),
                    "prompt_template_ref": prompt_template_ref,
                    "prompt_template_hash": str(prompt_binding["template_hash"]),
                    "prompt_compiler_version": str(prompt_binding["compiler_version"]),
                    "skill_ref": str(selected_skill["skill_ref"]),
                    "skill_version": str(selected_skill["version"]),
                    "skill_content_hash": str(selected_skill["content_hash"]),
                    "context_policy_payload": context,
                    "tool_policy_payload": tool,
                    "evaluation_policy_payload": evaluation,
                    "input_contract_ref": str(agent["input_contract_ref"]),
                    "output_contract_ref": str(agent["output_contract_ref"]),
                    "domain_acceptance_policy_ref": str(
                        agent.get("approval_policy_ref")
                        or "approval:chapter-domain-authority:v1"
                    ),
                }
            )
        nodes.append(binding)
    workflow = dict(manifest.get("workflow_template") or {})
    workflow_ref = f"{workflow.get('workflow_id')}@{workflow.get('workflow_version')}"
    payload = {
        "schema_version": "novelos.capability_pack.binding_set.v1",
        "pack_id": str(compiled["pack_id"]),
        "pack_version": str(compiled["pack_version"]),
        "compilation_hash": str(compiled["compilation_hash"]),
        "workflow_definition_ref": workflow_ref,
        "node_bindings": sorted(nodes, key=lambda item: int(item["ordinal"])),
        "artifact_bindings": artifact_bindings,
        "policy_bindings": policy_bindings,
    }
    return {**payload, "binding_set_hash": canonical_hash(payload)}


def _select_capability_skill(
    skills: Sequence[Mapping[str, Any]],
    *,
    capability_id: str,
    input_contract_ref: str,
    output_contract_ref: str,
) -> dict[str, Any]:
    """INVARIANT: Select a Skill from the Pack without requiring an Agent Definition.

    Exact input/output contract matches win.  Packs whose Skill contract is
    intentionally broader may fall back to a single required Skill; multiple
    ambiguous fallbacks fail closed instead of depending on list order.
    """
    exact = [
        dict(item)
        for item in skills
        if str(item.get("input_contract_ref") or "") == input_contract_ref
        and str(item.get("output_contract_ref") or "") == output_contract_ref
    ]
    if len(exact) == 1:
        return exact[0]
    output_matches = [
        dict(item)
        for item in skills
        if str(item.get("output_contract_ref") or "") == output_contract_ref
    ]
    if len(output_matches) == 1:
        return output_matches[0]
    foundation_skills = {
        "creative.proposal.generate": "topic-development",
        "theme.question.generate": "narrative-beat-design",
        "ending.intent.generate": "long-outline",
        "reader.promise.generate": "hot-novel-business-deconstruction",
        "world.design.generate": "worldbuilding",
        "character.cast.generate": "character-design",
    }
    preferred_skill = (
        foundation_skills[capability_id]
        if capability_id in foundation_skills
        else "chapter-outline"
        if capability_id.startswith("planning.")
        else "context-builder-source-isolation"
        if capability_id.startswith("retrieval.") or capability_id == "context.task.compile"
        else "prose-generation"
        if capability_id.startswith(("prose.", "revision."))
        else "canon-continuity-graph"
        if capability_id.startswith("canon.")
        else "quality-review"
        if capability_id.startswith(("review.", "quality.", "publishing.", "storage."))
        else ""
    )
    calibrated = {str(item.get("skill_ref")): str(item.get("version")) for item in skills}
    if capability_id == "reader.promise.generate" and calibrated.get("topic-development") == "topic-development-qualification-v2":
        preferred_skill = "topic-development"
    if capability_id in {"planning.book.generate", "planning.volume.generate", "planning.arc.generate", "planning.chapter_group.generate"} and calibrated.get("long-outline") in {"long-outline-v2", "long-outline-v3"}:
        preferred_skill = "long-outline"
    preferred = [
        dict(item)
        for item in skills
        if str(item.get("skill_ref") or "") == preferred_skill
    ]
    if len(preferred) == 1:
        return preferred[0]
    required = [dict(item) for item in skills if bool(item.get("required"))]
    if len(required) == 1:
        return required[0]
    raise KernelError(
        "CAPABILITY_PACK_SKILL_BINDING_AMBIGUOUS",
        "Capability node requires one contract-matching Skill binding",
    )


class CapabilityPackAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("Capability Pack Authority requires PostgreSQL")
        if not application_build_id or len(commit_sha) != 40:
            raise ValueError(
                "Capability Pack Authority requires exact release identity"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

    def execute(
        self, command: CapabilityPackAuthorityCommand, *, principal: Principal
    ) -> dict[str, Any]:
        permission = _permission_for(command.definition_name)
        principal.require(permission, command.project_id)
        if principal.principal_id != command.actor_id:
            raise PermissionError("Capability Pack actor must be the trusted Principal")
        _validate_command_scope(command, principal)
        self._register_definitions()
        prepared = self._prepare(command)
        context = AdmissionContext(
            actor_id=principal.principal_id,
            permissions=principal.permissions,
            available_handlers=frozenset({CAPABILITY_PACK_ADMIN_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            return self._execute_transaction(
                uow,
                operation_id=operation_id,
                command=command,
                prepared=prepared,
                checkpoint=checkpoint,
            )

        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": CAPABILITY_PACK_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "pack_id": command.pack_id,
                "pack_version": command.pack_version or "registration",
                "environment": command.environment,
                "idempotency_scope": "project:capability-pack-authority",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "pack_id": command.pack_id,
                    "pack_version": command.pack_version,
                    "compilation_id": command.compilation_id,
                    "deployment_id": command.deployment_id,
                    "rollout_id": command.rollout_id,
                    "expected_activation_version": (
                        command.expected_activation_version
                    ),
                    "payload": dict(command.payload),
                },
                "input_assets": [],
            },
            context=context,
            handler=handler,
            fault_injector=self.fault_injector,
        )

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in capability_pack_operation_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _prepare(self, command: CapabilityPackAuthorityCommand) -> dict[str, Any]:
        if command.definition_name in {
            "capability_pack.manifest.validate",
            "capability_pack.compile",
        }:
            return self._prepare_compilation(command)
        if command.definition_name == "capability_pack.deployment.create":
            return self._prepare_binding_set(command)
        return {}

    def _prepare_compilation(
        self, command: CapabilityPackAuthorityCommand
    ) -> dict[str, Any]:
        release_sha = str(command.payload.get("release_sha") or "")
        if release_sha != self.commit_sha:
            raise KernelError(
                "CAPABILITY_PACK_RELEASE_IDENTITY_CONFLICT",
                "trusted compilation must bind the running exact release SHA",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            version = uow.repositories.capability_packs.require_version(
                command.pack_id,
                command.pack_version,
                project_id=command.project_id,
            )
            catalog_records = (
                uow.repositories.capability_packs.exact_dependency_catalog(
                    pack_id=command.pack_id,
                    pack_version=command.pack_version,
                    project_id=command.project_id,
                )
            )
            manifest = load_capability_pack_payload(version["manifest"])
            identities = []
            for node in manifest.workflow_template.nodes:
                name, separator, value = str(node.operation_definition_ref).rpartition(
                    "@"
                )
                if not separator:
                    raise KernelError(
                        "CAPABILITY_PACK_OPERATION_DEFINITION_INVALID",
                        "Manifest requires exact OperationDefinition refs",
                    )
                identities.append((name, value))
            operation_catalog = RepositoryOperationDefinitionLoader(
                uow.repositories.definitions
            ).load(
                identities,
                commit_sha=self.commit_sha,
            )
        artifact_resolver = _artifact_resolver(version["artifact_catalog"])
        compiler = CapabilityPackCompiler(
            capability_registry=default_capability_registry(),
            capability_type_catalog=default_capability_type_catalog(),
            operation_catalog=operation_catalog,
            workflow_catalog=governed_workflow_binding_catalog(
                str(manifest.workflow_template.workflow_id),
                str(manifest.workflow_template.workflow_version),
            ),
            artifact_resolver=artifact_resolver,
            tool_catalog=default_tool_definition_catalog(),
            pack_catalog=ReadOnlyPackCatalog(
                PackCatalogEntry(
                    load_capability_pack_payload(record["manifest"]),
                    tuple(
                        PackDependency(item["pack_id"], item["version"])
                        for item in record["dependencies"]
                    ),
                )
                for record in catalog_records
            ),
        )
        result = compiler.compile(
            manifest,
            target_runtime_profile=str(
                command.payload.get("target_runtime_profile") or ""
            ),
            novel_forge_version=str(command.payload.get("novel_forge_version") or ""),
            release_sha=release_sha,
            release_channel=str(command.payload.get("release_channel") or ""),
            expected_manifest_hash=str(version["manifest_hash"]),
        )
        report = _compilation_report(result.report)
        return {
            "version_identity": {
                "manifest_hash": version["manifest_hash"],
                "artifact_catalog_hash": version["artifact_catalog_hash"],
            },
            "report": report,
            "compiled": result.compiled.to_dict() if result.compiled else None,
        }

    def _prepare_binding_set(
        self, command: CapabilityPackAuthorityCommand
    ) -> dict[str, Any]:
        if not command.compilation_id:
            raise ValueError("deployment creation requires compilation_id")
        with AuthorityUnitOfWork(self.database_url) as uow:
            compilation = (
                uow.repositories.capability_packs.require_admitted_compilation(
                    command.compilation_id, project_id=command.project_id, environment=command.environment,
                    book_id=str(command.payload.get("book_id") or "")
                )
            )
            _verify_target_identity(command, compilation)
            version = uow.repositories.capability_packs.require_version(
                str(compilation["pack_id"]),
                str(compilation["pack_version"]),
                project_id=command.project_id,
            )
            compiled = dict(compilation["compiled"])
            agent_definitions: dict[str, Mapping[str, Any]] = {}
            for node in compiled.get("workflow_nodes") or ():
                agent_ref = str(node.get("agent_definition_ref") or "")
                if not agent_ref:
                    continue
                agent_id, separator, raw_version = agent_ref.rpartition("@")
                if not separator or not raw_version.isdigit():
                    raise KernelError(
                        "CAPABILITY_PACK_AGENT_DEFINITION_INVALID",
                        f"Agent Definition ref must be exact: {agent_ref}",
                    )
                active = uow.repositories.agent_runtime.resolve_active_definition(
                    agent_id
                )
                if int(active["definition_version"]) != int(raw_version):
                    raise KernelError(
                        "CAPABILITY_PACK_AGENT_DEFINITION_NOT_ACTIVE",
                        f"Agent Definition is not active: {agent_ref}",
                    )
                agent_definitions[agent_ref] = active
        return {
            "compilation": compilation,
            "binding_set": build_binding_set(
                compiled=compiled,
                manifest=dict(version["manifest"]),
                agent_definitions=agent_definitions,
            ),
        }

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        command: CapabilityPackAuthorityCommand,
        prepared: Mapping[str, Any],
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        action = command.definition_name
        repository = uow.repositories.capability_packs
        repository.lock_pack_authority(command.pack_id)
        if action == "capability_pack.manifest.register":
            manifest_payload = command.payload.get("manifest")
            catalog_payload = command.payload.get("artifact_catalog")
            if not isinstance(manifest_payload, Mapping) or not isinstance(
                catalog_payload, Mapping
            ):
                raise KernelError(
                    "CAPABILITY_PACK_REGISTRATION_INPUT_INVALID",
                    "registration requires Manifest and exact Artifact Catalog",
                )
            manifest = load_capability_pack_payload(manifest_payload)
            if str(manifest.identity.pack_id) != command.pack_id:
                raise KernelError(
                    "CAPABILITY_PACK_IDENTITY_CONFLICT",
                    "route Pack identity differs from Manifest",
                )
            normalized_catalog = _normalized_artifact_catalog(catalog_payload)
            result = repository.register_version(
                project_id=command.project_id,
                manifest=manifest.to_dict(),
                manifest_hash=manifest.manifest_hash,
                artifact_catalog=normalized_catalog,
                artifact_catalog_hash=canonical_hash(normalized_catalog),
                release_channel=str(
                    command.payload.get("release_channel")
                    or manifest.governance.release_channel
                ),
                owner_scope_type=str(
                    command.payload.get("owner_scope_type") or "PROJECT"
                ),
                owner_project_id=str(
                    command.payload.get("owner_project_id")
                    or (
                        command.project_id
                        if str(
                            command.payload.get("owner_scope_type") or "PROJECT"
                        ).upper()
                        == "PROJECT"
                        else ""
                    )
                ),
                dependencies=tuple(command.payload.get("dependencies") or ()),
                registered_by=command.actor_id,
                operation_id=operation_id,
                checkpoint=checkpoint,
            )
            checkpoint("after_version_registry")
        elif action == "capability_pack.manifest.validate":
            version = repository.require_version(
                command.pack_id,
                command.pack_version,
                project_id=command.project_id,
                for_update=True,
            )
            _verify_prepared_identity(version, prepared)
            report = dict(prepared["report"])
            result = repository.record_validation(
                pack_id=command.pack_id,
                pack_version=command.pack_version,
                manifest_hash=str(version["manifest_hash"]),
                validator_version=CAPABILITY_PACK_COMPILER_VERSION,
                valid=bool(report["ok"]),
                report=report,
                validated_by=command.actor_id,
                operation_id=operation_id,
            )
        elif action == "capability_pack.compile":
            version = repository.require_version(
                command.pack_id,
                command.pack_version,
                project_id=command.project_id,
                for_update=True,
            )
            _verify_prepared_identity(version, prepared)
            if prepared.get("compiled") is None:
                raise KernelError(
                    "CAPABILITY_PACK_COMPILATION_REJECTED",
                    "trusted compilation failed: "
                    + ", ".join(
                        f"{item.get('code')}@{item.get('path')}:{item.get('message')}"
                        for item in prepared["report"].get("errors") or ()
                    ),
                )
            result = repository.store_compilation(
                project_id=command.project_id,
                compilation_id=command.compilation_id or str(uuid4()),
                compiled=dict(prepared["compiled"]),
                compiler_version=CAPABILITY_PACK_COMPILER_VERSION,
                compiled_by=command.actor_id,
                operation_id=operation_id,
                checkpoint=checkpoint,
            )
            checkpoint("after_compilation_registry")
        elif action == "capability_pack.validation.admit":
            from .validation_admission import record_validation_admission
            result = record_validation_admission(repository, command, operation_id)
        elif action == "capability_pack.approval.decide":
            compilation = repository.require_compilation(
                command.compilation_id, project_id=command.project_id
            )
            _verify_target_identity(command, compilation)
            result = repository.record_approval(
                project_id=command.project_id,
                compilation_id=command.compilation_id,
                compilation_hash=str(command.payload.get("compilation_hash") or ""),
                decision=ApprovalDecision(str(command.payload.get("decision") or "")),
                approval_policy_ref=str(
                    command.payload.get("approval_policy_ref") or ""
                ),
                approval_scope=CapabilityPackApprovalScope.from_payload(
                    dict(command.payload.get("scope") or {})
                ),
                reason=str(command.payload.get("reason") or ""),
                evidence_refs=tuple(command.payload.get("evidence_refs") or ()),
                limitations=normalize_limitations(
                    tuple(command.payload.get("limitations") or ())
                ),
                expires_at=_optional_datetime(command.payload.get("expires_at")),
                decided_by=command.actor_id,
                operation_id=operation_id,
                enforce_duties_separation=bool(
                    command.payload.get("enforce_duties_separation", True)
                ),
            )
            checkpoint("after_approval_decision")
        elif action == "capability_pack.deployment.create":
            compilation = repository.require_admitted_compilation(
                command.compilation_id, project_id=command.project_id, environment=command.environment,
                book_id=str(command.payload.get("book_id") or "")
            )
            _verify_target_identity(command, compilation)
            if (
                compilation["compilation_hash"]
                != prepared["compilation"]["compilation_hash"]
            ):
                raise KernelError(
                    "CAPABILITY_PACK_COMPILATION_DRIFT",
                    "Compilation changed after Binding Set preparation",
                )
            binding = dict(prepared["binding_set"])
            binding_set = repository.store_binding_set(
                binding_set_id=str(command.payload.get("binding_set_id") or uuid4()),
                compilation_id=command.compilation_id,
                binding_set_hash=str(binding["binding_set_hash"]),
                workflow_definition_ref=str(binding["workflow_definition_ref"]),
                node_bindings=tuple(binding["node_bindings"]),
                artifact_bindings=dict(binding["artifact_bindings"]),
                policy_bindings=dict(binding["policy_bindings"]),
                operation_id=operation_id,
            )
            checkpoint("after_binding_set_materialized")
            scope = _scope_from_payload(command.payload)
            result = repository.create_deployment(
                deployment_id=command.deployment_id or str(uuid4()),
                compilation=compilation,
                binding_set=binding_set,
                scope=scope,
                owner_project_id=command.project_id,
                environment=command.environment,
                rollout_policy_ref=str(
                    command.payload.get("rollout_policy_ref") or "rollout:off:v1"
                ),
                operation_id=operation_id,
            )
        elif action in {
            "capability_pack.deployment.activate",
            "capability_pack.rollback",
        }:
            deployment = repository.require_deployment(
                command.deployment_id, project_id=command.project_id
            )
            _verify_target_identity(command, deployment)
            checkpoint("before_activation_cas")
            result = repository.activate_deployment_cas(
                project_id=command.project_id,
                deployment_id=command.deployment_id,
                expected_activation_version=command.expected_activation_version,
                reason=str(command.payload.get("reason") or action),
                activated_by=command.actor_id,
                operation_id=operation_id,
            )
            if action == "capability_pack.rollback":
                repository.mark_rollouts_rolled_back(
                    command.deployment_id, project_id=command.project_id
                )
            checkpoint("after_activation_pointer")
        elif action == "capability_pack.deployment.disable":
            deployment = repository.require_deployment(
                command.deployment_id, project_id=command.project_id
            )
            _verify_target_identity(command, deployment)
            result = repository.disable_deployment(
                command.deployment_id, project_id=command.project_id
            )
        elif action == "capability_pack.rollout.start":
            baseline = repository.require_deployment(
                str(command.payload.get("baseline_deployment_id") or ""),
                project_id=command.project_id,
            )
            candidate = repository.require_deployment(
                str(command.payload.get("candidate_deployment_id") or ""),
                project_id=command.project_id,
            )
            _verify_pack_family(command, baseline)
            _verify_pack_family(command, candidate)
            result = repository.start_rollout(
                project_id=command.project_id,
                rollout_id=command.rollout_id or str(uuid4()),
                baseline_deployment_id=str(
                    command.payload.get("baseline_deployment_id") or ""
                ),
                candidate_deployment_id=str(
                    command.payload.get("candidate_deployment_id") or ""
                ),
                mode=RolloutStatus(str(command.payload.get("mode") or "")),
                percentage=float(command.payload.get("percentage") or 0),
                assignment_key_policy=str(
                    command.payload.get("assignment_key_policy") or "BOOK"
                ),
                operation_id=operation_id,
            )
        elif action in {
            "capability_pack.rollout.pause",
            "capability_pack.rollout.resume",
            "capability_pack.rollout.complete",
        }:
            rollout = repository.require_rollout(
                command.rollout_id, project_id=command.project_id
            )
            baseline = repository.require_deployment(
                str(rollout["baseline_deployment_id"]),
                project_id=command.project_id,
            )
            _verify_target_identity(command, baseline)
            status = {
                "capability_pack.rollout.pause": RolloutStatus.PAUSED,
                "capability_pack.rollout.resume": RolloutStatus(str(rollout["mode"])),
                "capability_pack.rollout.complete": RolloutStatus.COMPLETED,
            }[action]
            if action == "capability_pack.rollout.complete":
                if command.expected_activation_version <= 0:
                    raise KernelError(
                        "CAPABILITY_PACK_ACTIVATION_VERSION_REQUIRED",
                        "rollout completion requires expected_activation_version",
                    )
                result = repository.complete_rollout(
                    command.rollout_id,
                    project_id=command.project_id,
                    expected_activation_version=command.expected_activation_version,
                    reason=str(command.payload.get("reason") or action),
                    activated_by=command.actor_id,
                    operation_id=operation_id,
                )
            else:
                result = repository.update_rollout_status(
                    command.rollout_id, status, project_id=command.project_id
                )
        elif action in {"capability_pack.deprecate", "capability_pack.retire"}:
            repository.require_version(
                command.pack_id,
                command.pack_version,
                project_id=command.project_id,
                for_update=True,
            )
            result = repository.record_deprecation(
                pack_id=command.pack_id,
                pack_version=command.pack_version,
                replacement_pack_ref=str(
                    command.payload.get("replacement_pack_ref") or ""
                ),
                reason=str(command.payload.get("reason") or ""),
                retirement_deadline=_optional_datetime(
                    command.payload.get("retirement_deadline")
                ),
                migration_required=bool(
                    command.payload.get("migration_required", False)
                ),
                migration_policy_ref=str(
                    command.payload.get("migration_policy_ref") or ""
                ),
                retired=action == "capability_pack.retire",
                operation_id=operation_id,
            )
        elif action == "capability_pack.revoke":
            compilation = repository.require_compilation(
                command.compilation_id, project_id=command.project_id
            )
            _verify_target_identity(command, compilation)
            result = repository.record_approval(
                project_id=command.project_id,
                compilation_id=command.compilation_id,
                compilation_hash=str(compilation["compilation_hash"]),
                decision=ApprovalDecision.REVOKED,
                approval_policy_ref=str(
                    command.payload.get("approval_policy_ref")
                    or "security-revocation:v1"
                ),
                approval_scope=CapabilityPackApprovalScope.from_payload(
                    dict(
                        command.payload.get("scope")
                        or repository.require_approved_compilation(
                            command.compilation_id,
                            project_id=command.project_id,
                        )["approval_scope"]
                    )
                ),
                reason=str(command.payload.get("reason") or "security revocation"),
                evidence_refs=tuple(command.payload.get("evidence_refs") or ()),
                limitations=(),
                expires_at=None,
                decided_by=command.actor_id,
                operation_id=operation_id,
                enforce_duties_separation=False,
            )
            repository.mark_compilation_revoked(command.compilation_id)
        else:
            raise KernelError(
                "CAPABILITY_PACK_COMMAND_INVALID",
                f"unsupported Capability Pack action: {action}",
            )
        checkpoint("before_outbox")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_capability_pack",
                "aggregate_id": command.pack_id,
                "operation_id": operation_id,
                "project_id": command.project_id,
                "event_type": f"authority.{action}.committed",
                "correlation_id": command.correlation_id,
                "causation_id": operation_id,
                "payload": {
                    **_json_safe(result),
                    "operation_id": operation_id,
                    "project_id": command.project_id,
                    "trace_id": command.trace_id,
                    "execution_classification": "transaction_command",
                },
            }
        )
        return {**_json_safe(result), "operation_id": operation_id}


def _artifact_resolver(payload: Mapping[str, Any]) -> ExplicitArtifactResolver:
    normalized = _normalized_artifact_catalog(payload)
    artifacts = []
    for raw in normalized["artifacts"]:
        content = raw["content"]
        artifacts.append(
            ResolvedArtifact(
                kind=ArtifactKind(str(raw["kind"])),
                ref=str(raw["ref"]),
                version=str(raw["version"]),
                content_hash=str(raw["content_hash"]),
                content_json=canonical_artifact_json(content),
                source_identity=str(raw["source_identity"]),
            )
        )
    return ExplicitArtifactResolver(artifacts)


def _normalized_artifact_catalog(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "novelos.capability_pack.artifact_catalog.v1":
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_CATALOG_INVALID",
            "Artifact Catalog protocol is unsupported",
        )
    entries = payload.get("artifacts")
    if not isinstance(entries, list):
        raise KernelError(
            "CAPABILITY_PACK_ARTIFACT_CATALOG_INVALID",
            "Artifact Catalog requires an artifacts array",
        )
    normalized = []
    for raw in entries:
        if not isinstance(raw, Mapping) or "content" not in raw or "source_path" in raw:
            raise KernelError(
                "CAPABILITY_PACK_ARTIFACT_CATALOG_INVALID",
                "Authority Artifact Catalog requires inline registered content, never a path",
            )
        source_identity = str(raw.get("source_identity") or "")
        if source_identity.startswith("/"):
            raise KernelError(
                "CAPABILITY_PACK_ARTIFACT_SOURCE_INVALID",
                "absolute local Artifact source paths are forbidden",
            )
        content_hash = artifact_content_hash(raw["content"])
        claimed = str(raw.get("content_hash") or content_hash)
        if claimed != content_hash:
            raise KernelError(
                "CAPABILITY_PACK_ARTIFACT_HASH_DRIFT",
                "registered Artifact content differs from its hash",
            )
        normalized.append(
            {
                "kind": ArtifactKind(str(raw.get("kind") or "")).value,
                "ref": str(raw.get("ref") or ""),
                "version": str(raw.get("version") or ""),
                "content": raw["content"],
                "content_hash": content_hash,
                "source_identity": source_identity
                or f"authority-catalog:{raw.get('ref')}@{raw.get('version')}",
            }
        )
    normalized.sort(key=lambda item: (item["kind"], item["ref"], item["version"]))
    result = {
        "schema_version": "novelos.capability_pack.artifact_catalog.v1",
        "artifacts": normalized,
    }
    _artifact_resolver_without_normalizing(result)
    return result


def _artifact_resolver_without_normalizing(
    payload: Mapping[str, Any],
) -> ExplicitArtifactResolver:
    return ExplicitArtifactResolver(
        ResolvedArtifact(
            kind=ArtifactKind(str(raw["kind"])),
            ref=str(raw["ref"]),
            version=str(raw["version"]),
            content_hash=str(raw["content_hash"]),
            content_json=canonical_artifact_json(raw["content"]),
            source_identity=str(raw["source_identity"]),
        )
        for raw in payload["artifacts"]
    )


def _artifact_hash(artifacts: Sequence[Mapping[str, Any]], ref: str) -> str:
    if not ref:
        raise KernelError(
            "CAPABILITY_PACK_POLICY_BINDING_INCOMPLETE",
            "Binding Set policy reference is missing",
        )
    matches = [
        str(item["content_hash"]) for item in artifacts if str(item["ref"]) == ref
    ]
    if len(set(matches)) != 1:
        raise KernelError(
            "CAPABILITY_PACK_RUNTIME_ARTIFACT_DRIFT",
            f"Compilation has no unique Artifact for {ref}",
        )
    return matches[0]


def _require_artifact_identity(
    artifacts: Sequence[Mapping[str, Any]], ref: str, content_hash: str
) -> None:
    matches = []
    for item in artifacts:
        base = str(item["ref"])
        version = str(item["version"])
        accepted = {base, f"{base}@{version}", f"{base}:{version}"}
        if ref in accepted and str(item["content_hash"]) == content_hash:
            matches.append(item)
    if len(matches) != 1:
        raise KernelError(
            "CAPABILITY_PACK_RUNTIME_ARTIFACT_DRIFT",
            f"runtime Artifact {ref} does not exactly match the Compilation",
        )


def _versioned_ref(ref: str, version: str) -> str:
    if not ref or not version:
        raise KernelError(
            "CAPABILITY_PACK_RUNTIME_ARTIFACT_DRIFT",
            "Pack binding requires an exact Artifact ref and version",
        )
    return f"{ref}@{version}"


def _compilation_report(report: Any) -> dict[str, Any]:
    return {
        "ok": bool(report.ok),
        "pack_id": str(report.pack_id),
        "version": str(report.version),
        "manifest_hash": str(report.manifest_hash),
        "compilation_hash": str(report.compilation_hash),
        "errors": [asdict(item) for item in report.errors],
        "warnings": [asdict(item) for item in report.warnings],
    }


def _verify_prepared_identity(
    version: Mapping[str, Any], prepared: Mapping[str, Any]
) -> None:
    expected = dict(prepared["version_identity"])
    if (
        version["manifest_hash"] != expected["manifest_hash"]
        or version["artifact_catalog_hash"] != expected["artifact_catalog_hash"]
    ):
        raise KernelError(
            "CAPABILITY_PACK_COMPILER_INPUT_DRIFT",
            "Manifest or Artifact Catalog changed during compilation",
        )


def _verify_target_identity(
    command: CapabilityPackAuthorityCommand, target: Mapping[str, Any]
) -> None:
    if (
        str(target.get("pack_id") or "") != command.pack_id
        or str(target.get("pack_version") or "") != command.pack_version
    ):
        raise KernelError(
            "CAPABILITY_PACK_TARGET_IDENTITY_CONFLICT",
            "target object belongs to a different Capability Pack identity",
        )


def _verify_pack_family(
    command: CapabilityPackAuthorityCommand, target: Mapping[str, Any]
) -> None:
    if str(target.get("pack_id") or "") != command.pack_id:
        raise KernelError(
            "CAPABILITY_PACK_TARGET_IDENTITY_CONFLICT",
            "target object belongs to a different Capability Pack family",
        )


def _scope_from_payload(payload: Mapping[str, Any]) -> CapabilityPackScope:
    return CapabilityPackScope(
        ScopeType(str(payload.get("target_scope_type") or "")),
        project_id=str(payload.get("project_id") or ""),
        workspace_id=str(payload.get("workspace_id") or ""),
        book_id=str(payload.get("book_id") or ""),
    )


def _validate_command_scope(
    command: CapabilityPackAuthorityCommand, principal: Principal
) -> None:
    if command.definition_name != "capability_pack.deployment.create":
        return
    scope = _scope_from_payload(command.payload)
    if scope.scope_type is ScopeType.SYSTEM:
        if "*" not in principal.project_scope:
            raise PermissionError(
                "SYSTEM Capability Pack deployment requires global project scope"
            )
        return
    if scope.project_id != command.project_id:
        raise PermissionError(
            "Capability Pack target scope must belong to the authorized project"
        )
    if scope.scope_type in {ScopeType.WORKSPACE, ScopeType.BOOK} and (
        scope.workspace_id != command.workspace_id
    ):
        raise PermissionError(
            "Capability Pack target scope must belong to the authorized workspace"
        )


def _permission_for(action: str) -> str:
    definition = next(
        item
        for item in capability_pack_operation_definitions(
            application_build_id="permission-resolution",
            commit_sha="0" * 40,
        )
        if item["name"] == action
    )
    return str(definition["permissions"][0])


def _optional_datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _json_safe(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, datetime):
            result[key] = item.isoformat()
        elif isinstance(item, Decimal):
            result[key] = str(item)
        elif isinstance(item, Mapping):
            result[key] = _json_safe(item)
        elif isinstance(item, (list, tuple)):
            result[key] = [
                _json_safe(entry) if isinstance(entry, Mapping) else entry
                for entry in item
            ]
        else:
            result[key] = item
    return result


__all__ = [
    "CapabilityPackAuthorityApplication",
    "CapabilityPackAuthorityCommand",
    "build_binding_set",
]
