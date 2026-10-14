from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.command_kernel.errors import KernelError
from .harness import AgentHarnessStatus, canonical_execution_contract_hash, transcript_payload_hash


@dataclass(frozen=True, slots=True)
class AgentUnsentRecoveryRequest:
    project_id: str
    source_session_id: str
    expected_operation_version: int
    expected_session_version: int
    expected_request_digest: str
    target_release_sha: str
    reason: str
    reference_prose: bool = False


@dataclass(frozen=True, slots=True)
class AgentReferenceRecoveryRequest(AgentUnsentRecoveryRequest):
    reference_prose: bool = True


def recovery_session_identity(request, operation_id):
    prefix = "agent-reference-successor" if isinstance(request, AgentReferenceRecoveryRequest) else "agent-unsent-successor"
    return f"{prefix}:{operation_id}"


def require_unsent_source(uow: Any, request: AgentUnsentRecoveryRequest,
                          principal: Principal) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    if isinstance(request, AgentReferenceRecoveryRequest):
        return require_empty_reference_source(uow, request, principal)
    principal.require("agent.authority.admin", request.project_id)
    if principal.principal_type != PrincipalType.LOCAL_OPERATOR or not request.reason.strip():
        raise KernelError("AGENT_UNSENT_RECOVERY_AUTHORIZATION_REQUIRED",
                          "Known-unsent Agent recovery requires a trusted local operator and reason")
    uow.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o
        JOIN authority_agent_harness_session s USING(operation_id)
        WHERE s.agent_session_id=%s AND o.project_id=%s FOR UPDATE OF o""",
        [request.source_session_id, request.project_id])
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("AGENT_UNSENT_RECOVERY_SOURCE_MISSING", "Scoped source session does not exist")
    operation = dict(row[0])
    source = uow.repositories.agent_runtime.require_harness_session(request.source_session_id, lock=True)
    command = dict(operation["command_payload"])
    contract = dict(source.execution_contract)
    if (operation["status"] != "FAILED_FINAL" or source.status != AgentHarnessStatus.FAILED
            or operation["definition_name"] != "agent.session.execute"
            or operation["parent_operation_id"] or operation["root_operation_id"] != operation["operation_id"]
            or operation["actor_id"] != principal.principal_id
            or operation["version"] != request.expected_operation_version
            or source.version != request.expected_session_version
            or operation["request_digest"] != request.expected_request_digest
            or source.project_id != request.project_id
            or source.workspace_id != operation["workspace_id"]
            or contract.get("contract_version") != "agent-session-execution-contract.v1"
            or canonical_execution_contract_hash(contract) != source.execution_contract_hash
            or command.get("execution_contract") != contract
            or command.get("execution_contract_hash") != source.execution_contract_hash
            or command.get("agent_session_id") != source.agent_session_id
            or command.get("book_id") != source.accepted_boundary.book_id
            or command.get("agent_role") != source.role.value
            or command.get("skill_bindings") != [dict(item) for item in source.skill_bindings]
            or canonical_execution_contract_hash({"tools": command.get("tool_policy")})
               != canonical_execution_contract_hash({"tools": [asdict(item) for item in source.tool_policy]})
            or command.get("accepted_boundary") != asdict(source.accepted_boundary)
            or command.get("budget") != asdict(source.budget)
            or contract.get("accepted_boundary") != asdict(source.accepted_boundary)
            or contract.get("budget") != asdict(source.budget)
            or any(value for key, value in asdict(source.usage).items() if key != "cost_amount")
            or Decimal(source.usage.cost_amount) != 0):
        raise KernelError("AGENT_UNSENT_RECOVERY_SOURCE_DRIFT",
                          "Recovery requires the exact unchanged failed session, contract, actor and zero usage")
    uow.cursor.execute("""SELECT sequence,event_type,payload,payload_hash FROM authority_agent_transcript_event
        WHERE agent_session_id=%s ORDER BY sequence""", [source.agent_session_id])
    events = uow.cursor.fetchall()
    failure = dict(events[-1][2]) if events else {}
    if (not events or any(row[1] not in {"REQUEST_STARTED", "REQUEST_FAILED"} for row in events)
            or events[-1][1] != "REQUEST_FAILED"
            or any(transcript_payload_hash(row[2]) != row[3] for row in events)
            or failure.get("error_code") != "MODEL_EFFECT_RESERVATION_OVERRIDE_INVALID"
            or "account entitlement cannot declare a monetary reservation" not in str(failure.get("error_message") or "")):
        raise KernelError("AGENT_UNSENT_RECOVERY_FAILURE_UNPROVEN",
                          "Only the recorded membership monetary-override host failure can use this recovery")
    uow.cursor.execute("""SELECT
        EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
               WHERE a.operation_id=%s AND l.status='HELD' AND l.expires_at>NOW()),
        EXISTS(SELECT 1 FROM authority_operation WHERE parent_operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_output_asset
               WHERE operation_id=%s AND output_key<>'agent_harness.context'),
        EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_dependency WHERE depends_on_operation_id=%s)
        """, [operation["operation_id"]] * 7)
    if any(uow.cursor.fetchone()):
        raise KernelError("AGENT_UNSENT_RECOVERY_EXTERNAL_WORK_PRESENT",
                          "External intent, reservation, output, lease, child, cancellation or dependency requires its native owner")
    lineage = {"contract_version": "agent-known-unsent-successor.v1",
               "source_operation_id": operation["operation_id"],
               "source_session_id": source.agent_session_id,
               "source_operation_version": operation["version"], "source_session_version": source.version,
               "source_request_digest": operation["request_digest"],
               "source_command_hash": canonical_execution_contract_hash(command),
               "source_execution_contract_hash": source.execution_contract_hash,
               "source_failure": failure, "source_transcript_last_sequence": events[-1][0],
               "reason": request.reason, "actor_id": principal.principal_id,
               "target_release_sha": request.target_release_sha,
               "reference_prose": request.reference_prose,
               "external_effect_count": 0, "reservation_count": 0}
    return source, operation, lineage


def require_empty_reference_source(uow, request, principal):
    from novel_forge.modules.command_kernel.external_effect_runtime import _hash

    principal.require("agent.authority.admin", request.project_id)
    if principal.principal_type != PrincipalType.LOCAL_OPERATOR or not request.reason.strip() or not request.reference_prose:
        raise KernelError("AGENT_REFERENCE_RECOVERY_AUTHORIZATION_REQUIRED", "Empty reference continuation requires an explicit local operator reason")
    uow.cursor.execute("""SELECT to_jsonb(o) FROM authority_operation o
        JOIN authority_agent_harness_session s USING(operation_id)
        WHERE s.agent_session_id=%s AND o.project_id=%s FOR UPDATE OF o""", [request.source_session_id,request.project_id])
    row = uow.cursor.fetchone()
    if row is None:
        raise KernelError("AGENT_REFERENCE_RECOVERY_SOURCE_MISSING", "Retain the exact original reference session")
    operation = row[0]
    source = uow.repositories.agent_runtime.require_harness_session(request.source_session_id,lock=True)
    command = operation["command_payload"]
    contract = dict(source.execution_contract)
    reference = contract.get("reference_prose") or {}
    if (operation["status"] != "SUCCEEDED" or source.status != AgentHarnessStatus.COMPLETED
            or operation["version"] != request.expected_operation_version or source.version != request.expected_session_version
            or operation["request_digest"] != request.expected_request_digest
            or operation["actor_id"] != principal.principal_id or operation["definition_name"] != "agent.session.execute"
            or operation["root_operation_id"] != operation["operation_id"] or operation["parent_operation_id"]
            or source.project_id != request.project_id or source.workspace_id != operation["workspace_id"]
            or contract.get("contract_version") != "agent-session-execution-contract.v1"
            or contract.get("provider_io_policy") != "agent-io-budget.v1"
            or canonical_execution_contract_hash(contract) != source.execution_contract_hash
            or command.get("execution_contract") != contract or command.get("execution_contract_hash") != source.execution_contract_hash
            or command.get("agent_session_id") != source.agent_session_id
            or command.get("book_id") != source.accepted_boundary.book_id or command.get("agent_role") != source.role.value
            or command.get("skill_bindings") != [dict(item) for item in source.skill_bindings]
            or canonical_execution_contract_hash({"tools":command.get("tool_policy")})
               != canonical_execution_contract_hash({"tools":[asdict(item) for item in source.tool_policy]})
            or command.get("accepted_boundary") != asdict(source.accepted_boundary)
            or contract.get("accepted_boundary") != asdict(source.accepted_boundary)
            or command.get("budget") != asdict(source.budget) or contract.get("budget") != asdict(source.budget)
            or reference.get("contract_version") != "agent-reference-prose.v1" or reference.get("production_eligible") is not False
            or reference.get("tools_allowed") is not False or reference.get("skills_activation_allowed") is not False
            or reference.get("instruction_hash") != canonical_execution_contract_hash({"instruction":command.get("instruction")})
            or reference.get("book_id") != source.accepted_boundary.book_id or source.accepted_boundary.accepted_through_chapter != 0
            or source.usage.turns != 1 or source.usage.external_effects != 1 or source.usage.tool_calls != 0):
        raise KernelError("AGENT_REFERENCE_RECOVERY_SOURCE_DRIFT", "Only the exact completed one-turn empty reference may continue")
    uow.cursor.execute("""SELECT sequence,event_type,payload,payload_hash FROM authority_agent_transcript_event
        WHERE agent_session_id=%s ORDER BY sequence""", [source.agent_session_id])
    events = uow.cursor.fetchall()
    empty = {"basis":"frozen_instruction_only","status":"ineligible_reference_sample","candidate":None,
        "tool_requests":[],"owner_decision":None,"domain_submission":None,"validation_status":"reference_only",
        "accepted_story_facts":[],"domain_acceptance_claimed":False}
    if ([event[1] for event in events] != ["REQUEST_STARTED","MODEL_MESSAGE","REQUEST_COMMITTED"]
            or any(transcript_payload_hash(event[2]) != event[3] for event in events)
            or events[-1][2].get("response") != empty or events[1][2].get("final_response") != empty):
        raise KernelError("AGENT_REFERENCE_RECOVERY_RESULT_PRESENT", "Existing prose or a different response must be preserved and reviewed instead")
    uow.cursor.execute("""SELECT to_jsonb(e),d.evidence,d.status,d.payload_hash FROM authority_external_effect e
        LEFT JOIN authority_external_effect_dispatch d USING(external_effect_id) WHERE e.operation_id=%s
        ORDER BY d.generation""", [operation["operation_id"]])
    effects = uow.cursor.fetchall()
    if len(effects) != 1 or effects[0][0]["status"] != "SUCCEEDED" or effects[0][2] != "SUCCEEDED":
        raise KernelError("AGENT_REFERENCE_RECOVERY_EXTERNAL_UNKNOWN", "Reconcile every original external outcome before a reference continuation")
    effect, evidence, _dispatch_status, dispatch_hash = effects[0]
    effect_input = effect["request_payload"].get("input") or {}
    production = evidence.get("production_execution") or {}
    result = production.get("execution_result") or {}
    original = production.get("execution_request") or {}
    handle = production.get("execution_handle") or {}
    if (effect.get("effect_type") != "model.invoke" or effect["request_payload"].get("stage") != "agent_session"
            or dispatch_hash != effect.get("request_hash") or dispatch_hash != _hash(effect["request_payload"])
            or effect_input.get("agent_session_id") != source.agent_session_id or effect_input.get("instruction") != command["instruction"]
            or effect_input.get("execution_contract_hash") != source.execution_contract_hash
            or original.get("operation_id") != operation["operation_id"] or original.get("external_effect_id") != effect["external_effect_id"]
            or original.get("project_id") != source.project_id or original.get("book_id") != source.accepted_boundary.book_id
            or any(not original.get(key) or result.get(key) != original[key] or handle.get(key) != original[key]
                for key in ("execution_id","operation_id","attempt_id","fencing_token"))
            or result.get("outcome") != "SUCCEEDED" or not str(result.get("normalized_output_ref") or "").startswith("authority-asset-version:")):
        raise KernelError("AGENT_REFERENCE_RECOVERY_EXTERNAL_UNKNOWN", "Require the successful original native response identity")
    ref = result["normalized_output_ref"].split(":",1)[1]
    output = uow.repositories.asset_documents.require(project_id=request.project_id,asset_version_id=ref)
    payload = output.content.get("payload") or {}
    if (output.content_hash != _hash(output.content) or output.content.get("payload_hash") != _hash(payload).removeprefix("sha256:")
            or output.content.get("execution_id") != original.get("execution_id")
            or payload.get("action") != "FINAL" or payload.get("tool_call") is not None or payload.get("final_response") != empty):
        raise KernelError("AGENT_REFERENCE_RECOVERY_RESULT_PRESENT", "Retain the exact verified empty native response")
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
        WHERE a.operation_id=%s AND l.status='HELD' AND l.expires_at>NOW()),
        EXISTS(SELECT 1 FROM authority_operation WHERE parent_operation_id=%s),
        EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s),
        EXISTS(SELECT 1 FROM authority_operation_dependency WHERE depends_on_operation_id=%s)""", [operation["operation_id"]]*4)
    if any(uow.cursor.fetchone()):
        raise KernelError("AGENT_REFERENCE_RECOVERY_EXTERNAL_UNKNOWN", "Native work must stop before a reference continuation")
    return source, operation, {"contract_version":"agent-reference-output-continuation.v1",
        "source_operation_id":operation["operation_id"],"source_session_id":source.agent_session_id,
        "source_operation_version":operation["version"],"source_session_version":source.version,
        "source_request_digest":operation["request_digest"],"source_execution_contract_hash":source.execution_contract_hash,
        "source_response_asset_version_id":ref,"source_response_content_hash":output.content_hash,
        "source_transcript_last_sequence":events[-1][0],"source_external_effect_id":effect["external_effect_id"],
        "source_result":"COMPLETE_NATIVE_EMPTY_REFERENCE_RESPONSE","reason":request.reason,"actor_id":principal.principal_id,
        "target_release_sha":request.target_release_sha,"reference_prose":True,"external_effect_count":1}


