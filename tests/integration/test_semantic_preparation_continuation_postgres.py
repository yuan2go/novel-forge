import copy
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb
import pytest

from novel_forge.storage.migrations.versions.v20261018_0226_semantic_preparation_continuation import PERMITTED
from novel_forge.storage.migrations.versions.v20261018_0227_completed_preparation_handoff import PERMITTED as HANDOFF_PERMITTED
from novel_forge.storage.migrations.versions.v20261018_0228_terminal_preparation_handoff import PERMITTED as TERMINAL_PERMITTED
from novel_forge.storage.migrations.versions.v20261019_0229_routing_observation_preparation_recovery import PERMITTED as QUERY_PERMITTED
from novel_forge.storage.migrations.versions.v20261019_0230_unsent_preparation_lineage import PERMITTED as LINEAGE_PERMITTED, QUERY_V9_PERMITTED
from tests.integration.authority_postgres_support import DATABASE_URL


@pytest.mark.parametrize('mode', ['zero-send', 'acknowledged-preparation', 'terminal-preparation', 'query-preparation', 'lineage-preparation', 'query-after-lineage'])
def test_semantic_preparation_sql_preserves_exact_source_and_dispatch_guards(mode):
    completed = mode != 'zero-send'
    query_v9 = mode == 'query-after-lineage'
    lineage = mode == 'lineage-preparation'
    query = mode in {'query-preparation', 'lineage-preparation', 'query-after-lineage'}
    terminal = mode in {'terminal-preparation','query-preparation','lineage-preparation','query-after-lineage'}
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in (
                "operation", "story_planning_runtime_continuation", "story_planning_generation", "attempt",
                "attempt_capability_pack_snapshot", "operation_output_asset", "asset_version", "asset",
                "book_production", "story_formation_run", "story_creation_cancellation", "external_effect",
                "budget_reservation", "lease_acquisition", "cancellation_command", "worker_cancel_signal",
            ):
                connection.execute(f"CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA")
            connection.execute((QUERY_V9_PERMITTED if query_v9 else LINEAGE_PERMITTED if lineage else QUERY_PERMITTED if query else TERMINAL_PERMITTED if terminal else HANDOFF_PERMITTED if completed else PERMITTED).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))

            def insert(table, **values):
                columns = ",".join(values)
                placeholders = ",".join(["%s"] * len(values))
                connection.execute(f"INSERT INTO authority_{table} ({columns}) VALUES ({placeholders})",
                    [Jsonb(value) if isinstance(value, (dict, list)) else value for value in values.values()])

            working = {"book_run_id": "run", "target_chapter": 19, "accepted_through_chapter": 0}
            source = {"arc_working_set": {"working_manuscript": working}, "book_id": "book"}
            if completed:
                source['runtime_continuation_id'] = 'parent'
            child = {**source, "runtime_continuation_id": "runtime", "idempotency_key": "successor"}
            failure = {"error_code": "PROVIDER_CONTEXT_CAPACITY_UNCERTAIN", "failure_class": "retryable",
                "error_message": "PROVIDER_CONTEXT_CAPACITY_UNCERTAIN: a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression",
                "failure_details": {"upper_bound": 477003, "limit": 475000, "actual_tokens": None}}
            proof = {"contract_version": "same-capacity-semantic-preparation.v1", "context_asset_version_id": "context",
                "context_content_hash": "context-hash", "source_failure": failure, "single_request_limit": 475000}
            target = {"planning_capacity": {"context_revalidation": proof, "external_intents_at_source": 0,
                "allocated_task_tokens": 512000, "prior_task_tokens": 512000, "single_request_ceiling": 475000,
                "source_failure": failure}}
            if completed:
                target['planning_capacity']['external_intents_at_source'] = 1
                target['preparation_handoff'] = dict(contract_version='planning-completed-preparation-handoff.v1',
                    source_operation_id='source',source_attempt_id='attempt',source_submission_rights='REVOKED_BY_ACKNOWLEDGED_CANCELLATION',
                    main_dispatch_count=0,input_snapshot_id='book-snapshot',context_asset_version_id='context',context_content_hash='context-hash',
                    preparation_source_boundary=dict(kind='FROZEN_STAGE_INPUTS',project_id='project',book_id='book',pack_snapshot_hash='snapshot-hash',
                        sources=[dict(asset_version_id='context',content_hash='context-hash')]),preparation_source_projection_hash='projection-hash',
                    retained_preparation=[dict(external_effect_id='prepared',request_hash='request-hash',stage='context_compress')])
            host_failure = dict(error_code='CONTEXT_COMPRESSION_TASK_INVALID', failure_class='final_failure',
                error_message='CONTEXT_COMPRESSION_TASK_INVALID: compression needs a bounded source chunk and frozen task boundary', failure_details={})
            if terminal:
                target['preparation_handoff'].update(contract_version='planning-terminal-preparation-handoff.v1',
                    source_submission_rights='RELEASED_BY_TERMINAL_FAILURE', host_failure=host_failure)
            if query:
                host_failure = dict(error_code='PROGRAMMING_BUG', failure_class='programming_bug', error_message='canceling statement due to statement timeout', failure_details={})
                if lineage:
                    host_failure = dict(error_code='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED', failure_class='retryable', error_message='PLANNING_ROUTING_LINEAGE_DEPTH_EXCEEDED: Planning repair routing lineage exceeds its bounded depth', failure_details={})
                inherited = copy.deepcopy(target['preparation_handoff'])
                inherited['contract_version'] = 'planning-unsent-preparation-lineage-handoff.v1' if query_v9 else 'planning-unsent-preparation-query-handoff.v1' if lineage else 'planning-isolated-preparation-handoff.v1'
                inherited.pop('host_failure')
                target['preparation_handoff'] = {**inherited, 'contract_version':'planning-unsent-preparation-lineage-handoff.v1' if lineage else 'planning-unsent-preparation-query-handoff.v1',
                    'source_submission_rights':'RELEASED_BY_UNSENT_LINEAGE_FAILURE' if lineage else 'RELEASED_BY_UNSENT_QUERY_FAILURE', ('unsent_lineage_failure' if lineage else 'unsent_query_failure'):dict(
                        source_operation_id='source',source_attempt_id='attempt',original_failure=host_failure,inherited_preparation=inherited)}
                target['planning_capacity']['external_intents_at_source'] = 0
            for identity, status, definition, actor, payload, sha, cause in (
                ("source", "RECONCILIATION_REQUIRED" if completed and not terminal else "FAILED_FINAL", "story_planning.generate", "author" if completed else "worker", source, "old", None),
                ("child", "ADMITTED", "story_planning.generate", "author" if completed else "worker", child, "new", "source"),
                ("registration", "SUCCEEDED", "story_planning.runtime_continuation.register", "author", {}, "new", None),
            ):
                insert("operation", operation_id=identity, status=status, definition_name=definition, definition_version="9.0.0" if (lineage or query_v9) and identity=='registration' else "8.0.0" if query and identity=='registration' else "6.0.0" if terminal and identity=='registration' else "5.0.0" if completed and identity=='registration' else "1.21.0",
                    actor_id=actor, project_id="project", workspace_id="workspace", command_payload={"payload": payload},
                    definition_snapshot={"commit_sha": sha}, causation_operation_id=cause)
            insert("story_planning_runtime_continuation", continuation_id="runtime", source_operation_id="source",
                successor_operation_id="child", registered_by_operation_id="registration", chain_depth=2 if completed else 1,
                source_command=source, successor_command=child, project_id="project", workspace_id="workspace", book_id="book",
                target_runtime=target, decision_evidence={"formation_run_id": "formation"}, source_release_sha="old", target_release_sha="new")
            generation = {"book_id": "book", "generator_operation_name": "chapter_plan.generate", "logical_key": "chapter:19",
                "planning_scope": "CHAPTER", "input_snapshot": [{"role": "plan", "asset_version_id": "plan:v1", "content_hash": "hash"}],
                "input_snapshot_hash": "frozen-input-hash", "repair_number": 0}
            insert("story_planning_generation", operation_id="source", **generation)
            insert("attempt", operation_id="source", attempt_id="attempt", attempt_number=1, status="FAILED_RETRYABLE" if lineage else "FAILED_FINAL" if terminal else "CANCELLED" if completed else "FAILED_RETRYABLE", result=host_failure if terminal else {} if completed else failure)
            insert("attempt_capability_pack_snapshot", operation_id="source", attempt_id="attempt",
                snapshot_payload={"context_policy_ref": "context-policy:chapter-generation-pack:v4"},snapshot_hash='snapshot-hash')
            insert("operation_output_asset", operation_id="source", output_key="planning.context_bundle", asset_version_id="context", content_hash="context-hash", role="context_bundle")
            insert("asset", asset_id="context-owner", project_id="project", asset_type="context_bundle")
            insert("asset_version", asset_id="context-owner", asset_version_id="context", content_hash="context-hash",
                content={"project_id": "project", "workspace_id": "workspace", "book_id": "book",
                    "planning_context_policy_version": "context-policy:chapter-generation-pack:v4", "arc_working_set": source["arc_working_set"]})
            insert("book_production", book_run_id="run", project_id="project", workspace_id="workspace", book_id="book",
                state="READY", current_chapter=18, accepted_through_chapter=0, root_operation_id='book-root',input_snapshot_id='book-snapshot')
            insert("story_formation_run", formation_run_id="formation", project_id="project", workspace_id="workspace", book_id="book",
                frozen_stage_inputs={"generation_policy": {"auto_authorization": {"authorized_by_principal_id": "author"}}})
            insert("asset", asset_id="receipt-owner", project_id="project", asset_type="planning_runtime_continuation")
            insert("asset_version", asset_id="receipt-owner", asset_version_id="receipt", content={"source_operation_id": "source", "target_runtime": target})
            insert("operation_output_asset", operation_id="registration", role="primary", asset_version_id="receipt")
            if completed and not query:
                insert('story_planning_runtime_continuation', continuation_id='parent',successor_operation_id='source',
                    successor_command=source,project_id='project',workspace_id='workspace',book_id='book',chain_depth=1,
                    target_runtime={'planning_capacity':dict(target['planning_capacity'])})
                insert('external_effect', external_effect_id='prepared',operation_id='source',effect_type='model.invoke',status='SUCCEEDED',
                    request_hash='request-hash',request_payload={'stage':'context_compress','input':{'context_compression_task':{
                        'contract_version':'task-context-compression.v3','frozen_input_boundary':target['preparation_handoff']['preparation_source_boundary'],
                        'task':{'source_projection_hash':'projection-hash'}}}})
                insert('budget_reservation',external_effect_id='prepared',operation_id='source',status='SETTLED')
                if not terminal:
                    insert('cancellation_command',operation_id='source',actor_id='author')
                    insert('worker_cancel_signal',operation_id='source',attempt_id='attempt',status='ACKNOWLEDGED',acknowledged_at=datetime.now(timezone.utc))

            if query:
                insert('operation',operation_id='prior-registration',status='SUCCEEDED',definition_name='story_planning.runtime_continuation.register',definition_version='9.0.0' if query_v9 else '8.0.0' if lineage else '7.0.0',actor_id='author')
                insert('asset',asset_id='prior-receipt-owner',project_id='project',asset_type='planning_runtime_continuation')
                insert('asset_version',asset_id='prior-receipt-owner',asset_version_id='prior-receipt',content=dict(
                    continuation_id='parent',successor_command=source,target_runtime=dict(
                        preparation_handoff=inherited,planning_capacity=copy.deepcopy(target['planning_capacity']))))
                insert('operation_output_asset',operation_id='prior-registration',asset_version_id='prior-receipt',role='primary')
            if lineage or query_v9:
                pack = dict(pack_id='pack',pack_version='version',manifest_hash='manifest',compilation_hash='compilation',catalog_snapshot_hash='catalog',binding_set_id='binding',binding_set_hash='binding-hash')
                connection.execute("UPDATE authority_attempt_capability_pack_snapshot SET snapshot_id='attempt-snapshot',snapshot_payload=snapshot_payload || %s",[Jsonb(pack)])
                materialization = dict(schema_version='novelos.planning_capability_materialization.v1',stage='context_fidelity',pack_identity=pack,
                    attempt_snapshot=dict(snapshot_id='attempt-snapshot',snapshot_hash='snapshot-hash',operation_id='source',attempt_id='attempt'))
                local = dict(asset_version_id='materialization',content_hash='materialization-hash',output_key='production_execution.contract.capability_materialization_manifest.token',role='execution_contract',asset_type='capability_materialization_manifest',stage='context_fidelity')
                insert('asset',asset_id='materialization-owner',project_id='project',asset_type=local['asset_type'])
                insert('asset_version',asset_id='materialization-owner',asset_version_id='materialization',content_hash='materialization-hash',content=dict(contract=materialization))
                insert('operation_output_asset',operation_id='source',**{key:local[key] for key in ('asset_version_id','content_hash','output_key','role')})
                target['preparation_handoff']['retained_local_preparation']=[local]
                connection.execute('UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s',[Jsonb(target)])
                connection.execute("UPDATE authority_asset_version SET content=jsonb_set(content,'{target_runtime}',%s) WHERE asset_version_id='receipt'",[Jsonb(target)])
            def allowed(value=generation):
                function = 'authority_unsent_preparation_query_v9_permitted' if query_v9 else 'authority_unsent_preparation_lineage_permitted' if lineage else 'authority_unsent_preparation_query_permitted' if query else 'authority_terminal_preparation_handoff_permitted' if terminal else 'authority_completed_preparation_handoff_permitted' if completed else 'authority_semantic_preparation_continuation_permitted'
                return connection.execute(f"SELECT {function}('runtime','child',%s)", [Jsonb(value)]).fetchone()[0]

            assert allowed()
            for field, value in (("book_id", "foreign"), ("repair_number", 1), ("input_snapshot_hash", "changed"),
                    ("input_snapshot", []), ("repair_of_candidate_id", "other"), ("candidate_asset_version_id", "result")):
                assert not allowed({**generation, field: value})
            for statement in (
                "UPDATE authority_operation SET actor_id='other' WHERE operation_id='child'",
                "UPDATE authority_operation SET status='RUNNING' WHERE operation_id='source'",
                "UPDATE authority_book_production SET current_chapter=19",
                "UPDATE authority_book_production SET accepted_through_chapter=1",
                "UPDATE authority_book_production SET active_chapter_request_id='concurrent'",
                "UPDATE authority_book_production SET state='CANCELLED'",
                "UPDATE authority_asset_version SET content_hash='wrong' WHERE asset_version_id='context'",
                "UPDATE authority_attempt_capability_pack_snapshot SET snapshot_payload='{\"context_policy_ref\":\"context-policy:chapter-generation-pack:v3\"}'",
                "UPDATE authority_attempt SET status='EXECUTING'",
                "INSERT INTO authority_external_effect(operation_id,status) VALUES('source','UNKNOWN')",
                "INSERT INTO authority_external_effect(operation_id,status) VALUES('source','SUCCEEDED')",
                "INSERT INTO authority_budget_reservation(operation_id,status) VALUES('source','HELD_UNKNOWN')",
                "INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('attempt','HELD')",
                "INSERT INTO authority_cancellation_command(operation_id,actor_id) VALUES('source','foreign')",
                "INSERT INTO authority_worker_cancel_signal(operation_id) VALUES('source')",
                "INSERT INTO authority_story_creation_cancellation(formation_run_id) VALUES('formation')",
            ):
                connection.execute("SAVEPOINT negative")
                connection.execute(statement)
                assert not allowed(), statement
                connection.execute("ROLLBACK TO SAVEPOINT negative")
            if completed and not query:
                for statement in (
                    "INSERT INTO authority_worker_cancel_signal(operation_id,status) VALUES('source','REQUESTED')" if terminal else "UPDATE authority_worker_cancel_signal SET status='REQUESTED',acknowledged_at=NULL",
                    "UPDATE authority_attempt SET result='{}'" if terminal else "UPDATE authority_attempt SET status='FAILED_FINAL'",
                    "UPDATE authority_external_effect SET status='UNKNOWN'",
                    "UPDATE authority_external_effect SET request_hash='wrong'",
                    "UPDATE authority_external_effect SET request_payload='{\"stage\":\"chapter_plan.generate\"}'",
                    "UPDATE authority_budget_reservation SET status='HELD_UNKNOWN'",
                    "UPDATE authority_book_production SET input_snapshot_id='replaced'",
                    "INSERT INTO authority_cancellation_command(operation_id,actor_id) VALUES('book-root','author')",
                ):
                    connection.execute('SAVEPOINT handoff_negative')
                    connection.execute(statement)
                    assert not allowed(), statement
                    connection.execute('ROLLBACK TO SAVEPOINT handoff_negative')
            if query:
                for statement in (
                    "UPDATE authority_attempt SET result='{}'",
                    "UPDATE authority_book_production SET input_snapshot_id='replaced'",
                    "INSERT INTO authority_cancellation_command(operation_id,actor_id) VALUES('book-root','author')",
                    "UPDATE authority_operation_output_asset SET role='primary' WHERE operation_id='source'",
                    "INSERT INTO authority_operation_output_asset(operation_id,output_key,asset_version_id,content_hash) VALUES('source','chapter.draft','draft','context-hash')",
                    "UPDATE authority_operation SET definition_version='4.0.0' WHERE operation_id='prior-registration'",
                    "UPDATE authority_asset_version SET content=jsonb_set(content,'{target_runtime,preparation_handoff,retained_preparation}','[]') WHERE asset_version_id='prior-receipt'",
                ):
                    connection.execute('SAVEPOINT query_negative')
                    connection.execute(statement)
                    assert not allowed(), statement
                    connection.execute('ROLLBACK TO SAVEPOINT query_negative')
            if lineage or query_v9:
                for statement in (
                    "UPDATE authority_asset_version SET content=jsonb_set(content,'{contract,stage}','\"chapter_plan.generate\"') WHERE asset_version_id='materialization'",
                    "UPDATE authority_asset_version SET content=jsonb_set(content,'{contract,pack_identity,pack_id}','\"foreign\"') WHERE asset_version_id='materialization'",
                    "UPDATE authority_asset_version SET content=jsonb_set(content,'{contract,attempt_snapshot,attempt_id}','\"foreign\"') WHERE asset_version_id='materialization'",
                    "UPDATE authority_asset_version SET content_hash='changed' WHERE asset_version_id='materialization'",
                    "UPDATE authority_operation_output_asset SET role='primary' WHERE asset_version_id='materialization'",
                    "UPDATE authority_story_planning_runtime_continuation SET target_runtime=jsonb_set(target_runtime,'{preparation_handoff,retained_local_preparation}','[]')",
                ):
                    connection.execute('SAVEPOINT materialization_negative')
                    connection.execute(statement)
                    assert not allowed(), statement
                    connection.execute('ROLLBACK TO SAVEPOINT materialization_negative')
            changed = copy.deepcopy(target)
            changed["planning_capacity"]["allocated_task_tokens"] = 512001
            connection.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s", [Jsonb(changed)])
            assert not allowed()
        finally:
            connection.rollback()


