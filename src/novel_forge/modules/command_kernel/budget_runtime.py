from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Iterable, Mapping
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class BudgetAssessmentOutcome(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    ELIGIBLE = "ELIGIBLE"
    EXHAUSTED = "EXHAUSTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


def canonical_budget_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """INVARIANT: Validate and hash the immutable Provider budget contract.

    Provider work is accepted only with explicit finite call, token and cost
    limits.  Projection-only work is a separate, zero-Provider contract rather
    than an implicit zero-value budget.
    """
    raw = dict(policy)
    execution_mode = str(raw.get("execution_mode") or "").strip().upper()
    if execution_mode not in {"PROVIDER_ALLOWED", "PROJECTION_ONLY"}:
        raise KernelError(
            "BUDGET_SCOPE_POLICY_INVALID",
            "budget scope policy requires a supported execution_mode",
        )
    raw["execution_mode"] = execution_mode
    if execution_mode == "PROVIDER_ALLOWED":
        accounting_basis = str(raw.get("accounting_basis") or "PRICED").strip().upper()
        if accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}:
            raise KernelError(
                "BUDGET_SCOPE_POLICY_INVALID",
                "budget scope accounting basis is invalid",
            )
        try:
            provider_call_limit = int(raw.get("provider_call_limit"))
            token_limit = int(raw.get("token_limit"))
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "BUDGET_SCOPE_POLICY_INVALID",
                "budget scope policy limits are invalid",
            ) from exc
        if provider_call_limit <= 0 or token_limit <= 0:
            raise KernelError(
                "BUDGET_SCOPE_POLICY_INVALID",
                "budget scope policy limits must be positive",
            )
        raw["provider_call_limit"] = provider_call_limit
        raw["token_limit"] = token_limit
        per_call_tokens = int(raw.get("per_call_token_limit", token_limit))
        if per_call_tokens <= 0 or per_call_tokens > token_limit:
            raise KernelError(
                "BUDGET_SCOPE_POLICY_INVALID",
                "per-call budget limits must be positive and within scope limits",
            )
        if "per_call_token_limit" in raw:
            raw["per_call_token_limit"] = per_call_tokens
        if accounting_basis == "ACCOUNT_ENTITLEMENT":
            if any(
                field in raw for field in ("cost_limit_usd", "per_call_cost_limit_usd")
            ):
                raise KernelError(
                    "BUDGET_SCOPE_POLICY_INVALID",
                    "account entitlement budget must not declare monetary limits",
                )
            if (
                not str(raw.get("authorization_ref") or "").strip()
                or str(raw.get("cost_observability") or "").upper() != "UNKNOWN"
            ):
                raise KernelError(
                    "BUDGET_SCOPE_POLICY_INVALID",
                    "account entitlement requires authorization and UNKNOWN cost observability",
                )
            raw["accounting_basis"] = accounting_basis
            raw["cost_observability"] = "UNKNOWN"
        else:
            try:
                cost_limit = _amount(str(raw.get("cost_limit_usd")))
                per_call_cost = _amount(
                    str(raw.get("per_call_cost_limit_usd", cost_limit))
                )
            except (TypeError, ValueError) as exc:
                raise KernelError(
                    "BUDGET_SCOPE_POLICY_INVALID",
                    "budget scope policy cost limits are invalid",
                ) from exc
            if cost_limit <= 0 or per_call_cost <= 0 or per_call_cost > cost_limit:
                raise KernelError(
                    "BUDGET_SCOPE_POLICY_INVALID",
                    "per-call budget limits must be positive and within scope limits",
                )
            raw["cost_limit_usd"] = _decimal_text(cost_limit)
            if "per_call_cost_limit_usd" in raw:
                raw["per_call_cost_limit_usd"] = _decimal_text(per_call_cost)
    normalized = _canonical_value(raw)
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping guarantees it
        raise AssertionError("canonical budget policy must be an object")
    return {
        "policy_snapshot": normalized,
        "policy_hash": _canonical_hash(normalized),
    }


