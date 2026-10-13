from __future__ import annotations

import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from .craft_discovery import WRITING_METHODS_ROUTING, WRITING_METHODS_EVIDENCE_ROUTING


def source_observation_isolation_binding(cursor: Any, operation: dict, command: Any) -> dict:
    definition = operation["definition_snapshot"]
    if (definition.get("family") != "source_import"
            or definition.get("handler_key") != "novel_forge.source_import.deconstruction_execute"
            or definition.get("external_capabilities") != ["deconstruction.observe"]
            or (definition.get("policy") or {}).get("raw_source_in_generation_context_forbidden") is not True):
        raise KernelError("SOURCE_ISOLATION_SCOPE_INVALID", "Require the native Source Observation owner and model-only capability")
    successor_id = command.evidence.get("source_analysis_successor_import_job_id")
    cursor.execute("""SELECT job.import_job_id,job.workspace_id,owner.actor_id,
        job.intelligence_policy,job.source_locator,successor.intelligence_policy,successor.source_locator
        FROM authority_source_import_work work
        JOIN authority_source_import_job job USING(import_job_id,project_id)
        JOIN authority_operation owner ON owner.operation_id=job.discovery_operation_id
        JOIN authority_source_import_job successor ON successor.import_job_id=%s
          AND successor.project_id=job.project_id AND successor.workspace_id=job.workspace_id
        JOIN authority_operation successor_owner ON successor_owner.operation_id=successor.discovery_operation_id
        WHERE work.operation_id=%s AND work.project_id=%s AND work.work_kind='DECONSTRUCTION'
          AND job.source_type='corpus_content' AND successor.source_type='corpus_content'
          AND successor_owner.actor_id=owner.actor_id""",
        [successor_id, operation["operation_id"], command.project_id])
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise KernelError("SOURCE_ISOLATION_SCOPE_INVALID", "Require original owned Source work and one versioned analysis request")
    job_id, workspace, actor, policy, locator, next_policy, next_locator = rows[0]
    payload = operation["command_payload"].get("payload") or {}
    revision = locator.get("manifest", {}).get("curated_revision_id")
    analyzer = (payload.get("analysis_task") or {}).get("analyzer") or {}
    expected = {"skill_id": "multidisciplinary-knowledge", "skill_version": "1.2.0",
        "prompt_id": "source.writing_theory_methods.craft_principle", "prompt_version": "2.0",
        "schema_version": "source-mechanism-observation.v2", "dimension": "craft_principle",
        "capability_id": "deconstruction.observe"}
    if (actor != command.actor_id or workspace != operation["workspace_id"]
            or job_id != payload.get("import_job_id") or successor_id == job_id
            or not payload.get("source_document_id")
            or any(analyzer.get(key) != value for key, value in expected.items())
            or payload.get("narrative_reading") or payload.get("phase") or payload.get("review_target")
            or not revision or revision != next_locator.get("manifest", {}).get("curated_revision_id")
            or policy.get("routing_policy_version") != WRITING_METHODS_ROUTING
            or next_policy.get("routing_policy_version") != WRITING_METHODS_EVIDENCE_ROUTING):
        raise KernelError("SOURCE_ISOLATION_SCOPE_INVALID", "Preserve the exact Source and owner; require a different frozen analysis policy")
    return {"import_job_id": job_id, "successor_import_job_id": successor_id,
        "source_document_id": payload["source_document_id"],
        "original_actor_id": operation["actor_id"], "operator_actor_id": actor,
        "curated_revision_id": revision, "original_intelligence_policy": policy,
        "successor_intelligence_policy": next_policy}


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def require_source_observation_materialization(
    contract: dict, capability: dict, analyzer: dict, admission: dict,
) -> None:
    isolation = contract.get("source_isolation") or {}
    skill = contract.get("skill") or {}
    schema = contract.get("output_schema") or {}
    prompt = admission.get("prompt_materialization") or {}
    components = prompt.get("component_hashes") or {}
    runtime_admission = capability.get("provider_admission") or {}
    skill_text = skill.get("text")
    schema_content = schema.get("content")
    if (contract.get("schema_version") != "source-capability-materialization.v1"
            or contract.get("stage") != "source.deconstruction.observe"
            or contract.get("capability") != "deconstruction.observe"
            or isolation.get("raw_source_allowed_in_generation_context") is not False
            or isolation.get("raw_source_persisted_in_postgresql") is not False
            or isolation.get("provider_input_resolved_from_object_store") is not True
            or not isinstance(skill_text, str) or not skill_text.strip()
            or not isinstance(schema_content, dict) or not schema_content
            or skill.get("ref") != analyzer.get("skill_id")
            or skill.get("version") != analyzer.get("skill_version")
            or skill.get("content_hash") != analyzer.get("methodology_content_hash")
            or skill.get("content_hash") != "sha256:" + hashlib.sha256(skill_text.encode()).hexdigest()
            or schema.get("content_hash") != _hash(schema_content)
            or contract.get("materialization_hash") != _hash({k: v for k, v in contract.items() if k != "materialization_hash"})
            or contract.get("materialization_hash") != capability.get("materialization_hash")
            or admission.get("schema_version") != "novelos.provider_request_admission.v1"
            or admission.get("source_bytes_transient_only") is not True
            or admission.get("capability_materialization_asset_version_id") != capability.get("materialization_asset_version_id")
            or admission.get("capability_materialization_content_hash") != capability.get("materialization_content_hash")
            or prompt.get("skill") != {k: skill.get(k) for k in ("ref", "version", "content_hash")}
            or prompt.get("output_schema_hash") != schema.get("content_hash")
            or components.get("output_schema") != schema.get("content_hash")
            or components.get("governed_skill") != "sha256:" + hashlib.sha256(skill_text.strip().encode()).hexdigest()
            or not components.get("source_analysis_input") or not components.get("fully_rendered_prompt")
            or prompt.get("fully_rendered_prompt_hash") != components.get("fully_rendered_prompt")
            or runtime_admission.get("input_component_hashes") != components
            or admission.get("provider_admission") != runtime_admission
            or (capability.get("routing_decision") or {}).get("task", {}).get("input_hash") != components.get("fully_rendered_prompt")):
        raise KernelError("SOURCE_ISOLATION_MATERIALIZATION_INVALID", "Require the original governed Source Observation contract")