@pytest.mark.parametrize('binding', ['working', 'world', 'edition', 'search'])
def test_planning_dispatch_uses_exact_native_run_and_rejects_conflicting_or_missing_owner(binding):
    from novel_forge.modules.book_authority.production_policy import require_planning_provider_dispatch
    from novel_forge.modules.command_kernel.errors import KernelError
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in ('operation', 'story_planning_generation', 'book_production', 'cancellation_command',
                          'story_creation_cancellation', 'story_formation_run', 'story_narrative_search'):
                connection.execute(f'CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA')
            payload = {}
            if binding == 'working':
                payload['arc_working_set'] = dict(working_manuscript=dict(book_run_id='live'))
            elif binding == 'world':
                payload['world_preparation_request'] = dict(book_run_id='live')
            elif binding == 'edition':
                payload['edition_execution'] = dict(book_run_id='live')
            connection.execute("INSERT INTO authority_operation(operation_id,command_payload) VALUES('generation',%s)", [Jsonb(dict(payload=payload))])
            connection.execute("INSERT INTO authority_story_planning_generation(operation_id,project_id,workspace_id,book_id,narrative_search_id) VALUES('generation','project','workspace','book',%s)", ['search' if binding == 'search' else None])
            connection.execute("INSERT INTO authority_story_narrative_search(search_id,project_id,workspace_id,book_id,book_run_id) VALUES('search','project','workspace','book','live')")
            for run, state in [('live', 'READY'), ('sibling', 'CANCELLED')]:
                connection.execute('INSERT INTO authority_book_production(book_run_id,project_id,workspace_id,book_id,state,root_operation_id) VALUES(%s,\'project\',\'workspace\',\'book\',%s,%s)', [run, state, run+'-root'])
            def check():
                require_planning_provider_dispatch(connection.cursor(), project_id='project', operation_id='generation')
            check()
            for statement in (
                "UPDATE authority_story_narrative_search SET book_id='foreign'" if binding == 'search'
                    else "UPDATE authority_book_production SET workspace_id='foreign' WHERE book_run_id='live'",
                "UPDATE authority_book_production SET state='PAUSED' WHERE book_run_id='live'",
                "INSERT INTO authority_cancellation_command(operation_id) VALUES('live-root')",
                "UPDATE authority_book_production SET book_run_id='missing' WHERE book_run_id='live'",
                "UPDATE authority_book_production SET project_id='foreign' WHERE book_run_id='live'",
                "UPDATE authority_operation SET command_payload=jsonb_set(command_payload,'{payload,edition_execution}','{\"book_run_id\":\"sibling\"}')" if binding != 'edition'
                    else "UPDATE authority_operation SET command_payload=jsonb_set(command_payload,'{payload,world_preparation_request}','{\"book_run_id\":\"sibling\"}')",
            ):
                connection.execute('SAVEPOINT owner_negative')
                connection.execute(statement)
                if binding == 'search' and statement.startswith('UPDATE authority_story_narrative_search'):
                    connection.execute("DELETE FROM authority_book_production WHERE book_run_id='sibling'")
                with pytest.raises(KernelError, match='RUNTIME_DISPATCH_PAUSED|BOOK_GENERATION_EXECUTION_NOT_LIVE'):
                    check()
                connection.execute('ROLLBACK TO SAVEPOINT owner_negative')
            if binding == 'search':
                connection.execute('SAVEPOINT early_search')
                connection.execute('UPDATE authority_story_narrative_search SET book_run_id=NULL')
                connection.execute('DELETE FROM authority_book_production')
                check()
                connection.execute('ROLLBACK TO SAVEPOINT early_search')
            connection.execute("UPDATE authority_operation SET command_payload='{\"payload\":{}}'")
            connection.execute('UPDATE authority_story_planning_generation SET narrative_search_id=NULL')
            with pytest.raises(KernelError, match='BOOK_GENERATION_EXECUTION_NOT_LIVE'):
                check()
        finally:
            connection.rollback()


