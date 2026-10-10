from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .cli_effect_reconciliation import _asset
from .errors import KernelError
from .generation_isolation import isolation


CONTRACT = "isolated-api-reconciliation.v1"


def append_resolution(uow, effect, command):
    proof = isolation(uow.cursor, effect["external_effect_id"])
    if not proof or proof.get("execution_transport") != "REMOTE_PROVIDER_API":
        raise KernelError(
            "ISOLATED_API_RECEIPT_SCOPE_INVALID",
            "Require original isolated API generation",
        )
    ref = command.evidence.get("original_remote_receipt_ref")
    if not ref:
        ref = _intake(uow, effect, proof, command)
    receipt = _asset(uow.cursor, effect["project_id"], ref, kind="execution_evidence")
    source = _asset(
        uow.cursor,
        effect["project_id"],
        receipt.get("source_ref"),
        kind="execution_evidence",
    )
    identity = {
        "project_id": effect["project_id"],
        "operation_id": effect["operation_id"],
        "external_effect_id": effect["external_effect_id"],
        "request_hash": effect["request_hash"],
        "book_id": proof["book_id"],
        "workspace_id": proof["workspace_id"],
        **{
            key: value
            for key, value in proof["local_execution"].items()
            if value is not None
        },
    }
    uow.cursor.execute(
        "SELECT dispatch_id,generation,payload_hash,evidence FROM authority_external_effect_dispatch WHERE external_effect_id=%s ORDER BY generation FOR UPDATE",
        [effect["external_effect_id"]],
    )
    dispatches = uow.cursor.fetchall()
    matching = [
        row
        for row in dispatches
        if (row[0], row[1]) == (receipt.get("dispatch_id"), receipt.get("generation"))
    ]
    if len(matching) != 1 or matching[0][2] != effect["request_hash"]:
        _invalid("Receipt differs from original dispatch generation")
    identity.update(dispatch_id=matching[0][0], generation=matching[0][1])
    session = _asset(
        uow.cursor,
        effect["project_id"],
        "authority-asset-version:" + proof["evidence_asset_version_id"],
        kind="execution_recovery_session",
    )
    from .generation_isolation import require_native_api_isolation_record

    original_request, _ = require_native_api_isolation_record(
        session,
        project_id=effect["project_id"],
        book_id=proof["book_id"],
        operation_id=effect["operation_id"],
        effect_id=effect["external_effect_id"],
        capability=effect["request_payload"]["_production_execution"][
            "capability_runtime"
        ],
    )
    original = original_request.to_dict()
    if (matching[0][3].get("production_execution") or {}).get(
        "execution_request"
    ) != original:
        _invalid("Receipt session differs from the persisted original dispatch request")
    identity.update(
        execution_request_hash=original_request.contract_hash,
        input_manifest_ref=original_request.input_manifest_ref,
        model_id=effect["model_id"],
        provider=effect["provider"],
    )
    if any(
        original.get(key) != identity[key]
        for key in (
            "project_id",
            "book_id",
            "operation_id",
            "external_effect_id",
            "execution_id",
            "attempt_id",
            "fencing_token",
        )
    ):
        _invalid("Isolation differs from durable original invocation")
    if (
        receipt.get("contract_version") != "generation-remote-receipt.v1"
        or source.get("contract_version") != "generation-provider-record.v1"
        or receipt.get("verification_basis") != "AUTHORIZED_OPERATOR_ATTESTATION"
        or receipt.get("verified_by") != command.actor_id
        or not isinstance(receipt.get("provider_request_id"), str)
        or not receipt["provider_request_id"].strip()
        or any(
            receipt.get(key) != value or source.get(key) != value
            for key, value in identity.items()
        )
        or any(
            source.get(key) != receipt.get(key)
            for key in ("provider_request_id", "outcome", "usage", "cost", "result")
        )
    ):
        _invalid(
            "Trusted receipt and preserved provider record must bind the original scope and fence"
        )
    expected = {
        "MARK_SUCCEEDED": "success",
        "MARK_NOT_FOUND": "not_found",
        "MARK_FAILED_FINAL": "failed_final",
        "MARK_CANCELLED": "cancelled",
    }
    if expected.get(command.decision) != receipt.get("outcome"):
        _invalid("Decision differs from confirmed remote outcome")
    usage = receipt.get("usage")
    if (
        not isinstance(usage, dict)
        or usage.get("measurement") != "PROVIDER_REPORTED"
        or any(
            type(usage.get(key)) is not int or usage[key] < 0
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        or usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]
    ):
        _invalid(
            "Require measured original usage; unavailable usage cannot be invented"
        )
    if receipt["outcome"] == "not_found" and (
        receipt.get("provider_not_executed") is not True
        or source.get("provider_not_executed") is not True
        or usage["total_tokens"] != 0
    ):
        _invalid("NOT_FOUND requires affirmative original nonexecution evidence")
    from .external_effect_runtime import _hash

    fingerprint = _hash(
        {
            **identity,
            **{
                key: receipt.get(key)
                for key in (
                    "provider_request_id",
                    "outcome",
                    "usage",
                    "cost",
                    "result",
                    "provider_not_executed",
                )
            },
        }
    )
    uow.cursor.execute(
        "SELECT evidence FROM authority_effect_reconciliation_evidence WHERE external_effect_id=%s AND evidence->>'contract_version'=%s",
        [effect["external_effect_id"], CONTRACT],
    )
    prior = uow.cursor.fetchone()
    if prior:
        if prior[0]["receipt_fingerprint"] != fingerprint:
            raise KernelError(
                "ISOLATED_API_RECEIPT_CONFLICT",
                "Original generation already has different immutable reconciliation evidence",
            )
        return {**prior[0], "replayed": True}
    uow.cursor.execute(
        "SELECT reservation_id,status,accounting_basis,currency FROM authority_budget_reservation WHERE external_effect_id=%s AND project_id=%s FOR UPDATE",
        [effect["external_effect_id"], effect["project_id"]],
    )
    budgets = uow.cursor.fetchall()
    if len(budgets) != 1 or budgets[0][1] not in {"RESERVED", "HELD_UNKNOWN"}:
        _invalid(
            "Require original unsettled reservation; settled history cannot be overwritten"
        )
    reservation_id, _, basis, currency = budgets[0]
    amount = None
    cost = receipt.get("cost")
    if not isinstance(cost, dict):
        _invalid("Require explicit original cost observability")
    if basis == "PRICED":
        if (
            cost.get("measurement") != "PROVIDER_REPORTED"
            or cost.get("currency") != currency
        ):
            _invalid(
                "Paid settlement requires measured original cost in its reserved currency"
            )
        try:
            amount = Decimal(str(cost["amount"]))
        except (KeyError, InvalidOperation):
            _invalid("Paid cost is unavailable")
        if not amount.is_finite() or amount < 0:
            _invalid("Paid cost must be finite and nonnegative")
    elif basis != "ACCOUNT_ENTITLEMENT" or cost.get("amount") is not None:
        _invalid("Entitlement monetary cost remains UNKNOWN")
    from .budget_runtime import settle_provider_budget_in_uow

    settlement = settle_provider_budget_in_uow(
        uow,
        reservation_id=reservation_id,
        project_id=effect["project_id"],
        actual_amount=str(amount) if amount is not None else None,
        actual_tokens=usage["total_tokens"],
        evidence={
            "measurement_available": True,
            "usage": usage,
            "cost": cost,
            "original_remote_receipt_ref": ref,
            "usage_settlement_basis": "ISOLATED_ORIGINAL_RECEIPT",
            "business_commit_right": "REVOKED",
        },
    )
    body = {
        "contract_version": CONTRACT,
        **identity,
        "outcome": receipt["outcome"],
        "original_remote_receipt_ref": ref,
        "receipt_fingerprint": fingerprint,
        "accounting_only": True,
        "business_commit_right": "REVOKED",
        "activation_right": "REVOKED",
        "settlement": settlement,
    }
    uow.repositories.external_effects.record_reconciliation_evidence(
        {
            "reconciliation_id": str(uuid4()),
            "external_effect_id": effect["external_effect_id"],
            "provider": effect["provider"],
            "stable_idempotency_key": effect["stable_idempotency_key"],
            "outcome": receipt["outcome"],
            "evidence": body,
            "trace_id": command.trace_id,
            "correlation_id": command.correlation_id,
        }
    )
    return body


