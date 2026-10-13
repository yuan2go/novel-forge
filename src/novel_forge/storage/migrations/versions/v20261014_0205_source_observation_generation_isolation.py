from __future__ import annotations

from .v20261012_0201_working_revision_generation_isolation import UPGRADE_STATEMENTS as PREVIOUS
from .v20261009_0185_pure_generation_isolation import UPGRADE_STATEMENTS as ORIGINAL

MIGRATION_ID = "20261014_0205_source_observation_generation_isolation"
DOWN_REVISION = "20261013_0204_retrieval_generation_progress"
FORWARD_ONLY = True
BACKUP_REQUIRED = True
FORWARD_FIX = "Fence an owned stopped Source model Observation while retaining unknown outcome and usage; permit only a different frozen analysis policy over the same governed revision."

_SOURCE = """o.definition_name='source.import.deconstruction.execute'
 AND o.definition_snapshot->>'family'='source_import'
 AND o.definition_snapshot->>'handler_key'='novel_forge.source_import.deconstruction_execute'
 AND o.definition_snapshot->'external_capabilities'='["deconstruction.observe"]'::jsonb
 AND o.definition_snapshot#>'{policy,raw_source_in_generation_context_forbidden}'='true'::jsonb
 AND NEW.book_id='source-corpus:'||NEW.project_id
 AND NEW.proof->>'contract_version'='source-generation-isolation.v1'
 AND NEW.proof->>'execution_transport'='LOCAL_CLI_REMOTE_INFERENCE'
 AND EXISTS(SELECT 1 FROM authority_external_effect_dispatch dispatch
   WHERE dispatch.external_effect_id=e.external_effect_id AND dispatch.payload_hash=e.request_hash
   AND dispatch.evidence#>>'{production_execution,execution_handle,transport}'='LOCAL_CLI_REMOTE_INFERENCE')
 AND NEW.proof->>'continuation_id'='source-analysis-version:'||o.operation_id
 AND v.content#>>'{contract,schema_version}'='source-capability-materialization.v1'
 AND v.content#>>'{contract,stage}'='source.deconstruction.observe'
 AND v.content#>>'{contract,capability}'='deconstruction.observe'
 AND v.content#>>'{contract,skill,ref}'='multidisciplinary-knowledge'
 AND v.content#>>'{contract,skill,version}'='1.2.0'
 AND v.content#>>'{contract,skill,content_hash}'=o.command_payload#>>'{payload,analysis_task,analyzer,methodology_content_hash}'
 AND length(v.content#>>'{contract,skill,text}')>0
 AND length(v.content#>>'{contract,output_schema,content_hash}')>0
 AND v.content#>>'{contract,materialization_hash}'=e.request_payload#>>'{_production_execution,capability_runtime,materialization_hash}'
 AND EXISTS(SELECT 1 FROM authority_asset_version admission JOIN authority_asset admission_owner USING(asset_id)
   WHERE admission_owner.project_id=NEW.project_id
   AND admission.asset_version_id=e.request_payload#>>'{_production_execution,capability_runtime,provider_admission_asset_version_id}'
   AND admission.content_hash=e.request_payload#>>'{_production_execution,capability_runtime,provider_admission_content_hash}'
   AND admission.content#>>'{contract,schema_version}'='novelos.provider_request_admission.v1'
   AND admission.content#>>'{contract,capability_materialization_asset_version_id}'=v.asset_version_id
   AND admission.content#>>'{contract,capability_materialization_content_hash}'=v.content_hash
   AND admission.content#>'{contract,prompt_materialization,skill}'=(v.content#>'{contract,skill}')-'text'
   AND admission.content#>>'{contract,prompt_materialization,output_schema_hash}'=v.content#>>'{contract,output_schema,content_hash}'
   AND length(admission.content#>>'{contract,prompt_materialization,component_hashes,source_analysis_input}')>0
   AND length(admission.content#>>'{contract,prompt_materialization,fully_rendered_prompt_hash}')>0
   AND admission.content#>'{contract,provider_admission}'=e.request_payload#>'{_production_execution,capability_runtime,provider_admission}')
 AND v.content#>'{contract,source_isolation,raw_source_allowed_in_generation_context}'='false'::jsonb
 AND v.content#>'{contract,source_isolation,raw_source_persisted_in_postgresql}'='false'::jsonb
 AND v.content#>'{contract,source_isolation,provider_input_resolved_from_object_store}'='true'::jsonb
 AND e.capability='deconstruction.observe'
 AND EXISTS(SELECT 1 FROM authority_source_import_work work
 JOIN authority_source_import_job job USING(import_job_id,project_id)
 JOIN authority_operation owner ON owner.operation_id=job.discovery_operation_id
 JOIN authority_source_import_job successor ON successor.import_job_id=NEW.proof#>>'{source_recovery,successor_import_job_id}'
 JOIN authority_operation successor_owner ON successor_owner.operation_id=successor.discovery_operation_id
 WHERE work.operation_id=o.operation_id AND work.project_id=NEW.project_id AND work.work_kind='DECONSTRUCTION'
 AND job.source_type='corpus_content' AND successor.source_type='corpus_content'
 AND job.project_id=successor.project_id AND job.workspace_id=successor.workspace_id AND job.workspace_id=NEW.workspace_id
 AND owner.actor_id=NEW.proof->>'actor_id' AND successor_owner.actor_id=owner.actor_id
 AND work.import_job_id=o.command_payload#>>'{payload,import_job_id}'
 AND work.import_job_id=NEW.proof#>>'{source_recovery,import_job_id}'
 AND o.command_payload#>>'{payload,source_document_id}'=NEW.proof#>>'{source_recovery,source_document_id}'
 AND o.actor_id=NEW.proof#>>'{source_recovery,original_actor_id}'
 AND owner.actor_id=NEW.proof#>>'{source_recovery,operator_actor_id}'
 AND job.import_job_id<>successor.import_job_id
 AND job.intelligence_policy->>'routing_policy_version'='source-analysis-routing.writing-methods.v1'
 AND successor.intelligence_policy->>'routing_policy_version'='source-analysis-routing.writing-methods.v2'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,skill_id}'='multidisciplinary-knowledge'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,skill_version}'='1.2.0'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,prompt_id}'='source.writing_theory_methods.craft_principle'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,prompt_version}'='2.0'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,schema_version}'='source-mechanism-observation.v2'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,dimension}'='craft_principle'
 AND o.command_payload#>>'{payload,analysis_task,analyzer,capability_id}'='deconstruction.observe'
 AND COALESCE(o.command_payload#>'{payload,narrative_reading}','null'::jsonb)='null'::jsonb
 AND COALESCE(o.command_payload#>>'{payload,phase}','')=''
 AND COALESCE(o.command_payload#>'{payload,review_target}','null'::jsonb)='null'::jsonb
 AND job.source_locator#>>'{manifest,curated_revision_id}' IS NOT NULL
 AND job.source_locator#>>'{manifest,curated_revision_id}'=successor.source_locator#>>'{manifest,curated_revision_id}'
 AND o.command_payload#>'{payload,analysis_task,analyzer}' IS NOT NULL)"""

