from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from .craft_selection import _hash


def freeze_scope_dispositions(*, evidence: Mapping[str, Any], project_id: str, book_id: str,
                              old_scope: str, new_scope: str, proposal_id: str,
                              decision_asset_version_id: str, decision_content_hash: str,
                              activation_operation_id: str) -> list[dict[str, Any]]:
    values = evidence.get("craft_scope_dispositions", [])
    if not isinstance(values, list) or len(values) > 256:
        raise KernelError("CRAFT_SCOPE_TRANSITION_INVALID", "Plan Change Craft dispositions must be bounded")
    result, seen = [], set()
    fields = {"instance_id", "knowledge_card_asset_version_id", "content_hash", "predecessor_use_id", "acceptance_id", "action", "reason"}
    for value in values:
        if (not isinstance(value, Mapping) or set(value) != fields or any(not isinstance(item, str) or not item.strip() for item in value.values())
            or value["action"] not in {"INHERIT", "REBIND", "END"} or len(value["reason"]) > 512 or value["instance_id"] in seen):
            raise KernelError("CRAFT_SCOPE_TRANSITION_INVALID", "Every instance needs one exact accepted predecessor and an explicit inherit, rebind or end decision")
        seen.add(value["instance_id"])
        result.append({**dict(value), "project_id": project_id, "book_id": book_id,
                       "from_scope_id": old_scope, "to_scope_id": new_scope, "proposal_id": proposal_id,
                       "decision_asset_version_id": decision_asset_version_id, "decision_content_hash": decision_content_hash,
                       "activation_operation_id": activation_operation_id})
    return result


def approved_arc_scope_transitions(database_url: str, *, project_id: str, book_id: str,
                                   arc_plan_version_ids: list[str]) -> list[dict[str, Any]]:
    if not arc_plan_version_ids:
        return []
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute(
            """SELECT proposal.proposal_id, proposal.target_asset_version_id, proposal.proposed_asset_version_id,
                      proposal.activation_operation_id, decision.evidence, output.asset_version_id,
                      version.content_hash, version.content
               FROM authority_plan_change_proposal proposal
               JOIN authority_plan_change_decision decision ON decision.proposal_id=proposal.proposal_id
               JOIN authority_operation operation ON operation.operation_id=decision.decision_operation_id
               JOIN authority_operation_output_asset output ON output.operation_id=decision.decision_operation_id
                 AND output.output_key='plan_change.decision'
               JOIN authority_asset_version version ON version.asset_version_id=output.asset_version_id
               WHERE proposal.project_id=%s AND proposal.book_id=%s AND proposal.status='ACTIVE'
                 AND proposal.proposed_asset_version_id=ANY(%s) AND proposal.target_contract_type='ARC'
                 AND decision.project_id=proposal.project_id AND decision.decision='APPROVED'
                 AND proposal.approval_operation_id=decision.decision_operation_id AND operation.status='SUCCEEDED'
               ORDER BY proposal.proposal_id""",
            [project_id, book_id, arc_plan_version_ids],
        )
        rows = uow.cursor.fetchall()
    result = []
    for proposal, old, new, activation, evidence, asset, content_hash, content in rows:
        if content_hash != _hash(content) or content.get("evidence") != evidence or content.get("proposal_id") != proposal:
            raise KernelError("CRAFT_SCOPE_TRANSITION_DRIFT", "Scope inheritance must match its exact immutable Plan Change approval")
        result.extend(freeze_scope_dispositions(evidence=evidence, project_id=project_id, book_id=book_id,
            old_scope=old, new_scope=new, proposal_id=proposal, decision_asset_version_id=asset,
            decision_content_hash=content_hash, activation_operation_id=activation))
    if len(result) > 256:
        raise KernelError("CRAFT_SCOPE_TRANSITION_BUDGET_EXHAUSTED", "Approved scope evidence exceeds the supported bounded input")
    return result


def validate_scope_transition_decision(database_url: str, *, proposal: Mapping[str, Any], evidence: Mapping[str, Any]) -> None:
    if not evidence.get("craft_scope_dispositions"):
        return
    if proposal["target_contract_type"] != "ARC":
        raise KernelError("CRAFT_SCOPE_TRANSITION_INVALID", "This policy supports explicit dispositions for an approved Arc version replacement")
    dispositions = freeze_scope_dispositions(evidence=evidence, project_id=proposal["project_id"], book_id=proposal["book_id"],
        old_scope=proposal["target_asset_version_id"], new_scope=proposal["proposed_asset_version_id"],
        proposal_id=proposal["proposal_id"], decision_asset_version_id="pending", decision_content_hash="pending", activation_operation_id="pending")
    from .runtime_usage import list_accepted_craft_usage
    from .craft_usage import realized_instances, usage_is_open
    history = list_accepted_craft_usage(database_url, project_id=proposal["project_id"], book_id=proposal["book_id"], include_continuing=True)
    groups = {}
    for row in history:
        usage = row.get("usage") or {}
        if usage.get("scope_id") == proposal["target_asset_version_id"]:
            groups.setdefault(usage["instance_id"], []).append(row)
    latest = {identity: realized_instances(rows, rows[0]["usage"]["type_policy"]).get(identity) for identity, rows in groups.items()}
    for disposition in dispositions:
        source = latest.get(disposition["instance_id"])
        if (not source or not usage_is_open(source["usage"])
            or any(disposition[key] != source[key] for key in ("knowledge_card_asset_version_id", "content_hash", "acceptance_id"))
            or disposition["predecessor_use_id"] != source["use_id"]):
            raise KernelError("CRAFT_SCOPE_ACCEPTED_PREDECESSOR_REQUIRED", "Scope approval requires the latest successful open instance in the exact accepted source Arc")
