from __future__ import annotations

from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.execution_template import MODE, verify_template_provenance


def validation_state(state: Mapping[str, Any]) -> bool:
    return state.get("execution_evidence", {}).get("creative_validation", {}).get("mode") == MODE


def candidate_validation(cursor: Any, *, project_id: str, asset_version_id: str) -> dict[str, Any] | None:
    cursor.execute("""SELECT v.content_hash,e.request_payload #> '{_production_execution,capability_runtime,routing_decision}',
        e.external_effect_id,e.operation_id,v.content
        FROM authority_operation_output_asset output
        JOIN authority_asset_version v ON v.asset_version_id=output.asset_version_id
        JOIN authority_asset a ON a.asset_id=v.asset_id
        JOIN authority_external_effect e ON e.operation_id=COALESCE(v.content#>>'{execution_evidence,planning_host_revalidation,source_operation_id}',output.operation_id) AND e.project_id=a.project_id
        WHERE a.project_id=%s AND v.asset_version_id=%s AND e.status='SUCCEEDED'
          AND e.request_payload->>'stage'=v.content->>'generator_operation_name'
          AND e.request_payload #>> '{_production_execution,capability_runtime,routing_decision,mode}'='CREATIVE_VALIDATION'""",
        [project_id, asset_version_id])
    rows = cursor.fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise KernelError("CREATIVE_DESIGN_GENERATOR_AMBIGUOUS", asset_version_id)
    digest, decision, effect, operation, content = rows[0]
    template = verify_template_provenance(cursor, decision)
    if (not template or template["mode"] != MODE or template["require_literary_qualification"]
            or content.get("routing_eligibility") == "BENCHMARK_ONLY"
            or decision.get("status") != "SELECTED"
            or decision["task"]["operation_id"] != operation
            or content.get("book_id") != template["book_id"]):
        raise KernelError("CREATIVE_DESIGN_ADMISSION_INVALID", asset_version_id)
    host=content.get('execution_evidence',{}).get('planning_host_revalidation')
    if host:
        from novel_forge.modules.story_planning_runtime.runtime_continuation import require_source
        from novel_forge.storage.authority_uow import AuthorityUnitOfWork
        from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
        from novel_forge.modules.story_planning_runtime.execution import bind_provider_realization_selectors
        from psycopg.conninfo import make_conninfo
        database_url=make_conninfo(cursor.connection.info.dsn,password=cursor.connection.info.password)
        with AuthorityUnitOfWork(database_url) as uow:
            source=require_source(uow,source_operation_id=operation,project_id=project_id)
        child=content['execution_evidence']['operation_id']
        cursor.execute("SELECT target_runtime->'planning_host_revalidation' FROM authority_story_planning_runtime_continuation WHERE source_operation_id=%s AND successor_operation_id=%s AND chain_depth=4",[operation,child]);binding=cursor.fetchone()
        if source.get('planning_host_revalidation')!=host or not binding or binding[0]!=host:
            raise KernelError('CREATIVE_DESIGN_ADMISSION_INVALID','Exact host-only successor proof required')
        query=AuthorityAssetQuery(database_url);context=query.require(project_id=project_id,asset_version_id=content['execution_evidence']['context_bundle_asset_version_id'])
        original=query.require(project_id=project_id,asset_version_id=host['candidate_asset_version_id'])
        from copy import deepcopy
        expected=deepcopy(original.content['candidate_payload'])
        for manifest in ('world_realization','character_realization'):
            for entity in expected[manifest]:
                for field in ('invariant_refs','structure_refs','state_ref','identity_ref','trajectory_ref'):
                    rows=entity.get(field,[]);rows=rows if isinstance(rows,list) else [rows]
                    for ref in rows:ref['frozen_by_operation_id']=child
        expected.pop('constraint_envelope',None)
        if expected!={key:value for key,value in content['candidate_payload'].items() if key!='constraint_envelope'}:
            raise KernelError('CREATIVE_DESIGN_ADMISSION_INVALID','Host-only correction cannot alter generated content')
        operation=child
    return {"version": "creative-design-admission.v1", "mode": MODE,
            "project_id": project_id, "book_id": template["book_id"],
            "asset_version_id": asset_version_id, "content_hash": digest,
            "generation_operation_id": operation, "external_effect_id": effect,
            "routing_decision_id": decision["decision_id"],
            "policy_snapshot": decision["task"]["policy_snapshot"],
            "literary_qualification": "NOT_RUN", "checks": {"literary_qualification": {"status": "NOT_RUN", "reason": "creative validation template"}}}


