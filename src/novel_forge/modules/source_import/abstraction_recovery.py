from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import corpus_hash
from novel_forge.modules.source_authority.curation import require_curated_operation_current
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.source_authority_repositories import SourceAuthorityRepository
from novel_forge.storage.source_import_repositories import SourceImportRepository
from .craft_discovery import (
    CRAFT_DISCOVERY_POLICY, CRAFT_OUTPUT_CONTRACT, LEGACY_CRAFT_OUTPUT_CONTRACT,
    craft_discovery_schema, validate_discovery_schema,
)


def freeze_craft_output(cursor: Any, project_id: str, observation_id: str,
    version: str = CRAFT_OUTPUT_CONTRACT) -> dict:
    cursor.execute("""SELECT v.content,v.content_hash FROM authority_asset_version v
        JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s
          AND a.asset_type='source_deconstruction_observation' AND v.lifecycle='ACTIVE' AND v.governance='CLEAR'""",
        [observation_id, project_id])
    row = cursor.fetchone()
    if not row:
        raise KernelError("SOURCE_IMPORT_OBSERVATION_MISSING", "Freeze the exact active governed Observation")
    grounded = any("certainty" in finding for finding in row[0]["observation"]["findings"])
    return {"version": version, "observation_asset_version_id": observation_id,
        "observation_content_hash": row[1], "output_schema_hash": corpus_hash(
            craft_discovery_schema(grounded=grounded, observation_id=observation_id, contract_version=version))}


