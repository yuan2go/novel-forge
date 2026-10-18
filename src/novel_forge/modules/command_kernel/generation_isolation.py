from __future__ import annotations

from time import sleep
from uuid import uuid4

from psycopg.types.json import Jsonb

from .errors import KernelError


CONTRACT = "pure-generation-isolation.v1"


def generation_retry_usage(cursor, *, operation_id):
    cursor.execute("""WITH RECURSIVE edges(source,target) AS (
        SELECT source_operation_id,successor_operation_id FROM authority_story_planning_runtime_continuation
          WHERE successor_operation_id IS NOT NULL
        UNION SELECT predecessor_operation_id,successor_operation_id FROM authority_saga_step_successor),
        ancestors(operation_id) AS (SELECT %s::text UNION SELECT edges.source FROM edges
          JOIN ancestors ON ancestors.operation_id=edges.target), failures AS (
        SELECT DISTINCT COALESCE(NULLIF(dispatch.evidence #>> '{production_execution,execution_request,execution_id}',''),
          dispatch.dispatch_id) identity FROM authority_external_effect_dispatch dispatch
        JOIN authority_external_effect effect USING(external_effect_id) JOIN ancestors USING(operation_id)
        LEFT JOIN authority_generation_isolation isolation USING(external_effect_id)
        WHERE effect.effect_type='model.invoke' AND (isolation.external_effect_id IS NOT NULL OR (
          dispatch.status IN ('UNKNOWN','FAILED_RETRYABLE','FAILED_FINAL','RECONCILIATION_REQUIRED')
          AND COALESCE(dispatch.evidence #>> '{production_execution,execution_result,outcome}','')<>'SUCCEEDED')))
        SELECT (SELECT count(*) FROM failures),
          (SELECT min(COALESCE((operation.definition_snapshot #>> '{retry_policy,max_attempts}')::int,3))
           FROM authority_operation operation JOIN ancestors USING(operation_id))""", [operation_id])
    used,maximum=cursor.fetchone()
    return {"failure_attempts":int(used),"maximum_failure_attempts":int(maximum),
        "counter_source":"NATIVE_DISPATCH_LINEAGE","scope":"ORIGINAL_LOGICAL_GENERATION"}


def require_generation_retry_budget(cursor, *, operation_id):
    evidence=generation_retry_usage(cursor,operation_id=operation_id)
    return evidence


def require_native_api_isolation_record(content, *, project_id, book_id, operation_id, effect_id, capability):
    from novel_forge.modules.production_execution.contracts import ExecutionRequest
    from .external_effect_runtime import _hash

    record = content.get("record") or {}
    from novel_forge.modules.production_execution.process_liveness import provider_invocation_inflight
    if provider_invocation_inflight(record):
        raise KernelError("GENERATION_ISOLATION_PROCESS_LIVE", "The original local Provider invocation is still in flight")
    original = ExecutionRequest.from_dict(record.get("request") or {})
    frozen = record.get("frozen_output_contract") or {}
    if (original.project_id != project_id or original.book_id != book_id
            or original.operation_id != operation_id or original.external_effect_id != effect_id
            or original.contract_hash != content.get("request_contract_hash")
            or frozen.get("execution_request_hash") != original.contract_hash
            or frozen.get("request_hash") != capability.get("provider_request_envelope_hash")
            or frozen.get("contract_hash") != _hash({key:value for key,value in frozen.items() if key != "contract_hash"})
            or (record.get("handle") or {}).get("transport") != "REMOTE_PROVIDER_API"):
        raise KernelError("GENERATION_ISOLATION_IDENTITY_CONFLICT", "Require the original admitted native API invocation, inputs and output contract")
    if ((record.get("result") or {}).get("normalized_output_ref")
            or (record.get("provider_result") or {}).get("outcome") == "success"):
        raise KernelError("GENERATION_ISOLATION_RESULT_RECOVERABLE", "Reuse the retained complete API result before isolation")
    if (record.get("raw_evidence") or {}).get("submission_phase") not in {
            "PROVIDER_INVOKING","PROVIDER_OUTCOME_UNKNOWN","PROVIDER_RESULT_RECORDED","PROVIDER_RESULT_OBSERVED"}:
        raise KernelError("GENERATION_ISOLATION_EXECUTION_EVIDENCE_MISSING", "Require a durable local invocation boundary")
    return original, record


def require_reconciled_cli_isolation_record(content, execution, *, effect, project_id, book_id, capability):
    from novel_forge.modules.production_execution.contracts import ExecutionRequest
    from .external_effect_runtime import _hash
    import re

    record = content.get("record") or {}
    original = ExecutionRequest.from_dict(record.get("request") or {})
    frozen = record.get("frozen_output_contract") or {}
    result = record.get("result") or {}
    process = record.get("process_receipt") or {}
    handle = record.get("handle") or {}
    capability_evidence = (record.get("raw_evidence") or {}).get("capability_evidence") or {}
    provider_view = capability_evidence.get("provider_view") or {}
    prompt_hash = (provider_view.get("component_hashes") or {}).get("fully_rendered_prompt")
    prompt_digest = str(prompt_hash or "").removeprefix("sha256:")
    if (content.get("contract_version") != "authority-execution-recovery.v1"
            or content.get("execution_id") != original.execution_id
            or content.get("request_contract_hash") != original.contract_hash
            or content.get("record_state_hash") != _hash(record).removeprefix("sha256:")
            or original.project_id != project_id or original.book_id != book_id
            or original.operation_id != effect["operation_id"]
            or original.external_effect_id != effect["external_effect_id"]
            or original.stable_idempotency_key != effect["stable_idempotency_key"]
            or frozen.get("execution_request_hash") != original.contract_hash
            or capability_evidence.get("provider_request_envelope_hash") != capability.get("provider_request_envelope_hash")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(frozen.get("request_hash") or ""))
            or frozen.get("contract_hash") != _hash({k:v for k,v in frozen.items() if k != "contract_hash"})
            or handle.get("transport") != "LOCAL_CLI_REMOTE_INFERENCE"
            or not handle.get("backend_id") or not re.fullmatch(r"[0-9a-f]{64}", prompt_digest)
            or process.get("input_sha256") != prompt_digest
            or any(execution.get(key) != record.get(field) for key,field in (
                ("execution_request", "request"), ("execution_handle", "handle"), ("execution_result", "result")))
            or any(process.get(key) != getattr(original, key) or result.get(key) != getattr(original, key)
                   or handle.get(key) != getattr(original, key)
                for key in ("execution_id", "operation_id", "attempt_id", "fencing_token"))):
        raise KernelError("GENERATION_ISOLATION_IDENTITY_CONFLICT", "Reconciled CLI evidence must match the exact durable original execution")
    if (result.get("outcome") not in {"UNKNOWN", "ORPHANED", "TIMED_OUT", "CANCELLED"}
            or any(result.get(key) for key in ("normalized_output_ref", "output_manifest_ref", "raw_output_ref", "usage_receipt_ref"))
            or (record.get("provider_result") or {}).get("outcome") == "success"
            or process.get("status") not in {"FAILED", "TIMED_OUT", "ORPHANED", "CANCELLED"}
            or process.get("result_integrity") == "VALID"):
        raise KernelError("GENERATION_ISOLATION_RESULT_RECOVERABLE", "Reuse the original result or stop its process before isolation")
    require_stopped_reconciled_cli_process(process)
    return record


