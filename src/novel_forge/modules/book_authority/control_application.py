from __future__ import annotations

from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.authority_handler_runtime.policy_commands import (
    configure_owned_policy,
    owned_policy_definition,
)
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.narrative_state.reality import narrative_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.book_control_repositories import (
    BookControlRepository,
    control_decision_ref,
)
from .control_policy import CONTROL_BOUNDARIES, CONTROL_POLICY_OWNER, ControlPolicy


CONTROL_DECISION_OPERATION = "book.control.decide"
CONTROL_DECISION_HANDLER = "novel_forge.book.control.decide.v1"


def control_policy_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    return owned_policy_definition(
        owner=CONTROL_POLICY_OWNER,
        content=ControlPolicy().to_dict(),
        application_build_id=application_build_id,
        commit_sha=commit_sha,
    )


def control_decision_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    definition = control_policy_definition(
        application_build_id=application_build_id, commit_sha=commit_sha
    )
    properties = {
        key: {"type": "string", "minLength": 1}
        for key in (
            "project_id",
            "book_run_id",
            "boundary",
            "subject_version_id",
            "decision",
            "reason",
        )
    }
    properties["boundary"] = {"type": "string", "enum": sorted(CONTROL_BOUNDARIES)}
    properties["decision"] = {"type": "string", "enum": ["APPROVE", "REJECT"]}
    properties["chapter_number"] = {"type": "integer", "minimum": 1}
    schema = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    definition.update(
        name=CONTROL_DECISION_OPERATION,
        definition_version="1.0.0",
        family="book_control",
        command_schema=schema,
        input_contract=schema,
        command_schema_version="book-control-decision-command.v1",
        result_schema={
            "type": "object",
            "required": [
                "decision_version_id",
                "decision",
                "subject_version_id",
                "policy_hash",
            ],
        },
        output_contract={"type": "EditorialDecisionEvidence"},
        result_schema_version="book-control-decision-result.v1",
        handler_key=CONTROL_DECISION_HANDLER,
        handler_contract_version="book-control-decision.v1",
        idempotency_scope="book:editorial-decision",
        concurrency_key_template="book:{book_id}:editorial-decision",
        completion_contract={
            "version": "book-control-decision-completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": [CONTROL_DECISION_OPERATION],
        },
        policy={
            "execution_classification": "transaction_command",
            "fact_mutation_allowed": False,
            "authenticated_operator_required": True,
        },
    )
    return definition


