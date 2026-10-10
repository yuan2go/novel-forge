from __future__ import annotations

from uuid import uuid4

from .errors import KernelError


CONTRACT = "isolated-api-receipt.v1"


def _invalid(message):
    raise KernelError("ISOLATED_API_RECEIPT_INVALID", message)


def resolution(cursor, effect_id, dispatch_id=None):
    cursor.execute(
        """SELECT evidence FROM authority_effect_reconciliation_evidence
        WHERE external_effect_id=%s AND evidence->>'contract_version'=%s
          AND (%s::text IS NULL OR evidence->>'dispatch_id'=%s)
        ORDER BY reconciled_at DESC,reconciliation_id DESC LIMIT 1""",
        [effect_id, CONTRACT, dispatch_id, dispatch_id],
    )
    row = cursor.fetchone()
    return row[0] if row else None


def original_dispatch(uow, effect, dispatch_id=None):
    from .external_effect_runtime import _hash
    from .generation_isolation import isolation

    proof = isolation(uow.cursor, effect["external_effect_id"])
    if (
        not proof
        or not proof.get("dispatch_ids")
        or proof.get("business_commit_right") != "REVOKED"
        or proof.get("activation_right") != "REVOKED"
    ):
        _invalid("Require immutable native isolation with revoked business rights")
    uow.cursor.execute(
        """SELECT to_jsonb(d) FROM authority_external_effect_dispatch d
        WHERE external_effect_id=%s AND (%s::text IS NULL OR dispatch_id=%s) ORDER BY generation FOR UPDATE""",
        [effect["external_effect_id"], dispatch_id, dispatch_id],
    )
    rows = [row[0] for row in uow.cursor.fetchall()]
    if len(rows) != 1:
        _invalid("Bind exactly one original dispatch generation")
    dispatch = rows[0]
    production = dispatch["evidence"].get("production_execution") or {}
    if (
        effect["effect_type"] != "model.invoke"
        or dispatch["dispatch_id"] not in proof["dispatch_ids"]
        or dispatch["payload_hash"] != effect["request_hash"]
        or _hash(effect["request_payload"]) != effect["request_hash"]
        or (production.get("execution_handle") or {}).get("transport")
        != "REMOTE_PROVIDER_API"
    ):
        _invalid("Require the isolated original API request and dispatch hash")
    request = production.get("execution_request") or {}
    original = proof["local_execution"]
    if (
        request.get("project_id") != effect["project_id"]
        or request.get("operation_id") != effect["operation_id"]
        or request.get("external_effect_id") != effect["external_effect_id"]
        or request.get("book_id") != proof["book_id"]
        or (dispatch["dispatch_id"] == proof["dispatch_ids"][-1] and any(
            request.get(key) != original.get(key)
            for key in ("execution_id", "attempt_id", "fencing_token")
        ))
    ):
        _invalid(
            "Original execution, Attempt, fence and Book must match the isolation proof"
        )
    uow.cursor.execute(
        """SELECT EXISTS(SELECT 1 FROM authority_effect_dispatch_lease l JOIN authority_external_effect_dispatch d USING(dispatch_id) WHERE d.external_effect_id=%s AND l.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
        WHERE a.operation_id=%s AND l.status='HELD')""",
        [effect["external_effect_id"], effect["operation_id"]],
    )
    if uow.cursor.fetchone()[0]:
        _invalid("Original writers must be stopped and their leases released")
    return dispatch, proof


