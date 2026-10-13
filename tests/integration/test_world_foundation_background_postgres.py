from copy import deepcopy

import psycopg
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import MIGRATIONS, run_migrations
from novel_forge.storage.migrations.versions.v20261014_0209_world_foundation_background import UPGRADE_STATEMENTS
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import disposable_database_at_migration, restored_generation_backup
from tests.integration.test_world_contract_migration_guards_postgres import _schema


def test_foundation_background_guard_retains_exact_commands_sibling_receipts_and_live_lineage():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            _schema(connection)
            for ddl in (
                "ALTER TABLE authority_story_planning_runtime_continuation ADD COLUMN source_evidence_asset_version_id text",
                "ALTER TABLE authority_asset_version ADD COLUMN content_hash text DEFAULT 'sha256:asset'",
                "ALTER TABLE authority_external_effect ADD COLUMN effect_type text DEFAULT 'model.invoke'",
                "ALTER TABLE authority_external_effect_dispatch ADD COLUMN status text DEFAULT 'SUCCEEDED'",
                "ALTER TABLE authority_book_production ADD COLUMN current_chapter int DEFAULT 0",
                "ALTER TABLE authority_book_production ADD COLUMN accepted_through_chapter int DEFAULT 0",
                "ALTER TABLE authority_book_production ADD COLUMN input_snapshot_id text DEFAULT 'snapshot'",
                "ALTER TABLE authority_book_production ADD COLUMN active_chapter_request_id text",
                "CREATE TEMP TABLE authority_external_receipt(dispatch_id text,status text,payload jsonb)",
                "CREATE TEMP TABLE authority_generation_isolation(external_effect_id text,operation_id text,project_id text,workspace_id text,request_hash text,proof jsonb)",
            ):
                connection.execute(ddl)
            for statement in UPGRADE_STATEMENTS[:2]:
                connection.execute(statement)
            request = {"book_run_id": "run", "input_snapshot_id": "snapshot", "accepted_through_chapter": 0}
            command = {"book_id": "book", "logical_key": "chapter:1", "generator_operation_name": "chapter_plan.generate",
                "execution_contract_version": "1.21.0", "world_preparation_request": request}
            child = {**command, "repair_reason": "WORLD_HOST_REVALIDATION_SUCCESSOR", "runtime_continuation_id": "runtime"}
            refs = {key: {"asset_version_id": key, "content_hash": "sha256:asset"} for key in ("source-document", "generated", "evaluated", "blocked-action", "foundation")}
            proof = {"contract_version": "world-host-revalidation.v3", "revalidation_kind": "FOUNDATION_RULE_BACKGROUND",
                "source_operation_id": "source", "source": refs["source-document"], "generation": refs["generated"],
                "evaluation": refs["evaluated"], "action": refs["blocked-action"], "foundation_binding": refs["foundation"],
                "background_projection_hash": "sha256:" + "a" * 64, "plan_digest": "sha256:" + "b" * 64,
                "accepted_history_mutation_allowed": False, "character_knowledge_granted": False,
                "retained_effect_ids": ["generated-effect", "evaluated-effect"], "result_owners": {"generation": "origin", "evaluation": "source"}}
            for identity, status, payload, cause in (("origin", "FAILED_FINAL", command, None), ("source", "FAILED_FINAL", command, "origin"),
                ("child", "ADMITTED", child, "source"), ("registration", "SUCCEEDED", {}, None)):
                connection.execute("""INSERT INTO authority_operation(operation_id,project_id,workspace_id,actor_id,status,command_payload,
                    causation_operation_id,definition_name,definition_version) VALUES(%s,'project','workspace','owner',%s,%s,%s,%s,%s)""",
                    [identity, status, Jsonb({"payload": payload}), cause,
                        "story_planning.runtime_continuation.register" if identity == "registration" else "story_planning.generate",
                        "2.0.0" if identity == "registration" else "1.21.0"])
            connection.execute("""INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,book_id,
                generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status,repair_number)
                VALUES('source','source','project','workspace','book','chapter_plan.generate','CHAPTER','chapter:1','[]','sha256:frozen','FAILED_FINAL',0)""")
            connection.execute("""INSERT INTO authority_story_planning_runtime_continuation(continuation_id,source_operation_id,registered_by_operation_id,
                project_id,workspace_id,book_id,source_command,successor_command,target_runtime,decision_evidence,chain_depth,source_evidence_asset_version_id)
                VALUES('runtime','source','registration','project','workspace','book',%s,%s,%s,%s,9,'generated')""",
                [Jsonb(command), Jsonb(child), Jsonb({"world_host_revalidation": proof}), Jsonb({"host_revalidation": "world-host-revalidation.v3"})])
            connection.execute("INSERT INTO authority_attempt VALUES('attempt','source',1,'FAILED_FINAL','{\"error_code\":\"WORLD_PREPARATION_RESULT_INVALID\"}','{}')")
            foundation = {"entities": [{"entity_id": "system", "training_required": True}]}
            source = {"contract_version": "world-preparation-source.v3", "request": request, "world_foundation": foundation,
                "reality": {"baseline_kind": "APPROVED_FOUNDATION", "epistemic_contract": "world-agency.v2", "world_rule_constraints": [refs["foundation"]]}}
            documents = {"foundation": {"world_foundation": foundation}, "source-document": {"contract": source},
                "generated": {"contract": {"source": refs["source-document"], "evidence": {"operation_id": "origin", "external_receipt_ref": "generated-effect"}, "output": {"generation": "complete"}}},
                "evaluated": {"contract": {"source": refs["source-document"], "generation": refs["generated"], "evidence": {"operation_id": "source", "external_receipt_ref": "evaluated-effect"}, "output": {"evaluation": "complete"}}},
                "blocked-action": {"contract": {"source": refs["source-document"], "generation": refs["generated"], "evaluation": refs["evaluated"],
                    "world_plan": {"disposition": "BLOCKED", "rejected_paths": [{"rejection": {"code": "WORLD_COMPILED_RULE_VIOLATION"}}]}}}}
            for key, document in documents.items():
                connection.execute("INSERT INTO authority_asset_version(asset_version_id,content) VALUES(%s,%s)", [key, Jsonb(document)])
            for owner, asset in (("origin", "source-document"), ("origin", "generated"), ("source", "evaluated"), ("source", "blocked-action")):
                connection.execute("INSERT INTO authority_operation_output_asset VALUES(%s,%s)", [owner, asset])
            for key, owner, stage in (("generated", "origin", "world_candidates.generate"), ("evaluated", "source", "world_candidates.evaluate")):
                wire = {"stage": stage, "input": {"world_preparation": {"source_ref": refs["source-document"]}}}
                connection.execute("INSERT INTO authority_external_effect(operation_id,status,external_effect_id,request_payload) VALUES(%s,'SUCCEEDED',%s,%s)", [owner, key + "-effect", Jsonb(wire)])
                evidence = {"result": documents[key]["contract"]["output"]}
                connection.execute("INSERT INTO authority_external_effect_dispatch(external_effect_id,dispatch_id,generation,evidence) VALUES(%s,%s,1,%s)", [key + "-effect", key + "-dispatch", Jsonb(evidence)])
                connection.execute("INSERT INTO authority_external_receipt VALUES(%s,'VERIFIED',%s)", [key + "-dispatch", Jsonb({"evidence": evidence})])
            connection.execute("INSERT INTO authority_book_production(project_id,workspace_id,book_id,state,stable_idempotency_key,book_run_id) VALUES('project','workspace','book','CHAPTER_PLAN_REQUIRED','formation:production','run')")
            generation = {"project_id": "project", "workspace_id": "workspace", "book_id": "book", "generator_operation_name": "chapter_plan.generate",
                "logical_key": "chapter:1", "planning_scope": "CHAPTER", "input_snapshot": [], "input_snapshot_hash": "sha256:frozen", "repair_number": 0,
                "runtime_continuation_id": "runtime", "repair_reason": "WORLD_HOST_REVALIDATION_SUCCESSOR"}
            def permitted(value=generation):
                return connection.execute("SELECT authority_world_contract_continuation_permitted('runtime','child',%s)", [Jsonb(value)]).fetchone()[0]
            assert permitted()
            connection.execute("UPDATE authority_asset_version SET content=jsonb_build_object('candidate_payload',content) WHERE asset_version_id='foundation'")
            assert permitted()
            connection.execute("UPDATE authority_operation SET status='EXECUTING' WHERE operation_id='child'")
            connection.execute("INSERT INTO authority_attempt VALUES('child-attempt','child',1,'RUNNING','{}','{}')")
            connection.execute("INSERT INTO authority_lease_acquisition VALUES('child-attempt','HELD')")
            assert permitted()
            for mutation in (
                "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='registration'",
                "UPDATE authority_operation SET command_payload=jsonb_set(command_payload,'{payload,unfrozen}','true') WHERE operation_id='child'",
                "UPDATE authority_story_planning_runtime_continuation SET successor_operation_id='foreign'",
                "UPDATE authority_story_planning_generation SET candidate_asset_version_id='foreign'",
                "UPDATE authority_asset_version SET content_hash='drift' WHERE asset_version_id='foundation'",
                "UPDATE authority_asset_version SET content=jsonb_set(content,'{contract,world_foundation}','{}') WHERE asset_version_id='source-document'",
                "DELETE FROM authority_operation_output_asset WHERE asset_version_id='evaluated'",
                "UPDATE authority_external_effect SET request_payload='{}' WHERE external_effect_id='generated-effect'",
                "UPDATE authority_external_receipt SET payload='{}'",
                "UPDATE authority_external_effect SET status='UNKNOWN' WHERE external_effect_id='evaluated-effect'",
                "UPDATE authority_book_production SET current_chapter=1",
                "UPDATE authority_book_production SET active_chapter_request_id='active'",
                "INSERT INTO authority_story_creation_cancellation VALUES('project','formation')",
                "INSERT INTO authority_lease_acquisition VALUES('attempt','HELD')",
                "INSERT INTO authority_attempt VALUES('new-child-attempt','child',2,'RUNNING','{}','{}')",
                "INSERT INTO authority_budget_reservation(operation_id,status,external_effect_id) VALUES('source','HELD_UNKNOWN',NULL)",
            ):
                connection.execute("SAVEPOINT guard")
                connection.execute(mutation)
                assert not permitted(), mutation
                connection.execute("ROLLBACK TO SAVEPOINT guard")
                connection.execute("RELEASE SAVEPOINT guard")
            changed = deepcopy(generation)
            changed["input_snapshot_hash"] = "drift"
            assert not permitted(changed)
            connection.execute("INSERT INTO authority_external_effect(operation_id,status,external_effect_id) VALUES('origin','UNKNOWN','isolated-unknown')")
            assert not permitted()
            connection.execute("INSERT INTO authority_generation_isolation VALUES('isolated-unknown','origin','project','workspace','sha256:frozen','{\"contract_version\":\"pure-generation-isolation.v1\"}')")
            connection.execute("INSERT INTO authority_budget_reservation(operation_id,status,external_effect_id) VALUES('origin','HELD_UNKNOWN','isolated-unknown')")
            assert permitted()
            assert connection.execute("SELECT status FROM authority_external_effect WHERE external_effect_id='isolated-unknown'").fetchone() == ("UNKNOWN",)
        finally:
            connection.rollback()


