from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.service import _validate_json_schema

from .cost_routing import RoutingDecision, snapshot_hash, task_policy


MODE = "AUTHOR_SUPERVISED"
LITERARY_UNCERTAINTY = frozenset({"QUALITY_FLOOR_NOT_MET", "BENCHMARK_INSUFFICIENT"})
GRANT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["authorization_id", "book_id", "task_type", "producer_contract_hash",
                 "candidate_id", "model_revision", "author_id", "expires_at",
                 "maximum_tokens", "maximum_amount", "reason"],
    "properties": {
        **{key: {"type": "string", "minLength": 1} for key in (
            "authorization_id", "book_id", "task_type", "candidate_id", "model_revision",
            "author_id", "expires_at", "reason")},
        "producer_contract_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "maximum_tokens": {"type": "integer", "minimum": 1},
        "maximum_amount": {"type": "string", "pattern": "^[0-9]+(\\.[0-9]+)?$"},
    },
}


def validate_grants(content: Mapping[str, Any], *, author_id: str | None = None) -> None:
    seen_books = set()
    for book in content.get("author_supervised_books", []):
        if (not isinstance(book, dict) or set(book) != {"book_id", "author_id", "reason"}
                or any(not isinstance(v, str) or not v.strip() for v in book.values())
                or book["book_id"] in seen_books or author_id is not None and book["author_id"] != author_id):
            raise KernelError("AUTHOR_SUPERVISION_GRANT_INVALID", "Book mode requires an exact authenticated author decision")
        seen_books.add(book["book_id"])
    seen = set()
    for grant in content.get("author_supervised_authorizations", []):
        _validate_json_schema(GRANT_SCHEMA, grant)
        task_policy(grant["task_type"])
        expiry = datetime.fromisoformat(grant["expires_at"])
        identity = (grant["book_id"], grant["task_type"], grant["producer_contract_hash"])
        if (expiry.tzinfo is None or identity in seen or not Decimal(grant["maximum_amount"]).is_finite()
                or author_id is not None and grant["author_id"] != author_id):
            raise KernelError("AUTHOR_SUPERVISION_GRANT_INVALID", "Author, expiry or exact task scope differs")
        seen.add(identity)


def matching_grant(task: Mapping[str, Any], *, now: datetime) -> dict[str, Any] | None:
    policy = task.get("policy_snapshot", {})
    validate_grants(policy.get("policy", {}), author_id=policy.get("actor_id", ""))
    grants = [g for g in policy.get("policy", {}).get("author_supervised_authorizations", [])
              if (g["book_id"], g["task_type"], g["producer_contract_hash"]) ==
              (task["work_id"], task["task_type"], task.get("producer_contract_hash"))]
    if not grants:
        return None
    grant = dict(grants[0])
    if not policy.get("operation_id") or now >= datetime.fromisoformat(grant["expires_at"]):
        raise KernelError("AUTHOR_SUPERVISION_EXPIRED_OR_UNAUTHENTICATED", "A current native author policy is required")
    return grant


