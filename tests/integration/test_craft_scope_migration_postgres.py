import psycopg
import pytest
from psycopg.types.json import Jsonb

from novel_forge.storage.migrations.versions.v20261015_0214_story_design_book_scope import (
    BOOK_SCOPE_STATEMENT,
    PREFLIGHT_STATEMENTS,
)
from tests.integration.authority_postgres_support import DATABASE_URL


def test_scope_backfill_requires_agreement_between_nested_plan_and_chapter_producer_lineage():
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            for ddl in (
                "authority_story_design_version_state(project_id text,asset_version_id text)",
                "authority_story_planning_candidate(project_id text,book_id text,generation_id text,candidate_asset_version_id text)",
                "authority_story_planning_generation(project_id text,book_id text,generation_id text)",
                "story_plan_binding(project_id text,book_id text,asset_version_id text)",
                "authority_book(project_id text,book_id text,current_book_design_asset_version_id text)",
                "authority_asset_version(asset_version_id text,asset_id text,content jsonb)",
                "authority_asset(asset_id text,project_id text)",
                "authority_operation_output_asset(operation_id text,asset_version_id text)",
                "authority_operation(operation_id text,root_operation_id text,project_id text)",
                "authority_book_chapter_request(chapter_root_operation_id text,book_run_id text)",
                "authority_book_production(book_run_id text,project_id text,book_id text)",
            ):
                connection.execute("CREATE TEMP TABLE " + ddl)
            connection.execute(BOOK_SCOPE_STATEMENT.replace(
                "CREATE FUNCTION authority_story_design_book_scope",
                "CREATE FUNCTION pg_temp.craft_book_scope"))
            connection.execute("INSERT INTO authority_book VALUES('project','book-a',NULL),('project','book-b',NULL)")
            content_by_id = {
                "nested": {"scope": {"book_id": "book-a"}},
                "selected": {"creative_input_selection": {"book_id": "book-a"}},
                "producer": {},
                "unbound": {},
                "ambiguous": {"book_id": "book-a", "scope": {"book_id": "book-b"}},
                "missing-owner": {"scope": {"book_id": "missing-book"}},
                "cross-producer": {"book_id": "book-b"},
            }
            for identity, content in content_by_id.items():
                connection.execute("INSERT INTO authority_asset VALUES(%s,'project')", [identity])
                connection.execute("INSERT INTO authority_asset_version VALUES(%s,%s,%s)",
                                   [identity, identity, Jsonb(content)])
                connection.execute("INSERT INTO authority_story_design_version_state VALUES('project',%s)", [identity])
            connection.execute("INSERT INTO authority_operation VALUES('chapter-op','chapter-root','project')")
            connection.execute("INSERT INTO authority_book_chapter_request VALUES('chapter-root','book-run')")
            connection.execute("INSERT INTO authority_book_production VALUES('book-run','project','book-a')")
            connection.execute("INSERT INTO authority_operation_output_asset VALUES('chapter-op','producer'),('chapter-op','cross-producer')")
            for identity in ("nested", "selected", "producer"):
                assert connection.execute("SELECT pg_temp.craft_book_scope('project',%s)", [identity]).fetchone()[0] == "book-a"
            assert connection.execute("SELECT pg_temp.craft_book_scope('project','unbound')").fetchone()[0] is None
            blockers = dict(connection.execute(PREFLIGHT_STATEMENTS[0]).fetchall())
            assert blockers == {"STORY_DESIGN_BOOK_LINEAGE_AMBIGUOUS": 2, "STORY_DESIGN_BOOK_OWNER_MISSING": 1}
            for identity, message in (
                ("ambiguous", "lineage is ambiguous"),
                ("cross-producer", "lineage is ambiguous"),
                ("missing-owner", "no owning Book"),
            ):
                connection.execute("SAVEPOINT invalid_scope")
                with pytest.raises(psycopg.errors.RaiseException, match=message):
                    connection.execute("SELECT pg_temp.craft_book_scope('project',%s)", [identity])
                connection.execute("ROLLBACK TO SAVEPOINT invalid_scope")
                connection.execute("RELEASE SAVEPOINT invalid_scope")
        finally:
            connection.rollback()
