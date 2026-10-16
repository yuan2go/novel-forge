from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .story_projection import STORY_PROJECTION_VERSION, SOURCE_JSON_PROJECTION, restore_source_json_fields, story_history, visible_business_data
from .writer_projection import WRITER_PROSE_TYPES

_FIELDS = ("retrieval_document_id", "project_id", "book_id", "source_asset_version_id", "source_artifact_type",
           "accepted_from_chapter", "accepted_to_chapter", "memory_layer", "content_text", "entity_ids",
           "relationship_ids", "character_ids", "arc_plan_version_ids", "obligation_ids", "temporal_coordinate", "metadata")


def projection_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def writer_index_document(document: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    from novel_forge.storage.book_authority_repositories import _retrieval_graph_metadata, _historical_reference_ids, _structured_fact_ids

    clean = deepcopy(dict(document))
    original_text = json.dumps(source, ensure_ascii=False) if document["source_artifact_type"] in WRITER_PROSE_TYPES else str(document["content_text"])
    text = story_history(original_text, physical_type=str(document["source_artifact_type"]), preserve_json=True)
    if document["source_artifact_type"] not in WRITER_PROSE_TYPES:
        text, _ = restore_source_json_fields(text, source)
    clean["content_text"] = text
    try:
        semantic_content = json.loads(text)
    except ValueError:
        semantic_content = {"summary": text}
    graph = _retrieval_graph_metadata(semantic_content)
    for key in ("entity_ids", "relationship_ids", "character_ids"):
        clean[key] = graph[key]
    clean["metadata"] = {**visible_business_data(dict(clean.get("metadata") or {}), stage="draft", history=True, preserve_json=True),
                         "writer_projection_version": STORY_PROJECTION_VERSION, "source_json_projection": SOURCE_JSON_PROJECTION}
    clean["metadata"]["historical_reference_ids"] = _historical_reference_ids(semantic_content)
    clean["metadata"]["fact_ids"] = _structured_fact_ids(list(clean["metadata"].get("structured_facts") or ()))
    clean["projection_hash"] = projection_hash({key: clean.get(key) for key in _FIELDS})
    return clean


def require_clean_writer_indexes(cursor: Any, *, project_id: str, book_id: str, boundary: int) -> None:
    cursor.execute("""SELECT document.retrieval_document_id
        FROM authority_narrative_retrieval_document document
        JOIN authority_asset_version version ON version.asset_version_id=document.source_asset_version_id
        WHERE document.project_id=%s AND document.book_id=%s
          AND document.accepted_from_chapter<=%s AND (document.accepted_to_chapter IS NULL OR document.accepted_to_chapter>=%s)
          AND version.lifecycle IN ('ACTIVE','SUPERSEDED') AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'
          AND COALESCE(document.metadata->>'writer_projection_version','')<>%s LIMIT 1""",
                   [project_id, book_id, boundary, boundary, STORY_PROJECTION_VERSION])
    if cursor.fetchone():
        raise KernelError("WRITER_RETRIEVAL_REBUILD_REQUIRED", "accepted story indexes require a scoped dry-run and explicit rebuild before new Writer retrieval")


def plan_writer_index_rebuild(database_url: str, *, project_id: str, book_id: str,
                              from_chapter: int, to_chapter: int, limit: int = 100, after_id: str = "") -> dict[str, Any]:
    if not project_id or not book_id or from_chapter < 0 or to_chapter < from_chapter or not 1 <= limit <= 1000:
        raise ValueError("rebuild requires explicit Project/Book/chapter bounds and limit 1..1000")
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("SET TRANSACTION READ ONLY")
        uow.cursor.execute("""SELECT to_jsonb(document), version.content_hash, version.content
            FROM authority_narrative_retrieval_document document
            JOIN authority_asset_version version ON version.asset_version_id=document.source_asset_version_id
            JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=document.project_id
            WHERE document.project_id=%s AND document.book_id=%s

              AND document.accepted_from_chapter BETWEEN %s AND %s AND document.retrieval_document_id>%s
              AND version.lifecycle IN ('ACTIVE','SUPERSEDED') AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'
            ORDER BY document.retrieval_document_id LIMIT %s""",
                           [project_id, book_id, from_chapter, to_chapter, after_id, limit])
        rows = uow.cursor.fetchall()
    entries = []
    for document, source_hash, source in rows:
        before = {key: document.get(key) for key in (*_FIELDS, "projection_hash")}
        after = writer_index_document(before, source)
        entries.append({"before": before, "after": after, "source_content_hash": source_hash,
                        "source_json_hash": projection_hash(source), "action": "UNCHANGED" if before == after else "REBUILD"})
    plan = {"version": STORY_PROJECTION_VERSION, "project_id": project_id, "book_id": book_id,
            "from_chapter": from_chapter, "to_chapter": to_chapter, "limit": limit, "after_id": after_id,
            "next_after_id": rows[-1][0]["retrieval_document_id"] if rows else after_id,
            "entries": entries, "embedding_status": "REBUILD_PENDING_REQUIRES_AUTHORIZED_PROVIDER"}
    return {**plan, "plan_hash": projection_hash(plan)}


def apply_writer_index_rebuild(database_url: str, plan: Mapping[str, Any], *, rollback: bool = False) -> dict[str, Any]:
    if plan.get("version") != STORY_PROJECTION_VERSION or plan.get("plan_hash") != projection_hash({key: value for key, value in plan.items() if key != "plan_hash"}):
        raise KernelError("WRITER_REBUILD_PLAN_INVALID", "rebuild manifest version or digest changed")
    counts = {"updated": 0, "replayed": 0}
    with AuthorityUnitOfWork(database_url) as uow:
        for entry in plan["entries"]:
            before, after = entry["before"], entry["after"]
            if (before["project_id"] != plan["project_id"] or before["book_id"] != plan["book_id"]
                or not plan["from_chapter"] <= before["accepted_from_chapter"] <= plan["to_chapter"]):
                raise KernelError("WRITER_REBUILD_SCOPE_CHANGED", "manifest entry exceeds its explicit scope")
            uow.cursor.execute("""SELECT to_jsonb(document), version.content_hash, version.content
                FROM authority_narrative_retrieval_document document
                JOIN authority_asset_version version ON version.asset_version_id=document.source_asset_version_id
                JOIN authority_asset asset ON asset.asset_id=version.asset_id AND asset.project_id=document.project_id
                WHERE document.retrieval_document_id=%s AND document.project_id=%s AND document.book_id=%s
                  AND version.lifecycle IN ('ACTIVE','SUPERSEDED') AND version.eligibility='ELIGIBLE' AND version.governance='CLEAR'
                FOR UPDATE OF document FOR SHARE OF version""", [before["retrieval_document_id"], plan["project_id"], plan["book_id"]])
            row = uow.cursor.fetchone()
            if not row or row[1] != entry["source_content_hash"] or projection_hash(row[2]) != entry["source_json_hash"] or writer_index_document(before, row[2]) != after:
                raise KernelError("WRITER_REBUILD_SOURCE_CONFLICT", "frozen source or desired projection changed; make a new dry-run")
            current = {key: row[0].get(key) for key in (*_FIELDS, "projection_hash")}
            expected, desired = (after, before) if rollback else (before, after)
            if current == desired:
                counts["replayed"] += 1
                continue
            if current != expected:
                raise KernelError("WRITER_REBUILD_CONFLICT", "derived row changed since dry-run; no overwrite performed")
            uow.cursor.execute("""UPDATE authority_narrative_retrieval_document
                SET content_text=%s, entity_ids=%s, relationship_ids=%s, character_ids=%s,
                    metadata=%s, projection_hash=%s, embedding=NULL
                WHERE retrieval_document_id=%s AND projection_hash=%s""",
                               [desired["content_text"], Jsonb(desired["entity_ids"]), Jsonb(desired["relationship_ids"]), Jsonb(desired["character_ids"]),
                                Jsonb(desired["metadata"]), desired["projection_hash"], before["retrieval_document_id"], expected["projection_hash"]])
            if uow.cursor.rowcount != 1:
                raise KernelError("WRITER_REBUILD_CONFLICT", "derived row CAS failed")
            counts["updated"] += 1
        uow.commit()
    return {"status": "PASS", "plan_hash": plan["plan_hash"], "rollback": rollback, **counts,
            "embedding_status": "REBUILD_PENDING_REQUIRES_AUTHORIZED_PROVIDER",
            "frozen_requests": "UNCHANGED", "raw_assets": "UNCHANGED"}
