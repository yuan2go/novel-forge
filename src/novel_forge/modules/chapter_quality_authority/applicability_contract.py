from __future__ import annotations

from copy import deepcopy

from novel_forge.modules.command_kernel.errors import KernelError
from .domain import QUALITY_GROUPS

CONTRACT = "quality-host-applicability.v1"


def allowed_quality_statuses(schema, baseline, group):
    requirements=baseline.get('method_requirements',{})
    general=list(schema['properties']['dimensions']['items']['properties']['gate_status']['enum'])
    return {dimension: ['NOT_APPLICABLE'] if requirements.get(dimension,{}).get('status') in {'NOT_APPLICABLE','PROHIBITED'}
        else ['INSUFFICIENT_EVIDENCE'] if requirements.get(dimension,{}).get('status')=='UNDETERMINED'
        else [value for value in general if value!='NOT_APPLICABLE'] for dimension in QUALITY_GROUPS[group]}


def bind_quality_applicability_schema(schema, baseline, group):
    result=deepcopy(schema)
    statuses=allowed_quality_statuses(schema,baseline,group)
    branches=[]
    for dimension,allowed in statuses.items():
        item=deepcopy(schema['properties']['dimensions']['items'])
        item['properties']['dimension']={'type':'string','enum':[dimension]}
        item['properties']['gate_status']={'type':'string','enum':allowed}
        branches.append(item)
    result['properties']['dimensions']['items']={'anyOf':branches}
    result['properties']['dimensions']['minItems']=len(branches)
    result['properties']['dimensions']['maxItems']=len(branches)
    return result


def quality_applicability_repair_evidence(cursor,operation_id,attempt_id):
    cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content,e.request_payload->'input' FROM authority_operation_output_asset oa
        JOIN authority_asset x USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
        JOIN authority_external_effect e ON e.external_effect_id=v.content->>'external_effect_id'
        WHERE oa.operation_id=%s AND x.asset_type='model_call_log' AND v.content->>'attempt_id'=%s""",[operation_id,attempt_id])
    rows=cursor.fetchall()
    if len(rows)!=1:
        raise KernelError('QUALITY_APPLICABILITY_REPAIR_EVIDENCE_REQUIRED','Retain one exact settled Quality review')
    asset_id,asset_hash,log,payload=rows[0]
    output=log.get('provider_evidence',{}).get('production_execution',{}).get('process_evidence',{}).get('result',{})
    group=str(log.get('stage') or '').removeprefix('quality_')
    baseline=payload.get('quality_context',{}).get('creative_baseline',{})
    cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content->'creative_baseline' FROM authority_operation o,
        jsonb_array_elements(o.input_asset_snapshot) binding JOIN authority_asset_version v ON v.asset_version_id=binding->>'asset_version_id'
        AND v.content_hash=binding->>'content_hash' JOIN authority_asset x USING(asset_id)
        WHERE o.operation_id=%s AND x.asset_type='best_draft_candidate'""",[operation_id])
    inputs=cursor.fetchall()
    if len(inputs)!=1 or inputs[0][2]!=baseline or not baseline or group not in QUALITY_GROUPS:
        raise KernelError('QUALITY_APPLICABILITY_REPAIR_INPUT_REQUIRED','Review requires its exact frozen candidate baseline')
    dimensions=output.get('dimensions',[])
    if (len(dimensions)!=len(QUALITY_GROUPS[group]) or {d.get('dimension') for d in dimensions}!=set(QUALITY_GROUPS[group])):
        raise KernelError('QUALITY_APPLICABILITY_REPAIR_COVERAGE_REQUIRED','Retain complete Quality dimension coverage')
    requirements=baseline.get('method_requirements',{})
    invalid=[d['dimension'] for d in dimensions if d.get('gate_status')=='NOT_APPLICABLE'
        and requirements.get(d['dimension'],{}).get('status','APPLICABLE') not in {'NOT_APPLICABLE','PROHIBITED'}]
    if not invalid:
        raise KernelError('QUALITY_APPLICABILITY_REPAIR_DIAGNOSTIC_REQUIRED','Only a recorded forbidden non-applicability may adopt this contract')
    return {'contract_version':CONTRACT,'source_review_asset':{'asset_version_id':asset_id,'content_hash':asset_hash},
        'candidate_asset':{'asset_version_id':inputs[0][0],'content_hash':inputs[0][1]},
        'baseline_digest':baseline['baseline_digest'],'invalid_non_applicability':invalid,'assessment_reused':False}