def _invalid(message):
    raise KernelError("ISOLATED_API_RECEIPT_INVALID", message)


def _intake(uow, effect, proof, command):
    from .asset_commands import AuthorityAssetWriteCommand
    from .external_effect_runtime import _hash
    from novel_forge.modules.production_execution.security import (
        assert_no_inline_secrets,
    )

    receipt = command.evidence.get("original_remote_receipt")
    source = command.evidence.get("original_provider_record")
    if (
        not isinstance(receipt, dict)
        or not isinstance(source, dict)
        or receipt.get("source_ref")
    ):
        _invalid(
            "Provide the original provider record and its trusted attestation, or persistent receipt reference"
        )
    assert_no_inline_secrets(source, label="Original isolated API provider record")
    assert_no_inline_secrets(receipt, label="Original isolated API attestation")
    execution_id = proof["local_execution"]["execution_id"]

    def persist(kind, payload):
        digest = _hash(payload).removeprefix("sha256:")
        logical_ref = (
            f"production_execution/recovery/evidence/{execution_id}/{kind}/{digest}"
        )
        uow.cursor.execute(
            "SELECT current_asset_version_id FROM authority_asset_locator WHERE project_id=%s AND logical_ref=%s",
            [effect["project_id"], logical_ref],
        )
        existing = uow.cursor.fetchone()
        if existing:
            return "authority-asset-version:" + existing[0]
        document = uow.repositories.asset_documents.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=effect["operation_id"],
                project_id=effect["project_id"],
                asset_id="isolated-api-evidence:" + digest,
                asset_type="execution_evidence",
                schema_version="authority-execution-evidence.v1",
                logical_ref=logical_ref,
                category="production_execution_evidence",
                output_key="isolated-api." + kind + "." + digest,
                role="execution_evidence",
                content={
                    "contract_version": "authority-execution-evidence.v1",
                    "execution_id": execution_id,
                    "kind": kind,
                    "payload": payload,
                    "payload_hash": digest,
                },
                qualification_policy="isolated-api-accounting-only-v1",
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                causation_id=effect["external_effect_id"],
            )
        )
        return "authority-asset-version:" + document.asset_version_id

    source_ref = persist("generation-provider-record", source)
    return persist("generation-remote-receipt", {**receipt, "source_ref": source_ref})
