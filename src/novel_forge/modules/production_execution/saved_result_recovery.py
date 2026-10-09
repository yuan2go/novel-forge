from __future__ import annotations

from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext, accept_external_effect_receipt, _hash, _resolve_reconciled_budget, _read_verified_success,
)
from .backends import CodexCliExecutionBackend, RemoteProviderExecutionBackend
from .contracts import ExecutionOutcome


def recover_saved_local_results(transport, *, database_url, project_id, book_id, principal, operation_ids=()):
    principal.require("external_effect.resolve", project_id)
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT effect.external_effect_id,operation.operation_id,operation.trace_id,operation.correlation_id
            FROM authority_external_effect effect JOIN authority_operation operation USING(operation_id)
            JOIN authority_budget_reservation budget USING(external_effect_id)
            WHERE effect.project_id=%s AND operation.actor_id=%s AND effect.effect_type='model.invoke'
              AND effect.request_payload #>> '{_production_execution,book_id}'=%s
              AND effect.status='SUCCEEDED' AND budget.status IN ('RESERVED','HELD_UNKNOWN')
              AND NOT authority_generation_isolated(effect.external_effect_id)
              AND (%s::text[]='{}'::text[] OR operation.operation_id=ANY(%s))""", [project_id,principal.principal_id,book_id,list(operation_ids),list(operation_ids)])
        unsettled=uow.cursor.fetchall()
        accounting=[]
        for effect_id,operation_id,trace_id,correlation_id in unsettled:
            context=EffectCommandContext(operation_id,project_id,principal.principal_id,trace_id,correlation_id)
            verified=_read_verified_success(uow,uow.repositories.external_effects,context,effect_id)
            accounting.append((effect_id,verified["provider_evidence"]))
        uow.cursor.execute("""SELECT DISTINCT v.content->>'execution_id'
            FROM authority_asset_version v JOIN authority_asset asset USING(asset_id)
            JOIN authority_external_effect effect
              ON effect.external_effect_id=v.content #>> '{record,request,external_effect_id}'
            JOIN authority_operation operation ON operation.operation_id=effect.operation_id
            WHERE asset.project_id=%s AND asset.asset_type='execution_recovery_session'
              AND effect.effect_type='model.invoke' AND operation.actor_id=%s
              AND v.content #>> '{record,request,book_id}'=%s
              AND effect.status IN ('DISPATCHING','DISPATCHED','UNKNOWN','RECONCILIATION_REQUIRED')
              AND operation.status IN ('EXECUTING','FAILED_RETRYABLE','WAITING_EXTERNAL_RESULT','RECONCILIATION_REQUIRED')
              AND NOT authority_generation_isolated(effect.external_effect_id)
              AND (%s::text[]='{}'::text[] OR operation.operation_id=ANY(%s))""",
            [project_id, principal.principal_id, book_id,list(operation_ids),list(operation_ids)])
        identities = [row[0] for row in uow.cursor.fetchall()]
    for effect_id,evidence in accounting:
        _resolve_reconciled_budget(database_url,project_id=project_id,effect_id=effect_id,outcome="success",evidence=evidence)
    if not identities:
        return bool(accounting)
    session = transport.session_for_project(project_id)
    recovered = False
    for identity in identities:
        record = session.evidence_store.get_record(identity)
        request, handle = record.request, record.handle
        route = session.gateway.admission.resolve_route(request)
        backend = session.gateway.backends.resolve(route.backend_id)
        if type(backend) not in {CodexCliExecutionBackend, RemoteProviderExecutionBackend}:
            continue
        if type(backend) is RemoteProviderExecutionBackend and not (record.result and record.result.outcome == ExecutionOutcome.SUCCEEDED or record.provider_result and record.provider_result.outcome == "success"):
            continue
        session.gateway.admission._admit_frozen_contracts(request, backend.capability_profile)
        result = (backend.reconcile(handle, _consume_callback=False) if type(backend) is RemoteProviderExecutionBackend else backend.reconcile(handle))
        session.gateway._validate_result(handle, result)
        if result.outcome != ExecutionOutcome.SUCCEEDED:
            continue
        record = session.evidence_store.get_record(identity)
        manifest = session.gateway.admission.contracts.input_manifest(request.input_manifest_ref)
        evidence = {
            "provider_id": route.model_provider, "model_id": route.model_id,
            "prompt_version": manifest.prompt_bundle_version,
            "skill_version": manifest.skill_bundle_version,
            "real_model_call": True, "production_verified": False,
            "result": session.evidence_store.read_evidence(result.normalized_output_ref),
            "production_execution": {"execution_request": request.to_dict(),
                "execution_handle": handle.to_dict(), "execution_result": result.to_dict(),
                "route_snapshot": route.to_dict(), "input_manifest": manifest.to_dict(),
                "process_evidence": record.raw_evidence},
            "recovery_action": "LOCAL_SAVED_RESULT_REUSE", "remote_query_performed": False,
        }
        for key, ref in (("usage", result.usage_receipt_ref), ("cost", result.cost_receipt_ref)):
            if ref:
                evidence[key] = session.evidence_store.read_evidence(ref)
        if record.raw_evidence.get("capability_evidence"):
            evidence["capability_runtime"] = record.raw_evidence["capability_evidence"]
        with AuthorityUnitOfWork(database_url) as uow:
            uow.cursor.execute("""SELECT dispatch_id,generation,payload_hash,effect.request_hash
                FROM authority_external_effect_dispatch dispatch JOIN authority_external_effect effect USING(external_effect_id)
                WHERE effect.external_effect_id=%s AND effect.project_id=%s AND effect.operation_id=%s
                ORDER BY generation DESC LIMIT 1""", [request.external_effect_id, project_id, request.operation_id])
            dispatch = uow.cursor.fetchone()
        if not dispatch or dispatch[2] != dispatch[3]:
            raise KernelError("SAVED_RESULT_DISPATCH_IDENTITY_CONFLICT", identity)
        context = EffectCommandContext(request.operation_id, project_id, principal.principal_id,
            request.trace_id, request.correlation_id)
        receipt_id = "local-result:" + identity
        accept_external_effect_receipt(database_url, context, dispatch_id=dispatch[0],
            provider=transport.provider, receipt_id=receipt_id, message_id=receipt_id,
            payload_hash=_hash(evidence), provider_correlation_id=handle.provider_request_id or handle.backend_execution_id,
            generation=dispatch[1], outcome="success", evidence=evidence)
        _resolve_reconciled_budget(database_url, project_id=project_id,
            effect_id=request.external_effect_id, outcome="success", evidence=evidence)
        recovered = True
    return recovered
