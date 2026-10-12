from __future__ import annotations
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
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
    canonical_budget_policy,
    canonical_budget_reservation_snapshot,
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
    canonical_book_volume_allocation,
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
from .opening_workflow import (
    BOOK_OPENING_PROVIDER_BUDGET_POLICY_CONTRACT_VERSION,
    BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
    BookOpeningTopologyBudget,
    BookOpeningWorkflow,
    BookOpeningWorkflowNode,
    BookOpeningWorkflowNodeKind,
    BookOpeningWorkflowResult,
    assess_book_opening_topology_budget,
    build_book_opening_workflow,
)
from .recovery import (
    BOOK_OPENING_LEGACY_WORKFLOW_CONTRACT_VERSION,
    BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION,
    PostgresBookOpeningRecoveryApplication,
    _stable_id,
    book_opening_execution_contract_version,
    book_opening_runtime_job_identity,
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
BOOK_OPENING_WORKFLOW_DEFINITION_VERSION = "2.0.0"
BOOK_OPENING_HANDLER = "novel_forge.book_authority.opening"
BOOK_OPENING_OPERATIONS = frozenset(
    {
        "book.opening.admit",
        "book.opening.continue_unstarted",
        "book.opening.complete",
        "book.opening.complete_node",
        "book.opening.reconcile_legacy_budget_scope",
        "book.opening.resume",
        "book.opening.abort",
    }
)
BOOK_OPENING_BUDGET_POLICY_VERSION = (
    BOOK_OPENING_PROVIDER_BUDGET_POLICY_CONTRACT_VERSION
)
_BOOK_OPENING_PLANNING_INPUT_CONTROL_OPERATIONS = frozenset(
    {"book.opening.complete", "book.opening.complete_node"}
)
_BOOK_OPENING_RUNTIME_LINEAGE_CONTROL_OPERATIONS = frozenset({"book.opening.abort"})
DEFAULT_BOOK_OPENING_BUDGET_POLICY: Mapping[str, object] = {
    "execution_mode": "PROVIDER_ALLOWED",
    "provider_call_limit": 48,
    "token_limit": 4_800_000,
    "cost_limit_usd": "96",
    "per_call_token_limit": 100_000,
    "per_call_cost_limit_usd": "2",
}
DEFAULT_BOOK_OPENING_BUDGET_WINDOW_SECONDS = 3_600


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _opening_definition_version(name: str) -> str:
    return (
        BOOK_OPENING_WORKFLOW_DEFINITION_VERSION
        if name in {"book.opening.admit", "book.opening.complete_node"}
        else BOOK_OPENING_DEFINITION_VERSION
    )


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
    planning_replacement: Mapping[str, Any] | None = None

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
        if (
            not self.arc_logical_keys
            or len(set(self.arc_logical_keys)) != len(self.arc_logical_keys)
            or any(not str(item).strip() for item in self.arc_logical_keys)
        ):
            raise ValueError("Book opening requires a non-empty unique Arc portfolio")
        if (
            not self.initial_story_state_version
            or not self.initial_canon_snapshot_version
        ):
            raise ValueError(
                "Book opening requires the initial accepted Story State and Canon boundary"
            )
        if self.planning_replacement is not None:
            replacement = self.planning_replacement
            if (
                set(replacement) != {
                    "contract_version", "source_opening_run_id", "source_version",
                    "reason", "expected_active_plan_versions",
                }
                or replacement["contract_version"] != "unwritten-book-planning-replacement.v1"
                or not isinstance(replacement["source_version"], int)
                or isinstance(replacement["source_version"], bool)
                or replacement["source_version"] < 0
                or not str(replacement["source_opening_run_id"]).strip()
                or not str(replacement["reason"]).strip()
                or not isinstance(replacement["expected_active_plan_versions"], Mapping)
                or not replacement["expected_active_plan_versions"].get("book:main")
                or any(not str(key).strip() or not str(version).strip()
                       for key, version in replacement["expected_active_plan_versions"].items())
            ):
                raise ValueError("Unwritten Book planning replacement is incomplete")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["planning_input_versions"] = dict(self.planning_input_versions)
        value["arc_logical_keys"] = list(self.arc_logical_keys)
        if self.planning_replacement is None:
            value.pop("planning_replacement")
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
            set(value) not in (expected, expected | {"planning_replacement"})
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
            planning_replacement=value.get("planning_replacement"),
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


@dataclass(frozen=True, slots=True)
class BookOpeningNodeExecutionResult:
    opening_run_id: str
    workflow_node_id: str
    node_kind: str
    node_key: str
    node_receipt_id: str
    lifecycle: str
    status: str
    replayed: bool
    successor_runtime_job_id: str = ""
    book_opening_result: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "opening_run_id": self.opening_run_id,
            "workflow_node_id": self.workflow_node_id,
            "node_kind": self.node_kind,
            "node_key": self.node_key,
            "node_receipt_id": self.node_receipt_id,
            "lifecycle": self.lifecycle,
            "status": self.status,
            "replayed": self.replayed,
            "successor_runtime_job_id": self.successor_runtime_job_id,
            "book_opening_result": (
                dict(self.book_opening_result)
                if self.book_opening_result is not None
                else None
            ),
        }


