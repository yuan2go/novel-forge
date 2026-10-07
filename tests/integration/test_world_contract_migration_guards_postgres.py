from __future__ import annotations


import psycopg
import pytest
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations import MIGRATIONS
from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.migration_window_postgres_support import disposable_database_at_migration

HEADS = tuple(m.migration_id for m in MIGRATIONS if m.migration_id >= "20261007_0169")


def _schema(connection):
    connection.execute("CREATE TEMP TABLE authority_operation(operation_id text,project_id text,workspace_id text,actor_id text,status text,command_payload jsonb,causation_operation_id text,definition_name text,definition_version text)")
    connection.execute("CREATE TEMP TABLE authority_story_planning_generation(LIKE public.authority_story_planning_generation INCLUDING DEFAULTS)")
    connection.execute("CREATE TEMP TABLE authority_story_planning_runtime_continuation(continuation_id text,source_operation_id text,registered_by_operation_id text,project_id text,workspace_id text,book_id text,source_command jsonb,successor_command jsonb,target_runtime jsonb,successor_operation_id text,decision_evidence jsonb,chain_depth int)")
    connection.execute("CREATE TEMP TABLE authority_attempt(attempt_id text,operation_id text,attempt_number int,status text,result jsonb,error jsonb)")
    connection.execute("CREATE TEMP TABLE authority_operation_output_asset(operation_id text,asset_version_id text)")
    connection.execute("CREATE TEMP TABLE authority_asset_version(asset_version_id text,content jsonb)")
    connection.execute("""CREATE TEMP TABLE authority_external_effect(operation_id text,status text,request_payload jsonb DEFAULT '{"stage":"world_candidates.generate"}')""")
    connection.execute("CREATE TEMP TABLE authority_budget_reservation(operation_id text,status text)")
    connection.execute("CREATE TEMP TABLE authority_lease_acquisition(attempt_id text,status text)")
    connection.execute("CREATE TEMP TABLE authority_book_production(project_id text,book_id text,state text,stable_idempotency_key text)")
    connection.execute("CREATE TEMP TABLE authority_story_creation_cancellation(project_id text,formation_run_id text)")


def _seed(connection):
    source = {"book_id": "book", "logical_key": "chapter:1", "generator_operation_name": "chapter_plan.generate", "repair_number": 0, "execution_contract_version": "1.19.0", "world_preparation_request": {"book_run_id": "run", "input_snapshot_id": "snapshot", "accepted_through_chapter": 0, "story_state_version_id": "", "canon_version_id": ""}}
    child = {**source, "execution_contract_version": "1.20.0", "repair_reason": "WORLD_AGENCY_CONTRACT_SUCCESSOR", "runtime_continuation_id": "runtime"}
    for identity, status, payload, version, cause in [
        ("source", "FAILED_FINAL", source, "1.19.0", None),
        ("child", "ADMITTED", child, "1.20.0", "source"),
        ("registration", "SUCCEEDED", {}, "2.0.0", None),
    ]:
        connection.execute("INSERT INTO authority_operation VALUES(%s,'project','workspace','owner',%s,%s,%s,%s,%s)", [identity, status, Jsonb({"payload": payload}), cause, "story_planning.runtime_continuation.register" if identity == "registration" else "story_planning.generate", version])
    connection.execute("INSERT INTO authority_story_planning_generation(generation_id,operation_id,project_id,workspace_id,book_id,generator_operation_name,planning_scope,logical_key,input_snapshot,input_snapshot_hash,status,repair_number) VALUES('source','source','project','workspace','book','chapter_plan.generate','CHAPTER','chapter:1','[]','sha256:frozen','FAILED_FINAL',0)")
    connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES('runtime','source','registration','project','workspace','book',%s,%s,'{}',NULL,%s,1)", [Jsonb(source), Jsonb(child), Jsonb({"changed_contract": "world-agency.v2"})])
    connection.execute("INSERT INTO authority_attempt VALUES('attempt','source',1,'FAILED_FINAL',%s,'{}')", [Jsonb({"error_code": "WORLD_PREPARATION_RESULT_INVALID"})])
    connection.execute("INSERT INTO authority_operation_output_asset VALUES('source','blocked-action')")
    action = {"contract": {"world_plan": {"disposition": "BLOCKED", "candidate_futures": [{"rejection": {"code": "WORLD_CHARACTER_DECISION_BASIS_REQUIRED"}}], "rejected_paths": []}}}
    connection.execute("INSERT INTO authority_asset_version VALUES('blocked-action',%s)", [Jsonb(action)])
    connection.execute("INSERT INTO authority_external_effect(operation_id,status) VALUES('source','SUCCEEDED')")
    connection.execute("INSERT INTO authority_budget_reservation VALUES('source','SETTLED')")
    return {
        "project_id": "project", "workspace_id": "workspace", "book_id": "book",
        "generator_operation_name": "chapter_plan.generate", "logical_key": "chapter:1", "planning_scope": "CHAPTER",
        "input_snapshot": [], "input_snapshot_hash": "sha256:frozen", "repair_number": 0,
        "runtime_continuation_id": "runtime", "repair_reason": "WORLD_AGENCY_CONTRACT_SUCCESSOR",
    }


