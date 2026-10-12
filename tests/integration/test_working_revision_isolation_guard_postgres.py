import pytest
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated


@pytest.mark.parametrize("stage", ["chapter.review.evaluate", "chapter.revision.apply", "chapter.revision.review"])
@pytest.mark.parametrize("fault", [None, "foreign-book", "source-hash", "root-contract", "cancelled", "lease", "output"])
def test_working_revision_isolation_guard_requires_owned_stopped_model_stage(stage, fault):
    ensure_migrated()
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        tables = ("authority_external_effect", "authority_operation", "authority_story_planning_generation",
            "authority_asset_version", "authority_asset", "authority_saga_step", "authority_saga",
            "authority_book_production", "authority_book_chapter_request", "authority_story_creation_cancellation",
            "authority_lease_acquisition", "authority_attempt", "authority_operation_output_asset",
            "authority_generation_isolation")
        for table in tables:
            cursor.execute(sql.SQL("CREATE TEMP TABLE {} AS SELECT * FROM public.{} WITH NO DATA").format(
                sql.Identifier(table), sql.Identifier(table)))
        cursor.execute("""CREATE TRIGGER fixture_guard BEFORE INSERT ON authority_generation_isolation
            FOR EACH ROW EXECUTE FUNCTION public.authority_generation_isolation_guard()""")
        command = {"book_id": "book", "chapter": 3, "preparation_report": {"working_revision": {
            "contract_version": "chapter-working-revision.v1", "book_run_id": "run", "source_asset_version_id": "source",
            "source_content_hash": "source-hash", "source_inputs": {"draft": {"asset_version_id": "source", "content_hash": "source-hash"}}}}}
        cursor.execute("""INSERT INTO authority_operation(operation_id,project_id,workspace_id,actor_id,status,
            definition_name,definition_version,definition_snapshot,command_payload,input_asset_snapshot)
            VALUES('root','project','workspace','operator','WAITING_CHILDREN','chapter.slice.run',%s,%s,%s,%s)""",
            ["wrong" if fault == "root-contract" else "3.10.0-working-revision.v1",
             Jsonb({"policy": {"working_revision_contract": "chapter-working-revision.v1"}}), Jsonb(command),
             Jsonb([command["preparation_report"]["working_revision"]["source_inputs"]["draft"]])])
        cursor.execute("""INSERT INTO authority_operation(operation_id,project_id,workspace_id,actor_id,status,
            definition_name,definition_version,root_operation_id,saga_id,command_payload,definition_snapshot)
            VALUES('child','project','workspace','operator','FAILED_FINAL',%s,'3.10.0','root','saga',%s,'{}')""",
            [stage, Jsonb({"book_id": "book"})])
        cursor.execute("INSERT INTO authority_saga(saga_id,root_operation_id) VALUES('saga','root')")
        cursor.execute("INSERT INTO authority_saga_step(saga_id,operation_id) VALUES('saga','child')")
        cursor.execute("""INSERT INTO authority_book_production(book_run_id,project_id,workspace_id,book_id,state,
            accepted_through_chapter,current_chapter,stable_idempotency_key)
            VALUES('run','project','workspace',%s,'READY',0,3,'formation:production')""",
            ["other-book" if fault == "foreign-book" else "book"])
        cursor.execute("INSERT INTO authority_asset(asset_id,project_id) VALUES('materialization-owner','project'),('source-owner','project')")
        materialization = {"contract": {"tool_permissions": {"default": "DENY", "allowed": ["model.provider.invoke"]}}}
        cursor.execute("""INSERT INTO authority_asset_version(asset_version_id,asset_id,content,content_hash)
            VALUES('materialization','materialization-owner',%s,'materialization-hash'),('source','source-owner','{}',%s)""",
            [Jsonb(materialization), "changed" if fault == "source-hash" else "source-hash"])
        request = {"_production_execution": {"book_id": "book", "capability_runtime": {
            "materialization_asset_version_id": "materialization", "materialization_content_hash": "materialization-hash"}}}
        cursor.execute("""INSERT INTO authority_external_effect(external_effect_id,operation_id,project_id,effect_type,status,
            request_hash,request_payload) VALUES('effect','child','project','model.invoke','UNKNOWN','request-hash',%s)""", [Jsonb(request)])
        if fault == "cancelled":
            cursor.execute("INSERT INTO authority_story_creation_cancellation(project_id,formation_run_id) VALUES('project','formation')")
        if fault == "lease":
            cursor.execute("INSERT INTO authority_attempt(attempt_id,operation_id) VALUES('attempt','child')")
            cursor.execute("INSERT INTO authority_lease_acquisition(attempt_id,status) VALUES('attempt','HELD')")
        if fault == "output":
            cursor.execute("INSERT INTO authority_operation_output_asset(operation_id,role) VALUES('child','primary')")
        proof = {"contract_version": "pure-generation-isolation.v1", "actor_id": "operator",
            "continuation_id": "chapter-generation-successor:child", "remote_outcome": "UNKNOWN", "usage": "UNKNOWN",
            "business_commit_right": "REVOKED", "activation_right": "REVOKED"}
        def insert():
            cursor.execute("""INSERT INTO authority_generation_isolation(isolation_id,external_effect_id,operation_id,
                project_id,workspace_id,book_id,request_hash,materialization_asset_version_id,proof)
                VALUES('isolation','effect','child','project','workspace','book','request-hash','materialization',%s)""", [Jsonb(proof)])
        if fault:
            with pytest.raises(psycopg.errors.RaiseException, match="GENERATION_ISOLATION_SCOPE_UNSAFE"):
                insert()
            connection.rollback()
        else:
            insert()
            cursor.execute("SELECT status FROM authority_external_effect WHERE external_effect_id='effect'")
            assert cursor.fetchone() == ("UNKNOWN",)
            cursor.execute("SELECT status FROM authority_operation WHERE operation_id='child'")
            assert cursor.fetchone() == ("FAILED_FINAL",)
            connection.rollback()