def supervised_decision(decision: RoutingDecision, *, now: datetime) -> RoutingDecision:
    snapshot = decision.to_dict()
    task = snapshot["task"]
    supervised_book = any(book["book_id"] == task["work_id"]
        for book in task.get("policy_snapshot", {}).get("policy", {}).get("author_supervised_books", []))
    strict_evaluation = (task["task_type"] == "narrative_semantic_evaluation"
        and task.get("declared_requirements", {}).get("cross_model_review", {}).get("purpose") != "AUTHOR_ADVISORY")
    if strict_evaluation and not supervised_book:
        return decision
    grant = matching_grant(task, now=now)
    if grant is None:
        if not supervised_book:
            return decision
        for row in snapshot["candidates"]:
            row["strict_rejected_reasons"] = list(row["rejected_reasons"])
            row["rejected_reasons"].append("AUTHOR_SUPERVISION_TASK_AUTHORIZATION_REQUIRED")
        snapshot.update(status="BLOCKED", selected=None, mode=MODE, production_eligible=False,
            independent_qualification_eligible=False,
            author_supervision={"admission_contract_version": "author-supervision-admission.v2",
                "authorization": {}, "policy_operation_id": task.get("policy_snapshot", {}).get("operation_id", ""),
                "literary_qualification": "NOT_PROVEN", "author_review_required": True,
                "required_decision": "Approve this exact Book, task, Producer and model, then resume with a new Attempt"})
        snapshot.pop("decision_id", None)
        snapshot["decision_id"] = "routing-decision:" + snapshot_hash(snapshot)[7:]
        return RoutingDecision(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False))
    if strict_evaluation:
        selected = snapshot.get("selected")
        if selected is None:
            return decision
        candidate = selected["candidate"]
        reasons = []
        if (candidate["candidate_id"], candidate["model_revision"]) != (grant["candidate_id"], grant["model_revision"]):
            reasons.append("AUTHOR_SUPERVISION_MODEL_MISMATCH")
        if (selected["estimated_total_tokens"] > grant["maximum_tokens"] or
                Decimal(selected["reservation_upper_bound"] or "0") > Decimal(grant["maximum_amount"])):
            reasons.append("AUTHOR_SUPERVISION_BUDGET_EXCEEDED")
        if not reasons:
            return decision
        for row in snapshot["candidates"]:
            if row["candidate"]["candidate_id"] == candidate["candidate_id"]:
                row["strict_rejected_reasons"] = list(row["rejected_reasons"])
                row["rejected_reasons"].extend(reasons)
        snapshot.update(status="BLOCKED", selected=None, production_eligible=False,
            author_supervision={"admission_contract_version": "author-supervision-admission.v2",
                "authorization": grant, "authorization_hash": snapshot_hash(grant),
                "policy_operation_id": task["policy_snapshot"]["operation_id"], "qualification_override": False})
        snapshot.pop("decision_id", None)
        snapshot["decision_id"] = "routing-decision:" + snapshot_hash(snapshot)[7:]
        return RoutingDecision(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False))
    if snapshot.get("bootstrap_authorization"):
        raise KernelError("AUTHOR_SUPERVISION_EXPERIMENT_FORBIDDEN", "Sampling cannot become supervised production")
    selected = None
    for row in snapshot["candidates"]:
        row["strict_rejected_reasons"] = list(row["rejected_reasons"])
        candidate = row["candidate"]
        if (candidate["candidate_id"], candidate["model_revision"]) != (grant["candidate_id"], grant["model_revision"]):
            row["rejected_reasons"].append("AUTHOR_SUPERVISION_MODEL_MISMATCH")
            continue
        row["rejected_reasons"] = [reason for reason in row["rejected_reasons"] if reason not in LITERARY_UNCERTAINTY]
        if (row["estimated_total_tokens"] > grant["maximum_tokens"] or
                Decimal(row["reservation_upper_bound"] or "0") > Decimal(grant["maximum_amount"])):
            row["rejected_reasons"].append("AUTHOR_SUPERVISION_BUDGET_EXCEEDED")
        budgets = snapshot["task"].get("budget_snapshot", {}).get("candidates", {}).get(candidate["candidate_id"], {})
        if budgets.get("remaining_calls") is None or not any(k.startswith("tokens:") for k in budgets.get("scopes", {})):
            row["rejected_reasons"].append("AUTHOR_SUPERVISION_FINITE_BUDGET_REQUIRED")
        if candidate["provider"] == "scripted_provider_v2":
            row["rejected_reasons"].append("AUTHOR_SUPERVISION_FIXTURE_FORBIDDEN")
        if not row["rejected_reasons"]:
            selected = row
    snapshot.update(status="AUTHOR_SUPERVISED_SELECTED" if selected else "BLOCKED", selected=selected,
                    mode=MODE, production_eligible=selected is not None, independent_qualification_eligible=False,
                    author_supervision={"admission_contract_version": "author-supervision-admission.v2",
                        "authorization": grant, "authorization_hash": snapshot_hash(grant),
                        "policy_operation_id": snapshot["task"]["policy_snapshot"]["operation_id"],
                        "literary_qualification": "NOT_PROVEN", "author_review_required": True})
    snapshot.pop("decision_id", None)
    snapshot["decision_id"] = "routing-decision:" + snapshot_hash(snapshot)[7:]
    return RoutingDecision(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False))


def verify_frozen_supervision(snapshot: Mapping[str, Any]) -> None:
    task = snapshot["task"]
    if (task["task_type"] == "narrative_semantic_evaluation"
            and task.get("declared_requirements", {}).get("cross_model_review", {}).get("purpose") != "AUTHOR_ADVISORY"):
        raise KernelError("AUTHOR_ADVISORY_PURPOSE_REQUIRED", "Trial evaluation cannot produce strict qualification")
    original = datetime.fromisoformat(snapshot["created_at"])
    if original.tzinfo is None:
        raise KernelError("AUTHOR_SUPERVISION_IDENTITY_MISMATCH", "Frozen selection time is invalid")
    grant = matching_grant(task, now=original)
    receipt = snapshot.get("author_supervision", {})
    candidate = (snapshot.get("selected") or {}).get("candidate", {})
    cross_review = task.get("declared_requirements", {}).get("cross_model_review")
    if cross_review:
        from .cross_model_review import reviewer_rejection
        rejection = reviewer_rejection(cross_review, candidate)
        if rejection:
            raise KernelError(rejection, "Frozen reviewer must retain the exact cross-model constraint")
    if (not grant or snapshot.get("mode") != MODE or snapshot.get("independent_qualification_eligible") is not False
            or receipt.get("authorization_hash") != snapshot_hash(grant) or receipt.get("authorization") != grant
            or receipt.get("policy_operation_id") != task["policy_snapshot"]["operation_id"]
            or candidate.get("candidate_id") != grant["candidate_id"] or candidate.get("model_revision") != grant["model_revision"]
            or snapshot.get("bootstrap_authorization")):
        raise KernelError("AUTHOR_SUPERVISION_IDENTITY_MISMATCH", "Frozen author supervision differs from exact route scope")


