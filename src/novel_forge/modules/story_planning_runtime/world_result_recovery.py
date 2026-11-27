from __future__ import annotations

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.external_effect_runtime import (
    EffectCommandContext, read_failed_operation_success, read_checkpointed_operation_success,
    resume_operation_from_completed_effect,
)
from novel_forge.modules.worldbuilding.production_planning import WorldProductionPolicy, validate_generated_candidates
from novel_forge.modules.worldbuilding.production_schema import decode_world_generation
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


WORLD_GENERATION_CONTRACT_ERRORS = frozenset({
    "WORLD_PROVIDER_TRANSITION_INVALID", "WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN",
    "WORLD_GENERATION_IDENTITY_UNKNOWN", "WORLD_GENERATION_BOUND_EXCEEDED",
    "WORLD_GENERATION_DISPOSITION_INVALID", "WORLD_INFORMATION_SCOPE_INVALID",
    "WORLD_GENERATION_IDENTITY_COLLISION", "WORLD_PREPARATION_WINDOW_INVALID",
    "WORLD_AGENCY_CLASSIFICATION_REJECTED",
})
WORLD_CHECKPOINT_ERRORS = frozenset({
    "WORLD_GENERATION_PLAN_REFERENCE_UNKNOWN", "WORLD_GENERATION_IDENTITY_UNKNOWN",
})


def validate_world_generation_result(raw, source, command):
    from .world_preparation import PlanningWorldPreparation
    decoded = decode_world_generation({key: value for key, value in raw.items()
        if key not in {"knowledge_translations", "actor_adjudications"}},
        agency=source["reality"].get("epistemic_contract") == "world-agency.v2")
    candidates = validate_generated_candidates(decoded, WorldProductionPolicy(**source["policy"]))
    PlanningWorldPreparation._validate_references(source, candidates, command)
    return candidates


def require_world_result_repair_source(database_url, *, command, operation_id, source_asset_version_id="", require_valid_result=False, _checkpoint=False):
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
    receipt_reader = read_checkpointed_operation_success if _checkpoint else read_failed_operation_success
    receipt = receipt_reader(database_url, EffectCommandContext(operation_id=operation_id,
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
        validate_world_generation_result(raw, source.content["contract"], command)
        from .world_preparation import PlanningWorldPreparation
        PlanningWorldPreparation.validate_retained_generation(
            database_url, command=command, generation=document
        )
    except KernelError as error:
        if error.code not in WORLD_GENERATION_CONTRACT_ERRORS:
            raise
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


def resume_world_result_checkpoint(database_url, *, command, operation_id):
    from .application import _command_payload
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT o.status,o.command_payload->'payload',g.candidate_asset_version_id,
            a.status,a.checkpoint FROM authority_operation o
            JOIN authority_story_planning_generation g USING(operation_id)
            JOIN LATERAL (SELECT status,checkpoint FROM authority_attempt WHERE operation_id=o.operation_id
                ORDER BY attempt_number DESC LIMIT 1) a ON TRUE
            WHERE o.operation_id=%s AND o.project_id=%s AND o.definition_name='story_planning.generate'""",
            [operation_id, command.project_id])
        row = uow.cursor.fetchone()
        if not row or row[0] != 'WAITING_EXTERNAL_RESULT' or row[3] != 'CHECKPOINTED':
            return False
        code = (row[4] or {}).get('error_code')
        if code not in WORLD_CHECKPOINT_ERRORS:
            return False
        if row[2] or row[1] != _command_payload(command):
            raise KernelError('WORLD_CHECKPOINT_OWNER_DRIFT', 'Recovery requires the exact frozen Planning command without a candidate')
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_lease_acquisition l
            JOIN authority_attempt a USING(attempt_id) WHERE a.operation_id=%s AND l.status='HELD')""", [operation_id])
        if uow.cursor.fetchone()[0]:
            raise KernelError('WORLD_CHECKPOINT_LEASE_ACTIVE', 'Release the historical Attempt lease before recovery')
    retained = require_world_result_repair_source(database_url, command=command, operation_id=operation_id, _checkpoint=True)
    if not retained or retained['diagnostic']['error_code'] != code:
        raise KernelError('WORLD_CHECKPOINT_DIAGNOSTIC_DRIFT', 'The retained result must reproduce its exact known identifier failure')
    resume_operation_from_completed_effect(database_url, EffectCommandContext(operation_id=operation_id,
        project_id=command.project_id, actor_id=command.actor_id, trace_id=command.trace_id,
        correlation_id=command.correlation_id), effect_id=retained['execution_evidence']['external_receipt_ref'])
    return True


def world_result_failures(cursor, *, project_id, effect_ids):
    if not effect_ids:
        return {}
    cursor.execute("""SELECT e.external_effect_id,v.asset_version_id,v.content_hash,v.content,
        o.command_payload->'payload',s.content,s.content_hash FROM authority_external_effect e
        JOIN authority_operation o USING(operation_id)
        JOIN authority_story_planning_generation g USING(operation_id)
        JOIN authority_operation_output_asset output ON output.operation_id=o.operation_id
        JOIN authority_asset a ON a.asset_id=output.asset_id AND a.project_id=e.project_id
        JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
        JOIN authority_asset_version s ON s.asset_version_id=v.content #>> '{contract,source,asset_version_id}'
        WHERE e.project_id=%s AND e.external_effect_id=ANY(%s) AND e.status='SUCCEEDED'
          AND o.status='FAILED_FINAL' AND g.candidate_asset_version_id IS NULL
          AND a.asset_type='world_preparation_generation' AND v.governance='CLEAR'
          AND v.content #>> '{contract,evidence,external_receipt_ref}'=e.external_effect_id
          AND e.request_payload->>'stage'='world_candidates.generate'""", [project_id, list(effect_ids)])
    result = {}
    from .domain import canonical_hash
    from .application import _command_from_payload
    for effect_id, asset_id, digest, content, payload, source, source_hash in cursor.fetchall():
        if digest != canonical_hash(content):
            continue
        contract = content['contract']
        evidence = contract['evidence']
        if not evidence.get('real_model_call') or evidence.get('fixture_protocol_only'):
            continue
        if source_hash != canonical_hash(source) or source_hash != contract['source']['content_hash']:
            continue
        try:
            validate_world_generation_result(contract['output'], source['contract'], _command_from_payload(payload))
        except KernelError as error:
            if error.code not in WORLD_GENERATION_CONTRACT_ERRORS:
                continue
            result[effect_id] = {'accepted': False, 'failure_class':'SCHEMA_REJECTION',
                'validation_kind':'STRUCTURAL', 'error_code':error.code,
                'metric':'DOMAIN_GATE_ACCEPTANCE.v1', 'evidence_refs':['asset-version:'+asset_id]}
    return result
