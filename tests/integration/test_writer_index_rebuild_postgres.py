from copy import deepcopy
import json

import pytest
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_builder.production_retrieval import build_retrieval_query_plan, discover_accepted_retrieval_candidates
from novel_forge.modules.context_builder.retrieval_rebuild import apply_writer_index_rebuild, plan_writer_index_rebuild, projection_hash
from novel_forge.modules.context_builder.story_projection import STORY_PROJECTION_VERSION
from novel_forge.storage.book_authority_repositories import BookAuthorityRepository
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, identifier, insert_definition, insert_operation, seed_authority_project_book, transaction
from tests.unit.test_context_retrieval_v2 import _intent, _memo
from tests.unit.test_production_instruction_cleanup import mixed_source


def seed(count=1):
    ensure_migrated()
    project = identifier("writer-rebuild")
    book = "book:" + project
    seed_authority_project_book(project_id=project, book_id=book)
    operation = identifier("accepted-operation")
    with transaction() as connection, connection.cursor() as cursor:
        definition = identifier("accepted-definition")
        insert_definition(cursor, definition)
        insert_operation(cursor, operation_id=operation, definition_name=definition, project_id=project, status="SUCCEEDED", command_payload={"frozen_prompt": "ORIGINAL-REQUEST"})
        for index in range(count):
            asset = f"{project}:draft:{index}"
            source = {**mixed_source(), "selected_review": {"instruction": "metadataonlyword"}}
            cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,'best_draft_candidate')", [asset, project])
            cursor.execute("""INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version)
                VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'draft.v3')""", [asset + ":v1", asset, Jsonb(source), projection_hash(source)])
            cursor.execute("""INSERT INTO authority_narrative_retrieval_document(retrieval_document_id,project_id,book_id,source_asset_version_id,source_artifact_type,
                accepted_from_chapter,memory_layer,content_text,metadata,projection_hash,created_by_operation_id)
                VALUES (%s,%s,%s,%s,'best_draft_candidate',%s,'L0',%s,%s,%s,%s)""",
                [f"{project}:index:{index}", project, book, asset + ":v1", index + 1, json.dumps(source), Jsonb({"structured_facts": source["structured_facts"]}), projection_hash({"old": index}), operation])
    return project, book, operation


def plan(project, book, **kwargs):
    return plan_writer_index_rebuild(DATABASE_URL, project_id=project, book_id=book, from_chapter=0, to_chapter=10, **kwargs)


def rows(project):
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT retrieval_document_id, content_text, projection_hash, metadata FROM authority_narrative_retrieval_document WHERE project_id=%s ORDER BY retrieval_document_id", [project])
        return cursor.fetchall()


def test_dry_run_apply_idempotence_and_fts_input_isolation():
    project, book, operation = seed()
    original = rows(project)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT content, content_hash FROM authority_asset_version WHERE asset_version_id=%s", [project + ":draft:0:v1"])
        raw = cursor.fetchone()
        cursor.execute("SELECT ts_rank(search_vector,plainto_tsquery('simple','metadataonlyword')) FROM authority_narrative_retrieval_document WHERE project_id=%s", [project])
        assert cursor.fetchone()[0] > 0
    manifest = plan(project, book)
    assert rows(project) == original
    assert apply_writer_index_rebuild(DATABASE_URL, manifest)["updated"] == 1
    assert apply_writer_index_rebuild(DATABASE_URL, manifest)["replayed"] == 1
    current = rows(project)
    assert current[0][3]["writer_projection_version"] == STORY_PROJECTION_VERSION
    for marker in ("metadataonlyword", "REJECTED-QUOTE", "PROVIDER-ERROR", "PRIVATE-FACT"):
        assert marker not in json.dumps(current)
    assert "You owe me one joke." in current[0][1]
    assert plan(project, book)["entries"][0]["action"] == "UNCHANGED"
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT content, content_hash FROM authority_asset_version WHERE asset_version_id=%s", [project + ":draft:0:v1"])
        assert cursor.fetchone() == raw
        cursor.execute("SELECT command_payload FROM authority_operation WHERE operation_id=%s", [operation])
        assert cursor.fetchone()[0] == {"frozen_prompt": "ORIGINAL-REQUEST"}
        cursor.execute("SELECT ts_rank(search_vector,plainto_tsquery('simple','metadataonlyword')) FROM authority_narrative_retrieval_document WHERE project_id=%s", [project])
        assert cursor.fetchone()[0] == 0