def require_stopped_reconciled_cli_process(process):
    from novel_forge.modules.production_execution.process_liveness import PosixProcessIdentityProbe

    group = process.get("process_group") or {}
    if not group.get("pid") or process.get("recovery_reason") == "START_INTERRUPTED_PROCESS_ID_UNKNOWN":
        raise KernelError("GENERATION_ISOLATION_PROCESS_LIVE", "The original CLI process identity is unresolved")
    probe = PosixProcessIdentityProbe()
    for pid, recorded_start in ((group["pid"], group.get("process_start_token")),):
        if pid and probe.is_alive(int(pid)):
            current_start = probe.process_start_token(int(pid))
            if not current_start or not recorded_start or str(recorded_start).startswith("unverified:") or current_start == recorded_start:
                raise KernelError("GENERATION_ISOLATION_PROCESS_LIVE", "Original CLI or supervisor is live or its identity cannot be established")
    if process.get("supervisor_pid") and probe.is_alive(int(process["supervisor_pid"])):
        raise KernelError("GENERATION_ISOLATION_PROCESS_LIVE", "The original supervisor identity remains live or unresolved")


def reconciled_cli_isolation_execution(uow, effect, *, project_id, book_id, capability):
    from .external_effect_runtime import _hash

    cursor = uow.cursor
    cursor.execute("""SELECT r.reconciliation_id,r.outcome,r.evidence,r.provider,r.stable_idempotency_key,e.reconciliation
        FROM authority_effect_reconciliation_evidence r JOIN authority_external_effect e USING(external_effect_id)
        WHERE r.external_effect_id=%s ORDER BY r.reconciled_at DESC,r.reconciliation_id DESC LIMIT 1""", [effect["external_effect_id"]])
    row = cursor.fetchone()
    if (not row or row[1] != "ambiguous" or row[2] != row[5]
            or row[3] != effect["provider"] or row[4] != effect["stable_idempotency_key"]):
        raise KernelError("GENERATION_ISOLATION_RECEIPT_MISSING", "Require the original receipt or its exact native query reconciliation")
    execution = row[2].get("production_execution") or {}
    execution_id = (execution.get("execution_request") or {}).get("execution_id")
    cursor.execute("""SELECT v.asset_version_id FROM authority_asset_version v
        JOIN authority_asset a USING(asset_id) WHERE a.project_id=%s AND a.asset_type='execution_recovery_session'
          AND v.content->>'execution_id'=%s ORDER BY v.created_at DESC,v.asset_version_id DESC LIMIT 1""", [project_id, execution_id])
    session = cursor.fetchone()
    if not session:
        raise KernelError("GENERATION_ISOLATION_EXECUTION_EVIDENCE_MISSING", "Retain the original durable recovery session")
    document = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=session[0])
    if document.content_hash != _hash(document.content):
        raise KernelError("GENERATION_ISOLATION_IDENTITY_CONFLICT", "The original recovery session hash must verify")
    record = require_reconciled_cli_isolation_record(document.content, execution,
        effect=effect, project_id=project_id, book_id=book_id, capability=capability)
    return execution, record, {"reconciliation_evidence_id":row[0], "execution_recovery_asset_version_id":session[0],
        "execution_recovery_content_hash":document.content_hash}


def isolation(cursor, effect_id: str):
    cursor.execute(
        "SELECT proof FROM authority_generation_isolation WHERE external_effect_id=%s",
        [effect_id],
    )
    row = cursor.fetchone()
    return row[0] if row else None


def require_not_isolated(cursor, operation_id: str):
    cursor.execute(
        "SELECT external_effect_id FROM authority_generation_isolation WHERE operation_id=%s",
        [operation_id],
    )
    if cursor.fetchone():
        raise KernelError(
            "GENERATION_ATTEMPT_ISOLATED",
            "Old generation has permanently lost business commit and activation rights; follow its registered native continuation",
        )


def book_recovery_projection(cursor, *, project_id, book_id):
    cursor.execute("""WITH RECURSIVE edges(source,target) AS (
        SELECT source_operation_id,successor_operation_id FROM authority_story_planning_runtime_continuation
          WHERE project_id=%s AND successor_operation_id IS NOT NULL
        UNION SELECT predecessor_operation_id,successor_operation_id FROM authority_saga_step_successor
          WHERE project_id=%s), lineage(source,current,depth) AS (
        SELECT operation_id,operation_id,0 FROM authority_generation_isolation WHERE project_id=%s AND book_id=%s
        UNION ALL SELECT lineage.source,edges.target,lineage.depth+1 FROM lineage JOIN edges ON edges.source=lineage.current
          WHERE lineage.depth<32), latest AS (
        SELECT DISTINCT ON(source) source,current,depth FROM lineage ORDER BY source,depth DESC)
        SELECT isolation.external_effect_id,isolation.operation_id,isolation.proof,
          latest.current,operation.status,CASE WHEN operation.status IN
            ('FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER','WAITING_RETRY','RECONCILIATION_REQUIRED')
            THEN COALESCE(NULLIF(attempt.error,'{}'::jsonb),NULLIF(attempt.result,'{}'::jsonb)) END,latest.depth,
          effect.status,budget.status,budget.evidence->>'usage_basis',budget.evidence->'usage',budget.evidence->'cost',exhaustion.payload
        FROM authority_generation_isolation isolation JOIN latest ON latest.source=isolation.operation_id
        JOIN authority_operation operation ON operation.operation_id=latest.current
        LEFT JOIN LATERAL (SELECT error,result FROM authority_attempt WHERE operation_id=latest.current
          ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
        JOIN authority_external_effect effect USING(external_effect_id)
        LEFT JOIN authority_budget_reservation budget USING(external_effect_id)
        LEFT JOIN LATERAL (SELECT payload FROM state_event WHERE aggregate_type='authority_operation'
          AND aggregate_id=latest.current AND event_type='authority.generation.recovery_exhausted'
          ORDER BY sequence_number DESC LIMIT 1) exhaustion ON TRUE
        WHERE isolation.project_id=%s AND isolation.book_id=%s
        ORDER BY isolation.created_at DESC LIMIT 100""", [project_id,project_id,project_id,book_id,project_id,book_id])
    rows=[]
    for effect_id,source,proof,current,status,result,depth,effect_status,budget_status,usage_basis,usage,cost,exhaustion in cursor.fetchall():
        rows.append({"external_effect_id":effect_id,"source_operation_id":source,
            "observed_failure":proof["observed_failure"],"business_commit_right":proof["business_commit_right"],
            "activation_right":proof["activation_right"],"original_remote_outcome":proof["remote_outcome"],
            "original_effect_status":effect_status,"original_budget_status":budget_status,
            "original_usage":proof["usage"],"usage_basis":usage_basis,"current_accounting":{"usage":usage,"cost":cost},
            "continuation_id":proof["continuation_id"],"successor_operation_id":current if depth else None,
            "successor_status":status if depth else None,"successor_failure":result if depth else None,
            "recovery_exhaustion":exhaustion,"recovery_action":"STOP_AT_CHECKPOINT" if exhaustion else "NATIVE_CONTINUATION",
            "recovery_state":"EXHAUSTED" if exhaustion else "SUCCESSOR_COMPLETED" if depth and status=="SUCCEEDED" else
                "SUCCESSOR_FAILED" if depth and status in {"FAILED_FINAL","DEAD_LETTER"} else
                "SUCCESSOR_RUNNING" if depth else "ISOLATED_AWAITING_NATIVE_SUCCESSOR"})
    return rows


