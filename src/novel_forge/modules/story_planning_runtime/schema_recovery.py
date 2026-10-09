from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.command_kernel.generation_isolation import require_generation_retry_budget
from novel_forge.modules.production_execution.codex_configuration import codex_wire_correction_evidence
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery


def retained_world_action(database_url: str, *, command: Any, source_operation_id: str):
    if not command.world_preparation_request:
        return None, None
    from .world_preparation import PlanningWorldPreparation
    from novel_forge.modules.command_kernel.external_effect_runtime import EffectCommandContext, read_failed_operation_success

    query = AuthorityAssetQuery(database_url)
    action = PlanningWorldPreparation.retained_action(query, command, source_operation_id=source_operation_id)
    refs = action.content['contract']
    for key in ('generation', 'evaluation'):
        reference = refs[key]
        document = query.require(project_id=command.project_id, asset_version_id=reference['asset_version_id'])
        content = document.content['contract']
        receipt = read_failed_operation_success(database_url, EffectCommandContext(
            operation_id=source_operation_id, project_id=command.project_id, actor_id=command.actor_id,
            trace_id=command.trace_id, correlation_id=command.correlation_id), effect_id=content['evidence']['external_receipt_ref'])
        if (document.content_hash != reference['content_hash'] or content['source'] != refs['source']
            or receipt is None or receipt['provider_evidence'].get('result') != content['output']):
            raise KernelError('PLANNING_SCHEMA_WORLD_RECEIPT_INVALID', 'Retained World action requires exact trusted outputs and current source identities')
    return action, {'asset_version_id': action.asset_version_id, 'content_hash': action.content_hash,
        **{key: refs[key] for key in ('source', 'generation', 'evaluation')}}


def require_source(uow, *, source_operation_id: str, row, frozen) -> dict:
    from .application import _command_from_payload

    command = _command_from_payload(frozen)
    uow.cursor.execute("""SELECT output.asset_version_id,version.content_hash,version.content,
        effect.external_effect_id FROM authority_operation_output_asset output
        JOIN authority_asset_version version USING(asset_version_id)
        JOIN authority_asset asset ON asset.asset_id=version.asset_id
        JOIN authority_external_effect effect ON effect.operation_id=output.operation_id
        JOIN authority_external_effect_dispatch dispatch USING(external_effect_id)
        WHERE output.operation_id=%s AND asset.asset_type='model_call_log'
        AND version.content->>'stage'=%s AND effect.status='FAILED_FINAL'
        AND dispatch.status='FAILED_FINAL'
        AND dispatch.evidence->'production_execution'=version.content->'production_execution'
        AND effect.effect_type='model.invoke'""", [source_operation_id, command.generator_operation_name])
    outputs = uow.cursor.fetchall()
    if len(outputs) != 1:
        raise KernelError('PLANNING_SCHEMA_CORRECTION_SOURCE_INVALID', 'Require one immutable rejected Schema invocation and its native dispatch')
    asset_id, asset_hash, content, effect_id = outputs[0]
    production = content['production_execution']
    process = production['process_evidence']
    request = production['execution_request']
    correction = codex_wire_correction_evidence(process)
    if (not correction or correction['contract_version'] != 'codex-nullable-shared-types.v3'
        or process.get('failure_code') != 'PROVIDER_SCHEMA_REJECTED'
        or process.get('allowed_tools') != ['model.provider.invoke']
        or not process.get('model_authority', {}).get('local_user_config_ignored')
        or (request['operation_id'], request['project_id'], request['workspace_id'], request['book_id'], request['external_effect_id'])
        != (source_operation_id, command.project_id, command.workspace_id, command.book_id, effect_id)):
        raise KernelError('PLANNING_SCHEMA_CORRECTION_NOT_AVAILABLE', 'A successor requires a proven equivalent corrected transport; unchanged or untrusted contracts cannot be retried')
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE operation_id=%s
        AND (effect_type<>'model.invoke' OR status NOT IN ('SUCCEEDED','FAILED_FINAL')))
        OR EXISTS(SELECT 1 FROM authority_lease_acquisition lease JOIN authority_attempt attempt USING(attempt_id)
          WHERE attempt.operation_id=%s AND lease.status='HELD')
        OR EXISTS(SELECT 1 FROM authority_book_production WHERE project_id=%s AND book_id=%s
          AND state IN ('ABORTED','CANCELLED','COMPLETED'))""", [source_operation_id, source_operation_id, command.project_id, command.book_id])
    if uow.cursor.fetchone()[0]:
        raise KernelError('PLANNING_SCHEMA_CORRECTION_UNSAFE', 'An active writer, mixed effect or terminal Book cannot acquire a Schema successor')
    uow.cursor.execute('SELECT snapshot_payload FROM authority_attempt_capability_pack_snapshot WHERE operation_id=%s ORDER BY created_at DESC LIMIT 1', [source_operation_id])
    snapshot = uow.cursor.fetchone()
    if not snapshot:
        raise KernelError('PLANNING_SCHEMA_CORRECTION_SNAPSHOT_MISSING', 'Retain the rejected invocation Pack')
    import json
    tools = json.loads(snapshot[0]['tool_policy_payload_json'])
    if (tools.get('default') != 'DENY' or tools.get('database', {}).get('write_allowed')
        or tools.get('files', {}).get('write_allowed')):
        raise KernelError('PLANNING_SCHEMA_CORRECTION_UNSAFE', 'Schema continuation only permits a governed pure generation tool boundary')
    retry_usage = require_generation_retry_budget(uow.cursor, operation_id=source_operation_id)
    uow.cursor.execute('SELECT chain_depth FROM authority_story_planning_runtime_continuation WHERE successor_operation_id=%s', [source_operation_id])
    prior = uow.cursor.fetchone()
    _, world = retained_world_action(uow.database_url, command=command, source_operation_id=source_operation_id)
    return {'mode': 'PROVIDER_SCHEMA_CORRECTION', 'source_operation_id': source_operation_id,
        'command': frozen, 'version': int(row[1]), 'evidence_asset_version_id': asset_id,
        'evidence_hash': asset_hash, 'snapshot': dict(snapshot[0]), 'depth': (int(prior[0]) if prior else 0)+1,
        'provider_schema_correction': {'source_operation_id': source_operation_id, 'external_effect_id': effect_id,
            'model_call_log_asset_version_id': asset_id, 'model_call_log_content_hash': asset_hash,
            'wire_correction': correction, 'world_action': world, 'failure_retry_counter': retry_usage}}


def continuation_action(database_url: str, command: Any):
    if not command.runtime_continuation_id:
        return None
    from .runtime_continuation import require_binding

    proof = require_binding(database_url, command.runtime_continuation_id)['target_runtime'].get('provider_schema_correction')
    if not proof:
        return None
    action, current = retained_world_action(database_url, command=command, source_operation_id=proof['source_operation_id'])
    if current != proof['world_action']:
        raise KernelError('PLANNING_SCHEMA_WORLD_SOURCE_DRIFT', 'Schema correction retains the selected World action exactly')
    return action