def test_new_retrieval_blocks_legacy_index_until_explicit_rebuild_and_rollback_blocks_again():
    project, book, _ = seed()
    query = build_retrieval_query_plan(intent=_intent(), memo=_memo())
    with pytest.raises(KernelError, match="WRITER_RETRIEVAL_REBUILD_REQUIRED"):
        discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project, book_id=book, query_plan=query)
    manifest = plan(project, book)
    apply_writer_index_rebuild(DATABASE_URL, manifest)
    found = discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project, book_id=book, query_plan=query)
    assert found.query_plan["writer_projection_version"] == STORY_PROJECTION_VERSION
    assert apply_writer_index_rebuild(DATABASE_URL, manifest, rollback=True)["updated"] == 1
    assert apply_writer_index_rebuild(DATABASE_URL, manifest, rollback=True)["replayed"] == 1
    with pytest.raises(KernelError, match="WRITER_RETRIEVAL_REBUILD_REQUIRED"):
        discover_accepted_retrieval_candidates(DATABASE_URL, project_id=project, book_id=book, query_plan=query)


def test_partial_batch_resume_conflict_and_manifest_scope_are_explicit():
    project, book, _ = seed(2)
    full = plan(project, book)
    first = plan(project, book, limit=1)
    apply_writer_index_rebuild(DATABASE_URL, first)
    assert len(plan(project, book, after_id=first["next_after_id"])["entries"]) == 1
    completed = apply_writer_index_rebuild(DATABASE_URL, full)
    assert completed["updated"] == completed["replayed"] == 1
    current = plan(project, book)
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_narrative_retrieval_document SET metadata=metadata || '{\"concurrent\":true}'::jsonb WHERE retrieval_document_id=%s", [current["entries"][1]["before"]["retrieval_document_id"]])
    with pytest.raises(KernelError, match="WRITER_REBUILD_CONFLICT"):
        apply_writer_index_rebuild(DATABASE_URL, current)
    corrupted = deepcopy(full)
    corrupted["project_id"] = "another-project"
    corrupted["plan_hash"] = projection_hash({key: value for key, value in corrupted.items() if key != "plan_hash"})
    with pytest.raises(KernelError, match="WRITER_REBUILD_SCOPE_CHANGED"):
        apply_writer_index_rebuild(DATABASE_URL, corrupted)


def test_source_conflict_is_not_overwritten():
    project, book, _ = seed()
    manifest = plan(project, book)
    manifest["entries"][0]["source_content_hash"] = "sha256:" + "f" * 64
    manifest["plan_hash"] = projection_hash({key: value for key, value in manifest.items() if key != "plan_hash"})
    with pytest.raises(KernelError, match="WRITER_REBUILD_SOURCE_CONFLICT"):
        apply_writer_index_rebuild(DATABASE_URL, manifest)
    assert rows(project)[0][1] == manifest["entries"][0]["before"]["content_text"]


def test_real_accepted_repository_writes_clean_projection_and_detects_conflicting_existing_index():
    project, book, operation = seed()
    source_id = project + ":draft:0:v1"
    sources = {}
    with transaction() as connection, connection.cursor() as cursor:
        for kind in ("chapter_outcome", "story_state_snapshot", "canon_snapshot"):
            asset = project + ":" + kind
            content = {"type": kind, "summary": "accepted business fact"}
            cursor.execute("INSERT INTO authority_asset(asset_id,project_id,asset_type) VALUES (%s,%s,%s)", [asset, project, kind])
            cursor.execute("""INSERT INTO authority_asset_version(asset_version_id,asset_id,version_number,lifecycle,eligibility,governance,content,content_hash,schema_version)
                VALUES (%s,%s,1,'ACTIVE','ELIGIBLE','CLEAR',%s,%s,'test.v1')""", [asset + ":v1", asset, Jsonb(content), projection_hash(content)])
            sources[("story_state" if kind == "story_state_snapshot" else kind) + "_asset_version_id"] = asset + ":v1"
        cursor.execute("DELETE FROM authority_narrative_retrieval_document WHERE project_id=%s", [project])
        projection = {"project_id": project, "book_id": book, "projection_set_id": "projection:test", "source_versions": sources,
            "accepted_boundary": {"chapter_number": 1, "acceptance_operation_id": operation}, "arc_states": [], "obligation_states": [],
            "arc_progress": [], "arc_checkpoints": [], "source_chapter_outcome": {"chapter_number": 1, "accepted_draft_asset_version_id": source_id}}
        repository = BookAuthorityRepository(cursor)
        repository._commit_narrative_retrieval_documents(projection)
        repository._commit_narrative_retrieval_documents(projection)
        cursor.execute("SELECT content_text,metadata FROM authority_narrative_retrieval_document WHERE project_id=%s AND memory_layer='L0'", [project])
        text, metadata = cursor.fetchone()
        assert metadata["writer_projection_version"] == STORY_PROJECTION_VERSION
        assert "You owe me one joke." in text and "metadataonlyword" not in text
    manifest = plan(project, book)
    assert all(entry["action"] == "UNCHANGED" for entry in manifest["entries"])
    with transaction() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE authority_narrative_retrieval_document SET projection_hash=%s WHERE project_id=%s AND memory_layer='L0'", ["sha256:" + "f" * 64, project])
        with pytest.raises(ValueError, match="WRITER_RETRIEVAL_REBUILD_REQUIRED"):
            BookAuthorityRepository(cursor)._commit_narrative_retrieval_documents(projection)
