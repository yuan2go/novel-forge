from __future__ import annotations

from typing import Any
from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.errors import KernelError


class CorpusProcessingRecords:
    cursor: Any

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
        self, project: str, source: dict[str, Any], limit: int
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("candidate limit must be 1..100")
        self.cursor.execute(
            """SELECT to_jsonb(p) FROM authority_corpus_processing p
            WHERE p.project_id=%s AND p.processing_id<>%s AND (p.buckets && %s::text[] OR p.normalized_hash=%s)
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_processing n WHERE n.parent_id=p.processing_id)
            ORDER BY p.processing_id LIMIT %s""",
            [
                project,
                source["processing_id"],
                source["buckets"],
                source["normalized_hash"],
                limit,
            ],
        )
        return [r[0] for r in self.cursor.fetchall()]

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
