from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.authority_security import Principal
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.budget_runtime import (
    BudgetAssessmentOutcome,
    assess_budget_scope_in_uow,
)
from novel_forge.modules.runtime_job import (
    AUTHORITY_CONVERGENCE_REQUIRED,
    BOOK_OPENING_LEGACY_JOB_KIND,
    BOOK_OPENING_LEGACY_RUNTIME_GROUP,
    BOOK_OPENING_WORKFLOW_JOB_KIND,
    BOOK_OPENING_WORKFLOW_RUNTIME_GROUP,
    RuntimeJobAuthority,
    RuntimeJobClaim,
    RuntimeJobSpec,
)
from novel_forge.modules.story_design_authority.evaluation_runtime import (
    classify_narrative_evaluation_external_effects,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .opening_workflow import BOOK_OPENING_WORKFLOW_CONTRACT_VERSION


BOOK_OPENING_EXECUTION_CONTRACT_VERSION = "book-opening-execution-v2"
BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION = "book-opening-execution-v3"
BOOK_OPENING_LEGACY_WORKFLOW_CONTRACT_VERSION = "legacy-monolithic-v2"
BOOK_OPENING_EXECUTION_POLICY_VERSION = "book-opening-execution-policy-v1"
BOOK_OPENING_RECOVERY_POLICY_VERSION = "book-opening-recovery-v1"
BOOK_OPENING_AUTHORITY_VERSION = "book-opening-authority-v2"
BOOK_OPENING_MAX_SEMANTIC_EVALUATION_GENERATIONS = 3


def book_opening_execution_contract_version(workflow_contract_version: str) -> str:
    if workflow_contract_version == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION:
        return BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION
    if workflow_contract_version == BOOK_OPENING_LEGACY_WORKFLOW_CONTRACT_VERSION:
        return BOOK_OPENING_EXECUTION_CONTRACT_VERSION
    raise KernelError(
        "BOOK_OPENING_WORKFLOW_CONTRACT_UNSUPPORTED",
        "Book Opening has no supported execution contract",
    )


def book_opening_runtime_job_identity(
    workflow_contract_version: str,
) -> tuple[str, str]:
    if workflow_contract_version == BOOK_OPENING_WORKFLOW_CONTRACT_VERSION:
        return BOOK_OPENING_WORKFLOW_JOB_KIND, BOOK_OPENING_WORKFLOW_RUNTIME_GROUP
    if workflow_contract_version == BOOK_OPENING_LEGACY_WORKFLOW_CONTRACT_VERSION:
        return BOOK_OPENING_LEGACY_JOB_KIND, BOOK_OPENING_LEGACY_RUNTIME_GROUP
    raise KernelError(
        "BOOK_OPENING_WORKFLOW_CONTRACT_UNSUPPORTED",
        "Book Opening has no supported RuntimeJob capability",
    )


def _runtime_job_identity_for_execution_contract(
    execution_contract_version: str,
) -> tuple[str, str]:
    if execution_contract_version == BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION:
        return BOOK_OPENING_WORKFLOW_JOB_KIND, BOOK_OPENING_WORKFLOW_RUNTIME_GROUP
    if execution_contract_version == BOOK_OPENING_EXECUTION_CONTRACT_VERSION:
        return BOOK_OPENING_LEGACY_JOB_KIND, BOOK_OPENING_LEGACY_RUNTIME_GROUP
    raise KernelError(
        "BOOK_OPENING_EXECUTION_CONTRACT_UNSUPPORTED",
        "Book Opening has no supported RuntimeJob capability",
    )


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    identity = "\x1f".join(str(item) for item in parts)
    return f"{prefix}:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


class SemanticReplacementApplication(Protocol):
    def admit_replacement_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        predecessor_operation_id: str,
        recovery_intent_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        expected_head_generation: int,
        expected_head_version: int,
    ) -> dict[str, Any]: ...

    def cancel_unstarted_replacement_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def abort_opening_owned_execution_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        evaluation_execution_id: str,
        generation: int,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def release_replacement_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        operation_id: str,
        recovery_intent_id: str,
        actor_id: str,
        trace_id: str,
        correlation_id: str,
        causation_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RecoveryAssessment:
    recovery_assessment_id: str
    assessment_kind: str
    opening_run_id: str
    disposition: str
    snapshot_hash: str
    snapshot: dict[str, Any]
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecoveryReceipt:
    recovery_receipt_id: str
    receipt_kind: str
    opening_run_id: str
    recovery_assessment_id: str
    recovery_intent_id: str
    result_hash: str
    result: dict[str, Any]
    replayed: bool


