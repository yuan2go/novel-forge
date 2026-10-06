from __future__ import annotations

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_failed_operation_success
from novel_forge.modules.worldbuilding.production_schema import decode_world_generation
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def require_world_result_repair_source(database_url, *, command, operation_id, source_asset_version_id="", require_valid_result=False):
    if not command.world_preparation_request:
        return None
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT output.asset_version_id FROM authority_operation_output_asset output
            JOIN authority_asset a USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
            WHERE output.operation_id=%s AND a.project_id=%s AND a.asset_type='world_preparation_generation'""",
            [operation_id, command.project_id])
        sources = [str(row[0]) for row in uow.cursor.fetchall()]
    if not sources or source_asset_version_id and source_asset_version_id not in sources:
        return None
    if len(sources) != 1 or require_valid_result:
        raise KernelError("WORLD_RESULT_REPAIR_SOURCE_INVALID", "World recovery requires one invalid generation, never a Foundation admission")
    query = AuthorityAssetQuery(database_url)
    document = query.require(project_id=command.project_id, asset_version_id=sources[0])
    stored = document.content["contract"]
    raw, evidence, source_ref = stored["output"], dict(stored["evidence"]), stored["source"]
    source = query.require(project_id=command.project_id, asset_version_id=source_ref["asset_version_id"])
    if (source.asset_type != "world_preparation_source" or source.content_hash != source_ref["content_hash"]
            or source.content["contract"]["request"] != dict(command.world_preparation_request)
            or evidence.get("operation_id") != operation_id):
        raise KernelError("WORLD_RESULT_REPAIR_SOURCE_DRIFT", "World repair requires its exact Book frontier and source")
    effect_id = str(evidence.get("external_receipt_ref") or "")
    receipt = read_failed_operation_success(database_url, EffectCommandContext(operation_id=operation_id,
        project_id=command.project_id, actor_id=command.actor_id, trace_id=command.trace_id,
        correlation_id=command.correlation_id), effect_id=effect_id)
    if receipt is None or receipt["provider_evidence"].get("result") != raw or receipt["budget_reservation_status"] != "SETTLED":
        raise KernelError("WORLD_RESULT_REPAIR_RECEIPT_INVALID", "Reconcile exact succeeded world receipt and usage before repair")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT request_payload FROM authority_external_effect
            WHERE external_effect_id=%s AND operation_id=%s AND project_id=%s""", [effect_id, operation_id, command.project_id])
        row = uow.cursor.fetchone()
        if not row or row[0].get("stage") != "world_candidates.generate":
            raise KernelError("WORLD_RESULT_REPAIR_RECEIPT_INVALID", "Repair cannot substitute another Provider stage")
        task = row[0]["input"]["world_preparation"]
        if task.get("source_ref") != source_ref:
            raise KernelError("WORLD_RESULT_REPAIR_SOURCE_DRIFT", "Dispatched task must bind the retained world source")
        uow.cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset output
            JOIN authority_asset a USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
            WHERE output.operation_id=%s AND a.asset_type='context_bundle' AND v.content->'world_preparation'=%s::jsonb""",
            [operation_id, Jsonb(task)])
        contexts = uow.cursor.fetchall()
        if len(contexts) != 1:
            raise KernelError("WORLD_RESULT_REPAIR_CONTEXT_DRIFT", "World repair requires its exact rendered stage Context")
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s AND status<>'SUCCEEDED')
            OR EXISTS(SELECT 1 FROM authority_budget_reservation WHERE operation_id=%s AND status<>'SETTLED')""", [operation_id, operation_id])
        if uow.cursor.fetchone()[0]:
            raise KernelError("WORLD_RESULT_REPAIR_RECONCILIATION_REQUIRED", "All original calls and usage must be resolved before a successor")
    try:
        decode_world_generation({key: value for key, value in raw.items() if key not in {"knowledge_translations", "actor_adjudications"}})
    except KernelError as error:
        from .result_recovery import PlanningResultValidationError
        diagnostic = PlanningResultValidationError(error, raw_result=raw, execution_evidence=evidence).diagnostic
    else:
        raise KernelError("PLANNING_RESULT_REPAIR_NOT_REQUIRED", "Valid world generation cannot authorize another generation")
    context_id, context_hash, context = contexts[0]
    return {"asset_version_id": document.asset_version_id, "content_hash": document.content_hash,
        "source_operation_id": operation_id, "raw_result": raw, "diagnostic": diagnostic,
        "execution_evidence": evidence, "schema_version": "world-result-repair.v1",
        "context_asset_version_id": str(context_id), "context_hash": context_hash,
        "context_content": context, "provider_stage": "world_candidates.generate", "world_source": source_ref}


def world_result_failures(cursor, *, project_id, effect_ids):
    if not effect_ids:
        return {}
    cursor.execute("""SELECT e.external_effect_id,v.asset_version_id,v.content_hash,v.content FROM authority_external_effect e
        JOIN authority_operation o USING(operation_id)
        JOIN authority_story_planning_generation g USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=o.operation_id
        JOIN authority_asset a ON a.asset_id=output.asset_id AND a.project_id=e.project_id
        JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
        WHERE e.project_id=%s AND e.external_effect_id=ANY(%s) AND e.status='SUCCEEDED'
          AND o.status='FAILED_FINAL' AND g.candidate_asset_version_id IS NULL
          AND a.asset_type='world_preparation_generation' AND v.governance='CLEAR'
          AND v.content #>> '{contract,evidence,external_receipt_ref}'=e.external_effect_id
          AND e.request_payload->>'stage'='world_candidates.generate'""", [project_id, list(effect_ids)])
    result = {}
    from .domain import canonical_hash
    for effect_id, asset_id, digest, content in cursor.fetchall():
        if digest != canonical_hash(content):
            continue
        contract = content['contract']
        evidence = contract['evidence']
        if not evidence.get('real_model_call') or evidence.get('fixture_protocol_only'):
            continue
        try:
            decode_world_generation({key: value for key, value in contract['output'].items()
                if key not in {'knowledge_translations','actor_adjudications'}})
        except KernelError as error:
            result[effect_id] = {'accepted': False, 'failure_class':'SCHEMA_REJECTION',
                'validation_kind':'STRUCTURAL', 'error_code':error.code,
                'metric':'DOMAIN_GATE_ACCEPTANCE.v1', 'evidence_refs':['asset-version:'+asset_id]}
    return result
