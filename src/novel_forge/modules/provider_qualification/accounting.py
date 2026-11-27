from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.production_execution import CodexAccountEntitlementSnapshot


def accounting_scope_from_cost(cost: Mapping[str, Any]) -> dict[str, str]:
    basis = cost.get("accounting_basis", "PRICED")
    if basis == "PRICED":
        if cost.get("entitlement_snapshot") or cost.get("entitlement_snapshot_hash"):
            raise ValueError("entitlement evidence cannot be relabelled as priced accounting")
        return {}
    if basis != "ACCOUNT_ENTITLEMENT":
        raise ValueError("qualification accounting basis is unsupported")
    snapshot = cost.get("entitlement_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("entitlement snapshot is required")
    try:
        frozen = CodexAccountEntitlementSnapshot(**dict(snapshot))
    except (TypeError, ValueError) as exc:
        raise ValueError("entitlement snapshot is invalid") from exc
    if (cost.get("availability") != "UNAVAILABLE" or cost.get("measurement") != "UNKNOWN"
        or cost.get("currency") != "UNKNOWN" or cost.get("provider_billed") != "UNKNOWN"
        or cost.get("amount") is not None or cost.get("amount_usd") is not None
        or cost.get("pricing_snapshot_hash") or cost.get("pricing_snapshot")
        or not cost.get("reason")
        or cost.get("authorization_ref") != frozen.authorization_ref
        or cost.get("entitlement_snapshot_hash") != frozen.snapshot_hash):
        raise ValueError("entitlement qualification must preserve unknown monetary cost and exact account identity")
    return {"accounting_basis": "ACCOUNT_ENTITLEMENT", "authorization_ref": frozen.authorization_ref,
            "account_identity_ref": frozen.account_identity_ref, "entitlement_snapshot_hash": frozen.snapshot_hash}


def validate_accounting_scope(value: Mapping[str, Any]) -> dict[str, str]:
    if not value:
        return {}
    expected = {"accounting_basis", "authorization_ref", "account_identity_ref", "entitlement_snapshot_hash"}
    if (set(value) != expected or value.get("accounting_basis") != "ACCOUNT_ENTITLEMENT"
        or any(not isinstance(item, str) or not item.strip() for item in value.values())
        or len(value["entitlement_snapshot_hash"]) != 71
        or not value["entitlement_snapshot_hash"].startswith("sha256:")
        or any(letter not in "0123456789abcdef" for letter in value["entitlement_snapshot_hash"][7:])):
        raise ValueError("entitlement qualification scope is incomplete")
    return dict(value)


def require_entitlement_budget(cursor: Any, *, project_id: str, effect_id: str,
                               cost: Mapping[str, Any], usage: Mapping[str, Any],
                               reservation_rows: list[Any] | None = None) -> dict[str, Any]:
    scope = accounting_scope_from_cost(cost)
    if not scope:
        return {}
    total_tokens = usage.get("total_tokens")
    if not isinstance(total_tokens, int) or isinstance(total_tokens, bool) or total_tokens <= 0:
        raise ValueError("entitlement qualification requires measured Provider usage; unknown usage remains unqualified")
    rows = entitlement_budget_rows(cursor, project_id=project_id, effect_ids=(effect_id,)).get(effect_id, []) if reservation_rows is None else reservation_rows
    if len(rows) != 1:
        raise ValueError("entitlement qualification requires one exact settled Provider reservation")
    row = rows[0]
    evidence = row[11] or {}
    caps = {name: (evidence.get(name) or {}).get("project_total") for name in ("call_caps", "token_caps")}
    membership = evidence.get("resource_control_version") == "billing-channel-resources.v1"
    limits_valid = (evidence.get("call_caps") == evidence.get("token_caps") == {}) if membership else all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in caps.values())
    if (row[1:4] != ("SETTLED", "ACCOUNT_ENTITLEMENT", "UNKNOWN")
        or any(value is not None for value in row[4:7])
        or row[7:9] != ("UNKNOWN", "UNKNOWN") or row[9] <= 0
        or row[10] != total_tokens
        or evidence.get("cost_authorization_ref") != scope["authorization_ref"]
        or not limits_valid):
        raise ValueError("entitlement qualification requires exact account authorization, unknown cost and its frozen resource contract")
    return {"reservation_id": str(row[0]), "accounting_scope": scope,
            "call_caps": dict(evidence["call_caps"]), "token_caps": dict(evidence["token_caps"]),
            "estimated_tokens": int(row[9]), "actual_tokens": int(row[10]), "monetary_cost": "UNKNOWN",
            **({"resource_control_version": "billing-channel-resources.v1"} if membership else {})}


def entitlement_budget_rows(cursor: Any, *, project_id: str, effect_ids: tuple[str, ...]) -> dict[str, list[Any]]:
    if not effect_ids:
        return {}
    cursor.execute(
        """SELECT external_effect_id,reservation_id,status,accounting_basis,currency,estimated_amount,reserved_amount,
                  settled_amount,estimated_cost_status,settled_cost_status,estimated_tokens,actual_tokens,evidence
           FROM authority_budget_reservation WHERE project_id=%s AND external_effect_id=ANY(%s::text[])
           FOR SHARE""", [project_id, list(effect_ids)],
    )
    result: dict[str, list[Any]] = {}
    for row in cursor.fetchall():
        result.setdefault(str(row[0]), []).append(tuple(row[1:]))
    return result
