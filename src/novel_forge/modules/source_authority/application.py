from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.attempt_runtime import (
    WorkerLeaseCommand,
    WorkerResultCommand,
    acquire_attempt_lease,
    create_attempt,
    queue_attempt,
    start_attempt,
    submit_attempt_failure,
    submit_attempt_result,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.source_authority.definitions import (
    SOURCE_AUTHORITY_DEFINITION_VERSION,
    SOURCE_AUTHORITY_HANDLER_KEY,
    SOURCE_AUTHORITY_OPERATION,
    SOURCE_TRANSFORM_DEFINITION_VERSION,
    SOURCE_TRANSFORM_HANDLER_KEY,
    SOURCE_TRANSFORM_OPERATION,
    SOURCE_OBSERVATION_OPERATION,
    SOURCE_REPROCESSING_OPERATION,
    SOURCE_CONTENT_PROFILE_OPERATION,
    SOURCE_ANALYSIS_PLAN_OPERATION,
    source_authority_definitions,
)
from novel_forge.modules.source_authority.deconstruction_application import (
    CommitDeconstructionObservationCommand,
    PlanSourceReprocessingCommand,
    SourceDeconstructionApplication,
)
from novel_forge.modules.source_authority.profiling_application import (
    CommitSourceAnalysisPlanCommand,
    CommitSourceContentProfileCommand,
    SourceProfilingApplication,
)
from novel_forge.modules.source_authority.domain import (
    SourceChunkCandidate,
    decide_source_governance,
    validate_source_chunk_candidates,
)
from novel_forge.modules.source_authority.corpus_application import (
    CORPUS_OPERATION, CorpusCommand, SourceCorpusApplication,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository


@dataclass(frozen=True, slots=True)
class RegisterSourceDocumentCommand:
    project_id: str
    workspace_id: str
    blob_id: str
    title: str
    source_kind: str
    source_uri: str
    rights_authorization: str
    license_name: str
    copyright_boundary: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.workspace_id,
            self.blob_id,
            self.title,
            self.source_kind,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("SourceDocument command is incomplete")


@dataclass(frozen=True, slots=True)
class CommitSourceTransformCommand:
    project_id: str
    workspace_id: str
    source_document_id: str
    normalization_version: str
    chunking_version: str
    chunking_policy_hash: str
    chunks: tuple[SourceChunkCandidate, ...]
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    normalized_blob_id: str = ""
    normalized_content_hash: str = ""
    normalized_byte_size: int = 0

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.workspace_id,
            self.source_document_id,
            self.normalization_version,
            self.chunking_version,
            self.chunking_policy_hash,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required) or not self.chunks:
            raise ValueError("Source transform command is incomplete")
        normalized_values = (
            bool(self.normalized_blob_id),
            bool(self.normalized_content_hash),
            self.normalized_byte_size > 0,
        )
        if any(normalized_values) and not all(normalized_values):
            raise ValueError("normalized Source identity must be complete")


class SourceAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "source-authority-worker",
        allow_fixture_observations: bool = False,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.corpus = SourceCorpusApplication(
            database_url, application_build_id=application_build_id, commit_sha=commit_sha,
        )
        self.deconstruction = SourceDeconstructionApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            allow_fixture_observations=allow_fixture_observations,
        )
        self.profiling = SourceProfilingApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            allow_fixture_profiles=allow_fixture_observations,
        )

    def admit_corpus(self, command: CorpusCommand, *, principal: Principal | None = None) -> dict[str, Any]:
        return self.corpus.admit(command, principal=principal)

    def execute_content_profile(
        self,
        command: CommitSourceContentProfileCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_content_profile(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_content_profile(
        self,
        command: CommitSourceContentProfileCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._register_definition()
        return self.profiling.admit_profile(command, principal=principal)

    def execute_analysis_plan(
        self,
        command: CommitSourceAnalysisPlanCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_analysis_plan(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_analysis_plan(
        self,
        command: CommitSourceAnalysisPlanCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._register_definition()
        return self.profiling.admit_plan(command, principal=principal)

    def execute_observation(
        self,
        command: CommitDeconstructionObservationCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_observation(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_observation(
        self,
        command: CommitDeconstructionObservationCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._register_definition()
        return self.deconstruction.admit_observation(command, principal=principal)

    def execute_reprocessing_plan(
        self,
        command: PlanSourceReprocessingCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_reprocessing_plan(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_reprocessing_plan(
        self,
        command: PlanSourceReprocessingCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        self._register_definition()
        return self.deconstruction.admit_reprocessing_plan(command, principal=principal)

    def execute(
        self,
        command: RegisterSourceDocumentCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit(
        self,
        command: RegisterSourceDocumentCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("source.authority.execute", command.project_id)
            actor_id = principal.principal_id
        decision = decide_source_governance(
            authorization=command.rights_authorization,
            license_name=command.license_name,
            copyright_boundary=command.copyright_boundary,
        )
        blob = self._preflight(command)
        existing = self._existing(command.project_id, str(blob["actual_hash"]))
        if existing is not None:
            if existing["status"] != "SUCCEEDED":
                raise KernelError(
                    "SOURCE_OPERATION_RECOVERY_REQUIRED",
                    "existing SourceDocument generation is not complete; recover its Operation",
                )
            return {
                **existing,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        self._register_definition()
        stable_idempotency_key = (
            f"source.document.register:{command.project_id}:{blob['actual_hash']}"
        )
        payload = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "blob_id": command.blob_id,
            "payload": {
                "title": command.title,
                "source_kind": command.source_kind,
                "source_uri": command.source_uri,
                "rights_authorization": command.rights_authorization.strip().lower(),
                "license_name": command.license_name,
                "copyright_boundary": command.copyright_boundary,
                "client_idempotency_key": command.idempotency_key,
                "governance_status": decision.governance_status,
            },
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_AUTHORITY_OPERATION,
                "definition_version": SOURCE_AUTHORITY_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-document",
                "idempotency_key": stable_idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.blob_id,
                "input": payload,
                "input_assets": [],
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"source.authority.execute"}),
                available_handlers=frozenset({SOURCE_AUTHORITY_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        state = self._operation_state(operation_id, command.project_id)
        if state["status"] == "SUCCEEDED":
            return self._result(operation_id, command.project_id, replayed=True)
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="verified SourceDocument registration ready",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.blob_id,
                ),
            )
            state = self._operation_state(operation_id, command.project_id)
        return {
            "operation_id": operation_id,
            "project_id": command.project_id,
            "status": state["status"],
            "replayed": bool(admitted.get("replayed")),
            "duplicate": False,
        }

    def execute_transform(
        self,
        command: CommitSourceTransformCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        admitted = self.admit_transform(command, principal=principal)
        if admitted["status"] == "SUCCEEDED":
            return admitted
        return self._run(str(admitted["operation_id"]), command.project_id)

    def admit_transform(
        self,
        command: CommitSourceTransformCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("source.authority.execute", command.project_id)
            actor_id = principal.principal_id
        source, chunks, manifest_hash = self._preflight_transform(command)
        with AuthorityUnitOfWork(self.database_url) as uow:
            existing = SourceAuthorityRepository(uow.cursor).existing_transform(
                source_asset_version_id=str(source["asset_version_id"]),
                chunking_policy_hash=command.chunking_policy_hash,
                manifest_hash=manifest_hash,
            )
        if existing is not None:
            if existing["operation_status"] != "SUCCEEDED":
                raise KernelError(
                    "SOURCE_TRANSFORM_RECOVERY_REQUIRED",
                    "existing Source transform is incomplete; recover its Operation",
                )
            return {
                **existing,
                "project_id": command.project_id,
                "status": "SUCCEEDED",
                "replayed": True,
                "duplicate": True,
            }
        self._register_definition()
        payload = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "source_document_id": command.source_document_id,
            "payload": {
                "source_asset_version_id": source["asset_version_id"],
                "source_content_hash": source["source_content_hash"],
                "normalization_version": command.normalization_version,
                "chunking_version": command.chunking_version,
                "chunking_policy_hash": command.chunking_policy_hash,
                "manifest_hash": manifest_hash,
                "chunks": [asdict(chunk) for chunk in chunks],
                "normalized_blob_id": command.normalized_blob_id or None,
                "normalized_content_hash": command.normalized_content_hash or None,
                "normalized_byte_size": command.normalized_byte_size or None,
                "client_idempotency_key": command.idempotency_key,
                "raw_source_text_in_postgresql": False,
                "source_chunks_are_evidence_only": True,
            },
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_TRANSFORM_OPERATION,
                "definition_version": SOURCE_TRANSFORM_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-transform",
                "idempotency_key": (
                    f"source.transform.commit:{command.project_id}:"
                    f"{source['asset_version_id']}:{command.chunking_policy_hash}:"
                    f"{manifest_hash}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": str(source["created_by_operation_id"]),
                "input": payload,
                "input_assets": [
                    {
                        "asset_version_id": source["asset_version_id"],
                        "role": "source_document",
                        "content_hash": source["asset_content_hash"],
                    }
                ],
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"source.authority.execute"}),
                available_handlers=frozenset({SOURCE_TRANSFORM_HANDLER_KEY}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        state = self._operation_state(operation_id, command.project_id)
        if state["status"] == "SUCCEEDED":
            return self.result(operation_id, command.project_id, replayed=True)
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=command.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=actor_id,
                    reason="verified Source transform manifest ready",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=str(source["created_by_operation_id"]),
                ),
            )
            state = self._operation_state(operation_id, command.project_id)
        return {
            "operation_id": operation_id,
            "project_id": command.project_id,
            "status": state["status"],
            "manifest_hash": manifest_hash,
            "replayed": bool(admitted.get("replayed")),
            "duplicate": False,
        }

    def _register_definition(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in source_authority_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _preflight(self, command: RegisterSourceDocumentCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceAuthorityRepository(uow.cursor).require_scope(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
            )
            blob = uow.repositories.asset_blobs.blob_for_update(command.blob_id)
        if blob["project_id"] != command.project_id:
            raise KernelError(
                "CROSS_PROJECT_REFERENCE", "Source Blob belongs to another project"
            )
        if blob["status"] != "AVAILABLE" or not blob["actual_hash"]:
            raise KernelError(
                "SOURCE_BLOB_NOT_VERIFIED",
                "SourceDocument registration requires an AVAILABLE verified Blob",
            )
        if (
            blob["actual_hash"] != blob["expected_hash"]
            or blob["actual_size"] != blob["expected_size"]
            or blob["actual_object_key"] != blob["object_key"]
        ):
            raise KernelError(
                "SOURCE_BLOB_IDENTITY_CONFLICT",
                "Source Blob receipt differs from its frozen reservation",
            )
        return blob

    def _preflight_transform(
        self, command: CommitSourceTransformCommand
    ) -> tuple[dict[str, Any], tuple[SourceChunkCandidate, ...], str]:
        if not _is_sha256(command.chunking_policy_hash):
            raise KernelError(
                "SOURCE_CHUNK_POLICY_HASH_INVALID",
                "Source chunking policy hash must be canonical sha256",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
            )
            source = repository.source_for_transform(
                project_id=command.project_id,
                source_document_id=command.source_document_id,
            )
            if source["workspace_id"] != command.workspace_id:
                raise KernelError(
                    "SOURCE_PROJECT_SCOPE_INVALID",
                    "SourceDocument belongs to another workspace",
                )
            if (
                source["lifecycle"],
                source["eligibility"],
                source["governance"],
                source["governance_status"],
            ) != ("ACTIVE", "ELIGIBLE", "CLEAR", "ELIGIBLE"):
                raise KernelError(
                    "SOURCE_TRANSFORM_GOVERNANCE_BLOCKED",
                    "only an eligible governed SourceDocument can be transformed",
                )
            normalized_size = command.normalized_byte_size or int(source["source_size"])
            chunks = validate_source_chunk_candidates(
                command.chunks, source_size=normalized_size
            )
            blobs = repository.chunk_blobs_for_update(
                tuple(
                    dict.fromkeys(
                        (
                            *(chunk.blob_id for chunk in chunks),
                            *(
                                (command.normalized_blob_id,)
                                if command.normalized_blob_id
                                else ()
                            ),
                        )
                    )
                )
            )
        required_blob_ids = {chunk.blob_id for chunk in chunks}
        if command.normalized_blob_id:
            required_blob_ids.add(command.normalized_blob_id)
        if set(blobs) != required_blob_ids:
            raise KernelError(
                "SOURCE_CHUNK_BLOB_NOT_FOUND",
                "one or more normalized or Source chunk Blobs do not exist",
            )
        if command.normalized_blob_id:
            normalized_blob = blobs[command.normalized_blob_id]
            if (
                normalized_blob["project_id"] != command.project_id
                or normalized_blob["status"] != "AVAILABLE"
                or normalized_blob["actual_hash"] != command.normalized_content_hash
                or normalized_blob["expected_hash"] != command.normalized_content_hash
                or int(normalized_blob["actual_size"] or -1)
                != command.normalized_byte_size
                or int(normalized_blob["expected_size"]) != command.normalized_byte_size
                or normalized_blob["actual_object_key"] != normalized_blob["object_key"]
                or not str(normalized_blob["media_type"]).startswith("text/")
            ):
                raise KernelError(
                    "SOURCE_NORMALIZED_BLOB_IDENTITY_CONFLICT",
                    "normalized Source Blob differs from the frozen transform identity",
                )
        for chunk in chunks:
            blob = blobs[chunk.blob_id]
            if blob["project_id"] != command.project_id:
                raise KernelError(
                    "CROSS_PROJECT_REFERENCE",
                    "Source chunk Blob belongs to another project",
                )
            if (
                blob["status"] != "AVAILABLE"
                or blob["actual_hash"] != chunk.content_hash
                or blob["expected_hash"] != chunk.content_hash
                or int(blob["actual_size"] or -1) != chunk.byte_size
                or int(blob["expected_size"]) != chunk.byte_size
                or blob["actual_object_key"] != blob["object_key"]
                or not str(blob["media_type"]).startswith("text/")
            ):
                raise KernelError(
                    "SOURCE_CHUNK_BLOB_IDENTITY_CONFLICT",
                    "Source chunk Blob receipt differs from the transform manifest",
                )
        manifest_hash = _hash(
            {
                "source_asset_version_id": source["asset_version_id"],
                "source_content_hash": source["source_content_hash"],
                "normalization_version": command.normalization_version,
                "chunking_version": command.chunking_version,
                "chunking_policy_hash": command.chunking_policy_hash,
                "normalized_blob_id": command.normalized_blob_id or None,
                "normalized_content_hash": command.normalized_content_hash or None,
                "normalized_byte_size": command.normalized_byte_size or None,
                "chunks": [asdict(chunk) for chunk in chunks],
            }
        )
        return source, chunks, manifest_hash

    def _existing(
        self, project_id: str, source_content_hash: str
    ) -> dict[str, Any] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return SourceAuthorityRepository(uow.cursor).existing_by_hash(
                project_id=project_id, source_content_hash=source_content_hash
            )

    def _run(self, operation_id: str, project_id: str) -> dict[str, Any]:
        state = self._operation_state(operation_id, project_id)
        if state["status"] not in {"READY", "FAILED_RETRYABLE"}:
            raise KernelError(
                "SOURCE_OPERATION_NOT_RUNNABLE",
                f"Source Operation is not runnable from {state['status']}",
            )
        attempt = create_attempt(
            self.database_url,
            operation_id=operation_id,
            project_id=project_id,
            max_attempts=2,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        if attempt["dead_letter"] or not attempt["attempt_id"]:
            raise KernelError("SOURCE_OPERATION_DEAD_LETTER", "retry policy exhausted")
        attempt_id = str(attempt["attempt_id"])
        queue_attempt(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        lease = acquire_attempt_lease(
            self.database_url,
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            lease_seconds=30,
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
        )
        worker = WorkerLeaseCommand(
            attempt_id=attempt_id,
            project_id=project_id,
            worker_id=self.worker_id,
            fencing_token=int(lease["fencing_token"]),
            trace_id=str(state["trace_id"]),
            correlation_id=str(state["correlation_id"]),
            causation_id=operation_id,
        )
        start_attempt(self.database_url, worker)
        try:
            result = self.execute_fenced(worker)
            current = self._operation_state(operation_id, project_id)
            submit_attempt_result(
                self.database_url,
                WorkerResultCommand(
                    **worker.__dict__,
                    expected_operation_version=int(current["version"]),
                    expected_operation_status=str(current["status"]),
                ),
                outcome="success",
                result=result,
            )
        except Exception as exc:
            try:
                submit_attempt_failure(
                    self.database_url,
                    worker,
                    retryable=False,
                    error_code=(
                        exc.code
                        if isinstance(exc, KernelError)
                        else "SOURCE_HANDLER_FAILED"
                    ),
                    error_message=str(exc),
                    failure_class="SOURCE_GOVERNANCE_FAILURE",
                )
            except KernelError:
                pass
            raise
        return self.result(operation_id, project_id, replayed=False)

    def _execute_document_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            repository = SourceAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=worker.project_id,
                workspace_id=str(command["workspace_id"]),
            )
            blob = uow.repositories.asset_blobs.blob_for_update(str(command["blob_id"]))
            if blob["project_id"] != worker.project_id:
                raise KernelError(
                    "CROSS_PROJECT_REFERENCE", "Source Blob belongs to another project"
                )
            if blob["status"] != "AVAILABLE":
                raise KernelError(
                    "SOURCE_BLOB_NOT_VERIFIED", "Source Blob is no longer AVAILABLE"
                )
            decision = decide_source_governance(
                authorization=str(payload["rights_authorization"]),
                license_name=str(payload.get("license_name") or ""),
                copyright_boundary=str(payload.get("copyright_boundary") or ""),
            )
            source_hash = str(blob["actual_hash"])
            source_document_id = f"source-document:{worker.project_id}:{source_hash.removeprefix('sha256:')}"
            asset_version_id = f"{source_document_id}:v1"
            content = {
                "schema_version": "source-document-authority.v1",
                "source_document_id": source_document_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "title": str(payload["title"]),
                "source_kind": str(payload["source_kind"]),
                "source_uri": str(payload.get("source_uri") or ""),
                "rights": {
                    "authorization": str(payload["rights_authorization"]),
                    "license_name": str(payload.get("license_name") or ""),
                    "copyright_boundary": str(payload.get("copyright_boundary") or ""),
                },
                "object_reference": {
                    "blob_id": blob["blob_id"],
                    "provider": blob["provider"],
                    "object_key": blob["actual_object_key"],
                    "content_hash": source_hash,
                    "size": int(blob["actual_size"]),
                    "media_type": blob["media_type"],
                },
                "source_policy": {
                    "analysis_allowed": decision.analysis_allowed,
                    "raw_source_text_in_postgresql": False,
                    "raw_source_text_in_generation_context": False,
                    "requires_abstraction_before_context": True,
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "blob_receipt_required": True,
                },
            }
            content_hash = _hash(content)
            created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=source_document_id,
                asset_version_id=asset_version_id,
                qualification_id=f"{asset_version_id}:qualification:v1",
                asset_type="source_document",
                output_key="source.document",
                role="primary",
                content=content,
                content_hash=content_hash,
                qualification_policy="source-rights-and-isolation-v1",
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "blob_id": blob["blob_id"],
                    "source_content_hash": source_hash,
                    "rights_authorization": payload["rights_authorization"],
                    "generation_context_allowed": False,
                },
                lifecycle=decision.lifecycle,
                eligibility=decision.eligibility,
                governance=decision.governance,
            )
            if created:
                uow.repositories.asset_blobs.bind_blob(
                    f"source-blob-reference:{asset_version_id}",
                    asset_version_id,
                    str(blob["blob_id"]),
                    "raw_source",
                    0,
                    str(blob["media_type"]),
                    source_hash,
                )
                repository.register(
                    {
                        "source_document_id": source_document_id,
                        "project_id": worker.project_id,
                        "workspace_id": str(command["workspace_id"]),
                        "asset_version_id": asset_version_id,
                        "blob_id": str(blob["blob_id"]),
                        "source_content_hash": source_hash,
                        "source_size": int(blob["actual_size"]),
                        "media_type": str(blob["media_type"]),
                        "title": str(payload["title"]),
                        "source_kind": str(payload["source_kind"]),
                        "source_uri": str(payload.get("source_uri") or ""),
                        "rights_authorization": str(payload["rights_authorization"]),
                        "license_name": str(payload.get("license_name") or ""),
                        "copyright_boundary": str(
                            payload.get("copyright_boundary") or ""
                        ),
                        "governance_status": decision.governance_status,
                        "created_by_operation_id": worker.causation_id,
                    }
                )
                uow.repositories.operation_graph.record_event(
                    {
                        "event_id": str(uuid4()),
                        "audit_id": str(uuid4()),
                        "outbox_id": str(uuid4()),
                        "aggregate_type": "authority_source_document",
                        "aggregate_id": source_document_id,
                        "operation_id": worker.causation_id,
                        "project_id": worker.project_id,
                        "event_type": "authority.source.document.registered",
                        "correlation_id": worker.correlation_id,
                        "causation_id": str(blob["blob_id"]),
                        "payload": {
                            "operation_id": worker.causation_id,
                            "source_document_id": source_document_id,
                            "asset_version_id": asset_version_id,
                            "blob_id": blob["blob_id"],
                            "source_content_hash": source_hash,
                            "governance_status": decision.governance_status,
                            "trace_id": worker.trace_id,
                            "attempt_id": worker.attempt_id,
                            "fencing_token": worker.fencing_token,
                        },
                    }
                )
            uow.commit()
        return {
            "source_document_id": source_document_id,
            "asset_version_id": asset_version_id,
            "content_hash": content_hash,
        }

    def _execute_transform_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = dict(operation["command_payload"])
            payload = dict(command["payload"])
            repository = SourceAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=worker.project_id,
                workspace_id=str(command["workspace_id"]),
            )
            source = repository.source_for_transform(
                project_id=worker.project_id,
                source_document_id=str(command["source_document_id"]),
            )
            if source["asset_version_id"] != payload["source_asset_version_id"]:
                raise KernelError(
                    "SOURCE_TRANSFORM_INPUT_STALE",
                    "SourceDocument version changed after transform admission",
                )
            if (
                source["lifecycle"],
                source["eligibility"],
                source["governance"],
                source["governance_status"],
            ) != ("ACTIVE", "ELIGIBLE", "CLEAR", "ELIGIBLE"):
                raise KernelError(
                    "SOURCE_TRANSFORM_GOVERNANCE_BLOCKED",
                    "SourceDocument is no longer eligible for transformation",
                )
            normalized_size = int(
                payload.get("normalized_byte_size") or source["source_size"]
            )
            chunks = validate_source_chunk_candidates(
                tuple(SourceChunkCandidate(**item) for item in payload["chunks"]),
                source_size=normalized_size,
            )
            blobs = repository.chunk_blobs_for_update(
                tuple(
                    dict.fromkeys(
                        (
                            *(chunk.blob_id for chunk in chunks),
                            *(
                                (str(payload["normalized_blob_id"]),)
                                if payload.get("normalized_blob_id")
                                else ()
                            ),
                        )
                    )
                )
            )
            required_blob_ids = {chunk.blob_id for chunk in chunks}
            if payload.get("normalized_blob_id"):
                required_blob_ids.add(str(payload["normalized_blob_id"]))
            if set(blobs) != required_blob_ids:
                raise KernelError(
                    "SOURCE_CHUNK_BLOB_NOT_FOUND",
                    "one or more Source chunk Blobs disappeared",
                )
            if payload.get("normalized_blob_id"):
                normalized_blob = blobs[str(payload["normalized_blob_id"])]
                if (
                    normalized_blob["project_id"] != worker.project_id
                    or normalized_blob["status"] != "AVAILABLE"
                    or normalized_blob["actual_hash"]
                    != payload["normalized_content_hash"]
                    or normalized_blob["expected_hash"]
                    != payload["normalized_content_hash"]
                    or int(normalized_blob["actual_size"] or -1)
                    != int(payload["normalized_byte_size"])
                    or normalized_blob["actual_object_key"]
                    != normalized_blob["object_key"]
                ):
                    raise KernelError(
                        "SOURCE_NORMALIZED_BLOB_IDENTITY_CONFLICT",
                        "normalized Source Blob no longer matches the transform",
                    )
            for chunk in chunks:
                blob = blobs[chunk.blob_id]
                if (
                    blob["project_id"] != worker.project_id
                    or blob["status"] != "AVAILABLE"
                    or blob["actual_hash"] != chunk.content_hash
                    or blob["expected_hash"] != chunk.content_hash
                    or int(blob["actual_size"] or -1) != chunk.byte_size
                    or int(blob["expected_size"]) != chunk.byte_size
                    or blob["actual_object_key"] != blob["object_key"]
                    or not str(blob["media_type"]).startswith("text/")
                ):
                    raise KernelError(
                        "SOURCE_CHUNK_BLOB_IDENTITY_CONFLICT",
                        "Source chunk Blob no longer matches the transform manifest",
                    )
            expected_manifest_hash = _hash(
                {
                    "source_asset_version_id": source["asset_version_id"],
                    "source_content_hash": source["source_content_hash"],
                    "normalization_version": payload["normalization_version"],
                    "chunking_version": payload["chunking_version"],
                    "chunking_policy_hash": payload["chunking_policy_hash"],
                    "normalized_blob_id": payload.get("normalized_blob_id"),
                    "normalized_content_hash": payload.get("normalized_content_hash"),
                    "normalized_byte_size": payload.get("normalized_byte_size"),
                    "chunks": [asdict(chunk) for chunk in chunks],
                }
            )
            if expected_manifest_hash != payload["manifest_hash"]:
                raise KernelError(
                    "SOURCE_TRANSFORM_MANIFEST_DRIFT",
                    "Source transform manifest changed after admission",
                )
            manifest_digest = expected_manifest_hash.removeprefix("sha256:")
            source_transform_id = (
                f"source-transform:{worker.project_id}:{manifest_digest}"
            )
            transform_asset_version_id = f"{source_transform_id}:v1"
            chunk_rows = []
            for chunk in chunks:
                source_chunk_id = (
                    f"source-chunk:{worker.project_id}:{manifest_digest}:"
                    f"{chunk.chunk_index}"
                )
                chunk_rows.append(
                    {
                        **asdict(chunk),
                        "source_chunk_id": source_chunk_id,
                        "asset_version_id": f"{source_chunk_id}:v1",
                    }
                )
            manifest_content = {
                "schema_version": "source-transform-manifest.v1",
                "source_transform_id": source_transform_id,
                "project_id": worker.project_id,
                "workspace_id": str(command["workspace_id"]),
                "source_document_id": source["source_document_id"],
                "source_asset_version_id": source["asset_version_id"],
                "source_content_hash": source["source_content_hash"],
                "normalization_version": payload["normalization_version"],
                "chunking_version": payload["chunking_version"],
                "chunking_policy_hash": payload["chunking_policy_hash"],
                "normalized_object_reference": (
                    {
                        "blob_id": payload["normalized_blob_id"],
                        "content_hash": payload["normalized_content_hash"],
                        "size": payload["normalized_byte_size"],
                    }
                    if payload.get("normalized_blob_id")
                    else None
                ),
                "manifest_hash": expected_manifest_hash,
                "chunks": chunk_rows,
                "source_policy": {
                    "raw_source_text_in_postgresql": False,
                    "raw_source_text_in_generation_context": False,
                    "source_chunks_are_evidence_only": True,
                    "requires_abstraction_before_context": True,
                },
                "lineage": {
                    "created_by_operation_id": worker.causation_id,
                    "source_asset_version_id": source["asset_version_id"],
                },
            }
            transform_content_hash = _hash(manifest_content)
            created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=source_transform_id,
                asset_version_id=transform_asset_version_id,
                qualification_id=f"{transform_asset_version_id}:qualification:v1",
                asset_type="source_transform_manifest",
                output_key="source.transform.manifest",
                role="primary",
                content=manifest_content,
                content_hash=transform_content_hash,
                qualification_policy="source-transform-manifest-v1",
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "source_asset_version_id": source["asset_version_id"],
                    "manifest_hash": expected_manifest_hash,
                    "raw_source_text_in_postgresql": False,
                },
                lifecycle="ACTIVE",
                eligibility="ELIGIBLE",
                governance="CLEAR",
            )
            if created:
                repository.register_transform(
                    {
                        "source_transform_id": source_transform_id,
                        "project_id": worker.project_id,
                        "workspace_id": str(command["workspace_id"]),
                        "source_document_id": source["source_document_id"],
                        "source_asset_version_id": source["asset_version_id"],
                        "asset_version_id": transform_asset_version_id,
                        "created_by_operation_id": worker.causation_id,
                        "normalization_version": payload["normalization_version"],
                        "chunking_version": payload["chunking_version"],
                        "chunking_policy_hash": payload["chunking_policy_hash"],
                        "manifest_hash": expected_manifest_hash,
                        "chunk_count": len(chunks),
                        "total_chunk_bytes": sum(chunk.byte_size for chunk in chunks),
                        "normalized_blob_id": payload.get("normalized_blob_id"),
                        "normalized_content_hash": payload.get(
                            "normalized_content_hash"
                        ),
                        "normalized_byte_size": payload.get("normalized_byte_size"),
                    }
                )
                if payload.get("normalized_blob_id"):
                    uow.repositories.asset_blobs.bind_blob(
                        f"source-normalized-blob-reference:{transform_asset_version_id}",
                        transform_asset_version_id,
                        str(payload["normalized_blob_id"]),
                        "normalized_source",
                        0,
                        str(blobs[str(payload["normalized_blob_id"])]["media_type"]),
                        str(payload["normalized_content_hash"]),
                    )
                for chunk, row in zip(chunks, chunk_rows, strict=True):
                    blob = blobs[chunk.blob_id]
                    chunk_content = {
                        "schema_version": "source-chunk-evidence.v1",
                        "source_chunk_id": row["source_chunk_id"],
                        "source_transform_id": source_transform_id,
                        "source_document_id": source["source_document_id"],
                        "source_asset_version_id": source["asset_version_id"],
                        "chunk_index": chunk.chunk_index,
                        "content_hash": chunk.content_hash,
                        "byte_size": chunk.byte_size,
                        "character_count": chunk.character_count,
                        "token_count": chunk.token_count,
                        "evidence_span": {
                            "source_byte_start": chunk.source_byte_start,
                            "source_byte_end": chunk.source_byte_end,
                        },
                        "object_reference": {
                            "blob_id": chunk.blob_id,
                            "provider": blob["provider"],
                            "object_key": blob["actual_object_key"],
                            "content_hash": chunk.content_hash,
                            "size": chunk.byte_size,
                            "media_type": blob["media_type"],
                        },
                        "source_policy": {
                            "evidence_layer_only": True,
                            "generation_context_allowed": False,
                            "requires_abstraction_before_context": True,
                        },
                    }
                    chunk_content_hash = _hash(chunk_content)
                    chunk_created = (
                        uow.repositories.chapter_authority.materialize_output(
                            operation_id=worker.causation_id,
                            project_id=worker.project_id,
                            asset_id=str(row["source_chunk_id"]),
                            asset_version_id=str(row["asset_version_id"]),
                            qualification_id=(
                                f"{row['asset_version_id']}:qualification:v1"
                            ),
                            asset_type="source_chunk",
                            output_key=f"source.chunk.{chunk.chunk_index}",
                            role="evidence",
                            content=chunk_content,
                            content_hash=chunk_content_hash,
                            qualification_policy="source-evidence-only-v1",
                            qualification_evidence={
                                "operation_id": worker.causation_id,
                                "attempt_id": worker.attempt_id,
                                "fencing_token": worker.fencing_token,
                                "source_asset_version_id": source["asset_version_id"],
                                "manifest_hash": expected_manifest_hash,
                                "generation_context_allowed": False,
                            },
                            lifecycle="ACTIVE",
                            eligibility="INELIGIBLE",
                            governance="CLEAR",
                        )
                    )
                    if not chunk_created:
                        raise KernelError(
                            "SOURCE_CHUNK_REPLAY_CONFLICT",
                            "new Source transform encountered an existing chunk output",
                        )
                    uow.repositories.asset_blobs.bind_blob(
                        f"source-chunk-blob-reference:{row['asset_version_id']}",
                        str(row["asset_version_id"]),
                        chunk.blob_id,
                        "clean_source_chunk",
                        0,
                        str(blob["media_type"]),
                        chunk.content_hash,
                    )
                    repository.register_chunk(
                        {
                            **row,
                            "project_id": worker.project_id,
                            "workspace_id": str(command["workspace_id"]),
                            "source_transform_id": source_transform_id,
                            "source_document_id": source["source_document_id"],
                            "created_by_operation_id": worker.causation_id,
                        }
                    )
                uow.repositories.operation_graph.record_event(
                    {
                        "event_id": str(uuid4()),
                        "audit_id": str(uuid4()),
                        "outbox_id": str(uuid4()),
                        "aggregate_type": "authority_source_transform",
                        "aggregate_id": source_transform_id,
                        "operation_id": worker.causation_id,
                        "project_id": worker.project_id,
                        "event_type": "authority.source.transform.committed",
                        "correlation_id": worker.correlation_id,
                        "causation_id": str(source["asset_version_id"]),
                        "payload": {
                            "operation_id": worker.causation_id,
                            "source_transform_id": source_transform_id,
                            "asset_version_id": transform_asset_version_id,
                            "source_document_id": source["source_document_id"],
                            "source_asset_version_id": source["asset_version_id"],
                            "manifest_hash": expected_manifest_hash,
                            "chunk_count": len(chunks),
                            "trace_id": worker.trace_id,
                            "attempt_id": worker.attempt_id,
                            "fencing_token": worker.fencing_token,
                        },
                    }
                )
            uow.commit()
        return {
            "source_transform_id": source_transform_id,
            "asset_version_id": transform_asset_version_id,
            "manifest_hash": expected_manifest_hash,
            "chunk_count": len(chunks),
            "content_hash": transform_content_hash,
        }

    def execute_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [worker.causation_id, worker.project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "Source Operation does not exist")
        if row[0] == CORPUS_OPERATION:
            return self.corpus.execute_fenced(worker)
        if row[0] == SOURCE_AUTHORITY_OPERATION:
            return self._execute_document_fenced(worker)
        if row[0] == SOURCE_TRANSFORM_OPERATION:
            return self._execute_transform_fenced(worker)
        if row[0] in {SOURCE_OBSERVATION_OPERATION, SOURCE_REPROCESSING_OPERATION}:
            return self.deconstruction.execute_fenced(worker, str(row[0]))
        if row[0] in {
            SOURCE_CONTENT_PROFILE_OPERATION,
            SOURCE_ANALYSIS_PLAN_OPERATION,
        }:
            return self.profiling.execute_fenced(worker, str(row[0]))
        raise KernelError(
            "SOURCE_HANDLER_NOT_FOUND", f"unsupported Source Operation: {row[0]}"
        )

    def _operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
            uow.cursor.execute(
                """
                SELECT trace_id, correlation_id FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        return {**state, "trace_id": row[0], "correlation_id": row[1]}

    def _result(
        self, operation_id: str, project_id: str, *, replayed: bool
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT source.source_document_id, source.asset_version_id,
                       source.blob_id, source.governance_status, operation.status
                FROM authority_source_document AS source
                JOIN authority_operation AS operation
                  ON operation.operation_id = source.created_by_operation_id
                WHERE source.created_by_operation_id = %s
                  AND source.project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_RESULT_MISSING", "SourceDocument result is missing"
            )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "source_document_id": row[0],
            "asset_version_id": row[1],
            "blob_id": row[2],
            "governance_status": row[3],
            "status": row[4],
            "replayed": replayed,
            "duplicate": False,
        }

    def result(
        self, operation_id: str, project_id: str, *, replayed: bool
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name FROM authority_operation
                WHERE operation_id = %s AND project_id = %s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "Source Operation does not exist")
        if row[0] == SOURCE_AUTHORITY_OPERATION:
            return self._result(operation_id, project_id, replayed=replayed)
        if row[0] == CORPUS_OPERATION:
            return self.corpus.result(operation_id, project_id, replayed=replayed)
        if row[0] in {SOURCE_OBSERVATION_OPERATION, SOURCE_REPROCESSING_OPERATION}:
            return self.deconstruction.result(
                operation_id,
                project_id,
                definition_name=str(row[0]),
                replayed=replayed,
            )
        if row[0] in {
            SOURCE_CONTENT_PROFILE_OPERATION,
            SOURCE_ANALYSIS_PLAN_OPERATION,
        }:
            return self.profiling.result(
                operation_id,
                project_id,
                definition_name=str(row[0]),
                replayed=replayed,
            )
        if row[0] != SOURCE_TRANSFORM_OPERATION:
            raise KernelError(
                "SOURCE_HANDLER_NOT_FOUND", f"unsupported Source Operation: {row[0]}"
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT transform.source_transform_id, transform.asset_version_id,
                       transform.source_document_id, transform.manifest_hash,
                       transform.chunk_count, transform.status, operation.status
                FROM authority_source_transform AS transform
                JOIN authority_operation AS operation
                  ON operation.operation_id = transform.created_by_operation_id
                WHERE transform.created_by_operation_id = %s
                  AND transform.project_id = %s
                """,
                [operation_id, project_id],
            )
            transform = uow.cursor.fetchone()
        if transform is None:
            raise KernelError(
                "SOURCE_TRANSFORM_RESULT_MISSING",
                "Source transform result is missing",
            )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "source_transform_id": transform[0],
            "asset_version_id": transform[1],
            "source_document_id": transform[2],
            "manifest_hash": transform[3],
            "chunk_count": transform[4],
            "transform_status": transform[5],
            "status": transform[6],
            "replayed": replayed,
            "duplicate": False,
        }


def _hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    return (
        separator == ":"
        and prefix == "sha256"
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


__all__ = [
    "CommitSourceTransformCommand",
    "CommitDeconstructionObservationCommand",
    "PlanSourceReprocessingCommand",
    "RegisterSourceDocumentCommand",
    "SourceAuthorityApplication",
]
