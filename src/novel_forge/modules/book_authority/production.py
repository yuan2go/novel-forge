from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from enum import StrEnum
import hashlib
import json
from typing import Any, Callable, Protocol
from uuid import uuid4

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_followup_authority.application import (
    BookFollowupAdmission,
    BookFollowupAuthorityApplication,
    BookFollowupCommand,
)
from novel_forge.modules.book_followup_authority.contracts import (
    LONGFORM_RECAP_DEFINITION,
    READER_OUTCOME_DEFINITION,
)
from novel_forge.modules.chapter_authority.application import (
    ChapterAuthorityApplication,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSagaAdmission,
    SingleChapterRequest,
)
from novel_forge.modules.chapter_outcome import (
    ChapterOutcomeAuthorityApplication,
    ChapterOutcomeCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.cancellation import (
    CancelCommand,
    request_cancellation,
)
from novel_forge.modules.command_kernel.external_effect_runtime import (
    cancel_operation_external_effects,
)
from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapter,
)
from novel_forge.modules.command_kernel.operation_graph import (
    GraphCommandContext,
    coordinate_saga,
    register_saga_step,
    start_saga,
    transition_saga_gate,
)
from novel_forge.modules.command_kernel.runtime import (
    OperationTransitionCommand,
    transition_operation,
)
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    admit_command,
    execute_transaction_command,
)
from novel_forge.modules.book_authority.longform_projection import (
    AcceptedLongformEvidence,
    frozen_arc_plan_version_ids,
    project_accepted_longform,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.narrative_realization_repositories import (
    NarrativeRealizationRepository,
)


BOOK_COORDINATE_DEFINITION = "book.production.coordinate"
BOOK_COORDINATE_DEFINITION_VERSION = "1.0.0"
BOOK_COORDINATE_HANDLER = "novel_forge.book_authority.coordinator"
BOOK_MUTATION_DEFINITION = "book.authority.mutate"
BOOK_MUTATION_DEFINITION_VERSION = "1.0.0"
BOOK_MUTATION_HANDLER = "novel_forge.book_authority.mutate"
LONGFORM_CONTEXT_VERSION_KEYS = frozenset(
    {
        "volume_plan_version",
        "arc_plan_versions",
        "character_state_version",
        "foreshadowing_state_version",
        "quality_trend_version",
        "reward_ledger_version",
        "promise_ledger_version",
        "reader_segment_version",
        "reader_contract_version",
        "platform_profile_version",
    }
)


class BookProductionState(StrEnum):
    INPUT_RESOLUTION_REQUIRED = "INPUT_RESOLUTION_REQUIRED"
    PLANNING_REQUIRED = "PLANNING_REQUIRED"
    PLAN_GENERATING = "PLAN_GENERATING"
    PLAN_APPROVAL_PENDING = "PLAN_APPROVAL_PENDING"
    READY = "READY"
    CHAPTER_GROUP_REQUIRED = "CHAPTER_GROUP_REQUIRED"
    CHAPTER_PLAN_REQUIRED = "CHAPTER_PLAN_REQUIRED"
    CHAPTER_SUBMITTED = "CHAPTER_SUBMITTED"
    CHAPTER_RUNNING = "CHAPTER_RUNNING"
    CHAPTER_WAITING_RETRY = "CHAPTER_WAITING_RETRY"
    CHAPTER_COMPLETED = "CHAPTER_COMPLETED"
    CHAPTER_ACCEPTANCE_PENDING = "CHAPTER_ACCEPTANCE_PENDING"
    CHAPTER_FAILED_RETRYABLE = "CHAPTER_FAILED_RETRYABLE"
    CHAPTER_FAILED_TERMINAL = "CHAPTER_FAILED_TERMINAL"
    CANON_PENDING = "CANON_PENDING"
    CANON_COMMITTED = "CANON_COMMITTED"
    READER_OUTCOME_PENDING = "READER_OUTCOME_PENDING"
    FOLLOWUP_PENDING = "FOLLOWUP_PENDING"
    CHECKPOINT_PENDING = "CHECKPOINT_PENDING"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    REPLAN_GENERATING = "REPLAN_GENERATING"
    REPLAN_APPROVAL_PENDING = "REPLAN_APPROVAL_PENDING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class BookProductionStateClass(StrEnum):

    ACTIONABLE = "ACTIONABLE"
    DURABLE_WAIT = "DURABLE_WAIT"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True, slots=True)
class BookProductionStateSemantics:
    state_class: BookProductionStateClass
    next_expected_transition: str
    blocking_class: str
    blocking_reason: str
    wake_condition: str


def _state_semantics(
    state_class: BookProductionStateClass,
    next_expected_transition: str,
    *,
    blocking_class: str = "PRODUCTION_CRITICAL_WORK",
    blocking_reason: str = (
        "production-critical transition is active or eligible for worker execution"
    ),
    wake_condition: str = "BOOK_WORKER_TICK",
) -> BookProductionStateSemantics:
    return BookProductionStateSemantics(
        state_class=state_class,
        next_expected_transition=next_expected_transition,
        blocking_class=blocking_class,
        blocking_reason=blocking_reason,
        wake_condition=wake_condition,
    )


BOOK_PRODUCTION_STATE_SEMANTICS: dict[
    BookProductionState, BookProductionStateSemantics
] = {
    BookProductionState.INPUT_RESOLUTION_REQUIRED: _state_semantics(
        BookProductionStateClass.DURABLE_WAIT,
        "RESOLVE_AUTHORITY_INPUT",
        blocking_class="INPUT_AUTHORITY_WAIT",
        blocking_reason="governed Book production input is not resolved",
        wake_condition="BOOK_INPUT_SNAPSHOT_RESOLVED",
    ),
    BookProductionState.PLANNING_REQUIRED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "GENERATE_REQUIRED_PLAN"
    ),
    BookProductionState.PLAN_GENERATING: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "RECONCILE_PLAN_GENERATION"
    ),
    BookProductionState.PLAN_APPROVAL_PENDING: _state_semantics(
        BookProductionStateClass.DURABLE_WAIT,
        "APPROVE_GENERATED_PLAN",
        blocking_class="PLAN_GOVERNANCE_WAIT",
        blocking_reason="generated plan requires an owning Authority decision",
        wake_condition="PLAN_AUTHORITY_DECISION_COMMITTED",
    ),
    BookProductionState.READY: _state_semantics(
        BookProductionStateClass.ACTIONABLE,
        "PLAN_OR_DISPATCH_NEXT_CHAPTER",
        blocking_class="NONE",
        wake_condition="BOOK_WORKER_TICK",
    ),
    BookProductionState.CHAPTER_GROUP_REQUIRED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "GENERATE_OR_START_CHAPTER_GROUP"
    ),
    BookProductionState.CHAPTER_PLAN_REQUIRED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "GENERATE_OR_FREEZE_CHAPTER_PLAN"
    ),
    BookProductionState.CHAPTER_SUBMITTED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "RECONCILE_CHAPTER_OPERATION"
    ),
    BookProductionState.CHAPTER_RUNNING: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "RECONCILE_CHAPTER_OPERATION"
    ),
    BookProductionState.CHAPTER_WAITING_RETRY: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "RESUME_OR_RECONCILE_CHAPTER_RETRY"
    ),
    BookProductionState.CHAPTER_COMPLETED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "COMMIT_CHAPTER_ACCEPTANCE"
    ),
    BookProductionState.CHAPTER_ACCEPTANCE_PENDING: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "COMMIT_CHAPTER_ACCEPTANCE"
    ),
    BookProductionState.CHAPTER_FAILED_RETRYABLE: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "RECONCILE_CHAPTER_RETRY"
    ),
    BookProductionState.CHAPTER_FAILED_TERMINAL: _state_semantics(
        BookProductionStateClass.ACTIONABLE,
        "ABORT_BOOK_AFTER_TERMINAL_CHAPTER_FAILURE",
        blocking_class="TERMINAL_CHAPTER_FAILURE",
    ),
    BookProductionState.CANON_PENDING: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "REPLAY_ATOMIC_CHAPTER_ACCEPTANCE"
    ),
    BookProductionState.CANON_COMMITTED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "NORMALIZE_ACCEPTED_BOOK_CURSOR"
    ),
    BookProductionState.READER_OUTCOME_PENDING: _state_semantics(
        BookProductionStateClass.ACTIONABLE,
        "NORMALIZE_LEGACY_NON_BLOCKING_FOLLOWUP_STATE",
        blocking_class="LEGACY_STATE_RECOVERY",
    ),
    BookProductionState.FOLLOWUP_PENDING: _state_semantics(
        BookProductionStateClass.ACTIONABLE,
        "NORMALIZE_LEGACY_NON_BLOCKING_FOLLOWUP_STATE",
        blocking_class="LEGACY_STATE_RECOVERY",
    ),
    BookProductionState.CHECKPOINT_PENDING: _state_semantics(
        BookProductionStateClass.DURABLE_WAIT,
        "RECONCILE_ARC_CHECKPOINT_FOLLOWUP",
        blocking_class="ARC_CHECKPOINT_FOLLOWUP_WAIT",
        blocking_reason=(
            "accepted Arc checkpoint requires a future-only correction or "
            "replan decision before another Chapter may start"
        ),
        wake_condition="ARC_CHECKPOINT_FOLLOWUP_STATE_CHANGED",
    ),
    BookProductionState.REPLAN_REQUIRED: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "CREATE_GOVERNED_REPLAN"
    ),
    BookProductionState.REPLAN_GENERATING: _state_semantics(
        BookProductionStateClass.ACTIONABLE, "RECONCILE_GOVERNED_REPLAN"
    ),
    BookProductionState.REPLAN_APPROVAL_PENDING: _state_semantics(
        BookProductionStateClass.DURABLE_WAIT,
        "APPROVE_REPLAN",
        blocking_class="REPLAN_GOVERNANCE_WAIT",
        blocking_reason="future-only replan requires an owning Authority decision",
        wake_condition="REPLAN_AUTHORITY_DECISION_COMMITTED",
    ),
    BookProductionState.PAUSED: _state_semantics(
        BookProductionStateClass.DURABLE_WAIT,
        "RESUME_OR_ABORT_BOOK",
        blocking_class="OPERATOR_WAIT",
        blocking_reason="Book production is explicitly paused",
        wake_condition="BOOK_RESUME_OR_ABORT_COMMAND",
    ),
    BookProductionState.COMPLETED: _state_semantics(
        BookProductionStateClass.TERMINAL,
        "NONE",
        blocking_class="TERMINAL",
        wake_condition="NONE",
    ),
    BookProductionState.ABORTED: _state_semantics(
        BookProductionStateClass.TERMINAL,
        "NONE",
        blocking_class="TERMINAL",
        blocking_reason="Book production was aborted",
        wake_condition="NONE",
    ),
}


def book_production_state_semantics(
    state: BookProductionState | str,
) -> BookProductionStateSemantics:
    try:
        parsed = (
            state
            if isinstance(state, BookProductionState)
            else BookProductionState(state)
        )
        return BOOK_PRODUCTION_STATE_SEMANTICS[parsed]
    except (ValueError, KeyError) as exc:
        raise KernelError(
            "BOOK_PRODUCTION_STATE_UNCLASSIFIED",
            f"Book production state has no scheduling semantics: {state}",
        ) from exc


def actionable_book_production_states() -> tuple[str, ...]:
    return tuple(
        state.value
        for state in BookProductionState
        if BOOK_PRODUCTION_STATE_SEMANTICS[state].state_class
        is BookProductionStateClass.ACTIONABLE
    )


@dataclass(frozen=True, slots=True)
class StartBookProductionCommand:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    stable_idempotency_key: str
    book_design_version: str
    book_plan_version: str
    production_profile_version: str
    longform_context_versions: dict[str, Any]
    target_chapter_count: int
    input_mode: str
    light_recap_cadence: int = 5
    formal_recap_cadence: int = 10
    input_snapshot_id: str = ""
    edition_revision_id: str = ""


@dataclass(frozen=True, slots=True)
class SubmitBookChapterCommand:
    book_run_id: str
    chapter_number: int
    title: str
    premise: str
    chapter_plan_asset_version_id: str
    chapter_plan_content_hash: str
    context_candidates: tuple[dict[str, Any], ...]
    execution_chapter_plan_asset_version_id: str = ""
    execution_chapter_plan_content_hash: str = ""
    parent_group_version_id: str = ""
    narrative_realization_id: str = ""
    narrative_realization_slice_id: str = ""
    narrative_realization_contract_digest: str = ""
    context_version_refs: dict[str, Any] | None = None
    context_token_budget: int = 16_000
    preparation_report: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BookProductionAdmission:
    book_run_id: str
    root_operation_id: str
    saga_id: str
    replayed: bool


