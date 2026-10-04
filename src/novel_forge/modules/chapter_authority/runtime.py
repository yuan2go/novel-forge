from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from novel_forge.modules.authority_handler_runtime import (
    AuthorityAuxiliaryOutput,
    AuthorityExecutionResult,
    AuthorityHandlerOutput,
    AuthorityHandlerRegistration,
    AuthorityHandlerRequest,
    execute_authority_handler,
)
from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerRegistry,
    ChapterHandlerRequest,
    ChapterInputAsset,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION,
    CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS,
    CHAPTER_LEGACY_AUTHOR_INPUT_DEFINITION_VERSION,
    chapter_definition_version,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.routing_bootstrap import (
    CHAPTER_SAMPLE_DEFINITION_VERSION, chapter_sample_definition_name, chapter_sample_definition_supported, load_bootstrap_authorization,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .definitions import CHAPTER_SAMPLE_COMPLETION_TOPIC, CHAPTER_SAMPLE_OUTPUT_KEY


ChapterExecutionResult = AuthorityExecutionResult


def _handler_definition_version(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    node: ChapterNode,
    registry: ChapterHandlerRegistry,
    author_input: bool,
) -> str:
    expected = (
        CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION
        if author_input and node is ChapterNode.DRAFT
        else chapter_definition_version(registry.model_effects_required)
    )
    if registry.model_effects_required:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute(
                """SELECT operation.definition_version FROM authority_operation operation
                JOIN authority_attempt attempt USING(operation_id) WHERE attempt.attempt_id=%s AND operation.project_id=%s""",
                [command.attempt_id, command.project_id],
            )
            row = uow.cursor.fetchone()
        recoverable = (
            {CHAPTER_AUTHOR_INPUT_DEFINITION_VERSION, CHAPTER_LEGACY_AUTHOR_INPUT_DEFINITION_VERSION}
            if author_input and node is ChapterNode.DRAFT
            else CHAPTER_RECOVERABLE_MODEL_DEFINITION_VERSIONS
        )
        if row is not None and str(row[0]) in recoverable:
            return str(row[0])
    return expected


@dataclass(frozen=True, slots=True)
class _ChapterHandlerAdapter:
    node: ChapterNode
    registry: ChapterHandlerRegistry
    attempt_id: str
    fencing_token: int
    worker_id: str
    database_url: str
    sampling: bool = False

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        stage = "canon_support" if self.node is ChapterNode.CANON_PROPOSAL else self.node.value
        snapshot = None
        if self.sampling:
            with AuthorityUnitOfWork(self.database_url) as uow:
                snapshot = load_bootstrap_authorization(uow.cursor, project_id=request.project_id,
                                                       operation_id=request.operation_id, check_expiry=False)
            if snapshot is None:
                raise KernelError("CHAPTER_SAMPLE_AUTHORIZATION_REQUIRED", "sample materialization requires its frozen authorization")
        chapter_request = ChapterHandlerRequest(
            operation_id=request.operation_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
            command=request.command["payload"] if self.sampling else request.command,
            inputs=tuple(
                ChapterInputAsset(
                    asset_version_id=item.asset_version_id,
                    asset_type=item.asset_type,
                    content_hash=item.content_hash,
                    content=item.content,
                    blobs=item.blobs,
                )
                for item in request.inputs
            ),
            attempt_id=self.attempt_id,
            fencing_token=self.fencing_token,
            worker_id=self.worker_id,
            database_url=self.database_url,
            definition_version=request.definition_version,
        )
        reference = None
        if snapshot is not None and snapshot["authorization"]["purpose"] == "REFERENCE_EVALUATION":
            from novel_forge.modules.chapter_quality_authority.reference_sampling import require_chapter_reference
            from novel_forge.modules.chapter_quality_authority.reference_subject import require_chapter_sample_target

            with AuthorityUnitOfWork(self.database_url) as uow:
                subject = require_chapter_sample_target(uow.cursor, project_id=request.project_id, payload=chapter_request.command) if (
                    chapter_request.command["chapter_sampling"].get("generation_sample") is not None) else None
                reference = require_chapter_reference(uow.cursor, project_id=request.project_id, stage=stage,
                    input_versions=chapter_request.command["input_versions"],
                    binding=chapter_request.command["reference_evaluation"], evaluator_actor_id=request.actor_id,
                    chapter=chapter_request.command["chapter"], generation_sample=subject)
        output = self.registry.require(self.node).execute(chapter_request)
        agreement = None
        if reference is not None:
            from novel_forge.modules.chapter_quality_authority.reference_sampling import (
                chapter_reference_agreement, reference_provider_result,
            )

            with AuthorityUnitOfWork(self.database_url) as uow:
                provider = reference_provider_result(uow.cursor, project_id=request.project_id,
                    operation_id=request.operation_id, attempt_id=self.attempt_id, stage=stage)
            agreement = {**chapter_reference_agreement(reference, stage=stage, result=provider["result"]),
                         **{key: value for key, value in provider.items() if key != "result"}}
        if snapshot is not None:
            grant = snapshot["authorization"]
            return AuthorityHandlerOutput(
                asset_type="chapter_provider_sample", output_key=CHAPTER_SAMPLE_OUTPUT_KEY, role="primary",
                content={
                    "schema_version": "chapter-provider-sample.v1", "routing_eligibility": "BENCHMARK_ONLY",
                    "production_eligible": False, "stage": stage,
                    "source_operation_id": chapter_request.command["chapter_sampling"]["source_operation_id"],
                    "authorization_id": grant["authorization_id"], "campaign": grant["campaign"],
                    "sampled_asset_type": output.asset_type, "sampled_output": output.content,
                    **({"reference_evaluation": agreement} if agreement is not None else {}),
                    "uncommitted_auxiliary_candidates": [
                        {"asset_type": item.asset_type, "output_key": item.output_key, "content": item.content}
                        for item in output.auxiliary_outputs if item.role != "execution_commit_evidence"
                    ],
                },
                qualification_policy="chapter-provider-sample.v1", eligibility="INELIGIBLE",
                reference_asset_version_ids=tuple(item.asset_version_id for item in request.inputs) + (
                    tuple(item["asset_version_id"] for item in reference["binding"]["adjudications"]) if reference is not None else ()
                ),
                evidence={"authority_family": "chapter", "production_eligible": False},
            )
        return AuthorityHandlerOutput(
            asset_type=output.asset_type,
            output_key=output.output_key,
            role=output.role,
            content=output.content,
            qualification_policy=output.qualification_policy,
            reference_asset_version_ids=tuple(
                item.asset_version_id for item in request.inputs
            ),
            evidence={"authority_family": "chapter"},
            auxiliary_outputs=tuple(
                AuthorityAuxiliaryOutput(
                    asset_type=item.asset_type,
                    output_key=item.output_key,
                    role=item.role,
                    content=item.content,
                    qualification_policy=item.qualification_policy,
                    reference_asset_version_ids=(
                        item.reference_asset_version_ids
                        or tuple(input_item.asset_version_id for input_item in request.inputs)
                    ),
                    evidence=item.evidence or {"authority_family": "chapter"},
                )
                for item in output.auxiliary_outputs
            ),
        )


def execute_chapter_handler(
    database_url: str,
    *,
    command: WorkerLeaseCommand,
    node: ChapterNode,
    registry: ChapterHandlerRegistry,
    author_input: bool = False,
    execution_probe: Callable[[], object] | None = None,
    sampling: bool = False,
) -> ChapterExecutionResult:
    stage = "canon_support" if node is ChapterNode.CANON_PROPOSAL else node.value
    sample_version = CHAPTER_SAMPLE_DEFINITION_VERSION
    if sampling:
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT operation.definition_version FROM authority_operation operation
                JOIN authority_attempt attempt USING(operation_id) WHERE attempt.attempt_id=%s AND operation.project_id=%s""",
                [command.attempt_id, command.project_id])
            sample_version = uow.cursor.fetchone()[0]
        if not chapter_sample_definition_supported(chapter_sample_definition_name(stage), sample_version):
            raise KernelError("AUTHORITY_HANDLER_CONTRACT_STALE", "sample definition version is not supported by the runtime codec")
    return execute_authority_handler(
        database_url,
        command=command,
        execution_probe=execution_probe,
        registration=AuthorityHandlerRegistration(
            definition_name=chapter_sample_definition_name(stage) if sampling else node.definition_name,
            definition_version=sample_version if sampling else _handler_definition_version(
                database_url, command=command, node=node, registry=registry,
                author_input=author_input,
            ),
            handler_key="novel_forge.chapter_authority.sample." + stage if sampling else node.handler_key,
            handler_contract_version="chapter-provider-sample.v1" if sampling else "chapter-authority-handler-v2",
            output_asset_type="chapter_provider_sample" if sampling else node.asset_type,
            output_key=CHAPTER_SAMPLE_OUTPUT_KEY if sampling else node.output_key,
            role="primary",
            completion_topic=CHAPTER_SAMPLE_COMPLETION_TOPIC if sampling else node.completion_topic,
            handler=_ChapterHandlerAdapter(
                node,
                registry,
                command.attempt_id,
                command.fencing_token,
                command.worker_id,
                database_url,
                sampling=sampling,
            ),
        ),
    )


__all__ = ["ChapterExecutionResult", "execute_chapter_handler"]
