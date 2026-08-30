from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.asset_runtime import (
    AssetCommandContext,
    request_blob_upload,
    reserve_blob,
    verify_blob,
)
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext,
    classify_external_effect_recovery,
    dispatch_external_effect,
    plan_external_effect,
    reconcile_external_effect,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.mkaos_authority import (
    CommitKnowledgeCandidateCommand,
    MkaosAuthorityApplication,
)
from novel_forge.modules.mkaos_authority.domain import KnowledgeEvidenceSpan
from novel_forge.modules.source_authority import (
    CommitDeconstructionObservationCommand,
    CommitSourceAnalysisPlanCommand,
    CommitSourceContentProfileCommand,
    CommitSourceTransformCommand,
    RegisterSourceDocumentCommand,
    SourceAuthorityApplication,
)
from novel_forge.modules.source_authority.deconstruction import (
    AnalyzerContract,
    ObservationEvidenceSpan,
    ObservationScope,
)
from novel_forge.modules.source_authority.domain import (
    SourceChunkCandidate,
    decide_source_governance,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_import_repositories import SourceImportRepository
from novel_forge.storage.source_intelligence_repositories import (
    SourceIntelligenceRepository,
)
from novel_forge.storage.source_profile_repositories import SourceProfileRepository

from .analysis_profiles import (
    analysis_strategy_from_dict,
    plan_analysis_tasks,
    resolve_analysis_strategy,
)
from .definitions import (
    SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
    SOURCE_IMPORT_PROFILING_OPERATION,
    SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION,
    SOURCE_IMPORT_DEFINITION_VERSION,
    SOURCE_IMPORT_DISCOVERY_OPERATION,
    SOURCE_IMPORT_FILE_OPERATION,
    SOURCE_IMPORT_MKAOS_OPERATION,
    SOURCE_IMPORT_REPROCESSING_OPERATION,
    source_import_definitions,
)
from .domain import (
    ManifestDiffEntry,
    RepositoryFile,
    SourceImportPolicy,
    diff_repository_manifests,
    normalize_repository_url,
    normalize_source_bytes,
    chunk_normalized_text,
)
from .methodologies import SourceMethodologyRegistry
from .profiling import (
    LogicalDocumentScope,
    SourceAnalysisOverride,
    SourceContentType,
    SourceIntelligencePolicy,
    build_classification_evidence,
    resolve_profile,
)
from .object_store_adapter import SourceImportObjectStoreAdapter


class ContentIntelligenceExecutionPort(Protocol):
    external_effect_backed: bool
    production_execution_gateway_backed: bool

    def execute_classification(
        self,
        *,
        worker: WorkerLeaseCommand,
        logical_document_scope_hash: str,
        classifier_contract: dict[str, Any],
        classification_evidence: dict[str, Any],
        source_segments: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]: ...

    def execute_deconstruction(
        self,
        *,
        worker: WorkerLeaseCommand,
        analyzer: AnalyzerContract,
        scope: ObservationScope,
        evidence_spans: tuple[ObservationEvidenceSpan, ...],
        source_segments: tuple[dict[str, Any], ...],
        input_observations: tuple[dict[str, Any], ...] = (),
        analysis_plan_asset_version_id: str = "",
    ) -> dict[str, Any]: ...

    def execute_mkaos_extraction(
        self,
        *,
        worker: WorkerLeaseCommand,
        capability: str,
        abstraction_policy_version: str,
        observation_asset_version_id: str,
        observation: dict[str, Any],
        evidence_spans: tuple[KnowledgeEvidenceSpan, ...],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CreateSourceImportCommand:
    project_id: str
    workspace_id: str
    source_type: str
    repository_url: str
    requested_ref: str
    policy: SourceImportPolicy
    intelligence_policy: SourceIntelligencePolicy
    analysis_override: SourceAnalysisOverride | None
    mode: str
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
            self.source_type,
            self.repository_url,
            self.requested_ref,
            self.mode,
            self.rights_authorization,
            self.actor_id,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if any(not value.strip() for value in required):
            raise ValueError("Source import command is incomplete")
        if self.source_type != "github_repository":
            raise ValueError(
                "only github_repository is production-enabled in this release"
            )
        if self.mode not in {"PREVIEW", "IMPORT"}:
            raise ValueError("Source import mode must be PREVIEW or IMPORT")
        decide_source_governance(
            authorization=self.rights_authorization,
            license_name=self.license_name,
            copyright_boundary=self.copyright_boundary,
        )


@dataclass(frozen=True, slots=True)
class ApplyReprocessingPlanCommand:
    project_id: str
    workspace_id: str
    reprocessing_plan_asset_version_id: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.project_id,
                self.workspace_id,
                self.reprocessing_plan_asset_version_id,
                self.actor_id,
                self.idempotency_key,
                self.trace_id,
                self.correlation_id,
            )
        ):
            raise ValueError("reprocessing execution command is incomplete")


