"""Book + BookDesign commands through the shared Command Kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority.definitions import (
    BOOK_DESIGN_DEFINITION_VERSION,
    BOOK_DESIGN_HANDLER_KEY,
    BOOK_DESIGN_OPERATIONS,
    book_design_definitions,
)
from novel_forge.modules.book_design_authority.domain import (
    BookDesignPayload,
    BookScope,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
    NarrativeSemanticEvaluationExecutionPort,
)
from novel_forge.modules.story_design_authority.qualification import (
    required_qualification_profiles,
    scripted_qualification,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_design_authority_repositories import (
    BookDesignAuthorityRepository,
)


@dataclass(frozen=True, slots=True)
class BookDesignAuthorityCommand:
    definition_name: str
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    service_identity: str
    idempotency_key: str
    trace_id: str
    correlation_id: str
    payload: dict[str, Any]
    expected_book_version: int = 0
    expected_current_design_asset_version_id: str = ""
    target_asset_version_id: str = ""

    def __post_init__(self) -> None:
        if self.definition_name not in BOOK_DESIGN_OPERATIONS:
            raise ValueError(
                f"unsupported BookDesign Authority operation: {self.definition_name}"
            )
        for field in (
            "project_id",
            "workspace_id",
            "book_id",
            "actor_id",
            "service_identity",
            "idempotency_key",
            "trace_id",
            "correlation_id",
        ):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"{field} is required")
        if self.expected_book_version < 0:
            raise ValueError("expected_book_version cannot be negative")


class BookDesignAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: TransactionCheckpoint | None = None,
        semantic_evaluation_execution_port: NarrativeSemanticEvaluationExecutionPort
        | None = None,
        allow_scripted_evaluation_fixture: bool = False,
        narrative_evaluator_principal: Principal | None = None,
    ) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector
        self.allow_scripted_evaluation_fixture = allow_scripted_evaluation_fixture
        self.narrative_evaluator_principal = narrative_evaluator_principal
        self.semantic_evaluation = NarrativeSemanticEvaluationApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="book-design-semantic-evaluation-worker",
            execution_port=semantic_evaluation_execution_port,
            allow_scripted_fixture=allow_scripted_evaluation_fixture,
        )

    def execute(
        self, command: BookDesignAuthorityCommand, *, principal: Principal | None = None
    ) -> dict[str, Any]:
        actor_id = command.actor_id
        if principal is not None:
            principal.require("book_design.authority.execute", command.project_id)
            actor_id = principal.principal_id
        self._register_definitions()
        if (
            command.definition_name == "book_design.activate"
            and not self.allow_scripted_evaluation_fixture
        ):
            self._require_model_provider_qualification(
                project_id=command.project_id,
                book_id=command.book_id,
                asset_version_id=command.target_asset_version_id,
            )
        command_input = {
            "project_id": command.project_id,
            "workspace_id": command.workspace_id,
            "book_id": command.book_id,
            "service_identity": command.service_identity,
            "expected_book_version": command.expected_book_version,
            "expected_current_design_asset_version_id": command.expected_current_design_asset_version_id,
            "target_asset_version_id": command.target_asset_version_id,
            "payload": dict(command.payload),
        }
        input_assets: list[dict[str, str]] = []
        if command.target_asset_version_id:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT version.content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                    WHERE version.asset_version_id = %s AND asset.project_id = %s
                    """,
                    [command.target_asset_version_id, command.project_id],
                )
                row = uow.cursor.fetchone()
                if row is None:
                    raise KernelError(
                        "BOOK_DESIGN_CANDIDATE_NOT_FOUND",
                        "target AssetVersion is outside project scope",
                    )
                input_assets.append(
                    {
                        "asset_version_id": command.target_asset_version_id,
                        "content_hash": row[0],
                    }
                )
        context = AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset({"book_design.authority.execute"}),
            available_handlers=frozenset({BOOK_DESIGN_HANDLER_KEY}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": command.definition_name,
                "definition_version": BOOK_DESIGN_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": actor_id,
                "idempotency_scope": "book:design",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": command_input,
                "input_assets": input_assets,
            },
            context=context,
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )
        if (
            command.definition_name == "book_design.propose"
            and self.narrative_evaluator_principal is not None
            and (semantic_port := self.semantic_evaluation.execution_port) is not None
        ):
            candidate_id = str(result.get("asset_version_id") or "")
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT content_hash
                    FROM authority_asset_version AS version
                    JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                    WHERE version.asset_version_id=%s AND asset.project_id=%s
                    """,
                    [candidate_id, command.project_id],
                )
                row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "BOOK_DESIGN_CANDIDATE_NOT_FOUND",
                    "new BookDesign candidate is not readable for evaluation",
                )
            real_provider = bool(
                getattr(semantic_port, "real_provider_execution", False)
            )
            if not real_provider and not self.allow_scripted_evaluation_fixture:
                raise KernelError(
                    "NARRATIVE_EVALUATION_REAL_PROVIDER_REQUIRED",
                    "BookDesign production evaluation has no real Provider route",
                )
            evaluation = self.evaluate_semantics(
                NarrativeSemanticEvaluationCommand(
                    project_id=command.project_id,
                    workspace_id=command.workspace_id,
                    book_id=command.book_id,
                    actor_id=self.narrative_evaluator_principal.principal_id,
                    candidate_asset_version_id=candidate_id,
                    generation_operation_id=str(result.get("operation_id") or ""),
                    generator_operation_name="book_design.propose",
                    candidate_content_hash=str(row[0]),
                    evaluator_execution_class=(
                        "MODEL_PROVIDER" if real_provider else "SCRIPTED_FIXTURE"
                    ),
                    evaluation=(
                        None
                        if real_provider
                        else scripted_qualification("book_design.propose")
                    ),
                    idempotency_key=f"{command.idempotency_key}:semantic-evaluation",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                ),
                principal=self.narrative_evaluator_principal,
            )
            return {**result, "semantic_evaluation": evaluation}
        return result

    def _require_model_provider_qualification(
        self,
        *,
        project_id: str,
        book_id: str,
        asset_version_id: str,
    ) -> None:
        expected_layers = {
            profile.layer.value
            for profile in required_qualification_profiles("book_design.propose")
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT design_layer
                FROM authority_narrative_design_qualification
                WHERE project_id=%s AND book_id=%s AND asset_version_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                  AND evaluator_execution_class='MODEL_PROVIDER'
                  AND provider_model_call_asset_version_id IS NOT NULL
                  AND provider_model_call_content_hash IS NOT NULL
                  AND provider_evidence_hash IS NOT NULL
                  AND provider_result_hash IS NOT NULL
                  AND provider_route_snapshot_id IS NOT NULL
                """,
                [project_id, book_id, asset_version_id],
            )
            layers = {str(row[0]) for row in uow.cursor.fetchall()}
        if layers != expected_layers:
            raise KernelError(
                "NARRATIVE_EVALUATION_REAL_PROVIDER_REQUIRED",
                "BookDesign activation requires current real-Provider qualification",
            )

    def evaluate_semantics(
        self,
        command: NarrativeSemanticEvaluationCommand,
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        """Evaluate one immutable BookDesign candidate in a separate Attempt."""

        if command.generator_operation_name != "book_design.propose":
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_STAGE_INVALID",
                "BookDesign Authority can evaluate only BookDesign candidates",
            )
        result = self.semantic_evaluation.execute(
            command,
            principal=principal,
            caller_permission="book_design.authority.execute",
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = BookDesignAuthorityRepository(uow.cursor)
            book = repository.book_for_update(
                project_id=command.project_id,
                workspace_id=command.workspace_id,
                book_id=command.book_id,
            )
            projection = repository.complete_semantic_evaluation(
                book=book,
                asset_version_id=command.candidate_asset_version_id,
                generation_operation_id=command.generation_operation_id,
                evaluation_operation_id=result.lineage.evaluation_operation_id,
                passed=result.qualification.status == "PASS",
            )
            uow.commit()
        return {
            **projection,
            "generation_operation_id": result.lineage.generation_operation_id,
            "evaluation_operation_id": result.lineage.evaluation_operation_id,
            "evaluation_attempt_id": result.lineage.evaluation_attempt_id,
            "evaluation_asset_version_id": (result.lineage.evaluation_asset_version_id),
            "evaluation_evidence_hash": (result.lineage.evaluation_evidence_hash),
            "qualification_status": result.qualification.status,
            "trust_boundary": "INDEPENDENT",
            "replayed": result.replayed,
        }

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for definition in book_design_definitions(
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ):
                uow.repositories.definitions.register(definition)
            uow.commit()

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        project_id = self._project_for_operation(uow, operation_id)
        operation = uow.repositories.chapter_authority.operation_execution(
            operation_id, project_id
        )
        payload = dict(operation["command_payload"])
        action = str(operation["definition_name"])
        project_id = str(payload["project_id"])
        workspace_id = str(payload["workspace_id"])
        book_id = str(payload["book_id"])
        actor_id = str(operation["actor_id"])
        repository = BookDesignAuthorityRepository(uow.cursor)
        result: dict[str, Any] = {"book_id": book_id}
        if action == "book.create":
            scope = BookScope.from_mapping(
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                principal=actor_id,
                service_identity=str(payload["service_identity"]),
                payload=dict(payload["payload"]),
            )
            content = scope.content(title=str(payload["payload"].get("title") or ""))
            checkpoint("after_domain_validation")
            document = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id=f"book:{book_id}",
                    asset_type="book_record",
                    schema_version="book-authority.v1",
                    logical_ref=f"books/{book_id}",
                    category="books",
                    output_key="book.record",
                    role="primary",
                    content=content,
                    qualification_policy="book-authority-v1",
                    trace_id=str(operation["trace_id"]),
                    correlation_id=str(operation["correlation_id"]),
                    causation_id=operation_id,
                )
            )
            checkpoint("after_asset_version_insert")
            repository.create_book(
                scope=scope,
                book_asset_version_id=document.asset_version_id,
                operation_id=operation_id,
            )
            checkpoint("after_business_projection_update")
            result["asset_version_id"] = document.asset_version_id
            result["content_hash"] = document.content_hash
        else:
            book = repository.book_for_update(
                project_id=project_id, workspace_id=workspace_id, book_id=book_id
            )
            expected_version = int(payload["expected_book_version"])
            expected_design = str(
                payload.get("expected_current_design_asset_version_id") or ""
            )
            if (
                expected_version != book["version"]
                or expected_design != book["current_design_asset_version_id"]
            ):
                raise KernelError(
                    "BOOK_VERSION_CONFLICT", "expected Book/design version is stale"
                )
            if action == "book_design.propose":
                design = BookDesignPayload.from_mapping(dict(payload["payload"]))
                checkpoint("after_domain_validation")
                result.update(
                    repository.propose(
                        book=book,
                        design=design,
                        operation_id=operation_id,
                        trace_id=str(operation["trace_id"]),
                        checkpoint=checkpoint,
                    )
                )
                checkpoint("after_business_projection_update")
            elif action == "book_design.decide":
                target = str(payload.get("target_asset_version_id") or "")
                checkpoint("after_domain_validation")
                result["asset_version_id"] = target
                result["decision_id"] = repository.decide(
                    book=book,
                    asset_version_id=target,
                    decision=str(payload["payload"].get("decision") or ""),
                    reason=str(payload["payload"].get("reason") or ""),
                    decided_by=actor_id,
                    operation_id=operation_id,
                )
                checkpoint("after_business_projection_update")
            elif action == "book_design.activate":
                target = str(payload.get("target_asset_version_id") or "")
                checkpoint("after_domain_validation")
                result["asset_version_id"] = target
                result.update(
                    repository.activate(
                        book=book,
                        asset_version_id=target,
                        reason=str(payload["payload"].get("reason") or ""),
                        operation_id=operation_id,
                    )
                )
                checkpoint("after_business_projection_update")
            else:
                raise KernelError(
                    "BOOK_DESIGN_COMMAND_INVALID", f"unsupported action: {action}"
                )
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "authority_book",
                "aggregate_id": book_id,
                "operation_id": operation_id,
                "project_id": project_id,
                "event_type": f"authority.{action}.committed",
                "correlation_id": str(operation["correlation_id"]),
                "causation_id": operation_id,
                "payload": {
                    **result,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "workspace_id": workspace_id,
                    "trace_id": str(operation["trace_id"]),
                    "execution_classification": "transaction_command",
                },
            }
        )
        checkpoint("after_outbox_insert")
        return result

    @staticmethod
    def _project_for_operation(uow: AuthorityUnitOfWork, operation_id: str) -> str:
        uow.cursor.execute(
            "SELECT project_id FROM authority_operation WHERE operation_id = %s",
            [operation_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("OPERATION_NOT_FOUND", "BookDesign Operation disappeared")
        return str(row[0])


__all__ = ["BookDesignAuthorityApplication", "BookDesignAuthorityCommand"]