def test_pending_deployment_filters_exact_book_run_using_shared_dispatch_owner_scope():
    from novel_forge.modules.book_authority.production_policy import pending_planning_deployments
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in ('operation', 'story_planning_generation', 'story_planning_runtime_continuation', 'story_narrative_search'):
                connection.execute(f'CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA')
            for label, payload, search in (
                ('cancelled-sibling', {'arc_working_set': {'working_manuscript': {'book_run_id':'cancelled-run'}}}, None),
                ('working', {'arc_working_set': {'working_manuscript': {'book_run_id':'current-run'}}}, None),
                ('world', {'world_preparation_request': {'book_run_id':'current-run'}}, None),
                ('edition', {'edition_execution': {'book_run_id':'current-run'}}, None),
                ('search', {}, 'valid-search'),
                ('foreign-search', {'world_preparation_request': {'book_run_id':'current-run'}}, 'foreign-search'),
                ('conflict', {'arc_working_set': {'working_manuscript': {'book_run_id':'current-run'}},
                              'world_preparation_request': {'book_run_id':'cancelled-run'}}, None),
                ('unbound-opening', {}, None),
            ):
                connection.execute('INSERT INTO authority_operation(operation_id,command_payload) VALUES (%s,%s)', [label, Jsonb({'payload':payload})])
                connection.execute('INSERT INTO authority_story_planning_generation(operation_id,project_id,workspace_id,book_id,narrative_search_id) VALUES (%s,%s,%s,%s,%s)',
                    [label, 'project', 'workspace', 'book', search])
                connection.execute('INSERT INTO authority_story_planning_runtime_continuation(continuation_id,source_operation_id,project_id,book_id,target_release_sha,created_at) VALUES (%s,%s,%s,%s,%s,NOW())',
                    [label, label, 'project', 'book', 'old'])
            for label, project in (('valid-search', 'project'), ('foreign-search', 'foreign-project')):
                connection.execute('INSERT INTO authority_story_narrative_search(search_id,project_id,workspace_id,book_id,book_run_id) VALUES (%s,%s,%s,%s,%s)',
                    [label, project, 'workspace', 'book', 'current-run'])
            scope = dict(project_id='project', book_id='book', release_sha='new')
            selected = pending_planning_deployments(connection.cursor(), **scope, book_run_id='current-run')
            assert {row[0] for row in selected} == {'working','world','edition','search'}
            assert pending_planning_deployments(connection.cursor(), **scope, book_run_id='other-run') == []
            assert {row[0] for row in pending_planning_deployments(connection.cursor(), **scope, book_run_id='')} == {
                'cancelled-sibling','working','world','edition','search','foreign-search','conflict','unbound-opening'}
        finally:
            connection.rollback()
