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

from .contracts import BOOK_FOLLOWUP_DEFINITION_VERSION, ReaderOutcomeModelPort
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
        memory_model_port: ReaderOutcomeModelPort | None = None,
        reader_judge_resolver: ReaderJudgeRuntimeResolver | None = None,
        worker_id: str = "book-followup-authority-worker",
        coordinated_reader: bool = False,
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
            memory_model_port,
        )
        self.worker_id = worker_id
        self.coordinated_reader = coordinated_reader
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
        from .contracts import READER_OUTCOME_DEFINITION, READER_OUTCOME_DEFINITION_VERSION
        from .definitions import reader_outcome_definition
        from novel_forge.modules.capability_packs.schema import canonical_json
        from novel_forge.modules.command_kernel.errors import KernelError

        recovery = {}
        original_policy = None
        if recovery_source_operation_id:
            from .reader_recovery import read_reader_recovery_source
            with AuthorityUnitOfWork(self.database_url) as uow:
                source = read_reader_recovery_source(uow.cursor, recovery_source_operation_id, request.project_id)
            source = source or {}
            original = dict(source.get("command_payload") or {})
            if (not source or request.definition_name != READER_OUTCOME_DEFINITION
                or source.get("actor_id") != request.actor_id or source.get("workspace_id") != request.workspace_id
                or canonical_json(original.get("payload")) != canonical_json(request.payload)
                or canonical_json(source.get("input_asset_snapshot")) != canonical_json(list(request.input_assets))
                or request.causation_operation_id != recovery_source_operation_id
                or request.idempotency_key != source.get("idempotency_key", "") + ":contract-successor:" + READER_OUTCOME_DEFINITION_VERSION
                or request.trace_id != source.get("trace_id") or request.correlation_id != source.get("correlation_id")
                or request.root_operation_id is not None or request.parent_operation_id is not None):
                raise KernelError("BOOK_FOLLOWUP_SUCCESSOR_SOURCE_INVALID", "Retain exact original Reader owner, frozen inputs and no-intent failure")
            original_policy = request.payload.get("reader_proxy_policy_snapshot")
            if not isinstance(original_policy, dict):
                raise KernelError("BOOK_FOLLOWUP_SUCCESSOR_SOURCE_INVALID", "Retain the frozen original Reader policy")
            recovery = {"contract_version": "reader-contract-successor.v2",
                        "predecessor_operation_id": recovery_source_operation_id,
                        "source_definition_version": source["definition_version"], "target_definition_version": READER_OUTCOME_DEFINITION_VERSION,
                        "original_actor_id": source["actor_id"], "frozen_input_snapshot": source["input_asset_snapshot"],
                        "book_budget_reset_allowed": False, "historical_failure_retained": True}
        current_reader = request.definition_name == READER_OUTCOME_DEFINITION and (self.coordinated_reader or bool(recovery))
        from .contracts import LONGFORM_RECAP_DEFINITION, LONGFORM_RECAP_DEFINITION_VERSION
        from .definitions import longform_recap_definition
        current_recap = request.definition_name == LONGFORM_RECAP_DEFINITION and self.coordinated_reader
        if current_recap:
            from .accepted_realization import read_accepted_realization_deviations
            from novel_forge.modules.book_authority.reader_pack import require_current_reader_template
            observation = (request.payload.get("observations") or {}).get("accepted_realization_deviations")
            if not isinstance(observation,dict):
                raise KernelError("RECAP_ACCEPTED_REALIZATION_SCOPE_INVALID","Current Recap must carry exact native accepted observations")
            with AuthorityUnitOfWork(self.database_url) as uow:
                require_current_reader_template(uow.cursor,project_id=request.project_id,book_id=request.payload["book_id"])
                actual = read_accepted_realization_deviations(uow.cursor,project_id=request.project_id,
                    workspace_id=request.workspace_id,book_id=request.payload["book_id"],
                    chapter_request_id=str(observation.get("chapter_request_id") or ""),actor_id=request.actor_id)
            if (canonical_json(actual)!=canonical_json(observation)
                or actual["acceptance_operation_id"]!=request.payload.get("acceptance_operation_id")
                or actual["book_production_input_snapshot_id"]!=request.payload.get("book_production_input_snapshot_id")
                or actual["chapter_number"]!=request.payload.get("observed_through_chapter")
                or actual["chapter_number"]!=(request.payload.get("chapter_range") or [None])[-1]):
                raise KernelError("RECAP_ACCEPTED_REALIZATION_EVIDENCE_INVALID","Current Recap observations differ from exact immutable native evidence")
        if current_reader:
            from .reader_recovery import require_reader_book_scope
            with AuthorityUnitOfWork(self.database_url) as uow:
                require_reader_book_scope(uow.cursor, project_id=request.project_id, workspace_id=request.workspace_id,
                    actor_id=request.actor_id, payload=request.payload, source_operation_id=recovery_source_operation_id)
        policy_snapshot = original_policy if original_policy is not None else {} if request.definition_name.startswith("screenplay_") or request.definition_name == "working_memory_extract" else self.reader_policies.freeze_for_admission(
            project_id=request.project_id,
            idempotency_key=request.idempotency_key,
            actor_id=principal.principal_id,
        )
        definitions = book_followup_operation_definitions(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        if current_reader:
            definitions += (reader_outcome_definition(application_build_id=self.application_build_id, commit_sha=self.commit_sha),)
        if current_recap:
            definitions += (longform_recap_definition(application_build_id=self.application_build_id,commit_sha=self.commit_sha),)
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in definitions:
                uow.repositories.definitions.register(definition)
            uow.commit()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": request.definition_name,
                "definition_version": READER_OUTCOME_DEFINITION_VERSION if current_reader else LONGFORM_RECAP_DEFINITION_VERSION if current_recap else BOOK_FOLLOWUP_DEFINITION_VERSION,
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
                        **({"reader_contract_recovery": recovery} if recovery else {}),
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
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute('SELECT definition_name FROM authority_operation WHERE operation_id=%s AND project_id=%s',
                [admission.operation_id,admission.project_id])
            row = uow.cursor.fetchone()
        reconciler = self._reconcile_prose_state if (row and row[0] == 'longform.prose_review'
            and getattr(self.prose_model_port,'adapter',None) is not None) else None
        return ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,  # INVARIANT: shared scheduling cannot create another Attempt runtime.
            worker_id=self.worker_id,
            external_state_reconciler=reconciler,
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=admission.project_id,
        )

    def _reconcile_prose_state(self, worker):
        from novel_forge.modules.command_kernel.errors import KernelError
        from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, reconcile_external_effect
        from novel_forge.modules.production_execution import ExecutionRecoveryAction

        adapter = self.prose_model_port.adapter
        authorize = getattr(adapter,'for_recovery',None)
        if not callable(authorize):
            raise KernelError('MODEL_EFFECT_RECOVERY_AUTHORIZATION_MISSING','Review reconciliation requires the original execution adapter')
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("""SELECT external_effect_id,request_payload FROM authority_external_effect
                WHERE operation_id=%s AND project_id=%s AND effect_type='model.invoke'
                  AND status IN ('DISPATCHING','DISPATCHED','UNKNOWN','RECONCILIATION_REQUIRED')
                ORDER BY created_at,external_effect_id""", [worker.causation_id,worker.project_id])
            effects = uow.cursor.fetchall()
        if not effects:
            raise KernelError('EXTERNAL_EFFECT_RECONCILIATION_REQUIRED','No unresolved original review receipt was found')
        for effect_id,payload in effects:
            metadata = payload.get('_production_execution') or {}
            if (metadata.get('operation_id') != worker.causation_id or metadata.get('attempt_id') != worker.attempt_id
                    or metadata.get('project_id') != worker.project_id or not metadata.get('fencing_token')):
                raise KernelError('MODEL_EFFECT_EXECUTION_IDENTITY_INVALID','Review recovery must retain its original Attempt and execution fence')
            recovery = authorize(execution_id='chapter-execution:'+effect_id,external_effect_id=effect_id,
                operation_id=worker.causation_id,attempt_id=worker.attempt_id,
                execution_fencing_token=int(metadata['fencing_token']),recovery_fencing_token=worker.fencing_token,
                recovery_worker_id=worker.worker_id,action=ExecutionRecoveryAction.QUERY,
                trace_id=worker.trace_id,correlation_id=worker.correlation_id)
            outcome = reconcile_external_effect(self.database_url,EffectCommandContext(worker.causation_id,
                worker.project_id,worker.worker_id,worker.trace_id,worker.correlation_id),
                effect_id=effect_id,adapter=recovery,attempt_command=worker)
            if outcome['outcome'] in {'not_found','failed_final','cancelled'}:
                raise KernelError('CONTENT_RECOVERY_TERMINAL','The original review query settled as '+outcome['outcome'])
            if outcome['outcome'] != 'success':
                raise KernelError('EXTERNAL_EFFECT_RECONCILIATION_REQUIRED','The original review result remains unestablished')

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
