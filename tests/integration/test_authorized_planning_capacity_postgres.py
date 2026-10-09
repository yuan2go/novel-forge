import psycopg
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations.versions.v20261010_0197_authorized_planning_capacity import UPGRADE_STATEMENTS
from tests.integration.authority_postgres_support import DATABASE_URL


def test_authorized_capacity_sql_keeps_scope_counters_effects_and_lease_guards():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for ddl in [
                'authority_operation(operation_id text,status text,definition_name text,actor_id text,project_id text,workspace_id text,command_payload jsonb,causation_operation_id text)',
                'authority_story_planning_runtime_continuation(continuation_id text,source_operation_id text,registered_by_operation_id text,successor_operation_id text,chain_depth int,project_id text,workspace_id text,book_id text,source_command jsonb,successor_command jsonb,target_runtime jsonb,decision_evidence jsonb)',
                'authority_story_planning_generation(operation_id text,generator_operation_name text,logical_key text,planning_scope text,input_snapshot jsonb,input_snapshot_hash text,repair_number int,narrative_search_id text,narrative_search_branch_key text)',
                'authority_operation_output_asset(operation_id text,output_key text,asset_version_id text)',
                'authority_asset_version(asset_version_id text,asset_id text,content_hash text,content jsonb)',
                'authority_asset(asset_id text,asset_type text)',
                'authority_story_formation_run(formation_run_id text,project_id text,book_id text,workspace_id text,frozen_stage_inputs jsonb)',
                'authority_story_creation_cancellation(formation_run_id text)',
                'authority_external_effect(operation_id text)',
                'authority_budget_reservation(operation_id text)',
                'authority_lease_acquisition(attempt_id text,status text)',
                'authority_attempt(operation_id text,attempt_id text,attempt_number int,status text,error jsonb,result jsonb)',
            ]:
                connection.execute('CREATE TEMP TABLE ' + ddl)
            connection.execute(UPGRADE_STATEMENTS[0])
            source = {'generator_operation_name': 'chapter_plan.generate', 'logical_key': 'chapter:5'}
            child = {**source, 'runtime_continuation_id': 'runtime', 'idempotency_key': 'child'}
            runtime = {'planning_capacity': {'external_intents_at_source': 0, 'context_revalidation': {
                'contract_version': 'planning-exact-value-reference.v1', 'context_asset_version_id': 'context',
                'context_content_hash': 'context-hash', 'blocked_decision_id': 'decision'}}}
            for identity, status, definition, payload, cause in [
                ('source', 'FAILED_FINAL', 'story_planning.generate', source, None),
                ('registered', 'SUCCEEDED', 'story_planning.runtime_continuation.register', {}, None),
                ('child', 'ADMITTED', 'story_planning.generate', child, 'source'),
            ]:
                connection.execute("INSERT INTO authority_operation VALUES(%s,%s,%s,'owner','project','workspace',%s,%s)", [identity, status, definition, Jsonb({'payload': payload}), cause])
            connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES('runtime','source','registered','child',2,'project','workspace','book',%s,%s,%s,%s)", [Jsonb(source), Jsonb(child), Jsonb(runtime), Jsonb({'formation_run_id': 'formation'})])
            connection.execute("INSERT INTO authority_story_planning_generation VALUES('source','chapter_plan.generate','chapter:5','CHAPTER','[]','snapshot-hash',2,NULL,NULL)")
            connection.execute("INSERT INTO authority_story_formation_run VALUES('formation','project','book','workspace',%s)", [Jsonb({'generation_policy': {'auto_authorization': {'authorized_by_principal_id': 'owner'}}})])
            connection.execute("INSERT INTO authority_attempt VALUES('source','attempt',1,'FAILED_FINAL','{}',%s)", [Jsonb({'error_code': 'PROVIDER_ROUTING_BLOCKED'})])
            connection.execute("INSERT INTO authority_operation_output_asset VALUES('source','planning.context_bundle','context'),('source','routing.decision','route')")
            connection.execute("INSERT INTO authority_asset VALUES('route','routing_decision')")
            connection.execute("INSERT INTO authority_asset_version VALUES('context','context','context-hash','{}'),('route','route','route-hash','{}')")
            generation = {'book_id': 'book', 'generator_operation_name': 'chapter_plan.generate', 'logical_key': 'chapter:5', 'planning_scope': 'CHAPTER', 'input_snapshot': [], 'input_snapshot_hash': 'snapshot-hash', 'repair_number': 2}
            def accepted(value=generation):
                return connection.execute("SELECT authority_unsent_context_continuation_permitted('runtime','child',%s)", [Jsonb(value)]).fetchone()[0]
            def route(reasons):
                content = {'decision_id': 'decision', 'status': 'BLOCKED', 'task': {'operation_id': 'source', 'project_id': 'project', 'work_id': 'book'}, 'candidates': [{'rejected_reasons': value} for value in reasons]}
                connection.execute("UPDATE authority_asset_version SET content=%s WHERE asset_version_id='route'", [Jsonb(content)])
            legal = [['TEMPLATE_MODEL_UNAUTHORIZED', 'CONTEXT_CAPACITY_EXCEEDED'], ['CONTEXT_CAPACITY_EXCEEDED', 'BUDGET_HARD_LIMIT']]
            route(legal)
            assert accepted()
            for denied in [[['TEMPLATE_MODEL_UNAUTHORIZED', 'CONTEXT_CAPACITY_EXCEEDED']], [['BUDGET_HARD_LIMIT']], [['AUTHORIZATION_MISSING', 'CONTEXT_CAPACITY_EXCEEDED']]]:
                route(denied)
                assert not accepted()
            route(legal)
            for field, value in [('book_id', 'foreign'), ('input_snapshot_hash', 'foreign'), ('repair_number', 0)]:
                assert not accepted({**generation, field: value})
            for mutation in ["INSERT INTO authority_external_effect VALUES('source')", "INSERT INTO authority_budget_reservation VALUES('source')", "INSERT INTO authority_lease_acquisition VALUES('attempt','HELD')", "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='child'"]:
                connection.execute('SAVEPOINT boundary')
                connection.execute(mutation)
                assert not accepted()
                connection.execute('ROLLBACK TO SAVEPOINT boundary')
                connection.execute('RELEASE SAVEPOINT boundary')
        finally:
            connection.rollback()