def approved_validation_design(cursor: Any, *, project_id: str, book_id: str, asset_version_id: str) -> dict[str, Any] | None:
    receipt = candidate_validation(cursor, project_id=project_id, asset_version_id=asset_version_id)
    if receipt is None:
        return None
    cursor.execute("""SELECT state.lifecycle,state.qualification,state.approval,state.freshness,
        state.execution_evidence,d.asset_version_id,d.content_hash,d.content,op.status
        FROM authority_story_design_version_state state
        JOIN authority_story_design_transition transition ON transition.project_id=state.project_id
          AND transition.asset_version_id=state.asset_version_id AND transition.transition_type='APPROVE'
        JOIN authority_operation op ON op.operation_id=transition.transition_operation_id
        JOIN authority_operation_output_asset output ON output.operation_id=op.operation_id
        JOIN authority_asset_version d ON d.asset_version_id=output.asset_version_id
        WHERE state.project_id=%s AND state.asset_version_id=%s ORDER BY transition.to_version DESC LIMIT 1""",
        [project_id, asset_version_id])
    row = cursor.fetchone()
    if (not row or receipt["book_id"] != book_id or row[1:4] != ("STRUCTURALLY_VALID", "APPROVED", "CURRENT")
            or row[4].get("creative_validation") != receipt or row[7].get("evidence", {}).get("creative_validation") != receipt
            or row[8] != "SUCCEEDED"):
        raise KernelError("CREATIVE_DESIGN_APPROVAL_REQUIRED", asset_version_id)
    return {**receipt, "lifecycle": row[0], "decision_asset_version_id": row[5], "decision_content_hash": row[6]}


def project_approved_validation_eligibility(cursor: Any, *, project_id: str, book_id: str, asset_version_id: str) -> None:
    from psycopg.types.json import Jsonb
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash

    receipt = approved_validation_design(cursor, project_id=project_id, book_id=book_id, asset_version_id=asset_version_id)
    if receipt is None:
        raise KernelError("PLANNING_VALIDATION_ELIGIBILITY_INVALID", "Eligibility projection requires the original native validation approval")
    validation = {key: value for key, value in receipt.items() if key not in {"lifecycle", "decision_asset_version_id", "decision_content_hash"}}
    cursor.execute("""UPDATE authority_asset_version version SET eligibility='ELIGIBLE'
        FROM authority_asset asset WHERE version.asset_version_id=%s AND version.content_hash=%s
        AND version.asset_id=asset.asset_id AND asset.project_id=%s
        AND ((version.lifecycle='CANDIDATE' AND version.eligibility IN ('INELIGIBLE','ELIGIBLE'))
          OR (version.lifecycle='ACTIVE' AND version.eligibility='ELIGIBLE' AND %s='ACTIVE'))
        AND version.governance='CLEAR'""", [asset_version_id,validation['content_hash'],project_id,receipt['lifecycle']])
    if cursor.rowcount != 1:
        raise KernelError("PLANNING_CANDIDATE_ELIGIBILITY_CONFLICT", "Approved validation candidate cannot override a revoked or changed asset")
    identity = canonical_hash({"asset_version_id":asset_version_id,"validation":validation,"decision":"ELIGIBLE"})
    cursor.execute("""INSERT INTO authority_asset_qualification(qualification_id,asset_version_id,policy_version,decision,evidence)
        VALUES (%s,%s,'creative-validation-eligibility.v1','ELIGIBLE',%s) ON CONFLICT (qualification_id) DO NOTHING""",
        [identity,asset_version_id,Jsonb(validation)])
