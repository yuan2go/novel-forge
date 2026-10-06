from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from novel_forge.modules.command_kernel.errors import KernelError

from .cost_routing import RoutingDecision, snapshot_hash


VERSION = "creative-execution-template.v3"
MODE = "CREATIVE_VALIDATION"
RESOURCE_VERSION = "billing-channel-resources.v1"
BOOK_USAGE_SQL = """(e.request_payload #>> '{_production_execution,book_id}'=%s
    OR r.evidence->>'work_id'=%s
    OR r.evidence #>> '{creative_experiment,authorization,book_id}'=%s)"""
_Identity = Annotated[str, Field(min_length=1)]


class PaidResourceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    account_ref: _Identity
    currency: Literal["USD"]
    maximum_amount: Annotated[str, Field(pattern=r"^[0-9]+(\.[0-9]+)?$")]
    authorization_ref: _Identity


class RepairRoutingConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["native-repair-routing.v1"]
    max_same_route_repairs: Annotated[int, Field(ge=0, le=2)]


class ExecutionTemplateConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["creative-execution-template.v1", "creative-execution-template.v2", "creative-execution-template.v3"]
    book_id: _Identity
    mode: Literal["CREATIVE_VALIDATION", "STRICT_PRODUCTION"]
    allowed_candidates: Annotated[list[_Identity], Field(min_length=1, json_schema_extra={"uniqueItems": True})]
    member_authorization_ref: _Identity
    deepseek: PaidResourceConfiguration | None
    optional_enhancements: Annotated[list[_Identity], Field(json_schema_extra={"uniqueItems": True})]
    require_literary_qualification: bool
    require_independent_review: bool
    require_pack_human_approval: bool
    repair_routing: RepairRoutingConfiguration | None = None
    world_future_preparation: Literal["REQUIRED", "OPTIONAL", "DISABLED"] | None = None


TEMPLATE_SCHEMA = ExecutionTemplateConfiguration.model_json_schema()


def load_paid_configuration(values: Mapping[str, str]) -> tuple[dict[str, Any] | None, str]:
    source = str(values.get("NOVEL_FORGE_DEEPSEEK_BUDGET_TEMPLATE_FILE") or "").strip()
    if not source:
        return None, "PAID_TEMPLATE_NOT_CONFIGURED"
    try:
        paid = json.loads(Path(source).read_text())
        if paid is None:
            return None, "PAID_TEMPLATE_NOT_CONFIGURED"
        PaidResourceConfiguration.model_validate(paid)
        if Decimal(paid["maximum_amount"]) <= 0:
            return None, "PAID_TEMPLATE_AMOUNT_INVALID"
    except (OSError, ValueError):
        return None, "PAID_TEMPLATE_UNAVAILABLE_OR_INVALID"
    if paid["account_ref"] != values.get("NOVEL_FORGE_DEEPSEEK_BILLING_ACCOUNT_REF"):
        return None, "PAID_BILLING_ACCOUNT_DRIFT"
    return paid, ""


def validate_templates(content: Mapping[str, Any]) -> None:
    books = set()
    for value in content.get("execution_templates", []):
        try:
            ExecutionTemplateConfiguration.model_validate(value)
        except ValidationError as error:
            raise KernelError("EXECUTION_TEMPLATE_INVALID", "Template violates its closed typed contract") from error
        if any(len(value[key]) != len(set(value[key])) for key in ("allowed_candidates", "optional_enhancements")):
            raise KernelError("EXECUTION_TEMPLATE_DUPLICATE_ENTRY", value["book_id"])
        if value["book_id"] in books:
            raise KernelError("EXECUTION_TEMPLATE_DUPLICATE", value["book_id"])
        books.add(value["book_id"])
        if value["mode"] == "STRICT_PRODUCTION" and not value["require_literary_qualification"]:
            raise KernelError("STRICT_TEMPLATE_QUALIFICATION_REQUIRED", value["book_id"])
        if (value["version"] == "creative-execution-template.v1" and value.get("repair_routing") is not None
                or value["version"] in {"creative-execution-template.v2", VERSION} and value.get("repair_routing") is None):
            raise KernelError("EXECUTION_TEMPLATE_REPAIR_VERSION_INVALID", value["book_id"])
        if ((value['version'] == VERSION) != (value.get('world_future_preparation') is not None)
                or value['mode'] == 'STRICT_PRODUCTION' and value.get('world_future_preparation', 'REQUIRED') != 'REQUIRED'):
            raise KernelError('EXECUTION_TEMPLATE_WORLD_POLICY_INVALID', value['book_id'])
        paid = value["deepseek"]
        if paid is not None and Decimal(paid["maximum_amount"]) <= 0:
            raise KernelError("PAID_TEMPLATE_AMOUNT_INVALID", value["book_id"])