def _admitted(connection, generation):
    return connection.execute("SELECT public.authority_world_contract_continuation_permitted('runtime','child',%s)", [Jsonb(generation)]).fetchone()[0]


@pytest.mark.parametrize("head", HEADS)
def test_world_contract_successor_preserves_scope_counters_and_lineage_guards(head):
    with disposable_database_at_migration(DATABASE_URL, prefix="world_contract_guard", target_migration_id=head) as url:
        with psycopg.connect(url) as connection:
            _schema(connection)
            generation = _seed(connection)
            assert _admitted(connection, generation)
            connection.execute("UPDATE authority_operation SET status='RUNNING' WHERE operation_id='child'")
            connection.execute("INSERT INTO authority_attempt VALUES('current-attempt','child',1,'RUNNING','{}','{}')")
            connection.execute("INSERT INTO authority_lease_acquisition VALUES('current-attempt','HELD')")
            assert _admitted(connection, generation)
            connection.execute("SAVEPOINT current_attempt_guard")
            connection.execute("UPDATE authority_attempt SET status='FAILED_FINAL' WHERE attempt_id='current-attempt'")
            assert not _admitted(connection, generation)
            connection.execute("ROLLBACK TO SAVEPOINT current_attempt_guard")
            connection.execute("RELEASE SAVEPOINT current_attempt_guard")
            connection.execute("SAVEPOINT stale_attempt_guard")
            connection.execute("INSERT INTO authority_attempt VALUES('newer-attempt','child',2,'FAILED_FINAL','{}','{}')")
            assert not _admitted(connection, generation)
            connection.execute("ROLLBACK TO SAVEPOINT stale_attempt_guard")
            connection.execute("RELEASE SAVEPOINT stale_attempt_guard")
            for field, value in [("project_id", "foreign"), ("workspace_id", "foreign"), ("book_id", "foreign"), ("logical_key", "foreign"), ("input_snapshot_hash", "sha256:drift"), ("input_snapshot", ["drift"]), ("repair_number", 1), ("repair_of_operation_id", "foreign"), ("candidate_asset_version_id", "candidate")]:
                assert not _admitted(connection, {**generation, field: value})
            for mutation in [
                "UPDATE authority_operation SET workspace_id='foreign' WHERE operation_id='source'",
                "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='child'",
                "UPDATE authority_operation SET status='FAILED_RETRYABLE' WHERE operation_id='source'",
                "UPDATE authority_operation SET definition_version='1.19.0' WHERE operation_id='child'",
                "UPDATE authority_operation SET status='ADMITTED' WHERE operation_id='registration'",
                "UPDATE authority_operation SET definition_version='1.0.0' WHERE operation_id='registration'",
                "UPDATE authority_operation SET actor_id='foreign' WHERE operation_id='registration'",
                "UPDATE authority_operation SET project_id='foreign' WHERE operation_id='registration'",
                "UPDATE authority_operation SET command_payload=jsonb_set(command_payload,'{payload,execution_contract_version}','\"1.19.0\"') WHERE operation_id='child'",
                "UPDATE authority_attempt SET status='UNKNOWN'",
                "UPDATE authority_attempt SET result='{}'",
                "UPDATE authority_external_effect SET status='UNKNOWN'",
                "DELETE FROM authority_external_effect",
                "UPDATE authority_external_effect SET status='FAILED_FINAL'",
                "UPDATE authority_external_effect SET request_payload='{}'",
                "UPDATE authority_operation SET command_payload=command_payload #- '{payload,world_preparation_request}' WHERE operation_id='child'",
                "UPDATE authority_operation SET command_payload=jsonb_set(command_payload,'{payload,world_preparation_request}','null') WHERE operation_id='source'",
                "UPDATE authority_budget_reservation SET status='HELD'",
                "INSERT INTO authority_lease_acquisition VALUES('attempt','HELD')",
                "INSERT INTO authority_book_production VALUES('project','book','ABORTED','formation:production')",
                "INSERT INTO authority_operation VALUES('failed-successor','project','workspace','owner','FAILED_FINAL','{}','source','story_planning.generate','1.20.0'); INSERT INTO authority_budget_reservation VALUES('failed-successor','HELD')",
                "INSERT INTO authority_operation VALUES('failed-successor','project','workspace','owner','FAILED_FINAL','{}','source','story_planning.generate','1.20.0'); INSERT INTO authority_attempt VALUES('successor-attempt','failed-successor',1,'FAILED_FINAL','{}','{}'); INSERT INTO authority_lease_acquisition VALUES('successor-attempt','HELD')",
                "INSERT INTO authority_operation VALUES('ancestor','project','workspace','owner','FAILED_FINAL','{}',NULL,'story_planning.generate','1.19.0'); UPDATE authority_operation SET causation_operation_id='ancestor' WHERE operation_id='source'; INSERT INTO authority_budget_reservation VALUES('ancestor','HELD')",
            ]:
                connection.execute("SAVEPOINT guard_probe")
                connection.execute(mutation)
                assert not _admitted(connection, generation), mutation
                connection.execute("ROLLBACK TO SAVEPOINT guard_probe")
                connection.execute("RELEASE SAVEPOINT guard_probe")
            assert connection.execute("SELECT status FROM authority_operation WHERE operation_id='source'").fetchone() == ("FAILED_FINAL",)
            assert connection.execute("SELECT repair_number FROM authority_story_planning_generation WHERE operation_id='source'").fetchone() == (0,)