def require_host_release_compatibility(uow: Any, source: dict[str, Any], target: dict[str, Any],
                                       target_release_sha: str, *, project_id: str) -> dict[str, Any]:
    from novel_forge.modules.capability_packs.compiler import reconstruct_compilation_catalog
    from novel_forge.modules.capability_packs.loader import load_capability_pack_payload
    from novel_forge.modules.capability_packs.operation_catalog import governed_workflow_binding_catalog
    from novel_forge.modules.capability_packs.type_catalog import default_tool_definition_catalog
    if (len(target_release_sha) != 40 or target.get("release_sha") != target_release_sha
            or any(char not in "0123456789abcdef" for char in target_release_sha)):
        raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Require the exact authorized host release")
    if source.get("reference_prose") and source["reference_prose"] != target.get("reference_prose"):
        raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "A reference successor cannot gain tool or production rights")
    pack_evidence = {"release_sha", "deployment_id", "compilation_id", "compilation_hash",
                     "catalog_snapshot_hash", "binding_set_id", "binding_set_hash",
                     "assignment_ref", "activation_version"}
    def route_projection(value):
        return {k:v for k,v in value.items() if k not in {"release_sha", "runtime_binding_hash"}}
    def pack_projection(value):
        return {k:v for k,v in value.items() if k not in pack_evidence}
    def projection(contract):
        result = {k:v for k,v in contract.items() if k not in {
            "release_sha", "provider_io_policy", "unsent_recovery", "reference_recovery", "capability_pack_snapshot_hash", "reference_prose"}}
        result["runtime_binding"] = route_projection(contract["runtime_binding"])
        result["capability_pack_execution_snapshot"] = pack_projection(contract["capability_pack_execution_snapshot"])
        policy = dict(contract["agent_policy"])
        for key in ("policy_hash", "capability_pack_snapshot_hash"):
            policy.pop(key, None)
        policy["model_binding"] = route_projection(policy["model_binding"])
        policy["capability_pack_execution_snapshot"] = pack_projection(policy["capability_pack_execution_snapshot"])
        result["agent_policy"] = policy
        return result
    if projection(source) != projection(target):
        raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Host successor cannot change Pack semantics, route, model, tools, Skills, Book or budget")
    compiled_views, catalog_views, binding_views, deployment_views = [], [], [], []
    for contract in (source, target):
        snapshot = contract["capability_pack_execution_snapshot"]
        packs = uow.repositories.capability_packs
        compilation = packs.require_compilation(snapshot["compilation_id"], project_id=project_id)
        deployment = packs.require_deployment(snapshot["deployment_id"], project_id=project_id)
        binding = packs.binding_set_for_compilation(snapshot["compilation_id"])
        if (compilation["compilation_hash"] != snapshot["compilation_hash"]
                or compilation["release_sha"] != contract["release_sha"]
                or deployment["compilation_id"] != snapshot["compilation_id"]
                or deployment["binding_set_id"] != binding["binding_set_id"]
                or binding["binding_set_id"] != snapshot["binding_set_id"]
                or binding["binding_set_hash"] != snapshot["binding_set_hash"]
                or deployment["book_id"] != contract["accepted_boundary"]["book_id"]):
            raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Frozen compilation evidence is inconsistent")
        compiled = dict(compilation["compiled"])
        if any(compiled.get(key) != snapshot.get(key) or compilation.get(key) != snapshot.get(key)
               for key in ("pack_id", "pack_version", "manifest_hash", "catalog_snapshot_hash")):
            raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Compilation identity differs from its frozen Pack snapshot")
        if canonical_execution_contract_hash({k:v for k,v in compiled.items() if k != "compilation_hash"}) != compilation["compilation_hash"]:
            raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Compilation hash does not match its immutable complete payload")
        version = packs.require_version(snapshot["pack_id"], snapshot["pack_version"], project_id=project_id)
        manifest = load_capability_pack_payload(version["manifest"])
        if manifest.manifest_hash != snapshot["manifest_hash"] or version["manifest_hash"] != snapshot["manifest_hash"]:
            raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Manifest hash differs from its frozen Pack snapshot")
        catalog = reconstruct_compilation_catalog(compiled, manifest,
            governed_workflow_binding_catalog(str(manifest.workflow_template.workflow_id), str(manifest.workflow_template.workflow_version)),
            default_tool_definition_catalog())
        if canonical_execution_contract_hash(catalog) != compiled["catalog_snapshot_hash"]:
            raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Current static catalog cannot reconstruct the frozen compiler catalog")
        for item in compiled["resolved_operations"]:
            registered = uow.repositories.definitions.get_release(item["definition_name"], item["definition_version"], commit_sha=contract["release_sha"])
            if (registered is None or item["source_commit_sha"] != contract["release_sha"]
                    or item["application_build_id"] != registered["application_build_id"]
                    or item["definition_hash"] != registered["definition_hash"]):
                raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Resolved Operation must retain its registered release and semantic definition")
        def operations_projection(operations):
            return [{k:v for k,v in item.items() if k not in {"source_commit_sha", "application_build_id"}} for item in operations]
        catalog["operation_definitions"] = operations_projection(catalog["operation_definitions"])
        catalog_views.append(catalog)
        binding_payload = {"schema_version": "novelos.capability_pack.binding_set.v1",
            "pack_id": compiled["pack_id"], "pack_version": compiled["pack_version"],
            "compilation_hash": compilation["compilation_hash"],
            **{k:binding[k] for k in ("workflow_definition_ref", "node_bindings", "artifact_bindings", "policy_bindings")}}
        if canonical_execution_contract_hash(binding_payload) != binding["binding_set_hash"]:
            raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Binding Set hash does not match its complete payload")
        binding_payload.pop("compilation_hash")
        binding_views.append(binding_payload)
        deployment_views.append({k:v for k,v in deployment.items() if k not in {
            "deployment_id", "compilation_id", "binding_set_id", "deployment_status", "compilation_hash",
            "catalog_snapshot_hash", "release_sha", "binding_set_hash"}})
        for key in ("release_sha", "compilation_hash", "catalog_snapshot_hash"):
            compiled.pop(key, None)
        compiled["resolved_operations"] = operations_projection(compiled["resolved_operations"])
        compiled_views.append(compiled)
    if (compiled_views[0] != compiled_views[1] or catalog_views[0] != catalog_views[1]
            or binding_views[0] != binding_views[1] or deployment_views[0] != deployment_views[1]):
        raise KernelError("AGENT_UNSENT_RECOVERY_RUNTIME_DRIFT", "Resolved input/output Schemas and all selected artifacts must remain identical")
    return {"contract_version": "agent-host-release-compatibility.v1",
            "source_release_sha": source["release_sha"], "target_release_sha": target_release_sha,
            "source_pack_snapshot_hash": source["capability_pack_snapshot_hash"],
            "target_pack_snapshot_hash": target["capability_pack_snapshot_hash"],
            "semantic_projection_hash": canonical_execution_contract_hash(projection(target)),
            "resolved_compilation_projection_hash": canonical_execution_contract_hash(compiled_views[1]),
            "catalog_projection_hash": canonical_execution_contract_hash(catalog_views[1]),
            "binding_set_projection_hash": canonical_execution_contract_hash(binding_views[1])}
