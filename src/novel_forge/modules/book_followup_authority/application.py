from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    start_saga,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.reader_judge_authority import ReaderJudgeRuntimeResolver

from .contracts import BOOK_FOLLOWUP_DEFINITION_VERSION, READER_OUTCOME_DEFINITION_VERSION, READER_OUTCOME_DEFINITION, ReaderOutcomeModelPort
from .definitions import book_followup_operation_definitions
from .registry import BookFollowupHandlerRegistry
from .reader_policy_authority import PostgresReaderProxyPolicyAuthority


@dataclass(frozen=True, slots=True)
class BookFollowupCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    payload: dict[str, Any]
    input_assets: tuple[dict[str, str], ...] = ()
    root_operation_id: str | None = None
    parent_operation_id: str | None = None
    causation_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class BookFollowupAdmission:
    operation_id: str
    project_id: str
    replayed: bool


class BookFollowupAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        model_port: ReaderOutcomeModelPort | None = None,
        prose_model_port: ReaderOutcomeModelPort | None = None,
        screenplay_model_ports: dict[str, ReaderOutcomeModelPort] | None = None,
        reader_judge_resolver: ReaderJudgeRuntimeResolver | None = None,
        worker_id: str = "book-followup-authority-worker",
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("PostgreSQL, build id, and full commit SHA are required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.prose_model_port = prose_model_port
        self.screenplay_model_ports = screenplay_model_ports or {}
        self.registry = BookFollowupHandlerRegistry(
            model_port,
            reader_judge_resolver or ReaderJudgeRuntimeResolver(database_url),
            prose_model_port,
            screenplay_model_ports,
        )
        self.worker_id = worker_id
        self.reader_policies = PostgresReaderProxyPolicyAuthority(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )

    def admit(
        self, request: BookFollowupCommand, *, principal: Principal, recovery_source_operation_id: str = ""
    ) -> BookFollowupAdmission:
        from .prose_sampling import PROSE_SAMPLE_DEFINITION

        from .screenplay_sampling import sample_definition_name
        from .screenplay import SCREENPLAY_STAGES
        if request.definition_name == PROSE_SAMPLE_DEFINITION or request.definition_name in {sample_definition_name(stage) for stage in SCREENPLAY_STAGES}:
            from novel_forge.modules.command_kernel.errors import KernelError

            raise KernelError("PROSE_SAMPLE_COMMAND_REQUIRED", "use the native authorized prose sampling command")
        permission = f"book.followup:{request.definition_name}"
        principal.require("book.authority.execute", request.project_id)
        principal.require(permission, request.project_id)
        if request.actor_id != principal.principal_id:
            raise PermissionError("Book follow-up actor must be the trusted Principal")
        recovery = {}
        original_policy = None
        if recovery_source_operation_id:
            from novel_forge.modules.command_kernel.errors import KernelError
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute("""SELECT to_jsonb(operation), attempt.result->>'error_code',
                    EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=operation.operation_id)
                    FROM authority_operation operation JOIN LATERAL (SELECT result FROM authority_attempt
                      WHERE operation_id=operation.operation_id ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
                    WHERE operation.operation_id=%s AND operation.project_id=%s""",
                    [recovery_source_operation_id, request.project_id])
                row = uow.cursor.fetchone()
            source = dict(row[0]) if row else {}
            original_input = dict(source.get("command_payload") or {})
            if (not row or source.get("definition_name") != READER_OUTCOME_DEFINITION
                or source.get("definition_version") != "1.1.0" or source.get("status") != "FAILED_FINAL"
                or row[1] != "READER_OUTCOME_PROVIDER_CONTEXT_VIEW_INVALID" or row[2]
                or request.definition_name != READER_OUTCOME_DEFINITION
                or source.get("workspace_id") != request.workspace_id
                or original_input.get("payload") != request.payload
                or list(source.get("input_asset_snapshot") or []) != list(request.input_assets)
                or request.causation_operation_id != recovery_source_operation_id
                or request.idempotency_key != source.get("idempotency_key", "") + ":contract-successor:" + READER_OUTCOME_DEFINITION_VERSION
                or request.trace_id != source.get("trace_id") or request.correlation_id != source.get("correlation_id")
                or request.root_operation_id is not None or request.parent_operation_id is not None):
                raise KernelError("BOOK_FOLLOWUP_SUCCESSOR_SOURCE_INVALID", "Reader successor requires an exact retained local contract failure with no external dispatch")
            original_policy = request.payload.get("reader_proxy_policy_snapshot")
            recovery = {"contract_version": "reader-contract-successor.v1",
                        "predecessor_operation_id": recovery_source_operation_id,
                        "source_definition_version": "1.1.0", "target_definition_version": READER_OUTCOME_DEFINITION_VERSION,
                        "original_actor_id": source["actor_id"], "frozen_input_snapshot": source["input_asset_snapshot"],
                        "book_budget_reset_allowed": False, "historical_failure_retained": True}
        policy_snapshot = original_policy if original_policy is not None else {} if request.definition_name.startswith("screenplay_") else self.reader_policies.freeze_for_admission(
            project_id=request.project_id,
            idempotency_key=request.idempotency_key,
            actor_id=principal.principal_id,
        )
        definitions = book_followup_operation_definitions(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": request.definition_name,
                "definition_version": READER_OUTCOME_DEFINITION_VERSION if request.definition_name == READER_OUTCOME_DEFINITION else BOOK_FOLLOWUP_DEFINITION_VERSION,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "actor_id": request.actor_id,
                "idempotency_scope": "project:book-followup",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": request.causation_operation_id or "",
                "input": {
                    "project_id": request.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in request.input_assets
                    ],
                    "payload": {
                        **request.payload,
                        "reader_proxy_policy_snapshot": policy_snapshot,
                        **({"followup_contract_recovery": recovery} if recovery else {}),
                    },
                },
                "input_assets": list(request.input_assets),
                "root_operation_id": request.root_operation_id,
                "parent_operation_id": request.parent_operation_id,
                "causation_operation_id": request.causation_operation_id,
            },
            context=AdmissionContext(
                actor_id=request.actor_id,
                permissions=frozenset({permission}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                operation_id, request.project_id
            )
        if state["status"] == "ADMITTED":
            transition_operation(
                self.database_url,
                OperationTransitionCommand(
                    operation_id=operation_id,
                    project_id=request.project_id,
                    expected_version=int(state["version"]),
                    expected_status="ADMITTED",
                    target_status="READY",
                    actor_id=request.actor_id,
                    reason="book follow-up operation ready",
                    trace_id=request.trace_id,
                    correlation_id=request.correlation_id,
                    causation_id="",
                ),
            )
        if request.root_operation_id is None:
            # INVARIANT: follow-ups own a sidecar Saga. They retain acceptance
            # causation but cannot join or delay the production-critical Book Saga.
            start_saga(
                self.database_url,
                GraphCommandContext(
                    request.project_id,
                    request.actor_id,
                    request.trace_id,
                    request.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        return BookFollowupAdmission(
            operation_id=operation_id,
            project_id=request.project_id,
            replayed=bool(admitted["replayed"]),
        )

    def run_or_recover(self, admission: BookFollowupAdmission):
        return ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,  # INVARIANT: shared scheduling cannot create another Attempt runtime.
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=admission.project_id,
        )

    def prepare_screenplay_sample(self, command: Any, *, principal: Principal) -> dict[str, Any]:
        from .screenplay_sampling import prepare_screenplay_sample
        return prepare_screenplay_sample(self, command, principal=principal)

    def admit_screenplay_sample(self, command: Any, *, principal: Principal) -> dict[str, Any]:
        from .screenplay_sampling import admit_screenplay_sample
        return admit_screenplay_sample(self, command, principal=principal)

    def prepare_prose_sample(self, command: Any, *, principal: Principal) -> dict[str, Any]:
        from .prose_sampling import prepare_prose_sample

        return prepare_prose_sample(self, command, principal=principal)

    def admit_prose_sample(self, command: Any, *, principal: Principal) -> dict[str, Any]:
        from .prose_sampling import admit_prose_sample

        return admit_prose_sample(self, command, principal=principal)


__all__ = [
    "BookFollowupAdmission",
    "BookFollowupAuthorityApplication",
    "BookFollowupCommand",
]