_BASE = PREVIOUS[0]
_ACTOR = "AND o.workspace_id=NEW.workspace_id AND o.actor_id=NEW.proof->>'actor_id'"
_BRANCH = "AND ((o.definition_name='story_planning.generate'"
_CONTRACT = "AND NEW.proof->>'contract_version'='pure-generation-isolation.v1'"
assert all(_BASE.count(token) == 1 for token in (_ACTOR, _BRANCH, _CONTRACT))
UPGRADE_STATEMENTS = [_BASE.replace(_ACTOR,
    "AND o.workspace_id=NEW.workspace_id AND (o.actor_id=NEW.proof->>'actor_id' OR (" + _SOURCE + "))")
    .replace(_BRANCH, "AND ((" + _SOURCE + ") OR (o.definition_name='story_planning.generate'")
    .replace(_CONTRACT, "AND (NEW.proof->>'contract_version'='pure-generation-isolation.v1' OR (" + _SOURCE + "))")]
UPGRADE_STATEMENTS.append(ORIGINAL[1].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    .replace("i.proof->>'contract_version'='pure-generation-isolation.v1'",
        "i.proof->>'contract_version' IN ('pure-generation-isolation.v1','source-generation-isolation.v1')"))
DOWNGRADE_STATEMENTS: list[str] = []