class PostgresBookOpeningApplication:
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
        self.provider_budget_currency = (
            "UNKNOWN"
            if str(
                self.provider_budget_policy.get("accounting_basis") or "PRICED"
            ).upper()
            == "ACCOUNT_ENTITLEMENT"
            else "USD"
        )
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

    def _topology_budget_for_request(
        self, request: OpenBookProductionRequest
    ) -> BookOpeningTopologyBudget:
        try:
            return assess_book_opening_topology_budget(
                policy_contract_version=BOOK_OPENING_BUDGET_POLICY_VERSION,
                policy_hash=self.provider_budget_policy_hash,
                policy=self.provider_budget_policy,
                arc_count=len(request.arc_logical_keys),
            )
        except ValueError as exc:
            raise KernelError(
                "BOOK_OPENING_TOPOLOGY_BUDGET_INSUFFICIENT",
                "Provider budget cannot admit the frozen Book Opening topology",
            ) from exc

    def admit(
        self, request: OpenBookProductionRequest, *, principal: Principal
    ) -> BookOpeningAdmission:
        return self._admit(request, principal=principal)

    def reopen_unwritten(
        self, opening_run_id: str, *, expected_version: int,
        idempotency_key: str, reason: str, principal: Principal,
    ) -> BookOpeningAdmission:
        source = self.require(opening_run_id)
        principal.require("book.authority.execute", str(source["project_id"]))
        principal.require("story_planning.authority.execute", str(source["project_id"]))
        request = self._frozen_request(opening_run_id)
        if not idempotency_key.strip() or idempotency_key == request.idempotency_key:
            raise ValueError("Planning repair requires a distinct stable idempotency key")
        existing = self.find_by_key(
            project_id=request.project_id, book_id=request.book_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            frozen = self._frozen_request(str(existing["opening_run_id"]))
            replacement = frozen.planning_replacement or {}
            if (replacement.get("source_opening_run_id") != opening_run_id
                    or replacement.get("source_version") != expected_version
                    or replacement.get("reason") != reason):
                raise KernelError("BOOK_OPENING_IDEMPOTENCY_CONFLICT", "Planning repair replay differs from its frozen decision")
            return self.admit(frozen, principal=principal)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute("SELECT version FROM authority_book WHERE project_id=%s AND book_id=%s", [request.project_id, request.book_id])
            book = uow.cursor.fetchone()
            if book is None:
                raise KernelError("BOOK_NOT_FOUND", "Planning repair requires its existing Book")
            versions = self._unwritten_replacement_versions_in_uow(
                uow.cursor, request=request, source_opening_run_id=opening_run_id,
                source_version=expected_version,
            )
        return self.admit(replace(
            request, expected_book_version=int(book[0]), idempotency_key=idempotency_key,
            trace_id=f"trace:{opening_run_id}:planning-repair",
            planning_replacement={
                "contract_version": "unwritten-book-planning-replacement.v1",
                "source_opening_run_id": opening_run_id, "source_version": expected_version,
                "reason": reason, "expected_active_plan_versions": versions,
            },
        ), principal=principal)

    @staticmethod
    def _unwritten_replacement_versions_in_uow(
        cursor: Any, *, request: OpenBookProductionRequest,
        source_opening_run_id: str, source_version: int,
    ) -> dict[str, str]:
        cursor.execute("""SELECT project_id,workspace_id,book_id,lifecycle,version,frozen_request
            FROM authority_book_opening_run WHERE opening_run_id=%s FOR UPDATE""", [source_opening_run_id])
        source = cursor.fetchone()
        if source is None or tuple(source[:5]) != (
            request.project_id, request.workspace_id, request.book_id, "ABORTED", source_version,
        ):
            raise KernelError("BOOK_OPENING_REPLACEMENT_SOURCE_INVALID", "Planning repair requires the exact aborted same-Book Opening")
        previous = OpenBookProductionRequest.from_mapping(source[5])
        if any(getattr(previous, field) != getattr(request, field) for field in (
            "actor_id", "production_profile", "planning_input_versions", "arc_logical_keys",
            "initial_story_state_version", "initial_canon_snapshot_version",
        )):
            raise KernelError("BOOK_OPENING_REPLACEMENT_INPUT_DRIFT", "Planning repair must retain Foundation, profile and initial state")
        cursor.execute("SELECT book_run_id FROM authority_book_production WHERE project_id=%s AND book_id=%s FOR UPDATE", [request.project_id, request.book_id])
        if cursor.fetchone() is not None:
            raise KernelError("BOOK_OPENING_REPLAN_REQUIRED", "A BookRun requires governed Plan Change rather than unwritten repair")
        cursor.execute("""SELECT operation_id FROM authority_operation
            WHERE project_id=%s AND workspace_id=%s AND definition_name='story_planning.generate'
              AND command_payload#>>'{payload,book_id}'=%s
              AND status IN ('EXECUTING','WAITING_EXTERNAL_RESULT','CANCELLATION_REQUESTED') LIMIT 1""", [request.project_id, request.workspace_id, request.book_id])
        if cursor.fetchone() is not None:
            raise KernelError("BOOK_OPENING_REPLACEMENT_EXECUTION_UNSETTLED", "Stop prior live Planning work before planning repair")
        cursor.execute("""SELECT effect.external_effect_id FROM authority_external_effect effect
            JOIN authority_operation operation USING(operation_id)
            WHERE effect.project_id=%s AND operation.workspace_id=%s
              AND COALESCE(operation.command_payload#>>'{payload,book_id}',operation.command_payload->>'book_id')=%s
              AND effect.effect_type='model.invoke'
              AND effect.status NOT IN ('SUCCEEDED','FAILED_FINAL','CANCELLED')
              AND NOT authority_generation_isolated(effect.external_effect_id)
            LIMIT 1""", [request.project_id, request.workspace_id, request.book_id])
        if cursor.fetchone() is not None:
            raise KernelError("BOOK_OPENING_REPLACEMENT_EXECUTION_UNSETTLED", "Settle or natively isolate prior model work before planning repair")
        cursor.execute("""SELECT active.logical_key,active.asset_version_id,binding.execution_scope,
                COALESCE(operation.command_payload#>>'{payload,opening_execution_binding,opening_run_id}',
                         operation.command_payload#>>'{opening_execution_binding,opening_run_id}')
            FROM active_story_plan_version active
            JOIN story_plan_binding binding USING(binding_id)
            LEFT JOIN authority_story_planning_candidate candidate ON candidate.candidate_asset_version_id=active.asset_version_id
            LEFT JOIN authority_story_planning_generation generation USING(generation_id)
            LEFT JOIN authority_operation operation ON operation.operation_id=generation.operation_id
            WHERE active.project_id=%s AND active.book_id=%s
            ORDER BY active.logical_key FOR UPDATE OF active,binding""", [request.project_id, request.book_id])
        rows = cursor.fetchall()
        if not rows or any(row[2] != "PLANNED" or row[3] != source_opening_run_id for row in rows):
            raise KernelError("BOOK_OPENING_REPLACEMENT_SCOPE_INVALID", "Only the aborted Opening's unexecuted native plans may be replaced")
        return {str(row[0]): str(row[1]) for row in rows}

    def continue_unstarted_with_budget(
        self, opening_run_id: str, *, expected_version: int,
        reason: str, principal: Principal,
    ) -> BookOpeningAdmission:
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
            raise KernelError("BOOK_OPENING_CONTINUATION_INVALID", "expected_version must be a non-negative integer")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Opening capacity continuation requires a reason")
        source = self.require(opening_run_id)
        principal.require("book.authority.execute", str(source["project_id"]))
        request = self._frozen_request(opening_run_id)
        key = _stable_id("opening-capacity-continuation", opening_run_id, self.provider_budget_policy_hash, expected_version, reason)
        return self._admit(
            replace(request, idempotency_key=key), principal=principal,
            continuation={"source_opening_run_id": opening_run_id,
                          "source_root_operation_id": source["root_operation_id"],
                          "expected_version": expected_version, "reason": reason},
        )

    def _admit(
        self, request: OpenBookProductionRequest, *, principal: Principal,
        continuation: Mapping[str, Any] | None = None,
    ) -> BookOpeningAdmission:

        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        if principal.principal_id != request.actor_id:
            raise KernelError(
                "ACTOR_IDENTITY_INVALID",
                "Book opening actor differs from authenticated Principal",
            )
        self._require_canonical_opening_inputs(request)
        self._register_definitions()
        identity = "\x00".join(
            (request.project_id, request.book_id, request.idempotency_key)
        ).encode("utf-8")
        opening_run_id = "book-opening:" + hashlib.sha256(identity).hexdigest()
        frozen_request = request.to_dict()
        frozen_request_digest = _canonical_hash(frozen_request)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT project_id,workspace_id,book_id,root_operation_id,
                       frozen_request_digest
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            existing = uow.cursor.fetchone()
        if existing is not None:
            if (
                tuple(str(value) for value in existing[:3])
                != (
                    request.project_id,
                    request.workspace_id,
                    request.book_id,
                )
                or str(existing[4]) != frozen_request_digest
            ):
                raise KernelError(
                    "BOOK_OPENING_IDEMPOTENCY_CONFLICT",
                    "Book Opening idempotency identity belongs to another frozen request",
                )
            if continuation is not None:
                with AuthorityUnitOfWork(self.database_url) as uow:
                    uow.cursor.execute("SELECT evidence->'request' FROM authority_book_opening_capacity_continuation WHERE successor_opening_run_id=%s", [opening_run_id])
                    recorded = uow.cursor.fetchone()
                if recorded is None or recorded[0] != dict(continuation):
                    raise KernelError("BOOK_OPENING_CONTINUATION_CONFLICT", "Opening continuation replay differs from its immutable decision")
            run = self.require(opening_run_id)
            job = self._admission_job(opening_run_id)
            return BookOpeningAdmission(
                opening_run_id=opening_run_id,
                root_operation_id=str(existing[3]),
                runtime_job_id=str(job["runtime_job_id"]),
                lifecycle=str(run["lifecycle"]),
                replayed=True,
            )
        topology_budget = self._topology_budget_for_request(request)
        definition_name = "book.opening.continue_unstarted" if continuation else "book.opening.admit"
        executed = execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": _opening_definition_version(definition_name),
                "project_id": request.project_id,
                "workspace_id": request.workspace_id,
                "book_id": request.book_id,
                "actor_id": request.actor_id,
                "idempotency_scope": "book:opening",
                "idempotency_key": request.idempotency_key,
                "trace_id": request.trace_id,
                "span_id": str(uuid4()),
                "correlation_id": request.correlation_id,
                "causation_id": str((continuation or {}).get("source_root_operation_id") or ""),
                **({"causation_operation_id": continuation["source_root_operation_id"]} if continuation else {}),
                "input": {
                    "project_id": request.project_id,
                    "book_id": request.book_id,
                    "opening_run_id": opening_run_id,
                    "frozen_request": frozen_request,
                    "frozen_request_digest": frozen_request_digest,
                    **({"capacity_continuation": dict(continuation)} if continuation else {}),
                    "provider_budget_contract": {
                        "policy_contract_version": (BOOK_OPENING_BUDGET_POLICY_VERSION),
                        "policy_snapshot": dict(self.provider_budget_policy),
                        "policy_hash": self.provider_budget_policy_hash,
                        "currency": self.provider_budget_currency,
                        "budget_timezone": "UTC",
                        "window_seconds": self.provider_budget_window_seconds,
                        "opening_topology_budget": topology_budget.to_dict(),
                    },
                },
                "input_assets": self._opening_input_assets(request),
            },
            context=self._context(request.actor_id),
            handler=self._execute_transaction,
        )
        run = self.require(opening_run_id)
        job = self._admission_job(opening_run_id)
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

    def find_by_key(
        self, *, project_id: str, book_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        identity = "\x00".join((project_id, book_id, idempotency_key)).encode("utf-8")
        try:
            return self.require("book-opening:" + hashlib.sha256(identity).hexdigest())
        except KernelError as error:
            if error.code != "BOOK_OPENING_NOT_FOUND":
                raise
            return None

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
                       budget_contract_state,workflow_contract_version,
                       current_workflow_node_id,workflow_graph_revision,
                       workflow_graph_hash
                FROM authority_book_opening_run
                WHERE opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book opening run is missing")
        projection = dict(
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
                    "workflow_contract_version",
                    "current_workflow_node_id",
                    "workflow_graph_revision",
                    "workflow_graph_hash",
                ),
                row,
                strict=True,
            )
        )
        if (
            projection["workflow_contract_version"]
            == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
            and projection["lifecycle"] == "COMPLETE"
        ):
            if not isinstance(projection["result"], Mapping):
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_RESULT_INVALID",
                    "completed workflow Opening has no typed result",
                )
            try:
                projection["result"] = BookOpeningWorkflowResult.from_mapping(
                    projection["result"]
                ).to_dict()
            except ValueError as exc:
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_RESULT_INVALID",
                    "completed workflow Opening result violates its typed contract",
                ) from exc
        return projection

    def require_progress(self, opening_run_id: str) -> dict[str, Any]:

        from .opening_progress import PostgresBookOpeningWorkflowProgressQuery

        return (
            PostgresBookOpeningWorkflowProgressQuery(self.database_url)
            .progress(opening_run_id=opening_run_id)
            .to_dict()
        )

    def claim_next_node_execution(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        project_id: str = "",
        expected_opening_run_id: str = "",
        expected_runtime_job_id: str = "",
    ) -> RuntimeJobClaim | None:

        return self._claim_next_execution_for_contract(
            workflow_contract_version=BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            project_id=project_id,
            expected_opening_run_id=expected_opening_run_id,
            expected_runtime_job_id=expected_runtime_job_id,
        )

    def claim_next_legacy_execution(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        project_id: str = "",
        expected_opening_run_id: str = "",
        expected_runtime_job_id: str = "",
    ) -> RuntimeJobClaim | None:
        """COMPATIBILITY: Drain one explicitly selected legacy-monolithic-v2 execution.

        This seam is intentionally separate from the workflow-node worker loop.
        It exists only while admitted or recovered v2 RuntimeJobs are drained;
        its exact contract identity cannot claim workflow-v1/v3 node work.
        """
        return self._claim_next_execution_for_contract(
            workflow_contract_version=BOOK_OPENING_LEGACY_WORKFLOW_CONTRACT_VERSION,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            project_id=project_id,
            expected_opening_run_id=expected_opening_run_id,
            expected_runtime_job_id=expected_runtime_job_id,
        )

    def require_node_execution_result(
        self,
        *,
        opening_run_id: str,
        workflow_node_id: str,
        opening_execution_id: str,
        execution_generation: int,
    ) -> dict[str, Any]:

        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT node.node_kind,node.node_key,receipt.node_receipt_id,
                       transition.workflow_transition_receipt_id,
                       successor.runtime_job_id,opening.lifecycle,opening.result
                FROM authority_book_opening_node_receipt AS receipt
                JOIN authority_book_opening_workflow_node AS node
                  ON node.workflow_node_id=receipt.workflow_node_id
                 AND node.opening_run_id=receipt.opening_run_id
                JOIN authority_book_opening_run AS opening
                  ON opening.opening_run_id=receipt.opening_run_id
                LEFT JOIN authority_book_opening_workflow_transition_receipt
                          AS transition
                  ON transition.source_node_receipt_id=receipt.node_receipt_id
                 AND transition.opening_run_id=receipt.opening_run_id
                LEFT JOIN authority_book_opening_execution AS successor
                  ON successor.opening_execution_id=
                     transition.successor_opening_execution_id
                 AND successor.opening_run_id=transition.opening_run_id
                 AND successor.generation=
                     transition.successor_execution_generation
                WHERE receipt.opening_run_id=%s
                  AND receipt.workflow_node_id=%s
                  AND receipt.opening_execution_id=%s
                  AND receipt.execution_generation=%s
                """,
                [
                    opening_run_id,
                    workflow_node_id,
                    opening_execution_id,
                    execution_generation,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_NODE_RESULT_NOT_FOUND",
                "workflow node has no durable completion receipt",
            )
        has_successor = bool(str(row[3] or ""))
        is_terminal_node = (
            str(row[0]) == BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT.value
        )
        if has_successor == is_terminal_node:
            raise KernelError(
                "BOOK_OPENING_NODE_RESULT_INCONSISTENT",
                "workflow node receipt has an invalid successor relationship",
            )
        lifecycle = "ADMITTED" if has_successor else "COMPLETE"
        if not has_successor and (
            str(row[5]) != "COMPLETE" or not isinstance(row[6], dict)
        ):
            raise KernelError(
                "BOOK_OPENING_NODE_RESULT_INCONSISTENT",
                "terminal workflow node has no immutable completed Opening result",
            )
        completed_result: dict[str, Any] | None = None
        if not has_successor:
            try:
                completed_result = BookOpeningWorkflowResult.from_mapping(
                    row[6]
                ).to_dict()
            except ValueError as exc:
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_RESULT_INVALID",
                    "terminal node receipt points to an invalid workflow result",
                ) from exc
        return BookOpeningNodeExecutionResult(
            opening_run_id=opening_run_id,
            workflow_node_id=workflow_node_id,
            node_kind=str(row[0]),
            node_key=str(row[1]),
            node_receipt_id=str(row[2]),
            lifecycle=lifecycle,
            status="SUCCEEDED",
            replayed=True,
            successor_runtime_job_id=str(row[4] or ""),
            book_opening_result=completed_result,
        ).to_dict()

    def claim_next_execution(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        project_id: str = "",
        expected_opening_run_id: str = "",
        expected_runtime_job_id: str = "",
    ) -> RuntimeJobClaim | None:

        return self.claim_next_node_execution(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            project_id=project_id,
            expected_opening_run_id=expected_opening_run_id,
            expected_runtime_job_id=expected_runtime_job_id,
        )

    def _claim_next_execution_for_contract(
        self,
        *,
        workflow_contract_version: str,
        worker_id: str,
        lease_seconds: int,
        project_id: str = "",
        expected_opening_run_id: str = "",
        expected_runtime_job_id: str = "",
    ) -> RuntimeJobClaim | None:

        if not worker_id or lease_seconds <= 0:
            raise ValueError("Opening claim requires worker and positive lease")
        expected_execution_contract = book_opening_execution_contract_version(
            workflow_contract_version
        )
        expected_job_kind, expected_runtime_group = book_opening_runtime_job_identity(
            workflow_contract_version
        )
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
                WHERE opening.workflow_contract_version=%s
                  AND opening.execution_contract_version=%s
                  AND opening.lifecycle='ADMITTED'
                  AND execution.lifecycle='SCHEDULED'
                  AND execution.current_attempt_id IS NULL
                  AND job.status='READY' AND job.attempt_count=0
                  AND job.current_attempt_id IS NULL
                  AND job.max_attempts=1
                  AND job.lease_loss_policy=%s
                  AND job.job_kind=%s AND job.runtime_group=%s
                  AND (%s='' OR opening.project_id=%s)
                  AND (%s='' OR opening.opening_run_id=%s)
                  AND (%s='' OR job.runtime_job_id=%s)
                ORDER BY job.priority,job.available_at,job.created_at,
                         job.runtime_job_id
                LIMIT 1
                """,
                [
                    workflow_contract_version,
                    expected_execution_contract,
                    AUTHORITY_CONVERGENCE_REQUIRED,
                    expected_job_kind,
                    expected_runtime_group,
                    project_id,
                    project_id,
                    expected_opening_run_id,
                    expected_opening_run_id,
                    expected_runtime_job_id,
                    expected_runtime_job_id,
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
                       execution.input_snapshot_hash,
                       opening.workflow_contract_version,
                       opening.current_workflow_node_id,
                       opening.workflow_graph_revision,
                       opening.workflow_graph_hash,
                       execution.workflow_node_id,
                       execution.workflow_transition_kind,
                       opening.execution_contract_version,job.job_kind,
                       job.runtime_group
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=opening.current_execution_generation
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                WHERE opening.opening_run_id=%s
                  AND opening.workflow_contract_version=%s
                  AND opening.execution_contract_version=%s
                  AND opening.lifecycle='ADMITTED'
                  AND execution.lifecycle='SCHEDULED'
                  AND execution.current_attempt_id IS NULL
                  AND job.status='READY' AND job.attempt_count=0
                  AND job.current_attempt_id IS NULL
                  AND job.max_attempts=1
                  AND job.lease_loss_policy=%s
                  AND job.job_kind=%s AND job.runtime_group=%s
                  AND (%s='' OR job.runtime_job_id=%s)
                FOR UPDATE OF opening,execution,job
                """,
                [
                    opening_run_id,
                    workflow_contract_version,
                    expected_execution_contract,
                    AUTHORITY_CONVERGENCE_REQUIRED,
                    expected_job_kind,
                    expected_runtime_group,
                    expected_runtime_job_id,
                    expected_runtime_job_id,
                ],
            )
            binding = uow.cursor.fetchone()
            if binding is None:
                return None
            if (
                str(binding[1]) != str(binding[6])
                or str(binding[7]) != self.recovery._execution_policy_digest()
                or str(binding[8])
                != self.recovery._authority_digest(expected_execution_contract)
                or str(binding[9]) != str(binding[10])
                or str(binding[17]) != expected_execution_contract
                or str(binding[18]) != expected_job_kind
                or str(binding[19]) != expected_runtime_group
                or (
                    str(binding[11] or "") == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
                    and (
                        str(binding[12] or "") != str(binding[15] or "")
                        or int(binding[13] or 0) != 1
                        or not str(binding[14] or "").startswith("sha256:")
                        or str(binding[16] or "")
                        not in {"ADMISSION", "CONTINUATION", "RECOVERY"}
                    )
                )
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
                expected_job_kind=expected_job_kind,
                expected_runtime_group=expected_runtime_group,
            )
            if str(binding[11] or "") == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION:
                claim_snapshot = dict(claim.input_snapshot)
                if (
                    str(claim_snapshot.get("workflow_node_id") or "")
                    != str(binding[12])
                    or int(claim_snapshot.get("workflow_graph_revision") or 0)
                    != int(binding[13])
                    or str(claim_snapshot.get("workflow_graph_hash") or "")
                    != str(binding[14])
                    or str(claim_snapshot.get("workflow_transition_kind") or "")
                    != str(binding[16])
                ):
                    raise KernelError(
                        "BOOK_OPENING_WORKFLOW_NODE_FENCE_STALE",
                        "RuntimeJob input differs from the current workflow node",
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
        if str(run.get("workflow_contract_version") or "") == (
            BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
        ):
            return self._execute_workflow_node(
                run=run,
                expected_version=expected_version,
                runtime_claim=runtime_claim,
                principal=principal,
                execution_probe=execution_probe,
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

    def _execute_workflow_node(
        self,
        *,
        run: Mapping[str, Any],
        expected_version: int,
        runtime_claim: RuntimeJobClaim,
        principal: Principal,
        execution_probe: Callable[[], object] | None,
    ) -> dict[str, Any]:
        opening_run_id = str(run["opening_run_id"])
        node = self._require_current_workflow_node(opening_run_id)
        claim_node_id = str(runtime_claim.input_snapshot.get("workflow_node_id") or "")
        if claim_node_id != node.workflow_node_id:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_FENCE_STALE",
                "Runtime claim belongs to another Book Opening workflow node",
            )
        request = self._frozen_request(opening_run_id)
        self._bind_running_execution(
            opening_run_id,
            expected_version=expected_version,
            runtime_claim=runtime_claim,
        )
        self._probe(execution_probe)
        node_result = self._execute_workflow_node_payload(
            request=request,
            node=node,
            principal=principal,
            opening_run_id=opening_run_id,
            runtime_claim=runtime_claim,
            execution_probe=execution_probe,
        )
        if self.fault_injector is not None:
            self.fault_injector("after_workflow_node_payload")
        self._probe(execution_probe)
        completed = self._control(
            run=dict(run),
            principal=principal,
            definition_name="book.opening.complete_node",
            idempotency_key=(
                f"{opening_run_id}:node:{node.workflow_node_id}:"
                f"{_canonical_hash(node_result)}"
            ),
            payload={
                "expected_version": expected_version,
                "workflow_node_id": node.workflow_node_id,
                "node_result": node_result,
                "runtime_claim": self._runtime_claim_payload(runtime_claim),
            },
        )
        return BookOpeningNodeExecutionResult(
            opening_run_id=opening_run_id,
            workflow_node_id=node.workflow_node_id,
            node_kind=node.kind.value,
            node_key=node.node_key,
            node_receipt_id=str(completed["node_receipt_id"]),
            lifecycle=str(completed["lifecycle"]),
            status="SUCCEEDED",
            replayed=bool(
                completed.get("semantic_replayed") or completed.get("replayed")
            ),
            successor_runtime_job_id=str(
                completed.get("successor_runtime_job_id") or ""
            ),
            book_opening_result=(
                dict(completed["book_opening_result"])
                if isinstance(completed.get("book_opening_result"), Mapping)
                else None
            ),
        ).to_dict()

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
                    "goal": "realize the selected Arc purpose, including intended continuity or change",
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

    def _execute_workflow_node_payload(
        self,
        *,
        request: OpenBookProductionRequest,
        node: BookOpeningWorkflowNode,
        principal: Principal,
        opening_run_id: str,
        runtime_claim: RuntimeJobClaim,
        execution_probe: Callable[[], object] | None,
    ) -> dict[str, Any]:
        principal.require("book.authority.execute", request.project_id)
        principal.require("story_planning.authority.execute", request.project_id)
        self._require_canonical_opening_inputs(request)
        design_version = self._require_qualified_foundation(request)
        generic = dict(request.planning_input_versions)
        if (
            set(generic) != _OPENING_INPUT_ROLES
            or generic.get("book_design") != design_version
        ):
            raise KernelError(
                "BOOK_OPENING_INPUTS_INVALID",
                "workflow node inputs differ from the qualified Foundation",
            )
        receipts = self._workflow_receipt_results(opening_run_id)
        progress = self.recovery.require_execution_progress(
            opening_run_id,
            runtime_claim=runtime_claim,
        )
        accepted_state = request.initial_story_state_version

        if node.kind is BookOpeningWorkflowNodeKind.BOOK_PLAN:
            topology_budget = self._require_current_opening_topology_budget(
                opening_run_id,
                node=node,
            )
            if topology_budget.arc_count != len(request.arc_logical_keys):
                raise KernelError(
                    "BOOK_OPENING_TOPOLOGY_BUDGET_DRIFT",
                    "frozen topology Arc count differs from the Opening request",
                )
            target_chapters = self._production_target_chapters(request)
            search = self._search(
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
                horizon={
                    "level": "BOOK",
                    "stability": "HIGH",
                    "reach": "DISTANT",
                    "target_chapters": target_chapters,
                    "opening_topology_budget": topology_budget.to_dict(),
                },
                transformation={
                    "foundation_version": design_version,
                    "goal": "establish a sustainable Book narrative architecture",
                    "required_target_chapters": target_chapters,
                },
                opening_run_id=opening_run_id,
                runtime_claim=runtime_claim,
                progress=progress,
                execution_probe=execution_probe,
            )
            evidence = self._plan_asset_evidence(
                request,
                search.selected_generation.candidate_asset_version_id,
                expected_contract_type="BOOK",
                expected_logical_key="book:main",
            )
            return {
                "search_id": search.search_id,
                "asset_version_id": evidence["asset_version_id"],
                "content_hash": evidence["content_hash"],
                "binding_id": evidence["binding_id"],
            }

        book_receipt = self._require_node_receipt_result(
            receipts,
            BookOpeningWorkflowNodeKind.BOOK_PLAN,
        )
        book_plan = str(book_receipt["asset_version_id"])
        book_evidence = self._plan_asset_evidence(
            request,
            book_plan,
            expected_contract_type="BOOK",
            expected_logical_key="book:main",
        )

        if node.kind is BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO:
            skeleton, target_chapters = self._book_volume_contract(
                dict(book_evidence["content"])
            )
            volume_versions: list[dict[str, Any]] = []
            previous_end = 0
            for ordinal in range(1, len(skeleton) + 1):
                self._probe(execution_probe)
                logical_key = f"volume:{ordinal}"
                expected_chapter_range = list(skeleton[ordinal - 1]["chapter_range"])
                search = self._search(
                    request=request,
                    principal=principal,
                    generator="volume_plan.generate",
                    logical_key=logical_key,
                    input_versions=self._stage_inputs(
                        generic,
                        "volume_plan.generate",
                        book_plan=book_plan,
                    ),
                    parent_version_id=book_plan,
                    accepted_state=accepted_state,
                    horizon={
                        "level": "VOLUME",
                        "stability": "MEDIUM_HIGH",
                        "ordinal": ordinal,
                        "chapter_range": expected_chapter_range,
                        "starts_at_chapter": expected_chapter_range[0],
                        "ends_at_chapter": expected_chapter_range[1],
                    },
                    transformation={
                        "goal": "realize one ordered Book volume transformation",
                        "volume_ordinal": ordinal,
                        "volume_skeleton_entry": skeleton[ordinal - 1],
                        "required_chapter_range": expected_chapter_range,
                    },
                    opening_run_id=opening_run_id,
                    runtime_claim=runtime_claim,
                    progress=progress,
                    execution_probe=execution_probe,
                )
                evidence = self._plan_asset_evidence(
                    request,
                    search.selected_generation.candidate_asset_version_id,
                    expected_contract_type="VOLUME",
                    expected_logical_key=logical_key,
                )
                chapter_range = self._chapter_range(dict(evidence["content"]))
                if (
                    list(chapter_range) != expected_chapter_range
                    or chapter_range[0] != previous_end + 1
                ):
                    raise KernelError(
                        "BOOK_OPENING_VOLUME_PORTFOLIO_INVALID",
                        "Volume Plan range must exactly match its frozen Book portfolio allocation",
                    )
                previous_end = chapter_range[1]
                volume_versions.append(
                    {
                        "ordinal": ordinal,
                        "logical_key": logical_key,
                        "search_id": search.search_id,
                        "asset_version_id": evidence["asset_version_id"],
                        "content_hash": evidence["content_hash"],
                        "binding_id": evidence["binding_id"],
                        "chapter_range": list(chapter_range),
                    }
                )
            if previous_end != target_chapters:
                raise KernelError(
                    "BOOK_OPENING_VOLUME_PORTFOLIO_INCOMPLETE",
                    "Volume Portfolio does not cover the activated Book Plan target",
                )
            return {
                "source_book_plan_id": book_plan,
                "source_book_plan_hash": str(book_evidence["content_hash"]),
                "volume_skeleton_hash": _canonical_hash(skeleton),
                "target_chapters": target_chapters,
                "coverage_range": [1, target_chapters],
                "volume_plan_versions": volume_versions,
            }

        volume_receipt = self._require_node_receipt_result(
            receipts,
            BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO,
        )
        portfolio = list(volume_receipt.get("volume_plan_versions") or ())
        if not portfolio:
            raise KernelError(
                "BOOK_OPENING_VOLUME_PORTFOLIO_REQUIRED",
                "current-volume selection requires the durable Volume Portfolio",
            )

        if node.kind is BookOpeningWorkflowNodeKind.CURRENT_VOLUME:
            matching = [
                dict(item)
                for item in portfolio
                if isinstance(item, Mapping)
                and list(item.get("chapter_range") or [0, 0])[0]
                <= 1
                <= list(item.get("chapter_range") or [0, 0])[1]
            ]
            if len(matching) != 1:
                raise KernelError(
                    "BOOK_OPENING_CURRENT_VOLUME_AMBIGUOUS",
                    "chapter cursor one must resolve to exactly one Volume Plan",
                )
            current = matching[0]
            evidence = self._plan_asset_evidence(
                request,
                str(current["asset_version_id"]),
                expected_contract_type="VOLUME",
                expected_logical_key=str(current["logical_key"]),
            )
            if str(evidence["content_hash"]) != str(current["content_hash"]):
                raise KernelError(
                    "BOOK_OPENING_VOLUME_PORTFOLIO_DRIFT",
                    "current Volume differs from its durable portfolio evidence",
                )
            return {
                "chapter_cursor": 1,
                "volume_portfolio_hash": _canonical_hash(portfolio),
                "current_volume_plan_version_id": str(current["asset_version_id"]),
                "current_volume_content_hash": str(current["content_hash"]),
                "chapter_range": list(current["chapter_range"]),
            }

        current_receipt = self._require_node_receipt_result(
            receipts,
            BookOpeningWorkflowNodeKind.CURRENT_VOLUME,
        )
        current_volume = str(current_receipt["current_volume_plan_version_id"])

        if node.kind is BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE:
            arc_versions: list[dict[str, Any]] = []
            portfolio_ids = [str(item["asset_version_id"]) for item in portfolio]
            arc_scope = tuple(item for item in portfolio_ids if item != current_volume)
            for arc_key in request.arc_logical_keys:
                self._probe(execution_probe)
                search = self._search(
                    request=request,
                    principal=principal,
                    generator="arc_plan.generate",
                    logical_key=arc_key,
                    input_versions=self._stage_inputs(
                        generic,
                        "arc_plan.generate",
                        book_plan=book_plan,
                        volume_plan=current_volume,
                    ),
                    parent_version_id="",
                    accepted_state=accepted_state,
                    horizon={
                        "level": "ARC",
                        "stability": "MEDIUM",
                        "current_volume_plan_version_id": current_volume,
                    },
                    transformation={
                        "goal": "realize the selected Arc purpose, including intended continuity or change",
                        "arc_key": arc_key,
                    },
                    arc_scope_volume_plan_version_ids=arc_scope,
                    opening_run_id=opening_run_id,
                    runtime_claim=runtime_claim,
                    progress=progress,
                    execution_probe=execution_probe,
                )
                evidence = self._plan_asset_evidence(
                    request,
                    search.selected_generation.candidate_asset_version_id,
                    expected_contract_type="ARC",
                    expected_logical_key=arc_key,
                )
                arc_versions.append(
                    {
                        "logical_key": arc_key,
                        "search_id": search.search_id,
                        "asset_version_id": evidence["asset_version_id"],
                        "content_hash": evidence["content_hash"],
                        "binding_id": evidence["binding_id"],
                    }
                )
            return {
                "current_volume_plan_version_id": current_volume,
                "volume_portfolio_plan_version_ids": portfolio_ids,
                "arc_scope_hash": _canonical_hash(
                    {
                        "arc_logical_keys": list(request.arc_logical_keys),
                        "current_volume_plan_version_id": current_volume,
                        "volume_portfolio_plan_version_ids": portfolio_ids,
                    }
                ),
                "arc_plan_versions": arc_versions,
                "current_relevant_arc_plan_version_ids": [
                    str(item["asset_version_id"]) for item in arc_versions
                ],
            }

        if node.kind is not BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_UNSUPPORTED",
                "Book Opening worker received an unsupported planning layer",
            )
        arc_receipt = self._require_node_receipt_result(
            receipts,
            BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE,
        )
        overrides = tuple(
            (_RESOLVER_ROLE_BY_PLANNING_ROLE[role], version_id)
            for role, version_id in generic.items()
            if role in _RESOLVER_ROLE_BY_PLANNING_ROLE
        ) + (
            ("initial_story_state_version", request.initial_story_state_version),
            ("initial_canon_snapshot_version", request.initial_canon_snapshot_version),
        )
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
        expected_volumes = tuple(str(item["asset_version_id"]) for item in portfolio)
        expected_arcs = tuple(
            str(item["asset_version_id"])
            for item in arc_receipt.get("arc_plan_versions") or ()
        )
        if (
            snapshot.book_plan_version != book_plan
            or snapshot.volume_portfolio_plan_versions != expected_volumes
            or snapshot.current_volume_plan_version != current_volume
            or snapshot.arc_portfolio_plan_versions != expected_arcs
            or snapshot.current_relevant_arc_plan_versions
            != tuple(arc_receipt["current_relevant_arc_plan_version_ids"])
        ):
            raise KernelError(
                "BOOK_OPENING_INPUT_SNAPSHOT_DRIFT",
                "resolved Book input does not bind the exact completed planning layers",
            )
        return {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "book_design_version": snapshot.book_design_version,
            "book_plan_version": snapshot.book_plan_version,
            "volume_portfolio_plan_versions": list(
                snapshot.volume_portfolio_plan_versions
            ),
            "current_volume_plan_version": snapshot.current_volume_plan_version,
            "arc_portfolio_plan_versions": list(snapshot.arc_portfolio_plan_versions),
            "current_relevant_arc_plan_versions": list(
                snapshot.current_relevant_arc_plan_versions
            ),
        }

    def _require_current_workflow_node(
        self, opening_run_id: str
    ) -> BookOpeningWorkflowNode:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT node.workflow_node_id,node.node_kind,node.node_key,
                       node.ordinal,node.input_contract,node.input_hash,
                       node.stable_idempotency_key
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_workflow_node AS node
                  ON node.workflow_node_id=opening.current_workflow_node_id
                 AND node.opening_run_id=opening.opening_run_id
                 AND node.graph_revision=opening.workflow_graph_revision
                WHERE opening.opening_run_id=%s
                  AND opening.workflow_contract_version=%s
                """,
                [opening_run_id, BOOK_OPENING_WORKFLOW_CONTRACT_VERSION],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_MISSING",
                "Book Opening has no exact current workflow node",
            )
        return BookOpeningWorkflowNode(
            workflow_node_id=str(row[0]),
            kind=BookOpeningWorkflowNodeKind(str(row[1])),
            node_key=str(row[2]),
            ordinal=int(row[3]),
            input_contract=dict(row[4]),
            input_hash=str(row[5]),
            stable_idempotency_key=str(row[6]),
        )

    def _require_current_opening_topology_budget(
        self,
        opening_run_id: str,
        *,
        node: BookOpeningWorkflowNode,
    ) -> BookOpeningTopologyBudget:
        try:
            topology_budget = BookOpeningTopologyBudget.from_mapping(
                dict(node.input_contract.get("opening_topology_budget") or {})
            )
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "BOOK_OPENING_TOPOLOGY_BUDGET_DRIFT",
                "BOOK_PLAN node has no canonical frozen topology budget",
            ) from exc
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT scope.policy_contract_version,scope.policy_hash
                FROM authority_book_opening_run AS opening
                JOIN authority_provider_budget_scope AS scope
                  ON scope.budget_scope_id=opening.budget_scope_id
                 AND scope.revision=opening.budget_scope_revision
                 AND scope.project_id=opening.project_id
                 AND scope.owner_kind='BOOK_OPENING'
                 AND scope.owner_id=opening.opening_run_id
                WHERE opening.opening_run_id=%s
                  AND opening.workflow_contract_version=%s
                  AND opening.budget_contract_state='BOUND'
                """,
                [opening_run_id, BOOK_OPENING_WORKFLOW_CONTRACT_VERSION],
            )
            row = uow.cursor.fetchone()
        if row is None or tuple(str(value) for value in row) != (
            topology_budget.policy_contract_version,
            topology_budget.policy_hash,
        ):
            raise KernelError(
                "BOOK_OPENING_TOPOLOGY_BUDGET_DRIFT",
                "BOOK_PLAN node topology differs from the bound Budget Authority",
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            from .resource_succession import prospective_topology
            return prospective_topology(uow, opening_run_id=opening_run_id, original=topology_budget)

    def _workflow_receipt_results(
        self, opening_run_id: str
    ) -> dict[BookOpeningWorkflowNodeKind, dict[str, Any]]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT node.node_kind,receipt.result,receipt.result_hash
                FROM authority_book_opening_node_receipt AS receipt
                JOIN authority_book_opening_workflow_node AS node
                  ON node.workflow_node_id=receipt.workflow_node_id
                 AND node.opening_run_id=receipt.opening_run_id
                WHERE receipt.opening_run_id=%s
                ORDER BY node.ordinal
                """,
                [opening_run_id],
            )
            rows = uow.cursor.fetchall()
        results: dict[BookOpeningWorkflowNodeKind, dict[str, Any]] = {}
        for kind, raw_result, result_hash in rows:
            result = dict(raw_result)
            if _canonical_hash(result) != str(result_hash):
                raise KernelError(
                    "BOOK_OPENING_NODE_RECEIPT_DRIFT",
                    "workflow node receipt result differs from its immutable hash",
                )
            results[BookOpeningWorkflowNodeKind(str(kind))] = result
        return results

    @staticmethod
    def _require_node_receipt_result(
        receipts: Mapping[BookOpeningWorkflowNodeKind, dict[str, Any]],
        kind: BookOpeningWorkflowNodeKind,
    ) -> dict[str, Any]:
        result = receipts.get(kind)
        if result is None:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_PREDECESSOR_REQUIRED",
                f"{kind.value} durable node receipt is required",
            )
        return dict(result)

    def _plan_asset_evidence(
        self,
        request: OpenBookProductionRequest,
        asset_version_id: str,
        *,
        expected_contract_type: str,
        expected_logical_key: str,
    ) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id,version.content_hash,
                       version.content,version.lifecycle,version.eligibility,
                       version.governance,binding.binding_id,
                       binding.contract_type,binding.logical_key,
                       binding.freshness,active.asset_version_id
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                JOIN story_plan_binding AS binding
                  ON binding.asset_version_id=version.asset_version_id
                 AND binding.project_id=asset.project_id
                 AND binding.book_id=%s
                JOIN active_story_plan_version AS active
                  ON active.project_id=binding.project_id
                 AND active.book_id=binding.book_id
                 AND active.logical_key=binding.logical_key
                 AND active.binding_id=binding.binding_id
                 AND active.asset_version_id=binding.asset_version_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                """,
                [request.book_id, asset_version_id, request.project_id],
            )
            row = uow.cursor.fetchone()
        if (
            row is None
            or tuple(str(item) for item in row[3:6]) != ("ACTIVE", "ELIGIBLE", "CLEAR")
            or str(row[7]) != expected_contract_type
            or str(row[8]) != expected_logical_key
            or str(row[9]) != "CURRENT"
            or str(row[10]) != str(row[0])
        ):
            raise KernelError(
                "BOOK_OPENING_REVIEWABLE_PLAN_REQUIRED",
                "planning layer has no exact active, qualified, reviewable Plan asset",
            )
        return {
            "asset_version_id": str(row[0]),
            "content_hash": str(row[1]),
            "content": dict(row[2]),
            "binding_id": str(row[6]),
        }

    @staticmethod
    def _book_volume_contract(
        book_plan: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        try:
            skeleton, target = canonical_book_volume_allocation(book_plan)
        except ValueError as exc:
            raise KernelError(
                "BOOK_OPENING_BOOK_PLAN_PORTFOLIO_INVALID",
                "Book Plan cannot form one canonical Volume chapter allocation",
            ) from exc
        return [dict(item) for item in skeleton], target

    @staticmethod
    def _chapter_range(content: Mapping[str, Any]) -> tuple[int, int]:
        value = content.get("chapter_range")
        if (
            not isinstance(value, list)
            or len(value) != 2
            or any(
                not isinstance(item, int) or isinstance(item, bool) for item in value
            )
            or int(value[0]) <= 0
            or int(value[1]) < int(value[0])
        ):
            raise KernelError(
                "BOOK_OPENING_VOLUME_RANGE_INVALID",
                "Volume Plan requires one positive inclusive chapter range",
            )
        return int(value[0]), int(value[1])

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
        if definition_name in _BOOK_OPENING_PLANNING_INPUT_CONTROL_OPERATIONS:
            input_assets = self._opening_input_assets(
                self._frozen_request(str(run["opening_run_id"]))
            )
        elif definition_name in _BOOK_OPENING_RUNTIME_LINEAGE_CONTROL_OPERATIONS:
            # WHY: Abort does not consume the original Planning inputs.  Its
            # transaction handler locks the current Opening/Execution and then
            # validates the exact RuntimeJob/Attempt/Lease/fence lineage.  A
            # migrated legacy run must therefore remain governable even when
            # historical input assets are no longer retained.
            input_assets = []
        else:
            raise KernelError(
                "BOOK_OPENING_CONTROL_OPERATION_UNSUPPORTED",
                "Book Opening control command has no declared input authority",
            )

        def checkpoint(point: str) -> None:
            if self.fault_injector is None:
                return
            self.fault_injector(point)
            if (
                definition_name == "book.opening.complete_node"
                and point == "after_operation_completion_before_response"
            ):
                self.fault_injector("after_workflow_node_completion_commit")

        return execute_transaction_command(
            self.database_url,
            {
                "definition_name": definition_name,
                "definition_version": _opening_definition_version(definition_name),
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
                "input_assets": input_assets,
            },
            context=self._context(principal.principal_id),
            handler=self._execute_transaction,
            fault_injector=checkpoint,
        )

    def _validate_capacity_continuation_in_uow(
        self, uow: AuthorityUnitOfWork, *, payload: Mapping[str, Any],
        request: OpenBookProductionRequest, actor_id: str,
    ) -> dict[str, Any]:
        from novel_forge.modules.command_kernel.creative_budget_runtime import (
            _lock, _policy_for, _usage,
        )

        decision = payload.get("capacity_continuation")
        if not isinstance(decision, Mapping) or set(decision) != {
            "source_opening_run_id", "source_root_operation_id", "expected_version", "reason",
        } or not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise KernelError("BOOK_OPENING_CONTINUATION_INVALID", "Opening continuation requires exact source, version and reason")
        source_id = decision["source_opening_run_id"]
        self.recovery._lock_opening(uow, source_id)
        source = self.recovery._opening(uow, source_id, lock=True)
        uow.cursor.execute("SELECT failure FROM authority_book_opening_run WHERE opening_run_id=%s", [source_id])
        source["failure"] = uow.cursor.fetchone()[0]
        previous = dict(source["frozen_request"])
        current = request.to_dict()
        previous.pop("idempotency_key")
        current.pop("idempotency_key")
        if (source["lifecycle"] != "FAILED" or source["version"] != decision["expected_version"]
            or source["root_operation_id"] != decision["source_root_operation_id"]
            or previous != current or actor_id != request.actor_id
            or source["frozen_request_digest"] != _canonical_hash(source["frozen_request"])
            or (source.get("failure") or {}).get("code") not in {
                "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED", "PROVIDER_REQUEST_BUDGET_EXCEEDED",
            }):
            raise KernelError("BOOK_OPENING_CONTINUATION_SOURCE_INVALID", "Only the exact unstarted failed capacity request can continue")
        uow.cursor.execute("SELECT 1 FROM authority_book_opening_capacity_continuation WHERE source_opening_run_id=%s OR successor_opening_run_id=%s", [source_id, source_id])
        if uow.cursor.fetchone() is not None:
            raise KernelError("BOOK_OPENING_CONTINUATION_LIMIT", "One capacity continuation per Opening lineage is allowed")
        uow.cursor.execute(
            """WITH RECURSIVE owned(operation_id) AS (
                SELECT operation_id FROM authority_operation WHERE operation_id=%s OR (
                    project_id=%s AND COALESCE(command_payload #>> '{payload,opening_execution_binding,opening_run_id}',
                                              command_payload #>> '{opening_execution_binding,opening_run_id}')=%s)
                UNION SELECT child.operation_id FROM authority_operation child JOIN owned parent ON child.causation_operation_id=parent.operation_id
            ), all_operations AS (
                SELECT operation_id FROM owned UNION SELECT operation_id FROM authority_book_opening_budget_operation_binding WHERE opening_run_id=%s
            ) SELECT
                (SELECT count(*) FROM authority_external_effect WHERE operation_id IN (SELECT operation_id FROM all_operations)),
                (SELECT count(*) FROM authority_budget_reservation WHERE budget_scope_id=%s),
                (SELECT count(*) FROM authority_book_opening_node_receipt WHERE opening_run_id=%s),
                (SELECT count(*) FROM authority_operation_output_asset WHERE operation_id IN (SELECT operation_id FROM all_operations)),
                (SELECT count(*) FROM authority_runtime_job_lease lease JOIN authority_runtime_job job USING(runtime_job_id)
                 WHERE job.subject_kind='BOOK_OPENING_RUN' AND job.subject_id=%s AND lease.status='HELD' AND lease.lease_expires_at>clock_timestamp())
            """, [source["root_operation_id"], request.project_id, source_id, source_id, source["budget_scope_id"], source_id, source_id],
        )
        counts = uow.cursor.fetchone()
        if any(int(value) for value in counts):
            raise KernelError("BOOK_OPENING_CONTINUATION_WORK_EXISTS", "Provider, reservation, output, node or live lease evidence requires ordinary reconciliation")
        uow.cursor.execute("SELECT policy_snapshot,policy_hash FROM authority_provider_budget_scope WHERE budget_scope_id=%s AND revision=%s FOR SHARE", [source["budget_scope_id"], source["budget_scope_revision"]])
        old_policy, old_hash = uow.cursor.fetchone()
        budget = dict(payload["provider_budget_contract"])
        policy = canonical_budget_policy(budget["policy_snapshot"])
        updated = policy["policy_snapshot"]
        if updated.get("resource_control_version") == "billing-channel-resources.v1":
            from novel_forge.modules.production_execution.execution_template import selected_book_template
            admission = selected_book_template(uow.cursor, project_id=request.project_id, book_id=request.book_id)
            if admission is None:
                raise KernelError("EXECUTION_TEMPLATE_PROVENANCE_INVALID", request.book_id)
            return {"contract_version": "book-opening-capacity-continuation.v2", "request": dict(decision),
                "source_frozen_request_digest": source["frozen_request_digest"], "source_failure": source["failure"],
                "source_policy_hash": old_hash, "successor_policy_hash": policy["policy_hash"],
                "execution_template": admission,
                "zero_work_evidence": dict(zip(("effects", "reservations", "node_receipts", "outputs", "live_leases"), counts, strict=True))}
        allowed = {"token_limit", "per_call_token_limit"}
        if ({key: value for key, value in old_policy.items() if key not in allowed}
            != {key: value for key, value in updated.items() if key not in allowed}
            or updated.get("accounting_basis") != "ACCOUNT_ENTITLEMENT"
            or updated["per_call_token_limit"] <= old_policy["per_call_token_limit"]
            or updated["token_limit"] < old_policy["token_limit"]):
            raise KernelError("BOOK_OPENING_CONTINUATION_POLICY_INVALID", "Capacity continuation preserves account authorization, mode and call ceiling")
        selected = _policy_for(uow.cursor, request.project_id, required=True)
        _lock(uow.cursor, selected["policy"]["comparison_budget"]["experiment_id"])
        selected = _policy_for(uow.cursor, request.project_id, required=True)
        creative = selected["policy"]
        usage = _usage(uow.cursor, creative["comparison_budget"], request.project_id)
        arm = next(item for item in creative["comparison_budget"]["arms"] if item["project_id"] == request.project_id)
        remaining = {key: min(creative["comparison_budget"]["shared_total"][key] - usage["shared_total"][used], arm["project_total"][key] - usage["project_total"][used])
                     for key, used in (("calls", "calls_used_or_reserved"), ("tokens", "conservative_tokens"))}
        if (creative["authorization"]["book_id"] != request.book_id
            or updated["provider_call_limit"] > remaining["calls"]
            or updated["token_limit"] > remaining["tokens"]):
            raise KernelError("BOOK_OPENING_CONTINUATION_BUDGET_EXHAUSTED", "Continuation capacity exceeds the current Book's unused cumulative authorization")
        return {"contract_version": "book-opening-capacity-continuation.v1", "request": dict(decision),
                "source_frozen_request_digest": source["frozen_request_digest"],
                "source_failure": source["failure"], "source_policy_hash": old_hash,
                "successor_policy_hash": policy["policy_hash"], "creative_policy_hash": selected["policy_hash"],
                "unused_cumulative_headroom": remaining,
                "zero_work_evidence": dict(zip(("effects", "reservations", "node_receipts", "outputs", "live_leases"), counts, strict=True))}

    def _execute_transaction(
        self,
        uow: AuthorityUnitOfWork,
        operation_id: str,
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT definition_name,project_id,workspace_id,command_payload,
                   actor_id,created_at,input_asset_snapshot
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
        if definition_name in {"book.opening.admit", "book.opening.continue_unstarted"}:
            frozen_request = dict(payload["frozen_request"])
            digest = _canonical_hash(frozen_request)
            if digest != str(payload["frozen_request_digest"]):
                raise KernelError(
                    "BOOK_OPENING_FROZEN_REQUEST_DRIFT",
                    "Book opening request differs from its digest",
                )
            request = OpenBookProductionRequest.from_mapping(frozen_request)
            predecessor = ""
            continuation_evidence = None
            if definition_name == "book.opening.continue_unstarted":
                continuation_evidence = self._validate_capacity_continuation_in_uow(
                    uow, payload=payload, request=request, actor_id=str(operation[4]),
                )
                predecessor = str(continuation_evidence["request"]["source_opening_run_id"])
            self._require_canonical_opening_inputs(request)
            design_version = self._require_qualified_foundation_in_uow(
                uow.cursor, request
            )
            if request.planning_replacement is not None:
                replacement = request.planning_replacement
                current_versions = self._unwritten_replacement_versions_in_uow(
                    uow.cursor, request=request,
                    source_opening_run_id=str(replacement["source_opening_run_id"]),
                    source_version=int(replacement["source_version"]),
                )
                if current_versions != dict(replacement["expected_active_plan_versions"]):
                    raise KernelError("BOOK_OPENING_REPLACEMENT_VERSION_CONFLICT", "Active plans changed after the unwritten repair decision")
            if request.planning_input_versions.get("book_design") != design_version:
                raise KernelError(
                    "BOOK_OPENING_INPUTS_INVALID",
                    "Book Opening input roles do not bind the active BookDesign",
                )
            self._production_target_chapters_in_uow(uow.cursor, request)
            self._lock_and_require_opening_input_assets_in_uow(
                uow.cursor,
                request=request,
                input_asset_snapshot=operation[6],
            )
            excluded_openings = [opening_run_id, predecessor]
            uow.cursor.execute("SELECT to_regclass('authority_book_opening_capacity_continuation')")
            if uow.cursor.fetchone()[0] is not None:
                uow.cursor.execute("SELECT source_opening_run_id FROM authority_book_opening_capacity_continuation WHERE project_id=%s AND book_id=%s", [request.project_id, request.book_id])
                excluded_openings.extend(str(row[0]) for row in uow.cursor.fetchall())
            uow.cursor.execute(
                """
                SELECT opening_run_id
                FROM authority_book_opening_run
                WHERE project_id=%s AND book_id=%s
                  AND lifecycle IN ('ADMITTED','RUNNING','FAILED')
                  AND opening_run_id<>ALL(%s)
                FOR UPDATE
                """,
                [request.project_id, request.book_id, excluded_openings],
            )
            if uow.cursor.fetchone() is not None:
                raise KernelError(
                    "BOOK_OPENING_ACTIVE_WORKFLOW_CONFLICT",
                    "Book already has an active or recoverable Opening workflow",
                )
            uow.cursor.execute(
                """
                SELECT book_run_id
                FROM authority_book_production
                WHERE project_id=%s AND book_id=%s
                  AND state NOT IN ('COMPLETED','ABORTED')
                FOR UPDATE
                """,
                [request.project_id, request.book_id],
            )
            if uow.cursor.fetchone() is not None:
                raise KernelError(
                    "BOOK_OPENING_REPLAN_REQUIRED",
                    "An active BookRun may change plans only through governed replan",
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
            raw_topology_budget = budget_contract.get("opening_topology_budget")
            try:
                topology_budget = BookOpeningTopologyBudget.from_mapping(
                    dict(raw_topology_budget or {})
                )
                expected_topology_budget = assess_book_opening_topology_budget(
                    policy_contract_version=str(
                        budget_contract.get("policy_contract_version") or ""
                    ),
                    policy_hash=str(budget_contract.get("policy_hash") or ""),
                    policy=dict(canonical_policy["policy_snapshot"]),
                    arc_count=len(request.arc_logical_keys),
                )
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "BOOK_OPENING_TOPOLOGY_BUDGET_INVALID",
                    "Book Opening topology budget is incomplete or non-canonical",
                ) from exc
            if (
                str(canonical_policy["policy_hash"])
                != str(budget_contract.get("policy_hash") or "")
                or int(budget_contract.get("window_seconds") or 0) <= 0
                or topology_budget != expected_topology_budget
            ):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_CONTRACT_INVALID",
                    "Book Opening Provider budget differs from its frozen hash",
                )
            workflow = build_book_opening_workflow(
                opening_run_id=opening_run_id,
                frozen_request_digest=digest,
                arc_logical_keys=request.arc_logical_keys,
                topology_budget=topology_budget,
            )
            first_node = workflow.node(BookOpeningWorkflowNodeKind.BOOK_PLAN)
            if continuation_evidence is not None:
                uow.cursor.execute("UPDATE authority_book_opening_run SET capacity_successor_opening_run_id=%s WHERE opening_run_id=%s AND capacity_successor_opening_run_id IS NULL", [opening_run_id, predecessor])
                if uow.cursor.rowcount != 1:
                    raise KernelError("BOOK_OPENING_CONTINUATION_CONFLICT", "Opening already has a capacity successor")
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_run(
                    opening_run_id,project_id,workspace_id,book_id,
                    root_operation_id,stable_idempotency_key,lifecycle,
                    frozen_request,frozen_request_digest,
                    execution_contract_version,recovery_state,
                    workflow_contract_version,current_workflow_node_id,
                    workflow_graph_revision,workflow_graph_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,'ADMITTED',%s,%s,%s,'READY',
                          %s,%s,%s,%s)
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
                    BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION,
                    workflow.contract_version,
                    first_node.workflow_node_id,
                    workflow.graph_revision,
                    workflow.graph_hash,
                ],
            )
            created = uow.cursor.rowcount == 1
            if not created:
                uow.cursor.execute(
                    """
                    SELECT root_operation_id,frozen_request_digest,
                           workflow_contract_version,current_workflow_node_id,
                           workflow_graph_revision,workflow_graph_hash
                    FROM authority_book_opening_run WHERE opening_run_id=%s
                    """,
                    [opening_run_id],
                )
                existing = uow.cursor.fetchone()
                if existing is None or (
                    str(existing[0]) != operation_id
                    or str(existing[1]) != digest
                    or str(existing[2]) != workflow.contract_version
                    or str(existing[3]) != first_node.workflow_node_id
                    or int(existing[4]) != workflow.graph_revision
                    or str(existing[5]) != workflow.graph_hash
                ):
                    raise KernelError(
                        "BOOK_OPENING_IDEMPOTENCY_CONFLICT",
                        "Book opening identity binds different frozen evidence",
                    )
            self._persist_workflow_graph_in_uow(uow, workflow)
            if created:
                execution_id = _stable_id("book-opening-execution", opening_run_id, 1)
                runtime_job_kind, runtime_group = book_opening_runtime_job_identity(
                    workflow.contract_version
                )
                execution_contract_version = book_opening_execution_contract_version(
                    workflow.contract_version
                )
                runtime_spec = RuntimeJobSpec(
                    job_kind=runtime_job_kind,
                    runtime_group=runtime_group,
                    subject_kind="BOOK_OPENING_RUN",
                    subject_id=opening_run_id,
                    project_id=str(operation[1]),
                    dedupe_key=(
                        f"{opening_run_id}:workflow-node:"
                        f"{first_node.workflow_node_id}:execution-generation:1"
                    ),
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
                        "workflow_contract_version": workflow.contract_version,
                        "workflow_graph_revision": workflow.graph_revision,
                        "workflow_graph_hash": workflow.graph_hash,
                        "workflow_node_id": first_node.workflow_node_id,
                        "workflow_node_kind": first_node.kind.value,
                        "workflow_node_key": first_node.node_key,
                        "workflow_node_input_hash": first_node.input_hash,
                        "workflow_transition_kind": "ADMISSION",
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
                        authority_contract_hash,workflow_node_id,
                        workflow_transition_kind,source_checkpoint_sequence,
                        source_checkpoint_hash
                    ) VALUES (%s,%s,1,%s,'SCHEDULED',%s,%s,%s,%s,%s,
                              'ADMISSION',0,'')
                    """,
                    [
                        execution_id,
                        opening_run_id,
                        runtime_job["runtime_job_id"],
                        digest,
                        runtime_spec.input_hash,
                        self.recovery._execution_policy_digest(),
                        self.recovery._authority_digest(execution_contract_version),
                        first_node.workflow_node_id,
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
            if continuation_evidence is not None:
                uow.cursor.execute(
                    """INSERT INTO authority_book_opening_capacity_continuation(
                        source_opening_run_id,successor_opening_run_id,operation_id,
                        project_id,workspace_id,book_id,evidence,evidence_hash
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [predecessor, opening_run_id, operation_id, request.project_id,
                     request.workspace_id, request.book_id, Jsonb(continuation_evidence),
                     _canonical_hash(continuation_evidence)],
                )
                checkpoint("after_capacity_continuation")
        elif definition_name == "book.opening.complete_node":
            return self._complete_workflow_node_in_uow(
                uow,
                operation_id=operation_id,
                payload=payload,
                checkpoint=checkpoint,
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
                    or str(budget_scope["currency"]).upper()
                    != self.provider_budget_currency
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

    def _complete_workflow_node_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        payload: Mapping[str, Any],
        checkpoint: TransactionCheckpoint,
    ) -> dict[str, Any]:
        opening_run_id = str(payload.get("opening_run_id") or "")
        workflow_node_id = str(payload.get("workflow_node_id") or "")
        raw_result = payload.get("node_result")
        if (
            not opening_run_id
            or not workflow_node_id
            or not isinstance(raw_result, Mapping)
        ):
            raise KernelError(
                "BOOK_OPENING_NODE_RESULT_INVALID",
                "workflow node completion payload is incomplete",
            )
        node_result = dict(raw_result)
        runtime_claim = self._runtime_claim_from_payload(payload.get("runtime_claim"))
        run = self.recovery._opening(uow, opening_run_id, lock=True)
        execution = self.recovery._current_execution(uow, run, lock=True)
        if (
            str(run.get("workflow_contract_version") or "")
            != BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
            or str(run.get("execution_contract_version") or "")
            != BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION
            or str(run.get("current_workflow_node_id") or "") != workflow_node_id
            or int(run["version"]) != int(payload.get("expected_version", -1))
            or str(run["lifecycle"]) != "RUNNING"
            or str(execution.get("workflow_node_id") or "") != workflow_node_id
            or str(execution["lifecycle"]) != "RUNNING"
        ):
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_COMMIT_CONFLICT",
                "workflow node no longer owns the current Opening execution",
            )
        self.recovery._require_live_checkpoint_claim(
            uow,
            run=run,
            execution=execution,
            runtime_claim=runtime_claim,
        )
        uow.cursor.execute(
            """
            SELECT node_kind,node_key,ordinal,input_contract,input_hash,
                   graph_revision,stable_idempotency_key
            FROM authority_book_opening_workflow_node
            WHERE workflow_node_id=%s AND opening_run_id=%s
              AND graph_revision=%s
            FOR SHARE
            """,
            [workflow_node_id, opening_run_id, run["workflow_graph_revision"]],
        )
        node_row = uow.cursor.fetchone()
        if node_row is None:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_MISSING",
                "current workflow node disappeared before completion",
            )
        node_kind = BookOpeningWorkflowNodeKind(str(node_row[0]))
        node_key = str(node_row[1])
        evidence = self._validate_workflow_node_result_in_uow(
            uow,
            run=run,
            node_kind=node_kind,
            node_key=node_key,
            node_input_contract=dict(node_row[3]),
            result=node_result,
        )

        for search_id in self._workflow_node_search_ids(node_kind, node_result):
            search_evidence = self.recovery._narrative_search_evidence(
                uow,
                search_id=search_id,
                project_id=str(run["project_id"]),
                workspace_id=str(run["workspace_id"]),
                book_id=str(run["book_id"]),
            )
            appended = self.recovery._append_checkpoint_in_uow(
                uow,
                run=run,
                execution=execution,
                semantic_work_key=(
                    f"{search_evidence['generator_operation_name']}:"
                    f"{search_evidence['logical_key']}"
                ),
                owning_authority="STORY_PLANNING",
                evidence_type="NARRATIVE_SEARCH",
                evidence_id=search_id,
                evidence_version=int(search_evidence["version"]),
                evidence_hash=str(search_evidence["evidence_hash"]),
                workflow_node_id=workflow_node_id,
            )
            run["current_checkpoint_id"] = appended["checkpoint_id"]
            run["current_checkpoint_sequence"] = appended["sequence"]
            run["current_checkpoint_hash"] = appended["checkpoint_hash"]

        result_hash = _canonical_hash(node_result)
        node_receipt_id = _stable_id(
            "book-opening-node-receipt",
            opening_run_id,
            workflow_node_id,
            str(node_row[4]),
            result_hash,
        )
        authoritative_payload = {
            "contract_version": "book-opening-node-authoritative-evidence.v1",
            "opening_run_id": opening_run_id,
            "workflow_node_id": workflow_node_id,
            "node_kind": node_kind.value,
            "node_key": node_key,
            "node_input_hash": str(node_row[4]),
            "result_hash": result_hash,
            "reviewable_artifact_kind": evidence["reviewable_artifact_kind"],
            "reviewable_asset_version_ids": evidence["reviewable_asset_version_ids"],
            "authoritative_inner_evidence": evidence["authoritative_inner_evidence"],
        }
        authoritative_evidence_hash = _canonical_hash(authoritative_payload)
        semantic_work_key = f"book-opening-node:{node_kind.value}:{workflow_node_id}"
        checkpoint_id = _stable_id(
            "book-opening-checkpoint",
            opening_run_id,
            semantic_work_key,
            "BOOK_AUTHORITY",
            "BOOK_OPENING_NODE_RECEIPT",
            node_receipt_id,
            1,
            authoritative_evidence_hash,
        )
        checkpoint_sequence = int(run["current_checkpoint_sequence"]) + 1
        checkpoint_payload = {
            "opening_run_id": opening_run_id,
            "opening_execution_id": str(execution["opening_execution_id"]),
            "execution_generation": int(execution["generation"]),
            "sequence": checkpoint_sequence,
            "semantic_work_key": semantic_work_key,
            "owning_authority": "BOOK_AUTHORITY",
            "evidence_type": "BOOK_OPENING_NODE_RECEIPT",
            "evidence_id": node_receipt_id,
            "evidence_version": 1,
            "evidence_hash": authoritative_evidence_hash,
            "frozen_request_digest": str(run["frozen_request_digest"]),
            "predecessor_checkpoint_id": str(run["current_checkpoint_id"] or ""),
            "predecessor_checkpoint_hash": str(run["current_checkpoint_hash"] or ""),
        }
        checkpoint_hash = _canonical_hash(checkpoint_payload)
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_node_receipt(
                node_receipt_id,opening_run_id,workflow_node_id,
                opening_execution_id,execution_generation,result,result_hash,
                authoritative_evidence_hash,reviewable_artifact_kind,
                reviewable_asset_version_ids,checkpoint_id,
                checkpoint_sequence,checkpoint_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (workflow_node_id) DO NOTHING
            """,
            [
                node_receipt_id,
                opening_run_id,
                workflow_node_id,
                execution["opening_execution_id"],
                execution["generation"],
                Jsonb(node_result),
                result_hash,
                authoritative_evidence_hash,
                evidence["reviewable_artifact_kind"],
                evidence["reviewable_asset_version_ids"],
                checkpoint_id,
                checkpoint_sequence,
                checkpoint_hash,
            ],
        )
        if uow.cursor.rowcount != 1:
            uow.cursor.execute(
                """
                SELECT node_receipt_id,result_hash,authoritative_evidence_hash,
                       checkpoint_id,checkpoint_sequence,checkpoint_hash
                FROM authority_book_opening_node_receipt
                WHERE workflow_node_id=%s
                """,
                [workflow_node_id],
            )
            existing = uow.cursor.fetchone()
            if existing is None or tuple(existing) != (
                node_receipt_id,
                result_hash,
                authoritative_evidence_hash,
                checkpoint_id,
                checkpoint_sequence,
                checkpoint_hash,
            ):
                raise KernelError(
                    "BOOK_OPENING_NODE_RECEIPT_IDEMPOTENCY_CONFLICT",
                    "workflow node already binds different durable evidence",
                )
        checkpoint("after_workflow_node_receipt_insert")
        node_checkpoint = self.recovery._append_checkpoint_in_uow(
            uow,
            run=run,
            execution=execution,
            semantic_work_key=semantic_work_key,
            owning_authority="BOOK_AUTHORITY",
            evidence_type="BOOK_OPENING_NODE_RECEIPT",
            evidence_id=node_receipt_id,
            evidence_version=1,
            evidence_hash=authoritative_evidence_hash,
            workflow_node_id=workflow_node_id,
        )
        if (
            str(node_checkpoint["checkpoint_id"]) != checkpoint_id
            or int(node_checkpoint["sequence"]) != checkpoint_sequence
            or str(node_checkpoint["checkpoint_hash"]) != checkpoint_hash
        ):
            raise KernelError(
                "BOOK_OPENING_NODE_CHECKPOINT_CONFLICT",
                "workflow node receipt does not bind the predicted checkpoint head",
            )
        run["current_checkpoint_id"] = checkpoint_id
        run["current_checkpoint_sequence"] = checkpoint_sequence
        run["current_checkpoint_hash"] = checkpoint_hash

        if node_kind is BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT:
            input_snapshot_binding_id = _stable_id(
                "book-opening-input-snapshot-binding",
                opening_run_id,
                workflow_node_id,
                node_receipt_id,
                str(node_result["snapshot_id"]),
                str(node_result["snapshot_hash"]),
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_input_snapshot_binding(
                    input_snapshot_binding_id,opening_run_id,workflow_node_id,
                    node_receipt_id,checkpoint_id,checkpoint_sequence,
                    checkpoint_hash,snapshot_id,snapshot_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                [
                    input_snapshot_binding_id,
                    opening_run_id,
                    workflow_node_id,
                    node_receipt_id,
                    checkpoint_id,
                    checkpoint_sequence,
                    checkpoint_hash,
                    node_result["snapshot_id"],
                    node_result["snapshot_hash"],
                ],
            )
            if uow.cursor.rowcount != 1:
                uow.cursor.execute(
                    """
                    SELECT input_snapshot_binding_id,opening_run_id,
                           workflow_node_id,node_receipt_id,checkpoint_id,
                           checkpoint_sequence,checkpoint_hash,snapshot_hash
                    FROM authority_book_opening_input_snapshot_binding
                    WHERE snapshot_id=%s
                    """,
                    [node_result["snapshot_id"]],
                )
                existing_binding = uow.cursor.fetchone()
                if existing_binding is None or tuple(existing_binding) != (
                    input_snapshot_binding_id,
                    opening_run_id,
                    workflow_node_id,
                    node_receipt_id,
                    checkpoint_id,
                    checkpoint_sequence,
                    checkpoint_hash,
                    str(node_result["snapshot_hash"]),
                ):
                    raise KernelError(
                        "BOOK_OPENING_INPUT_SNAPSHOT_BINDING_CONFLICT",
                        "Input Snapshot already belongs to another Opening workflow",
                    )

        uow.cursor.execute(
            """
            UPDATE authority_book_opening_execution
            SET lifecycle='SUCCEEDED',terminal_reason='{}'::jsonb,
                version=version+1,terminal_at=transaction_timestamp(),
                updated_at=transaction_timestamp()
            WHERE opening_execution_id=%s AND opening_run_id=%s
              AND generation=%s AND version=%s AND lifecycle='RUNNING'
              AND workflow_node_id=%s
            """,
            [
                execution["opening_execution_id"],
                opening_run_id,
                execution["generation"],
                execution["version"],
                workflow_node_id,
            ],
        )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_COMMIT_CONFLICT",
                "Opening execution changed before node terminalization",
            )
        self.runtime_jobs.complete_authority_owned_in_uow(
            uow,
            runtime_claim,
            {
                "workflow_node_id": workflow_node_id,
                "node_kind": node_kind.value,
                "node_receipt_id": node_receipt_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_hash": checkpoint_hash,
            },
        )

        successor = self._workflow_successor_in_uow(
            uow,
            opening_run_id=opening_run_id,
            workflow_node_id=workflow_node_id,
            ordinal=int(node_row[2]),
        )
        successor_runtime_job_id = ""
        book_opening_result: dict[str, Any] | None = None
        next_version = int(run["version"]) + 1
        if successor is None:
            if node_kind is not BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT:
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_GRAPH_INCOMPLETE",
                    "non-terminal workflow node has no successor",
                )
            book_opening_result = self._aggregate_workflow_result_in_uow(
                uow,
                opening_run_id=opening_run_id,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='COMPLETE',result=%s,failure='{}'::jsonb,
                    recovery_instruction='{}'::jsonb,recovery_state='READY',
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s AND lifecycle='RUNNING'
                  AND current_workflow_node_id=%s
                """,
                [
                    Jsonb(book_opening_result),
                    opening_run_id,
                    run["version"],
                    workflow_node_id,
                ],
            )
        else:
            successor_generation = int(execution["generation"]) + 1
            successor_execution_id = _stable_id(
                "book-opening-execution",
                opening_run_id,
                successor_generation,
            )
            runtime_job_kind, runtime_group = book_opening_runtime_job_identity(
                BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
            )
            runtime_spec = RuntimeJobSpec(
                job_kind=runtime_job_kind,
                runtime_group=runtime_group,
                subject_kind="BOOK_OPENING_RUN",
                subject_id=opening_run_id,
                project_id=str(run["project_id"]),
                dedupe_key=(
                    f"{opening_run_id}:workflow-node:{successor['workflow_node_id']}:"
                    f"execution-generation:{successor_generation}"
                ),
                input_snapshot={
                    "opening_run_id": opening_run_id,
                    "observed_version": next_version,
                    "frozen_request_digest": str(run["frozen_request_digest"]),
                    "opening_execution_id": successor_execution_id,
                    "execution_generation": successor_generation,
                    "recovery_intent_id": "",
                    "replacement_evaluation_operation_id": "",
                    "semantic_evaluation_operation_id": "",
                    "semantic_evaluation_execution_id": "",
                    "semantic_evaluation_generation": 0,
                    "semantic_execution_mode": "NONE",
                    "workflow_contract_version": BOOK_OPENING_WORKFLOW_CONTRACT_VERSION,
                    "workflow_graph_revision": int(run["workflow_graph_revision"]),
                    "workflow_graph_hash": str(run["workflow_graph_hash"]),
                    "workflow_node_id": str(successor["workflow_node_id"]),
                    "workflow_node_kind": str(successor["node_kind"]),
                    "workflow_node_key": str(successor["node_key"]),
                    "workflow_node_input_hash": str(successor["input_hash"]),
                    "workflow_transition_kind": "CONTINUATION",
                    "source_checkpoint_id": checkpoint_id,
                    "source_checkpoint_sequence": checkpoint_sequence,
                    "source_checkpoint_hash": checkpoint_hash,
                },
                max_attempts=1,
                lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
            )
            scheduled = self.runtime_jobs.schedule_in_uow(uow, runtime_spec)
            successor_runtime_job_id = str(scheduled["runtime_job_id"])
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_execution(
                    opening_execution_id,opening_run_id,generation,
                    predecessor_execution_id,predecessor_generation,
                    runtime_job_id,lifecycle,frozen_request_digest,
                    input_snapshot_hash,policy_snapshot_hash,
                    authority_contract_hash,workflow_node_id,
                    workflow_transition_kind,source_checkpoint_id,
                    source_checkpoint_sequence,source_checkpoint_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,'SCHEDULED',%s,%s,%s,%s,%s,
                          'CONTINUATION',%s,%s,%s)
                """,
                [
                    successor_execution_id,
                    opening_run_id,
                    successor_generation,
                    execution["opening_execution_id"],
                    execution["generation"],
                    successor_runtime_job_id,
                    run["frozen_request_digest"],
                    runtime_spec.input_hash,
                    self.recovery._execution_policy_digest(),
                    self.recovery._authority_digest(
                        BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION
                    ),
                    successor["workflow_node_id"],
                    checkpoint_id,
                    checkpoint_sequence,
                    checkpoint_hash,
                ],
            )
            transition_payload = {
                "contract_version": "book-opening-workflow-transition.v1",
                "opening_run_id": opening_run_id,
                "source_node_receipt_id": node_receipt_id,
                "predecessor_opening_execution_id": str(
                    execution["opening_execution_id"]
                ),
                "predecessor_execution_generation": int(execution["generation"]),
                "successor_opening_execution_id": successor_execution_id,
                "successor_execution_generation": successor_generation,
                "successor_workflow_node_id": str(successor["workflow_node_id"]),
                "source_checkpoint_id": checkpoint_id,
                "source_checkpoint_sequence": checkpoint_sequence,
                "source_checkpoint_hash": checkpoint_hash,
                "transition_kind": "CONTINUATION",
            }
            transition_hash = _canonical_hash(transition_payload)
            transition_receipt_id = _stable_id(
                "book-opening-workflow-transition-receipt",
                opening_run_id,
                node_receipt_id,
                successor_execution_id,
                successor_generation,
                transition_hash,
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_workflow_transition_receipt(
                    workflow_transition_receipt_id,opening_run_id,
                    source_node_receipt_id,predecessor_opening_execution_id,
                    predecessor_execution_generation,
                    successor_opening_execution_id,
                    successor_execution_generation,successor_workflow_node_id,
                    source_checkpoint_id,source_checkpoint_sequence,
                    source_checkpoint_hash,transition_kind,transition_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          'CONTINUATION',%s)
                """,
                [
                    transition_receipt_id,
                    opening_run_id,
                    node_receipt_id,
                    execution["opening_execution_id"],
                    execution["generation"],
                    successor_execution_id,
                    successor_generation,
                    successor["workflow_node_id"],
                    checkpoint_id,
                    checkpoint_sequence,
                    checkpoint_hash,
                    transition_hash,
                ],
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='ADMITTED',current_workflow_node_id=%s,
                    current_execution_id=%s,current_execution_generation=%s,
                    failure='{}'::jsonb,recovery_instruction='{}'::jsonb,
                    recovery_state='READY',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s AND lifecycle='RUNNING'
                  AND current_workflow_node_id=%s
                """,
                [
                    successor["workflow_node_id"],
                    successor_execution_id,
                    successor_generation,
                    opening_run_id,
                    run["version"],
                    workflow_node_id,
                ],
            )
        if uow.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_COMMIT_CONFLICT",
                "Book Opening changed before node continuation commit",
            )
        lifecycle = "COMPLETE" if successor is None else "ADMITTED"
        event_payload = {
            "operation_id": operation_id,
            "opening_run_id": opening_run_id,
            "workflow_node_id": workflow_node_id,
            "node_kind": node_kind.value,
            "node_receipt_id": node_receipt_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint_sequence": checkpoint_sequence,
            "checkpoint_hash": checkpoint_hash,
            "successor_runtime_job_id": successor_runtime_job_id,
            "lifecycle": lifecycle,
            "version": next_version,
        }
        uow.repositories.operation_graph.record_event(
            {
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
                "aggregate_type": "book_opening",
                "aggregate_id": opening_run_id,
                "operation_id": operation_id,
                "project_id": str(run["project_id"]),
                "event_type": "book.opening.transitioned",
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "payload": event_payload,
            }
        )
        return {
            "opening_run_id": opening_run_id,
            "workflow_node_id": workflow_node_id,
            "node_kind": node_kind.value,
            "node_key": node_key,
            "node_receipt_id": node_receipt_id,
            "lifecycle": lifecycle,
            "version": next_version,
            "successor_runtime_job_id": successor_runtime_job_id,
            "book_opening_result": book_opening_result,
        }

    def _validate_workflow_node_result_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: Mapping[str, Any],
        node_kind: BookOpeningWorkflowNodeKind,
        node_key: str,
        node_input_contract: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        del node_key

        def plan(
            *,
            asset_version_id: str,
            content_hash: str,
            binding_id: str,
            contract_type: str,
            logical_key: str,
        ) -> dict[str, Any]:
            uow.cursor.execute(
                """
                SELECT version.content_hash,version.lifecycle,version.eligibility,
                       version.governance,binding.binding_id,
                       binding.contract_type,binding.logical_key,
                       binding.freshness,active.asset_version_id,
                       version.content
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
                JOIN story_plan_binding AS binding
                  ON binding.asset_version_id=version.asset_version_id
                 AND binding.project_id=asset.project_id
                 AND binding.book_id=%s
                JOIN active_story_plan_version AS active
                  ON active.project_id=binding.project_id
                 AND active.book_id=binding.book_id
                 AND active.logical_key=binding.logical_key
                 AND active.binding_id=binding.binding_id
                 AND active.asset_version_id=binding.asset_version_id
                WHERE version.asset_version_id=%s AND asset.project_id=%s
                FOR SHARE OF version,asset,binding,active
                """,
                [run["book_id"], asset_version_id, run["project_id"]],
            )
            row = uow.cursor.fetchone()
            if (
                row is None
                or str(row[0]) != content_hash
                or tuple(str(item) for item in row[1:4])
                != ("ACTIVE", "ELIGIBLE", "CLEAR")
                or str(row[4]) != binding_id
                or str(row[5]) != contract_type
                or str(row[6]) != logical_key
                or str(row[7]) != "CURRENT"
                or str(row[8]) != asset_version_id
            ):
                raise KernelError(
                    "BOOK_OPENING_NODE_ARTIFACT_DRIFT",
                    "node result differs from its active reviewable Plan Authority",
                )
            return {
                "asset_version_id": asset_version_id,
                "content_hash": content_hash,
                "binding_id": binding_id,
                "contract_type": contract_type,
                "logical_key": logical_key,
                "content": dict(row[9]),
            }

        def plan_identity(artifact: Mapping[str, Any]) -> dict[str, Any]:
            return {key: value for key, value in artifact.items() if key != "content"}

        def search(search_id: str, expected_asset_version_id: str) -> dict[str, Any]:
            item = self.recovery._narrative_search_evidence(
                uow,
                search_id=search_id,
                project_id=str(run["project_id"]),
                workspace_id=str(run["workspace_id"]),
                book_id=str(run["book_id"]),
            )
            if str(item["selected_candidate_asset_version_id"]) != (
                expected_asset_version_id
            ):
                raise KernelError(
                    "BOOK_OPENING_NODE_SEARCH_DRIFT",
                    "node artifact differs from the Planning selection decision",
                )
            return {
                "search_id": search_id,
                "search_evidence_hash": str(item["evidence_hash"]),
            }

        inner: list[dict[str, Any]] = []
        assets: list[str] = []
        if node_kind is BookOpeningWorkflowNodeKind.BOOK_PLAN:
            if set(result) != {
                "search_id",
                "asset_version_id",
                "content_hash",
                "binding_id",
            }:
                raise KernelError(
                    "BOOK_OPENING_NODE_RESULT_INVALID",
                    "BOOK_PLAN node result fields must match exactly",
                )
            try:
                topology_budget = BookOpeningTopologyBudget.from_mapping(
                    dict(node_input_contract.get("opening_topology_budget") or {})
                )
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "BOOK_OPENING_BOOK_PLAN_TOPOLOGY_INVALID",
                    "BOOK_PLAN node has no immutable canonical topology budget",
                ) from exc
            uow.cursor.execute(
                """
                SELECT scope.policy_contract_version,scope.policy_hash
                FROM authority_provider_budget_scope AS scope
                WHERE scope.budget_scope_id=%s AND scope.revision=%s
                  AND scope.project_id=%s AND scope.owner_kind='BOOK_OPENING'
                  AND scope.owner_id=%s
                FOR SHARE
                """,
                [
                    run.get("budget_scope_id"),
                    run.get("budget_scope_revision"),
                    run["project_id"],
                    run["opening_run_id"],
                ],
            )
            budget_scope = uow.cursor.fetchone()
            if budget_scope is None or tuple(str(value) for value in budget_scope) != (
                topology_budget.policy_contract_version,
                topology_budget.policy_hash,
            ):
                raise KernelError(
                    "BOOK_OPENING_TOPOLOGY_BUDGET_DRIFT",
                    "BOOK_PLAN receipt topology differs from bound Budget Authority",
                )
            artifact = plan(
                asset_version_id=str(result["asset_version_id"]),
                content_hash=str(result["content_hash"]),
                binding_id=str(result["binding_id"]),
                contract_type="BOOK",
                logical_key="book:main",
            )
            try:
                skeleton, _ = self._book_volume_contract(dict(artifact["content"]))
                from .resource_succession import prospective_topology
                prospective_topology(uow, opening_run_id=run["opening_run_id"], original=topology_budget).require_volume_count(len(skeleton))
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "BOOK_OPENING_BOOK_PLAN_TOPOLOGY_INVALID",
                    "Book Plan receipt exceeds its immutable node topology budget",
                ) from exc
            inner.extend(
                (
                    plan_identity(artifact),
                    search(str(result["search_id"]), artifact["asset_version_id"]),
                )
            )
            assets.append(artifact["asset_version_id"])
            artifact_kind = "BOOK_PLAN"
        elif node_kind is BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO:
            expected = {
                "source_book_plan_id",
                "source_book_plan_hash",
                "volume_skeleton_hash",
                "target_chapters",
                "coverage_range",
                "volume_plan_versions",
            }
            members = result.get("volume_plan_versions")
            if set(result) != expected or not isinstance(members, list) or not members:
                raise KernelError(
                    "BOOK_OPENING_NODE_RESULT_INVALID",
                    "VOLUME_PORTFOLIO node result fields must match exactly",
                )
            book = self._node_receipt_result_in_uow(
                uow, str(run["opening_run_id"]), BookOpeningWorkflowNodeKind.BOOK_PLAN
            )
            if str(result["source_book_plan_id"]) != str(
                book["asset_version_id"]
            ) or str(result["source_book_plan_hash"]) != str(book["content_hash"]):
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
                    "Volume Portfolio differs from its Book Plan receipt",
                )
            source_book = plan(
                asset_version_id=str(book["asset_version_id"]),
                content_hash=str(book["content_hash"]),
                binding_id=str(book["binding_id"]),
                contract_type="BOOK",
                logical_key="book:main",
            )
            skeleton, target_chapters = self._book_volume_contract(
                dict(source_book["content"])
            )
            if (
                str(result["volume_skeleton_hash"]) != _canonical_hash(skeleton)
                or not isinstance(result["target_chapters"], int)
                or isinstance(result["target_chapters"], bool)
                or int(result["target_chapters"]) != target_chapters
                or result["coverage_range"] != [1, target_chapters]
                or len(members) != len(skeleton)
            ):
                raise KernelError(
                    "BOOK_OPENING_VOLUME_PORTFOLIO_INVALID",
                    "Volume Portfolio does not match the activated Book Plan contract",
                )
            previous_end = 0
            for ordinal, raw in enumerate(members, start=1):
                if (
                    not isinstance(raw, Mapping)
                    or set(raw)
                    != {
                        "ordinal",
                        "logical_key",
                        "search_id",
                        "asset_version_id",
                        "content_hash",
                        "binding_id",
                        "chapter_range",
                    }
                    or not isinstance(raw["ordinal"], int)
                    or isinstance(raw["ordinal"], bool)
                    or int(raw["ordinal"]) != ordinal
                    or str(raw["logical_key"]) != f"volume:{ordinal}"
                ):
                    raise KernelError(
                        "BOOK_OPENING_NODE_RESULT_INVALID",
                        "Volume Portfolio member identity is invalid",
                    )
                artifact = plan(
                    asset_version_id=str(raw["asset_version_id"]),
                    content_hash=str(raw["content_hash"]),
                    binding_id=str(raw["binding_id"]),
                    contract_type="VOLUME",
                    logical_key=f"volume:{ordinal}",
                )
                chapter_range = self._chapter_range(dict(artifact["content"]))
                if (
                    raw["chapter_range"] != list(chapter_range)
                    or raw["chapter_range"]
                    != list(skeleton[ordinal - 1]["chapter_range"])
                    or chapter_range[0] != previous_end + 1
                ):
                    raise KernelError(
                        "BOOK_OPENING_VOLUME_PORTFOLIO_INVALID",
                        "Volume Plan ranges must exactly cover a contiguous portfolio",
                    )
                previous_end = chapter_range[1]
                inner.extend(
                    (
                        plan_identity(artifact),
                        search(str(raw["search_id"]), artifact["asset_version_id"]),
                    )
                )
                assets.append(artifact["asset_version_id"])
            if previous_end != target_chapters:
                raise KernelError(
                    "BOOK_OPENING_VOLUME_PORTFOLIO_INCOMPLETE",
                    "Volume Portfolio does not cover the activated Book Plan target",
                )
            artifact_kind = "VOLUME_PORTFOLIO"
        elif node_kind is BookOpeningWorkflowNodeKind.CURRENT_VOLUME:
            if (
                set(result)
                != {
                    "chapter_cursor",
                    "volume_portfolio_hash",
                    "current_volume_plan_version_id",
                    "current_volume_content_hash",
                    "chapter_range",
                }
                or int(result["chapter_cursor"]) != 1
            ):
                raise KernelError(
                    "BOOK_OPENING_NODE_RESULT_INVALID",
                    "CURRENT_VOLUME node result fields must match exactly",
                )
            portfolio = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO,
            )
            members = list(portfolio["volume_plan_versions"])
            cursor_matches = [
                item
                for item in members
                if isinstance(item.get("chapter_range"), list)
                and len(item["chapter_range"]) == 2
                and int(item["chapter_range"][0]) <= 1 <= int(item["chapter_range"][1])
            ]
            if len(cursor_matches) != 1:
                raise KernelError(
                    "BOOK_OPENING_CURRENT_VOLUME_AMBIGUOUS",
                    "chapter cursor one does not resolve to exactly one portfolio member",
                )
            item = cursor_matches[0]
            if (
                _canonical_hash(members) != str(result["volume_portfolio_hash"])
                or str(result["current_volume_plan_version_id"])
                != str(item["asset_version_id"])
                or str(result["current_volume_content_hash"])
                != str(item["content_hash"])
                or result["chapter_range"] != list(item["chapter_range"])
            ):
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
                    "current Volume differs from its portfolio receipt",
                )
            artifact = plan(
                asset_version_id=str(item["asset_version_id"]),
                content_hash=str(item["content_hash"]),
                binding_id=str(item["binding_id"]),
                contract_type="VOLUME",
                logical_key=str(item["logical_key"]),
            )
            if self._chapter_range(dict(artifact["content"])) != tuple(
                item["chapter_range"]
            ):
                raise KernelError(
                    "BOOK_OPENING_NODE_ARTIFACT_DRIFT",
                    "current Volume range differs from its active Plan Authority",
                )
            inner.append(plan_identity(artifact))
            assets.append(artifact["asset_version_id"])
            artifact_kind = "CURRENT_VOLUME_PLAN"
        elif node_kind is BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE:
            if (
                set(result)
                != {
                    "current_volume_plan_version_id",
                    "volume_portfolio_plan_version_ids",
                    "arc_scope_hash",
                    "arc_plan_versions",
                    "current_relevant_arc_plan_version_ids",
                }
                or not isinstance(result.get("arc_plan_versions"), list)
                or not result["arc_plan_versions"]
                or not isinstance(result.get("volume_portfolio_plan_version_ids"), list)
                or not isinstance(
                    result.get("current_relevant_arc_plan_version_ids"), list
                )
            ):
                raise KernelError(
                    "BOOK_OPENING_NODE_RESULT_INVALID",
                    "INITIAL_ARC_SCOPE node result fields must match exactly",
                )
            current = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.CURRENT_VOLUME,
            )
            if str(result["current_volume_plan_version_id"]) != str(
                current["current_volume_plan_version_id"]
            ):
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
                    "Arc scope differs from the current Volume receipt",
                )
            portfolio = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO,
            )
            portfolio_ids = [
                str(item["asset_version_id"])
                for item in portfolio["volume_plan_versions"]
            ]
            request = OpenBookProductionRequest.from_mapping(
                dict(run["frozen_request"])
            )
            expected_scope_hash = _canonical_hash(
                {
                    "arc_logical_keys": list(request.arc_logical_keys),
                    "current_volume_plan_version_id": str(
                        current["current_volume_plan_version_id"]
                    ),
                    "volume_portfolio_plan_version_ids": portfolio_ids,
                }
            )
            if (
                list(result["volume_portfolio_plan_version_ids"]) != portfolio_ids
                or str(result["arc_scope_hash"]) != expected_scope_hash
                or len(result["arc_plan_versions"]) != len(request.arc_logical_keys)
            ):
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
                    "Arc scope differs from its frozen Volume and Arc portfolio",
                )
            for expected_key, raw in zip(
                request.arc_logical_keys, result["arc_plan_versions"], strict=True
            ):
                if not isinstance(raw, Mapping) or set(raw) != {
                    "logical_key",
                    "search_id",
                    "asset_version_id",
                    "content_hash",
                    "binding_id",
                }:
                    raise KernelError(
                        "BOOK_OPENING_NODE_RESULT_INVALID",
                        "Arc Portfolio member identity is invalid",
                    )
                if str(raw["logical_key"]) != expected_key:
                    raise KernelError(
                        "BOOK_OPENING_NODE_RESULT_INVALID",
                        "Arc Portfolio order differs from the frozen Arc scope",
                    )
                artifact = plan(
                    asset_version_id=str(raw["asset_version_id"]),
                    content_hash=str(raw["content_hash"]),
                    binding_id=str(raw["binding_id"]),
                    contract_type="ARC",
                    logical_key=str(raw["logical_key"]),
                )
                inner.extend(
                    (
                        plan_identity(artifact),
                        search(str(raw["search_id"]), artifact["asset_version_id"]),
                    )
                )
                assets.append(artifact["asset_version_id"])
            if list(result["current_relevant_arc_plan_version_ids"]) != assets:
                raise KernelError(
                    "BOOK_OPENING_NODE_RESULT_INVALID",
                    "current relevant Arc identity differs from the Arc Portfolio",
                )
            artifact_kind = "INITIAL_ARC_SCOPE"
        else:
            expected = {
                "snapshot_id",
                "snapshot_hash",
                "book_design_version",
                "book_plan_version",
                "volume_portfolio_plan_versions",
                "current_volume_plan_version",
                "arc_portfolio_plan_versions",
                "current_relevant_arc_plan_versions",
            }
            if set(result) != expected:
                raise KernelError(
                    "BOOK_OPENING_NODE_RESULT_INVALID",
                    "INPUT_SNAPSHOT node result fields must match exactly",
                )
            uow.cursor.execute(
                """
                SELECT snapshot_hash,book_design_version,book_plan_version,
                       volume_portfolio_plan_versions,
                       current_volume_plan_version,arc_portfolio_plan_versions,
                       current_relevant_arc_plan_versions,workspace_id,book_id
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s AND project_id=%s
                FOR SHARE
                """,
                [result["snapshot_id"], run["project_id"]],
            )
            row = uow.cursor.fetchone()
            expected_values = (
                str(result["snapshot_hash"]),
                str(result["book_design_version"]),
                str(result["book_plan_version"]),
                list(result["volume_portfolio_plan_versions"]),
                str(result["current_volume_plan_version"]),
                list(result["arc_portfolio_plan_versions"]),
                list(result["current_relevant_arc_plan_versions"]),
                str(run["workspace_id"]),
                str(run["book_id"]),
            )
            if row is None or tuple(row) != expected_values:
                raise KernelError(
                    "BOOK_OPENING_NODE_ARTIFACT_DRIFT",
                    "Input Snapshot differs from the Book Authority result",
                )
            book = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.BOOK_PLAN,
            )
            portfolio = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO,
            )
            current = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.CURRENT_VOLUME,
            )
            arcs = self._node_receipt_result_in_uow(
                uow,
                str(run["opening_run_id"]),
                BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE,
            )
            exact_predecessor_identity = (
                str(result["book_plan_version"]) == str(book["asset_version_id"])
                and list(result["volume_portfolio_plan_versions"])
                == [
                    str(item["asset_version_id"])
                    for item in portfolio["volume_plan_versions"]
                ]
                and str(result["current_volume_plan_version"])
                == str(current["current_volume_plan_version_id"])
                and list(result["arc_portfolio_plan_versions"])
                == [str(item["asset_version_id"]) for item in arcs["arc_plan_versions"]]
                and list(result["current_relevant_arc_plan_versions"])
                == list(arcs["current_relevant_arc_plan_version_ids"])
            )
            if not exact_predecessor_identity:
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_PREDECESSOR_DRIFT",
                    "Input Snapshot does not bind the exact completed planning layers",
                )
            inner.append(
                {
                    "snapshot_id": str(result["snapshot_id"]),
                    "snapshot_hash": str(result["snapshot_hash"]),
                }
            )
            artifact_kind = "BOOK_PRODUCTION_INPUT_SNAPSHOT"

        return {
            "reviewable_artifact_kind": artifact_kind,
            "reviewable_asset_version_ids": assets,
            "authoritative_inner_evidence": inner,
        }

    @staticmethod
    def _workflow_node_search_ids(
        node_kind: BookOpeningWorkflowNodeKind,
        result: Mapping[str, Any],
    ) -> tuple[str, ...]:
        if node_kind is BookOpeningWorkflowNodeKind.BOOK_PLAN:
            return (str(result["search_id"]),)
        collection_name = (
            "volume_plan_versions"
            if node_kind is BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO
            else "arc_plan_versions"
            if node_kind is BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE
            else ""
        )
        if not collection_name:
            return ()
        return tuple(str(item["search_id"]) for item in result[collection_name])

    @staticmethod
    def _node_receipt_result_in_uow(
        uow: AuthorityUnitOfWork,
        opening_run_id: str,
        node_kind: BookOpeningWorkflowNodeKind,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT receipt.result,receipt.result_hash
            FROM authority_book_opening_node_receipt AS receipt
            JOIN authority_book_opening_workflow_node AS node
              ON node.workflow_node_id=receipt.workflow_node_id
             AND node.opening_run_id=receipt.opening_run_id
            WHERE receipt.opening_run_id=%s AND node.node_kind=%s
            FOR SHARE OF receipt,node
            """,
            [opening_run_id, node_kind.value],
        )
        row = uow.cursor.fetchone()
        if row is None or _canonical_hash(dict(row[0])) != str(row[1]):
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_PREDECESSOR_REQUIRED",
                f"{node_kind.value} has no exact durable node receipt",
            )
        return dict(row[0])

    @staticmethod
    def _workflow_successor_in_uow(
        uow: AuthorityUnitOfWork,
        *,
        opening_run_id: str,
        workflow_node_id: str,
        ordinal: int,
    ) -> dict[str, Any] | None:
        uow.cursor.execute(
            """
            SELECT successor.workflow_node_id,successor.node_kind,
                   successor.node_key,successor.ordinal,successor.input_hash
            FROM authority_book_opening_workflow_edge AS edge
            JOIN authority_book_opening_workflow_node AS successor
              ON successor.workflow_node_id=edge.successor_workflow_node_id
             AND successor.opening_run_id=edge.opening_run_id
            WHERE edge.opening_run_id=%s
              AND edge.predecessor_workflow_node_id=%s
              AND edge.edge_kind='REQUIRES'
            FOR SHARE OF edge,successor
            """,
            [opening_run_id, workflow_node_id],
        )
        rows = uow.cursor.fetchall()
        if not rows:
            return None
        if len(rows) != 1 or int(rows[0][3]) != ordinal + 1:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_GRAPH_CONFLICT",
                "workflow node has an ambiguous or non-linear successor",
            )
        row = rows[0]
        return {
            "workflow_node_id": str(row[0]),
            "node_kind": str(row[1]),
            "node_key": str(row[2]),
            "ordinal": int(row[3]),
            "input_hash": str(row[4]),
        }

    def _aggregate_workflow_result_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        opening_run_id: str,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT node.node_kind,receipt.node_receipt_id,
                   receipt.result,receipt.result_hash
            FROM authority_book_opening_workflow_node AS node
            JOIN authority_book_opening_node_receipt AS receipt
              ON receipt.workflow_node_id=node.workflow_node_id
             AND receipt.opening_run_id=node.opening_run_id
            WHERE node.opening_run_id=%s
            ORDER BY node.ordinal
            FOR SHARE OF node,receipt
            """,
            [opening_run_id],
        )
        rows = uow.cursor.fetchall()
        if len(rows) != len(BookOpeningWorkflowNodeKind):
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_INCOMPLETE",
                "Book Opening cannot complete before all five node receipts exist",
            )
        by_kind: dict[BookOpeningWorkflowNodeKind, dict[str, Any]] = {}
        receipt_ids: list[str] = []
        for kind, receipt_id, raw_result, result_hash in rows:
            result = dict(raw_result)
            if _canonical_hash(result) != str(result_hash):
                raise KernelError(
                    "BOOK_OPENING_NODE_RECEIPT_DRIFT",
                    "Book Opening aggregate contains a drifted node receipt",
                )
            by_kind[BookOpeningWorkflowNodeKind(str(kind))] = result
            receipt_ids.append(str(receipt_id))
        book = by_kind[BookOpeningWorkflowNodeKind.BOOK_PLAN]
        volumes = by_kind[BookOpeningWorkflowNodeKind.VOLUME_PORTFOLIO]
        current = by_kind[BookOpeningWorkflowNodeKind.CURRENT_VOLUME]
        arcs = by_kind[BookOpeningWorkflowNodeKind.INITIAL_ARC_SCOPE]
        snapshot = by_kind[BookOpeningWorkflowNodeKind.INPUT_SNAPSHOT]
        search_ids = [
            str(book["search_id"]),
            *(str(item["search_id"]) for item in volumes["volume_plan_versions"]),
            *(str(item["search_id"]) for item in arcs["arc_plan_versions"]),
        ]
        return BookOpeningWorkflowResult(
            book_design_version=str(snapshot["book_design_version"]),
            book_plan_version=str(book["asset_version_id"]),
            volume_portfolio_plan_versions=tuple(
                str(item["asset_version_id"])
                for item in volumes["volume_plan_versions"]
            ),
            current_volume_plan_version=str(current["current_volume_plan_version_id"]),
            arc_portfolio_plan_versions=tuple(
                str(item["asset_version_id"]) for item in arcs["arc_plan_versions"]
            ),
            current_relevant_arc_plan_versions=tuple(
                arcs["current_relevant_arc_plan_version_ids"]
            ),
            input_snapshot_id=str(snapshot["snapshot_id"]),
            search_ids=tuple(search_ids),
            node_receipt_ids=tuple(receipt_ids),
        ).to_dict()

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

    @staticmethod
    def _persist_workflow_graph_in_uow(
        uow: AuthorityUnitOfWork,
        workflow: BookOpeningWorkflow,
    ) -> None:

        for node in workflow.nodes:
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_workflow_node(
                    workflow_node_id,opening_run_id,node_key,node_kind,ordinal,
                    input_contract,input_hash,graph_revision,
                    stable_idempotency_key
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (workflow_node_id) DO NOTHING
                """,
                [
                    node.workflow_node_id,
                    workflow.opening_run_id,
                    node.node_key,
                    node.kind.value,
                    node.ordinal,
                    Jsonb(dict(node.input_contract)),
                    node.input_hash,
                    workflow.graph_revision,
                    node.stable_idempotency_key,
                ],
            )
            uow.cursor.execute(
                """
                SELECT opening_run_id,node_key,node_kind,ordinal,input_contract,
                       input_hash,graph_revision,stable_idempotency_key
                FROM authority_book_opening_workflow_node
                WHERE workflow_node_id=%s
                """,
                [node.workflow_node_id],
            )
            stored = uow.cursor.fetchone()
            expected = (
                workflow.opening_run_id,
                node.node_key,
                node.kind.value,
                node.ordinal,
                dict(node.input_contract),
                node.input_hash,
                workflow.graph_revision,
                node.stable_idempotency_key,
            )
            if stored is None or tuple(stored) != expected:
                raise KernelError(
                    "BOOK_OPENING_WORKFLOW_GRAPH_CONFLICT",
                    "workflow node identity differs from its immutable graph",
                )
        for edge in workflow.edges:
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_workflow_edge(
                    opening_run_id,predecessor_workflow_node_id,
                    successor_workflow_node_id,edge_kind
                ) VALUES (%s,%s,%s,'REQUIRES')
                ON CONFLICT DO NOTHING
                """,
                [
                    workflow.opening_run_id,
                    edge.parent_node_id,
                    edge.child_node_id,
                ],
            )
        uow.cursor.execute(
            """
            SELECT predecessor_workflow_node_id,successor_workflow_node_id,
                   edge_kind
            FROM authority_book_opening_workflow_edge
            WHERE opening_run_id=%s
            ORDER BY predecessor_workflow_node_id,successor_workflow_node_id
            """,
            [workflow.opening_run_id],
        )
        stored_edges = {
            (str(row[0]), str(row[1]), str(row[2])) for row in uow.cursor.fetchall()
        }
        expected_edges = {
            (edge.parent_node_id, edge.child_node_id, edge.relation)
            for edge in workflow.edges
        }
        if stored_edges != expected_edges:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_GRAPH_CONFLICT",
                "workflow edges differ from the immutable five-layer graph",
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
            request.production_profile,
            request.initial_story_state_version,
            request.initial_canon_snapshot_version,
            *(request.planning_replacement or {}).get("expected_active_plan_versions", {}).values(),
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

    @staticmethod
    def _lock_and_require_opening_input_assets_in_uow(
        cursor: Any,
        *,
        request: OpenBookProductionRequest,
        input_asset_snapshot: object,
    ) -> None:
        requested = {
            *request.planning_input_versions.values(),
            request.production_profile,
            request.initial_story_state_version,
            request.initial_canon_snapshot_version,
            *(request.planning_replacement or {}).get("expected_active_plan_versions", {}).values(),
        }
        if not isinstance(input_asset_snapshot, list):
            raise KernelError(
                "BOOK_OPENING_INPUT_ASSET_DRIFT",
                "Book Opening Operation has no frozen input-asset snapshot",
            )
        frozen: dict[str, str] = {}
        for raw in input_asset_snapshot:
            if not isinstance(raw, Mapping):
                raise KernelError(
                    "BOOK_OPENING_INPUT_ASSET_DRIFT",
                    "Book Opening input-asset snapshot is malformed",
                )
            asset_version_id = str(raw.get("asset_version_id") or "")
            content_hash = str(raw.get("content_hash") or "")
            if (
                not asset_version_id
                or not content_hash.startswith("sha256:")
                or asset_version_id in frozen
            ):
                raise KernelError(
                    "BOOK_OPENING_INPUT_ASSET_DRIFT",
                    "Book Opening input-asset snapshot is not canonical",
                )
            frozen[asset_version_id] = content_hash
        if set(frozen) != requested:
            raise KernelError(
                "BOOK_OPENING_INPUT_ASSET_DRIFT",
                "Book Opening Operation inputs differ from its frozen request",
            )
        cursor.execute(
            """
            SELECT version.asset_version_id,version.content_hash,
                   version.lifecycle,version.eligibility,version.governance,
                   asset.project_id,asset.asset_type
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE version.asset_version_id=ANY(%s)
            ORDER BY version.asset_version_id
            FOR SHARE OF version,asset
            """,
            [sorted(requested)],
        )
        rows = cursor.fetchall()
        current = {str(row[0]): str(row[1]) for row in rows}
        if current != frozen or any(
            tuple(str(value) for value in row[2:6])
            != ("ACTIVE", "ELIGIBLE", "CLEAR", request.project_id)
            or not str(row[6])
            for row in rows
        ):
            raise KernelError(
                "BOOK_OPENING_INPUT_ASSET_DRIFT",
                "Book Opening inputs are no longer active governed Project assets",
            )

    def _bind_running_execution(
        self,
        opening_run_id: str,
        *,
        expected_version: int,
        runtime_claim: RuntimeJobClaim,
    ) -> None:

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
                       recovery_state,workflow_contract_version,
                       current_workflow_node_id,workflow_graph_revision,
                       workflow_graph_hash,execution_contract_version
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
                       recovery_intent_id,workflow_node_id,
                       workflow_transition_kind,source_checkpoint_id,
                       source_checkpoint_sequence,source_checkpoint_hash
                FROM authority_book_opening_execution
                WHERE opening_run_id=%s AND opening_execution_id=%s
                  AND generation=%s
                FOR UPDATE
                """,
                [opening_run_id, str(opening[1]), int(opening[2])],
            )
            execution = uow.cursor.fetchone()
            expected_execution_contract = book_opening_execution_contract_version(
                str(opening[7] or "")
            )
            expected_job_kind, expected_runtime_group = (
                book_opening_runtime_job_identity(str(opening[7] or ""))
            )
            if (
                execution is None
                or str(execution[0]) not in {"BOUND", "RUNNING"}
                or str(execution[2]) != runtime_claim.runtime_job_id
                or str(execution[4]) != str(opening[3])
                or str(execution[5]) != self.recovery._execution_policy_digest()
                or str(execution[6])
                != self.recovery._authority_digest(expected_execution_contract)
                or str(execution[7]) != runtime_claim.attempt_id
                or str(execution[8]) != runtime_claim.lease_id
                or str(execution[9]) != runtime_claim.worker_id
                or int(execution[10] or 0) != runtime_claim.fencing_token
                or str(opening[11]) != expected_execution_contract
                or runtime_claim.job_kind != expected_job_kind
                or runtime_claim.runtime_group != expected_runtime_group
                or (
                    str(opening[7] or "") == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION
                    and (
                        str(execution[12] or "") != str(opening[8] or "")
                        or str(
                            runtime_claim.input_snapshot.get("workflow_node_id") or ""
                        )
                        != str(opening[8] or "")
                        or int(
                            runtime_claim.input_snapshot.get("workflow_graph_revision")
                            or 0
                        )
                        != int(opening[9] or 0)
                        or str(
                            runtime_claim.input_snapshot.get("workflow_graph_hash")
                            or ""
                        )
                        != str(opening[10] or "")
                        or str(
                            runtime_claim.input_snapshot.get("workflow_transition_kind")
                            or ""
                        )
                        != str(execution[13] or "")
                    )
                )
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

    def _admission_job(self, opening_run_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT job.runtime_job_id,job.status
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_run_id=opening.opening_run_id
                 AND execution.generation=1
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                 AND job.subject_kind='BOOK_OPENING_RUN'
                 AND job.subject_id=opening.opening_run_id
                 AND (
                     (
                         opening.workflow_contract_version=
                             'book-opening-workflow-v1'
                         AND opening.execution_contract_version=
                             'book-opening-execution-v3'
                         AND job.job_kind=
                             'BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                         AND job.runtime_group='book_opening_workflow_v1'
                         AND execution.workflow_transition_kind='ADMISSION'
                     ) OR (
                         opening.workflow_contract_version=
                             'legacy-monolithic-v2'
                         AND opening.execution_contract_version=
                             'book-opening-execution-v2'
                         AND job.job_kind='BOOK_OPENING_EXECUTE'
                         AND job.runtime_group='book_opening'
                         AND execution.workflow_transition_kind=
                             'LEGACY_MONOLITHIC'
                     )
                 )
                WHERE opening.opening_run_id=%s
                """,
                [opening_run_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_JOB_MISSING",
                "Book opening admission has no durable initial RuntimeJob lineage",
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
        arc_scope_volume_plan_version_ids: tuple[str, ...] = (),
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
            arc_scope_volume_plan_version_ids=(arc_scope_volume_plan_version_ids),
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
            ),
            accepted_through_chapter=0,
            parent_state_asset_version_id=accepted_state,
            expected_active_asset_version_id=str(
                (request.planning_replacement or {}).get("expected_active_plan_versions", {}).get(logical_key, "")
            ),
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
                expected_branch_keys=self.narrative_search.selected_branch_keys(search_id,
                    expected_branch_keys=tuple(f"future-{ordinal}" for ordinal in range(1,len(search_request.strategy_directives)+1))),
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
            return self._require_qualified_foundation_in_uow(uow.cursor, request)

    @staticmethod
    def _require_qualified_foundation_in_uow(
        cursor: Any, request: OpenBookProductionRequest
    ) -> str:
        cursor.execute(
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
            FOR UPDATE OF book
            """,
            [
                request.project_id,
                request.workspace_id,
                request.book_id,
                request.expected_book_version,
            ],
        )
        row = cursor.fetchone()
        if (
            row is None
            or str(row[1])
            not in {FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION, "book-design.v6", "book-design.v7"}
            or tuple(str(item) for item in row[2:5]) != ("ACTIVE", "ELIGIBLE", "CLEAR")
        ):
            raise KernelError(
                "BOOK_OPENING_FOUNDATION_REQUIRED",
                "Book opening requires the exact active and qualified Foundation synthesis",
            )
        cursor.execute(
            """
            SELECT formation_run_id
            FROM authority_story_formation_run
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
            ORDER BY formation_run_id
            FOR SHARE
            """,
            [request.project_id, request.workspace_id, request.book_id],
        )
        cursor.fetchall()
        foundation = require_current_foundation_set(
            cursor,
            project_id=request.project_id,
            book_id=request.book_id,
            require_ready=True,
            lock=True,
        )
        design = BookDesignPayload.from_mapping(dict(row[6]))
        if design.foundation_set != foundation:
            raise KernelError(
                "BOOK_OPENING_FOUNDATION_DRIFT",
                "BookDesign does not bind the current qualified Foundation Set",
            )
        cursor.execute(
            """
            SELECT formation_run_id
            FROM authority_story_formation_run
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
              AND lifecycle='READY' AND current_stage='COMPLETE'
              AND foundation_set_digest=%s
              AND book_design_asset_version_id=%s
              AND book_design_content_hash=%s
              AND NOT EXISTS(SELECT 1 FROM authority_story_creation_cancellation cancellation
                WHERE cancellation.formation_run_id=authority_story_formation_run.formation_run_id)
            ORDER BY updated_at DESC
            LIMIT 1
            FOR SHARE
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
        if cursor.fetchone() is None:
            raise KernelError(
                "BOOK_OPENING_FORMATION_NOT_READY",
                "Book opening requires a READY durable Story Formation bound to the active synthesis",
            )
        return str(row[0])

    def _production_target_chapters(self, request: OpenBookProductionRequest) -> int:
        with AuthorityUnitOfWork(self.database_url) as uow:
            return self._production_target_chapters_in_uow(uow.cursor, request)

    @staticmethod
    def _production_target_chapters_in_uow(
        cursor: Any, request: OpenBookProductionRequest
    ) -> int:
        cursor.execute(
            """
            SELECT version.content
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
            WHERE version.asset_version_id=%s
              AND asset.project_id=%s
              AND version.lifecycle='ACTIVE'
              AND version.eligibility='ELIGIBLE'
              AND version.governance='CLEAR'
            FOR SHARE OF version
            """,
            [request.production_profile, request.project_id],
        )
        row = cursor.fetchone()
        content = dict(row[0]) if row is not None else {}
        target = content.get("target_chapter_count")
        if not isinstance(target, int) or isinstance(target, bool) or target <= 0:
            raise KernelError(
                "BOOK_OPENING_PRODUCTION_TARGET_REQUIRED",
                "Book Opening requires one positive frozen Production Profile chapter target",
            )
        return target

    @staticmethod
    def _require_canonical_opening_inputs(
        request: OpenBookProductionRequest,
    ) -> None:
        if set(request.planning_input_versions) != _OPENING_INPUT_ROLES:
            raise KernelError(
                "BOOK_OPENING_INPUTS_INVALID",
                "Book Opening inputs must exactly match the governed Planning roles",
            )
        if (
            str(request.planning_input_versions.get("production_profile") or "")
            != request.production_profile
        ):
            raise KernelError(
                "BOOK_OPENING_PRODUCTION_PROFILE_DRIFT",
                "Book Opening requires one canonical Production Profile identity",
            )
        if (
            str(request.planning_input_versions.get("story_state") or "")
            != request.initial_story_state_version
            or str(request.planning_input_versions.get("canon_snapshot") or "")
            != request.initial_canon_snapshot_version
        ):
            raise KernelError(
                "BOOK_OPENING_ACCEPTED_BOUNDARY_DRIFT",
                "Book Opening requires one canonical accepted Story State and Canon boundary",
            )


def book_opening_capacity_continuation_definition(*, application_build_id: str, commit_sha: str) -> dict[str, Any]:
    return _opening_definition("book.opening.continue_unstarted", application_build_id=application_build_id, commit_sha=commit_sha)


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
        "definition_version": _opening_definition_version(name),
        "family": "book_authority",
        "enabled": True,
        "definition_status": "implemented",
        "command_schema_version": "book-opening-command.v1",
        "result_schema_version": (
            "book-opening-workflow-result.v3"
            if name == "book.opening.complete_node"
            else "book-opening-result.v1"
        ),
        "command_schema": schema,
        "result_schema": {"type": "object"},
        "input_contract": schema,
        "output_contract": {
            "type": (
                "BookOpeningWorkflowNodeTransition"
                if name == "book.opening.complete_node"
                else "BookOpeningTransition"
            )
        },
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
