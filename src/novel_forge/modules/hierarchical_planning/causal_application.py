from __future__ import annotations

from typing import Any
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.asset_commands import AuthorityAssetWriteCommand
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.causal_planning_repositories import causal_action_ref
from novel_forge.modules.context_builder.reality_projection import project_role_context
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.causal_planning_repositories import CausalPlanningRepository

from .causal_domain import CandidateFuture, build_causal_plan


CAUSAL_OPERATION = "planning.causal.propose"
CAUSAL_HANDLER = "planning.causal.propose.v1"


def causal_planning_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    properties = {
        key: {"type": "string"}
        for key in (
            "project_id",
            "book_run_id",
            "reality_revision_id",
            "intent_version_id",
        )
    }
    properties.update(
        {
            "chapter_number": {"type": "integer", "minimum": 1},
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": {"type": "object"},
            },
        }
    )
    return {
        "name": CAUSAL_OPERATION,
        "definition_version": "1.0.0",
        "family": "hierarchical_planning",
        "enabled": True,
        "command_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": [
                "plan_digest",
                "reality_revision_id",
                "candidate_futures",
                "causal_debts",
            ],
        },
        "handler_key": CAUSAL_HANDLER,
        "handler_contract_version": "causal-planning-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "book:causal-planning",
        "concurrency_key_template": "book:{book_id}:causal-planning",
        "retry_policy": {"max_attempts": 1, "mode": "client_replay_only"},
        "timeout_policy": {"operation_timeout_seconds": 60},
        "cancellation_policy": {"mode": "not_applicable_atomic_transaction"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable planning proposal",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "execution_classification": "transaction_command",
            "accepted_actual_mutation": False,
            "frozen_input_drift_fails_closed": True,
        },
        "completion_contract": {
            "version": "planning.causal.propose.completion.v1",
            "required_asset_selectors": [],
            "required_qualifications": [],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["planning.causal.proposed"],
        },
    }


class PostgresCausalPlanningApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        fault_injector: TransactionCheckpoint | None = None,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.fault_injector = fault_injector

    def propose(
        self,
        *,
        principal: Principal,
        project_id: str,
        book_run_id: str,
        reality_revision_id: str,
        intent_version_id: str,
        chapter_number: int,
        candidates: list[dict[str, Any]],
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", project_id)
        payload = dict(
            project_id=project_id,
            book_run_id=book_run_id,
            reality_revision_id=reality_revision_id,
            intent_version_id=intent_version_id,
            chapter_number=chapter_number,
            candidates=candidates,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                causal_planning_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        with AuthorityUnitOfWork(self.database_url) as uow:
            repository = CausalPlanningRepository(uow.cursor)
            replay_inputs = repository.frozen_replay_inputs(
                project_id=project_id, idempotency_key=idempotency_key
            )
            if replay_inputs is None:
                reality, refs, workspace_id = repository.require_inputs(
                    project_id=project_id,
                    book_run_id=book_run_id,
                    intent_version_id=intent_version_id,
                    reality_revision_id=reality_revision_id,
                    current=False,
                )
                book_id = reality["book_id"]
            else:
                book_id, workspace_id, refs = replay_inputs
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": CAUSAL_OPERATION,
                "definition_version": "1.0.0",
                "project_id": project_id,
                "workspace_id": workspace_id,
                "book_id": book_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:causal-planning",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "input": payload,
                "input_assets": refs,
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({CAUSAL_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=self._execute,
            fault_injector=self.fault_injector,
        )

    def _execute(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        repository = CausalPlanningRepository(uow.cursor)
        payload = repository.operation_payload(operation_id)
        candidates = tuple(
            CandidateFuture.from_mapping(c) for c in payload["candidates"]
        )
        reality, _, _ = repository.require_inputs(
            cause_refs=tuple(
                sorted(
                    {
                        ref
                        for candidate in candidates
                        for ref in candidate.transition.cause_refs
                    }
                )
            ),
            **{
                key: payload[key]
                for key in (
                    "project_id",
                    "book_run_id",
                    "intent_version_id",
                    "reality_revision_id",
                )
            },
        )
        repository.validate_candidate_references(reality=reality, candidates=candidates)
        result = build_causal_plan(
            reality=reality,
            candidates=candidates,
            chapter_number=payload["chapter_number"],
            intent_revision_id=payload["intent_version_id"],
        )
        result["director_context"] = project_role_context(
            reality=reality,
            role="DIRECTOR",
            token_budget=32768,
            required_event_ids=tuple(
                sorted(
                    {
                        ref
                        for item in payload["candidates"]
                        for ref in item["transition"]["cause_refs"]
                    }
                )
            ),
        )
        result["plan_digest"] = canonical_hash(
            {key: value for key, value in result.items() if key != "plan_digest"}
        )
        logical_ref = causal_action_ref(
            payload["book_run_id"],
            payload["reality_revision_id"],
            payload["chapter_number"],
        )
        current_version = repository.current_action(
            project_id=payload["project_id"],
            book_run_id=payload["book_run_id"],
            reality_revision_id=payload["reality_revision_id"],
            chapter_number=payload["chapter_number"],
            lock=True,
        )
        action = {
            "type": "NarrativeGovernanceAction",
            "contract_version": "causal-planning-action.v1",
            "project_id": payload["project_id"],
            "book_id": reality["book_id"],
            "book_run_id": payload["book_run_id"],
            "reality_revision_id": payload["reality_revision_id"],
            "accepted_through_chapter": reality["chapter_number"],
            "chapter_number": payload["chapter_number"],
            "authority": "PLANNING_PROPOSAL",
            "causal_plan": result,
            "constraints": [
                {
                    "kind": "CAUSAL_PREPARATION",
                    "plan_digest": result["plan_digest"],
                    "selected_candidate_id": result["selected_candidate_id"],
                    "candidate_futures": result["candidate_futures"],
                    "causal_debts": result["causal_debts"],
                }
            ],
            "preserve_accepted_history": True,
        }
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=operation_id,
                project_id=payload["project_id"],
                asset_id="causal-action:" + canonical_hash(logical_ref),
                asset_type="narrative_governance_action",
                schema_version="causal-planning-action.v1",
                logical_ref=logical_ref,
                category="planning",
                output_key="planning.causal.action",
                role="primary",
                content=action,
                qualification_policy="causal-candidate-contract.v1",
                trace_id=operation_id,
                correlation_id=operation_id,
                expected_current_asset_version_id=current_version,
            )
        )
        result["governance_action_version_id"] = document.asset_version_id
        checkpoint("after_causal_validation")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "causal_plan",
                "aggregate_id": result["plan_digest"],
                "operation_id": operation_id,
                "project_id": payload["project_id"],
                "event_type": "planning.causal.proposed",
                "correlation_id": operation_id,
                "causation_id": operation_id,
                "payload": {
                    "operation_id": operation_id,
                    "project_id": payload["project_id"],
                    "plan_digest": result["plan_digest"],
                    "reality_revision_id": result["reality_revision_id"],
                    "selected_candidate_id": result["selected_candidate_id"],
                },
            }
        )
        checkpoint("after_causal_proposal_event")
        return result
