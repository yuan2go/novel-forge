from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from novel_forge.storage.versioned_policy_repository import policy_hash

from .errors import KernelError


def authorization_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def bootstrap_command_hash(payload: Mapping[str, Any]) -> str:
    return authorization_hash(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "routing_bootstrap_authorization",
                "routing_bootstrap_authorization_id",
            }
        }
    )


def validate_bootstrap_authorization(grant: Mapping[str, Any]) -> None:
    strings = {
        "authorization_id",
        "reason",
        "environment",
        "book_id",
        "task_type",
        "logical_key",
        "generation_idempotency_key",
        "input_versions_hash",
        "command_hash",
        "candidate_id",
        "model_revision",
        "expires_at",
        "maximum_amount",
        "currency",
        "purpose",
    }
    if set(grant) - {"campaign"} != strings | {
        "maximum_calls",
        "maximum_tokens",
        "production_eligible",
    }:
        raise ValueError("ROUTING_BOOTSTRAP_CONTRACT_INVALID")
    if any(
        not isinstance(grant[key], str) or not grant[key].strip() for key in strings
    ):
        raise ValueError("ROUTING_BOOTSTRAP_IDENTITY_REQUIRED")
    if (
        grant["environment"] != "validation"
        or grant["purpose"] != "BENCHMARK_CHALLENGER"
        or grant["production_eligible"] is not False
        or grant["currency"] != "USD"
    ):
        raise ValueError("ROUTING_BOOTSTRAP_BOUNDARY_INVALID")
    if any(
        type(grant[key]) is not int or grant[key] <= 0
        for key in ("maximum_calls", "maximum_tokens")
    ):
        raise ValueError("ROUTING_BOOTSTRAP_QUOTA_INVALID")
    amount = Decimal(grant["maximum_amount"])
    if (
        not amount.is_finite()
        or amount <= 0
        or datetime.fromisoformat(grant["expires_at"]).tzinfo is None
    ):
        raise ValueError("ROUTING_BOOTSTRAP_LIMIT_INVALID")
    for digest in (grant["input_versions_hash"], grant["command_hash"]):
        if (
            len(digest) != 71
            or not digest.startswith("sha256:")
            or any(c not in "0123456789abcdef" for c in digest[7:])
        ):
            raise ValueError("ROUTING_BOOTSTRAP_INPUT_IDENTITY_INVALID")
    if "campaign" in grant:
        validate_bootstrap_campaign(grant["campaign"])
        campaign = grant["campaign"]
        if (
            grant["maximum_calls"] > campaign["maximum_calls"]
            or grant["maximum_tokens"] > campaign["maximum_tokens"]
            or amount > Decimal(campaign["maximum_amount"])
            or datetime.fromisoformat(grant["expires_at"])
            > datetime.fromisoformat(campaign["expires_at"])
        ):
            raise ValueError("ROUTING_CAMPAIGN_GRANT_EXCEEDS_TOTAL")


def validate_bootstrap_campaign(campaign: Mapping[str, Any]) -> None:
    if not isinstance(campaign, Mapping) or set(campaign) != {
        "campaign_id", "manifest_hash", "sample_id", "group_id", "partition",
        "maximum_calls", "maximum_tokens", "maximum_amount", "expires_at",
    }:
        raise ValueError("ROUTING_CAMPAIGN_CONTRACT_INVALID")
    for key in ("campaign_id", "sample_id", "group_id", "manifest_hash", "expires_at", "maximum_amount"):
        if not isinstance(campaign[key], str) or not campaign[key].strip():
            raise ValueError("ROUTING_CAMPAIGN_IDENTITY_REQUIRED")
    digest = campaign["manifest_hash"]
    if len(digest) != 71 or not digest.startswith("sha256:") or any(
        char not in "0123456789abcdef" for char in digest[7:]
    ):
        raise ValueError("ROUTING_CAMPAIGN_MANIFEST_IDENTITY_INVALID")
    if campaign["partition"] not in {"DEVELOPMENT", "CALIBRATION", "HOLDOUT"}:
        raise ValueError("ROUTING_CAMPAIGN_PARTITION_INVALID")
    if any(type(campaign[key]) is not int or campaign[key] <= 0
           for key in ("maximum_calls", "maximum_tokens")):
        raise ValueError("ROUTING_CAMPAIGN_QUOTA_INVALID")
    amount = Decimal(campaign["maximum_amount"])
    if not amount.is_finite() or amount <= 0 or datetime.fromisoformat(
        campaign["expires_at"]
    ).tzinfo is None:
        raise ValueError("ROUTING_CAMPAIGN_LIMIT_INVALID")