def checkpoint_orphaned_cli_dispatch(database_url, *, project_id, book_id, principal, execution_id, evidence):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from novel_forge.modules.production_execution.contracts import ExecutionRequest
    from .external_effect_runtime import EffectCommandContext, _hash, _record
    from .budget_runtime import resolve_provider_budget_failure_in_uow
    from novel_forge.modules.authority_security.service import PrincipalType

    principal.require("external_effect.resolve", project_id)
    production = evidence.get("production_execution") or {}
    request = ExecutionRequest.from_dict(production.get("execution_request") or {})
    if (request.execution_id != execution_id or request.project_id != project_id or request.book_id != book_id):
        raise KernelError("ORPHANED_DISPATCH_IDENTITY_CONFLICT", "Retain the original project, Book and execution")
    with AuthorityUnitOfWork(database_url) as uow:
        cursor = uow.cursor
        effect = uow.repositories.external_effects.get_for_update(request.external_effect_id)
        cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE", [request.operation_id])
        row = cursor.fetchone()
        operation = row[0] if row else {}
        if (effect["project_id"] != project_id or effect["operation_id"] != request.operation_id
                or operation.get("project_id") != project_id
                or (operation.get("actor_id") != principal.principal_id and principal.principal_type is not PrincipalType.LOCAL_OPERATOR)):
            raise KernelError("ORPHANED_DISPATCH_IDENTITY_CONFLICT", "Only the original scoped owner can checkpoint this dispatch")
        if effect["effect_type"] != "model.invoke" or effect["status"] != "DISPATCHING" or operation["status"] != "FAILED_RETRYABLE":
            return False
        cursor.execute("""SELECT v.asset_version_id FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='execution_recovery_session' AND v.content->>'execution_id'=%s
            ORDER BY v.created_at DESC LIMIT 1""", [project_id, execution_id])
        row = cursor.fetchone()
        if not row:
            raise KernelError("ORPHANED_DISPATCH_EVIDENCE_REQUIRED", "Require the original persistent Gateway recovery record")
        document = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=row[0])
        content, record = document.content, document.content.get("record") or {}
        result, process, handle = record.get("result") or {}, record.get("process_receipt") or {}, record.get("handle") or {}
        if (document.content_hash != _hash(content) or content.get("record_state_hash") != _hash(record).split(":", 1)[1]
                or content.get("request_contract_hash") != request.contract_hash
                or record.get("request") != request.to_dict() or production.get("execution_handle") != handle
                or production.get("execution_result") != result or handle.get("transport") != "LOCAL_CLI_REMOTE_INFERENCE"
                or result.get("outcome") != "ORPHANED" or process.get("status") != "ORPHANED"
                or process.get("result_integrity") == "VALID" or result.get("normalized_output_ref") or result.get("raw_output_ref")
                or result.get("usage_receipt_ref")):
            raise KernelError("ORPHANED_DISPATCH_EVIDENCE_CONFLICT", "Require unchanged orphaned local evidence without a complete result")
        for key in ("execution_id", "operation_id", "attempt_id", "fencing_token"):
            if process.get(key) != getattr(request, key) or result.get(key) != getattr(request, key):
                raise KernelError("ORPHANED_DISPATCH_IDENTITY_CONFLICT", "Original process and result identities differ")
        receipt_ref = result.get("process_receipt_ref") or ""
        if not receipt_ref.startswith("authority-asset-version:"):
            raise KernelError("ORPHANED_DISPATCH_EVIDENCE_REQUIRED", "Require the persisted original process receipt")
        receipt = uow.repositories.asset_documents.require(project_id=project_id, asset_version_id=receipt_ref.split(":", 1)[1])
        if receipt.content_hash != _hash(receipt.content) or receipt.content.get("payload", receipt.content) != process:
            raise KernelError("ORPHANED_DISPATCH_EVIDENCE_CONFLICT", "Original receipt differs from the Gateway observation")
        cursor.execute("""SELECT dispatch_id,generation,status,payload_hash FROM authority_external_effect_dispatch
            WHERE external_effect_id=%s ORDER BY generation DESC LIMIT 1 FOR UPDATE""", [request.external_effect_id])
        dispatch = cursor.fetchone()
        if not dispatch or dispatch[2] != "DISPATCHING" or dispatch[3] != effect["request_hash"]:
            return False
        cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
            WHERE a.operation_id=%s AND l.status='HELD' AND l.expires_at>NOW()) OR
            EXISTS(SELECT 1 FROM authority_effect_dispatch_lease WHERE dispatch_id=%s AND status='HELD' AND expires_at>NOW())""",
            [request.operation_id, dispatch[0]])
        if cursor.fetchone()[0]:
            return False
        cursor.execute("SELECT status FROM authority_attempt WHERE attempt_id=%s AND operation_id=%s", [request.attempt_id, request.operation_id])
        attempt = cursor.fetchone()
        if not attempt or attempt[0] != "FAILED_RETRYABLE":
            return False
        cursor.execute("""UPDATE authority_effect_dispatch_lease SET status='EXPIRED',released_at=NOW(),
            release_reason='orphaned_original_dispatch' WHERE dispatch_id=%s AND status='HELD' AND expires_at<=NOW()""", [dispatch[0]])
        observed = {**evidence, "recovery_action": "ORPHANED_ORIGINAL_DISPATCH_CHECKPOINT",
            "recovery_record_asset_version_id": document.asset_version_id, "remote_outcome": "UNKNOWN"}
        repository = uow.repositories.external_effects
        repository.submit_result(repository.dispatch_for_update(dispatch[0]), "unknown", observed,
            handle["backend_execution_id"], handle.get("provider_request_id") or "")
        resolve_provider_budget_failure_in_uow(uow, reservation_id=request.budget_reservation_id,
            project_id=project_id, external_state_unknown=True)
        context = EffectCommandContext(request.operation_id, project_id, principal.principal_id, request.trace_id, request.correlation_id)
        _record(repository, context, request.external_effect_id, "external_effect.orphaned_dispatch_checkpointed",
            {"dispatch_id": dispatch[0], "generation": dispatch[1], "process_receipt_ref": receipt_ref,
                "recovery_record_asset_version_id": document.asset_version_id, "outcome": "unknown"})
        uow.commit()
    return True


def recover_book_generations(application, *, project_id, book_id, principal, source_actor_id=None):
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from .manual_effect_resolution import (
        ExternalEffectManualResolutionCommand,
        resolve_external_effect_manually,
    )
    from .budget_runtime import unresolved_cli_outcomes

    from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results

    source_actor_id = source_actor_id or principal.principal_id
    if source_actor_id != principal.principal_id:
        from novel_forge.modules.authority_security.service import PrincipalType
        if principal.principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise PermissionError("Only a scoped trusted operator can recover another native generation owner")
    recover_saved_local_results(application.execution_binder.resolver.execution_preparer.execution_transport,
        database_url=application.database_url, project_id=project_id, book_id=book_id, principal=principal,
        source_actor_id=source_actor_id, operation_definition_name="story_planning.generate")
    from novel_forge.modules.story_planning_runtime.gateway_result_recovery import recover_completed_planning_outputs
    recover_completed_planning_outputs(application, project_id=project_id, book_id=book_id, principal=principal)
    from .execution_window import continue_saved_result_finalization
    continue_saved_result_finalization(application.database_url, project_id=project_id,
        book_id=book_id, principal=principal)
    principal.require("external_effect.resolve", project_id)
    with AuthorityUnitOfWork(application.database_url) as uow:
        uow.cursor.execute("""SELECT generation.operation_id,operation.version FROM authority_story_planning_generation generation
            JOIN authority_operation operation USING(operation_id)
            JOIN LATERAL (SELECT result FROM authority_attempt WHERE operation_id=operation.operation_id
              ORDER BY attempt_number DESC LIMIT 1) attempt ON TRUE
            WHERE generation.project_id=%s AND generation.book_id=%s AND operation.actor_id=%s
              AND operation.status IN ('FAILED_RETRYABLE','FAILED_FINAL','DEAD_LETTER') AND COALESCE(generation.candidate_asset_version_id,'')=''
              AND (attempt.result->>'error_code'='PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED' OR (
                attempt.result->>'error_code'='PROVIDER_ROUTING_BLOCKED' AND generation.generator_operation_name='arc_plan.generate'
                AND EXISTS(SELECT 1 FROM authority_operation_output_asset output JOIN authority_asset_version version USING(asset_version_id)
                  JOIN authority_asset asset ON asset.asset_id=version.asset_id WHERE output.operation_id=operation.operation_id
                  AND asset.asset_type='routing_decision' AND version.content->>'status'='BLOCKED'
                  AND jsonb_path_exists(version.content,'$.candidates[*].rejected_reasons[*] ? (@ == "CONTEXT_CAPACITY_EXCEEDED")'))))
              AND NOT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=generation.operation_id)
              AND NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation WHERE source_operation_id=generation.operation_id)""",
            [project_id,book_id,source_actor_id])
        capacities=uow.cursor.fetchall()
        rows = unresolved_cli_outcomes(uow.cursor, project_id, book_id=book_id)
        uow.cursor.execute("""SELECT effect.external_effect_id,effect.operation_id,effect.status
            FROM authority_external_effect effect JOIN authority_story_planning_generation generation USING(operation_id)
            JOIN authority_operation operation ON operation.operation_id=effect.operation_id
            WHERE effect.project_id=%s AND generation.book_id=%s AND operation.actor_id=%s
              AND effect.effect_type='model.invoke' AND effect.status IN ('UNKNOWN','RECONCILIATION_REQUIRED')
              AND operation.status IN ('WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED','FAILED_FINAL','DEAD_LETTER')
              AND NOT authority_generation_isolated(effect.external_effect_id)""",[project_id,book_id,source_actor_id])
        seen={row["external_effect_id"] for row in rows}
        rows.extend({"external_effect_id":row[0],"operation_id":row[1],"effect_status":row[2]} for row in uow.cursor.fetchall() if row[0] not in seen)
        uow.cursor.execute(
            """SELECT to_jsonb(e),to_jsonb(o) FROM authority_generation_isolation i
            JOIN authority_external_effect e USING(external_effect_id) JOIN authority_operation o ON o.operation_id=i.operation_id
            WHERE i.project_id=%s AND i.book_id=%s AND o.definition_name='story_planning.generate' AND NOT EXISTS(SELECT 1 FROM authority_story_planning_runtime_continuation r
            WHERE r.source_operation_id=i.operation_id)""",
            [project_id, book_id],
        )
        pending = uow.cursor.fetchall()
    for operation_id,version in capacities:
        application.register_runtime_continuation(operation_id,project_id=project_id,principal=principal,
            expected_source_version=version,decision_evidence={"authorization_ref":"NATIVE_CONTINUOUS_CREATION_TEMPLATE",
                "reason":"Allocate bounded native task capacity after a proven unsent failure while retaining original inputs and authorization"},
            trace_id="trace:generation-capacity:"+operation_id,correlation_id=book_id)
    candidates = {effect["external_effect_id"]: (effect, operation) for effect, operation in pending}
    for item in rows:
        with AuthorityUnitOfWork(application.database_url) as uow:
            effect = uow.repositories.external_effects.get_for_update(item["external_effect_id"])
            uow.cursor.execute("SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s", [effect["operation_id"]])
            operation = uow.cursor.fetchone()[0]
        if operation["definition_name"] == "story_planning.generate":
            candidates[effect["external_effect_id"]] = (effect, operation)
    for effect, operation in candidates.values():
        exhausted = None
        with AuthorityUnitOfWork(application.database_url, coordinate_nested=True) as uow:
            effect = uow.repositories.external_effects.get_for_update(effect["external_effect_id"])
            authorization = effect["request_payload"].get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {}).get("selected", {}).get("candidate", {}).get("authorization_ref")
            proof = isolation(uow.cursor, effect["external_effect_id"])
            if not proof:
                uow.cursor.execute("SELECT version FROM authority_operation WHERE operation_id=%s", [operation["operation_id"]])
                version = uow.cursor.fetchone()[0]
                resolve_external_effect_manually(application.database_url, ExternalEffectManualResolutionCommand(
                    effect["external_effect_id"], operation["operation_id"], project_id, operation["actor_id"],
                    "ISOLATE_PURE_GENERATION", "Original stopped pure generation has no recoverable result; preserve remote facts and continue the same task",
                    {"authorization_ref": authorization, "recovery_operator_principal_id": principal.principal_id}, "generation-isolation:" + effect["external_effect_id"],
                    version, operation["trace_id"], operation["correlation_id"]))
                proof = isolation(uow.cursor, effect["external_effect_id"])
            uow.cursor.execute("SELECT version FROM authority_operation WHERE operation_id=%s", [operation["operation_id"]])
            version = uow.cursor.fetchone()[0]
            try:
                application.register_runtime_continuation(operation["operation_id"], project_id=project_id,
                    principal=principal, expected_source_version=version,
                    decision_evidence={"authorization_ref": proof["authorization_ref"], "reason": proof["reason"]},
                    trace_id=operation["trace_id"], correlation_id=operation["correlation_id"])
            except KernelError as error:
                if error.code != "GENERATION_RECOVERY_EXHAUSTED":
                    raise
                exhausted = error
                _record_exhaustion(uow, operation, error)
            uow.commit()
        if exhausted:
            raise exhausted
    if candidates:
        sleep(30)
    return bool(candidates or capacities)


def append_isolation(uow, effect, command):
    cursor = uow.cursor
    prior = isolation(cursor, effect["external_effect_id"])
    if prior:
        return prior
    cursor.execute(
        "SELECT to_jsonb(o) FROM authority_operation o WHERE operation_id=%s FOR UPDATE",
        [effect["operation_id"]],
    )
    operation = cursor.fetchone()[0]
    source_generation = operation["definition_name"] == "source.import.deconstruction.execute"
    source_binding = None
    if source_generation:
        from novel_forge.modules.source_import.generation_recovery import source_observation_isolation_binding

        source_binding = source_observation_isolation_binding(cursor, operation, command)
    from .cli_effect_reconciliation import historical_cli_dispatch
    historical = historical_cli_dispatch(cursor, effect)
    stopped_legacy = bool(historical and historical["evidence"]["production_execution"]["execution_result"]["outcome"] in {"UNKNOWN", "TIMED_OUT", "CANCELLED", "ORPHANED"})
    followup_generation = operation['definition_name'] == 'longform.prose_review'
    if followup_generation and (operation['root_operation_id'] != operation['operation_id']
        or operation['parent_operation_id'] or operation['definition_snapshot']['family'] != 'book_followup_authority'
        or any(operation['definition_snapshot']['policy'].get(key) is not False for key in ('body_mutation_allowed','plan_mutation_allowed'))
        or operation['definition_snapshot']['irreversible_effect_policy'].get('allowed') is not False):
        raise KernelError('GENERATION_ISOLATION_SCOPE_UNSAFE', 'Review recovery requires the original read-only sidecar boundary')
    chapter_generation = operation["definition_name"] in {
        "chapter.context.build",
        "chapter.memo.generate",
        "chapter.draft.generate",
        "chapter.review.evaluate",
        "chapter.revision.apply",
        "chapter.revision.review",
        "chapter.canon.extract",
    }
    if (
        operation["status"]
        not in {
            "FAILED_FINAL",
            "DEAD_LETTER",
            "WAITING_EXTERNAL_RESULT",
            "RECONCILIATION_REQUIRED",
            *({"FAILED_RETRYABLE"} if stopped_legacy else set()),
        }
        or (not source_generation and operation["actor_id"] != command.actor_id)
        or not (
            operation["definition_name"] == "story_planning.generate"
            or chapter_generation
            or followup_generation
            or source_generation
        )
        or effect["effect_type"] != "model.invoke"
        or effect["status"] not in {"UNKNOWN", "RECONCILIATION_REQUIRED", *({"FAILED_RETRYABLE"} if stopped_legacy else set())}
    ):
        raise KernelError(
            "GENERATION_ISOLATION_SCOPE_UNSAFE",
            "Only an owned stopped native model generation can be isolated",
        )
    cursor.execute(
        """SELECT 1 WHERE EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
          WHERE a.operation_id=%s AND l.status='HELD') OR EXISTS(SELECT 1 FROM authority_effect_dispatch_lease l
          JOIN authority_external_effect_dispatch d USING(dispatch_id) WHERE d.external_effect_id=%s AND l.status='HELD')""",
        [effect["operation_id"], effect["external_effect_id"]],
    )
    if cursor.fetchone():
        raise KernelError(
            "GENERATION_ISOLATION_WRITER_ACTIVE",
            "Release or expire the original writer lease before isolation",
        )
    cursor.execute(
        "SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND role='primary'",
        [effect["operation_id"]],
    )
    if cursor.fetchone():
        raise KernelError(
            "GENERATION_ISOLATION_RESULT_RECOVERABLE",
            "Read and reuse the original primary output",
        )
    if chapter_generation:
        from .step_successor import require_live_chapter_frontier
        from .step_successor_v2 import has_domain_outputs

        require_live_chapter_frontier(
            cursor,
            root_id=operation["root_operation_id"],
            project_id=command.project_id,
        )
        if has_domain_outputs(cursor, operation["operation_id"]):
            raise KernelError(
                "GENERATION_ISOLATION_RESULT_RECOVERABLE",
                "Reuse the immutable domain output",
            )
        cursor.execute("SELECT to_jsonb(root) FROM authority_operation root WHERE operation_id=%s", [operation["root_operation_id"]])
        chapter_root = cursor.fetchone()[0]
        from novel_forge.modules.chapter_authority.working_revision import ROOT_VERSIONS
        if chapter_root["definition_version"] in ROOT_VERSIONS:
            cursor.execute("""SELECT book.book_id,book.workspace_id FROM authority_book_production book
                JOIN authority_operation root ON root.command_payload #>> '{preparation_report,working_revision,book_run_id}'=book.book_run_id
                JOIN authority_saga_step step ON step.operation_id=%s AND step.saga_id=%s
                WHERE root.operation_id=%s AND book.project_id=%s AND root.actor_id=%s
                  AND root.status='WAITING_CHILDREN'""",
                [operation["operation_id"], operation["saga_id"], operation["root_operation_id"], command.project_id, command.actor_id])
        else:
            cursor.execute(
            """SELECT book.book_id,book.workspace_id FROM authority_book_chapter_request request
            JOIN authority_book_production book USING(book_run_id)
            JOIN authority_saga_step step ON step.operation_id=%s AND step.saga_id=%s
            JOIN authority_operation root ON root.operation_id=request.chapter_root_operation_id
            WHERE request.chapter_root_operation_id=%s AND book.project_id=%s
            AND root.definition_name='chapter.slice.run' AND root.actor_id=%s
            AND root.status='WAITING_CHILDREN'""",
            [
                operation["operation_id"],
                operation["saga_id"],
                operation["root_operation_id"],
                command.project_id,
                command.actor_id,
            ],
        )
    elif source_generation:
        generation = ("source-corpus:" + command.project_id, operation["workspace_id"])
    elif followup_generation:
        cursor.execute("""SELECT book.book_id,book.workspace_id FROM authority_book_prose_review_event event
            JOIN authority_book_prose_review_run run USING(run_id)
            JOIN authority_book_production book USING(book_run_id)
            WHERE event.kind='WINDOW_ADMITTED' AND authority_generation_current_operation(event.content->>'operation_id')=%s
            AND run.project_id=%s AND book.project_id=%s AND book.workspace_id=%s
            AND book.book_id=%s""",
            [operation['operation_id'],command.project_id,command.project_id,operation['workspace_id'],
                operation['command_payload'].get('payload',{}).get('book_id')])
    else:
        cursor.execute(
            "SELECT book_id, workspace_id FROM authority_story_planning_generation WHERE operation_id=%s",
            [operation["operation_id"]],
        )
    if not source_generation:
        generation = cursor.fetchone()
    frozen = (
        operation["command_payload"]
        if chapter_generation
        else operation["command_payload"].get("payload", {})
    )
    runtime = effect["request_payload"].get("_production_execution") or {}
    if (
        not generation
        or (generation[0], generation[1])
        != (runtime.get("book_id"), operation["workspace_id"])
        or (
            not chapter_generation and not followup_generation and not source_generation
            and (
                frozen.get("project_id"),
                frozen.get("workspace_id"),
                frozen.get("book_id"),
            )
            != (command.project_id, operation["workspace_id"], generation[0])
        )
        or (chapter_generation and frozen.get("book_id") != generation[0])
    ):
        raise KernelError(
            "GENERATION_ISOLATION_SCOPE_UNSAFE",
            "Original native generation and frozen request must bind the same Book and workspace",
        )
    capability = runtime.get("capability_runtime") or {}
    materialization_id = capability.get("materialization_asset_version_id")
    materialization = uow.repositories.asset_documents.require(
        project_id=command.project_id, asset_version_id=materialization_id
    )
    tools = materialization.content.get("contract", {}).get("tool_permissions") or {}
    if source_generation:
        from novel_forge.modules.source_import.generation_recovery import require_source_observation_materialization

        admission = uow.repositories.asset_documents.require(
            project_id=command.project_id, asset_version_id=capability.get("provider_admission_asset_version_id")
        )
        if admission.content_hash != capability.get("provider_admission_content_hash"):
            raise KernelError("SOURCE_ISOLATION_MATERIALIZATION_INVALID", "Retain the original Provider admission")
        require_source_observation_materialization(materialization.content["contract"], capability,
            frozen["analysis_task"]["analyzer"], admission.content["contract"])
    if (
        materialization.content_hash != capability.get("materialization_content_hash")
        or tools.get("default") != "DENY"
        or set(tools.get("allowed") or []) != {"model.provider.invoke"}
    ):
        raise KernelError(
            "GENERATION_ISOLATION_TOOL_BOUNDARY_UNSAFE",
            "Frozen input must disable every external write Tool",
        )
    cursor.execute(
        "SELECT to_jsonb(d) FROM authority_external_effect_dispatch d WHERE external_effect_id=%s ORDER BY generation FOR UPDATE",
        [effect["external_effect_id"]],
    )
    dispatches = [r[0] for r in cursor.fetchall()]
    if not dispatches or any(
        d["payload_hash"] != effect["request_hash"] for d in dispatches
    ):
        raise KernelError(
            "GENERATION_ISOLATION_IDENTITY_CONFLICT",
            "Every original dispatch must bind the frozen request",
        )
    cursor.execute(
        "SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1",
        [effect["operation_id"]],
    )
    pack = cursor.fetchone()
    if source_generation:
        pack = ({"source_materialization_asset_version_id": materialization_id,
            "source_materialization_content_hash": materialization.content_hash,
            "source_recovery": source_binding},)
    if not pack:
        raise KernelError(
            "GENERATION_ISOLATION_CONTRACT_MISSING",
            "Retain the original execution Pack",
        )
    last = dispatches[-1]
    execution = last["evidence"].get("production_execution") or {}
    result = execution.get("execution_result") or {}
    reconciled_record, reconciled_binding = None, {}
    if not result.get("process_receipt_ref") and (execution.get("execution_handle") or {}).get("transport") != "REMOTE_PROVIDER_API":
        execution, reconciled_record, reconciled_binding = reconciled_cli_isolation_execution(uow, effect,
            project_id=command.project_id, book_id=generation[0], capability=capability)
        result = execution["execution_result"]
    from types import SimpleNamespace
    transport = (execution.get("execution_handle") or {}).get("transport")
    if source_generation and transport != "LOCAL_CLI_REMOTE_INFERENCE":
        raise KernelError("SOURCE_ISOLATION_SCOPE_INVALID", "Source isolation requires the stopped original local CLI")
    if transport == "REMOTE_PROVIDER_API":
        cursor.execute("""SELECT version.asset_version_id,version.content FROM authority_asset_version version
            JOIN authority_asset asset USING(asset_id)
            WHERE asset.project_id=%s AND asset.asset_type='execution_recovery_session'
              AND version.content #>> '{record,request,external_effect_id}'=%s
            ORDER BY version.created_at DESC LIMIT 1""",[command.project_id,effect["external_effect_id"]])
        session = cursor.fetchone()
        if not session:
            raise KernelError("GENERATION_ISOLATION_EXECUTION_EVIDENCE_MISSING", "Retain the original durable API invocation and frozen tool boundary")
        original, record = require_native_api_isolation_record(session[1], project_id=command.project_id,
            book_id=generation[0], operation_id=operation["operation_id"], effect_id=effect["external_effect_id"], capability=capability)
        process = {"execution_id":original.execution_id,"attempt_id":original.attempt_id,"fencing_token":original.fencing_token}
        observed = (record.get("raw_evidence") or {}).get("failure")
        if not observed:
            observed = {"error_code":"ORIGINAL_RESULT_UNRECOVERABLE","stage":"PROVIDER_RESPONSE",
                "cause":"The durable invocation has no recoverable completion and the original writer is stopped",
                "identity":process,"retryable":True,"recovery_action":"ISOLATE_AND_CONTINUE",
                "recovery_state":"REQUIRED","business_impact":"CURRENT_TASK_BLOCKED"}
        ref = None
        evidence_asset_version_id = session[0]
    else:
        ref = result.get("process_receipt_ref")
        if not ref or not ref.startswith("authority-asset-version:"):
            raise KernelError(
                "GENERATION_ISOLATION_RECEIPT_MISSING",
                "The original local process receipt is required",
            )
        receipt = uow.repositories.asset_documents.require(
            project_id=command.project_id, asset_version_id=ref.split(":", 1)[1]
        )
        process = receipt.content.get("payload", receipt.content)
        if reconciled_record is not None:
            from .external_effect_runtime import _hash
            if (process != reconciled_record["process_receipt"]
                    or receipt.content.get("payload_hash") != _hash(process).removeprefix("sha256:")):
                raise KernelError("GENERATION_ISOLATION_IDENTITY_CONFLICT", "The queried process receipt must verify against its exact native recovery record")
        if (
            process.get("operation_id") != effect["operation_id"]
            or process.get("status") not in {"FAILED", "TIMED_OUT", "ORPHANED", "CANCELLED"}
            or process.get("result_integrity") == "VALID"
        ):
            raise KernelError(
                "GENERATION_ISOLATION_RESULT_RECOVERABLE",
                "Require stopped original execution without a complete local result",
            )
        from pathlib import Path
        import json

        result_path = process.get("result_path")
        if result_path and Path(result_path).is_file() and Path(result_path).stat().st_size and process.get("result_integrity") != "CORRUPT":
            raise KernelError(
                "GENERATION_ISOLATION_RESULT_RECOVERABLE",
                "Reconcile the local result before isolating generation",
            )
        stdout_path = process.get("stdout_path")
        if not stdout_path or not Path(stdout_path).is_file():
            raise KernelError(
                "GENERATION_ISOLATION_EXECUTION_EVIDENCE_MISSING",
                "Original CLI event stream must remain readable",
            )
        for line in Path(stdout_path).read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(event, dict)
                and isinstance(event.get("item"), dict)
                and event["item"].get("type")
                in {"command_execution", "mcp_tool_call", "file_change", "web_search"}
            ):
                raise KernelError(
                    "GENERATION_ISOLATION_TOOL_BOUNDARY_UNSAFE",
                    "Observed Tool work requires its owning external-effect reconciliation",
                )
        from novel_forge.modules.production_execution.provider_protocol_failure import (
            observed_provider_failure,
        )

        observed = observed_provider_failure(
            Path(stdout_path).read_text(),
            status=process["status"],
            request=SimpleNamespace(
                **{**process, "project_id": command.project_id, "book_id": generation[0]}
            ),
        )
        evidence_asset_version_id = receipt.asset_version_id
    proof = {
        **reconciled_binding,
        "observed_failure": observed,
        "contract_version": "source-generation-isolation.v1" if source_generation else CONTRACT,
        "external_effect_id": effect["external_effect_id"],
        "operation_id": effect["operation_id"],
        "project_id": command.project_id,
        "workspace_id": operation["workspace_id"],
        "book_id": runtime.get("book_id"),
        "request_hash": effect["request_hash"],
        "dispatch_ids": [d["dispatch_id"] for d in dispatches],
        "process_receipt_ref": ref,
        "materialization_asset_version_id": materialization_id,
        "materialization_hash": materialization.content_hash,
        "pack_snapshot": pack[0],
        "local_execution": {
            k: process.get(k)
            for k in (
                "execution_id",
                "attempt_id",
                "fencing_token",
                "input_sha256",
                "command_sha256",
            )
        },
        "remote_outcome": "UNKNOWN",
        "usage": "UNKNOWN",
        "original_history": "PRESERVED",
        "business_commit_right": "REVOKED",
        "activation_right": "REVOKED",
        "continuation_id": (
            "chapter-generation-successor:"
            if chapter_generation
            else "source-analysis-version:" if source_generation
            else "followup-generation-successor:" if followup_generation else "planning-runtime-continuation:"
        )
        + effect["operation_id"],
        "recovery_state": "ISOLATED_AWAITING_NATIVE_SUCCESSOR",
        "reason": command.reason,
        "authorization_ref": command.evidence.get("authorization_ref"),
        "actor_id": command.actor_id,
        "recovery_operator_principal_id": command.evidence.get("recovery_operator_principal_id", command.actor_id),
    }
    if not proof["authorization_ref"] or not proof["book_id"]:
        raise KernelError(
            "GENERATION_ISOLATION_AUTHORIZATION_REQUIRED",
            "Bind actual generation recovery authorization and original Book",
        )
    proof["stopped_legacy_cli"] = stopped_legacy
    if source_generation:
        proof["source_recovery"] = source_binding
        proof["recovery_state"] = "ISOLATED_AWAITING_VERSIONED_ANALYSIS"
    proof["execution_transport"] = transport
    proof["evidence_asset_version_id"] = evidence_asset_version_id
    if operation["status"] not in {"FAILED_FINAL", "DEAD_LETTER"}:
        from .attempt_runtime import _cas_operation, _transition_attempt

        attempt = uow.repositories.attempt_runtime.get_for_update(
            process["attempt_id"], command.project_id
        )
        if (
            attempt["operation_id"] != operation["operation_id"]
            or (attempt["status"] != "CHECKPOINTED" and not (stopped_legacy and operation["status"] == "FAILED_RETRYABLE" and attempt["status"] == "FAILED_RETRYABLE"))
        ):
            raise KernelError(
                "GENERATION_ISOLATION_WRITER_ACTIVE",
                "Only a released stopped reconciliation checkpoint may be retired",
            )
        if attempt["status"] == "CHECKPOINTED":
            _transition_attempt(
                uow,
                attempt,
                "CANCELLED",
                worker_id=command.actor_id,
                fencing_token=None,
                trace_id=command.trace_id,
                correlation_id=command.correlation_id,
                result={
                    "error_code": "GENERATION_ATTEMPT_ISOLATED",
                    "failure": observed,
                    "local_execution_disposition": "RETIRED",
                    "remote_cancellation": "NOT_ESTABLISHED",
                },
            )
        _cas_operation(
            uow,
            operation_id=operation["operation_id"],
            project_id=command.project_id,
            expected_status=operation["status"],
            expected_version=operation["version"],
            target_status="FAILED_FINAL",
            actor_id=command.actor_id,
            reason="Isolate stopped pure generation; remote outcome and usage remain UNKNOWN",
            trace_id=command.trace_id,
            correlation_id=command.correlation_id,
            causation_id=effect["external_effect_id"],
        )
    cursor.execute(
        """INSERT INTO authority_generation_isolation(isolation_id,external_effect_id,operation_id,
        project_id,workspace_id,book_id,request_hash,materialization_asset_version_id,proof)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            str(uuid4()),
            effect["external_effect_id"],
            operation["operation_id"],
            command.project_id,
            operation["workspace_id"],
            proof["book_id"],
            effect["request_hash"],
            materialization_id,
            Jsonb(proof),
        ],
    )
    return proof