def require_versioned_source_successor(cursor: Any, project_id: str, operation_id: str) -> None:
    cursor.execute("""SELECT job.import_job_id,job.intelligence_policy,isolation.proof
        FROM authority_source_import_work work
        JOIN authority_source_import_job job USING(import_job_id,project_id)
        JOIN authority_generation_isolation isolation ON isolation.project_id=job.project_id
          AND isolation.workspace_id=job.workspace_id
          AND isolation.proof->>'contract_version'='source-generation-isolation.v1'
          AND isolation.proof#>>'{source_recovery,curated_revision_id}'=job.source_locator#>>'{manifest,curated_revision_id}'
        WHERE work.operation_id=%s AND work.project_id=%s""", [operation_id, project_id])
    for job_id, policy, proof in cursor.fetchall():
        binding = proof["source_recovery"]
        route = policy.get("routing_policy_version")
        recovery_routes = {binding["original_intelligence_policy"].get("routing_policy_version"),
            binding["successor_intelligence_policy"].get("routing_policy_version")}
        if (job_id == binding["import_job_id"]
                or (job_id == binding["successor_import_job_id"] and policy != binding["successor_intelligence_policy"])
                or (route in recovery_routes and job_id != binding["successor_import_job_id"])):
            raise KernelError("SOURCE_ISOLATED_CONTRACT_REDISPATCH_FORBIDDEN",
                "The stopped Source contract cannot be renamed or resubmitted; use the bound versioned analysis")
