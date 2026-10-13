from types import SimpleNamespace

from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import corpus_hash
from novel_forge.modules.source_import.abstraction_recovery import recover_abstraction_schema
from novel_forge.modules.source_import.craft_discovery import (
    CRAFT_DISCOVERY_POLICY, CRAFT_OUTPUT_CONTRACT, LEGACY_CRAFT_OUTPUT_CONTRACT, craft_discovery_schema,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


@pytest.mark.parametrize('fault', [None, 'actor', 'version', 'status', 'failure', 'unknown', 'receipt', 'unchanged', 'lease',
    'reading', 'materialization_hash', 'dispatch_hash', 'dispatch_status', 'last_error', 'skill_hash'])
def test_abstraction_schema_recovery_keeps_failure_and_requires_changed_owned_known_contract(monkeypatch, fault):
    from novel_forge.modules.source_import import abstraction_recovery
    from novel_forge.modules.source_import.corpus_ingestion import curated_analysis
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    ensure_migrated()
    monkeypatch.setattr(abstraction_recovery, 'require_curated_operation_current', lambda *args: None)
    monkeypatch.setattr(curated_analysis, 'require_known_cli_outcomes', lambda *args, **kwargs: None)
    with AuthorityUnitOfWork(DATABASE_URL, coordinate_nested=True) as uow:
        cursor = uow.cursor
        for table in ('authority_operation', 'authority_source_import_work', 'authority_source_import_job',
                'authority_asset', 'authority_asset_version', 'authority_external_effect', 'authority_external_effect_dispatch',
                'authority_operation_output_asset', 'authority_attempt', 'authority_lease_acquisition', 'authority_effect_dispatch_lease'):
            cursor.execute(sql.SQL('CREATE TEMP TABLE {} AS SELECT * FROM public.{} WITH NO DATA').format(sql.Identifier(table), sql.Identifier(table)))
        definition = {'family': 'source_import', 'handler_key': 'novel_forge.source_import.mkaos_extract'}
        payload = {'payload': {'import_job_id': 'job', 'observation_asset_version_id': 'observation:1', 'capability': 'mkaos.knowledge.extract',
            'abstraction_policy_version': CRAFT_DISCOVERY_POLICY, 'mkaos_skill_id': 'anti-copy-abstraction',
            'mkaos_skill_version': '1.0.0', 'mkaos_methodology_content_hash': 'sha256:skill'}}
        cursor.execute("INSERT INTO authority_operation(operation_id,project_id,actor_id,definition_name,status,version,command_payload,definition_snapshot) VALUES('owner','project','operator','source.import.corpus.analysis','SUCCEEDED',1,'{}','{}'),('failed','project','source-worker','source.import.mkaos.extract',%s,3,%s,%s)", ['SUCCEEDED' if fault == 'status' else 'FAILED_FINAL', Jsonb(payload), Jsonb(definition)])
        cursor.execute("INSERT INTO authority_source_import_job(import_job_id,project_id,workspace_id,discovery_operation_id,status) VALUES('job','project','workspace','owner','PARTIALLY_COMPLETED')")
        cursor.execute("INSERT INTO authority_source_import_work(work_id,operation_id,project_id,import_job_id,work_kind,status,failure) VALUES('work','failed','project','job','MKAOS_EXTRACTION','FAILED_FINAL',%s)", [Jsonb({'code': 'OTHER' if fault == 'failure' else 'SOURCE_PROVIDER_SCHEMA_REJECTED'})])
        origin = {'analysis_task': {'analyzer': {'analyzer_id': 'novel-forge.writing_theory_methods.craft_principle',
            'skill_id': 'multidisciplinary-knowledge', 'dimension': 'craft_principle',
            'capability_id': 'deconstruction.observe', 'schema_version': 'source-mechanism-observation.v2'}}}
        if fault == 'reading':
            origin['narrative_reading'] = {'bounded': True}
        cursor.execute("INSERT INTO authority_operation(operation_id,project_id,command_payload) VALUES('origin','project',%s)", [Jsonb({'payload': origin})])
        cursor.execute("INSERT INTO authority_source_import_work(work_id,operation_id,project_id,import_job_id,work_kind,status,result) VALUES('observation-work','origin','project','job','DECONSTRUCTION','SUCCEEDED',%s)", [Jsonb({'observation_asset_version_id': 'observation:1'})])
        cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES('observation','project','source_deconstruction_observation'),('materialization','project','capability_materialization')")
        observation = {'observation': {'findings': [{'certainty': 'HYPOTHESIS', 'statement': 'conditional procedure'}]}}
        schema = craft_discovery_schema(grounded=True, observation_id='observation:1', contract_version=CRAFT_OUTPUT_CONTRACT if fault == 'unchanged' else LEGACY_CRAFT_OUTPUT_CONTRACT)
        contract = {'schema_version': 'source-capability-materialization.v1', 'stage': 'source.mkaos.extract',
            'capability': 'mkaos.knowledge.extract', 'output_schema': {'content': schema, 'content_hash': corpus_hash(schema)},
            'skill': {'ref': 'anti-copy-abstraction', 'version': '1.0.0', 'content_hash': 'sha256:other' if fault == 'skill_hash' else 'sha256:skill'}}
        contract['materialization_hash'] = None if fault == 'materialization_hash' else corpus_hash(contract)
        materialization = {'contract': contract}
        for version, asset, content in [('observation:1', 'observation', observation), ('materialization:1', 'materialization', materialization)]:
            cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,content,content_hash,lifecycle,governance) VALUES(%s,%s,%s,%s,'ACTIVE','CLEAR')", [version, asset, Jsonb(content), corpus_hash(content)])
        request = {'_production_execution': {'capability_runtime': {'materialization_asset_version_id': 'materialization:1',
            'materialization_content_hash': corpus_hash(materialization), 'materialization_hash': contract['materialization_hash']}}}
        result = {'operation_id': 'failed', 'outcome': 'FINAL_FAILURE', 'error': {'cause_code': 'OTHER' if fault == 'receipt' else 'PROVIDER_SCHEMA_REJECTED', 'stage': 'OUTPUT_CONTRACT_ADMISSION'}}
        evidence = {'production_execution': {'execution_result': result}}
        cursor.execute("INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,capability,status,request_payload,request_hash,last_error) VALUES('effect','failed','project','model.invoke','mkaos.knowledge.extract',%s,%s,%s,%s)", ['UNKNOWN' if fault == 'unknown' else 'FAILED_FINAL', Jsonb(request), corpus_hash(request), Jsonb({} if fault == 'last_error' else evidence)])
        cursor.execute("INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,generation,evidence,payload_hash,status) VALUES('dispatch','effect',1,%s,%s,%s)", [Jsonb(evidence), 'wrong' if fault == 'dispatch_hash' else corpus_hash(request), 'SUCCEEDED' if fault == 'dispatch_status' else 'FAILED_FINAL'])
        if fault == 'lease':
            cursor.execute("INSERT INTO authority_attempt(attempt_id,operation_id) VALUES('attempt','failed')")
            cursor.execute("INSERT INTO authority_lease_acquisition(lease_id,attempt_id,status) VALUES('lease','attempt','HELD')")
        seen = []
        app = SimpleNamespace(database_url=DATABASE_URL, _admit_mkaos_from_scope=lambda **kwargs: seen.append(kwargs) or 'successor')
        principal = SimpleNamespace(principal_id='other' if fault == 'actor' else 'operator', require=lambda *args: None)
        args = dict(project_id='project', operation_id='failed', expected_version=4 if fault == 'version' else 3,
            authorization_ref='fixture-authorization', reason='Correct the frozen rejected output Schema', principal=principal)
        if fault:
            with pytest.raises(KernelError):
                recover_abstraction_schema(app, **args)
            assert not seen
        else:
            recovered = recover_abstraction_schema(app, **args)
            assert recovered['output_contract']['version'] == CRAFT_OUTPUT_CONTRACT
            assert recovered['new_observation_required'] is False
            assert recovered['knowledge_approved'] is False
            assert seen[0]['schema_recovery']['original_external_effect_id'] == 'effect'
            assert seen[0]['payload']['mkaos_capability'] == 'mkaos.knowledge.extract'
            cursor.execute("SELECT o.status,o.version,e.status FROM authority_operation o JOIN authority_external_effect e USING(operation_id) WHERE o.operation_id='failed'")
            assert cursor.fetchone() == ('FAILED_FINAL', 3, 'FAILED_FINAL')
