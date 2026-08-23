"""Project-scoped provider budget reservation and cost settlement."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True, slots=True)
class BudgetReservationRequest:
    operation_id: str
    external_effect_id: str
    project_id: str
    stable_idempotency_key: str
    provider: str
    currency: str
    estimated_amount: str
    estimated_tokens: int
    chapter: int | None = None
    caps: dict[str, str] | None = None
    budget_timezone: str = "UTC"


def reserve_provider_budget(
    database_url: str,
    request: BudgetReservationRequest,
) -> dict[str, Any]:
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
    caps = {key: _amount(value) for key, value in (request.caps or {}).items()}
    with AuthorityUnitOfWork(database_url) as uow:
        # A currency-scoped transaction lock serializes cap decisions, including
        # global_daily across different projects. It is released on commit/rollback.
        uow.cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"authority-provider-budget:{request.currency.upper()}"],
        )
        uow.cursor.execute(
            """
            SELECT operation.project_id, effect.project_id
            FROM authority_operation AS operation
            JOIN authority_external_effect AS effect
              ON effect.external_effect_id = %s AND effect.operation_id = operation.operation_id
            WHERE operation.operation_id = %s
            FOR UPDATE OF operation, effect
            """,
            [request.external_effect_id, request.operation_id],
        )
        scope = uow.cursor.fetchone()
        if scope is None or scope != (request.project_id, request.project_id):
            raise KernelError(
                "BUDGET_SCOPE_CONFLICT", "budget effect is outside project scope"
            )
        _enforce_agent_session_aggregate(
            uow.cursor,
            request,
            amount=amount,
            tokens=request.estimated_tokens,
        )
        _enforce_caps(uow.cursor, request, amount, caps)
        reservation_id = str(uuid4())
        uow.cursor.execute(
            """
            INSERT INTO authority_budget_reservation (
                reservation_id, operation_id, external_effect_id, project_id,
                stable_idempotency_key, provider, chapter, currency,
                estimated_amount, reserved_amount, estimated_tokens, status, caps, evidence
                , budget_timezone
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, 'RESERVED', %s, %s, %s
            )
            ON CONFLICT (project_id, stable_idempotency_key) DO NOTHING
            RETURNING reservation_id
            """,
            [
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
                request.estimated_tokens,
                Jsonb({key: str(value) for key, value in caps.items()}),
                Jsonb({"phase": "pre_dispatch", "fixture": amount == 0}),
                request.budget_timezone,
            ],
        )
        inserted = uow.cursor.fetchone()
        replayed = inserted is None
        if replayed:
            uow.cursor.execute(
                """
                SELECT reservation_id, operation_id, external_effect_id, provider,
                       currency, estimated_amount, estimated_tokens, status
                FROM authority_budget_reservation
                WHERE project_id = %s AND stable_idempotency_key = %s
                """,
                [request.project_id, request.stable_idempotency_key],
            )
            existing = uow.cursor.fetchone()
            expected = (
                request.operation_id,
                request.external_effect_id,
                request.provider,
                request.currency,
                amount,
                request.estimated_tokens,
            )
            if existing is None or tuple(existing[1:7]) != expected:
                raise KernelError(
                    "BUDGET_IDEMPOTENCY_CONFLICT",
                    "budget stable key belongs to another request",
                )
            reservation_id = str(existing[0])
        else:
            _record(
                uow,
                request,
                reservation_id,
                "authority.budget.reserved",
                {"amount": str(amount)},
            )
        uow.commit()
    return {
        "reservation_id": reservation_id,
        "status": "RESERVED",
        "replayed": replayed,
    }


def settle_provider_budget(
    database_url: str,
    *,
    reservation_id: str,
    project_id: str,
    actual_amount: str,
    actual_tokens: int,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    amount = _amount(actual_amount)
    if actual_tokens < 0:
        raise KernelError(
            "BUDGET_SETTLEMENT_INVALID", "actual tokens cannot be negative"
        )
    breached = False
    agent_budget_exceeded: list[str] = []
    with AuthorityUnitOfWork(database_url) as uow:
        row = _reservation(uow, reservation_id, project_id, lock=True)
        if row["status"] == "SETTLED":
            if row["settled_amount"] != amount or row["actual_tokens"] != actual_tokens:
                raise KernelError(
                    "BUDGET_SETTLEMENT_CONFLICT", "settlement replay differs"
                )
            return {
                "reservation_id": reservation_id,
                "status": "SETTLED",
                "replayed": True,
            }
        if row["status"] not in {"RESERVED", "HELD_UNKNOWN"}:
            raise KernelError("BUDGET_STATUS_CONFLICT", "reservation cannot be settled")
        if amount > row["reserved_amount"]:
            breached = True
            uow.cursor.execute(
                """
                UPDATE authority_budget_reservation
                SET budget_breach = TRUE, status = 'HELD_UNKNOWN',
                    evidence = evidence || %s, updated_at = NOW()
                WHERE reservation_id = %s AND project_id = %s
                """,
                [
                    Jsonb(
                        {
                            **evidence,
                            "budget_breach": True,
                            "actual_amount": str(amount),
                            "reserved_amount": str(row["reserved_amount"]),
                            "manual_resolution_required": True,
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
                    "actual_amount": str(amount),
                    "reserved_amount": str(row["reserved_amount"]),
                },
            )
            uow.commit()
        else:
            uow.cursor.execute(
                """
            UPDATE authority_budget_reservation
            SET status = 'SETTLED', settled_amount = %s, actual_tokens = %s,
                evidence = evidence || %s, settled_at = NOW(), updated_at = NOW()
            WHERE reservation_id = %s AND project_id = %s
            """,
                [amount, actual_tokens, Jsonb(evidence), reservation_id, project_id],
            )
            uow.cursor.execute(
                """
                INSERT INTO authority_operation_cost_evidence (
                    cost_evidence_id, operation_id, provider, model,
                    amount, currency, evidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (cost_evidence_id) DO NOTHING
                """,
                [
                    f"budget-cost:{reservation_id}",
                    row["operation_id"],
                    row["provider"],
                    str(evidence.get("model_id") or ""),
                    amount,
                    row["currency"],
                    Jsonb({**evidence, "reservation_id": reservation_id}),
                ],
            )
            request = _request_from_row(row)
            _record(
                uow,
                request,
                reservation_id,
                "authority.budget.settled",
                {"amount": str(amount)},
            )
            agent_budget_exceeded = _agent_session_actual_exceeded(
                uow.cursor,
                operation_id=str(row["operation_id"]),
                project_id=project_id,
            )
            uow.commit()
    if breached:
        raise KernelError(
            "BUDGET_ACTUAL_EXCEEDS_RESERVATION",
            "provider actual cost exceeds reservation and requires manual resolution",
        )
    if agent_budget_exceeded:
        raise KernelError(
            "AGENT_HARNESS_BUDGET_EXHAUSTED",
            "Agent Session aggregate budget exceeded after measured provider usage: "
            + ", ".join(agent_budget_exceeded),
        )
    return {"reservation_id": reservation_id, "status": "SETTLED", "replayed": False}


def resolve_provider_budget_failure(
    database_url: str,
    *,
    reservation_id: str,
    project_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        row = _reservation(uow, reservation_id, project_id, lock=True)
        if row["status"] in {"RELEASED", "HELD_UNKNOWN", "SETTLED"}:
            return {
                "reservation_id": reservation_id,
                "status": row["status"],
                "replayed": True,
            }
        uow.cursor.execute(
            "SELECT status FROM authority_external_effect WHERE external_effect_id = %s",
            [row["external_effect_id"]],
        )
        effect_status = str(uow.cursor.fetchone()[0])
        target = (
            "HELD_UNKNOWN"
            if effect_status in {"UNKNOWN", "RECONCILIATION_REQUIRED"}
            else "RELEASED"
        )
        uow.cursor.execute(
            """
            UPDATE authority_budget_reservation
            SET status = %s, updated_at = NOW(),
                evidence = evidence || %s
            WHERE reservation_id = %s AND project_id = %s AND status = 'RESERVED'
            """,
            [
                target,
                Jsonb({"effect_status": effect_status}),
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
            {"effect_status": effect_status},
        )
        uow.commit()
    return {"reservation_id": reservation_id, "status": target, "replayed": False}


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
    amount: Decimal,
    tokens: int,
) -> None:
    """Charge a provider effect to any causal Agent Session ancestor.

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
    if Decimal(spent_amount) + amount > _amount(
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
    cursor: Any, *, operation_id: str, project_id: str
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
    if Decimal(amount) > _amount(str(budget.get("max_cost_amount") or "0")):
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
        SELECT reservation_id, operation_id, external_effect_id, project_id,
               stable_idempotency_key, provider, chapter, currency,
               estimated_amount, reserved_amount, settled_amount,
               estimated_tokens, actual_tokens, status, caps, evidence
               , budget_timezone, budget_breach
        FROM authority_budget_reservation
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
            ),
            row,
            strict=True,
        )
    )


def _request_from_row(row: dict[str, Any]) -> BudgetReservationRequest:
    return BudgetReservationRequest(
        operation_id=str(row["operation_id"]),
        external_effect_id=str(row["external_effect_id"]),
        project_id=str(row["project_id"]),
        stable_idempotency_key=str(row["stable_idempotency_key"]),
        provider=str(row["provider"]),
        currency=str(row["currency"]),
        estimated_amount=str(row["estimated_amount"]),
        estimated_tokens=int(row["estimated_tokens"]),
        chapter=row["chapter"],
        caps=dict(row["caps"] or {}),
        budget_timezone=str(row.get("budget_timezone") or "UTC"),
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
    if result < 0:
        raise KernelError("BUDGET_AMOUNT_INVALID", "budget amount cannot be negative")
    return result


__all__ = [
    "BudgetReservationRequest",
    "reserve_provider_budget",
    "resolve_provider_budget_failure",
    "settle_provider_budget",
]