class PostgresBookOpeningRecoveryApplication:

    def __init__(
        self,
        database_url: str,
        *,
        application_build_id: str,
        commit_sha: str,
        semantic_replacement: SemanticReplacementApplication | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        if not database_url or not application_build_id or len(commit_sha) != 40:
            raise ValueError("Book Opening recovery requires PostgreSQL/build identity")
        self.database_url = database_url
        self.application_build_id = application_build_id
        self.commit_sha = commit_sha
        self.runtime_jobs = RuntimeJobAuthority(database_url)
        self.semantic_replacement = semantic_replacement
        self.fault_injector = fault_injector

    def reconcile_legacy_execution(
        self,
        opening_run_id: str,
        *,
        idempotency_key: str,
        principal: Principal,
    ) -> RecoveryReceipt:

        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            replay = self._receipt_by_key(
                uow,
                opening_run_id,
                "LEGACY_EXECUTION_RECONCILIATION",
                idempotency_key,
            )
            if replay is not None:
                return self._receipt_result(replay, replayed=True)
            if run["current_execution_id"]:
                raise KernelError(
                    "BOOK_OPENING_RECONCILIATION_ALREADY_BOUND",
                    "Book Opening already has an execution identity",
                )
            if str(run["execution_contract_version"]) != "legacy-unbound":
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_CONTRACT_DRIFT",
                    "legacy reconciliation requires an unbound legacy Opening",
                )
            execution_id = _stable_id("book-opening-execution", opening_run_id, 1)
            binding = self._legacy_runtime_binding(
                uow,
                run,
                execution_id=execution_id,
            )
            snapshot = {
                "opening_run_id": opening_run_id,
                "opening_version": int(run["version"]),
                "opening_lifecycle": str(run["lifecycle"]),
                "frozen_request_digest": str(run["frozen_request_digest"]),
                "runtime": binding,
                "checkpoint": None,
                "semantic_progress_reconciled": False,
                "execution_contract_version": BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
            }
            lifecycle = str(binding["execution_lifecycle"])
            terminal = lifecycle in {"FAILED", "LOST", "ABORTED"}
            terminal_reason = dict(binding.get("terminal_reason") or {})
            # WHY: The execution row validates the exact workflow/execution contract
            # pair at INSERT time. Advance the locked compatibility run first;
            # the execution and current pointer remain in this UoW so an
            # insert/final-CAS failure cannot leave a partial reconciliation.
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET execution_contract_version=%s
                WHERE opening_run_id=%s AND version=%s
                  AND current_execution_id IS NULL
                  AND execution_contract_version='legacy-unbound'
                  AND workflow_contract_version='legacy-monolithic-v2'
                  AND lifecycle IN ('ADMITTED','RUNNING','FAILED')
                """,
                [
                    BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
                    opening_run_id,
                    run["version"],
                ],
            )
            if uow.cursor.rowcount != 1:
                self._stale("legacy Opening contract advancement changed")
            bound_run = {
                **run,
                "execution_contract_version": BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
            }
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_execution(
                    opening_execution_id,opening_run_id,generation,
                    runtime_job_id,current_attempt_id,current_lease_id,
                    current_worker_id,current_fencing_token,lifecycle,
                    frozen_request_digest,input_snapshot_hash,
                    policy_snapshot_hash,authority_contract_hash,
                    terminal_reason,terminal_at
                ) VALUES (%s,%s,1,%s,NULLIF(%s,''),NULLIF(%s,''),
                          NULLIF(%s,''),NULLIF(%s,0),%s,%s,%s,%s,%s,%s,
                          CASE WHEN %s THEN transaction_timestamp() END)
                """,
                [
                    execution_id,
                    opening_run_id,
                    binding["runtime_job_id"],
                    binding["attempt_id"],
                    binding["lease_id"],
                    binding["worker_id"],
                    binding.get("fencing_token"),
                    lifecycle,
                    run["frozen_request_digest"],
                    binding["input_hash"],
                    self._execution_policy_digest(),
                    self._authority_digest(),
                    Jsonb(terminal_reason),
                    terminal,
                ],
            )
            assessment_id = self._insert_assessment(
                uow,
                run=bound_run,
                kind="LEGACY_EXECUTION_RECONCILIATION",
                idempotency_key=idempotency_key,
                snapshot=snapshot,
                disposition="RECONCILIATION_REQUIRED",
                execution={
                    "opening_execution_id": execution_id,
                    "generation": 1,
                },
            )
            if terminal:
                failure = {
                    "code": "BOOK_OPENING_LEGACY_EXECUTION_UNRECOVERABLE",
                    "opening_execution_id": execution_id,
                    "runtime_job_id": binding["runtime_job_id"],
                    "runtime_history_digest": binding["runtime_history_digest"],
                    "terminal_lifecycle": lifecycle,
                }
                uow.cursor.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_execution_id=%s,
                        current_execution_generation=1,lifecycle='FAILED',
                        failure=%s,recovery_instruction=%s,
                        recovery_state='RECOVERY_REQUIRED',version=version+1,
                        updated_at=transaction_timestamp()
                    WHERE opening_run_id=%s AND version=%s
                      AND current_execution_id IS NULL
                      AND execution_contract_version=%s
                      AND lifecycle IN ('ADMITTED','RUNNING','FAILED')
                    """,
                    [
                        execution_id,
                        Jsonb(failure),
                        Jsonb(
                            {
                                "action": "ASSESS_BOOK_OPENING_RECOVERY",
                                "opening_run_id": opening_run_id,
                            }
                        ),
                        opening_run_id,
                        run["version"],
                        BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
                    ],
                )
            else:
                uow.cursor.execute(
                    """
                    UPDATE authority_book_opening_run
                    SET current_execution_id=%s,
                        current_execution_generation=1,
                        recovery_state='READY',version=version+1,
                        updated_at=transaction_timestamp()
                    WHERE opening_run_id=%s AND version=%s
                      AND current_execution_id IS NULL
                      AND execution_contract_version=%s
                      AND lifecycle IN ('ADMITTED','RUNNING')
                    """,
                    [
                        execution_id,
                        opening_run_id,
                        run["version"],
                        BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
                    ],
                )
            if uow.cursor.rowcount != 1:
                self._stale("legacy Opening binding changed")
            result = {
                "opening_execution_id": execution_id,
                "execution_generation": 1,
                "runtime_job_id": binding["runtime_job_id"],
                "execution_lifecycle": lifecycle,
                "opening_lifecycle": "FAILED" if terminal else run["lifecycle"],
                "runtime_history_digest": binding["runtime_history_digest"],
                "semantic_progress_reconciled": False,
                "provider_invoked": False,
            }
            receipt = self._insert_receipt(
                uow,
                run=bound_run,
                kind="LEGACY_EXECUTION_RECONCILIATION",
                assessment_id=assessment_id,
                intent_id="",
                predecessor_execution=(execution_id, 1),
                successor_execution=None,
                idempotency_key=idempotency_key,
                result=result,
            )
            self._record_event(
                uow,
                bound_run,
                "book.opening.legacy_execution_reconciled",
                {**result, "recovery_assessment_id": assessment_id},
            )
            uow.commit()
        return self._receipt_result(receipt, replayed=False)

    def assess_execution_loss(
        self,
        opening_run_id: str,
        *,
        idempotency_key: str,
        principal: Principal,
    ) -> RecoveryAssessment:
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            existing = self._assessment_by_key(
                uow, opening_run_id, "EXECUTION_LOSS", idempotency_key
            )
            if existing is not None:
                return self._assessment_result(existing, replayed=True)
            execution = self._current_execution(uow, run, lock=True)
            active_pair = (str(run["lifecycle"]), str(execution["lifecycle"])) in {
                ("ADMITTED", "BOUND"),
                ("RUNNING", "RUNNING"),
            }
            if not active_pair:
                raise KernelError(
                    "BOOK_OPENING_LOSS_STATE_INVALID",
                    "execution-loss assessment requires an exact BOUND or RUNNING execution",
                )
            snapshot = self._authoritative_snapshot(uow, run, execution)
            runtime = dict(snapshot["runtime"])
            if not bool(runtime["lease_expired"]):
                raise KernelError(
                    "BOOK_OPENING_EXECUTION_STILL_VALID",
                    "Opening execution lease has not expired",
                )
            assessment_id = self._insert_assessment(
                uow,
                run=run,
                kind="EXECUTION_LOSS",
                idempotency_key=idempotency_key,
                snapshot=snapshot,
                disposition="EXECUTION_LOST",
                execution=execution,
            )
            row = self._assessment_by_id(uow, assessment_id)
            assert row is not None
            uow.commit()
        return self._assessment_result(row, replayed=False)

    def converge_execution_loss(
        self,
        recovery_assessment_id: str,
        *,
        idempotency_key: str,
        principal: Principal,
        expected_opening_run_id: str = "",
    ) -> RecoveryReceipt:

        with AuthorityUnitOfWork(self.database_url) as uow:
            assessment = self._assessment_by_id(uow, recovery_assessment_id)
            if (
                assessment is None
                or str(assessment["assessment_kind"]) != "EXECUTION_LOSS"
            ):
                raise KernelError(
                    "BOOK_OPENING_LOSS_ASSESSMENT_INVALID",
                    "execution-loss convergence requires a loss assessment",
                )
            opening_run_id = str(assessment["opening_run_id"])
            if expected_opening_run_id and opening_run_id != expected_opening_run_id:
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_SCOPE_MISMATCH",
                    "loss assessment belongs to another Book Opening",
                )
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            replay = self._receipt_by_key(
                uow, opening_run_id, "EXECUTION_LOSS_CONVERGENCE", idempotency_key
            )
            if replay is not None:
                self._require_loss_replay_binding(
                    replay, recovery_assessment_id=recovery_assessment_id
                )
                return self._receipt_result(replay, replayed=True)
            execution = self._current_execution(uow, run, lock=True)
            current_snapshot = self._authoritative_snapshot(uow, run, execution)
            if _canonical_hash(current_snapshot) != str(
                assessment["snapshot_hash"]
            ) or int(run["version"]) != int(assessment["opening_version"]):
                self._stale("execution-loss assessment drifted")
            runtime = dict(current_snapshot["runtime"])
            reason = {
                "code": "BOOK_OPENING_EXECUTION_LOST",
                "recovery_assessment_id": recovery_assessment_id,
                "opening_execution_id": execution["opening_execution_id"],
                "runtime_job_id": runtime["runtime_job_id"],
                "attempt_id": runtime["attempt_id"],
                "lease_id": runtime["lease_id"],
                "fencing_token": runtime["fencing_token"],
            }
            runtime_result = self.runtime_jobs.terminalize_execution_loss_in_uow(
                uow,
                runtime_job_id=str(runtime["runtime_job_id"]),
                expected_attempt_id=str(runtime["attempt_id"]),
                expected_lease_id=str(runtime["lease_id"]),
                expected_fencing_token=int(runtime["fencing_token"]),
                reason=reason,
            )
            self._checkpoint("after_execution_loss_runtime_terminalization")
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_execution
                SET lifecycle='LOST', terminal_reason=%s, version=version+1,
                    terminal_at=transaction_timestamp(),
                    updated_at=transaction_timestamp()
                WHERE opening_execution_id=%s AND version=%s
                  AND lifecycle IN ('BOUND','RUNNING')
                """,
                [
                    Jsonb(reason),
                    execution["opening_execution_id"],
                    execution["version"],
                ],
            )
            if uow.cursor.rowcount != 1:
                self._stale("Opening execution changed during loss convergence")
            self._checkpoint("after_execution_loss_transition")
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='FAILED',failure=%s,recovery_instruction=%s,
                    recovery_state='RECOVERY_REQUIRED',version=version+1,
                    updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle IN ('ADMITTED','RUNNING')
                  AND current_execution_id=%s
                  AND current_execution_generation=%s
                """,
                [
                    Jsonb(reason),
                    Jsonb(
                        {
                            "action": "ASSESS_BOOK_OPENING_RECOVERY",
                            "opening_run_id": opening_run_id,
                        }
                    ),
                    opening_run_id,
                    run["version"],
                    execution["opening_execution_id"],
                    execution["generation"],
                ],
            )
            if uow.cursor.rowcount != 1:
                self._stale("Book Opening changed during loss convergence")
            self._checkpoint("after_execution_loss_opening_failure")
            result = {
                "opening_run_id": opening_run_id,
                "opening_execution_id": execution["opening_execution_id"],
                "execution_generation": int(execution["generation"]),
                "opening_lifecycle": "FAILED",
                "execution_lifecycle": "LOST",
                "runtime_job_status": runtime_result["status"],
                "recovery_intent_created": False,
                "provider_invoked": False,
            }
            receipt = self._insert_receipt(
                uow,
                run=run,
                kind="EXECUTION_LOSS_CONVERGENCE",
                assessment_id=recovery_assessment_id,
                intent_id="",
                predecessor_execution=(
                    str(execution["opening_execution_id"]),
                    int(execution["generation"]),
                ),
                successor_execution=None,
                idempotency_key=idempotency_key,
                result=result,
            )
            self._checkpoint("after_execution_loss_receipt")
            self._record_event(uow, run, "book.opening.execution_lost", result)
            self._checkpoint("after_execution_loss_outbox")
            uow.commit()
            self._checkpoint("after_execution_loss_commit_before_response")
        return self._receipt_result(receipt, replayed=False)

    def assess_recovery(
        self,
        opening_run_id: str,
        *,
        idempotency_key: str,
        principal: Principal,
    ) -> RecoveryAssessment:
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            existing = self._assessment_by_key(
                uow, opening_run_id, "RECOVERY", idempotency_key
            )
            if existing is not None:
                return self._assessment_result(existing, replayed=True)
            self._require_not_capacity_predecessor(uow, opening_run_id)
            if str(run["lifecycle"]) != "FAILED":
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_STATE_INVALID",
                    "recovery assessment requires a FAILED Opening",
                )
            execution = self._current_execution(uow, run, lock=True)
            if str(execution["lifecycle"]) not in {"FAILED", "LOST", "ABORTED"}:
                self._stale("failed Opening does not bind a terminal execution")
            snapshot = self._authoritative_snapshot(uow, run, execution)
            disposition = str(snapshot["external_effect"]["classification"])
            assessment_id = self._insert_assessment(
                uow,
                run=run,
                kind="RECOVERY",
                idempotency_key=idempotency_key,
                snapshot=snapshot,
                disposition=disposition,
                execution=execution,
            )
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET recovery_state='RECOVERY_ASSESSED',
                    updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s
                  AND lifecycle='FAILED'
                  AND recovery_state IN ('RECOVERY_REQUIRED','RECOVERY_ASSESSED')
                """,
                [opening_run_id, run["version"]],
            )
            if uow.cursor.rowcount != 1:
                self._stale("Book Opening changed while assessment was recorded")
            row = self._assessment_by_id(uow, assessment_id)
            assert row is not None
            uow.commit()
        return self._assessment_result(row, replayed=False)

    def recover(
        self,
        recovery_assessment_id: str,
        *,
        idempotency_key: str,
        reason: str,
        principal: Principal,
        expected_opening_run_id: str = "",
    ) -> RecoveryReceipt:

        if not reason.strip():
            raise ValueError("Book Opening recovery reason is required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            assessment = self._assessment_by_id(uow, recovery_assessment_id)
            if assessment is None or str(assessment["assessment_kind"]) != "RECOVERY":
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_ASSESSMENT_INVALID",
                    "recovery requires an immutable recovery assessment",
                )
            opening_run_id = str(assessment["opening_run_id"])
            if expected_opening_run_id and opening_run_id != expected_opening_run_id:
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_SCOPE_MISMATCH",
                    "recovery assessment belongs to another Book Opening",
                )
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            replay = self._receipt_by_key(
                uow, opening_run_id, "RECOVERY_ADMISSION", idempotency_key
            )
            if replay is not None:
                self._require_recovery_replay_binding(
                    uow,
                    replay,
                    recovery_assessment_id=recovery_assessment_id,
                    idempotency_key=idempotency_key,
                    reason=reason,
                    principal_id=principal.principal_id,
                )
                return self._receipt_result(replay, replayed=True)
            self._require_not_capacity_predecessor(uow, opening_run_id)
            execution = self._current_execution(uow, run, lock=True)
            snapshot = self._authoritative_snapshot(uow, run, execution)
            if (
                str(run["lifecycle"]) != "FAILED"
                or int(run["version"]) != int(assessment["opening_version"])
                or _canonical_hash(snapshot) != str(assessment["snapshot_hash"])
            ):
                self._stale("RecoveryAssessment no longer matches Authority state")
            budget = dict(snapshot.get("budget") or {})
            budget_outcome = str(budget.get("outcome") or "")
            if budget_outcome == BudgetAssessmentOutcome.RECONCILIATION_REQUIRED:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_RECONCILIATION_REQUIRED",
                    "Provider budget evidence must reconcile before recovery",
                )
            if budget_outcome == BudgetAssessmentOutcome.EXHAUSTED:
                raise KernelError(
                    "BOOK_OPENING_BUDGET_EXHAUSTED",
                    "Book Opening recovery has no Provider budget headroom",
                )
            if budget_outcome not in {
                BudgetAssessmentOutcome.ELIGIBLE,
                BudgetAssessmentOutcome.NOT_REQUIRED,
            }:
                self._stale("RecoveryAssessment has no authoritative budget outcome")
            disposition = str(assessment["disposition"])
            if disposition in {"UNKNOWN_AMBIGUOUS", "RECONCILIATION_REQUIRED"}:
                raise KernelError(
                    "BOOK_OPENING_EXTERNAL_EFFECT_RECONCILIATION_REQUIRED",
                    "ambiguous Provider state cannot be overridden by recovery",
                )
            evaluation = dict(snapshot["semantic_evaluation"])
            replacement_required = self._semantic_replacement_required(
                evaluation=evaluation,
                disposition=disposition,
            )
            predecessor_generation = int(execution["generation"])
            successor_generation = predecessor_generation + 1
            intent_id = _stable_id(
                "book-opening-recovery-intent",
                opening_run_id,
                recovery_assessment_id,
                idempotency_key,
            )
            intent_payload = {
                "opening_run_id": opening_run_id,
                "recovery_assessment_id": recovery_assessment_id,
                "predecessor_execution_id": execution["opening_execution_id"],
                "predecessor_generation": predecessor_generation,
                "successor_generation": successor_generation,
                "actor_id": principal.principal_id,
                "reason": reason,
            }
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_recovery_intent(
                    recovery_intent_id,opening_run_id,recovery_assessment_id,
                    predecessor_execution_id,predecessor_generation,
                    successor_generation,idempotency_key,intent_hash,
                    authorized_by,authorization_reason
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    intent_id,
                    opening_run_id,
                    recovery_assessment_id,
                    execution["opening_execution_id"],
                    predecessor_generation,
                    successor_generation,
                    idempotency_key,
                    _canonical_hash(intent_payload),
                    principal.principal_id,
                    reason,
                ],
            )
            self._checkpoint("after_recovery_intent")
            replacement: dict[str, Any] | None = None
            if replacement_required:
                if self.semantic_replacement is None:
                    raise KernelError(
                        "BOOK_OPENING_REPLACEMENT_RUNTIME_REQUIRED",
                        "recovery requires the semantic replacement Application",
                    )
                try:
                    replacement = self.semantic_replacement.admit_replacement_in_uow(
                        uow,
                        predecessor_operation_id=str(evaluation["operation_id"]),
                        recovery_intent_id=intent_id,
                        actor_id=str(evaluation["evaluator_actor_id"]),
                        trace_id=(
                            f"trace:{opening_run_id}:recovery:{successor_generation}"
                        ),
                        correlation_id=str(run["root_operation_id"]),
                        expected_head_generation=int(evaluation["generation"]),
                        expected_head_version=int(evaluation["head_version"]),
                    )
                except KernelError as exc:
                    if (
                        exc.code
                        == "NARRATIVE_EVALUATION_DURABLE_OUTPUT_RECONCILIATION_REQUIRED"
                    ):
                        raise KernelError(
                            "BOOK_OPENING_DURABLE_OUTPUT_RECONCILIATION_REQUIRED",
                            exc.message,
                        ) from exc
                    raise
            self._checkpoint("after_replacement_generation")
            successor_execution_id = _stable_id(
                "book-opening-execution", opening_run_id, successor_generation
            )
            semantic_binding = {
                "semantic_evaluation_operation_id": "",
                "semantic_evaluation_execution_id": "",
                "semantic_evaluation_generation": 0,
                "semantic_execution_mode": "NONE",
            }
            if replacement is not None:
                semantic_binding = {
                    "semantic_evaluation_operation_id": str(
                        replacement["operation_id"]
                    ),
                    "semantic_evaluation_execution_id": str(
                        replacement["evaluation_execution_id"]
                    ),
                    "semantic_evaluation_generation": int(replacement["generation"]),
                    "semantic_execution_mode": "NEW_REPLACEMENT",
                }
            elif str(evaluation.get("operation_id") or ""):
                semantic_binding = {
                    "semantic_evaluation_operation_id": str(evaluation["operation_id"]),
                    "semantic_evaluation_execution_id": str(
                        evaluation["evaluation_execution_id"]
                    ),
                    "semantic_evaluation_generation": int(evaluation["generation"]),
                    "semantic_execution_mode": "RESUME_CURRENT",
                }
            workflow_contract_version = str(run["workflow_contract_version"])
            expected_execution_contract = book_opening_execution_contract_version(
                workflow_contract_version
            )
            if str(run["execution_contract_version"]) != expected_execution_contract:
                self._stale("Book Opening execution contract drifted")
            runtime_job_kind, runtime_group = book_opening_runtime_job_identity(
                workflow_contract_version
            )
            runtime_spec = RuntimeJobSpec(
                job_kind=runtime_job_kind,
                runtime_group=runtime_group,
                subject_kind="BOOK_OPENING_RUN",
                subject_id=opening_run_id,
                project_id=str(run["project_id"]),
                dedupe_key=(
                    f"{opening_run_id}:execution-generation:{successor_generation}"
                ),
                input_snapshot={
                    "opening_run_id": opening_run_id,
                    "observed_version": int(run["version"]) + 1,
                    "frozen_request_digest": str(run["frozen_request_digest"]),
                    "opening_execution_id": successor_execution_id,
                    "execution_generation": successor_generation,
                    "recovery_intent_id": intent_id,
                    "replacement_evaluation_operation_id": str(
                        (replacement or {}).get("operation_id") or ""
                    ),
                    **semantic_binding,
                    **(
                        {
                            "workflow_contract_version": str(
                                run["workflow_contract_version"]
                            ),
                            "workflow_graph_revision": int(
                                run["workflow_graph_revision"]
                            ),
                            "workflow_graph_hash": str(run["workflow_graph_hash"]),
                            "workflow_node_id": str(execution["workflow_node_id"]),
                            "workflow_node_kind": self._workflow_node_kind(
                                uow, str(execution["workflow_node_id"])
                            ),
                            "workflow_node_key": self._workflow_node_key(
                                uow, str(execution["workflow_node_id"])
                            ),
                            "workflow_node_input_hash": self._workflow_node_input_hash(
                                uow, str(execution["workflow_node_id"])
                            ),
                            "workflow_transition_kind": "RECOVERY",
                            "source_checkpoint_id": str(
                                run["current_checkpoint_id"] or ""
                            ),
                            "source_checkpoint_sequence": int(
                                run["current_checkpoint_sequence"]
                            ),
                            "source_checkpoint_hash": str(
                                run["current_checkpoint_hash"] or ""
                            ),
                        }
                        if str(run.get("workflow_contract_version") or "")
                        == "book-opening-workflow-v1"
                        else {}
                    ),
                },
                max_attempts=1,
                lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
            )
            runtime_job = self.runtime_jobs.schedule_in_uow(uow, runtime_spec)
            self._checkpoint("after_recovery_runtime_job_creation")
            uow.cursor.execute(
                """
                INSERT INTO authority_book_opening_execution(
                    opening_execution_id,opening_run_id,generation,
                    predecessor_execution_id,predecessor_generation,
                    recovery_intent_id,runtime_job_id,lifecycle,frozen_request_digest,
                    input_snapshot_hash,policy_snapshot_hash,
                    authority_contract_hash,workflow_node_id,
                    workflow_transition_kind,source_checkpoint_id,
                    source_checkpoint_sequence,source_checkpoint_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'SCHEDULED',%s,%s,%s,%s,
                          NULLIF(%s,''),%s,NULLIF(%s,''),%s,%s)
                """,
                [
                    successor_execution_id,
                    opening_run_id,
                    successor_generation,
                    execution["opening_execution_id"],
                    predecessor_generation,
                    intent_id,
                    runtime_job["runtime_job_id"],
                    run["frozen_request_digest"],
                    runtime_spec.input_hash,
                    self._execution_policy_digest(),
                    self._authority_digest(str(run["execution_contract_version"])),
                    str(execution.get("workflow_node_id") or ""),
                    (
                        "RECOVERY"
                        if str(run.get("workflow_contract_version") or "")
                        == "book-opening-workflow-v1"
                        else "LEGACY_MONOLITHIC"
                    ),
                    str(run["current_checkpoint_id"] or ""),
                    int(run["current_checkpoint_sequence"]),
                    str(run["current_checkpoint_hash"] or ""),
                ],
            )
            self._checkpoint("after_recovery_execution_creation")
            uow.cursor.execute(
                """
                UPDATE authority_book_opening_run
                SET lifecycle='ADMITTED',failure='{}'::jsonb,
                    recovery_instruction='{}'::jsonb,
                    recovery_state='RECOVERY_ADMITTED',
                    current_execution_id=%s,current_execution_generation=%s,
                    version=version+1,updated_at=transaction_timestamp()
                WHERE opening_run_id=%s AND version=%s AND lifecycle='FAILED'
                  AND current_execution_id=%s
                  AND current_execution_generation=%s
                """,
                [
                    successor_execution_id,
                    successor_generation,
                    opening_run_id,
                    run["version"],
                    execution["opening_execution_id"],
                    predecessor_generation,
                ],
            )
            if uow.cursor.rowcount != 1:
                self._stale("Book Opening recovery generation CAS lost")
            self._checkpoint("after_recovery_opening_transition")
            result = {
                "opening_run_id": opening_run_id,
                "recovery_intent_id": intent_id,
                "opening_execution_id": successor_execution_id,
                "execution_generation": successor_generation,
                "runtime_job_id": runtime_job["runtime_job_id"],
                "replacement_evaluation_execution_id": str(
                    (replacement or {}).get("evaluation_execution_id") or ""
                ),
                "replacement_evaluation_operation_id": str(
                    (replacement or {}).get("operation_id") or ""
                ),
                "provider_invoked": False,
            }
            self._checkpoint("before_recovery_receipt")
            receipt = self._insert_receipt(
                uow,
                run=run,
                kind="RECOVERY_ADMISSION",
                assessment_id=recovery_assessment_id,
                intent_id=intent_id,
                predecessor_execution=(
                    str(execution["opening_execution_id"]),
                    predecessor_generation,
                ),
                successor_execution=(successor_execution_id, successor_generation),
                idempotency_key=idempotency_key,
                result=result,
            )
            self._checkpoint("after_recovery_receipt")
            self._record_event(uow, run, "book.opening.recovery_admitted", result)
            self._checkpoint("after_recovery_outbox")
            uow.commit()
            self._checkpoint("after_recovery_commit_before_response")
        return self._receipt_result(receipt, replayed=False)

    def append_execution_checkpoint(
        self,
        opening_run_id: str,
        *,
        runtime_claim: RuntimeJobClaim,
        semantic_work_key: str,
        owning_authority: str,
        evidence_type: str,
        evidence_id: str,
        evidence_version: int,
        evidence_hash: str,
    ) -> dict[str, Any]:

        self._validate_checkpoint_evidence_identity(
            semantic_work_key=semantic_work_key,
            owning_authority=owning_authority,
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            execution = self._current_execution(uow, run, lock=True)
            self._require_live_checkpoint_claim(
                uow,
                run=run,
                execution=execution,
                runtime_claim=runtime_claim,
            )
            result = self._append_checkpoint_in_uow(
                uow,
                run=run,
                execution=execution,
                semantic_work_key=semantic_work_key,
                owning_authority=owning_authority,
                evidence_type=evidence_type,
                evidence_id=evidence_id,
                evidence_version=evidence_version,
                evidence_hash=evidence_hash,
            )
            uow.commit()
            self._checkpoint("after_checkpoint_commit_before_response")
        return result

    def append_execution_narrative_search_checkpoint(
        self,
        opening_run_id: str,
        search_id: str,
        *,
        runtime_claim: RuntimeJobClaim,
    ) -> dict[str, Any]:

        with AuthorityUnitOfWork(self.database_url) as uow:
            run = self._opening(uow, opening_run_id, lock=False)
            evidence = self._narrative_search_evidence(
                uow,
                search_id=search_id,
                project_id=str(run["project_id"]),
                workspace_id=str(run["workspace_id"]),
                book_id=str(run["book_id"]),
            )
        return self.append_execution_checkpoint(
            opening_run_id,
            runtime_claim=runtime_claim,
            semantic_work_key=(
                f"{evidence['generator_operation_name']}:{evidence['logical_key']}"
            ),
            owning_authority="STORY_PLANNING",
            evidence_type="NARRATIVE_SEARCH",
            evidence_id=search_id,
            evidence_version=int(evidence["version"]),
            evidence_hash=str(evidence["evidence_hash"]),
        )

    def assert_execution_completion_checkpoints_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        opening_run_id: str,
        opening_execution_id: str,
        execution_generation: int,
        result: dict[str, Any],
    ) -> None:
        """INVARIANT: Prove the complete frozen search graph before terminalization.

        This assertion deliberately lives inside the Book Opening completion
        transaction.  Calling the application coordinator's checkpoint
        helpers in order is not an Authority invariant: an internal caller
        could otherwise submit ``book.opening.complete`` directly and bypass
        every durable semantic work item.
        """
        expected_result_fields = {
            "book_design_version",
            "book_plan_version",
            "volume_plan_version",
            "arc_plan_versions",
            "input_snapshot_id",
            "search_ids",
        }
        if (
            set(result) != expected_result_fields
            or any(
                not isinstance(result.get(field), str)
                or not str(result.get(field) or "")
                for field in (
                    "book_design_version",
                    "book_plan_version",
                    "volume_plan_version",
                    "input_snapshot_id",
                )
            )
            or not isinstance(result.get("arc_plan_versions"), list)
            or not result["arc_plan_versions"]
            or any(
                not isinstance(item, str) or not item
                for item in result["arc_plan_versions"]
            )
            or len(set(result["arc_plan_versions"])) != len(result["arc_plan_versions"])
            or not isinstance(result.get("search_ids"), list)
            or any(
                not isinstance(item, str) or not item for item in result["search_ids"]
            )
        ):
            raise KernelError(
                "BOOK_OPENING_COMPLETION_RESULT_INVALID",
                "completion result is not the exact typed Book Opening result",
            )

        run = self._opening(uow, opening_run_id, lock=False)
        if (
            str(run["lifecycle"]) != "RUNNING"
            or str(run["current_execution_id"] or "") != opening_execution_id
            or int(run["current_execution_generation"] or 0) != execution_generation
        ):
            raise KernelError(
                "BOOK_OPENING_COMPLETION_BINDING_INVALID",
                "completion checkpoints belong to another Opening execution",
            )

        cursor = self._validated_checkpoint_cursor(uow, run)
        entries = list(cursor["entries"])
        by_work_key: dict[str, dict[str, Any]] = {}
        for entry in entries:
            work_key = str(entry["semantic_work_key"])
            if work_key in by_work_key:
                raise KernelError(
                    "BOOK_OPENING_COMPLETION_CHECKPOINT_INVALID",
                    "completion checkpoint ledger contains duplicate work identity",
                )
            by_work_key[work_key] = entry

        graph = self._expected_search_graph(uow, run)
        expected_search_ids = list(graph.values())
        if list(result["search_ids"]) != expected_search_ids:
            raise KernelError(
                "BOOK_OPENING_COMPLETION_RESULT_DRIFT",
                "completion result does not name the frozen Narrative Search graph",
            )

        selected_versions: list[str] = []
        for semantic_work_key, search_id in graph.items():
            search_checkpoint = by_work_key.get(semantic_work_key)
            if (
                search_checkpoint is None
                or str(search_checkpoint["owning_authority"]) != "STORY_PLANNING"
                or str(search_checkpoint["evidence_type"]) != "NARRATIVE_SEARCH"
                or str(search_checkpoint["evidence_id"]) != search_id
            ):
                raise KernelError(
                    "BOOK_OPENING_COMPLETION_CHECKPOINT_REQUIRED",
                    f"completed search lacks its outer checkpoint: {semantic_work_key}",
                )
            search_evidence = self._narrative_search_evidence(
                uow,
                search_id=search_id,
                project_id=str(run["project_id"]),
                workspace_id=str(run["workspace_id"]),
                book_id=str(run["book_id"]),
            )
            selected_versions.append(
                str(search_evidence["selected_candidate_asset_version_id"])
            )
            uow.cursor.execute(
                """
                SELECT strategy_directives,candidate_target
                FROM authority_story_narrative_search
                WHERE search_id=%s AND project_id=%s AND workspace_id=%s
                  AND book_id=%s
                FOR SHARE
                """,
                [
                    search_id,
                    run["project_id"],
                    run["workspace_id"],
                    run["book_id"],
                ],
            )
            search_contract = uow.cursor.fetchone()
            if (
                search_contract is None
                or int(search_contract[1]) <= 0
                or int(search_contract[1]) != len(list(search_contract[0] or []))
            ):
                raise KernelError(
                    "BOOK_OPENING_COMPLETION_CHECKPOINT_INVALID",
                    "Narrative Search branch contract is not exact",
                )
            for ordinal in range(1, int(search_contract[1]) + 1):
                branch_key = f"future-{ordinal}"
                branch_work_key = f"narrative-search-branch:{search_id}:{branch_key}"
                branch_checkpoint = by_work_key.get(branch_work_key)
                if (
                    branch_checkpoint is None
                    or str(branch_checkpoint["owning_authority"]) != "STORY_PLANNING"
                    or str(branch_checkpoint["evidence_type"])
                    not in {
                        "NARRATIVE_SEARCH_BRANCH",
                        "NARRATIVE_SEARCH_BRANCH_RECONCILIATION",
                    }
                ):
                    raise KernelError(
                        "BOOK_OPENING_COMPLETION_CHECKPOINT_REQUIRED",
                        f"completed search lacks branch checkpoint {branch_work_key}",
                    )

        expected_book_plan = selected_versions[0]
        expected_volume_plan = selected_versions[1]
        expected_arc_plans = selected_versions[2:]
        if (
            str(result["book_plan_version"]) != expected_book_plan
            or str(result["volume_plan_version"]) != expected_volume_plan
            or list(result["arc_plan_versions"]) != expected_arc_plans
        ):
            raise KernelError(
                "BOOK_OPENING_COMPLETION_RESULT_DRIFT",
                "completion plan versions differ from selected Planning evidence",
            )

        input_checkpoint = by_work_key.get("book-opening:input-snapshot-resolved")
        if (
            input_checkpoint is None
            or str(input_checkpoint["owning_authority"]) != "BOOK_AUTHORITY"
            or str(input_checkpoint["evidence_type"]) != "INPUT_SNAPSHOT"
            or str(input_checkpoint["evidence_id"]) != str(result["input_snapshot_id"])
            or str(cursor["checkpoint_id"]) != str(input_checkpoint["checkpoint_id"])
        ):
            raise KernelError(
                "BOOK_OPENING_COMPLETION_CHECKPOINT_REQUIRED",
                "resolved input snapshot must be the durable checkpoint head",
            )
        uow.cursor.execute(
            """
            SELECT project_id,workspace_id,book_id,book_design_version,
                   book_plan_version,current_volume_plan_version,
                   active_arc_plan_versions
            FROM authority_book_production_input_snapshot
            WHERE snapshot_id=%s
            FOR SHARE
            """,
            [result["input_snapshot_id"]],
        )
        snapshot = uow.cursor.fetchone()
        if (
            snapshot is None
            or tuple(str(item) for item in snapshot[:3])
            != (
                str(run["project_id"]),
                str(run["workspace_id"]),
                str(run["book_id"]),
            )
            or str(snapshot[3]) != str(result["book_design_version"])
            or str(snapshot[4]) != expected_book_plan
            or str(snapshot[5]) != expected_volume_plan
            or list(snapshot[6] or []) != expected_arc_plans
        ):
            raise KernelError(
                "BOOK_OPENING_COMPLETION_RESULT_DRIFT",
                "completion result differs from the authoritative input snapshot",
            )

    def commit_execution_narrative_search_branch(
        self,
        opening_run_id: str,
        *,
        runtime_claim: RuntimeJobClaim,
        search_id: str,
        branch_key: str,
        branch_committer: Callable[[AuthorityUnitOfWork], Any],
    ) -> Any:
        """INVARIANT: Atomically register one Planning branch and advance Opening progress.

        Provider execution and Planning generation happen before this short
        transaction.  The transaction only locks the existing execution
        owners, validates the exact live fence, commits Planning membership,
        appends immutable checkpoint evidence, and advances the monotonic
        BookOpening checkpoint head.
        """
        if not search_id or not branch_key or not branch_key.startswith("future-"):
            raise ValueError("Narrative Search branch identity is invalid")
        with AuthorityUnitOfWork(self.database_url) as uow:
            # WHY: Canonical order: Opening advisory/row -> OpeningExecution ->
            # RuntimeJob -> RuntimeAttempt -> RuntimeLease -> Planning rows.
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            execution = self._current_execution(uow, run, lock=True)
            self._require_live_checkpoint_claim(
                uow,
                run=run,
                execution=execution,
                runtime_claim=runtime_claim,
            )
            expected_search_ids = set(self._expected_search_graph(uow, run).values())
            if search_id not in expected_search_ids:
                raise KernelError(
                    "BOOK_OPENING_BRANCH_SEARCH_DRIFT",
                    "Planning branch belongs to another frozen Book Opening graph",
                )
            evidence = branch_committer(uow)
            membership_id = str(getattr(evidence, "membership_id", ""))
            evidence_type = str(getattr(evidence, "evidence_type", ""))
            evidence_id = str(getattr(evidence, "evidence_id", ""))
            if (
                str(getattr(evidence, "search_id", "")) != search_id
                or str(getattr(evidence, "branch_key", "")) != branch_key
                or int(getattr(evidence, "evidence_version", 0)) != 1
                or not str(getattr(evidence, "evidence_hash", "")).startswith("sha256:")
                or evidence_type
                not in {
                    "NARRATIVE_SEARCH_BRANCH",
                    "NARRATIVE_SEARCH_BRANCH_RECONCILIATION",
                }
                or not evidence_id
            ):
                raise KernelError(
                    "BOOK_OPENING_BRANCH_EVIDENCE_INVALID",
                    "Planning branch committer returned different evidence",
                )
            semantic_work_key = f"narrative-search-branch:{search_id}:{branch_key}"
            if evidence_type == "NARRATIVE_SEARCH_BRANCH_RECONCILIATION":
                if (
                    str(getattr(evidence, "opening_run_id", "")) != opening_run_id
                    or str(getattr(evidence, "opening_execution_id", ""))
                    != str(execution["opening_execution_id"])
                    or int(getattr(evidence, "execution_generation", 0))
                    != int(execution["generation"])
                ):
                    raise KernelError(
                        "BOOK_OPENING_BRANCH_EVIDENCE_INVALID",
                        "Planning reconciliation evidence belongs to another execution",
                    )
                replay = self._branch_reconciliation_receipt(
                    uow,
                    opening_run_id=opening_run_id,
                    membership_id=membership_id,
                )
                if replay is not None:
                    checkpoint = self._append_checkpoint_in_uow(
                        uow,
                        run=run,
                        execution=execution,
                        semantic_work_key=semantic_work_key,
                        owning_authority="STORY_PLANNING",
                        evidence_type=evidence_type,
                        evidence_id=evidence_id,
                        evidence_version=int(evidence.evidence_version),
                        evidence_hash=str(evidence.evidence_hash),
                    )
                    self._assert_branch_reconciliation_receipt_replay(
                        replay,
                        evidence=evidence,
                        checkpoint=checkpoint,
                    )
                    uow.commit()
                    self._checkpoint("after_branch_checkpoint_commit_before_response")
                    return evidence
                assessment = self._assess_branch_reconciliation_in_uow(
                    uow,
                    run=run,
                    execution=execution,
                    runtime_claim=runtime_claim,
                    evidence=evidence,
                    semantic_work_key=semantic_work_key,
                )
                self._checkpoint("after_branch_reconciliation_assessment")
            else:
                assessment = None
            checkpoint = self._append_checkpoint_in_uow(
                uow,
                run=run,
                execution=execution,
                semantic_work_key=semantic_work_key,
                owning_authority="STORY_PLANNING",
                evidence_type=evidence_type,
                evidence_id=evidence_id,
                evidence_version=int(evidence.evidence_version),
                evidence_hash=str(evidence.evidence_hash),
            )
            if assessment is not None:
                self._record_branch_reconciliation_receipt_in_uow(
                    uow,
                    run=run,
                    assessment=assessment,
                    evidence=evidence,
                    checkpoint=checkpoint,
                )
                self._checkpoint("after_branch_reconciliation_receipt")
            self._checkpoint("after_branch_checkpoint_before_commit")
            uow.commit()
            self._checkpoint("after_branch_checkpoint_commit_before_response")
        return evidence

    def _assess_branch_reconciliation_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        execution: dict[str, Any],
        runtime_claim: RuntimeJobClaim,
        evidence: Any,
        semantic_work_key: str,
    ) -> dict[str, Any]:
        cursor = self._validated_checkpoint_cursor(uow, run)
        stable_key = _stable_id(
            "book-opening-branch-reconciliation-intent",
            run["opening_run_id"],
            evidence.membership_id,
            evidence.reconciliation_evidence_id,
            evidence.evidence_hash,
        )
        snapshot = {
            "opening_run_id": str(run["opening_run_id"]),
            "opening_execution_id": str(execution["opening_execution_id"]),
            "execution_generation": int(execution["generation"]),
            "runtime_job_id": runtime_claim.runtime_job_id,
            "runtime_attempt_id": runtime_claim.attempt_id,
            "runtime_lease_id": runtime_claim.lease_id,
            "runtime_worker_id": runtime_claim.worker_id,
            "runtime_fencing_token": runtime_claim.fencing_token,
            "membership_id": str(evidence.membership_id),
            "reconciliation_evidence_id": str(evidence.reconciliation_evidence_id),
            "reconciliation_evidence_hash": str(evidence.evidence_hash),
            "semantic_work_key": semantic_work_key,
            "predecessor_checkpoint_id": str(cursor["checkpoint_id"]),
            "predecessor_checkpoint_sequence": int(cursor["sequence"]),
            "predecessor_checkpoint_hash": str(cursor["checkpoint_hash"]),
            "frozen_request_digest": str(run["frozen_request_digest"]),
            "assessment_contract_version": (
                "book-opening-branch-reconciliation-assessment.v1"
            ),
        }
        assessment_hash = _canonical_hash(snapshot)
        assessment_id = _stable_id(
            "book-opening-branch-reconciliation-assessment", stable_key
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_branch_reconciliation_assessment(
                branch_reconciliation_assessment_id,opening_run_id,
                opening_execution_id,execution_generation,runtime_job_id,
                runtime_attempt_id,runtime_lease_id,runtime_worker_id,
                runtime_fencing_token,membership_id,reconciliation_evidence_id,
                semantic_work_key,predecessor_checkpoint_id,
                predecessor_checkpoint_sequence,predecessor_checkpoint_hash,
                assessment_contract_version,assessment_snapshot,assessment_hash,
                reconciliation_intent_hash,outcome,stable_idempotency_key
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,''),%s,%s,%s,
                %s,%s,%s,'RECONCILABLE',%s
            ) ON CONFLICT DO NOTHING
            """,
            [
                assessment_id,
                run["opening_run_id"],
                execution["opening_execution_id"],
                execution["generation"],
                runtime_claim.runtime_job_id,
                runtime_claim.attempt_id,
                runtime_claim.lease_id,
                runtime_claim.worker_id,
                runtime_claim.fencing_token,
                evidence.membership_id,
                evidence.reconciliation_evidence_id,
                semantic_work_key,
                cursor["checkpoint_id"],
                cursor["sequence"],
                cursor["checkpoint_hash"],
                "book-opening-branch-reconciliation-assessment.v1",
                Jsonb(snapshot),
                assessment_hash,
                _canonical_hash(
                    {
                        "stable_idempotency_key": stable_key,
                        "assessment_hash": assessment_hash,
                    }
                ),
                stable_key,
            ],
        )
        uow.cursor.execute(
            """
            SELECT branch_reconciliation_assessment_id,opening_run_id,
                   opening_execution_id,execution_generation,runtime_job_id,
                   runtime_attempt_id,runtime_lease_id,runtime_worker_id,
                   runtime_fencing_token,membership_id,reconciliation_evidence_id,
                   semantic_work_key,COALESCE(predecessor_checkpoint_id,''),
                   predecessor_checkpoint_sequence,predecessor_checkpoint_hash,
                   assessment_contract_version,assessment_snapshot,assessment_hash,
                   reconciliation_intent_hash,outcome,stable_idempotency_key
            FROM authority_book_opening_branch_reconciliation_assessment
            WHERE opening_run_id=%s AND membership_id=%s
            FOR SHARE
            """,
            [run["opening_run_id"], evidence.membership_id],
        )
        row = uow.cursor.fetchone()
        expected = (
            assessment_id,
            str(run["opening_run_id"]),
            str(execution["opening_execution_id"]),
            int(execution["generation"]),
            runtime_claim.runtime_job_id,
            runtime_claim.attempt_id,
            runtime_claim.lease_id,
            runtime_claim.worker_id,
            runtime_claim.fencing_token,
            str(evidence.membership_id),
            str(evidence.reconciliation_evidence_id),
            semantic_work_key,
            str(cursor["checkpoint_id"]),
            int(cursor["sequence"]),
            str(cursor["checkpoint_hash"]),
            "book-opening-branch-reconciliation-assessment.v1",
            snapshot,
            assessment_hash,
            _canonical_hash(
                {
                    "stable_idempotency_key": stable_key,
                    "assessment_hash": assessment_hash,
                }
            ),
            "RECONCILABLE",
            stable_key,
        )
        normalized = (
            None
            if row is None
            else (
                *(str(item) for item in row[:3]),
                int(row[3]),
                *(str(item) for item in row[4:8]),
                int(row[8]),
                *(str(item) for item in row[9:13]),
                int(row[13]),
                *(str(item) for item in row[14:16]),
                dict(row[16]),
                *(str(item) for item in row[17:]),
            )
        )
        if normalized != expected:
            raise KernelError(
                "BOOK_OPENING_BRANCH_RECONCILIATION_CONFLICT",
                "legacy branch assessment conflicts with durable recovery evidence",
            )
        return {
            "assessment_id": assessment_id,
            "assessment_hash": assessment_hash,
            "intent_hash": expected[18],
            "stable_idempotency_key": stable_key,
        }

    @staticmethod
    def _branch_reconciliation_receipt(
        uow: AuthorityUnitOfWork,
        *,
        opening_run_id: str,
        membership_id: str,
    ) -> tuple[Any, ...] | None:
        uow.cursor.execute(
            """
            SELECT receipt.branch_reconciliation_receipt_id,
                   receipt.branch_reconciliation_assessment_id,
                   receipt.reconciliation_evidence_id,receipt.checkpoint_id,
                   receipt.checkpoint_sequence,receipt.checkpoint_hash,
                   receipt.result,receipt.result_hash,
                   receipt.stable_idempotency_key,assessment.assessment_hash,
                   assessment.stable_idempotency_key,
                   receipt.event_id,receipt.audit_id,receipt.outbox_id
            FROM authority_book_opening_branch_reconciliation_receipt AS receipt
            JOIN authority_book_opening_branch_reconciliation_assessment
                 AS assessment
              ON assessment.branch_reconciliation_assessment_id=
                 receipt.branch_reconciliation_assessment_id
            WHERE receipt.opening_run_id=%s AND receipt.membership_id=%s
            FOR SHARE OF receipt,assessment
            """,
            [opening_run_id, membership_id],
        )
        return uow.cursor.fetchone()

    @staticmethod
    def _assert_branch_reconciliation_receipt_replay(
        receipt: tuple[Any, ...],
        *,
        evidence: Any,
        checkpoint: dict[str, Any],
    ) -> None:
        expected_receipt_id = _stable_id(
            "book-opening-branch-reconciliation-receipt",
            str(receipt[1]),
        )
        expected_result = {
            "branch_reconciliation_receipt_id": expected_receipt_id,
            "branch_reconciliation_assessment_id": str(receipt[1]),
            "reconciliation_evidence_id": evidence.reconciliation_evidence_id,
            "membership_id": evidence.membership_id,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_sequence": checkpoint["sequence"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
        }
        if (
            str(receipt[0]) != expected_receipt_id
            or str(receipt[2]) != str(evidence.reconciliation_evidence_id)
            or str(receipt[3]) != str(checkpoint["checkpoint_id"])
            or int(receipt[4]) != int(checkpoint["sequence"])
            or str(receipt[5]) != str(checkpoint["checkpoint_hash"])
            or dict(receipt[6]) != expected_result
            or str(receipt[7]) != _canonical_hash(expected_result)
            or str(receipt[8]) != str(receipt[10])
            or str(receipt[11]) != _stable_id("event", expected_receipt_id)
            or str(receipt[12]) != _stable_id("audit", expected_receipt_id)
            or str(receipt[13]) != _stable_id("outbox", expected_receipt_id)
        ):
            raise KernelError(
                "BOOK_OPENING_BRANCH_RECONCILIATION_CONFLICT",
                "durable reconciliation receipt differs from checkpoint replay",
            )

    def _record_branch_reconciliation_receipt_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        assessment: dict[str, Any],
        evidence: Any,
        checkpoint: dict[str, Any],
    ) -> None:
        receipt_id = _stable_id(
            "book-opening-branch-reconciliation-receipt",
            assessment["assessment_id"],
        )
        event_id = _stable_id("event", receipt_id)
        audit_id = _stable_id("audit", receipt_id)
        outbox_id = _stable_id("outbox", receipt_id)
        result = {
            "branch_reconciliation_receipt_id": receipt_id,
            "branch_reconciliation_assessment_id": assessment["assessment_id"],
            "reconciliation_evidence_id": evidence.reconciliation_evidence_id,
            "membership_id": evidence.membership_id,
            "checkpoint_id": checkpoint["checkpoint_id"],
            "checkpoint_sequence": checkpoint["sequence"],
            "checkpoint_hash": checkpoint["checkpoint_hash"],
        }
        result_hash = _canonical_hash(result)
        self._record_event(
            uow,
            run,
            "book.opening.branch_reconciled",
            result,
            event_id=event_id,
            audit_id=audit_id,
            outbox_id=outbox_id,
        )
        self._checkpoint("after_branch_reconciliation_event")
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_branch_reconciliation_receipt(
                branch_reconciliation_receipt_id,
                branch_reconciliation_assessment_id,opening_run_id,membership_id,
                reconciliation_evidence_id,checkpoint_id,checkpoint_sequence,
                checkpoint_hash,result,result_hash,stable_idempotency_key,
                event_id,audit_id,outbox_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            [
                receipt_id,
                assessment["assessment_id"],
                run["opening_run_id"],
                evidence.membership_id,
                evidence.reconciliation_evidence_id,
                checkpoint["checkpoint_id"],
                checkpoint["sequence"],
                checkpoint["checkpoint_hash"],
                Jsonb(result),
                result_hash,
                assessment["stable_idempotency_key"],
                event_id,
                audit_id,
                outbox_id,
            ],
        )

    def require_execution_progress(
        self,
        opening_run_id: str,
        *,
        runtime_claim: RuntimeJobClaim,
    ) -> dict[str, dict[str, Any]]:

        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            execution = self._current_execution(uow, run, lock=True)
            self._require_live_checkpoint_claim(
                uow,
                run=run,
                execution=execution,
                runtime_claim=runtime_claim,
            )
            cursor = self._validated_checkpoint_cursor(uow, run)
        return {
            str(item["semantic_work_key"]): dict(item) for item in cursor["entries"]
        }

    def assess_checkpoint_reconciliation(
        self,
        opening_run_id: str,
        *,
        semantic_work_key: str,
        owning_authority: str,
        evidence_type: str,
        evidence_id: str,
        evidence_version: int,
        evidence_hash: str,
        idempotency_key: str,
        principal: Principal,
    ) -> RecoveryAssessment:

        evidence = self._checkpoint_evidence_payload(
            semantic_work_key=semantic_work_key,
            owning_authority=owning_authority,
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
        )
        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            existing = self._assessment_by_key(
                uow, opening_run_id, "CHECKPOINT_RECONCILIATION", idempotency_key
            )
            if existing is not None:
                frozen = dict(
                    dict(existing["snapshot"]).get("checkpoint_reconciliation") or {}
                )
                if frozen != evidence:
                    raise KernelError(
                        "BOOK_OPENING_RECOVERY_IDEMPOTENCY_CONFLICT",
                        "checkpoint assessment key is bound to different evidence",
                    )
                return self._assessment_result(existing, replayed=True)
            if str(run["lifecycle"]) != "FAILED":
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_RECONCILIATION_STATE_INVALID",
                    "checkpoint reconciliation requires a FAILED Opening",
                )
            execution = self._current_execution(uow, run, lock=True)
            if str(execution["lifecycle"]) not in {"FAILED", "LOST"}:
                self._stale("checkpoint reconciliation requires terminal execution")
            snapshot = self._authoritative_snapshot(
                uow, run, execution, pending_checkpoint_evidence=evidence
            )
            assessment_id = self._insert_assessment(
                uow,
                run=run,
                kind="CHECKPOINT_RECONCILIATION",
                idempotency_key=idempotency_key,
                snapshot=snapshot,
                disposition="RECONCILIATION_REQUIRED",
                execution=execution,
            )
            row = self._assessment_by_id(uow, assessment_id)
            assert row is not None
            uow.commit()
        return self._assessment_result(row, replayed=False)

    def reconcile_checkpoint(
        self,
        checkpoint_assessment_id: str,
        *,
        idempotency_key: str,
        principal: Principal,
        expected_opening_run_id: str = "",
    ) -> RecoveryReceipt:

        with AuthorityUnitOfWork(self.database_url) as uow:
            assessment = self._assessment_by_id(uow, checkpoint_assessment_id)
            if (
                assessment is None
                or str(assessment["assessment_kind"]) != "CHECKPOINT_RECONCILIATION"
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_ASSESSMENT_INVALID",
                    "checkpoint reconciliation requires its immutable assessment",
                )
            opening_run_id = str(assessment["opening_run_id"])
            if expected_opening_run_id and opening_run_id != expected_opening_run_id:
                raise KernelError(
                    "BOOK_OPENING_RECOVERY_SCOPE_MISMATCH",
                    "checkpoint assessment belongs to another Book Opening",
                )
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            principal.require("book.authority.execute", str(run["project_id"]))
            replay = self._receipt_by_key(
                uow, opening_run_id, "CHECKPOINT_RECONCILIATION", idempotency_key
            )
            if replay is not None:
                self._require_loss_replay_binding(
                    replay, recovery_assessment_id=checkpoint_assessment_id
                )
                return self._receipt_result(replay, replayed=True)
            if str(run["lifecycle"]) != "FAILED":
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_RECONCILIATION_STATE_INVALID",
                    "checkpoint reconciliation requires a FAILED Opening",
                )
            execution = self._current_execution(uow, run, lock=True)
            evidence = dict(
                dict(assessment["snapshot"]).get("checkpoint_reconciliation") or {}
            )
            self._validate_checkpoint_evidence_identity(**evidence)
            current = self._authoritative_snapshot(
                uow, run, execution, pending_checkpoint_evidence=evidence
            )
            if int(run["version"]) != int(
                assessment["opening_version"]
            ) or _canonical_hash(current) != str(assessment["snapshot_hash"]):
                self._stale("checkpoint assessment no longer matches Authority state")
            checkpoint = self._append_checkpoint_in_uow(
                uow, run=run, execution=execution, **evidence
            )
            result = {
                **checkpoint,
                "opening_run_id": opening_run_id,
                "opening_execution_id": str(execution["opening_execution_id"]),
                "execution_generation": int(execution["generation"]),
                "provider_invoked": False,
            }
            receipt = self._insert_receipt(
                uow,
                run=run,
                kind="CHECKPOINT_RECONCILIATION",
                assessment_id=checkpoint_assessment_id,
                intent_id="",
                predecessor_execution=(
                    str(execution["opening_execution_id"]),
                    int(execution["generation"]),
                ),
                successor_execution=None,
                idempotency_key=idempotency_key,
                result=result,
            )
            self._record_event(uow, run, "book.opening.checkpoint_reconciled", result)
            uow.commit()
            self._checkpoint("after_checkpoint_commit_before_response")
        return self._receipt_result(receipt, replayed=False)

    @staticmethod
    def _checkpoint_evidence_payload(
        *,
        semantic_work_key: str,
        owning_authority: str,
        evidence_type: str,
        evidence_id: str,
        evidence_version: int,
        evidence_hash: str,
    ) -> dict[str, Any]:
        PostgresBookOpeningRecoveryApplication._validate_checkpoint_evidence_identity(
            semantic_work_key=semantic_work_key,
            owning_authority=owning_authority,
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
        )
        return {
            "semantic_work_key": semantic_work_key,
            "owning_authority": owning_authority,
            "evidence_type": evidence_type,
            "evidence_id": evidence_id,
            "evidence_version": evidence_version,
            "evidence_hash": evidence_hash,
        }

    @staticmethod
    def _validate_checkpoint_evidence_identity(
        *,
        semantic_work_key: str,
        owning_authority: str,
        evidence_type: str,
        evidence_id: str,
        evidence_version: int,
        evidence_hash: str,
    ) -> None:
        if (
            not semantic_work_key.strip()
            or not owning_authority.strip()
            or not evidence_type.strip()
            or not evidence_id.strip()
            or evidence_version < 0
            or not evidence_hash.startswith("sha256:")
        ):
            raise ValueError("semantic checkpoint evidence identity is invalid")

    def _require_live_checkpoint_claim(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        execution: dict[str, Any],
        runtime_claim: RuntimeJobClaim,
    ) -> None:
        if (
            str(run["lifecycle"]) != "RUNNING"
            or str(execution["lifecycle"]) != "RUNNING"
            or str(execution["frozen_request_digest"])
            != str(run["frozen_request_digest"])
            or str(execution["policy_snapshot_hash"]) != self._execution_policy_digest()
            or str(execution["authority_contract_hash"])
            != self._authority_digest(str(run["execution_contract_version"]))
        ):
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EXECUTION_STALE",
                "checkpoint writer does not own the current Opening execution contract",
            )
        runtime = self._runtime_binding(uow, execution, lock=True)
        exact = (
            str(runtime["runtime_job_id"]) == runtime_claim.runtime_job_id
            and str(runtime["attempt_id"]) == runtime_claim.attempt_id
            and str(runtime["lease_id"]) == runtime_claim.lease_id
            and str(runtime["worker_id"]) == runtime_claim.worker_id
            and int(runtime["fencing_token"]) == runtime_claim.fencing_token
            and str(runtime["runtime_job_status"]) in {"RUNNING", "CHECKPOINTED"}
            and str(runtime["attempt_status"]) in {"RUNNING", "CHECKPOINTED"}
            and str(runtime["lease_status"]) == "HELD"
            and not bool(runtime["lease_expired"])
            and str(runtime_claim.input_snapshot.get("opening_execution_id") or "")
            == str(execution["opening_execution_id"])
            and int(runtime_claim.input_snapshot.get("execution_generation") or 0)
            == int(execution["generation"])
        )
        if not exact:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_FENCE_STALE",
                "checkpoint writer lost its exact RuntimeJob/Attempt/Lease fence",
            )

    def _append_checkpoint_in_uow(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        execution: dict[str, Any],
        semantic_work_key: str,
        owning_authority: str,
        evidence_type: str,
        evidence_id: str,
        evidence_version: int,
        evidence_hash: str,
        workflow_node_id: str = "",
    ) -> dict[str, Any]:
        self._validate_checkpoint_evidence_identity(
            semantic_work_key=semantic_work_key,
            owning_authority=owning_authority,
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
        )
        bound_workflow_node_id = str(
            workflow_node_id or execution.get("workflow_node_id") or ""
        )
        if str(run.get("workflow_contract_version") or "") == (
            "book-opening-workflow-v1"
        ) and bound_workflow_node_id != str(run.get("current_workflow_node_id") or ""):
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_WORKFLOW_NODE_STALE",
                "checkpoint writer differs from the current workflow node",
            )
        cursor = self._validated_checkpoint_cursor(uow, run)
        if (
            str(cursor["checkpoint_id"]) != str(run["current_checkpoint_id"] or "")
            or int(cursor["sequence"]) != int(run["current_checkpoint_sequence"])
            or str(cursor["checkpoint_hash"])
            != str(run["current_checkpoint_hash"] or "")
        ):
            self._stale("semantic checkpoint cursor projection drifted")
        self._verify_evidence(
            uow,
            run=run,
            semantic_work_key=semantic_work_key,
            owning_authority=owning_authority,
            evidence_type=evidence_type,
            evidence_id=evidence_id,
            evidence_version=evidence_version,
            evidence_hash=evidence_hash,
        )
        uow.cursor.execute(
            """
            SELECT checkpoint_id,checkpoint_sequence,checkpoint_hash
            FROM authority_book_opening_semantic_checkpoint
            WHERE opening_run_id=%s AND semantic_work_key=%s
              AND owning_authority=%s AND evidence_type=%s
              AND evidence_id=%s AND evidence_version=%s
              AND evidence_hash=%s
              AND workflow_node_id IS NOT DISTINCT FROM NULLIF(%s,'')
            """,
            [
                run["opening_run_id"],
                semantic_work_key,
                owning_authority,
                evidence_type,
                evidence_id,
                evidence_version,
                evidence_hash,
                bound_workflow_node_id,
            ],
        )
        existing = uow.cursor.fetchone()
        if existing is not None:
            return {
                "checkpoint_id": str(existing[0]),
                "sequence": int(existing[1]),
                "checkpoint_hash": str(existing[2]),
                "replayed": True,
            }
        sequence = int(run["current_checkpoint_sequence"]) + 1
        predecessor_id = str(run["current_checkpoint_id"] or "")
        predecessor_hash = str(run["current_checkpoint_hash"] or "")
        checkpoint_id = _stable_id(
            "book-opening-checkpoint",
            run["opening_run_id"],
            semantic_work_key,
            owning_authority,
            evidence_type,
            evidence_id,
            evidence_version,
            evidence_hash,
        )
        payload = {
            "opening_run_id": str(run["opening_run_id"]),
            "opening_execution_id": str(execution["opening_execution_id"]),
            "execution_generation": int(execution["generation"]),
            "sequence": sequence,
            "semantic_work_key": semantic_work_key,
            "owning_authority": owning_authority,
            "evidence_type": evidence_type,
            "evidence_id": evidence_id,
            "evidence_version": evidence_version,
            "evidence_hash": evidence_hash,
            "frozen_request_digest": str(run["frozen_request_digest"]),
            "predecessor_checkpoint_id": predecessor_id,
            "predecessor_checkpoint_hash": predecessor_hash,
        }
        checkpoint_hash = _canonical_hash(payload)
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_semantic_checkpoint(
                checkpoint_id,opening_run_id,opening_execution_id,
                execution_generation,checkpoint_sequence,semantic_work_key,
                owning_authority,evidence_type,evidence_id,evidence_version,
                evidence_hash,frozen_request_digest,
                predecessor_checkpoint_id,predecessor_checkpoint_sequence,
                predecessor_checkpoint_hash,checkpoint_hash,workflow_node_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      NULLIF(%s,''),%s,NULLIF(%s,''),%s,NULLIF(%s,''))
            """,
            [
                checkpoint_id,
                run["opening_run_id"],
                execution["opening_execution_id"],
                execution["generation"],
                sequence,
                semantic_work_key,
                owning_authority,
                evidence_type,
                evidence_id,
                evidence_version,
                evidence_hash,
                run["frozen_request_digest"],
                predecessor_id,
                int(run["current_checkpoint_sequence"]) or None,
                predecessor_hash,
                checkpoint_hash,
                bound_workflow_node_id,
            ],
        )
        self._checkpoint("after_checkpoint_append")
        uow.cursor.execute(
            """
            UPDATE authority_book_opening_run
            SET current_checkpoint_id=%s,current_checkpoint_sequence=%s,
                current_checkpoint_hash=%s,updated_at=transaction_timestamp()
            WHERE opening_run_id=%s AND current_checkpoint_sequence=%s
              AND current_execution_id=%s AND current_execution_generation=%s
            """,
            [
                checkpoint_id,
                sequence,
                checkpoint_hash,
                run["opening_run_id"],
                run["current_checkpoint_sequence"],
                execution["opening_execution_id"],
                execution["generation"],
            ],
        )
        if uow.cursor.rowcount != 1:
            self._stale("semantic checkpoint cursor changed")
        self._checkpoint("after_checkpoint_projection")
        return {
            "checkpoint_id": checkpoint_id,
            "sequence": sequence,
            "checkpoint_hash": checkpoint_hash,
            "replayed": False,
        }

    def scan_expired_executions(
        self, *, principal: Principal, limit: int = 100
    ) -> tuple[dict[str, Any], ...]:

        if limit <= 0:
            raise ValueError("execution-loss scan limit must be positive")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT opening.opening_run_id,execution.opening_execution_id,
                       execution.generation,lease.lease_id,lease.fencing_token
                FROM authority_book_opening_run AS opening
                JOIN authority_book_opening_execution AS execution
                  ON execution.opening_execution_id=opening.current_execution_id
                 AND execution.generation=opening.current_execution_generation
                JOIN authority_runtime_job AS job
                  ON job.runtime_job_id=execution.runtime_job_id
                 AND job.lease_loss_policy='AUTHORITY_CONVERGENCE_REQUIRED'
                JOIN authority_runtime_job_attempt AS attempt
                  ON attempt.attempt_id=execution.current_attempt_id
                 AND attempt.attempt_id=job.current_attempt_id
                JOIN authority_runtime_job_lease AS lease
                  ON lease.lease_id=execution.current_lease_id
                 AND lease.attempt_id=attempt.attempt_id
                 AND lease.fencing_token=execution.current_fencing_token
                WHERE (
                    (opening.lifecycle='ADMITTED' AND execution.lifecycle='BOUND')
                    OR
                    (opening.lifecycle='RUNNING' AND execution.lifecycle='RUNNING')
                )
                  AND job.status IN ('CLAIMED','RUNNING','CHECKPOINTED')
                  AND lease.status='HELD'
                  AND lease.lease_expires_at <= transaction_timestamp()
                ORDER BY lease.lease_expires_at,opening.opening_run_id
                LIMIT %s
                """,
                [limit],
            )
            candidates = [tuple(row) for row in uow.cursor.fetchall()]
        converged: list[dict[str, Any]] = []
        for opening_run_id, execution_id, generation, lease_id, fence in candidates:
            try:
                key = self._execution_loss_scan_key(str(opening_run_id))
                assessment = self.assess_execution_loss(
                    str(opening_run_id), idempotency_key=key, principal=principal
                )
                receipt = self.converge_execution_loss(
                    assessment.recovery_assessment_id,
                    idempotency_key=key,
                    principal=principal,
                    expected_opening_run_id=str(opening_run_id),
                )
            except KernelError as exc:
                if exc.code not in {
                    "BOOK_OPENING_EXECUTION_STILL_VALID",
                    "BOOK_OPENING_LOSS_STATE_INVALID",
                    "BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED",
                }:
                    raise
                # WHY: Heartbeat, completion, abort, or another loss sweeper won
                # after this bounded scan.  That candidate has already moved
                # to an authoritative state; continue so it cannot starve the
                # remaining expired executions in the batch.
                continue
            converged.append(dict(receipt.result))
        return tuple(converged)

    def _execution_loss_scan_key(self, opening_run_id: str) -> str:

        with AuthorityUnitOfWork(self.database_url) as uow:
            self._lock_opening(uow, opening_run_id)
            run = self._opening(uow, opening_run_id, lock=True)
            execution = self._current_execution(uow, run, lock=True)
            snapshot_hash = _canonical_hash(
                self._authoritative_snapshot(uow, run, execution)
            )
        return (
            f"loss:{execution['opening_execution_id']}:{execution['generation']}:"
            f"{snapshot_hash}"
        )

    def _authoritative_snapshot(
        self,
        uow: AuthorityUnitOfWork,
        run: dict[str, Any],
        execution: dict[str, Any],
        *,
        pending_checkpoint_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if _canonical_hash(dict(run["frozen_request"])) != str(
            run["frozen_request_digest"]
        ):
            self._stale("Book Opening frozen request digest drifted")
        runtime = self._runtime_binding(uow, execution, lock=True)
        checkpoint = self._validated_checkpoint_cursor(uow, run)
        if pending_checkpoint_evidence is not None:
            self._validate_checkpoint_evidence_identity(**pending_checkpoint_evidence)
            self._verify_evidence(
                uow,
                run=run,
                semantic_work_key=str(pending_checkpoint_evidence["semantic_work_key"]),
                owning_authority=str(pending_checkpoint_evidence["owning_authority"]),
                evidence_type=str(pending_checkpoint_evidence["evidence_type"]),
                evidence_id=str(pending_checkpoint_evidence["evidence_id"]),
                evidence_version=int(pending_checkpoint_evidence["evidence_version"]),
                evidence_hash=str(pending_checkpoint_evidence["evidence_hash"]),
            )
        # INVARIANT: Canonical cross-Authority order is Opening/Execution/Runtime ->
        # Budget -> semantic Operation/ExternalEffect.  Reservation takes the
        # Budget prefix before locking its Operation/Effect; keeping recovery
        # in the same order prevents an AB/BA deadlock during assessment.
        # Lock and validate Budget Authority before semantic/effect rows to
        # preserve the canonical cross-Authority lock order.  A second
        # assessment below asks for headroom only when the authoritative
        # ExternalEffect evidence proves another Provider call is necessary.
        replay_budget = self._budget_authority_snapshot(
            uow, run, provider_call_required=False
        )
        evaluation = self._semantic_evaluation(uow, run, checkpoint=checkpoint)
        external = self._external_effect_evidence(
            uow, str(evaluation.get("operation_id") or "")
        )
        budget = (
            replay_budget
            if str(external.get("classification") or "") == "PROVEN_SUCCESS"
            else self._budget_authority_snapshot(uow, run, provider_call_required=True)
        )
        snapshot = {
            "opening": {
                "opening_run_id": run["opening_run_id"],
                "lifecycle": run["lifecycle"],
                "version": int(run["version"]),
                "frozen_request_digest": run["frozen_request_digest"],
                "execution_contract_version": run["execution_contract_version"],
                "current_execution_id": run["current_execution_id"],
                "current_execution_generation": run["current_execution_generation"],
                "budget_scope_id": str(run.get("budget_scope_id") or ""),
                "budget_scope_revision": int(run.get("budget_scope_revision") or 0),
                "budget_contract_state": str(run.get("budget_contract_state") or ""),
                "workflow_contract_version": str(
                    run.get("workflow_contract_version") or ""
                ),
                "current_workflow_node_id": str(
                    run.get("current_workflow_node_id") or ""
                ),
                "workflow_graph_revision": int(run.get("workflow_graph_revision") or 0),
                "workflow_graph_hash": str(run.get("workflow_graph_hash") or ""),
            },
            "execution": {
                "opening_execution_id": execution["opening_execution_id"],
                "generation": int(execution["generation"]),
                "lifecycle": execution["lifecycle"],
                "version": int(execution["version"]),
                "policy_snapshot_hash": execution["policy_snapshot_hash"],
                "authority_contract_hash": execution["authority_contract_hash"],
                "workflow_node_id": str(execution.get("workflow_node_id") or ""),
                "workflow_transition_kind": str(
                    execution.get("workflow_transition_kind") or ""
                ),
                "source_checkpoint_id": str(
                    execution.get("source_checkpoint_id") or ""
                ),
                "source_checkpoint_sequence": int(
                    execution.get("source_checkpoint_sequence") or 0
                ),
                "source_checkpoint_hash": str(
                    execution.get("source_checkpoint_hash") or ""
                ),
            },
            "runtime": runtime,
            "checkpoint": checkpoint,
            "semantic_evaluation": evaluation,
            "external_effect": external,
            "budget": budget,
            "policy_config_digest": self._policy_digest(),
            # INVARIANT: The execution contract is release-stable so a rolling deployment
            # cannot strand an unclaimed generation.  RecoveryAssessment is
            # intentionally release-bound and therefore uses the exact running
            # application identity instead.
            "authority_version_digest": self._application_release_digest(
                str(run["execution_contract_version"])
            ),
        }
        if pending_checkpoint_evidence is not None:
            snapshot["checkpoint_reconciliation"] = dict(pending_checkpoint_evidence)
        return snapshot

    def _budget_authority_snapshot(
        self,
        uow: AuthorityUnitOfWork,
        run: dict[str, Any],
        *,
        provider_call_required: bool,
    ) -> dict[str, Any]:
        budget_scope_id = str(run.get("budget_scope_id") or "")
        budget_scope_revision = int(run.get("budget_scope_revision") or 0)
        contract_state = str(run.get("budget_contract_state") or "")
        if (
            contract_state != "BOUND"
            or not budget_scope_id
            or budget_scope_revision <= 0
        ):
            body = {
                "contract_version": "provider-budget-authority-snapshot.v1",
                "budget_scope_id": budget_scope_id,
                "budget_scope_revision": budget_scope_revision,
                "budget_policy_hash": "",
                "budget_contract_state": (
                    contract_state or "LEGACY_BUDGET_RECONCILIATION_REQUIRED"
                ),
                "outcome": (BudgetAssessmentOutcome.RECONCILIATION_REQUIRED.value),
                "reasons": ["book_opening_budget_scope_unbound"],
            }
            return {**body, "budget_snapshot_digest": _canonical_hash(body)}
        assessment = assess_budget_scope_in_uow(
            uow,
            budget_scope_id=budget_scope_id,
            project_id=str(run["project_id"]),
            requested_amount=None,
            requested_tokens=0,
            requested_calls=0,
            execution_mode=(
                "PROVIDER_ALLOWED"
                if provider_call_required
                else "DURABLE_RESULT_REPLAY"
            ),
            expected_revision=budget_scope_revision,
            use_policy_next_provider_allowance=provider_call_required,
        )
        return dict(assessment)

    def _runtime_binding(
        self,
        uow: AuthorityUnitOfWork,
        execution: dict[str, Any],
        *,
        lock: bool,
    ) -> dict[str, Any]:
        if (
            str(execution["lifecycle"]) == "ABORTED"
            and not execution.get("current_attempt_id")
            and not execution.get("current_lease_id")
            and not execution.get("current_worker_id")
            and not execution.get("current_fencing_token")
        ):
            suffix = " FOR UPDATE" if lock else ""
            uow.cursor.execute(
                f"""
                SELECT runtime_job_id,status,input_hash,current_attempt_id,
                       current_fencing_token,claimed_by,lease_loss_policy
                FROM authority_runtime_job
                WHERE runtime_job_id=%s{suffix}
                """,
                [execution["runtime_job_id"]],
            )
            marker = uow.cursor.fetchone()
            if (
                marker is None
                or str(marker[0]) != str(execution["runtime_job_id"])
                or str(marker[1]) != "CANCELLED"
                or str(marker[2]) != str(execution["input_snapshot_hash"])
                or marker[3] is not None
                or int(marker[4]) != 0
                or str(marker[5]) != ""
                or str(marker[6]) != AUTHORITY_CONVERGENCE_REQUIRED
            ):
                self._stale("Opening legacy loss marker binding drifted")
            return {
                "runtime_job_id": str(marker[0]),
                "runtime_job_status": str(marker[1]),
                "input_hash": str(marker[2]),
                "attempt_id": "",
                "fencing_token": 0,
                "lease_loss_policy": str(marker[6]),
                "attempt_status": "",
                "worker_id": "",
                "lease_id": "",
                "lease_status": "",
                "lease_expires_at": "",
                "lease_expired": False,
            }
        lock_sql = " FOR UPDATE OF job,attempt,lease" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT job.runtime_job_id,job.status,job.input_hash,
                   job.current_attempt_id,job.current_fencing_token,
                   job.lease_loss_policy,attempt.status,attempt.worker_id,
                   attempt.lease_id,lease.status,lease.lease_expires_at,
                   lease.lease_id,lease.fencing_token,
                   lease.lease_expires_at <= transaction_timestamp()
            FROM authority_runtime_job AS job
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
            WHERE job.runtime_job_id=%s{lock_sql}
            """,
            [execution["runtime_job_id"]],
        )
        row = uow.cursor.fetchone()
        if row is None:
            self._stale("Opening RuntimeJob binding is missing")
        exact = (
            str(row[0]) == str(execution["runtime_job_id"])
            and str(row[3]) == str(execution["current_attempt_id"])
            and int(row[4]) == int(execution["current_fencing_token"])
            and str(row[7]) == str(execution["current_worker_id"])
            and str(row[8]) == str(execution["current_lease_id"])
            and str(row[11]) == str(execution["current_lease_id"])
            and int(row[12]) == int(execution["current_fencing_token"])
            and str(row[5]) == AUTHORITY_CONVERGENCE_REQUIRED
        )
        if not exact:
            self._stale("Opening RuntimeJob/Attempt/Lease/fence binding drifted")
        return {
            "runtime_job_id": str(row[0]),
            "runtime_job_status": str(row[1]),
            "input_hash": str(row[2]),
            "attempt_id": str(row[3]),
            "fencing_token": int(row[4]),
            "lease_loss_policy": str(row[5]),
            "attempt_status": str(row[6]),
            "worker_id": str(row[7]),
            "lease_id": str(row[8]),
            "lease_status": str(row[9]),
            "lease_expires_at": str(row[10]),
            "lease_expired": bool(row[13]),
        }

    def _semantic_evaluation(
        self,
        uow: AuthorityUnitOfWork,
        run: dict[str, Any],
        *,
        checkpoint: dict[str, Any],
    ) -> dict[str, Any]:
        completed_search_work = {
            str(item["semantic_work_key"])
            for item in checkpoint.get("entries") or []
            if (
                str(item["owning_authority"]) == "STORY_PLANNING"
                and str(item["evidence_type"]) == "NARRATIVE_SEARCH"
            )
        }
        graph = self._expected_search_graph(uow, run)
        target = next(
            (
                (semantic_work_key, search_id)
                for semantic_work_key, search_id in graph.items()
                if semantic_work_key not in completed_search_work
            ),
            None,
        )
        if target is None:
            return self._empty_semantic_evaluation()
        semantic_work_key, target_search_id = target
        generator, logical_key = semantic_work_key.split(":", 1)
        stable_search_key = (
            f"{dict(run['frozen_request'])['idempotency_key']}:"
            f"{semantic_work_key}:narrative-search"
        )
        uow.cursor.execute(
            """
            SELECT status,strategy_directives,candidate_target
            FROM authority_story_narrative_search
            WHERE search_id=%s AND project_id=%s AND workspace_id=%s
              AND book_id=%s AND generator_operation_name=%s
              AND logical_key=%s AND stable_idempotency_key=%s
            FOR SHARE
            """,
            [
                target_search_id,
                run["project_id"],
                run["workspace_id"],
                run["book_id"],
                generator,
                logical_key,
                stable_search_key,
            ],
        )
        search_row = uow.cursor.fetchone()
        if search_row is None:
            return self._empty_semantic_evaluation()
        if str(search_row[0]) in {"SELECTED", "ACTIVATED"}:
            # INVARIANT: Planning already owns a complete durable result.  The missing
            # outer cursor is replayed/reconciled from that Authority; creating
            # a semantic replacement here would orphan executable READY work.
            return self._empty_semantic_evaluation()
        directives = list(search_row[1] or [])
        candidate_target = int(search_row[2])
        expected_branches = [
            f"future-{ordinal}" for ordinal in range(1, candidate_target + 1)
        ]
        if candidate_target != len(directives):
            self._stale("Narrative Search branch contract drifted")
        uow.cursor.execute(
            """
            SELECT branch_key
            FROM authority_story_narrative_search_candidate
            WHERE search_id=%s
            ORDER BY branch_key
            FOR SHARE
            """,
            [target_search_id],
        )
        completed_branches = {str(row[0]) for row in uow.cursor.fetchall()}
        if not completed_branches.issubset(set(expected_branches)):
            self._stale("Narrative Search contains an unexpected branch")
        current_branch = next(
            (item for item in expected_branches if item not in completed_branches),
            "",
        )
        if not current_branch:
            # INVARIANT: Every branch has durable Planning membership.  Search selection
            # itself is the next idempotent step; no semantic generation is
            # authorized here.
            return self._empty_semantic_evaluation()
        # WHY: Select the exact Planning-owned search lineage first, then take the same
        # candidate advisory lock used by normal semantic admission before any
        # Evaluation/head row lock.  This preserves the canonical
        # candidate-lock -> head/evaluation-lock order during recovery.
        uow.cursor.execute(
            """
            SELECT candidate_asset_version_id
            FROM authority_story_planning_generation
            WHERE project_id=%s AND workspace_id=%s AND book_id=%s
              AND narrative_search_id=%s
              AND narrative_search_branch_key=%s
              AND status='EVALUATION_PENDING'
              AND candidate_asset_version_id IS NOT NULL
            ORDER BY repair_number DESC,created_at DESC,operation_id DESC
            LIMIT 2
            """,
            [
                str(run["project_id"]),
                str(run["workspace_id"]),
                str(run["book_id"]),
                target_search_id,
                current_branch,
            ],
        )
        candidate_rows = uow.cursor.fetchall()
        if not candidate_rows:
            return self._empty_semantic_evaluation()
        if len(candidate_rows) != 1:
            self._stale("Narrative Search has multiple current Planning generations")
        candidate_id = str(candidate_rows[0][0])
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"narrative-evaluation:{run['project_id']}:{candidate_id}"],
        )
        uow.cursor.execute(
            """
            SELECT evaluation.evaluation_execution_id,evaluation.generation,
                   evaluation.operation_id,evaluation.lifecycle,evaluation.version,
                   evaluation.candidate_asset_version_id,
                   evaluation.candidate_content_hash,operation.status,
                   head.version,operation.actor_id
            FROM authority_narrative_evaluation_execution AS evaluation
            JOIN authority_story_planning_generation AS generation
              ON generation.candidate_asset_version_id=
                 evaluation.candidate_asset_version_id
             AND generation.project_id=evaluation.project_id
             AND generation.book_id=evaluation.book_id
            JOIN authority_operation AS operation
              ON operation.operation_id=evaluation.operation_id
             AND operation.project_id=%s
            JOIN authority_narrative_evaluation_execution_head AS head
              ON head.project_id=evaluation.project_id
             AND head.candidate_asset_version_id=
                 evaluation.candidate_asset_version_id
             AND head.current_execution_id=
                 evaluation.evaluation_execution_id
             AND head.current_generation=evaluation.generation
            WHERE evaluation.project_id=%s AND evaluation.book_id=%s
              AND evaluation.candidate_asset_version_id=%s
              AND generation.narrative_search_id=%s
              AND generation.narrative_search_branch_key=%s
              AND generation.status='EVALUATION_PENDING'
              AND operation.command_payload->'payload'->>'book_id'=%s
            ORDER BY operation.created_at DESC,operation.operation_id DESC
            LIMIT 1
            FOR UPDATE OF evaluation,head
            """,
            [
                str(run["project_id"]),
                str(run["project_id"]),
                str(run["book_id"]),
                candidate_id,
                target_search_id,
                current_branch,
                str(run["book_id"]),
            ],
        )
        row = uow.cursor.fetchone()
        if row is None:
            self._stale("Book-scoped semantic Evaluation lineage changed")
        keys = (
            "evaluation_execution_id",
            "generation",
            "operation_id",
            "lifecycle",
            "execution_version",
            "candidate_asset_version_id",
            "candidate_content_hash",
            "operation_status",
            "head_version",
            "evaluator_actor_id",
        )
        result = dict(zip(keys, row, strict=True))
        for key in ("generation", "execution_version", "head_version"):
            result[key] = int(result[key])
        return result

    def _external_effect_evidence(
        self, uow: AuthorityUnitOfWork, operation_id: str
    ) -> dict[str, Any]:
        if not operation_id:
            return {
                "classification": "PROVEN_NO_EFFECT",
                "evidence": [],
                "digest": _canonical_hash([]),
            }
        uow.cursor.execute(
            """
            SELECT external_effect_id,status,request_hash
            FROM authority_external_effect
            WHERE operation_id=%s
            ORDER BY external_effect_id
            FOR UPDATE
            """,
            [operation_id],
        )
        effects = [tuple(row) for row in uow.cursor.fetchall()]
        if not effects:
            return {
                "classification": "PROVEN_NO_EFFECT",
                "evidence": [],
                "digest": _canonical_hash([]),
            }
        effect_ids = [str(row[0]) for row in effects]
        uow.cursor.execute(
            """
            SELECT dispatch_id,external_effect_id,generation,status,payload_hash
            FROM authority_external_effect_dispatch
            WHERE external_effect_id=ANY(%s)
            ORDER BY external_effect_id,generation,dispatch_id
            FOR UPDATE
            """,
            [effect_ids],
        )
        dispatches = [tuple(row) for row in uow.cursor.fetchall()]
        dispatch_ids = [str(row[0]) for row in dispatches]
        receipts: list[tuple[Any, ...]] = []
        if dispatch_ids:
            uow.cursor.execute(
                """
                SELECT external_receipt_id,dispatch_id,status,payload_hash
                FROM authority_external_receipt
                WHERE dispatch_id=ANY(%s)
                ORDER BY dispatch_id,external_receipt_id
                FOR UPDATE
                """,
                [dispatch_ids],
            )
            receipts = [tuple(row) for row in uow.cursor.fetchall()]
        dispatch_by_effect: dict[str, list[tuple[Any, ...]]] = {}
        for dispatch in dispatches:
            dispatch_by_effect.setdefault(str(dispatch[1]), []).append(dispatch)
        receipts_by_dispatch: dict[str, list[tuple[Any, ...]]] = {}
        for receipt in receipts:
            receipts_by_dispatch.setdefault(str(receipt[1]), []).append(receipt)
        evidence: list[dict[str, Any]] = []
        for effect in effects:
            items = dispatch_by_effect.get(str(effect[0])) or [None]
            for dispatch in items:
                dispatch_receipts = (
                    [None]
                    if dispatch is None
                    else receipts_by_dispatch.get(str(dispatch[0])) or [None]
                )
                for receipt in dispatch_receipts:
                    evidence.append(
                        {
                            "effect_id": str(effect[0]),
                            "effect_status": str(effect[1]),
                            "request_hash": str(effect[2]),
                            "dispatch_id": str(dispatch[0]) if dispatch else "",
                            "dispatch_status": (str(dispatch[3]) if dispatch else ""),
                            "dispatch_payload_hash": (
                                str(dispatch[4] or "") if dispatch else ""
                            ),
                            "receipt_id": str(receipt[0]) if receipt else "",
                            "receipt_status": str(receipt[2]) if receipt else "",
                            "receipt_payload_hash": (
                                str(receipt[3] or "") if receipt else ""
                            ),
                        }
                    )
        classification = classify_narrative_evaluation_external_effects(
            {
                **item,
                "external_effect_id": item["effect_id"],
                "dispatch_id": item["dispatch_id"] or None,
            }
            for item in evidence
        ).value
        return {
            "classification": classification,
            "evidence": evidence,
            "digest": _canonical_hash(evidence),
        }

    @staticmethod
    def _require_not_capacity_predecessor(uow: AuthorityUnitOfWork, opening_run_id: str) -> None:
        uow.cursor.execute("SELECT to_regclass('authority_book_opening_capacity_continuation')")
        if uow.cursor.fetchone()[0] is None:
            return
        uow.cursor.execute("SELECT successor_opening_run_id FROM authority_book_opening_capacity_continuation WHERE source_opening_run_id=%s", [opening_run_id])
        row = uow.cursor.fetchone()
        if row is not None:
            raise KernelError("BOOK_OPENING_CAPACITY_PREDECESSOR_FENCED", "Resume the registered capacity successor: " + str(row[0]))

    @staticmethod
    def _lock_opening(uow: AuthorityUnitOfWork, opening_run_id: str) -> None:
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"book-opening:{opening_run_id}"],
        )

    @staticmethod
    def _opening(
        uow: AuthorityUnitOfWork, opening_run_id: str, *, lock: bool
    ) -> dict[str, Any]:
        suffix = " FOR UPDATE" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT opening_run_id,project_id,workspace_id,book_id,
                   root_operation_id,lifecycle,frozen_request,
                   frozen_request_digest,version,execution_contract_version,
                   current_execution_id,current_execution_generation,
                   current_checkpoint_id,current_checkpoint_sequence,
                   current_checkpoint_hash,recovery_state,budget_scope_id,
                   budget_scope_revision,budget_contract_state,
                   workflow_contract_version,current_workflow_node_id,
                   workflow_graph_revision,workflow_graph_hash
            FROM authority_book_opening_run
            WHERE opening_run_id=%s{suffix}
            """,
            [opening_run_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("BOOK_OPENING_NOT_FOUND", "Book Opening is missing")
        keys = (
            "opening_run_id",
            "project_id",
            "workspace_id",
            "book_id",
            "root_operation_id",
            "lifecycle",
            "frozen_request",
            "frozen_request_digest",
            "version",
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
        )
        return dict(zip(keys, row, strict=True))

    @staticmethod
    def _empty_semantic_evaluation() -> dict[str, Any]:
        return {
            "evaluation_execution_id": "",
            "generation": 0,
            "operation_id": "",
            "lifecycle": "",
            "execution_version": 0,
            "candidate_asset_version_id": "",
            "candidate_content_hash": "",
            "operation_status": "",
            "head_version": 0,
            "evaluator_actor_id": "",
        }

    @staticmethod
    def _current_execution(
        uow: AuthorityUnitOfWork, run: dict[str, Any], *, lock: bool
    ) -> dict[str, Any]:
        if not run["current_execution_id"] or not run["current_execution_generation"]:
            raise KernelError(
                "BOOK_OPENING_EXECUTION_RECONCILIATION_REQUIRED",
                "legacy Opening must reconcile its execution identity first",
            )
        suffix = " FOR UPDATE" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT opening_execution_id,opening_run_id,generation,
                   predecessor_execution_id,predecessor_generation,
                   runtime_job_id,current_attempt_id,current_lease_id,
                   current_worker_id,current_fencing_token,lifecycle,
                   frozen_request_digest,input_snapshot_hash,
                   policy_snapshot_hash,authority_contract_hash,version,
                   workflow_node_id,workflow_transition_kind,
                   source_checkpoint_id,source_checkpoint_sequence,
                   source_checkpoint_hash
            FROM authority_book_opening_execution
            WHERE opening_execution_id=%s AND opening_run_id=%s
              AND generation=%s{suffix}
            """,
            [
                run["current_execution_id"],
                run["opening_run_id"],
                run["current_execution_generation"],
            ],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_EXECUTION_BINDING_INVALID",
                "Opening current execution pointer is not exact",
            )
        keys = (
            "opening_execution_id",
            "opening_run_id",
            "generation",
            "predecessor_execution_id",
            "predecessor_generation",
            "runtime_job_id",
            "current_attempt_id",
            "current_lease_id",
            "current_worker_id",
            "current_fencing_token",
            "lifecycle",
            "frozen_request_digest",
            "input_snapshot_hash",
            "policy_snapshot_hash",
            "authority_contract_hash",
            "version",
            "workflow_node_id",
            "workflow_transition_kind",
            "source_checkpoint_id",
            "source_checkpoint_sequence",
            "source_checkpoint_hash",
        )
        return dict(zip(keys, row, strict=True))

    def _legacy_runtime_binding(
        self,
        uow: AuthorityUnitOfWork,
        run: dict[str, Any],
        *,
        execution_id: str,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT job.runtime_job_id,job.input_hash,job.status,
                   attempt.attempt_id,attempt.worker_id,attempt.lease_id,
                   attempt.fencing_token,lease.lease_id,lease.status,
                   lease.lease_expires_at,attempt.status,
                   job.lease_loss_policy,job.max_attempts,
                   job.current_attempt_id,job.current_fencing_token
            FROM authority_runtime_job AS job
            LEFT JOIN authority_runtime_job_attempt AS attempt
              ON attempt.attempt_id=job.current_attempt_id
            LEFT JOIN authority_runtime_job_lease AS lease
              ON lease.attempt_id=attempt.attempt_id
             AND lease.runtime_job_id=job.runtime_job_id
             AND lease.fencing_token=job.current_fencing_token
            WHERE job.project_id=%s AND job.job_kind='BOOK_OPENING_EXECUTE'
              AND job.runtime_group='book_opening'
              AND job.subject_kind='BOOK_OPENING_RUN'
              AND job.subject_id=%s
            ORDER BY job.created_at,job.runtime_job_id
            FOR UPDATE OF job
            """,
            [run["project_id"], run["opening_run_id"]],
        )
        rows = [tuple(row) for row in uow.cursor.fetchall()]
        executable = [
            row
            for row in rows
            if str(row[2])
            in {"READY", "RETRY_WAIT", "CLAIMED", "RUNNING", "CHECKPOINTED"}
        ]
        if len(executable) > 1:
            raise KernelError(
                "BOOK_OPENING_LEGACY_BINDING_AMBIGUOUS",
                "legacy Opening has more than one executable RuntimeJob",
            )
        history = [
            {
                "runtime_job_id": str(row[0]),
                "status": str(row[2]),
                "attempt_id": str(row[3] or ""),
                "attempt_status": str(row[10] or ""),
                "lease_id": str(row[7] or ""),
                "lease_status": str(row[8] or ""),
                "fencing_token": int(row[6] or 0),
            }
            for row in rows
        ]
        history_digest = _canonical_hash(history)
        if executable:
            row = executable[0]
            if str(row[11]) != AUTHORITY_CONVERGENCE_REQUIRED:
                raise KernelError(
                    "BOOK_OPENING_LEGACY_BINDING_INVALID",
                    "legacy executable RuntimeJob lacks the no-takeover contract",
                )
            status = str(row[2])
            if status in {"CLAIMED", "RUNNING", "CHECKPOINTED"} and str(
                run["lifecycle"]
            ) in {"ADMITTED", "RUNNING"}:
                if (
                    not row[3]
                    or str(row[3]) != str(row[13])
                    or str(row[5]) != str(row[7])
                    or int(row[6] or 0) <= 0
                    or int(row[6]) != int(row[14])
                    or str(row[8]) != "HELD"
                    or str(row[10]) != status
                ):
                    raise KernelError(
                        "BOOK_OPENING_LEGACY_BINDING_INVALID",
                        "legacy RuntimeJob Attempt/Lease identity is inconsistent",
                    )
                return {
                    "runtime_job_id": str(row[0]),
                    "input_hash": str(row[1]),
                    "runtime_job_status": status,
                    "attempt_id": str(row[3]),
                    "worker_id": str(row[4]),
                    "lease_id": str(row[5]),
                    "fencing_token": int(row[6]),
                    "lease_status": str(row[8]),
                    "lease_expires_at": str(row[9]),
                    "execution_lifecycle": (
                        "RUNNING" if str(run["lifecycle"]) == "RUNNING" else "BOUND"
                    ),
                    "terminal_reason": {},
                    "runtime_history_digest": history_digest,
                }
            runtime_job_id = str(row[0])
            input_hash = str(row[1])
        else:
            bindable_terminal = [
                row
                for row in rows
                if (
                    str(row[2]) == "FAILED"
                    and (
                        (str(row[10]) == "FAILED" and str(row[8]) == "RELEASED")
                        or (str(row[10]) == "ABANDONED" and str(row[8]) == "EXPIRED")
                    )
                    and row[3]
                    and str(row[3]) == str(row[13])
                    and str(row[5]) == str(row[7])
                    and int(row[6] or 0) == int(row[14] or 0)
                )
            ]
            if len(rows) == 1 and len(bindable_terminal) == 1:
                row = bindable_terminal[0]
                lost = str(row[10]) == "ABANDONED"
                return {
                    "runtime_job_id": str(row[0]),
                    "input_hash": str(row[1]),
                    "runtime_job_status": str(row[2]),
                    "attempt_id": str(row[3]),
                    "worker_id": str(row[4]),
                    "lease_id": str(row[5]),
                    "fencing_token": int(row[6]),
                    "lease_status": str(row[8]),
                    "lease_expires_at": str(row[9]),
                    "execution_lifecycle": "LOST" if lost else "FAILED",
                    "terminal_reason": {
                        "code": "BOOK_OPENING_LEGACY_TERMINAL_RUNTIME_RECONCILED",
                        "runtime_job_id": str(row[0]),
                        "runtime_history_digest": history_digest,
                    },
                    "runtime_history_digest": history_digest,
                }
            marker_spec = RuntimeJobSpec(
                job_kind="BOOK_OPENING_EXECUTE",
                runtime_group="book_opening",
                subject_kind="BOOK_OPENING_RUN",
                subject_id=str(run["opening_run_id"]),
                project_id=str(run["project_id"]),
                dedupe_key=f"{run['opening_run_id']}:legacy-loss-marker:generation:1",
                input_snapshot={
                    "opening_run_id": str(run["opening_run_id"]),
                    "observed_version": int(run["version"]),
                    "frozen_request_digest": str(run["frozen_request_digest"]),
                    "opening_execution_id": execution_id,
                    "execution_generation": 1,
                    "recovery_intent_id": "",
                    "replacement_evaluation_operation_id": "",
                    "semantic_evaluation_operation_id": "",
                    "semantic_evaluation_execution_id": "",
                    "semantic_evaluation_generation": 0,
                    "semantic_execution_mode": "NONE",
                    "legacy_runtime_history_digest": history_digest,
                    "legacy_loss_marker": True,
                },
                max_attempts=1,
                lease_loss_policy=AUTHORITY_CONVERGENCE_REQUIRED,
            )
            scheduled = self.runtime_jobs.schedule_in_uow(uow, marker_spec)
            if str(scheduled["runtime_job_id"]) != marker_spec.runtime_job_id:
                raise KernelError(
                    "BOOK_OPENING_LEGACY_BINDING_AMBIGUOUS",
                    "legacy loss marker coalesced with another executable job",
                )
            runtime_job_id = marker_spec.runtime_job_id
            input_hash = marker_spec.input_hash
        reason = {
            "code": "BOOK_OPENING_LEGACY_RUNTIME_LOST",
            "opening_run_id": str(run["opening_run_id"]),
            "opening_execution_id": execution_id,
            "runtime_history_digest": history_digest,
        }
        terminal = self.runtime_jobs.terminalize_authority_abort_in_uow(
            uow,
            runtime_job_id=runtime_job_id,
            reason=reason,
        )
        if str(terminal["status"]) != "CANCELLED":
            raise KernelError(
                "BOOK_OPENING_LEGACY_BINDING_INVALID",
                "legacy RuntimeJob did not converge to a terminal loss marker",
            )
        return {
            "runtime_job_id": runtime_job_id,
            "input_hash": input_hash,
            "runtime_job_status": "CANCELLED",
            "attempt_id": str(terminal["attempt_id"]),
            "worker_id": str(terminal["worker_id"]),
            "lease_id": str(terminal["lease_id"]),
            "fencing_token": int(terminal["fencing_token"]),
            "lease_status": "RELEASED" if terminal["lease_id"] else "",
            "lease_expires_at": "",
            "execution_lifecycle": "ABORTED",
            "terminal_reason": reason,
            "runtime_history_digest": history_digest,
        }

    @staticmethod
    def _assessment_by_key(
        uow: AuthorityUnitOfWork,
        opening_run_id: str,
        kind: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        uow.cursor.execute(
            """
            SELECT recovery_assessment_id,assessment_kind,opening_run_id,
                   opening_version,disposition,snapshot,snapshot_hash
            FROM authority_book_opening_recovery_assessment
            WHERE opening_run_id=%s AND assessment_kind=%s AND idempotency_key=%s
            """,
            [opening_run_id, kind, idempotency_key],
        )
        row = uow.cursor.fetchone()
        return PostgresBookOpeningRecoveryApplication._assessment_row(row)

    @staticmethod
    def _assessment_by_id(
        uow: AuthorityUnitOfWork, assessment_id: str, *, lock: bool = False
    ) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if lock else ""
        uow.cursor.execute(
            f"""
            SELECT recovery_assessment_id,assessment_kind,opening_run_id,
                   opening_version,disposition,snapshot,snapshot_hash
            FROM authority_book_opening_recovery_assessment
            WHERE recovery_assessment_id=%s{suffix}
            """,
            [assessment_id],
        )
        return PostgresBookOpeningRecoveryApplication._assessment_row(
            uow.cursor.fetchone()
        )

    @staticmethod
    def _assessment_row(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(
            zip(
                (
                    "recovery_assessment_id",
                    "assessment_kind",
                    "opening_run_id",
                    "opening_version",
                    "disposition",
                    "snapshot",
                    "snapshot_hash",
                ),
                row,
                strict=True,
            )
        )

    def _insert_assessment(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        kind: str,
        idempotency_key: str,
        snapshot: dict[str, Any],
        disposition: str,
        execution: dict[str, Any] | None,
    ) -> str:
        assessment_id = _stable_id(
            "book-opening-recovery-assessment",
            run["opening_run_id"],
            kind,
            idempotency_key,
        )
        runtime = dict(snapshot.get("runtime") or {})
        runtime_identity_complete = all(
            (
                str(runtime.get("runtime_job_id") or ""),
                str(runtime.get("attempt_id") or ""),
                str(runtime.get("lease_id") or ""),
                str(runtime.get("worker_id") or ""),
                int(runtime.get("fencing_token") or 0) > 0,
            )
        )
        checkpoint = dict(snapshot.get("checkpoint") or {})
        evaluation = dict(snapshot.get("semantic_evaluation") or {})
        external = dict(snapshot.get("external_effect") or {})
        budget = dict(snapshot.get("budget") or {})
        budget_v2 = bool(
            str(budget.get("budget_scope_id") or "")
            and int(budget.get("budget_scope_revision") or 0) > 0
            and str(budget.get("budget_policy_hash") or "")
            and str(budget.get("budget_snapshot_digest") or "")
            and str(budget.get("outcome") or "")
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_recovery_assessment(
                recovery_assessment_id,assessment_kind,opening_run_id,
                opening_version,opening_execution_id,execution_generation,
                runtime_job_id,runtime_attempt_id,runtime_lease_id,
                runtime_worker_id,runtime_fencing_token,checkpoint_id,
                checkpoint_sequence,checkpoint_hash,evaluation_head_digest,
                external_effect_digest,policy_config_digest,
                authority_version_digest,snapshot,snapshot_hash,disposition,
                assessment_contract_version,budget_scope_id,
                budget_scope_revision,budget_policy_hash,
                budget_snapshot_digest,budget_outcome,idempotency_key
            ) VALUES (%s,%s,%s,%s,NULLIF(%s,''),%s,NULLIF(%s,''),NULLIF(%s,''),
                      NULLIF(%s,''),NULLIF(%s,''),%s,NULLIF(%s,''),%s,%s,
                      %s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,''),%s,
                      NULLIF(%s,''),NULLIF(%s,''),NULLIF(%s,''),%s)
            """,
            [
                assessment_id,
                kind,
                run["opening_run_id"],
                run["version"],
                str((execution or {}).get("opening_execution_id") or ""),
                (execution or {}).get("generation"),
                (
                    str(runtime.get("runtime_job_id") or "")
                    if runtime_identity_complete
                    else ""
                ),
                (
                    str(runtime.get("attempt_id") or "")
                    if runtime_identity_complete
                    else ""
                ),
                (
                    str(runtime.get("lease_id") or "")
                    if runtime_identity_complete
                    else ""
                ),
                (
                    str(runtime.get("worker_id") or "")
                    if runtime_identity_complete
                    else ""
                ),
                runtime.get("fencing_token") if runtime_identity_complete else None,
                str(checkpoint.get("checkpoint_id") or ""),
                int(checkpoint.get("sequence") or 0),
                str(checkpoint.get("checkpoint_hash") or ""),
                _canonical_hash(
                    {
                        "evaluation_execution_id": evaluation.get(
                            "evaluation_execution_id", ""
                        ),
                        "generation": evaluation.get("generation", 0),
                        "head_version": evaluation.get("head_version", 0),
                    }
                ),
                str(external.get("digest") or _canonical_hash([])),
                self._policy_digest(),
                self._application_release_digest(
                    str(run["execution_contract_version"])
                ),
                Jsonb(snapshot),
                _canonical_hash(snapshot),
                disposition,
                (
                    "book-opening-recovery-assessment.v2"
                    if budget_v2
                    else "book-opening-recovery-assessment.v1"
                ),
                str(budget.get("budget_scope_id") or "") if budget_v2 else "",
                (int(budget["budget_scope_revision"]) if budget_v2 else None),
                str(budget.get("budget_policy_hash") or "") if budget_v2 else "",
                (str(budget.get("budget_snapshot_digest") or "") if budget_v2 else ""),
                str(budget.get("outcome") or "") if budget_v2 else "",
                idempotency_key,
            ],
        )
        return assessment_id

    @staticmethod
    def _receipt_by_key(
        uow: AuthorityUnitOfWork,
        opening_run_id: str,
        kind: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        uow.cursor.execute(
            """
            SELECT recovery_receipt_id,receipt_kind,opening_run_id,
                   recovery_assessment_id,recovery_intent_id,result,result_hash
            FROM authority_book_opening_recovery_receipt
            WHERE opening_run_id=%s AND receipt_kind=%s AND idempotency_key=%s
            """,
            [opening_run_id, kind, idempotency_key],
        )
        row = uow.cursor.fetchone()
        if row is None:
            return None
        return dict(
            zip(
                (
                    "recovery_receipt_id",
                    "receipt_kind",
                    "opening_run_id",
                    "recovery_assessment_id",
                    "recovery_intent_id",
                    "result",
                    "result_hash",
                ),
                row,
                strict=True,
            )
        )

    @staticmethod
    def _require_loss_replay_binding(
        receipt: dict[str, Any], *, recovery_assessment_id: str
    ) -> None:
        if str(receipt["recovery_assessment_id"]) != recovery_assessment_id:
            raise KernelError(
                "BOOK_OPENING_RECOVERY_IDEMPOTENCY_CONFLICT",
                "execution-loss replay key is already bound to another assessment",
            )

    @staticmethod
    def _require_recovery_replay_binding(
        uow: AuthorityUnitOfWork,
        receipt: dict[str, Any],
        *,
        recovery_assessment_id: str,
        idempotency_key: str,
        reason: str,
        principal_id: str,
    ) -> None:
        intent_id = str(receipt["recovery_intent_id"] or "")
        expected_intent_id = _stable_id(
            "book-opening-recovery-intent",
            receipt["opening_run_id"],
            recovery_assessment_id,
            idempotency_key,
        )
        if (
            str(receipt["recovery_assessment_id"]) != recovery_assessment_id
            or not intent_id
            or intent_id != expected_intent_id
        ):
            raise KernelError(
                "BOOK_OPENING_RECOVERY_IDEMPOTENCY_CONFLICT",
                "recovery replay key is already bound to another assessment",
            )
        uow.cursor.execute(
            """
            SELECT recovery_intent_id,opening_run_id,recovery_assessment_id,
                   predecessor_execution_id,predecessor_generation,
                   successor_generation,idempotency_key,intent_hash,
                   authorized_by,authorization_reason
            FROM authority_book_opening_recovery_intent
            WHERE recovery_intent_id=%s
            """,
            [intent_id],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_RECOVERY_IDEMPOTENCY_CONFLICT",
                "recovery receipt has no immutable authorization intent",
            )
        intent = dict(
            zip(
                (
                    "recovery_intent_id",
                    "opening_run_id",
                    "recovery_assessment_id",
                    "predecessor_execution_id",
                    "predecessor_generation",
                    "successor_generation",
                    "idempotency_key",
                    "intent_hash",
                    "authorized_by",
                    "authorization_reason",
                ),
                row,
                strict=True,
            )
        )
        expected_payload = {
            "opening_run_id": str(intent["opening_run_id"]),
            "recovery_assessment_id": recovery_assessment_id,
            "predecessor_execution_id": str(intent["predecessor_execution_id"]),
            "predecessor_generation": int(intent["predecessor_generation"]),
            "successor_generation": int(intent["successor_generation"]),
            "actor_id": principal_id,
            "reason": reason,
        }
        if (
            str(intent["opening_run_id"]) != str(receipt["opening_run_id"])
            or str(intent["recovery_assessment_id"]) != recovery_assessment_id
            or str(intent["idempotency_key"]) != idempotency_key
            or str(intent["authorized_by"]) != principal_id
            or str(intent["authorization_reason"]) != reason
            or str(intent["intent_hash"]) != _canonical_hash(expected_payload)
        ):
            raise KernelError(
                "BOOK_OPENING_RECOVERY_IDEMPOTENCY_CONFLICT",
                "recovery replay request differs from its immutable authorization",
            )

    def _insert_receipt(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        kind: str,
        assessment_id: str,
        intent_id: str,
        predecessor_execution: tuple[str, int] | None,
        successor_execution: tuple[str, int] | None,
        idempotency_key: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        receipt_id = _stable_id(
            "book-opening-recovery-receipt",
            run["opening_run_id"],
            kind,
            idempotency_key,
        )
        result_hash = _canonical_hash(result)
        uow.cursor.execute(
            """
            INSERT INTO authority_book_opening_recovery_receipt(
                recovery_receipt_id,receipt_kind,opening_run_id,
                recovery_assessment_id,recovery_intent_id,
                predecessor_execution_id,predecessor_generation,
                successor_execution_id,successor_generation,result,result_hash,
                idempotency_key
            ) VALUES (%s,%s,%s,%s,NULLIF(%s,''),NULLIF(%s,''),%s,
                      NULLIF(%s,''),%s,%s,%s,%s)
            """,
            [
                receipt_id,
                kind,
                run["opening_run_id"],
                assessment_id,
                intent_id,
                str((predecessor_execution or ("", 0))[0]),
                (predecessor_execution or ("", None))[1],
                str((successor_execution or ("", 0))[0]),
                (successor_execution or ("", None))[1],
                Jsonb(result),
                result_hash,
                idempotency_key,
            ],
        )
        receipt = self._receipt_by_key(
            uow, str(run["opening_run_id"]), kind, idempotency_key
        )
        assert receipt is not None
        return receipt

    @staticmethod
    def _assessment_result(
        row: dict[str, Any], *, replayed: bool
    ) -> RecoveryAssessment:
        return RecoveryAssessment(
            recovery_assessment_id=str(row["recovery_assessment_id"]),
            assessment_kind=str(row["assessment_kind"]),
            opening_run_id=str(row["opening_run_id"]),
            disposition=str(row["disposition"]),
            snapshot_hash=str(row["snapshot_hash"]),
            snapshot=dict(row["snapshot"]),
            replayed=replayed,
        )

    @staticmethod
    def _receipt_result(row: dict[str, Any], *, replayed: bool) -> RecoveryReceipt:
        return RecoveryReceipt(
            recovery_receipt_id=str(row["recovery_receipt_id"]),
            receipt_kind=str(row["receipt_kind"]),
            opening_run_id=str(row["opening_run_id"]),
            recovery_assessment_id=str(row["recovery_assessment_id"]),
            recovery_intent_id=str(row["recovery_intent_id"] or ""),
            result_hash=str(row["result_hash"]),
            result=dict(row["result"]),
            replayed=replayed,
        )

    @staticmethod
    def _record_event(
        uow: AuthorityUnitOfWork,
        run: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        audit_id: str | None = None,
        outbox_id: str | None = None,
    ) -> None:
        uow.repositories.operation_graph.record_event(
            {
                "event_id": event_id or str(uuid4()),
                "audit_id": audit_id or str(uuid4()),
                "outbox_id": outbox_id or str(uuid4()),
                "aggregate_type": "book_opening",
                "aggregate_id": str(run["opening_run_id"]),
                "operation_id": str(run["root_operation_id"]),
                "project_id": str(run["project_id"]),
                "event_type": event_type,
                "correlation_id": str(run["root_operation_id"]),
                "causation_id": str(run["root_operation_id"]),
                "payload": payload,
            }
        )

    def _validated_checkpoint_cursor(
        self, uow: AuthorityUnitOfWork, run: dict[str, Any]
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT checkpoint_id,opening_execution_id,execution_generation,
                   checkpoint_sequence,semantic_work_key,owning_authority,
                   evidence_type,evidence_id,evidence_version,evidence_hash,
                   frozen_request_digest,predecessor_checkpoint_id,
                   predecessor_checkpoint_sequence,predecessor_checkpoint_hash,
                   checkpoint_hash,workflow_node_id
            FROM authority_book_opening_semantic_checkpoint
            WHERE opening_run_id=%s
            ORDER BY checkpoint_sequence
            FOR SHARE
            """,
            [run["opening_run_id"]],
        )
        rows = [tuple(row) for row in uow.cursor.fetchall()]
        expected_count = int(run["current_checkpoint_sequence"])
        if not rows:
            if (
                expected_count != 0
                or run["current_checkpoint_id"] is not None
                or str(run["current_checkpoint_hash"] or "")
            ):
                self._stale("Book Opening checkpoint cursor has no ledger evidence")
            return {
                "checkpoint_id": "",
                "sequence": 0,
                "checkpoint_hash": "",
                "entries": [],
            }
        if len(rows) != expected_count:
            self._stale("Book Opening checkpoint ledger is not contiguous")
        previous_id = ""
        previous_hash = ""
        for expected_sequence, row in enumerate(rows, start=1):
            (
                checkpoint_id,
                opening_execution_id,
                execution_generation,
                sequence,
                semantic_work_key,
                owning_authority,
                evidence_type,
                evidence_id,
                evidence_version,
                evidence_hash,
                frozen_request_digest,
                predecessor_id,
                predecessor_sequence,
                predecessor_hash,
                checkpoint_hash,
                workflow_node_id,
            ) = row
            if (
                int(sequence) != expected_sequence
                or str(frozen_request_digest) != str(run["frozen_request_digest"])
                or str(predecessor_id or "") != previous_id
                or int(predecessor_sequence or 0) != expected_sequence - 1
                or str(predecessor_hash or "") != previous_hash
            ):
                self._stale("Book Opening checkpoint hash chain is inconsistent")
            if str(run.get("workflow_contract_version") or "") == (
                "book-opening-workflow-v1"
            ):
                if not str(workflow_node_id or ""):
                    self._stale("workflow checkpoint has no durable node identity")
                uow.cursor.execute(
                    """
                    SELECT 1
                    FROM authority_book_opening_execution
                    WHERE opening_execution_id=%s AND opening_run_id=%s
                      AND generation=%s AND workflow_node_id=%s
                    """,
                    [
                        opening_execution_id,
                        run["opening_run_id"],
                        execution_generation,
                        workflow_node_id,
                    ],
                )
                if uow.cursor.fetchone() is None:
                    self._stale("workflow checkpoint differs from its execution node")
            self._verify_evidence(
                uow,
                run=run,
                semantic_work_key=str(semantic_work_key),
                owning_authority=str(owning_authority),
                evidence_type=str(evidence_type),
                evidence_id=str(evidence_id),
                evidence_version=int(evidence_version),
                evidence_hash=str(evidence_hash),
            )
            payload = {
                "opening_run_id": str(run["opening_run_id"]),
                "opening_execution_id": str(opening_execution_id),
                "execution_generation": int(execution_generation),
                "sequence": int(sequence),
                "semantic_work_key": str(semantic_work_key),
                "owning_authority": str(owning_authority),
                "evidence_type": str(evidence_type),
                "evidence_id": str(evidence_id),
                "evidence_version": int(evidence_version),
                "evidence_hash": str(evidence_hash),
                "frozen_request_digest": str(frozen_request_digest),
                "predecessor_checkpoint_id": previous_id,
                "predecessor_checkpoint_hash": previous_hash,
            }
            if str(checkpoint_hash) != _canonical_hash(payload):
                self._stale("Book Opening checkpoint content hash is invalid")
            previous_id = str(checkpoint_id)
            previous_hash = str(checkpoint_hash)
        if previous_id != str(
            run["current_checkpoint_id"] or ""
        ) or previous_hash != str(run["current_checkpoint_hash"] or ""):
            self._stale("Book Opening checkpoint cursor does not name the ledger head")
        return {
            "checkpoint_id": previous_id,
            "sequence": expected_count,
            "checkpoint_hash": previous_hash,
            "entries": [
                {
                    "checkpoint_id": str(row[0]),
                    "opening_execution_id": str(row[1]),
                    "execution_generation": int(row[2]),
                    "sequence": int(row[3]),
                    "semantic_work_key": str(row[4]),
                    "owning_authority": str(row[5]),
                    "evidence_type": str(row[6]),
                    "evidence_id": str(row[7]),
                    "evidence_version": int(row[8]),
                    "evidence_hash": str(row[9]),
                    "checkpoint_hash": str(row[14]),
                    "workflow_node_id": str(row[15] or ""),
                }
                for row in rows
            ],
        }

    @staticmethod
    def _narrative_search_evidence(
        uow: AuthorityUnitOfWork,
        *,
        search_id: str,
        project_id: str,
        workspace_id: str,
        book_id: str,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT search.generator_operation_name,search.logical_key,
                   search.version,search.status,
                   search.selected_candidate_asset_version_id,
                   search.input_snapshot_hash,
                   decision.selected_candidate_asset_version_id,
                   decision.candidate_set_hash,decision.comparison_hash
            FROM authority_story_narrative_search AS search
            JOIN authority_story_narrative_search_decision AS decision
              ON decision.search_id=search.search_id
            WHERE search.search_id=%s AND search.project_id=%s
              AND search.workspace_id=%s AND search.book_id=%s
            FOR SHARE OF search,decision
            """,
            [search_id, project_id, workspace_id, book_id],
        )
        row = uow.cursor.fetchone()
        if (
            row is None
            or str(row[3]) != "ACTIVATED"
            or not row[4]
            or str(row[4]) != str(row[6])
        ):
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "Narrative Search is not backed by an exact durable selection decision",
            )
        payload = {
            "search_id": search_id,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "book_id": book_id,
            "generator_operation_name": str(row[0]),
            "logical_key": str(row[1]),
            "version": int(row[2]),
            "status": str(row[3]),
            "selected_candidate_asset_version_id": str(row[4]),
            "input_snapshot_hash": str(row[5]),
            "candidate_set_hash": str(row[7]),
            "comparison_hash": str(row[8]),
        }
        return {
            **payload,
            "evidence_hash": _canonical_hash(payload),
        }

    def _node_receipt_authoritative_evidence(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: Mapping[str, Any],
        node_receipt_id: str,
    ) -> dict[str, Any]:
        uow.cursor.execute(
            """
            SELECT receipt.workflow_node_id,node.node_kind,node.node_key,
                   node.input_hash,receipt.result,receipt.result_hash,
                   receipt.authoritative_evidence_hash,
                   receipt.reviewable_artifact_kind,
                   receipt.reviewable_asset_version_ids,
                   receipt.opening_execution_id,receipt.execution_generation
            FROM authority_book_opening_node_receipt AS receipt
            JOIN authority_book_opening_workflow_node AS node
              ON node.workflow_node_id=receipt.workflow_node_id
             AND node.opening_run_id=receipt.opening_run_id
            WHERE receipt.node_receipt_id=%s AND receipt.opening_run_id=%s
            FOR SHARE OF receipt,node
            """,
            [node_receipt_id, run["opening_run_id"]],
        )
        row = uow.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "workflow node receipt is missing",
            )
        result = dict(row[4])
        result_hash = _canonical_hash(result)
        if result_hash != str(row[5]):
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "workflow node receipt result hash drifted",
            )

        def asset(item: Mapping[str, Any]) -> dict[str, Any]:
            uow.cursor.execute(
                """
                SELECT version.content_hash,binding.binding_id,
                       binding.contract_type,binding.logical_key,
                       version.lifecycle,version.eligibility,version.governance,
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
                FOR SHARE OF version,asset,binding,active
                """,
                [run["book_id"], item["asset_version_id"], run["project_id"]],
            )
            plan = uow.cursor.fetchone()
            if (
                plan is None
                or str(plan[0]) != str(item["content_hash"])
                or str(plan[1]) != str(item["binding_id"])
                or tuple(str(value) for value in plan[4:7])
                != ("ACTIVE", "ELIGIBLE", "CLEAR")
                or str(plan[7]) != "CURRENT"
                or str(plan[8]) != str(item["asset_version_id"])
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "node receipt Plan asset is no longer authoritative",
                )
            return {
                "asset_version_id": str(item["asset_version_id"]),
                "content_hash": str(item["content_hash"]),
                "binding_id": str(item["binding_id"]),
                "contract_type": str(plan[2]),
                "logical_key": str(plan[3]),
            }

        def search(search_id: str, asset_version_id: str) -> dict[str, Any]:
            item = self._narrative_search_evidence(
                uow,
                search_id=search_id,
                project_id=str(run["project_id"]),
                workspace_id=str(run["workspace_id"]),
                book_id=str(run["book_id"]),
            )
            if str(item["selected_candidate_asset_version_id"]) != asset_version_id:
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "node receipt search selection changed",
                )
            return {
                "search_id": search_id,
                "search_evidence_hash": str(item["evidence_hash"]),
            }

        node_kind = str(row[1])
        inner: list[dict[str, Any]] = []
        assets: list[str] = []
        if node_kind == "BOOK_PLAN":
            plan_item = asset(result)
            inner.extend(
                (
                    plan_item,
                    search(str(result["search_id"]), plan_item["asset_version_id"]),
                )
            )
            assets.append(plan_item["asset_version_id"])
        elif node_kind in {"VOLUME_PORTFOLIO", "INITIAL_ARC_SCOPE"}:
            collection = (
                "volume_plan_versions"
                if node_kind == "VOLUME_PORTFOLIO"
                else "arc_plan_versions"
            )
            for raw in result.get(collection) or ():
                plan_item = asset(dict(raw))
                inner.extend(
                    (
                        plan_item,
                        search(str(raw["search_id"]), plan_item["asset_version_id"]),
                    )
                )
                assets.append(plan_item["asset_version_id"])
        elif node_kind == "CURRENT_VOLUME":
            uow.cursor.execute(
                """
                SELECT binding.binding_id
                FROM story_plan_binding AS binding
                WHERE binding.project_id=%s AND binding.book_id=%s
                  AND binding.asset_version_id=%s
                """,
                [
                    run["project_id"],
                    run["book_id"],
                    result["current_volume_plan_version_id"],
                ],
            )
            binding = uow.cursor.fetchone()
            if binding is None:
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "current Volume binding is missing",
                )
            plan_item = asset(
                {
                    "asset_version_id": result["current_volume_plan_version_id"],
                    "content_hash": result["current_volume_content_hash"],
                    "binding_id": str(binding[0]),
                }
            )
            inner.append(plan_item)
            assets.append(plan_item["asset_version_id"])
        elif node_kind == "INPUT_SNAPSHOT":
            uow.cursor.execute(
                """
                SELECT snapshot_hash,workspace_id,book_id
                FROM authority_book_production_input_snapshot
                WHERE snapshot_id=%s AND project_id=%s
                FOR SHARE
                """,
                [result["snapshot_id"], run["project_id"]],
            )
            snapshot = uow.cursor.fetchone()
            if (
                snapshot is None
                or str(snapshot[0]) != str(result["snapshot_hash"])
                or str(snapshot[1]) != str(run["workspace_id"])
                or str(snapshot[2]) != str(run["book_id"])
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "node receipt Input Snapshot is no longer authoritative",
                )
            inner.append(
                {
                    "snapshot_id": str(result["snapshot_id"]),
                    "snapshot_hash": str(result["snapshot_hash"]),
                }
            )
        else:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "workflow node receipt carries an unknown node kind",
            )
        if assets != [str(item) for item in row[8]]:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "node receipt reviewable asset set drifted",
            )
        authoritative_payload = {
            "contract_version": "book-opening-node-authoritative-evidence.v1",
            "opening_run_id": str(run["opening_run_id"]),
            "workflow_node_id": str(row[0]),
            "node_kind": node_kind,
            "node_key": str(row[2]),
            "node_input_hash": str(row[3]),
            "result_hash": result_hash,
            "reviewable_artifact_kind": str(row[7]),
            "reviewable_asset_version_ids": assets,
            "authoritative_inner_evidence": inner,
        }
        authoritative_hash = _canonical_hash(authoritative_payload)
        if authoritative_hash != str(row[6]):
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "workflow node authoritative evidence hash drifted",
            )
        return {
            "workflow_node_id": str(row[0]),
            "node_kind": node_kind,
            "authoritative_evidence_hash": authoritative_hash,
            "opening_execution_id": str(row[9]),
            "execution_generation": int(row[10]),
        }

    def _verify_evidence(
        self,
        uow: AuthorityUnitOfWork,
        *,
        run: dict[str, Any],
        semantic_work_key: str,
        owning_authority: str,
        evidence_type: str,
        evidence_id: str,
        evidence_version: int,
        evidence_hash: str,
    ) -> None:
        if (owning_authority, evidence_type) == (
            "BOOK_AUTHORITY",
            "BOOK_OPENING_NODE_RECEIPT",
        ):
            evidence = self._node_receipt_authoritative_evidence(
                uow,
                run=run,
                node_receipt_id=evidence_id,
            )
            if (
                evidence_version != 1
                or str(evidence["authoritative_evidence_hash"]) != evidence_hash
                or semantic_work_key
                != (
                    f"book-opening-node:{evidence['node_kind']}:"
                    f"{evidence['workflow_node_id']}"
                )
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "checkpoint differs from its authoritative workflow node receipt",
                )
            return
        if (owning_authority, evidence_type) == (
            "STORY_PLANNING",
            "NARRATIVE_SEARCH",
        ):
            evidence = self._narrative_search_evidence(
                uow,
                search_id=evidence_id,
                project_id=str(run["project_id"]),
                workspace_id=str(run["workspace_id"]),
                book_id=str(run["book_id"]),
            )
            if (
                int(evidence["version"]) != evidence_version
                or str(evidence["evidence_hash"]) != evidence_hash
                or semantic_work_key
                != (f"{evidence['generator_operation_name']}:{evidence['logical_key']}")
                or self._expected_search_graph(uow, run).get(semantic_work_key)
                != evidence_id
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "checkpoint differs from Planning-owned search evidence",
                )
            return
        if (owning_authority, evidence_type) == (
            "STORY_PLANNING",
            "NARRATIVE_SEARCH_BRANCH",
        ):
            uow.cursor.execute(
                """
                SELECT membership.membership_id,membership.search_id,
                       membership.branch_key,
                       membership.candidate_asset_version_id,
                       membership.generation_operation_id,
                       generation.input_snapshot_hash,
                       candidate.content_hash,membership.projection_hash,
                       membership.strategy_fingerprint,
                       membership.qualification_hash,
                       membership.branch_evidence_contract_version,
                       membership.branch_evidence_hash
                FROM authority_story_narrative_search_candidate AS membership
                JOIN authority_story_planning_generation AS generation
                  ON generation.operation_id=
                     membership.generation_operation_id
                 AND generation.narrative_search_id=membership.search_id
                 AND generation.narrative_search_branch_key=
                     membership.branch_key
                 AND generation.candidate_asset_version_id=
                     membership.candidate_asset_version_id
                JOIN authority_story_planning_candidate AS candidate
                  ON candidate.generation_id=generation.generation_id
                 AND candidate.candidate_asset_version_id=
                     membership.candidate_asset_version_id
                JOIN authority_story_narrative_search AS search
                  ON search.search_id=membership.search_id
                WHERE membership.membership_id=%s
                  AND search.project_id=%s AND search.workspace_id=%s
                  AND search.book_id=%s
                FOR SHARE OF membership,generation,candidate,search
                """,
                [
                    evidence_id,
                    run["project_id"],
                    run["workspace_id"],
                    run["book_id"],
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "Planning branch checkpoint has no exact durable membership",
                )
            payload = {
                "membership_id": str(row[0]),
                "search_id": str(row[1]),
                "branch_key": str(row[2]),
                "candidate_asset_version_id": str(row[3]),
                "generation_operation_id": str(row[4]),
                "generation_input_snapshot_hash": str(row[5]),
                "candidate_content_hash": str(row[6]),
                "projection_hash": str(row[7]),
                "strategy_fingerprint": str(row[8]),
                "qualification_hash": str(row[9]),
                "evidence_version": 1,
            }
            expected_key = f"narrative-search-branch:{row[1]}:{row[2]}"
            if (
                evidence_version != 1
                or str(row[10]) != "narrative-search-branch-evidence.v1"
                or str(row[11]) != evidence_hash
                or _canonical_hash(payload) != evidence_hash
                or semantic_work_key != expected_key
                or str(row[1])
                not in set(self._expected_search_graph(uow, run).values())
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "checkpoint differs from Planning-owned branch evidence",
                )
            return
        if (owning_authority, evidence_type) == (
            "STORY_PLANNING",
            "NARRATIVE_SEARCH_BRANCH_RECONCILIATION",
        ):
            uow.cursor.execute(
                """
                SELECT reconciliation.reconciliation_evidence_id,
                       membership.membership_id,membership.search_id,
                       membership.branch_key,
                       membership.candidate_asset_version_id,
                       membership.generation_operation_id,
                       reconciliation.source_branch_evidence_contract_version,
                       reconciliation.opening_run_id,
                       reconciliation.opening_execution_id,
                       reconciliation.execution_generation,
                       generation.input_snapshot_hash,candidate.content_hash,
                       membership.projection_hash,membership.strategy_fingerprint,
                       membership.qualification_hash,
                       reconciliation.qualification_receipt_set_hash,
                       reconciliation.reconciled_branch_evidence_hash,
                       reconciliation.reconciliation_contract_version,
                       reconciliation.evidence_version,
                       reconciliation.evidence_payload,
                       reconciliation.evidence_hash,membership.projection,
                       membership.branch_evidence_contract_version,
                       membership.branch_evidence_hash
                FROM authority_story_narrative_branch_reconciliation_evidence
                     AS reconciliation
                JOIN authority_story_narrative_search_candidate AS membership
                  ON membership.membership_id=reconciliation.membership_id
                 AND membership.search_id=reconciliation.search_id
                 AND membership.branch_key=reconciliation.branch_key
                 AND membership.candidate_asset_version_id=
                     reconciliation.candidate_asset_version_id
                 AND membership.generation_operation_id=
                     reconciliation.generation_operation_id
                 AND membership.branch_evidence_contract_version=
                     reconciliation.source_branch_evidence_contract_version
                JOIN authority_story_planning_generation AS generation
                  ON generation.operation_id=membership.generation_operation_id
                 AND generation.narrative_search_id=membership.search_id
                 AND generation.narrative_search_branch_key=membership.branch_key
                 AND generation.candidate_asset_version_id=
                     membership.candidate_asset_version_id
                JOIN authority_story_planning_candidate AS candidate
                  ON candidate.generation_id=generation.generation_id
                 AND candidate.candidate_asset_version_id=
                     membership.candidate_asset_version_id
                JOIN authority_story_narrative_search AS search
                  ON search.search_id=membership.search_id
                WHERE reconciliation.reconciliation_evidence_id=%s
                  AND reconciliation.opening_run_id=%s
                  AND search.project_id=%s AND search.workspace_id=%s
                  AND search.book_id=%s
                FOR SHARE OF reconciliation,membership,generation,candidate,search
                """,
                [
                    evidence_id,
                    run["opening_run_id"],
                    run["project_id"],
                    run["workspace_id"],
                    run["book_id"],
                ],
            )
            row = uow.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "Planning reconciliation checkpoint has no exact sidecar evidence",
                )
            stored_payload = dict(row[19])
            qualification_receipts = stored_payload.get("qualification_receipts")
            if (
                not isinstance(qualification_receipts, list)
                or not qualification_receipts
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "Planning reconciliation omitted semantic receipt lineage",
                )
            qualification_ids = [
                str(item.get("qualification_id") or "")
                for item in qualification_receipts
                if isinstance(item, dict)
            ]
            if (
                len(qualification_ids) != len(qualification_receipts)
                or any(not item for item in qualification_ids)
                or len(set(qualification_ids)) != len(qualification_ids)
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "Planning reconciliation semantic receipt identity is invalid",
                )
            uow.cursor.execute(
                """
                SELECT qualification_id,design_layer,profile_id,profile_version,
                       profile_hash,evaluation_hash,qualification_hash,
                       evaluator_execution_class,evaluation_operation_id,
                       evaluation_attempt_id,evaluation_asset_version_id,
                       evaluation_evidence_hash,
                       provider_model_call_asset_version_id,
                       provider_model_call_content_hash,provider_evidence_hash,
                       provider_result_hash,provider_route_snapshot_id
                FROM authority_narrative_design_qualification
                WHERE qualification_id=ANY(%s)
                  AND project_id=%s AND book_id=%s AND asset_version_id=%s
                  AND generation_operation_id=%s
                  AND qualification_status='PASS'
                  AND trust_boundary='INDEPENDENT'
                ORDER BY design_layer
                FOR SHARE
                """,
                [
                    qualification_ids,
                    run["project_id"],
                    run["book_id"],
                    row[4],
                    row[5],
                ],
            )
            receipt_rows = uow.cursor.fetchall()
            current_receipts = [
                {
                    "qualification_id": str(item[0]),
                    "design_layer": str(item[1]),
                    "profile_id": str(item[2]),
                    "profile_version": str(item[3]),
                    "profile_hash": str(item[4]),
                    "evaluation_hash": str(item[5]),
                    "qualification_hash": str(item[6]),
                    "evaluator_execution_class": str(item[7]),
                    "evaluation_operation_id": str(item[8]),
                    "evaluation_attempt_id": str(item[9]),
                    "evaluation_asset_version_id": str(item[10]),
                    "evaluation_evidence_hash": str(item[11]),
                    "provider_model_call_asset_version_id": str(item[12] or ""),
                    "provider_model_call_content_hash": str(item[13] or ""),
                    "provider_evidence_hash": str(item[14] or ""),
                    "provider_result_hash": str(item[15] or ""),
                    "provider_route_snapshot_id": str(item[16] or ""),
                }
                for item in receipt_rows
            ]
            branch_payload = {
                "membership_id": str(row[1]),
                "search_id": str(row[2]),
                "branch_key": str(row[3]),
                "candidate_asset_version_id": str(row[4]),
                "generation_operation_id": str(row[5]),
                "generation_input_snapshot_hash": str(row[10]),
                "candidate_content_hash": str(row[11]),
                "projection_hash": str(row[12]),
                "strategy_fingerprint": str(row[13]),
                "qualification_hash": str(row[14]),
                "evidence_version": 1,
            }
            expected_payload = {
                **branch_payload,
                "source_branch_evidence_contract_version": "legacy-unbound",
                "opening_run_id": str(row[7]),
                "opening_execution_id": str(row[8]),
                "execution_generation": int(row[9]),
                "qualification_receipt_set_hash": _canonical_hash(current_receipts),
                "qualification_receipts": current_receipts,
                "reconciled_branch_evidence_hash": _canonical_hash(branch_payload),
                "reconciliation_contract_version": (
                    "narrative-search-branch-reconciliation.v1"
                ),
            }
            expected_key = f"narrative-search-branch:{row[2]}:{row[3]}"
            if (
                evidence_version != 1
                or int(row[18]) != 1
                or str(row[6]) != "legacy-unbound"
                or str(row[17]) != "narrative-search-branch-reconciliation.v1"
                or str(row[22]) != "legacy-unbound"
                or str(row[23]) != ""
                or _canonical_hash(dict(row[21])) != str(row[12])
                or _canonical_hash(current_receipts) != str(row[15])
                or _canonical_hash(branch_payload) != str(row[16])
                or expected_payload != stored_payload
                or _canonical_hash(expected_payload) != str(row[20])
                or str(row[20]) != evidence_hash
                or semantic_work_key != expected_key
                or str(row[2])
                not in set(self._expected_search_graph(uow, run).values())
            ):
                raise KernelError(
                    "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                    "checkpoint differs from revalidated Planning sidecar evidence",
                )
            return
        selectors = {
            ("STORY_PLANNING", "PLANNING_GENERATION"): (
                "authority_story_planning_generation",
                "generation_id",
                "version",
                "input_snapshot_hash",
            ),
            ("BOOK_AUTHORITY", "INPUT_SNAPSHOT"): (
                "authority_book_production_input_snapshot",
                "snapshot_id",
                "0",
                "snapshot_hash",
            ),
        }
        selector = selectors.get((owning_authority, evidence_type))
        if selector is None:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_UNSUPPORTED",
                "checkpoint evidence must name a supported owning Authority",
            )
        table, identity_column, version_column, hash_column = selector
        expected_key = (
            f"planning-generation:{evidence_id}"
            if evidence_type == "PLANNING_GENERATION"
            else "book-opening:input-snapshot-resolved"
        )
        if semantic_work_key != expected_key:
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "checkpoint work key differs from its authoritative evidence identity",
            )
        if version_column == "0":
            sql = (
                f"SELECT 0,{hash_column},workspace_id,book_id,NULL::text "
                f"FROM {table} WHERE {identity_column}=%s AND project_id=%s FOR SHARE"
            )
        else:
            sql = (
                f"SELECT {version_column},{hash_column},workspace_id,book_id,"
                f"COALESCE(narrative_search_id,'') FROM {table} "
                f"WHERE {identity_column}=%s AND project_id=%s FOR SHARE"
            )
        uow.cursor.execute(sql, [evidence_id, run["project_id"]])
        row = uow.cursor.fetchone()
        expected_search_ids = set(self._expected_search_graph(uow, run).values())
        if (
            row is None
            or int(row[0]) != evidence_version
            or str(row[1]) != evidence_hash
            or str(row[2]) != str(run["workspace_id"])
            or str(row[3]) != str(run["book_id"])
            or (
                evidence_type == "PLANNING_GENERATION"
                and str(row[4]) not in expected_search_ids
            )
        ):
            raise KernelError(
                "BOOK_OPENING_CHECKPOINT_EVIDENCE_DRIFT",
                "checkpoint reference differs from authoritative durable evidence",
            )

    @staticmethod
    def _workflow_node_value(
        uow: AuthorityUnitOfWork,
        workflow_node_id: str,
        column: str,
    ) -> str:
        allowed = {"node_kind", "node_key", "input_hash"}
        if column not in allowed or not workflow_node_id:
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_MISSING",
                "recovery workflow node identity is incomplete",
            )
        uow.cursor.execute(
            f"SELECT {column} FROM authority_book_opening_workflow_node "
            "WHERE workflow_node_id=%s",
            [workflow_node_id],
        )
        row = uow.cursor.fetchone()
        if row is None or not str(row[0] or ""):
            raise KernelError(
                "BOOK_OPENING_WORKFLOW_NODE_MISSING",
                "recovery workflow node evidence is missing",
            )
        return str(row[0])

    @classmethod
    def _workflow_node_kind(
        cls, uow: AuthorityUnitOfWork, workflow_node_id: str
    ) -> str:
        return cls._workflow_node_value(uow, workflow_node_id, "node_kind")

    @classmethod
    def _workflow_node_key(cls, uow: AuthorityUnitOfWork, workflow_node_id: str) -> str:
        return cls._workflow_node_value(uow, workflow_node_id, "node_key")

    @classmethod
    def _workflow_node_input_hash(
        cls, uow: AuthorityUnitOfWork, workflow_node_id: str
    ) -> str:
        return cls._workflow_node_value(uow, workflow_node_id, "input_hash")

    @staticmethod
    def _expected_search_graph(
        uow: AuthorityUnitOfWork,
        run: dict[str, Any],
    ) -> dict[str, str]:
        frozen = dict(run["frozen_request"])
        stable_key = str(frozen.get("idempotency_key") or "")
        arc_keys = [str(item) for item in frozen.get("arc_logical_keys") or []]
        if not stable_key or not arc_keys or any(not item for item in arc_keys):
            raise KernelError(
                "BOOK_OPENING_FROZEN_GRAPH_INVALID",
                "Opening frozen request cannot derive its exact semantic work graph",
            )
        if str(run.get("workflow_contract_version") or "") == (
            "book-opening-workflow-v1"
        ):
            uow.cursor.execute(
                """
                SELECT ordinal
                FROM authority_book_opening_workflow_node
                WHERE workflow_node_id=%s AND opening_run_id=%s
                """,
                [run.get("current_workflow_node_id"), run["opening_run_id"]],
            )
            current = uow.cursor.fetchone()
            if current is None:
                raise KernelError(
                    "BOOK_OPENING_FROZEN_GRAPH_INVALID",
                    "Opening workflow has no current node ordinal",
                )
            ordinal = int(current[0])
            work: list[tuple[str, str]] = [("book_plan.generate", "book:main")]
            if ordinal >= 2:
                uow.cursor.execute(
                    """
                    SELECT version.content
                    FROM authority_book_opening_node_receipt AS receipt
                    JOIN authority_book_opening_workflow_node AS node
                      ON node.workflow_node_id=receipt.workflow_node_id
                     AND node.opening_run_id=receipt.opening_run_id
                    JOIN authority_asset_version AS version
                      ON version.asset_version_id=
                         receipt.result->>'asset_version_id'
                    WHERE receipt.opening_run_id=%s AND node.node_kind='BOOK_PLAN'
                    """,
                    [run["opening_run_id"]],
                )
                book = uow.cursor.fetchone()
                skeleton = list(
                    (dict(book[0]) if book else {}).get("volume_skeleton") or ()
                )
                if not skeleton:
                    raise KernelError(
                        "BOOK_OPENING_FROZEN_GRAPH_INVALID",
                        "workflow Volume graph cannot be derived from its Book Plan receipt",
                    )
                work.extend(
                    ("volume_plan.generate", f"volume:{volume_ordinal}")
                    for volume_ordinal in range(1, len(skeleton) + 1)
                )
            if ordinal >= 4:
                work.extend(("arc_plan.generate", key) for key in arc_keys)
        else:
            work = [
                ("book_plan.generate", "book:main"),
                ("volume_plan.generate", "volume:1"),
                *(("arc_plan.generate", key) for key in arc_keys),
            ]
        graph: dict[str, str] = {}
        for generator, logical_key in work:
            semantic_work_key = f"{generator}:{logical_key}"
            search_key = f"{stable_key}:{generator}:{logical_key}:narrative-search"
            graph[semantic_work_key] = "narrative-search:" + _canonical_hash(
                {
                    "project_id": str(run["project_id"]),
                    "book_id": str(run["book_id"]),
                    "stable_idempotency_key": search_key,
                }
            ).removeprefix("sha256:")
        return graph

    def _checkpoint(self, point: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(point)

    @staticmethod
    def _semantic_replacement_required(
        *, evaluation: dict[str, Any], disposition: str
    ) -> bool:
        """INVARIANT: Apply the frozen bounded replacement policy before creating Intent.

        A non-terminal semantic Operation remains the Command Kernel's
        execution truth.  The successor Opening generation re-enters through
        its deterministic command identity and lets the normal worker replay
        or fenced takeover converge that same Operation.  Only immutable
        terminal predecessors receive an append-only replacement generation.
        """
        operation_id = str(evaluation.get("operation_id") or "")
        if not operation_id:
            return False
        operation_status = str(evaluation.get("operation_status") or "")
        terminal_statuses = {
            "SUCCEEDED",
            "FAILED_FINAL",
            "CANCELLED",
            "DEAD_LETTER",
            "COMPENSATED",
            "COMPENSATION_FAILED",
        }
        if operation_status not in terminal_statuses:
            # WHY: The successor Opening re-enters the same deterministic semantic
            # command.  Its governed scheduler owns Attempt/effect/output
            # replay, including a durable success receipt that has not yet
            # materialized output.  UNKNOWN was rejected before this policy
            # check, so continuing the same generation cannot duplicate an
            # unproven Provider effect.
            return False
        generation = int(evaluation.get("generation") or 0)
        if generation <= 0:
            raise KernelError(
                "BOOK_OPENING_SEMANTIC_REPLACEMENT_POLICY_DENIED",
                "semantic replacement requires an exact generation head",
            )
        if generation >= BOOK_OPENING_MAX_SEMANTIC_EVALUATION_GENERATIONS:
            raise KernelError(
                "BOOK_OPENING_SEMANTIC_REPLACEMENT_POLICY_EXHAUSTED",
                "semantic Evaluation replacement generation limit is exhausted",
            )
        if disposition == "PROVEN_SUCCESS":
            allowed = {"SUCCEEDED"}
        elif disposition in {"PROVEN_NO_EFFECT", "PROVEN_TERMINAL_FAILURE"}:
            allowed = terminal_statuses - {"SUCCEEDED"}
        else:
            allowed = set()
        if operation_status not in allowed:
            raise KernelError(
                "BOOK_OPENING_SEMANTIC_REPLACEMENT_POLICY_DENIED",
                "semantic predecessor terminal status is not authorized by the recovery policy",
            )
        return True

    def _policy_digest(self) -> str:
        return _canonical_hash(
            {
                "version": BOOK_OPENING_RECOVERY_POLICY_VERSION,
                "lease_loss_policy": AUTHORITY_CONVERGENCE_REQUIRED,
                "unknown_external_effect": "FAIL_CLOSED",
                "provider_in_recovery": False,
                "semantic_evaluation_replacement": {
                    "allowed_terminal_operation_statuses": [
                        "SUCCEEDED",
                        "CANCELLED",
                        "DEAD_LETTER",
                        "FAILED_FINAL",
                        "COMPENSATED",
                        "COMPENSATION_FAILED",
                    ],
                    "proven_success_requires_durable_bundle": True,
                    "max_generations": (
                        BOOK_OPENING_MAX_SEMANTIC_EVALUATION_GENERATIONS
                    ),
                },
            }
        )

    @staticmethod
    def _execution_policy_digest() -> str:

        return _canonical_hash(
            {
                "version": BOOK_OPENING_EXECUTION_POLICY_VERSION,
                "lease_loss_policy": AUTHORITY_CONVERGENCE_REQUIRED,
                "max_runtime_attempts": 1,
                "generic_takeover": False,
                "provider_execution_path": "GOVERNED_COMMAND_WORKER_ONLY",
            }
        )

    def _authority_digest(
        self,
        execution_contract_version: str = BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
    ) -> str:

        payload = {
            "version": BOOK_OPENING_AUTHORITY_VERSION,
            "execution_contract": execution_contract_version,
        }
        if execution_contract_version != BOOK_OPENING_EXECUTION_CONTRACT_VERSION:
            runtime_job_kind, runtime_group = (
                _runtime_job_identity_for_execution_contract(execution_contract_version)
            )
            payload.update(
                {
                    "runtime_job_kind": runtime_job_kind,
                    "runtime_group": runtime_group,
                }
            )
        return _canonical_hash(payload)

    def _application_release_digest(
        self,
        execution_contract_version: str = BOOK_OPENING_EXECUTION_CONTRACT_VERSION,
    ) -> str:

        return _canonical_hash(
            {
                "authority_contract_digest": self._authority_digest(
                    execution_contract_version
                ),
                "application_build_id": self.application_build_id,
                "commit_sha": self.commit_sha,
            }
        )

    @staticmethod
    def _stale(message: str) -> None:
        raise KernelError(
            "BOOK_OPENING_RECOVERY_REASSESSMENT_REQUIRED",
            f"{message}; create a fresh RecoveryAssessment",
        )


__all__ = [
    "BOOK_OPENING_AUTHORITY_VERSION",
    "BOOK_OPENING_EXECUTION_CONTRACT_VERSION",
    "BOOK_OPENING_WORKFLOW_EXECUTION_CONTRACT_VERSION",
    "BOOK_OPENING_EXECUTION_POLICY_VERSION",
    "BOOK_OPENING_MAX_SEMANTIC_EVALUATION_GENERATIONS",
    "BOOK_OPENING_RECOVERY_POLICY_VERSION",
    "PostgresBookOpeningRecoveryApplication",
    "RecoveryAssessment",
    "RecoveryReceipt",
    "book_opening_execution_contract_version",
    "book_opening_runtime_job_identity",
]