def _mode(connection, generation, mode):
    successor_reason = 'WORLD_HOST_REVALIDATION_SUCCESSOR' if mode == 'host' else 'WORLD_HOST_PROJECTION_SUCCESSOR'
    source = connection.execute("SELECT command_payload->'payload' FROM authority_operation WHERE operation_id='source'").fetchone()[0]
    source = {**source, 'execution_contract_version': '1.20.0', **({'repair_reason': 'WORLD_HOST_REVALIDATION_SUCCESSOR'} if mode == 'projection' else {'repair_reason': 'WORLD_AGENCY_CONTRACT_SUCCESSOR'})}
    child = {**source, 'runtime_continuation_id': 'runtime', 'repair_reason': successor_reason}
    connection.execute("UPDATE authority_operation SET definition_version='1.20.0',command_payload=%s WHERE operation_id='source'", [Jsonb({'payload': source})])
    connection.execute("UPDATE authority_operation SET command_payload=%s WHERE operation_id='child'", [Jsonb({'payload': child})])
    proof = {'contract_version': 'world-host-revalidation.v1', 'source_operation_id': 'source', 'plan_digest': 'sha256:' + 'a' * 64}
    target = {'pack_snapshot': {'snapshot_hash': 'sha256:' + 'b' * 64}, 'world_host_revalidation': proof}
    decision = {'host_revalidation': 'world-host-revalidation.v1'}
    if mode == 'projection':
        decision['projection_revalidation'] = 'world-direction-projection.v1'
        connection.execute("UPDATE authority_story_planning_generation SET repair_reason='WORLD_HOST_REVALIDATION_SUCCESSOR' WHERE operation_id='source'")
        connection.execute("UPDATE authority_attempt SET result=%s", [Jsonb({'error_code': 'PROGRAMMING_BUG', 'error_message': "'frozen_source'"})])
        connection.execute("DELETE FROM authority_external_effect")
        connection.execute("DELETE FROM authority_budget_reservation")
    else:
        action = {'contract': {'world_plan': {'disposition': 'BLOCKED', 'rejected_paths': [{'rejection': {'code': 'WORLD_PERCEPTION_ACTOR_INVALID'}}]}}}
        connection.execute("UPDATE authority_asset_version SET content=%s", [Jsonb(action)])
    depth = 2 if mode == 'host' else 3
    connection.execute("UPDATE authority_story_planning_runtime_continuation SET source_command=%s,successor_command=%s,target_runtime=%s,decision_evidence=%s,chain_depth=%s", [Jsonb(source), Jsonb(child), Jsonb(target), Jsonb(decision), depth])
    connection.execute("INSERT INTO authority_story_planning_runtime_continuation VALUES('parent','earlier','registration','project','workspace','book','{}','{}',%s,'source','{}',%s)", [Jsonb(target), depth - 1])
    return {**generation, 'repair_reason': successor_reason}


