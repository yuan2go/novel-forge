from __future__ import annotations

import json

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import verify_template_provenance
from .domain import canonical_hash

INPUT_SCOPE_MODE = "UNSENT_CURRENT_WORKING_PLAN_SCOPE"
INPUT_SCOPE_CONTRACT = "planning-unsent-working-input-scope.v1"


def require_input_scope_source(uow, *, source_operation_id, row, frozen, attempt):
    from novel_forge.modules.book_authority.manuscript import historical_working_inputs

    failure = dict(attempt[2] or {})
    if (row[0] != "FAILED_FINAL" or attempt[0] != "FAILED_FINAL"
            or failure.get("error_code") != "MANUSCRIPT_CONTEXT_INVALID"
            or failure.get("error_message") != "MANUSCRIPT_CONTEXT_INVALID: Only the selected preceding writing history can be read"
            or frozen.get("execution_contract_version") != "1.21.0"
            or frozen.get("runtime_continuation_id") or frozen.get("repair_number") != 0
            or len(frozen.get("change_evidence_version_ids") or []) != 1):
        raise KernelError("PLANNING_INPUT_SCOPE_SOURCE_INVALID", "Require the exact fresh current-chapter Planning input-scope failure")
    uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [source_operation_id])
    operation = uow.cursor.fetchone()[0]
    working = (frozen.get("arc_working_set") or {}).get("working_manuscript") or {}
    uow.cursor.execute("SELECT current_chapter,accepted_through_chapter,state,active_chapter_request_id FROM authority_book_production WHERE book_run_id=%s FOR UPDATE", [working.get("book_run_id")])
    book = uow.cursor.fetchone()
    if (not book or type(working.get("target_chapter")) is not int or book[0] != working["target_chapter"]
            or book[1] >= book[0] or book[2] not in {"READY", "PAUSED"} or book[3]):
        raise KernelError("PLANNING_INPUT_SCOPE_SOURCE_INVALID", "Retain the exact owning Book checkpoint")
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_attempt WHERE operation_id=%s AND status<>'FAILED_FINAL')
        OR (SELECT count(*)<>1 FROM authority_attempt WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
            WHERE a.operation_id=%s AND l.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_cancellation_command WHERE operation_id=%s)
        OR EXISTS(SELECT 1 FROM authority_worker_cancel_signal WHERE operation_id=%s AND acknowledged_at IS NULL)""",
        [source_operation_id] * 9)
    if uow.cursor.fetchone() != (False,):
        raise KernelError("PLANNING_INPUT_SCOPE_SOURCE_UNSAFE", "Retain a stopped zero-preparation source without cancellation or execution rights")
    uow.cursor.execute("SELECT attempt_id,attempt_number FROM authority_attempt WHERE operation_id=%s", [source_operation_id])
    attempt_id, attempt_number = uow.cursor.fetchone()
    book_id, history = historical_working_inputs(uow, operation)
    if book_id != frozen["book_id"] or not history or working.get("target_chapter") is None:
        raise KernelError("PLANNING_INPUT_SCOPE_SOURCE_INVALID", "The repaired native change-request and current history scope must pass")
    for pointer in operation["input_asset_snapshot"]:
        document = uow.repositories.asset_documents.require(project_id=frozen["project_id"], asset_version_id=pointer["asset_version_id"])
        if document.content_hash != pointer["content_hash"]:
            raise KernelError("PLANNING_INPUT_SCOPE_SOURCE_INVALID", "Retain every original frozen input hash")
    evidence = uow.repositories.asset_documents.require(project_id=frozen["project_id"], asset_version_id=frozen["change_evidence_version_ids"][0])
    uow.cursor.execute("""SELECT generation.operation_id,snapshot.snapshot_payload,snapshot.snapshot_id,snapshot.snapshot_hash
        FROM authority_story_planning_candidate candidate
        JOIN authority_story_planning_generation generation USING(generation_id)
        JOIN authority_external_effect effect ON effect.operation_id=generation.operation_id
          AND effect.status='SUCCEEDED' AND effect.request_payload->>'stage'=generation.generator_operation_name
        JOIN authority_attempt_capability_pack_snapshot snapshot
          ON snapshot.snapshot_id=effect.request_payload #>> '{_production_execution,capability_runtime,snapshot_id}'
          AND snapshot.snapshot_hash=effect.request_payload #>> '{_production_execution,capability_runtime,snapshot_hash}'
          AND snapshot.operation_id=generation.operation_id
        WHERE candidate.candidate_asset_version_id=%s AND generation.project_id=%s AND generation.book_id=%s
          AND generation.workspace_id=%s AND generation.generator_operation_name=%s""",
        [evidence.content["target_plan_version_id"], frozen["project_id"], frozen["book_id"],
         frozen["workspace_id"], frozen["generator_operation_name"]])
    references = uow.cursor.fetchall()
    if len(references) != 1:
        raise KernelError("PLANNING_INPUT_SCOPE_REFERENCE_REQUIRED", "Require one completed native target-plan route reference")
    reference, snapshot, snapshot_id, snapshot_hash = references[0]
    proof = {"contract_version": INPUT_SCOPE_CONTRACT, "source_operation_id": source_operation_id,
        "source_failure": failure, "source_failure_hash": canonical_hash(failure),
        "source_attempt_id": attempt_id, "source_attempt_number": attempt_number,
        "input_snapshot_hash": canonical_hash(operation["input_asset_snapshot"]),
        "working_snapshot_hash": working["snapshot_hash"], "source_pack_snapshot": None,
        "source_provider_dispatch_count": 0, "reference_operation_id": reference,
        "reference_pack_snapshot_id": snapshot_id, "reference_pack_snapshot_hash": snapshot_hash}
    return {"mode": INPUT_SCOPE_MODE, "source_operation_id": source_operation_id, "command": frozen,
        "version": int(row[1]), "evidence_asset_version_id": evidence.asset_version_id,
        "evidence_hash": evidence.content_hash, "snapshot": None,
        "source_release_sha": operation["definition_snapshot"]["commit_sha"], "depth": 1,
        "reference_snapshot": snapshot, "reference_operation_id": reference, "input_scope_failure": proof}


def authorize_input_scope(uow, *, source, successor, principal, target):
    from .runtime_continuation import _capacity_authorization
    from .database_recovery import completed_reference_route

    if source["source_release_sha"] == target["pack_snapshot"]["release_sha"]:
        raise KernelError("PLANNING_INPUT_SCOPE_RELEASE_UNCHANGED", "A failed input-scope implementation requires its verified correction")
    checked = _capacity_authorization(uow, source={**source, "snapshot": source["reference_snapshot"]},
        successor=successor, principal=principal, target=target)
    if (checked.get("pack_version_successor") or checked.get("capacity_policy_upgrade")
            or any(source["reference_snapshot"].get(key) != target["pack_snapshot"].get(key)
                for key in ("manifest_hash", "prompt_bundle_hash", "route_policy_hash", "context_policy_hash", "skill_bundle_hash", "tool_policy_hash"))):
        raise KernelError("PLANNING_INPUT_SCOPE_PACK_CHANGED", "Input-scope recovery requires the unchanged semantic Pack and capacity policy")
    actual = completed_reference_route(uow, reference_operation_id=source["reference_operation_id"], command=successor, prior=target)
    return {**checked, "capacity_only": False, "recovery_kind": INPUT_SCOPE_CONTRACT,
        "source_input_scope_failure": source["input_scope_failure"],
        "reference_route": actual, "route_reference_scope": "TARGET_PLAN_COMPLETED_CALL_NOT_FAILED_SOURCE",
        "preserved_repair_number": successor.repair_number, "first_preparation": "NATIVE_SUCCESSOR"}


def require_capacity_source(uow, *, source_operation_id, project_id, frozen, version, routing_failure=False, input_order_failure=False):
    from .application import _command_from_payload
    from .result_recovery import require_result_repair_source

    command = _command_from_payload(frozen)
    if not routing_failure and not input_order_failure and (not command.repair_of_operation_id or not command.repair_result_asset_version_id):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED", "Capacity recovery requires a frozen raw-result repair")
    uow.cursor.execute("""SELECT
        (SELECT count(*) FROM authority_external_effect WHERE operation_id=%s),
        (SELECT count(*) FROM authority_budget_reservation WHERE operation_id=%s),
        (SELECT count(*) FROM authority_attempt WHERE operation_id=%s AND status IN ('CLAIMED','EXECUTING','WAITING_EXTERNAL_RESULT'))""",
        [source_operation_id]*3)
    if any(uow.cursor.fetchone()):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE", "Capacity successor requires no Effect, reservation or live Attempt")
    if input_order_failure:
        retained, blocked_decision = require_input_order_source(uow,command=command,source_operation_id=source_operation_id)
    elif routing_failure:
        retained, blocked_decision = require_route_source(uow,command=command,source_operation_id=source_operation_id)
    else:
        retained = require_result_repair_source(uow.database_url, command=command, operation_id=command.repair_of_operation_id,
            source_asset_version_id=command.repair_result_asset_version_id)
    result_operation_id = retained.get("operation_id",command.repair_of_operation_id)
    effect_id = retained["execution_evidence"]["external_receipt_ref"]
    uow.cursor.execute("SELECT provider,model_id,request_payload FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s AND status='SUCCEEDED'", [effect_id,result_operation_id])
    effect = uow.cursor.fetchone()
    if not effect:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_MISSING", "Original result must retain its settled successful Provider call")
    capability = effect[2]["_production_execution"]["capability_runtime"]
    policy = verify_template_provenance(uow.cursor, capability["routing_decision"])
    if not policy or policy["mode"] != "CREATIVE_VALIDATION" or policy["require_literary_qualification"] or policy["book_id"] != command.book_id:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_POLICY_REQUIRED", "Capacity recovery cannot relax strict production")
    evidence_id = capability["provider_admission_asset_version_id"]
    uow.cursor.execute("""SELECT v.content_hash,v.content,a.asset_type FROM authority_operation_output_asset o
        JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE o.operation_id=%s AND o.asset_version_id=%s""", [result_operation_id,evidence_id])
    receipt = uow.cursor.fetchone()
    if not receipt or receipt[0] != capability["provider_admission_content_hash"] or receipt[2] != "provider_request_admission_manifest":
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID", "Original native Provider admission identity is missing")
    identity = receipt[1].get("contract",receipt[1])["provider_request_identity"]
    if identity["model"] != effect[1]:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_MODEL_ROUTE_DRIFT", "Original result model identity differs")
    uow.cursor.execute("""SELECT v.content->'contract' FROM authority_operation_output_asset o
        JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE o.operation_id=%s AND a.asset_type='route_snapshot'
            AND v.content #>> '{contract,route_snapshot_id}'=%s""",
        [result_operation_id, retained["execution_evidence"]["route_snapshot_id"]])
    route = uow.cursor.fetchone()
    if not route or not route[0].get("auth_profile_ref"):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_REQUIRED", "Original result must retain its exact native authentication binding")
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1", [source_operation_id])
    row = uow.cursor.fetchone()
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE snapshot_id=%s AND snapshot_hash=%s AND operation_id=%s",
        [capability["snapshot_id"],capability["snapshot_hash"],result_operation_id])
    parent_snapshot = uow.cursor.fetchone()
    if not row or not parent_snapshot or row[0]["route_policy_hash"] != parent_snapshot[0]["route_policy_hash"]:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_SNAPSHOT_MISSING", "Capacity source must retain the original route and failed Pack snapshot")
    snapshot = row[0]
    if ("planning_task_token_budget" not in json.loads(snapshot["context_policy_payload_json"])
            and (snapshot["context_policy_hash"] != parent_snapshot[0]["context_policy_hash"]
                 or snapshot["catalog_snapshot_hash"] != parent_snapshot[0]["catalog_snapshot_hash"])):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_CAPACITY_DRIFT", "Legacy capacity must retain the original result's exact frozen Context policy and catalog")
    depth = 0
    if command.runtime_continuation_id:
        uow.cursor.execute("SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE continuation_id=%s AND successor_operation_id=%s", [command.runtime_continuation_id,source_operation_id])
        prior = uow.cursor.fetchone()
        if not prior:
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_LINEAGE_INVALID", source_operation_id)
        depth = prior[0]
    uow.cursor.execute("SELECT attempt_id,result,error FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source_operation_id])
    attempt = uow.cursor.fetchone()
    return {"source_operation_id":source_operation_id,"command":frozen,"version":version,
        "evidence_asset_version_id":evidence_id,"evidence_hash":receipt[0],"snapshot":snapshot,
        "provider":identity["provider"],"model_id":effect[1],"depth":depth+1,
        "route_evidence_operation_id":result_operation_id,
        "original_context_target":retained["context_content"]["token_budget"],
        "source_auth_profile_ref":route[0]["auth_profile_ref"],
        "source_backend_id":route[0]["backend_id"],
        "source_reasoning_effort":route[0]["reasoning_effort"],
        "preflight_failure":{"contract_version":"planning-input-order-preflight.v1" if input_order_failure else "planning-repair-route-preflight.v1" if routing_failure else "planning-capacity-preflight.v1",
            **({"blocked_decision":blocked_decision} if routing_failure or input_order_failure else {}),"attempt_id":attempt[0],
            "result":attempt[1],"error":attempt[2],"effect_count":0,"reservation_count":0,
            "repair_number":command.repair_number,"source_result_asset_version_id":retained["asset_version_id"],
            "source_result_hash":retained["content_hash"],"settled_original_effect_id":effect_id}}


def require_capacity_target(source, target):
    old = json.loads(source["snapshot"]["context_policy_payload_json"])
    new = json.loads(target["pack_snapshot"]["context_policy_payload_json"])
    if (source.get("preflight_failure") or {}).get("contract_version") in {"planning-repair-route-preflight.v1","planning-input-order-preflight.v1"}:
        if old != new:
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_CAPACITY_DRIFT","Routing recovery retains the exact Context policy")
        return {"context_policy":"UNCHANGED","recovery_kind":"NATIVE_BOUNDED_REPAIR_ROUTE","book_usage_budget":False}
    original = old.pop("planning_task_token_budget", source.get("original_context_target"))
    successor = new.pop("planning_task_token_budget",None)
    policy_upgrade = (old.get("policy_id") in {"context-policy:chapter-generation-pack:v2", "context-policy:chapter-generation-pack:v3"}
        and new.get("policy_id") in {"context-policy:chapter-generation-pack:v3", "context-policy:chapter-generation-pack:v4"}
        and old.get("policy_id") != new.get("policy_id")
        and new.get("capacity_policy") == "complete-request-capacity.v1"
        and new.get("context_substage_method") == ("source-unit-dependency-and-final-composition.v2" if new.get("policy_id") == "context-policy:chapter-generation-pack:v4" else "shared-rules-and-native-context-contract.v1"))
    comparison = {**old, "policy_id": new["policy_id"], "capacity_policy": new["capacity_policy"],
                  "context_substage_method": new["context_substage_method"]} if policy_upgrade else old
    if policy_upgrade and "capacity_history_exact_chapters" in new:
        if new["policy_id"] != "context-policy:chapter-generation-pack:v4" or type(new["capacity_history_exact_chapters"]) is not int or new["capacity_history_exact_chapters"] < 1:
            raise KernelError("PLANNING_RUNTIME_CONTINUATION_CAPACITY_DRIFT", "History protection requires the frozen semantic policy")
        comparison["capacity_history_exact_chapters"] = new["capacity_history_exact_chapters"]
    if comparison != new or type(original) is not int or type(successor) is not int or not original <= successor <= old["max_tokens"] <= 512000 or (not policy_upgrade and original == successor):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_CAPACITY_DRIFT", "Only the bounded Planning task Context target may increase")
    return {"original_target":original,"successor_target":successor,
        "system_ceiling":old["max_tokens"],"unchanged_context_policy_hash":canonical_hash(old),
        **({"capacity_policy_upgrade": "complete-request-capacity.v1"} if policy_upgrade else {}),
        "book_usage_budget":False}



def _native_preflight_evidence(uow, *, command, source_operation_id, lineage):
    from novel_forge.modules.story_planning_runtime.planning_repair_routing import native_planning_repair
    from novel_forge.modules.production_execution.execution_template import planning_repair_evidence_version
    uow.cursor.execute("""SELECT v.content FROM authority_operation_output_asset o
        JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE o.operation_id=%s AND a.project_id=%s AND a.asset_type='routing_decision'""",
        [source_operation_id, command.project_id])
    decisions = uow.cursor.fetchall()
    if not decisions:
        from .execution import require_candidate_repair_operation
        parent = command.repair_of_operation_id
        if command.repair_of_candidate_id:
            parent = require_candidate_repair_operation(uow.cursor, candidate_asset_version_id=command.repair_of_candidate_id,
                project_id=command.project_id, book_id=command.book_id,
                generator_operation_name=command.generator_operation_name, logical_key=command.logical_key)
        result_id = command.repair_of_candidate_id or command.repair_result_asset_version_id
        uow.cursor.execute("""SELECT e.request_payload #> '{_production_execution,capability_runtime,routing_decision}'
            FROM authority_external_effect e JOIN authority_asset_version v ON v.asset_version_id=%s
            WHERE e.operation_id=%s AND e.project_id=%s AND e.request_payload->>'stage'=%s
              AND e.status IN ('SUCCEEDED','FAILED_FINAL')
              AND e.external_effect_id=COALESCE(v.content #>> '{execution_evidence,external_receipt_ref}',
                  v.content->>'external_effect_id',v.content #>> '{contract,evidence,external_receipt_ref}')""",
            [result_id, parent, command.project_id, command.generator_operation_name])
        decisions = uow.cursor.fetchall()
    if len(decisions) != 1 or not decisions[0][0]:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID", "Preflight requires its exact recorded route or native parent route")
    template = verify_template_provenance(uow.cursor, decisions[0][0])
    if not template or template["book_id"] != command.book_id:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID", "Preflight must retain this Book's frozen creative template")
    version = planning_repair_evidence_version(template)
    return native_planning_repair(uow.cursor, project_id=command.project_id, book_id=command.book_id,
        operation_id=source_operation_id, task_type=command.generator_operation_name, lineage=lineage, evidence_version=version)


def require_route_source(uow, *, command, source_operation_id):
    from .execution import _planning_repair_routing_lineage
    lineage = _planning_repair_routing_lineage(uow.database_url,project_id=command.project_id,book_id=command.book_id,
        generator_operation_name=command.generator_operation_name,operation_id=source_operation_id,
        repair_of_operation_id=command.repair_of_operation_id,repair_of_candidate_id=command.repair_of_candidate_id)
    evidence = _native_preflight_evidence(uow, command=command, source_operation_id=source_operation_id, lineage=lineage)
    if not evidence:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED","Only an actual creative native repair may receive a routing successor")
    uow.cursor.execute("""SELECT v.content,v.content_hash,v.asset_version_id FROM authority_operation_output_asset o
        JOIN authority_asset_version v USING(asset_version_id) JOIN authority_asset a ON a.asset_id=v.asset_id
        WHERE o.operation_id=%s AND a.asset_type='routing_decision'""",[source_operation_id])
    decisions = uow.cursor.fetchall()
    if len(decisions) != 1:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID","Blocked repair requires its exact routing decision")
    decision, digest, decision_id = decisions[0]
    template = verify_template_provenance(uow.cursor,decision)
    candidate = evidence["parent_candidate_id"]
    rows = [row for row in decision["candidates"] if row["candidate"]["candidate_id"] == candidate]
    if (not template or template['mode'] != 'CREATIVE_VALIDATION' or template['require_literary_qualification']
            or decision['status'] != 'BLOCKED' or len(rows) != 1
            or set(rows[0]['rejected_reasons']) - {'FAILED_ROUTE_EXCLUDED','SEMANTIC_ARBITRATION_REQUIRED','ROUTE_RETRY_LIMIT_REACHED'}
            or 'FAILED_ROUTE_EXCLUDED' not in rows[0]['rejected_reasons']
            or not decision['task']['history']
            or any(h.get('failure_class') not in {'SCHEMA_REJECTION','MALFORMED_STRUCTURED_OUTPUT',''}
                for h in decision['task']['history'])):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED","Only bounded contract-repair failed-route exclusion permits this successor")
    blocked = {'asset_version_id':decision_id,'content_hash':digest,
        'decision':decision,'native_repair_evidence':evidence}
    if command.repair_result_asset_version_id:
        from .result_recovery import require_result_repair_source
        retained = require_result_repair_source(uow.database_url,command=command,
            operation_id=evidence['parent_operation_id'],source_asset_version_id=evidence['source_result_asset_version_id'])
        return {**retained,'operation_id':evidence['parent_operation_id']}, blocked
    return retained_candidate_source(uow,evidence=evidence), blocked


def retained_candidate_source(uow, *, evidence):
    uow.cursor.execute("SELECT content FROM authority_asset_version WHERE asset_version_id=%s AND content_hash=%s",
        [evidence['source_result_asset_version_id'],evidence['source_result_hash']])
    content = uow.cursor.fetchone()[0]
    execution = content['execution_evidence']
    uow.cursor.execute("SELECT v.content FROM authority_operation_output_asset o JOIN authority_asset_version v USING(asset_version_id) WHERE o.operation_id=%s AND v.asset_version_id=%s",
        [evidence['parent_operation_id'],execution['context_bundle_asset_version_id']])
    context = uow.cursor.fetchone()
    if not context or canonical_hash(context[0]) != execution['context_bundle_hash']:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID","Original native repair Context is missing or changed")
    return {'operation_id':evidence['parent_operation_id'],'execution_evidence':execution,
        'context_content':context[0],'asset_version_id':evidence['source_result_asset_version_id'],
        'content_hash':evidence['source_result_hash']}


def require_input_order_source(uow, *, command, source_operation_id):
    from .execution import _planning_repair_routing_lineage
    if not command.repair_of_candidate_id or command.repair_of_operation_id:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED","Input-order recovery requires an exact native candidate repair")
    lineage = _planning_repair_routing_lineage(uow.database_url,project_id=command.project_id,book_id=command.book_id,
        generator_operation_name=command.generator_operation_name,operation_id=source_operation_id,
        repair_of_operation_id=command.repair_of_operation_id,repair_of_candidate_id=command.repair_of_candidate_id)
    evidence = _native_preflight_evidence(uow, command=command, source_operation_id=source_operation_id, lineage=lineage)
    if not evidence or evidence['input_snapshot_hash'] == evidence['parent_input_snapshot_hash']:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED","Only an identical role map with changed ordered input hash permits this successor")
    uow.cursor.execute("SELECT report_hash FROM authority_story_planning_validation_report WHERE candidate_asset_version_id=%s AND status='FAIL'",[command.repair_of_candidate_id])
    if not any(command.repair_reason.endswith(row[0]) for row in uow.cursor.fetchall()):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_EVIDENCE_INVALID","Repair must retain its native rejected candidate report")
    return retained_candidate_source(uow,evidence=evidence), {'native_repair_evidence':evidence,
        'source_operation_id':source_operation_id,'failure_code':'NATIVE_PLANNING_REPAIR_SOURCE_INVALID'}