def append_operator_resolution(uow, effect, command):
    from .cli_effect_reconciliation import _asset
    from .external_effect_runtime import _hash

    receipt = _asset(
        uow.cursor,
        effect["project_id"],
        command.evidence.get("original_remote_receipt_ref"),
        kind="execution_evidence",
    )
    if (
        receipt.get("contract_version") != "api-original-receipt.v1"
        or receipt.get("verification_basis") != "AUTHORIZED_OPERATOR_ATTESTATION"
        or receipt.get("verified_by") != command.actor_id
    ):
        _invalid("Require the authorized operator's preserved original API record")
    _require_api_schema(
        uow,
        command.evidence.get("original_remote_receipt_ref"),
        "api-original-receipt.v1",
    )
    source = _asset(
        uow.cursor,
        effect["project_id"],
        receipt.get("source_ref"),
        kind="execution_evidence",
    )
    _require_api_schema(uow, receipt.get("source_ref"), "api-provider-record.v1")
    observed = {
        key: value
        for key, value in receipt.items()
        if key
        not in {"contract_version", "verification_basis", "verified_by", "source_ref"}
    }
    if source != {"contract_version": "api-provider-record.v1", **observed}:
        _invalid("Attestation differs from the immutable original Provider record")
    dispatch, proof = original_dispatch(uow, effect, receipt.get("dispatch_id"))
    production = dispatch["evidence"]["production_execution"]
    request = production["execution_request"]
    expected = {
        "project_id": effect["project_id"],
        "operation_id": effect["operation_id"],
        "external_effect_id": effect["external_effect_id"],
        "book_id": proof["book_id"],
        "dispatch_id": dispatch["dispatch_id"],
        "generation": dispatch["generation"],
        "request_hash": effect["request_hash"],
        **{
            key: request[key] for key in ("execution_id", "attempt_id", "fencing_token")
        },
        "execution_request_hash": _hash(request),
        "input_manifest_hash": _hash(production["input_manifest"]),
        "provider_id": production["route_snapshot"]["model_provider"],
        "model_id": production["route_snapshot"]["model_id"],
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        _invalid("Receipt differs from the original frozen call identity or inputs")
    request_id = production["execution_handle"].get("provider_request_id")
    if dispatch["dispatch_id"] == proof["dispatch_ids"][-1]:
        request_id = request_id or effect.get("provider_request_id")
    if not receipt.get("provider_request_id") or (
        request_id and receipt["provider_request_id"] != request_id
    ):
        _invalid("Original remote request identity differs")
    expected_outcome = {
        "MARK_SUCCEEDED": "success",
        "MARK_NOT_FOUND": "not_found",
        "MARK_FAILED_FINAL": "final_failure",
        "MARK_CANCELLED": "cancelled",
    }
    if expected_outcome.get(command.decision) != receipt.get("outcome"):
        _invalid("Decision differs from the verified original terminal outcome")
    return append_receipt(
        uow,
        effect,
        dispatch,
        receipt=observed,
        verification={
            "basis": "AUTHORIZED_OPERATOR_ATTESTATION",
            "receipt_ref": command.evidence["original_remote_receipt_ref"],
            "actor_id": command.actor_id,
        },
        trace_id=command.trace_id,
        correlation_id=command.correlation_id,
    )


def append_callback_receipt(
    uow,
    effect,
    context,
    *,
    dispatch_id,
    generation,
    provider_request_id,
    message_id,
    payload_hash,
    outcome,
    evidence,
):
    dispatch, proof = original_dispatch(uow, effect, dispatch_id)
    uow.cursor.execute(
        """SELECT provider,provider_request_id,normalized_receipt FROM authority_provider_callback_receipt
        WHERE callback_receipt_id=%s AND project_id=%s AND external_effect_id=%s AND dispatch_id=%s
          AND signature_status='VERIFIED' AND payload_hash=%s""",
        [
            context.causation_id,
            effect["project_id"],
            effect["external_effect_id"],
            dispatch_id,
            payload_hash,
        ],
    )
    row = uow.cursor.fetchone()
    expected = {
        "provider_request_id": provider_request_id,
        "message_id": message_id,
        "payload_hash": payload_hash,
        "outcome": outcome,
        "evidence": evidence,
    }
    if (
        not row
        or row[0]
        != dispatch["evidence"]["production_execution"]["route_snapshot"][
            "model_provider"
        ]
        or row[1] != provider_request_id
        or (dispatch["evidence"]["production_execution"]["execution_handle"].get("provider_request_id")
            or (effect.get("provider_request_id") if dispatch_id == proof["dispatch_ids"][-1] else None)) != provider_request_id
        or any(row[2].get(key) != value for key, value in expected.items())
        or generation != dispatch["generation"]
    ):
        _invalid(
            "Require a signature-verified callback bound to the original remote request"
        )
    return append_receipt(
        uow,
        effect,
        dispatch,
        receipt={
            "outcome": outcome,
            "provider_request_id": provider_request_id,
            "result": evidence.get("result"),
            "usage": evidence.get("usage"),
            "cost": evidence.get("cost"),
        },
        verification={
            "basis": "VERIFIED_PROVIDER_CALLBACK",
            "callback_receipt_id": context.causation_id,
        },
        trace_id=context.trace_id,
        correlation_id=context.correlation_id,
    )


def append_receipt(
    uow, effect, dispatch, *, receipt, verification, trace_id, correlation_id
):
    from .external_effect_runtime import _hash
    from .budget_runtime import settle_provider_budget_in_uow
    from .provider_failure_accounting import successful_provider_budget_settlement

    receipt = {
        key: receipt.get(key)
        for key in (
            "outcome",
            "provider_request_id",
            "result",
            "usage",
            "cost",
            "provider_not_executed",
        )
    }
    if receipt.get("outcome") not in {
        "success",
        "final_failure",
        "cancelled",
        "not_found",
    }:
        _invalid("Require an authenticated terminal outcome; never retry isolated work")
    usage = receipt.get("usage")
    if usage is not None and (
        not isinstance(usage, dict)
        or usage.get("measurement") not in {"MEASURED", "PROVIDER_REPORTED"}
        or any(
            type(usage.get(key)) is not int or usage[key] < 0
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        or usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]
    ):
        _invalid("Require consistent measured original usage or preserve its absence")
    if receipt["outcome"] == "not_found" and (
        receipt.get("provider_not_executed") is not True
        or not usage
        or usage["total_tokens"] != 0
    ):
        _invalid("NOT_FOUND requires affirmative non-execution and measured zero usage")
    existing = resolution(uow.cursor, effect["external_effect_id"], dispatch["dispatch_id"])
    digest = _hash(receipt)
    if existing:
        if existing["receipt_hash"] == digest:
            return {**existing, "replayed": True}
        prior = existing["receipt"]
        if (
            (prior.get("usage") is not None and prior["usage"] != usage)
            or (existing["accounting"] != "HELD_UNKNOWN")
            or (
                _known_cost(prior.get("cost"))
                and prior.get("cost") != receipt.get("cost")
            )
            or not (
                (prior.get("usage") is None and usage is not None)
                or (
                    not _known_cost(prior.get("cost"))
                    and _known_cost(receipt.get("cost"))
                )
            )
            or {k: v for k, v in prior.items() if k not in {"usage", "cost"}}
            != {k: v for k, v in receipt.items() if k not in {"usage", "cost"}}
        ):
            raise KernelError(
                "ISOLATED_API_RECEIPT_CONFLICT",
                "Conflicting original evidence cannot replace an immutable receipt",
            )
    body = {
        "contract_version": CONTRACT,
        "project_id": effect["project_id"],
        "operation_id": effect["operation_id"],
        "dispatch_id": dispatch["dispatch_id"],
        "generation": dispatch["generation"],
        "request_hash": effect["request_hash"],
        "receipt_hash": digest,
        "receipt": receipt,
        "verification": verification,
        "business_commit_right": "REVOKED",
        "activation_right": "REVOKED",
        "accounting": "HELD_UNKNOWN",
    }
    accounting_receipt = _aggregate_accounting_receipts(uow, effect, dispatch, receipt)
    usage = accounting_receipt.get("usage") if accounting_receipt else None
    if usage is not None:
        uow.cursor.execute(
            """SELECT reservation_id,reserved_amount,estimated_tokens,accounting_basis,currency FROM authority_budget_reservation
            WHERE external_effect_id=%s AND project_id=%s AND status IN ('RESERVED','HELD_UNKNOWN','SETTLED')""",
            [effect["external_effect_id"], effect["project_id"]],
        )
        budgets = uow.cursor.fetchall()
        if len(budgets) != 1:
            _invalid("Require the original reservation; never create another charge")
        rid, reserved, tokens, basis, currency = budgets[0]
        cost = accounting_receipt.get("cost") or {}
        if basis != "ACCOUNT_ENTITLEMENT" and cost.get("availability") == "AVAILABLE":
            from decimal import Decimal, InvalidOperation

            try:
                measured_amount = Decimal(str(cost.get("amount")))
            except InvalidOperation:
                _invalid("Measured original cost requires a finite amount")
            if (
                not measured_amount.is_finite()
                or measured_amount < 0
                or cost.get("currency") != currency
            ):
                _invalid(
                    "Measured original cost currency or amount differs from its reservation"
                )
        amount, actual_tokens, settlement = successful_provider_budget_settlement(
            real_model_call=True,
            usage_tokens=usage["total_tokens"],
            cost_amount=str(cost.get("amount") or "0"),
            cost={**cost, "accounting_basis": basis},
            reserved_amount=None if basis == "ACCOUNT_ENTITLEMENT" else str(reserved),
            reserved_tokens=tokens,
            frozen_capability_profile=effect["provider_capability_profile"],
        )
        actual_tokens = usage["total_tokens"]
        settlement["token_settlement_basis"] = "PROVIDER_USAGE_RECEIPT"
        if accounting_receipt["outcome"] == "not_found":
            amount, actual_tokens = (None if basis == "ACCOUNT_ENTITLEMENT" else "0"), 0
            settlement = {
                "token_settlement_basis": "ORIGINAL_NON_EXECUTION_RECEIPT",
                "cost_settlement_basis": "ORIGINAL_NON_EXECUTION_RECEIPT",
            }
        if (
            basis == "ACCOUNT_ENTITLEMENT"
            or settlement["cost_settlement_basis"] != "RESERVATION_CEILING"
        ):
            result = settle_provider_budget_in_uow(
                uow,
                reservation_id=rid,
                project_id=effect["project_id"],
                actual_amount=amount,
                actual_tokens=actual_tokens,
                evidence={
                    "usage": usage,
                    "cost": accounting_receipt.get("cost"),
                    "isolated_dispatch_receipts": accounting_receipt.get("dispatch_receipts", []),
                    **settlement,
                    "isolated_original_receipt": verification,
                    "reconciled": True,
                },
            )
            body.update(
                accounting=result["status"],
                budget_breach=result["budget_breach"],
                reservation_id=rid,
            )
    uow.repositories.external_effects.record_reconciliation_evidence(
        {
            "reconciliation_id": str(uuid4()),
            "external_effect_id": effect["external_effect_id"],
            "provider": effect["provider"],
            "stable_idempotency_key": effect["stable_idempotency_key"],
            "outcome": {"final_failure": "failed_final"}.get(
                receipt["outcome"], receipt["outcome"]
            ),
            "evidence": body,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
        }
    )
    return {**body, "replayed": False}


def _require_api_schema(uow, ref, schema):
    uow.cursor.execute(
        "SELECT schema_version FROM authority_asset_version WHERE asset_version_id=%s",
        [ref.split(":", 1)[1]],
    )
    if uow.cursor.fetchone() != (schema,):
        _invalid("Original API evidence must retain its exact schema version")


def _known_cost(cost):
    return (
        isinstance(cost, dict)
        and cost.get("availability") == "AVAILABLE"
        and cost.get("amount") is not None
        and cost.get("provider_billed") is True
        and cost.get("measurement") in {"MEASURED", "PROVIDER_REPORTED"}
        and str(cost.get("source") or "").lower() not in {"not_provided", "usage_pricing", "usage_pricing_upper_bound"}
    )


def _aggregate_accounting_receipts(uow, effect, dispatch, receipt):
    from decimal import Decimal, InvalidOperation
    from .generation_isolation import isolation
    from .external_effect_runtime import _hash

    ids = isolation(uow.cursor, effect["external_effect_id"])["dispatch_ids"]
    if len(ids) == 1:
        return receipt
    uow.cursor.execute("SELECT accounting_basis,currency FROM authority_budget_reservation WHERE external_effect_id=%s AND project_id=%s", [effect["external_effect_id"], effect["project_id"]])
    budgets = uow.cursor.fetchall()
    if len(budgets) != 1:
        _invalid("Require the original shared reservation")
    basis, currency = budgets[0]
    records = []
    complete = True
    total_cost = Decimal(0)
    for identity in ids:
        recorded = resolution(uow.cursor, effect["external_effect_id"], identity)
        item = receipt if identity == dispatch["dispatch_id"] else recorded["receipt"] if recorded else None
        if item is None:
            complete = False
            continue
        if item.get("usage") is None:
            complete = False
        if basis != "ACCOUNT_ENTITLEMENT":
            cost = item.get("cost")
            if not _known_cost(cost):
                complete = False
            else:
                try:
                    amount = Decimal(str(cost["amount"]))
                except InvalidOperation:
                    _invalid("Every dispatch requires a finite measured cost")
                if not amount.is_finite() or amount < 0 or cost.get("currency") != currency:
                    _invalid("Every dispatch must retain its original reservation currency")
                total_cost += amount
        records.append((identity, item))
    if not complete:
        return None
    return {"outcome": "not_found" if all(item["outcome"] == "not_found" for _, item in records) else "success",
        "usage": {"measurement": "MEASURED", **{key: sum(item["usage"][key] for _, item in records)
            for key in ("input_tokens", "output_tokens", "total_tokens")}},
        "cost": {"availability": "AVAILABLE", "measurement": "MEASURED", "source": "isolated_original_provider_receipts", "provider_billed": True, "amount": str(total_cost), "currency": currency}
            if basis != "ACCOUNT_ENTITLEMENT" else {"availability": "UNAVAILABLE", "amount": None},
        "dispatch_receipts": [{"dispatch_id": identity, "receipt_hash": _hash(item)} for identity, item in records]}
