from __future__ import annotations

import json

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import verify_template_provenance
from .domain import canonical_hash


def require_capacity_source(uow, *, source_operation_id, project_id, frozen, version):
    from .application import _command_from_payload
    from .result_recovery import require_result_repair_source

    command = _command_from_payload(frozen)
    if not command.repair_of_operation_id or not command.repair_result_asset_version_id:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_FAILURE_NOT_ALLOWED", "Capacity recovery requires a frozen raw-result repair")
    uow.cursor.execute("""SELECT
        (SELECT count(*) FROM authority_external_effect WHERE operation_id=%s),
        (SELECT count(*) FROM authority_budget_reservation WHERE operation_id=%s),
        (SELECT count(*) FROM authority_attempt WHERE operation_id=%s AND status IN ('CLAIMED','EXECUTING','WAITING_EXTERNAL_RESULT'))""",
        [source_operation_id]*3)
    if any(uow.cursor.fetchone()):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_DISPATCH_UNSAFE", "Capacity successor requires no Effect, reservation or live Attempt")
    retained = require_result_repair_source(uow.database_url, command=command, operation_id=command.repair_of_operation_id,
        source_asset_version_id=command.repair_result_asset_version_id)
    effect_id = retained["execution_evidence"]["external_receipt_ref"]
    uow.cursor.execute("SELECT provider,model_id,request_payload FROM authority_external_effect WHERE external_effect_id=%s AND operation_id=%s AND status='SUCCEEDED'", [effect_id,command.repair_of_operation_id])
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
        WHERE o.operation_id=%s AND o.asset_version_id=%s""", [command.repair_of_operation_id,evidence_id])
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
        [command.repair_of_operation_id, retained["execution_evidence"]["route_snapshot_id"]])
    route = uow.cursor.fetchone()
    if not route or not route[0].get("auth_profile_ref"):
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_ROUTE_EVIDENCE_REQUIRED", "Original result must retain its exact native authentication binding")
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1", [source_operation_id])
    row = uow.cursor.fetchone()
    uow.cursor.execute("SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE snapshot_id=%s AND snapshot_hash=%s AND operation_id=%s",
        [capability["snapshot_id"],capability["snapshot_hash"],command.repair_of_operation_id])
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
    if depth >= 2:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_BOUND_EXCEEDED", source_operation_id)
    uow.cursor.execute("SELECT attempt_id,result,error FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source_operation_id])
    attempt = uow.cursor.fetchone()
    return {"source_operation_id":source_operation_id,"command":frozen,"version":version,
        "evidence_asset_version_id":evidence_id,"evidence_hash":receipt[0],"snapshot":snapshot,
        "provider":identity["provider"],"model_id":effect[1],"depth":depth+1,
        "route_evidence_operation_id":command.repair_of_operation_id,
        "original_context_target":retained["context_content"]["token_budget"],
        "source_auth_profile_ref":route[0]["auth_profile_ref"],
        "source_backend_id":route[0]["backend_id"],
        "source_reasoning_effort":route[0]["reasoning_effort"],
        "preflight_failure":{"contract_version":"planning-capacity-preflight.v1","attempt_id":attempt[0],
            "result":attempt[1],"error":attempt[2],"effect_count":0,"reservation_count":0,
            "repair_number":command.repair_number,"source_result_asset_version_id":retained["asset_version_id"],
            "source_result_hash":retained["content_hash"],"settled_original_effect_id":effect_id}}


def require_capacity_target(source, target):
    old = json.loads(source["snapshot"]["context_policy_payload_json"])
    new = json.loads(target["pack_snapshot"]["context_policy_payload_json"])
    original = old.pop("planning_task_token_budget", source["original_context_target"])
    successor = new.pop("planning_task_token_budget",None)
    if old != new or type(original) is not int or type(successor) is not int or not original < successor <= old["max_tokens"] <= 512000:
        raise KernelError("PLANNING_RUNTIME_CONTINUATION_CAPACITY_DRIFT", "Only the bounded Planning task Context target may increase")
    return {"original_target":original,"successor_target":successor,
        "system_ceiling":old["max_tokens"],"unchanged_context_policy_hash":canonical_hash(old),
        "book_usage_budget":False}
