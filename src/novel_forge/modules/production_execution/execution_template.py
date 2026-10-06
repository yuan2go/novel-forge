from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from novel_forge.modules.command_kernel.errors import KernelError

from .cost_routing import RoutingDecision, snapshot_hash


VERSION = "creative-execution-template.v1"
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


class ExecutionTemplateConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["creative-execution-template.v1"]
    book_id: _Identity
    mode: Literal["CREATIVE_VALIDATION", "STRICT_PRODUCTION"]
    allowed_candidates: Annotated[list[_Identity], Field(min_length=1, json_schema_extra={"uniqueItems": True})]
    member_authorization_ref: _Identity
    deepseek: PaidResourceConfiguration | None
    optional_enhancements: Annotated[list[_Identity], Field(json_schema_extra={"uniqueItems": True})]
    require_literary_qualification: bool
    require_independent_review: bool
    require_pack_human_approval: bool


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


def configure_execution_template(settings: Any, args: Any) -> dict[str, Any]:
    import os
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
    from novel_forge.modules.production_execution.codex_model_catalog import parse_codex_model_catalog
    from novel_forge.modules.production_execution.execution_template import validate_templates
    from novel_forge.modules.production_execution.membership_identity import observe_membership_identity
    from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.execute", args.project_id)
    if os.environ.get("NOVEL_FORGE_RESOURCE_CONTROL_VERSION") != "billing-channel-resources.v1":
        raise ValueError("BILLING_CHANNEL_RESOURCE_CONFIGURATION_REQUIRED")
    identity = observe_membership_identity(os.environ.get("NOVEL_FORGE_CODEX_HOME", ""))
    if identity["account_ref"] != os.environ.get("NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF"):
        raise ValueError("CODEX_MEMBERSHIP_IDENTITY_DRIFT")
    authorization = os.environ.get("NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF", "").strip()
    if not authorization:
        raise ValueError("CODEX_MEMBERSHIP_AUTHORIZATION_REQUIRED")
    models = parse_codex_model_catalog(os.environ.get("NOVEL_FORGE_CODEX_ROUTER_MODELS", ""))
    value = json.loads(args.template_file.read_text())
    value.update(book_id=args.book_id, member_authorization_ref=authorization,
        allowed_candidates=[f"codex-cli:{model['model']}:{model['reasoning']}" for model in models if model["role"] in {"PRIMARY", "REFERENCE"}])
    from novel_forge.modules.production_execution.execution_template import load_paid_configuration
    if value.get("deepseek") is not None:
        raise ValueError("PAID_TEMPLATE_MUST_INHERIT_CONFIGURED_AUTHORIZATION")
    paid, paid_unavailable = load_paid_configuration(os.environ)
    if paid is not None:
        value["deepseek"] = paid
        from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
        value["allowed_candidates"].extend(model.candidate_id for model in deepseek_candidates(available=True))
    validate_templates({"execution_templates": [value]})
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [args.project_id, args.book_id])
        if uow.cursor.fetchone() != (args.workspace_id,):
            raise ValueError("EXECUTION_TEMPLATE_BOOK_SCOPE_INVALID")
    prior = PostgresRoutingRegistry(settings.database_url).policy(args.project_id)
    content = dict(prior.get("policy") or {"task_overrides": [], "reason": "configured template for internal creative validation"})
    content.update(policy_version=args.policy_version, reason="native creation template; paid channel: " + (paid_unavailable or "AUTHORIZED_CONFIGURATION"), execution_templates=[
        item for item in content.get("execution_templates", []) if item["book_id"] != args.book_id] + [value])
    build_id, sha = authority_release_identity()
    return configure_owned_policy(database_url=settings.database_url, owner="PROVIDER_ROUTING", content=content,
        project_id=args.project_id, workspace_id=args.workspace_id, idempotency_key=args.idempotency_key,
        trace_id="trace:" + args.idempotency_key, correlation_id=args.book_id,
        application_build_id=build_id, commit_sha=sha, principal=principal)