def selected_template(policy: Mapping[str, Any], book_id: str) -> dict[str, Any] | None:
    validate_templates(policy)
    return next((dict(value) for value in policy.get("execution_templates", [])
                 if value["book_id"] == book_id), None)


def decision_template(decision: Mapping[str, Any]) -> dict[str, Any] | None:
    task = decision.get("task", {})
    return selected_template(task.get("policy_snapshot", {}).get("policy", {}), task.get("work_id", ""))


def verify_template_provenance(cursor: Any, decision: Mapping[str, Any]) -> dict[str, Any] | None:
    template = decision_template(decision)
    if template is None:
        return None
    from novel_forge.storage.versioned_policy_repository import policy_hash

    task = decision["task"]
    policy = task["policy_snapshot"]
    cursor.execute("""SELECT v.content,v.content_hash,v.actor_id,v.created_by_operation_id,op.status
        FROM authority_runtime_policy_version v
        JOIN authority_operation op ON op.operation_id=v.created_by_operation_id
          AND op.project_id=v.project_id
        WHERE v.owner='PROVIDER_ROUTING' AND v.project_id=%s AND v.policy_version=%s""",
        [task["project_id"], policy["policy"]["policy_version"]])
    row = cursor.fetchone()
    if (not row or row[0] != policy["policy"] or row[1] != policy_hash(row[0])
            or row[1] != policy.get("policy_hash") or row[2] != policy.get("actor_id")
            or row[3] != policy.get("operation_id") or row[4] != "SUCCEEDED"):
        raise KernelError("EXECUTION_TEMPLATE_PROVENANCE_INVALID", task["work_id"])
    return template


def paid_usage(cursor: Any, *, project_id: str, book_id: str, exclude_key: str = "") -> Decimal:
    cursor.execute(f"""SELECT COALESCE(sum(CASE WHEN r.status='SETTLED'
        THEN r.settled_amount ELSE GREATEST(r.reserved_amount,
            COALESCE((r.evidence->>'actual_amount')::numeric,0)) END),0)
        FROM authority_budget_reservation r
        JOIN authority_external_effect e USING(external_effect_id)
        WHERE r.project_id=%s AND r.provider='deepseek' AND r.currency='USD'
          AND r.accounting_basis='PRICED' AND r.status IN ('RESERVED','HELD_UNKNOWN','SETTLED')
          AND {BOOK_USAGE_SQL}
          AND r.stable_idempotency_key<>%s""", [project_id, book_id, book_id, book_id, exclude_key])
    return Decimal(cursor.fetchone()[0])


def validate_template_succession(cursor: Any, *, project_id: str, content: Mapping[str, Any]) -> None:
    validate_templates(content)
    cursor.execute("SELECT content FROM authority_runtime_policy_version WHERE owner='PROVIDER_ROUTING' AND project_id=%s",
                   [project_id])
    history = [row[0] for row in cursor.fetchall()]
    for template in content.get("execution_templates", []):
        paid = template["deepseek"]
        for prior in history:
            old = selected_template(prior, template["book_id"])
            if not old or not old["deepseek"] or not paid:
                continue
            if (paid["account_ref"] != old["deepseek"]["account_ref"]
                    or paid["currency"] != old["deepseek"]["currency"]
                    or Decimal(paid["maximum_amount"]) > Decimal(old["deepseek"]["maximum_amount"])):
                raise KernelError("PAID_TEMPLATE_SUCCESSOR_EXPANSION_FORBIDDEN", template["book_id"])


