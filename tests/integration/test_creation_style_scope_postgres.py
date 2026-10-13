from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4
import time

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from novel_forge.modules.authority_handler_runtime.contracts import AuthorityHandlerRequest, AuthorityInputAsset
from novel_forge.modules.book_authority.creation_inputs import require_style_scope_frontier
from novel_forge.modules.chapter_authority.receipt_recovery import lock_scope_recovery_creation
from novel_forge.modules.command_kernel.errors import KernelError
from tests.integration.authority_postgres_support import DATABASE_URL


@pytest.fixture
def scope():
    schema = "test_creation_style_scope_" + uuid4().hex
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        for ddl in (
            "authority_operation(operation_id text,actor_id text,project_id text,workspace_id text,status text)",
            "authority_story_formation_run(formation_run_id text,project_id text,workspace_id text,book_id text,lifecycle text,book_design_asset_version_id text,root_operation_id text)",
            "authority_book_production(book_run_id text,project_id text,workspace_id text,book_id text,version int,active_chapter_request_id text,book_design_version text,state text,stable_idempotency_key text)",
            "authority_book_chapter_request(chapter_request_id text,book_run_id text,chapter_root_operation_id text)",
            "authority_story_creation_cancellation(formation_run_id text)",
            "authority_asset(asset_id text,project_id text,asset_type text)",
            "authority_asset_version(asset_id text,asset_version_id text,content_hash text,content jsonb,lifecycle text,eligibility text,governance text)",
            "authority_external_effect(project_id text,request_payload jsonb,status text,external_effect_id text,operation_id text,request_hash text)",
            "authority_generation_isolation(external_effect_id text,operation_id text,project_id text,workspace_id text,request_hash text,proof jsonb)",
        ):
            connection.execute("CREATE TABLE " + ddl)
        connection.execute("INSERT INTO authority_operation VALUES('formation-root','author','project','workspace','SUCCEEDED')")
        connection.execute("INSERT INTO authority_story_formation_run VALUES('formation','project','workspace','book','READY','design','formation-root')")
        connection.execute("INSERT INTO authority_book_production VALUES('run','project','workspace','book',1,NULL,'design','READY','formation:production')")
        connection.execute("INSERT INTO authority_book_chapter_request VALUES('chapter','run','chapter-root')")
        connection.execute("INSERT INTO authority_asset VALUES('style','project','style_policy')")
        connection.execute("INSERT INTO authority_asset_version VALUES('style','style-v4','hash',%s,'ACTIVE','ELIGIBLE','CLEAR')",
            [Jsonb({"book_id": "book", "contract_version": "foundation-style-projection.v4",
                "source_bindings": [{"asset_version_id": "design", "content_hash": "design-hash"}]})])
    proof = {"contract_version": "creation-style-scope.v1", "formation_run_id": "formation", "book_run_id": "run",
        "book_version": 1, "book_design_asset_version_id": "design", "source_style": {"asset_version_id": "style-v4", "content_hash": "hash"}}
    request = AuthorityHandlerRequest("style-owner", "project", "workspace", "author", "trace", "correlation",
        "chapter.style_policy.compile", "2.1.6", {"payload": {"book_id": "book", "style_scope_revalidation": proof}},
        (AuthorityInputAsset("design", "book_design", "design-hash", {}),))
    try:
        yield schema, request
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def scoped_connection(schema):
    connection = psycopg.connect(DATABASE_URL)
    connection.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
    return connection


@pytest.mark.parametrize("mutation", [None, "active-chapter", "book-version", "creator", "source-hash", "unresolved-effect"])
def test_style_scope_commit_requires_exact_current_owned_checkpoint(scope, mutation):
    schema, request = scope
    with scoped_connection(schema) as connection:
        if mutation == "active-chapter":
            connection.execute("UPDATE authority_book_production SET active_chapter_request_id='chapter'")
        elif mutation == "book-version":
            connection.execute("UPDATE authority_book_production SET version=2")
        elif mutation == "creator":
            connection.execute("UPDATE authority_operation SET actor_id='another-author'")
        elif mutation == "source-hash":
            connection.execute("UPDATE authority_asset_version SET content_hash='changed'")
        elif mutation == "unresolved-effect":
            connection.execute("INSERT INTO authority_external_effect VALUES('project','{\"_production_execution\":{\"book_id\":\"book\"}}','UNKNOWN','not-isolated','generation','request-hash')")
        with connection.cursor() as cursor:
            uow = SimpleNamespace(cursor=cursor)
            if mutation:
                with pytest.raises(KernelError, match="CREATION_STYLE_SCOPE"):
                    require_style_scope_frontier(uow, request)
            else:
                require_style_scope_frontier(uow, request)


@pytest.mark.parametrize("guard", ["style", "draft"])
def test_native_cancellation_serializes_with_style_and_receipt_commit_guards(scope, guard):
    schema, request = scope
    with scoped_connection(schema) as blocker:
        if guard == "draft":
            blocker.execute("UPDATE authority_book_production SET active_chapter_request_id='chapter'")
            blocker.commit()
        blocker.execute("SELECT 1 FROM authority_story_formation_run WHERE formation_run_id='formation' FOR UPDATE")
        worker = scoped_connection(schema)
        worker_pid = worker.info.backend_pid
        def commit_guard():
            try:
                with worker:
                    with worker.cursor() as cursor:
                        if guard == "style":
                            require_style_scope_frontier(SimpleNamespace(cursor=cursor), request)
                        else:
                            lock_scope_recovery_creation(cursor, root_id="chapter-root", project_id="project")
            except KernelError as error:
                return error.code
            return "UNEXPECTED_COMMIT_PERMISSION"
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(commit_guard)
            until = time.monotonic() + 5
            while not blocker.execute("SELECT cardinality(pg_blocking_pids(%s))>0", [worker_pid]).fetchone()[0]:
                assert not result.done() and time.monotonic() < until
                time.sleep(0.01)
            blocker.execute("INSERT INTO authority_story_creation_cancellation VALUES('formation')")
            blocker.commit()
            assert result.result(timeout=5) == ("CREATION_STYLE_SCOPE_FRONTIER_CHANGED" if guard == "style" else "DRAFT_SCOPE_RECOVERY_CANCELLED")
