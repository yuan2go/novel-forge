"""Command application using the shared Authority Attempt/runtime."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from novel_forge.modules.authority_handler_runtime import (
    AuthorityHandlerRegistration,
    AuthorityMaterializedOutput,
)
from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import AdmissionContext, admit_command
from novel_forge.modules.content_authority.scheduler import ContentAuthorityScheduler
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import (
    CHAPTER_OUTCOME_COMMIT_DEFINITION,
    CHAPTER_OUTCOME_DEFINITION_VERSION,
    CHAPTER_OUTCOME_HANDLER_KEY,
)
from .handlers import ChapterOutcomeCommitHandler


@dataclass(frozen=True, slots=True)
class ChapterOutcomeCommand:
    project_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    payload: dict[str, Any]
    input_assets: tuple[dict[str, str], ...]
    root_operation_id: str | None = None
    parent_operation_id: str | None = None
    causation_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChapterOutcomeAdmission:
    operation_id: str
    project_id: str
    replayed: bool


class _ChapterOutcomeRegistry:
    def __init__(self) -> None:
        self._registration = AuthorityHandlerRegistration(
            definition_name=CHAPTER_OUTCOME_COMMIT_DEFINITION,
            definition_version=CHAPTER_OUTCOME_DEFINITION_VERSION,
            handler_key=CHAPTER_OUTCOME_HANDLER_KEY,
            handler_contract_version="chapter-outcome-handler-v1",
            output_asset_type="chapter_outcome",
            output_key="chapter.outcome",
            role="primary",
            completion_topic="book.chapter.accepted",
            handler=ChapterOutcomeCommitHandler(),
        )

    def registration(
        self, definition_name: str, definition_version: str
    ) -> AuthorityHandlerRegistration:
        if (
            definition_name != CHAPTER_OUTCOME_COMMIT_DEFINITION
            or definition_version != CHAPTER_OUTCOME_DEFINITION_VERSION
        ):
            raise KeyError(definition_name)
        return self._registration

    @property
    def available_handler_keys(self) -> frozenset[str]:
        return frozenset({CHAPTER_OUTCOME_HANDLER_KEY})


class ChapterOutcomeAuthorityApplication:
    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        worker_id: str = "chapter-outcome-worker",
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.worker_id = worker_id
        self.registry = _ChapterOutcomeRegistry()
        self.failure_injector = failure_injector

    def admit(
        self, command: ChapterOutcomeCommand, *, principal: Principal
    ) -> ChapterOutcomeAdmission:
        principal.require("book.authority.execute", command.project_id)
        definition = chapter_outcome_operation_definition(
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(definition)
            uow.commit()
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": CHAPTER_OUTCOME_COMMIT_DEFINITION,
                "definition_version": CHAPTER_OUTCOME_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:book-chapter-acceptance",
                "idempotency_key": command.idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": command.causation_operation_id or "",
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": [
                        item["asset_version_id"] for item in command.input_assets
                    ],
                    "payload": command.payload,
                },
                "input_assets": list(command.input_assets),
                "root_operation_id": command.root_operation_id,
                "parent_operation_id": command.parent_operation_id,
                "causation_operation_id": command.causation_operation_id,
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=self.registry.available_handler_keys,
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
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
                    actor_id=principal.principal_id,
                    reason="Chapter acceptance evidence is frozen",
                    trace_id=command.trace_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.causation_operation_id or "",
                ),
            )
        if command.root_operation_id is None:
            from novel_forge.modules.command_kernel.operation_graph import (
                GraphCommandContext,
                start_saga,
            )

            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    principal.principal_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=operation_id,
            )
        return ChapterOutcomeAdmission(
            operation_id=operation_id,
            project_id=command.project_id,
            replayed=bool(admitted["replayed"]),
        )

    def run_or_recover(self, admission: ChapterOutcomeAdmission):
        result = ContentAuthorityScheduler(
            self.database_url,
            registry=self.registry,
            worker_id=self.worker_id,
        ).run_or_recover(
            operation_id=admission.operation_id,
            project_id=admission.project_id,
        )
        materialized = (
            result.output.materialized_outputs
            or self.require_materialized_outputs(
                operation_id=admission.operation_id,
                project_id=admission.project_id,
            )
        )
        by_type = {item.asset_type: item for item in materialized}
        story_state = by_type.get("story_state_snapshot")
        if story_state is None:
            return result
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT content
                FROM authority_asset_version
                WHERE asset_version_id=%s
                """,
                [story_state.asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise RuntimeError("materialized Story State content is missing")
        applications = list((row[0] or {}).get("reducer_applications") or [])
        if self.failure_injector is not None:
            self.failure_injector("before_reducer")
        for index, application in enumerate(applications):
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.repositories.story_state.record_reducer_applications(
                    project_id=admission.project_id,
                    story_state_asset_version_id=story_state.asset_version_id,
                    applications=[dict(application)],
                )
                uow.commit()
            if (
                self.failure_injector is not None
                and index + 1 == max(1, len(applications) // 2)
            ):
                self.failure_injector("mid_reducer")
        return result

    def require_materialized_outputs(
        self, *, operation_id: str, project_id: str
    ) -> tuple[AuthorityMaterializedOutput, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT binding.asset_id, binding.asset_version_id,
                       asset.asset_type, binding.output_key, binding.role,
                       binding.content_hash
                FROM authority_operation_output_asset AS binding
                JOIN authority_asset AS asset
                  ON asset.asset_id=binding.asset_id
                 AND asset.project_id=%s
                WHERE binding.operation_id=%s
                ORDER BY binding.created_at, binding.output_key
                """,
                [project_id, operation_id],
            )
            rows = uow.cursor.fetchall()
        return tuple(
            AuthorityMaterializedOutput(
                asset_id=str(row[0]),
                asset_version_id=str(row[1]),
                asset_type=str(row[2]),
                output_key=str(row[3]),
                role=str(row[4]),
                content_hash=str(row[5]),
                replayed=True,
            )
            for row in rows
        )


def chapter_outcome_operation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    command_schema = {
        "type": "object",
        "required": ["project_id", "input_asset_version_ids", "payload"],
        "properties": {
            "project_id": {"type": "string"},
            "input_asset_version_ids": {"type": "array"},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    return {
        "name": CHAPTER_OUTCOME_COMMIT_DEFINITION,
        "definition_version": CHAPTER_OUTCOME_DEFINITION_VERSION,
        "family": "book_authority",
        "command_schema_version": "book.chapter.accept.command.v1",
        "result_schema_version": "book.chapter.accept.result.v1",
        "enabled": True,
        "definition_status": "integration_proven",
        "command_schema": command_schema,
        "result_schema": {"type": "object"},
        "input_contract": command_schema,
        "output_contract": {
            "asset_type": "chapter_outcome",
            "output_key": "chapter.outcome",
            "auxiliary_asset_types": ["story_state_snapshot", "canon_snapshot"],
        },
        "handler_key": CHAPTER_OUTCOME_HANDLER_KEY,
        "handler_contract_version": "chapter-outcome-handler-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "worker",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "frozen_inputs_required": True,
            "chapter_acceptance_evidence_required": True,
            "deterministic_story_state_reducer": True,
            "body_mutation_allowed": False,
        },
        "idempotency_scope": "project:book-chapter-acceptance",
        "concurrency_key_template": "project:{project_id}:book-chapter-acceptance",
        "retry_policy": {"max_attempts": 2},
        "timeout_policy": {"operation_timeout_seconds": 120},
        "cancellation_policy": {"mode": "cancel_active_attempt"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only ChapterOutcome and Story State",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["book_authority_checkpoint"],
        "migration_owner": "chapter-outcome-authority",
        "completion_contract": {
            "version": "book.chapter.accept.completion.v1",
            "required_asset_selectors": [
                {
                    "selector": "chapter_outcome",
                    "output_key": "chapter.outcome",
                    "role": "primary",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
                {
                    "selector": "story_state_snapshot",
                    "output_key": "chapter.story_state",
                    "role": "story_state",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
                {
                    "selector": "canon_snapshot",
                    "output_key": "chapter.canon.current",
                    "role": "canon_truth",
                    "lifecycle": "ACTIVE",
                    "eligibility": "ELIGIBLE",
                    "governance": "CLEAR",
                },
            ],
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["book.chapter.accepted"],
        },
    }


__all__ = [
    "ChapterOutcomeAdmission",
    "ChapterOutcomeAuthorityApplication",
    "ChapterOutcomeCommand",
    "chapter_outcome_operation_definition",
]