def enforce_template_resources(cursor: Any, request: Any, amount: Decimal | None) -> bool:
    cursor.execute("SELECT request_payload #> '{_production_execution,capability_runtime,routing_decision}' FROM authority_external_effect WHERE external_effect_id=%s AND project_id=%s",
                   [request.external_effect_id, request.project_id])
    row = cursor.fetchone()
    decision = row[0] if row else None
    if not decision:
        return False
    template = verify_template_provenance(cursor, decision)
    if template is None:
        return False
    candidate = decision.get("selected", {}).get("candidate", {})
    if (decision.get("status") != "SELECTED" or decision["task"]["work_id"] != request.work_id
            or decision["task"]["operation_id"] != request.operation_id
            or candidate.get("candidate_id") not in template["allowed_candidates"]
            or candidate.get("provider") != request.provider or candidate.get("model") != request.model_id):
        raise KernelError("EXECUTION_TEMPLATE_SCOPE_MISMATCH", request.work_id)
    if request.provider == "codex-cli":
        if (amount is not None or request.accounting_basis != "ACCOUNT_ENTITLEMENT"
                or request.cost_authorization_ref != template["member_authorization_ref"]
                or candidate.get("authorization_ref") != request.cost_authorization_ref):
            raise KernelError("MEMBERSHIP_BILLING_IDENTITY_MISMATCH", request.work_id)
    elif request.provider == "deepseek":
        paid = template["deepseek"]
        if (not paid or amount is None or request.accounting_basis != "PRICED"
                or request.currency != paid["currency"]
                or decision["task"].get("budget_snapshot", {}).get("candidates", {}).get(candidate["candidate_id"], {}).get("account_ref") != paid["account_ref"]):
            raise KernelError("PAID_TEMPLATE_AUTHORIZATION_REQUIRED", request.work_id)
        used = paid_usage(cursor, project_id=request.project_id, book_id=request.work_id,
                          exclude_key=request.stable_idempotency_key)
        if used + amount > Decimal(paid["maximum_amount"]):
            raise KernelError("PAID_WORK_BUDGET_EXHAUSTED", request.work_id)
    else:
        raise KernelError("EXECUTION_TEMPLATE_PROVIDER_UNAUTHORIZED", request.provider)
    return True