def canonical_budget_snapshot(
    *,
    scope: Mapping[str, Any],
    reservations: Iterable[Mapping[str, Any]],
    evidence_links: Iterable[Mapping[str, Any]],
    legacy_attributions: Iterable[Mapping[str, Any]] = (),
    outcome: BudgetAssessmentOutcome | str,
    reasons: Iterable[str],
    usage: Mapping[str, Any] | None = None,
    headroom: Mapping[str, Any] | None = None,
    window_state: str = "ACTIVE",
    request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """INVARIANT: Build the stable Authority snapshot used as a stale precondition.

    Wall-clock observation time is deliberately excluded.  The persisted
    deadline and its boundary state are authoritative; including a continuously
    changing timestamp would make every otherwise-identical assessment stale.
    """
    try:
        normalized_outcome = BudgetAssessmentOutcome(str(outcome)).value
    except ValueError as exc:
        raise KernelError(
            "BUDGET_ASSESSMENT_OUTCOME_INVALID",
            "budget assessment outcome is invalid",
        ) from exc
    normalized_scope = _canonical_value(dict(scope))
    normalized_reservations = sorted(
        (_canonical_value(dict(item)) for item in reservations),
        key=lambda item: str(item.get("reservation_id") or ""),
    )
    normalized_links = sorted(
        (_canonical_value(dict(item)) for item in evidence_links),
        key=lambda item: str(item.get("budget_evidence_link_id") or ""),
    )
    normalized_attributions = sorted(
        (_canonical_value(dict(item)) for item in legacy_attributions),
        key=lambda item: str(item.get("legacy_budget_attribution_id") or ""),
    )
    body = {
        "contract_version": "provider-budget-authority-snapshot.v2",
        "scope": normalized_scope,
        "reservations": normalized_reservations,
        "evidence_links": normalized_links,
        "legacy_attributions": normalized_attributions,
        "request": _canonical_value(dict(request or {})),
        "usage": _canonical_value(dict(usage or {})),
        "headroom": _canonical_value(dict(headroom or {})),
        "window_state": str(window_state).strip().upper(),
        "outcome": normalized_outcome,
        "reasons": sorted({str(reason) for reason in reasons if str(reason)}),
    }
    return {**body, "snapshot_hash": _canonical_hash(body)}


def next_provider_budget_allowance(policy: Mapping[str, Any]) -> dict[str, Any]:

    canonical = canonical_budget_policy(policy)["policy_snapshot"]
    if str(canonical["execution_mode"]) == "PROJECTION_ONLY":
        return {
            "execution_mode": "PROJECTION_ONLY",
            "requested_calls": 0,
            "requested_tokens": 0,
            "requested_amount": "0",
        }
    if str(canonical.get("accounting_basis") or "PRICED") == "ACCOUNT_ENTITLEMENT":
        return {
            "execution_mode": "PROVIDER_ALLOWED",
            "accounting_basis": "ACCOUNT_ENTITLEMENT",
            "requested_calls": 1,
            "requested_tokens": int(
                canonical.get("per_call_token_limit", canonical["token_limit"])
            ),
            "requested_amount": None,
            "cost_status": "UNKNOWN",
        }
    return {
        "execution_mode": "PROVIDER_ALLOWED",
        "requested_calls": 1,
        "requested_tokens": int(
            canonical.get("per_call_token_limit", canonical["token_limit"])
        ),
        "requested_amount": _decimal_text(
            _amount(
                str(
                    canonical.get(
                        "per_call_cost_limit_usd", canonical["cost_limit_usd"]
                    )
                )
            )
        ),
    }


def resolve_provider_token_reservation_contract(
    database_url: str,
    *,
    operation_id: str,
    project_id: str,
    currency: str,
    frozen_request_token_ceiling: int,
    accounting_basis: str = "PRICED",
    cost_authorization_ref: str = "",
) -> dict[str, Any]:
    """INVARIANT: Freeze one positive token reservation and Provider output ceiling.

    Opening work uses the exact same immutable per-call policy allowance used by
    RecoveryAssessment.  Non-Opening work reserves a conservative input plus
    output ceiling from its already-frozen request contract.
    """
    normalized_basis = accounting_basis.strip().upper()
    if normalized_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}:
        raise KernelError(
            "PROVIDER_COST_ACCOUNTING_INVALID",
            "Provider token reservation accounting basis is invalid",
        )
    if normalized_basis == "ACCOUNT_ENTITLEMENT" and not cost_authorization_ref:
        raise KernelError(
            "PROVIDER_COST_AUTHORIZATION_REQUIRED",
            "account-entitlement Provider execution requires authorization",
        )
    if frozen_request_token_ceiling <= 0:
        raise KernelError(
            "PROVIDER_TOKEN_CEILING_REQUIRED",
            "Provider execution requires a positive frozen token ceiling",
        )
    with AuthorityUnitOfWork(database_url) as uow:
        binding = resolve_book_opening_budget_scope_in_uow(
            uow,
            operation_id=operation_id,
            project_id=project_id,
            currency=currency,
        )
        if binding is not None:
            allowance = next_provider_budget_allowance(binding["policy_snapshot"])
            policy = canonical_budget_policy(binding["policy_snapshot"])[
                "policy_snapshot"
            ]
            policy_basis = str(policy.get("accounting_basis") or "PRICED")
            if policy_basis != normalized_basis:
                raise KernelError(
                    "BUDGET_SCOPE_CONFLICT",
                    "Opening BudgetScope accounting basis differs from Provider runtime",
                )
            policy_authorization_ref = str(policy.get("authorization_ref") or "")
            if (
                normalized_basis == "ACCOUNT_ENTITLEMENT"
                and policy_authorization_ref != cost_authorization_ref
            ):
                raise KernelError(
                    "BUDGET_SCOPE_CONFLICT",
                    "Opening BudgetScope authorization differs from Provider runtime",
                )
            estimated_tokens = int(allowance["requested_tokens"])
            if (
                allowance["execution_mode"] != "PROVIDER_ALLOWED"
                or int(allowance["requested_calls"]) != 1
                or estimated_tokens <= 0
            ):
                raise KernelError(
                    "BUDGET_SCOPE_PROVIDER_EXECUTION_FORBIDDEN",
                    "Opening BudgetScope does not authorize a Provider call",
                )
            source = "BOOK_OPENING_IMMUTABLE_PER_CALL_POLICY"
            budget_scope_id = str(binding["budget_scope_id"])
            budget_scope_revision = int(binding["revision"])
            allowance_amount = allowance["requested_amount"]
            estimated_cost_amount: str | None = (
                str(allowance_amount) if allowance_amount is not None else None
            )
        else:
            estimated_tokens = frozen_request_token_ceiling * 2
            source = "FROZEN_REQUEST_INPUT_PLUS_OUTPUT_CEILING"
            budget_scope_id = ""
            budget_scope_revision = None
            estimated_cost_amount = None
        if estimated_tokens <= 0 or estimated_tokens > 1_000_000_000:
            raise KernelError(
                "PROVIDER_TOKEN_RESERVATION_INVALID",
                "Provider token reservation is outside supported bounds",
            )
        remaining_output_tokens = estimated_tokens - frozen_request_token_ceiling
        if remaining_output_tokens <= 0:
            raise KernelError(
                "PROVIDER_TOKEN_RESERVATION_INSUFFICIENT",
                "Provider token reservation must cover frozen input and positive output",
            )
        max_output_tokens = min(
            frozen_request_token_ceiling,
            remaining_output_tokens,
        )
        contract = {
            "contract_version": "provider-token-reservation.v1",
            "estimated_total_tokens": estimated_tokens,
            "input_token_ceiling": frozen_request_token_ceiling,
            "max_output_tokens": max_output_tokens,
            "estimated_cost_amount": estimated_cost_amount,
            "accounting_basis": normalized_basis,
            "cost_status": (
                "UNKNOWN" if normalized_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
            ),
            "cost_authorization_ref": cost_authorization_ref,
            "source": source,
            "budget_scope_id": budget_scope_id,
            "budget_scope_revision": budget_scope_revision,
        }
        uow.commit()
        return {**contract, "contract_hash": _canonical_hash(contract)}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise KernelError(
            "BUDGET_AMOUNT_INVALID", "budget amount must be a finite decimal"
        )
    normalized = format(value.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _has_budget_cost_observability_schema(uow: AuthorityUnitOfWork) -> bool:
    uow.cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema=current_schema()
          AND (table_name,column_name) IN (
              ('authority_budget_reservation','accounting_basis'),
              ('authority_budget_reservation','estimated_cost_status'),
              ('authority_budget_reservation','settled_cost_status'),
              ('authority_operation_cost_evidence','accounting_basis'),
              ('authority_operation_cost_evidence','cost_status')
          )
        """
    )
    return int(uow.cursor.fetchone()[0]) == 5


def deterministic_budget_scope_id(
    *, project_id: str, owner_kind: str, owner_id: str
) -> str:
    identity = "\x1f".join(
        (project_id.strip(), owner_kind.strip().upper(), owner_id.strip())
    )
    return "budget-scope:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def deterministic_budget_operation_binding_id(
    *,
    operation_id: str,
    opening_execution_id: str,
    opening_execution_generation: int,
    runtime_attempt_id: str,
    runtime_fencing_token: int,
) -> str:
    identity = "\x1f".join(
        (
            operation_id.strip(),
            opening_execution_id.strip(),
            str(opening_execution_generation),
            runtime_attempt_id.strip(),
            str(runtime_fencing_token),
        )
    )
    return (
        "budget-operation-binding:"
        + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    )


def deterministic_budget_effect_binding_id(
    *, external_effect_id: str, reservation_id: str
) -> str:
    identity = "\x1f".join((external_effect_id.strip(), reservation_id.strip()))
    return (
        "budget-effect-binding:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    )


def canonical_budget_reservation_snapshot(
    reservation: Mapping[str, Any],
) -> dict[str, Any]:

    fields = (
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
    accounting_basis = str(reservation.get("accounting_basis") or "PRICED").upper()
    body = {
        "contract_version": "provider-budget-reservation-snapshot.v1",
        **{field_name: reservation.get(field_name) for field_name in fields},
    }
    if accounting_basis == "ACCOUNT_ENTITLEMENT":
        body.update(
            {
                "contract_version": "provider-budget-reservation-snapshot.v2",
                "accounting_basis": accounting_basis,
                "estimated_cost_status": str(
                    reservation.get("estimated_cost_status") or "UNKNOWN"
                ),
                "settled_cost_status": str(
                    reservation.get("settled_cost_status") or "PENDING"
                ),
            }
        )
    normalized = _canonical_value(body)
    return {**normalized, "snapshot_hash": _canonical_hash(normalized)}


@dataclass(frozen=True, slots=True)
class BudgetScopeRequest:
    project_id: str
    owner_kind: str
    owner_id: str
    stable_idempotency_key: str
    currency: str
    policy_contract_version: str
    policy_snapshot: Mapping[str, Any]
    started_at: datetime
    deadline_at: datetime
    created_by_operation_id: str
    budget_scope_id: str = ""
    budget_timezone: str = "UTC"
    policy_hash: str = field(init=False)

    def __post_init__(self) -> None:
        required = (
            self.project_id,
            self.owner_id,
            self.stable_idempotency_key,
            self.currency,
            self.policy_contract_version,
            self.created_by_operation_id,
            self.budget_timezone,
        )
        if any(not str(item).strip() for item in required):
            raise KernelError(
                "BUDGET_SCOPE_INVALID", "budget scope identity is incomplete"
            )
        owner_kind = self.owner_kind.strip().upper()
        if owner_kind != "BOOK_OPENING":
            raise KernelError(
                "BUDGET_SCOPE_OWNER_INVALID",
                "budget scope owner_kind must be BOOK_OPENING",
            )
        if (
            self.started_at.tzinfo is None
            or self.started_at.utcoffset() is None
            or self.deadline_at.tzinfo is None
            or self.deadline_at.utcoffset() is None
        ):
            raise KernelError(
                "BUDGET_SCOPE_TIME_INVALID",
                "budget scope timestamps must be timezone-aware",
            )
        if self.deadline_at <= self.started_at:
            raise KernelError(
                "BUDGET_SCOPE_DEADLINE_INVALID",
                "budget scope deadline must be after started_at",
            )
        policy = canonical_budget_policy(self.policy_snapshot)
        currency = self.currency.strip().upper()
        budget_scope_id = self.budget_scope_id.strip() or deterministic_budget_scope_id(
            project_id=self.project_id,
            owner_kind=owner_kind,
            owner_id=self.owner_id,
        )
        object.__setattr__(self, "owner_kind", owner_kind)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "budget_scope_id", budget_scope_id)
        object.__setattr__(self, "policy_snapshot", policy["policy_snapshot"])
        object.__setattr__(self, "policy_hash", policy["policy_hash"])


def deterministic_budget_evidence_link_id(
    *,
    budget_scope_id: str,
    reservation_id: str,
    evidence_kind: str,
    evidence_id: str,
    evidence_version: int,
) -> str:
    identity = "\x1f".join(
        (
            budget_scope_id.strip(),
            reservation_id.strip(),
            evidence_kind.strip().upper(),
            evidence_id.strip(),
            str(evidence_version),
        )
    )
    return (
        "budget-evidence-link:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    )


@dataclass(frozen=True, slots=True)
class BudgetEvidenceLinkRequest:
    budget_scope_id: str
    budget_scope_revision: int
    project_id: str
    reservation_id: str
    evidence_kind: str
    evidence_id: str
    evidence_version: int
    evidence_hash: str
    stable_idempotency_key: str
    budget_evidence_link_id: str = ""

    def __post_init__(self) -> None:
        required = (
            self.budget_scope_id,
            self.project_id,
            self.reservation_id,
            self.evidence_id,
            self.evidence_hash,
            self.stable_idempotency_key,
        )
        if any(not str(value).strip() for value in required):
            raise KernelError(
                "BUDGET_EVIDENCE_LINK_INVALID",
                "budget evidence link identity is incomplete",
            )
        evidence_kind = self.evidence_kind.strip().upper()
        if evidence_kind not in {"OPERATION_COST", "COST_LEDGER", "MODEL_CALL"}:
            raise KernelError(
                "BUDGET_EVIDENCE_KIND_INVALID",
                "budget evidence link evidence_kind is invalid",
            )
        if self.budget_scope_revision <= 0 or self.evidence_version < 0:
            raise KernelError(
                "BUDGET_EVIDENCE_LINK_INVALID",
                "budget evidence link versions cannot be negative",
            )
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.evidence_hash) is None:
            raise KernelError(
                "BUDGET_EVIDENCE_LINK_INVALID",
                "budget evidence link hash is invalid",
            )
        link_id = self.budget_evidence_link_id.strip() or (
            deterministic_budget_evidence_link_id(
                budget_scope_id=self.budget_scope_id,
                reservation_id=self.reservation_id,
                evidence_kind=evidence_kind,
                evidence_id=self.evidence_id,
                evidence_version=self.evidence_version,
            )
        )
        object.__setattr__(self, "evidence_kind", evidence_kind)
        object.__setattr__(self, "budget_evidence_link_id", link_id)


def acquire_budget_locks_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    currencies: Iterable[str],
    budget_scope_ids: Iterable[str] = (),
) -> None:
    """INVARIANT: Acquire the Command Kernel's canonical budget advisory lock prefix.

    Every path takes sorted currency locks before sorted scope locks.  Callers
    may then lock the BudgetScope owner row, followed by Operation/Effect and
    Reservation rows.  This order prevents cap-query insert phantoms without
    introducing a recovery-versus-reservation lock inversion.
    """
    currency_keys = sorted(
        {
            str(currency).strip().upper()
            for currency in currencies
            if str(currency).strip()
        }
    )
    scope_keys = sorted(
        {
            str(scope_id).strip()
            for scope_id in budget_scope_ids
            if str(scope_id).strip()
        }
    )
    for currency in currency_keys:
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"authority-provider-budget:{currency}"],
        )
    for budget_scope_id in scope_keys:
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"authority-provider-budget-scope:{budget_scope_id}"],
        )


def create_or_get_budget_scope(
    database_url: str, request: BudgetScopeRequest
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        result = create_or_get_budget_scope_in_uow(uow, request)
        uow.commit()
        return result


def create_or_get_budget_scope_in_uow(
    uow: AuthorityUnitOfWork, request: BudgetScopeRequest
) -> dict[str, Any]:

    acquire_budget_locks_in_uow(
        uow,
        currencies=(request.currency,),
        budget_scope_ids=(request.budget_scope_id,),
    )
    uow.cursor.execute(
        """
        SELECT project_id
        FROM authority_book_opening_run
        WHERE opening_run_id=%s
        """,
        [request.owner_id],
    )
    owner = uow.cursor.fetchone()
    if owner is None or str(owner[0]) != request.project_id:
        raise KernelError(
            "BUDGET_SCOPE_OWNER_CONFLICT",
            "budget scope owner is missing or outside project scope",
        )
    uow.cursor.execute(
        """
        SELECT project_id
        FROM authority_operation
        WHERE operation_id=%s
        FOR KEY SHARE
        """,
        [request.created_by_operation_id],
    )
    operation = uow.cursor.fetchone()
    if operation is None or str(operation[0]) != request.project_id:
        raise KernelError(
            "BUDGET_SCOPE_OPERATION_CONFLICT",
            "budget scope creation Operation is outside project scope",
        )
    uow.cursor.execute(
        """
        INSERT INTO authority_provider_budget_scope(
            budget_scope_id,project_id,owner_kind,owner_id,currency,
            policy_contract_version,policy_snapshot,policy_hash,
            budget_timezone,started_at,deadline_at,revision,
            created_by_operation_id,stable_idempotency_key
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)
        ON CONFLICT DO NOTHING
        RETURNING budget_scope_id
        """,
        [
            request.budget_scope_id,
            request.project_id,
            request.owner_kind,
            request.owner_id,
            request.currency,
            request.policy_contract_version,
            Jsonb(dict(request.policy_snapshot)),
            request.policy_hash,
            request.budget_timezone,
            request.started_at,
            request.deadline_at,
            request.created_by_operation_id,
            request.stable_idempotency_key,
        ],
    )
    created = uow.cursor.fetchone() is not None
    if created:
        _record_budget_scope(
            uow,
            request,
            topic="authority.provider_budget_scope.created",
            payload={
                "policy_contract_version": request.policy_contract_version,
                "policy_hash": request.policy_hash,
            },
        )
    else:
        uow.cursor.execute(
            """
            SELECT budget_scope_id
            FROM authority_provider_budget_scope
            WHERE project_id=%s AND (
                budget_scope_id=%s
                OR stable_idempotency_key=%s
                OR (owner_kind=%s AND owner_id=%s)
            )
            ORDER BY CASE WHEN budget_scope_id=%s THEN 0 ELSE 1 END
            LIMIT 1
            FOR UPDATE
            """,
            [
                request.project_id,
                request.budget_scope_id,
                request.stable_idempotency_key,
                request.owner_kind,
                request.owner_id,
                request.budget_scope_id,
            ],
        )
        existing_id = uow.cursor.fetchone()
        if existing_id is None:
            raise KernelError(
                "BUDGET_SCOPE_IDEMPOTENCY_CONFLICT",
                "budget scope conflict cannot be resolved to Authority evidence",
            )
        existing = _budget_scope(
            uow,
            budget_scope_id=str(existing_id[0]),
            project_id=request.project_id,
            lock=False,
        )
        expected = {
            "budget_scope_id": request.budget_scope_id,
            "project_id": request.project_id,
            "owner_kind": request.owner_kind,
            "owner_id": request.owner_id,
            "currency": request.currency,
            "policy_contract_version": request.policy_contract_version,
            "policy_snapshot": dict(request.policy_snapshot),
            "policy_hash": request.policy_hash,
            "budget_timezone": request.budget_timezone,
            "started_at": request.started_at,
            "deadline_at": request.deadline_at,
            "created_by_operation_id": request.created_by_operation_id,
            "stable_idempotency_key": request.stable_idempotency_key,
        }
        if any(existing[key] != value for key, value in expected.items()):
            raise KernelError(
                "BUDGET_SCOPE_IDEMPOTENCY_CONFLICT",
                "budget scope identity belongs to another policy contract",
            )
    scope = _budget_scope(
        uow,
        budget_scope_id=request.budget_scope_id,
        project_id=request.project_id,
        lock=True,
    )
    return {**scope, "replayed": not created}


def lock_budget_scope_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    budget_scope_id: str,
    project_id: str,
) -> dict[str, Any]:
    """INVARIANT: Lock one scope in canonical currency -> scope -> owner-row order."""
    uow.cursor.execute(
        """
        SELECT currency
        FROM authority_provider_budget_scope
        WHERE budget_scope_id=%s AND project_id=%s
        """,
        [budget_scope_id, project_id],
    )
    identity = uow.cursor.fetchone()
    if identity is None:
        raise KernelError("BUDGET_SCOPE_NOT_FOUND", "budget scope is missing")
    currency = str(identity[0]).upper()
    acquire_budget_locks_in_uow(
        uow,
        currencies=(currency,),
        budget_scope_ids=(budget_scope_id,),
    )
    scope = _budget_scope(
        uow,
        budget_scope_id=budget_scope_id,
        project_id=project_id,
        lock=True,
    )
    if str(scope["currency"]).upper() != currency:
        raise KernelError(
            "BUDGET_SCOPE_REASSESS_REQUIRED",
            "budget scope lock identity changed while acquiring Authority locks",
        )
    return scope


def resolve_book_opening_budget_scope_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
    currency: str,
) -> dict[str, Any] | None:
    """INVARIANT: Resolve an exact persisted or frozen Opening execution binding.

    Book identity alone is never authorization.  A direct frozen execution
    fence or an immutable causation lineage to a persisted binding selects the
    Opening owner.  If a project has live Opening work but neither identity is
    present, Provider work fails closed.
    """
    lineage = _operation_opening_lineage_in_uow(
        uow, operation_id=operation_id, project_id=project_id
    )
    candidates = list(lineage["candidates"])
    if not candidates:
        return None
    opening_ids = {str(item.get("opening_run_id") or "") for item in candidates}
    opening_ids.discard("")
    if len(opening_ids) != 1:
        raise KernelError(
            "BOOK_OPENING_BUDGET_OWNER_AMBIGUOUS",
            "Operation causation lineage reaches multiple Opening owners",
        )
    opening_run_id = next(iter(opening_ids), "")
    if not opening_run_id:
        raise KernelError(
            "BOOK_OPENING_EXACT_BUDGET_BINDING_REQUIRED",
            "Opening execution binding has no owner identity",
        )
    # INVARIANT: Match BookOpening recovery's canonical owner-first lock order.  Taking
    # Budget locks before the referenced Opening/runtime rows would allow the
    # binding FK to deadlock with recovery (Budget -> Opening versus
    # Opening -> Budget).
    uow.cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        [f"book-opening:{opening_run_id}"],
    )
    uow.cursor.execute(
        """
        SELECT opening_run_id,book_id,budget_contract_state,budget_scope_id,
               budget_scope_revision,current_execution_id,current_execution_generation
        FROM authority_book_opening_run
        WHERE opening_run_id=%s AND project_id=%s AND lifecycle='RUNNING'
        FOR UPDATE
        """,
        [opening_run_id, project_id],
    )
    opening = uow.cursor.fetchone()
    if opening is None:
        raise KernelError(
            "BOOK_OPENING_EXECUTION_NOT_LIVE",
            "exact Opening owner is not RUNNING",
        )
    if str(opening[2]) != "BOUND" or opening[3] is None or opening[4] is None:
        raise KernelError(
            "BOOK_OPENING_BUDGET_SCOPE_REQUIRED",
            "RUNNING Book Opening has no authoritative BudgetScope binding",
        )
    book_id = str(opening[1])
    budget_scope_id = str(opening[3])
    scope_revision = int(opening[4])
    live_before = _live_book_opening_budget_binding(
        uow,
        opening_run_id=opening_run_id,
        project_id=project_id,
        book_id=book_id,
        budget_scope_id=budget_scope_id,
        budget_scope_revision=scope_revision,
        opening_execution_id=str(opening[5] or ""),
        opening_execution_generation=int(opening[6] or 0),
        lock=True,
    )
    if live_before is None:
        raise KernelError(
            "BOOK_OPENING_EXECUTION_NOT_LIVE",
            "RUNNING Book Opening has no exact live Job/Attempt/Lease chain",
        )
    scope = lock_budget_scope_in_uow(
        uow,
        budget_scope_id=budget_scope_id,
        project_id=project_id,
    )
    if (
        int(scope["revision"]) != scope_revision
        or str(scope["owner_kind"]) != "BOOK_OPENING"
        or str(scope["owner_id"]) != opening_run_id
        or str(scope["currency"]).upper() != currency.strip().upper()
    ):
        raise KernelError(
            "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
            "Book Opening budget binding differs from Budget Authority",
        )
    live_after = _live_book_opening_budget_binding(
        uow,
        opening_run_id=opening_run_id,
        project_id=project_id,
        book_id=book_id,
        budget_scope_id=budget_scope_id,
        budget_scope_revision=scope_revision,
        opening_execution_id=str(opening[5] or ""),
        opening_execution_generation=int(opening[6] or 0),
        lock=True,
    )
    if live_after is None or live_after != live_before:
        raise KernelError(
            "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
            "Book Opening execution changed while acquiring budget locks",
        )
    current_candidates = [
        item
        for item in candidates
        if str(item.get("opening_execution_id") or "")
        == str(live_after["opening_execution_id"])
        and int(item.get("opening_execution_generation") or 0)
        == int(live_after["opening_execution_generation"])
    ]
    source = current_candidates[0] if current_candidates else candidates[0]
    source_execution_id = str(source.get("opening_execution_id") or "")
    source_generation = int(source.get("opening_execution_generation") or 0)
    if not source_execution_id or source_generation <= 0:
        raise KernelError(
            "BOOK_OPENING_EXACT_BUDGET_BINDING_REQUIRED",
            "Opening lineage does not contain an exact execution generation",
        )
    if not current_candidates and not _recovery_authorizes_successor_binding_in_uow(
        uow,
        opening_run_id=opening_run_id,
        source_execution_id=source_execution_id,
        source_generation=source_generation,
        successor_execution_id=str(live_after["opening_execution_id"]),
        successor_generation=int(live_after["opening_execution_generation"]),
        budget_scope_id=budget_scope_id,
        budget_scope_revision=scope_revision,
    ):
        raise KernelError(
            "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
            "historical Opening fence has no authoritative recovery lineage",
        )
    if current_candidates:
        for key in (
            "runtime_job_id",
            "runtime_attempt_id",
            "runtime_lease_id",
            "runtime_worker_id",
            "runtime_fencing_token",
        ):
            value = source.get(key)
            if value not in {None, ""} and str(value) != str(live_after[key]):
                raise KernelError(
                    "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
                    "frozen Operation execution fence is no longer current",
                )
    binding_source = (
        "EXPLICIT_OPENING_CONTEXT"
        if str(source.get("candidate_source") or "").startswith("EXPLICIT")
        else "CAUSATION_LINEAGE"
    )
    operation_budget_binding_id = deterministic_budget_operation_binding_id(
        operation_id=operation_id,
        opening_execution_id=str(live_after["opening_execution_id"]),
        opening_execution_generation=int(live_after["opening_execution_generation"]),
        runtime_attempt_id=str(live_after["runtime_attempt_id"]),
        runtime_fencing_token=int(live_after["runtime_fencing_token"]),
    )
    uow.cursor.execute(
        """
        INSERT INTO authority_book_opening_budget_operation_binding(
            operation_budget_binding_id,operation_id,opening_run_id,project_id,budget_scope_id,
            budget_scope_revision,opening_execution_id,
            opening_execution_generation,runtime_job_id,runtime_attempt_id,
            runtime_lease_id,runtime_worker_id,runtime_fencing_token,
            binding_source,bound_by_operation_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
        """,
        [
            operation_budget_binding_id,
            operation_id,
            opening_run_id,
            project_id,
            budget_scope_id,
            scope_revision,
            live_after["opening_execution_id"],
            live_after["opening_execution_generation"],
            live_after["runtime_job_id"],
            live_after["runtime_attempt_id"],
            live_after["runtime_lease_id"],
            live_after["runtime_worker_id"],
            live_after["runtime_fencing_token"],
            binding_source,
            operation_id,
        ],
    )
    uow.cursor.execute(
        """
        SELECT operation_budget_binding_id,opening_run_id,budget_scope_id,budget_scope_revision,
               opening_execution_id,opening_execution_generation,
               runtime_job_id,runtime_attempt_id,runtime_lease_id,
               runtime_worker_id,runtime_fencing_token
        FROM authority_book_opening_budget_operation_binding
        WHERE operation_id=%s AND opening_execution_id=%s
          AND opening_execution_generation=%s
          AND runtime_attempt_id=%s AND runtime_fencing_token=%s
        """,
        [
            operation_id,
            live_after["opening_execution_id"],
            live_after["opening_execution_generation"],
            live_after["runtime_attempt_id"],
            live_after["runtime_fencing_token"],
        ],
    )
    durable = uow.cursor.fetchone()
    expected_durable = (
        operation_budget_binding_id,
        opening_run_id,
        budget_scope_id,
        scope_revision,
        live_after["opening_execution_id"],
        live_after["opening_execution_generation"],
        live_after["runtime_job_id"],
        live_after["runtime_attempt_id"],
        live_after["runtime_lease_id"],
        live_after["runtime_worker_id"],
        live_after["runtime_fencing_token"],
    )
    if durable is None or tuple(durable) != expected_durable:
        raise KernelError(
            "BOOK_OPENING_BUDGET_BINDING_CONFLICT",
            "Operation is already bound to another Opening execution",
        )
    return {
        **scope,
        **live_after,
        "book_id": book_id,
        "operation_budget_binding_id": operation_budget_binding_id,
    }


def _operation_opening_lineage_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    operation_id: str,
    project_id: str,
) -> dict[str, Any]:

    uow.cursor.execute(
        """
        WITH RECURSIVE ancestry AS (
            SELECT operation_id,project_id,command_payload,
                   causation_operation_id,parent_operation_id,
                   ARRAY[operation_id]::TEXT[] AS path,0 AS depth
            FROM authority_operation WHERE operation_id=%s
            UNION ALL
            SELECT parent.operation_id,parent.project_id,parent.command_payload,
                   parent.causation_operation_id,parent.parent_operation_id,
                   ancestry.path || parent.operation_id,ancestry.depth+1
            FROM ancestry
            CROSS JOIN LATERAL (
                VALUES (ancestry.causation_operation_id),
                       (ancestry.parent_operation_id)
            ) AS edge(operation_id)
            JOIN authority_operation AS parent
              ON parent.operation_id=edge.operation_id
            WHERE ancestry.depth<32
              AND edge.operation_id IS NOT NULL
              AND NOT parent.operation_id=ANY(ancestry.path)
        )
        SELECT operation_id,project_id,command_payload,depth
        FROM ancestry
        ORDER BY depth,operation_id
        """,
        [operation_id],
    )
    operations = [tuple(row) for row in uow.cursor.fetchall()]
    if not operations or str(operations[0][1]) != project_id:
        raise KernelError(
            "BUDGET_SCOPE_CONFLICT",
            "budget Operation is missing or outside project scope",
        )
    if any(str(row[1]) != project_id for row in operations):
        raise KernelError(
            "BOOK_OPENING_BUDGET_OWNER_AMBIGUOUS",
            "Operation causation lineage crosses project scope",
        )
    operation_ids = [str(row[0]) for row in operations]
    uow.cursor.execute(
        """
        SELECT operation_budget_binding_id,operation_id,opening_run_id,
               budget_scope_id,budget_scope_revision,opening_execution_id,
               opening_execution_generation,runtime_job_id,runtime_attempt_id,
               runtime_lease_id,runtime_worker_id,runtime_fencing_token
        FROM authority_book_opening_budget_operation_binding
        WHERE operation_id=ANY(%s) AND project_id=%s
        ORDER BY created_at DESC,operation_budget_binding_id
        """,
        [operation_ids, project_id],
    )
    persisted_columns = (
        "operation_budget_binding_id",
        "operation_id",
        "opening_run_id",
        "budget_scope_id",
        "budget_scope_revision",
        "opening_execution_id",
        "opening_execution_generation",
        "runtime_job_id",
        "runtime_attempt_id",
        "runtime_lease_id",
        "runtime_worker_id",
        "runtime_fencing_token",
    )
    candidates: list[dict[str, Any]] = []
    depth_by_operation = {str(row[0]): int(row[3]) for row in operations}
    for row in uow.cursor.fetchall():
        candidate = dict(zip(persisted_columns, row, strict=True))
        candidate["candidate_source"] = "PERSISTED"
        candidate["depth"] = depth_by_operation[str(candidate["operation_id"])]
        candidates.append(candidate)
    for lineage_operation_id, _, raw_payload, depth in operations:
        command_payload = dict(raw_payload or {})
        nested_payload = command_payload.get("payload")
        nested = dict(nested_payload) if isinstance(nested_payload, Mapping) else {}
        frozen = nested.get("opening_execution_binding") or command_payload.get(
            "opening_execution_binding"
        )
        if isinstance(frozen, Mapping) and frozen:
            candidates.append(
                {
                    **dict(frozen),
                    "operation_id": str(lineage_operation_id),
                    "candidate_source": "EXPLICIT",
                    "depth": int(depth),
                }
            )
    candidates.sort(
        key=lambda item: (
            int(item.get("depth") or 0),
            0 if item.get("candidate_source") == "PERSISTED" else 1,
            -int(item.get("opening_execution_generation") or 0),
        )
    )
    return {"operation_ids": operation_ids, "candidates": candidates}


def _recovery_authorizes_successor_binding_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    opening_run_id: str,
    source_execution_id: str,
    source_generation: int,
    successor_execution_id: str,
    successor_generation: int,
    budget_scope_id: str,
    budget_scope_revision: int,
) -> bool:

    current_id = successor_execution_id
    current_generation = successor_generation
    seen: set[tuple[str, int]] = set()
    while (current_id, current_generation) != (
        source_execution_id,
        source_generation,
    ):
        identity = (current_id, current_generation)
        if identity in seen or current_generation <= source_generation:
            return False
        seen.add(identity)
        uow.cursor.execute(
            """
            SELECT execution.predecessor_execution_id,
                   execution.predecessor_generation,execution.recovery_intent_id
            FROM authority_book_opening_execution AS execution
            WHERE execution.opening_run_id=%s
              AND execution.opening_execution_id=%s
              AND execution.generation=%s
            """,
            [opening_run_id, current_id, current_generation],
        )
        predecessor = uow.cursor.fetchone()
        if predecessor is None or predecessor[0] is None or predecessor[1] is None:
            return False
        predecessor_id = str(predecessor[0])
        predecessor_generation = int(predecessor[1])
        recovery_intent_id = str(predecessor[2] or "")
        uow.cursor.execute(
            """
            SELECT 1
            FROM authority_book_opening_recovery_receipt AS receipt
            JOIN authority_book_opening_recovery_intent AS intent
              ON intent.recovery_intent_id=receipt.recovery_intent_id
             AND intent.opening_run_id=receipt.opening_run_id
            JOIN authority_book_opening_recovery_assessment AS assessment
              ON assessment.recovery_assessment_id=
                    receipt.recovery_assessment_id
             AND assessment.opening_run_id=receipt.opening_run_id
            WHERE receipt.opening_run_id=%s
              AND receipt.receipt_kind='RECOVERY_ADMISSION'
              AND receipt.recovery_intent_id=%s
              AND receipt.predecessor_execution_id=%s
              AND receipt.predecessor_generation=%s
              AND receipt.successor_execution_id=%s
              AND receipt.successor_generation=%s
              AND intent.predecessor_execution_id=%s
              AND intent.predecessor_generation=%s
              AND intent.successor_generation=%s
              AND assessment.assessment_contract_version=
                    'book-opening-recovery-assessment.v2'
              AND assessment.budget_scope_id=%s
              AND assessment.budget_scope_revision=%s
            """,
            [
                opening_run_id,
                recovery_intent_id,
                predecessor_id,
                predecessor_generation,
                current_id,
                current_generation,
                predecessor_id,
                predecessor_generation,
                current_generation,
                budget_scope_id,
                budget_scope_revision,
            ],
        )
        if not recovery_intent_id or uow.cursor.fetchone() is None:
            return False
        current_id = predecessor_id
        current_generation = predecessor_generation
    return True


def revalidate_book_opening_budget_scope_in_uow(
    uow: AuthorityUnitOfWork, binding: Mapping[str, Any]
) -> None:

    if not binding.get("opening_run_id"):
        return
    current = _live_book_opening_budget_binding(
        uow,
        opening_run_id=str(binding["opening_run_id"]),
        project_id=str(binding["project_id"]),
        book_id=str(binding["book_id"]),
        budget_scope_id=str(binding["budget_scope_id"]),
        budget_scope_revision=int(binding["revision"]),
        opening_execution_id=str(binding["opening_execution_id"]),
        opening_execution_generation=int(binding["opening_execution_generation"]),
    )
    expected = {
        key: binding[key]
        for key in (
            "opening_run_id",
            "opening_execution_id",
            "opening_execution_generation",
            "runtime_job_id",
            "runtime_attempt_id",
            "runtime_lease_id",
            "runtime_worker_id",
            "runtime_fencing_token",
        )
    }
    if current is None or current != expected:
        raise KernelError(
            "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
            "Book Opening execution changed before budget reservation",
        )


def assert_provider_execution_authorized(
    database_url: str,
    *,
    operation_id: str,
    external_effect_id: str,
    project_id: str,
    budget_reservation_id: str = "",
) -> dict[str, Any]:
    """SECURITY: Hard-stop immediately before a Provider request can leave the process."""
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """
            SELECT effect.opening_run_id,effect.budget_scope_id,
                   effect.budget_scope_revision,effect.reservation_id,
                   effect.reservation_version,scope.currency,
                   effect.operation_budget_binding_id
            FROM authority_book_opening_budget_effect_binding AS effect
            JOIN authority_provider_budget_scope AS scope
              ON scope.budget_scope_id=effect.budget_scope_id
             AND scope.revision=effect.budget_scope_revision
            WHERE effect.external_effect_id=%s AND effect.operation_id=%s
              AND effect.reservation_id=%s
            """,
            [external_effect_id, operation_id, budget_reservation_id],
        )
        identity = uow.cursor.fetchone()
        if identity is None:
            uow.cursor.execute(
                """
                SELECT operation.project_id,effect.project_id
                FROM authority_operation AS operation
                JOIN authority_external_effect AS effect
                  ON effect.operation_id=operation.operation_id
                 AND effect.external_effect_id=%s
                WHERE operation.operation_id=%s
                """,
                [external_effect_id, operation_id],
            )
            effect_scope = uow.cursor.fetchone()
            if effect_scope is None or tuple(map(str, effect_scope)) != (
                project_id,
                project_id,
            ):
                raise KernelError(
                    "BUDGET_SCOPE_CONFLICT",
                    "Provider effect is missing or outside project scope",
                )
            lineage = _operation_opening_lineage_in_uow(
                uow, operation_id=operation_id, project_id=project_id
            )
            if not lineage["candidates"]:
                return {"book_opening_bound": False, "execution_authorized": True}
            raise KernelError(
                "BOOK_OPENING_BUDGET_EFFECT_BINDING_REQUIRED",
                "Opening-lineage Provider effect has no exact reservation binding",
            )
        (
            opening_run_id,
            budget_scope_id,
            budget_scope_revision,
            reservation_id,
            reservation_version,
            currency,
            operation_budget_binding_id,
        ) = identity
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            [f"book-opening:{opening_run_id}"],
        )
        uow.cursor.execute(
            """
            SELECT opening.current_execution_id,
                   opening.current_execution_generation,
                   opening.budget_scope_id,opening.budget_scope_revision,
                   opening.lifecycle,opening.budget_contract_state,
                   execution.lifecycle,execution.runtime_job_id,
                   execution.current_attempt_id,execution.current_lease_id,
                   execution.current_worker_id,execution.current_fencing_token,
                   job.status,job.current_attempt_id,job.current_fencing_token,
                   job.claimed_by,attempt.status,attempt.lease_id,
                   lease.status,lease.lease_expires_at>clock_timestamp()
            FROM authority_book_opening_run AS opening
            JOIN authority_book_opening_execution AS execution
              ON execution.opening_run_id=opening.opening_run_id
             AND execution.opening_execution_id=opening.current_execution_id
             AND execution.generation=opening.current_execution_generation
            JOIN authority_runtime_job AS job
              ON job.runtime_job_id=execution.runtime_job_id
             AND (
                 (
                     opening.workflow_contract_version=
                         'book-opening-workflow-v1'
                     AND opening.execution_contract_version=
                         'book-opening-execution-v3'
                     AND job.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                     AND job.runtime_group='book_opening_workflow_v1'
                 ) OR (
                     opening.workflow_contract_version='legacy-monolithic-v2'
                     AND opening.execution_contract_version=
                         'book-opening-execution-v2'
                     AND job.job_kind='BOOK_OPENING_EXECUTE'
                     AND job.runtime_group='book_opening'
                 )
             )
            JOIN authority_runtime_job_attempt AS attempt
              ON attempt.runtime_job_id=job.runtime_job_id
             AND attempt.attempt_id=execution.current_attempt_id
            JOIN authority_runtime_job_lease AS lease
              ON lease.runtime_job_id=job.runtime_job_id
             AND lease.attempt_id=attempt.attempt_id
             AND lease.lease_id=execution.current_lease_id
            WHERE opening.opening_run_id=%s AND opening.project_id=%s
            FOR UPDATE OF opening,execution,job,attempt,lease
            """,
            [opening_run_id, project_id],
        )
        live = uow.cursor.fetchone()
        if live is None:
            raise KernelError(
                "BOOK_OPENING_PROVIDER_EXECUTION_NOT_LIVE",
                "Opening execution chain is missing before Provider send",
            )
        acquire_budget_locks_in_uow(
            uow,
            currencies=(str(currency),),
            budget_scope_ids=(str(budget_scope_id),),
        )
        scope = _budget_scope(
            uow,
            budget_scope_id=str(budget_scope_id),
            project_id=project_id,
            lock=True,
        )
        uow.cursor.execute(
            """
            SELECT operation.project_id,effect.project_id,effect.status,
                   reservation.status,reservation.version,
                   reservation.estimated_tokens,
                   NULLIF(effect.request_payload->>'max_output_tokens','')::BIGINT,
                   binding.opening_execution_id,
                   binding.opening_execution_generation,binding.runtime_job_id,
                   binding.runtime_attempt_id,binding.runtime_lease_id,
                   binding.runtime_worker_id,binding.runtime_fencing_token,
                   CASE
                     WHEN operation.definition_name=
                          'story_design.semantic_evaluate'
                     THEN authority_narrative_replacement_gate_is_open(
                         operation.operation_id,operation.project_id
                     )
                     ELSE TRUE
                   END
            FROM authority_operation AS operation
            JOIN authority_external_effect AS effect
              ON effect.operation_id=operation.operation_id
             AND effect.external_effect_id=%s
            JOIN authority_budget_reservation AS reservation
              ON reservation.operation_id=operation.operation_id
             AND reservation.external_effect_id=effect.external_effect_id
             AND reservation.reservation_id=%s
            JOIN authority_book_opening_budget_operation_binding AS binding
              ON binding.operation_budget_binding_id=%s
             AND binding.operation_id=operation.operation_id
             AND binding.opening_run_id=%s
             AND binding.budget_scope_id=%s
             AND binding.budget_scope_revision=%s
            WHERE operation.operation_id=%s
            FOR UPDATE OF operation,effect,reservation
            """,
            [
                external_effect_id,
                reservation_id,
                operation_budget_binding_id,
                opening_run_id,
                budget_scope_id,
                budget_scope_revision,
                operation_id,
            ],
        )
        execution = uow.cursor.fetchone()
        expected_fence = (
            str(live[0]),
            int(live[1]),
            str(live[7]),
            str(live[8]),
            str(live[9]),
            str(live[10]),
            int(live[11]),
        )
        actual_fence = tuple(execution[7:14]) if execution is not None else ()
        uow.cursor.execute(
            """
            SELECT clock_timestamp(),lease.lease_expires_at>clock_timestamp()
            FROM authority_runtime_job_lease AS lease
            WHERE lease.runtime_job_id=%s AND lease.attempt_id=%s
              AND lease.lease_id=%s AND lease.worker_id=%s
              AND lease.fencing_token=%s AND lease.status='HELD'
            """,
            expected_fence[2:],
        )
        final_clock = uow.cursor.fetchone()
        if (
            str(live[2]) != str(budget_scope_id)
            or int(live[3] or 0) != int(budget_scope_revision)
            or str(live[4]) != "RUNNING"
            or str(live[5]) != "BOUND"
            or str(live[6]) != "RUNNING"
            or str(live[12]) not in {"RUNNING", "CHECKPOINTED"}
            or str(live[13]) != str(live[8])
            or int(live[14] or 0) != int(live[11])
            or str(live[15]) != str(live[10])
            or str(live[16]) not in {"RUNNING", "CHECKPOINTED"}
            or str(live[17]) != str(live[9])
            or str(live[18]) != "HELD"
            or str(scope["budget_scope_id"]) != str(budget_scope_id)
            or int(scope["revision"]) != int(budget_scope_revision)
            or final_clock is None
            or not bool(final_clock[1])
            or scope["deadline_at"] <= final_clock[0]
            or execution is None
            or str(execution[0]) != project_id
            or str(execution[1]) != project_id
            or str(execution[2]) != "DISPATCHING"
            or str(execution[3]) != "RESERVED"
            or int(execution[4]) != int(reservation_version)
            or int(execution[5]) <= 0
            or execution[6] is None
            or int(execution[6]) <= 0
            or int(execution[6]) > int(execution[5])
            or actual_fence != expected_fence
            or not bool(execution[14])
        ):
            raise KernelError(
                "BOOK_OPENING_PROVIDER_EXECUTION_NOT_AUTHORIZED",
                "budget, reservation, replacement gate or Opening fence is stale",
            )
        return {
            "book_opening_bound": True,
            "execution_authorized": True,
            "opening_run_id": str(opening_run_id),
            "budget_scope_id": str(budget_scope_id),
            "budget_scope_revision": int(budget_scope_revision),
            "reservation_id": str(reservation_id),
            "reservation_version": int(reservation_version),
        }


def _database_clock_timestamp(uow: AuthorityUnitOfWork) -> datetime:
    uow.cursor.execute("SELECT clock_timestamp()")
    return uow.cursor.fetchone()[0]


def _live_book_opening_budget_binding(
    uow: AuthorityUnitOfWork,
    *,
    opening_run_id: str,
    project_id: str,
    book_id: str,
    budget_scope_id: str,
    budget_scope_revision: int,
    opening_execution_id: str,
    opening_execution_generation: int,
    lock: bool = False,
) -> dict[str, Any] | None:

    lock_clause = " FOR UPDATE OF opening,execution,job,attempt,lease" if lock else ""
    uow.cursor.execute(
        f"""
        SELECT opening.opening_run_id,opening.budget_scope_id,
               opening.budget_scope_revision,execution.opening_execution_id,
               execution.generation,job.runtime_job_id,attempt.attempt_id,
               lease.lease_id,lease.worker_id,lease.fencing_token
        FROM authority_book_opening_run AS opening
        JOIN authority_book_opening_execution AS execution
          ON execution.opening_run_id=opening.opening_run_id
         AND execution.opening_execution_id=opening.current_execution_id
         AND execution.generation=opening.current_execution_generation
         AND execution.lifecycle='RUNNING'
        JOIN authority_runtime_job AS job
          ON job.runtime_job_id=execution.runtime_job_id
         AND (
             (
                 opening.workflow_contract_version='book-opening-workflow-v1'
                 AND opening.execution_contract_version=
                     'book-opening-execution-v3'
                 AND job.job_kind='BOOK_OPENING_WORKFLOW_NODE_EXECUTE'
                 AND job.runtime_group='book_opening_workflow_v1'
             ) OR (
                 opening.workflow_contract_version='legacy-monolithic-v2'
                 AND opening.execution_contract_version=
                     'book-opening-execution-v2'
                 AND job.job_kind='BOOK_OPENING_EXECUTE'
                 AND job.runtime_group='book_opening'
             )
         )
         AND job.status IN ('RUNNING','CHECKPOINTED')
         AND job.current_attempt_id=execution.current_attempt_id
         AND job.current_fencing_token=execution.current_fencing_token
        JOIN authority_runtime_job_attempt AS attempt
          ON attempt.runtime_job_id=job.runtime_job_id
         AND attempt.attempt_id=job.current_attempt_id
         AND attempt.status=job.status
         AND attempt.worker_id=job.claimed_by
         AND attempt.fencing_token=job.current_fencing_token
        JOIN authority_runtime_job_lease AS lease
          ON lease.runtime_job_id=job.runtime_job_id
         AND lease.attempt_id=attempt.attempt_id
         AND lease.lease_id=attempt.lease_id
         AND lease.worker_id=attempt.worker_id
         AND lease.fencing_token=attempt.fencing_token
         AND lease.status='HELD'
         AND lease.lease_expires_at>clock_timestamp()
        WHERE opening.opening_run_id=%s
          AND opening.project_id=%s
          AND opening.book_id=%s
          AND opening.lifecycle='RUNNING'
          AND opening.budget_contract_state='BOUND'
          AND opening.budget_scope_id=%s
          AND opening.budget_scope_revision=%s
          AND opening.current_execution_id=%s
          AND opening.current_execution_generation=%s
          AND execution.current_attempt_id=attempt.attempt_id
          AND execution.current_lease_id=lease.lease_id
          AND execution.current_worker_id=attempt.worker_id
          AND execution.current_fencing_token=attempt.fencing_token
        {lock_clause}
        """,
        [
            opening_run_id,
            project_id,
            book_id,
            budget_scope_id,
            budget_scope_revision,
            opening_execution_id,
            opening_execution_generation,
        ],
    )
    live = uow.cursor.fetchone()
    if live is None:
        return None
    return {
        "opening_run_id": str(live[0]),
        "opening_execution_id": str(live[3]),
        "opening_execution_generation": int(live[4]),
        "runtime_job_id": str(live[5]),
        "runtime_attempt_id": str(live[6]),
        "runtime_lease_id": str(live[7]),
        "runtime_worker_id": str(live[8]),
        "runtime_fencing_token": int(live[9]),
    }


def assess_budget_scope_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    budget_scope_id: str,
    project_id: str,
    requested_amount: str | Decimal | None = None,
    requested_tokens: int = 0,
    requested_calls: int = 1,
    execution_mode: str = "PROVIDER_ALLOWED",
    expected_revision: int | None = None,
    locked_scope: Mapping[str, Any] | None = None,
    use_policy_next_provider_allowance: bool = False,
) -> dict[str, Any]:
    if requested_tokens < 0 or requested_calls < 0:
        raise KernelError(
            "BUDGET_ASSESSMENT_INVALID",
            "budget assessment requested usage cannot be negative",
        )
    mode = execution_mode.strip().upper()
    if mode not in {
        "PROVIDER_ALLOWED",
        "PROJECTION_ONLY",
        "DURABLE_RESULT_REPLAY",
    }:
        raise KernelError(
            "BUDGET_ASSESSMENT_INVALID",
            "budget assessment execution_mode is invalid",
        )
    scope = (
        dict(locked_scope)
        if locked_scope is not None
        else lock_budget_scope_in_uow(
            uow,
            budget_scope_id=budget_scope_id,
            project_id=project_id,
        )
    )
    if (
        str(scope.get("budget_scope_id") or "") != budget_scope_id
        or str(scope.get("project_id") or "") != project_id
    ):
        raise KernelError(
            "BUDGET_SCOPE_CONFLICT",
            "locked budget scope does not match the requested Authority owner",
        )
    revision = int(scope["revision"])
    if expected_revision is not None and revision != expected_revision:
        raise KernelError(
            "BUDGET_SCOPE_REASSESS_REQUIRED",
            "budget scope policy revision changed after assessment",
        )
    canonical_policy = canonical_budget_policy(dict(scope["policy_snapshot"] or {}))
    if canonical_policy["policy_hash"] != str(scope["policy_hash"]) or canonical_policy[
        "policy_snapshot"
    ] != dict(scope["policy_snapshot"] or {}):
        raise KernelError(
            "BUDGET_SCOPE_POLICY_DRIFT",
            "budget scope policy differs from its authoritative hash",
        )
    policy = canonical_policy["policy_snapshot"]
    accounting_basis = str(policy.get("accounting_basis") or "PRICED").upper()
    amount: Decimal | None
    if accounting_basis == "ACCOUNT_ENTITLEMENT":
        if requested_amount is not None:
            raise KernelError(
                "BUDGET_ASSESSMENT_INVALID",
                "account entitlement assessment cannot claim a monetary amount",
            )
        amount = None
    else:
        amount = _amount(str(requested_amount if requested_amount is not None else "0"))
    if use_policy_next_provider_allowance:
        allowance = next_provider_budget_allowance(canonical_policy["policy_snapshot"])
        mode = str(allowance["execution_mode"])
        requested_calls = int(allowance["requested_calls"])
        requested_tokens = int(allowance["requested_tokens"])
        allowance_amount = allowance["requested_amount"]
        amount = (
            _amount(str(allowance_amount)) if allowance_amount is not None else None
        )
    uow.cursor.execute("SELECT clock_timestamp()")
    database_now = uow.cursor.fetchone()[0]
    window_state = "EXPIRED" if database_now >= scope["deadline_at"] else "ACTIVE"
    uow.cursor.execute(
        """
        SELECT reservation.reservation_id,reservation.operation_id,
               reservation.external_effect_id,reservation.provider,
               reservation.chapter,reservation.currency,
               reservation.estimated_amount,reservation.reserved_amount,
               reservation.settled_amount,reservation.estimated_tokens,
               reservation.actual_tokens,reservation.status,
               reservation.budget_breach,reservation.budget_scope_revision,
               reservation.version,
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'accounting_basis',''),
                   'PRICED'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'estimated_cost_status',''),
                   'KNOWN'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'settled_cost_status',''),
                   CASE WHEN reservation.status='SETTLED' THEN 'KNOWN'
                        ELSE 'PENDING' END
               )
        FROM authority_budget_reservation AS reservation
        WHERE budget_scope_id=%s AND project_id=%s
        ORDER BY reservation_id
        """,
        [budget_scope_id, project_id],
    )
    reservation_columns = (
        "reservation_id",
        "operation_id",
        "external_effect_id",
        "provider",
        "chapter",
        "currency",
        "estimated_amount",
        "reserved_amount",
        "settled_amount",
        "estimated_tokens",
        "actual_tokens",
        "status",
        "budget_breach",
        "budget_scope_revision",
        "version",
        "accounting_basis",
        "estimated_cost_status",
        "settled_cost_status",
    )
    reservations = [
        dict(zip(reservation_columns, row, strict=True))
        for row in uow.cursor.fetchall()
    ]
    for reservation in reservations:
        reservation["authority_source"] = "DIRECT_SCOPE"
    uow.cursor.execute(
        """
        SELECT attribution.legacy_budget_attribution_id,
               attribution.budget_reconciliation_receipt_id,
               attribution.reservation_version,
               attribution.reservation_status,
               attribution.reservation_snapshot,
               attribution.reservation_snapshot_hash,
               attribution.cost_evidence_id,
               attribution.cost_evidence_version,
               attribution.cost_evidence_hash,
               reservation.reservation_id,reservation.operation_id,
               reservation.external_effect_id,reservation.project_id,
               reservation.stable_idempotency_key,reservation.provider,
               reservation.chapter,reservation.currency,
               reservation.estimated_amount,reservation.reserved_amount,
               reservation.settled_amount,reservation.estimated_tokens,
               reservation.actual_tokens,reservation.status,reservation.caps,
               reservation.evidence,reservation.budget_timezone,
               reservation.budget_scope_id,reservation.budget_scope_revision,
               reservation.budget_breach,reservation.version,
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'accounting_basis',''),
                   'PRICED'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'estimated_cost_status',''),
                   'KNOWN'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'settled_cost_status',''),
                   CASE WHEN reservation.status='SETTLED' THEN 'KNOWN'
                        ELSE 'PENDING' END
               )
        FROM authority_book_opening_legacy_budget_reservation_attribution
             AS attribution
        JOIN authority_budget_reservation AS reservation
          ON reservation.reservation_id=attribution.reservation_id
         AND reservation.project_id=attribution.project_id
        WHERE attribution.budget_scope_id=%s
          AND attribution.budget_scope_revision=%s
          AND attribution.project_id=%s
        ORDER BY attribution.legacy_budget_attribution_id
        """,
        [budget_scope_id, revision, project_id],
    )
    legacy_columns = (
        "legacy_budget_attribution_id",
        "budget_reconciliation_receipt_id",
        "attributed_reservation_version",
        "attributed_reservation_status",
        "reservation_snapshot",
        "reservation_snapshot_hash",
        "cost_evidence_id",
        "cost_evidence_version",
        "cost_evidence_hash",
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
        "accounting_basis",
        "estimated_cost_status",
        "settled_cost_status",
    )
    legacy_attributions = [
        dict(zip(legacy_columns, row, strict=True)) for row in uow.cursor.fetchall()
    ]
    legacy_drift_reasons: list[str] = []
    for attribution in legacy_attributions:
        current_snapshot = canonical_budget_reservation_snapshot(attribution)
        if (
            int(attribution["attributed_reservation_version"])
            != int(attribution["version"])
            or str(attribution["attributed_reservation_status"])
            != str(attribution["status"])
            or dict(attribution["reservation_snapshot"])
            != {
                key: value
                for key, value in current_snapshot.items()
                if key != "snapshot_hash"
            }
            or str(attribution["reservation_snapshot_hash"])
            != str(current_snapshot["snapshot_hash"])
        ):
            legacy_drift_reasons.append("legacy_reservation_authority_drift")
        if str(attribution["status"]) == "SETTLED":
            try:
                _validate_budget_evidence_authority(
                    uow,
                    BudgetEvidenceLinkRequest(
                        budget_scope_id=budget_scope_id,
                        budget_scope_revision=revision,
                        project_id=project_id,
                        reservation_id=str(attribution["reservation_id"]),
                        evidence_kind="OPERATION_COST",
                        evidence_id=str(attribution["cost_evidence_id"] or ""),
                        evidence_version=int(attribution["cost_evidence_version"] or 0),
                        evidence_hash=str(attribution["cost_evidence_hash"] or ""),
                        stable_idempotency_key=(
                            "legacy-operation-cost:"
                            + str(attribution["reservation_id"])
                        ),
                    ),
                    operation_id=str(attribution["operation_id"]),
                )
            except KernelError:
                legacy_drift_reasons.append("legacy_cost_evidence_authority_drift")
        attribution["authority_source"] = "LEGACY_ATTRIBUTION"
        attribution["original_budget_scope_id"] = attribution["budget_scope_id"]
        attribution["original_budget_scope_revision"] = attribution[
            "budget_scope_revision"
        ]
        attribution["budget_scope_revision"] = revision
        reservations.append(attribution)
    uow.cursor.execute(
        """
        SELECT budget_evidence_link_id,budget_scope_id,budget_scope_revision,
               reservation_id,evidence_kind,evidence_id,evidence_version,
               evidence_hash,stable_idempotency_key
        FROM authority_budget_evidence_link
        WHERE budget_scope_id=%s
        ORDER BY budget_evidence_link_id
        """,
        [budget_scope_id],
    )
    link_columns = (
        "budget_evidence_link_id",
        "budget_scope_id",
        "budget_scope_revision",
        "reservation_id",
        "evidence_kind",
        "evidence_id",
        "evidence_version",
        "evidence_hash",
        "stable_idempotency_key",
    )
    evidence_links = [
        dict(zip(link_columns, row, strict=True)) for row in uow.cursor.fetchall()
    ]
    provider_call_count = sum(
        1
        for reservation in reservations
        if reservation["status"] in {"RESERVED", "HELD_UNKNOWN", "SETTLED"}
        or (
            reservation["status"] == "RELEASED"
            and int(reservation["actual_tokens"]) > 0
        )
    )
    committed_tokens = 0
    committed_amount = Decimal("0")
    status_counts: dict[str, int] = {}
    reasons: list[str] = list(legacy_drift_reasons)
    for reservation in reservations:
        status = str(reservation["status"])
        reservation_basis = str(reservation.get("accounting_basis") or "PRICED").upper()
        if reservation_basis != accounting_basis:
            reasons.append("reservation_accounting_basis_drift")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "SETTLED":
            committed_tokens += int(reservation["actual_tokens"])
            if reservation_basis == "PRICED":
                committed_amount += Decimal(reservation["settled_amount"])
        elif status in {"RESERVED", "HELD_UNKNOWN"}:
            committed_tokens += int(reservation["estimated_tokens"])
            if reservation_basis == "PRICED":
                committed_amount += Decimal(reservation["reserved_amount"])
        elif status == "RELEASED" and int(reservation["actual_tokens"]) > 0:
            committed_tokens += int(reservation["actual_tokens"])
        if status == "HELD_UNKNOWN" or bool(reservation["budget_breach"]):
            reasons.append("budget_external_state_ambiguous")
        reservation_revision = reservation["budget_scope_revision"]
        if reservation_revision is None or int(reservation_revision) != revision:
            reasons.append("reservation_policy_revision_drift")
    operation_cost_links = {
        str(link["reservation_id"])
        for link in evidence_links
        if str(link["evidence_kind"]) == "OPERATION_COST"
    }
    if any(
        reservation["status"] == "SETTLED"
        and reservation.get("authority_source") != "LEGACY_ATTRIBUTION"
        and str(reservation["reservation_id"]) not in operation_cost_links
        for reservation in reservations
    ):
        reasons.append("settlement_evidence_link_missing")
    reservations_by_id = {
        str(reservation["reservation_id"]): reservation for reservation in reservations
    }
    for link in evidence_links:
        reservation = reservations_by_id.get(str(link["reservation_id"]))
        if reservation is None:
            reasons.append("budget_evidence_reservation_missing")
            continue
        try:
            _validate_budget_evidence_authority(
                uow,
                BudgetEvidenceLinkRequest(
                    budget_scope_id=str(link["budget_scope_id"]),
                    budget_scope_revision=int(link["budget_scope_revision"]),
                    project_id=project_id,
                    reservation_id=str(link["reservation_id"]),
                    evidence_kind=str(link["evidence_kind"]),
                    evidence_id=str(link["evidence_id"]),
                    evidence_version=int(link["evidence_version"]),
                    evidence_hash=str(link["evidence_hash"]),
                    stable_idempotency_key=str(link["stable_idempotency_key"]),
                    budget_evidence_link_id=str(link["budget_evidence_link_id"]),
                ),
                operation_id=str(reservation["operation_id"]),
            )
        except KernelError:
            reasons.append("budget_evidence_authority_drift")
    policy_mode = str(policy["execution_mode"])
    if mode == "PROJECTION_ONLY":
        outcome = BudgetAssessmentOutcome.NOT_REQUIRED
        reasons = []
        call_headroom: int | None = None
        token_headroom: int | None = None
        cost_headroom: Decimal | None = None
    elif mode == "DURABLE_RESULT_REPLAY":
        # INVARIANT: Re-projecting an immutable, already-paid Provider result performs no
        # external call.  It still validates reservation/cost evidence and
        # therefore cannot bypass ambiguous or drifted Budget Authority.
        outcome = (
            BudgetAssessmentOutcome.RECONCILIATION_REQUIRED
            if reasons
            else BudgetAssessmentOutcome.NOT_REQUIRED
        )
        call_headroom = token_headroom = None
        cost_headroom = None
    elif reasons or policy_mode == "PROJECTION_ONLY":
        if policy_mode == "PROJECTION_ONLY":
            reasons.append("provider_execution_forbidden_by_scope")
        outcome = BudgetAssessmentOutcome.RECONCILIATION_REQUIRED
        call_headroom = token_headroom = None
        cost_headroom = None
    else:
        call_limit = int(policy["provider_call_limit"])
        token_limit = int(policy["token_limit"])
        call_headroom = max(0, call_limit - provider_call_count)
        token_headroom = max(0, token_limit - committed_tokens)
        cost_limit = (
            None
            if accounting_basis == "ACCOUNT_ENTITLEMENT"
            else _amount(str(policy["cost_limit_usd"]))
        )
        cost_headroom = (
            None
            if cost_limit is None
            else max(Decimal("0"), cost_limit - committed_amount)
        )
        if window_state == "EXPIRED":
            reasons.append("budget_deadline_expired")
        if provider_call_count + requested_calls > call_limit:
            reasons.append("provider_call_limit_exhausted")
        if committed_tokens + requested_tokens > token_limit:
            reasons.append("token_limit_exhausted")
        if (
            cost_limit is not None
            and amount is not None
            and committed_amount + amount > cost_limit
        ):
            reasons.append("cost_limit_exhausted")
        per_call_token_limit = int(policy.get("per_call_token_limit", token_limit))
        if (
            requested_calls > 0
            and requested_tokens > per_call_token_limit * requested_calls
        ):
            reasons.append("per_call_token_limit_exceeded")
        if cost_limit is not None and amount is not None:
            per_call_cost_limit = _amount(
                str(policy.get("per_call_cost_limit_usd", cost_limit))
            )
            if requested_calls > 0 and amount > per_call_cost_limit * requested_calls:
                reasons.append("per_call_cost_limit_exceeded")
        outcome = (
            BudgetAssessmentOutcome.EXHAUSTED
            if reasons
            else BudgetAssessmentOutcome.ELIGIBLE
        )
    usage = {
        "provider_call_count": provider_call_count,
        "committed_tokens": committed_tokens,
        "committed_amount": (
            None
            if accounting_basis == "ACCOUNT_ENTITLEMENT"
            else _decimal_text(committed_amount)
        ),
        "cost_status": (
            "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
        ),
        "status_counts": status_counts,
    }
    headroom = {
        "provider_calls": call_headroom,
        "tokens": token_headroom,
        "cost_amount": (
            _decimal_text(cost_headroom) if cost_headroom is not None else None
        ),
    }
    snapshot = canonical_budget_snapshot(
        scope=scope,
        reservations=reservations,
        evidence_links=evidence_links,
        legacy_attributions=legacy_attributions,
        usage=usage,
        headroom=headroom,
        window_state=window_state,
        outcome=outcome,
        reasons=reasons,
        request={
            "execution_mode": mode,
            "requested_calls": requested_calls,
            "requested_tokens": requested_tokens,
            "requested_amount": _decimal_text(amount) if amount is not None else None,
            "accounting_basis": accounting_basis,
            "cost_status": (
                "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
            ),
        },
    )
    return {
        **snapshot,
        "budget_scope_id": budget_scope_id,
        "budget_scope_revision": revision,
        "budget_policy_hash": str(scope["policy_hash"]),
        "budget_snapshot_digest": snapshot["snapshot_hash"],
    }


def append_budget_evidence_link(
    database_url: str, request: BudgetEvidenceLinkRequest
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        result = append_budget_evidence_link_in_uow(uow, request)
        uow.commit()
        return result


def append_budget_evidence_link_in_uow(
    uow: AuthorityUnitOfWork,
    request: BudgetEvidenceLinkRequest,
    *,
    locked_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:

    scope = (
        dict(locked_scope)
        if locked_scope is not None
        else lock_budget_scope_in_uow(
            uow,
            budget_scope_id=request.budget_scope_id,
            project_id=request.project_id,
        )
    )
    if (
        str(scope.get("budget_scope_id") or "") != request.budget_scope_id
        or str(scope.get("project_id") or "") != request.project_id
        or int(scope.get("revision") or 0) != request.budget_scope_revision
    ):
        raise KernelError(
            "BUDGET_SCOPE_REASSESS_REQUIRED",
            "budget evidence link policy revision is stale",
        )
    uow.cursor.execute(
        """
        SELECT operation_id,budget_scope_id,budget_scope_revision
        FROM authority_budget_reservation
        WHERE reservation_id=%s AND project_id=%s
        FOR UPDATE
        """,
        [request.reservation_id, request.project_id],
    )
    reservation = uow.cursor.fetchone()
    if reservation is None or (
        str(reservation[1]) != request.budget_scope_id
        or int(reservation[2]) != request.budget_scope_revision
    ):
        raise KernelError(
            "BUDGET_EVIDENCE_SCOPE_CONFLICT",
            "budget evidence reservation is outside its policy scope",
        )
    _validate_budget_evidence_authority(uow, request, operation_id=str(reservation[0]))
    uow.cursor.execute(
        """
        INSERT INTO authority_budget_evidence_link(
            budget_evidence_link_id,budget_scope_id,budget_scope_revision,
            reservation_id,evidence_kind,evidence_id,evidence_version,
            evidence_hash,stable_idempotency_key
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
        RETURNING budget_evidence_link_id
        """,
        [
            request.budget_evidence_link_id,
            request.budget_scope_id,
            request.budget_scope_revision,
            request.reservation_id,
            request.evidence_kind,
            request.evidence_id,
            request.evidence_version,
            request.evidence_hash,
            request.stable_idempotency_key,
        ],
    )
    created = uow.cursor.fetchone() is not None
    if not created:
        uow.cursor.execute(
            """
            SELECT budget_evidence_link_id,budget_scope_id,
                   budget_scope_revision,reservation_id,evidence_kind,
                   evidence_id,evidence_version,evidence_hash,
                   stable_idempotency_key
            FROM authority_budget_evidence_link
            WHERE budget_scope_id=%s AND (
                budget_evidence_link_id=%s OR stable_idempotency_key=%s
                OR (
                    reservation_id=%s AND evidence_kind=%s
                    AND evidence_id=%s AND evidence_version=%s
                )
            )
            ORDER BY CASE WHEN budget_evidence_link_id=%s THEN 0 ELSE 1 END
            LIMIT 1
            """,
            [
                request.budget_scope_id,
                request.budget_evidence_link_id,
                request.stable_idempotency_key,
                request.reservation_id,
                request.evidence_kind,
                request.evidence_id,
                request.evidence_version,
                request.budget_evidence_link_id,
            ],
        )
        existing = uow.cursor.fetchone()
        expected = (
            request.budget_evidence_link_id,
            request.budget_scope_id,
            request.budget_scope_revision,
            request.reservation_id,
            request.evidence_kind,
            request.evidence_id,
            request.evidence_version,
            request.evidence_hash,
            request.stable_idempotency_key,
        )
        if existing is None or tuple(existing) != expected:
            raise KernelError(
                "BUDGET_EVIDENCE_IDEMPOTENCY_CONFLICT",
                "budget evidence identity belongs to another Authority edge",
            )
    else:
        _record_budget_evidence_link(
            uow,
            request,
            operation_id=str(reservation[0]),
        )
    return {
        "budget_evidence_link_id": request.budget_evidence_link_id,
        "budget_scope_id": request.budget_scope_id,
        "budget_scope_revision": request.budget_scope_revision,
        "replayed": not created,
    }


def _operation_cost_authority_payload(
    *,
    cost_evidence_id: str,
    operation_id: str,
    provider: str,
    model: str,
    amount: Decimal | None,
    currency: str,
    evidence: Mapping[str, Any],
    accounting_basis: str,
    cost_status: str,
) -> dict[str, Any]:
    basis = accounting_basis.strip().upper() or "PRICED"
    payload: dict[str, Any] = {
        "cost_evidence_id": cost_evidence_id,
        "operation_id": operation_id,
        "provider": provider,
        "model": model,
        "amount": _decimal_text(amount) if amount is not None else None,
        "currency": currency,
        "evidence": dict(evidence),
    }
    if basis == "ACCOUNT_ENTITLEMENT":
        payload.update(
            {
                "accounting_basis": basis,
                "cost_status": cost_status.strip().upper() or "UNKNOWN",
            }
        )
    return payload


def _read_operation_cost_authority_payload(
    uow: AuthorityUnitOfWork,
    *,
    cost_evidence_id: str,
    operation_id: str,
) -> dict[str, Any] | None:
    uow.cursor.execute(
        """
        SELECT cost.cost_evidence_id,cost.operation_id,cost.provider,cost.model,
               cost.amount,cost.currency,cost.evidence,
               COALESCE(
                   NULLIF(to_jsonb(cost)->>'accounting_basis',''),
                   'PRICED'
               ),
               COALESCE(
                   NULLIF(to_jsonb(cost)->>'cost_status',''),
                   'KNOWN'
               )
        FROM authority_operation_cost_evidence AS cost
        WHERE cost.cost_evidence_id=%s AND cost.operation_id=%s
        FOR KEY SHARE
        """,
        [cost_evidence_id, operation_id],
    )
    row = uow.cursor.fetchone()
    if row is None:
        return None
    return _operation_cost_authority_payload(
        cost_evidence_id=str(row[0]),
        operation_id=str(row[1]),
        provider=str(row[2]),
        model=str(row[3]),
        amount=Decimal(row[4]) if row[4] is not None else None,
        currency=str(row[5]),
        evidence=dict(row[6] or {}),
        accounting_basis=str(row[7]),
        cost_status=str(row[8]),
    )


def _validate_budget_evidence_authority(
    uow: AuthorityUnitOfWork,
    request: BudgetEvidenceLinkRequest,
    *,
    operation_id: str,
) -> None:
    if request.evidence_kind == "OPERATION_COST":
        evidence = _read_operation_cost_authority_payload(
            uow,
            cost_evidence_id=request.evidence_id,
            operation_id=operation_id,
        )
        if evidence is None or request.evidence_version != 0:
            raise KernelError(
                "BUDGET_EVIDENCE_AUTHORITY_MISSING",
                "operation cost evidence is missing",
            )
        if _canonical_hash(evidence) != request.evidence_hash:
            raise KernelError(
                "BUDGET_EVIDENCE_HASH_CONFLICT",
                "operation cost evidence differs from its link hash",
            )
        return
    expected_asset_type = (
        "cost_ledger" if request.evidence_kind == "COST_LEDGER" else "model_call_log"
    )
    uow.cursor.execute(
        """
        SELECT version.version_number,version.content_hash,asset.project_id,
               asset.asset_type
        FROM authority_asset_version AS version
        JOIN authority_asset AS asset ON asset.asset_id=version.asset_id
        WHERE version.asset_version_id=%s
        FOR KEY SHARE OF version,asset
        """,
        [request.evidence_id],
    )
    asset = uow.cursor.fetchone()
    if asset is None or (
        int(asset[0]) != request.evidence_version
        or str(asset[1]) != request.evidence_hash
        or str(asset[2]) != request.project_id
        or str(asset[3]) != expected_asset_type
    ):
        raise KernelError(
            "BUDGET_EVIDENCE_AUTHORITY_MISSING",
            "budget evidence Asset is missing or differs from its Authority version",
        )


def _record_budget_evidence_link(
    uow: AuthorityUnitOfWork,
    request: BudgetEvidenceLinkRequest,
    *,
    operation_id: str,
) -> None:
    event_id = str(uuid4())
    body = {
        "budget_scope_id": request.budget_scope_id,
        "budget_scope_revision": request.budget_scope_revision,
        "budget_evidence_link_id": request.budget_evidence_link_id,
        "reservation_id": request.reservation_id,
        "evidence_kind": request.evidence_kind,
        "evidence_id": request.evidence_id,
        "evidence_version": request.evidence_version,
        "evidence_hash": request.evidence_hash,
    }
    uow.cursor.execute(
        """
        SELECT COALESCE(MAX(sequence_number),0)+1
        FROM state_event
        WHERE aggregate_type='authority_provider_budget_scope'
          AND aggregate_id=%s
        """,
        [request.budget_scope_id],
    )
    sequence = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        """
        INSERT INTO state_event(
            event_id,project_id,aggregate_type,aggregate_id,event_type,
            event_version,sequence_number,payload,correlation_id,causation_id
        ) VALUES (
            %s,%s,'authority_provider_budget_scope',%s,
            'authority.provider_budget_scope.evidence_linked',1,%s,%s,'',%s
        )
        """,
        [
            event_id,
            request.project_id,
            request.budget_scope_id,
            sequence,
            Jsonb(body),
            operation_id,
        ],
    )
    uow.cursor.execute(
        """
        INSERT INTO audit_log(audit_id,project_id,operation_id,action,payload)
        VALUES (%s,%s,%s,'authority.provider_budget_scope.evidence_linked',%s)
        """,
        [str(uuid4()), request.project_id, operation_id, Jsonb(body)],
    )
    uow.cursor.execute(
        """
        INSERT INTO outbox_event(
            outbox_id,event_id,project_id,topic,status,payload
        ) VALUES (
            %s,%s,%s,'authority.provider_budget_scope.evidence_linked','pending',%s
        )
        """,
        [str(uuid4()), event_id, request.project_id, Jsonb(body)],
    )


def _budget_scope(
    uow: AuthorityUnitOfWork,
    *,
    budget_scope_id: str,
    project_id: str,
    lock: bool,
) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    uow.cursor.execute(
        f"""
        SELECT budget_scope_id,project_id,owner_kind,owner_id,currency,
               policy_contract_version,policy_snapshot,policy_hash,
               budget_timezone,started_at,deadline_at,revision,
               created_by_operation_id,stable_idempotency_key
        FROM authority_provider_budget_scope
        WHERE budget_scope_id=%s AND project_id=%s{suffix}
        """,
        [budget_scope_id, project_id],
    )
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("BUDGET_SCOPE_NOT_FOUND", "budget scope is missing")
    return dict(
        zip(
            (
                "budget_scope_id",
                "project_id",
                "owner_kind",
                "owner_id",
                "currency",
                "policy_contract_version",
                "policy_snapshot",
                "policy_hash",
                "budget_timezone",
                "started_at",
                "deadline_at",
                "revision",
                "created_by_operation_id",
                "stable_idempotency_key",
            ),
            row,
            strict=True,
        )
    )


def _record_budget_scope(
    uow: AuthorityUnitOfWork,
    request: BudgetScopeRequest,
    *,
    topic: str,
    payload: Mapping[str, Any],
) -> None:
    event_id = str(uuid4())
    body = {"budget_scope_id": request.budget_scope_id, **dict(payload)}
    uow.cursor.execute(
        """
        INSERT INTO state_event(
            event_id,project_id,aggregate_type,aggregate_id,event_type,
            event_version,sequence_number,payload,correlation_id,causation_id
        ) VALUES (
            %s,%s,'authority_provider_budget_scope',%s,%s,1,1,%s,'',%s
        )
        """,
        [
            event_id,
            request.project_id,
            request.budget_scope_id,
            topic,
            Jsonb(body),
            request.created_by_operation_id,
        ],
    )
    uow.cursor.execute(
        """
        INSERT INTO audit_log(
            audit_id,project_id,operation_id,action,payload
        ) VALUES (%s,%s,%s,%s,%s)
        """,
        [
            str(uuid4()),
            request.project_id,
            request.created_by_operation_id,
            topic,
            Jsonb(body),
        ],
    )
    uow.cursor.execute(
        """
        INSERT INTO outbox_event(
            outbox_id,event_id,project_id,topic,status,payload
        ) VALUES (%s,%s,%s,%s,'pending',%s)
        """,
        [str(uuid4()), event_id, request.project_id, topic, Jsonb(body)],
    )


@dataclass(frozen=True, slots=True)
class BudgetReservationRequest:
    operation_id: str
    external_effect_id: str
    project_id: str
    stable_idempotency_key: str
    provider: str
    currency: str
    estimated_amount: str | None
    estimated_tokens: int
    chapter: int | None = None
    caps: dict[str, str] | None = None
    call_caps: dict[str, int] | None = None
    token_caps: dict[str, int] | None = None
    budget_timezone: str = "UTC"
    budget_scope_id: str = ""
    expected_budget_scope_revision: int | None = None
    accounting_basis: str = "PRICED"
    cost_authorization_ref: str = ""
    model_id: str = ""
    work_id: str = ""


def reserve_provider_budget(
    database_url: str,
    request: BudgetReservationRequest,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        result = reserve_provider_budget_in_uow(uow, request)
        uow.commit()
        return result


def reserve_provider_budget_in_uow(
    uow: AuthorityUnitOfWork,
    request: BudgetReservationRequest,
) -> dict[str, Any]:

    accounting_basis = request.accounting_basis.strip().upper()
    if accounting_basis not in {"PRICED", "ACCOUNT_ENTITLEMENT"}:
        raise KernelError(
            "BUDGET_RESERVATION_INVALID", "budget accounting basis is invalid"
        )
    cost_observability_schema = _has_budget_cost_observability_schema(uow)
    if accounting_basis == "ACCOUNT_ENTITLEMENT" and not cost_observability_schema:
        raise KernelError(
            "BUDGET_SCHEMA_UPGRADE_REQUIRED",
            "account entitlement requires the budget cost-observability migration",
        )
    if accounting_basis == "ACCOUNT_ENTITLEMENT":
        if request.estimated_amount is not None or not request.cost_authorization_ref:
            raise KernelError(
                "BUDGET_RESERVATION_INVALID",
                "account entitlement reservation requires UNKNOWN cost and authorization",
            )
        amount: Decimal | None = None
    else:
        if request.estimated_amount is None:
            raise KernelError(
                "BUDGET_RESERVATION_INVALID",
                "priced reservation requires an estimated amount",
            )
        amount = _amount(request.estimated_amount)
    if (
        not all(
            (
                request.operation_id,
                request.external_effect_id,
                request.project_id,
                request.stable_idempotency_key,
                request.provider,
                request.currency,
                request.budget_timezone,
            )
        )
        or request.estimated_tokens < 0
        or (request.chapter is not None and request.chapter <= 0)
    ):
        raise KernelError(
            "BUDGET_RESERVATION_INVALID", "budget reservation is incomplete"
        )
    if (
        request.expected_budget_scope_revision is not None
        and not request.budget_scope_id
    ):
        raise KernelError(
            "BUDGET_RESERVATION_INVALID",
            "budget scope revision requires a budget_scope_id",
        )
    caps = {key: _amount(value) for key, value in (request.caps or {}).items()}
    call_caps = _canonical_usage_caps(request.call_caps, kind="call")
    token_caps = _canonical_usage_caps(request.token_caps, kind="token")
    locked_budget_scope = resolve_book_opening_budget_scope_in_uow(
        uow,
        operation_id=request.operation_id,
        project_id=request.project_id,
        currency=request.currency,
    )
    if locked_budget_scope is not None:
        scope_basis = str(
            dict(locked_budget_scope.get("policy_snapshot") or {}).get(
                "accounting_basis"
            )
            or "PRICED"
        ).upper()
        if scope_basis != accounting_basis:
            raise KernelError(
                "BUDGET_SCOPE_CONFLICT",
                "reservation accounting basis differs from its BudgetScope",
            )
        if request.estimated_tokens <= 0:
            raise KernelError(
                "BOOK_OPENING_PROVIDER_TOKEN_CEILING_REQUIRED",
                "Book Opening Provider execution requires a positive frozen token ceiling",
            )
        if request.budget_scope_id and request.budget_scope_id != str(
            locked_budget_scope["budget_scope_id"]
        ):
            raise KernelError(
                "BOOK_OPENING_BUDGET_SCOPE_DRIFT",
                "reservation requested a different live Opening BudgetScope",
            )
        if (
            request.expected_budget_scope_revision is not None
            and request.expected_budget_scope_revision
            != int(locked_budget_scope["revision"])
        ):
            raise KernelError(
                "BUDGET_SCOPE_REASSESS_REQUIRED",
                "reservation requested a stale live Opening policy revision",
            )
    elif request.budget_scope_id:
        locked_budget_scope = lock_budget_scope_in_uow(
            uow,
            budget_scope_id=request.budget_scope_id,
            project_id=request.project_id,
        )
        if str(locked_budget_scope["currency"]).upper() != request.currency.upper():
            raise KernelError(
                "BUDGET_SCOPE_CONFLICT",
                "budget reservation currency differs from its BudgetScope",
            )
        if str(locked_budget_scope["owner_kind"]) == "BOOK_OPENING":
            raise KernelError(
                "BOOK_OPENING_EXACT_BUDGET_BINDING_REQUIRED",
                "Book Opening BudgetScope cannot be selected without exact Operation lineage",
            )
    else:
        acquire_budget_locks_in_uow(uow, currencies=(request.currency,))
    if locked_budget_scope is not None:
        scope_policy = canonical_budget_policy(
            dict(locked_budget_scope.get("policy_snapshot") or {})
        )["policy_snapshot"]
        scope_basis = str(scope_policy.get("accounting_basis") or "PRICED").upper()
        if scope_basis != accounting_basis:
            raise KernelError(
                "BUDGET_SCOPE_CONFLICT",
                "reservation accounting basis differs from its BudgetScope",
            )
        if (
            accounting_basis == "ACCOUNT_ENTITLEMENT"
            and str(scope_policy.get("authorization_ref") or "")
            != request.cost_authorization_ref
        ):
            raise KernelError(
                "BUDGET_SCOPE_CONFLICT",
                "reservation authorization differs from its BudgetScope",
            )
    effective_budget_scope_id = (
        str(locked_budget_scope["budget_scope_id"])
        if locked_budget_scope is not None
        else ""
    )
    effective_budget_scope_revision = (
        int(locked_budget_scope["revision"])
        if locked_budget_scope is not None
        else None
    )
    uow.cursor.execute(
        """
        SELECT operation.project_id,effect.project_id,
               COALESCE(
                   NULLIF(operation.command_payload->'payload'->>'book_id',''),
                   NULLIF(operation.command_payload->>'book_id',''),
                   ''
               ), effect.model_id,
               effect.request_payload #>> '{_production_execution,book_id}'
        FROM authority_operation AS operation
        JOIN authority_external_effect AS effect
          ON effect.external_effect_id = %s AND effect.operation_id = operation.operation_id
        WHERE operation.operation_id = %s
        FOR UPDATE OF operation, effect
        """,
        [request.external_effect_id, request.operation_id],
    )
    operation_scope = uow.cursor.fetchone()
    if operation_scope and ((request.model_id and str(operation_scope[3]) != request.model_id)
        or (request.work_id and str(operation_scope[4]) != request.work_id)):
        raise KernelError("BUDGET_SCOPE_CONFLICT", "budget model or work differs from frozen Effect")
    expected_book_id = str((locked_budget_scope or {}).get("book_id") or "")
    if (
        operation_scope is None
        or tuple(operation_scope[:2])
        != (
            request.project_id,
            request.project_id,
        )
        or (expected_book_id and str(operation_scope[2]) != expected_book_id)
    ):
        raise KernelError(
            "BUDGET_SCOPE_CONFLICT", "budget effect is outside project scope"
        )
    if locked_budget_scope is not None:
        revalidate_book_opening_budget_scope_in_uow(uow, locked_budget_scope)
    uow.cursor.execute(
        """
        SELECT reservation.reservation_id,reservation.operation_id,
               reservation.external_effect_id,reservation.provider,
               reservation.currency,reservation.estimated_amount,
               reservation.estimated_tokens,reservation.status,
               reservation.budget_scope_id,reservation.budget_scope_revision,
               reservation.version,
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'accounting_basis',''),
                   'PRICED'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'estimated_cost_status',''),
                   'KNOWN'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'settled_cost_status',''),
                   CASE WHEN reservation.status='SETTLED' THEN 'KNOWN'
                        ELSE 'PENDING' END
               ),
               reservation.evidence
        FROM authority_budget_reservation AS reservation
        WHERE project_id=%s AND stable_idempotency_key=%s
        FOR UPDATE
        """,
        [request.project_id, request.stable_idempotency_key],
    )
    existing = uow.cursor.fetchone()
    if existing is not None:
        expected = (
            request.operation_id,
            request.external_effect_id,
            request.provider,
            request.currency,
            amount,
            request.estimated_tokens,
            effective_budget_scope_id or None,
            effective_budget_scope_revision,
            accounting_basis,
            call_caps,
            token_caps,
            request.cost_authorization_ref,
        )
        actual = (
            str(existing[1]),
            str(existing[2]),
            str(existing[3]),
            str(existing[4]),
            existing[5],
            int(existing[6]),
            str(existing[8]) if existing[8] is not None else None,
            int(existing[9]) if existing[9] is not None else None,
            str(existing[11]),
            dict(existing[14] or {}).get("call_caps", {}),
            dict(existing[14] or {}).get("token_caps", {}),
            str(dict(existing[14] or {}).get("cost_authorization_ref") or ""),
        )
        if actual != expected:
            raise KernelError(
                "BUDGET_IDEMPOTENCY_CONFLICT",
                "budget stable key belongs to another request",
            )
        status = str(existing[7])
        if status == "RESERVED" and locked_budget_scope is not None:
            _bind_budget_effect_in_uow(
                uow,
                reservation_id=str(existing[0]),
                reservation_version=int(existing[10]),
                request=request,
                opening_binding=locked_budget_scope,
            )
        return {
            "reservation_id": str(existing[0]),
            "status": status,
            "replayed": True,
            "budget_scope_id": effective_budget_scope_id,
            "budget_scope_revision": effective_budget_scope_revision,
            "version": int(existing[10]),
            "execution_authorized": status == "RESERVED",
            "replay_disposition": _reservation_replay_disposition(status),
            "accounting_basis": accounting_basis,
            "cost_status": (
                "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
            ),
        }
    from novel_forge.modules.command_kernel.creative_budget_runtime import reserve_creative_budget_in_uow
    creative_budget = reserve_creative_budget_in_uow(uow, request)
    budget_scope_revision: int | None = None
    if locked_budget_scope is not None:
        budget_scope_revision = effective_budget_scope_revision
        assessment = assess_budget_scope_in_uow(
            uow,
            budget_scope_id=effective_budget_scope_id,
            project_id=request.project_id,
            requested_amount=amount,
            requested_tokens=request.estimated_tokens,
            requested_calls=1,
            execution_mode="PROVIDER_ALLOWED",
            expected_revision=(
                request.expected_budget_scope_revision
                if request.expected_budget_scope_revision is not None
                else effective_budget_scope_revision
            ),
            locked_scope=locked_budget_scope,
        )
        if assessment["outcome"] != BudgetAssessmentOutcome.ELIGIBLE:
            code = (
                "BUDGET_SCOPE_EXHAUSTED"
                if assessment["outcome"] == BudgetAssessmentOutcome.EXHAUSTED
                else "BUDGET_SCOPE_RECONCILIATION_REQUIRED"
            )
            raise KernelError(
                code,
                "budget scope does not authorize a new Provider reservation",
            )
    _enforce_agent_session_aggregate(
        uow.cursor,
        request,
        amount=amount,
        tokens=request.estimated_tokens,
    )
    _enforce_usage_caps(
        uow.cursor,
        request,
        tokens=request.estimated_tokens,
        call_caps=call_caps,
        token_caps=token_caps,
    )
    if amount is not None:
        _enforce_caps(uow.cursor, request, amount, caps)
    elif caps:
        raise KernelError(
            "BUDGET_CAP_INVALID",
            "account entitlement cannot use monetary reservation caps",
        )
    reservation_id = str(uuid4())
    reservation_evidence = Jsonb(
        {
            "phase": "pre_dispatch",
            "fixture": amount == 0,
            "accounting_basis": accounting_basis,
            "estimated_cost_status": (
                "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
            ),
            "cost_authorization_ref": request.cost_authorization_ref,
            "call_caps": call_caps,
            "token_caps": token_caps,
            "budget_scope_id": effective_budget_scope_id,
            "budget_scope_revision": budget_scope_revision,
            **({"creative_experiment": creative_budget} if creative_budget is not None else {}),
        }
    )
    insert_values: list[Any] = [
        reservation_id,
        request.operation_id,
        request.external_effect_id,
        request.project_id,
        request.stable_idempotency_key,
        request.provider,
        request.chapter,
        request.currency,
        amount,
        amount,
        Decimal("0") if amount is not None else None,
        request.estimated_tokens,
        Jsonb({key: str(value) for key, value in caps.items()}),
        reservation_evidence,
        request.budget_timezone,
        effective_budget_scope_id or None,
        budget_scope_revision,
    ]
    if cost_observability_schema:
        uow.cursor.execute(
            """
            INSERT INTO authority_budget_reservation (
                reservation_id, operation_id, external_effect_id, project_id,
                stable_idempotency_key, provider, chapter, currency,
                estimated_amount, reserved_amount, settled_amount,
                estimated_tokens, status, caps,
                evidence, budget_timezone, budget_scope_id,
                budget_scope_revision, version, accounting_basis,
                estimated_cost_status,settled_cost_status
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, 'RESERVED', %s, %s, %s, %s, %s, 0,
                %s,%s,'PENDING'
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            RETURNING reservation_id
            """,
            [
                *insert_values,
                accounting_basis,
                (
                    "UNKNOWN"
                    if accounting_basis == "ACCOUNT_ENTITLEMENT"
                    else "KNOWN"
                ),
            ],
        )
    else:
        uow.cursor.execute(
            """
            INSERT INTO authority_budget_reservation (
                reservation_id, operation_id, external_effect_id, project_id,
                stable_idempotency_key, provider, chapter, currency,
                estimated_amount, reserved_amount, settled_amount,
                estimated_tokens, status, caps,
                evidence, budget_timezone, budget_scope_id,
                budget_scope_revision, version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, 'RESERVED', %s, %s, %s, %s, %s, 0
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            RETURNING reservation_id
            """,
            insert_values,
        )
    inserted = uow.cursor.fetchone()
    replayed = inserted is None
    if replayed:
        uow.cursor.execute(
            """
            SELECT reservation.reservation_id,reservation.operation_id,
                   reservation.external_effect_id,reservation.provider,
                   reservation.currency,reservation.estimated_amount,
                   reservation.estimated_tokens,reservation.status,
                   reservation.budget_scope_id,
                   reservation.budget_scope_revision,reservation.version,
                   COALESCE(
                       NULLIF(to_jsonb(reservation)->>'accounting_basis',''),
                       'PRICED'
                   ),
                   COALESCE(
                       NULLIF(
                           to_jsonb(reservation)->>'estimated_cost_status',''
                       ),
                       'KNOWN'
                   ),
                   COALESCE(
                       NULLIF(
                           to_jsonb(reservation)->>'settled_cost_status',''
                       ),
                       CASE WHEN reservation.status='SETTLED' THEN 'KNOWN'
                            ELSE 'PENDING' END
                   ),
                   reservation.evidence
            FROM authority_budget_reservation AS reservation
            WHERE project_id = %s AND stable_idempotency_key = %s
            """,
            [
                request.project_id,
                request.stable_idempotency_key,
            ],
        )
        concurrent = uow.cursor.fetchone()
        expected = (
            request.operation_id,
            request.external_effect_id,
            request.provider,
            request.currency,
            amount,
            request.estimated_tokens,
            effective_budget_scope_id or None,
            budget_scope_revision,
            accounting_basis,
            call_caps,
            token_caps,
        )
        if (
            concurrent is None
            or tuple(concurrent[1:7])
            + (
                str(concurrent[8]) if concurrent[8] is not None else None,
                int(concurrent[9]) if concurrent[9] is not None else None,
                str(concurrent[11]),
                dict(concurrent[14] or {}).get("call_caps", {}),
                dict(concurrent[14] or {}).get("token_caps", {}),
            )
            != expected
        ):
            raise KernelError(
                "BUDGET_IDEMPOTENCY_CONFLICT",
                "budget stable key belongs to another request",
            )
        reservation_id = str(concurrent[0])
        status = str(concurrent[7])
    else:
        status = "RESERVED"
        reservation_version = 0
    if replayed:
        reservation_version = int(concurrent[10])
    if locked_budget_scope is not None and status == "RESERVED":
        _bind_budget_effect_in_uow(
            uow,
            reservation_id=reservation_id,
            reservation_version=reservation_version,
            request=request,
            opening_binding=locked_budget_scope,
        )
    if not replayed:
        _record(
            uow,
            request,
            reservation_id,
            "authority.budget.reserved",
            {
                "amount": str(amount) if amount is not None else None,
                "cost_status": (
                    "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
                ),
                "budget_scope_id": effective_budget_scope_id,
                "budget_scope_revision": budget_scope_revision,
                "call_caps": call_caps,
                "token_caps": token_caps,
            },
        )
    return {
        "reservation_id": reservation_id,
        "status": status,
        "replayed": replayed,
        "budget_scope_id": effective_budget_scope_id,
        "budget_scope_revision": budget_scope_revision,
        "version": reservation_version,
        "execution_authorized": status == "RESERVED",
        "replay_disposition": _reservation_replay_disposition(status),
        "accounting_basis": accounting_basis,
        "cost_status": (
            "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
        ),
        "call_caps": call_caps,
        "token_caps": token_caps,
    }


def _reservation_replay_disposition(status: str) -> str:
    return {
        "RESERVED": "EXECUTION_AUTHORIZED",
        "SETTLED": "DURABLE_RESULT_REQUIRED",
        "HELD_UNKNOWN": "RECONCILIATION_REQUIRED",
        "RELEASED": "NEW_RESERVATION_GENERATION_REQUIRED",
        "REJECTED": "NEW_RESERVATION_GENERATION_REQUIRED",
    }.get(status, "RECONCILIATION_REQUIRED")


def _bind_budget_effect_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    reservation_id: str,
    reservation_version: int,
    request: BudgetReservationRequest,
    opening_binding: Mapping[str, Any],
) -> None:
    opening_run_id = str(opening_binding.get("opening_run_id") or "")
    if not opening_run_id:
        raise KernelError(
            "BOOK_OPENING_EXACT_BUDGET_BINDING_REQUIRED",
            "Opening BudgetScope reservation has no exact execution owner",
        )
    operation_budget_binding_id = str(
        opening_binding.get("operation_budget_binding_id") or ""
    )
    if not operation_budget_binding_id:
        raise KernelError(
            "BOOK_OPENING_EXACT_BUDGET_BINDING_REQUIRED",
            "Opening reservation has no exact Operation execution binding",
        )
    budget_effect_binding_id = deterministic_budget_effect_binding_id(
        external_effect_id=request.external_effect_id,
        reservation_id=reservation_id,
    )
    uow.cursor.execute(
        """
        INSERT INTO authority_book_opening_budget_effect_binding(
            budget_effect_binding_id,external_effect_id,
            operation_budget_binding_id,operation_id,opening_run_id,budget_scope_id,
            budget_scope_revision,reservation_id,reservation_version
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
        """,
        [
            budget_effect_binding_id,
            request.external_effect_id,
            operation_budget_binding_id,
            request.operation_id,
            opening_run_id,
            opening_binding["budget_scope_id"],
            opening_binding["revision"],
            reservation_id,
            reservation_version,
        ],
    )
    uow.cursor.execute(
        """
        SELECT budget_effect_binding_id,operation_budget_binding_id,
               operation_id,opening_run_id,budget_scope_id,
               budget_scope_revision,reservation_id,reservation_version
        FROM authority_book_opening_budget_effect_binding
        WHERE external_effect_id=%s AND reservation_id=%s
        """,
        [request.external_effect_id, reservation_id],
    )
    durable = uow.cursor.fetchone()
    expected = (
        budget_effect_binding_id,
        operation_budget_binding_id,
        request.operation_id,
        opening_run_id,
        str(opening_binding["budget_scope_id"]),
        int(opening_binding["revision"]),
        reservation_id,
        reservation_version,
    )
    if durable is None or tuple(durable) != expected:
        raise KernelError(
            "BOOK_OPENING_BUDGET_EFFECT_BINDING_CONFLICT",
            "ExternalEffect is already bound to another budget execution",
        )


def settle_provider_budget(
    database_url: str,
    *,
    reservation_id: str,
    project_id: str,
    actual_amount: str | None,
    actual_tokens: int,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        result = settle_provider_budget_in_uow(
            uow,
            reservation_id=reservation_id,
            project_id=project_id,
            actual_amount=actual_amount,
            actual_tokens=actual_tokens,
            evidence=evidence,
        )
        uow.commit()
    if result.pop("budget_breach", False):
        raise KernelError(
            "BUDGET_ACTUAL_EXCEEDS_RESERVATION",
            "provider actual cost or tokens exceed reservation and require reconciliation",
        )
    agent_budget_exceeded = result.pop("agent_budget_exceeded", [])
    if agent_budget_exceeded:
        raise KernelError(
            "AGENT_HARNESS_BUDGET_EXHAUSTED",
            "Agent Session aggregate budget exceeded after measured provider usage: "
            + ", ".join(agent_budget_exceeded),
        )
    return result


def settle_provider_budget_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    reservation_id: str,
    project_id: str,
    actual_amount: str | None,
    actual_tokens: int,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if actual_tokens < 0:
        raise KernelError(
            "BUDGET_SETTLEMENT_INVALID", "actual tokens cannot be negative"
        )
    identity = _reservation_lock_identity(uow, reservation_id, project_id)
    locked_scope: dict[str, Any] | None = None
    if identity["budget_scope_id"]:
        locked_scope = lock_budget_scope_in_uow(
            uow,
            budget_scope_id=str(identity["budget_scope_id"]),
            project_id=project_id,
        )
    else:
        acquire_budget_locks_in_uow(uow, currencies=(str(identity["currency"]),))
    row = _reservation(uow, reservation_id, project_id, lock=True)
    accounting_basis = str(row.get("accounting_basis") or "PRICED").upper()
    cost_observability_schema = _has_budget_cost_observability_schema(uow)
    if accounting_basis == "ACCOUNT_ENTITLEMENT" and not cost_observability_schema:
        raise KernelError(
            "BUDGET_SCHEMA_UPGRADE_REQUIRED",
            "account entitlement requires the budget cost-observability migration",
        )
    if accounting_basis == "ACCOUNT_ENTITLEMENT":
        if actual_amount is not None:
            raise KernelError(
                "BUDGET_SETTLEMENT_INVALID",
                "account entitlement settlement cannot claim a monetary amount",
            )
        amount: Decimal | None = None
        cost_status = "UNKNOWN"
    else:
        if actual_amount is None:
            raise KernelError(
                "BUDGET_SETTLEMENT_INVALID",
                "priced settlement requires a monetary amount",
            )
        amount = _amount(actual_amount)
        cost_status = "KNOWN"
    if row["status"] == "SETTLED":
        if row["settled_amount"] != amount or row["actual_tokens"] != actual_tokens:
            raise KernelError("BUDGET_SETTLEMENT_CONFLICT", "settlement replay differs")
        if locked_scope is not None:
            _link_operation_cost_evidence_in_uow(
                uow,
                row=row,
                evidence=evidence,
                locked_scope=locked_scope,
            )
        return {
            "reservation_id": reservation_id,
            "status": "SETTLED",
            "replayed": True,
            "budget_scope_id": str(row["budget_scope_id"] or ""),
            "budget_scope_revision": row["budget_scope_revision"],
            "budget_breach": False,
            "agent_budget_exceeded": [],
            "accounting_basis": accounting_basis,
            "cost_status": cost_status,
        }
    if row["status"] not in {"RESERVED", "HELD_UNKNOWN"}:
        raise KernelError("BUDGET_STATUS_CONFLICT", "reservation cannot be settled")
    monetary_breach = (
        amount is not None
        and row["reserved_amount"] is not None
        and amount > row["reserved_amount"]
    )
    token_overrun = actual_tokens > int(row["estimated_tokens"])
    settlement_evidence = dict(evidence)
    entitlement_usage_reconciled = False
    entitlement_usage_cap_error = ""
    request = _request_from_row(row)
    if (
        token_overrun
        and accounting_basis == "ACCOUNT_ENTITLEMENT"
        and settlement_evidence.get("token_accounting_precision")
        == "APPLICATION_VISIBLE_UPPER_BOUND"
        and settlement_evidence.get("actual_token_source")
        == "PROVIDER_USAGE_RECEIPT"
        and bool(request.token_caps)
    ):
        try:
            _enforce_usage_caps(
                uow.cursor,
                request,
                tokens=actual_tokens,
                call_caps={},
                token_caps=request.token_caps or {},
            )
        except KernelError as exc:
            if exc.code != "BUDGET_TOKEN_CAP_EXCEEDED":
                raise
            entitlement_usage_cap_error = exc.code
        else:
            token_overrun = False
            entitlement_usage_reconciled = True
            settlement_evidence.update(
                {
                    "application_visible_estimate_overrun": True,
                    "actual_usage_cap_revalidated": True,
                    "budget_breach": False,
                    "manual_resolution_required": False,
                    "pre_call_token_control": "APPLICATION_VISIBLE_ONLY",
                }
            )
    from novel_forge.modules.command_kernel.creative_budget_runtime import check_creative_settlement_in_uow
    try:
        check_creative_settlement_in_uow(uow, row, actual_tokens)
    except KernelError as exc:
        if exc.code != "CREATIVE_BUDGET_EXHAUSTED":
            raise
        token_overrun = True
        entitlement_usage_cap_error = exc.code
    if monetary_breach or token_overrun:
        uow.cursor.execute(
            """
            UPDATE authority_budget_reservation
            SET budget_breach=TRUE,status='HELD_UNKNOWN',actual_tokens=GREATEST(actual_tokens,%s),
                evidence=evidence || %s,version=version+1,updated_at=NOW()
            WHERE reservation_id=%s AND project_id=%s
            """,
            [
                actual_tokens,
                Jsonb(
                    {
                        **settlement_evidence,
                        "budget_breach": True,
                        "actual_amount": str(amount) if amount is not None else None,
                        "reserved_amount": (
                            str(row["reserved_amount"])
                            if row["reserved_amount"] is not None
                            else None
                        ),
                        "cost_status": cost_status,
                        "actual_tokens": actual_tokens,
                        "estimated_tokens": int(row["estimated_tokens"]),
                        "manual_resolution_required": True,
                        "token_cap_error_code": entitlement_usage_cap_error,
                    }
                ),
                reservation_id,
                project_id,
            ],
        )
        _record(
            uow,
            _request_from_row(row),
            reservation_id,
            "authority.budget.breach_detected",
            {
                "actual_amount": str(amount) if amount is not None else None,
                "reserved_amount": (
                    str(row["reserved_amount"])
                    if row["reserved_amount"] is not None
                    else None
                ),
                "cost_status": cost_status,
                "actual_tokens": actual_tokens,
                "estimated_tokens": int(row["estimated_tokens"]),
                "token_cap_error_code": entitlement_usage_cap_error,
            },
        )
        return {
            "reservation_id": reservation_id,
            "status": "HELD_UNKNOWN",
            "replayed": False,
            "budget_scope_id": str(row["budget_scope_id"] or ""),
            "budget_scope_revision": row["budget_scope_revision"],
            "budget_breach": True,
            "agent_budget_exceeded": [],
            "accounting_basis": accounting_basis,
            "cost_status": cost_status,
        }
    cost_evidence_id = f"budget-cost:{reservation_id}"
    cost_payload = {
        **settlement_evidence,
        "reservation_id": reservation_id,
        "accounting_basis": accounting_basis,
        "cost_status": cost_status,
        "entitlement_usage_reconciled": entitlement_usage_reconciled,
        "cost_authorization_ref": str(
            dict(row.get("evidence") or {}).get("cost_authorization_ref") or ""
        ),
    }
    settlement_values = [
        amount,
        actual_tokens,
        Jsonb(cost_payload),
        reservation_id,
        project_id,
    ]
    cost_evidence_values = [
        cost_evidence_id,
        row["operation_id"],
        row["provider"],
        str(evidence.get("model_id") or ""),
        amount,
        row["currency"],
        Jsonb(cost_payload),
    ]
    if cost_observability_schema:
        uow.cursor.execute(
            """
            UPDATE authority_budget_reservation
            SET status='SETTLED',settled_amount=%s,actual_tokens=%s,
                evidence=evidence || %s,settled_at=NOW(),version=version+1,
                updated_at=NOW(),settled_cost_status=%s,budget_breach=FALSE
            WHERE reservation_id=%s AND project_id=%s
            """,
            [
                amount,
                actual_tokens,
                Jsonb(cost_payload),
                cost_status,
                reservation_id,
                project_id,
            ],
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_operation_cost_evidence(
                cost_evidence_id,operation_id,provider,model,amount,currency,
                evidence,accounting_basis,cost_status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (cost_evidence_id) DO NOTHING
            """,
            [*cost_evidence_values, accounting_basis, cost_status],
        )
    else:
        uow.cursor.execute(
            """
            UPDATE authority_budget_reservation
            SET status='SETTLED',settled_amount=%s,actual_tokens=%s,
                evidence=evidence || %s,settled_at=NOW(),version=version+1,
                updated_at=NOW(),budget_breach=FALSE
            WHERE reservation_id=%s AND project_id=%s
            """,
            settlement_values,
        )
        uow.cursor.execute(
            """
            INSERT INTO authority_operation_cost_evidence(
                cost_evidence_id,operation_id,provider,model,amount,currency,
                evidence
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (cost_evidence_id) DO NOTHING
            """,
            cost_evidence_values,
        )
    if locked_scope is not None:
        _link_operation_cost_evidence_in_uow(
            uow,
            row={**row, "settled_amount": amount, "actual_tokens": actual_tokens},
            evidence=evidence,
            locked_scope=locked_scope,
            cost_payload=cost_payload,
        )
    _record(
        uow,
        _request_from_row(row),
        reservation_id,
        "authority.budget.settled",
        {
            "amount": str(amount) if amount is not None else None,
            "accounting_basis": accounting_basis,
            "cost_status": cost_status,
        },
    )
    agent_budget_exceeded = _agent_session_actual_exceeded(
        uow.cursor,
        operation_id=str(row["operation_id"]),
        project_id=project_id,
        accounting_basis=accounting_basis,
    )
    return {
        "reservation_id": reservation_id,
        "status": "SETTLED",
        "replayed": False,
        "budget_scope_id": str(row["budget_scope_id"] or ""),
        "budget_scope_revision": row["budget_scope_revision"],
        "budget_breach": False,
        "agent_budget_exceeded": agent_budget_exceeded,
        "accounting_basis": accounting_basis,
        "cost_status": cost_status,
        "entitlement_usage_reconciled": entitlement_usage_reconciled,
    }


def _link_operation_cost_evidence_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    row: Mapping[str, Any],
    evidence: Mapping[str, Any],
    locked_scope: Mapping[str, Any],
    cost_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reservation_id = str(row["reservation_id"])
    cost_evidence_id = f"budget-cost:{reservation_id}"
    accounting_basis = str(row.get("accounting_basis") or "PRICED").upper()
    cost_status = "UNKNOWN" if accounting_basis == "ACCOUNT_ENTITLEMENT" else "KNOWN"
    if cost_payload is None:
        authoritative = _read_operation_cost_authority_payload(
            uow,
            cost_evidence_id=cost_evidence_id,
            operation_id=str(row["operation_id"]),
        )
        if authoritative is None:
            raise KernelError(
                "BUDGET_EVIDENCE_AUTHORITY_MISSING",
                "operation cost evidence is missing",
            )
    else:
        authoritative = _operation_cost_authority_payload(
            cost_evidence_id=cost_evidence_id,
            operation_id=str(row["operation_id"]),
            provider=str(row["provider"]),
            model=str(evidence.get("model_id") or ""),
            amount=(
                Decimal(row["settled_amount"])
                if row["settled_amount"] is not None
                else None
            ),
            currency=str(row["currency"]),
            evidence=cost_payload,
            accounting_basis=accounting_basis,
            cost_status=cost_status,
        )
    return append_budget_evidence_link_in_uow(
        uow,
        BudgetEvidenceLinkRequest(
            budget_scope_id=str(row["budget_scope_id"]),
            budget_scope_revision=int(row["budget_scope_revision"]),
            project_id=str(row["project_id"]),
            reservation_id=reservation_id,
            evidence_kind="OPERATION_COST",
            evidence_id=cost_evidence_id,
            evidence_version=0,
            evidence_hash=_canonical_hash(authoritative),
            stable_idempotency_key=f"operation-cost:{reservation_id}",
        ),
        locked_scope=locked_scope,
    )


def resolve_provider_budget_failure(
    database_url: str,
    *,
    reservation_id: str,
    project_id: str,
    external_state_unknown: bool = False,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        result = resolve_provider_budget_failure_in_uow(
            uow,
            reservation_id=reservation_id,
            project_id=project_id,
            external_state_unknown=external_state_unknown,
        )
        uow.commit()
        return result


def resolve_provider_budget_failure_in_uow(
    uow: AuthorityUnitOfWork,
    *,
    reservation_id: str,
    project_id: str,
    external_state_unknown: bool = False,
) -> dict[str, Any]:
    identity = _reservation_lock_identity(uow, reservation_id, project_id)
    if identity["budget_scope_id"]:
        lock_budget_scope_in_uow(
            uow,
            budget_scope_id=str(identity["budget_scope_id"]),
            project_id=project_id,
        )
    else:
        acquire_budget_locks_in_uow(uow, currencies=(str(identity["currency"]),))
    row = _reservation(uow, reservation_id, project_id, lock=True)
    if row["status"] in {"RELEASED", "HELD_UNKNOWN", "SETTLED"}:
        if external_state_unknown and row["status"] == "RELEASED":
            raise KernelError(
                "BUDGET_FAILURE_RESOLUTION_CONFLICT",
                "an externally ambiguous Provider call cannot reuse a released reservation",
            )
        return {
            "reservation_id": reservation_id,
            "status": row["status"],
            "replayed": True,
            "budget_scope_id": str(row["budget_scope_id"] or ""),
            "budget_scope_revision": row["budget_scope_revision"],
        }
    uow.cursor.execute(
        "SELECT status FROM authority_external_effect WHERE external_effect_id=%s",
        [row["external_effect_id"]],
    )
    effect = uow.cursor.fetchone()
    if effect is None:
        raise KernelError(
            "BUDGET_EFFECT_NOT_FOUND",
            "budget reservation ExternalEffect is missing",
        )
    effect_status = str(effect[0])
    uow.cursor.execute(
        f"SELECT {_STARTED_CODEX_DISPATCH_SQL} FROM authority_budget_reservation WHERE reservation_id=%s AND project_id=%s",
        [reservation_id, project_id],
    )
    process_started = bool(uow.cursor.fetchone()[0])
    target = (
        "HELD_UNKNOWN"
        if external_state_unknown
        or process_started
        or effect_status
        in {
            "DISPATCHING",
            "DISPATCHED",
            "UNKNOWN",
            "RECONCILIATION_REQUIRED",
            "SUCCEEDED",
        }
        else "RELEASED"
    )
    uow.cursor.execute(
        """
        UPDATE authority_budget_reservation
        SET status=%s,updated_at=NOW(),evidence=evidence || %s,
            version=version+1
        WHERE reservation_id=%s AND project_id=%s AND status='RESERVED'
        """,
        [
            target,
            Jsonb(
                {
                    "effect_status": effect_status,
                    "external_state_unknown": external_state_unknown,
                    "started_cli_usage_unmeasured": process_started,
                }
            ),
            reservation_id,
            project_id,
        ],
    )
    request = _request_from_row(row)
    _record(
        uow,
        request,
        reservation_id,
        "authority.budget.held_unknown"
        if target == "HELD_UNKNOWN"
        else "authority.budget.released",
        {
            "effect_status": effect_status,
            "external_state_unknown": external_state_unknown,
        },
    )
    return {
        "reservation_id": reservation_id,
        "status": target,
        "replayed": False,
        "budget_scope_id": str(row["budget_scope_id"] or ""),
        "budget_scope_revision": row["budget_scope_revision"],
    }


_STARTED_CODEX_DISPATCH_SQL = """EXISTS (
    SELECT 1 FROM authority_external_effect_dispatch d
    WHERE d.external_effect_id=authority_budget_reservation.external_effect_id
      AND d.evidence #>> '{production_execution,execution_handle,transport}'='LOCAL_CLI_REMOTE_INFERENCE'
      AND NULLIF(d.evidence #>> '{production_execution,execution_result,started_at}', '') IS NOT NULL
)"""


def provider_usage_accounted_sql() -> str:
    return f"""(status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
        OR (status='RELEASED' AND (actual_tokens>0 OR {_STARTED_CODEX_DISPATCH_SQL})))"""


def unresolved_cli_outcomes(cursor: Any, project_id: str) -> list[dict[str, Any]]:
    cursor.execute(
        """SELECT e.external_effect_id,e.operation_id,e.status,
            d.evidence #>> '{production_execution,execution_result,process_receipt_ref}'
        FROM authority_budget_reservation b
        JOIN authority_external_effect e USING(external_effect_id)
        JOIN LATERAL (SELECT evidence FROM authority_external_effect_dispatch
            WHERE external_effect_id=e.external_effect_id ORDER BY generation DESC LIMIT 1) d ON true
        WHERE b.project_id=%s AND e.status<>'SUCCEEDED'
          AND d.evidence #>> '{production_execution,execution_handle,transport}'='LOCAL_CLI_REMOTE_INFERENCE'
          AND d.evidence #>> '{production_execution,execution_result,outcome}' IN ('TIMED_OUT','CANCELLED','ORPHANED')
          AND (d.evidence #>> '{production_execution,execution_result,outcome}'='ORPHANED'
            OR NULLIF(d.evidence #>> '{production_execution,execution_result,started_at}', '') IS NOT NULL)
          AND d.evidence #>> '{production_execution,execution_result,usage_receipt_ref}' IS NULL
          AND NOT EXISTS(SELECT 1 FROM authority_effect_manual_resolution m
              WHERE m.external_effect_id=e.external_effect_id AND m.project_id=b.project_id)
        ORDER BY e.created_at,e.external_effect_id LIMIT 20""",
        [project_id],
    )
    return [dict(zip(("external_effect_id", "operation_id", "effect_status", "process_receipt_ref"), row, strict=True))
        | {"state": "RECONCILIATION_REQUIRED", "usage": "UNKNOWN"} for row in cursor.fetchall()]


def provider_project_usage(cursor: Any, project_id: str) -> dict[str, Any]:
    cursor.execute(
        f"""SELECT count(DISTINCT external_effect_id),
            COALESCE(sum(CASE WHEN status='SETTLED' THEN actual_tokens
                ELSE greatest(actual_tokens,estimated_tokens) END),0),
            COALESCE(sum(actual_tokens),0),
            count(*) FILTER (WHERE status<>'SETTLED' AND actual_tokens=0),
            COALESCE(sum(greatest(actual_tokens,estimated_tokens)) FILTER
                (WHERE status<>'SETTLED' AND actual_tokens=0),0)
        FROM authority_budget_reservation
        WHERE project_id=%s AND {provider_usage_accounted_sql()}""",
        [project_id],
    )
    row = cursor.fetchone()
    return dict(zip(("calls_used_or_reserved", "conservative_tokens", "recorded_actual_tokens",
        "unmeasured_reservations", "unmeasured_reserved_tokens"), map(int, row), strict=True))


_USAGE_CAP_DIMENSIONS = frozenset(
    {
        "operation_total",
        "chapter_total",
        "project_daily",
        "project_total",
        "provider_project_daily",
        "provider_project_total",
        "global_daily",
        "global_total", "global_monthly", "project_monthly", "work_total", "model_project_total",
    }
)


def _canonical_usage_caps(
    values: Mapping[str, int] | None, *, kind: str
) -> dict[str, int]:
    caps: dict[str, int] = {}
    for dimension, raw_value in (values or {}).items():
        if dimension not in _USAGE_CAP_DIMENSIONS:
            raise KernelError(
                "BUDGET_CAP_INVALID", f"unsupported {kind} budget cap: {dimension}"
            )
        if isinstance(raw_value, bool):
            raise KernelError(
                "BUDGET_CAP_INVALID", f"{kind} budget cap must be a positive integer"
            )
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise KernelError(
                "BUDGET_CAP_INVALID", f"{kind} budget cap must be a positive integer"
            ) from exc
        if value <= 0 or value != raw_value:
            raise KernelError(
                "BUDGET_CAP_INVALID", f"{kind} budget cap must be a positive integer"
            )
        caps[str(dimension)] = value
    return caps


def _extended_budget_dimensions(request: BudgetReservationRequest) -> dict[str, tuple[str, list[Any]]]:
    return {
        "global_total": ("currency=%s", [request.currency]),
        "global_monthly": (
            "currency=%s AND date_trunc('month',created_at AT TIME ZONE %s) = date_trunc('month',NOW() AT TIME ZONE %s)",
            [request.currency, request.budget_timezone, request.budget_timezone]),
        "project_monthly": (
            "project_id=%s AND date_trunc('month',created_at AT TIME ZONE %s) = date_trunc('month',NOW() AT TIME ZONE %s)",
            [request.project_id, request.budget_timezone, request.budget_timezone]),
        "work_total": (
            "project_id=%s AND external_effect_id IN (SELECT external_effect_id FROM authority_external_effect WHERE project_id=%s AND request_payload #>> '{_production_execution,book_id}'=%s)",
            [request.project_id, request.project_id, request.work_id]),
        "model_project_total": (
            "project_id=%s AND provider=%s AND external_effect_id IN (SELECT external_effect_id FROM authority_external_effect WHERE project_id=%s AND model_id=%s)",
            [request.project_id, request.provider, request.project_id, request.model_id]),
    }


def _usage_cap_dimension(
    request: BudgetReservationRequest, dimension: str
) -> tuple[str, list[Any]]:
    if (dimension == "work_total" and not request.work_id) or (dimension == "model_project_total" and not request.model_id):
        raise KernelError("BUDGET_SCOPE_IDENTITY_REQUIRED", dimension)
    dimensions: dict[str, tuple[str, list[Any]]] = {
        **_extended_budget_dimensions(request),
        "operation_total": ("operation_id = %s", [request.operation_id]),
        "chapter_total": (
            "project_id = %s AND chapter = %s",
            [request.project_id, request.chapter],
        ),
        "project_daily": (
            "project_id = %s AND (created_at AT TIME ZONE %s)::date = "
            "(NOW() AT TIME ZONE %s)::date",
            [request.project_id, request.budget_timezone, request.budget_timezone],
        ),
        "project_total": ("project_id = %s", [request.project_id]),
        "provider_project_daily": (
            "project_id = %s AND provider = %s AND "
            "(created_at AT TIME ZONE %s)::date = "
            "(NOW() AT TIME ZONE %s)::date",
            [
                request.project_id,
                request.provider,
                request.budget_timezone,
                request.budget_timezone,
            ],
        ),
        "provider_project_total": (
            "project_id = %s AND provider = %s",
            [request.project_id, request.provider],
        ),
        "global_daily": (
            "currency = %s AND (created_at AT TIME ZONE %s)::date = "
            "(NOW() AT TIME ZONE %s)::date",
            [request.currency, request.budget_timezone, request.budget_timezone],
        ),
    }
    if dimension == "chapter_total" and request.chapter is None:
        raise KernelError(
            "BUDGET_CAP_INVALID", "chapter_total budget cap requires a chapter"
        )
    return dimensions[dimension]


def _enforce_usage_caps(
    cursor: Any,
    request: BudgetReservationRequest,
    *,
    tokens: int,
    call_caps: Mapping[str, int],
    token_caps: Mapping[str, int],
) -> None:
    for kind, caps in (("call", call_caps), ("token", token_caps)):
        for dimension, cap in caps.items():
            where, params = _usage_cap_dimension(request, dimension)
            aggregate = (
                "COUNT(DISTINCT external_effect_id)"
                if kind == "call"
                else "COALESCE(SUM(CASE WHEN status='SETTLED' THEN actual_tokens "
                "ELSE GREATEST(actual_tokens,estimated_tokens) END),0)"
            )
            cursor.execute(
                f"""
                SELECT {aggregate}
                FROM authority_budget_reservation
                WHERE {where} AND stable_idempotency_key <> %s
                  AND {provider_usage_accounted_sql()}
                """,
                [*params, request.stable_idempotency_key],
            )
            committed = int(cursor.fetchone()[0])
            requested = 1 if kind == "call" else tokens
            if committed + requested > cap:
                raise KernelError(
                    f"BUDGET_{kind.upper()}_CAP_EXCEEDED",
                    f"{dimension} {kind} budget cap would be exceeded",
                )


def _enforce_caps(
    cursor: Any,
    request: BudgetReservationRequest,
    amount: Decimal,
    caps: dict[str, Decimal],
) -> None:
    try:
        cursor.execute("SELECT NOW() AT TIME ZONE %s", [request.budget_timezone])
        cursor.fetchone()
    except Exception as exc:
        raise KernelError(
            "BUDGET_TIMEZONE_INVALID", "budget timezone is invalid"
        ) from exc
    dimensions = {
        **_extended_budget_dimensions(request),
        "operation_total": ("operation_id = %s", [request.operation_id]),
        "chapter_total": (
            "project_id = %s AND chapter = %s",
            [request.project_id, request.chapter],
        ),
        "project_daily": (
            "project_id = %s AND (created_at AT TIME ZONE %s)::date = (NOW() AT TIME ZONE %s)::date",
            [request.project_id, request.budget_timezone, request.budget_timezone],
        ),
        "project_total": ("project_id = %s", [request.project_id]),
        "provider_project_daily": (
            "project_id = %s AND provider = %s AND (created_at AT TIME ZONE %s)::date = (NOW() AT TIME ZONE %s)::date",
            [
                request.project_id,
                request.provider,
                request.budget_timezone,
                request.budget_timezone,
            ],
        ),
        "provider_project_total": (
            "project_id = %s AND provider = %s",
            [request.project_id, request.provider],
        ),
        "global_daily": (
            "currency = %s AND (created_at AT TIME ZONE %s)::date = (NOW() AT TIME ZONE %s)::date",
            [request.currency, request.budget_timezone, request.budget_timezone],
        ),
    }
    for dimension, cap in caps.items():
        if (dimension == "work_total" and not request.work_id) or (dimension == "model_project_total" and not request.model_id):
            raise KernelError("BUDGET_SCOPE_IDENTITY_REQUIRED", dimension)
        if dimension not in dimensions or (
            dimension == "chapter_total" and request.chapter is None
        ):
            raise KernelError(
                "BUDGET_CAP_INVALID", f"unsupported budget cap: {dimension}"
            )
        where, params = dimensions[dimension]
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(
                CASE WHEN status = 'SETTLED' THEN settled_amount ELSE reserved_amount END
            ), 0)
            FROM authority_budget_reservation
            WHERE {where} AND stable_idempotency_key <> %s
              AND status IN ('RESERVED', 'HELD_UNKNOWN', 'SETTLED')
            """,
            [*params, request.stable_idempotency_key],
        )
        committed = Decimal(cursor.fetchone()[0])
        if committed + amount > cap:
            raise KernelError(
                "BUDGET_CAP_EXCEEDED",
                f"{dimension} budget cap would be exceeded",
            )


def _enforce_agent_session_aggregate(
    cursor: Any,
    request: BudgetReservationRequest,
    *,
    amount: Decimal | None,
    tokens: int,
) -> None:
    """INVARIANT: Charge a provider effect to any causal Agent Session ancestor.

    Reservations and receipts remain the only ledger.  The Session budget is a
    locked aggregate gate over that existing evidence, including Typed
    Capability child Operations.
    """
    cursor.execute(
        """
        WITH RECURSIVE lineage AS (
          SELECT operation_id, parent_operation_id, causation_operation_id, 0 AS depth
          FROM authority_operation
          WHERE operation_id=%s AND project_id=%s
          UNION
          SELECT parent.operation_id, parent.parent_operation_id,
                 parent.causation_operation_id, child.depth + 1
          FROM authority_operation AS parent
          JOIN lineage AS child
            ON parent.operation_id=child.parent_operation_id
            OR parent.operation_id=child.causation_operation_id
          WHERE parent.project_id=%s
        )
        SELECT session.agent_session_id, session.operation_id, session.budget
        FROM lineage
        JOIN authority_agent_harness_session AS session
          ON session.operation_id=lineage.operation_id
        ORDER BY lineage.depth
        LIMIT 1
        FOR UPDATE OF session
        """,
        [request.operation_id, request.project_id, request.project_id],
    )
    owner = cursor.fetchone()
    if owner is None:
        return
    session_id, session_operation_id, raw_budget = owner
    budget = dict(raw_budget or {})
    cursor.execute(
        """
        WITH RECURSIVE descendants AS (
          SELECT operation_id
          FROM authority_operation
          WHERE operation_id=%s AND project_id=%s
          UNION
          SELECT child.operation_id
          FROM authority_operation AS child
          JOIN descendants AS parent
            ON child.parent_operation_id=parent.operation_id
            OR child.causation_operation_id=parent.operation_id
          WHERE child.project_id=%s
        )
        SELECT COALESCE(SUM(
                 CASE WHEN reservation.status='SETTLED'
                      THEN reservation.settled_amount
                      ELSE reservation.reserved_amount END
               ), 0),
               COALESCE(SUM(
                 CASE WHEN reservation.status='SETTLED'
                      THEN reservation.actual_tokens
                      ELSE reservation.estimated_tokens END
               ), 0),
               COUNT(DISTINCT reservation.external_effect_id)
        FROM authority_budget_reservation AS reservation
        WHERE reservation.operation_id IN (SELECT operation_id FROM descendants)
          AND reservation.project_id=%s
          AND reservation.stable_idempotency_key<>%s
          AND reservation.status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
        """,
        [
            session_operation_id,
            request.project_id,
            request.project_id,
            request.project_id,
            request.stable_idempotency_key,
        ],
    )
    spent_amount, spent_tokens, effect_count = cursor.fetchone()
    exceeded = []
    if amount is not None and Decimal(spent_amount) + amount > _amount(
        str(budget.get("max_cost_amount") or "0")
    ):
        exceeded.append("cost")
    if int(spent_tokens) + tokens > int(budget.get("max_input_tokens") or 0) + int(
        budget.get("max_output_tokens") or 0
    ):
        exceeded.append("tokens")
    if int(effect_count) + 1 > int(budget.get("max_external_effects") or 0):
        exceeded.append("external_effects")
    if exceeded:
        raise KernelError(
            "AGENT_HARNESS_BUDGET_EXHAUSTED",
            f"Agent Session {session_id} aggregate budget exceeded: "
            + ", ".join(exceeded),
        )


def _agent_session_actual_exceeded(
    cursor: Any,
    *,
    operation_id: str,
    project_id: str,
    accounting_basis: str = "PRICED",
) -> list[str]:
    cursor.execute(
        """
        WITH RECURSIVE lineage AS (
          SELECT operation_id, parent_operation_id, causation_operation_id, 0 AS depth
          FROM authority_operation
          WHERE operation_id=%s AND project_id=%s
          UNION
          SELECT parent.operation_id, parent.parent_operation_id,
                 parent.causation_operation_id, child.depth + 1
          FROM authority_operation AS parent
          JOIN lineage AS child
            ON parent.operation_id=child.parent_operation_id
            OR parent.operation_id=child.causation_operation_id
          WHERE parent.project_id=%s
        )
        SELECT session.operation_id, session.budget
        FROM lineage
        JOIN authority_agent_harness_session AS session
          ON session.operation_id=lineage.operation_id
        ORDER BY lineage.depth LIMIT 1
        """,
        [operation_id, project_id, project_id],
    )
    owner = cursor.fetchone()
    if owner is None:
        return []
    session_operation_id, raw_budget = owner
    budget = dict(raw_budget or {})
    cursor.execute(
        """
        WITH RECURSIVE descendants AS (
          SELECT operation_id FROM authority_operation
          WHERE operation_id=%s AND project_id=%s
          UNION
          SELECT child.operation_id
          FROM authority_operation AS child
          JOIN descendants AS parent
            ON child.parent_operation_id=parent.operation_id
            OR child.causation_operation_id=parent.operation_id
          WHERE child.project_id=%s
        )
        SELECT COALESCE(SUM(
                 CASE WHEN status='SETTLED' THEN settled_amount ELSE reserved_amount END
               ), 0),
               COALESCE(SUM(
                 CASE WHEN status='SETTLED' THEN actual_tokens ELSE estimated_tokens END
               ), 0),
               COUNT(DISTINCT external_effect_id)
        FROM authority_budget_reservation
        WHERE operation_id IN (SELECT operation_id FROM descendants)
          AND project_id=%s
          AND status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
        """,
        [session_operation_id, project_id, project_id, project_id],
    )
    amount, tokens, effects = cursor.fetchone()
    exceeded = []
    if accounting_basis != "ACCOUNT_ENTITLEMENT" and Decimal(amount) > _amount(
        str(budget.get("max_cost_amount") or "0")
    ):
        exceeded.append("cost")
    if int(tokens) > int(budget.get("max_input_tokens") or 0) + int(
        budget.get("max_output_tokens") or 0
    ):
        exceeded.append("tokens")
    if int(effects) > int(budget.get("max_external_effects") or 0):
        exceeded.append("external_effects")
    return exceeded


def _reservation(
    uow: AuthorityUnitOfWork, reservation_id: str, project_id: str, *, lock: bool
) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    uow.cursor.execute(
        f"""
        SELECT reservation.reservation_id,reservation.operation_id,
               reservation.external_effect_id,reservation.project_id,
               reservation.stable_idempotency_key,reservation.provider,
               reservation.chapter,reservation.currency,
               reservation.estimated_amount,reservation.reserved_amount,
               reservation.settled_amount,reservation.estimated_tokens,
               reservation.actual_tokens,reservation.status,reservation.caps,
               reservation.evidence,reservation.budget_timezone,
               reservation.budget_breach,reservation.budget_scope_id,
               reservation.budget_scope_revision,reservation.version,
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'accounting_basis',''),
                   'PRICED'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'estimated_cost_status',''),
                   'KNOWN'
               ),
               COALESCE(
                   NULLIF(to_jsonb(reservation)->>'settled_cost_status',''),
                   CASE WHEN reservation.status='SETTLED' THEN 'KNOWN'
                        ELSE 'PENDING' END
               )
        FROM authority_budget_reservation AS reservation
        WHERE reservation_id = %s AND project_id = %s{suffix}
        """,
        [reservation_id, project_id],
    )
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "BUDGET_RESERVATION_NOT_FOUND", "budget reservation is missing"
        )
    return dict(
        zip(
            (
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
                "budget_breach",
                "budget_scope_id",
                "budget_scope_revision",
                "version",
                "accounting_basis",
                "estimated_cost_status",
                "settled_cost_status",
            ),
            row,
            strict=True,
        )
    )


def _reservation_lock_identity(
    uow: AuthorityUnitOfWork, reservation_id: str, project_id: str
) -> dict[str, Any]:
    """INVARIANT: Pre-read immutable lock keys; callers must revalidate after locking."""
    uow.cursor.execute(
        """
        SELECT currency,budget_scope_id
        FROM authority_budget_reservation
        WHERE reservation_id=%s AND project_id=%s
        """,
        [reservation_id, project_id],
    )
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError(
            "BUDGET_RESERVATION_NOT_FOUND", "budget reservation is missing"
        )
    return {"currency": str(row[0]), "budget_scope_id": row[1]}


def _request_from_row(row: dict[str, Any]) -> BudgetReservationRequest:
    return BudgetReservationRequest(
        operation_id=str(row["operation_id"]),
        external_effect_id=str(row["external_effect_id"]),
        project_id=str(row["project_id"]),
        stable_idempotency_key=str(row["stable_idempotency_key"]),
        provider=str(row["provider"]),
        currency=str(row["currency"]),
        estimated_amount=(
            str(row["estimated_amount"])
            if row["estimated_amount"] is not None
            else None
        ),
        estimated_tokens=int(row["estimated_tokens"]),
        chapter=row["chapter"],
        caps=dict(row["caps"] or {}),
        budget_timezone=str(row.get("budget_timezone") or "UTC"),
        budget_scope_id=str(row.get("budget_scope_id") or ""),
        expected_budget_scope_revision=(
            int(row["budget_scope_revision"])
            if row.get("budget_scope_revision") is not None
            else None
        ),
        accounting_basis=str(row.get("accounting_basis") or "PRICED"),
        cost_authorization_ref=str(
            dict(row.get("evidence") or {}).get("cost_authorization_ref") or ""
        ),
        call_caps={
            str(key): int(value)
            for key, value in dict(row.get("evidence") or {})
            .get("call_caps", {})
            .items()
        },
        token_caps={
            str(key): int(value)
            for key, value in dict(row.get("evidence") or {})
            .get("token_caps", {})
            .items()
        },
    )


def _record(
    uow: AuthorityUnitOfWork,
    request: BudgetReservationRequest,
    reservation_id: str,
    topic: str,
    payload: dict[str, Any],
) -> None:
    event_id = str(uuid4())
    body = {"reservation_id": reservation_id, **payload}
    uow.cursor.execute(
        """
        SELECT COALESCE(MAX(sequence_number), 0) + 1
        FROM state_event
        WHERE aggregate_type = 'authority_budget_reservation' AND aggregate_id = %s
        """,
        [reservation_id],
    )
    sequence = int(uow.cursor.fetchone()[0])
    uow.cursor.execute(
        """
        INSERT INTO state_event (
            event_id, project_id, aggregate_type, aggregate_id,
            event_type, event_version, sequence_number, payload,
            correlation_id, causation_id
        ) VALUES (%s, %s, 'authority_budget_reservation', %s, %s, 1, %s, %s, '', %s)
        """,
        [
            event_id,
            request.project_id,
            reservation_id,
            topic,
            sequence,
            Jsonb(body),
            request.operation_id,
        ],
    )
    uow.cursor.execute(
        "INSERT INTO audit_log (audit_id, project_id, operation_id, action, payload) VALUES (%s, %s, %s, %s, %s)",
        [str(uuid4()), request.project_id, request.operation_id, topic, Jsonb(body)],
    )
    uow.cursor.execute(
        "INSERT INTO outbox_event (outbox_id, event_id, project_id, topic, status, payload) VALUES (%s, %s, %s, %s, 'pending', %s)",
        [str(uuid4()), event_id, request.project_id, topic, Jsonb(body)],
    )


def _amount(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise KernelError(
            "BUDGET_AMOUNT_INVALID", "budget amount must be decimal"
        ) from exc
    if not result.is_finite():
        raise KernelError(
            "BUDGET_AMOUNT_INVALID", "budget amount must be a finite decimal"
        )
    if result < 0:
        raise KernelError("BUDGET_AMOUNT_INVALID", "budget amount cannot be negative")
    return result


__all__ = [
    "BudgetAssessmentOutcome",
    "BudgetEvidenceLinkRequest",
    "BudgetReservationRequest",
    "BudgetScopeRequest",
    "acquire_budget_locks_in_uow",
    "append_budget_evidence_link",
    "append_budget_evidence_link_in_uow",
    "assert_provider_execution_authorized",
    "assess_budget_scope_in_uow",
    "canonical_budget_policy",
    "canonical_budget_snapshot",
    "create_or_get_budget_scope",
    "create_or_get_budget_scope_in_uow",
    "deterministic_budget_evidence_link_id",
    "deterministic_budget_scope_id",
    "lock_budget_scope_in_uow",
    "next_provider_budget_allowance",
    "reserve_provider_budget",
    "reserve_provider_budget_in_uow",
    "resolve_book_opening_budget_scope_in_uow",
    "resolve_provider_budget_failure",
    "resolve_provider_budget_failure_in_uow",
    "revalidate_book_opening_budget_scope_in_uow",
    "settle_provider_budget",
    "settle_provider_budget_in_uow",
]