def recover_abstraction_schema(app: Any, *, project_id: str, operation_id: str,
    expected_version: int, authorization_ref: str, reason: str, principal: Any) -> dict:
    principal.require("source.authority.execute", project_id)
    if not authorization_ref.strip() or not reason.strip() or len(reason) > 4000:
        raise ValueError("Schema recovery requires actual authorization and a bounded correction reason")
    with AuthorityUnitOfWork(app.database_url, coordinate_nested=True) as uow:
        uow.cursor.execute("""SELECT to_jsonb(o),to_jsonb(work),owner.actor_id
            FROM authority_operation o JOIN authority_source_import_work work USING(operation_id,project_id)
            JOIN authority_source_import_job job USING(import_job_id,project_id)
            JOIN authority_operation owner ON owner.operation_id=job.discovery_operation_id
            WHERE o.operation_id=%s AND o.project_id=%s FOR UPDATE OF o,work""", [operation_id, project_id])
        row = uow.cursor.fetchone()
        if not row:
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_SCOPE_INVALID", "Recover the original owned Source abstraction")
        original, work, owner = row
        payload = original["command_payload"].get("payload") or {}
        definition = original["definition_snapshot"]
        if (owner != principal.principal_id or original["definition_name"] != "source.import.mkaos.extract"
                or definition.get("family") != "source_import" or definition.get("handler_key") != "novel_forge.source_import.mkaos_extract"
                or payload.get("narrative_reading") or payload.get("source_sampling")
                or work["work_kind"] != "MKAOS_EXTRACTION" or original["status"] != "FAILED_FINAL"
                or original["version"] != expected_version
                or work["failure"].get("code") != "SOURCE_PROVIDER_SCHEMA_REJECTED"
                or payload.get("abstraction_policy_version") != CRAFT_DISCOVERY_POLICY):
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_SCOPE_INVALID", "Require the owned known Schema rejection and unchanged source version")
        repository = SourceImportRepository(uow.cursor)
        job = repository.job_for_update(project_id=project_id, import_job_id=work["import_job_id"])
        if job["status"] in {"PAUSED", "CANCELLED", "FAILED_FINAL"}:
            raise KernelError("SOURCE_ABSTRACTION_JOB_BLOCKED", "The original Source job does not permit recovery")
        require_curated_operation_current(SourceAuthorityRepository(uow.cursor), project_id, operation_id)
        from .corpus_ingestion.curated_analysis import require_known_cli_outcomes

        require_known_cli_outcomes(uow.cursor, project_id, operation_id=operation_id)
        observation_id = payload["observation_asset_version_id"]
        uow.cursor.execute("""SELECT o.command_payload->'payload' FROM authority_source_import_work w
            JOIN authority_operation o USING(operation_id,project_id)
            WHERE w.project_id=%s AND w.import_job_id=%s AND w.work_kind='DECONSTRUCTION'
              AND w.status='SUCCEEDED' AND w.result->>'observation_asset_version_id'=%s""",
            [project_id, job["import_job_id"], observation_id])
        origins = uow.cursor.fetchall()
        origin = origins[0][0] if len(origins) == 1 else {}
        analyzer = (origin.get("analysis_task") or {}).get("analyzer") or {}
        if (any(origin.get(key) for key in ("narrative_reading", "phase", "review_target", "source_sampling"))
                or analyzer.get("analyzer_id") != "novel-forge.writing_theory_methods.craft_principle"
                or analyzer.get("skill_id") != "multidisciplinary-knowledge"
                or analyzer.get("dimension") != "craft_principle"
                or analyzer.get("capability_id") != "deconstruction.observe"
                or analyzer.get("schema_version") != "source-mechanism-observation.v2"):
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_SCOPE_INVALID", "Require the original ordinary writing-method Observation")
        uow.cursor.execute("""SELECT e.external_effect_id,e.status,v.content,v.content_hash,dispatch.evidence,
            e.request_payload,e.request_hash,dispatch.payload_hash,dispatch.status,e.last_error
            FROM authority_external_effect e
            JOIN authority_asset_version v ON v.asset_version_id=e.request_payload#>>'{_production_execution,capability_runtime,materialization_asset_version_id}'
            JOIN authority_asset materialization_owner ON materialization_owner.asset_id=v.asset_id AND materialization_owner.project_id=e.project_id
            JOIN LATERAL(SELECT evidence,payload_hash,status FROM authority_external_effect_dispatch WHERE external_effect_id=e.external_effect_id ORDER BY generation DESC LIMIT 1) dispatch ON TRUE
            WHERE e.operation_id=%s AND e.project_id=%s AND e.effect_type='model.invoke' AND e.capability='mkaos.knowledge.extract'""", [operation_id, project_id])
        effects = uow.cursor.fetchall()
        if len(effects) != 1 or effects[0][1] != "FAILED_FINAL":
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_OUTCOME_UNRESOLVED", "Require the original known terminal Provider rejection")
        effect_id, _, materialization, materialization_hash, dispatch, request, request_hash, dispatch_hash, dispatch_status, last_error = effects[0]
        capability = request.get("_production_execution", {}).get("capability_runtime") or {}
        contract = materialization["contract"]
        output = contract.get("output_schema") or {}
        skill = contract.get("skill") or {}
        if (not request_hash or request_hash != dispatch_hash or corpus_hash(request) != request_hash
                or dispatch_status != "FAILED_FINAL" or last_error != dispatch
                or contract.get("schema_version") != "source-capability-materialization.v1"
                or not contract.get("materialization_hash")
                or contract["materialization_hash"] != corpus_hash({k: v for k, v in contract.items() if k != "materialization_hash"})
                or materialization_hash != capability.get("materialization_content_hash")
                or contract.get("materialization_hash") != capability.get("materialization_hash")
                or contract.get("stage") != "source.mkaos.extract" or contract.get("capability") != payload.get("capability")
                or not output.get("content_hash") or output["content_hash"] != corpus_hash(output.get("content"))
                or not skill.get("content_hash") or skill["content_hash"] != payload.get("mkaos_methodology_content_hash")
                or skill.get("ref") != payload.get("mkaos_skill_id") or skill.get("version") != payload.get("mkaos_skill_version")):
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_CONTRACT_INVALID", "Retain the original identity-bound Source materialization")
        result = dispatch.get("production_execution", {}).get("execution_result") or {}
        error = result.get("error") or {}
        if (result.get("operation_id") != operation_id or result.get("outcome") != "FINAL_FAILURE"
                or error.get("cause_code") != "PROVIDER_SCHEMA_REJECTED"
                or error.get("stage") != "OUTPUT_CONTRACT_ADMISSION"):
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_OUTCOME_UNRESOLVED", "Retain the original typed Provider Schema rejection")
        old_schema = output["content"]
        if not validate_discovery_schema(old_schema):
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_SCOPE_INVALID", "Retain a governed Craft output contract")
        old = freeze_craft_output(uow.cursor, project_id, observation_id, LEGACY_CRAFT_OUTPUT_CONTRACT)
        corrected = freeze_craft_output(uow.cursor, project_id, observation_id)
        if corpus_hash(old_schema) != old["output_schema_hash"] or old["output_schema_hash"] == corrected["output_schema_hash"]:
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_CONTRACT_UNCHANGED", "Require the exact rejected legacy Schema and a changed output contract")
        uow.cursor.execute("""SELECT 1 WHERE EXISTS(SELECT 1 FROM authority_operation_output_asset WHERE operation_id=%s AND role='primary')
            OR EXISTS(SELECT 1 FROM authority_lease_acquisition l JOIN authority_attempt a USING(attempt_id)
              WHERE a.operation_id=%s AND l.status='HELD')
            OR EXISTS(SELECT 1 FROM authority_effect_dispatch_lease l JOIN authority_external_effect_dispatch d USING(dispatch_id)
              WHERE d.external_effect_id=%s AND l.status='HELD')""", [operation_id, operation_id, effect_id])
        if uow.cursor.fetchone():
            raise KernelError("SOURCE_ABSTRACTION_RECOVERY_NOT_STOPPED", "Reuse available output or release original execution ownership")
        recovery = {"contract_version": "source-abstraction-schema-recovery.v1", "original_operation_id": operation_id,
            "original_operation_version": expected_version, "original_external_effect_id": effect_id,
            "original_materialization_hash": materialization_hash, "original_output_schema_hash": old["output_schema_hash"],
            "corrected_output_contract": corrected, "authorization_ref": authorization_ref,
            "operator_actor_id": principal.principal_id, "reason": reason, "original_failure_preserved": True}
        child = app._admit_mkaos_from_scope(project_id=project_id, parent_operation_id=operation_id,
            trace_id="trace:source-abstraction-schema:" + operation_id, correlation_id=job["import_job_id"], job=job,
            observation={"observation_asset_version_id": observation_id},
            payload={**payload, "mkaos_capability": payload["capability"]}, schema_recovery=recovery)
        uow.commit()
    return {"operation_id": child, "original_operation_id": operation_id, "import_job_id": job["import_job_id"],
        "observation_asset_version_id": observation_id, "output_contract": corrected,
        "original_failure_preserved": True, "new_observation_required": False, "knowledge_approved": False}