def recover_chapter_generations(authority, *, book_run_id, principal, working_revision_root_id=None):
    from .manual_effect_resolution import (
        ExternalEffectManualResolutionCommand,
        resolve_external_effect_manually,
    )
    from .service import AdmissionContext
    from .step_successor_v2 import replace_failed_step
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    book = authority.require(book_run_id)
    if not book.get("active_chapter_request_id") and not working_revision_root_id:
        return False
    for permission in (
        "external_effect.resolve",
        "book.authority.execute",
        "chapter.authority.execute",
    ):
        principal.require(permission, book["project_id"])
    if working_revision_root_id:
        from novel_forge.modules.chapter_authority.working_revision import require_working_revision_frontier
        with AuthorityUnitOfWork(authority.database_url) as uow:
            uow.cursor.execute("SELECT to_jsonb(root) FROM authority_operation root WHERE operation_id=%s", [working_revision_root_id])
            row = uow.cursor.fetchone()
            if row is None or row[0]["actor_id"] != principal.principal_id:
                raise KernelError("GENERATION_ISOLATION_SCOPE_UNSAFE", "Require this operator's exact working revision Root")
            require_working_revision_frontier(uow, root=row[0], book_run_id=book_run_id)
        root_id = working_revision_root_id
        request = {"chapter_request_id": None}
    else:
        request = authority.require_chapter_request(book["active_chapter_request_id"])
        root_id = request["chapter_root_operation_id"]
    from novel_forge.modules.production_execution.saved_result_recovery import recover_saved_local_results

    from novel_forge.modules.chapter_authority.receipt_recovery import recover_completed_chapter_results
    revalidated = recover_completed_chapter_results(authority, book_run_id=book_run_id,
        principal=principal, root_operation_id=root_id)
    recovered = recover_saved_local_results(authority.chapter_port.application._model_port.adapter,
        database_url=authority.database_url, project_id=book["project_id"], book_id=book["book_id"], principal=principal,
        root_operation_id=root_id)
    with AuthorityUnitOfWork(authority.database_url) as uow:
        uow.cursor.execute(
            """SELECT to_jsonb(o) FROM authority_operation o
            JOIN authority_saga_step step USING(operation_id) WHERE o.root_operation_id=%s
            AND o.status IN ('WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED','FAILED_FINAL','DEAD_LETTER')
            AND EXISTS(SELECT 1 FROM authority_external_effect effect WHERE effect.operation_id=o.operation_id
              AND effect.effect_type='model.invoke' AND effect.status IN ('UNKNOWN','RECONCILIATION_REQUIRED'))
            ORDER BY o.created_at""",
            [root_id],
        )
        sources = [row[0] for row in uow.cursor.fetchall()]
    changed = recovered or revalidated
    for source in sources:
        exhausted = None
        with AuthorityUnitOfWork(authority.database_url, coordinate_nested=True) as uow:
            uow.repositories.operation_graph.saga_for_update(source["saga_id"], book["project_id"])
            uow.cursor.execute("SELECT successor_operation_id FROM authority_saga_step_successor WHERE predecessor_operation_id=%s", [source["operation_id"]])
            if uow.cursor.fetchone():
                continue
            uow.cursor.execute("SELECT to_jsonb(e) FROM authority_external_effect e WHERE operation_id=%s ORDER BY external_effect_id FOR UPDATE", [source["operation_id"]])
            effects = [row[0] for row in uow.cursor.fetchall()]
            uncertain, completed = partition_generation_effects(effects)
            for effect in uncertain:
                if isolation(uow.cursor, effect["external_effect_id"]):
                    continue
                authorization = effect["request_payload"].get("_production_execution", {}).get("capability_runtime", {}).get("routing_decision", {}).get("selected", {}).get("candidate", {}).get("authorization_ref")
                uow.cursor.execute("SELECT version FROM authority_operation WHERE operation_id=%s", [source["operation_id"]])
                version = uow.cursor.fetchone()[0]
                resolve_external_effect_manually(authority.database_url, ExternalEffectManualResolutionCommand(
                    effect["external_effect_id"], source["operation_id"], book["project_id"], principal.principal_id,
                    "ISOLATE_PURE_GENERATION", "Retire stopped pure generation and retain original unknown remote outcome and usage",
                    {"authorization_ref": authorization}, "generation-isolation:" + effect["external_effect_id"],
                    version, source["trace_id"], source["correlation_id"]))
            proofs = [isolation(uow.cursor, effect["external_effect_id"]) for effect in uncertain]
            uow.cursor.execute("SELECT result->>'error_code' FROM authority_attempt WHERE operation_id=%s ORDER BY attempt_number DESC LIMIT 1", [source["operation_id"]])
            failure_code = uow.cursor.fetchone()[0]
            try:
                retry_usage = require_generation_retry_budget(uow.cursor, operation_id=source["operation_id"])
                replace_failed_step(authority.database_url, predecessor_id=source["operation_id"],
                    target_version=source["definition_version"],
                    context=AdmissionContext(principal.principal_id, principal.permissions,
                        authority.chapter_port.application.registry.available_handler_keys,
                        authority.application_build_id, authority.commit_sha),
                    policy_evidence={"contract_version": "chapter-pure-generation-successor.v1",
                        "generation_isolations": proofs,
                        "completed_model_effects": [{"external_effect_id": e["external_effect_id"], "request_hash": e["request_hash"], "stage": e["request_payload"]["stage"]} for e in completed],
                        "book_run_id": book_run_id, "chapter_request_id": request["chapter_request_id"],
                        "failure_retry_counter": retry_usage, "remote_outcome": "UNKNOWN", "usage": "UNKNOWN",
                        "completion_checks": "UNCHANGED"}, expected_failure_code=failure_code,
                    known_isolated_effects=tuple((e["external_effect_id"], e["request_hash"]) for e in uncertain),
                    known_receipt_effects=tuple((e["external_effect_id"], e["request_hash"]) for e in completed))
            except KernelError as error:
                if error.code != "GENERATION_RECOVERY_EXHAUSTED":
                    raise
                exhausted = error
                _record_exhaustion(uow, source, error)
            uow.commit()
        if exhausted:
            raise exhausted
        changed = True
        sleep(30)
    return changed