class ChapterAuthorityCommandPort(Protocol):
    def recover_admission(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission | None: ...

    def submit(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission: ...

    def require_run(
        self, *, project_id: str, root_operation_id: str
    ) -> dict[str, Any]: ...

    def require_acceptance_evidence(
        self, *, project_id: str, root_operation_id: str
    ) -> dict[str, Any]: ...

    def cancel(
        self,
        *,
        project_id: str,
        root_operation_id: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class ChapterAuthorityCommandAdapter:
    application: ChapterAuthorityApplication
    external_effect_adapters: dict[str, ExternalEffectAdapter]

    def recover_admission(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission | None:
        return self.application.recover_admission(request, principal=principal)

    def submit(
        self, request: SingleChapterRequest, *, principal: Principal
    ) -> ChapterSagaAdmission:
        return self.application.admit(request, principal=principal)

    def require_run(self, *, project_id: str, root_operation_id: str) -> dict[str, Any]:
        return self.application.query.require_run(
            project_id=project_id, root_operation_id=root_operation_id
        )

    def require_acceptance_evidence(
        self, *, project_id: str, root_operation_id: str
    ) -> dict[str, Any]:
        return self.application.query.require_acceptance_evidence(
            project_id=project_id, root_operation_id=root_operation_id
        )

    def cancel(
        self,
        *,
        project_id: str,
        root_operation_id: str,
        actor_id: str,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        state = self.application.query.require_operation_control_state(
            project_id=project_id,
            root_operation_id=root_operation_id,
        )
        terminal = {"SUCCEEDED", "FAILED_FINAL", "CANCELLED", "DEAD_LETTER", "COMPENSATED"}
        if state["status"] in terminal:
            return {"status": state["status"], "cancellation_requested": False,
                    "external_effect_cancellations": []}
        result = {"status": state["status"], "replayed": True}
        if state["status"] != "CANCELLATION_REQUESTED":
            try:
                result = request_cancellation(
                    self.application.database_url,
                    CancelCommand(
                        operation_id=root_operation_id, project_id=project_id, actor_id=actor_id,
                        reason=reason, expected_version=int(state["version"]),
                        idempotency_key=idempotency_key, trace_id=trace_id, correlation_id=correlation_id,
                    ),
                )
            except KernelError as error:
                if error.code not in {"OPERATION_VERSION_CONFLICT", "OPERATION_STATUS_CONFLICT"}:
                    raise
                current = self.application.query.require_operation_control_state(
                    project_id=project_id, root_operation_id=root_operation_id)
                if current["status"] not in terminal:
                    raise
                return {"status": current["status"], "cancellation_requested": False,
                        "external_effect_cancellations": []}
        cancellations = cancel_operation_external_effects(
            self.application.database_url,
            root_operation_id=root_operation_id,
            project_id=project_id,
            actor_id=actor_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            adapters=self.external_effect_adapters,
        )
        return {**result, "external_effect_cancellations": list(cancellations)}


def stable_chapter_submission_key(
    *,
    book_id: str,
    book_plan_version: str,
    chapter_number: int,
    chapter_plan_version: str,
    production_profile_version: str,
) -> str:
    if (
        not book_id
        or not book_plan_version
        or chapter_number <= 0
        or not chapter_plan_version
        or not production_profile_version
    ):
        raise ValueError("complete versioned chapter submission identity is required")
    payload = {
        "book_id": book_id,
        "book_plan_version": book_plan_version,
        "chapter_number": chapter_number,
        "chapter_plan_version": chapter_plan_version,
        "production_profile_version": production_profile_version,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"book-chapter:{digest}"


class PostgresBookAuthority:
    def __init__(
        self,
        database_url: str,
        *,
        chapter_port: ChapterAuthorityCommandPort,
        followup_application: BookFollowupAuthorityApplication,
        application_build_id: str,
        commit_sha: str,
        failure_injector: Callable[[str], None] | None = None,
        legacy_fixture_input_allowed: bool = False,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("PostgreSQL, build id, and full commit SHA are required")
        self.database_url = database_url
        self.chapter_port = chapter_port
        self.followup = followup_application
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.failure_injector = failure_injector
        self.legacy_fixture_input_allowed = legacy_fixture_input_allowed
        self.outcomes = ChapterOutcomeAuthorityApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            worker_id="book-chapter-acceptance-worker",
            failure_injector=failure_injector,
        )

    def start(
        self, command: StartBookProductionCommand, *, principal: Principal
    ) -> BookProductionAdmission:
        principal.require("book.authority.execute", command.project_id)
        _validate_start(command)
        if (
            command.input_mode == "LEGACY_FIXTURE_INPUT_MODE"
            and not self.legacy_fixture_input_allowed
        ):
            raise KernelError(
                "BOOK_PRODUCTION_LEGACY_INPUT_FORBIDDEN",
                "controlled Book Production requires an Authority-resolved input snapshot",
            )
        resolved_input_versions = self._validate_input_snapshot(command)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                book_coordinate_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()
        root_input_version_ids = resolved_input_versions or (
            command.book_design_version,
            command.book_plan_version,
            *_longform_context_asset_version_ids(command.longform_context_versions),
        )
        if command.edition_revision_id:
            from .edition_runtime import edition_start_inputs
            root_input_version_ids = tuple(dict.fromkeys((*root_input_version_ids, *edition_start_inputs(
                self.database_url, project_id=command.project_id, book_id=command.book_id, revision_id=command.edition_revision_id))))
        root_input_assets = self.resolve_asset_refs(
            project_id=command.project_id,
            asset_version_ids=root_input_version_ids,
        )
        admitted = admit_command(
            self.database_url,
            {
                "definition_name": BOOK_COORDINATE_DEFINITION,
                "definition_version": BOOK_COORDINATE_DEFINITION_VERSION,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "actor_id": principal.principal_id,
                "idempotency_scope": "project:book-coordinate",
                "idempotency_key": command.stable_idempotency_key,
                "trace_id": command.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": command.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": command.project_id,
                    "input_asset_version_ids": list(root_input_version_ids),
                    "payload": {key: value for key, value in asdict(command).items() if key != "edition_revision_id" or value},
                },
                "input_assets": list(root_input_assets),
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({BOOK_COORDINATE_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
        )
        root_operation_id = str(admitted["operation_id"])
        with AuthorityUnitOfWork(self.database_url) as uow:
            state = uow.repositories.attempt_runtime.operation_state(
                root_operation_id, command.project_id
            )
        if state["status"] == "ADMITTED":
            for expected, target in (("ADMITTED", "READY"), ("READY", "EXECUTING")):
                with AuthorityUnitOfWork(self.database_url) as uow:
                    current = uow.repositories.attempt_runtime.operation_state(
                        root_operation_id, command.project_id
                    )
                transition_operation(
                    self.database_url,
                    OperationTransitionCommand(
                        operation_id=root_operation_id,
                        project_id=command.project_id,
                        expected_version=int(current["version"]),
                        expected_status=expected,
                        target_status=target,
                        actor_id=principal.principal_id,
                        reason="start persistent Book Authority coordination",
                        trace_id=command.trace_id,
                        correlation_id=command.correlation_id,
                        causation_id="",
                    ),
                )
        saga_id = str(
            start_saga(
                self.database_url,
                GraphCommandContext(
                    command.project_id,
                    principal.principal_id,
                    command.trace_id,
                    command.correlation_id,
                ),
                root_operation_id=root_operation_id,
            )["saga_id"]
        )
        book_run_id = f"book-run:{root_operation_id}"

        def commit_start(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.cursor.execute(
                """
                SELECT book_id,version,current_book_design_asset_version_id,status
                FROM authority_book
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                FOR UPDATE
                """,
                [command.project_id, command.workspace_id, command.book_id],
            )
            book_owner = uow.cursor.fetchone()
            if book_owner is None:
                raise KernelError(
                    "BOOK_NOT_FOUND",
                    "Book Production requires its exact Book Authority owner",
                )
            uow.cursor.execute(
                """
                SELECT opening_run_id
                FROM authority_book_opening_run
                WHERE project_id=%s AND book_id=%s
                  AND lifecycle IN ('ADMITTED','RUNNING','FAILED')
                FOR UPDATE
                """,
                [command.project_id, command.book_id],
            )
            if uow.cursor.fetchone() is not None:
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_COMPLETION_REQUIRED",
                    "BookRun cannot start while an Opening workflow is active",
                )
            uow.cursor.execute("""SELECT formation_run_id FROM authority_story_formation_run
                WHERE project_id=%s AND book_id=%s AND formation_run_id || ':production'=%s FOR SHARE""",
                [command.project_id, command.book_id, command.stable_idempotency_key])
            source = uow.cursor.fetchone()
            if source:
                uow.cursor.execute("SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=%s", [source[0]])
                if uow.cursor.fetchone():
                    raise KernelError("CREATION_CANCELLED", "Cancelled native creation cannot start Book production")
            self._require_snapshot_plan_portfolio_current_in_uow(
                uow,
                command,
                book_version=int(book_owner[1]),
                book_design_version=str(book_owner[2] or ""),
                book_status=str(book_owner[3]),
            )
            uow.repositories.book_authority.create_run(
                {
                    "book_run_id": book_run_id,
                    "project_id": command.project_id,
                    "workspace_id": command.workspace_id,
                    "book_id": command.book_id,
                    "book_design_version": command.book_design_version,
                    "book_plan_version": command.book_plan_version,
                    "production_profile_version": command.production_profile_version,
                    "longform_context_versions": command.longform_context_versions,
                    "root_operation_id": root_operation_id,
                    "saga_id": saga_id,
                    "stable_idempotency_key": command.stable_idempotency_key,
                    "target_chapter_count": command.target_chapter_count,
                    "light_recap_cadence": command.light_recap_cadence,
                    "formal_recap_cadence": command.formal_recap_cadence,
                    "input_snapshot_id": command.input_snapshot_id,
                    "input_mode": command.input_mode,
                }
            )
            checkpoint("after_book_run_insert")
            if command.edition_revision_id:
                from novel_forge.storage.book_edition_repositories import BookEditionRepository
                edition_repository = BookEditionRepository(uow.cursor)
                revision = edition_repository.revision(project_id=command.project_id, revision_id=command.edition_revision_id, book_id=command.book_id)
                if revision["edition"]["current_revision_id"] != revision["revision_id"]:
                    raise KernelError("EDITION_VERSION_CONFLICT", "Validation must start from the current saved candidate")
                if any(event["event_kind"] == "REJECTED" for event in edition_repository.events(revision["revision_id"])):
                    raise KernelError("EDITION_VALIDATION_REJECTED", "A rejected candidate cannot create a validation run")
                uow.cursor.execute("INSERT INTO authority_book_edition_run(book_run_id,revision_id,role,created_by_operation_id) VALUES(%s,%s,'VALIDATION',%s)",
                                   [book_run_id, command.edition_revision_id, _operation_id])
                edition_repository.event(revision_id=command.edition_revision_id, kind="VALIDATION_BOUND",
                    content={"validation_book_run_id": book_run_id, "manifest_digest": revision["manifest_digest"]}, operation_id=_operation_id)
                from .edition_runtime import inherit_unchanged_prefix
                inherit_unchanged_prefix(uow, book_run_id=book_run_id, revision=revision, operation_id=_operation_id)
            if command.input_mode == "RESOLVED_AUTHORITY_INPUT":
                binding_id = (
                    "book-input-binding:"
                    + hashlib.sha256(
                        f"{book_run_id}:1:{command.input_snapshot_id}".encode()
                    ).hexdigest()
                )
                uow.repositories.book_authority.create_input_binding(
                    {
                        "binding_id": binding_id,
                        "project_id": command.project_id,
                        "book_id": command.book_id,
                        "book_run_id": book_run_id,
                        "binding_version": 1,
                        "snapshot_id": command.input_snapshot_id,
                        "reason": "BOOK_START",
                        "bound_by_operation_id": root_operation_id,
                    },
                    ignore_replay_conflict=True,
                )
                checkpoint("after_input_binding_insert")
            uow.cursor.execute(
                """
                SELECT book_run_id, root_operation_id, saga_id
                FROM authority_book_production
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [command.project_id, command.stable_idempotency_key],
            )
            row = uow.cursor.fetchone()
            if row is None or row[1] != root_operation_id:
                raise KernelError(
                    "BOOK_AUTHORITY_IDEMPOTENCY_CONFLICT",
                    "Book command replay resolved to a different root Operation",
                )
            return {
                "book_run_id": str(row[0]),
                "root_operation_id": str(row[1]),
                "saga_id": str(row[2]),
                "state": BookProductionState.READY.value,
            }

        committed = self._execute_mutation(
            book={
                "book_run_id": book_run_id,
                "project_id": command.project_id,
                "workspace_id": command.workspace_id,
                "book_id": command.book_id,
                "root_operation_id": root_operation_id,
                "stable_idempotency_key": command.stable_idempotency_key,
            },
            action="start",
            event_type="book.production.started",
            idempotency_key=f"{command.stable_idempotency_key}:start-commit",
            actor_id=principal.principal_id,
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=root_operation_id,
            payload={
                "input_snapshot_id": command.input_snapshot_id,
                "input_mode": command.input_mode,
                "target_chapter_count": command.target_chapter_count,
            },
            handler=commit_start,
        )
        row = (
            committed["book_run_id"],
            committed["root_operation_id"],
            committed["saga_id"],
        )
        if row is None or row[1] != root_operation_id:
            raise KernelError(
                "BOOK_AUTHORITY_IDEMPOTENCY_CONFLICT",
                "Book command replay resolved to a different root Operation",
            )
        return BookProductionAdmission(
            book_run_id=str(row[0]),
            root_operation_id=str(row[1]),
            saga_id=str(row[2]),
            replayed=bool(admitted["replayed"]),
        )

    def submit_chapter(
        self, command: SubmitBookChapterCommand, *, principal: Principal
    ) -> dict[str, Any]:
        book = self.require(command.book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        stable_key = stable_chapter_submission_key(
            book_id=book["book_id"],
            book_plan_version=book["book_plan_version"],
            chapter_number=command.chapter_number,
            chapter_plan_version=command.chapter_plan_asset_version_id,
            production_profile_version=book["production_profile_version"],
        )
        from .edition_runtime import edition_dispatch_binding, freeze_edition_adoption
        edition_binding = edition_dispatch_binding(self.database_url, book=book, chapter=command.chapter_number)
        if edition_binding:
            stable_key += ":edition:" + edition_binding["revision_id"]
            command = replace(command, preparation_report={**dict(command.preparation_report or {}), "book_edition": edition_binding})
            if edition_binding["role"] == "VALIDATION" and command.chapter_number <= edition_binding["unit_count"]:
                adoption = freeze_edition_adoption(self.database_url, project_id=book["project_id"], workspace_id=book["workspace_id"],
                    book_id=book["book_id"], chapter=command.chapter_number, revision_id=edition_binding["revision_id"],
                    book_run_id=command.book_run_id, principal=principal)
                from .edition_planning import require_edition_execution_plan
                require_edition_execution_plan(self.database_url, project_id=book["project_id"], book_id=book["book_id"],
                    book_run_id=command.book_run_id, execution_plan_version_id=command.execution_chapter_plan_asset_version_id or command.chapter_plan_asset_version_id,
                    revision_id=edition_binding["revision_id"], chapter=command.chapter_number, source_plan_version_id=adoption["source_chapter_plan_asset_version_id"])
                command = replace(command, preparation_report={**dict(command.preparation_report or {}), "author_draft_adoption": adoption})
        if command.chapter_number > int(book["target_chapter_count"]):
            raise KernelError(
                "BOOK_CHAPTER_OUT_OF_RANGE", "chapter exceeds Book target count"
            )
        self._require_chapter_production_admission(book, command)
        from .control_application import PostgresBookControlApplication
        PostgresBookControlApplication(self.database_url, application_build_id=self.application_build_id, commit_sha=self.commit_sha).require_approvals(
            project_id=book["project_id"], book_run_id=command.book_run_id, chapter_number=command.chapter_number, actor_id=principal.principal_id,
            subjects={"CHAPTER": command.chapter_plan_asset_version_id, "SCENE": command.chapter_plan_asset_version_id},
        )
        request_id = f"chapter-request:{stable_key.removeprefix('book-chapter:')}"

        def commit_reservation(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
            from .edition_runtime import edition_dispatch_binding_in_uow
            if edition_dispatch_binding_in_uow(uow, book=book, chapter=command.chapter_number) != edition_binding:
                raise KernelError("EDITION_DISPATCH_SELECTION_CHANGED", "Edition selection changed before the new request could freeze")
            uow.cursor.execute(
                """
                SELECT version, state, current_chapter
                FROM authority_book_production
                WHERE book_run_id=%s FOR UPDATE
                """,
                [command.book_run_id],
            )
            locked = uow.cursor.fetchone()
            if locked is None or int(locked[0]) != int(book["version"]):
                raise KernelError(
                    "BOOK_CHAPTER_RESERVATION_CONFLICT",
                    "Book checkpoint changed before Chapter reservation",
                )
            uow.cursor.execute(
                """
                SELECT chapter_request_id, chapter_root_operation_id
                FROM authority_book_chapter_request
                WHERE project_id=%s AND stable_idempotency_key=%s
                """,
                [book["project_id"], stable_key],
            )
            existing = uow.cursor.fetchone()
            if existing is None:
                frozen_command = asdict(command)
                uow.cursor.execute(
                    "SELECT version.content FROM authority_asset_version version JOIN authority_asset asset USING(asset_id) WHERE version.asset_version_id=%s AND asset.project_id=%s AND asset.asset_type='production_profile'",
                    [book["production_profile_version"], book["project_id"]],
                )
                profile_row = uow.cursor.fetchone()
                prose_policy = (profile_row[0] if profile_row else {}).get("cross_chapter_review_policy")
                if prose_policy is not None:
                    from .prose_sources import freeze_accepted_prose
                    frozen_command["accepted_prose_snapshot"] = freeze_accepted_prose(
                        uow, book=book, chapter=command.chapter_number, policy=prose_policy,
                    )
                uow.repositories.book_authority.create_chapter_request(
                    {
                        "chapter_request_id": request_id,
                        "book_run_id": command.book_run_id,
                        "project_id": book["project_id"],
                        "chapter_number": command.chapter_number,
                        "chapter_plan_version": command.chapter_plan_asset_version_id,
                        "chapter_plan_content_hash": command.chapter_plan_content_hash,
                        "parent_group_version_id": command.parent_group_version_id,
                        "narrative_realization_id": command.narrative_realization_id,
                        "narrative_realization_slice_id": (
                            command.narrative_realization_slice_id
                        ),
                        "narrative_realization_contract_digest": (
                            command.narrative_realization_contract_digest
                        ),
                        "production_profile_version": book[
                            "production_profile_version"
                        ],
                        "stable_idempotency_key": stable_key,
                        "command_payload": frozen_command,
                    }
                )
                if not uow.repositories.book_authority.reserve_chapter(
                    book_run_id=command.book_run_id,
                    chapter_request_id=request_id,
                    chapter_number=command.chapter_number,
                    expected_version=int(book["version"]),
                ):
                    raise KernelError(
                        "BOOK_CHAPTER_SUBMISSION_NOT_READY",
                        "Book is not READY for the next sequential Chapter",
                    )
                existing = (request_id, None)
            checkpoint("after_chapter_reservation")
            return {
                "chapter_request_id": str(existing[0]),
                "chapter_root_operation_id": str(existing[1] or ""),
                "chapter_number": command.chapter_number,
                "state": BookProductionState.CHAPTER_SUBMITTED.value,
            }

        reservation = self._execute_mutation(
            book=book,
            action="chapter_reserve",
            event_type="book.chapter_request.reserved",
            idempotency_key=f"{stable_key}:reserve",
            actor_id=principal.principal_id,
            trace_id=(
                f"{book['root_operation_id']}:chapter:{command.chapter_number}:reserve"
            ),
            correlation_id=str(book["root_operation_id"]),
            causation_id=str(book["root_operation_id"]),
            payload={
                "chapter_request_id": request_id,
                "chapter_number": command.chapter_number,
                "chapter_plan_version": command.chapter_plan_asset_version_id,
            },
            handler=commit_reservation,
        )
        existing = (
            reservation["chapter_request_id"],
            reservation["chapter_root_operation_id"] or None,
        )
        if existing is None:
            raise KernelError(
                "BOOK_CHAPTER_REQUEST_MISSING", "chapter request was not persisted"
            )
        return self._dispatch_reserved_chapter(str(existing[0]), principal=principal)

    def _dispatch_reserved_chapter(self, chapter_request_id: str, *, principal: Principal) -> dict[str, Any]:
        persisted_request = self.require_chapter_request(chapter_request_id)
        book = self.require(persisted_request["book_run_id"])
        principal.require("book.authority.execute", book["project_id"])
        if book["state"] in {BookProductionState.PAUSED.value, BookProductionState.ABORTED.value, BookProductionState.COMPLETED.value}:
            raise KernelError("BOOK_CHAPTER_RECOVERY_NOT_RUNNABLE", "Paused or terminal Book coordination cannot dispatch a reserved request")
        if persisted_request["chapter_root_operation_id"]:
            return persisted_request
        if book["active_chapter_request_id"] != chapter_request_id:
            raise KernelError("BOOK_CHAPTER_RECOVERY_NOT_ACTIVE", "Only the Book's exact reserved request can resume admission")
        payload = dict(persisted_request["command_payload"])
        command = SubmitBookChapterCommand(**{field.name: payload[field.name] for field in fields(SubmitBookChapterCommand) if field.name in payload})
        if command.book_run_id != book["book_run_id"] or command.chapter_number != persisted_request["chapter_number"]:
            raise KernelError("BOOK_CHAPTER_RECOVERY_SCOPE_DRIFT", "Frozen Chapter request identity must match its owned Book reservation")
        stable_key = persisted_request["stable_idempotency_key"]
        request_id = chapter_request_id
        from .chapter_dispatch import reserved_chapter_command
        self._probe("before_child_admission")
        chapter_command = reserved_chapter_command(self.database_url, book=book, persisted=persisted_request,
            actor_id=principal.principal_id, application_build_id=self.application_build_id, commit_sha=self.commit_sha)
        recover_admission = getattr(self.chapter_port, "recover_admission", None)
        admission = recover_admission(chapter_command, principal=principal) if recover_admission else None
        if admission is None:
            admission = self.chapter_port.submit(chapter_command, principal=principal)
        self._probe("after_child_admission")
        self._probe("before_delegation_persist")
        delegation_id = (
            "child-delegation:"
            + hashlib.sha256(f"{stable_key}:chapter".encode()).hexdigest()
        )
        current = self.require(command.book_run_id)

        def commit_link(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.cursor.execute("SELECT book_id FROM authority_book WHERE book_id=%s FOR UPDATE", [book["book_id"]])
            uow.cursor.execute("SELECT version,state,active_chapter_request_id,current_chapter FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [command.book_run_id])
            locked = uow.cursor.fetchone()
            if locked != (int(current["version"]), BookProductionState.CHAPTER_SUBMITTED.value, request_id, command.chapter_number - 1):
                raise KernelError("BOOK_CHAPTER_LINK_STATE_CHANGED", "Chapter admission cannot overwrite a concurrent pause, cancellation or frontier change")
            uow.repositories.book_authority.link_chapter(
                chapter_request_id=request_id,
                book_run_id=command.book_run_id,
                project_id=book["project_id"],
                chapter_number=command.chapter_number,
                chapter_plan_version=command.chapter_plan_asset_version_id,
                stable_idempotency_key=stable_key,
                delegation_id=delegation_id,
                root_operation_id=admission.root_operation_id,
                saga_id=admission.saga_id,
                expected_book_version=int(current["version"]),
            )
            checkpoint("after_chapter_link")
            return {
                "chapter_request_id": request_id,
                "chapter_root_operation_id": admission.root_operation_id,
                "chapter_saga_id": admission.saga_id,
                "state": BookProductionState.CHAPTER_SUBMITTED.value,
            }

        self._execute_mutation(
            book=current,
            action="chapter_link",
            event_type="book.chapter_request.linked",
            idempotency_key=f"{stable_key}:link",
            actor_id=principal.principal_id,
            trace_id=(
                f"{book['root_operation_id']}:chapter:{command.chapter_number}:link"
            ),
            correlation_id=str(book["root_operation_id"]),
            causation_id=admission.root_operation_id,
            payload={
                "chapter_request_id": request_id,
                "chapter_number": command.chapter_number,
            },
            handler=commit_link,
        )
        self._probe("after_delegation_persist")
        return self.require_chapter_request(request_id)

    def _require_chapter_production_admission(
        self, book: dict[str, Any], command: SubmitBookChapterCommand
    ) -> None:
        if book["input_mode"] != "RESOLVED_AUTHORITY_INPUT":
            return
        self._require_accepted_projection_boundary(book)
        if not command.parent_group_version_id:
            raise KernelError(
                "CHAPTER_PRODUCTION_ADMISSION_REQUIRED",
                "resolved Book production requires a frozen ChapterGroup plan",
            )
        if not all(
            (
                command.narrative_realization_id,
                command.narrative_realization_slice_id,
                command.narrative_realization_contract_digest,
            )
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_REQUIRED",
                "resolved Chapter production requires exact Frozen realization lineage",
            )
        from .queries import PostgresBookProductionQuery

        query = PostgresBookProductionQuery(self.database_url)
        authoritative = query.require_chapter_production_admission(
            book_run_id=command.book_run_id,
            snapshot_id=str(book["input_snapshot_id"]),
            chapter_group_plan_version_id=command.parent_group_version_id,
            chapter_plan_version_id=command.chapter_plan_asset_version_id,
            chapter_number=command.chapter_number,
            accepted_through_chapter=int(book["accepted_through_chapter"]),
            active_story_state_version_id=str(
                book.get("active_story_state_version_id") or ""
            ),
            active_canon_snapshot_version_id=str(
                book.get("active_canon_snapshot_version_id") or ""
            ),
        )
        execution_plan = query.require_chapter_execution_plan(
            command.chapter_plan_asset_version_id
        )
        if (
            command.chapter_plan_content_hash != execution_plan["source_content_hash"]
            or command.execution_chapter_plan_asset_version_id
            != execution_plan["asset_version_id"]
            or command.execution_chapter_plan_content_hash
            != execution_plan["content_hash"]
        ):
            raise KernelError(
                "CHAPTER_PRODUCTION_EXECUTION_PLAN_MISMATCH",
                "Chapter Saga input must be the governed projection of the admitted ChapterPlan",
            )
        supplied = dict(command.preparation_report or {}).get(
            "chapter_production_admission"
        )
        refs = dict(command.context_version_refs or {})
        if supplied != authoritative or (
            refs.get("longform_design_qualification_hash")
            != authoritative["longform_design_qualification_hash"]
            or refs.get("chapter_production_admission_hash")
            != authoritative["admission_hash"]
        ):
            raise KernelError(
                "CHAPTER_PRODUCTION_ADMISSION_MISMATCH",
                "Chapter command differs from authoritative design admission",
            )
        if (
            command.narrative_realization_id
            != authoritative["narrative_realization_id"]
            or command.narrative_realization_slice_id
            != authoritative["narrative_realization_slice_id"]
            or command.narrative_realization_contract_digest
            != authoritative["narrative_realization_contract_digest"]
        ):
            raise KernelError(
                "NARRATIVE_REALIZATION_ADMISSION_MISMATCH",
                "Chapter command changed its governed realization identity",
            )

    def _require_accepted_projection_boundary(self, book: dict[str, Any]) -> None:
        accepted_through = int(book["accepted_through_chapter"])
        if accepted_through == 0:
            return
        projection_set_id = str(book.get("active_longform_projection_set_id") or "")
        if not projection_set_id:
            raise KernelError(
                "BOOK_ACCEPTED_PROJECTION_SET_INCOMPLETE",
                "the next Chapter cannot start before the prior acceptance projection is complete",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT 1
                FROM authority_book_narrative_projection_set AS projection
                JOIN authority_book_chapter_acceptance AS acceptance
                  ON acceptance.acceptance_id=projection.acceptance_id
                 AND acceptance.longform_projection_set_id=
                     projection.projection_set_id
                 AND acceptance.status='COMMITTED'
                WHERE projection.projection_set_id=%s
                  AND projection.project_id=%s AND projection.book_id=%s
                  AND projection.book_run_id=authority_book_source_run(%s,projection.chapter_number)
                  AND projection.chapter_number=%s
                  AND projection.status='COMPLETE'
                  AND projection.chapter_outcome_asset_version_id=%s
                  AND projection.story_state_asset_version_id=%s
                  AND projection.canon_snapshot_asset_version_id=%s
                  AND acceptance.book_run_id=authority_book_source_run(%s,acceptance.chapter_number)
                  AND acceptance.project_id=%s
                  AND acceptance.chapter_number=%s
                  AND acceptance.chapter_outcome_asset_version_id=
                      projection.chapter_outcome_asset_version_id
                  AND acceptance.story_state_asset_version_id=
                      projection.story_state_asset_version_id
                  AND acceptance.canon_snapshot_asset_version_id=
                      projection.canon_snapshot_asset_version_id
                """,
                [
                    projection_set_id,
                    book["project_id"],
                    book["book_id"],
                    book["book_run_id"],
                    accepted_through,
                    book["last_chapter_outcome_version_id"],
                    book["active_story_state_version_id"],
                    book["active_canon_snapshot_version_id"],
                    book["book_run_id"],
                    book["project_id"],
                    accepted_through,
                ],
            )
            complete = uow.cursor.fetchone()
        if complete is None:
            raise KernelError(
                "BOOK_ACCEPTED_PROJECTION_SET_INCOMPLETE",
                "the next Chapter cannot use an incomplete or mismatched accepted projection",
            )

    def accept_chapter(
        self, chapter_request_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        request = self.require_chapter_request(chapter_request_id)
        book = self.require(request["book_run_id"])
        principal.require("book.authority.execute", request["project_id"])
        existing_acceptance = self._find_chapter_acceptance(
            chapter_request_id=chapter_request_id,
            project_id=request["project_id"],
        )
        if existing_acceptance is not None:
            return {
                **book,
                "acceptance_operation_id": existing_acceptance[
                    "acceptance_operation_id"
                ],
                "last_chapter_outcome_version_id": existing_acceptance[
                    "chapter_outcome_asset_version_id"
                ],
                "active_story_state_version_id": existing_acceptance[
                    "story_state_asset_version_id"
                ],
                "active_canon_snapshot_version_id": existing_acceptance[
                    "canon_snapshot_asset_version_id"
                ],
                "active_longform_projection_set_id": existing_acceptance[
                    "longform_projection_set_id"
                ],
            }
        if book["active_chapter_request_id"] != chapter_request_id:
            raise KernelError("BOOK_CHAPTER_SUPERSEDED", "Only the current unaccepted Book child can be accepted")
        if not request["chapter_root_operation_id"]:
            raise KernelError(
                "BOOK_CHAPTER_ACCEPTANCE_NOT_READY",
                "Chapter delegation has not been admitted",
            )
        evidence = self.chapter_port.require_acceptance_evidence(
            project_id=request["project_id"],
            root_operation_id=request["chapter_root_operation_id"],
        )
        selected_for_admission = select_chapter_acceptance_outputs(evidence)
        internal = selected_for_admission["final_release_gate_report"]["content"].get("internal_admission")
        if internal is not None:
            from novel_forge.modules.chapter_quality_authority.creative_validation import verify_internal_quality
            verify_internal_quality(self.database_url, internal, project_id=request["project_id"], book_id=book["book_id"])
        acceptance_inputs = _validate_chapter_acceptance_evidence(
            request=request,
            evidence=evidence,
        )
        selected_acceptance_outputs = select_chapter_acceptance_outputs(evidence)
        from .control_application import PostgresBookControlApplication
        controls = PostgresBookControlApplication(self.database_url, application_build_id=self.application_build_id, commit_sha=self.commit_sha)
        editorial_inputs = controls.require_approvals(project_id=request["project_id"], book_run_id=request["book_run_id"], chapter_number=int(request["chapter_number"]), actor_id=principal.principal_id,
            subjects={"FINAL_CANDIDATE": str(selected_acceptance_outputs["best_draft_candidate"]["asset_version_id"])})
        acceptance_inputs = (*acceptance_inputs, *editorial_inputs)
        execution_chapter_plan_asset_version_id = str(
            selected_acceptance_outputs["chapter_plan"]["asset_version_id"]
        )
        if bool(book["active_story_state_version_id"]) != bool(
            book["active_canon_snapshot_version_id"]
        ):
            raise KernelError(
                "BOOK_NARRATIVE_STATE_CHECKPOINT_INCOMPLETE",
                "Story State and Canon checkpoints must advance together",
            )
        if int(book["accepted_through_chapter"]) > 0 and not str(
            book.get("active_longform_projection_set_id") or ""
        ):
            raise KernelError(
                "BOOK_ACCEPTED_PROJECTION_SET_INCOMPLETE",
                "the previous Accepted Chapter lacks its complete long-form projection set",
            )
        if book["active_story_state_version_id"]:
            acceptance_inputs = (
                *acceptance_inputs,
                *self.resolve_asset_refs(
                    project_id=request["project_id"],
                    asset_version_ids=(
                        str(book["active_story_state_version_id"]),
                        str(book["active_canon_snapshot_version_id"]),
                    ),
                ),
            )
        elif (
            int(request["chapter_number"]) == 1
            and book["input_mode"] == "RESOLVED_AUTHORITY_INPUT"
        ):
            acceptance_inputs = (
                *acceptance_inputs,
                *self._initial_narrative_state_inputs(book=book, request=request),
            )
        stable_key = f"{request['stable_idempotency_key']}:accept"
        admission = self.outcomes.admit(
            ChapterOutcomeCommand(
                project_id=request["project_id"],
                workspace_id=book["workspace_id"],
                actor_id=principal.principal_id,
                trace_id=f"{request['chapter_root_operation_id']}:accept",
                correlation_id=book["root_operation_id"],
                idempotency_key=stable_key,
                payload={
                    "book_id": book["book_id"],
                    **({"creative_requirements_contract": "work-requirements.v1"} if selected_acceptance_outputs["best_draft_candidate"]["content"].get("creative_baseline") else {}),
                    "chapter_number": int(request["chapter_number"]),
                    "parent_group_version_id": str(
                        request.get("parent_group_version_id") or ""
                    ),
                    "cost_receipt_refs": list(evidence.get("cost_receipt_refs") or ()),
                },
                input_assets=acceptance_inputs,
                root_operation_id=book["root_operation_id"],
                parent_operation_id=book["root_operation_id"],
                causation_operation_id=request["chapter_root_operation_id"],
            ),
            principal=principal,
        )
        register_saga_step(
            self.database_url,
            self._book_graph_context(book, principal.principal_id),
            str(book["saga_id"]),
            admission.operation_id,
            f"chapter:{request['chapter_number']}:accept",
            int(request["chapter_number"]),
            "",
        )
        execution = self.outcomes.run_or_recover(admission).output
        materialized_outputs = (
            execution.materialized_outputs
            or self.outcomes.require_materialized_outputs(
                operation_id=admission.operation_id,
                project_id=request["project_id"],
            )
        )
        outputs = {item.asset_type: item for item in materialized_outputs}
        outcome = outputs["chapter_outcome"]
        story_state = outputs["story_state_snapshot"]
        canon_snapshot = outputs["canon_snapshot"]
        reality_approval_inputs = controls.require_approvals(project_id=request["project_id"], book_run_id=request["book_run_id"], chapter_number=int(request["chapter_number"]), actor_id=principal.principal_id, subjects={"REALITY_COMMIT": outcome.asset_version_id})
        followup_snapshot = self._accepted_followup_snapshot(
            book=book,
            request=request,
            chapter_outcome_asset_version_id=outcome.asset_version_id,
            story_state_asset_version_id=story_state.asset_version_id,
            canon_snapshot_asset_version_id=canon_snapshot.asset_version_id,
            acceptance_operation_id=admission.operation_id,
        )
        self._probe("before_acceptance")
        acceptance_id = (
            "chapter-acceptance:" + hashlib.sha256(stable_key.encode()).hexdigest()
        )
        current = self.require(request["book_run_id"])

        def commit_acceptance(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.cursor.execute("SELECT active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [request["book_run_id"]])
            if uow.cursor.fetchone()[0] != chapter_request_id:
                raise KernelError("BOOK_CHAPTER_SUPERSEDED", "Book child changed before acceptance commit")
            locked_outputs = uow.repositories.book_authority.lock_acceptance_assets(
                project_id=request["project_id"], selected=selected_acceptance_outputs,
            )
            if evidence.get("model_effects") or locked_outputs["canon_patch"]["content"].get("grounding"):
                from novel_forge.modules.chapter_outcome.acceptance_contract import require_grounded_acceptance
                require_grounded_acceptance(project_id=request["project_id"], selected=locked_outputs)
            from novel_forge.storage.book_control_repositories import BookControlRepository
            for boundary, subject in (("FINAL_CANDIDATE", str(selected_acceptance_outputs["best_draft_candidate"]["asset_version_id"])), ("REALITY_COMMIT", outcome.asset_version_id)):
                BookControlRepository(uow.cursor).require_approval(project_id=request["project_id"], book_run_id=request["book_run_id"], chapter_number=int(request["chapter_number"]), actor_id=principal.principal_id, boundary=boundary, subject_version_id=subject)
            uow.cursor.execute(
                """
                SELECT delegation_id
                FROM authority_child_delegation
                WHERE chapter_request_id=%s AND project_id=%s
                """,
                [chapter_request_id, request["project_id"]],
            )
            delegation = uow.cursor.fetchone()
            if delegation is None:
                raise KernelError(
                    "BOOK_CHILD_DELEGATION_MISSING",
                    "Chapter acceptance requires a persisted child delegation",
                )
            uow.cursor.execute(
                """
                SELECT outcome.content, story_state.content, chapter_plan.content
                FROM authority_asset_version AS outcome
                JOIN authority_asset_version AS story_state
                  ON story_state.asset_version_id=%s
                JOIN authority_asset_version AS chapter_plan
                  ON chapter_plan.asset_version_id=%s
                WHERE outcome.asset_version_id=%s
                """,
                [
                    story_state.asset_version_id,
                    execution_chapter_plan_asset_version_id,
                    outcome.asset_version_id,
                ],
            )
            projection_inputs = uow.cursor.fetchone()
            if projection_inputs is None:
                raise KernelError(
                    "BOOK_LONGFORM_PROJECTION_INPUT_MISSING",
                    "accepted long-form projection inputs are not materialized",
                )
            outcome_content = dict(projection_inputs[0])
            story_state_content = dict(projection_inputs[1])
            chapter_plan_content = dict(projection_inputs[2])
            active_arc_plan_versions = frozen_arc_plan_version_ids(
                request_payload=dict(request.get("command_payload") or {}),
                book_context=dict(book["longform_context_versions"]),
            )
            expected_progress_units = {
                str(item.get("arc_plan_version_id") or item.get("arc_id") or ""): int(
                    item["expected_progress_units"]
                )
                for item in chapter_plan_content.get("required_arc_contributions") or ()
                if isinstance(item, dict)
                and str(item.get("arc_plan_version_id") or item.get("arc_id") or "")
                and item.get("expected_progress_units") is not None
            }
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash,
                       version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE version.asset_version_id=ANY(%s) AND asset.project_id=%s
                """,
                [list(active_arc_plan_versions), request["project_id"]],
            )
            arc_plan_rows = uow.cursor.fetchall()
            arc_plan_snapshots = {
                str(row[0]): dict(row[2] or {}) for row in arc_plan_rows
            }
            arc_plan_content_hashes = {
                str(row[0]): str(row[1]) for row in arc_plan_rows
            }
            if set(arc_plan_snapshots) != set(active_arc_plan_versions):
                raise KernelError(
                    "BOOK_FROZEN_ARC_PLAN_MISSING",
                    "accepted projection requires every frozen ArcPlan AssetVersion",
                )
            previous_arc_states: dict[str, dict[str, Any]] = {}
            if int(request["chapter_number"]) > 1:
                uow.cursor.execute(
                    """
                    SELECT arc_state
                    FROM authority_book_narrative_projection_set
                    WHERE book_run_id=authority_book_source_run(%s,chapter_number) AND chapter_number=%s
                      AND status='COMPLETE'
                    """,
                    [request["book_run_id"], int(request["chapter_number"]) - 1],
                )
                previous_projection = uow.cursor.fetchone()
                if previous_projection is None:
                    raise KernelError(
                        "BOOK_PREVIOUS_LONGFORM_PROJECTION_MISSING",
                        "accepted projection requires the preceding Book-run projection",
                    )
                previous_arc_states = {
                    str(item.get("arc_plan_version_id") or ""): dict(item)
                    for item in previous_projection[0] or ()
                    if isinstance(item, dict)
                    and str(item.get("arc_plan_version_id") or "")
                }
                uow.cursor.execute(
                    """
                    SELECT outcome.arc_plan_version_id, outcome.status,
                           outcome.accepted_through_chapter
                    FROM authority_arc_outcome_v2 AS outcome
                    JOIN authority_book_narrative_projection_set AS projection
                      ON projection.projection_set_id=outcome.projection_set_id
                    WHERE projection.book_run_id=authority_book_source_run(%s,projection.chapter_number)
                      AND outcome.accepted_through_chapter < %s
                    """,
                    [request["book_run_id"], int(request["chapter_number"])],
                )
                for arc_id, lifecycle, accepted_chapter in uow.cursor.fetchall():
                    previous_arc_states.setdefault(
                        str(arc_id),
                        {
                            "arc_plan_version_id": str(arc_id),
                            "lifecycle_status": str(lifecycle),
                            "accepted_through_chapter": int(accepted_chapter),
                            "cumulative_progress_units": 0,
                        },
                    )
            from novel_forge.modules.canon_graph.world_reconciliation import validate_actual_world_events
            from novel_forge.storage.narrative_reality_repositories import NarrativeRealityRepository
            if int(request["chapter_number"]) > 1:
                previous_reality = NarrativeRealityRepository(uow.cursor).require(book_run_id=request["book_run_id"], chapter_number=int(request["chapter_number"])-1, event_ids=tuple(sorted({ref for event in outcome_content.get("state_events", []) for ref in event.get("causality", {}).get("cause_refs", [])})))
            else:
                previous_reality = {"current_state": {}, "events": []}
                initial_version_id = str(story_state_content.get("previous_story_state_asset_version_id") or "")
                initial_state = NarrativeRealityRepository(uow.cursor).initial_state(
                    version_id=initial_version_id,
                    frozen_versions={ref["asset_version_id"] for ref in acceptance_inputs},
                )
                if initial_state is not None:
                    previous_reality["current_state"] = dict(initial_state.get("current_state") or {})
            previous_reality["world_rule_constraints"], _ = NarrativeRealityRepository(uow.cursor).frozen_world_rules(book_run_id=request["book_run_id"])
            from novel_forge.storage.world_preparation_repositories import WorldPreparationRepository
            world_baseline = WorldPreparationRepository(uow.cursor).validate_acceptance(
                project_id=request["project_id"], book_id=book["book_id"],
                binding=(chapter_plan_content.get("constraint_envelope") or {}).get("world_preparation") or {}, outcome=outcome_content,
            )
            if world_baseline is not None:
                previous_reality = world_baseline
            validate_actual_world_events(previous_reality=previous_reality, chapter_outcome=outcome_content)
            from novel_forge.storage.causal_planning_repositories import CausalPlanningRepository
            CausalPlanningRepository(uow.cursor).validate_obligation_origins(book_run_id=request["book_run_id"], previous_reality=previous_reality, chapter_outcome=outcome_content)
            longform_projection_set = project_accepted_longform(
                AcceptedLongformEvidence(
                    project_id=request["project_id"],
                    book_id=book["book_id"],
                    book_run_id=request["book_run_id"],
                    chapter_request_id=chapter_request_id,
                    chapter_number=int(request["chapter_number"]),
                    acceptance_id=acceptance_id,
                    acceptance_operation_id=admission.operation_id,
                    chapter_outcome_asset_version_id=outcome.asset_version_id,
                    chapter_outcome_content_hash=outcome.content_hash,
                    story_state_asset_version_id=story_state.asset_version_id,
                    story_state_content_hash=story_state.content_hash,
                    canon_snapshot_asset_version_id=canon_snapshot.asset_version_id,
                    canon_snapshot_content_hash=canon_snapshot.content_hash,
                    chapter_plan_asset_version_id=(
                        execution_chapter_plan_asset_version_id
                    ),
                    chapter_plan_content_hash=str(
                        selected_acceptance_outputs["chapter_plan"].get("content_hash")
                        or ""
                    ),
                    active_arc_plan_version_ids=active_arc_plan_versions,
                    expected_progress_units=expected_progress_units,
                    previous_arc_states=previous_arc_states,
                    arc_plan_snapshots=arc_plan_snapshots,
                    arc_plan_content_hashes=arc_plan_content_hashes,
                    chapter_outcome=outcome_content,
                    story_state=story_state_content,
                    source_contract=str(
                        outcome_content.get("contract_version") or "UNKNOWN"
                    ),
                )
            )
            uow.repositories.book_authority.commit_chapter_acceptance(
                acceptance_id=acceptance_id,
                project_id=request["project_id"],
                book_run_id=request["book_run_id"],
                chapter_request_id=chapter_request_id,
                delegation_id=str(delegation[0]),
                acceptance_operation_id=admission.operation_id,
                chapter_number=int(request["chapter_number"]),
                chapter_outcome_asset_version_id=outcome.asset_version_id,
                story_state_asset_version_id=story_state.asset_version_id,
                canon_snapshot_asset_version_id=canon_snapshot.asset_version_id,
                longform_projection_set=longform_projection_set,
                evidence={
                    "child_root_operation_id": request["chapter_root_operation_id"],
                    "child_saga_id": request["chapter_saga_id"],
                    "final_release_gate": next(
                        item["asset_version_id"]
                        for item in evidence["outputs"]
                        if item["asset_type"] == "final_release_gate_report"
                    ),
                    "cost_receipt_refs": list(evidence.get("cost_receipt_refs") or ()),
                    "followup_snapshot": followup_snapshot,
                },
                before_cursor_advance=lambda: self._probe(
                    "after_acceptance_before_cursor"
                ),
                expected_book_version=int(current["version"]),
            )
            command_payload = dict(request.get("command_payload") or {})
            realization_id = str(command_payload.get("narrative_realization_id") or "")
            if book["input_mode"] == "RESOLVED_AUTHORITY_INPUT" and not realization_id:
                raise KernelError(
                    "NARRATIVE_REALIZATION_REQUIRED",
                    "resolved Chapter acceptance lost its Frozen realization lineage",
                )
            realization_coverage: dict[str, Any] = {}
            if realization_id:
                realization_coverage = NarrativeRealizationRepository(
                    uow.cursor
                ).consume_accepted_chapter(
                    project_id=request["project_id"],
                    book_id=book["book_id"],
                    realization_id=realization_id,
                    chapter_number=int(request["chapter_number"]),
                    chapter_plan_asset_version_id=str(request["chapter_plan_version"]),
                    acceptance_id=acceptance_id,
                    chapter_outcome_asset_version_id=outcome.asset_version_id,
                    realization_evidence=[
                        dict(item)
                        for item in outcome_content.get("realization_evidence") or ()
                        if isinstance(item, dict)
                    ],
                    operation_id=operation_id,
                )
                uow.cursor.execute(
                    """
                    UPDATE story_plan_binding
                    SET execution_scope='EXECUTED', version=version+1
                    WHERE project_id=%s AND book_id=%s
                      AND asset_version_id=%s AND contract_type='CHAPTER'
                      AND execution_scope='FROZEN' AND freshness='CURRENT'
                    """,
                    [
                        request["project_id"],
                        book["book_id"],
                        request["chapter_plan_version"],
                    ],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "CHAPTER_PLAN_EXECUTION_SCOPE_CONFLICT",
                        "accepted Chapter requires one current Frozen ChapterPlan",
                    )
                if realization_coverage["deviations"]:
                    uow.cursor.execute(
                        """
                        UPDATE authority_book_production
                        SET state='REPLAN_REQUIRED', version=version+1,
                            updated_at=NOW()
                        WHERE book_run_id=%s AND accepted_through_chapter=%s
                          AND state IN ('READY','CHECKPOINT_PENDING')
                        """,
                        [request["book_run_id"], int(request["chapter_number"])],
                    )
                    if uow.cursor.rowcount != 1:
                        raise KernelError(
                            "BOOK_REALIZATION_DEVIATION_REPLAN_CONFLICT",
                            "realization deviation could not request future-only replan",
                        )
            checkpoint("after_chapter_acceptance")
            return {
                "acceptance_id": acceptance_id,
                "chapter_request_id": chapter_request_id,
                "chapter_number": int(request["chapter_number"]),
                "chapter_outcome_asset_version_id": outcome.asset_version_id,
                "story_state_asset_version_id": story_state.asset_version_id,
                "canon_snapshot_asset_version_id": canon_snapshot.asset_version_id,
                "longform_projection_set_id": longform_projection_set[
                    "projection_set_id"
                ],
                "narrative_realization_coverage": realization_coverage,
            }

        self._execute_mutation(
            book=current,
            action="chapter_accept",
            event_type="book.chapter.accepted",
            idempotency_key=f"{stable_key}:book-commit",
            actor_id=principal.principal_id,
            trace_id=f"{request['chapter_root_operation_id']}:book-accept",
            correlation_id=str(book["root_operation_id"]),
            causation_id=admission.operation_id,
            payload={
                "chapter_request_id": chapter_request_id,
                "chapter_number": int(request["chapter_number"]),
                "acceptance_operation_id": admission.operation_id,
            },
            handler=commit_acceptance,
            input_assets=(*editorial_inputs, *reality_approval_inputs),
        )
        self._probe("after_acceptance_commit")
        result = self.require(request["book_run_id"])
        return {
            **result,
            "acceptance_operation_id": admission.operation_id,
            "last_chapter_outcome_version_id": outcome.asset_version_id,
            "active_story_state_version_id": story_state.asset_version_id,
            "active_canon_snapshot_version_id": canon_snapshot.asset_version_id,
        }

    def pause(
        self, book_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        book = self.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        if book["state"] in {
            BookProductionState.COMPLETED.value,
            BookProductionState.ABORTED.value,
        }:
            raise KernelError(
                "BOOK_GATE_TERMINAL", "terminal Book production cannot be paused"
            )
        context = self._book_graph_context(book, principal.principal_id)
        transition_saga_gate(
            self.database_url,
            context,
            str(book["saga_id"]),
            target_status="WAITING_GATE",
            reason=reason or "operator pause",
        )
        expected_version = int(book["version"])

        def commit_pause(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            _checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            self._cas_book_state(
                uow,
                book_run_id=book_run_id,
                expected_version=expected_version,
                target_state=BookProductionState.PAUSED,
                paused_reason=reason or "operator pause",
            )
            return {
                "book_run_id": book_run_id,
                "state": BookProductionState.PAUSED.value,
            }

        self._execute_mutation(
            book=book,
            action="pause",
            event_type="book.production.paused",
            idempotency_key=(
                f"{book['stable_idempotency_key']}:pause:v{expected_version}"
            ),
            actor_id=principal.principal_id,
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
            causation_id=str(book["root_operation_id"]),
            payload={"reason": reason or "operator pause"},
            handler=commit_pause,
        )
        return self.require(book_run_id)

    def cancel(
        self, book_run_id: str, *, reason: str, principal: Principal
    ) -> dict[str, Any]:
        book = self.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        if book["state"] == BookProductionState.COMPLETED.value:
            return book
        context = self._book_graph_context(book, principal.principal_id)
        request_id = str(book["active_chapter_request_id"] or "")
        if request_id:
            request = self.require_chapter_request(request_id)
            child_root = str(request["chapter_root_operation_id"] or "")
            if child_root:
                self.chapter_port.cancel(
                    project_id=book["project_id"],
                    root_operation_id=child_root,
                    actor_id=principal.principal_id,
                    reason=reason or "Book production cancelled",
                    idempotency_key=f"{book['stable_idempotency_key']}:cancel-child",
                    trace_id=context.trace_id,
                    correlation_id=context.correlation_id,
                )
        if book["state"] == BookProductionState.ABORTED.value:
            return self.require(book_run_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            root = uow.repositories.attempt_runtime.operation_state(
                str(book["root_operation_id"]), book["project_id"]
            )
        if root["status"] not in {
            "CANCELLED",
            "CANCELLATION_REQUESTED",
            "SUCCEEDED",
            "FAILED_FINAL",
            "DEAD_LETTER",
        }:
            request_cancellation(
                self.database_url,
                CancelCommand(
                    operation_id=str(book["root_operation_id"]),
                    project_id=book["project_id"],
                    actor_id=principal.principal_id,
                    reason=reason or "Book production cancelled",
                    expected_version=int(root["version"]),
                    idempotency_key=f"{book['stable_idempotency_key']}:cancel-root",
                    trace_id=context.trace_id,
                    correlation_id=context.correlation_id,
                ),
            )
        current = self.require(book_run_id)
        if current["state"] in {BookProductionState.COMPLETED.value, BookProductionState.ABORTED.value}:
            return current
        expected_version = int(current["version"])

        def commit_abort(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            _checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.repositories.book_authority.request_delegation_cancellation(
                book_run_id=book_run_id
            )
            self._cas_book_state(
                uow,
                book_run_id=book_run_id,
                expected_version=expected_version,
                target_state=BookProductionState.ABORTED,
                paused_reason=reason or "Book production cancelled",
                failure_reason=reason or "Book production cancelled",
            )
            return {
                "book_run_id": book_run_id,
                "state": BookProductionState.ABORTED.value,
            }

        self._execute_mutation(
            book=current,
            action="abort",
            event_type="book.production.aborted",
            idempotency_key=(
                f"{book['stable_idempotency_key']}:abort:v{expected_version}"
            ),
            actor_id=principal.principal_id,
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
            causation_id=str(book["root_operation_id"]),
            payload={"reason": reason or "Book production cancelled"},
            handler=commit_abort,
        )
        return self.require(book_run_id)

    def resume(
        self, book_run_id: str, *, reason: str, principal: Principal, expected_version: int | None = None,
    ) -> dict[str, Any]:
        book = self.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        if expected_version is not None and int(book["version"]) != expected_version:
            raise KernelError("BOOK_MUTATION_CONFLICT", "Book checkpoint changed before its requested resume")
        if book["state"] != BookProductionState.PAUSED.value:
            raise KernelError(
                "BOOK_GATE_NOT_PAUSED", "only a paused Book production can resume"
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT status, followup_id
                FROM authority_arc_checkpoint_followup
                WHERE book_run_id=%s
                  AND projection_set_id=%s
                  AND status IN (
                    'FAILED_FINAL','DEAD_LETTER','CANCELLED',
                    'MANUAL_INTERVENTION'
                  )
                ORDER BY updated_at DESC, followup_id
                LIMIT 1
                """,
                [book_run_id, str(book["active_longform_projection_set_id"] or "")],
            )
            unresolved_arc_followup = uow.cursor.fetchone()
        if unresolved_arc_followup is not None:
            raise KernelError(
                "ARC_CHECKPOINT_RECOVERY_REQUIRED",
                "Book cannot resume until terminal Arc follow-up evidence is "
                "resolved or the Book is explicitly aborted: "
                f"{unresolved_arc_followup[1]} ({unresolved_arc_followup[0]})",
            )
        context = self._book_graph_context(book, principal.principal_id)
        transition_saga_gate(
            self.database_url,
            context,
            str(book["saga_id"]),
            target_status="RUNNING",
            reason=reason or "operator resume",
        )
        next_state = BookProductionState.READY
        active_request_id = str(book["active_chapter_request_id"] or "")
        if active_request_id:
            request = self.reconcile_chapter(active_request_id)
            next_state = {
                "SUBMITTING": BookProductionState.CHAPTER_SUBMITTED,
                "ADMITTED": BookProductionState.CHAPTER_SUBMITTED,
                "RUNNING": BookProductionState.CHAPTER_RUNNING,
                "WAITING_RETRY": BookProductionState.CHAPTER_WAITING_RETRY,
                "SUCCEEDED": BookProductionState.CHAPTER_COMPLETED,
                "FAILED_RETRYABLE": BookProductionState.CHAPTER_FAILED_RETRYABLE,
                "FAILED_TERMINAL": BookProductionState.CHAPTER_FAILED_TERMINAL,
            }.get(str(request["status_reference"]), BookProductionState.READY)
        current = self.require(book_run_id)
        expected_version = int(current["version"]) if expected_version is None else expected_version

        def commit_resume(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            _checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            self._cas_book_state(
                uow,
                book_run_id=book_run_id,
                expected_version=expected_version,
                target_state=next_state,
            )
            return {"book_run_id": book_run_id, "state": next_state.value}

        self._execute_mutation(
            book=current,
            action="resume",
            event_type="book.production.resumed",
            idempotency_key=(
                f"{book['stable_idempotency_key']}:resume:v{expected_version}"
            ),
            actor_id=principal.principal_id,
            trace_id=context.trace_id,
            correlation_id=context.correlation_id,
            causation_id=str(book["root_operation_id"]),
            payload={"reason": reason or "operator resume", "state": next_state.value},
            handler=commit_resume,
        )
        return self.require(book_run_id)

    def advance_supervisor_checkpoint(
        self,
        book_run_id: str,
        *,
        expected_version: int,
        expected_state: str,
        target_state: BookProductionState,
        principal: Principal,
    ) -> str:

        book = self.require(book_run_id)
        principal.require("book.authority.execute", str(book["project_id"]))
        if (
            int(book["version"]) != expected_version
            or str(book["state"]) != expected_state
        ):
            raise KernelError(
                "BOOK_SUPERVISOR_CHECKPOINT_CONFLICT",
                "Book checkpoint changed during Supervisor Tick",
            )

        def commit_checkpoint(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            checkpoint("after_domain_validation")
            self._cas_book_state(
                uow,
                book_run_id=book_run_id,
                expected_version=expected_version,
                target_state=target_state,
            )
            return {
                "previous_state": expected_state,
                "state": target_state.value,
                "expected_version": expected_version,
            }

        result = self._execute_mutation(
            book=book,
            action="supervisor_checkpoint_advance",
            event_type="book.supervisor.checkpoint.advanced",
            idempotency_key=(
                f"{book['stable_idempotency_key']}:supervisor-state:"
                f"{expected_version}:{target_state.value}"
            ),
            actor_id=principal.principal_id,
            trace_id=(f"{book['root_operation_id']}:supervisor:{target_state.value}"),
            correlation_id=str(book["root_operation_id"]),
            causation_id=str(book["root_operation_id"]),
            payload={
                "previous_state": expected_state,
                "state": target_state.value,
                "expected_version": expected_version,
            },
            handler=commit_checkpoint,
        )
        return str(result["operation_id"])

    def bind_replanned_input_snapshot(
        self,
        book_run_id: str,
        *,
        snapshot_id: str,
        causation_operation_id: str,
        target_state: BookProductionState,
        expected_version: int,
        principal: Principal,
    ) -> dict[str, Any]:
        book = self.require(book_run_id)
        principal.require("book.authority.execute", book["project_id"])
        if target_state not in {
            BookProductionState.PAUSED,
            BookProductionState.READY,
            BookProductionState.CHAPTER_GROUP_REQUIRED,
            BookProductionState.CHAPTER_PLAN_REQUIRED,
            BookProductionState.PLANNING_REQUIRED,
        }:
            raise ValueError("replanned Book input target state is invalid")
        if (
            str(book.get("input_snapshot_id") or "") == snapshot_id
            and str(book["state"]) == target_state.value
        ):
            return book
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                book_replan_input_binding_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()

        def handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.cursor.execute(
                """
                SELECT version, COALESCE(input_snapshot_id,''), state
                FROM authority_book_production
                WHERE book_run_id=%s FOR UPDATE
                """,
                [book_run_id],
            )
            locked = uow.cursor.fetchone()
            if locked is not None and (
                str(locked[1]) == snapshot_id and str(locked[2]) == target_state.value
            ):
                return {
                    "book_run_id": book_run_id,
                    "state": target_state.value,
                    "input_snapshot_id": snapshot_id,
                }
            if locked is None or int(locked[0]) != expected_version:
                raise KernelError(
                    "BOOK_REPLAN_CHECKPOINT_CONFLICT",
                    "Book checkpoint changed before replacement input binding",
                )
            uow.cursor.execute(
                """
                SELECT project_id, book_id FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s
                """,
                [snapshot_id],
            )
            snapshot = uow.cursor.fetchone()
            if snapshot != (book["project_id"], book["book_id"]):
                raise KernelError(
                    "BOOK_REPLAN_INPUT_SCOPE_MISMATCH",
                    "replacement input snapshot belongs to another Book",
                )
            checkpoint("after_domain_validation")
            uow.cursor.execute(
                """
                SELECT COALESCE(MAX(binding_version),0)
                FROM authority_book_production_input_binding
                WHERE book_run_id=%s
                """,
                [book_run_id],
            )
            binding_version = int(uow.cursor.fetchone()[0]) + 1
            binding_id = (
                "book-input-binding:"
                + hashlib.sha256(
                    f"{book_run_id}:{binding_version}:{snapshot_id}".encode()
                ).hexdigest()
            )
            uow.repositories.book_authority.create_input_binding(
                {
                    "binding_id": binding_id,
                    "project_id": book["project_id"],
                    "book_id": book["book_id"],
                    "book_run_id": book_run_id,
                    "binding_version": binding_version,
                    "snapshot_id": snapshot_id,
                    "reason": "PLAN_CHANGE_ACTIVATED",
                    "bound_by_operation_id": operation_id,
                },
                ignore_replay_conflict=False,
            )
            if not uow.repositories.book_authority.bind_input_snapshot(
                book_run_id=book_run_id,
                snapshot_id=snapshot_id,
                state=target_state.value,
                expected_version=expected_version,
            ):
                raise KernelError(
                    "BOOK_REPLAN_CHECKPOINT_CONFLICT",
                    "Book checkpoint changed before replacement input binding",
                )
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "book_production_input_binding",
                    "aggregate_id": binding_id,
                    "operation_id": operation_id,
                    "project_id": str(book["project_id"]),
                    "event_type": "book.production_input.replanned",
                    "correlation_id": causation_operation_id,
                    "causation_id": causation_operation_id,
                    "payload": {
                        "operation_id": operation_id,
                        "book_run_id": book_run_id,
                        "binding_id": binding_id,
                        "binding_version": binding_version,
                        "snapshot_id": snapshot_id,
                        "state": target_state.value,
                    },
                }
            )
            checkpoint("after_outbox_insert")
            return {
                "book_run_id": book_run_id,
                "state": target_state.value,
                "input_snapshot_id": snapshot_id,
                "binding_id": binding_id,
            }

        result = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "book.production_input.replan_bind",
                "definition_version": "1.0.0",
                "project_id": str(book["project_id"]),
                "workspace_id": str(book["workspace_id"]),
                "book_id": str(book["book_id"]),
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:production-input-binding",
                "idempotency_key": (
                    f"{book['stable_idempotency_key']}:replan-input:{snapshot_id}"
                ),
                "trace_id": f"{causation_operation_id}:book-replan-input",
                "span_id": str(uuid4()),
                "correlation_id": causation_operation_id,
                "causation_id": causation_operation_id,
                "causation_operation_id": causation_operation_id,
                "input": {
                    "book_run_id": book_run_id,
                    "snapshot_id": snapshot_id,
                    "target_state": target_state.value,
                    "expected_version": expected_version,
                },
                "input_assets": [],
            },
            context=AdmissionContext(
                actor_id=principal.principal_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset(
                    {"novel_forge.book_authority.production_input.replan_bind"}
                ),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=handler,
        )
        return {**self.require(book_run_id), "operation_id": result["operation_id"]}

    def recover_chapter_submission(
        self, chapter_request_id: str, *, principal: Principal
    ) -> dict[str, Any]:
        request = self.require_chapter_request(chapter_request_id)
        principal.require("book.authority.execute", self.require(request["book_run_id"])["project_id"])
        if request["chapter_root_operation_id"]:
            return self.reconcile_chapter(chapter_request_id)
        payload = dict(request["command_payload"])
        if payload.get("execution_replacement_chapter_command"):
            from .execution_recovery import resume_successor
            return resume_successor(self, chapter_request_id=chapter_request_id, principal=principal)
        if payload.get("author_replacement_chapter_command"):
            from .author_revision import resume_author_chapter_replacement
            return resume_author_chapter_replacement(self, chapter_request_id=chapter_request_id, principal=principal)
        return self._dispatch_reserved_chapter(chapter_request_id, principal=principal)

    def reconcile_chapter(self, chapter_request_id: str) -> dict[str, Any]:
        request = self.require_chapter_request(chapter_request_id)
        if (
            self._find_chapter_acceptance(
                chapter_request_id=chapter_request_id,
                project_id=request["project_id"],
            )
            is not None
        ):
            # INVARIANT: Acceptance and the Book narrative cursor commit atomically. A
            # ChapterGroup replay may still need to consume that acceptance,
            # but reconciliation must never regress the accepted Book state.
            return request
        book = self.require(request["book_run_id"])
        if book["active_chapter_request_id"] != chapter_request_id:
            return request
        root = request["chapter_root_operation_id"]
        if not root:
            return request
        run = self.chapter_port.require_run(
            project_id=request["project_id"], root_operation_id=root
        )
        operation_status = str(run["status"])
        saga_status = str(run.get("saga", {}).get("status") or "")
        if operation_status == "SUCCEEDED" or saga_status == "SUCCEEDED":
            request_status, book_state = (
                "SUCCEEDED",
                BookProductionState.CHAPTER_COMPLETED,
            )
        elif operation_status == "FAILED_RETRYABLE":
            request_status, book_state = (
                "FAILED_RETRYABLE",
                BookProductionState.CHAPTER_FAILED_RETRYABLE,
            )
        elif operation_status in {"FAILED_FINAL", "DEAD_LETTER"}:
            request_status, book_state = (
                "FAILED_TERMINAL",
                BookProductionState.CHAPTER_FAILED_TERMINAL,
            )
        elif operation_status == "CANCELLED":
            request_status, book_state = "CANCELLED", BookProductionState.PAUSED
        else:
            request_status, book_state = "RUNNING", BookProductionState.CHAPTER_RUNNING
        book = self.require(request["book_run_id"])
        if request["status_reference"] == request_status and book["state"] == book_state.value:
            return request
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT actor_id, trace_id, correlation_id
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                """,
                [book["root_operation_id"], book["project_id"]],
            )
            root_identity = uow.cursor.fetchone()
        if root_identity is None:
            raise KernelError(
                "BOOK_ROOT_OPERATION_MISSING",
                "Book root Operation is missing during child reconciliation",
            )

        def commit_reconciliation(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.repositories.book_authority.record_chapter_status(
                chapter_request_id=chapter_request_id,
                book_run_id=request["book_run_id"],
                request_status=request_status,
                book_state=book_state.value,
                expected_request_status=str(request["status_reference"]),
                expected_book_version=int(book["version"]),
            )
            checkpoint("after_chapter_status_reconciliation")
            return {
                "chapter_request_id": chapter_request_id,
                "request_status": request_status,
                "state": book_state.value,
            }

        self._execute_mutation(
            book=book,
            action="chapter_reconcile",
            event_type="book.chapter.status_reconciled",
            idempotency_key=(
                f"{request['stable_idempotency_key']}:reconcile:"
                f"{request['status_reference']}:{request_status}:"
                f"{run.get('version', 0)}:{run.get('saga', {}).get('version', 0)}"
            ),
            actor_id=str(root_identity[0]),
            trace_id=str(root_identity[1]),
            correlation_id=str(root_identity[2]),
            causation_id=str(root),
            payload={
                "chapter_request_id": chapter_request_id,
                "child_operation_status": operation_status,
                "child_saga_status": saga_status,
            },
            handler=commit_reconciliation,
        )
        return self.require_chapter_request(chapter_request_id)

    def schedule_reader_outcome(
        self,
        chapter_request_id: str,
        *,
        principal: Principal,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
    ) -> BookFollowupAdmission:
        return self._schedule_followup(
            chapter_request_id,
            principal=principal,
            definition_name=READER_OUTCOME_DEFINITION,
            followup_type="READER_OUTCOME",
            payload=payload,
            input_assets=input_assets,
        )

    def schedule_longform_recap(
        self,
        chapter_request_id: str,
        *,
        principal: Principal,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
    ) -> BookFollowupAdmission:
        return self._schedule_followup(
            chapter_request_id,
            principal=principal,
            definition_name=LONGFORM_RECAP_DEFINITION,
            followup_type="LONGFORM_RECAP",
            payload=payload,
            input_assets=input_assets,
        )

    def complete_book_checkpoint(
        self, book_run_id: str, *, chapter_number: int
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.target_chapter_count, book.saga_id, book.project_id,
                       root.actor_id, root.trace_id, root.correlation_id
                FROM authority_book_production AS book
                JOIN authority_operation AS root
                  ON root.operation_id=book.root_operation_id
                WHERE book.book_run_id=%s
                """,
                [book_run_id],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "BOOK_RUN_NOT_FOUND", "Book Authority run does not exist"
                )
        state = (
            BookProductionState.COMPLETED
            if chapter_number >= int(row[0])
            else BookProductionState.READY
        )
        book = self.require(book_run_id)
        expected_version = int(book["version"])

        def commit_checkpoint(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            _checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            if not uow.repositories.book_authority.advance_if_version(
                book_run_id=book_run_id,
                chapter_number=chapter_number,
                state=state.value,
                expected_version=expected_version,
            ):
                raise KernelError(
                    "BOOK_CHECKPOINT_CONFLICT",
                    "Book checkpoint changed before advancement",
                )
            return {
                "book_run_id": book_run_id,
                "chapter_number": chapter_number,
                "state": state.value,
            }

        self._execute_mutation(
            book=book,
            action="checkpoint_advance",
            event_type="book.checkpoint.advanced",
            idempotency_key=(
                f"{book['stable_idempotency_key']}:production-completion:"
                f"{chapter_number}:v{expected_version}"
            ),
            actor_id=str(row[3]),
            trace_id=str(row[4]),
            correlation_id=str(row[5]),
            causation_id=str(book["root_operation_id"]),
            payload={"chapter_number": chapter_number},
            handler=commit_checkpoint,
        )
        if state is BookProductionState.COMPLETED:
            coordinate_saga(
                self.database_url,
                GraphCommandContext(str(row[2]), str(row[3]), str(row[4]), str(row[5])),
                str(row[1]),
            )
        return self.require(book_run_id)

    def require(self, book_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book_run_id, project_id, workspace_id, book_id,
                       book_design_version, book_plan_version,
                       production_profile_version, longform_context_versions,
                       root_operation_id, saga_id,
                       stable_idempotency_key, state, current_chapter,
                       target_chapter_count, light_recap_cadence,
                       formal_recap_cadence, active_chapter_request_id,
                       version, paused_reason, failure_classification
                       ,accepted_through_chapter,
                       active_child_delegation_id, active_chapter_number,
                       active_plan_version_id, active_story_state_version_id,
                       active_canon_snapshot_version_id,
                       active_longform_projection_set_id,
                       last_chapter_outcome_version_id, failure_reason,
                       COALESCE(input_snapshot_id, ''), input_mode
                FROM authority_book_production WHERE book_run_id=%s
                """,
                [book_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_RUN_NOT_FOUND", "Book Authority run does not exist")
        fields = (
            "book_run_id",
            "project_id",
            "workspace_id",
            "book_id",
            "book_design_version",
            "book_plan_version",
            "production_profile_version",
            "longform_context_versions",
            "root_operation_id",
            "saga_id",
            "stable_idempotency_key",
            "state",
            "current_chapter",
            "target_chapter_count",
            "light_recap_cadence",
            "formal_recap_cadence",
            "active_chapter_request_id",
            "version",
            "paused_reason",
            "failure_classification",
            "accepted_through_chapter",
            "active_child_delegation_id",
            "active_chapter_number",
            "active_plan_version_id",
            "active_story_state_version_id",
            "active_canon_snapshot_version_id",
            "active_longform_projection_set_id",
            "last_chapter_outcome_version_id",
            "failure_reason",
            "input_snapshot_id",
            "input_mode",
        )
        return dict(zip(fields, row, strict=True))

    def _validate_input_snapshot(
        self, command: StartBookProductionCommand
    ) -> tuple[str, ...]:
        if command.input_mode == "LEGACY_FIXTURE_INPUT_MODE":
            return ()
        if (
            command.input_mode != "RESOLVED_AUTHORITY_INPUT"
            or not command.input_snapshot_id
        ):
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_SNAPSHOT_REQUIRED",
                "controlled Book Production must bind a resolved Authority snapshot",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id, workspace_id, book_id,
                       book_design_version, book_plan_version,
                       production_profile_version,
                       current_volume_plan_version,
                       current_relevant_arc_plan_versions,
                       COALESCE(current_chapter_group_plan_version, ''),
                       reader_segment_version, reader_contract_version,
                       platform_profile_version, character_state_version,
                       foreshadowing_state_version, quality_trend_version,
                       reward_ledger_version, promise_ledger_version,
                       COALESCE(initial_story_state_version, ''),
                       COALESCE(initial_canon_snapshot_version, ''),
                       profile.content
                FROM authority_book_production_input_snapshot AS snapshot
                JOIN authority_asset_version AS profile
                  ON profile.asset_version_id=snapshot.production_profile_version
                WHERE snapshot.snapshot_id=%s
                """,
                [command.input_snapshot_id],
            )
            row = uow.cursor.fetchone()
        if row is None or tuple(str(item) for item in row[:3]) != (
            command.project_id,
            command.workspace_id,
            command.book_id,
        ):
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_SNAPSHOT_SCOPE_INVALID",
                "Book Production snapshot does not belong to the requested scope",
            )
        if not str(row[17]) or not str(row[18]):
            raise KernelError(
                "BOOK_INITIAL_NARRATIVE_STATE_REQUIRED",
                "controlled Book Production requires an initial accepted Story State and Canon pair",
            )
        expected = {
            "book_design_version": str(row[3]),
            "book_plan_version": str(row[4]),
            "production_profile_version": str(row[5]),
            "volume_plan_version": str(row[6]),
            "reader_segment_version": str(row[9]),
            "reader_contract_version": str(row[10]),
            "platform_profile_version": str(row[11]),
            "character_state_version": str(row[12]),
            "foreshadowing_state_version": str(row[13]),
            "quality_trend_version": str(row[14]),
            "reward_ledger_version": str(row[15]),
            "promise_ledger_version": str(row[16]),
        }
        if (
            command.book_design_version != expected["book_design_version"]
            or command.book_plan_version != expected["book_plan_version"]
            or command.production_profile_version
            != expected["production_profile_version"]
            or any(
                command.longform_context_versions[key] != value
                for key, value in expected.items()
                if key in LONGFORM_CONTEXT_VERSION_KEYS
            )
            or tuple(command.longform_context_versions["arc_plan_versions"])
            != tuple(str(item) for item in row[7])
            or command.target_chapter_count
            != int(dict(row[19]).get("target_chapter_count") or 0)
        ):
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_SNAPSHOT_DRIFT",
                "caller projection differs from the immutable Authority snapshot",
            )
        self._require_completed_opening_workflow_for_snapshot(command)
        values = [str(item) for item in row[3:7]]
        values.extend(str(item) for item in row[7])
        if row[8]:
            values.append(str(row[8]))
        values.extend(str(item) for item in row[9:17])
        values.extend(str(item) for item in row[17:19] if item)
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _require_snapshot_plan_portfolio_current_in_uow(
        uow: AuthorityUnitOfWork,
        command: StartBookProductionCommand,
        *,
        book_version: int,
        book_design_version: str,
        book_status: str,
    ) -> None:
        if command.input_mode != "RESOLVED_AUTHORITY_INPUT":
            return
        uow.cursor.execute(
            """
            SELECT expected_book_version,book_design_version,book_plan_version,
                   volume_portfolio_plan_versions,arc_portfolio_plan_versions
            FROM authority_book_production_input_snapshot
            WHERE snapshot_id=%s AND project_id=%s
              AND workspace_id=%s AND book_id=%s
            FOR KEY SHARE
            """,
            [
                command.input_snapshot_id,
                command.project_id,
                command.workspace_id,
                command.book_id,
            ],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_PRODUCTION_INPUT_SNAPSHOT_SCOPE_INVALID",
                "BookRun snapshot changed before admission commit",
            )
        if (
            int(row[0]) != book_version
            or str(row[1]) != book_design_version
            or book_status != "DESIGN_ACTIVE"
        ):
            raise KernelError(
                "BOOK_INPUT_BOOK_AUTHORITY_STALE",
                "BookRun snapshot no longer matches the locked Book Authority epoch",
            )
        book_plan_id = str(row[2])
        volume_ids = tuple(str(item) for item in row[3])
        arc_ids = tuple(str(item) for item in row[4])
        portfolio = (book_plan_id, *volume_ids, *arc_ids)
        if len(portfolio) != len(set(portfolio)):
            raise KernelError(
                "BOOK_INPUT_PORTFOLIO_STALE",
                "BookRun snapshot has a duplicate Plan portfolio",
            )
        uow.cursor.execute(
            """
            SELECT binding.asset_version_id,binding.contract_type,
                   binding.freshness
            FROM active_story_plan_version AS active
            JOIN story_plan_binding AS binding
              ON binding.binding_id=active.binding_id
             AND binding.asset_version_id=active.asset_version_id
            JOIN authority_asset_version AS version
              ON version.asset_version_id=binding.asset_version_id
            WHERE binding.project_id=%s AND binding.book_id=%s
              AND binding.asset_version_id=ANY(%s)
              AND version.lifecycle='ACTIVE'
              AND version.eligibility='ELIGIBLE'
              AND version.governance='CLEAR'
            FOR SHARE OF active,binding,version
            """,
            [command.project_id, command.book_id, list(portfolio)],
        )
        bindings = {
            str(asset_id): (str(contract_type), str(freshness))
            for asset_id, contract_type, freshness in uow.cursor.fetchall()
        }
        expected = {
            book_plan_id: "BOOK",
            **{asset_id: "VOLUME" for asset_id in volume_ids},
            **{asset_id: "ARC" for asset_id in arc_ids},
        }
        if set(bindings) != set(expected) or any(
            bindings[asset_id] != (contract_type, "CURRENT")
            for asset_id, contract_type in expected.items()
        ):
            raise KernelError(
                "BOOK_INPUT_PORTFOLIO_STALE",
                "BookRun snapshot Plan portfolio is no longer active and current",
            )

    def _require_completed_opening_workflow_for_snapshot(
        self, command: StartBookProductionCommand
    ) -> None:
        """COMPATIBILITY: Gate BookRun admission on an exact terminal Opening evidence link.

        Migration 0104 transactionally entitles the exact InputSnapshot rows
        that already existed at cutover.  New snapshots must instead have the
        immutable final-node binding written by the Opening completion UoW, or
        exact legacy-monolithic completion evidence.  Wall-clock timestamps are
        never used as authorization provenance.
        """
        from .opening_progress import PostgresBookOpeningWorkflowProgressQuery

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT link.opening_run_id,opening.lifecycle,
                       opening.current_workflow_node_id,opening.result,
                       link.workflow_node_id,link.node_receipt_id,
                       link.checkpoint_id,link.checkpoint_sequence,
                       link.checkpoint_hash,link.snapshot_hash,
                       snapshot.snapshot_hash,receipt.reviewable_artifact_kind
                FROM authority_book_opening_input_snapshot_binding AS link
                JOIN authority_book_opening_run AS opening
                  ON opening.opening_run_id=link.opening_run_id
                JOIN authority_book_opening_node_receipt AS receipt
                  ON receipt.opening_run_id=link.opening_run_id
                 AND receipt.node_receipt_id=link.node_receipt_id
                 AND receipt.workflow_node_id=link.workflow_node_id
                JOIN authority_book_production_input_snapshot AS snapshot
                  ON snapshot.snapshot_id=link.snapshot_id
                WHERE link.snapshot_id=%s
                  AND opening.project_id=%s
                  AND opening.workspace_id=%s
                  AND opening.book_id=%s
                """,
                [
                    command.input_snapshot_id,
                    command.project_id,
                    command.workspace_id,
                    command.book_id,
                ],
            )
            bindings = tuple(uow.cursor.fetchall())
            legacy_opening_run_id = ""
            legacy_snapshot_entitled = False
            if not bindings:
                uow.cursor.execute(
                    """
                    SELECT entitlement.snapshot_id
                    FROM authority_book_opening_legacy_snapshot_entitlement
                         AS entitlement
                    JOIN authority_book_production_input_snapshot AS snapshot
                      ON snapshot.snapshot_id=entitlement.snapshot_id
                     AND snapshot.project_id=entitlement.project_id
                     AND snapshot.workspace_id=entitlement.workspace_id
                     AND snapshot.book_id=entitlement.book_id
                     AND snapshot.snapshot_hash=entitlement.snapshot_hash
                    WHERE entitlement.snapshot_id=%s
                      AND entitlement.project_id=%s
                      AND entitlement.workspace_id=%s
                      AND entitlement.book_id=%s
                      AND entitlement.source_migration_id=
                          '20260829_0104_book_opening_workflow_nodes'
                    """,
                    [
                        command.input_snapshot_id,
                        command.project_id,
                        command.workspace_id,
                        command.book_id,
                    ],
                )
                legacy_snapshot_entitled = len(tuple(uow.cursor.fetchall())) == 1
                uow.cursor.execute(
                    """
                    SELECT opening_run_id,lifecycle,result
                    FROM authority_book_opening_run
                    WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                      AND workflow_contract_version='legacy-monolithic-v2'
                      AND lifecycle='COMPLETE'
                      AND result->>'input_snapshot_id'=%s
                    """,
                    [
                        command.project_id,
                        command.workspace_id,
                        command.book_id,
                        command.input_snapshot_id,
                    ],
                )
                legacy_rows = tuple(uow.cursor.fetchall())
                if len(legacy_rows) == 1 and isinstance(legacy_rows[0][2], dict):
                    legacy_opening_run_id = str(legacy_rows[0][0])
        if legacy_snapshot_entitled:
            return
        if legacy_opening_run_id:
            legacy_progress = PostgresBookOpeningWorkflowProgressQuery(
                self.database_url
            ).progress(opening_run_id=legacy_opening_run_id)
            legacy_report = legacy_progress.to_dict()
            legacy_checkpoint = legacy_report.get("persistent_checkpoint")
            if (
                legacy_progress.compatibility_mode == "LEGACY_MONOLITHIC"
                and legacy_progress.progress_status == "COMPLETE"
                and isinstance(legacy_checkpoint, dict)
                and str(legacy_checkpoint.get("status") or "") == "AVAILABLE_LEGACY"
            ):
                return
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_EVIDENCE_INVALID",
                "Legacy Book Opening has no exact completed checkpoint evidence",
            )
        if len(bindings) != 1:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_COMPLETION_REQUIRED",
                "BookRun input must have one exact final Book Opening workflow binding",
            )
        (
            opening_run_id,
            lifecycle,
            current_node_id,
            result,
            bound_node_id,
            _node_receipt_id,
            checkpoint_id,
            checkpoint_sequence,
            checkpoint_hash,
            bound_snapshot_hash,
            actual_snapshot_hash,
            artifact_kind,
        ) = bindings[0]
        if (
            str(lifecycle) != "COMPLETE"
            or str(current_node_id or "") != str(bound_node_id)
            or not isinstance(result, dict)
            or str(result.get("input_snapshot_id") or "") != command.input_snapshot_id
            or str(bound_snapshot_hash) != str(actual_snapshot_hash)
            or str(artifact_kind) != "BOOK_PRODUCTION_INPUT_SNAPSHOT"
        ):
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_COMPLETION_REQUIRED",
                "BookRun cannot start before the Input Snapshot layer completes",
            )
        progress = PostgresBookOpeningWorkflowProgressQuery(self.database_url).progress(
            opening_run_id=str(opening_run_id)
        )
        projected = progress.to_dict()
        furthest = projected.get("furthest_completed_layer")
        artifact = projected.get("reviewable_artifact")
        checkpoint = projected.get("persistent_checkpoint")
        if (
            progress.progress_status != "COMPLETE"
            or not isinstance(furthest, dict)
            or str(furthest.get("node_kind") or "") != "INPUT_SNAPSHOT"
            or not isinstance(artifact, dict)
            or str(artifact.get("status") or "") != "AVAILABLE"
            or str(artifact.get("artifact_kind") or "")
            != "BOOK_PRODUCTION_INPUT_SNAPSHOT"
            or not isinstance(checkpoint, dict)
            or str(checkpoint.get("status") or "") != "AVAILABLE"
            or str(checkpoint.get("source_workflow_node_id") or "")
            != str(bound_node_id)
            or str(checkpoint.get("checkpoint_id") or "") != str(checkpoint_id)
            or int(checkpoint.get("checkpoint_sequence") or 0)
            != int(checkpoint_sequence)
            or str(checkpoint.get("checkpoint_hash") or "") != str(checkpoint_hash)
        ):
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_EVIDENCE_INVALID",
                "BookRun admission requires an authoritative final asset and checkpoint",
            )

    def require_chapter_request(self, chapter_request_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT request.chapter_request_id, request.book_run_id,
                       request.project_id, request.chapter_number,
                       request.chapter_plan_version,
                       request.chapter_plan_content_hash,
                       request.parent_group_version_id,
                       request.production_profile_version,
                       request.stable_idempotency_key, request.command_payload,
                       request.chapter_root_operation_id,
                       request.chapter_saga_id,
                       request.status_reference, request.failure_classification,
                       delegation.delegation_id
                FROM authority_book_chapter_request AS request
                LEFT JOIN authority_child_delegation AS delegation
                  ON delegation.chapter_request_id=request.chapter_request_id
                WHERE request.chapter_request_id=%s
                """,
                [chapter_request_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_CHAPTER_REQUEST_NOT_FOUND", "chapter request does not exist"
            )
        fields = (
            "chapter_request_id",
            "book_run_id",
            "project_id",
            "chapter_number",
            "chapter_plan_version",
            "chapter_plan_content_hash",
            "parent_group_version_id",
            "production_profile_version",
            "stable_idempotency_key",
            "command_payload",
            "chapter_root_operation_id",
            "chapter_saga_id",
            "status_reference",
            "failure_classification",
            "delegation_id",
        )
        return dict(zip(fields, row, strict=True))

    def resolve_asset_refs(
        self, *, project_id: str, asset_version_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]:
        if len(asset_version_ids) != len(set(asset_version_ids)):
            raise KernelError(
                "BOOK_INPUT_VERSION_DUPLICATE",
                "Book Authority input AssetVersions must be distinct",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s
                  AND version.asset_version_id = ANY(%s)
                """,
                [project_id, list(asset_version_ids)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        missing = [item for item in asset_version_ids if item not in found]
        if missing:
            raise KernelError(
                "BOOK_AUTHORITY_INPUT_ASSET_MISSING",
                "missing immutable Book input AssetVersions: " + ", ".join(missing),
            )
        return tuple(
            {"asset_version_id": item, "content_hash": found[item]}
            for item in asset_version_ids
        )

    def _schedule_followup(
        self,
        chapter_request_id: str,
        *,
        principal: Principal,
        definition_name: str,
        followup_type: str,
        payload: dict[str, Any],
        input_assets: tuple[dict[str, str], ...],
    ) -> BookFollowupAdmission:
        request = self.require_chapter_request(chapter_request_id)
        if (
            followup_type == "READER_OUTCOME"
            and request["status_reference"] != "SUCCEEDED"
        ):
            raise KernelError(
                "BOOK_READER_OUTCOME_NOT_READY",
                "Reader Outcome requires a completed Chapter operation",
            )
        existing_operation_id = self._followup_operation_id(
            chapter_request_id=chapter_request_id,
            followup_type=followup_type,
        )
        if existing_operation_id:
            return BookFollowupAdmission(
                existing_operation_id,
                str(request["project_id"]),
                True,
            )
        required_lineage = (
            "observed_through_chapter",
            "acceptance_operation_id",
            "book_production_input_snapshot_id",
        )
        missing_lineage = [
            name for name in required_lineage if payload.get(name) in (None, "")
        ]
        if missing_lineage:
            raise KernelError(
                "BOOK_FOLLOWUP_ACCEPTED_LINEAGE_REQUIRED",
                "new follow-up admission is missing accepted lineage: "
                + ", ".join(missing_lineage),
            )
        stable_key = (
            f"{request['stable_idempotency_key']}:{followup_type.lower()}:"
            f"{payload.get('checkpoint_type') or 'v1'}"
        )
        book = self.require(request["book_run_id"])
        admission = self.followup.admit(
            BookFollowupCommand(
                definition_name=definition_name,
                project_id=request["project_id"],
                workspace_id=book["workspace_id"],
                actor_id=principal.principal_id,
                trace_id=f"{request['chapter_root_operation_id']}:{followup_type.lower()}",
                correlation_id=request["chapter_root_operation_id"],
                idempotency_key=stable_key,
                payload=payload,
                input_assets=input_assets,
                root_operation_id=None,
                parent_operation_id=None,
                causation_operation_id=str(
                    payload.get("acceptance_operation_id")
                    or request["chapter_root_operation_id"]
                ),
            ),
            principal=principal,
        )
        existing_operation_id = self._followup_operation_id(
            chapter_request_id=chapter_request_id,
            followup_type=followup_type,
        )
        if existing_operation_id:
            if existing_operation_id != admission.operation_id:
                raise KernelError(
                    "BOOK_FOLLOWUP_IDEMPOTENCY_CONFLICT",
                    "Chapter follow-up replay resolved to a different Operation",
                )
            return admission
        followup_id = "book-followup:" + hashlib.sha256(stable_key.encode()).hexdigest()

        def commit_followup_link(
            uow: AuthorityUnitOfWork,
            _operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            uow.repositories.book_authority.link_followup(
                followup_id=followup_id,
                book_run_id=request["book_run_id"],
                chapter_request_id=chapter_request_id,
                project_id=request["project_id"],
                followup_type=followup_type,
                operation_id=admission.operation_id,
                stable_idempotency_key=stable_key,
            )
            checkpoint("after_followup_link")
            return {
                "followup_id": followup_id,
                "followup_operation_id": admission.operation_id,
                "followup_type": followup_type,
            }

        self._execute_mutation(
            book=book,
            action="followup_link",
            event_type="book.followup.linked",
            idempotency_key=f"{stable_key}:book-link",
            actor_id=principal.principal_id,
            trace_id=f"{request['chapter_root_operation_id']}:followup-link",
            correlation_id=str(request["chapter_root_operation_id"]),
            causation_id=admission.operation_id,
            payload={
                "chapter_request_id": chapter_request_id,
                "followup_type": followup_type,
            },
            handler=commit_followup_link,
        )
        return admission

    def _accepted_followup_snapshot(
        self,
        *,
        book: dict[str, Any],
        request: dict[str, Any],
        chapter_outcome_asset_version_id: str,
        story_state_asset_version_id: str,
        canon_snapshot_asset_version_id: str,
        acceptance_operation_id: str,
    ) -> dict[str, Any]:

        command_payload = dict(request.get("command_payload") or {})
        context_refs = dict(command_payload.get("context_version_refs") or {})
        longform_refs = dict(book.get("longform_context_versions") or {})
        arc_plan_versions = tuple(
            str(item)
            for item in (
                context_refs.get("arc_plan_versions")
                or longform_refs.get("arc_plan_versions")
                or ()
            )
        )
        return {
            "schema_version": "book-followup-accepted-snapshot-v2",
            "observed_through_chapter": int(request["chapter_number"]),
            "context_token_budget": int(
                command_payload.get("context_token_budget") or 0
            ),
            "book_production_input_snapshot_id": str(
                context_refs.get("book_production_input_snapshot_id")
                or book.get("input_snapshot_id")
                or ""
            ),
            "book_design_version": str(
                context_refs.get("book_design_version") or book["book_design_version"]
            ),
            "book_plan_version": str(
                context_refs.get("book_plan_version") or book["book_plan_version"]
            ),
            "volume_plan_version": str(
                context_refs.get("volume_plan_version")
                or longform_refs.get("volume_plan_version")
                or ""
            ),
            "arc_plan_versions": list(arc_plan_versions),
            "chapter_group_plan_version": str(
                context_refs.get("chapter_group_plan_version")
                or request.get("parent_group_version_id")
                or ""
            ),
            "chapter_plan_version": str(request["chapter_plan_version"]),
            "production_profile_version": str(request["production_profile_version"]),
            "light_recap_cadence": int(book["light_recap_cadence"]),
            "formal_recap_cadence": int(book["formal_recap_cadence"]),
            "reader_segment_version": str(
                context_refs.get("reader_segment_version")
                or longform_refs.get("reader_segment_version")
                or ""
            ),
            "reader_contract_version": str(
                context_refs.get("reader_contract_version")
                or longform_refs.get("reader_contract_version")
                or ""
            ),
            "platform_profile_version": str(
                context_refs.get("platform_profile_version")
                or longform_refs.get("platform_profile_version")
                or ""
            ),
            "quality_trend_version": str(
                context_refs.get("quality_trend_version")
                or longform_refs.get("quality_trend_version")
                or ""
            ),
            "accepted_chapter_outcome_version": chapter_outcome_asset_version_id,
            "accepted_story_state_version": story_state_asset_version_id,
            "accepted_canon_snapshot_version": canon_snapshot_asset_version_id,
            "acceptance_operation_id": acceptance_operation_id,
            "chapter_root_operation_id": str(
                request.get("chapter_root_operation_id") or ""
            ),
        }

    def _followup_operation_id(
        self, *, chapter_request_id: str, followup_type: str
    ) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT operation_id
                FROM authority_book_followup_operation
                WHERE chapter_request_id=%s AND followup_type=%s
                """,
                [chapter_request_id, followup_type],
            )
            row = uow.cursor.fetchone()
        return str(row[0]) if row is not None else ""

    def _book_graph_context(
        self, book: dict[str, Any], actor_id: str
    ) -> GraphCommandContext:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT trace_id, correlation_id
                FROM authority_operation
                WHERE operation_id=%s AND project_id=%s
                """,
                [book["root_operation_id"], book["project_id"]],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_ROOT_OPERATION_MISSING", "Book root Operation is missing"
            )
        return GraphCommandContext(
            str(book["project_id"]), actor_id, str(row[0]), str(row[1])
        )

    def _find_chapter_acceptance(
        self, *, chapter_request_id: str, project_id: str
    ) -> dict[str, str] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT acceptance_operation_id,
                       chapter_outcome_asset_version_id,
                       story_state_asset_version_id,
                       canon_snapshot_asset_version_id,
                       longform_projection_set_id
                FROM authority_book_chapter_acceptance
                WHERE chapter_request_id=%s AND project_id=%s
                """,
                [chapter_request_id, project_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return {
            "acceptance_operation_id": str(row[0]),
            "chapter_outcome_asset_version_id": str(row[1]),
            "story_state_asset_version_id": str(row[2]),
            "canon_snapshot_asset_version_id": str(row[3]),
            "longform_projection_set_id": str(row[4] or ""),
        }

    def _initial_narrative_state_inputs(
        self, *, book: dict[str, Any], request: dict[str, Any]
    ) -> tuple[dict[str, str], ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COALESCE(initial_story_state_version, ''),
                       COALESCE(initial_canon_snapshot_version, '')
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s AND project_id=%s AND book_id=%s
                """,
                [
                    book["input_snapshot_id"],
                    book["project_id"],
                    book["book_id"],
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_INPUT_SNAPSHOT_MISSING",
                "Book initial Narrative State requires its frozen input snapshot",
            )
        versions = tuple(str(item or "") for item in row)
        if not any(versions):
            return ()
        if not all(versions):
            raise KernelError(
                "BOOK_INITIAL_NARRATIVE_STATE_INCOMPLETE",
                "initial Story State and Canon must advance together",
            )
        expected = dict(
            zip(("story_state_snapshot", "canon_snapshot"), versions, strict=True)
        )
        submitted = dict(request.get("command_payload") or {})
        candidates = tuple(submitted.get("context_candidates") or ())
        observed: dict[str, list[str]] = {key: [] for key in expected}
        for candidate in candidates:
            asset_type = str(candidate.get("asset_type") or "")
            if asset_type in observed:
                observed[asset_type].append(
                    str(candidate.get("asset_version_id") or "")
                )
        if any(observed[key] != [version] for key, version in expected.items()):
            raise KernelError(
                "BOOK_INITIAL_NARRATIVE_STATE_CONTEXT_LINEAGE_MISSING",
                "Chapter 1 did not consume the frozen initial Story State and Canon pair",
            )
        return self.resolve_asset_refs(
            project_id=str(book["project_id"]),
            asset_version_ids=versions,
        )

    def _context_candidates_for_dispatch(self, *, book_run_id: str, project_id: str,
                                         chapter_number: int, requested: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        from .chapter_dispatch import context_candidates_for_dispatch
        return context_candidates_for_dispatch(self.database_url, book_id=self.require(book_run_id)["book_id"],
            book_run_id=book_run_id, project_id=project_id, chapter_number=chapter_number, requested=requested)

    def _execute_mutation(
        self,
        *,
        book: dict[str, Any],
        action: str,
        event_type: str,
        idempotency_key: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
        payload: dict[str, Any],
        handler: Callable[
            [AuthorityUnitOfWork, str, TransactionCheckpoint], dict[str, Any]
        ],
        input_assets: tuple[dict[str, str], ...] = (),
    ) -> dict[str, Any]:

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.repositories.definitions.register(
                book_authority_mutation_definition(
                    application_build_id=self.application_build_id,
                    commit_sha=self.commit_sha,
                )
            )
            uow.commit()

        def governed_handler(
            uow: AuthorityUnitOfWork,
            operation_id: str,
            checkpoint: TransactionCheckpoint,
        ) -> dict[str, Any]:
            result = handler(uow, operation_id, checkpoint)
            event_payload = {
                "operation_id": operation_id,
                "action": action,
                "book_run_id": str(book["book_run_id"]),
                "book_id": str(book["book_id"]),
                **payload,
                **result,
            }
            uow.repositories.operation_graph.record_event(
                {
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                    "aggregate_type": "book_production",
                    "aggregate_id": str(book["book_run_id"]),
                    "operation_id": operation_id,
                    "project_id": str(book["project_id"]),
                    "event_type": event_type,
                    "correlation_id": correlation_id,
                    "causation_id": causation_id,
                    "payload": event_payload,
                }
            )
            checkpoint("after_business_event")
            return result

        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": BOOK_MUTATION_DEFINITION,
                "definition_version": BOOK_MUTATION_DEFINITION_VERSION,
                "project_id": str(book["project_id"]),
                "workspace_id": str(book["workspace_id"]),
                "book_id": str(book["book_id"]),
                "actor_id": actor_id,
                "idempotency_scope": "book:authority-mutation",
                "idempotency_key": idempotency_key,
                "trace_id": trace_id,
                "span_id": str(uuid4()),
                "correlation_id": correlation_id,
                "causation_id": causation_id,
                "causation_operation_id": causation_id,
                "input": {
                    "project_id": str(book["project_id"]),
                    "input_asset_version_ids": [ref["asset_version_id"] for ref in input_assets],
                    "payload": {
                        "action": action,
                        "book_run_id": str(book["book_run_id"]),
                        **payload,
                    },
                },
                "input_assets": list(input_assets),
            },
            context=AdmissionContext(
                actor_id=actor_id,
                permissions=frozenset({"book.authority.execute"}),
                available_handlers=frozenset({BOOK_MUTATION_HANDLER}),
                application_build_id=self.application_build_id,
                commit_sha=self.commit_sha,
            ),
            handler=governed_handler,
            fault_injector=self.failure_injector,
        )

    @staticmethod
    def _cas_book_state(
        uow: AuthorityUnitOfWork,
        *,
        book_run_id: str,
        expected_version: int,
        target_state: BookProductionState,
        paused_reason: str = "",
        failure_reason: str = "",
    ) -> None:
        if not uow.repositories.book_authority.compare_and_set_state(
            book_run_id=book_run_id,
            expected_version=expected_version,
            state=target_state.value,
            paused_reason=paused_reason,
            failure_reason=failure_reason,
        ):
            raise KernelError(
                "BOOK_MUTATION_CONFLICT",
                "Book Authority checkpoint changed before mutation commit",
            )

    def _probe(self, point: str) -> None:
        if self.failure_injector is not None:
            self.failure_injector(point)


def book_authority_mutation_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": BOOK_MUTATION_DEFINITION,
        "definition_version": BOOK_MUTATION_DEFINITION_VERSION,
        "family": "book_authority",
        "enabled": True,
        "definition_status": "integration_proven",
        "command_schema_version": "book.authority.mutate.command.v1",
        "result_schema_version": "book.authority.mutate.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "BookAuthorityMutationResult"},
        "handler_key": BOOK_MUTATION_HANDLER,
        "handler_contract_version": "book-authority-mutation-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "book:authority-mutation",
        "concurrency_key_template": "book:{book_id}:authority-mutation",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "CAS-protected deterministic Authority mutation",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "execution_classification": "transaction_command",
            "cas_required": True,
            "business_event_required": True,
            "attempt_runtime_forbidden": True,
        },
        "completion_contract": {
            "version": "book-authority-mutation-completion-v1",
            "required_evidence": ["trace", "audit"],
        },
    }


def book_replan_input_binding_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": "book.production_input.replan_bind",
        "definition_version": "1.0.0",
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented_validation_pending",
        "command_schema_version": "book.production_input.replan_bind.command.v1",
        "result_schema_version": "book.production_input.replan_bind.result.v1",
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {"type": "BookProductionInputBinding"},
        "handler_key": "novel_forge.book_authority.production_input.replan_bind",
        "handler_contract_version": "book-production-input-replan-binding-v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "book:production-input-binding",
        "concurrency_key_template": "book:{book_id}:production-input-binding",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 30},
        "cancellation_policy": {"mode": "not_applicable"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only snapshot binding",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "policy": {
            "execution_classification": "transaction_command",
            "plan_change_activation_required": True,
            "append_only_binding": True,
        },
        "completion_contract": {
            "version": "book-production-input-replan-binding-completion-v1",
            "required_evidence": ["trace", "audit", "input_snapshot"],
        },
    }


def book_coordinate_definition(
    *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {"type": "object"}
    return {
        "name": BOOK_COORDINATE_DEFINITION,
        "definition_version": BOOK_COORDINATE_DEFINITION_VERSION,
        "family": "book_authority",
        "command_schema_version": "book.production.coordinate.command.v1",
        "result_schema_version": "book.production.coordinate.result.v1",
        "enabled": True,
        "command_schema": schema,
        "result_schema": schema,
        "input_contract": schema,
        "output_contract": {
            "type": "book_authority_checkpoint",
            "authority_state_table": "authority_book_production",
        },
        "handler_key": BOOK_COORDINATE_HANDLER,
        "handler_contract_version": "book-authority-coordinator-v1",
        "definition_status": "integration_proven",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "saga",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "idempotency_scope": "project:book-coordinate",
        "concurrency_key_template": "project:{project_id}:book",
        "retry_policy": {"max_attempts": 1},
        "timeout_policy": {"operation_timeout_seconds": 86400},
        "cancellation_policy": {"mode": "cancel_children"},
        "compensation_policy": {
            "supported": False,
            "reason": "append-only child authority references",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["book_authority_checkpoint"],
        "migration_owner": "book-authority",
        "policy": {
            "execution_classification": "saga",
            "chapter_authority_state_ownership": "reference_only",
            "persistent_checkpoint_required": True,
        },
        "completion_contract": {
            "version": "book.production.coordinate.completion.v1",
            "required_evidence": ["trace", "audit", "book_checkpoint"],
        },
    }


def select_chapter_acceptance_outputs(
    evidence: dict[str, Any],
) -> dict[str, dict[str, Any]]:

    outputs = list(evidence.get("outputs") or ())
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in outputs:
        by_type.setdefault(str(item["asset_type"]), []).append(item)
    lineage_roots = (
        "chapter_plan",
        "release_package",
        "final_release_gate_report",
    )
    missing = [
        asset_type
        for asset_type in lineage_roots
        if len(by_type.get(asset_type, ())) != 1
    ]
    if missing:
        raise KernelError(
            "BOOK_CHAPTER_ACCEPTANCE_EVIDENCE_MISSING",
            "missing unique Chapter outputs: " + ", ".join(missing),
        )
    selected = {key: by_type[key][0] for key in lineage_roots}
    final_gate = selected["final_release_gate_report"]["content"]
    release = selected["release_package"]["content"]
    accepted_versions = final_gate.get("accepted_asset_version_ids")
    if not isinstance(accepted_versions, dict):
        raise KernelError(
            "BOOK_CHAPTER_ACCEPTANCE_EVIDENCE_MISSING",
            "final release gate has no accepted asset lineage",
        )
    expected_versions = {
        "best_draft_candidate": str(release.get("source_asset_version_id") or ""),
        "re_review_report": str(accepted_versions.get("rereview") or ""),
        "canon_patch": str(accepted_versions.get("canon") or ""),
        "quality_score_report": str(accepted_versions.get("quality") or ""),
        "release_package": str(accepted_versions.get("export") or ""),
    }
    output_by_version = {
        str(item.get("asset_version_id") or ""): item for item in outputs
    }
    invalid_lineage = [
        asset_type
        for asset_type, asset_version_id in expected_versions.items()
        if not asset_version_id
        or asset_version_id not in output_by_version
        or str(output_by_version[asset_version_id].get("asset_type") or "")
        != asset_type
    ]
    if invalid_lineage:
        raise KernelError(
            "BOOK_CHAPTER_ACCEPTANCE_EVIDENCE_MISSING",
            "final release asset lineage is incomplete: " + ", ".join(invalid_lineage),
        )
    selected.update(
        {
            asset_type: output_by_version[asset_version_id]
            for asset_type, asset_version_id in expected_versions.items()
        }
    )
    return selected


def _validate_chapter_acceptance_evidence(
    *,
    request: dict[str, Any],
    evidence: dict[str, Any],
) -> tuple[dict[str, str], ...]:
    if (
        evidence.get("status") != "SUCCEEDED"
        or (evidence.get("saga") or {}).get("status") != "SUCCEEDED"
    ):
        raise KernelError(
            "BOOK_CHAPTER_ACCEPTANCE_NOT_READY",
            "Chapter root Operation and Saga must both succeed",
        )
    required_types = (
        "chapter_plan",
        "best_draft_candidate",
        "re_review_report",
        "canon_patch",
        "quality_score_report",
        "release_package",
        "final_release_gate_report",
    )
    selected = select_chapter_acceptance_outputs(evidence)
    final_gate = selected["final_release_gate_report"]["content"]
    release = selected["release_package"]["content"]
    quality = selected["quality_score_report"]["content"]
    rereview = selected["re_review_report"]["content"]
    canon = selected["canon_patch"]["content"]
    plan = selected["chapter_plan"]["content"]
    candidate = selected["best_draft_candidate"]["content"]
    if "creative_baseline" in candidate:
        from novel_forge.modules.chapter_authority.chapter_plan_views import (
            validate_creative_baseline,
        )

        baseline = validate_creative_baseline(candidate["creative_baseline"])
        if (
            quality.get("creative_baseline_digest") != baseline["baseline_digest"]
            or rereview.get("creative_baseline_digest") != baseline["baseline_digest"]
            or quality.get("evaluation_semantics_version") not in {"work-quality.v1", "work-quality.v2"}
            or baseline["source_plan"]
            != {
                "asset_version_id": plan.get("source_chapter_plan_asset_version_id"),
                "content_hash": plan.get("source_chapter_plan_content_hash"),
            }
        ):
            raise KernelError(
                "BOOK_CHAPTER_CREATIVE_BASELINE_DRIFT",
                "Acceptance must use the exact selected, reviewed and evaluated work baseline",
            )
    submitted = dict(request.get("command_payload") or {})
    execution_plan_version = str(
        submitted.get("execution_chapter_plan_asset_version_id")
        or request["chapter_plan_version"]
    )
    execution_plan_hash = str(
        submitted.get("execution_chapter_plan_content_hash")
        or request["chapter_plan_content_hash"]
    )
    model_effects = list(evidence.get("model_effects") or ())
    if model_effects or canon.get("grounding"):
        from novel_forge.modules.chapter_outcome.acceptance_contract import require_grounded_acceptance
        require_grounded_acceptance(project_id=str(request["project_id"]), selected=selected)
    effect_operation_ids = {
        str(item.get("operation_id") or "") for item in model_effects
    }
    succeeded_effect_operation_ids = {
        str(item.get("operation_id") or "")
        for item in model_effects
        if item.get("attempt_status") == "SUCCEEDED"
        and item.get("status") == "SUCCEEDED"
    }
    internal = (final_gate.get("final_gate_contract_version") == "creative-internal-finalize.v1"
        and final_gate.get("gate") == "INTERNAL_ADMITTED"
        and final_gate.get("release_status") == "INTERNAL_VALIDATION_FINALIZED"
        and final_gate.get("internal_admission") == quality.get("internal_admission")
        and (quality.get("internal_admission") or {}).get("status") == "INTERNAL_ADMITTED"
        and (quality.get("internal_admission") or {}).get("target_asset_version_id") == selected["best_draft_candidate"]["asset_version_id"])
    checks = {
        "final_release": internal and bool(final_gate.get("blob_receipt", {}).get("receipt_id")) or (
            final_gate.get("gate") == "PASSED"
            and final_gate.get("release_status") == "INTERNAL_RELEASE_FINALIZED"
            and bool(final_gate.get("blob_receipt", {}).get("receipt_id"))
        ),
        "quality": internal or quality.get("gate") in {"PASSED", "PASSED_WITH_UNCALIBRATED"},
        "review": (
            rereview.get("decision") == "PASSED"
            and int(rereview.get("blocking_issue_count", 0)) == 0
        ),
        "canon": canon.get("gate") == "PASSED" and not canon.get("conflicts"),
        "export": release.get("release_status") == "READY_FOR_BLOB_VERIFICATION",
        "plan_binding": (
            plan.get("source_chapter_plan_asset_version_id") == execution_plan_version
            and plan.get("source_chapter_plan_content_hash") == execution_plan_hash
            and int(plan.get("chapter") or 0) == int(request["chapter_number"])
        ),
        "assets_current": all(
            item.get("lifecycle") == "ACTIVE"
            and item.get("eligibility") == "ELIGIBLE"
            and item.get("governance") == "CLEAR"
            for item in selected.values()
        ),
        "effects_attempt_bound": all(
            bool(item.get("operation_id"))
            and bool(item.get("attempt_id"))
            and bool(item.get("attempt_status"))
            for item in model_effects
        ),
        "effects_terminal": (
            not model_effects
            or (
                effect_operation_ids == succeeded_effect_operation_ids
                and all(
                    item.get("status") == "SUCCEEDED"
                    for item in model_effects
                    if item.get("attempt_status") == "SUCCEEDED"
                )
            )
        ),
        "budget_settled": all(
            item.get("status") in {"SETTLED", "RELEASED"}
            for item in evidence.get("budgets") or ()
        ),
    }
    failed = sorted(key for key, passed in checks.items() if not passed)
    if failed:
        raise KernelError(
            "BOOK_CHAPTER_ACCEPTANCE_EVIDENCE_BLOCKED",
            "Chapter acceptance checks failed: " + ", ".join(failed),
        )
    return tuple(
        {
            "asset_version_id": str(selected[asset_type]["asset_version_id"]),
            "content_hash": str(selected[asset_type]["content_hash"]),
        }
        for asset_type in required_types
    )


def _validate_start(command: StartBookProductionCommand) -> None:
    required = (
        command.project_id,
        command.workspace_id,
        command.book_id,
        command.actor_id,
        command.trace_id,
        command.correlation_id,
        command.stable_idempotency_key,
        command.book_design_version,
        command.book_plan_version,
        command.production_profile_version,
    )
    versions = command.longform_context_versions
    if (
        any(not item for item in required)
        or command.target_chapter_count <= 0
        or command.light_recap_cadence <= 0
        or command.formal_recap_cadence <= 0
        or set(versions) != LONGFORM_CONTEXT_VERSION_KEYS
        or any(
            not value or value.endswith(":current")
            for key, value in versions.items()
            if key != "arc_plan_versions"
        )
        or not isinstance(versions.get("arc_plan_versions"), (list, tuple))
        or not versions.get("arc_plan_versions")
        or any(
            not isinstance(value, str) or not value or value.endswith(":current")
            for value in versions.get("arc_plan_versions", ())
        )
        or len(set(versions.get("arc_plan_versions", ())))
        != len(versions.get("arc_plan_versions", ()))
        or command.input_mode
        not in {"LEGACY_FIXTURE_INPUT_MODE", "RESOLVED_AUTHORITY_INPUT"}
        or (
            command.input_mode == "LEGACY_FIXTURE_INPUT_MODE"
            and command.input_snapshot_id
        )
    ):
        raise ValueError(
            "Book Authority start command requires complete immutable context versions"
        )


def _longform_context_asset_version_ids(versions: dict[str, Any]) -> tuple[str, ...]:
    scalar_ids = (
        str(versions[key])
        for key in sorted(LONGFORM_CONTEXT_VERSION_KEYS - {"arc_plan_versions"})
    )
    return tuple(
        dict.fromkeys(
            (*scalar_ids, *(str(item) for item in versions["arc_plan_versions"]))
        )
    )


__all__ = [
    "BOOK_COORDINATE_DEFINITION",
    "LONGFORM_CONTEXT_VERSION_KEYS",
    "BookProductionAdmission",
    "BookProductionState",
    "BookProductionStateClass",
    "BookProductionStateSemantics",
    "ChapterAuthorityCommandAdapter",
    "ChapterAuthorityCommandPort",
    "PostgresBookAuthority",
    "StartBookProductionCommand",
    "SubmitBookChapterCommand",
    "stable_chapter_submission_key",
    "book_coordinate_definition",
    "book_production_state_semantics",
    "actionable_book_production_states",
    "select_chapter_acceptance_outputs",
]