def campaign_contract(campaign: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in campaign.items()
            if key not in {"sample_id", "group_id", "partition"}}


def validate_bootstrap_history(
    grants: list[Mapping[str, Any]], previous: list[Mapping[str, Any]]
) -> None:
    identities: dict[str, Mapping[str, Any]] = {}
    campaigns: dict[str, Mapping[str, Any]] = {}
    groups: dict[tuple[str, str], str] = {}
    samples: dict[tuple[str, str], tuple[str, str, str]] = {}
    inputs: dict[tuple[str, str], str] = {}
    for grant in [*previous, *grants]:
        key = grant["authorization_id"]
        if key in identities and identities[key] != grant:
            raise KernelError("ROUTING_BOOTSTRAP_AUTHORIZATION_REDEFINED",
                              "an authorization retains its original scope and quota")
        identities[key] = grant
        campaign = grant.get("campaign")
        if campaign is None:
            continue
        identity = campaign["campaign_id"]
        contract = campaign_contract(campaign)
        if identity in campaigns and campaigns[identity] != contract:
            raise KernelError("ROUTING_CAMPAIGN_REDEFINED",
                              "a campaign retains its frozen manifest and cumulative quota")
        campaigns[identity] = contract
        group = (identity, campaign["group_id"])
        partition = campaign["partition"]
        if group in groups and groups[group] != partition:
            raise KernelError("ROUTING_CAMPAIGN_HOLDOUT_LEAKAGE",
                              "a data group cannot cross experiment partitions")
        groups[group] = partition
        sample = (identity, campaign["sample_id"])
        binding = (campaign["group_id"], grant["task_type"], grant["input_versions_hash"])
        if sample in samples and samples[sample] != binding:
            raise KernelError("ROUTING_CAMPAIGN_SAMPLE_REDEFINED",
                              "a sample retains its data group, task and input versions")
        samples[sample] = binding
        source = (identity, grant["input_versions_hash"])
        if source in inputs and inputs[source] != partition:
            raise KernelError("ROUTING_CAMPAIGN_HOLDOUT_LEAKAGE",
                              "identical inputs cannot acquire a new partition by renaming")
        inputs[source] = partition
    if len(campaigns) > 1:
        raise KernelError("ROUTING_CAMPAIGN_PROJECT_REBIND_FORBIDDEN",
                          "a campaign project cannot reset usage by changing campaign identity")
    historical_ids = {grant["authorization_id"] for grant in previous}
    if campaigns and any(not grant.get("campaign") and grant["authorization_id"] not in historical_ids
                         for grant in grants):
        raise KernelError("ROUTING_CAMPAIGN_MEMBERSHIP_REQUIRED",
                          "new sampling grants must retain the project's campaign budget")


def validate_bootstrap_policy_in_uow(
    cursor: Any, *, project_id: str, content: Mapping[str, Any]
) -> None:
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ["routing-bootstrap-policy:" + project_id],
    )
    cursor.execute(
        "SELECT content,content_hash FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s",
        [project_id],
    )
    previous = []
    for policy, digest in cursor.fetchall():
        if policy_hash(policy) != digest:
            raise KernelError("RUNTIME_POLICY_HASH_MISMATCH", "policy integrity failed")
        previous.extend(policy.get("bootstrap_authorizations", []))
    validate_bootstrap_history(list(content.get("bootstrap_authorizations", [])), previous)


def validate_bootstrap_scope(
    snapshot: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    check_expiry: bool = True,
) -> Mapping[str, Any]:
    try:
        grant = snapshot["authorization"]
        validate_bootstrap_authorization(grant)
        if (
            snapshot["authorization_hash"] != authorization_hash(grant)
            or snapshot["project_id"] != payload["project_id"]
            or snapshot["environment"] != "validation"
        ):
            raise ValueError("snapshot identity differs")
        expected = {
            "authorization_id": payload.get("routing_bootstrap_authorization_id"),
            "book_id": payload.get("book_id"),
            "task_type": payload.get("generator_operation_name"),
            "logical_key": payload.get("logical_key"),
            "generation_idempotency_key": payload.get("idempotency_key"),
            "input_versions_hash": authorization_hash(payload.get("input_versions")),
            "command_hash": bootstrap_command_hash(payload),
        }
        if any(grant[key] != value for key, value in expected.items()):
            raise ValueError("command identity differs")
    except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
        raise KernelError(
            "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
            "benchmark authorization does not match its admitted task",
        ) from exc
    if check_expiry and datetime.now(timezone.utc) >= datetime.fromisoformat(
        grant["expires_at"]
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_EXPIRED", "benchmark authorization has expired"
        )
    return grant


