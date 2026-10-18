from __future__ import annotations

import psycopg
import pytest
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import MIGRATIONS
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import disposable_database_at_migration

MAIN_HEAD = "20261007_0159_planning_dead_letter_result_recovery"
INTEGRATION_HEADS = tuple(m.migration_id for m in MIGRATIONS if m.migration_id > MAIN_HEAD)


def _generation(connection, *, operation_id, source=None, runtime=None, project="project"):
    connection.execute(
        """INSERT INTO authority_story_planning_generation
           (generation_id,operation_id,project_id,workspace_id,book_id,generator_operation_name,
            planning_scope,logical_key,input_snapshot,input_snapshot_hash,status,repair_number,
            repair_of_operation_id,repair_result_asset_version_id,runtime_continuation_id,repair_reason)
           VALUES (%s,%s,%s,'workspace','book','world.design.generate','FOUNDATION','world:1',
                   '[]'::jsonb,'sha256:frozen','ADMITTED',%s,%s,%s,%s,%s)""",
        [operation_id, operation_id, project, 1 if source else 0, source,
         "retained-result" if source else None, runtime, "known-raw-diagnosis" if source else None],
    )



def _capacity_cause_probe(connection):
    connection.execute("CREATE TRIGGER native_capacity_cause BEFORE UPDATE OR DELETE ON authority_story_planning_runtime_continuation FOR EACH ROW EXECUTE FUNCTION public.authority_planning_runtime_continuation_guard()")
    connection.execute("INSERT INTO authority_operation VALUES ('repair-origin','project','SUCCEEDED','{}',NULL,'story_planning.generate')")
    _generation(connection, operation_id="repair-origin")
    connection.execute("UPDATE authority_story_planning_generation SET candidate_asset_version_id='approved-repair' WHERE operation_id='repair-origin'")
    connection.execute("INSERT INTO authority_operation_output_asset VALUES ('repair-origin','approved-repair')")
    for name, effect_status, cause in (("capacity-good", None, "repair-origin"), ("capacity-unknown", "UNKNOWN", "repair-origin"), ("capacity-foreign", None, "foreign-origin")):
        source = {"repair_of_candidate_id": "approved-repair"}
        successor = {"runtime_continuation_id": name}
        connection.execute("INSERT INTO authority_operation VALUES (%s,'project','DEAD_LETTER',%s,NULL,'story_planning.generate'),(%s,'project','ADMITTED',%s,%s,'story_planning.generate')", [name, Jsonb({"payload": source}), name + ":successor", Jsonb({"payload": successor}), cause])
        connection.execute("INSERT INTO authority_attempt VALUES (%s,%s,1,'FAILED_FINAL',%s,'{}')", [name, name, Jsonb({"error_code": "PLANNING_PROVIDER_CONTEXT_BUDGET_EXCEEDED"})])
        if effect_status:
            connection.execute("INSERT INTO authority_external_effect VALUES (%s,%s,%s,'{}')", [name, name, effect_status])
        connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES (%s,%s,'registration','project','workspace','book',%s,%s,%s,NULL,'{}')", [name, name, Jsonb(source), Jsonb(successor), Jsonb({"planning_capacity": {"version": "planning-capacity-allocation.v1"}})])
        if name == "capacity-good":
            connection.execute("UPDATE authority_story_planning_runtime_continuation SET successor_operation_id=%s WHERE continuation_id=%s", [name + ":successor", name])
        else:
            with pytest.raises(psycopg.errors.CheckViolation, match="PLANNING_RUNTIME_CONTINUATION_SUCCESSOR_INVALID"):
                with connection.transaction():
                    connection.execute("UPDATE authority_story_planning_runtime_continuation SET successor_operation_id=%s WHERE continuation_id=%s", [name + ":successor", name])
        assert connection.execute("SELECT status FROM authority_operation WHERE operation_id=%s", [name]).fetchone() == ("DEAD_LETTER",)



