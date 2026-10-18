import copy

import psycopg
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations.versions.v20261018_0226_semantic_preparation_continuation import PERMITTED
from tests.integration.authority_postgres_support import DATABASE_URL


def test_semantic_preparation_sql_preserves_exact_source_and_dispatch_guards():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for table in (
                "operation", "story_planning_runtime_continuation", "story_planning_generation", "attempt",
                "attempt_capability_pack_snapshot", "operation_output_asset", "asset_version", "asset",
                "book_production", "story_formation_run", "story_creation_cancellation", "external_effect",
                "budget_reservation", "lease_acquisition", "cancellation_command", "worker_cancel_signal",
            ):
                connection.execute(f"CREATE TEMP TABLE authority_{table} AS SELECT * FROM public.authority_{table} WITH NO DATA")
            connection.execute(PERMITTED.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))

            def insert(table, **values):
                columns = ",".join(values)
                placeholders = ",".join(["%s"] * len(values))
                connection.execute(f"INSERT INTO authority_{table} ({columns}) VALUES ({placeholders})",
                    [Jsonb(value) if isinstance(value, (dict, list)) else value for value in values.values()])

            working = {"book_run_id": "run", "target_chapter": 19, "accepted_through_chapter": 0}
            source = {"arc_working_set": {"working_manuscript": working}, "book_id": "book"}
            child = {**source, "runtime_continuation_id": "runtime", "idempotency_key": "successor"}
            failure = {"error_code": "PROVIDER_CONTEXT_CAPACITY_UNCERTAIN", "failure_class": "retryable",
                "error_message": "PROVIDER_CONTEXT_CAPACITY_UNCERTAIN: a byte upper bound exceeds capacity; configure a matched tokenizer before lossy compression",
                "failure_details": {"upper_bound": 477003, "limit": 475000, "actual_tokens": None}}
            proof = {"contract_version": "same-capacity-semantic-preparation.v1", "context_asset_version_id": "context",
                "context_content_hash": "context-hash", "source_failure": failure, "single_request_limit": 475000}
            target = {"planning_capacity": {"context_revalidation": proof, "external_intents_at_source": 0,
                "allocated_task_tokens": 512000, "prior_task_tokens": 512000, "single_request_ceiling": 475000}}
            for identity, status, definition, actor, payload, sha, cause in (
                ("source", "FAILED_FINAL", "story_planning.generate", "worker", source, "old", None),
                ("child", "ADMITTED", "story_planning.generate", "worker", child, "new", "source"),
                ("registration", "SUCCEEDED", "story_planning.runtime_continuation.register", "author", {}, "new", None),
            ):
                insert("operation", operation_id=identity, status=status, definition_name=definition, definition_version="1.21.0",
                    actor_id=actor, project_id="project", workspace_id="workspace", command_payload={"payload": payload},
                    definition_snapshot={"commit_sha": sha}, causation_operation_id=cause)
            insert("story_planning_runtime_continuation", continuation_id="runtime", source_operation_id="source",
                successor_operation_id="child", registered_by_operation_id="registration", chain_depth=1,
                source_command=source, successor_command=child, project_id="project", workspace_id="workspace", book_id="book",
                target_runtime=target, decision_evidence={"formation_run_id": "formation"}, source_release_sha="old", target_release_sha="new")
            generation = {"book_id": "book", "generator_operation_name": "chapter_plan.generate", "logical_key": "chapter:19",
                "planning_scope": "CHAPTER", "input_snapshot": [{"role": "plan", "asset_version_id": "plan:v1", "content_hash": "hash"}],
                "input_snapshot_hash": "frozen-input-hash", "repair_number": 0}
            insert("story_planning_generation", operation_id="source", **generation)
            insert("attempt", operation_id="source", attempt_id="attempt", attempt_number=1, status="FAILED_RETRYABLE", result=failure)
            insert("attempt_capability_pack_snapshot", operation_id="source", attempt_id="attempt",
                snapshot_payload={"context_policy_ref": "context-policy:chapter-generation-pack:v4"})
            insert("operation_output_asset", operation_id="source", output_key="planning.context_bundle", asset_version_id="context", content_hash="context-hash")
            insert("asset", asset_id="context-owner", project_id="project", asset_type="context_bundle")
            insert("asset_version", asset_id="context-owner", asset_version_id="context", content_hash="context-hash",
                content={"project_id": "project", "workspace_id": "workspace", "book_id": "book",
                    "planning_context_policy_version": "context-policy:chapter-generation-pack:v4", "arc_working_set": source["arc_working_set"]})
            insert("book_production", book_run_id="run", project_id="project", workspace_id="workspace", book_id="book",
                state="READY", current_chapter=18, accepted_through_chapter=0)
            insert("story_formation_run", formation_run_id="formation", project_id="project", workspace_id="workspace", book_id="book",
                frozen_stage_inputs={"generation_policy": {"auto_authorization": {"authorized_by_principal_id": "author"}}})
            insert("asset", asset_id="receipt-owner", project_id="project", asset_type="planning_runtime_continuation")
            insert("asset_version", asset_id="receipt-owner", asset_version_id="receipt", content={"source_operation_id": "source", "target_runtime": target})
            insert("operation_output_asset", operation_id="registration", role="primary", asset_version_id="receipt")

            def allowed(value=generation):
                return connection.execute("SELECT authority_semantic_preparation_continuation_permitted('runtime','child',%s)", [Jsonb(value)]).fetchone()[0]

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
                "INSERT INTO authority_cancellation_command(operation_id) VALUES('source')",
                "INSERT INTO authority_worker_cancel_signal(operation_id) VALUES('source')",
                "INSERT INTO authority_story_creation_cancellation(formation_run_id) VALUES('formation')",
            ):
                connection.execute("SAVEPOINT negative")
                connection.execute(statement)
                assert not allowed(), statement
                connection.execute("ROLLBACK TO SAVEPOINT negative")
            changed = copy.deepcopy(target)
            changed["planning_capacity"]["allocated_task_tokens"] = 512001
            connection.execute("UPDATE authority_story_planning_runtime_continuation SET target_runtime=%s", [Jsonb(changed)])
            assert not allowed()
        finally:
            connection.rollback()