def load_bootstrap_authorization(
    cursor: Any, *, project_id: str, operation_id: str, check_expiry: bool = True
) -> Mapping[str, Any] | None:
    cursor.execute(
        "SELECT command_payload->'payload',definition_name,definition_version,idempotency_scope,idempotency_key FROM authority_operation WHERE project_id=%s AND operation_id=%s",
        [project_id, operation_id],
    )
    row = cursor.fetchone()
    payload = (row[0] if row else None) or {}
    snapshot = payload.get("routing_bootstrap_authorization")
    if not snapshot:
        if payload.get("routing_bootstrap_authorization_id"):
            raise KernelError(
                "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                "admitted benchmark task lacks its immutable grant",
            )
        return None
    if tuple(row[1:4]) != (
        "story_planning.generate",
        "1.16.0",
        "book:story-planning-generation",
    ) or row[4] != payload.get("idempotency_key"):
        raise KernelError(
            "ROUTING_BOOTSTRAP_SCOPE_MISMATCH",
            "benchmark authorization requires its admitted Planning operation contract",
        )
    grant = validate_bootstrap_scope(snapshot, payload, check_expiry=check_expiry)
    cursor.execute(
        "SELECT content,content_hash,actor_id,created_by_operation_id FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s AND policy_version=%s",
        [project_id, snapshot.get("policy_version")],
    )
    policy = cursor.fetchone()
    if (
        not policy
        or policy_hash(policy[0]) != policy[1]
        or policy[1] != snapshot.get("policy_hash")
        or policy[2] != snapshot.get("policy_actor_id")
        or policy[3] != snapshot.get("policy_operation_id")
        or grant not in policy[0].get("bootstrap_authorizations", [])
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_POLICY_INTEGRITY_FAILURE",
            "benchmark grant does not match its immutable policy version",
        )
    return snapshot


