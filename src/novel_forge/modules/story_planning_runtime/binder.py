from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5
from novel_forge.modules.capability_pack_authority import CapabilityPackAttemptSnapshot
from novel_forge.modules.capability_pack_authority.runtime import (
    CapabilityPackResolutionRequest,
    CapabilityPackRuntimeResolver,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.domain_execution import (
    CandidateKind,
    DomainExecutionCommand,
    DomainExecutionPort,
    DomainModelOperation,
)
from novel_forge.modules.story_design_authority import GeneratorDefinition
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .domain import (
    FrozenPlanningInput,
    PlanningExecutionEvidence,
    PlanningGenerationCandidate,
    StoryPlanningGenerationCommand,
    canonical_hash,
)


@dataclass(frozen=True, slots=True)
class PlanningCapabilityBinding:

    binding_id: str
    operation_id: str
    attempt_id: str
    fencing_token: int
    project_id: str
    workspace_id: str
    book_id: str
    capability_ref: str
    capability_hash: str
    execution_capability_id: str
    execution_capability_hash: str
    input_manifest_ref: str
    context_bundle_asset_version_id: str
    context_bundle_hash: str
    narrative_intelligence_selection_digest: str
    commit_authority: str
    capability_pack_attempt_snapshot_id: str
    capability_pack_attempt_snapshot_hash: str

    @property
    def binding_hash(self) -> str:
        return canonical_hash(
            {
                name: getattr(self, name)
                for name in self.__dataclass_fields__
                if name != "binding_hash"
            }
        )


@dataclass(frozen=True, slots=True)
class PlanningExecutionBundle:
    attempt_snapshot: CapabilityPackAttemptSnapshot
    capability_binding: PlanningCapabilityBinding
    execution_port: DomainExecutionPort


@dataclass(frozen=True, slots=True)
class PreparedPlanningExecution:

    execution_port: DomainExecutionPort
    context_bundle_asset_version_id: str
    context_bundle_hash: str
    narrative_intelligence_selection_digest: str
    route_snapshot_ref: str
    route_snapshot_hash: str
    input_manifest_ref: str
    input_manifest_hash: str
    prompt_bundle_ref: str
    prompt_bundle_hash: str
    skill_bundle_ref: str
    skill_bundle_hash: str
    tool_permission_snapshot_ref: str
    tool_permission_snapshot_hash: str
    context_policy_ref: str
    context_policy_hash: str
    validation_policy_ref: str
    commit_policy_ref: str
    timeout_policy_ref: str

    def __post_init__(self) -> None:
        references = (
            self.context_bundle_asset_version_id,
            self.narrative_intelligence_selection_digest,
            self.route_snapshot_ref,
            self.input_manifest_ref,
            self.prompt_bundle_ref,
            self.skill_bundle_ref,
            self.tool_permission_snapshot_ref,
            self.context_policy_ref,
            self.validation_policy_ref,
            self.commit_policy_ref,
            self.timeout_policy_ref,
        )
        hashes = (
            self.context_bundle_hash,
            self.narrative_intelligence_selection_digest,
            self.route_snapshot_hash,
            self.input_manifest_hash,
            self.prompt_bundle_hash,
            self.skill_bundle_hash,
            self.tool_permission_snapshot_hash,
            self.context_policy_hash,
        )
        if any(not str(value).strip() for value in references):
            raise ValueError("prepared Planning execution references are incomplete")
        if any(
            not str(value).startswith("sha256:") or len(str(value)) != 71
            for value in hashes
        ):
            raise ValueError("prepared Planning execution hashes must be SHA-256")
        if not getattr(
            self.execution_port, "production_execution_gateway_backed", False
        ) or not getattr(self.execution_port, "external_effect_backed", False):
            raise ValueError(
                "prepared Planning execution must use the ExternalEffect-backed PEP"
            )


class PlanningExecutionPreparer(Protocol):
    def prepare(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
        attempt_snapshot: CapabilityPackAttemptSnapshot,
    ) -> PreparedPlanningExecution: ...


class PlanningExecutionBundleResolver(Protocol):
    def resolve(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningExecutionBundle: ...


class PostgresPlanningExecutionBundleResolver:
    def __init__(
        self,
        database_url: str,
        *,
        execution_preparer: PlanningExecutionPreparer,
        workflow_definition_ref: str,
        pack_id: str,
        environment: str,
        runtime_profile: str,
        release_channel: str,
        release_sha: str,
    ) -> None:
        values = (
            database_url,
            workflow_definition_ref,
            pack_id,
            environment,
            runtime_profile,
            release_channel,
            release_sha,
        )
        if any(not value.strip() for value in values) or len(release_sha) != 40:
            raise ValueError("Planning execution resolver configuration is incomplete")
        self.database_url = database_url
        self.execution_preparer = execution_preparer
        self.workflow_definition_ref = workflow_definition_ref
        self.pack_id = pack_id
        self.environment = environment
        self.runtime_profile = runtime_profile
        self.release_channel = release_channel
        self.release_sha = release_sha
        self.pack_resolver = CapabilityPackRuntimeResolver(database_url)

    def resolve(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
        world_sample: Any = None,
    ) -> PlanningExecutionBundle:
        from novel_forge.modules.production_execution.postgres import (
            PostgresAttemptFenceVerifier,
        )

        PostgresAttemptFenceVerifier(self.database_url).assert_recovery_current(
            operation_id, attempt_id, fencing_token, worker_id
        )
        attempt_snapshot = self.pack_resolver.freeze_attempt_snapshot(
            CapabilityPackResolutionRequest(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
                workflow_definition_ref=(
                    world_sample.workflow_ref if world_sample is not None else
                    "story_planning_generators@1.10.0"
                    if command.execution_contract_version == "1.11.0"
                    and self.workflow_definition_ref.startswith(
                        "story_planning_generators@"
                    )
                    else self.workflow_definition_ref
                ),
                workflow_node_id=world_sample.stage.name if world_sample is not None else command.generator_operation_name,
                environment=self.environment,
                runtime_profile=self.runtime_profile,
                release_channel=self.release_channel,
                release_sha=self.release_sha,
                operation_definition_ref=("world.provider.sample." + world_sample.stage.name.rsplit(".", 1)[1] + "@" + world_sample.definition_version
                                          if world_sample is not None else f"story_planning.generate@{command.execution_contract_version}"),
                pack_id=self.pack_id + world_sample.pack_suffix if world_sample is not None else self.pack_id,
            ),
            operation_id=operation_id,
            attempt_id=attempt_id,
            execution_fencing_token=fencing_token,
            worker_id=worker_id,
        )
        frozen = attempt_snapshot.execution_snapshot
        if command.runtime_continuation_id:
            from .runtime_continuation import require_snapshot
            require_snapshot(self.database_url, command, attempt_snapshot)
        if (
            frozen.execution_capability_id != definition.capability
            or frozen.commit_authority
            not in {
                "STORY_DESIGN_AUTHORITY",
                "HIERARCHICAL_PLANNING_AUTHORITY",
                "PLAN_CHANGE_AUTHORITY",
            }
        ):
            raise KernelError(
                "PLANNING_CAPABILITY_PACK_NODE_INVALID",
                "Capability Pack node cannot submit this Planning Candidate",
            )
        prepare = self.execution_preparer._prepare_stage if world_sample is not None else self.execution_preparer.prepare
        prepared = prepare(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
            command=command,
            inputs=inputs,
            definition=definition,
            attempt_snapshot=attempt_snapshot,
            **({"provider_stage": world_sample.stage, "frozen_world_sample": world_sample} if world_sample is not None else {}),
        )
        CapabilityPackRuntimeResolver.validate_runtime_admission(
            frozen,
            {
                "operation_definition_ref": frozen.operation_definition_ref,
                "operation_definition_hash": frozen.operation_definition_hash,
                "agent_definition_ref": frozen.agent_definition_ref,
                "agent_definition_hash": frozen.agent_definition_hash,
                "capability_ref": frozen.capability_ref,
                "capability_hash": frozen.capability_hash,
                "execution_capability_id": frozen.execution_capability_id,
                "execution_capability_hash": frozen.execution_capability_hash,
                "prompt_bundle_ref": prepared.prompt_bundle_ref,
                "prompt_bundle_hash": prepared.prompt_bundle_hash,
                "skill_bundle_ref": prepared.skill_bundle_ref,
                "skill_bundle_hash": prepared.skill_bundle_hash,
                "tool_policy_ref": frozen.tool_policy_ref,
                "tool_policy_hash": frozen.tool_policy_hash,
                "context_policy_ref": prepared.context_policy_ref,
                "context_policy_hash": prepared.context_policy_hash,
                "evaluation_policy_ref": prepared.validation_policy_ref,
                "evaluation_policy_hash": frozen.evaluation_policy_hash,
                "release_sha": self.release_sha,
            },
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = self._operation(uow, operation_id, command.project_id)
            operation_name, separator, operation_version = (
                frozen.operation_definition_ref.rpartition("@")
            )
            if (
                operation["definition_name"],
                operation["definition_version"],
                operation["definition_hash"],
            ) != (
                operation_name if separator else "",
                operation_version if separator else "",
                frozen.operation_definition_hash,
            ):
                raise KernelError(
                    "PLANNING_OPERATION_BINDING_DRIFT",
                    "Planning Operation differs from the frozen Pack node",
                )
        capability_binding = PlanningCapabilityBinding(
            binding_id=_identity("planning-capability-binding", attempt_id),
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            project_id=command.project_id,
            workspace_id=command.workspace_id,
            book_id=command.book_id,
            capability_ref=frozen.capability_ref,
            capability_hash=frozen.capability_hash,
            execution_capability_id=frozen.execution_capability_id,
            execution_capability_hash=frozen.execution_capability_hash,
            input_manifest_ref=prepared.input_manifest_ref,
            context_bundle_asset_version_id=(prepared.context_bundle_asset_version_id),
            context_bundle_hash=prepared.context_bundle_hash,
            narrative_intelligence_selection_digest=(
                prepared.narrative_intelligence_selection_digest
            ),
            commit_authority=frozen.commit_authority,
            capability_pack_attempt_snapshot_id=attempt_snapshot.snapshot_id,
            capability_pack_attempt_snapshot_hash=attempt_snapshot.snapshot_hash,
        )
        return PlanningExecutionBundle(
            attempt_snapshot,
            capability_binding,
            prepared.execution_port,
        )

    @staticmethod
    def _operation(
        uow: AuthorityUnitOfWork, operation_id: str, project_id: str
    ) -> dict[str, str]:
        uow.cursor.execute(
            """
            SELECT operation.definition_name, operation.definition_version,
                   operation.definition_snapshot, saga.saga_id
            FROM authority_operation AS operation
            JOIN authority_saga AS saga
              ON saga.root_operation_id=operation.root_operation_id
             AND saga.project_id=operation.project_id
            WHERE operation.operation_id=%s AND operation.project_id=%s
            """,
            [operation_id, project_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PLANNING_CAPABILITY_OPERATION_INVALID",
                "Planning Capability binding requires an admitted Saga Operation",
            )
        snapshot = dict(row[2] or {})
        return {
            "operation_id": operation_id,
            "definition_name": str(row[0]),
            "definition_version": str(row[1]),
            "definition_hash": str(snapshot.get("definition_hash") or ""),
            "saga_id": str(row[3]),
        }


class PlanningExecutionBinder(Protocol):
    def execute(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningGenerationCandidate: ...


class CapabilityPackBackedPlanningExecutionBinder:
    production_execution_gateway_backed = True

    def __init__(self, resolver: PlanningExecutionBundleResolver) -> None:
        self.resolver = resolver

    def execute(
        self,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        worker_id: str,
        command: StoryPlanningGenerationCommand,
        inputs: tuple[FrozenPlanningInput, ...],
        definition: GeneratorDefinition,
    ) -> PlanningGenerationCandidate:
        bundle = self.resolver.resolve(
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            worker_id=worker_id,
            command=command,
            inputs=inputs,
            definition=definition,
        )
        self._validate_bundle(
            bundle,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            command=command,
            definition=definition,
        )
        execution = bundle.execution_port.execute(
            DomainExecutionCommand(
                capability=definition.capability,
                operation=DomainModelOperation.GENERATE,
                candidate_kind=CandidateKind.GENERATION,
                # WHY: The actual prompt is the frozen Pack prompt bundle.  The
                # Domain port receives only its immutable reference here.
                prompt=bundle.attempt_snapshot.execution_snapshot.prompt_bundle_ref,
                context={
                    "input_manifest_ref": bundle.capability_binding.input_manifest_ref,
                    "capability_binding_id": bundle.capability_binding.binding_id,
                    "logical_key": command.logical_key,
                    "planning_scope": command.planning_scope.value,
                },
            )
        )
        evidence = execution.evidence
        planning_evidence = PlanningExecutionEvidence(
            operation_id=evidence.operation_id,
            attempt_id=evidence.attempt_id,
            fencing_token=evidence.fencing_token,
            route_snapshot_id=evidence.route_snapshot_id,
            input_manifest_ref=evidence.input_manifest_ref,
            output_manifest_ref=evidence.output_manifest_ref,
            validation_manifest_ref=evidence.validation_manifest_ref,
            usage_receipt_ref=evidence.usage_receipt_ref,
            cost_receipt_ref=evidence.cost_receipt_ref,
            external_receipt_ref=evidence.external_receipt_ref,
            capability_pack_attempt_snapshot_id=(
                bundle.attempt_snapshot.snapshot_id
            ),
            capability_pack_attempt_snapshot_hash=(
                bundle.attempt_snapshot.snapshot_hash
            ),
            capability_execution_ref=bundle.capability_binding.binding_id,
            capability_execution_hash=bundle.capability_binding.binding_hash,
            capability_runtime_binding_ref=(bundle.attempt_snapshot.snapshot_id),
            capability_runtime_binding_hash=(bundle.attempt_snapshot.snapshot_hash),
            commit_authority=bundle.capability_binding.commit_authority,
            fixture_protocol_only=evidence.fixture_protocol_only,
            context_bundle_asset_version_id=(
                getattr(
                    bundle.capability_binding,
                    "context_bundle_asset_version_id",
                    "",
                )
            ),
            context_bundle_hash=getattr(
                bundle.capability_binding, "context_bundle_hash", ""
            ),
            narrative_intelligence_selection_digest=(
                getattr(
                    bundle.capability_binding,
                    "narrative_intelligence_selection_digest",
                    "",
                )
            ),
            real_provider_proven=(
                evidence.real_model_call and not evidence.fixture_protocol_only
            ),
            production_verified=evidence.production_verified,
        )
        from .result_recovery import PlanningResultValidationError, validate_raw_result

        original_provider_result = execution.raw_output
        candidate_payload = execution.raw_output
        try:
            catalog = getattr(bundle.execution_port, "realization_selector_catalog", None)
            if catalog is not None and command.execution_contract_version == "1.21.0":
                from .execution import bind_provider_realization_selectors
                candidate_payload = bind_provider_realization_selectors(original_provider_result, catalog)
            validate_raw_result(
                command.generator_operation_name,
                candidate_payload,
                work_requirements=command.execution_contract_version in {"1.17.0", "1.18.0", "1.19.0", "1.21.0"},
                aligned_methods=command.execution_contract_version in {"1.18.0", "1.19.0", "1.21.0"},
                rfc6901_paths=command.execution_contract_version in {"1.19.0", "1.21.0"},
                narrative_search=bool(command.narrative_search_id) and command.execution_contract_version == "1.21.0",
                compiled_scope="BOOK" if command.generator_operation_name == "world.design.generate" and command.execution_contract_version in {"1.15.0", "1.16.0", "1.17.0", "1.18.0", "1.19.0", "1.21.0"} else None,
            )
        except KernelError as error:
            raise PlanningResultValidationError(error, raw_result=original_provider_result, execution_evidence=planning_evidence.to_dict()) from error
        return PlanningGenerationCandidate(
            generator_operation_name=command.generator_operation_name,
            planning_scope=command.planning_scope,
            logical_key=command.logical_key,
            candidate_payload=dict(candidate_payload),
            raw_provider_result=dict(original_provider_result),
            frozen_inputs=inputs,
            evidence=planning_evidence,
        )

    @staticmethod
    def _validate_bundle(
        bundle: PlanningExecutionBundle,
        *,
        operation_id: str,
        attempt_id: str,
        fencing_token: int,
        command: StoryPlanningGenerationCommand,
        definition: GeneratorDefinition,
    ) -> None:
        snapshot = bundle.attempt_snapshot
        binding = bundle.capability_binding
        if not getattr(
            bundle.execution_port, "production_execution_gateway_backed", False
        ) or not getattr(bundle.execution_port, "external_effect_backed", False):
            raise KernelError(
                "PLANNING_EXECUTION_PLANE_INVALID",
                "Planning execution requires the ExternalEffect-backed PEP port",
            )
        identity = (operation_id, attempt_id, fencing_token)
        if (
            (snapshot.operation_id, snapshot.attempt_id) != (operation_id, attempt_id)
            or not 0 < snapshot.execution_fencing_token <= fencing_token
            or (binding.operation_id, binding.attempt_id, binding.fencing_token)
            != identity
        ):
            raise KernelError(
                "PLANNING_EXECUTION_ATTEMPT_DRIFT",
                "Frozen Pack provenance must belong to this Attempt and the Capability binding must use its verified current fence",
            )
        execution_snapshot = snapshot.execution_snapshot
        if (
            execution_snapshot.execution_capability_id != definition.capability
            or binding.execution_capability_id != definition.capability
        ):
            raise KernelError(
                "PLANNING_EXECUTION_CAPABILITY_DRIFT",
                "Planning execution differs from GeneratorDefinition capability",
            )
        if (
            binding.capability_pack_attempt_snapshot_id != snapshot.snapshot_id
            or binding.capability_pack_attempt_snapshot_hash != snapshot.snapshot_hash
        ):
            raise KernelError(
                "PLANNING_CAPABILITY_PACK_SNAPSHOT_DRIFT",
                "Capability binding must consume the frozen Attempt Pack Snapshot",
            )
        if binding.commit_authority not in {
            "STORY_DESIGN_AUTHORITY",
            "HIERARCHICAL_PLANNING_AUTHORITY",
            "PLAN_CHANGE_AUTHORITY",
        }:
            raise KernelError(
                "PLANNING_COMMIT_AUTHORITY_INVALID",
                "Planning Capability can only submit a Candidate to a planning Authority",
            )
        if (
            binding.project_id != command.project_id
            or binding.book_id != command.book_id
        ):
            raise KernelError(
                "PLANNING_CAPABILITY_SCOPE_DRIFT",
                "Planning Capability binding belongs to another Project or Book",
            )


def _identity(kind: str, source: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"novel-forge:{kind}:{source}"))


__all__ = [
    "CapabilityPackBackedPlanningExecutionBinder",
    "PlanningExecutionPreparer",
    "PlanningExecutionBinder",
    "PlanningExecutionBundle",
    "PlanningCapabilityBinding",
    "PlanningExecutionBundleResolver",
    "PostgresPlanningExecutionBundleResolver",
    "PreparedPlanningExecution",
]