class SourceImportApplication:

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "source-import-worker",
        git_adapter: Any | None = None,
        object_store_adapter: Any | None = None,
        object_store_reader: Any | None = None,
        execution_port: ContentIntelligenceExecutionPort | None = None,
        methodology_registry: SourceMethodologyRegistry | None = None,
        allow_fixture_intelligence: bool = False,
        allow_file_repositories: bool = False,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        if execution_port is not None and not (
            bool(getattr(execution_port, "external_effect_backed", False))
            and bool(
                getattr(execution_port, "production_execution_gateway_backed", False)
            )
        ):
            raise ValueError(
                "content intelligence execution must use ExternalEffect and PEP"
            )
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.git_adapter = git_adapter
        self.object_store_adapter = object_store_adapter
        self.object_store_reader = object_store_reader
        self.execution_port = execution_port
        self.methodology_registry = methodology_registry or SourceMethodologyRegistry(
            Path(__file__).resolve().parents[4] / "skills"
        )
        self.allow_file_repositories = allow_file_repositories
        self.source_authority = SourceAuthorityApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id=f"{worker_id}:source-authority",
            allow_fixture_observations=allow_fixture_intelligence,
        )
        self.mkaos_authority = MkaosAuthorityApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id=f"{worker_id}:mkaos-authority",
            allow_fixture_activation=allow_fixture_intelligence,
        )

    def create_import(
        self,
        command: CreateSourceImportCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("source.authority.execute", command.project_id)
            actor_id = principal.principal_id
        repository_url = normalize_repository_url(
            command.repository_url,
            allow_file=self.allow_file_repositories,
        )
        self._register_definitions()
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceImportRepository(uow.cursor).require_scope(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
            )
        payload = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "payload": {
                "source_type": command.source_type,
                "repository_url": repository_url,
                "requested_ref": command.requested_ref,
                "policy": asdict(command.policy),
                "import_policy_hash": command.policy.policy_hash,
                "intelligence_policy": asdict(command.intelligence_policy),
                "intelligence_policy_hash": (command.intelligence_policy.policy_hash),
                "analysis_override": (
                    command.analysis_override.to_dict()
                    if command.analysis_override is not None
                    else {}
                ),
                "mode": command.mode,
                "rights_authorization": command.rights_authorization,
                "license_name": command.license_name,
                "copyright_boundary": command.copyright_boundary,
            },
        }
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_IMPORT_DISCOVERY_OPERATION,
                "definition_version": SOURCE_IMPORT_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-import",
                "idempotency_key": (
                    f"source.import.request:{command.project_id}:"
                    f"{command.idempotency_key}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.requested_ref,
                "input": payload,
                "input_assets": [],
            },
            context=self._admission_context(actor_id),
        )
        operation_id = str(admitted["operation_id"])
        import_job_id = f"source-import:{operation_id}"
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            created = repository.register_job(
                {
                    "import_job_id": import_job_id,
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "source_type": command.source_type,
                    "source_locator": {
                        "repository_url": repository_url,
                        "rights_authorization": command.rights_authorization,
                        "license_name": command.license_name,
                        "copyright_boundary": command.copyright_boundary,
                    },
                    "requested_ref": command.requested_ref,
                    "import_policy": asdict(command.policy),
                    "import_policy_hash": command.policy.policy_hash,
                    "intelligence_policy": asdict(command.intelligence_policy),
                    "intelligence_policy_hash": (
                        command.intelligence_policy.policy_hash
                    ),
                    "analysis_override": (
                        command.analysis_override.to_dict()
                        if command.analysis_override is not None
                        else {}
                    ),
                    "mode": command.mode,
                    "status": "ADMITTED",
                    "discovery_operation_id": operation_id,
                    "counters": {},
                    "failure": {},
                }
            )
            if created:
                repository.register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": import_job_id,
                        "project_id": command.project_id,
                        "work_kind": "DISCOVERY",
                        "stable_key": "repository-discovery",
                        "source_path": "",
                        "target_asset_version_id": None,
                        "operation_id": operation_id,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
            uow.commit()
        state = self._operation_state(operation_id, command.project_id)
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
                    reason="governed Source repository discovery ready",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.requested_ref,
                ),
            )
        return {
            "import_job_id": import_job_id,
            "operation_id": operation_id,
            "project_id": command.project_id,
            "status": self._operation_state(operation_id, command.project_id)["status"],
            "replayed": bool(admitted.get("replayed")),
            "mode": command.mode,
        }

    def apply_reprocessing_plan(
        self,
        command: ApplyReprocessingPlanCommand,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("source.authority.execute", command.project_id)
            actor_id = principal.principal_id
        self._register_definitions()
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT plan.workspace_id, plan.status, version.content_hash
                FROM authority_source_reprocessing_plan AS plan
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=plan.asset_version_id
                WHERE plan.project_id=%s AND plan.asset_version_id=%s
                """,
                [command.project_id, command.reprocessing_plan_asset_version_id],
            )
            plan = uow.cursor.fetchone()
        if plan is None or str(plan[0]) != command.workspace_id:
            raise KernelError(
                "SOURCE_REPROCESSING_SCOPE_INVALID",
                "reprocessing plan is outside the project/workspace",
            )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": SOURCE_IMPORT_REPROCESSING_OPERATION,
                "definition_version": SOURCE_IMPORT_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-import",
                "idempotency_key": (
                    f"source.reprocessing.apply:{command.project_id}:"
                    f"{command.reprocessing_plan_asset_version_id}:"
                    f"{command.idempotency_key}"
                ),
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.reprocessing_plan_asset_version_id,
                "input": {
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "payload": {
                        "reprocessing_plan_asset_version_id": (
                            command.reprocessing_plan_asset_version_id
                        )
                    },
                },
                "input_assets": [
                    {
                        "asset_version_id": command.reprocessing_plan_asset_version_id,
                        "role": "reprocessing_plan",
                        "content_hash": str(plan[2]),
                    }
                ],
            },
            context=self._admission_context(actor_id),
        )
        self._ready_child(
            operation_id=str(admitted["operation_id"]),
            project_id=command.project_id,
            actor_id=actor_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=command.reprocessing_plan_asset_version_id,
            reason="selective reprocessing execution ready",
        )
        return {
            "operation_id": str(admitted["operation_id"]),
            "project_id": command.project_id,
            "status": self._operation_state(
                str(admitted["operation_id"]), command.project_id
            )["status"],
            "replayed": bool(admitted.get("replayed")),
        }

    def resume_import(
        self,
        *,
        project_id: str,
        import_job_id: str,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        if principal is not None:
            principal.require("source.authority.execute", project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            job = repository.job_for_update(
                project_id=project_id, import_job_id=import_job_id
            )
            work = repository.list_work(
                project_id=project_id, import_job_id=import_job_id
            )
            operation_ids = [str(item["operation_id"]) for item in work]
            uow.cursor.execute(
                """
                SELECT operation_id, status
                FROM authority_operation
                WHERE project_id=%s AND operation_id=ANY(%s)
                """,
                [project_id, operation_ids],
            )
            states = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
            terminal = [
                operation_id
                for operation_id, status in states.items()
                if status in {"FAILED_FINAL", "DEAD_LETTER", "CANCELLED"}
            ]
            resumable = [
                operation_id
                for operation_id, status in states.items()
                if status in {"READY", "FAILED_RETRYABLE", "EXECUTING"}
            ]
            if terminal:
                raise KernelError(
                    "SOURCE_IMPORT_RETRY_REQUIRES_NEW_JOB",
                    "terminal Source import work cannot be mutated; create a new import "
                    "request so completed assets are reused",
                )
            if resumable and job["status"] in {
                "FAILED_RETRYABLE",
                "PARTIALLY_COMPLETED",
                "PROCESSING",
            }:
                repository.transition_job(
                    project_id=project_id,
                    import_job_id=import_job_id,
                    expected=(str(job["status"]),),
                    target="PROCESSING",
                    failure={},
                )
            uow.commit()
        return {
            "import_job_id": import_job_id,
            "project_id": project_id,
            "status": "PROCESSING" if resumable else str(job["status"]),
            "resumable_operation_ids": resumable,
            "new_provider_work_created": False,
        }

    def record_execution_failure(
        self,
        *,
        operation_id: str,
        project_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        failure = {
            "code": error_code,
            "message": error_message[:4_000],
            "operation_id": operation_id,
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, command_payload->'payload'
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                FOR UPDATE
                """,
                [operation_id, project_id],
            )
            operation = uow.cursor.fetchone()
            if operation is None or str(operation[0]) not in {
                "FAILED_RETRYABLE",
                "FAILED_FINAL",
                "DEAD_LETTER",
            }:
                return
            target = (
                "FAILED_RETRYABLE"
                if str(operation[0]) == "FAILED_RETRYABLE"
                else "FAILED_FINAL"
            )
            payload = dict(operation[1] or {})
            plan_id = str(payload.get("reprocessing_plan_asset_version_id") or "")
            if plan_id:
                ordinal = payload.get("reprocessing_item_ordinal")
                if ordinal is not None:
                    uow.cursor.execute(
                        """
                        UPDATE authority_source_reprocessing_plan_item
                        SET status='FAILED', last_error=%s, updated_at=NOW()
                        WHERE reprocessing_plan_asset_version_id=%s
                          AND ordinal=%s AND status='RUNNING'
                        """,
                        [json.dumps(failure), plan_id, int(ordinal)],
                    )
                uow.cursor.execute(
                    """
                    UPDATE authority_source_reprocessing_plan
                    SET status='FAILED'
                    WHERE asset_version_id=%s
                      AND status IN ('RUNNING', 'PARTIALLY_APPLIED')
                    """,
                    [plan_id],
                )
                uow.commit()
                return
            uow.cursor.execute(
                """
                SELECT import_job_id, work_kind
                FROM authority_source_import_work
                WHERE project_id=%s AND operation_id=%s
                FOR UPDATE
                """,
                [project_id, operation_id],
            )
            work = uow.cursor.fetchone()
            if work is None:
                return
            uow.cursor.execute(
                """
                UPDATE authority_source_import_work
                SET status=%s, failure=%s, updated_at=NOW()
                WHERE project_id=%s AND operation_id=%s
                  AND status IN ('PLANNED', 'RUNNING', 'FAILED_RETRYABLE')
                """,
                [target, json.dumps(failure), project_id, operation_id],
            )
            job_target = (
                "FAILED_RETRYABLE"
                if str(work[1]) == "DISCOVERY" and target == "FAILED_RETRYABLE"
                else "FAILED_FINAL"
                if str(work[1]) == "DISCOVERY"
                else "PARTIALLY_COMPLETED"
            )
            uow.cursor.execute(
                """
                UPDATE authority_source_import_job
                SET status=%s, failure=%s, updated_at=NOW()
                WHERE project_id=%s AND import_job_id=%s
                  AND status NOT IN ('IMPORTED', 'CANCELLED')
                """,
                [
                    job_target,
                    json.dumps(failure),
                    project_id,
                    str(work[0]),
                ],
            )
            uow.commit()

    def execute_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        definition = self._operation_definition(worker.causation_id, worker.project_id)
        if definition == SOURCE_IMPORT_DISCOVERY_OPERATION:
            return self._execute_discovery(worker)
        if definition == SOURCE_IMPORT_FILE_OPERATION:
            return self._execute_file(worker)
        if definition == SOURCE_IMPORT_PROFILING_OPERATION:
            return self._execute_profiling(worker)
        if definition == SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION:
            return self._execute_analysis_planning(worker)
        if definition == SOURCE_IMPORT_DECONSTRUCTION_OPERATION:
            return self._execute_deconstruction(worker)
        if definition == SOURCE_IMPORT_MKAOS_OPERATION:
            return self._execute_mkaos(worker)
        if definition == SOURCE_IMPORT_REPROCESSING_OPERATION:
            return self._execute_reprocessing(worker)
        raise KernelError(
            "SOURCE_IMPORT_HANDLER_NOT_FOUND",
            f"unsupported Source import Operation: {definition}",
        )

    def result(
        self, operation_id: str, project_id: str, *, replayed: bool
    ) -> dict[str, Any]:
        definition = self._operation_definition(operation_id, project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
            if definition == SOURCE_IMPORT_REPROCESSING_OPERATION:
                uow.cursor.execute(
                    """
                    SELECT command_payload->'payload'->>'reprocessing_plan_asset_version_id'
                    FROM authority_operation WHERE operation_id=%s AND project_id=%s
                    """,
                    [operation_id, project_id],
                )
                plan_id = str(uow.cursor.fetchone()[0])
                return {
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "reprocessing_plan_asset_version_id": plan_id,
                    "status": state["status"],
                    "replayed": replayed,
                }
            if definition in {
                SOURCE_IMPORT_PROFILING_OPERATION,
                SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION,
                SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
                SOURCE_IMPORT_MKAOS_OPERATION,
            }:
                uow.cursor.execute(
                    """
                    SELECT command_payload->'payload'
                    FROM authority_operation
                    WHERE operation_id=%s AND project_id=%s
                    """,
                    [operation_id, project_id],
                )
                payload = dict(uow.cursor.fetchone()[0] or {})
                plan_id = str(payload.get("reprocessing_plan_asset_version_id") or "")
                if plan_id:
                    ordinal = int(payload["reprocessing_item_ordinal"])
                    uow.cursor.execute(
                        """
                        SELECT status, result
                        FROM authority_source_reprocessing_plan_item
                        WHERE reprocessing_plan_asset_version_id=%s
                          AND ordinal=%s
                        """,
                        [plan_id, ordinal],
                    )
                    item = uow.cursor.fetchone()
                    if item is None:
                        raise KernelError(
                            "SOURCE_REPROCESSING_ITEM_NOT_FOUND",
                            "reprocessing result item is unavailable",
                        )
                    return {
                        "operation_id": operation_id,
                        "project_id": project_id,
                        "reprocessing_plan_asset_version_id": plan_id,
                        "reprocessing_item_ordinal": ordinal,
                        "work_status": str(item[0]),
                        "result": dict(item[1] or {}),
                        "status": state["status"],
                        "replayed": replayed,
                    }
            work = SourceImportRepository(uow.cursor).work_by_operation(
                project_id=project_id, operation_id=operation_id
            )
        return {
            "operation_id": operation_id,
            "project_id": project_id,
            "import_job_id": work["import_job_id"],
            "work_kind": work["work_kind"],
            "work_status": work["status"],
            "result": work["result"],
            "status": state["status"],
            "replayed": replayed,
        }

    def _execute_discovery(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        if self.git_adapter is None:
            raise KernelError(
                "SOURCE_IMPORT_GIT_ADAPTER_REQUIRED",
                "Source import worker has no governed Git adapter",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            job = repository.job_for_update(
                project_id=worker.project_id, import_job_id=work["import_job_id"]
            )
            if work["status"] == "SUCCEEDED":
                return dict(work["result"])
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            if job["status"] in {"ADMITTED", "FAILED_RETRYABLE", "DISCOVERING"}:
                repository.transition_job(
                    project_id=worker.project_id,
                    import_job_id=job["import_job_id"],
                    expected=(job["status"],),
                    target="DISCOVERING",
                    failure={},
                )
            uow.commit()
        discovery = self._execute_external_effect(
            worker=worker,
            effect_type="source.repository.discovery",
            capability="source.remote.fetch",
            stable_key=f"source.repository.discovery:{worker.causation_id}",
            request_payload={
                "repository_url": str(job["source_locator"]["repository_url"]),
                "ref": str(job["requested_ref"]),
                "policy": dict(job["import_policy"]),
            },
            adapter=self.git_adapter,
            max_attempts=3,
            timeout_seconds=300,
        )
        result = self._commit_discovery(worker, job, discovery)
        if job["mode"] == "IMPORT":
            self._admit_file_children(worker, job, result)
            self._admit_reused_profiling_children(worker, job, result)
            with AuthorityUnitOfWork(self.database_url) as uow:
                repository = SourceImportRepository(uow.cursor)
                work = repository.work_by_operation(
                    project_id=worker.project_id,
                    operation_id=worker.causation_id,
                )
                if work["status"] == "RUNNING":
                    repository.update_work(
                        project_id=worker.project_id,
                        operation_id=worker.causation_id,
                        expected=("RUNNING",),
                        status="SUCCEEDED",
                        result=result,
                    )
                uow.commit()
        return result

    def _commit_discovery(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        current_files = tuple(
            RepositoryFile(
                path=str(item["path"]),
                mode=str(item["mode"]),
                object_type=str(item["object_type"]),
                object_id=str(item["object_id"]),
                size_bytes=int(item["size_bytes"]),
                eligibility=str(item["eligibility"]),
                block_reason=str(item.get("block_reason") or ""),
                content_hash=str(item.get("content_hash") or ""),
            )
            for item in discovery["files"]
        )
        policy = SourceImportPolicy(**dict(job["import_policy"]))
        governance = decide_source_governance(
            authorization=str(job["source_locator"]["rights_authorization"]),
            license_name=str(job["source_locator"].get("license_name") or ""),
            copyright_boundary=str(
                job["source_locator"].get("copyright_boundary") or ""
            ),
        )
        governance_policy_hash = _hash(
            {
                "schema_version": "source-import-governance-policy.v1",
                "authorization": job["source_locator"]["rights_authorization"],
                "license_name": job["source_locator"].get("license_name") or "",
                "copyright_boundary": job["source_locator"].get("copyright_boundary")
                or "",
                "governance_status": governance.governance_status,
            }
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            existing = repository.snapshot_by_identity(
                project_id=worker.project_id,
                repository_identity=str(discovery["repository_identity"]),
                resolved_commit_sha=str(discovery["resolved_commit_sha"]),
                import_policy_hash=str(discovery["import_policy_hash"]),
                governance_policy_hash=governance_policy_hash,
            )
            if existing is not None:
                stored_files = repository.snapshot_files(
                    project_id=worker.project_id,
                    snapshot_asset_version_id=str(existing["asset_version_id"]),
                )
                counters = self._discovery_counters(
                    stored_files, policy=policy, snapshot_reused=True
                )
                target = "PREVIEWED" if job["mode"] == "PREVIEW" else "PROCESSING"
                repository.transition_job(
                    project_id=worker.project_id,
                    import_job_id=job["import_job_id"],
                    expected=("DISCOVERING", "PROCESSING"),
                    target=target,
                    counters=counters,
                    repository_snapshot_asset_version_id=str(
                        existing["asset_version_id"]
                    ),
                )
                result = {
                    "repository_snapshot_asset_version_id": existing[
                        "asset_version_id"
                    ],
                    "resolved_commit_sha": existing["resolved_commit_sha"],
                    "manifest_hash": existing["manifest_hash"],
                    "snapshot_reused": True,
                    "counters": counters,
                    "license_findings": list(discovery.get("license_findings") or []),
                }
                repository.update_work(
                    project_id=worker.project_id,
                    operation_id=worker.causation_id,
                    expected=("RUNNING",),
                    status=("RUNNING" if job["mode"] == "IMPORT" else "REUSED"),
                    result=result,
                )
                uow.commit()
                return result
            previous = repository.latest_snapshot(
                project_id=worker.project_id,
                repository_identity=str(discovery["repository_identity"]),
                import_policy_hash=str(discovery["import_policy_hash"]),
                governance_policy_hash=governance_policy_hash,
                excluding_commit_sha=str(discovery["resolved_commit_sha"]),
            )
            previous_rows = (
                repository.snapshot_files(
                    project_id=worker.project_id,
                    snapshot_asset_version_id=str(previous["asset_version_id"]),
                )
                if previous is not None
                else []
            )
            previous_files = tuple(
                _repository_file_from_row(row) for row in previous_rows
            )
            diffs = diff_repository_manifests(previous_files, current_files)
            snapshot_digest = _hash(
                {
                    "manifest_hash": discovery["manifest_hash"],
                    "governance_policy_hash": governance_policy_hash,
                }
            ).removeprefix("sha256:")
            snapshot_id = (
                f"source-repository-snapshot:{worker.project_id}:{snapshot_digest}"
            )
            snapshot_version_id = f"{snapshot_id}:v1"
            file_rows = self._build_snapshot_file_rows(
                project_id=worker.project_id,
                snapshot_asset_version_id=snapshot_version_id,
                current_files=current_files,
                previous_rows=previous_rows,
                diffs=diffs,
                repository=repository,
                governance_eligible=governance.analysis_allowed,
            )
            snapshot_content = {
                "schema_version": "source-repository-snapshot.v1",
                "repository_snapshot_id": snapshot_id,
                "repository_identity": discovery["repository_identity"],
                "repository_url": discovery["repository_url"],
                "requested_ref": discovery["requested_ref"],
                "resolved_commit_sha": discovery["resolved_commit_sha"],
                "manifest_hash": discovery["manifest_hash"],
                "import_policy_hash": discovery["import_policy_hash"],
                "governance_policy_hash": governance_policy_hash,
                "file_count": discovery["file_count"],
                "repository_bytes": discovery["repository_bytes"],
                "files": [
                    {
                        key: row[key]
                        for key in (
                            "path",
                            "file_identity_hash",
                            "diff_state",
                            "previous_path",
                            "object_mode",
                            "object_type",
                            "object_id",
                            "size_bytes",
                            "eligibility",
                            "block_reason",
                            "content_hash",
                            "status",
                        )
                    }
                    for row in file_rows
                ],
                "license_findings": list(discovery.get("license_findings") or []),
                "rights": {
                    "authorization": job["source_locator"]["rights_authorization"],
                    "license_name": job["source_locator"].get("license_name") or "",
                    "copyright_boundary": job["source_locator"].get(
                        "copyright_boundary"
                    )
                    or "",
                    "analysis_allowed": governance.analysis_allowed,
                },
                "source_policy": {
                    "raw_source_text_in_postgresql": False,
                    "raw_source_text_in_generation_context": False,
                    "requires_governed_abstraction": True,
                },
            }
            content_hash = _hash(snapshot_content)
            created = uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=snapshot_id,
                asset_version_id=snapshot_version_id,
                qualification_id=f"{snapshot_version_id}:qualification:v1",
                asset_type="source_repository_snapshot",
                output_key="source.import.repository_snapshot",
                role="manifest",
                content=snapshot_content,
                content_hash=content_hash,
                qualification_policy="source-repository-snapshot-v1",
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "resolved_commit_sha": discovery["resolved_commit_sha"],
                    "manifest_hash": discovery["manifest_hash"],
                    "preview_only": job["mode"] == "PREVIEW",
                    "provider_calls": 0,
                },
                lifecycle="ACTIVE",
                eligibility="ELIGIBLE",
                governance="CLEAR",
            )
            if not created:
                raise KernelError(
                    "SOURCE_IMPORT_SNAPSHOT_REPLAY_CONFLICT",
                    "new repository snapshot identity already exists",
                )
            repository.register_snapshot(
                {
                    "repository_snapshot_id": snapshot_id,
                    "project_id": worker.project_id,
                    "workspace_id": job["workspace_id"],
                    "asset_version_id": snapshot_version_id,
                    "repository_identity": discovery["repository_identity"],
                    "repository_url": discovery["repository_url"],
                    "requested_ref": discovery["requested_ref"],
                    "resolved_commit_sha": discovery["resolved_commit_sha"],
                    "manifest_hash": discovery["manifest_hash"],
                    "import_policy_hash": discovery["import_policy_hash"],
                    "governance_policy_hash": governance_policy_hash,
                    "file_count": discovery["file_count"],
                    "repository_bytes": discovery["repository_bytes"],
                    "created_by_operation_id": worker.causation_id,
                }
            )
            repository.register_files(file_rows)
            counters = self._discovery_counters(
                file_rows, policy=policy, snapshot_reused=False
            )
            target = "PREVIEWED" if job["mode"] == "PREVIEW" else "PROCESSING"
            repository.transition_job(
                project_id=worker.project_id,
                import_job_id=job["import_job_id"],
                expected=("DISCOVERING",),
                target=target,
                counters=counters,
                repository_snapshot_asset_version_id=snapshot_version_id,
                previous_snapshot_asset_version_id=(
                    str(previous["asset_version_id"]) if previous else ""
                ),
            )
            result = {
                "repository_snapshot_asset_version_id": snapshot_version_id,
                "resolved_commit_sha": discovery["resolved_commit_sha"],
                "manifest_hash": discovery["manifest_hash"],
                "snapshot_reused": False,
                "counters": counters,
                "license_findings": list(discovery.get("license_findings") or []),
            }
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="SUCCEEDED" if job["mode"] == "PREVIEW" else "RUNNING",
                result=result,
            )
            self._record_event(
                uow,
                worker,
                aggregate_type="authority_source_repository_snapshot",
                aggregate_id=snapshot_id,
                event_type="authority.source.import.repository.discovered",
                payload={
                    "import_job_id": job["import_job_id"],
                    "asset_version_id": snapshot_version_id,
                    "resolved_commit_sha": discovery["resolved_commit_sha"],
                    "manifest_hash": discovery["manifest_hash"],
                    "counters": counters,
                },
            )
            uow.commit()
        return result

    def _execute_reprocessing_deconstruction(
        self, worker: WorkerLeaseCommand, payload: dict[str, Any]
    ) -> dict[str, Any]:
        port = self._require_execution_port()
        plan_id = str(payload["reprocessing_plan_asset_version_id"])
        ordinal = int(payload["reprocessing_item_ordinal"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            uow.cursor.execute(
                """
                SELECT item.status, item.result, plan.workspace_id
                FROM authority_source_reprocessing_plan_item AS item
                JOIN authority_source_reprocessing_plan AS plan
                  ON plan.asset_version_id=
                     item.reprocessing_plan_asset_version_id
                WHERE item.project_id=%s
                  AND item.reprocessing_plan_asset_version_id=%s
                  AND item.ordinal=%s
                FOR UPDATE OF item
                """,
                [worker.project_id, plan_id, ordinal],
            )
            item = uow.cursor.fetchone()
            if item is None:
                raise KernelError(
                    "SOURCE_REPROCESSING_ITEM_NOT_FOUND",
                    "reprocessing deconstruction item is unavailable",
                )
            if str(item[0]) == "APPLIED":
                return dict(item[1] or {})
            workspace_id = str(item[2])
            source_chunk_ids = tuple(
                str(value)
                for value in payload.get("source_chunk_asset_version_ids") or ()
            )
            lower_ids = self._resolve_reprocessing_observation_ids(
                uow, plan_id, payload.get("input_observation_asset_version_ids") or ()
            )
            uow.cursor.execute(
                """
                SELECT chunk.asset_version_id, chunk.blob_id, chunk.byte_size,
                       chunk.content_hash, blob.actual_object_key,
                       blob.actual_hash, blob.actual_size, blob.status
                FROM authority_source_chunk AS chunk
                JOIN authority_blob AS blob ON blob.blob_id=chunk.blob_id
                WHERE chunk.project_id=%s AND chunk.asset_version_id=ANY(%s)
                ORDER BY chunk.chunk_index
                FOR SHARE OF chunk, blob
                """,
                [worker.project_id, list(source_chunk_ids)],
            )
            chunk_rows = uow.cursor.fetchall()
            if len(chunk_rows) != len(source_chunk_ids):
                raise KernelError(
                    "SOURCE_REPROCESSING_INPUT_MISSING",
                    "reprocessing SourceChunk input is unavailable",
                )
            uow.cursor.execute(
                """
                SELECT observation.asset_version_id, version.content_hash,
                       version.content
                FROM authority_source_deconstruction_observation AS observation
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=observation.asset_version_id
                WHERE observation.project_id=%s
                  AND observation.asset_version_id=ANY(%s)
                  AND version.lifecycle='ACTIVE'
                ORDER BY observation.asset_version_id
                """,
                [worker.project_id, list(lower_ids)],
            )
            lower_rows = uow.cursor.fetchall()
            if len(lower_rows) != len(lower_ids):
                raise KernelError(
                    "SOURCE_REPROCESSING_LOWER_OBSERVATION_MISSING",
                    "aggregate reprocessing input Observation is unavailable",
                )
            uow.commit()
        if chunk_rows and self.object_store_reader is None:
            raise KernelError(
                "SOURCE_IMPORT_OBJECT_READER_REQUIRED",
                "reprocessing cannot read governed SourceChunk objects",
            )
        segments: list[dict[str, Any]] = []
        for row in chunk_rows:
            if str(row[7]) != "AVAILABLE":
                raise KernelError(
                    "SOURCE_IMPORT_CHUNK_BLOB_UNAVAILABLE",
                    "reprocessing SourceChunk Blob is not AVAILABLE",
                )
            assert self.object_store_reader is not None
            content = self.object_store_reader.read(
                object_key=str(row[4]),
                expected_hash=str(row[5]),
                expected_size=int(row[6]),
            )
            segments.append(
                {
                    "source_chunk_asset_version_id": str(row[0]),
                    "content": content.decode("utf-8", errors="strict"),
                    "content_hash": str(row[3]),
                    "byte_size": int(row[2]),
                }
            )
        declared_spans = list(payload.get("evidence_spans") or [])
        spans = tuple(
            ObservationEvidenceSpan(
                source_chunk_asset_version_id=str(
                    span["source_chunk_asset_version_id"]
                ),
                chunk_byte_start=int(span["chunk_byte_start"]),
                chunk_byte_end=int(span["chunk_byte_end"]),
                evidence_hash=str(span["evidence_hash"]),
            )
            for span in declared_spans
        )
        if not spans:
            spans = tuple(
                ObservationEvidenceSpan(
                    source_chunk_asset_version_id=str(row[0]),
                    chunk_byte_start=0,
                    chunk_byte_end=int(row[2]),
                    evidence_hash=str(row[3]),
                )
                for row in chunk_rows
            )
        analyzer = AnalyzerContract(
            **{
                key: value
                for key, value in dict(payload["analyzer"]).items()
                if key != "fingerprint"
            }
        )
        scope = ObservationScope(**dict(payload["scope"]))
        lower_inputs = tuple(
            {
                "asset_version_id": str(row[0]),
                "content_hash": str(row[1]),
                "observation": dict(row[2])["observation"],
            }
            for row in lower_rows
        )
        executed = port.execute_deconstruction(
            worker=worker,
            analyzer=analyzer,
            scope=scope,
            evidence_spans=spans,
            source_segments=tuple(segments),
            input_observations=lower_inputs,
        )
        observation = self.source_authority.execute_observation(
            CommitDeconstructionObservationCommand(
                project_id=worker.project_id,
                workspace_id=workspace_id,
                execution_asset_version_id=str(executed["execution_asset_version_id"]),
                scope=scope,
                analyzer=analyzer,
                observation=dict(executed["observation"]),
                evidence_spans=spans,
                input_observation_asset_version_ids=lower_ids,
                evidence_class=str(executed["evidence_class"]),
                actor_id=self.worker_id,
                idempotency_key=f"reprocess-observation:{plan_id}:{ordinal}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
        )
        result = {
            "observation_id": observation["observation_id"],
            "observation_asset_version_id": observation["asset_version_id"],
            "execution_asset_version_id": executed["execution_asset_version_id"],
            "replaced_asset_version_id": str(
                payload.get("current_asset_version_id") or ""
            ),
            "analyzer_contract_hash": analyzer.fingerprint,
            "provider_execution_reused": bool(
                executed.get("provider_execution_reused")
            ),
        }
        self._complete_reprocessing_item(plan_id, ordinal, "APPLIED", result=result)
        self._resolve_reprocessing_invalidation(
            project_id=worker.project_id,
            plan_id=plan_id,
            target_asset_version_id=result["replaced_asset_version_id"],
            resolved_by_operation_id=worker.causation_id,
        )
        self._queue_reprocessing_continuation(worker, plan_id, ordinal)
        self._refresh_reprocessing_plan(plan_id)
        return result

    def _execute_reprocessing_mkaos(
        self, worker: WorkerLeaseCommand, payload: dict[str, Any]
    ) -> dict[str, Any]:
        port = self._require_execution_port()
        plan_id = str(payload["reprocessing_plan_asset_version_id"])
        ordinal = int(payload["reprocessing_item_ordinal"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            uow.cursor.execute(
                """
                SELECT item.status, item.result, plan.workspace_id
                FROM authority_source_reprocessing_plan_item AS item
                JOIN authority_source_reprocessing_plan AS plan
                  ON plan.asset_version_id=
                     item.reprocessing_plan_asset_version_id
                WHERE item.project_id=%s
                  AND item.reprocessing_plan_asset_version_id=%s
                  AND item.ordinal=%s
                FOR UPDATE OF item
                """,
                [worker.project_id, plan_id, ordinal],
            )
            item = uow.cursor.fetchone()
            if item is None:
                raise KernelError(
                    "SOURCE_REPROCESSING_ITEM_NOT_FOUND",
                    "reprocessing MKAOS item is unavailable",
                )
            if str(item[0]) == "APPLIED":
                return dict(item[1] or {})
            workspace_id = str(item[2])
            observation_ids = self._resolve_reprocessing_observation_ids(
                uow, plan_id, payload.get("observation_asset_version_ids") or ()
            )
            if len(observation_ids) != 1:
                raise KernelError(
                    "SOURCE_REPROCESSING_ABSTRACTION_SCOPE_UNSUPPORTED",
                    "one MKAOS execution must abstract exactly one Observation",
                )
            observation_id = observation_ids[0]
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                  AND asset.asset_type='source_deconstruction_observation'
                  AND version.lifecycle='ACTIVE'
                """,
                [observation_id, worker.project_id],
            )
            observation_row = uow.cursor.fetchone()
            if observation_row is None:
                raise KernelError(
                    "SOURCE_REPROCESSING_OBSERVATION_MISSING",
                    "replacement Observation is unavailable for abstraction",
                )
            uow.cursor.execute(
                """
                SELECT span.source_chunk_asset_version_id,
                       span.chunk_byte_start, span.chunk_byte_end,
                       span.evidence_hash
                FROM authority_source_deconstruction_observation_input AS input
                JOIN authority_source_evidence_span AS span
                  ON span.evidence_span_id=input.evidence_span_id
                WHERE input.project_id=%s
                  AND input.observation_asset_version_id=%s
                  AND input.role='SOURCE_CHUNK_EVIDENCE'
                ORDER BY input.ordinal
                """,
                [worker.project_id, observation_id],
            )
            evidence_spans = tuple(
                KnowledgeEvidenceSpan(
                    source_chunk_asset_version_id=str(row[0]),
                    chunk_byte_start=int(row[1]),
                    chunk_byte_end=int(row[2]),
                    evidence_hash=str(row[3]),
                )
                for row in uow.cursor.fetchall()
            )
            uow.commit()
        observation_content = dict(observation_row[0])
        executed = port.execute_mkaos_extraction(
            worker=worker,
            capability=str(payload["capability"]),
            abstraction_policy_version=str(payload["abstraction_policy_version"]),
            observation_asset_version_id=observation_id,
            observation=dict(observation_content["observation"]),
            evidence_spans=evidence_spans,
        )
        candidate = self.mkaos_authority.execute_candidate(
            CommitKnowledgeCandidateCommand(
                project_id=worker.project_id,
                workspace_id=workspace_id,
                execution_asset_version_id=str(executed["execution_asset_version_id"]),
                candidate=dict(executed["candidate"]),
                evidence_spans=evidence_spans,
                abstraction_policy_version=str(payload["abstraction_policy_version"]),
                actor_id=self.worker_id,
                idempotency_key=f"reprocess-candidate:{plan_id}:{ordinal}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                observation_asset_version_ids=(observation_id,),
            )
        )
        result = {
            "knowledge_candidate_id": candidate["knowledge_candidate_id"],
            "candidate_asset_version_id": candidate["asset_version_id"],
            "observation_asset_version_id": observation_id,
            "status": "NEEDS_REVIEW",
            "execution_asset_version_id": executed["execution_asset_version_id"],
        }
        self._complete_reprocessing_item(plan_id, ordinal, "APPLIED", result=result)
        self._queue_reprocessing_continuation(worker, plan_id, ordinal)
        self._refresh_reprocessing_plan(plan_id)
        return result

    def _build_snapshot_file_rows(
        self,
        *,
        project_id: str,
        snapshot_asset_version_id: str,
        current_files: tuple[RepositoryFile, ...],
        previous_rows: list[dict[str, Any]],
        diffs: tuple[ManifestDiffEntry, ...],
        repository: SourceImportRepository,
        governance_eligible: bool,
    ) -> list[dict[str, Any]]:
        current = {item.path: item for item in current_files}
        previous = {str(item["path"]): item for item in previous_rows}
        rows: list[dict[str, Any]] = []
        reusable_in_snapshot: dict[str, dict[str, Any]] = {}
        for diff in diffs:
            item = current.get(diff.path)
            prior = previous.get(diff.previous_path or diff.path)
            if item is None:
                assert prior is not None
                rows.append(
                    _file_row(
                        project_id=project_id,
                        snapshot_asset_version_id=snapshot_asset_version_id,
                        path=diff.path,
                        diff=diff,
                        file=None,
                        prior=prior,
                        status="REMOVED",
                    )
                )
                continue
            eligibility = item.eligibility
            block_reason = item.block_reason
            status = "BLOCKED" if eligibility == "BLOCKED" else "DISCOVERED"
            reuse = None
            if not governance_eligible and eligibility == "ELIGIBLE":
                eligibility = "BLOCKED"
                block_reason = "rights_governance"
                status = "BLOCKED"
            elif eligibility == "ELIGIBLE" and item.content_hash:
                if (
                    prior
                    and str(prior.get("content_hash") or "") == item.content_hash
                    and prior.get("source_document_id")
                    and prior.get("source_transform_id")
                ):
                    reuse = prior
                else:
                    reuse = reusable_in_snapshot.get(item.content_hash)
                    if reuse is None:
                        reuse = repository.reusable_content(
                            project_id=project_id,
                            content_hash=item.content_hash,
                        )
                if reuse is not None:
                    status = "REUSED"
                    reusable_in_snapshot[item.content_hash] = reuse
            row = _file_row(
                project_id=project_id,
                snapshot_asset_version_id=snapshot_asset_version_id,
                path=diff.path,
                diff=diff,
                file=item,
                prior=prior,
                status=status,
                eligibility=eligibility,
                block_reason=block_reason,
                reuse=reuse,
            )
            rows.append(row)
            if status == "REUSED" and item.content_hash:
                reusable_in_snapshot[item.content_hash] = row
        return rows

    def _admit_file_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        discovery_result: dict[str, Any],
    ) -> None:
        snapshot_id = str(discovery_result["repository_snapshot_asset_version_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            rows = SourceImportRepository(uow.cursor).snapshot_files(
                project_id=worker.project_id,
                snapshot_asset_version_id=snapshot_id,
            )
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if row["status"] == "DISCOVERED" and row.get("content_hash"):
                groups.setdefault(str(row["content_hash"]), []).append(row)
        for content_hash, grouped in sorted(groups.items()):
            canonical = sorted(grouped, key=lambda item: str(item["path"]))[0]
            child = self._admit_child(
                definition_name=SOURCE_IMPORT_FILE_OPERATION,
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                actor_id=self.worker_id,
                idempotency_key=(
                    f"source.import.file:{job['import_job_id']}:{content_hash}:"
                    f"{job['import_policy_hash']}"
                ),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=worker.causation_id,
                parent_operation_id=worker.causation_id,
                payload={
                    "import_job_id": job["import_job_id"],
                    "repository_snapshot_asset_version_id": snapshot_id,
                    "repository_identity": discovery_result.get("repository_identity")
                    or "",
                    "path": canonical["path"],
                    "object_id": canonical["object_id"],
                    "content_hash": content_hash,
                    "size_bytes": canonical["size_bytes"],
                },
                input_assets=(
                    {
                        "asset_version_id": snapshot_id,
                        "role": "repository_snapshot",
                    },
                ),
                ready=False,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                repository = SourceImportRepository(uow.cursor)
                for row in grouped:
                    repository.update_file(
                        project_id=worker.project_id,
                        snapshot_asset_version_id=snapshot_id,
                        path=str(row["path"]),
                        expected=("DISCOVERED", "QUEUED"),
                        status="QUEUED",
                        processing_operation_id=child,
                    )
                repository.register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job["import_job_id"],
                        "project_id": worker.project_id,
                        "work_kind": "FILE",
                        "stable_key": content_hash,
                        "source_path": canonical["path"],
                        "target_asset_version_id": snapshot_id,
                        "operation_id": child,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
                uow.commit()
            self._ready_child(
                operation_id=child,
                project_id=worker.project_id,
                actor_id=self.worker_id,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=worker.causation_id,
                reason="Source import file processing ready",
            )

    def _admit_reused_profiling_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        discovery_result: dict[str, Any],
    ) -> None:
        snapshot_id = str(discovery_result["repository_snapshot_asset_version_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            rows = SourceImportRepository(uow.cursor).snapshot_files(
                project_id=worker.project_id,
                snapshot_asset_version_id=snapshot_id,
            )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            transform_id = str(row.get("source_transform_id") or "")
            if (
                transform_id
                and row["eligibility"] == "ELIGIBLE"
                and row["status"]
                in {
                    "REUSED",
                    "TRANSFORMED",
                    "PROFILED",
                    "PROFILE_REVIEW_REQUIRED",
                    "ANALYZING",
                    "CANDIDATE_READY",
                }
            ):
                grouped.setdefault(transform_id, []).append(row)
        for rows_for_transform in grouped.values():
            first = rows_for_transform[0]
            self._admit_profiling_child(
                worker,
                {
                    **job,
                    "repository_snapshot_asset_version_id": snapshot_id,
                },
                {
                    "source_document_id": first["source_document_id"],
                    "source_transform_id": first["source_transform_id"],
                    "source_transform_asset_version_id": "",
                },
                source_paths=tuple(
                    sorted(str(item["path"]) for item in rows_for_transform)
                ),
            )

    def _admit_profiling_child(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        transform: dict[str, Any],
        *,
        source_paths: tuple[str, ...],
    ) -> None:
        transform_id = str(transform["source_transform_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            uow.cursor.execute(
                """
                SELECT transform.asset_version_id, transform.source_document_id,
                       chunk.asset_version_id, chunk.chunk_index,
                       version.content_hash
                FROM authority_source_transform AS transform
                JOIN authority_source_chunk AS chunk
                  ON chunk.source_transform_id=transform.source_transform_id
                 AND chunk.project_id=transform.project_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=chunk.asset_version_id
                WHERE transform.project_id=%s
                  AND transform.source_transform_id=%s
                  AND transform.status='ACTIVE'
                ORDER BY chunk.chunk_index
                """,
                [worker.project_id, transform_id],
            )
            rows = uow.cursor.fetchall()
            if not rows:
                raise KernelError(
                    "SOURCE_PROFILE_TRANSFORM_MISSING",
                    "profiling requires an active SourceTransform with chunks",
                )
            transform_version = str(rows[0][0])
            source_document_id = str(rows[0][1])
            chunks = tuple(
                {
                    "asset_version_id": str(row[2]),
                    "chunk_index": int(row[3]),
                    "content_hash": str(row[4]),
                }
                for row in rows
            )
        policy = SourceIntelligencePolicy(**dict(job["intelligence_policy"]))
        scope = LogicalDocumentScope(
            scope_kind="FILE_DOCUMENT",
            source_document_id=source_document_id,
            source_transform_id=transform_id,
            source_chunk_asset_version_ids=tuple(
                str(row[2]) for row in rows
            ),
            boundary_policy_version=policy.logical_document_policy_version,
            label=f"governed file document {source_document_id}",
        )
        requested_override = _source_analysis_override(job.get("analysis_override"))
        override = (
            requested_override
            if requested_override is not None
            and requested_override.logical_document_scope_hash == scope.scope_hash
            else None
        )
        stable_key = _hash(
            {
                "logical_document_scope_hash": scope.scope_hash,
                "profiling_policy_hash": policy.profiling_policy_hash,
                "override_contract_hash": (override.contract_hash if override else ""),
                "path_hints": list(source_paths),
            }
        )
        child = self._admit_child(
            definition_name=SOURCE_IMPORT_PROFILING_OPERATION,
            project_id=worker.project_id,
            workspace_id=str(job["workspace_id"]),
            actor_id=self.worker_id,
            idempotency_key=(
                f"source.import.profile:{job['import_job_id']}:{stable_key}"
            ),
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=transform_version,
            parent_operation_id=worker.causation_id,
            payload={
                "import_job_id": job["import_job_id"],
                "repository_snapshot_asset_version_id": job[
                    "repository_snapshot_asset_version_id"
                ],
                "logical_document_scope": scope.to_dict(),
                "intelligence_policy": asdict(policy),
                "analysis_override": (override.to_dict() if override else {}),
                "source_paths": list(source_paths),
            },
            input_assets=tuple(
                {
                    "asset_version_id": item["asset_version_id"],
                    "role": "source_chunk_evidence",
                    "content_hash": item["content_hash"],
                }
                for item in chunks
            ),
            ready=False,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            repository.update_files_analysis_by_transform(
                project_id=worker.project_id,
                snapshot_asset_version_id=str(
                    job["repository_snapshot_asset_version_id"]
                ),
                source_transform_id=transform_id,
                expected=(
                    "REUSED",
                    "TRANSFORMED",
                    "PROFILED",
                    "PROFILE_REVIEW_REQUIRED",
                    "ANALYZING",
                    "CANDIDATE_READY",
                ),
                status="PROFILING",
                processing_operation_id=child,
            )
            repository.register_work(
                {
                    "work_id": str(uuid4()),
                    "import_job_id": job["import_job_id"],
                    "project_id": worker.project_id,
                    "work_kind": "PROFILING",
                    "stable_key": stable_key,
                    "source_path": source_paths[0] if source_paths else "",
                    "target_asset_version_id": transform_version,
                    "operation_id": child,
                    "status": "PLANNED",
                    "result": {},
                    "failure": {},
                }
            )
            uow.commit()
        self._ready_child(
            operation_id=child,
            project_id=worker.project_id,
            actor_id=self.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=transform_version,
            reason="LogicalDocument Source profiling ready",
        )

    def _execute_file(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        if self.git_adapter is None or self.object_store_adapter is None:
            raise KernelError(
                "SOURCE_IMPORT_STORAGE_RUNTIME_REQUIRED",
                "Source import worker lacks Git or object-store execution",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            if work["status"] in {"SUCCEEDED", "REUSED"}:
                return dict(work["result"])
            job = repository.job_for_update(
                project_id=worker.project_id, import_job_id=work["import_job_id"]
            )
            snapshot = repository.snapshot(
                project_id=worker.project_id,
                asset_version_id=str(job["repository_snapshot_asset_version_id"]),
            )
            files = repository.snapshot_files(
                project_id=worker.project_id,
                snapshot_asset_version_id=str(snapshot["asset_version_id"]),
            )
            target = next(
                (
                    row
                    for row in files
                    if row["processing_operation_id"] == worker.causation_id
                ),
                None,
            )
            if target is None:
                raise KernelError(
                    "SOURCE_IMPORT_FILE_NOT_FOUND",
                    "file work has no repository manifest target",
                )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            repository.update_files_by_content(
                project_id=worker.project_id,
                snapshot_asset_version_id=str(snapshot["asset_version_id"]),
                content_hash=str(target["content_hash"]),
                expected=("QUEUED", "PROCESSING"),
                status="PROCESSING",
                source_document_id=None,
                source_transform_id=None,
                processing_operation_id=worker.causation_id,
            )
            uow.commit()
        raw = self.git_adapter.read_blob(
            str(snapshot["repository_identity"]), str(target["object_id"])
        )
        actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
        if actual_hash != target["content_hash"] or len(raw) != int(
            target["size_bytes"]
        ):
            raise KernelError(
                "SOURCE_IMPORT_GIT_OBJECT_DRIFT",
                "Git object bytes differ from the frozen repository manifest",
            )
        policy = SourceImportPolicy(**dict(job["import_policy"]))
        normalized = normalize_source_bytes(
            raw,
            path=str(target["path"]),
            normalization_version=policy.normalization_version,
        )
        chunks = chunk_normalized_text(
            normalized, max_chunk_bytes=policy.max_chunk_bytes
        )
        raw_blob_id = self._put_blob(
            worker,
            content=raw,
            content_hash=actual_hash,
            media_type=normalized.media_type,
            purpose="raw",
        )
        source_uri = (
            f"{snapshot['repository_url']}@{snapshot['resolved_commit_sha']}:"
            f"{target['path']}"
        )
        source_result = self.source_authority.execute(
            RegisterSourceDocumentCommand(
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                blob_id=raw_blob_id,
                title=str(target["path"]).rsplit("/", 1)[-1],
                source_kind="github_repository_file",
                source_uri=source_uri,
                rights_authorization=str(job["source_locator"]["rights_authorization"]),
                license_name=str(job["source_locator"].get("license_name") or ""),
                copyright_boundary=str(
                    job["source_locator"].get("copyright_boundary") or ""
                ),
                actor_id=self.worker_id,
                idempotency_key=f"import:{job['import_job_id']}:{actual_hash}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
        )
        if source_result["governance_status"] != "ELIGIBLE":
            raise KernelError(
                "SOURCE_IMPORT_RIGHTS_REVIEW_REQUIRED",
                "Source was imported but governance blocks transform and analysis",
            )
        normalized_bytes = normalized.text.encode("utf-8")
        normalized_blob_id = self._put_blob(
            worker,
            content=normalized_bytes,
            content_hash=normalized.content_hash,
            media_type=normalized.media_type,
            purpose=f"normalized:{policy.normalization_version}",
        )
        chunk_blob_ids: dict[str, str] = {}
        chunk_candidates: list[SourceChunkCandidate] = []
        for chunk in chunks:
            blob_id = chunk_blob_ids.get(chunk.content_hash)
            if blob_id is None:
                blob_id = self._put_blob(
                    worker,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    media_type="text/plain",
                    purpose=f"chunk:{policy.chunking_version}",
                )
                chunk_blob_ids[chunk.content_hash] = blob_id
            chunk_candidates.append(
                SourceChunkCandidate(
                    chunk_index=chunk.chunk_index,
                    blob_id=blob_id,
                    content_hash=chunk.content_hash,
                    byte_size=chunk.byte_size,
                    character_count=chunk.character_count,
                    token_count=chunk.token_count,
                    source_byte_start=chunk.normalized_byte_start,
                    source_byte_end=chunk.normalized_byte_end,
                )
            )
        transform = self.source_authority.execute_transform(
            CommitSourceTransformCommand(
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                source_document_id=str(source_result["source_document_id"]),
                normalization_version=policy.normalization_version,
                chunking_version=policy.chunking_version,
                chunking_policy_hash=policy.chunking_policy_hash,
                chunks=tuple(chunk_candidates),
                actor_id=self.worker_id,
                idempotency_key=(
                    f"import-transform:{source_result['asset_version_id']}:"
                    f"{policy.chunking_policy_hash}"
                ),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                normalized_blob_id=normalized_blob_id,
                normalized_content_hash=normalized.content_hash,
                normalized_byte_size=normalized.byte_size,
            )
        )
        result = {
            "source_document_id": source_result["source_document_id"],
            "source_asset_version_id": source_result["asset_version_id"],
            "source_transform_id": transform["source_transform_id"],
            "source_transform_asset_version_id": transform["asset_version_id"],
            "chunk_count": transform["chunk_count"],
            "raw_blob_id": raw_blob_id,
            "normalized_blob_id": normalized_blob_id,
            "content_hash": actual_hash,
            "provider_tokens": 0,
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            repository.update_files_by_content(
                project_id=worker.project_id,
                snapshot_asset_version_id=str(snapshot["asset_version_id"]),
                content_hash=actual_hash,
                expected=("PROCESSING", "QUEUED"),
                status="TRANSFORMED",
                source_document_id=str(source_result["source_document_id"]),
                source_transform_id=str(transform["source_transform_id"]),
                processing_operation_id=worker.causation_id,
            )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="RUNNING",
                result=result,
            )
            uow.commit()
        self._admit_profiling_child(
            worker,
            job,
            result,
            source_paths=tuple(
                sorted(
                    str(item["path"])
                    for item in files
                    if item.get("content_hash") == actual_hash
                )
            ),
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceImportRepository(uow.cursor).update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="SUCCEEDED",
                result=result,
            )
            uow.commit()
        return result

    def _execute_profiling(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        port = self._require_execution_port()
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            if work["status"] in {"SUCCEEDED", "REUSED"}:
                return dict(work["result"])
            job = repository.job_for_update(
                project_id=worker.project_id,
                import_job_id=work["import_job_id"],
            )
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            payload = dict(operation["command_payload"])["payload"]
            scope = LogicalDocumentScope(**dict(payload["logical_document_scope"]))
            uow.cursor.execute(
                """
                SELECT chunk.asset_version_id, chunk.blob_id, chunk.byte_size,
                       chunk.content_hash, blob.actual_object_key,
                       blob.actual_hash, blob.actual_size, blob.status
                FROM authority_source_chunk AS chunk
                JOIN authority_blob AS blob ON blob.blob_id=chunk.blob_id
                WHERE chunk.project_id=%s AND chunk.asset_version_id=ANY(%s)
                ORDER BY chunk.chunk_index
                FOR SHARE OF chunk, blob
                """,
                [
                    worker.project_id,
                    list(scope.source_chunk_asset_version_ids),
                ],
            )
            rows = uow.cursor.fetchall()
            if len(rows) != len(scope.source_chunk_asset_version_ids):
                raise KernelError(
                    "SOURCE_CLASSIFICATION_INPUT_MISSING",
                    "LogicalDocument SourceChunk input is unavailable",
                )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            uow.commit()
        if self.object_store_reader is None:
            raise KernelError(
                "SOURCE_IMPORT_OBJECT_READER_REQUIRED",
                "profiling worker cannot read governed SourceChunk objects",
            )
        segments: list[dict[str, Any]] = []
        for row in rows:
            if str(row[7]) != "AVAILABLE":
                raise KernelError(
                    "SOURCE_IMPORT_CHUNK_BLOB_UNAVAILABLE",
                    "profiling SourceChunk Blob is not AVAILABLE",
                )
            content = self.object_store_reader.read(
                object_key=str(row[4]),
                expected_hash=str(row[5]),
                expected_size=int(row[6]),
            )
            segments.append(
                {
                    "source_chunk_asset_version_id": str(row[0]),
                    "content": content.decode("utf-8", errors="strict"),
                    "content_hash": str(row[3]),
                    "byte_size": int(row[2]),
                }
            )
        policy = SourceIntelligencePolicy(**dict(payload["intelligence_policy"]))
        override = _source_analysis_override(payload.get("analysis_override"))
        if (
            override is not None
            and override.logical_document_scope_hash != scope.scope_hash
        ):
            raise KernelError(
                "SOURCE_PROFILE_OVERRIDE_SCOPE_MISMATCH",
                "governance override belongs to another LogicalDocument",
            )
        evidence = build_classification_evidence(
            scope=scope,
            path_hints=tuple(payload.get("source_paths") or ()),
            source_segments=tuple(segments),
            policy=policy,
        )
        override_hash = override.contract_hash if override else ""
        with AuthorityUnitOfWork(self.database_url) as uow:
            current = SourceProfileRepository(uow.cursor).current_profile(
                project_id=worker.project_id,
                logical_document_scope_hash=scope.scope_hash,
            )
        if current is not None and current["operation_status"] != "SUCCEEDED":
            raise KernelError(
                "SOURCE_PROFILE_RECOVERY_REQUIRED",
                "current Source Profile Authority Operation requires recovery",
            )
        exact_profile = bool(
            current
            and current["classifier_contract_hash"] == policy.classifier_contract_hash
            and current["classification_input_hash"] == evidence.input_hash
            and SourceIntelligencePolicy(
                **dict(current["content"]["intelligence_policy"])
            ).profiling_policy_hash
            == policy.profiling_policy_hash
            and current["override_contract_hash"] == override_hash
        )
        if exact_profile:
            assert current is not None
            profile = {
                "asset_version_id": current["asset_version_id"],
                "source_content_profile_id": current["source_content_profile_id"],
                "profile_status": current["status"],
                "resolved_content_type": current["resolved_content_type"],
                "duplicate": True,
            }
            classifier_reused = True
            profile_reused = True
        else:
            reusable_classifier = bool(
                current
                and current["classifier_contract_hash"]
                == policy.classifier_contract_hash
                and current["classification_input_hash"] == evidence.input_hash
            )
            if reusable_classifier:
                assert current is not None
                current_content = dict(current["content"])
                executed = {
                    "classification": dict(current_content["classifier_output"]),
                    "execution_asset_version_id": current_content["execution_evidence"][
                        "asset_version_id"
                    ],
                    "evidence_class": current_content["execution_evidence"][
                        "evidence_class"
                    ],
                    "provider_execution_reused": True,
                }
            else:
                executed = port.execute_classification(
                    worker=worker,
                    logical_document_scope_hash=scope.scope_hash,
                    classifier_contract=policy.classifier_contract,
                    classification_evidence=evidence.to_dict(),
                    source_segments=tuple(segments),
                )
            resolution = resolve_profile(
                classifier_output=dict(executed["classification"]),
                policy=policy,
                override=override,
            )
            profile = self.source_authority.execute_content_profile(
                CommitSourceContentProfileCommand(
                    project_id=worker.project_id,
                    workspace_id=str(job["workspace_id"]),
                    logical_document_scope=scope.to_dict(),
                    intelligence_policy=asdict(policy),
                    classifier_contract=policy.classifier_contract,
                    classification_evidence=evidence.to_dict(),
                    classifier_output=dict(executed["classification"]),
                    resolution=resolution.to_dict(),
                    execution_asset_version_id=str(
                        executed["execution_asset_version_id"]
                    ),
                    evidence_class=str(executed["evidence_class"]),
                    governance_override=(override.to_dict() if override else {}),
                    actor_id=self.worker_id,
                    idempotency_key=(f"import-profile:{work['stable_key']}"),
                    trace_id=worker.trace_id,
                    correlation_id=worker.correlation_id,
                )
            )
            classifier_reused = bool(executed.get("provider_execution_reused"))
            profile_reused = bool(profile.get("duplicate"))
        result = {
            "source_content_profile_id": profile["source_content_profile_id"],
            "profile_asset_version_id": profile["asset_version_id"],
            "profile_status": profile["profile_status"],
            "resolved_content_type": profile["resolved_content_type"],
            "logical_document_scope_hash": scope.scope_hash,
            "classifier_contract_hash": policy.classifier_contract_hash,
            "classification_input_hash": evidence.input_hash,
            "classifier_execution_reused": classifier_reused,
            "profile_reused": profile_reused,
        }
        blocked = profile["profile_status"] != "ROUTABLE"
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            repository.update_files_analysis_by_transform(
                project_id=worker.project_id,
                snapshot_asset_version_id=str(
                    job["repository_snapshot_asset_version_id"]
                ),
                source_transform_id=scope.source_transform_id,
                expected=("PROFILING",),
                status=("PROFILE_REVIEW_REQUIRED" if blocked else "PROFILED"),
                processing_operation_id=worker.causation_id,
                profile_asset_version_id=str(profile["asset_version_id"]),
            )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status=(
                    "BLOCKED"
                    if blocked
                    else "REUSED"
                    if profile_reused
                    else "SUCCEEDED"
                ),
                result=result,
                failure=(
                    {
                        "code": "SOURCE_PROFILE_REVIEW_REQUIRED",
                        "resolved_content_type": profile["resolved_content_type"],
                    }
                    if blocked
                    else {}
                ),
            )
            uow.commit()
        if not blocked:
            self._admit_analysis_planning_child(
                worker,
                job,
                scope=scope,
                profile_asset_version_id=str(profile["asset_version_id"]),
                resolved_content_type=str(profile["resolved_content_type"]),
            )
        else:
            with AuthorityUnitOfWork(self.database_url) as uow:
                repository = SourceImportRepository(uow.cursor)
                self._refresh_job(
                    repository,
                    str(job["import_job_id"]),
                    worker.project_id,
                )
                uow.commit()
        return result

    def _admit_analysis_planning_child(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        *,
        scope: LogicalDocumentScope,
        profile_asset_version_id: str,
        resolved_content_type: str,
    ) -> None:
        policy = SourceIntelligencePolicy(**dict(job["intelligence_policy"]))
        strategy = resolve_analysis_strategy(
            SourceContentType(resolved_content_type),
            registry=self.methodology_registry,
            routing_policy_version=policy.routing_policy_version,
        )
        stable_key = _hash(
            {
                "profile_asset_version_id": profile_asset_version_id,
                "analysis_strategy_fingerprint": strategy.fingerprint,
            }
        )
        child = self._admit_child(
            definition_name=SOURCE_IMPORT_ANALYSIS_PLANNING_OPERATION,
            project_id=worker.project_id,
            workspace_id=str(job["workspace_id"]),
            actor_id=self.worker_id,
            idempotency_key=(
                f"source.import.analysis.plan:{job['import_job_id']}:{stable_key}"
            ),
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=profile_asset_version_id,
            parent_operation_id=worker.causation_id,
            payload={
                "import_job_id": job["import_job_id"],
                "profile_asset_version_id": profile_asset_version_id,
                "logical_document_scope": scope.to_dict(),
                "routing_policy_version": policy.routing_policy_version,
                "analysis_strategy": strategy.to_dict(),
                "analysis_strategy_fingerprint": strategy.fingerprint,
            },
            input_assets=(
                {
                    "asset_version_id": profile_asset_version_id,
                    "role": "source_content_profile",
                },
            ),
            ready=False,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceImportRepository(uow.cursor).register_work(
                {
                    "work_id": str(uuid4()),
                    "import_job_id": job["import_job_id"],
                    "project_id": worker.project_id,
                    "work_kind": "ANALYSIS_PLANNING",
                    "stable_key": stable_key,
                    "source_path": "",
                    "target_asset_version_id": profile_asset_version_id,
                    "operation_id": child,
                    "status": "PLANNED",
                    "result": {},
                    "failure": {},
                }
            )
            uow.commit()
        self._ready_child(
            operation_id=child,
            project_id=worker.project_id,
            actor_id=self.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=profile_asset_version_id,
            reason="Source analysis strategy resolution ready",
        )

    def _execute_analysis_planning(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            if work["status"] in {"SUCCEEDED", "REUSED"}:
                return dict(work["result"])
            job = repository.job_for_update(
                project_id=worker.project_id,
                import_job_id=work["import_job_id"],
            )
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            payload = dict(operation["command_payload"])["payload"]
            profile = SourceProfileRepository(uow.cursor).profile(
                project_id=worker.project_id,
                asset_version_id=str(payload["profile_asset_version_id"]),
            )
            if profile is None or profile["status"] != "ROUTABLE":
                raise KernelError(
                    "SOURCE_ANALYSIS_PROFILE_NOT_ROUTABLE",
                    "Analysis planning stopped because Profile is not routable",
                )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            uow.commit()
        strategy = analysis_strategy_from_dict(
            dict(payload["analysis_strategy"]),
            expected_fingerprint=str(payload["analysis_strategy_fingerprint"]),
        )
        if strategy.content_type.value != str(
            profile["resolved_content_type"]
        ) or strategy.routing_policy_version != str(payload["routing_policy_version"]):
            raise KernelError(
                "SOURCE_ANALYSIS_STRATEGY_PROFILE_CONFLICT",
                "admission-frozen Analysis Strategy differs from its Profile or route",
            )
        plan = self.source_authority.execute_analysis_plan(
            CommitSourceAnalysisPlanCommand(
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                profile_asset_version_id=str(payload["profile_asset_version_id"]),
                strategy=strategy.to_dict(),
                actor_id=self.worker_id,
                idempotency_key=f"import-analysis-plan:{work['stable_key']}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
        )
        scope = LogicalDocumentScope(**dict(payload["logical_document_scope"]))
        result = {
            "source_analysis_plan_id": plan["source_analysis_plan_id"],
            "analysis_plan_asset_version_id": plan["asset_version_id"],
            "profile_asset_version_id": payload["profile_asset_version_id"],
            "resolved_content_type": profile["resolved_content_type"],
            "profile_id": strategy.profile_id,
            "profile_version": strategy.profile_version,
            "strategy_contract_hash": strategy.fingerprint,
            "methodologies": [
                {
                    "skill_id": item.skill_id,
                    "skill_version": item.skill_version,
                    "methodology_content_hash": item.methodology_content_hash,
                }
                for item in strategy.analyzers
            ],
            "plan_reused": bool(plan.get("duplicate")),
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = SourceImportRepository(uow.cursor)
            repository.update_files_analysis_by_transform(
                project_id=worker.project_id,
                snapshot_asset_version_id=str(
                    job["repository_snapshot_asset_version_id"]
                ),
                source_transform_id=scope.source_transform_id,
                expected=("PROFILED", "ANALYZING", "CANDIDATE_READY"),
                status="ANALYZING",
                processing_operation_id=worker.causation_id,
                profile_asset_version_id=str(payload["profile_asset_version_id"]),
                analysis_plan_asset_version_id=str(plan["asset_version_id"]),
            )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="REUSED" if plan.get("duplicate") else "SUCCEEDED",
                result=result,
            )
            uow.commit()
        self._admit_deconstruction_children(
            worker,
            job,
            logical_document_scope=scope,
            strategy=strategy,
            analysis_plan_asset_version_id=str(plan["asset_version_id"]),
        )
        return result

    def _admit_deconstruction_children(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        *,
        logical_document_scope: LogicalDocumentScope,
        strategy: Any,
        analysis_plan_asset_version_id: str,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset_version_id, chunk_index, byte_size, content_hash
                FROM authority_source_chunk
                WHERE project_id=%s AND source_transform_id=%s
                ORDER BY chunk_index
                """,
                [worker.project_id, logical_document_scope.source_transform_id],
            )
            chunks = [
                {
                    "asset_version_id": row[0],
                    "chunk_index": row[1],
                    "byte_size": row[2],
                    "content_hash": row[3],
                }
                for row in uow.cursor.fetchall()
            ]
        tasks = plan_analysis_tasks(
            strategy=strategy,
            logical_document_scope=logical_document_scope,
            analysis_plan_asset_version_id=analysis_plan_asset_version_id,
            chunks=chunks,
        )
        for task in tasks:
            child = self._admit_child(
                definition_name=SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                actor_id=self.worker_id,
                idempotency_key=(
                    f"source.import.analysis:{job['import_job_id']}:{task.stable_key}"
                ),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=analysis_plan_asset_version_id,
                parent_operation_id=worker.causation_id,
                payload={
                    "import_job_id": job["import_job_id"],
                    "source_document_id": logical_document_scope.source_document_id,
                    "source_transform_id": logical_document_scope.source_transform_id,
                    "analysis_plan_asset_version_id": analysis_plan_asset_version_id,
                    "mkaos_capability": strategy.mkaos_capability,
                    "abstraction_policy_version": (strategy.abstraction_policy_version),
                    "analysis_task": task.to_dict(),
                },
                input_assets=(
                    {
                        "asset_version_id": analysis_plan_asset_version_id,
                        "role": "source_analysis_plan",
                    },
                    *tuple(
                        {
                            "asset_version_id": chunk_id,
                            "role": "source_chunk_evidence",
                        }
                        for chunk_id in task.source_chunk_asset_version_ids
                    ),
                ),
                ready=False,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                SourceImportRepository(uow.cursor).register_work(
                    {
                        "work_id": str(uuid4()),
                        "import_job_id": job["import_job_id"],
                        "project_id": worker.project_id,
                        "work_kind": "DECONSTRUCTION",
                        "stable_key": task.stable_key,
                        "source_path": "",
                        "target_asset_version_id": analysis_plan_asset_version_id,
                        "operation_id": child,
                        "status": "PLANNED",
                        "result": {},
                        "failure": {},
                    }
                )
                uow.commit()
            self._ready_child(
                operation_id=child,
                project_id=worker.project_id,
                actor_id=self.worker_id,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=analysis_plan_asset_version_id,
                reason="Source deconstruction execution ready",
            )

    def _execute_deconstruction(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        port = self._require_execution_port()
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            operation_payload = dict(operation["command_payload"])["payload"]
        if "reprocessing_plan_asset_version_id" in operation_payload:
            return self._execute_reprocessing_deconstruction(
                worker, dict(operation_payload)
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            if work["status"] in {"SUCCEEDED", "REUSED"}:
                return dict(work["result"])
            job = repository.job_for_update(
                project_id=worker.project_id, import_job_id=work["import_job_id"]
            )
            payload = dict(operation_payload)
            task = dict(payload["analysis_task"])
            chunk_ids = tuple(task["source_chunk_asset_version_ids"])
            uow.cursor.execute(
                """
                SELECT chunk.asset_version_id, chunk.blob_id, chunk.byte_size,
                       chunk.content_hash, blob.actual_object_key,
                       blob.actual_hash, blob.actual_size, blob.status
                FROM authority_source_chunk AS chunk
                JOIN authority_blob AS blob ON blob.blob_id=chunk.blob_id
                WHERE chunk.project_id=%s AND chunk.asset_version_id=ANY(%s)
                ORDER BY chunk.chunk_index
                FOR SHARE OF chunk, blob
                """,
                [worker.project_id, list(chunk_ids)],
            )
            rows = uow.cursor.fetchall()
            if len(rows) != len(chunk_ids):
                raise KernelError(
                    "SOURCE_IMPORT_ANALYSIS_INPUT_MISSING",
                    "deconstruction SourceChunk input is unavailable",
                )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            uow.commit()
        analyzer = AnalyzerContract(
            **{
                key: value
                for key, value in dict(task["analyzer"]).items()
                if key != "fingerprint"
            }
        )
        scope = ObservationScope(
            scale=str(task["scale"]),
            range_start=int(task["range_start"]),
            range_end=int(task["range_end"]),
            source_document_ids=(str(payload["source_document_id"]),),
            label=str(task["label"]),
        )
        analysis_plan_asset_version_id = str(payload["analysis_plan_asset_version_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            current = SourceIntelligenceRepository(uow.cursor).current_observation(
                project_id=worker.project_id,
                scope_hash=scope.fingerprint,
                analyzer_id=analyzer.analyzer_id,
            )
        if (
            current is not None
            and current["operation_status"] == "SUCCEEDED"
            and current["analyzer_contract_hash"] == analyzer.fingerprint
            and current["analysis_plan_asset_version_id"]
            == analysis_plan_asset_version_id
            and current["methodology_content_hash"] == analyzer.methodology_content_hash
        ):
            current_content = dict(current["content"])
            reused_result = {
                "observation_id": current["observation_id"],
                "observation_asset_version_id": current["asset_version_id"],
                "execution_asset_version_id": current_content["execution_evidence"][
                    "asset_version_id"
                ],
                "evidence_class": current_content["execution_evidence"][
                    "evidence_class"
                ],
                "provider_execution_reused": True,
                "observation_reused": True,
                "analyzer_id": analyzer.analyzer_id,
                "analyzer_contract_hash": analyzer.fingerprint,
                "analysis_plan_asset_version_id": analysis_plan_asset_version_id,
            }
            with AuthorityUnitOfWork(self.database_url) as uow:
                SourceImportRepository(uow.cursor).update_work(
                    project_id=worker.project_id,
                    operation_id=worker.causation_id,
                    expected=("RUNNING",),
                    status="REUSED",
                    result=reused_result,
                )
                uow.commit()
            self._admit_mkaos_child(worker, job, reused_result, payload=payload)
            return reused_result
        if self.object_store_reader is None:
            raise KernelError(
                "SOURCE_IMPORT_OBJECT_READER_REQUIRED",
                "deconstruction worker cannot read governed SourceChunk objects",
            )
        segments = []
        spans = []
        for row in rows:
            if row[7] != "AVAILABLE":
                raise KernelError(
                    "SOURCE_IMPORT_CHUNK_BLOB_UNAVAILABLE",
                    "deconstruction SourceChunk Blob is not AVAILABLE",
                )
            content = self.object_store_reader.read(
                object_key=str(row[4]),
                expected_hash=str(row[5]),
                expected_size=int(row[6]),
            )
            segments.append(
                {
                    "source_chunk_asset_version_id": row[0],
                    "content": content.decode("utf-8", errors="strict"),
                    "content_hash": row[3],
                    "byte_size": row[2],
                }
            )
            spans.append(
                ObservationEvidenceSpan(
                    source_chunk_asset_version_id=str(row[0]),
                    chunk_byte_start=0,
                    chunk_byte_end=int(row[2]),
                    evidence_hash=str(row[3]),
                )
            )
        executed = port.execute_deconstruction(
            worker=worker,
            analyzer=analyzer,
            scope=scope,
            evidence_spans=tuple(spans),
            source_segments=tuple(segments),
            analysis_plan_asset_version_id=analysis_plan_asset_version_id,
        )
        observation = self.source_authority.execute_observation(
            CommitDeconstructionObservationCommand(
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                execution_asset_version_id=str(executed["execution_asset_version_id"]),
                scope=scope,
                analyzer=analyzer,
                observation=dict(executed["observation"]),
                evidence_spans=tuple(spans),
                input_observation_asset_version_ids=(),
                evidence_class=str(executed["evidence_class"]),
                actor_id=self.worker_id,
                idempotency_key=f"import-observation:{task['stable_key']}",
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                analysis_plan_asset_version_id=analysis_plan_asset_version_id,
            )
        )
        result = {
            "observation_id": observation["observation_id"],
            "observation_asset_version_id": observation["asset_version_id"],
            "execution_asset_version_id": executed["execution_asset_version_id"],
            "evidence_class": executed["evidence_class"],
            "provider_execution_reused": bool(
                executed.get("provider_execution_reused")
            ),
            "analyzer_id": analyzer.analyzer_id,
            "analyzer_contract_hash": analyzer.fingerprint,
            "analysis_plan_asset_version_id": analysis_plan_asset_version_id,
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            SourceImportRepository(uow.cursor).update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="RUNNING",
                result=result,
            )
            uow.commit()
        self._admit_mkaos_child(worker, job, result, payload=payload)
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceImportRepository(uow.cursor).update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="SUCCEEDED",
                result=result,
            )
            uow.commit()
        return result

    def _admit_mkaos_child(
        self,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        observation: dict[str, Any],
        *,
        payload: dict[str, Any],
    ) -> None:
        capability = str(payload["mkaos_capability"])
        abstraction_policy_version = str(payload["abstraction_policy_version"])
        mkaos_methodology = self.methodology_registry.require("anti-copy-abstraction")
        observation_version = str(observation["observation_asset_version_id"])
        child = self._admit_child(
            definition_name=SOURCE_IMPORT_MKAOS_OPERATION,
            project_id=worker.project_id,
            workspace_id=str(job["workspace_id"]),
            actor_id=self.worker_id,
            idempotency_key=(
                f"source.import.mkaos:{job['import_job_id']}:"
                f"{observation_version}:"
                f"{abstraction_policy_version}:{capability}:"
                f"{mkaos_methodology.skill_version}:"
                f"{mkaos_methodology.content_digest}"
            ),
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=observation_version,
            parent_operation_id=worker.causation_id,
            payload={
                "import_job_id": job["import_job_id"],
                "observation_asset_version_id": observation_version,
                "analysis_plan_asset_version_id": payload[
                    "analysis_plan_asset_version_id"
                ],
                "source_transform_id": payload["source_transform_id"],
                "capability": capability,
                "abstraction_policy_version": abstraction_policy_version,
                "mkaos_skill_id": mkaos_methodology.skill_id,
                "mkaos_skill_version": mkaos_methodology.skill_version,
                "mkaos_methodology_content_hash": (mkaos_methodology.content_digest),
            },
            input_assets=(
                {
                    "asset_version_id": observation_version,
                    "role": "source_deconstruction_observation",
                },
            ),
            ready=False,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            SourceImportRepository(uow.cursor).register_work(
                {
                    "work_id": str(uuid4()),
                    "import_job_id": job["import_job_id"],
                    "project_id": worker.project_id,
                    "work_kind": "MKAOS_EXTRACTION",
                    "stable_key": (
                        f"{observation_version}:{abstraction_policy_version}:"
                        f"{capability}:{mkaos_methodology.skill_version}:"
                        f"{mkaos_methodology.content_digest}"
                    ),
                    "source_path": "",
                    "target_asset_version_id": observation_version,
                    "operation_id": child,
                    "status": "PLANNED",
                    "result": {},
                    "failure": {},
                }
            )
            uow.commit()
        self._ready_child(
            operation_id=child,
            project_id=worker.project_id,
            actor_id=self.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=observation_version,
            reason="MKAOS Observation abstraction ready",
        )

    def _execute_mkaos(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            operation_payload = dict(operation["command_payload"])["payload"]
        if "reprocessing_plan_asset_version_id" in operation_payload:
            return self._execute_reprocessing_mkaos(worker, dict(operation_payload))
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            work = repository.work_by_operation(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                for_update=True,
            )
            if work["status"] in {"SUCCEEDED", "REUSED"}:
                return dict(work["result"])
            job = repository.job_for_update(
                project_id=worker.project_id, import_job_id=work["import_job_id"]
            )
            payload = dict(operation_payload)
            observation_version = str(payload["observation_asset_version_id"])
            uow.cursor.execute(
                """
                SELECT version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                  AND asset.asset_type='source_deconstruction_observation'
                """,
                [observation_version, worker.project_id],
            )
            observation_row = uow.cursor.fetchone()
            if observation_row is None:
                raise KernelError(
                    "SOURCE_IMPORT_OBSERVATION_MISSING",
                    "MKAOS extraction Observation is unavailable",
                )
            uow.cursor.execute(
                """
                SELECT span.source_chunk_asset_version_id,
                       span.chunk_byte_start, span.chunk_byte_end,
                       span.evidence_hash
                FROM authority_source_deconstruction_observation_input AS input
                JOIN authority_source_evidence_span AS span
                  ON span.evidence_span_id=input.evidence_span_id
                WHERE input.project_id=%s
                  AND input.observation_asset_version_id=%s
                  AND input.role='SOURCE_CHUNK_EVIDENCE'
                ORDER BY input.ordinal
                """,
                [worker.project_id, observation_version],
            )
            evidence_spans = tuple(
                KnowledgeEvidenceSpan(
                    source_chunk_asset_version_id=str(row[0]),
                    chunk_byte_start=int(row[1]),
                    chunk_byte_end=int(row[2]),
                    evidence_hash=str(row[3]),
                )
                for row in uow.cursor.fetchall()
            )
            mkaos_methodology = self.methodology_registry.require(
                str(payload["mkaos_skill_id"]),
                expected_digest=str(payload["mkaos_methodology_content_hash"]),
            )
            if mkaos_methodology.skill_version != str(payload["mkaos_skill_version"]):
                raise KernelError(
                    "SOURCE_MKAOS_SKILL_VERSION_MISMATCH",
                    "MKAOS Skill version differs from the frozen child Operation",
                )
            reusable_candidate = self._reusable_mkaos_candidate(
                uow,
                project_id=worker.project_id,
                observation_asset_version_id=observation_version,
                capability=str(payload["capability"]),
                abstraction_policy_version=str(payload["abstraction_policy_version"]),
                methodology_content_hash=mkaos_methodology.content_digest,
            )
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("PLANNED", "RUNNING", "FAILED_RETRYABLE"),
                status="RUNNING",
            )
            uow.commit()
        if reusable_candidate is not None:
            result = {
                **reusable_candidate,
                "status": reusable_candidate["candidate_status"],
                "observation_asset_version_id": observation_version,
                "provider_execution_reused": True,
                "candidate_reused": True,
            }
            with AuthorityUnitOfWork(self.database_url) as uow:
                repository = SourceImportRepository(uow.cursor)
                repository.update_work(
                    project_id=worker.project_id,
                    operation_id=worker.causation_id,
                    expected=("RUNNING",),
                    status="REUSED",
                    result=result,
                )
                self._complete_analysis_file_if_ready(
                    uow,
                    repository=repository,
                    worker=worker,
                    job=job,
                    payload=payload,
                )
                self._refresh_job(
                    repository, str(job["import_job_id"]), worker.project_id
                )
                uow.commit()
            return result
        port = self._require_execution_port()
        observation_content = dict(observation_row[0])
        executed = port.execute_mkaos_extraction(
            worker=worker,
            capability=str(payload["capability"]),
            abstraction_policy_version=str(payload["abstraction_policy_version"]),
            observation_asset_version_id=observation_version,
            observation=dict(observation_content["observation"]),
            evidence_spans=evidence_spans,
        )
        candidate = self.mkaos_authority.execute_candidate(
            CommitKnowledgeCandidateCommand(
                project_id=worker.project_id,
                workspace_id=str(job["workspace_id"]),
                execution_asset_version_id=str(executed["execution_asset_version_id"]),
                candidate=dict(executed["candidate"]),
                evidence_spans=evidence_spans,
                abstraction_policy_version=str(payload["abstraction_policy_version"]),
                actor_id=self.worker_id,
                idempotency_key=(
                    f"import-candidate:{observation_version}:"
                    f"{payload['abstraction_policy_version']}"
                ),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                observation_asset_version_ids=(observation_version,),
            )
        )
        result = {
            "knowledge_candidate_id": candidate["knowledge_candidate_id"],
            "candidate_asset_version_id": candidate["asset_version_id"],
            "status": "NEEDS_REVIEW",
            "execution_asset_version_id": executed["execution_asset_version_id"],
            "observation_asset_version_id": observation_version,
            "provider_execution_reused": bool(
                executed.get("provider_execution_reused")
            ),
            "candidate_reused": bool(candidate.get("duplicate")),
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            repository = SourceImportRepository(uow.cursor)
            repository.update_work(
                project_id=worker.project_id,
                operation_id=worker.causation_id,
                expected=("RUNNING",),
                status="REUSED" if candidate.get("duplicate") else "SUCCEEDED",
                result=result,
            )
            self._complete_analysis_file_if_ready(
                uow,
                repository=repository,
                worker=worker,
                job=job,
                payload=payload,
            )
            self._refresh_job(repository, job["import_job_id"], worker.project_id)
            uow.commit()
        return result

    def _reusable_mkaos_candidate(
        self,
        uow: AuthorityUnitOfWork,
        *,
        project_id: str,
        observation_asset_version_id: str,
        capability: str,
        abstraction_policy_version: str,
        methodology_content_hash: str,
    ) -> dict[str, Any] | None:
        uow.cursor.execute(
            """
            SELECT candidate.knowledge_candidate_id,
                   candidate.asset_version_id,
                   candidate.execution_asset_version_id,
                   candidate.status
            FROM authority_mkaos_knowledge_candidate AS candidate
            JOIN authority_operation AS candidate_operation
              ON candidate_operation.operation_id=candidate.created_by_operation_id
            JOIN authority_asset_version AS candidate_version
              ON candidate_version.asset_version_id=candidate.asset_version_id
            JOIN authority_asset_version AS execution_version
              ON execution_version.asset_version_id=
                 candidate.execution_asset_version_id
            WHERE candidate.project_id=%s
              AND candidate_operation.status='SUCCEEDED'
              AND candidate.abstraction_policy_version=%s
              AND candidate_version.content->'observation_asset_version_ids'
                    @> jsonb_build_array(%s::text)
              AND jsonb_array_length(
                    candidate_version.content->'observation_asset_version_ids'
                  )=1
              AND execution_version.content->>'capability'=%s
              AND execution_version.content->'methodology'->>'skill_id'=
                    'anti-copy-abstraction'
              AND execution_version.content->'methodology'->>'content_hash'=%s
              AND NOT EXISTS (
                    SELECT 1 FROM authority_content_invalidation AS invalidation
                    WHERE invalidation.project_id=candidate.project_id
                      AND invalidation.target_asset_version_id=
                          candidate.asset_version_id
                      AND invalidation.status='OPEN'
                  )
            ORDER BY candidate.created_at DESC
            LIMIT 1
            """,
            [
                project_id,
                abstraction_policy_version,
                observation_asset_version_id,
                capability,
                methodology_content_hash,
            ],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        return {
            "knowledge_candidate_id": str(row[0]),
            "candidate_asset_version_id": str(row[1]),
            "execution_asset_version_id": str(row[2]),
            "candidate_status": str(row[3]),
        }

    def _complete_analysis_file_if_ready(
        self,
        uow: AuthorityUnitOfWork,
        *,
        repository: SourceImportRepository,
        worker: WorkerLeaseCommand,
        job: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        uow.cursor.execute(
            """
            SELECT EXISTS (
              SELECT 1
              FROM authority_source_import_work AS work
              JOIN authority_operation AS operation
                ON operation.operation_id=work.operation_id
              WHERE work.project_id=%s AND work.import_job_id=%s
                AND work.work_kind IN ('DECONSTRUCTION', 'MKAOS_EXTRACTION')
                AND work.status IN ('PLANNED', 'RUNNING', 'FAILED_RETRYABLE')
                AND operation.command_payload->'payload'->>'source_transform_id'=%s
            )
            """,
            [
                worker.project_id,
                job["import_job_id"],
                payload["source_transform_id"],
            ],
        )
        if bool(uow.cursor.fetchone()[0]):
            return
        repository.update_files_analysis_by_transform(
            project_id=worker.project_id,
            snapshot_asset_version_id=str(job["repository_snapshot_asset_version_id"]),
            source_transform_id=str(payload["source_transform_id"]),
            expected=("ANALYZING", "CANDIDATE_READY"),
            status="CANDIDATE_READY",
            processing_operation_id=worker.causation_id,
            profile_asset_version_id=None,
            analysis_plan_asset_version_id=str(
                payload["analysis_plan_asset_version_id"]
            ),
        )

    def _execute_reprocessing(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            require_current_fence(uow, worker)
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            payload = dict(operation["command_payload"])["payload"]
            plan_id = str(payload["reprocessing_plan_asset_version_id"])
            uow.cursor.execute(
                """
                SELECT plan.status, plan.workspace_id
                FROM authority_source_reprocessing_plan AS plan
                WHERE plan.project_id=%s AND plan.asset_version_id=%s
                FOR UPDATE
                """,
                [worker.project_id, plan_id],
            )
            plan = uow.cursor.fetchone()
            if plan is None:
                raise KernelError(
                    "SOURCE_REPROCESSING_PLAN_NOT_FOUND",
                    "reprocessing plan is unavailable",
                )
            uow.cursor.execute(
                """
                SELECT ordinal, action, target_key, reason, dependency_ids,
                       execution_spec, status, child_operation_id,
                       attempt_count, last_error, result
                FROM authority_source_reprocessing_plan_item
                WHERE reprocessing_plan_asset_version_id=%s
                ORDER BY ordinal
                FOR UPDATE
                """,
                [plan_id],
            )
            keys = (
                "ordinal",
                "action",
                "target_key",
                "reason",
                "dependency_ids",
                "execution_spec",
                "status",
                "child_operation_id",
                "attempt_count",
                "last_error",
                "result",
            )
            items = [dict(zip(keys, row, strict=True)) for row in uow.cursor.fetchall()]
            if str(plan[0]) == "APPLIED":
                return {
                    "reprocessing_plan_asset_version_id": plan_id,
                    "status": "APPLIED",
                    "replayed": True,
                }
            uow.cursor.execute(
                """
                UPDATE authority_source_reprocessing_plan
                SET status='RUNNING'
                WHERE asset_version_id=%s
                  AND status IN ('PLANNED', 'RUNNING', 'PARTIALLY_APPLIED', 'FAILED')
                """,
                [plan_id],
            )
            uow.commit()
        applied = 0
        status_by_target = {
            str(item["target_key"]): str(item["status"]) for item in items
        }
        for item in items:
            ordinal = int(item["ordinal"])
            action = str(item["action"])
            target_key = str(item["target_key"])
            status = str(item["status"])
            if status in {"APPLIED", "REUSED"}:
                applied += 1
                continue
            if status == "RUNNING":
                continue
            if action == "REUSE":
                self._complete_reprocessing_item(
                    plan_id, ordinal, "REUSED", result={"provider_calls": 0}
                )
                status_by_target[target_key] = "REUSED"
                applied += 1
                continue
            dependencies = tuple(str(value) for value in item["dependency_ids"] or ())
            if any(
                status_by_target.get(dependency) in {"BLOCKED", "FAILED"}
                for dependency in dependencies
            ):
                self._block_reprocessing_item(
                    plan_id,
                    ordinal,
                    code="UPSTREAM_REPROCESSING_BLOCKED",
                    message="a required upstream reprocessing item is blocked",
                )
                status_by_target[target_key] = "BLOCKED"
                continue
            if any(
                status_by_target.get(dependency) not in {"APPLIED", "REUSED"}
                for dependency in dependencies
            ):
                continue
            execution_spec = dict(item["execution_spec"] or {})
            if action in {"RECOMPUTE", "RECOMPUTE_AGGREGATE"} and str(
                execution_spec.get("analysis_plan_asset_version_id") or ""
            ):
                self._block_reprocessing_item(
                    plan_id,
                    ordinal,
                    code="SOURCE_ANALYSIS_PLAN_RECOMPOSITION_REQUIRED",
                    message=(
                        "plan-bound Observation cannot be independently recomputed; "
                        "create a new classification/routing AnalysisPlan so all "
                        "affected downstream work is recomposed"
                    ),
                )
                status_by_target[target_key] = "BLOCKED"
                continue
            if (
                action
                in {
                    "RECOMPUTE",
                    "RECOMPUTE_AGGREGATE",
                    "REABSTRACT",
                    "REBUILD_PROJECTION",
                }
                and not execution_spec
            ):
                self._block_reprocessing_item(
                    plan_id,
                    ordinal,
                    code="REPROCESSING_EXECUTION_SPEC_REQUIRED",
                    message=(
                        "legacy plan lacks a frozen execution spec; regenerate it "
                        "with the current planner"
                    ),
                )
                status_by_target[target_key] = "BLOCKED"
                continue
            if action == "REGOVERN":
                self._block_reprocessing_item(
                    plan_id,
                    ordinal,
                    code="GOVERNANCE_REVIEW_REQUIRED",
                    message="reprocessing requires an explicit governance decision",
                )
                status_by_target[target_key] = "BLOCKED"
                continue
            child_definition = {
                "RECOMPUTE": SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
                "RECOMPUTE_AGGREGATE": SOURCE_IMPORT_DECONSTRUCTION_OPERATION,
                "REABSTRACT": SOURCE_IMPORT_MKAOS_OPERATION,
            }.get(action)
            if child_definition is None:
                self._block_reprocessing_item(
                    plan_id,
                    ordinal,
                    code="PROJECTION_REBUILDER_NOT_REGISTERED",
                    message="projection rebuild requires its registered owner",
                )
                status_by_target[target_key] = "BLOCKED"
                continue
            frozen_payload = {
                **execution_spec,
                "reprocessing_plan_asset_version_id": plan_id,
                "reprocessing_item_ordinal": ordinal,
            }
            input_assets: list[dict[str, Any]] = []
            current_id = str(execution_spec.get("current_asset_version_id") or "")
            if current_id:
                input_assets.append(
                    {"asset_version_id": current_id, "role": "stale_asset"}
                )
            for chunk_id in execution_spec.get("source_chunk_asset_version_ids") or ():
                input_assets.append(
                    {
                        "asset_version_id": str(chunk_id),
                        "role": "source_chunk_evidence",
                    }
                )
            for observation_id in (
                execution_spec.get("observation_asset_version_ids")
                or execution_spec.get("input_observation_asset_version_ids")
                or ()
            ):
                input_assets.append(
                    {
                        "asset_version_id": str(observation_id),
                        "role": "source_deconstruction_observation",
                    }
                )
            child_id = self._admit_child(
                definition_name=child_definition,
                project_id=worker.project_id,
                workspace_id=str(plan[1]),
                actor_id=self.worker_id,
                idempotency_key=(
                    f"source.reprocessing.item:{plan_id}:{ordinal}:{target_key}"
                ),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=plan_id,
                parent_operation_id=worker.causation_id,
                payload=frozen_payload,
                input_assets=tuple(input_assets),
                ready=False,
            )
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    UPDATE authority_source_reprocessing_plan_item
                    SET status='RUNNING', child_operation_id=%s,
                        attempt_count=attempt_count+1, updated_at=NOW()
                    WHERE reprocessing_plan_asset_version_id=%s
                      AND ordinal=%s AND status IN ('PENDING', 'FAILED')
                    """,
                    [child_id, plan_id, ordinal],
                )
                uow.commit()
            self._ready_child(
                operation_id=child_id,
                project_id=worker.project_id,
                actor_id=self.worker_id,
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
                causation_id=plan_id,
                reason=f"selective reprocessing item {ordinal} ready",
            )
        target, counts = self._refresh_reprocessing_plan(plan_id)
        return {
            "reprocessing_plan_asset_version_id": plan_id,
            "status": target,
            "counts": counts,
            "newly_applied": applied,
        }

    def _complete_reprocessing_item(
        self,
        plan_id: str,
        ordinal: int,
        status: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_source_reprocessing_plan_item
                SET status=%s, result=%s, last_error='{}'::jsonb,
                    updated_at=NOW()
                WHERE reprocessing_plan_asset_version_id=%s AND ordinal=%s
                  AND status IN ('PENDING', 'RUNNING', 'FAILED')
                """,
                [status, json.dumps(result or {}), plan_id, ordinal],
            )
            uow.commit()

    def _block_reprocessing_item(
        self, plan_id: str, ordinal: int, *, code: str, message: str
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_source_reprocessing_plan_item
                SET status='BLOCKED', last_error=%s, updated_at=NOW()
                WHERE reprocessing_plan_asset_version_id=%s AND ordinal=%s
                  AND status IN ('PENDING', 'RUNNING', 'FAILED')
                """,
                [json.dumps({"code": code, "message": message}), plan_id, ordinal],
            )
            uow.commit()

    def _refresh_reprocessing_plan(self, plan_id: str) -> tuple[str, dict[str, int]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, COUNT(*)
                FROM authority_source_reprocessing_plan_item
                WHERE reprocessing_plan_asset_version_id=%s
                GROUP BY status
                """,
                [plan_id],
            )
            counts = {str(row[0]): int(row[1]) for row in uow.cursor.fetchall()}
            pending = sum(counts.get(key, 0) for key in ("PENDING", "RUNNING"))
            failed = counts.get("FAILED", 0)
            blocked = counts.get("BLOCKED", 0)
            target = (
                "APPLIED"
                if not pending and not failed and not blocked
                else "BLOCKED"
                if not pending and not failed and blocked
                else "FAILED"
                if not pending and failed and not blocked
                else "PARTIALLY_APPLIED"
            )
            uow.cursor.execute(
                """
                UPDATE authority_source_reprocessing_plan
                SET status=%s WHERE asset_version_id=%s
                """,
                [target, plan_id],
            )
            uow.commit()
        return target, counts

    @staticmethod
    def _resolve_reprocessing_observation_ids(
        uow: AuthorityUnitOfWork,
        plan_id: str,
        requested_ids: Any,
    ) -> tuple[str, ...]:
        requested = tuple(str(value) for value in requested_ids or () if str(value))
        if not requested:
            return ()
        uow.cursor.execute(
            """
            SELECT execution_spec->>'current_asset_version_id',
                   result->>'observation_asset_version_id'
            FROM authority_source_reprocessing_plan_item
            WHERE reprocessing_plan_asset_version_id=%s
              AND action IN ('RECOMPUTE', 'RECOMPUTE_AGGREGATE')
              AND status='APPLIED'
              AND result ? 'observation_asset_version_id'
            """,
            [plan_id],
        )
        replacements = {
            str(row[0]): str(row[1])
            for row in uow.cursor.fetchall()
            if str(row[0] or "") and str(row[1] or "")
        }
        return tuple(replacements.get(value, value) for value in requested)

    def _resolve_reprocessing_invalidation(
        self,
        *,
        project_id: str,
        plan_id: str,
        target_asset_version_id: str,
        resolved_by_operation_id: str,
    ) -> None:
        if not target_asset_version_id:
            return
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                UPDATE authority_content_invalidation
                SET status='RESOLVED', resolved_by_operation_id=%s,
                    resolved_at=NOW()
                WHERE project_id=%s AND cause_ref=%s
                  AND target_asset_version_id=%s AND status='OPEN'
                """,
                [
                    resolved_by_operation_id,
                    project_id,
                    plan_id,
                    target_asset_version_id,
                ],
            )
            uow.commit()

    def _queue_reprocessing_continuation(
        self, worker: WorkerLeaseCommand, plan_id: str, ordinal: int
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT workspace_id
                FROM authority_source_reprocessing_plan
                WHERE project_id=%s AND asset_version_id=%s
                """,
                [worker.project_id, plan_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "SOURCE_REPROCESSING_PLAN_NOT_FOUND",
                "cannot resume an unavailable reprocessing plan",
            )
        self.apply_reprocessing_plan(
            ApplyReprocessingPlanCommand(
                project_id=worker.project_id,
                workspace_id=str(row[0]),
                reprocessing_plan_asset_version_id=plan_id,
                actor_id=self.worker_id,
                idempotency_key=(f"continue:{plan_id}:{ordinal}:{worker.causation_id}"),
                trace_id=worker.trace_id,
                correlation_id=worker.correlation_id,
            )
        )

    def _put_blob(
        self,
        worker: WorkerLeaseCommand,
        *,
        content: bytes,
        content_hash: str,
        media_type: str,
        purpose: str,
    ) -> str:
        adapter = SourceImportObjectStoreAdapter(
            self.object_store_adapter, content=content
        )
        digest = content_hash.removeprefix("sha256:")
        object_key = f"source-import/{worker.project_id}/{purpose}/{digest}"
        context = AssetCommandContext(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            actor_id=self.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=worker.attempt_id,
        )
        blob_id = reserve_blob(
            self.database_url,
            context,
            provider=str(adapter.provider),
            object_key=object_key,
            expected_hash=content_hash,
            expected_size=len(content),
            media_type=media_type,
            retention_class="LONG_TERM",
            encryption_metadata={"source_import": True},
            stable_identity=f"{purpose}:{content_hash}",
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            blob = uow.repositories.asset_blobs.blob_for_update(blob_id)
        if blob["status"] == "AVAILABLE":
            if blob["actual_hash"] != content_hash or int(blob["actual_size"]) != len(
                content
            ):
                raise KernelError(
                    "SOURCE_IMPORT_BLOB_REUSE_CONFLICT",
                    "content-addressed Blob has a different verified identity",
                )
            return blob_id
        effect_id = str(blob.get("upload_effect_id") or "")
        if blob["status"] == "PENDING_UPLOAD":
            planned = request_blob_upload(
                self.database_url,
                context,
                blob_id=blob_id,
            )
            effect_id = str(planned["external_effect_id"])
        if blob["status"] in {"UPLOADED"}:
            verify_blob(self.database_url, context, blob_id=blob_id)
            return blob_id
        if not effect_id:
            raise KernelError(
                "SOURCE_IMPORT_BLOB_RECOVERY_REQUIRED",
                f"Blob cannot resume upload from {blob['status']}",
            )
        self._execute_planned_effect(
            worker=worker,
            effect_id=effect_id,
            adapter=adapter,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            updated = uow.repositories.asset_blobs.blob_for_update(blob_id)
        if updated["status"] == "UPLOADED":
            verify_blob(self.database_url, context, blob_id=blob_id)
        elif updated["status"] != "AVAILABLE":
            raise KernelError(
                "SOURCE_IMPORT_BLOB_UPLOAD_INCOMPLETE",
                f"Blob upload ended in {updated['status']}",
            )
        return blob_id

    def _execute_external_effect(
        self,
        *,
        worker: WorkerLeaseCommand,
        effect_type: str,
        capability: str,
        stable_key: str,
        request_payload: dict[str, Any],
        adapter: Any,
        max_attempts: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        context = self._effect_context(worker)
        planned = plan_external_effect(
            self.database_url,
            context,
            effect_type=effect_type,
            provider=str(adapter.provider),
            capability=capability,
            stable_idempotency_key=stable_key,
            request_payload=request_payload,
            max_attempts=max_attempts,
            reversible=False,
            completion_policy="synchronous_final",
            request_timeout_seconds=timeout_seconds,
            reconciliation_mode=str(adapter.reconciliation_mode),
            provider_capability_profile=dict(adapter.capability_profile),
        )
        return self._execute_planned_effect(
            worker=worker,
            effect_id=str(planned["external_effect_id"]),
            adapter=adapter,
        )

    def _execute_planned_effect(
        self,
        *,
        worker: WorkerLeaseCommand,
        effect_id: str,
        adapter: Any,
    ) -> dict[str, Any]:
        context = self._effect_context(worker)
        with AuthorityUnitOfWork(self.database_url) as uow:
            effect = uow.repositories.external_effects.get_for_update(effect_id)
        disposition = classify_external_effect_recovery(str(effect["status"]))
        if disposition.value in {"QUERY_EXISTING", "RECONCILE_UNKNOWN"}:
            reconciled = reconcile_external_effect(
                self.database_url,
                context,
                effect_id=effect_id,
                adapter=adapter,
                attempt_command=worker,
            )
            if reconciled["outcome"] != "success":
                raise KernelError(
                    "SOURCE_IMPORT_EFFECT_RECONCILIATION_FAILED",
                    f"ExternalEffect reconciliation returned {reconciled['outcome']}",
                )
            return self._effect_evidence(effect_id)
        if disposition.value == "CONSUME_SUCCEEDED":
            return self._effect_evidence(effect_id)
        if disposition.value in {"TERMINAL_FAILURE", "TERMINAL_CANCELLED"}:
            raise KernelError(
                "SOURCE_IMPORT_EFFECT_TERMINAL",
                f"ExternalEffect is terminal: {effect['status']}",
            )
        dispatched = dispatch_external_effect(
            self.database_url,
            context,
            effect_id=effect_id,
            worker_id=self.worker_id,
            lease_seconds=30,
            adapter=adapter,
        )
        if dispatched["outcome"] != "success":
            raise KernelError(
                "SOURCE_IMPORT_EFFECT_FAILED",
                f"ExternalEffect returned {dispatched['outcome']}",
            )
        evidence = dispatched.get("provider_evidence")
        if not isinstance(evidence, Mapping):
            raise KernelError(
                "SOURCE_IMPORT_EFFECT_EVIDENCE_MISSING",
                "ExternalEffect returned no structured evidence",
            )
        return dict(evidence)

    def _effect_evidence(self, effect_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COALESCE(effect.reconciliation, dispatch.evidence)
                FROM authority_external_effect AS effect
                LEFT JOIN LATERAL (
                    SELECT evidence
                    FROM authority_external_effect_dispatch
                    WHERE external_effect_id=effect.external_effect_id
                    ORDER BY generation DESC LIMIT 1
                ) AS dispatch ON TRUE
                WHERE effect.external_effect_id=%s AND effect.status='SUCCEEDED'
                """,
                [effect_id],
            )
            row = uow.cursor.fetchone()
        if row is None or not isinstance(row[0], dict):
            raise KernelError(
                "SOURCE_IMPORT_EFFECT_EVIDENCE_MISSING",
                "succeeded ExternalEffect has no durable evidence",
            )
        return dict(row[0])

    def _admit_child(
        self,
        *,
        definition_name: str,
        project_id: str,
        workspace_id: str,
        actor_id: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
        parent_operation_id: str,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, Any], ...],
        ready: bool = True,
    ) -> str:
        resolved_inputs = self._resolve_input_assets(project_id, input_assets)
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": SOURCE_IMPORT_DEFINITION_VERSION,
                "project_id": project_id,
                "workspace_id": workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "project:source-import",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "parent_operation_id": parent_operation_id,
                "root_operation_id": self._root_operation(parent_operation_id),
                "causation_operation_id": parent_operation_id,
                "input": {
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "payload": payload,
                },
                "input_assets": resolved_inputs,
            },
            context=self._admission_context(actor_id),
        )
        operation_id = str(admitted["operation_id"])
        if ready:
            self._ready_child(
                operation_id=operation_id,
                project_id=project_id,
                actor_id=actor_id,
                trace_id=trace_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
                reason=f"Source import child {definition_name} ready",
            )
        return operation_id

    def _resolve_input_assets(
        self,
        project_id: str,
        inputs: tuple[dict[str, Any], ...],
    ) -> list[dict[str, Any]]:
        if not inputs:
            return []
        with AuthorityUnitOfWork(self.database_url) as uow:
            identities = [str(item["asset_version_id"]) for item in inputs]
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
                """,
                [project_id, identities],
            )
            hashes = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        if set(hashes) != set(identities):
            raise KernelError(
                "SOURCE_IMPORT_INPUT_ASSET_MISSING",
                "Source import child input AssetVersion is unavailable",
            )
        return [
            {
                "asset_version_id": identity,
                "role": str(item["role"]),
                "content_hash": hashes[identity],
            }
            for item, identity in zip(inputs, identities, strict=True)
        ]

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in source_import_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _admission_context(self, actor_id: str) -> AdmissionContext:
        return AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"source.authority.execute"}),
            available_handlers=frozenset(
                definition["handler_key"]
                for definition in source_import_definitions(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            ),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    def _ready_child(
        self,
        *,
        operation_id: str,
        project_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
        reason: str,
    ) -> None:
        state = self._operation_state(operation_id, project_id)
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

    def _operation_state(self, operation_id: str, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )

    def _operation_definition(self, operation_id: str, project_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT definition_name FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                """,
                [operation_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND", "Source import Operation does not exist"
            )
        return str(row[0])

    def _root_operation(self, operation_id: str) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT root_operation_id FROM authority_operation WHERE operation_id=%s",
                [operation_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "parent Operation does not exist")
        return str(row[0])

    def _effect_context(self, worker: WorkerLeaseCommand) -> EffectCommandContext:
        return EffectCommandContext(
            operation_id=worker.causation_id,
            project_id=worker.project_id,
            actor_id=self.worker_id,
            trace_id=worker.trace_id,
            correlation_id=worker.correlation_id,
            causation_id=worker.attempt_id,
        )

    def _require_execution_port(self) -> ContentIntelligenceExecutionPort:
        if self.execution_port is None:
            raise KernelError(
                "SOURCE_IMPORT_PEP_RUNTIME_REQUIRED",
                "deconstruction and MKAOS require a configured Production Execution Plane",
            )
        return self.execution_port

    def _refresh_job(
        self,
        repository: SourceImportRepository,
        import_job_id: str,
        project_id: str,
    ) -> None:
        work = repository.list_work(project_id=project_id, import_job_id=import_job_id)
        statuses = {str(item["status"]) for item in work}
        job = repository.job_for_update(
            project_id=project_id, import_job_id=import_job_id
        )
        transition_failure: dict[str, Any] | None = None
        if statuses & {"FAILED_RETRYABLE", "FAILED_FINAL"}:
            target = "PARTIALLY_COMPLETED"
        elif statuses & {"PLANNED", "RUNNING"}:
            return
        else:
            requested_override = _source_analysis_override(job.get("analysis_override"))
            override_applied = True
            if requested_override is not None:
                repository.cursor.execute(
                    """
                    SELECT EXISTS (
                      SELECT 1
                      FROM authority_source_repository_file AS file
                      JOIN authority_source_content_profile AS profile
                        ON profile.asset_version_id=
                           file.source_content_profile_asset_version_id
                      WHERE file.project_id=%s
                        AND file.repository_snapshot_asset_version_id=%s
                        AND profile.logical_document_scope_hash=%s
                        AND profile.override_contract_hash=%s
                    )
                    """,
                    [
                        project_id,
                        job["repository_snapshot_asset_version_id"],
                        requested_override.logical_document_scope_hash,
                        requested_override.contract_hash,
                    ],
                )
                override_applied = bool(repository.cursor.fetchone()[0])
            if not override_applied:
                target = "AWAITING_GOVERNANCE"
                transition_failure = {
                    "code": "SOURCE_PROFILE_OVERRIDE_TARGET_NOT_FOUND",
                    "logical_document_scope_hash": (
                        requested_override.logical_document_scope_hash
                        if requested_override is not None
                        else ""
                    ),
                }
            elif statuses & {"BLOCKED"} or any(
                item["work_kind"] == "MKAOS_EXTRACTION" for item in work
            ):
                target = "AWAITING_GOVERNANCE"
            else:
                target = "IMPORTED"
        if job["status"] == target:
            return
        repository.transition_job(
            project_id=project_id,
            import_job_id=import_job_id,
            expected=(
                "PROCESSING",
                "PARTIALLY_COMPLETED",
                "AWAITING_GOVERNANCE",
            ),
            target=target,
            failure=transition_failure,
        )

    @staticmethod
    def _discovery_counters(
        rows: list[dict[str, Any]], *, policy: SourceImportPolicy, snapshot_reused: bool
    ) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row["diff_state"]).lower()
            counts[key] = counts.get(key, 0) + 1
        eligible = [row for row in rows if row["eligibility"] == "ELIGIBLE"]
        to_process = [row for row in eligible if row["status"] == "DISCOVERED"]
        unique_to_process = list(
            {
                str(row.get("content_hash") or row["object_id"]): row
                for row in reversed(to_process)
            }.values()
        )
        estimated_chunks = sum(
            max(
                1,
                (int(row["size_bytes"]) + policy.max_chunk_bytes - 1)
                // policy.max_chunk_bytes,
            )
            for row in unique_to_process
        )
        estimated_tokens = sum(
            max(1, int(row["size_bytes"]) // 3) for row in unique_to_process
        )
        return {
            "files_discovered": len(rows),
            "files_eligible": len(eligible),
            "files_blocked": sum(row["eligibility"] == "BLOCKED" for row in rows),
            "files_reused": sum(row["status"] == "REUSED" for row in rows),
            "files_to_fetch": len(unique_to_process),
            "estimated_bytes": sum(int(row["size_bytes"]) for row in unique_to_process),
            "estimated_chunks": estimated_chunks,
            "estimated_classification_calls": len(unique_to_process),
            "estimated_model_work": len(unique_to_process),
            "estimated_tokens": estimated_tokens,
            "provider_calls_performed": 0,
            "snapshot_reused": snapshot_reused,
            "diff": counts,
        }

    @staticmethod
    def _record_event(
        uow: AuthorityUnitOfWork,
        worker: WorkerLeaseCommand,
        *,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
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
                "causation_id": worker.attempt_id,
                "payload": {
                    **payload,
                    "trace_id": worker.trace_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                },
            }
        )


def _repository_file_from_row(row: dict[str, Any]) -> RepositoryFile:
    return RepositoryFile(
        path=str(row["path"]),
        mode=str(row["object_mode"] or "100644"),
        object_type=str(row["object_type"] or "blob"),
        object_id=str(row["object_id"] or row["previous_object_id"]),
        size_bytes=max(0, int(row["size_bytes"])),
        eligibility=str(row["eligibility"]),
        block_reason=str(row["block_reason"]),
        content_hash=str(row["content_hash"] or ""),
    )


def _source_analysis_override(
    value: Any,
) -> SourceAnalysisOverride | None:
    if not value:
        return None
    if isinstance(value, SourceAnalysisOverride):
        return value
    return SourceAnalysisOverride(**dict(value))


def _file_row(
    *,
    project_id: str,
    snapshot_asset_version_id: str,
    path: str,
    diff: ManifestDiffEntry,
    file: RepositoryFile | None,
    prior: dict[str, Any] | None,
    status: str,
    eligibility: str = "BLOCKED",
    block_reason: str = "removed",
    reuse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_hash = (
        file.content_hash
        if file is not None
        else str((prior or {}).get("content_hash") or "")
    )
    object_id = file.object_id if file is not None else ""
    size = (
        file.size_bytes
        if file is not None
        else int((prior or {}).get("size_bytes") or 0)
    )
    return {
        "repository_snapshot_asset_version_id": snapshot_asset_version_id,
        "project_id": project_id,
        "path": path,
        "file_identity_hash": _hash(
            {
                "path": path,
                "object_id": object_id,
                "content_hash": content_hash,
                "diff_state": diff.state,
            }
        ),
        "diff_state": diff.state,
        "previous_path": diff.previous_path,
        "previous_object_id": diff.previous_object_id,
        "object_mode": file.mode if file is not None else "",
        "object_type": file.object_type if file is not None else "",
        "object_id": object_id,
        "size_bytes": size,
        "eligibility": eligibility,
        "block_reason": block_reason if eligibility == "BLOCKED" else "",
        "content_hash": content_hash or None,
        "source_document_id": (reuse or {}).get("source_document_id"),
        "source_transform_id": (reuse or {}).get("source_transform_id"),
        "processing_operation_id": (reuse or {}).get("processing_operation_id"),
        "status": status,
        "failure": {},
    }


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ApplyReprocessingPlanCommand",
    "ContentIntelligenceExecutionPort",
    "CreateSourceImportCommand",
    "SourceImportApplication",
]
