from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError

REPAIR_VERSION = "native-planning-repair-evidence.v2"
LEGACY_REPAIR_VERSION = "native-planning-repair-evidence.v1"
REPAIRABLE_FAILURES = {"SCHEMA_REJECTION", "MALFORMED_STRUCTURED_OUTPUT"}


def native_planning_repair(cursor, *, project_id, book_id, operation_id, task_type, lineage, evidence_version=REPAIR_VERSION):
    if evidence_version not in {REPAIR_VERSION,LEGACY_REPAIR_VERSION}:
        raise KernelError("NATIVE_PLANNING_REPAIR_VERSION_INVALID","Repair evidence requires an exact supported version")
    cursor.execute("""SELECT o.command_payload->'payload',g.input_snapshot_hash,g.input_snapshot
        FROM authority_operation o JOIN authority_story_planning_generation g USING(operation_id)
        WHERE o.operation_id=%s AND o.project_id=%s AND g.book_id=%s
          AND (g.generator_operation_name=%s OR (%s='world_candidates.generate'
            AND o.command_payload #>> '{payload,repair_result_diagnostic,error_code}'='WORLD_PROVIDER_TRANSITION_INVALID'))
          AND o.definition_name='story_planning.generate'""",
        [operation_id,project_id,book_id,task_type,task_type])
    current = cursor.fetchone()
    if not current:
        return None
    command, input_hash, inputs = current
    world_repair = (command.get('repair_result_diagnostic') or {}).get('error_code') == 'WORLD_PROVIDER_TRANSITION_INVALID'
    if world_repair and task_type != 'world_candidates.generate':
        return None
    candidate = command.get("repair_of_candidate_id")
    raw = command.get("repair_result_asset_version_id")
    number = command.get("repair_number",0)
    if not candidate and not raw:
        return None
    if bool(candidate) == bool(raw) or type(number) is not int or not 1 <= number <= 2:
        raise KernelError("NATIVE_PLANNING_REPAIR_INVALID", "Repair requires one bounded native result identity")
    result_id = candidate or raw
    cursor.execute("""SELECT o.operation_id,o.status,g.repair_number,v.content_hash,e.external_effect_id,
            e.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
            g.input_snapshot_hash,g.input_snapshot
        FROM authority_operation_output_asset output JOIN authority_asset_version v USING(asset_version_id)
        JOIN authority_operation o ON o.operation_id=output.operation_id
        JOIN authority_story_planning_generation g ON g.operation_id=o.operation_id
        JOIN authority_external_effect e ON e.operation_id=o.operation_id AND e.status='SUCCEEDED'
          AND e.external_effect_id=COALESCE(v.content #>> '{execution_evidence,external_receipt_ref}',
              v.content->>'external_effect_id',v.content #>> '{contract,evidence,external_receipt_ref}')
        JOIN authority_budget_reservation r ON r.external_effect_id=e.external_effect_id AND r.status='SETTLED'
        WHERE output.asset_version_id=%s AND o.project_id=%s AND g.book_id=%s
          AND g.generator_operation_name=%s AND g.logical_key=%s
          AND e.request_payload->>'stage'=%s
          AND (%s AND g.candidate_asset_version_id=%s AND o.status='SUCCEEDED'
               OR NOT %s AND o.operation_id=%s AND g.candidate_asset_version_id IS NULL AND o.status='FAILED_FINAL')""",
        [result_id,project_id,book_id,command.get('generator_operation_name',task_type),command['logical_key'],task_type,
         bool(candidate),result_id,bool(candidate),command.get('repair_of_operation_id','')])
    parents = cursor.fetchall()
    if len(parents) != 1:
        raise KernelError("NATIVE_PLANNING_REPAIR_SOURCE_INVALID", "Repair must bind its exact settled native parent result and unchanged inputs")
    parent = parents[0]
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    from novel_forge.modules.story_planning_runtime.application import _replay_generation_input_snapshot
    frozen_inputs = _replay_generation_input_snapshot(inputs,parent[7],parent[6])
    if (canonical_hash(inputs) != input_hash
            or evidence_version == LEGACY_REPAIR_VERSION and input_hash != parent[6]):
        raise KernelError("NATIVE_PLANNING_REPAIR_SOURCE_INVALID", "Repair input evidence differs from its native parent")
    if parent[0] not in lineage or lineage[-1] != operation_id or number != parent[2]+1:
        raise KernelError("NATIVE_PLANNING_REPAIR_LINEAGE_INVALID", "Repair counter and lineage differ from the native parent")
    from .execution_template import verify_template_provenance
    policy = verify_template_provenance(cursor,parent[5])
    if not policy or policy['mode'] != 'CREATIVE_VALIDATION' or policy['require_literary_qualification']:
        return None
    selected = parent[5]['selected']['candidate']
    return {'version':evidence_version,'operation_id':operation_id,'parent_operation_id':parent[0],
        'source_result_asset_version_id':result_id,'source_result_hash':parent[3],
        'settled_parent_effect_id':parent[4],'input_snapshot_hash':input_hash,'repair_number':number,
        'parent_candidate_id':selected['candidate_id'],'lineage_operation_ids':list(lineage),
        **({'parent_input_snapshot_hash':parent[6],
            'input_scope_hash':canonical_hash({item['role']:item for item in frozen_inputs})}
            if evidence_version == REPAIR_VERSION else {})}


