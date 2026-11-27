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
from novel_forge.storage.migrations.versions.v20261019_0231_prepared_main_handoff import PERMITTED as MAIN_PERMITTED, HOST_PERMITTED
from tests.integration.authority_postgres_support import DATABASE_URL


@pytest.mark.parametrize('mode', ['zero-send', 'acknowledged-preparation', 'terminal-preparation', 'query-preparation', 'lineage-preparation', 'query-after-lineage', 'prepared-main', 'query-after-main', 'lineage-after-main'])
def test_semantic_preparation_sql_preserves_exact_source_and_dispatch_guards(mode):
    main = mode == 'prepared-main'
    after_main = mode in {'query-after-main','lineage-after-main'}
    completed = mode != 'zero-send'
    query_v9 = mode in {'query-after-lineage','query-after-main','lineage-after-main'}
    lineage = mode in {'lineage-preparation','lineage-after-main'}
    query = mode in {'query-preparation', 'lineage-preparation', 'query-after-lineage', 'prepared-main', 'query-after-main', 'lineage-after-main'}
    terminal = mode in {'terminal-preparation','query-preparation','lineage-preparation','query-after-lineage','prepared-main','query-after-main','lineage-after-main'}
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in (
                "operation", "story_planning_runtime_continuation", "story_planning_generation", "attempt",
                "attempt_capability_pack_snapshot", "operation_output_asset", "asset_version", "asset",
                "book_production", "story_formation_run", "story_creation_cancellation", "external_effect",
                "budget_reservation", "lease_acquisition", "cancellation_command", "worker_cancel_signal",
                "external_effect_dispatch", "effect_dispatch_lease", "external_receipt",
            ):
                connection.execute(f"CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA")
            connection.execute((HOST_PERMITTED[1 if lineage else 0] if after_main else MAIN_PERMITTED if main else QUERY_V9_PERMITTED if query_v9 else LINEAGE_PERMITTED if lineage else QUERY_PERMITTED if query else TERMINAL_PERMITTED if terminal else HANDOFF_PERMITTED if completed else PERMITTED).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))

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
                if after_main:
                    inherited.update(contract_version='planning-prepared-main-handoff.v1',main_dispatch_count=1)
                target['preparation_handoff'] = {**inherited, 'contract_version':'planning-unsent-preparation-lineage-handoff.v1' if lineage else 'planning-unsent-preparation-query-handoff.v1',
                    'source_submission_rights':'RELEASED_BY_UNSENT_LINEAGE_FAILURE' if lineage else 'RELEASED_BY_UNSENT_QUERY_FAILURE', ('unsent_lineage_failure' if lineage else 'unsent_query_failure'):dict(
                        source_operation_id='source',source_attempt_id='attempt',original_failure=host_failure,inherited_preparation=inherited)}
                if after_main:
                    target['preparation_handoff']['contract_version']='planning-prepared-main-handoff.v1'
                target['planning_capacity']['external_intents_at_source'] = 0
            if main:
                from novel_forge.modules.story_planning_runtime.preparation_recovery import PRE_SUBMIT_FAILURE
                host_failure = dict(error_code='EFFECT_RETRYABLE_FAILURE_RECORDED', failure_class='retryable', failure_details={},
                    error_message='EFFECT_RETRYABLE_FAILURE_RECORDED: adapter exception was recorded as retryable_failure')
                target['preparation_handoff'].update(contract_version='planning-prepared-main-handoff.v1', main_dispatch_count=1,
                    source_submission_rights='RELEASED_BY_TERMINAL_PRE_SUBMIT_HANDOFF',
                    prepared_main_failure=dict(source_operation_id='source',source_attempt_id='attempt',external_effect_id='main',
                        request_hash='main-hash',dispatch_id='main-dispatch',generation=1,diagnostic=PRE_SUBMIT_FAILURE,
                        original_failure=host_failure,inherited_preparation=inherited))
                target['preparation_handoff'].pop('unsent_query_failure')
                target['planning_capacity']['external_intents_at_source'] = 2
            for identity, status, definition, actor, payload, sha, cause in (
                ("source", "RECONCILIATION_REQUIRED" if completed and not terminal else "FAILED_FINAL", "story_planning.generate", "author" if completed else "worker", source, "old", None),
                ("child", "ADMITTED", "story_planning.generate", "author" if completed else "worker", child, "new", "source"),
                ("registration", "SUCCEEDED", "story_planning.runtime_continuation.register", "author", {}, "new", None),
            ):
                insert("operation", operation_id=identity, status=status, definition_name=definition, definition_version="10.0.0" if (main or after_main) and identity=='registration' else "9.0.0" if (lineage or query_v9) and identity=='registration' else "8.0.0" if query and identity=='registration' else "6.0.0" if terminal and identity=='registration' else "5.0.0" if completed and identity=='registration' else "1.21.0",
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
            insert("attempt", operation_id="source", attempt_id="attempt", attempt_number=1, status="FAILED_RETRYABLE" if lineage or main else "FAILED_FINAL" if terminal else "CANCELLED" if completed else "FAILED_RETRYABLE", result=host_failure if terminal else {} if completed else failure)
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
                insert('operation',operation_id='prior-registration',status='SUCCEEDED',definition_name='story_planning.runtime_continuation.register',definition_version='10.0.0' if after_main else '9.0.0' if query_v9 else '8.0.0' if lineage else '7.0.0',actor_id='author')
                insert('asset',asset_id='prior-receipt-owner',project_id='project',asset_type='planning_runtime_continuation')
                insert('asset_version',asset_id='prior-receipt-owner',asset_version_id='prior-receipt',content=dict(
                    continuation_id='parent',successor_command=source,target_runtime=dict(
                        preparation_handoff=inherited,planning_capacity=copy.deepcopy(target['planning_capacity']))))
                insert('operation_output_asset',operation_id='prior-registration',asset_version_id='prior-receipt',role='primary')
            if main:
                parent_target = dict(preparation_handoff=inherited,planning_capacity=copy.deepcopy(target['planning_capacity']))
                insert('story_planning_runtime_continuation',continuation_id='parent',successor_operation_id='source',
                    successor_command=source,project_id='project',book_id='book',target_runtime=parent_target,registered_by_operation_id='prior-registration')
                connection.execute("UPDATE authority_asset_version SET content=jsonb_set(content,'{target_runtime}',%s),content_hash='parent-hash' WHERE asset_version_id='prior-receipt'",[Jsonb(parent_target)])
                connection.execute("UPDATE authority_operation_output_asset SET content_hash='parent-hash' WHERE asset_version_id='prior-receipt'")
                boundary = target['preparation_handoff']['preparation_source_boundary']
                insert('external_effect',external_effect_id='main',operation_id='source',project_id='project',effect_type='model.invoke',status='FAILED_RETRYABLE',
                    request_hash='main-hash',last_error=PRE_SUBMIT_FAILURE,request_payload=dict(stage='chapter_plan.generate',operation_id='source',
                        _production_execution=dict(attempt_id='attempt'),input=dict(_context_capacity_projection=dict(source_boundary=boundary,original_hash='projection-hash'))))
                insert('budget_reservation',external_effect_id='main',operation_id='source',status='RELEASED')
                insert('external_effect_dispatch',external_effect_id='main',dispatch_id='main-dispatch',generation=1,status='FAILED_RETRYABLE',evidence=PRE_SUBMIT_FAILURE)
                insert('external_effect',external_effect_id='prepared',operation_id='source',effect_type='model.invoke',status='SUCCEEDED',request_hash='prepared-hash',
                    request_payload=dict(stage='context_compress',input=dict(context_compression_task=dict(frozen_input_boundary=boundary,task=dict(source_projection_hash='projection-hash')))))
                insert('budget_reservation',external_effect_id='prepared',operation_id='source',status='SETTLED')
                insert('external_effect_dispatch',external_effect_id='prepared',dispatch_id='prepared-dispatch',status='SUCCEEDED')
                insert('external_receipt',dispatch_id='prepared-dispatch',status='VERIFIED')
                target['preparation_handoff']['retained_preparation'] = [*inherited['retained_preparation'],dict(external_effect_id='prepared',operation_id='source',request_hash='prepared-hash',stage='context_compress',receipt_contract='STOPPED_GENERATION_SIBLING')]
                connection.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s WHERE continuation_id='runtime'",[Jsonb(target)])
                connection.execute("UPDATE authority_asset_version SET content=jsonb_set(content,'{target_runtime}',%s) WHERE asset_version_id='receipt'",[Jsonb(target)])
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
                function = 'authority_prepared_main_lineage_permitted' if after_main and lineage else 'authority_prepared_main_query_permitted' if after_main else 'authority_prepared_main_handoff_permitted' if main else 'authority_unsent_preparation_query_v9_permitted' if query_v9 else 'authority_unsent_preparation_lineage_permitted' if lineage else 'authority_unsent_preparation_query_permitted' if query else 'authority_terminal_preparation_handoff_permitted' if terminal else 'authority_completed_preparation_handoff_permitted' if completed else 'authority_semantic_preparation_continuation_permitted'
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
            if query and not main:
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
            if main:
                for statement in (
                    "UPDATE authority_external_effect SET last_error=jsonb_set(last_error,'{request_sent}','true') WHERE external_effect_id='main'",
                    "UPDATE authority_external_effect SET request_hash='changed' WHERE external_effect_id='main'",
                    "UPDATE authority_external_effect_dispatch SET status='UNKNOWN' WHERE external_effect_id='main'",
                    "INSERT INTO authority_external_effect_dispatch(external_effect_id,status) VALUES('main','FAILED_RETRYABLE')",
                    "INSERT INTO authority_effect_dispatch_lease(dispatch_id,status) VALUES('main-dispatch','HELD')",
                    "INSERT INTO authority_external_receipt(dispatch_id,status) VALUES('main-dispatch','VERIFIED')",
                    "UPDATE authority_external_effect SET status='UNKNOWN' WHERE external_effect_id='prepared'",
                    "UPDATE authority_external_receipt SET status='REJECTED' WHERE dispatch_id='prepared-dispatch'",
                    "UPDATE authority_book_production SET input_snapshot_id='replaced'",
                    "UPDATE authority_operation SET definition_version='9.0.0' WHERE operation_id='registration'",
                    "UPDATE authority_story_planning_runtime_continuation SET target_runtime=jsonb_set(target_runtime,'{preparation_handoff,retained_preparation}','[]') WHERE continuation_id='runtime'",
                ):
                    connection.execute('SAVEPOINT main_negative')
                    connection.execute(statement)
                    assert not allowed(), statement
                    connection.execute('ROLLBACK TO SAVEPOINT main_negative')
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


@pytest.mark.parametrize('contract,version', [('planning-unsent-preparation-query-handoff.v1','8.0.0'),('planning-unsent-preparation-lineage-handoff.v1','9.0.0'),('planning-prepared-main-handoff.v1','10.0.0')])
def test_unsent_carrier_control_reader_requires_exact_successful_native_receipt(monkeypatch, contract, version):
    from types import SimpleNamespace
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    from novel_forge.modules.story_planning_runtime.preparation_recovery import _require_unsent_carrier
    from novel_forge.modules.command_kernel.errors import KernelError
    frozen=dict(project_id='project',book_id='book',actor_id='author')
    key='prepared_main_failure' if version=='10.0.0' else 'unsent_lineage_failure' if version=='9.0.0' else 'unsent_query_failure'
    handoff=dict(contract_version=contract,**{key:dict(source_operation_id='source')})
    target=dict(preparation_handoff=handoff)
    member=dict(continuation_id='link',command=frozen,target=target)
    receipt=dict(source_operation_id='source',successor_command=frozen,target_runtime=target)
    monkeypatch.setattr('novel_forge.modules.story_planning_runtime.runtime_continuation.require_source',lambda *_a,**_kw:dict(completed_preparation=handoff))
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in ('story_planning_runtime_continuation','operation','operation_output_asset','asset_version','asset'):
                connection.execute(f'CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA')
            connection.execute("INSERT INTO authority_story_planning_runtime_continuation(continuation_id,source_operation_id,registered_by_operation_id,project_id,book_id) VALUES('link','source','control','project','book')")
            connection.execute("INSERT INTO authority_operation(operation_id,definition_name,definition_version,status,actor_id) VALUES('control','story_planning.runtime_continuation.register',%s,'SUCCEEDED','author')",[version])
            connection.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES('asset','project','planning_runtime_continuation')")
            connection.execute("INSERT INTO authority_asset_version(asset_id,asset_version_id,content,content_hash) VALUES('asset','receipt',%s,%s)",[Jsonb(receipt),canonical_hash(receipt)])
            connection.execute("INSERT INTO authority_operation_output_asset(operation_id,asset_version_id,role,content_hash) VALUES('control','receipt','primary',%s)",[canonical_hash(receipt)])
            with connection.cursor() as cursor:
                uow=SimpleNamespace(cursor=cursor)
                def read():return _require_unsent_carrier(uow,member=member,operation_id='source',frozen=frozen,rejected=KernelError('CARRIER_UNSAFE','exact control required'))
                assert read()
                for statement in (
                    "UPDATE authority_operation SET status='EXECUTING'",
                    "UPDATE authority_operation SET actor_id='foreign'",
                    "UPDATE authority_operation SET definition_version='7.0.0'",
                    "UPDATE authority_asset SET project_id='foreign'",
                    "UPDATE authority_asset SET asset_type='draft_version'",
                    "UPDATE authority_operation_output_asset SET role='execution_contract'",
                    "UPDATE authority_asset_version SET content_hash='wrong'",
                    "UPDATE authority_asset_version SET content=jsonb_set(content,'{source_operation_id}','\"foreign\"')",
                    "UPDATE authority_story_planning_runtime_continuation SET source_operation_id='other'",
                ):
                    cursor.execute('SAVEPOINT carrier_negative')
                    cursor.execute(statement)
                    with pytest.raises(KernelError,match='CARRIER_UNSAFE'):
                        read()
                    cursor.execute('ROLLBACK TO SAVEPOINT carrier_negative')
                if version=='9.0.0':
                    cursor.execute("UPDATE authority_operation SET definition_version='8.0.0'")
                    with pytest.raises(KernelError,match='CARRIER_UNSAFE'):
                        read()
        finally:
            connection.rollback()


@pytest.mark.parametrize('version,bridge,lineage_stop', [('11.0.0', False, False), ('11.0.0', True, False), ('12.0.0', False, False), ('12.0.0', True, False), ('12.0.0', True, True), ('13.0.0', True, True), ('14.0.0', False, False), ('15.0.0', False, False)])
def test_first_isolation_sql_retains_exact_stopped_ancestry_and_rejects_live_or_foreign_changes(version, bridge, lineage_stop):
    capacity_stop = version == '13.0.0'
    acknowledged = version in {'14.0.0', '15.0.0'}
    cli_version = version == '15.0.0'
    if cli_version:
        from novel_forge.storage.migrations.versions.v20261020_0237_preparation_cli_version_identity import PERMITTED as FIRST_PERMITTED
        from novel_forge.storage.migrations.versions.v20261019_0233_acknowledged_preparation_routing import MEMBER_STOPPED
    elif acknowledged:
        from novel_forge.storage.migrations.versions.v20261020_0236_acknowledged_preparation_custody import PERMITTED as FIRST_PERMITTED
        from novel_forge.storage.migrations.versions.v20261019_0233_acknowledged_preparation_routing import MEMBER_STOPPED
    elif capacity_stop:
        from novel_forge.storage.migrations.versions.v20261019_0234_settled_preparation_capacity import PERMITTED as FIRST_PERMITTED, MEMBER_STOPPED, CAPACITY_STOPPED
    elif version == '12.0.0':
        from novel_forge.storage.migrations.versions.v20261019_0233_acknowledged_preparation_routing import PERMITTED as FIRST_PERMITTED, MEMBER_STOPPED
    else:
        from novel_forge.storage.migrations.versions.v20261019_0232_first_isolated_preparation_custody import PERMITTED as FIRST_PERMITTED, MEMBER_STOPPED
    with psycopg.connect(DATABASE_URL) as c:
        try:
            for table in ('operation', 'story_planning_generation', 'story_planning_runtime_continuation', 'attempt',
                'attempt_capability_pack_snapshot', 'asset', 'asset_version', 'operation_output_asset', 'book_production',
                'story_formation_run', 'story_creation_cancellation', 'generation_isolation', 'cancellation_command',
                'worker_cancel_signal', 'lease_acquisition', 'external_effect', 'budget_reservation',
                'external_effect_dispatch', 'external_receipt', 'effect_dispatch_lease'):
                c.execute(f'CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA')
            for statement in ((CAPACITY_STOPPED,) if capacity_stop else ()) + (MEMBER_STOPPED, FIRST_PERMITTED):
                c.execute(statement.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
            def insert(table, **values):
                c.execute(f'INSERT INTO authority_{table} ({",".join(values)}) VALUES ({",".join(["%s"] * len(values))})',
                    [Jsonb(v) if isinstance(v, (dict, list)) else v for v in values.values()])
            command = dict(book_id='book', arc_working_set=dict(working_manuscript=dict(book_run_id='run', target_chapter=20, accepted_through_chapter=0)))
            source = 'lineage-stop' if lineage_stop else 'bridge' if bridge else 'anchor'
            bridge_command = {**command, 'runtime_continuation_id': 'generic'}
            source_command = {**command, **(dict(runtime_continuation_id='bridge-link' if lineage_stop else 'generic') if bridge else {})}
            child_command = {**command, 'runtime_continuation_id': 'new-link', 'idempotency_key': 'new'}
            gen = dict(book_id='book', generator_operation_name='chapter_plan.generate', logical_key='chapter:20', planning_scope='CHAPTER',
                input_snapshot=[], input_snapshot_hash='inputs', repair_number=0)
            for identity, status, payload in [('anchor', 'FAILED_FINAL', command), ('child', 'ADMITTED', child_command)]:
                insert('operation', operation_id=identity, status=status, project_id='project', workspace_id='workspace', actor_id='author',
                    definition_name='story_planning.generate', definition_version='1.21.0', command_payload=dict(payload=payload),
                    definition_snapshot=dict(commit_sha='new' if identity == 'child' else 'old'), causation_operation_id=source if identity == 'child' else None)
                insert('story_planning_generation', operation_id=identity, **gen)
            insert('attempt', attempt_id='anchor-attempt', operation_id='anchor', status='CANCELLED', attempt_number=1)
            insert('operation', operation_id='control', status='SUCCEEDED', actor_id='author', definition_name='story_planning.runtime_continuation.register', definition_version=version)
            isolation = dict(contract_version='pure-generation-isolation.v1', actor_id='author', business_commit_right='REVOKED', activation_right='REVOKED')
            insert('generation_isolation', operation_id='anchor', external_effect_id='unknown', project_id='project', workspace_id='workspace', request_hash='unknown-hash', proof=isolation)
            insert('external_effect', external_effect_id='unknown', operation_id='anchor', project_id='project', effect_type='model.invoke', status='UNKNOWN', request_hash='unknown-hash', request_payload=dict(stage='context_fidelity'))
            insert('budget_reservation', external_effect_id='unknown', operation_id='anchor', status='HELD_UNKNOWN')
            if bridge:
                insert('operation', operation_id='bridge', status='RECONCILIATION_REQUIRED', actor_id='author', project_id='project', workspace_id='workspace',
                    definition_name='story_planning.generate', definition_version='1.21.0', command_payload=dict(payload=bridge_command), definition_snapshot=dict(commit_sha='old'))
                insert('story_planning_generation', operation_id='bridge', **gen)
                insert('attempt', attempt_id='bridge-attempt', operation_id='bridge', status='CANCELLED', attempt_number=1)
                insert('cancellation_command', operation_id='bridge', actor_id='author')
                insert('worker_cancel_signal', operation_id='bridge', status='ACKNOWLEDGED', acknowledged_at=datetime.now(timezone.utc))
                insert('story_planning_runtime_continuation', continuation_id='generic', source_operation_id='anchor', successor_operation_id='bridge', project_id='project', book_id='book', chain_depth=1)
            if lineage_stop:
                from novel_forge.modules.story_planning_runtime.fresh_preparation_custody import LINEAGE_LINK_FAILURE
                insert('operation', operation_id='lineage-stop', status='FAILED_FINAL', actor_id='author', project_id='project', workspace_id='workspace',
                    definition_name='story_planning.generate', definition_version='1.21.0', command_payload=dict(payload=source_command), definition_snapshot=dict(commit_sha='old'))
                insert('story_planning_generation', operation_id='lineage-stop', **gen)
                insert('attempt', attempt_id='lineage-attempt', operation_id='lineage-stop', status='FAILED_FINAL', attempt_number=1, result=LINEAGE_LINK_FAILURE)
                insert('story_planning_runtime_continuation', continuation_id='bridge-link', source_operation_id='bridge', successor_operation_id='lineage-stop', project_id='project', book_id='book', chain_depth=2)
                assert not c.execute("SELECT authority_first_preparation_member_stopped('lineage-stop','author')").fetchone()[0]
                assert c.execute("SELECT authority_first_preparation_member_v12_stopped('lineage-stop','author')").fetchone()[0]
                if capacity_stop:
                    capacity_boundary = dict(kind='FROZEN_STAGE_INPUTS', project_id='project', book_id='book', pack_snapshot_hash='snapshot-hash', sources=[dict(asset_version_id='context', content_hash='context-hash')])
                    capacity_projection = dict(contract_version='complete-request-capacity.v1', semantic_contract='source-unit-dependency-and-final-composition.v2',
                        original_hash='projection', result_hash='projection', stage='chapter_plan.generate', source_boundary=capacity_boundary,
                        compression_receipt=dict(fast_path=True), measurement=dict(before_reserved=480000, after_reserved=480384, limit=475000, actual_provider_tokens=None))
                    failure = dict(error_code='TASK_CONTEXT_COMPRESSION_NO_PROGRESS', failure_class='retryable',
                        error_message='TASK_CONTEXT_COMPRESSION_NO_PROGRESS: All remaining source expression is required or already verified; the complete request still exceeds capacity',
                        failure_details=dict(projection=capacity_projection))
                    c.execute("UPDATE authority_attempt SET status='FAILED_RETRYABLE',result=%s WHERE attempt_id='lineage-attempt'", [Jsonb(failure)])
                    insert('external_effect', external_effect_id='capacity-success', operation_id='lineage-stop', project_id='project', effect_type='model.invoke', status='SUCCEEDED', request_hash='capacity-hash',
                        request_payload=dict(stage='context_fidelity', input=dict(context_compression_task=dict(frozen_input_boundary=capacity_boundary, task=dict(source_projection_hash='projection')))))
                    insert('budget_reservation', external_effect_id='capacity-success', operation_id='lineage-stop', project_id='project', status='SETTLED')
                    insert('external_effect_dispatch', dispatch_id='capacity-dispatch', external_effect_id='capacity-success', status='SUCCEEDED')
                    insert('external_receipt', dispatch_id='capacity-dispatch', status='VERIFIED')
                    assert not c.execute("SELECT authority_first_preparation_member_v12_stopped('lineage-stop','author')").fetchone()[0]
                    assert c.execute("SELECT authority_first_preparation_member_v13_stopped('lineage-stop','author')").fetchone()[0]
            snapshot = dict(context_policy_payload_json='{"planning_task_token_budget":512000}')
            boundary = dict(kind='FROZEN_STAGE_INPUTS', project_id='project', book_id='book', pack_snapshot_hash='snapshot-hash', sources=[dict(asset_version_id='context', content_hash='context-hash')])
            proof = dict(contract_version='planning-first-isolated-preparation-handoff.v1' if version == '11.0.0' else 'planning-first-isolated-preparation-handoff.v2', source_operation_id='anchor', source_attempt_id='anchor-attempt',
                custody_source_operation_id=source, main_dispatch_count=0, source_submission_rights='REVOKED_OR_TERMINALLY_RELEASED', input_snapshot_id='book-input',
                original_route=dict(model_provider='codex-cli', model_id='model', backend_id='backend', reasoning_effort='medium', auth_profile_ref='auth'),
                original_pack_snapshot=snapshot, original_pack_snapshot_id='snapshot', original_pack_snapshot_hash='snapshot-hash',
                context_asset_version_id='context', context_content_hash='context-hash', preparation_source_boundary=boundary, preparation_source_projection_hash='projection',
                stopped_ancestry=[dict(operation_id='anchor'), *([dict(operation_id='bridge')] if bridge else []), *([dict(operation_id='lineage-stop')] if lineage_stop else [])],
                retained_preparation=[dict(operation_id='anchor', external_effect_id='success', request_hash='success-hash', stage='context_compress')])
            if capacity_stop:
                proof['contract_version'] = 'planning-first-isolated-preparation-handoff.v3'
                proof['preparation_source_projection_hash'] = 'projection'
                proof['preparation_source_boundary'] = boundary
                proof['stopped_ancestry'][-1]['kind'] = 'UNSENT_CAPACITY_FAILURE'
                proof['retained_preparation'].append(dict(operation_id='lineage-stop', external_effect_id='capacity-success', request_hash='capacity-hash', stage='context_fidelity'))
            target = dict(model_provider='codex-cli', model_id='model', model_backend_id='backend', reasoning_effort='medium', auth_profile_ref='auth', preparation_handoff=proof, planning_capacity=dict(allocated_task_tokens=512000, prior_task_tokens=512000,
                context_revalidation=dict(contract_version='same-capacity-isolated-preparation.v1', context_asset_version_id='context', context_content_hash='context-hash')))
            insert('external_effect', external_effect_id='success', operation_id='anchor', project_id='project', effect_type='model.invoke', status='SUCCEEDED', request_hash='success-hash',
                request_payload=dict(stage='context_compress', input=dict(context_compression_task=dict(frozen_input_boundary=boundary, task=dict(source_projection_hash='projection')))))
            insert('budget_reservation', external_effect_id='success', operation_id='anchor', status='SETTLED')
            insert('external_effect_dispatch', dispatch_id='success-dispatch', external_effect_id='success', status='SUCCEEDED')
            insert('external_receipt', dispatch_id='success-dispatch', status='VERIFIED')
            insert('attempt_capability_pack_snapshot', operation_id='anchor', attempt_id='anchor-attempt', snapshot_id='snapshot', snapshot_hash='snapshot-hash', snapshot_payload=snapshot)
            insert('asset', asset_id='context-owner', project_id='project', asset_type='context_bundle')
            insert('asset_version', asset_version_id='context', asset_id='context-owner', content_hash='context-hash', content=dict(arc_working_set=command['arc_working_set']))
            insert('book_production', book_run_id='run', project_id='project', workspace_id='workspace', book_id='book', root_operation_id='book-root', current_chapter=19, accepted_through_chapter=0, state='PAUSED', input_snapshot_id='book-input')
            insert('story_formation_run', formation_run_id='formation', project_id='project', workspace_id='workspace', book_id='book', frozen_stage_inputs=dict(generation_policy=dict(auto_authorization=dict(authorized_by_principal_id='author'))))
            insert('story_planning_runtime_continuation', continuation_id='new-link', source_operation_id=source, successor_operation_id='child', registered_by_operation_id='control',
                source_command=source_command, successor_command=child_command, project_id='project', workspace_id='workspace', book_id='book', source_release_sha='old', chain_depth=3 if lineage_stop else 2 if bridge else 1, target_release_sha='new', target_runtime=target, decision_evidence=dict(formation_run_id='formation'))
            insert('asset', asset_id='receipt-owner', project_id='project', asset_type='planning_runtime_continuation')
            insert('asset_version', asset_version_id='receipt', asset_id='receipt-owner', content_hash='receipt-hash', content=dict(source_operation_id=source, target_runtime=target))
            insert('operation_output_asset', operation_id='control', asset_version_id='receipt', content_hash='receipt-hash', role='primary')
            if acknowledged:
                c.execute("DELETE FROM authority_generation_isolation")
                c.execute("DELETE FROM authority_external_effect WHERE external_effect_id='unknown'")
                c.execute("DELETE FROM authority_budget_reservation WHERE external_effect_id='unknown'")
                c.execute("UPDATE authority_operation SET status='RECONCILIATION_REQUIRED' WHERE operation_id='anchor'")
                insert('cancellation_command', operation_id='anchor', actor_id='author')
                insert('worker_cancel_signal', operation_id='anchor', status='ACKNOWLEDGED', acknowledged_at=datetime.now(timezone.utc))
                proof.update(contract_version='planning-acknowledged-preparation-handoff.v1', isolated_generation_count=0,
                    stopped_ancestry=[dict(operation_id='anchor', kind='ACKNOWLEDGED_CANCELLATION')])
                if cli_version:
                    old_entitlement = dict(cli_version='old', executable_sha256='same', configuration_ref='config', billing_identity=dict(account_ref='same'))
                    new_entitlement = {**old_entitlement, 'cli_version': 'observed'}
                    proof['contract_version'] = 'planning-acknowledged-preparation-handoff.v2'
                    proof['account_version_reconciliation'] = dict(version='codex-cli-version-reconciliation.v1',
                        source_auth_profile_ref='auth', target_auth_profile_ref='observed-auth', original_entitlement=old_entitlement,
                        target_entitlement=new_entitlement, original_entitlement_hash='old-hash')
                    target.update(auth_profile_ref='observed-auth', account=dict(entitlement=new_entitlement))
                    c.execute("UPDATE authority_external_receipt SET payload=%s", [Jsonb(dict(evidence=dict(cost=dict(
                        accounting_basis='ACCOUNT_ENTITLEMENT', entitlement_snapshot=old_entitlement, entitlement_snapshot_hash='old-hash'))))])
                target['preparation_handoff'] = proof
                c.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s WHERE continuation_id='new-link'", [Jsonb(target)])
                c.execute("UPDATE authority_asset_version SET content=%s WHERE asset_version_id='receipt'", [Jsonb(dict(source_operation_id=source, target_runtime=target))])
            def allowed():
                function = 'authority_acknowledged_cli_version_permitted' if cli_version else 'authority_acknowledged_preparation_permitted' if acknowledged else 'authority_first_isolated_preparation_v13_permitted' if capacity_stop else 'authority_first_isolated_preparation_v12_permitted' if version == '12.0.0' else 'authority_first_isolated_preparation_permitted'
                return c.execute('SELECT '+function+'(%s,%s,%s)', ['new-link', 'child', Jsonb(gen)]).fetchone()[0]
            assert allowed()
            if cli_version:
                for statement in (
                    "UPDATE authority_external_receipt SET payload='{}'",
                    "UPDATE authority_story_planning_runtime_continuation SET target_runtime=jsonb_set(target_runtime,'{account,entitlement,billing_identity,account_ref}','\"foreign\"')",
                    "UPDATE authority_story_planning_runtime_continuation SET target_runtime=jsonb_set(target_runtime,'{account,entitlement,cli_version}','\"old\"')",
                ):
                    c.execute('SAVEPOINT cli_negative')
                    c.execute(statement)
                    assert not allowed(), statement
                    c.execute('ROLLBACK TO SAVEPOINT cli_negative')
            if capacity_stop:
                for statement in (
                    "UPDATE authority_operation SET status='FAILED_RETRYABLE' WHERE operation_id='lineage-stop'",
                    "UPDATE authority_attempt SET result=jsonb_set(result,'{failure_details,projection,result_hash}','\"other\"') WHERE attempt_id='lineage-attempt'",
                    "UPDATE authority_attempt SET result=jsonb_set(result,'{failure_details,projection,source_boundary,book_id}','\"foreign\"') WHERE attempt_id='lineage-attempt'",
                    "UPDATE authority_attempt SET result=jsonb_set(result,'{failure_details,projection,measurement,after_reserved}','1') WHERE attempt_id='lineage-attempt'",
                    "UPDATE authority_budget_reservation SET status='HELD_UNKNOWN' WHERE external_effect_id='capacity-success'",
                    "UPDATE authority_external_receipt SET status='REJECTED' WHERE dispatch_id='capacity-dispatch'",
                    "UPDATE authority_external_effect SET request_payload='{}' WHERE external_effect_id='capacity-success'",
                    "INSERT INTO authority_cancellation_command(operation_id,actor_id) VALUES('lineage-stop','author')",
                ):
                    c.execute('SAVEPOINT capacity_negative')
                    c.execute(statement)
                    assert not allowed(), statement
                    c.execute('ROLLBACK TO SAVEPOINT capacity_negative')
            for statement in (
                "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='child'",
                "UPDATE authority_book_production SET current_chapter=20",
                "UPDATE authority_book_production SET accepted_through_chapter=1",
                "UPDATE authority_book_production SET input_snapshot_id='new-book-input'",
                *(["DELETE FROM authority_cancellation_command", "UPDATE authority_worker_cancel_signal SET acknowledged_at=NULL", "UPDATE authority_external_effect SET status='UNKNOWN' WHERE external_effect_id='success'"] if acknowledged else ["UPDATE authority_generation_isolation SET proof=jsonb_set(proof,'{activation_right}','\"GRANTED\"')", "DELETE FROM authority_generation_isolation"]),
                "UPDATE authority_external_effect SET request_hash='wrong' WHERE external_effect_id='success'",
                "UPDATE authority_budget_reservation SET status='RESERVED' WHERE external_effect_id='success'",
                "UPDATE authority_external_effect SET request_payload='{\"stage\":\"chapter_plan.generate\"}' WHERE external_effect_id='success'",
                "UPDATE authority_attempt SET status='EXECUTING' WHERE operation_id='anchor'",
                "INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('anchor-attempt','HELD')",
                "UPDATE authority_operation SET status='EXECUTING' WHERE operation_id='anchor'",
                "UPDATE authority_asset_version SET content_hash='wrong' WHERE asset_version_id='context'",
                "INSERT INTO authority_cancellation_command(operation_id) VALUES('book-root')",
                "UPDATE authority_story_planning_generation SET candidate_asset_version_id='already-written' WHERE operation_id='anchor'",
                "UPDATE authority_operation SET definition_version='1.0.0' WHERE operation_id='control'",
            ):
                c.execute('SAVEPOINT negative')
                c.execute(statement)
                assert not allowed(), statement
                c.execute('ROLLBACK TO SAVEPOINT negative')
        finally:
            c.rollback()


@pytest.mark.parametrize('version', ['5.0.0', '11.0.0', '12.0.0', '14.0.0', '15.0.0'])
def test_acknowledged_routing_link_retains_exact_frozen_contract_and_revoked_submission_rights(version):
    from novel_forge.modules.story_planning_runtime.runtime_continuation import acknowledged_routing_link, ACKNOWLEDGED_ROUTING_CONTRACTS
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    with psycopg.connect(DATABASE_URL) as c:
        try:
            for table in ('operation', 'story_planning_runtime_continuation', 'attempt', 'lease_acquisition',
                'cancellation_command', 'worker_cancel_signal', 'operation_output_asset', 'asset_version', 'asset'):
                c.execute(f'CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA')
            def insert(table, **values):
                c.execute(f'INSERT INTO authority_{table} ({",".join(values)}) VALUES ({",".join(["%s"] * len(values))})',
                    [Jsonb(v) if isinstance(v, (dict, list)) else v for v in values.values()])
            source = dict(project_id='project', workspace_id='workspace', book_id='book', actor_id='author', repair_number=0)
            successor = {**source, 'runtime_continuation_id': 'link'}
            contract, key = ACKNOWLEDGED_ROUTING_CONTRACTS[version]
            proof = dict(contract_version=contract, source_attempt_id='attempt', stopped_ancestry=[dict(operation_id='source',kind='ACKNOWLEDGED_CANCELLATION')])
            proof[key] = 'source'
            target = dict(preparation_handoff=proof)
            receipt = dict(contract_version='planning-runtime-continuation.v'+version.split('.')[0], source_operation_id='source',
                source_command=source, successor_command=successor, continuation_id='link', target_runtime=target)
            digest = canonical_hash(receipt)
            insert('operation', operation_id='source', status='RECONCILIATION_REQUIRED', project_id='project', workspace_id='workspace', actor_id='author', command_payload=dict(payload=source))
            insert('operation', operation_id='control', status='SUCCEEDED', actor_id='author', definition_name='story_planning.runtime_continuation.register', definition_version=version)
            insert('story_planning_runtime_continuation', continuation_id='link', source_operation_id='source', successor_operation_id='child', registered_by_operation_id='control',
                project_id='project', workspace_id='workspace', book_id='book', source_command=source, successor_command=successor, target_runtime=target)
            insert('attempt', attempt_id='attempt', operation_id='source', status='CANCELLED')
            insert('worker_cancel_signal', operation_id='source', attempt_id='attempt', status='ACKNOWLEDGED', acknowledged_at=datetime.now(timezone.utc))
            insert('cancellation_command', operation_id='source', actor_id='author')
            insert('asset', asset_id='owner', asset_type='planning_runtime_continuation', project_id='project')
            insert('asset_version', asset_id='owner', asset_version_id='receipt', content_hash=digest, content=receipt)
            insert('operation_output_asset', operation_id='control', asset_version_id='receipt', content_hash=digest, role='primary')
            def read():
                return acknowledged_routing_link(c.cursor(), continuation_id='link', successor_operation_id='child', project_id='project', book_id='book')
            assert read() == ('source', successor, source, source)
            for statement in (
                "UPDATE authority_operation SET actor_id='other' WHERE operation_id='control'",
                "UPDATE authority_operation SET definition_version='13.0.0' WHERE operation_id='control'",
                "UPDATE authority_operation SET status='EXECUTING' WHERE operation_id='source'",
                "UPDATE authority_attempt SET status='CHECKPOINTED'",
                "UPDATE authority_worker_cancel_signal SET acknowledged_at=NULL",
                "UPDATE authority_cancellation_command SET actor_id='other'",
                "DELETE FROM authority_cancellation_command",
                "INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('attempt','HELD')",
                "UPDATE authority_asset_version SET content_hash='wrong'",
                "UPDATE authority_asset_version SET content=jsonb_set(content,'{source_operation_id}','\"other\"')",
                "UPDATE authority_story_planning_runtime_continuation SET book_id='foreign'",
                "UPDATE authority_story_planning_runtime_continuation SET target_runtime=jsonb_set(target_runtime,'{preparation_handoff,contract_version}','\"unknown\"')",
            ):
                c.execute('SAVEPOINT negative_ack')
                c.execute(statement)
                assert read() is None, statement
                c.execute('ROLLBACK TO SAVEPOINT negative_ack')
        finally:
            c.rollback()


@pytest.mark.parametrize('prior', ['20261019_0233_acknowledged_preparation_routing', '20261019_0234_settled_preparation_capacity'])
def test_settled_capacity_upgrade_preserves_prior_functions_and_restored_business_facts(tmp_path, prior):
    from novel_forge.storage.migrations import run_migrations
    from tests.integration.migration_window_postgres_support import (
        disposable_database_at_migration, restored_generation_backup,
        _database_fingerprint, assert_database_at_migration,
    )
    current = '20261019_0235_source_isolation_convergence'
    with disposable_database_at_migration(DATABASE_URL, prefix='settled_capacity', target_migration_id=prior) as original:
        with restored_generation_backup(original, backup_root=tmp_path / 'restore') as restored:
            _, before = _database_fingerprint(restored)
            with psycopg.connect(restored) as c:
                names = ['authority_first_isolated_preparation_permitted', 'authority_first_isolated_preparation_v12_permitted',
                    'authority_first_preparation_member_stopped', 'authority_first_preparation_member_v12_stopped']
                old = dict(c.execute('SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE proname=ANY(%s)', [names]).fetchall())
                assert set(old) == set(names)
                isolated_before = c.execute("SELECT prosrc FROM pg_proc WHERE proname='authority_generation_isolation_guard'").fetchone()[0]
                assert 'working-plan-regeneration.v1' in isolated_before
                assert 'source-generation-isolation.v1' not in isolated_before
            status = run_migrations(restored, backup_directory=str(tmp_path / 'upgrade-backup'))
            assert status['ok']
            assert_database_at_migration(restored, target_migration_id=current)
            assert_database_at_migration(original, target_migration_id=prior)
            _, after = _database_fingerprint(restored)
            assert {k:v for k,v in before.items() if k != 'nf_schema_migrations'} == {k:v for k,v in after.items() if k != 'nf_schema_migrations'}
            with psycopg.connect(restored) as c:
                assert old == dict(c.execute('SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE proname=ANY(%s)', [names]).fetchall())
                guard = c.execute("SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname='authority_planning_result_repair_guard'").fetchone()[0]
                assert 'authority_first_isolated_preparation_v13_permitted' in guard
                isolated_after = c.execute("SELECT prosrc FROM pg_proc WHERE proname='authority_generation_isolation_guard'").fetchone()[0]
                assert 'working-plan-regeneration.v1' in isolated_after
                assert 'source-generation-isolation.v1' in isolated_after
            assert run_migrations(restored)['ok']


def test_chapter_dispatch_checks_native_book_pause_retirement_and_cancellation():
    from novel_forge.modules.book_authority.production_policy import require_chapter_provider_dispatch
    from novel_forge.modules.command_kernel.errors import KernelError
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in ('operation', 'book_chapter_request', 'book_production', 'cancellation_command',
                          'story_creation_cancellation', 'story_formation_run'):
                connection.execute(f'CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA')
            connection.execute("INSERT INTO authority_operation(operation_id,root_operation_id,project_id) VALUES('aux','chapter-root','project'),('revision','revision-root','project')")
            connection.execute("INSERT INTO authority_book_chapter_request(chapter_request_id,chapter_root_operation_id,book_run_id,project_id) VALUES('request','chapter-root','run','project')")
            connection.execute("INSERT INTO authority_book_production(book_run_id,project_id,book_id,state,root_operation_id,active_chapter_request_id) VALUES('run','project','book','READY','book-root','request')")
            def check(operation='aux'):
                require_chapter_provider_dispatch(connection.cursor(), project_id='project', operation_id=operation)
            check()
            for statement in (
                "UPDATE authority_book_production SET state='PAUSED'",
                "UPDATE authority_book_production SET active_chapter_request_id=NULL",
                "UPDATE authority_book_production SET project_id='foreign'",
                "INSERT INTO authority_cancellation_command(operation_id) VALUES('book-root')",
                "UPDATE authority_book_production SET state='COMPLETED'",
            ):
                connection.execute('SAVEPOINT chapter_negative')
                connection.execute(statement)
                with pytest.raises(KernelError, match='RUNTIME_DISPATCH_PAUSED|BOOK_GENERATION_EXECUTION_NOT_LIVE'):
                    check()
                check('revision')
                connection.execute('ROLLBACK TO SAVEPOINT chapter_negative')
        finally:
            connection.rollback()
