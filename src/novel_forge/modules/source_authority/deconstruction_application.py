"""Command-Kernel application for governed source Observations and replay plans."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.source_authority.deconstruction import (
    AnalyzerContract,
    ObservationEvidenceSpan,
    ObservationScope,
    ReprocessingTarget,
    stable_hash,
    validate_evidence_spans,
    validate_observation_payload,
)
from novel_forge.modules.source_authority.definitions import (
    SOURCE_OBSERVATION_DEFINITION_VERSION,
    SOURCE_OBSERVATION_HANDLER_KEY,
    SOURCE_OBSERVATION_OPERATION,
    SOURCE_REPROCESSING_DEFINITION_VERSION,
    SOURCE_REPROCESSING_HANDLER_KEY,
    SOURCE_REPROCESSING_OPERATION,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.mkaos_authority_repositories import MkaosAuthorityRepository
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_intelligence_repositories import (
    SourceIntelligenceRepository,
)


@dataclass(frozen=True, slots=True)
class CommitDeconstructionObservationCommand:
    project_id: str
    workspace_id: str
    execution_asset_version_id: str
    scope: ObservationScope
    analyzer: AnalyzerContract
    observation: dict[str, Any]
    evidence_spans: tuple[ObservationEvidenceSpan, ...]
    input_observation_asset_version_ids: tuple[str, ...]
    evidence_class: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.execution_asset_version_id,
            self.evidence_class,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if self.scope.scale not in self.analyzer.recommended_scales:
            raise ValueError("analyzer does not support the Observation scale")
        if self.evidence_class not in {
            "DETERMINISTIC",
            "FIXTURE",
            "PROVIDER_UNCALIBRATED",
            "PROVIDER_QUALIFIED",
        }:
            raise ValueError("unsupported Observation evidence_class")


@dataclass(frozen=True, slots=True)
class PlanSourceReprocessingCommand:
    project_id: str
    workspace_id: str
    targets: tuple[ReprocessingTarget, ...]
    cause_type: str
    source_transform_id: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        _require_strings(
            self.project_id,
            self.workspace_id,
            self.cause_type,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if not self.targets:
            raise ValueError("reprocessing plan requires at least one target")
        if self.cause_type not in {
            "ANALYZER_UPGRADE",
            "SCHEMA_UPGRADE",
            "PROMPT_UPGRADE",
            "SKILL_UPGRADE",
            "POLICY_UPGRADE",
            "UPSTREAM_REPLACED",
        }:
            raise ValueError("unsupported reprocessing cause_type")
        keys = [target.target_key for target in self.targets]
        if len(keys) != len(set(keys)):
            raise ValueError("reprocessing targets must be unique")


class SourceDeconstructionApplication:
    """Persists structured intelligence; it never fetches Source Blob bytes."""

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        allow_fixture_observations: bool = False,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.allow_fixture_observations = allow_fixture_observations

    def admit_observation(
        self,
        command: CommitDeconstructionObservationCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(command.actor_id, principal, command.project_id)
        validated = self._preflight_observation(command)
        existing = validated["existing"]
        if existing is not None:
            if existing["operation_status"] != "SUCCEEDED":
                raise KernelError(
                    "DECONSTRUCTION_OBSERVATION_RECOVERY_REQUIRED",
                    "the matching Observation Operation requires recovery",
                )
            return {
                **existing,
                "project_id": command.project_id,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        payload = self._observation_payload(command, validated)
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_OBSERVATION_OPERATION,
                "definition_version": SOURCE_OBSERVATION_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-observation",
                "idempotency_key": (
                    f"source.observation:{command.project_id}:"
                    f"{payload['payload']['scope_hash']}:"
                    f"{payload['payload']['analyzer']['fingerprint']}:"
                    f"{payload['payload']['observation_hash']}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.execution_asset_version_id,
                "input": payload,
                "input_assets": validated["input_assets"],
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"source.authority.execute"}),
                available_handlers=frozenset({SOURCE_OBSERVATION_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        return self._ready(
            admitted,
            command.project_id,
            actor_id=actor_id,
            reason="governed source Observation ready",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.execution_asset_version_id,
        )

    def admit_reprocessing_plan(
        self,
        command: PlanSourceReprocessingCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = self._actor(command.actor_id, principal, command.project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            source = SourceAuthorityRepository(uow.cursor)
            source.require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            if command.source_transform_id:
                uow.cursor.execute(
                    """
                    SELECT asset_version_id, project_id, workspace_id
                    FROM authority_source_transform
                    WHERE source_transform_id=%s
                    """,
                    [command.source_transform_id],
                )
                transform = uow.cursor.fetchone()
                if transform is None or transform[1:] != (
                    command.project_id,
                    command.workspace_id,
                ):
                    raise KernelError(
                        "SOURCE_REPROCESSING_SCOPE_INVALID",
                        "Source transform belongs to another project/workspace",
                    )
                transform_input = {
                    "asset_version_id": transform[0],
                    "role": "source_transform",
                }
                versions = SourceIntelligenceRepository(uow.cursor).asset_versions(
                    project_id=command.project_id, asset_version_ids=(transform[0],)
                )
                transform_input["content_hash"] = versions[transform[0]]["content_hash"]
            else:
                transform_input = None
        desired = [
            {
                "target_key": target.target_key,
                "scope": target.scope.to_dict(),
                "scope_hash": target.scope.fingerprint,
                "analyzer": target.analyzer.to_dict(),
            }
            for target in sorted(command.targets, key=lambda item: item.target_key)
        ]
        desired_state_hash = stable_hash(desired)
        payload = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "payload": {
                "source_transform_id": command.source_transform_id,
                "cause_type": command.cause_type,
                "desired_state_hash": desired_state_hash,
                "targets": desired,
                "client_idempotency_key": command.idempotency_key,
                "provider_call_allowed": False,
            },
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_REPROCESSING_OPERATION,
                "definition_version": SOURCE_REPROCESSING_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-reprocessing-plan",
                "idempotency_key": (
                    f"source.reprocessing:{command.project_id}:{desired_state_hash}:"
                    f"{command.cause_type}:{command.source_transform_id}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.source_transform_id,
                "input": payload,
                "input_assets": [transform_input] if transform_input else [],
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"source.authority.execute"}),
                available_handlers=frozenset({SOURCE_REPROCESSING_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        return self._ready(
            admitted,
            command.project_id,
            actor_id=actor_id,
            reason="lineage-based selective reprocessing plan ready",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.source_transform_id,
        )

    def execute_fenced(
        self, worker: WorkerLeaseCommand, definition_name: str
    ) -> dict[str, Any]:
        if definition_name == SOURCE_OBSERVATION_OPERATION:
            return self._execute_observation_fenced(worker)
        if definition_name == SOURCE_REPROCESSING_OPERATION:
            return self._execute_plan_fenced(worker)
        raise KernelError(
            "SOURCE_HANDLER_NOT_FOUND",
            f"unsupported deconstruction Operation: {definition_name}",
        )

    def result(
        self,
        operation_id: str,
        project_id: str,
        *,
        definition_name: str,
        replayed: bool,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceIntelligenceRepository(uow.cursor)
            key = (
                "source.deconstruction.observation"
                if definition_name == SOURCE_OBSERVATION_OPERATION
                else "source.reprocessing.plan"
            )
            output = repository.operation_output(
                project_id=project_id, operation_id=operation_id, output_key=key
            )
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
            if output is None:
                raise KernelError(
                    "SOURCE_INTELLIGENCE_RESULT_MISSING",
                    "Source intelligence Operation output is missing",
                )
            content = repository.asset_versions(
                project_id=project_id,
                asset_version_ids=(str(output["asset_version_id"]),),
            )[str(output["asset_version_id"])]["content"]
        identity_key = (
            "observation_id"
            if definition_name == SOURCE_OBSERVATION_OPERATION
            else "reprocessing_plan_id"
        )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            identity_key: content[identity_key],
            "asset_version_id": output["asset_version_id"],
            "content_hash": output["content_hash"],
            **({"items": content["items"]} if "items" in content else {}),
            "status": state["status"],
            "replayed": replayed,
            "duplicate": False,
        }

    def _preflight_observation(
        self, command: CommitDeconstructionObservationCommand
    ) -> dict[str, Any]:
        observation = validate_observation_payload(
            command.observation,
            evidence_spans=command.evidence_spans,
            input_observation_asset_version_ids=(
                command.input_observation_asset_version_ids
            ),
        )
        observation_hash = stable_hash(observation)
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceAuthorityRepository(uow.cursor).require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            execution = MkaosAuthorityRepository(uow.cursor).execution_evidence(
                project_id=command.project_id,
                asset_version_id=command.execution_asset_version_id,
            )
            proof = _execution_proof(
                execution["content"], evidence_class=command.evidence_class
            )
            chunk_ids = tuple(
                sorted(
                    {
                        span.source_chunk_asset_version_id
                        for span in command.evidence_spans
                    }
                )
            )
            repository = SourceIntelligenceRepository(uow.cursor)
            chunks = repository.source_chunks(
                project_id=command.project_id, asset_version_ids=chunk_ids
            )
            lower_ids = tuple(
                sorted(set(command.input_observation_asset_version_ids))
            )
            lower = repository.observations(
                project_id=command.project_id, asset_version_ids=lower_ids
            )
            existing = repository.existing_observation(
                project_id=command.project_id,
                scope_hash=command.scope.fingerprint,
                analyzer_contract_hash=command.analyzer.fingerprint,
                observation_hash=observation_hash,
            )
        self._validate_execution_class(command.evidence_class, proof)
        if len(chunks) != len(chunk_ids) or len(lower) != len(lower_ids):
            raise KernelError(
                "DECONSTRUCTION_LINEAGE_NOT_FOUND",
                "Observation input is absent from the Authority project",
            )
        spans = validate_evidence_spans(
            command.evidence_spans,
            source_chunk_sizes={key: int(value["byte_size"]) for key, value in chunks.items()},
        )
        source_documents = set(command.scope.source_document_ids)
        if chunks and (
            {str(row["source_document_id"]) for row in chunks.values()}
            - source_documents
        ):
            raise KernelError(
                "DECONSTRUCTION_SCOPE_EVIDENCE_CONFLICT",
                "EvidenceSpan SourceDocument is outside the Observation scope",
            )
        for item in lower.values():
            if item["lifecycle"] != "ACTIVE" or item["governance"] != "CLEAR":
                raise KernelError(
                    "DECONSTRUCTION_LOWER_OBSERVATION_INELIGIBLE",
                    "lower-scale Observation is no longer active and governed",
                )
            nested = dict(item["scope"])
            if not set(nested.get("source_document_ids") or []).issubset(
                source_documents
            ):
                raise KernelError(
                    "DECONSTRUCTION_SCOPE_AGGREGATION_CONFLICT",
                    "lower-scale Observation is outside the aggregate scope",
                )
        execution_binding = _execution_binding(
            execution["content"],
            evidence_class=command.evidence_class,
            analyzer_contract_hash=command.analyzer.fingerprint,
            scope_hash=command.scope.fingerprint,
            observation_hash=observation_hash,
            evidence_span_ids=tuple(span.evidence_span_id for span in spans),
            input_observation_asset_version_ids=lower_ids,
        )
        input_assets = [
            {
                "asset_version_id": execution["asset_version_id"],
                "role": "execution_evidence",
                "content_hash": execution["content_hash"],
            },
            *[
                {
                    "asset_version_id": key,
                    "role": "source_chunk_evidence",
                    "content_hash": chunks[key]["asset_content_hash"],
                }
                for key in sorted(chunks)
            ],
            *[
                {
                    "asset_version_id": key,
                    "role": "lower_scale_observation",
                    "content_hash": lower[key]["content_hash"],
                }
                for key in sorted(lower)
            ],
        ]
        return {
            "observation": observation,
            "observation_hash": observation_hash,
            "execution": execution,
            "execution_proof": proof,
            "chunks": chunks,
            "lower": lower,
            "spans": spans,
            "existing": existing,
            "input_assets": input_assets,
            "execution_binding": execution_binding,
        }

    def _observation_payload(
        self, command: CommitDeconstructionObservationCommand, validated: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "payload": {
                "execution_asset_version_id": command.execution_asset_version_id,
                "scope": command.scope.to_dict(),
                "scope_hash": command.scope.fingerprint,
                "analyzer": command.analyzer.to_dict(),
                "observation": validated["observation"],
                "observation_hash": validated["observation_hash"],
                "evidence_spans": [span.to_dict() for span in validated["spans"]],
                "input_observation_asset_version_ids": sorted(validated["lower"]),
                "execution_proof": validated["execution_proof"],
                "execution_binding": validated["execution_binding"],
                "evidence_class": command.evidence_class,
                "client_idempotency_key": command.idempotency_key,
                "raw_source_text_in_postgresql": False,
                "generation_context_allowed": False,
            },
        }

    def _execute_observation_fenced(
        self, worker: WorkerLeaseCommand
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceIntelligenceRepository(uow.cursor)
            replay = repository.operation_output(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                output_key="source.deconstruction.observation",
            )
            if replay is not None:
                return {
                    "observation_id": replay["asset_id"],
                    "asset_version_id": replay["asset_version_id"],
                    "content_hash": replay["content_hash"],
                }
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            analyzer = AnalyzerContract(
                **{
                    key: value
                    for key, value in dict(payload["analyzer"]).items()
                    if key != "fingerprint"
                }
            )
            scope = ObservationScope(**dict(payload["scope"]))
            spans = tuple(
                ObservationEvidenceSpan(
                    source_chunk_asset_version_id=str(
                        item["source_chunk_asset_version_id"]
                    ),
                    chunk_byte_start=int(item["chunk_byte_start"]),
                    chunk_byte_end=int(item["chunk_byte_end"]),
                    evidence_hash=str(item["evidence_hash"]),
                )
                for item in payload["evidence_spans"]
            )
            lower_ids = tuple(payload["input_observation_asset_version_ids"])
            chunks = repository.source_chunks(
                project_id=worker.project_id,
                asset_version_ids=tuple(
                    span.source_chunk_asset_version_id for span in spans
                ),
            )
            lower = repository.observations(
                project_id=worker.project_id, asset_version_ids=lower_ids
            )
            observation = validate_observation_payload(
                dict(payload["observation"]),
                evidence_spans=spans,
                input_observation_asset_version_ids=lower_ids,
            )
            expected_hash = stable_hash(observation)
            if (
                scope.fingerprint != payload["scope_hash"]
                or analyzer.fingerprint != payload["analyzer"]["fingerprint"]
                or expected_hash != payload["observation_hash"]
                or len(chunks) != len({span.source_chunk_asset_version_id for span in spans})
                or len(lower) != len(lower_ids)
            ):
                raise KernelError(
                    "DECONSTRUCTION_INPUT_DRIFT",
                    "Observation inputs changed after admission",
                )
            identity_digest = stable_hash(
                {
                    "scope_hash": scope.fingerprint,
                    "analyzer_id": analyzer.analyzer_id,
                }
            ).removeprefix("sha256:")
            observation_id = (
                f"source-observation:{worker.project_id}:{identity_digest}"
            )
            current = repository.current_observation(
                project_id=worker.project_id,
                scope_hash=scope.fingerprint,
                analyzer_id=analyzer.analyzer_id,
            )
            content = {
                "schema_version": analyzer.schema_version,
                "observation_id": observation_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "scope": scope.to_dict(),
                "dimension": analyzer.dimension,
                "scale": scope.scale,
                "analyzer": analyzer.to_dict(),
                "observation": observation,
                "evidence_spans": [span.to_dict() for span in spans],
                "execution_evidence": {
                    "asset_version_id": payload["execution_asset_version_id"],
                    "proof": payload["execution_proof"],
                    "binding": payload["execution_binding"],
                    "evidence_class": payload["evidence_class"],
                },
                "source_policy": {
                    "raw_source_expression_included": False,
                    "generation_context_allowed": False,
                    "reusable_knowledge": False,
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "source_chunk_asset_version_ids": sorted(chunks),
                    "input_observation_asset_version_ids": sorted(lower),
                    "supersedes_asset_version_id": (
                        current["asset_version_id"] if current else None
                    ),
                },
            }
            created = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=worker.causation_id,
                    project_id=worker.project_id,
                    asset_id=observation_id,
                    asset_type="source_deconstruction_observation",
                    schema_version="source-deconstruction-observation.v1",
                    logical_ref=(
                        f"source-intelligence/observations/{identity_digest}.json"
                    ),
                    category="source-intelligence",
                    output_key="source.deconstruction.observation",
                    role="evidence",
                    content=content,
                    qualification_policy="source-observation-isolation-v1",
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    expected_current_asset_version_id=(
                        str(current["asset_version_id"]) if current else None
                    ),
                    causation_id=str(payload["execution_asset_version_id"]),
                    eligibility="INELIGIBLE",
                    governance="CLEAR",
                )
            )
            repository.register_observation(
                {
                    "observation_id": observation_id,
                    "project_id": worker.project_id,
                    "workspace_id": str(command["workspace_id"]),
                    "asset_version_id": created.asset_version_id,
                    "execution_asset_version_id": payload[
                        "execution_asset_version_id"
                    ],
                    "scope": scope.to_dict(),
                    "scope_hash": scope.fingerprint,
                    "dimension": analyzer.dimension,
                    "scale": scope.scale,
                    "analyzer_id": analyzer.analyzer_id,
                    "analyzer_version": analyzer.analyzer_version,
                    "analyzer_contract_hash": analyzer.fingerprint,
                    "prompt_id": analyzer.prompt_id,
                    "prompt_version": analyzer.prompt_version,
                    "skill_id": analyzer.skill_id,
                    "skill_version": analyzer.skill_version,
                    "capability_id": analyzer.capability_id,
                    "capability_version": analyzer.capability_version,
                    "provider_policy_version": analyzer.provider_policy_version,
                    "aggregation_policy_version": analyzer.aggregation_policy_version,
                    "observation_schema_version": analyzer.schema_version,
                    "observation_hash": expected_hash,
                    "confidence": observation["confidence"],
                    "evidence_class": payload["evidence_class"],
                    "created_by_operation_id": worker.causation_id,
                }
            )
            if current is not None:
                repository.resolve_invalidations(
                    project_id=worker.project_id,
                    target_asset_version_id=str(current["asset_version_id"]),
                    resolved_by_operation_id=worker.causation_id,
                )
            input_ordinal = 0
            for span in spans:
                chunk = chunks[span.source_chunk_asset_version_id]
                repository.register_evidence_span(
                    {
                        "evidence_span_id": span.evidence_span_id,
                        "project_id": worker.project_id,
                        "source_document_id": chunk["source_document_id"],
                        "source_transform_id": chunk["source_transform_id"],
                        "source_chunk_id": chunk["source_chunk_id"],
                        "source_chunk_asset_version_id": span.source_chunk_asset_version_id,
                        "chunk_byte_start": span.chunk_byte_start,
                        "chunk_byte_end": span.chunk_byte_end,
                        "evidence_hash": span.evidence_hash,
                        "created_by_operation_id": worker.causation_id,
                    }
                )
                repository.register_observation_input(
                    {
                        "observation_asset_version_id": created.asset_version_id,
                        "project_id": worker.project_id,
                        "input_asset_version_id": span.source_chunk_asset_version_id,
                        "evidence_span_id": span.evidence_span_id,
                        "role": "SOURCE_CHUNK_EVIDENCE",
                        "ordinal": input_ordinal,
                        "created_by_operation_id": worker.causation_id,
                    }
                )
                self._dependency(
                    repository,
                    worker,
                    upstream=span.source_chunk_asset_version_id,
                    downstream=created.asset_version_id,
                    relationship="EVIDENCES",
                    selector_key=analyzer.dimension,
                )
                input_ordinal += 1
            for ordinal, lower_id in enumerate(sorted(lower)):
                repository.register_observation_input(
                    {
                        "observation_asset_version_id": created.asset_version_id,
                        "project_id": worker.project_id,
                        "input_asset_version_id": lower_id,
                        "evidence_span_id": None,
                        "role": "LOWER_SCALE_OBSERVATION",
                        "ordinal": ordinal,
                        "created_by_operation_id": worker.causation_id,
                    }
                )
                self._dependency(
                    repository,
                    worker,
                    upstream=lower_id,
                    downstream=created.asset_version_id,
                    relationship="AGGREGATES",
                    selector_key=analyzer.dimension,
                )
            repository.register_observation_input(
                {
                    "observation_asset_version_id": created.asset_version_id,
                    "project_id": worker.project_id,
                    "input_asset_version_id": payload[
                        "execution_asset_version_id"
                    ],
                    "evidence_span_id": None,
                    "role": "EXECUTION_EVIDENCE",
                    "ordinal": 0,
                    "created_by_operation_id": worker.causation_id,
                }
            )
            self._event(
                uow,
                worker,
                aggregate_type="authority_source_deconstruction_observation",
                aggregate_id=observation_id,
                event_type="authority.source.deconstruction.observation.committed",
                causation_id=str(payload["execution_asset_version_id"]),
                payload={
                    "observation_id": observation_id,
                    "asset_version_id": created.asset_version_id,
                    "analyzer_contract_hash": analyzer.fingerprint,
                    "observation_hash": expected_hash,
                    "evidence_span_count": len(spans),
                    "input_observation_count": len(lower),
                    "provider_tokens_consumed_by_commit": 0,
                },
            )
            uow.commit()
        return {
            "observation_id": observation_id,
            "asset_version_id": created.asset_version_id,
            "content_hash": created.content_hash,
        }

    def _execute_plan_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceIntelligenceRepository(uow.cursor)
            replay = repository.operation_output(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                output_key="source.reprocessing.plan",
            )
            if replay is not None:
                content = repository.asset_versions(
                    project_id=worker.project_id,
                    asset_version_ids=(str(replay["asset_version_id"]),),
                )[str(replay["asset_version_id"])]["content"]
                return {
                    "reprocessing_plan_id": replay["asset_id"],
                    "asset_version_id": replay["asset_version_id"],
                    "content_hash": replay["content_hash"],
                    "items": content["items"],
                }
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            items: list[dict[str, Any]] = []
            invalidations: dict[str, dict[str, Any]] = {}
            for requested in payload["targets"]:
                current = repository.current_observation(
                    project_id=worker.project_id,
                    scope_hash=str(requested["scope_hash"]),
                    analyzer_id=str(requested["analyzer"]["analyzer_id"]),
                )
                desired_hash = str(requested["analyzer"]["fingerprint"])
                if current is None:
                    action, reason = "RECOMPUTE", "no current Observation"
                elif current["analyzer_contract_hash"] == desired_hash:
                    action, reason = "REUSE", "analyzer contract unchanged"
                else:
                    action = "RECOMPUTE"
                    reason = (
                        "analyzer contract changed from "
                        f"{current['analyzer_contract_hash']}"
                    )
                    invalidations[str(current["asset_version_id"])] = {
                        "dimension": str(requested["analyzer"]["dimension"]),
                        "selector_key": str(requested["target_key"]),
                        "derived_action": "",
                        "scale": str(requested["scope"]["scale"]),
                    }
                    for descendant in repository.descendants(
                        project_id=worker.project_id,
                        upstream_asset_version_id=str(current["asset_version_id"]),
                    ):
                        if descendant["lifecycle"] in {
                            "SUPERSEDED",
                            "RETIRED",
                            "DELETED",
                        }:
                            continue
                        invalidations[str(descendant["asset_version_id"])] = {
                            "dimension": str(requested["analyzer"]["dimension"]),
                            "selector_key": str(requested["target_key"]),
                            "derived_action": _derived_reprocessing_action(
                                str(descendant["asset_type"])
                            ),
                            "scale": str(requested["scope"]["scale"]),
                        }
                items.append(
                    {
                        "target_key": requested["target_key"],
                        "dimension": requested["analyzer"]["dimension"],
                        "scale": requested["scope"]["scale"],
                        "action": action,
                        "current_asset_version_id": (
                            current["asset_version_id"] if current else None
                        ),
                        "desired_analyzer_contract_hash": desired_hash,
                        "reason": reason,
                    }
                )
            for asset_version_id, invalidation in sorted(invalidations.items()):
                if not invalidation["derived_action"]:
                    continue
                items.append(
                    {
                        "target_key": stable_hash(
                            {
                                "projection_asset_version_id": asset_version_id,
                                "selector_key": invalidation["selector_key"],
                            }
                        ),
                        "dimension": invalidation["dimension"],
                        "scale": invalidation["scale"],
                        "action": invalidation["derived_action"],
                        "current_asset_version_id": asset_version_id,
                        "desired_analyzer_contract_hash": stable_hash(
                            {"projection": "rebuild", "cause": payload["cause_type"]}
                        ),
                        "reason": "downstream lineage depends on a stale Observation",
                    }
                )
            plan_hash = stable_hash(items)
            digest = plan_hash.removeprefix("sha256:")
            plan_id = f"source-reprocessing-plan:{worker.project_id}:{digest}"
            content = {
                "schema_version": "source-reprocessing-plan.v1",
                "reprocessing_plan_id": plan_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "source_transform_id": payload["source_transform_id"],
                "cause_type": payload["cause_type"],
                "desired_state_hash": payload["desired_state_hash"],
                "plan_hash": plan_hash,
                "items": items,
                "cost_policy": {
                    "provider_call_allowed": False,
                    "unchanged_observations_reused": sum(
                        item["action"] == "REUSE" for item in items
                    ),
                    "observations_to_recompute": sum(
                        item["action"] == "RECOMPUTE" for item in items
                    ),
                    "projections_to_rebuild": sum(
                        item["action"] == "REBUILD_PROJECTION" for item in items
                    ),
                    "derived_assets_to_reprocess": sum(
                        item["action"]
                        in {"RECOMPUTE_AGGREGATE", "REABSTRACT", "REGOVERN"}
                        for item in items
                    ),
                },
                "lineage": {"created_by_operation_id": worker.causation_id},
            }
            created = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=worker.causation_id,
                    project_id=worker.project_id,
                    asset_id=plan_id,
                    asset_type="source_reprocessing_plan",
                    schema_version="source-reprocessing-plan.v1",
                    logical_ref=f"source-intelligence/reprocessing/{digest}.json",
                    category="source-intelligence",
                    output_key="source.reprocessing.plan",
                    role="operational",
                    content=content,
                    qualification_policy="source-selective-reprocessing-v1",
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                    causation_id=str(payload["source_transform_id"] or ""),
                    eligibility="INELIGIBLE",
                    governance="CLEAR",
                )
            )
            repository.register_plan(
                {
                    "reprocessing_plan_id": plan_id,
                    "project_id": worker.project_id,
                    "workspace_id": str(command["workspace_id"]),
                    "asset_version_id": created.asset_version_id,
                    "source_transform_id": payload["source_transform_id"] or None,
                    "desired_state_hash": payload["desired_state_hash"],
                    "plan_hash": plan_hash,
                    "item_count": len(items),
                    "created_by_operation_id": worker.causation_id,
                }
            )
            for ordinal, item in enumerate(items):
                repository.register_plan_item(
                    {
                        "reprocessing_plan_asset_version_id": created.asset_version_id,
                        "project_id": worker.project_id,
                        "ordinal": ordinal,
                        **item,
                        "created_by_operation_id": worker.causation_id,
                    }
                )
            for asset_version_id, invalidation in invalidations.items():
                repository.record_invalidation(
                    {
                        "invalidation_id": str(uuid4()),
                        "project_id": worker.project_id,
                        "target_asset_version_id": asset_version_id,
                        "cause_type": payload["cause_type"],
                        "cause_ref": created.asset_version_id,
                        "dimension": invalidation["dimension"],
                        "created_by_operation_id": worker.causation_id,
                    }
                )
            self._event(
                uow,
                worker,
                aggregate_type="authority_source_reprocessing_plan",
                aggregate_id=plan_id,
                event_type="authority.source.deconstruction.reprocessing.planned",
                causation_id=str(payload["source_transform_id"] or ""),
                payload={
                    "reprocessing_plan_id": plan_id,
                    "asset_version_id": created.asset_version_id,
                    "plan_hash": plan_hash,
                    "item_count": len(items),
                    "provider_calls": 0,
                },
            )
            uow.commit()
        return {
            "reprocessing_plan_id": plan_id,
            "asset_version_id": created.asset_version_id,
            "content_hash": created.content_hash,
            "items": items,
        }

    def _validate_execution_class(
        self, evidence_class: str, proof: dict[str, bool]
    ) -> None:
        deterministic = proof.get("deterministic_execution", False)
        if evidence_class == "DETERMINISTIC":
            if not deterministic:
                raise KernelError(
                    "DECONSTRUCTION_DETERMINISTIC_PROOF_REQUIRED",
                    "deterministic Observation requires zero-usage execution evidence",
                )
            return
        if deterministic:
            raise KernelError(
                "DECONSTRUCTION_EVIDENCE_CLASS_CONFLICT",
                "deterministic execution cannot be labeled as provider evidence",
            )
        if proof["fixture_protocol_only"]:
            if evidence_class != "FIXTURE" or not self.allow_fixture_observations:
                raise KernelError(
                    "DECONSTRUCTION_FIXTURE_EVIDENCE_BLOCKED",
                    "fixture analysis is disabled outside an explicit test profile",
                )
            return
        if evidence_class == "FIXTURE":
            raise KernelError(
                "DECONSTRUCTION_EVIDENCE_CLASS_CONFLICT",
                "non-fixture execution cannot be labeled FIXTURE",
            )
        if evidence_class == "PROVIDER_QUALIFIED" and not (
            proof["real_provider_proven"] and proof["production_verified"]
        ):
            raise KernelError(
                "DECONSTRUCTION_PROVIDER_NOT_QUALIFIED",
                "qualified provider Observation requires production-verified proof",
            )

    def _ready(
        self,
        admitted: dict[str, Any],
        project_id: str,
        *,
        actor_id: str,
        reason: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
    ) -> dict[str, Any]:
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        if state["status"] == "SUCCEEDED":
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    "SELECT definition_name FROM authority_operation WHERE operation_id=%s",
                    [operation_id],
                )
                definition_name = str(uow.cursor.fetchone()[0])
            return self.result(
                operation_id,
                project_id,
                definition_name=definition_name,
                replayed=True,
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason=reason,
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                ),
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                state = uow.repositories.attempt_runtime.operation_state(
                    operation_id, project_id
                )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "status": state["status"],
            "replayed": bool(admitted.get("replayed")),
            "duplicate": False,
        }

    @staticmethod
    def _actor(
        actor_id: str, principal: Principal | None, project_id: str
    ) -> str:
        if principal is None:
            return actor_id
        principal.require("source.authority.execute", project_id)
        return principal.principal_id

    @staticmethod
    def _dependency(
        repository: SourceIntelligenceRepository,
        worker: WorkerLeaseCommand,
        *,
        upstream: str,
        downstream: str,
        relationship: str,
        selector_key: str,
    ) -> None:
        repository.record_dependency(
            {
                "dependency_id": str(uuid4()),
                "project_id": worker.project_id,
                "upstream_asset_version_id": upstream,
                "downstream_asset_version_id": downstream,
                "relationship": relationship,
                "selector_key": selector_key,
                "created_by_operation_id": worker.causation_id,
            }
        )

    @staticmethod
    def _event(
        uow: AuthorityUnitOfWork,
        worker: WorkerLeaseCommand,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        causation_id: str,
        payload: dict[str, Any],
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "operation_id": worker.causation_id,
                "project_id": worker.project_id,
                "event_type": event_type,
                "correlation_id": worker.correlation_id,
                "causation_id": causation_id,
                "payload": {
                    **payload,
                    "operation_id": worker.causation_id,
                    "trace_id": worker.trace_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                },
            }
        )


def _require_strings(*values: str) -> None:
    if any(not str(value).strip() for value in values):
        raise ValueError("Source intelligence command strings must not be empty")


def _derived_reprocessing_action(asset_type: str) -> str:
    if asset_type == "source_deconstruction_observation":
        return "RECOMPUTE_AGGREGATE"
    if asset_type == "knowledge_card_candidate":
        return "REABSTRACT"
    if asset_type in {"knowledge_governance_decision", "knowledge_card"}:
        return "REGOVERN"
    return "REBUILD_PROJECTION"


def _execution_binding(
    content: Any,
    *,
    evidence_class: str,
    analyzer_contract_hash: str,
    scope_hash: str,
    observation_hash: str,
    evidence_span_ids: tuple[str, ...],
    input_observation_asset_version_ids: tuple[str, ...],
) -> dict[str, Any]:
    expected = {
        "schema_version": "source-deconstruction-execution-binding.v1",
        "analyzer_contract_hash": analyzer_contract_hash,
        "scope_hash": scope_hash,
        "observation_hash": observation_hash,
        "evidence_span_ids": sorted(set(evidence_span_ids)),
        "input_observation_asset_version_ids": sorted(
            set(input_observation_asset_version_ids)
        ),
    }
    binding = content.get("source_deconstruction_binding") if isinstance(content, dict) else None
    if binding is None and evidence_class == "FIXTURE":
        return {
            "schema_version": expected["schema_version"],
            "validation_status": "FIXTURE_PROTOCOL_UNBOUND",
        }
    if not isinstance(binding, dict) or any(
        binding.get(key) != value for key, value in expected.items()
    ):
        raise KernelError(
            "DECONSTRUCTION_EXECUTION_OUTPUT_UNBOUND",
            "execution evidence is not bound to this Observation contract, inputs and output",
        )
    return {**expected, "validation_status": "VERIFIED"}


def _execution_proof(
    content: Any, *, evidence_class: str = "PROVIDER_UNCALIBRATED"
) -> dict[str, bool]:
    if not isinstance(content, dict):
        raise KernelError(
            "DECONSTRUCTION_EXECUTION_EVIDENCE_INVALID",
            "execution evidence content must be an object",
        )
    if evidence_class == "DETERMINISTIC":
        usage = content.get("usage")
        cost = content.get("cost")
        if not isinstance(usage, dict) or not isinstance(cost, dict):
            raise KernelError(
                "DECONSTRUCTION_DETERMINISTIC_EVIDENCE_INVALID",
                "deterministic execution requires explicit zero usage and cost",
            )
        try:
            token_values = (
                int(usage.get("input_tokens") or 0),
                int(usage.get("output_tokens") or 0),
                int(usage.get("total_tokens") or 0),
            )
            amount = float(cost.get("amount_usd") or 0)
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "DECONSTRUCTION_DETERMINISTIC_EVIDENCE_INVALID",
                "deterministic execution cost must be numeric",
            ) from exc
        if (
            content.get("deterministic_execution") is not True
            or content.get("model_call_performed") is not False
            or any(token_values)
            or amount != 0
        ):
            raise KernelError(
                "DECONSTRUCTION_DETERMINISTIC_EVIDENCE_INVALID",
                "deterministic execution must prove that no provider tokens were consumed",
            )
        return {
            "production_execution_gateway_backed": False,
            "deterministic_execution": True,
            "fixture_protocol_only": False,
            "real_provider_proven": False,
            "production_verified": False,
        }
    gateway_backed = bool(
        content.get("production_execution_gateway_backed")
        or content.get("gateway") == "ProductionExecutionGateway"
    )
    if not gateway_backed:
        raise KernelError(
            "DECONSTRUCTION_EXECUTION_GATEWAY_REQUIRED",
            "model analysis evidence must come through ProductionExecutionGateway",
        )
    fixture = bool(content.get("fixture_protocol_only"))
    real_provider = bool(content.get("real_provider_proven"))
    production_verified = bool(content.get("production_verified"))
    if fixture and production_verified:
        raise KernelError(
            "DECONSTRUCTION_EXECUTION_PROOF_CONFLICT",
            "fixture execution cannot claim production verification",
        )
    if production_verified and not real_provider:
        raise KernelError(
            "DECONSTRUCTION_EXECUTION_PROOF_CONFLICT",
            "production verification requires real-provider proof",
        )
    return {
        "production_execution_gateway_backed": True,
        "deterministic_execution": False,
        "fixture_protocol_only": fixture,
        "real_provider_proven": real_provider,
        "production_verified": production_verified,
    }


__all__ = [
    "CommitDeconstructionObservationCommand",
    "PlanSourceReprocessingCommand",
    "SourceDeconstructionApplication",
]
