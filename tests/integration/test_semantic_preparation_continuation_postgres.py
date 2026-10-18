import copy
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb
import pytest

from novel_forge.storage.migrations.versions.v20261018_0226_semantic_preparation_continuation import PERMITTED
from novel_forge.storage.migrations.versions.v20261018_0227_completed_preparation_handoff import PERMITTED as HANDOFF_PERMITTED
from novel_forge.storage.migrations.versions.v20261018_0228_terminal_preparation_handoff import PERMITTED as TERMINAL_PERMITTED
from tests.integration.authority_postgres_support import DATABASE_URL


@pytest.mark.parametrize('mode', ['zero-send', 'acknowledged-preparation', 'terminal-preparation'])
def test_semantic_preparation_sql_preserves_exact_source_and_dispatch_guards(mode):
    completed = mode != 'zero-send'
    terminal = mode == 'terminal-preparation'
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in (
                "operation", "story_planning_runtime_continuation", "story_planning_generation", "attempt",
                "attempt_capability_pack_snapshot", "operation_output_asset", "asset_version", "asset",
                "book_production", "story_formation_run", "story_creation_cancellation", "external_effect",
                "budget_reservation", "lease_acquisition", "cancellation_command", "worker_cancel_signal",
            ):
                connection.execute(f"CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA")
            connection.execute((TERMINAL_PERMITTED if terminal else HANDOFF_PERMITTED if completed else PERMITTED).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))

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
            for identity, status, definition, actor, payload, sha, cause in (
                ("source", "RECONCILIATION_REQUIRED" if completed and not terminal else "FAILED_FINAL", "story_planning.generate", "author" if completed else "worker", source, "old", None),
                ("child", "ADMITTED", "story_planning.generate", "author" if completed else "worker", child, "new", "source"),
                ("registration", "SUCCEEDED", "story_planning.runtime_continuation.register", "author", {}, "new", None),
            ):
                insert("operation", operation_id=identity, status=status, definition_name=definition, definition_version="6.0.0" if terminal and identity=='registration' else "5.0.0" if completed and identity=='registration' else "1.21.0",
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
            insert("attempt", operation_id="source", attempt_id="attempt", attempt_number=1, status="FAILED_FINAL" if terminal else "CANCELLED" if completed else "FAILED_RETRYABLE", result=host_failure if terminal else {} if completed else failure)
            insert("attempt_capability_pack_snapshot", operation_id="source", attempt_id="attempt",
                snapshot_payload={"context_policy_ref": "context-policy:chapter-generation-pack:v4"},snapshot_hash='snapshot-hash')
            insert("operation_output_asset", operation_id="source", output_key="planning.context_bundle", asset_version_id="context", content_hash="context-hash")
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
            if completed:
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

            def allowed(value=generation):
                function = 'authority_terminal_preparation_handoff_permitted' if terminal else 'authority_completed_preparation_handoff_permitted' if completed else 'authority_semantic_preparation_continuation_permitted'
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
            if completed:
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
            changed = copy.deepcopy(target)
            changed["planning_capacity"]["allocated_task_tokens"] = 512001
            connection.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s", [Jsonb(changed)])
            assert not allowed()
        finally:
            connection.rollback()
