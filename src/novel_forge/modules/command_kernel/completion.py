from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.lifecycle import (
    require_attempt_transition,
    require_operation_transition,
)
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


@dataclass(frozen=True)
class CompletionCommandContext:
    project_id: str
    actor_id: str
    trace_id: str
    correlation_id: str
    causation_id: str = ""


def evaluate_completion_contract(
    database_url: str,
    operation_id: str,
    project_id: str,
) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        operation = uow.repositories.completion_contracts.operation(
            operation_id,
            project_id,
            lock=False,
        )
        return evaluate_completion_in_uow(uow, operation)


def evaluate_completion_in_uow(uow: AuthorityUnitOfWork, operation: dict[str, Any]) -> dict[str, Any]:
    repository = uow.repositories.completion_contracts
    contract = operation["contract"] or {}
    if not isinstance(contract, dict):
        raise KernelError(
            "COMPLETION_CONTRACT_INVALID",
            "frozen completion contract must be an object",
        )
    missing: list[str] = []
    failed: list[str] = []

    child_states = repository.child_states(operation["operation_id"])
    for requirement in contract.get("required_child_operations", []):
        if not isinstance(requirement, dict):
            raise _invalid("required_child_operations")
        definition_name = str(requirement.get("definition_name") or "")
        allowed = set(requirement.get("allowed_states") or ["SUCCEEDED"])
        if not definition_name or not any(
            name == definition_name and status in allowed for name, status in child_states
        ):
            missing.append(f"child:{definition_name}")

    approvals = repository.approval_states(operation["operation_id"])
    for requirement in contract.get("required_approvals", []):
        key = _requirement_key(requirement, "approval_key")
        status = approvals.get(key)
        if status == "REJECTED":
            failed.append(f"approval:{key}")
        elif status != "APPROVED":
            missing.append(f"approval:{key}")

    gates = repository.gate_states(operation["operation_id"])
    for requirement in contract.get("required_gates", []):
        key = _requirement_key(requirement, "gate_key")
        status = gates.get(key)
        if status == "FAILED":
            failed.append(f"gate:{key}")
        elif status != "PASSED":
            missing.append(f"gate:{key}")

    effect_states = repository.effect_states(operation["operation_id"])
    from novel_forge.modules.command_kernel.retained_completion import retained_completion_evidence

    retained_effects = retained_completion_evidence(uow, operation, effect_states)
    completion_effects = effect_states + [(item["capability"], item["status"]) for item in retained_effects]
    effect_unknown = False
    optional_memo = False
    if any(item.get("capability") == "model.memo" for item in contract.get("required_external_effects", [])):
        from novel_forge.modules.chapter_authority.creative_memo import optional_memo_completion
        optional_memo = optional_memo_completion(uow, operation)
    for requirement in contract.get("required_external_effects", []):
        if not isinstance(requirement, dict):
            raise _invalid("required_external_effects")
        capability = str(requirement.get("capability") or "")
        if capability == "model.memo" and optional_memo:
            continue
        allowed = set(requirement.get("allowed_states") or ["SUCCEEDED"])
        matching = [status for current, status in completion_effects if current == capability]
        if any(status in {"UNKNOWN", "RECONCILIATION_REQUIRED"} for status in matching):
            effect_unknown = True
        if not any(status in allowed for status in matching):
            missing.append(f"effect:{capability}")

    aggregate_states = repository.aggregate_states(operation["operation_id"])
    for requirement in contract.get("required_aggregate_states", []):
        if not isinstance(requirement, dict):
            raise _invalid("required_aggregate_states")
        aggregate_type = str(requirement.get("aggregate_type") or "")
        aggregate_id = str(requirement.get("aggregate_id") or "")
        allowed = set(requirement.get("allowed_states") or [])
        if not aggregate_type or not aggregate_id or not allowed:
            raise _invalid("required_aggregate_states")
        if not any(
            current_type == aggregate_type
            and current_id == aggregate_id
            and state in allowed
            for current_type, current_id, state in aggregate_states
        ):
            missing.append(f"aggregate:{aggregate_type}:{aggregate_id}")

    asset_version_ids: list[str] = []
    for requirement in contract.get("required_asset_selectors", []):
        if not isinstance(requirement, dict):
            raise _invalid("required_asset_selectors")
        selector = str(requirement.get("selector") or requirement.get("asset_type") or "")
        assets = repository.qualifying_assets(
            operation["operation_id"],
            operation["project_id"],
            selector,
            output_key=str(requirement.get("output_key") or ""),
            role=str(requirement.get("role") or ""),
        )
        allowed_lifecycles = set(
            requirement.get("allowed_lifecycles")
            or [requirement.get("lifecycle", "ACTIVE")]
        )
        allowed_eligibility = set(
            requirement.get("allowed_eligibility")
            or [requirement.get("eligibility", "ELIGIBLE")]
        )
        allowed_governance = set(
            requirement.get("allowed_governance")
            or [requirement.get("governance", "CLEAR")]
        )
        matching = [
            asset
            for asset in assets
            if asset["lifecycle"] in allowed_lifecycles
            and asset["eligibility"] in allowed_eligibility
            and asset["governance"] in allowed_governance
        ]
        if len(matching) < int(requirement.get("min_count", 1)):
            missing.append(f"asset:{selector}")
        asset_version_ids.extend(asset["asset_version_id"] for asset in matching)

    qualification_states = repository.qualifications(asset_version_ids)
    for requirement in contract.get("required_qualifications", []):
        requested = _requirement_key(requirement, "decision")
        normalized = "ELIGIBLE" if requested == "production_eligible" else requested
        if not asset_version_ids or any(
            qualification_states.get(asset_version_id) != normalized
            for asset_version_id in asset_version_ids
        ):
            missing.append(f"qualification:{requested}")

    blob_states = repository.blob_states(asset_version_ids)
    for requirement in contract.get("required_blobs", []):
        required_status = _requirement_key(requirement, "status")
        role = str(requirement.get("role") or "") if isinstance(requirement, dict) else ""
        min_count = int(requirement.get("min_count", 1)) if isinstance(requirement, dict) else 1
        matching_blobs = [
            blob
            for blob in blob_states
            if blob["status"] == required_status and (not role or blob["role"] == role)
        ]
        if len(matching_blobs) < min_count:
            missing.append(f"blob:{required_status}")

    required_evidence = set(contract.get("required_evidence", []))
    if "trace" in required_evidence and not operation["trace_id"]:
        missing.append("evidence:trace")
    if "audit" in required_evidence and not repository.has_audit(operation["operation_id"]):
        missing.append("evidence:audit")
    audit_actions = repository.audit_actions(operation["operation_id"])
    for action in contract.get("required_audit_actions", []):
        if not isinstance(action, str) or not action:
            raise _invalid("required_audit_actions")
        if action not in audit_actions:
            missing.append(f"audit:{action}")
    provider_used = bool(effect_states) or bool(
        (operation.get("definition_snapshot") or {}).get("external_capabilities") and not optional_memo
    )
    if (
        "cost_when_provider_used" in required_evidence
        and provider_used
        and not repository.has_cost(operation["operation_id"])
        and not retained_effects
    ):
        missing.append("evidence:cost")

    topics = repository.outbox_topics(operation["project_id"], operation["operation_id"])
    for topic in contract.get("required_outbox_events", []):
        if topic not in topics:
            missing.append(f"outbox:{topic}")

    target_status = _target_status(missing, failed, effect_unknown)
    return {
        "operation_id": operation["operation_id"],
        "satisfied": not missing and not failed,
        "target_status": target_status,
        "missing": sorted(set(missing)),
        "failed": sorted(set(failed)),
        "contract": contract,
    }


