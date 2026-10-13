import hashlib
from types import SimpleNamespace

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_import.generation_recovery import (
    _hash, source_observation_isolation_binding, require_source_observation_materialization,
    require_versioned_source_successor,
)
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


def _contracts():
    skill_text = 'An abstract optional writing method.\n'
    skill = {'ref': 'multidisciplinary-knowledge', 'version': '1.2.0', 'text': skill_text,
        'content_hash': 'sha256:' + hashlib.sha256(skill_text.encode()).hexdigest()}
    schema = {'type': 'object', 'properties': {'findings': {'type': 'array'}}}
    contract = {'schema_version': 'source-capability-materialization.v1',
        'stage': 'source.deconstruction.observe', 'capability': 'deconstruction.observe',
        'tool_permissions': {'default': 'DENY', 'allowed': ['model.provider.invoke']},
        'source_isolation': {'raw_source_allowed_in_generation_context': False,
            'raw_source_persisted_in_postgresql': False, 'provider_input_resolved_from_object_store': True},
        'skill': skill, 'output_schema': {'content': schema, 'content_hash': _hash(schema)}}
    contract['materialization_hash'] = _hash(contract)
    analyzer = {'skill_id': 'multidisciplinary-knowledge', 'skill_version': '1.2.0',
        'prompt_id': 'source.writing_theory_methods.craft_principle', 'prompt_version': '2.0',
        'schema_version': 'source-mechanism-observation.v2', 'dimension': 'craft_principle',
        'capability_id': 'deconstruction.observe', 'methodology_content_hash': skill['content_hash']}
    components = {'output_schema': _hash(schema),
        'governed_skill': 'sha256:' + hashlib.sha256(skill_text.strip().encode()).hexdigest(),
        'source_analysis_input': _hash('fixture input'), 'fully_rendered_prompt': _hash('fixture prompt')}
    prompt = {'skill': {k: skill[k] for k in ('ref', 'version', 'content_hash')},
        'output_schema_hash': _hash(schema), 'component_hashes': components,
        'fully_rendered_prompt_hash': components['fully_rendered_prompt']}
    provider_admission = {'input_component_hashes': components}
    admission = {'schema_version': 'novelos.provider_request_admission.v1',
        'source_bytes_transient_only': True, 'capability_materialization_asset_version_id': 'materialization',
        'capability_materialization_content_hash': _hash({'contract': contract}),
        'prompt_materialization': prompt, 'provider_admission': provider_admission}
    capability = {'materialization_asset_version_id': 'materialization',
        'materialization_content_hash': _hash({'contract': contract}),
        'materialization_hash': contract['materialization_hash'],
        'provider_admission_asset_version_id': 'admission',
        'provider_admission_content_hash': _hash({'contract': admission}),
        'provider_admission': provider_admission,
        'routing_decision': {'task': {'input_hash': components['fully_rendered_prompt']}}}
    return contract, analyzer, admission, capability


@pytest.mark.parametrize('fault', [None, 'operator', 'workspace', 'revision', 'policy', 'source',
    'phase', 'analyzer', 'materialization', 'missing_hashes', 'skill_bytes', 'input_hash', 'api_transport'])
