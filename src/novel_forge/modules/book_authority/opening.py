"""Book opening coordinator over existing design, planning, and input Authorities."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetScopeRequest,
    canonical_budget_reservation_snapshot,
    canonical_budget_policy,
    create_or_get_budget_scope_in_uow,
    deterministic_budget_operation_binding_id,
    lock_budget_scope_in_uow,
)
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
        "book.opening.reconcile_legacy_budget_scope",
        "book.opening.resume",
        "book.opening.abort",
    }
)
BOOK_OPENING_BUDGET_POLICY_VERSION = "book-opening-provider-budget.v1"
DEFAULT_BOOK_OPENING_BUDGET_POLICY: Mapping[str, object] = {
    "execution_mode": "PROVIDER_ALLOWED",
    "provider_call_limit": 40,
    "token_limit": 1_800_000,
    "cost_limit_usd": "20",
    "per_call_token_limit": 100_000,
    "per_call_cost_limit_usd": "2",
}
DEFAULT_BOOK_OPENING_BUDGET_WINDOW_SECONDS = 3_600


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
class BookOpeningBudgetReconciliationRequest:
    """Explicit, bounded contract for one legacy Opening budget binding."""

    expected_opening_version: int
    expected_frozen_request_digest: str
    idempotency_key: str
    policy_contract_version: str
    policy_snapshot: Mapping[str, Any]
    policy_hash: str
    currency: str
    budget_timezone: str
    started_at: datetime
    deadline_at: datetime
    reason: str
    legacy_operation_ids: tuple[str, ...] = ()
    legacy_reservation_ids: tuple[str, ...] = ()
    contract_hash: str = field(init=False)

    def __post_init__(self) -> None:
        required = (
            self.idempotency_key,
            self.policy_contract_version,
            self.currency,
            self.budget_timezone,
            self.reason,
        )
        if self.expected_opening_version < 0 or any(
            not str(value).strip() for value in required
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "legacy budget reconciliation request is incomplete",
            )
        if (
            re.fullmatch(r"sha256:[0-9a-f]{64}", self.expected_frozen_request_digest)
            is None
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "expected frozen request digest is invalid",
            )
        if (
            self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
            or self.deadline_at.tzinfo is None
            or self.deadline_at.utcoffset() is None
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "legacy budget timestamps must be timezone-aware",
            )
        if self.deadline_at <= self.started_at:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "legacy budget deadline must be after started_at",
            )
        policy = canonical_budget_policy(dict(self.policy_snapshot))
        if str(policy["policy_hash"]) != self.policy_hash:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "explicit budget policy hash differs from its snapshot",
            )
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "policy_snapshot", policy["policy_snapshot"])
        operation_ids = tuple(
            sorted({str(item).strip() for item in self.legacy_operation_ids})
        )
        reservation_ids = tuple(
            sorted({str(item).strip() for item in self.legacy_reservation_ids})
        )
        if any(not item for item in (*operation_ids, *reservation_ids)):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "legacy budget Authority identities cannot be empty",
            )
        object.__setattr__(self, "legacy_operation_ids", operation_ids)
        object.__setattr__(self, "legacy_reservation_ids", reservation_ids)
        object.__setattr__(
            self,
            "contract_hash",
            _canonical_hash(self.contract_snapshot()),
        )

    def contract_snapshot(self) -> dict[str, Any]:
        return {
            "contract_version": "book-opening-budget-reconciliation-contract.v1",
            "policy_contract_version": self.policy_contract_version,
            "policy_snapshot": dict(self.policy_snapshot),
            "policy_hash": self.policy_hash,
            "currency": self.currency,
            "budget_timezone": self.budget_timezone,
            "started_at": self.started_at.isoformat(),
            "deadline_at": self.deadline_at.isoformat(),
            "legacy_operation_ids": list(self.legacy_operation_ids),
            "legacy_reservation_ids": list(self.legacy_reservation_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_opening_version": self.expected_opening_version,
            "expected_frozen_request_digest": self.expected_frozen_request_digest,
            "idempotency_key": self.idempotency_key,
            "reason": self.reason,
            **self.contract_snapshot(),
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "BookOpeningBudgetReconciliationRequest":
        expected = {
            "expected_opening_version",
            "expected_frozen_request_digest",
            "idempotency_key",
            "reason",
            "contract_version",
            "policy_contract_version",
            "policy_snapshot",
            "policy_hash",
            "currency",
            "budget_timezone",
            "started_at",
            "deadline_at",
            "contract_hash",
            "legacy_operation_ids",
            "legacy_reservation_ids",
        }
        if set(value) != expected or value.get("contract_version") != (
            "book-opening-budget-reconciliation-contract.v1"
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "frozen legacy budget contract fields are invalid",
            )
        request = cls(
            expected_opening_version=int(value["expected_opening_version"]),
            expected_frozen_request_digest=str(value["expected_frozen_request_digest"]),
            idempotency_key=str(value["idempotency_key"]),
            policy_contract_version=str(value["policy_contract_version"]),
            policy_snapshot=dict(value["policy_snapshot"]),
            policy_hash=str(value["policy_hash"]),
            currency=str(value["currency"]),
            budget_timezone=str(value["budget_timezone"]),
            started_at=datetime.fromisoformat(str(value["started_at"])),
            deadline_at=datetime.fromisoformat(str(value["deadline_at"])),
            reason=str(value["reason"]),
            legacy_operation_ids=tuple(
                str(item) for item in value["legacy_operation_ids"]
            ),
            legacy_reservation_ids=tuple(
                str(item) for item in value["legacy_reservation_ids"]
            ),
        )
        if request.contract_hash != str(value["contract_hash"]):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "frozen legacy budget contract hash drifted",
            )
        return request


@dataclass(frozen=True, slots=True)
class BookOpeningBudgetReconciliationReceipt:
    budget_reconciliation_receipt_id: str
    opening_run_id: str
    budget_scope_id: str
    budget_scope_revision: int
    policy_hash: str
    contract_hash: str
    result_hash: str
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
        provider_budget_policy: Mapping[str, object] | None = None,
        provider_budget_window_seconds: int = (
            DEFAULT_BOOK_OPENING_BUDGET_WINDOW_SECONDS
        ),
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("Book opening requires PostgreSQL/build identity")
        self.database_url = database_url
        self.narrative_search = narrative_search
        self.input_resolver = input_resolver
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        if provider_budget_window_seconds <= 0:
            raise ValueError("Book opening Provider budget window must be positive")
        budget_policy = canonical_budget_policy(
            dict(provider_budget_policy or DEFAULT_BOOK_OPENING_BUDGET_POLICY)
        )
        self.provider_budget_policy = dict(budget_policy["policy_snapshot"])
        self.provider_budget_policy_hash = str(budget_policy["policy_hash"])
        self.provider_budget_window_seconds = provider_budget_window_seconds
        self.fault_injector = fault_injector
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
                    "provider_budget_contract": {
                        "policy_contract_version": (BOOK_OPENING_BUDGET_POLICY_VERSION),
                        "policy_snapshot": dict(self.provider_budget_policy),
                        "policy_hash": self.provider_budget_policy_hash,
                        "currency": "USD",
                        "budget_timezone": "UTC",
                        "window_seconds": self.provider_budget_window_seconds,
                    },
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

    def reconcile_legacy_budget_scope(
        self,
        opening_run_id: str,
        request: BookOpeningBudgetReconciliationRequest,
        *,
        principal: Principal,
    ) -> BookOpeningBudgetReconciliationReceipt:
        """Bind an explicit BudgetScope to one migrated legacy Opening."""

        run = self.require(opening_run_id)
        principal.require("book.authority.execute", str(run["project_id"]))
        self._register_definitions()
        executed = execute_transaction_command(
            self.database_url,
            {
                "definition_name": "book.opening.reconcile_legacy_budget_scope",
                "definition_version": BOOK_OPENING_DEFINITION_VERSION,
                "project_id": str(run["project_id"]),
                "workspace_id": str(run["workspace_id"]),
                "book_id": str(run["book_id"]),
                "actor_id": principal.principal_id,
                "idempotency_scope": "book:opening",
                "idempotency_key": (
                    f"{opening_run_id}:legacy-budget:{request.idempotency_key}"
                ),
                "trace_id": f"trace:{opening_run_id}:legacy-budget",
                "span_id": str(uuid4()),
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "causation_operation_id": str(run["root_operation_id"]),
                "input": {
                    "project_id": str(run["project_id"]),
                    "book_id": str(run["book_id"]),
                    "opening_run_id": opening_run_id,
                    "budget_reconciliation": request.to_dict(),
                },
                "input_assets": [],
            },
            context=self._context(principal.principal_id),
            handler=self._execute_transaction,
            fault_injector=self.fault_injector,
        )
        return BookOpeningBudgetReconciliationReceipt(
            budget_reconciliation_receipt_id=str(
                executed["budget_reconciliation_receipt_id"]
            ),
            opening_run_id=opening_run_id,
            budget_scope_id=str(executed["budget_scope_id"]),
            budget_scope_revision=int(executed["budget_scope_revision"]),
            policy_hash=str(executed["policy_hash"]),
            contract_hash=str(executed["contract_hash"]),
            result_hash=str(executed["result_hash"]),
            replayed=bool(
                executed.get("replayed") or executed.get("semantic_replayed")
            ),
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
                       recovery_state,budget_scope_id,budget_scope_revision,
                       budget_contract_state
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
                    "budget_scope_id",
                    "budget_scope_revision",
                    "budget_contract_state",
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
            opening_run_id=opening_run_id,
            runtime_claim=runtime_claim,
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
            opening_run_id=opening_run_id,
            runtime_claim=runtime_claim,
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
                opening_run_id=opening_run_id,
                runtime_claim=runtime_claim,
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
            SELECT definition_name,project_id,workspace_id,command_payload,
                   actor_id,created_at
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
        if definition_name == "book.opening.reconcile_legacy_budget_scope":
            return self._reconcile_legacy_budget_scope_in_uow(
                uow,
                operation_id=operation_id,
                payload=payload,
                principal_id=str(operation[4]),
                checkpoint=checkpoint,
            )
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
                        "semantic_evaluation_operation_id": "",
                        "semantic_evaluation_execution_id": "",
                        "semantic_evaluation_generation": 0,
                        "semantic_execution_mode": "NONE",
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
            budget_contract = payload.get("provider_budget_contract")
            if not isinstance(budget_contract, Mapping):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_CONTRACT_INVALID",
                    "Book Opening admission has no frozen Provider budget",
                )
            canonical_policy = canonical_budget_policy(
                dict(budget_contract.get("policy_snapshot") or {})
            )
            if (
                str(canonical_policy["policy_hash"])
                != str(budget_contract.get("policy_hash") or "")
                or int(budget_contract.get("window_seconds") or 0) <= 0
            ):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_CONTRACT_INVALID",
                    "Book Opening Provider budget differs from its frozen hash",
                )
            started_at = operation[5]
            budget_scope = create_or_get_budget_scope_in_uow(
                uow,
                BudgetScopeRequest(
                    project_id=str(operation[1]),
                    owner_kind="BOOK_OPENING",
                    owner_id=opening_run_id,
                    stable_idempotency_key=(f"book-opening-budget:{opening_run_id}"),
                    currency=str(budget_contract.get("currency") or ""),
                    policy_contract_version=str(
                        budget_contract.get("policy_contract_version") or ""
                    ),
                    policy_snapshot=dict(canonical_policy["policy_snapshot"]),
                    started_at=started_at,
                    deadline_at=started_at
                    + timedelta(seconds=int(budget_contract["window_seconds"])),
                    created_by_operation_id=operation_id,
                    budget_timezone=str(budget_contract.get("budget_timezone") or ""),
                ),
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET budget_scope_id=%s,budget_scope_revision=%s,
                    budget_contract_state='BOUND',
                    updated_at=transaction_timestamp()
                WHERE opening_run_id=%s
                  AND (
                      budget_scope_id IS NULL
                      OR (
                          budget_scope_id=%s
                          AND budget_scope_revision=%s
                          AND budget_contract_state='BOUND'
                      )
                  )
                """,
                [
                    budget_scope["budget_scope_id"],
                    budget_scope["revision"],
                    opening_run_id,
                    budget_scope["budget_scope_id"],
                    budget_scope["revision"],
                ],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_BINDING_CONFLICT",
                    "Book Opening is already bound to another Budget Authority",
                )
            checkpoint("after_budget_scope_binding")
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
            self.recovery.assert_execution_completion_checkpoints_in_uow(
                uow,
                opening_run_id=opening_run_id,
                opening_execution_id=str(execution[0]),
                execution_generation=int(execution[1]),
                result=result,
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
                       execution.current_fencing_token,opening.project_id,
                       opening.budget_contract_state,opening.budget_scope_id,
                       opening.budget_scope_revision
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                WHERE opening.opening_run_id=%s AND opening.version=%s
                  AND opening.lifecycle IN ('ADMITTED','RUNNING','FAILED')
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
            if str(binding[0]) in {"ADMITTED", "RUNNING"}:
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
                if (
                    str(binding[11]) != "BOUND"
                    or binding[12] is None
                    or binding[13] is None
                ):
                    raise KernelError(
                        "BOOK_OPENING_BUDGET_SCOPE_REQUIRED",
                        "Opening abort requires an authoritative BudgetScope binding",
                    )
                budget_scope = lock_budget_scope_in_uow(
                    uow,
                    budget_scope_id=str(binding[12]),
                    project_id=str(binding[10]),
                )
                if (
                    int(budget_scope["revision"]) != int(binding[13])
                    or str(budget_scope["owner_kind"]) != "BOOK_OPENING"
                    or str(budget_scope["owner_id"]) != opening_run_id
                    or str(budget_scope["currency"]).upper() != "USD"
                ):
                    raise KernelError(
                        "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
                        "Opening abort BudgetScope differs from its frozen binding",
                    )
                semantic_mode = str(runtime["semantic_execution_mode"])
                semantic_operation_id = str(runtime["semantic_evaluation_operation_id"])
                semantic_execution_id = str(runtime["semantic_evaluation_execution_id"])
                semantic_generation = int(runtime["semantic_evaluation_generation"])
                replacement_operation_id = str(
                    runtime["replacement_evaluation_operation_id"]
                )
                if semantic_mode == "NEW_REPLACEMENT":
                    if (
                        not replacement_operation_id
                        or replacement_operation_id != semantic_operation_id
                        or not semantic_execution_id
                        or semantic_generation <= 1
                    ):
                        raise KernelError(
                            "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                            "Opening abort replacement identity is incomplete",
                        )
                    if self.recovery.semantic_replacement is None:
                        raise KernelError(
                            "BOOK_OPENING_REPLACEMENT_RUNTIME_REQUIRED",
                            "Opening abort requires the semantic replacement Application",
                        )
                    if str(binding[0]) == "ADMITTED":
                        self.recovery.semantic_replacement.cancel_unstarted_replacement_in_uow(
                            uow,
                            operation_id=replacement_operation_id,
                            actor_id=str(operation[4]),
                            trace_id=f"trace:{opening_run_id}:abort",
                            correlation_id=str(operation_id),
                            reason=(
                                "Book Opening was aborted before replacement execution"
                            ),
                        )
                    else:
                        self.recovery.semantic_replacement.abort_opening_owned_execution_in_uow(
                            uow,
                            operation_id=semantic_operation_id,
                            evaluation_execution_id=semantic_execution_id,
                            generation=semantic_generation,
                            actor_id=str(operation[4]),
                            trace_id=f"trace:{opening_run_id}:abort",
                            correlation_id=str(operation_id),
                            reason=(
                                "Book Opening owner aborted active semantic "
                                "replacement execution"
                            ),
                        )
                elif semantic_mode == "RESUME_CURRENT":
                    if (
                        replacement_operation_id
                        or not semantic_operation_id
                        or not semantic_execution_id
                        or semantic_generation <= 0
                    ):
                        raise KernelError(
                            "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                            "Opening abort resume identity is incomplete",
                        )
                    if self.recovery.semantic_replacement is None:
                        raise KernelError(
                            "BOOK_OPENING_REPLACEMENT_RUNTIME_REQUIRED",
                            "Opening abort requires the semantic Evaluation Application",
                        )
                    self.recovery.semantic_replacement.abort_opening_owned_execution_in_uow(
                        uow,
                        operation_id=semantic_operation_id,
                        evaluation_execution_id=semantic_execution_id,
                        generation=semantic_generation,
                        actor_id=str(operation[4]),
                        trace_id=f"trace:{opening_run_id}:abort",
                        correlation_id=str(operation_id),
                        reason="Book Opening owner aborted resumed semantic execution",
                    )
                elif semantic_mode == "NONE":
                    if (
                        replacement_operation_id
                        or semantic_operation_id
                        or semantic_execution_id
                        or semantic_generation != 0
                    ):
                        raise KernelError(
                            "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                            "Opening abort NONE mode carries semantic execution identity",
                        )
                else:
                    raise KernelError(
                        "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                        "Opening abort RuntimeJob carries an unknown semantic mode",
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
                  AND lifecycle IN ('ADMITTED','RUNNING','FAILED')
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

    def _reconcile_legacy_budget_scope_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        payload: Mapping[str, Any],
        principal_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        opening_run_id = str(payload.get("opening_run_id") or "")
        raw_request = payload.get("budget_reconciliation")
        if not opening_run_id or not isinstance(raw_request, Mapping):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_INVALID",
                "legacy budget reconciliation payload is incomplete",
            )
        request = BookOpeningBudgetReconciliationRequest.from_mapping(raw_request)
        uow.cursor.execute(
            """
            SELECT opening_run_id,project_id,book_id,root_operation_id,
                   lifecycle,version,frozen_request_digest,budget_scope_id,
                   budget_scope_revision,budget_contract_state,
                   current_execution_id,current_execution_generation
            FROM authority_book_opening_run
            WHERE opening_run_id=%s
            FOR UPDATE
            """,
            [opening_run_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book opening run is missing")
        run = dict(
            zip(
                (
                    "opening_run_id",
                    "project_id",
                    "book_id",
                    "root_operation_id",
                    "lifecycle",
                    "version",
                    "frozen_request_digest",
                    "budget_scope_id",
                    "budget_scope_revision",
                    "budget_contract_state",
                    "current_execution_id",
                    "current_execution_generation",
                ),
                row,
                strict=True,
            )
        )
        if str(run["project_id"]) != str(payload.get("project_id") or "") or str(
            run["book_id"]
        ) != str(payload.get("book_id") or ""):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_SCOPE_CONFLICT",
                "legacy budget command is outside its Opening scope",
            )
        intent = {
            "contract_version": "book-opening-budget-reconciliation-intent.v1",
            "opening_run_id": opening_run_id,
            "expected_opening_version": request.expected_opening_version,
            "expected_frozen_request_digest": (request.expected_frozen_request_digest),
            "contract_hash": request.contract_hash,
            "authorized_by": principal_id,
            "authorization_reason": request.reason,
        }
        intent_hash = _canonical_hash(intent)
        uow.cursor.execute(
            """
            SELECT budget_reconciliation_receipt_id,project_id,budget_scope_id,
                   budget_scope_revision,expected_opening_version,
                   frozen_request_digest,contract_snapshot,contract_hash,
                   intent_hash,authorized_by,authorization_reason,result,
                   result_hash
            FROM authority_book_opening_budget_reconciliation_receipt
            WHERE opening_run_id=%s
            """,
            [opening_run_id],
        )
        existing = uow.cursor.fetchone()
        if existing is not None:
            receipt = dict(
                zip(
                    (
                        "budget_reconciliation_receipt_id",
                        "project_id",
                        "budget_scope_id",
                        "budget_scope_revision",
                        "expected_opening_version",
                        "frozen_request_digest",
                        "contract_snapshot",
                        "contract_hash",
                        "intent_hash",
                        "authorized_by",
                        "authorization_reason",
                        "result",
                        "result_hash",
                    ),
                    existing,
                    strict=True,
                )
            )
            if (
                str(receipt["project_id"]) != str(run["project_id"])
                or int(receipt["expected_opening_version"])
                != request.expected_opening_version
                or str(receipt["frozen_request_digest"])
                != request.expected_frozen_request_digest
                or dict(receipt["contract_snapshot"]) != request.contract_snapshot()
                or str(receipt["contract_hash"]) != request.contract_hash
                or str(receipt["intent_hash"]) != intent_hash
                or str(receipt["authorized_by"]) != principal_id
                or str(receipt["authorization_reason"]) != request.reason
                or _canonical_hash(dict(receipt["result"]))
                != str(receipt["result_hash"])
                or str(run["budget_contract_state"]) != "BOUND"
                or str(run["budget_scope_id"] or "") != str(receipt["budget_scope_id"])
                or int(run["budget_scope_revision"] or 0)
                != int(receipt["budget_scope_revision"])
            ):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_IDEMPOTENCY_CONFLICT",
                    "legacy budget reconciliation intent differs from its receipt",
                )
            return {
                "budget_reconciliation_receipt_id": str(
                    receipt["budget_reconciliation_receipt_id"]
                ),
                **dict(receipt["result"]),
                "result_hash": str(receipt["result_hash"]),
                "semantic_replayed": True,
            }
        if (
            int(run["version"]) != request.expected_opening_version
            or str(run["frozen_request_digest"])
            != request.expected_frozen_request_digest
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_STALE",
                "Book Opening version or frozen request changed before reconciliation",
            )
        if str(run["lifecycle"]) not in {"ADMITTED", "FAILED"}:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_STATE_INVALID",
                "legacy budget reconciliation requires unclaimed ADMITTED or terminally failed Opening work",
            )
        if (
            str(run["budget_contract_state"]) != "LEGACY_BUDGET_RECONCILIATION_REQUIRED"
            or run["budget_scope_id"] is not None
            or run["budget_scope_revision"] is not None
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_STATE_INVALID",
                "Book Opening is not an unbound legacy budget owner",
            )
        execution_binding = self._lock_legacy_budget_reconciliation_execution(
            uow, run=run
        )
        if str(run["lifecycle"]) == "ADMITTED" and (
            request.legacy_operation_ids or request.legacy_reservation_ids
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_STATE_INVALID",
                "unclaimed Opening cannot attribute historical Provider work",
            )
        scope = create_or_get_budget_scope_in_uow(
            uow,
            BudgetScopeRequest(
                project_id=str(run["project_id"]),
                owner_kind="BOOK_OPENING",
                owner_id=opening_run_id,
                stable_idempotency_key=(
                    f"book-opening-budget-reconciliation:{opening_run_id}"
                ),
                currency=request.currency,
                policy_contract_version=request.policy_contract_version,
                policy_snapshot=request.policy_snapshot,
                started_at=request.started_at,
                deadline_at=request.deadline_at,
                created_by_operation_id=operation_id,
                budget_timezone=request.budget_timezone,
            ),
        )
        checkpoint("after_legacy_budget_scope_creation")
        operation_bindings = self._bind_legacy_budget_operations_in_uow(
            uow,
            run=run,
            execution_binding=execution_binding,
            scope=scope,
            operation_ids=request.legacy_operation_ids,
            bound_by_operation_id=operation_id,
        )
        reservation_attributions = (
            self._prepare_legacy_budget_reservation_attributions_in_uow(
                uow,
                run=run,
                scope=scope,
                operation_ids=request.legacy_operation_ids,
                reservation_ids=request.legacy_reservation_ids,
            )
        )
        uow.cursor.execute(
            """
            UPDATE authority_book_opening_run
            SET budget_scope_id=%s,budget_scope_revision=%s,
                budget_contract_state='BOUND',version=version+1,
                updated_at=transaction_timestamp()
            WHERE opening_run_id=%s AND version=%s
              AND frozen_request_digest=%s
              AND budget_scope_id IS NULL
              AND budget_scope_revision IS NULL
              AND budget_contract_state=
                  'LEGACY_BUDGET_RECONCILIATION_REQUIRED'
            """,
            [
                scope["budget_scope_id"],
                scope["revision"],
                opening_run_id,
                request.expected_opening_version,
                request.expected_frozen_request_digest,
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_STALE",
                "Book Opening budget binding CAS lost",
            )
        checkpoint("after_legacy_budget_scope_binding")
        result = {
            "opening_run_id": opening_run_id,
            "opening_version": request.expected_opening_version + 1,
            "budget_scope_id": str(scope["budget_scope_id"]),
            "budget_scope_revision": int(scope["revision"]),
            "policy_hash": request.policy_hash,
            "contract_hash": request.contract_hash,
            "operation_budget_binding_ids": [
                item["operation_budget_binding_id"] for item in operation_bindings
            ],
            "legacy_budget_attribution_ids": [
                item["legacy_budget_attribution_id"]
                for item in reservation_attributions
            ],
            "legacy_budget_attribution_hash": _canonical_hash(reservation_attributions),
            "provider_invoked": False,
        }
        result_hash = _canonical_hash(result)
        receipt_id = _stable_id(
            "book-opening-budget-reconciliation-receipt",
            opening_run_id,
            intent_hash,
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_budget_reconciliation_receipt(
                budget_reconciliation_receipt_id,opening_run_id,project_id,
                budget_scope_id,budget_scope_revision,command_operation_id,
                expected_opening_version,frozen_request_digest,
                contract_snapshot,contract_hash,intent_hash,idempotency_key,
                authorized_by,authorization_reason,result,result_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                receipt_id,
                opening_run_id,
                run["project_id"],
                scope["budget_scope_id"],
                scope["revision"],
                operation_id,
                request.expected_opening_version,
                request.expected_frozen_request_digest,
                Jsonb(request.contract_snapshot()),
                request.contract_hash,
                intent_hash,
                request.idempotency_key,
                principal_id,
                request.reason,
                Jsonb(result),
                result_hash,
            ],
        )
        checkpoint("after_legacy_budget_reconciliation_receipt")
        for attribution in reservation_attributions:
            uow.cursor.execute(
                """
                INSERT INTO
                    authority_book_opening_legacy_budget_reservation_attribution(
                        legacy_budget_attribution_id,
                        budget_reconciliation_receipt_id,opening_run_id,
                        project_id,budget_scope_id,budget_scope_revision,
                        reservation_id,operation_id,external_effect_id,
                        reservation_version,reservation_status,
                        reservation_snapshot,reservation_snapshot_hash,
                        cost_evidence_id,cost_evidence_version,
                        cost_evidence_hash,attributed_by_operation_id
                    )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        NULLIF(%s,''),%s,NULLIF(%s,''),%s)
                """,
                [
                    attribution["legacy_budget_attribution_id"],
                    receipt_id,
                    opening_run_id,
                    run["project_id"],
                    scope["budget_scope_id"],
                    scope["revision"],
                    attribution["reservation_id"],
                    attribution["operation_id"],
                    attribution["external_effect_id"],
                    attribution["reservation_version"],
                    attribution["reservation_status"],
                    Jsonb(attribution["reservation_snapshot"]),
                    attribution["reservation_snapshot_hash"],
                    attribution["cost_evidence_id"],
                    attribution["cost_evidence_version"],
                    attribution["cost_evidence_hash"],
                    operation_id,
                ],
            )
        checkpoint("after_legacy_budget_reservation_attribution")
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_opening",
                "aggregate_id": opening_run_id,
                "operation_id": operation_id,
                "project_id": str(run["project_id"]),
                "event_type": "book.opening.legacy_budget_reconciled",
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "payload": {
                    "operation_id": operation_id,
                    "budget_reconciliation_receipt_id": receipt_id,
                    **result,
                },
            }
        )
        checkpoint("after_legacy_budget_reconciliation_outbox")
        return {
            "budget_reconciliation_receipt_id": receipt_id,
            **result,
            "result_hash": result_hash,
            "semantic_replayed": False,
        }

    @staticmethod
    def _lock_legacy_budget_reconciliation_execution(
        uow: AuthorityUnitOfWork, *, run: Mapping[str, Any]
    ) -> dict[str, Any]:
        execution_id = str(run.get("current_execution_id") or "")
        execution_generation = int(run.get("current_execution_generation") or 0)
        if not execution_id or execution_generation <= 0:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_EXECUTION_REQUIRED",
                "legacy runtime execution must be reconciled before its budget",
            )
        uow.cursor.execute(
            """
            SELECT opening_execution_id,generation,runtime_job_id,lifecycle,
                   current_attempt_id,current_lease_id,current_worker_id,
                   current_fencing_token
            FROM authority_book_opening_execution
            WHERE opening_run_id=%s AND opening_execution_id=%s
              AND generation=%s
            FOR UPDATE
            """,
            [run["opening_run_id"], execution_id, execution_generation],
        )
        execution = uow.cursor.fetchone()
        if execution is None or execution[2] is None:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_EXECUTION_REQUIRED",
                "Book Opening has no authoritative RuntimeJob execution",
            )
        uow.cursor.execute(
            """
            SELECT runtime_job_id,status,current_attempt_id,current_fencing_token,
                   claimed_by,attempt_count
            FROM authority_runtime_job WHERE runtime_job_id=%s FOR UPDATE
            """,
            [execution[2]],
        )
        job = uow.cursor.fetchone()
        if job is None:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_EXECUTION_REQUIRED",
                "Book Opening RuntimeJob is missing",
            )
        attempt = None
        lease = None
        if execution[4] is not None:
            uow.cursor.execute(
                """
                SELECT attempt_id,status,lease_id,worker_id,fencing_token
                FROM authority_runtime_job_attempt
                WHERE runtime_job_id=%s AND attempt_id=%s FOR UPDATE
                """,
                [execution[2], execution[4]],
            )
            attempt = uow.cursor.fetchone()
        if execution[5] is not None:
            uow.cursor.execute(
                """
                SELECT lease_id,status,worker_id,fencing_token,
                       lease_expires_at>clock_timestamp()
                FROM authority_runtime_job_lease
                WHERE runtime_job_id=%s AND attempt_id=%s AND lease_id=%s
                FOR UPDATE
                """,
                [execution[2], execution[4], execution[5]],
            )
            lease = uow.cursor.fetchone()
        if str(run["lifecycle"]) == "ADMITTED":
            valid = (
                str(execution[3]) == "SCHEDULED"
                and all(value is None for value in execution[4:8])
                and str(job[1]) == "READY"
                and job[2] is None
                and int(job[3] or 0) == 0
                and str(job[4] or "") == ""
                and int(job[5]) == 0
                and attempt is None
                and lease is None
            )
        else:
            valid = (
                str(execution[3]) in {"FAILED", "LOST", "ABORTED"}
                and str(job[1]) in {"FAILED", "DEAD_LETTER", "CANCELLED"}
                and (
                    attempt is None
                    or str(attempt[1]) in {"FAILED", "ABANDONED", "SUCCEEDED"}
                )
                and (
                    lease is None or str(lease[1]) in {"RELEASED", "EXPIRED", "REVOKED"}
                )
            )
        if not valid:
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_LIVE_EXECUTION",
                "legacy budget reconciliation cannot run with a valid live holder or nonterminal chain",
            )
        return {
            "opening_execution_id": str(execution[0]),
            "opening_execution_generation": int(execution[1]),
            "runtime_job_id": str(execution[2]),
            "runtime_attempt_id": str(execution[4] or ""),
            "runtime_lease_id": str(execution[5] or ""),
            "runtime_worker_id": str(execution[6] or ""),
            "runtime_fencing_token": int(execution[7] or 0),
        }

    @staticmethod
    def _bind_legacy_budget_operations_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        run: Mapping[str, Any],
        execution_binding: Mapping[str, Any],
        scope: Mapping[str, Any],
        operation_ids: tuple[str, ...],
        bound_by_operation_id: str,
    ) -> list[dict[str, Any]]:
        if not operation_ids:
            return []
        if not all(
            (
                execution_binding.get("runtime_attempt_id"),
                execution_binding.get("runtime_lease_id"),
                execution_binding.get("runtime_worker_id"),
                int(execution_binding.get("runtime_fencing_token") or 0) > 0,
            )
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_RECONCILIATION_EXECUTION_REQUIRED",
                "historical Provider work requires an exact terminal execution fence",
            )
        bound: list[dict[str, Any]] = []
        for legacy_operation_id in sorted(operation_ids):
            uow.cursor.execute(
                """
                WITH RECURSIVE ancestry AS (
                    SELECT operation_id,project_id,causation_operation_id,
                           parent_operation_id,ARRAY[operation_id]::TEXT[] path
                    FROM authority_operation WHERE operation_id=%s
                    UNION ALL
                    SELECT parent.operation_id,parent.project_id,
                           parent.causation_operation_id,parent.parent_operation_id,
                           ancestry.path || parent.operation_id
                    FROM ancestry
                    CROSS JOIN LATERAL (
                        VALUES (ancestry.causation_operation_id),
                               (ancestry.parent_operation_id)
                    ) edge(operation_id)
                    JOIN authority_operation parent
                      ON parent.operation_id=edge.operation_id
                    WHERE edge.operation_id IS NOT NULL
                      AND cardinality(ancestry.path)<33
                      AND NOT parent.operation_id=ANY(ancestry.path)
                )
                SELECT bool_and(project_id=%s),bool_or(operation_id=%s)
                FROM ancestry
                """,
                [
                    legacy_operation_id,
                    run["project_id"],
                    run["root_operation_id"],
                ],
            )
            authority = uow.cursor.fetchone()
            if authority is None or not bool(authority[0]) or not bool(authority[1]):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_SCOPE_CONFLICT",
                    "legacy Operation is not causally owned by this Book Opening",
                )
            uow.cursor.execute(
                "SELECT project_id FROM authority_operation WHERE operation_id=%s FOR KEY SHARE",
                [legacy_operation_id],
            )
            if uow.cursor.fetchone() is None:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_SCOPE_CONFLICT",
                    "legacy Operation is missing",
                )
            binding_id = deterministic_budget_operation_binding_id(
                operation_id=legacy_operation_id,
                opening_execution_id=str(execution_binding["opening_execution_id"]),
                opening_execution_generation=int(
                    execution_binding["opening_execution_generation"]
                ),
                runtime_attempt_id=str(execution_binding["runtime_attempt_id"]),
                runtime_fencing_token=int(execution_binding["runtime_fencing_token"]),
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_budget_operation_binding(
                    operation_budget_binding_id,operation_id,opening_run_id,
                    project_id,budget_scope_id,budget_scope_revision,
                    opening_execution_id,opening_execution_generation,
                    runtime_job_id,runtime_attempt_id,runtime_lease_id,
                    runtime_worker_id,runtime_fencing_token,binding_source,
                    bound_by_operation_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          'LEGACY_RECONCILIATION',%s)
                ON CONFLICT DO NOTHING
                """,
                [
                    binding_id,
                    legacy_operation_id,
                    run["opening_run_id"],
                    run["project_id"],
                    scope["budget_scope_id"],
                    scope["revision"],
                    execution_binding["opening_execution_id"],
                    execution_binding["opening_execution_generation"],
                    execution_binding["runtime_job_id"],
                    execution_binding["runtime_attempt_id"],
                    execution_binding["runtime_lease_id"],
                    execution_binding["runtime_worker_id"],
                    execution_binding["runtime_fencing_token"],
                    bound_by_operation_id,
                ],
            )
            bound.append(
                {
                    "operation_id": legacy_operation_id,
                    "operation_budget_binding_id": binding_id,
                }
            )
        return bound

    @staticmethod
    def _prepare_legacy_budget_reservation_attributions_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        run: Mapping[str, Any],
        scope: Mapping[str, Any],
        operation_ids: tuple[str, ...],
        reservation_ids: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        operation_set = set(operation_ids)
        attributions: list[dict[str, Any]] = []
        for reservation_id in sorted(reservation_ids):
            uow.cursor.execute(
                """
                SELECT operation_id,external_effect_id,project_id
                FROM authority_budget_reservation
                WHERE reservation_id=%s
                """,
                [reservation_id],
            )
            reservation_identity = uow.cursor.fetchone()
            if (
                reservation_identity is None
                or str(reservation_identity[0]) not in operation_set
                or str(reservation_identity[2]) != str(run["project_id"])
            ):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_RESERVATION_MISSING",
                    "legacy BudgetReservation is missing or outside its listed Operation set",
                )
            uow.cursor.execute(
                """
                SELECT 1 FROM authority_external_effect
                WHERE external_effect_id=%s AND operation_id=%s
                  AND project_id=%s FOR KEY SHARE
                """,
                [
                    reservation_identity[1],
                    reservation_identity[0],
                    run["project_id"],
                ],
            )
            if uow.cursor.fetchone() is None:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_SCOPE_CONFLICT",
                    "legacy BudgetReservation ExternalEffect is missing",
                )
            uow.cursor.execute(
                """
                SELECT reservation_id,operation_id,external_effect_id,project_id,
                       stable_idempotency_key,provider,chapter,currency,
                       estimated_amount,reserved_amount,settled_amount,
                       estimated_tokens,actual_tokens,status,caps,evidence,
                       budget_timezone,budget_scope_id,budget_scope_revision,
                       budget_breach,version
                FROM authority_budget_reservation
                WHERE reservation_id=%s AND project_id=%s
                FOR UPDATE
                """,
                [reservation_id, run["project_id"]],
            )
            row = uow.cursor.fetchone()
            columns = (
                "reservation_id",
                "operation_id",
                "external_effect_id",
                "project_id",
                "stable_idempotency_key",
                "provider",
                "chapter",
                "currency",
                "estimated_amount",
                "reserved_amount",
                "settled_amount",
                "estimated_tokens",
                "actual_tokens",
                "status",
                "caps",
                "evidence",
                "budget_timezone",
                "budget_scope_id",
                "budget_scope_revision",
                "budget_breach",
                "version",
            )
            if row is None:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_RESERVATION_MISSING",
                    "legacy BudgetReservation is missing",
                )
            reservation = dict(zip(columns, row, strict=True))
            if (
                str(reservation["operation_id"]) not in operation_set
                or reservation["budget_scope_id"] is not None
                or reservation["budget_scope_revision"] is not None
            ):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_SCOPE_CONFLICT",
                    "legacy BudgetReservation is not an unbound listed Operation cost",
                )
            if str(reservation["status"]) not in {
                "SETTLED",
                "RELEASED",
                "REJECTED",
            }:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_RESERVATION_NOT_TERMINAL",
                    "legacy reservation must be formally terminal before attribution",
                )
            if str(reservation["operation_id"]) != str(reservation_identity[0]) or str(
                reservation["external_effect_id"]
            ) != str(reservation_identity[1]):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_SCOPE_CONFLICT",
                    "legacy BudgetReservation identity changed while acquiring locks",
                )
            snapshot = canonical_budget_reservation_snapshot(reservation)
            snapshot_hash = str(snapshot.pop("snapshot_hash"))
            cost_evidence_id = ""
            cost_evidence_version: int | None = None
            cost_evidence_hash = ""
            if str(reservation["status"]) == "SETTLED":
                cost_evidence_id = f"budget-cost:{reservation_id}"
                uow.cursor.execute(
                    """
                    SELECT cost_evidence_id,operation_id,provider,model,amount,
                           currency,evidence
                    FROM authority_operation_cost_evidence
                    WHERE cost_evidence_id=%s AND operation_id=%s
                    FOR KEY SHARE
                    """,
                    [cost_evidence_id, reservation["operation_id"]],
                )
                cost = uow.cursor.fetchone()
                if cost is None:
                    raise KernelError(
                        "BOOK_OPENING_BUDGET_RECONCILIATION_EVIDENCE_MISSING",
                        "settled legacy reservation lacks immutable cost evidence",
                    )
                cost_evidence_version = 0
                cost_evidence_hash = _canonical_hash(
                    {
                        "cost_evidence_id": str(cost[0]),
                        "operation_id": str(cost[1]),
                        "provider": str(cost[2]),
                        "model": str(cost[3]),
                        "amount": format(cost[4].normalize(), "f"),
                        "currency": str(cost[5]),
                        "evidence": dict(cost[6] or {}),
                    }
                )
            attributions.append(
                {
                    "legacy_budget_attribution_id": _stable_id(
                        "legacy-budget-attribution",
                        str(run["opening_run_id"]),
                        reservation_id,
                        str(scope["budget_scope_id"]),
                    ),
                    "reservation_id": reservation_id,
                    "operation_id": str(reservation["operation_id"]),
                    "external_effect_id": str(reservation["external_effect_id"]),
                    "reservation_version": int(reservation["version"]),
                    "reservation_status": str(reservation["status"]),
                    "reservation_snapshot": snapshot,
                    "reservation_snapshot_hash": snapshot_hash,
                    "cost_evidence_id": cost_evidence_id,
                    "cost_evidence_version": cost_evidence_version,
                    "cost_evidence_hash": cost_evidence_hash,
                }
            )
        return attributions

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
        """Atomically activate Runtime, Opening, and semantic replacement work."""

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
                SELECT lifecycle,current_execution_id,current_execution_generation,
                       frozen_request_digest,root_operation_id,project_id,
                       recovery_state
                FROM authority_book_opening_run
                WHERE opening_run_id=%s AND version=%s
                FOR UPDATE
                """,
                [opening_run_id, expected_version],
            )
            opening = uow.cursor.fetchone()
            if (
                opening is None
                or str(opening[0]) not in {"ADMITTED", "RUNNING"}
                or not str(opening[1] or "")
                or int(opening[2] or 0) <= 0
            ):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                    "Book Opening has no current executable generation",
                )
            uow.cursor.execute(
                """
                SELECT lifecycle,version,runtime_job_id,input_snapshot_hash,
                       frozen_request_digest,policy_snapshot_hash,
                       authority_contract_hash,current_attempt_id,
                       current_lease_id,current_worker_id,current_fencing_token,
                       recovery_intent_id
                FROM authority_book_opening_execution
                WHERE opening_run_id=%s AND opening_execution_id=%s
                  AND generation=%s
                FOR UPDATE
                """,
                [opening_run_id, str(opening[1]), int(opening[2])],
            )
            execution = uow.cursor.fetchone()
            if (
                execution is None
                or str(execution[0]) not in {"BOUND", "RUNNING"}
                or str(execution[2]) != runtime_claim.runtime_job_id
                or str(execution[4]) != str(opening[3])
                or str(execution[5]) != self.recovery._execution_policy_digest()
                or str(execution[6]) != self.recovery._authority_digest()
                or str(execution[7]) != runtime_claim.attempt_id
                or str(execution[8]) != runtime_claim.lease_id
                or str(execution[9]) != runtime_claim.worker_id
                or int(execution[10] or 0) != runtime_claim.fencing_token
            ):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                    "OpeningExecution does not bind the exact Runtime claim",
                )
            self.runtime_jobs.start_authority_owned_in_uow(uow, runtime_claim)
            uow.cursor.execute(
                """
                SELECT job.input_hash,job.input_snapshot,job.status,
                       job.current_attempt_id,job.current_fencing_token,
                       job.lease_loss_policy,job.claimed_by,
                       attempt.status,attempt.worker_id,attempt.lease_id,
                       attempt.fencing_token,lease.status,lease.worker_id,
                       lease.fencing_token,
                       lease.lease_expires_at>clock_timestamp()
                FROM authority_runtime_job AS job
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.attempt_id=attempt.attempt_id
                 AND lease.lease_id=attempt.lease_id
                WHERE job.runtime_job_id=%s
                """,
                [runtime_claim.runtime_job_id],
            )
            runtime = uow.cursor.fetchone()
            if (
                runtime is None
                or str(runtime[0]) != str(execution[3])
                or dict(runtime[1] or {}) != dict(runtime_claim.input_snapshot)
                or str(runtime[2]) not in {"RUNNING", "CHECKPOINTED"}
                or str(runtime[3]) != runtime_claim.attempt_id
                or int(runtime[4]) != runtime_claim.fencing_token
                or str(runtime[5]) != AUTHORITY_CONVERGENCE_REQUIRED
                or str(runtime[6]) != runtime_claim.worker_id
                or str(runtime[7]) not in {"RUNNING", "CHECKPOINTED"}
                or str(runtime[8]) != runtime_claim.worker_id
                or str(runtime[9]) != runtime_claim.lease_id
                or int(runtime[10]) != runtime_claim.fencing_token
                or str(runtime[11]) != "HELD"
                or str(runtime[12]) != runtime_claim.worker_id
                or int(runtime[13]) != runtime_claim.fencing_token
            ):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                    "RuntimeJob/Attempt/Lease differs from the current Opening fence",
                )
            if not bool(runtime[14]):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_LEASE_EXPIRED",
                    "Opening execution lease expired before atomic activation",
                )
            if str(execution[0]) == "BOUND":
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
                        str(opening[1]),
                        int(execution[1]),
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
                [opening_run_id, expected_version, str(opening[1]), int(opening[2])],
            )
            if uow.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_CONFLICT",
                    "Book Opening changed while its execution was bound",
                )
            semantic = dict(runtime_claim.input_snapshot)
            if "semantic_execution_mode" not in semantic:
                if int(opening[2]) != 1 or str(execution[11] or ""):
                    raise KernelError(
                        "BOOK_OPENING_SEMANTIC_BINDING_RECONCILIATION_REQUIRED",
                        "legacy semantic binding is allowed only for generation one",
                    )
                semantic_mode = "NONE"
            else:
                semantic_mode = str(semantic.get("semantic_execution_mode") or "")
            semantic_operation_id = str(
                semantic.get("semantic_evaluation_operation_id") or ""
            )
            semantic_execution_id = str(
                semantic.get("semantic_evaluation_execution_id") or ""
            )
            semantic_generation = int(
                semantic.get("semantic_evaluation_generation") or 0
            )
            if semantic_mode == "NONE":
                if (
                    semantic_operation_id
                    or semantic_execution_id
                    or semantic_generation != 0
                ):
                    raise KernelError(
                        "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                        "NONE semantic mode carries executable Evaluation identity",
                    )
            elif semantic_mode in {"NEW_REPLACEMENT", "RESUME_CURRENT"}:
                if (
                    not semantic_operation_id
                    or not semantic_execution_id
                    or semantic_generation <= 0
                ):
                    raise KernelError(
                        "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                        "semantic execution binding is incomplete",
                    )
                if semantic_mode == "NEW_REPLACEMENT":
                    if self.recovery.semantic_replacement is None:
                        raise KernelError(
                            "BOOK_OPENING_REPLACEMENT_RUNTIME_REQUIRED",
                            "replacement release requires Story Design Authority",
                        )
                    uow.cursor.execute(
                        "SELECT actor_id FROM authority_operation "
                        "WHERE operation_id=%s AND project_id=%s",
                        [semantic_operation_id, str(opening[5])],
                    )
                    semantic_actor = uow.cursor.fetchone()
                    if semantic_actor is None or not str(execution[11] or ""):
                        raise KernelError(
                            "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                            "replacement lineage is not bound to this execution",
                        )
                    self.recovery.semantic_replacement.release_replacement_in_uow(
                        uow,
                        operation_id=semantic_operation_id,
                        recovery_intent_id=str(execution[11]),
                        actor_id=str(semantic_actor[0]),
                        trace_id=(f"trace:{opening_run_id}:activation:{opening[2]}"),
                        correlation_id=str(opening[4]),
                        causation_id=str(execution[11]),
                    )
                else:
                    uow.cursor.execute(
                        "SELECT authority_narrative_replacement_gate_is_open(%s,%s)",
                        [semantic_operation_id, str(opening[5])],
                    )
                    gate = uow.cursor.fetchone()
                    if gate is None or not bool(gate[0]):
                        raise KernelError(
                            "NARRATIVE_EVALUATION_REPLACEMENT_EXECUTION_GATE_CLOSED",
                            "resumed semantic Evaluation lacks a live outer execution",
                        )
            else:
                raise KernelError(
                    "BOOK_OPENING_SEMANTIC_BINDING_INVALID",
                    "RuntimeJob carries an unknown semantic execution mode",
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
        opening_run_id: str = "",
        runtime_claim: RuntimeJobClaim | None = None,
        progress: Mapping[str, Mapping[str, Any]] | None = None,
        execution_probe: Callable[[], object] | None = None,
    ):
        opening_execution_binding: dict[str, Any] | None = None
        if opening_run_id:
            if runtime_claim is None:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_REQUIRED",
                    "Planning generation requires the exact Opening Runtime claim",
                )
            if str(runtime_claim.input_snapshot.get("opening_run_id") or "") != (
                opening_run_id
            ):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                    "Planning generation Runtime claim belongs to another Opening",
                )
            opening_execution_binding = {
                "opening_run_id": opening_run_id,
                "opening_execution_id": str(
                    runtime_claim.input_snapshot.get("opening_execution_id") or ""
                ),
                "opening_execution_generation": int(
                    runtime_claim.input_snapshot.get("execution_generation") or 0
                ),
                "runtime_job_id": runtime_claim.runtime_job_id,
                "runtime_attempt_id": runtime_claim.attempt_id,
                "runtime_lease_id": runtime_claim.lease_id,
                "runtime_worker_id": runtime_claim.worker_id,
                "runtime_fencing_token": runtime_claim.fencing_token,
            }
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
            opening_execution_binding=opening_execution_binding,
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
        qualified_branch_committer = None
        if opening_run_id:
            if runtime_claim is None or opening_execution_binding is None:
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_REQUIRED",
                    "Planning branch checkpoint requires the exact Runtime claim",
                )

            def commit_qualified_branch(*, search_id, branch_key, result):
                def commit_in_uow(uow):
                    try:
                        return self.narrative_search.register_qualified_branch_in_uow(
                            uow,
                            search_id=search_id,
                            branch_key=branch_key,
                            result=result,
                        )
                    except KernelError as exc:
                        if (
                            exc.code
                            != "NARRATIVE_SEARCH_BRANCH_RECONCILIATION_REQUIRED"
                        ):
                            raise
                    return (
                        self.narrative_search.reconcile_legacy_qualified_branch_in_uow(
                            uow,
                            search_id=search_id,
                            branch_key=branch_key,
                            result=result,
                            opening_run_id=opening_run_id,
                            opening_execution_id=str(
                                opening_execution_binding["opening_execution_id"]
                            ),
                            execution_generation=int(
                                opening_execution_binding[
                                    "opening_execution_generation"
                                ]
                            ),
                        )
                    )

                return self.recovery.commit_execution_narrative_search_branch(
                    opening_run_id,
                    runtime_claim=runtime_claim,
                    search_id=search_id,
                    branch_key=branch_key,
                    branch_committer=commit_in_uow,
                )

            qualified_branch_committer = commit_qualified_branch
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
            search_id = str(checkpoint.get("evidence_id") or "")
            branches = self.narrative_search.require_qualified_branches(
                search_id,
                expected_branch_keys=tuple(
                    f"future-{ordinal}"
                    for ordinal in range(
                        1,
                        len(search_request.strategy_directives) + 1,
                    )
                ),
                project_id=request.project_id,
            )
            for branch in branches:
                branch_key = branch.branch_key
                branch_work_key = f"narrative-search-branch:{search_id}:{branch_key}"
                branch_checkpoint = dict((progress or {}).get(branch_work_key) or {})
                if branch_checkpoint:
                    if (
                        str(branch_checkpoint.get("owning_authority"))
                        != "STORY_PLANNING"
                        or str(branch_checkpoint.get("evidence_type"))
                        != branch.evidence_type
                        or str(branch_checkpoint.get("evidence_id") or "")
                        != branch.evidence_id
                        or int(branch_checkpoint.get("evidence_version") or 0)
                        != branch.evidence_version
                        or str(branch_checkpoint.get("evidence_hash") or "")
                        != branch.evidence_hash
                    ):
                        raise KernelError(
                            "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                            "future branch checkpoint is not Planning-owned evidence",
                        )
                    continue
                if qualified_branch_committer is None:
                    raise KernelError(
                        "BOOK_OPENING_BRANCH_CHECKPOINT_REQUIRED",
                        "whole-search replay cannot bypass a future branch checkpoint",
                    )
                qualified_branch_committer(
                    search_id=search_id,
                    branch_key=branch_key,
                    result=branch.result,
                )
            resumed = self.narrative_search.require_selected(
                search_request,
                activate_selected=True,
                allow_reconciled_branches=True,
                opening_run_id=opening_run_id,
            )
            if resumed.search_id != search_id:
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "resumed Narrative Search differs from the checkpoint cursor",
                )
            return resumed
        explore_options: dict[str, Any] = {
            "principal": principal,
            "activate_selected": True,
            "execution_probe": execution_probe,
        }
        if qualified_branch_committer is not None:
            explore_options["qualified_branch_committer"] = qualified_branch_committer
        return self.narrative_search.explore(search_request, **explore_options)

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
    required_outbox_event = (
        "book.opening.legacy_budget_reconciled"
        if name == "book.opening.reconcile_legacy_budget_scope"
        else "book.opening.transitioned"
    )
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
            "required_outbox_events": [required_outbox_event],
        },
    }


__all__ = [
    "BookOpeningAdmission",
    "BookOpeningResult",
    "OpenBookProductionRequest",
    "PostgresBookOpeningApplication",
]