class PostgresBookControlApplication:
    def __init__(
        self, database_url: str, *, application_build_id: str, commit_sha: str
    ) -> None:
        self.database_url, self.application_build_id, self.commit_sha = (
            database_url,
            application_build_id,
            commit_sha,
        )

    def configure(self, *, policy: ControlPolicy, **command: Any) -> dict[str, Any]:
        return configure_owned_policy(
            database_url=self.database_url,
            owner=CONTROL_POLICY_OWNER,
            content=policy.to_dict(),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
            **command,
        )

    def readiness(self, *, project_id: str, book_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return BookControlRepository(uow.cursor).readiness(
                project_id=project_id, book_run_id=book_run_id
            )

    def require_approvals(
        self,
        *,
        project_id: str,
        book_run_id: str,
        chapter_number: int,
        actor_id: str,
        subjects: dict[str, str],
    ) -> tuple[dict[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            BookControlRepository(uow.cursor).freeze(
                project_id=project_id,
                book_run_id=book_run_id,
                chapter_number=chapter_number,
                actor_id=actor_id,
            )
            uow.commit()
        with AuthorityUnitOfWork(self.database_url) as uow:
            refs = tuple(
                ref
                for boundary, subject in subjects.items()
                for ref in BookControlRepository(uow.cursor).require_approval(
                    project_id=project_id,
                    book_run_id=book_run_id,
                    chapter_number=chapter_number,
                    actor_id=actor_id,
                    boundary=boundary,
                    subject_version_id=subject,
                )
            )
        return refs

    def require_causal_approval(
        self,
        *,
        project_id: str,
        book_run_id: str,
        chapter_number: int,
        actor_id: str,
        subject_version_id: str,
    ) -> tuple[dict[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            subjects = BookControlRepository(uow.cursor).causal_subjects(
                project_id=project_id,
                book_run_id=book_run_id,
                chapter_number=chapter_number,
                subject_version_id=subject_version_id,
            )
        if subjects.get("DIRECTOR") != subject_version_id:
            raise KernelError(
                "BOOK_CONTROL_SUBJECT_STALE",
                "Director approval must bind the current Reality-bound causal plan",
            )
        return self.require_approvals(
            project_id=project_id,
            book_run_id=book_run_id,
            chapter_number=chapter_number,
            actor_id=actor_id,
            subjects=subjects,
        )

    def decide(
        self,
        *,
        principal: Principal,
        project_id: str,
        book_run_id: str,
        chapter_number: int,
        boundary: str,
        subject_version_id: str,
        decision: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise PermissionError(
                "editorial approval requires an authenticated operator; an Agent cannot approve itself"
            )
        if (
            boundary not in CONTROL_BOUNDARIES
            or decision not in {"APPROVE", "REJECT"}
            or not reason.strip()
        ):
            raise KernelError(
                "BOOK_CONTROL_DECISION_INVALID",
                "Editorial evidence needs a declared boundary, decision and reason",
            )
        payload = dict(
            project_id=project_id,
            book_run_id=book_run_id,
            chapter_number=chapter_number,
            boundary=boundary,
            subject_version_id=subject_version_id,
            decision=decision,
            reason=reason,
        )
        definition = control_decision_definition(
            application_build_id=self.application_build_id, commit_sha=self.commit_sha
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            repository = BookControlRepository(uow.cursor)
            book = repository.book_scope(book_run_id, project_id=project_id)
            source = repository.subject(
                project_id=project_id, version_id=subject_version_id
            )
            uow.commit()

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            repository = BookControlRepository(uow.cursor)
            current = repository.book_scope(book_run_id, project_id=project_id)
            if chapter_number <= current["accepted_through_chapter"]:
                raise KernelError(
                    "BOOK_CONTROL_HISTORY_IMMUTABLE",
                    "Editorial intervention cannot rewrite an accepted chapter",
                )
            snapshot = repository.freeze(
                project_id=project_id,
                book_run_id=book_run_id,
                chapter_number=chapter_number,
                actor_id=principal.principal_id,
            )
            logical_ref = control_decision_ref(
                book_run_id,
                chapter_number,
                boundary,
                subject_version_id,
                snapshot["policy_hash"],
            )
            previous = repository.current_decision(
                project_id=project_id, logical_ref=logical_ref
            )
            content = {
                "type": "EditorialDecisionEvidence",
                "contract_version": "book-control-decision.v1",
                **payload,
                "book_id": book["book_id"],
                "operator_id": principal.principal_id,
                "operator_type": principal.principal_type.value,
                "policy_snapshot": snapshot,
                "accepted_through_chapter": current["accepted_through_chapter"],
                "fact_mutation_allowed": False,
            }
            artifact = uow.repositories.asset_documents.materialize_output(
                AuthorityAssetWriteCommand(
                    operation_id=operation_id,
                    project_id=project_id,
                    asset_id="editorial-decision:" + narrative_hash(logical_ref),
                    asset_type="editorial_decision_evidence",
                    schema_version="book-control-decision.v1",
                    logical_ref=logical_ref,
                    category="approval",
                    output_key="book.control.decision",
                    role="primary",
                    content=content,
                    qualification_policy="authenticated-editorial-decision.v1",
                    trace_id=trace_id,
                    correlation_id=correlation_id,
                    expected_current_asset_version_id=previous["asset_version_id"]
                    if previous
                    else None,
                )
            )
            checkpoint("after_editorial_decision")
            result = {
                "decision_version_id": artifact.asset_version_id,
                "subject_version_id": subject_version_id,
                "decision": decision,
                "policy_hash": snapshot["policy_hash"],
            }
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "book_control",
                    "aggregate_id": book_run_id,
                    "operation_id": operation_id,
                    "project_id": project_id,
                    "event_type": CONTROL_DECISION_OPERATION,
                    "correlation_id": correlation_id,
                    "causation_id": operation_id,
                    "payload": {"operation_id": operation_id, **result},
                }
            )
            return result

        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": CONTROL_DECISION_OPERATION,
                "definition_version": "1.0.0",
                "project_id": project_id,
                "workspace_id": book["workspace_id"],
                "book_id": book["book_id"],
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:editorial-decision",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "input": payload,
                "input_assets": [source],
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({CONTROL_DECISION_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=handler,
            fault_injector=fault_injector,
        )