def test_source_isolation_requires_owned_method_correction_and_preserves_unknown(fault):
    ensure_migrated()
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        tables = ('authority_source_import_job', 'authority_source_import_work', 'authority_operation',
            'authority_external_effect', 'authority_external_effect_dispatch', 'authority_asset',
            'authority_asset_version', 'authority_story_planning_generation', 'authority_lease_acquisition',
            'authority_attempt', 'authority_operation_output_asset', 'authority_generation_isolation')
        for table in tables:
            cursor.execute(sql.SQL('CREATE TEMP TABLE {} AS SELECT * FROM public.{} WITH NO DATA').format(
                sql.Identifier(table), sql.Identifier(table)))
        cursor.execute('CREATE TRIGGER isolation_guard BEFORE INSERT ON authority_generation_isolation FOR EACH ROW EXECUTE FUNCTION authority_generation_isolation_guard()')
        cursor.execute('CREATE TRIGGER effect_commit_guard BEFORE UPDATE ON authority_external_effect FOR EACH ROW EXECUTE FUNCTION authority_generation_commit_guard()')
        cursor.execute('CREATE TRIGGER output_commit_guard BEFORE INSERT ON authority_operation_output_asset FOR EACH ROW EXECUTE FUNCTION authority_generation_commit_guard()')
        contract, analyzer, admission, capability = _contracts()
        definition = {'family': 'source_import', 'handler_key': 'novel_forge.source_import.deconstruction_execute',
            'external_capabilities': ['deconstruction.observe'], 'policy': {'raw_source_in_generation_context_forbidden': True}}
        payload = {'payload': {'import_job_id': 'original', 'source_document_id': 'source-document',
            'analysis_task': {'analyzer': analyzer}}}
        operation = dict(operation_id='observation', actor_id='source-worker', workspace_id='workspace',
            definition_snapshot=definition, command_payload=payload)
        cursor.execute("INSERT INTO authority_operation(operation_id,actor_id,workspace_id,project_id,definition_name,definition_snapshot,status,command_payload) VALUES('owner','operator','workspace','project','analysis','{}','SUCCEEDED','{}'),('next-owner','operator','workspace','project','analysis','{}','SUCCEEDED','{}'),('observation','source-worker','workspace','project','source.import.deconstruction.execute',%s,'FAILED_FINAL',%s)", [Jsonb(definition), Jsonb(payload)])
        for job, owner, route in [('original', 'owner', 'v1'), ('successor', 'next-owner', 'v2'),
                ('renamed', 'owner', 'v1'), ('later-method', 'next-owner', 'different-method')]:
            cursor.execute("INSERT INTO authority_source_import_job(import_job_id,project_id,workspace_id,discovery_operation_id,source_type,intelligence_policy,source_locator) VALUES(%s,'project','workspace',%s,'corpus_content',%s,%s)", [job, owner, Jsonb({'routing_policy_version': 'source-analysis-routing.writing-methods.' + route}), Jsonb({'manifest': {'curated_revision_id': 'frozen-revision'}})])
            cursor.execute("INSERT INTO authority_source_import_work(operation_id,import_job_id,project_id,work_kind) VALUES(%s,%s,'project','DECONSTRUCTION')", ['observation' if job == 'original' else job + '-work', job])
        command = SimpleNamespace(project_id='project', actor_id='operator', evidence={'source_analysis_successor_import_job_id': 'successor'})
        if fault == 'operator':
            command.actor_id = 'other'
        if fault == 'workspace':
            cursor.execute("UPDATE authority_source_import_job SET workspace_id='other' WHERE import_job_id='successor'", [ ])
        if fault == 'revision':
            cursor.execute("UPDATE authority_source_import_job SET source_locator=%s WHERE import_job_id='successor'", [Jsonb({'manifest': {'curated_revision_id': 'other'}})])
        if fault == 'policy':
            cursor.execute("UPDATE authority_source_import_job SET intelligence_policy=%s WHERE import_job_id='successor'", [Jsonb({'routing_policy_version': 'source-analysis-routing.writing-methods.v1'})])
        if fault == 'source':
            payload['payload']['import_job_id'] = 'other'
        if fault == 'phase':
            payload['payload']['narrative_reading'] = {'phase': 'REVIEW'}
        if fault == 'analyzer':
            analyzer['prompt_version'] = 'other'
        if fault in {'operator', 'workspace', 'revision', 'policy', 'source', 'phase', 'analyzer'}:
            with pytest.raises(KernelError, match='SOURCE_ISOLATION_SCOPE_INVALID'):
                source_observation_isolation_binding(cursor, operation, command)
            return
        binding = source_observation_isolation_binding(cursor, operation, command)
        if fault == 'materialization':
            contract['source_isolation']['raw_source_allowed_in_generation_context'] = True
        if fault == 'missing_hashes':
            contract['skill'].pop('content_hash')
            analyzer.pop('methodology_content_hash')
        if fault == 'skill_bytes':
            contract['skill']['text'] += 'drift'
        if fault == 'input_hash':
            capability['routing_decision']['task']['input_hash'] = 'other'
        if fault in {'materialization', 'missing_hashes', 'skill_bytes', 'input_hash'}:
            with pytest.raises(KernelError, match='SOURCE_ISOLATION_MATERIALIZATION_INVALID'):
                require_source_observation_materialization(contract, capability, analyzer, admission)
            return
        require_source_observation_materialization(contract, capability, analyzer, admission)
        cursor.execute("INSERT INTO authority_asset(asset_id,project_id) VALUES('asset','project')")
        for version, content in [('materialization', contract), ('admission', admission)]:
            cursor.execute("INSERT INTO authority_asset_version(asset_version_id,asset_id,content,content_hash) VALUES(%s,'asset',%s,%s)", [version, Jsonb({'contract': content}), _hash({'contract': content})])
        cursor.execute("INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,status,request_hash,request_payload,capability) VALUES('effect','observation','project','model.invoke','UNKNOWN','request-hash',%s,'deconstruction.observe')", [Jsonb({'_production_execution': {'book_id': 'source-corpus:project', 'capability_runtime': capability}})])
        transport = 'REMOTE_PROVIDER_API' if fault == 'api_transport' else 'LOCAL_CLI_REMOTE_INFERENCE'
        cursor.execute("INSERT INTO authority_external_effect_dispatch(dispatch_id,external_effect_id,payload_hash,evidence) VALUES('dispatch','effect','request-hash',%s)", [Jsonb({'production_execution': {'execution_handle': {'transport': transport}}})])
        proof = {'contract_version': 'source-generation-isolation.v1', 'actor_id': 'operator',
            'execution_transport': transport, 'continuation_id': 'source-analysis-version:observation',
            'remote_outcome': 'UNKNOWN', 'usage': 'UNKNOWN', 'business_commit_right': 'REVOKED',
            'activation_right': 'REVOKED', 'source_recovery': binding}
        insert = "INSERT INTO authority_generation_isolation(isolation_id,external_effect_id,operation_id,project_id,workspace_id,book_id,request_hash,materialization_asset_version_id,proof) VALUES('isolation','effect','observation','project','workspace','source-corpus:project','request-hash','materialization',%s)"
        if fault == 'api_transport':
            with pytest.raises(psycopg.errors.RaiseException), connection.transaction():
                cursor.execute(insert, [Jsonb(proof)])
            return
        cursor.execute(insert, [Jsonb(proof)])
        cursor.execute("SELECT status,authority_generation_isolated('effect') FROM authority_external_effect WHERE external_effect_id='effect'")
        assert cursor.fetchone() == ('UNKNOWN', True)
        for statement in ("UPDATE authority_external_effect SET status='SUCCEEDED' WHERE external_effect_id='effect'",
                          "INSERT INTO authority_operation_output_asset(operation_id,role) VALUES('observation','primary')"):
            with pytest.raises(psycopg.errors.RaiseException, match='GENERATION_ATTEMPT_ISOLATED'), connection.transaction():
                cursor.execute(statement)
        require_versioned_source_successor(cursor, 'project', 'successor-work')
        require_versioned_source_successor(cursor, 'project', 'later-method-work')
        for blocked in ('observation', 'renamed-work'):
            with pytest.raises(KernelError, match='SOURCE_ISOLATED_CONTRACT_REDISPATCH_FORBIDDEN'):
                require_versioned_source_successor(cursor, 'project', blocked)
        for policy in ({'routing_policy_version': 'source-analysis-routing.writing-methods.v1', 'budget': 'changed'},
                       {'routing_policy_version': 'source-analysis-routing.writing-methods.v2'}):
            cursor.execute("UPDATE authority_source_import_job SET intelligence_policy=%s WHERE import_job_id='renamed'", [Jsonb(policy)])
            with pytest.raises(KernelError, match='SOURCE_ISOLATED_CONTRACT_REDISPATCH_FORBIDDEN'):
                require_versioned_source_successor(cursor, 'project', 'renamed-work')
        cursor.execute("UPDATE authority_source_import_job SET intelligence_policy=intelligence_policy||'{\"budget\":\"changed\"}'::jsonb WHERE import_job_id='successor'")
        with pytest.raises(KernelError, match='SOURCE_ISOLATED_CONTRACT_REDISPATCH_FORBIDDEN'):
            require_versioned_source_successor(cursor, 'project', 'successor-work')
        assert binding['original_actor_id'] == 'source-worker'
        assert binding['operator_actor_id'] == 'operator'