def _verified_effect(
    cursor: Any, *, external_effect_id: str, project_id: str, check_expiry: bool
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    cursor.execute(
        "SELECT operation_id,request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE external_effect_id=%s AND project_id=%s",
        [external_effect_id, project_id],
    )
    row = cursor.fetchone()
    if not row:
        return None
    decision = row[1] or {}
    snapshot = load_bootstrap_authorization(
        cursor, project_id=project_id, operation_id=row[0], check_expiry=check_expiry
    )
    if snapshot is None:
        if decision.get("status") == "BENCHMARK_SELECTED" or decision.get(
            "bootstrap_authorization"
        ):
            raise KernelError(
                "ROUTING_BOOTSTRAP_AUTHORIZATION_REQUIRED",
                "benchmark route lacks admitted authorization",
            )
        return None
    grant = snapshot["authorization"]
    candidate = (decision.get("selected") or {}).get("candidate") or {}
    task = decision.get("task") or {}
    if (
        decision.get("status") != "BENCHMARK_SELECTED"
        or decision.get("mode") != "BENCHMARK_CHALLENGER"
        or decision.get("production_eligible") is not False
        or decision.get("bootstrap_authorization") != snapshot
        or task.get("task_type") != grant["task_type"]
        or task.get("work_id") != grant["book_id"]
        or task.get("operation_id") != row[0]
        or task.get("project_id") != project_id
        or candidate.get("candidate_id") != grant["candidate_id"]
        or candidate.get("model_revision") != grant["model_revision"]
        or candidate.get("provider") != "deepseek"
        or candidate.get("pricing", {}).get("accounting_basis") != "PRICED"
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_DECISION_CONFLICT",
            "benchmark decision differs from its admitted authorization",
        )
    content = {
        key: value
        for key, value in decision.items()
        if key not in {"asset_version_id", "decision_id"}
    }
    if (
        decision.get("decision_id")
        != "routing-decision:" + authorization_hash(content)[7:]
    ):
        raise KernelError(
            "ROUTING_DECISION_INTEGRITY_FAILURE", "benchmark decision hash differs"
        )
    cursor.execute(
        """SELECT asset.asset_type,version.content,version.content_hash
           FROM authority_asset_version version JOIN authority_asset asset USING(asset_id)
           WHERE asset.project_id=%s AND version.asset_version_id=%s""",
        [project_id, decision.get("asset_version_id")],
    )
    persisted = cursor.fetchone()
    frozen_content = {
        key: value for key, value in decision.items() if key != "asset_version_id"
    }
    if (
        not persisted
        or persisted[0] != "routing_decision"
        or persisted[1] != frozen_content
        or persisted[2] != authorization_hash(frozen_content)
    ):
        raise KernelError(
            "ROUTING_DECISION_INTEGRITY_FAILURE",
            "benchmark decision differs from its immutable routing asset",
        )
    return snapshot, grant


def verify_routing_bootstrap_budget(
    cursor: Any, request: Any, amount: Decimal | None, *, check_usage: bool = True
) -> None:
    verified = _verified_effect(
        cursor,
        external_effect_id=request.external_effect_id,
        project_id=request.project_id,
        check_expiry=check_usage,
    )
    if verified is None:
        return
    _, grant = verified
    if (
        amount is None
        or request.currency != "USD"
        or request.accounting_basis != "PRICED"
    ):
        raise KernelError(
            "ROUTING_BOOTSTRAP_ACCOUNTING_INVALID",
            "benchmark execution requires priced accounting",
        )
    if not check_usage:
        return
    from .budget_runtime import provider_usage_accounted_sql

    prefix = ["_production_execution", "capability_runtime", "routing_decision",
              "bootstrap_authorization", "authorization"]
    scopes = [(grant, prefix + ["authorization_id"], grant["authorization_id"], "BOOTSTRAP")]
    if campaign := grant.get("campaign"):
        scopes.append((campaign, prefix + ["campaign", "campaign_id"], campaign["campaign_id"], "CAMPAIGN"))
    for quota, path, identity, label in scopes:
        cursor.execute(
            f"""SELECT count(*),COALESCE(sum(CASE WHEN b.status='SETTLED' THEN b.settled_amount ELSE b.reserved_amount END),0),COALESCE(sum(CASE WHEN b.status='SETTLED' THEN b.actual_tokens ELSE greatest(b.actual_tokens,b.estimated_tokens) END),0),bool_or(b.status IN ('RESERVED','HELD_UNKNOWN'))
            FROM (SELECT * FROM authority_budget_reservation WHERE {provider_usage_accounted_sql()}) b JOIN authority_external_effect e USING(external_effect_id)
            WHERE b.project_id=%s AND e.request_payload #>> %s::text[]=%s""",
            [request.project_id, path, identity],
        )
        calls, spent, tokens, pending = cursor.fetchone()
        cursor.execute(
            """SELECT EXISTS (
                SELECT 1 FROM authority_budget_reservation b
                JOIN authority_external_effect e USING(external_effect_id)
                WHERE b.project_id=%s AND b.status<>'REJECTED'
                  AND e.status IN ('UNKNOWN','SENT_UNKNOWN','UNKNOWN_AMBIGUOUS','RECONCILIATION_REQUIRED')
                  AND e.request_payload #>> %s::text[]=%s
            )""",
            [request.project_id, path, identity],
        )
        unknown = bool(cursor.fetchone()[0])
        if pending or unknown:
            raise KernelError(
                f"ROUTING_{label}_RECONCILIATION_REQUIRED",
                "earlier benchmark execution must resolve first",
            )
        if (
            int(calls) + 1 > quota["maximum_calls"]
            or int(tokens) + request.estimated_tokens > quota["maximum_tokens"]
            or Decimal(spent) + amount > Decimal(quota["maximum_amount"])
        ):
            raise KernelError(
                f"ROUTING_{label}_QUOTA_EXCEEDED",
                "cumulative benchmark authorization quota would be exceeded",
            )


def verify_routing_bootstrap_dispatch(
    cursor: Any, *, external_effect_id: str, project_id: str
) -> None:
    _verified_effect(
        cursor,
        external_effect_id=external_effect_id,
        project_id=project_id,
        check_expiry=True,
    )
