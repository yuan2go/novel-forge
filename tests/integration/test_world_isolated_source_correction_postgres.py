import psycopg
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import MIGRATIONS, run_migrations
from novel_forge.storage.migrations.versions.v20261014_0208_world_isolated_source_correction import UPGRADE_STATEMENTS
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import (
    disposable_database_at_migration,
    restored_generation_backup,
)


def test_world_source_correction_requires_exact_parent_result_receipt_and_authority():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for ddl in [
                "authority_operation(operation_id text,status text,definition_name text,definition_version text,actor_id text,project_id text,workspace_id text,command_payload jsonb,causation_operation_id text)",
                "authority_story_planning_runtime_continuation(continuation_id text,source_operation_id text,registered_by_operation_id text,successor_operation_id text,chain_depth int,project_id text,workspace_id text,book_id text,source_command jsonb,successor_command jsonb,target_runtime jsonb,decision_evidence jsonb)",
                "authority_story_planning_generation(operation_id text,generator_operation_name text,logical_key text,planning_scope text,input_snapshot jsonb,input_snapshot_hash text,repair_number int,narrative_search_id text,narrative_search_branch_key text)",
                "authority_external_effect(operation_id text,external_effect_id text,project_id text,effect_type text,status text,request_payload jsonb,request_hash text)",
                "authority_generation_isolation(external_effect_id text,operation_id text,project_id text,workspace_id text,book_id text,request_hash text,proof jsonb)",
                "authority_budget_reservation(operation_id text)",
                "authority_lease_acquisition(attempt_id text,status text)",
                "authority_attempt(operation_id text,attempt_id text,attempt_number int,status text,result jsonb)",
                "authority_asset_version(asset_version_id text,content_hash text,content jsonb)",
                "authority_operation_output_asset(operation_id text,asset_version_id text)",
                "authority_external_effect_dispatch(dispatch_id text,external_effect_id text,status text,evidence jsonb)",
                "authority_external_receipt(dispatch_id text,status text,payload jsonb)",
                "authority_book_production(book_run_id text,project_id text,workspace_id text,book_id text,state text,current_chapter int,input_snapshot_id text,accepted_through_chapter int,stable_idempotency_key text)",
                "authority_story_creation_cancellation(project_id text,formation_run_id text)",
            ]:
                connection.execute("CREATE TEMP TABLE " + ddl)
            connection.execute(UPGRADE_STATEMENTS[0])
            request = {"book_run_id":"book-run","input_snapshot_id":"input","accepted_through_chapter":0}
            source = {"book_id":"book","world_preparation_request":request,"runtime_continuation_id":"parent"}
            child = {**source,"runtime_continuation_id":"correction","idempotency_key":"successor"}
            isolation = {"contract_version":"pure-generation-isolation.v1","external_effect_id":"unknown-director","authorization_ref":"original-isolation"}
            refs = {key:{"asset_version_id":key,"content_hash":key+"-hash"} for key in ("frozen","generated")}
            proof = {"contract_version":"world-isolated-source-correction.v1","source_operation_id":"source","parent_continuation_id":"parent","source":refs["frozen"],"generation":refs["generated"],"isolation":isolation,"skipped_source_versions":[{"source":"older"}]}
            target = {"world_source_correction":proof,"generation_isolation":isolation}
            for identity,status,definition,payload,cause in [
                ("origin","FAILED_FINAL","story_planning.generate",source,None),
                ("source","FAILED_FINAL","story_planning.generate",source,"origin"),
                ("child","ADMITTED","story_planning.generate",child,"source"),
                ("registered","SUCCEEDED","story_planning.runtime_continuation.register",{},None),
            ]:
                connection.execute("INSERT INTO authority_operation VALUES(%s,%s,%s,'1.21.0','creator','project','workspace',%s,%s)",[identity,status,definition,Jsonb({"payload":payload}),cause])
            for identity in ("origin","source"):
                connection.execute("INSERT INTO authority_story_planning_generation VALUES(%s,'chapter_plan.generate','chapter:1','CHAPTER','[]','input-hash',0,NULL,NULL)",[identity])
            connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES('parent','origin','registered','source',7,'project','workspace','book','{}',%s,%s,'{}')",[Jsonb(source),Jsonb({"generation_isolation":isolation})])
            decision = {"host_revalidation":"world-isolated-source-correction.v1","authorization_ref":"native-author-template"}
            connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES('correction','source','registered','child',8,'project','workspace','book',%s,%s,%s,%s)",[Jsonb(source),Jsonb(child),Jsonb(target),Jsonb(decision)])
            connection.execute("INSERT INTO authority_attempt VALUES('source','attempt',1,'FAILED_FINAL','{\"error_code\":\"WORLD_ISOLATED_RECEIPT_INVALID\"}')")
            connection.execute("INSERT INTO authority_external_effect VALUES('origin','unknown-director','project','model.invoke','UNKNOWN','{}','unknown-request')")
            connection.execute("INSERT INTO authority_generation_isolation VALUES('unknown-director','origin','project','workspace','book','unknown-request',%s)",[Jsonb(isolation)])
            output = {"complete":"retained generation"}
            connection.execute("INSERT INTO authority_asset_version VALUES('frozen','frozen-hash',%s),('generated','generated-hash',%s)",[
                Jsonb({"contract":{"contract_version":"world-preparation-source.v3","request":request}}),
                Jsonb({"contract":{"source":refs["frozen"],"evidence":{"external_receipt_ref":"complete-generation"},"output":output}})])
            connection.execute("INSERT INTO authority_operation_output_asset VALUES('origin','frozen'),('origin','generated')")
            connection.execute("INSERT INTO authority_external_effect VALUES('origin','complete-generation','project','model.invoke','SUCCEEDED','{\"stage\":\"world_candidates.generate\"}','complete-request')")
            evidence = {"result":output}
            connection.execute("INSERT INTO authority_external_effect_dispatch VALUES('dispatch','complete-generation','SUCCEEDED',%s)",[Jsonb(evidence)])
            connection.execute("INSERT INTO authority_external_receipt VALUES('dispatch','VERIFIED',%s)",[Jsonb({"evidence":evidence})])
            connection.execute("INSERT INTO authority_book_production VALUES('book-run','project','workspace','book','CHAPTER_PLAN_REQUIRED',0,'input',0,'formation:production')")
            generation = {"book_id":"book","generator_operation_name":"chapter_plan.generate","logical_key":"chapter:1","planning_scope":"CHAPTER","input_snapshot":[],"input_snapshot_hash":"input-hash","repair_number":0}
            def permitted():
                return connection.execute("SELECT authority_generation_continuation_permitted('correction','child',%s)",[Jsonb(generation)]).fetchone()[0]
            assert permitted()
            for mutation in [
                "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='registered'",
                "UPDATE authority_story_planning_runtime_continuation SET successor_command='{}' WHERE continuation_id='parent'",
                "UPDATE authority_asset_version SET content_hash='drift' WHERE asset_version_id='generated'",
                "UPDATE authority_external_receipt SET payload='{}'",
                "UPDATE authority_external_effect SET status='UNKNOWN' WHERE external_effect_id='complete-generation'",
                "INSERT INTO authority_external_effect(operation_id) VALUES('source')",
                "INSERT INTO authority_budget_reservation VALUES('source')",
                "INSERT INTO authority_lease_acquisition VALUES('attempt','HELD')",
                "UPDATE authority_book_production SET current_chapter=1",
                "INSERT INTO authority_story_creation_cancellation VALUES('project','formation')",
            ]:
                connection.execute("SAVEPOINT guard")
                connection.execute(mutation)
                assert not permitted(), mutation
                connection.execute("ROLLBACK TO SAVEPOINT guard")
                connection.execute("RELEASE SAVEPOINT guard")
            # WHY: The direct legacy isolation join must not turn a marker into an authorization bypass.
            connection.execute("UPDATE authority_generation_isolation SET operation_id='source'")
            connection.execute("UPDATE authority_external_effect SET operation_id='source' WHERE external_effect_id='unknown-director'")
            assert not permitted()
            assert connection.execute("SELECT status FROM authority_external_effect WHERE external_effect_id='unknown-director'").fetchone()==("UNKNOWN",)
        finally:
            connection.rollback()


def test_world_source_correction_upgrade_and_restore_preserve_observation_constraints(tmp_path):
    with disposable_database_at_migration(DATABASE_URL,prefix="world_source_upgrade",target_migration_id="20261014_0207_world_revalidation_capacity") as url:
        with psycopg.connect(url) as connection:
            original = connection.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='authority_story_planning_runtime_continuation'::regclass AND conname='authority_story_planning_runtime_continuation_chain_depth_check'").fetchone()[0]
        assert run_migrations(url)["ok"]
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='authority_story_planning_runtime_continuation'::regclass AND conname='authority_story_planning_runtime_continuation_chain_depth_check'").fetchone()==(original,)
            assert original=="CHECK ((chain_depth > 0))"
        with restored_generation_backup(url,backup_root=tmp_path/"world-source-restore") as restored:
            assert run_migrations(restored)["ok"]
            with psycopg.connect(restored) as connection:
                assert connection.execute("SELECT max(migration_id) FROM nf_schema_migrations").fetchone()==(MIGRATIONS[-1].migration_id,)
