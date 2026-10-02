from __future__ import annotations

from typing import Any
from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.errors import KernelError


class CorpusProcessingRecords:
    cursor: Any

    def require_source_observation(self, project: str, operation: str, inputs: dict) -> dict:
        from novel_forge.modules.source_authority.observation import observation_boundary, validate_local_integrity

        boundary = observation_boundary(inputs["observation_boundary"])
        self.cursor.execute("SELECT actor_id,command_payload,definition_name FROM authority_operation WHERE project_id=%s AND operation_id=%s", [project, operation])
        admitted = self.cursor.fetchone()
        projection = ((admitted[1].get("payload") or {}).get("task_projection") or {}) if admitted else {}
        if not admitted or admitted[0] != boundary.authorized_actor_id or admitted[2] != "source.import.deconstruction.execute" or projection.get("observation_boundary") != inputs["observation_boundary"]:
            raise KernelError("SOURCE_OBSERVATION_NOT_REGISTERED", "scope must match the admitted author Operation")
        import json
        if json.dumps(projection, sort_keys=True, default=str) != json.dumps(dict(inputs), sort_keys=True, default=str):
            raise KernelError("SOURCE_OBSERVATION_INPUT_DRIFT", "research projection changed after admission")
        processing = self.corpus_processing(project, boundary.processing_id)
        self.cursor.execute("SELECT 1 FROM authority_corpus_processing WHERE parent_id=%s", [boundary.processing_id])
        if self.cursor.fetchone() or processing["edition_id"] != boundary.edition_id or processing["source_work_asset_version_id"] != boundary.source_work_asset_version_id:
            raise KernelError("SOURCE_OBSERVATION_VERSION", "current exact processing required")
        ids = list({span.unit_version_id for span in boundary.spans})
        self.cursor.execute("SELECT to_jsonb(u) FROM authority_source_unit_version u WHERE project_id=%s AND source_work_asset_version_id=%s AND source_unit_version_id=ANY(%s)", [project, boundary.source_work_asset_version_id, ids])
        units = [r[0] for r in self.cursor.fetchall()]
        if len(units) != len(ids) or any(u["status"] != "AVAILABLE" or u["raw_file_hash"] != boundary.source_hash for u in units):
            raise KernelError("SOURCE_OBSERVATION_UNIT", "observed source identity is unavailable or changed")
        validate_local_integrity(processing["assessment"], units)
        indexed = {u["source_unit_version_id"]: u for u in units}
        segments = inputs.get("source_segments") or []
        chunks = list({span.chunk_asset_version_id for span in boundary.spans})
        if set(chunks) != {s.get("source_chunk_asset_version_id") for s in segments}:
            raise KernelError("SOURCE_OBSERVATION_SCOPE", "source chunks exceed observation spans")
        self.cursor.execute("SELECT to_jsonb(c) FROM authority_source_chunk c WHERE project_id=%s AND source_document_id=%s AND asset_version_id=ANY(%s)", [project, processing["source_document_id"], chunks])
        found = {r[0]["asset_version_id"]: r[0] for r in self.cursor.fetchall()}
        if len(found) != len(chunks):
            raise KernelError("SOURCE_OBSERVATION_SCOPE", "chunk is outside processing document")
        for span in boundary.spans:
            unit, chunk = indexed[span.unit_version_id], found[span.chunk_asset_version_id]
            if not unit["source_locator"] or unit["source_locator"].get("precision") != "UNIT_BYTES":
                raise KernelError("SOURCE_OBSERVATION_MAPPING", "stable original unit mapping required")
            if not str(unit["title"]).startswith(f"第{span.chapter}章 "):
                raise KernelError("SOURCE_OBSERVATION_CHAPTER", "chapter binding differs from source unit")
            if span.byte_end > chunk["byte_size"] or chunk["source_byte_start"] + span.byte_start < unit["normalized_byte_start"] or chunk["source_byte_start"] + span.byte_end > unit["normalized_byte_end"]:
                raise KernelError("SOURCE_OBSERVATION_SCOPE", "slice exceeds authorized source unit")
        return {**boundary.model_dump(mode="json"), "source_document_id": processing["source_document_id"]}

    def corpus_processing(
        self, project: str, identity: str, *, edition: bool = False
    ) -> dict[str, Any]:
        condition = (
            "p.edition_id=%s AND NOT EXISTS(SELECT 1 FROM authority_corpus_processing n WHERE n.parent_id=p.processing_id)"
            if edition
            else "p.processing_id=%s"
        )
        self.cursor.execute(
            "SELECT to_jsonb(p) FROM authority_corpus_processing p WHERE p.project_id=%s AND "
            + condition,
            [project, identity],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CORPUS_PROCESSING_NOT_FOUND",
                "no processing revision in the project scope",
            )
        value = row[0]
        self.cursor.execute(
            "SELECT to_jsonb(r) FROM authority_corpus_review r WHERE r.processing_id=%s AND NOT EXISTS(SELECT 1 FROM authority_corpus_review n WHERE n.previous_id=r.review_id)",
            [value["processing_id"]],
        )
        review = self.cursor.fetchone()
        value["review"] = review[0] if review else None
        if review:
            value["assessment"] = review[0]["assessment"]
        self.cursor.execute(
            """SELECT target_asset_version_id,cause_type,status FROM authority_content_invalidation
            WHERE project_id=%s AND created_by_operation_id=%s
            ORDER BY target_asset_version_id LIMIT 101""",
            [project, value["created_by_operation_id"]],
        )
        impacts = self.cursor.fetchall()
        value["downstream_impact"] = {
            "invalidated": [
                dict(zip(("asset_version_id", "cause", "status"), r, strict=True))
                for r in impacts[:100]
            ],
            "truncated": len(impacts) > 100,
            "operation_id": value["created_by_operation_id"],
            "full_query": "source intelligence invalidations by operation",
        }
        return value

    def corpus_insert_processing(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """INSERT INTO authority_corpus_processing(processing_id,project_id,edition_id,parent_id,source_work_asset_version_id,source_document_id,parsed_blob_id,input_hash,parser_hash,normalized_hash,profile,assessment,fingerprint,buckets,created_by_operation_id)
            VALUES (%(processing_id)s,%(project_id)s,%(edition_id)s,%(parent_id)s,%(source_work_asset_version_id)s,%(source_document_id)s,%(parsed_blob_id)s,%(input_hash)s,%(parser_hash)s,%(normalized_hash)s,%(profile)s,%(assessment)s,%(fingerprint)s,%(buckets)s,%(created_by_operation_id)s)
            ON CONFLICT(processing_id) DO NOTHING""",
            {
                **row,
                **{k: Jsonb(row[k]) for k in ("profile", "assessment", "fingerprint")},
            },
        )
        self.cursor.execute(
            "SELECT to_jsonb(p) FROM authority_corpus_processing p WHERE processing_id=%s",
            [row["processing_id"]],
        )
        stored = self.cursor.fetchone()[0]
        if any(
            stored[k] != v for k, v in row.items() if k != "created_by_operation_id"
        ):
            raise KernelError(
                "CORPUS_PROCESSING_IDENTITY_CONFLICT", "immutable processing differs"
            )

    def corpus_quality_insert(self, table: str, row: dict[str, Any]) -> None:
        from psycopg import sql

        if table not in {"review", "equivalence"}:
            raise ValueError("unsupported decision")
        self.cursor.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier("authority_corpus_" + table),
                sql.SQL(",").join(map(sql.Identifier, row)),
                sql.SQL(",").join(sql.Placeholder() for _ in row),
            ),
            [Jsonb(v) if isinstance(v, (dict, list)) else v for v in row.values()],
        )

    def corpus_equivalence_current(
        self, project: str, left: str, right: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """SELECT to_jsonb(e) FROM authority_corpus_equivalence e WHERE e.project_id=%s AND e.left_id=%s AND e.right_id=%s
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_equivalence n WHERE n.previous_id=e.decision_id)""",
            [project, left, right],
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def corpus_similar(
        self,
        project: str,
        source: dict[str, Any],
        limit: int,
        *,
        after: str = "",
        historical: bool = False,
    ) -> dict[str, Any]:
        import base64
        import json
        from novel_forge.modules.source_authority.corpus import corpus_hash

        if not 1 <= limit <= 100 or len(after) > 4096:
            raise ValueError("bounded candidate page required")
        self.cursor.execute(
            "SELECT max(created_at)::text FROM authority_corpus_processing WHERE project_id=%s",
            [project],
        )
        watermark = self.cursor.fetchone()[0]
        if not historical:
            self.cursor.execute(
                "SELECT 1 FROM authority_corpus_processing WHERE parent_id=%s",
                [source["processing_id"]],
            )
            if self.cursor.fetchone():
                raise KernelError(
                    "CORPUS_DISCOVERY_TARGET_SUPERSEDED",
                    "select current processing or explicitly request historical versions",
                )
        query = {
            "project": project,
            "source": source["processing_id"],
            "input": source["input_hash"],
            "watermark": watermark,
            "historical": historical,
            "policy": "corpus-discovery.v2",
        }
        query_id = corpus_hash(query)
        priority, identity, evaluated = -1, "", 0
        if after:
            try:
                saved = json.loads(base64.urlsafe_b64decode(after))
            except (ValueError, TypeError) as exc:
                raise KernelError(
                    "CORPUS_DISCOVERY_CURSOR_INVALID", "invalid cursor"
                ) from exc
            if (
                not isinstance(saved, dict)
                or not isinstance(saved.get("identity"), str)
                or len(saved["identity"]) > 512
                or saved.get("priority") not in (0, 1)
                or type(saved.get("evaluated")) is not int
                or saved["evaluated"] < 0
            ):
                raise KernelError(
                    "CORPUS_DISCOVERY_CURSOR_INVALID", "cursor fields are invalid"
                )
            if saved.get("query_id") != query_id:
                raise KernelError(
                    "CORPUS_DISCOVERY_CURSOR_STALE",
                    "project, target, policy or candidate catalog changed; restart explicitly",
                )
            priority, identity, evaluated = (
                saved["priority"],
                saved["identity"],
                saved["evaluated"],
            )
        self.cursor.execute(
            """SELECT to_jsonb(p),CASE WHEN p.normalized_hash=%s THEN 0 ELSE 1 END AS priority
            FROM authority_corpus_processing p
            WHERE p.project_id=%s AND p.processing_id<>%s AND (p.normalized_hash=%s OR p.buckets && %s::text[])
            AND (%s OR NOT EXISTS(SELECT 1 FROM authority_corpus_processing n WHERE n.parent_id=p.processing_id))
            AND (CASE WHEN p.normalized_hash=%s THEN 0 ELSE 1 END,p.processing_id)>(%s,%s)
            ORDER BY priority,p.processing_id LIMIT %s""",
            [
                source["normalized_hash"],
                project,
                source["processing_id"],
                source["normalized_hash"],
                source["buckets"],
                historical,
                source["normalized_hash"],
                priority,
                identity,
                limit + 1,
            ],
        )
        rows = self.cursor.fetchall()
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "query_id": query_id,
                        "priority": page[-1][1],
                        "identity": page[-1][0]["processing_id"],
                        "evaluated": evaluated + len(page),
                    }
                ).encode()
            ).decode()
        return {
            "rows": [r[0] for r in page],
            "query_identity": query_id,
            "policy": query["policy"],
            "catalog_watermark": watermark,
            "next_cursor": next_cursor,
            "evaluated_before": evaluated,
            "evaluated_total": evaluated + len(page),
            "candidate_pool": "INDEX_MATCHING_CURRENT_VERSIONS"
            if not historical
            else "INDEX_MATCHING_ALL_VERSIONS",
            "unscanned_matching_candidates": bool(next_cursor),
            "recall_limit": "Bucket matching is incomplete; this page is not global Top K. Exact normalized hashes are enumerated first.",
        }

    def corpus_unbridged_documents(
        self, project: str, documents: tuple[str, ...]
    ) -> dict[str, str]:
        self.cursor.execute(
            """SELECT d.source_document_id FROM authority_source_document d
            WHERE d.project_id=%s AND d.source_document_id=ANY(%s) AND d.corpus_edition_id IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_bridge b JOIN authority_source_work_version w ON w.asset_version_id=b.source_work_asset_version_id AND w.status='ACTIVE' WHERE b.source_document_id=d.source_document_id
                AND b.edition_id=d.corpus_edition_id AND b.project_id=d.project_id)""",
            [project, list(documents)],
        )
        return {
            r[0]: "CORPUS_EXACT_DOCUMENT_BRIDGE_MISSING" for r in self.cursor.fetchall()
        }

    def corpus_processing_denials(
        self, project: str, documents: tuple[str, ...]
    ) -> dict[str, str]:
        self.cursor.execute(
            """SELECT p.source_document_id,
            EXISTS(SELECT 1 FROM authority_corpus_processing n WHERE n.parent_id=p.processing_id),
            COALESCE(r.assessment,p.assessment)->>'structure_usable'
            FROM authority_corpus_processing p LEFT JOIN LATERAL
              (SELECT assessment FROM authority_corpus_review r WHERE r.processing_id=p.processing_id
               AND NOT EXISTS(SELECT 1 FROM authority_corpus_review n WHERE n.previous_id=r.review_id)) r ON true
            WHERE p.project_id=%s AND p.source_document_id=ANY(%s)""",
            [project, list(documents)],
        )
        return {
            r[0]: "CORPUS_PROCESSING_SUPERSEDED"
            if r[1]
            else "CORPUS_INTEGRITY_REVIEW_REQUIRED"
            for r in self.cursor.fetchall()
            if r[1] or r[2] != "true"
        }
