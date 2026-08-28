"""Book opening coordinator over existing design, planning, and input Authorities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import (
    AdmissionContext,
    TransactionCheckpoint,
    execute_transaction_command,
)
from novel_forge.modules.runtime_job import (
    AUTHORITY_CONVERGENCE_REQUIRED,
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.modules.story_planning_runtime import (
    GENERATOR_INPUT_ROLES,
    NarrativeSearchRequest,
    PostgresNarrativeSearchApplication,
    StoryPlanningGenerationCommand,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)

from .input_resolver import (
    BookProductionInputResolver,
    BookProductionInputSnapshot,
    ResolveBookProductionInputCommand,
)
from .recovery import (
    BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
    PostgresBookOpeningRecoveryApplication,
    _stable_id,
)


_RESOLVER_ROLE_BY_PLANNING_ROLE = {
    "production_profile": "production_profile_version",
    "reader_segment": "reader_segment_version",
    "reader_contract": "reader_contract_version",
    "platform_profile": "platform_profile_version",
    "character_state": "character_state_version",
    "foreshadowing_state": "foreshadowing_state_version",
    "quality_trend": "quality_trend_version",
    "reward_ledger": "reward_ledger_version",
    "promise_ledger": "promise_ledger_version",
}
_OPENING_INPUT_ROLES = frozenset(
    role
    for generator in (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
    )
    for role in GENERATOR_INPUT_ROLES[generator]
    if role not in {"book_plan", "volume_plan"}
)
BOOK_OPENING_DEFINITION_VERSION = "1.0.0"
BOOK_OPENING_HANDLER = "novel_forge.book_authority.opening"
BOOK_OPENING_OPERATIONS = frozenset(
    {
        "book.opening.admit",
        "book.opening.complete",
        "book.opening.resume",
        "book.opening.abort",
    }
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OpenBookProductionRequest:
    project_id: str
    workspace_id: str
    book_id: str
    actor_id: str
    expected_book_version: int
    production_profile: str
    planning_input_versions: Mapping[str, str]
    arc_logical_keys: tuple[str, ...]
    idempotency_key: str
    trace_id: str
    correlation_id: str
    initial_story_state_version: str = ""
    initial_canon_snapshot_version: str = ""

    def __post_init__(self) -> None:
        identities = (
            self.project_id,
            self.workspace_id,
            self.book_id,
            self.actor_id,
            self.production_profile,
            self.idempotency_key,
            self.trace_id,
            self.correlation_id,
        )
        if (
            any(not item.strip() for item in identities)
            or self.expected_book_version <= 0
        ):
            raise ValueError("Book opening request is incomplete")
        if not self.arc_logical_keys or len(set(self.arc_logical_keys)) != len(
            self.arc_logical_keys
        ):
            raise ValueError("Book opening requires a non-empty unique Arc portfolio")
        if (
            not self.initial_story_state_version
            or not self.initial_canon_snapshot_version
        ):
            raise ValueError(
                "Book opening requires the initial accepted Story State and Canon boundary"
            )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["planning_input_versions"] = dict(self.planning_input_versions)
        value["arc_logical_keys"] = list(self.arc_logical_keys)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OpenBookProductionRequest":
        expected = {
            "project_id",
            "workspace_id",
            "book_id",
            "actor_id",
            "expected_book_version",
            "production_profile",
            "planning_input_versions",
            "arc_logical_keys",
            "idempotency_key",
            "trace_id",
            "correlation_id",
            "initial_story_state_version",
            "initial_canon_snapshot_version",
        }
        if (
            set(value) != expected
            or not isinstance(value.get("planning_input_versions"), Mapping)
            or not isinstance(value.get("arc_logical_keys"), list)
        ):
            raise KernelError(
                "BOOK_OPENING_REQUEST_INVALID",
                "frozen Book opening request fields must match exactly",
            )
        return cls(
            project_id=str(value["project_id"]),
            workspace_id=str(value["workspace_id"]),
            book_id=str(value["book_id"]),
            actor_id=str(value["actor_id"]),
            expected_book_version=int(value["expected_book_version"]),
            production_profile=str(value["production_profile"]),
            planning_input_versions={
                str(role): str(version)
                for role, version in value["planning_input_versions"].items()
            },
            arc_logical_keys=tuple(str(item) for item in value["arc_logical_keys"]),
            idempotency_key=str(value["idempotency_key"]),
            trace_id=str(value["trace_id"]),
            correlation_id=str(value["correlation_id"]),
            initial_story_state_version=str(value["initial_story_state_version"]),
            initial_canon_snapshot_version=str(value["initial_canon_snapshot_version"]),
        )


@dataclass(frozen=True, slots=True)
class BookOpeningAdmission:
    opening_run_id: str
    root_operation_id: str
    runtime_job_id: str
    lifecycle: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class BookOpeningResult:
    book_design_version: str
    book_plan_version: str
    volume_plan_version: str
    arc_plan_versions: tuple[str, ...]
    input_snapshot: BookProductionInputSnapshot
    search_ids: tuple[str, ...]


class PostgresBookOpeningApplication:
    """Coordinates existing Authorities; it owns no new truth or execution state."""

    def __init__(
        self,
        database_url: str,
        *,
        narrative_search: PostgresNarrativeSearchApplication,
        input_resolver: BookProductionInputResolver,
        application_build_id: str,
        commit_sha: str,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("Book opening requires PostgreSQL/build identity")
        self.database_url = database_url
        self.narrative_search = narrative_search
        self.input_resolver = input_resolver
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.runtime_jobs = RuntimeJobAuthority(database_url)
        semantic_replacement = getattr(
            getattr(narrative_search, "planning", None),
            "semantic_evaluation",
            None,
        )
        self.recovery = PostgresBookOpeningRecoveryApplication(
            database_url,
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            semantic_replacement=semantic_replacement,
        )

    def admit(
        self, request: OpenBookProductionRequest, *, principal: Principal
    ) -> BookOpeningAdmission:
        """Freeze a durable opening run without owning Provider execution."""

        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        if principal.principal_id != request.actor_id:
            raise KernelError(
                "ACTOR_IDENTITY_INVALID",
                "Book opening actor differs from authenticated Principal",
            )
        self._require_qualified_foundation(request)
        self._register_definitions()
        identity = "\x00".join(
            (request.project_id, request.book_id, request.idempotency_key)
        ).encode("utf-8")
        opening_run_id = "book-opening:" + hashlib.sha256(identity).hexdigest()
        frozen_request = request.to_dict()
        executed = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "book.opening.admit",
                "definition_version": BOOK_OPENING_DEFINITION_VERSION,
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "book_id": request.book_id,
                "actor_id": request.actor_id,
                "idempotency_scope": "book:opening",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": "",
                "input": {
                    "project_id": request.project_id,
                    "book_id": request.book_id,
                    "opening_run_id": opening_run_id,
                    "frozen_request": frozen_request,
                    "frozen_request_digest": _canonical_hash(frozen_request),
                },
                "input_assets": self._opening_input_assets(request),
            },
            context=self._context(request.actor_id),
            handler=self._execute_transaction,
        )
        run = self.require(opening_run_id)
        job = self._latest_job(opening_run_id)
        return BookOpeningAdmission(
            opening_run_id=opening_run_id,
            root_operation_id=str(executed["operation_id"]),
            runtime_job_id=str(job["runtime_job_id"]),
            lifecycle=str(run["lifecycle"]),
            replayed=bool(executed["replayed"]),
        )

    def require(self, opening_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT opening_run_id,project_id,workspace_id,book_id,
                       root_operation_id,lifecycle,frozen_request_digest,
                       version,result,failure,recovery_instruction,
                       execution_contract_version,current_execution_id,
                       current_execution_generation,current_checkpoint_id,
                       current_checkpoint_sequence,current_checkpoint_hash,
                       recovery_state
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book opening run is missing")
        return dict(
            zip(
                (
                    "opening_run_id",
                    "project_id",
                    "workspace_id",
                    "book_id",
                    "root_operation_id",
                    "lifecycle",
                    "frozen_request_digest",
                    "version",
                    "result",
                    "failure",
                    "recovery_instruction",
                    "execution_contract_version",
                    "current_execution_id",
                    "current_execution_generation",
                    "current_checkpoint_id",
                    "current_checkpoint_sequence",
                    "current_checkpoint_hash",
                    "recovery_state",
                ),
                row,
                strict=True,
            )
        )

    def claim_next_execution(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        project_id: str = "",
    ) -> RuntimeJobClaim | None:
        """Atomically claim and bind the first no-takeover Opening execution."""

        if not worker_id or lease_seconds <= 0:
            raise ValueError("Opening claim requires worker and positive lease")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT opening.opening_run_id
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                WHERE opening.execution_contract_version=%s
                  AND opening.lifecycle='ADMITTED'
                  AND execution.lifecycle='SCHEDULED'
                  AND execution.current_attempt_id IS NULL
                  AND job.status='READY' AND job.attempt_count=0
                  AND job.current_attempt_id IS NULL
                  AND job.max_attempts=1
                  AND job.lease_loss_policy=%s
                  AND (%s='' OR opening.project_id=%s)
                ORDER BY job.priority,job.available_at,job.created_at,
                         job.runtime_job_id
                LIMIT 1
                """,
                [
                    BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
                    AUTHORITY_CONVERGENCE_REQUIRED,
                    project_id,
                    project_id,
                ],
            )
            candidate = uow.cursor.fetchone()
            if candidate is None:
                return None
            opening_run_id = str(candidate[0])
            uow.cursor.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))",
                [f"book-opening:{opening_run_id}"],
            )
            if not bool(uow.cursor.fetchone()[0]):
                return None
            uow.cursor.execute(
                """
                SELECT opening.project_id,opening.frozen_request_digest,
                       opening.current_execution_generation,
                       execution.opening_execution_id,execution.version,
                       execution.runtime_job_id,execution.frozen_request_digest,
                       execution.policy_snapshot_hash,
                       execution.authority_contract_hash,job.input_hash,
                       execution.input_snapshot_hash
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                WHERE opening.opening_run_id=%s
                  AND opening.execution_contract_version=%s
                  AND opening.lifecycle='ADMITTED'
                  AND execution.lifecycle='SCHEDULED'
                  AND execution.current_attempt_id IS NULL
                  AND job.status='READY' AND job.attempt_count=0
                  AND job.current_attempt_id IS NULL
                  AND job.max_attempts=1
                  AND job.lease_loss_policy=%s
                FOR UPDATE OF opening,execution,job
                """,
                [
                    opening_run_id,
                    BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
                    AUTHORITY_CONVERGENCE_REQUIRED,
                ],
            )
            binding = uow.cursor.fetchone()
            if binding is None:
                return None
            if (
                str(binding[1]) != str(binding[6])
                or str(binding[7]) != self.recovery._execution_policy_digest()
                or str(binding[8]) != self.recovery._authority_digest()
                or str(binding[9]) != str(binding[10])
            ):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_CONTRACT_STALE",
                    "Opening execution cannot be claimed by a drifted runtime contract",
                )
            claim = self.runtime_jobs.claim_ready_in_uow(
                uow,
                runtime_job_id=str(binding[5]),
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET current_attempt_id=%s,current_lease_id=%s,
                    current_worker_id=%s,current_fencing_token=%s,
                    lifecycle='BOUND',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND version=%s
                  AND lifecycle='SCHEDULED' AND current_attempt_id IS NULL
                """,
                [
                    claim.attempt_id,
                    claim.lease_id,
                    claim.worker_id,
                    claim.fencing_token,
                    binding[3],
                    binding[4],
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_CONFLICT",
                    "Opening execution changed during coordinated claim",
                )
            uow.commit()
        return claim

    def execute_run(
        self,
        opening_run_id: str,
        *,
        expected_version: int,
        runtime_claim: RuntimeJobClaim,
        principal: Principal,
        execution_probe: Callable[[], object] | None = None,
    ) -> dict[str, Any]:
        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        if str(run["lifecycle"]) == "COMPLETE":
            return dict(run["result"])
        if (
            str(run["lifecycle"]) not in {"ADMITTED", "RUNNING"}
            or int(run["version"]) != expected_version
        ):
            raise KernelError(
                "BOOK_OPENING_JOB_STALE",
                "Book opening RuntimeJob differs from its frozen run version",
            )
        request = self._frozen_request(opening_run_id)
        self._bind_running_execution(
            opening_run_id,
            expected_version=expected_version,
            runtime_claim=runtime_claim,
        )
        self._probe(execution_probe)
        opened = self._open_frozen(
            request,
            principal=principal,
            opening_run_id=opening_run_id,
            runtime_claim=runtime_claim,
            execution_probe=execution_probe,
        )
        result = {
            "book_design_version": opened.book_design_version,
            "book_plan_version": opened.book_plan_version,
            "volume_plan_version": opened.volume_plan_version,
            "arc_plan_versions": list(opened.arc_plan_versions),
            "input_snapshot_id": opened.input_snapshot.snapshot_id,
            "search_ids": list(opened.search_ids),
        }
        self._probe(execution_probe)
        self._checkpoint_opening_result(opening_run_id, opened, runtime_claim)
        self._probe(execution_probe)
        self._control(
            run=run,
            principal=principal,
            definition_name="book.opening.complete",
            idempotency_key=f"{opening_run_id}:complete:{_canonical_hash(result)}",
            payload={
                "expected_version": expected_version,
                "result": result,
                "runtime_claim": self._runtime_claim_payload(runtime_claim),
            },
        )
        return result

    def record_failure(
        self,
        opening_run_id: str,
        *,
        expected_version: int,
        runtime_claim: RuntimeJobClaim,
        error: dict[str, Any],
    ) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                [f"book-opening:{opening_run_id}"],
            )
            uow.cursor.execute(
                """
                SELECT current_execution_id,current_execution_generation,
                       version,lifecycle,failure
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                FOR UPDATE
                """,
                [opening_run_id],
            )
            binding = uow.cursor.fetchone()
            active = bool(
                binding is not None
                and int(binding[2]) == expected_version
                and str(binding[3]) in {"ADMITTED", "RUNNING"}
            )
            replay = bool(
                binding is not None
                and int(binding[2]) == expected_version + 1
                and str(binding[3]) == "FAILED"
            )
            if not active and not replay:
                raise KernelError(
                    "BOOK_OPENING_FAILURE_STALE",
                    "Book Opening changed before governed failure convergence",
                )
            if replay and _canonical_hash(dict(binding[4] or {})) != _canonical_hash(
                error
            ):
                raise KernelError(
                    "BOOK_OPENING_FAILURE_IDEMPOTENCY_CONFLICT",
                    "Book Opening failure replay carries a different error",
                )
            uow.cursor.execute(
                """
                SELECT version,lifecycle,current_attempt_id,current_lease_id,
                       current_worker_id,current_fencing_token,runtime_job_id,
                       terminal_reason
                FROM authority_book_opening_execution
                WHERE opening_execution_id=%s AND opening_run_id=%s
                  AND generation=%s
                FOR UPDATE
                """,
                [str(binding[0]), opening_run_id, int(binding[1])],
            )
            execution = uow.cursor.fetchone()
            if execution is None or str(execution[6]) != runtime_claim.runtime_job_id:
                raise KernelError(
                    "BOOK_OPENING_FAILURE_STALE",
                    "Opening execution identity changed before failure convergence",
                )
            stored_claim = (
                str(execution[2] or ""),
                str(execution[3] or ""),
                str(execution[4] or ""),
                int(execution[5] or 0),
            )
            requested_claim = (
                runtime_claim.attempt_id,
                runtime_claim.lease_id,
                runtime_claim.worker_id,
                runtime_claim.fencing_token,
            )
            if stored_claim != ("", "", "", 0) and stored_claim != requested_claim:
                raise KernelError(
                    "BOOK_OPENING_FAILURE_STALE",
                    "Opening execution carries another Runtime claim",
                )
            if replay and (
                str(execution[1]) != "FAILED"
                or _canonical_hash(dict(execution[7] or {})) != _canonical_hash(error)
            ):
                raise KernelError(
                    "BOOK_OPENING_FAILURE_IDEMPOTENCY_CONFLICT",
                    "Opening execution terminal reason differs from failure replay",
                )
            self.runtime_jobs.terminalize_authority_failure_in_uow(
                uow, runtime_claim, error
            )
            if replay:
                uow.commit()
                return
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET current_attempt_id=COALESCE(current_attempt_id,%s),
                    current_lease_id=COALESCE(current_lease_id,%s),
                    current_worker_id=COALESCE(current_worker_id,%s),
                    current_fencing_token=COALESCE(current_fencing_token,%s),
                    lifecycle='FAILED',terminal_reason=%s,version=version+1,
                    terminal_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND opening_run_id=%s
                  AND generation=%s AND version=%s
                  AND lifecycle IN ('SCHEDULED','BOUND','RUNNING')
                  AND runtime_job_id=%s
                  AND (current_attempt_id IS NULL OR current_attempt_id=%s)
                  AND (current_lease_id IS NULL OR current_lease_id=%s)
                  AND (current_worker_id IS NULL OR current_worker_id=%s)
                  AND (current_fencing_token IS NULL OR current_fencing_token=%s)
                """,
                [
                    runtime_claim.attempt_id,
                    runtime_claim.lease_id,
                    runtime_claim.worker_id,
                    runtime_claim.fencing_token,
                    Jsonb(error),
                    str(binding[0]),
                    opening_run_id,
                    int(binding[1]),
                    int(execution[0]),
                    runtime_claim.runtime_job_id,
                    runtime_claim.attempt_id,
                    runtime_claim.lease_id,
                    runtime_claim.worker_id,
                    runtime_claim.fencing_token,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_FAILURE_STALE",
                    "Opening execution changed before governed failure convergence",
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='FAILED',failure=%s,recovery_instruction=%s,
                    recovery_state='RECOVERY_REQUIRED',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','RUNNING')
                """,
                [
                    Jsonb(error),
                    Jsonb(
                        {
                            "action": "ASSESS_BOOK_OPENING_RECOVERY",
                            "opening_run_id": opening_run_id,
                        }
                    ),
                    opening_run_id,
                    expected_version,
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_FAILURE_STALE",
                    "Book Opening changed before governed failure convergence",
                )
            uow.commit()

    def resume(
        self, opening_run_id: str, *, expected_version: int, principal: Principal
    ) -> dict[str, Any]:
        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        del expected_version
        raise KernelError(
            "BOOK_OPENING_RECOVERY_ASSESSMENT_REQUIRED",
            "legacy resume is blocked; assess and recover through the canonical Recovery Application",
        )

    def abort(
        self, opening_run_id: str, *, expected_version: int, principal: Principal
    ) -> dict[str, Any]:
        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        self._control(
            run=run,
            principal=principal,
            definition_name="book.opening.abort",
            idempotency_key=f"{opening_run_id}:abort:{expected_version}",
            payload={"expected_version": expected_version},
        )
        return self.require(opening_run_id)

    def _open_frozen(
        self,
        request: OpenBookProductionRequest,
        *,
        principal: Principal,
        opening_run_id: str = "",
        runtime_claim: RuntimeJobClaim | None = None,
        execution_probe: Callable[[], object] | None = None,
    ) -> BookOpeningResult:
        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        design_version = self._require_qualified_foundation(request)
        generic = dict(request.planning_input_versions)
        if (
            set(generic) != _OPENING_INPUT_ROLES
            or generic.get("book_design") != design_version
        ):
            raise KernelError(
                "BOOK_OPENING_INPUTS_INVALID",
                "opening inputs must exactly match the Book planning Authority roles and active Foundation",
            )
        accepted_state = request.initial_story_state_version
        search_ids: list[str] = []
        progress: Mapping[str, Mapping[str, Any]] = {}
        if opening_run_id:
            if runtime_claim is None:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_REQUIRED",
                    "Opening semantic progress requires its exact Runtime claim",
                )
            progress = self.recovery.require_execution_progress(
                opening_run_id,
                runtime_claim=runtime_claim,
            )
        self._probe(execution_probe)
        book_search = self._search(
            request=request,
            principal=principal,
            generator="book_plan.generate",
            logical_key="book:main",
            input_versions={
                role: generic[role]
                for role in GENERATOR_INPUT_ROLES["book_plan.generate"]
            },
            parent_version_id="",
            accepted_state=accepted_state,
            horizon={"level": "BOOK", "stability": "HIGH", "reach": "DISTANT"},
            transformation={
                "foundation_version": design_version,
                "goal": "establish a sustainable Book narrative architecture",
            },
            progress=progress,
            execution_probe=execution_probe,
        )
        self._probe(execution_probe)
        search_ids.append(book_search.search_id)
        self._checkpoint_search(
            opening_run_id, book_search.search_id, runtime_claim=runtime_claim
        )
        book_plan = book_search.selected_generation.candidate_asset_version_id
        volume_inputs = self._stage_inputs(
            generic, "volume_plan.generate", book_plan=book_plan
        )
        volume_search = self._search(
            request=request,
            principal=principal,
            generator="volume_plan.generate",
            logical_key="volume:1",
            input_versions=volume_inputs,
            parent_version_id=book_plan,
            accepted_state=accepted_state,
            horizon={"level": "VOLUME", "stability": "MEDIUM_HIGH", "ordinal": 1},
            transformation={
                "goal": "create the first irreversible stage transformation"
            },
            progress=progress,
            execution_probe=execution_probe,
        )
        self._probe(execution_probe)
        search_ids.append(volume_search.search_id)
        self._checkpoint_search(
            opening_run_id, volume_search.search_id, runtime_claim=runtime_claim
        )
        volume_plan = volume_search.selected_generation.candidate_asset_version_id
        arc_versions: list[str] = []
        for arc_key in request.arc_logical_keys:
            self._probe(execution_probe)
            arc_inputs = self._stage_inputs(
                generic,
                "arc_plan.generate",
                book_plan=book_plan,
                volume_plan=volume_plan,
            )
            arc_search = self._search(
                request=request,
                principal=principal,
                generator="arc_plan.generate",
                logical_key=arc_key,
                input_versions=arc_inputs,
                parent_version_id="",
                accepted_state=accepted_state,
                horizon={"level": "ARC", "stability": "MEDIUM", "volume": 1},
                transformation={
                    "goal": "produce a causal transformation with closure criteria",
                    "arc_key": arc_key,
                },
                progress=progress,
                execution_probe=execution_probe,
            )
            self._probe(execution_probe)
            search_ids.append(arc_search.search_id)
            self._checkpoint_search(
                opening_run_id, arc_search.search_id, runtime_claim=runtime_claim
            )
            arc_versions.append(
                arc_search.selected_generation.candidate_asset_version_id
            )
        overrides = tuple(
            (
                _RESOLVER_ROLE_BY_PLANNING_ROLE[role],
                version_id,
            )
            for role, version_id in generic.items()
            if role in _RESOLVER_ROLE_BY_PLANNING_ROLE
        )
        overrides += (
            ("initial_story_state_version", request.initial_story_state_version),
            ("initial_canon_snapshot_version", request.initial_canon_snapshot_version),
        )
        self._probe(execution_probe)
        snapshot = self.input_resolver.resolve(
            ResolveBookProductionInputCommand(
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                book_id=request.book_id,
                production_profile=request.production_profile,
                expected_book_version=request.expected_book_version,
                actor_id=request.actor_id,
                idempotency_key=f"{request.idempotency_key}:production-input",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                role_asset_version_overrides=overrides,
            ),
            principal=principal,
        )
        self._probe(execution_probe)
        return BookOpeningResult(
            book_design_version=design_version,
            book_plan_version=book_plan,
            volume_plan_version=volume_plan,
            arc_plan_versions=tuple(arc_versions),
            input_snapshot=snapshot,
            search_ids=tuple(search_ids),
        )

    def _control(
        self,
        *,
        run: dict[str, Any],
        principal: Principal,
        definition_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._register_definitions()
        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": BOOK_OPENING_DEFINITION_VERSION,
                "project_id": str(run["project_id"]),
                "workspace_id": str(run["workspace_id"]),
                "book_id": str(run["book_id"]),
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:opening",
                "idempotency_key": idempotency_key,
                "trace_id": f"trace:{run['opening_run_id']}",
                "span_id": str(uuid4()),
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "causation_operation_id": str(run["root_operation_id"]),
                "input": {
                    "project_id": str(run["project_id"]),
                    "book_id": str(run["book_id"]),
                    "opening_run_id": str(run["opening_run_id"]),
                    **payload,
                },
                "input_assets": self._opening_input_assets(
                    self._frozen_request(str(run["opening_run_id"]))
                ),
            },
            context=self._context(principal.principal_id),
            handler=self._execute_transaction,
        )

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT definition_name,project_id,workspace_id,command_payload,actor_id
            FROM authority_operation WHERE operation_id=%s
            """,
            [operation_id],
        )
        operation = uow.cursor.fetchone()
        if operation is None:
            raise KernelError(
                "OPERATION_NOT_FOUND", "Book opening Operation is missing"
            )
        definition_name = str(operation[0])
        payload = dict(operation[3])
        opening_run_id = str(payload["opening_run_id"])
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"book-opening:{opening_run_id}"],
        )
        checkpoint("after_domain_validation")
        if definition_name == "book.opening.admit":
            frozen_request = dict(payload["frozen_request"])
            digest = _canonical_hash(frozen_request)
            if digest != str(payload["frozen_request_digest"]):
                raise KernelError(
                    "BOOK_OPENING_FROZEN_REQUEST_DRIFT",
                    "Book opening request differs from its digest",
                )
            OpenBookProductionRequest.from_mapping(frozen_request)
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_run(
                    opening_run_id,project_id,workspace_id,book_id,
                    root_operation_id,stable_idempotency_key,lifecycle,
                    frozen_request,frozen_request_digest,
                    execution_contract_version,recovery_state
                ) VALUES (%s,%s,%s,%s,%s,%s,'ADMITTED',%s,%s,%s,'READY')
                ON CONFLICT (opening_run_id) DO NOTHING
                """,
                [
                    opening_run_id,
                    str(operation[1]),
                    str(operation[2]),
                    str(payload["book_id"]),
                    operation_id,
                    str(frozen_request["idempotency_key"]),
                    Jsonb(frozen_request),
                    digest,
                    BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
                ],
            )
            created = uow.cursor.rowcount == 1
            if not created:
                uow.cursor.execute(
                    """
                    SELECT root_operation_id,frozen_request_digest
                    FROM authority_book_opening_run WHERE opening_run_id=%s
                    """,
                    [opening_run_id],
                )
                existing = uow.cursor.fetchone()
                if existing is None or tuple(str(item) for item in existing) != (
                    operation_id,
                    digest,
                ):
                    raise KernelError(
                        "BOOK_OPENING_IDEMPOTENCY_CONFLICT",
                        "Book opening identity binds different frozen evidence",
                    )
            else:
                execution_id = _stable_id("book-opening-execution", opening_run_id, 1)
                runtime_spec = RuntimeJobSpec(
                    job_kind="BOOK_OPENING_EXECUTE",
                    runtime_group="book_opening",
                    subject_kind="BOOK_OPENING_RUN",
                    subject_id=opening_run_id,
                    project_id=str(operation[1]),
                    dedupe_key=f"{opening_run_id}:execution-generation:1",
                    input_snapshot={
                        "opening_run_id": opening_run_id,
                        "observed_version": 0,
                        "frozen_request_digest": digest,
                        "opening_execution_id": execution_id,
                        "execution_generation": 1,
                        "recovery_intent_id": "",
                        "replacement_evaluation_operation_id": "",
                    },
                    max_attempts=1,
                    lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
                )
                runtime_job = self.runtime_jobs.schedule_in_uow(uow, runtime_spec)
                uow.cursor.execute(
                    """
                    INSERT INTO authority_book_opening_execution(
                        opening_execution_id,opening_run_id,generation,
                        runtime_job_id,lifecycle,frozen_request_digest,
                        input_snapshot_hash,policy_snapshot_hash,
                        authority_contract_hash
                    ) VALUES (%s,%s,1,%s,'SCHEDULED',%s,%s,%s,%s)
                    """,
                    [
                        execution_id,
                        opening_run_id,
                        runtime_job["runtime_job_id"],
                        digest,
                        runtime_spec.input_hash,
                        self.recovery._execution_policy_digest(),
                        self.recovery._authority_digest(),
                    ],
                )
                uow.cursor.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_execution_id=%s,current_execution_generation=1,
                        updated_at=transaction_timestamp()
                    WHERE opening_run_id=%s AND current_execution_id IS NULL
                    """,
                    [execution_id, opening_run_id],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "BOOK_OPENING_EXECUTION_ADMISSION_CONFLICT",
                        "Opening execution identity changed during admission",
                    )
        elif definition_name == "book.opening.complete":
            result = payload.get("result")
            if not isinstance(result, dict):
                raise KernelError(
                    "BOOK_OPENING_RESULT_INVALID", "Book opening result is not typed"
                )
            uow.cursor.execute(
                """
                SELECT opening.current_execution_id,
                       opening.current_execution_generation,
                       execution.lifecycle,execution.version,
                       execution.runtime_job_id,execution.current_attempt_id,
                       execution.current_lease_id,execution.current_worker_id,
                       execution.current_fencing_token
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                WHERE opening.opening_run_id=%s AND opening.version=%s
                  AND opening.lifecycle='RUNNING'
                FOR UPDATE OF opening,execution
                """,
                [opening_run_id, int(payload["expected_version"])],
            )
            execution = uow.cursor.fetchone()
            if execution is None:
                raise KernelError(
                    "BOOK_OPENING_COMMIT_CONFLICT",
                    "Book Opening changed before completion",
                )
            runtime_claim = self._runtime_claim_from_payload(
                payload.get("runtime_claim")
            )
            if (
                runtime_claim.subject_id != opening_run_id
                or str(execution[4]) != runtime_claim.runtime_job_id
                or str(execution[5]) != runtime_claim.attempt_id
                or str(execution[6]) != runtime_claim.lease_id
                or str(execution[7]) != runtime_claim.worker_id
                or int(execution[8]) != runtime_claim.fencing_token
            ):
                raise KernelError(
                    "BOOK_OPENING_COMPLETION_BINDING_INVALID",
                    "completion does not carry the exact Opening execution claim",
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='SUCCEEDED',terminal_reason='{}'::jsonb,
                    version=version+1,terminal_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND opening_run_id=%s
                  AND generation=%s AND version=%s AND lifecycle='RUNNING'
                """,
                [execution[0], opening_run_id, execution[1], execution[3]],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_COMMIT_CONFLICT",
                    "Opening execution changed before completion",
                )
            self.runtime_jobs.complete_authority_owned_in_uow(
                uow, runtime_claim, result
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='COMPLETE',result=%s,failure='{}'::jsonb,
                    recovery_instruction='{}'::jsonb,recovery_state='READY',
                    version=version+1,
                    updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s AND lifecycle='RUNNING'
                """,
                [
                    Jsonb(result),
                    opening_run_id,
                    int(payload["expected_version"]),
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_COMMIT_CONFLICT",
                    "Book opening completion changed concurrently",
                )
        elif definition_name == "book.opening.resume":
            raise KernelError(
                "BOOK_OPENING_RECOVERY_ASSESSMENT_REQUIRED",
                "legacy resume cannot authorize a new Opening execution generation",
            )
        else:
            uow.cursor.execute(
                """
                SELECT opening.lifecycle,opening.current_execution_id,
                       opening.current_execution_generation,
                       execution.lifecycle,execution.version,
                       execution.runtime_job_id,execution.current_attempt_id,
                       execution.current_lease_id,execution.current_worker_id,
                       execution.current_fencing_token
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                WHERE opening.opening_run_id=%s AND opening.version=%s
                  AND opening.lifecycle IN ('ADMITTED','FAILED')
                FOR UPDATE OF opening,execution
                """,
                [opening_run_id, int(payload["expected_version"])],
            )
            binding = uow.cursor.fetchone()
            if binding is None:
                raise KernelError(
                    "BOOK_OPENING_ABORT_CONFLICT",
                    "Book opening cannot abort at the expected version",
                )
            if str(binding[0]) == "ADMITTED":
                reason = {
                    "code": "BOOK_OPENING_AUTHORITY_ABORTED",
                    "opening_run_id": opening_run_id,
                    "operation_id": operation_id,
                }
                runtime = self.runtime_jobs.terminalize_authority_abort_in_uow(
                    uow,
                    runtime_job_id=str(binding[5]),
                    reason=reason,
                )
                runtime_identity = (
                    str(runtime["attempt_id"]),
                    str(runtime["lease_id"]),
                    str(runtime["worker_id"]),
                    int(runtime["fencing_token"]),
                )
                stored_identity = (
                    str(binding[6] or ""),
                    str(binding[7] or ""),
                    str(binding[8] or ""),
                    int(binding[9] or 0),
                )
                if stored_identity != ("", "", "", 0) and (
                    stored_identity != runtime_identity
                ):
                    raise KernelError(
                        "BOOK_OPENING_ABORT_BINDING_INVALID",
                        "Opening execution and Runtime abort identity differ",
                    )
                replacement_operation_id = str(
                    runtime["replacement_evaluation_operation_id"]
                )
                if replacement_operation_id:
                    if self.recovery.semantic_replacement is None:
                        raise KernelError(
                            "BOOK_OPENING_REPLACEMENT_RUNTIME_REQUIRED",
                            "Opening abort requires the semantic replacement Application",
                        )
                    self.recovery.semantic_replacement.cancel_unstarted_replacement_in_uow(
                        uow,
                        operation_id=replacement_operation_id,
                        actor_id=str(operation[4]),
                        trace_id=f"trace:{opening_run_id}:abort",
                        correlation_id=str(operation_id),
                        reason="Book Opening was aborted before replacement execution",
                    )
                uow.cursor.execute(
                    """
                    UPDATE authority_book_opening_execution
                    SET current_attempt_id=COALESCE(
                            current_attempt_id,NULLIF(%s,'')
                        ),
                        current_lease_id=COALESCE(
                            current_lease_id,NULLIF(%s,'')
                        ),
                        current_worker_id=COALESCE(
                            current_worker_id,NULLIF(%s,'')
                        ),
                        current_fencing_token=COALESCE(
                            current_fencing_token,NULLIF(%s,0)
                        ),
                        lifecycle='ABORTED',terminal_reason=%s,
                        version=version+1,terminal_at=transaction_timestamp(),
                        updated_at=transaction_timestamp()
                    WHERE opening_execution_id=%s AND opening_run_id=%s
                      AND generation=%s AND version=%s
                      AND lifecycle IN ('SCHEDULED','BOUND','RUNNING')
                    """,
                    [
                        *runtime_identity,
                        Jsonb(reason),
                        binding[1],
                        opening_run_id,
                        binding[2],
                        binding[4],
                    ],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "BOOK_OPENING_ABORT_CONFLICT",
                        "Opening execution changed during Authority abort",
                    )
            elif str(binding[3]) not in {"FAILED", "LOST", "ABORTED"}:
                raise KernelError(
                    "BOOK_OPENING_ABORT_BINDING_INVALID",
                    "failed Opening does not bind immutable terminal execution history",
                )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='ABORTED',version=version+1,updated_at=NOW()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','FAILED')
                """,
                [opening_run_id, int(payload["expected_version"])],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_ABORT_CONFLICT",
                    "Book opening cannot abort at the expected version",
                )
        checkpoint("after_business_projection_update")
        run = self._require_in_uow(uow, opening_run_id)
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_opening",
                "aggregate_id": opening_run_id,
                "operation_id": operation_id,
                "project_id": str(operation[1]),
                "event_type": "book.opening.transitioned",
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "payload": {
                    "operation_id": operation_id,
                    "opening_run_id": opening_run_id,
                    "lifecycle": str(run["lifecycle"]),
                    "version": int(run["version"]),
                },
            }
        )
        checkpoint("after_outbox_insert")
        return {
            "opening_run_id": opening_run_id,
            "lifecycle": str(run["lifecycle"]),
            "version": int(run["version"]),
        }

    @staticmethod
    def _runtime_claim_payload(claim: RuntimeJobClaim) -> dict[str, Any]:
        return {
            "runtime_job_id": claim.runtime_job_id,
            "job_kind": claim.job_kind,
            "runtime_group": claim.runtime_group,
            "subject_kind": claim.subject_kind,
            "subject_id": claim.subject_id,
            "project_id": claim.project_id,
            "attempt_id": claim.attempt_id,
            "attempt_number": claim.attempt_number,
            "worker_id": claim.worker_id,
            "lease_id": claim.lease_id,
            "fencing_token": claim.fencing_token,
            "lease_expires_at": claim.lease_expires_at.isoformat(),
            "input_snapshot": dict(claim.input_snapshot),
        }

    @staticmethod
    def _runtime_claim_from_payload(value: object) -> RuntimeJobClaim:
        if not isinstance(value, dict):
            raise KernelError(
                "BOOK_OPENING_COMPLETION_BINDING_INVALID",
                "completion Runtime claim is missing",
            )
        try:
            return RuntimeJobClaim(
                runtime_job_id=str(value["runtime_job_id"]),
                job_kind=str(value["job_kind"]),
                runtime_group=str(value["runtime_group"]),
                subject_kind=str(value["subject_kind"]),
                subject_id=str(value["subject_id"]),
                project_id=str(value["project_id"]),
                attempt_id=str(value["attempt_id"]),
                attempt_number=int(value["attempt_number"]),
                worker_id=str(value["worker_id"]),
                lease_id=str(value["lease_id"]),
                fencing_token=int(value["fencing_token"]),
                lease_expires_at=datetime.fromisoformat(str(value["lease_expires_at"])),
                input_snapshot=dict(value["input_snapshot"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise KernelError(
                "BOOK_OPENING_COMPLETION_BINDING_INVALID",
                "completion Runtime claim is malformed",
            ) from exc

    @staticmethod
    def _require_in_uow(
        uow: AuthorityUnitOfWork, opening_run_id: str
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT opening_run_id,root_operation_id,lifecycle,version
            FROM authority_book_opening_run WHERE opening_run_id=%s
            """,
            [opening_run_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book opening run is missing")
        return dict(
            zip(
                ("opening_run_id", "root_operation_id", "lifecycle", "version"),
                row,
                strict=True,
            )
        )

    def _frozen_request(self, opening_run_id: str) -> OpenBookProductionRequest:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT frozen_request,frozen_request_digest
                FROM authority_book_opening_run WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or not isinstance(row[0], dict)
            or _canonical_hash(dict(row[0])) != str(row[1])
        ):
            raise KernelError(
                "BOOK_OPENING_FROZEN_REQUEST_DRIFT",
                "Book opening frozen request is missing or digest-mismatched",
            )
        return OpenBookProductionRequest.from_mapping(dict(row[0]))

    def _opening_input_assets(
        self, request: OpenBookProductionRequest
    ) -> list[dict[str, str]]:
        requested = {
            *request.planning_input_versions.values(),
            request.initial_story_state_version,
            request.initial_canon_snapshot_version,
        }
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id,version.content_hash
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                WHERE asset.project_id=%s AND version.asset_version_id=ANY(%s)
                """,
                [request.project_id, list(requested)],
            )
            found = {str(row[0]): str(row[1]) for row in uow.cursor.fetchall()}
        if set(found) != requested:
            raise KernelError(
                "BOOK_OPENING_INPUT_ASSET_MISSING",
                "Book opening frozen inputs are missing or outside Project scope",
            )
        return [
            {"asset_version_id": item, "content_hash": found[item]}
            for item in sorted(requested)
        ]

    def _bind_running_execution(
        self,
        opening_run_id: str,
        *,
        expected_version: int,
        runtime_claim: RuntimeJobClaim,
    ) -> None:
        """Bind the exact live Runtime claim before business execution."""

        if runtime_claim.subject_id != opening_run_id:
            raise KernelError(
                "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                "RuntimeJob subject differs from the Book Opening",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                [f"book-opening:{opening_run_id}"],
            )
            uow.cursor.execute(
                """
                SELECT opening.lifecycle,opening.current_execution_id,
                       opening.current_execution_generation,
                       execution.lifecycle,execution.version,
                       execution.runtime_job_id,execution.input_snapshot_hash,
                       job.input_hash,job.status,job.current_attempt_id,
                       job.current_fencing_token,job.lease_loss_policy,
                       attempt.worker_id,attempt.lease_id,attempt.status,
                       lease.lease_id,lease.worker_id,lease.fencing_token,
                       lease.status,lease.lease_expires_at,
                       execution.frozen_request_digest,
                       opening.frozen_request_digest,
                       execution.policy_snapshot_hash,
                       execution.authority_contract_hash,
                       execution.current_attempt_id,
                       execution.current_lease_id,
                       execution.current_worker_id,
                       execution.current_fencing_token
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.attempt_id=attempt.attempt_id
                WHERE opening.opening_run_id=%s AND opening.version=%s
                  AND execution.runtime_job_id=%s
                FOR UPDATE OF opening,execution,job,attempt,lease
                """,
                [opening_run_id, expected_version, runtime_claim.runtime_job_id],
            )
            row = uow.cursor.fetchone()
            valid = bool(
                row is not None
                and str(row[0]) in {"ADMITTED", "RUNNING"}
                and str(row[3]) in {"BOUND", "RUNNING"}
                and str(row[6]) == str(row[7])
                and str(row[8]) in {"RUNNING", "CHECKPOINTED"}
                and str(row[9]) == runtime_claim.attempt_id
                and int(row[10]) == runtime_claim.fencing_token
                and str(row[11]) == AUTHORITY_CONVERGENCE_REQUIRED
                and str(row[12]) == runtime_claim.worker_id
                and str(row[13]) == runtime_claim.lease_id
                and str(row[14]) in {"RUNNING", "CHECKPOINTED"}
                and str(row[15]) == runtime_claim.lease_id
                and str(row[16]) == runtime_claim.worker_id
                and int(row[17]) == runtime_claim.fencing_token
                and str(row[18]) == "HELD"
                and str(row[20]) == str(row[21])
                and str(row[22]) == self.recovery._execution_policy_digest()
                and str(row[23]) == self.recovery._authority_digest()
                and str(row[24]) == runtime_claim.attempt_id
                and str(row[25]) == runtime_claim.lease_id
                and str(row[26]) == runtime_claim.worker_id
                and int(row[27]) == runtime_claim.fencing_token
            )
            if not valid:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                    "Opening does not bind the exact RuntimeJob/Attempt/Lease/fence",
                )
            uow.cursor.execute(
                "SELECT %s::timestamptz > transaction_timestamp()",
                [row[19]],
            )
            if not bool(uow.cursor.fetchone()[0]):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_LEASE_EXPIRED",
                    "Opening execution lease expired before business execution",
                )
            if str(row[3]) == "BOUND":
                uow.cursor.execute(
                    """
                    UPDATE authority_book_opening_execution
                    SET lifecycle='RUNNING',version=version+1,
                        started_at=transaction_timestamp(),
                        updated_at=transaction_timestamp()
                    WHERE opening_execution_id=%s AND version=%s
                      AND lifecycle='BOUND' AND current_attempt_id=%s
                      AND current_lease_id=%s AND current_worker_id=%s
                      AND current_fencing_token=%s
                    """,
                    [
                        str(row[1]),
                        int(row[4]),
                        runtime_claim.attempt_id,
                        runtime_claim.lease_id,
                        runtime_claim.worker_id,
                        runtime_claim.fencing_token,
                    ],
                )
                if uow.cursor.rowcount != 1:
                    raise KernelError(
                        "BOOK_OPENING_EXECUTION_BINDING_CONFLICT",
                        "Opening execution was concurrently bound",
                    )
            else:
                uow.cursor.execute(
                    """
                    SELECT 1 FROM authority_book_opening_execution
                    WHERE opening_execution_id=%s AND current_attempt_id=%s
                      AND current_lease_id=%s AND current_worker_id=%s
                      AND current_fencing_token=%s AND lifecycle='RUNNING'
                    """,
                    [
                        str(row[1]),
                        runtime_claim.attempt_id,
                        runtime_claim.lease_id,
                        runtime_claim.worker_id,
                        runtime_claim.fencing_token,
                    ],
                )
                if uow.cursor.fetchone() is None:
                    raise KernelError(
                        "BOOK_OPENING_EXECUTION_BINDING_CONFLICT",
                        "RUNNING Opening execution carries a different claim",
                    )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='RUNNING',recovery_state='READY',
                    updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','RUNNING')
                  AND current_execution_id=%s
                  AND current_execution_generation=%s
                """,
                [opening_run_id, expected_version, str(row[1]), int(row[2])],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_CONFLICT",
                    "Book Opening changed while its execution was bound",
                )
            uow.commit()

    def _checkpoint_opening_result(
        self,
        opening_run_id: str,
        opened: BookOpeningResult,
        runtime_claim: RuntimeJobClaim,
    ) -> None:
        for search_id in opened.search_ids:
            self._checkpoint_search(
                opening_run_id, search_id, runtime_claim=runtime_claim
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT snapshot_hash
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s
                """,
                [opened.input_snapshot.snapshot_id],
            )
            snapshot = uow.cursor.fetchone()
        if snapshot is None:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_MISSING",
                "Book input snapshot disappeared before checkpoint",
            )
        self.recovery.append_execution_checkpoint(
            opening_run_id,
            runtime_claim=runtime_claim,
            semantic_work_key="book-opening:input-snapshot-resolved",
            owning_authority="BOOK_AUTHORITY",
            evidence_type="INPUT_SNAPSHOT",
            evidence_id=opened.input_snapshot.snapshot_id,
            evidence_version=0,
            evidence_hash=str(snapshot[0]),
        )

    def _checkpoint_search(
        self,
        opening_run_id: str,
        search_id: str,
        *,
        runtime_claim: RuntimeJobClaim | None,
    ) -> None:
        if opening_run_id:
            if runtime_claim is None:
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EXECUTION_REQUIRED",
                    "Opening progress checkpoint requires its exact Runtime claim",
                )
            self.recovery.append_execution_narrative_search_checkpoint(
                opening_run_id, search_id, runtime_claim=runtime_claim
            )

    @staticmethod
    def _probe(execution_probe: Callable[[], object] | None) -> None:
        if execution_probe is not None:
            execution_probe()

    def _latest_job(self, opening_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT job.runtime_job_id,job.status
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                 AND job.job_kind='BOOK_OPENING_EXECUTE'
                 AND job.runtime_group='book_opening'
                 AND job.subject_kind='BOOK_OPENING_RUN'
                 AND job.subject_id=opening.opening_run_id
                WHERE opening.opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_JOB_MISSING",
                "Book opening replay has no durable RuntimeJob lineage",
            )
        return {"runtime_job_id": str(row[0]), "status": str(row[1])}

    def _register_definitions(self) -> None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            for name in sorted(BOOK_OPENING_OPERATIONS):
                uow.repositories.definitions.register(
                    _opening_definition(
                        name,
                        application_build_id=self.application_build_id,
                        commit_sha=self.commit_sha,
                    )
                )
            uow.commit()

    def _context(self, actor_id: str) -> AdmissionContext:
        return AdmissionContext(
            actor_id=actor_id,
            permissions=frozenset(
                {"book.authority.execute", "story_planning.authority.execute"}
            ),
            available_handlers=frozenset({BOOK_OPENING_HANDLER}),
            application_build_id=self.application_build_id,
            commit_sha=self.commit_sha,
        )

    def _search(
        self,
        *,
        request: OpenBookProductionRequest,
        principal: Principal,
        generator: str,
        logical_key: str,
        input_versions: Mapping[str, str],
        parent_version_id: str,
        accepted_state: str,
        horizon: Mapping[str, object],
        transformation: Mapping[str, object],
        progress: Mapping[str, Mapping[str, Any]] | None = None,
        execution_probe: Callable[[], object] | None = None,
    ):
        generation = StoryPlanningGenerationCommand(
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            book_id=request.book_id,
            actor_id=request.actor_id,
            generator_operation_name=generator,
            logical_key=logical_key,
            input_versions=input_versions,
            parent_version_id=parent_version_id,
            idempotency_key=f"{request.idempotency_key}:{generator}:{logical_key}",
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )
        search_request = NarrativeSearchRequest(
            generation=generation,
            planning_horizon=horizon,
            desired_transformation=transformation,
            hard_constraints=(
                "preserve the approved Creative Foundation",
                "protect reader promise and ending direction",
                "do not convert future intent into accepted reality",
            ),
            accepted_through_chapter=0,
            parent_state_asset_version_id=accepted_state,
        )
        checkpoint = dict((progress or {}).get(f"{generator}:{logical_key}") or {})
        if checkpoint:
            if (
                str(checkpoint.get("owning_authority")) != "STORY_PLANNING"
                or str(checkpoint.get("evidence_type")) != "NARRATIVE_SEARCH"
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "semantic work checkpoint is not a Planning-owned Narrative Search",
                )
            resumed = self.narrative_search.require_selected(
                search_request,
                activate_selected=True,
            )
            if resumed.search_id != str(checkpoint.get("evidence_id") or ""):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "resumed Narrative Search differs from the checkpoint cursor",
                )
            return resumed
        return self.narrative_search.explore(
            search_request,
            principal=principal,
            activate_selected=True,
            execution_probe=execution_probe,
        )

    @staticmethod
    def _stage_inputs(
        generic: Mapping[str, str],
        generator: str,
        *,
        book_plan: str,
        volume_plan: str = "",
    ) -> dict[str, str]:
        values = dict(generic)
        values["book_plan"] = book_plan
        if volume_plan:
            values["volume_plan"] = volume_plan
        return {role: values[role] for role in GENERATOR_INPUT_ROLES[generator]}

    def _require_qualified_foundation(self, request: OpenBookProductionRequest) -> str:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book.current_book_design_asset_version_id,
                       version.schema_version, version.lifecycle,
                       version.eligibility, version.governance,
                       version.content_hash, version.content
                FROM authority_book AS book
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=book.current_book_design_asset_version_id
                WHERE book.project_id=%s AND book.workspace_id=%s AND book.book_id=%s
                  AND book.version=%s AND book.status='DESIGN_ACTIVE'
                """,
                [
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                    request.expected_book_version,
                ],
            )
            row = uow.cursor.fetchone()
            if row is None or tuple(str(item) for item in row[1:5]) != (
                FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                "ACTIVE",
                "ELIGIBLE",
                "CLEAR",
            ):
                raise KernelError(
                    "BOOK_OPENING_FOUNDATION_REQUIRED",
                    "Book opening requires the exact active and qualified Foundation synthesis",
                )
            foundation = require_current_foundation_set(
                uow.cursor,
                project_id=request.project_id,
                book_id=request.book_id,
                require_ready=True,
            )
            design = BookDesignPayload.from_mapping(dict(row[6]))
            if design.foundation_set != foundation:
                raise KernelError(
                    "BOOK_OPENING_FOUNDATION_DRIFT",
                    "BookDesign does not bind the current qualified Foundation Set",
                )
            uow.cursor.execute(
                """
                SELECT formation_run_id
                FROM authority_story_formation_run
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                  AND lifecycle='READY' AND current_stage='COMPLETE'
                  AND foundation_set_digest=%s
                  AND book_design_asset_version_id=%s
                  AND book_design_content_hash=%s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                [
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                    foundation.set_digest,
                    str(row[0]),
                    str(row[5]),
                ],
            )
            formation = uow.cursor.fetchone()
        if formation is None:
            raise KernelError(
                "BOOK_OPENING_FORMATION_NOT_READY",
                "Book opening requires a READY durable Story Formation bound to the active synthesis",
            )
        return str(row[0])


def _opening_definition(
    name: str, *, application_build_id: str, commit_sha: str
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "required": ["project_id", "book_id", "opening_run_id"],
        "properties": {
            "project_id": {"type": "string"},
            "book_id": {"type": "string"},
            "opening_run_id": {"type": "string"},
        },
    }
    return {
        "name": name,
        "definition_version": BOOK_OPENING_DEFINITION_VERSION,
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented",
        "command_schema_version": "book-opening-command.v1",
        "result_schema_version": "book-opening-result.v1",
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {"type": "BookOpeningTransition"},
        "handler_key": BOOK_OPENING_HANDLER,
        "handler_contract_version": "book-opening-handler.v1",
        "application_build_id": application_build_id,
        "commit_sha": commit_sha,
        "execution_mode": "transactional",
        "permissions": ["book.authority.execute"],
        "approval_policy": {"required": False},
        "policy": {
            "execution_classification": "transaction_command",
            "worker_owned_provider_chain": True,
            "frozen_inputs_required": True,
        },
        "idempotency_scope": "book:opening",
        "concurrency_key_template": "book:{book_id}:opening",
        "retry_policy": {"max_attempts": 5},
        "timeout_policy": {"operation_timeout_seconds": 300},
        "cancellation_policy": {"mode": "reject_if_committing"},
        "compensation_policy": {
            "supported": False,
            "reason": "immutable selected search and Plan activation lineage",
        },
        "irreversible_effect_policy": {"allowed": False},
        "external_capabilities": [],
        "projection_consumers": ["book_opening_run"],
        "migration_owner": "book-authority",
        "completion_contract": {
            "version": "book-opening-completion.v1",
            "required_evidence": ["trace", "audit"],
            "required_outbox_events": ["book.opening.transitioned"],
        },
    }


__all__ = [
    "BookOpeningAdmission",
    "BookOpeningResult",
    "OpenBookProductionRequest",
    "PostgresBookOpeningApplication",
]
