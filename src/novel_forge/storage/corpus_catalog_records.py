from __future__ import annotations

from typing import Any
from psycopg import sql
from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.errors import KernelError
from .corpus_processing_records import CorpusProcessingRecords


class CorpusCatalogRecords(CorpusProcessingRecords):
    def catalog_current(
        self, kind: str, project: str, identity: str, *, revision: bool = False
    ) -> dict[str, Any] | None:
        if kind not in {"work", "curated"}:
            raise ValueError("unknown corpus catalog kind")
        key = "work_id" if kind == "work" else "corpus_id"
        table = "authority_corpus_" + kind + "_revision"
        condition = (
            "r.revision_id=%s"
            if revision
            else f"r.{key}=%s AND NOT EXISTS(SELECT 1 FROM {table} n WHERE n.previous_id=r.revision_id)"
        )
        self.cursor.execute(
            sql.SQL(
                "SELECT to_jsonb(r) FROM {} r WHERE r.project_id=%s AND " + condition
            ).format(sql.Identifier(table)),
            [project, identity],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        self.cursor.execute(
            sql.SQL(
                "SELECT to_jsonb(m) FROM {} m WHERE m.revision_id=%s ORDER BY m.edition_id LIMIT 101"
            ).format(sql.Identifier("authority_corpus_" + kind + "_member")),
            [value["revision_id"]],
        )
        value["members"] = [r[0] for r in self.cursor.fetchall()]
        if len(value["members"]) > 100:
            raise KernelError(
                "CORPUS_MEMBER_BOUND_EXCEEDED", "catalog manifest exceeds frozen bound"
            )
        return value

    def catalog_insert(
        self, kind: str, row: dict[str, Any], members: list[dict[str, Any]]
    ) -> None:
        if kind not in {"work", "curated"} or len(members) > 100:
            raise ValueError("bounded catalog revision required")
        self.cursor.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier("authority_corpus_" + kind + "_revision"),
                sql.SQL(",").join(map(sql.Identifier, row)),
                sql.SQL(",").join(sql.Placeholder() for _ in row),
            ),
            [Jsonb(v) if isinstance(v, dict) else v for v in row.values()],
        )
        for member in members:
            self.cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (revision_id,project_id,processing_id,edition_id,evidence) VALUES (%s,%s,%s,%s,%s)"
                ).format(sql.Identifier("authority_corpus_" + kind + "_member")),
                [
                    row["revision_id"],
                    row["project_id"],
                    member["processing_id"],
                    member["edition_id"],
                    Jsonb(member["evidence"]),
                ],
            )

    def catalog_processings(
        self, project: str, ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if len(ids) > 800:
            raise ValueError("processing batch too large")
        self.cursor.execute(
            """SELECT to_jsonb(p),COALESCE(r.assessment,p.assessment),r.review_id,w.workspace_id,w.source_transform_id,
            NOT EXISTS(SELECT 1 FROM authority_corpus_processing n WHERE n.parent_id=p.processing_id)
            FROM authority_corpus_processing p JOIN authority_source_work_version w ON w.asset_version_id=p.source_work_asset_version_id
            LEFT JOIN LATERAL(SELECT * FROM authority_corpus_review r WHERE r.processing_id=p.processing_id AND NOT EXISTS(SELECT 1 FROM authority_corpus_review n WHERE n.previous_id=r.review_id)) r ON true
            WHERE p.project_id=%s AND p.processing_id=ANY(%s)""",
            [project, ids],
        )
        return {
            r[0]["processing_id"]: {
                **r[0],
                "assessment": r[1],
                "review_id": r[2],
                "workspace_id": r[3],
                "source_transform_id": r[4],
                "current": r[5],
            }
            for r in self.cursor.fetchall()
        }

    def catalog_relation_versions(self, project: str, editions: list[str]) -> dict[str, list[str]]:
        if len(editions) > 800:
            raise ValueError("bounded edition relation query required")
        self.cursor.execute("""SELECT p.edition_id,e.decision_id FROM authority_corpus_processing p
            JOIN authority_corpus_equivalence e ON e.project_id=p.project_id AND (e.left_id=p.processing_id OR e.right_id=p.processing_id)
            WHERE p.project_id=%s AND p.edition_id=ANY(%s)
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_equivalence n WHERE n.previous_id=e.decision_id)
            ORDER BY p.edition_id,e.decision_id LIMIT 10001""", [project, editions])
        rows = self.cursor.fetchall()
        if len(rows) > 10000:
            raise KernelError("CORPUS_RELATION_QUERY_BOUND", "narrow relation review scope")
        result = {}
        for edition, decision in rows:
            result.setdefault(edition, set()).add(decision)
        return {edition: sorted(decisions) for edition, decisions in result.items()}

    def catalog_conflicts(
        self, project: str, editions: list[str], changed_work_ids: list[str]
    ) -> dict[str, Any]:
        self.cursor.execute(
            """SELECT e.decision_id,e.relation,a.edition_id,b.edition_id FROM authority_corpus_equivalence e
            JOIN authority_corpus_processing a ON a.processing_id=e.left_id JOIN authority_corpus_processing b ON b.processing_id=e.right_id
            WHERE e.project_id=%s AND a.edition_id=ANY(%s) AND b.edition_id=ANY(%s)
            AND (e.relation='DIFFERENT_WORK' OR (e.relation IS NULL AND e.decision='REJECT'))
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_equivalence n WHERE n.previous_id=e.decision_id) LIMIT 101""",
            [project, editions, editions],
        )
        negatives = self.cursor.fetchall()
        self.cursor.execute(
            """SELECT r.work_id,m.edition_id FROM authority_corpus_work_member m JOIN authority_corpus_work_revision r USING(revision_id,project_id)
            WHERE r.project_id=%s AND m.edition_id=ANY(%s) AND NOT(r.work_id=ANY(%s)) AND r.manifest->>'state'='ACTIVE'
            AND NOT EXISTS(SELECT 1 FROM authority_corpus_work_revision n WHERE n.previous_id=r.revision_id) LIMIT 101""",
            [project, editions, changed_work_ids],
        )
        return {
            "negative_relations": negatives,
            "existing_groups": self.cursor.fetchall(),
        }

    def catalog_candidates(
        self, project: str, purpose: str, filters: dict[str, Any], limit: int
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("candidate catalog bound required")
        self.cursor.execute(
            """SELECT p.processing_id,p.edition_id,m.membership_id,s.rights_id,m.purpose,c.revision_id,c.manifest,
            COALESCE(r.assessment,p.assessment),w.character_count
            FROM authority_corpus_processing p
            JOIN authority_corpus_edition e ON e.edition_id=p.edition_id
            JOIN authority_corpus_snapshot s ON s.snapshot_id=e.snapshot_id
            JOIN authority_corpus_membership m ON m.edition_id=e.edition_id AND m.purpose=%s
            JOIN authority_source_work_version w ON w.asset_version_id=p.source_work_asset_version_id
            LEFT JOIN LATERAL(SELECT * FROM authority_corpus_review r WHERE r.processing_id=p.processing_id AND NOT EXISTS(SELECT 1 FROM authority_corpus_review n WHERE n.previous_id=r.review_id)) r ON true
            LEFT JOIN LATERAL(SELECT r.* FROM authority_corpus_work_member m JOIN authority_corpus_work_revision r USING(revision_id,project_id) WHERE m.edition_id=p.edition_id AND r.manifest->>'state'='ACTIVE' AND NOT EXISTS(SELECT 1 FROM authority_corpus_work_revision n WHERE n.previous_id=r.revision_id)) c ON true
            WHERE p.project_id=%s AND NOT EXISTS(SELECT 1 FROM authority_corpus_processing n WHERE n.parent_id=p.processing_id)
            AND (cardinality(%s::text[])=0 OR e.source_id=ANY(%s))
            AND (cardinality(%s::text[])=0 OR c.work_id=ANY(%s))
            AND (%s='' OR COALESCE(c.manifest->>'language','und')=%s)
            AND (cardinality(%s::text[])=0 OR c.manifest->'genre_tags' ?| %s::text[])
            AND w.character_count BETWEEN %s AND %s
            AND (cardinality(%s::text[])=0 OR COALESCE(r.assessment,p.assessment)->>'coverage'=ANY(%s))
            AND (%s::boolean IS NULL OR (COALESCE(r.assessment,p.assessment)->>'structure_usable')::boolean=%s)
            ORDER BY p.edition_id LIMIT %s""",
            [
                purpose,
                project,
                filters["source_ids"],
                filters["source_ids"],
                filters["work_ids"],
                filters["work_ids"],
                filters["language"],
                filters["language"],
                filters["genre_tags"],
                filters["genre_tags"],
                filters["min_characters"],
                filters["max_characters"],
                filters["coverages"],
                filters["coverages"],
                filters["structure_usable"],
                filters["structure_usable"],
                limit + 1,
            ],
        )
        rows = self.cursor.fetchall()
        return {
            "truncated": len(rows) > limit,
            "members": [
                {
                    "processing_id": r[0],
                    "edition_id": r[1],
                    "evidence": {
                        "membership_id": r[2],
                        "rights_id": r[3],
                        "purpose": r[4],
                        "canonical_revision_id": r[5],
                        "language": (r[6] or {}).get("language", "und"),
                        "genre_tags": (r[6] or {}).get("genre_tags", []),
                        "coverage": r[7]["coverage"],
                        "structure_usable": r[7]["structure_usable"],
                        "characters": r[8],
                        "selected": False,
                        "reason": "candidate requires explicit selection",
                    },
                }
                for r in rows[:limit]
            ],
        }

    def catalog_analysis_previous(
        self, project: str, key: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            "SELECT o.command_payload->'payload',o.operation_id,j.import_job_id FROM authority_operation o JOIN authority_source_import_job j ON j.discovery_operation_id=o.operation_id WHERE o.project_id=%s AND o.idempotency_key=%s AND o.definition_name='source.import.corpus.analysis'",
            [project, key],
        )
        row = self.cursor.fetchone()
        return (
            {**row[0], "discovery_operation_id": row[1], "import_job_id": row[2]}
            if row
            else None
        )

    def catalog_execution_binding(
        self, project: str, operation: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """WITH RECURSIVE chain AS (
            SELECT operation_id,parent_operation_id,command_payload,0 AS depth FROM authority_operation WHERE operation_id=%s AND project_id=%s
            UNION ALL SELECT p.operation_id,p.parent_operation_id,p.command_payload,c.depth+1 FROM chain c JOIN authority_operation p ON p.operation_id=c.parent_operation_id WHERE c.depth<20 AND p.project_id=%s
        ) SELECT command_payload->'payload' FROM chain WHERE command_payload->'payload' ? 'member_processing_id' ORDER BY depth LIMIT 1""",
            [operation, project, project],
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def catalog_active_work_revisions(self, project: str, ids: list[str]) -> set[str]:
        self.cursor.execute(
            "SELECT revision_id FROM authority_corpus_work_revision r WHERE r.project_id=%s AND r.revision_id=ANY(%s) AND r.manifest->>'state'='ACTIVE' AND NOT EXISTS(SELECT 1 FROM authority_corpus_work_revision n WHERE n.previous_id=r.revision_id)",
            [project, ids],
        )
        return {r[0] for r in self.cursor.fetchall()}