def verify_policy_provenance(cursor: Any, snapshot: Mapping[str, Any]) -> None:
    from novel_forge.storage.versioned_policy_repository import policy_hash

    task, policy = snapshot["task"], snapshot["task"]["policy_snapshot"]
    cursor.execute(
        """SELECT v.content, v.content_hash, v.actor_id, o.status
           FROM authority_runtime_policy_version v
           JOIN authority_operation o ON o.operation_id=%s AND o.project_id=v.project_id
           WHERE v.owner='PROVIDER_ROUTING' AND v.project_id=%s AND v.policy_version=%s
             AND o.command_payload #> '{policy}'=v.content
             AND v.actor_id=o.actor_id AND o.definition_name='provider.routing_policy.configure'""",
        [policy["operation_id"], task["project_id"], policy["policy"]["policy_version"]],
    )
    row = cursor.fetchone()
    if (row is None or row[0] != policy["policy"] or row[1] != policy_hash(dict(row[0]))
            or row[1] != policy["policy_hash"] or row[2] != policy["actor_id"] or row[3] != "SUCCEEDED"):
        raise KernelError("AUTHOR_SUPERVISION_POLICY_UNTRUSTED", "Frozen policy lacks its native authenticated decision")


def verify_dispatch_budget(cursor: Any, decision: Mapping[str, Any], *, estimated_tokens: int,
                           amount: Decimal | None, new_dispatch: bool) -> None:
    if decision.get("status") != "AUTHOR_SUPERVISED_SELECTED":
        return
    verify_frozen_supervision(decision)
    verify_policy_provenance(cursor, decision)
    grant = decision["author_supervision"]["authorization"]
    if new_dispatch and datetime.now(timezone.utc) >= datetime.fromisoformat(grant["expires_at"]):
        raise KernelError("AUTHOR_SUPERVISION_EXPIRED", "Expired supervision cannot authorize another dispatch")
    if estimated_tokens > grant["maximum_tokens"] or (amount is not None and amount > Decimal(grant["maximum_amount"])):
        raise KernelError("AUTHOR_SUPERVISION_BUDGET_EXCEEDED", "Exact reservation exceeds the frozen author limit")


def selected_book_supervision(cursor: Any, *, project_id: str, book_id: str) -> dict[str, Any] | None:
    cursor.execute("""SELECT v.content,v.content_hash,v.actor_id,s.selected_by_operation_id
        FROM authority_runtime_policy_selection s JOIN authority_runtime_policy_version v
          USING(owner,project_id,policy_version)
        WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=%s""", [project_id])
    row = cursor.fetchone()
    if row is None:
        return None
    policy = dict(zip(("policy", "policy_hash", "actor_id", "operation_id"), row))
    validate_grants(policy["policy"], author_id=policy["actor_id"])
    grants = [g for g in policy["policy"].get("author_supervised_authorizations", []) if g["book_id"] == book_id]
    books = [b for b in policy["policy"].get("author_supervised_books", []) if b["book_id"] == book_id]
    if not grants and not books:
        return None
    if not books and any(datetime.now(timezone.utc) >= datetime.fromisoformat(g["expires_at"]) for g in grants):
        raise KernelError("AUTHOR_SUPERVISION_EXPIRED", "Book author supervision requires current scoped authorization")
    result = {"mode": MODE, "project_id": project_id, "book_id": book_id,
              "author_id": policy["actor_id"], "policy_snapshot": policy, "literary_qualification": "NOT_PROVEN"}
    verify_book_supervision(cursor, result)
    return result


def verify_book_supervision(cursor: Any, supervision: Mapping[str, Any]) -> None:
    policy = supervision["policy_snapshot"]
    if (supervision.get("mode") != MODE or supervision.get("author_id") != policy["actor_id"]
            or not any(g["book_id"] == supervision["book_id"]
                       for g in [*policy["policy"].get("author_supervised_authorizations", []), *policy["policy"].get("author_supervised_books", [])])):
        raise KernelError("AUTHOR_SUPERVISION_BOOK_SCOPE", "Book decision differs from its author policy")
    validate_grants(policy["policy"], author_id=policy["actor_id"])
    verify_policy_provenance(cursor, {"task": {"project_id": supervision["project_id"], "policy_snapshot": policy}})