def _optional_world_probe(connection):
    policy = {"policy_snapshot": {"policy": {"execution_templates": [{
        "book_id": "book", "mode": "CREATIVE_VALIDATION",
        "version": "creative-execution-template.v3", "world_future_preparation": "OPTIONAL",
        "require_literary_qualification": False,
    }]}}}
    content = {"contract": {"book_id": "book", "optional_preparation": {
        "contract_version": "world-optional-preparation.v1", "status": "NOT_RUN",
        "policy_admission": policy,
    }, "world_plan": {"disposition": "DEFER", "selected_candidate_id": "",
                      "preparation_schedule": []}, "fact_mutation_allowed": False}}
    source = {"world_preparation_request": {"book_id": "book"}}
    successor = {**source, "runtime_continuation_id": "optional-runtime"}
    connection.execute("INSERT INTO authority_operation VALUES ('optional-source','project','FAILED_FINAL',%s,NULL,'story_planning.generate'),('optional-child','project','ADMITTED',%s,'optional-source','story_planning.generate'),('optional-registration','project','SUCCEEDED','{}',NULL,'story_planning.world_preparation.defer')", [Jsonb({"payload": source}), Jsonb({"payload": successor})])
    _generation(connection, operation_id="optional-source")
    connection.execute("INSERT INTO authority_attempt VALUES ('optional-attempt','optional-source',1,'FAILED_FINAL','{}',%s)", [Jsonb({"error_code": "WORLD_PREPARATION_RESULT_INVALID"})])
    for stage in ("world_candidates.generate", "world_candidates.evaluate"):
        connection.execute("INSERT INTO authority_external_effect VALUES (%s,'optional-source','SUCCEEDED',%s)", [stage, Jsonb({"stage": stage})])
        connection.execute("INSERT INTO authority_budget_reservation VALUES ('optional-source','SETTLED')")
    connection.execute("INSERT INTO authority_asset VALUES ('deferred-action','project','narrative_governance_action')")
    connection.execute("INSERT INTO authority_asset_version VALUES ('deferred-version','deferred-action','sha256:deferred',%s)", [Jsonb(content)])
    connection.execute("INSERT INTO authority_operation_output_asset VALUES ('optional-registration','deferred-version')")
    decision = {"policy_admission": policy, "world_optional_action": {
        "asset_version_id": "deferred-version", "content_hash": "sha256:deferred"}}
    connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES ('optional-runtime','optional-source','optional-registration','project','workspace','book',%s,%s,'{}',NULL,%s)", [Jsonb(source), Jsonb(successor), Jsonb(decision)])
    for terminal, diagnosis in (("FAILED_FINAL", "WORLD_PREPARATION_RESULT_INVALID"),
                                ("DEAD_LETTER", "WORLD_PREPARATION_RESULT_INVALID"),
                                ("FAILED_FINAL", "WORLD_PREPARATION_BLOCKED")):
        connection.execute("SAVEPOINT optional_probe")
        connection.execute("UPDATE authority_operation SET status=%s WHERE operation_id='optional-source'", [terminal])
        connection.execute("UPDATE authority_attempt SET error=%s WHERE attempt_id='optional-attempt'", [Jsonb({"error_code": diagnosis})])
        _generation(connection, operation_id="optional-child", runtime="optional-runtime")
        assert connection.execute("SELECT repair_number,runtime_continuation_id FROM authority_story_planning_generation WHERE operation_id='optional-child'").fetchone() == (0, "optional-runtime")
        assert connection.execute("SELECT status FROM authority_operation WHERE operation_id='optional-source'").fetchone() == (terminal,)
        connection.execute("ROLLBACK TO SAVEPOINT optional_probe")
        connection.execute("RELEASE SAVEPOINT optional_probe")
    invalid = (
        "UPDATE authority_operation SET status='FAILED_RETRYABLE' WHERE operation_id='optional-source'",
        "UPDATE authority_attempt SET status='FAILED_RETRYABLE' WHERE attempt_id='optional-attempt'",
        "UPDATE authority_attempt SET error='{}' WHERE attempt_id='optional-attempt'",
        "UPDATE authority_external_effect SET status='UNKNOWN' WHERE external_effect_id='world_candidates.generate'",
        "UPDATE authority_budget_reservation SET status='RESERVED' WHERE operation_id='optional-source'",
        "INSERT INTO authority_lease_acquisition VALUES ('optional-attempt','HELD')",
        "UPDATE authority_asset_version SET content_hash='sha256:forged' WHERE asset_version_id='deferred-version'",
        "UPDATE authority_asset_version SET content=jsonb_set(content,'{contract,world_plan,disposition}','\"BLOCKED\"') WHERE asset_version_id='deferred-version'",
        "DELETE FROM authority_operation_output_asset WHERE operation_id='optional-registration'",
        "UPDATE authority_asset_version SET content=jsonb_set(content,'{contract,optional_preparation,policy_admission}','{}') WHERE asset_version_id='deferred-version'",
        "UPDATE authority_story_planning_generation SET candidate_asset_version_id='unapproved' WHERE operation_id='optional-source'",
        "UPDATE authority_story_planning_generation SET input_snapshot_hash='sha256:foreign' WHERE operation_id='optional-source'",
        "UPDATE authority_operation SET causation_operation_id='foreign' WHERE operation_id='optional-child'",
        "UPDATE authority_story_planning_generation SET book_id='foreign' WHERE operation_id='optional-source'",
        "UPDATE authority_story_planning_generation SET repair_number=1 WHERE operation_id='optional-source'",
    )
    for mutation in invalid:
        connection.execute("SAVEPOINT optional_probe")
        connection.execute(mutation)
        try:
            with connection.transaction():
                _generation(connection, operation_id="optional-child", runtime="optional-runtime")
        except psycopg.errors.CheckViolation as error:
            assert "PLANNING_RUNTIME_CONTINUATION_GENERATION_INVALID" in str(error)
        else:
            pytest.fail(f"optional guard admitted forbidden change: {mutation}")
        assert connection.execute("SELECT count(*) FROM authority_story_planning_generation WHERE operation_id='optional-child'").fetchone() == (0,)
        connection.execute("ROLLBACK TO SAVEPOINT optional_probe")
        connection.execute("RELEASE SAVEPOINT optional_probe")
    assert connection.execute("SELECT status FROM authority_operation WHERE operation_id='optional-source'").fetchone() == ("FAILED_FINAL",)
    assert connection.execute("SELECT repair_number FROM authority_story_planning_generation WHERE operation_id='optional-source'").fetchone() == (0,)

