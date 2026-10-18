from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from novel_forge.storage.plan_change_repositories import PlanChangeRepository
from tests.integration.authority_postgres_support import DATABASE_URL


@pytest.fixture
def impact_schema():
    schema = 'impact_recovery_' + uuid4().hex
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            connection.execute(sql.SQL('SET search_path TO {}, public').format(sql.Identifier(schema)))
            for table in ('authority_plan_change_proposal', 'story_plan_binding', 'active_story_plan_version', 'authority_plan_change_impact'):
                connection.execute(sql.SQL('CREATE TABLE {} AS SELECT * FROM public.{} WITH NO DATA').format(sql.Identifier(table), sql.Identifier(table)))
            connection.execute('CREATE UNIQUE INDEX direct_impact_identity ON authority_plan_change_impact(proposal_id,impacted_asset_version_id)')
            connection.execute("""INSERT INTO authority_plan_change_proposal(proposal_id,project_id,book_id,status,target_asset_version_id,
                proposed_asset_version_id,target_execution_scope,target_logical_key,approval_operation_id,activation_operation_id)
                VALUES('proposal','p','b','ACTIVE','old','new','FROZEN','group:next','approval','activation')""")
            connection.execute("INSERT INTO story_plan_binding(project_id,book_id,asset_version_id,execution_scope,freshness) VALUES('p','b','old','FROZEN','STALE')")
            connection.execute("INSERT INTO active_story_plan_version(project_id,book_id,logical_key,asset_version_id) VALUES('p','b','group:next','new')")
            connection.execute("""INSERT INTO authority_plan_change_impact(impact_id,proposal_id,project_id,source_asset_version_id,
                impacted_asset_version_id,dependency_path,execution_scope,previous_freshness,target_freshness,automatic_mutation_allowed,recorded_by_operation_id)
                VALUES('existing','proposal','p','old','descendant','["old","descendant"]','PLANNED','FRESH','STALE',false,'activation')""")
            yield schema
        finally:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def scoped(connection, schema):
    connection.execute(sql.SQL('SET search_path TO {}, public').format(sql.Identifier(schema)))
    return PlanChangeRepository(connection.cursor())


@pytest.mark.parametrize('mutation', [None, 'replacement', 'book', 'executed', 'approval', 'freshness'])
def test_legacy_active_direct_impact_is_append_only_and_exactly_scoped(impact_schema, mutation):
    with psycopg.connect(DATABASE_URL) as connection:
        repository = scoped(connection, impact_schema)
        before = connection.execute('SELECT to_jsonb(impact) FROM authority_plan_change_impact impact').fetchone()[0]
        edits = {
            'replacement': "UPDATE active_story_plan_version SET asset_version_id='later'",
            'book': "UPDATE story_plan_binding SET book_id='other'",
            'executed': "UPDATE story_plan_binding SET execution_scope='EXECUTED'",
            'approval': 'UPDATE authority_plan_change_proposal SET approval_operation_id=NULL',
            'freshness': "UPDATE story_plan_binding SET freshness='FRESH'",
        }
        if mutation:
            connection.execute(edits[mutation])
        assert repository.reconcile_replaced_target_impact('proposal') is (mutation is None)
        assert repository.reconcile_replaced_target_impact('proposal') is False
        assert connection.execute("SELECT to_jsonb(impact) FROM authority_plan_change_impact impact WHERE impact_id='existing'").fetchone()[0] == before
        if mutation is None:
            row = connection.execute("SELECT recorded_by_operation_id,execution_scope,dependency_path FROM authority_plan_change_impact WHERE impacted_asset_version_id='old'").fetchone()
            assert row == ('activation', 'FROZEN', ['old'])


def test_concurrent_legacy_active_repair_has_one_successful_append(impact_schema):
    entered = Event()
    with psycopg.connect(DATABASE_URL) as first, psycopg.connect(DATABASE_URL) as second, ThreadPoolExecutor(max_workers=1) as pool:
        one, two = scoped(first, impact_schema), scoped(second, impact_schema)
        assert one.reconcile_replaced_target_impact('proposal')

        def competing():
            entered.set()
            result = two.reconcile_replaced_target_impact('proposal')
            second.commit()
            return result

        future = pool.submit(competing)
        assert entered.wait(timeout=5)
        first.commit()
        assert future.result(timeout=10) is False
        assert first.execute("SELECT count(*) FROM authority_plan_change_impact WHERE impacted_asset_version_id='old'").fetchone()[0] == 1