def _record_exhaustion(uow, operation, error):
    from .operation_graph import GraphCommandContext, _record
    uow.cursor.execute("SELECT 1 FROM state_event WHERE aggregate_type='authority_operation' AND aggregate_id=%s AND event_type='authority.generation.recovery_exhausted'", [operation["operation_id"]])
    if not uow.cursor.fetchone():
        _record(uow.repositories.operation_graph,
            GraphCommandContext(operation["project_id"], operation["actor_id"], operation["trace_id"], operation["correlation_id"]),
            operation["operation_id"], "authority.generation.recovery_exhausted",
            {"error_code": error.code, **error.details, "recovery_action": "STOP_AT_CHECKPOINT"})


def partition_generation_effects(effects):
    uncertain, completed = [], []
    for effect in effects:
        if effect["effect_type"] != "model.invoke":
            raise KernelError("GENERATION_ISOLATION_EFFECT_BOUNDARY_UNSAFE", "A non-model effect requires its owning reconciliation; no blind successor")
        if effect["status"] in {"UNKNOWN", "RECONCILIATION_REQUIRED"}:
            uncertain.append(effect)
        elif effect["status"] == "SUCCEEDED":
            completed.append(effect)
        else:
            raise KernelError("GENERATION_RECOVERY_EFFECT_STATE_UNSUPPORTED", "Retain the concrete failure and resolve its current state before bounded node continuation", details={"external_effect_id": effect["external_effect_id"], "status": effect["status"], "cause": effect.get("last_error"), "recovery_action": "CLASSIFY_RETAINED_EFFECT_FAILURE", "business_impact": "CURRENT_NODE_STOPPED"})
    if not uncertain:
        raise KernelError("GENERATION_ISOLATION_RESULT_RECOVERABLE", "No uncertain result exists; reuse completed output")
    return uncertain, completed