@pytest.mark.parametrize("head", (MAIN_HEAD, *INTEGRATION_HEADS))
def test_every_forward_head_retains_dead_letter_known_result_and_exact_causation(head):
    with disposable_database_at_migration(DATABASE_URL, prefix="creative_guard", target_migration_id=head) as url:
        with psycopg.connect(url) as connection:
            connection.execute("CREATE TEMP TABLE authority_story_planning_generation (LIKE public.authority_story_planning_generation INCLUDING DEFAULTS)")
            connection.execute("ALTER TABLE authority_story_planning_generation ADD COLUMN IF NOT EXISTS runtime_continuation_id text")
            connection.execute("CREATE TEMP TABLE authority_operation (operation_id text, project_id text, status text, command_payload jsonb, causation_operation_id text, definition_name text, workspace_id text DEFAULT 'workspace', actor_id text DEFAULT 'owner', definition_version text, definition_snapshot jsonb DEFAULT '{}', input_asset_snapshot jsonb DEFAULT '[]')")
            connection.execute("CREATE TEMP TABLE authority_operation_output_asset (operation_id text,asset_version_id text,output_key text DEFAULT 'fixture', content_hash text, role text DEFAULT 'primary')")
            connection.execute("CREATE TEMP TABLE authority_external_effect (external_effect_id text,operation_id text,status text,request_payload jsonb,request_hash text DEFAULT 'sha256:frozen',project_id text DEFAULT 'project',effect_type text DEFAULT 'model.invoke', provider text DEFAULT 'scripted_provider_v2', model_id text DEFAULT 'gpt-test')")
            connection.execute("CREATE TEMP TABLE authority_story_planning_runtime_continuation (continuation_id text,source_operation_id text,registered_by_operation_id text,project_id text,workspace_id text,book_id text,source_command jsonb,successor_command jsonb,target_runtime jsonb,successor_operation_id text,decision_evidence jsonb, chain_depth int DEFAULT 1, source_release_sha text, target_release_sha text)")
            connection.execute("CREATE TEMP TABLE authority_attempt (attempt_id text,operation_id text,attempt_number integer,status text,result jsonb,error jsonb)")
            connection.execute("CREATE TEMP TABLE authority_budget_reservation (operation_id text,status text,external_effect_id text)")
            connection.execute("CREATE TEMP TABLE authority_lease_acquisition (attempt_id text,status text)")
            connection.execute("CREATE TEMP TABLE authority_asset (asset_id text,project_id text,asset_type text)")
            connection.execute("CREATE TEMP TABLE authority_asset_version (asset_version_id text,asset_id text,content_hash text,content jsonb,lifecycle text DEFAULT 'ACTIVE',eligibility text DEFAULT 'ELIGIBLE',governance text DEFAULT 'CLEAR')")
            connection.execute("CREATE TRIGGER integration_guard BEFORE INSERT OR UPDATE ON authority_story_planning_generation FOR EACH ROW EXECUTE FUNCTION public.authority_planning_result_repair_guard()")
            connection.execute("INSERT INTO authority_operation VALUES ('source','project','DEAD_LETTER','{}',NULL,'story_planning.generate'),('successor','project','ADMITTED','{}','source','story_planning.generate')")
            _generation(connection, operation_id="source")
            connection.execute("INSERT INTO authority_operation_output_asset VALUES ('source','retained-result')")
            connection.execute("INSERT INTO authority_external_effect VALUES ('known','source','SUCCEEDED','{}')")
            _generation(connection, operation_id="successor", source="source")
            assert connection.execute("SELECT repair_of_operation_id,repair_number FROM authority_story_planning_generation WHERE operation_id='successor'").fetchone() == ("source", 1)
            for effect_status in ("UNKNOWN", "WAITING_RESULT"):
                with connection.transaction():
                    connection.execute("INSERT INTO authority_external_effect VALUES ('unresolved','source',%s,'{}')", [effect_status])
                    with pytest.raises(psycopg.errors.CheckViolation, match="PLANNING_RESULT_REPAIR_SOURCE_INVALID"):
                        with connection.transaction():
                            _generation(connection, operation_id="unresolved-repair", source="source")
                    connection.execute("DELETE FROM authority_external_effect WHERE external_effect_id='unresolved'")
            identities = ("cross-scope", "forged-cause", "forged-runtime") if head >= "20261007_0161" else ("cross-scope", "forged-cause")
            for identity in identities:
                connection.execute("INSERT INTO authority_operation VALUES (%s,'project','ADMITTED','{}',%s,'story_planning.generate')", [identity, "source" if identity != "forged-cause" else "foreign"])
                error = "PLANNING_RUNTIME_CONTINUATION_GENERATION_INVALID" if identity == "forged-runtime" else "PLANNING_RESULT_REPAIR_SOURCE_INVALID"
                with pytest.raises(psycopg.errors.CheckViolation, match=error):
                    with connection.transaction():
                        _generation(connection, operation_id=identity, source="source",
                            runtime="unregistered-continuation" if identity == "forged-runtime" else None,
                            project="foreign" if identity == "cross-scope" else "project")
            with pytest.raises(psycopg.errors.CheckViolation, match="PLANNING_RESULT_REPAIR_IDENTITY_IMMUTABLE"):
                with connection.transaction():
                    connection.execute("UPDATE authority_story_planning_generation SET repair_result_asset_version_id='substitute' WHERE operation_id='successor'")
            assert connection.execute("SELECT status FROM authority_operation WHERE operation_id='source'").fetchone() == ("DEAD_LETTER",)
            definition = connection.execute("SELECT pg_get_functiondef('authority_planning_runtime_continuation_guard()'::regprocedure)").fetchone()[0]
            assert "planning-capacity-allocation.v1" in definition
            assert "repair_of_candidate_id" in definition
            assert "PLANNING_RUNTIME_CONTINUATION_SUCCESSOR_INVALID" in definition
            _capacity_cause_probe(connection)
            if head >= "20261007_0163":
                _optional_world_probe(connection)
