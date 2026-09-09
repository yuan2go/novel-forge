from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime.runtime import require_current_fence
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.attempt_runtime import WorkerLeaseCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    admit_command_in_uow,
)
from novel_forge.modules.source_authority.corpus import (
    validate_corpus_action,
    CORPUS_POLICY_VERSION,
    CorpusAction,
    ControlCorpusImport,
    ImportCorpusBatch,
    corpus_hash,
    corpus_identity,
)
from novel_forge.modules.source_authority.corpus_mutations import apply_corpus_action
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository


CORPUS_OPERATION = "source.corpus.commit"
CORPUS_VERSION = "1.0.0"
CORPUS_HANDLER = "novel_forge.source_authority.corpus_commit"


@dataclass(frozen=True, slots=True)
class CorpusCommand:
    project_id: str
    workspace_id: str
    actor_id: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    action: CorpusAction

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.project_id,
                self.workspace_id,
                self.actor_id,
                self.idempotency_key,
                self.trace_id,
                self.correlation_id,
            )
        ):
            raise ValueError(
                "Corpus command requires project, workspace, actor and execution lineage"
            )


def corpus_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    return {
        "name": CORPUS_OPERATION,
        "definition_version": CORPUS_VERSION,
        "family": "source_governance",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "required": ["project_id", "workspace_id", "payload"],
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["asset_version_id"],
            "properties": {"asset_version_id": {"type": "string"}},
            "additionalProperties": True,
        },
        "handler_key": CORPUS_HANDLER,
        "handler_contract_version": "source-corpus-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["source.authority.execute"],
        "approval_policy": {"required": False, "policy_key": CORPUS_POLICY_VERSION},
        "idempotency_scope": "project:source-corpus",
        "concurrency_key_template": "project:{project_id}:source-corpus",
        "retry_policy": {"max_attempts": 3},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only Corpus lineage",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "execution_classification": "durable_job",
            "project_scope_required": True,
            "postgresql_authority_required": True,
            "generation_context_forbidden": True,
            "max_batch_entries": 100,
            "max_command_bytes": 262144,
            "corpus_policy_version": CORPUS_POLICY_VERSION,
        },
        "completion_contract": {
            "version": "source.corpus.completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "corpus_record",
                    "output_key": "source.corpus.record",
                    "role": "evidence",
                    "lifecycle": "ACTIVE",
                    "eligibility": "INELIGIBLE",
                    "governance": "CLEAR",
                }
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["authority.source.corpus.committed"],
        },
    }