def finalize_operation_completion(
    database_url: str,
    context: CompletionCommandContext,
    *,
    operation_id: str,
    expected_status: str,
    expected_version: int,
    require_uncancelled: bool = False,
) -> dict[str, Any]:
    _validate_context(context)
    with AuthorityUnitOfWork(database_url) as uow:
        if require_uncancelled:
            uow.cursor.execute("""SELECT COALESCE(NULLIF(root_operation_id,''),operation_id)
                FROM authority_operation WHERE operation_id=%s AND project_id=%s""",
                [operation_id, context.project_id])
            owner = uow.cursor.fetchone()
            if owner is None:
                raise KernelError("OPERATION_NOT_FOUND", "completion owner is missing")
            uow.cursor.execute("SELECT operation_id FROM authority_operation WHERE operation_id=%s AND project_id=%s FOR UPDATE",
                [owner[0], context.project_id])
            if uow.cursor.fetchone() is None:
                raise KernelError("OPERATION_NOT_FOUND", "completion Root is missing")
            uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=ANY(%s))",
                [[operation_id, owner[0]]])
            if uow.cursor.fetchone()[0]:
                raise KernelError("OPERATION_CANCELLATION_ACTIVE", "Cancelled submitted work cannot be automatically finalized")
        operation = uow.repositories.completion_contracts.operation(
            operation_id,
            context.project_id,
            lock=True,
        )
        if operation["version"] != expected_version:
            raise KernelError("OPERATION_VERSION_CONFLICT", "completion version is stale")
        if operation["status"] != expected_status:
            raise KernelError("OPERATION_STATUS_CONFLICT", "completion status is stale")
        evaluation = evaluate_completion_in_uow(uow, operation)
        target = evaluation["target_status"]
        if target == expected_status:
            return {**evaluation, "status": target, "version": expected_version, "replayed": True}
        require_operation_transition(expected_status, target)
        submitted_attempt = uow.repositories.attempt_runtime.submitted_for_operation(
            operation_id,
            context.project_id,
        )
        if submitted_attempt is not None and target in {"SUCCEEDED", "FAILED_FINAL"}:
            require_attempt_transition(submitted_attempt["status"], target)
            uow.repositories.attempt_runtime.transition(
                submitted_attempt["attempt_id"],
                submitted_attempt["status"],
                target,
            )
            uow.repositories.runtime_evidence.record_attempt_transition(
                {
                    "attempt_id": submitted_attempt["attempt_id"],
                    "operation_id": operation_id,
                    "project_id": context.project_id,
                    "expected_status": submitted_attempt["status"],
                    "target_status": target,
                    "worker_id": submitted_attempt["worker_id"],
                    "fencing_token": None,
                    "trace_id": context.trace_id,
                    "correlation_id": context.correlation_id,
                    "causation_id": context.causation_id,
                    "event_id": str(uuid4()),
                    "audit_id": str(uuid4()),
                    "outbox_id": str(uuid4()),
                }
            )
        result = uow.repositories.operation_lifecycle.compare_and_set(
            {
                "operation_id": operation_id,
                "project_id": context.project_id,
                "expected_version": expected_version,
                "expected_status": expected_status,
                "target_status": target,
            }
        )
        uow.repositories.runtime_evidence.record_operation_transition(
            {
                "operation_id": operation_id,
                "project_id": context.project_id,
                "expected_version": expected_version,
                "expected_status": expected_status,
                "target_status": target,
                "actor_id": context.actor_id,
                "reason": "completion contract evaluated",
                "trace_id": context.trace_id,
                "correlation_id": context.correlation_id,
                "causation_id": context.causation_id,
                "version": result["version"],
                "event_id": str(uuid4()),
                "audit_id": str(uuid4()),
                "outbox_id": str(uuid4()),
            }
        )
        uow.commit()
    return {**evaluation, **result, "replayed": False}


def _target_status(missing: list[str], failed: list[str], effect_unknown: bool) -> str:
    if failed:
        return "FAILED_FINAL"
    if effect_unknown:
        return "RECONCILIATION_REQUIRED"
    if any(item.startswith("approval:") for item in missing):
        return "WAITING_APPROVAL"
    if any(item.startswith("child:") for item in missing):
        return "WAITING_CHILDREN"
    if any(item.startswith("effect:") for item in missing):
        return "WAITING_EXTERNAL_RESULT"
    if missing:
        return "WAITING_GATE"
    return "SUCCEEDED"


def _requirement_key(requirement: Any, field: str) -> str:
    if isinstance(requirement, str) and requirement:
        return requirement
    if isinstance(requirement, dict) and str(requirement.get(field) or ""):
        return str(requirement[field])
    raise _invalid(field)


def _invalid(section: str) -> KernelError:
    return KernelError(
        "COMPLETION_CONTRACT_INVALID",
        f"completion contract section is invalid: {section}",
    )


def _validate_context(context: CompletionCommandContext) -> None:
    if not all((context.project_id, context.actor_id, context.trace_id, context.correlation_id)):
        raise KernelError("KERNEL_COMMAND_INVALID", "completion context is incomplete")