@pytest.mark.parametrize('head', HEADS)
@pytest.mark.parametrize('mode', ['host', 'projection'])
def test_world_host_and_zero_dispatch_projection_permissions_start_at_exact_head(head, mode):
    with disposable_database_at_migration(DATABASE_URL, prefix='world_mode_guard', target_migration_id=head) as url:
        with psycopg.connect(url) as connection:
            _schema(connection)
            generation = _mode(connection, _seed(connection), mode)
            introduced = head >= ('20261007_0170' if mode == 'host' else '20261007_0171')
            assert _admitted(connection, generation) is introduced
            if not introduced:
                return
            for mutation in [
                "UPDATE authority_story_planning_runtime_continuation SET chain_depth=4 WHERE continuation_id='runtime'",
                "UPDATE authority_story_planning_runtime_continuation SET chain_depth=1 WHERE continuation_id='parent'" if mode == 'projection' else "DELETE FROM authority_story_planning_runtime_continuation WHERE continuation_id='parent'",
                "UPDATE authority_story_planning_runtime_continuation SET target_runtime='{}' WHERE continuation_id='runtime'",
                "UPDATE authority_story_planning_runtime_continuation SET decision_evidence='{}' WHERE continuation_id='runtime'",
                "UPDATE authority_operation SET status='UNKNOWN' WHERE operation_id='source'",
                "UPDATE authority_attempt SET result='{}'",
                "INSERT INTO authority_external_effect(operation_id,status) VALUES('source','READY')",
                "INSERT INTO authority_budget_reservation VALUES('source','HELD')",
                "INSERT INTO authority_lease_acquisition VALUES('attempt','HELD')",
            ]:
                connection.execute('SAVEPOINT mode_guard')
                connection.execute(mutation)
                assert not _admitted(connection, generation), mutation
                connection.execute('ROLLBACK TO SAVEPOINT mode_guard')
                connection.execute('RELEASE SAVEPOINT mode_guard')
            assert connection.execute("SELECT status FROM authority_operation WHERE operation_id='source'").fetchone() == ('FAILED_FINAL',)
            assert connection.execute("SELECT repair_number FROM authority_story_planning_generation WHERE operation_id='source'").fetchone() == (0,)