class SourceCorpusApplication:
    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha

    def admit(
        self, command: CorpusCommand, *, principal: Principal | None = None, parent_worker: WorkerLeaseCommand | None = None
    ) -> dict[str, Any]:
        actor = command.actor_id
        if principal is not None:
            principal.require("source.authority.execute", command.project_id)
            actor = principal.principal_id
        action = validate_corpus_action(command.action.model_dump(mode="json"))
        payload = action.model_dump(mode="json")
        key = command.idempotency_key
        if isinstance(action, ImportCorpusBatch):
            key = corpus_identity(
                "batch-command",
                command.project_id,
                action.snapshot_id,
                action.batch_key,
            )
        with AuthorityUnitOfWork(self.database_url, coordinate_nested=True) as uow:
            if parent_worker is not None:
                require_current_fence(uow, parent_worker)
                if parent_worker.project_id != command.project_id:
                    raise KernelError("CROSS_PROJECT_REFERENCE", "Corpus delegation changed project")
            repository = SourceAuthorityRepository(uow.cursor)
            repository.require_scope(
                project_id=command.project_id, workspace_id=command.workspace_id
            )
            if isinstance(action, ImportCorpusBatch):
                snapshot = repository.corpus_record(
                    "snapshot", command.project_id, action.snapshot_id
                )
                source = repository.corpus_record(
                    "source", command.project_id, snapshot["source_id"]
                )
                if source["workspace_id"] != command.workspace_id:
                    raise KernelError(
                        "CORPUS_WORKSPACE_INVALID",
                        "import snapshot is outside the workspace",
                    )
            uow.repositories.definitions.register(
                corpus_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            admitted = admit_command_in_uow(
                uow,
                {
                    "definition_name": CORPUS_OPERATION,
                    "definition_version": CORPUS_VERSION,
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "actor_id": actor,
                    "idempotency_scope": "project:source-corpus",
                    "idempotency_key": key,
                    "trace_id": command.trace_id,
                    "span_id": str(uuid4()),
                    "correlation_id": command.correlation_id,
                    "causation_id": key,
                    "input_assets": [],
                    "input": {
                        "project_id": command.project_id,
                        "workspace_id": command.workspace_id,
                        "payload": payload,
                    },
                },
                context=AdmissionContext(
                    actor_id=actor,
                    permissions=frozenset({"source.authority.execute"}),
                    available_handlers=frozenset({CORPUS_HANDLER}),
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                ),
            )
            operation_id = str(admitted["operation_id"])
            if isinstance(action, ImportCorpusBatch):
                SourceImportRepository(uow.cursor).register_job(
                    {
                        "import_job_id": f"source-import:{operation_id}",
                        "project_id": command.project_id,
                        "workspace_id": command.workspace_id,
                        "source_type": "corpus_manifest",
                        "source_locator": {"snapshot_id": action.snapshot_id},
                        "requested_ref": action.snapshot_id,
                        "corpus_snapshot_id": action.snapshot_id,
                        "import_policy": {
                            "version": CORPUS_POLICY_VERSION,
                            "max_batch_entries": 100,
                        },
                        "import_policy_hash": corpus_hash(
                            {"version": CORPUS_POLICY_VERSION, "max_batch_entries": 100}
                        ),
                        "intelligence_policy": {},
                        "intelligence_policy_hash": corpus_hash({}),
                        "analysis_override": {},
                        "mode": "FOUNDATION",
                        "status": "ADMITTED",
                        "discovery_operation_id": operation_id,
                    }
                )
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, command.project_id
            )
            if state["status"] == "ADMITTED":
                transition_operation(
                    self.database_url,
                    OperationTransitionCommand(
                        operation_id=operation_id,
                        project_id=command.project_id,
                        expected_version=int(state["version"]),
                        expected_status="ADMITTED",
                        target_status="READY",
                        actor_id=actor,
                        reason="bounded Corpus metadata command frozen",
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                        causation_id=key,
                    ),
                )
                state = uow.repositories.attempt_runtime.operation_state(
                    operation_id, command.project_id
                )
            uow.commit()
        if state["status"] == "SUCCEEDED":
            return self.result(operation_id, command.project_id, replayed=True)
        return {
            "operation_id": operation_id,
            "project_id": command.project_id,
            "status": state["status"],
            "replayed": bool(admitted.get("replayed")),
            **(
                {"import_job_id": f"source-import:{operation_id}"}
                if isinstance(action, ImportCorpusBatch)
                else {}
            ),
        }

    def execute_fenced(self, worker: WorkerLeaseCommand) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url, coordinate_nested=True) as uow:
            require_current_fence(uow, worker)
            repository = SourceAuthorityRepository(uow.cursor)
            output = repository.corpus_output(worker.project_id, worker.causation_id)
            if output is not None:
                return output
            operation = uow.repositories.chapter_authority.operation_execution(
                worker.causation_id, worker.project_id
            )
            command = operation["command_payload"]
            repository.require_scope(
                project_id=worker.project_id, workspace_id=command["workspace_id"]
            )
            action = validate_corpus_action(command["payload"])
            if isinstance(action, ControlCorpusImport):
                from .corpus_import_control import control_corpus_import
                result = control_corpus_import(repository, action, project_id=worker.project_id,
                    workspace_id=command["workspace_id"], operation_id=worker.causation_id, database_url=self.database_url)
            else:
                result = apply_corpus_action(
                    repository, action, project_id=worker.project_id,
                    workspace_id=command["workspace_id"], operation_id=worker.causation_id,
                )
            if isinstance(action, ImportCorpusBatch):
                job_id = f"source-import:{worker.causation_id}"
                denied = sum(
                    item["admission"]["decision"] == "DENY"
                    for item in result["entries"]
                )
                SourceImportRepository(uow.cursor).transition_job(
                    project_id=worker.project_id,
                    import_job_id=job_id,
                    expected=("ADMITTED",),
                    target="BLOCKED" if denied else "IMPORTED",
                    counters={
                        "editions": len(action.entries),
                        "denied_memberships": denied,
                    },
                )
                result["import_job_id"] = job_id
            content = {
                "schema_version": "source-corpus-result.v1",
                "action": action.action,
                "input_hash": corpus_hash(command["payload"]),
                "policy_version": CORPUS_POLICY_VERSION,
                **result,
            }
            asset_id = corpus_identity("result", worker.causation_id)
            version_id = asset_id + ":v1"
            uow.repositories.chapter_authority.materialize_output(
                operation_id=worker.causation_id,
                project_id=worker.project_id,
                asset_id=asset_id,
                asset_version_id=version_id,
                qualification_id=version_id + ":contract",
                asset_type="corpus_record",
                output_key="source.corpus.record",
                role="evidence",
                content=content,
                content_hash=corpus_hash(content),
                qualification_policy=CORPUS_POLICY_VERSION,
                qualification_evidence={
                    "operation_id": worker.causation_id,
                    "attempt_id": worker.attempt_id,
                    "fencing_token": worker.fencing_token,
                    "generation_context_allowed": False,
                },
                lifecycle="ACTIVE",
                eligibility="INELIGIBLE",
                governance="CLEAR",
            )
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "authority_corpus_source",
                    "aggregate_id": result.get("source_id", asset_id),
                    "operation_id": worker.causation_id,
                    "project_id": worker.project_id,
                    "event_type": "authority.source.corpus.committed",
                    "correlation_id": worker.correlation_id,
                    "causation_id": worker.causation_id,
                    "payload": {
                        "operation_id": worker.causation_id,
                        "action": action.action,
                        "asset_version_id": version_id,
                        "input_hash": content["input_hash"],
                        "trace_id": worker.trace_id,
                        "attempt_id": worker.attempt_id,
                        "fencing_token": worker.fencing_token,
                    },
                }
            )
            uow.commit()
        return {**content, "asset_version_id": version_id}

    def result(
        self, operation_id: str, project_id: str, *, replayed: bool
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url, coordinate_nested=True) as uow:
            output = SourceAuthorityRepository(uow.cursor).corpus_output(
                project_id, operation_id
            )
            if output is None:
                raise KernelError(
                    "CORPUS_RESULT_MISSING", "Corpus Operation has no committed result"
                )
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, project_id
            )
        return {
            **output,
            "operation_id": operation_id,
            "project_id": project_id,
            "status": state["status"],
            "replayed": replayed,
        }