def test_foundation_background_upgrade_backup_restore_preserves_legacy_guard_and_history(tmp_path):
    with disposable_database_at_migration(DATABASE_URL, prefix="world_foundation_upgrade", target_migration_id="20261014_0208_world_isolated_source_correction") as url:
        with psycopg.connect(url) as connection:
            old = connection.execute("SELECT pg_get_functiondef('authority_world_contract_continuation_permitted(text,text,jsonb)'::regprocedure)").fetchone()[0]
        assert run_migrations(url)["ok"]
        with psycopg.connect(url) as connection:
            legacy = connection.execute("SELECT pg_get_functiondef('authority_world_contract_continuation_permitted_legacy_0209(text,text,jsonb)'::regprocedure)").fetchone()[0]
            assert legacy == old.replace("authority_world_contract_continuation_permitted(", "authority_world_contract_continuation_permitted_legacy_0209(")
            assert connection.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='authority_story_planning_runtime_continuation'::regclass AND conname='authority_story_planning_runtime_continuation_chain_depth_check'").fetchone() == ("CHECK ((chain_depth > 0))",)
        with restored_generation_backup(url, backup_root=tmp_path / "world-foundation-restore") as restored:
            assert run_migrations(restored)["ok"]
            with psycopg.connect(restored) as connection:
                assert connection.execute("SELECT max(migration_id) FROM nf_schema_migrations").fetchone() == (MIGRATIONS[-1].migration_id,)