def repair_route_admission(snapshot, row, template):
    policy = template.get('repair_routing')
    evidence = snapshot['task'].get('declared_requirements',{}).get('native_planning_repair')
    if (not policy or not evidence or evidence.get('version') not in {REPAIR_VERSION,LEGACY_REPAIR_VERSION}
            or evidence.get('operation_id') != snapshot['task']['operation_id']
            or evidence.get('lineage_operation_ids') != snapshot['task'].get('lineage_operation_ids')
            or type(evidence.get('repair_number')) is not int
            or not 1 <= evidence['repair_number'] <= policy['max_same_route_repairs']
            or evidence.get('parent_candidate_id') != row['candidate']['candidate_id']):
        return None
    previous = [h for h in snapshot['task']['history'] if h.get('candidate_id') == row['candidate']['candidate_id']]
    failures = [h.get('failure_class') for h in previous if h.get('failure_class')]
    if (not failures or any(f not in REPAIRABLE_FAILURES for f in failures)
            or any(h.get('failure_class') and h['failure_class'] not in REPAIRABLE_FAILURES
                for h in snapshot['task']['history'])
            or len(previous) > evidence['repair_number']):
        return None
    superseded = [reason for reason in row['rejected_reasons'] if reason in {
        'FAILED_ROUTE_EXCLUDED','SEMANTIC_ARBITRATION_REQUIRED','ROUTE_RETRY_LIMIT_REACHED'}]
    return {'version':'native-repair-routing.v1','status':'BOUNDED_REPAIR_ADMITTED',
        'evidence':evidence,'retained_failed_outcomes':previous,'superseded_route_reasons':superseded,
        'candidate_contract_acceptance':'REQUIRED_AFTER_REPAIR','literary_qualification':'NOT_RUN'}


def verify_native_repair(cursor, decision):
    evidence = decision['task'].get('declared_requirements',{}).get('native_planning_repair')
    if evidence is None:
        return
    task = decision['task']
    current = native_planning_repair(cursor,project_id=task['project_id'],book_id=task['work_id'],
        operation_id=task['operation_id'],task_type=task['task_type'],lineage=tuple(task['lineage_operation_ids']),
        evidence_version=evidence['version'])
    if current != evidence:
        raise KernelError('NATIVE_PLANNING_REPAIR_EVIDENCE_DRIFT','Frozen repair admission must retain its native source and counter')