def template_decision(decision: RoutingDecision) -> RoutingDecision:
    snapshot = decision.to_dict()
    template = decision_template(snapshot)
    if template is None:
        return decision
    selected = None
    plan = snapshot["task"].get("budget_snapshot", {}).get("work_resource_plan")
    pressure = False
    if plan is not None and template["deepseek"]:
        paid = plan["deepseek"]
        calls = plan["provider_calls_range"]
        if calls and paid.get("remaining_cost_range") is None:
            costs = [Decimal(row["reservation_upper_bound"]) for row in snapshot["candidates"]
                     if row["candidate"]["provider"] == "deepseek" and row["reservation_upper_bound"] is not None]
            if costs:
                paid["remaining_cost_range"] = [str(max(costs) * count) for count in calls]
                paid["estimate_basis"] = "current rendered request upper bound; future context and repair demand may differ"
        pressure = bool(paid.get("remaining_cost_range") and Decimal(paid["remaining_cost_range"][-1]) > Decimal(paid["remaining_amount"]))
        paid["completion_headroom_pressure"] = pressure
    relax = template["mode"] == MODE and not template["require_literary_qualification"]
    for row in snapshot["candidates"]:
        candidate = row["candidate"]
        row["strict_rejected_reasons"] = list(row["rejected_reasons"])
        if candidate["candidate_id"] not in template["allowed_candidates"]:
            row["rejected_reasons"].append("TEMPLATE_MODEL_UNAUTHORIZED")
        if relax:
            row["rejected_reasons"] = [reason for reason in row["rejected_reasons"]
                                       if reason not in {"QUALITY_FLOOR_NOT_MET", "BENCHMARK_INSUFFICIENT"}]
        if relax and template["version"] in {"creative-execution-template.v2", VERSION}:
            from .planning_repair_routing import repair_route_admission
            repair = repair_route_admission(snapshot, row, template)
            if repair is not None:
                row["native_repair_admission"] = repair
                row["rejected_reasons"] = [reason for reason in row["rejected_reasons"]
                    if reason not in repair["superseded_route_reasons"]]
        if candidate["provider"] == "codex-cli" and candidate["authorization_ref"] != template["member_authorization_ref"]:
            row["rejected_reasons"].append("MEMBERSHIP_BILLING_IDENTITY_MISMATCH")
        if (pressure and snapshot["task"]["task_type"] in template["optional_enhancements"]
                and candidate["provider"] == "deepseek"):
            row["rejected_reasons"].append("OPTIONAL_ENHANCEMENT_DEFERRED_FOR_COMPLETION")
        if not row["rejected_reasons"]:
            if selected is None or (candidate["provider"] == "codex-cli" and selected["candidate"]["provider"] != "codex-cli"):
                selected = row
    snapshot.update(status="SELECTED" if selected else "BLOCKED", selected=selected,
                    mode=template["mode"], resource_control_version=RESOURCE_VERSION,
                    internal_production_eligible=selected is not None,
                    independent_qualification_eligible=not relax,
                    strict_certification_eligible=template["mode"] == "STRICT_PRODUCTION",
                    checks={"literary_model_qualification": {
                        "status": "NOT_RUN" if relax else "REQUIRED",
                        "reason": "creative validation template excludes model literary calibration" if relax else "strict or explicit validation objective"}},
                    resource_actions={"paid_completion_pressure": pressure,
                        "membership_preferred_for_substitutable_work": True,
                        "deferred_paid_optional_tasks": template["optional_enhancements"] if pressure else [],
                        "work_scope_changed": False, "quality_floor_changed": False},
                    execution_template_hash=snapshot_hash(template))
    snapshot.pop("decision_id", None)
    snapshot["decision_id"] = "routing-decision:" + snapshot_hash(snapshot)[7:]
    return RoutingDecision(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, allow_nan=False))


def selected_book_template(cursor: Any, *, project_id: str, book_id: str, allow_literary_required: bool = False) -> dict[str, Any] | None:
    cursor.execute("""SELECT v.content,v.content_hash,v.actor_id,v.created_by_operation_id
        FROM authority_runtime_policy_selection s JOIN authority_runtime_policy_version v USING(owner,project_id,policy_version)
        WHERE s.owner='PROVIDER_ROUTING' AND s.project_id=%s""", [project_id])
    row = cursor.fetchone()
    snapshot = dict(zip(("policy", "policy_hash", "actor_id", "operation_id"), row)) if row else {}
    if not snapshot:
        return None
    decision = {"task": {"project_id": project_id, "work_id": book_id, "policy_snapshot": snapshot}}
    template = verify_template_provenance(cursor, decision)
    if not template or template["mode"] != MODE or (template["require_literary_qualification"] and not allow_literary_required):
        return None
    return {"version": "creative-book-admission.v1", "mode": MODE,
            "project_id": project_id, "book_id": book_id, "policy_snapshot": snapshot,
            "literary_qualification": "REQUIRED" if template["require_literary_qualification"] else "NOT_RUN"}


def verify_book_template(cursor: Any, admission: Mapping[str, Any]) -> None:
    template = verify_template_provenance(cursor, {"task": {"project_id": admission["project_id"],
        "work_id": admission["book_id"], "policy_snapshot": admission["policy_snapshot"]}})
    if not template or template["mode"] != MODE or template["require_literary_qualification"] or admission.get("mode") != MODE:
        raise KernelError("CREATIVE_BOOK_POLICY_INVALID", admission["book_id"])
