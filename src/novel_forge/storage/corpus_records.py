from __future__ import annotations

from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.corpus_ingestion_records import CorpusIngestionRecords


CORPUS_KEYS = {
    "source": "source_id",
    "rights": "rights_id",
    "snapshot": "snapshot_id",
    "book_identity": "book_source_id",
    "edition": "edition_id",
    "admission": "decision_id",
    "membership": "membership_id",
    "retirement": "source_id",
}


class CorpusRecords(CorpusIngestionRecords):
    cursor: Any

    def corpus_authorization_lock(self, project_id: str, *, write: bool = False) -> None:
        function = "pg_advisory_xact_lock" if write else "pg_advisory_xact_lock_shared"
        self.cursor.execute(sql.SQL("SELECT {}(hashtextextended(%s,0))").format(sql.Identifier(function)), ["source-corpus-authorization:" + project_id])

    def corpus_record(
        self, kind: str, project_id: str, identity: str, *, lock: bool = False
    ) -> dict[str, Any]:
        key = CORPUS_KEYS[kind]
        self.cursor.execute(
            sql.SQL(
                "SELECT to_jsonb(r) FROM {} r WHERE project_id=%s AND {}=%s {}"
            ).format(
                sql.Identifier("authority_corpus_" + kind),
                sql.Identifier(key),
                sql.SQL("FOR UPDATE" if lock else ""),
            ),
            [project_id, identity],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CORPUS_REFERENCE_NOT_FOUND",
                f"{kind} is not in this project: {identity}",
            )
        return dict(row[0])

    def corpus_insert(self, kind: str, row: dict[str, Any]) -> dict[str, Any]:
        key = CORPUS_KEYS[kind]
        self.cursor.execute(
            sql.SQL(
                "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO NOTHING RETURNING to_jsonb({})"
            ).format(
                sql.Identifier("authority_corpus_" + kind),
                sql.SQL(",").join(map(sql.Identifier, row)),
                sql.SQL(",").join(sql.Placeholder() for _ in row),
                sql.Identifier(key),
                sql.Identifier("authority_corpus_" + kind),
            ),
            [
                Jsonb(value) if isinstance(value, (dict, list)) else value
                for value in row.values()
            ],
        )
        inserted = self.cursor.fetchone()
        if inserted:
            return dict(inserted[0])
        existing = self.corpus_record(kind, row["project_id"], row[key])
        for field, value in row.items():
            if field != "created_by_operation_id" and existing[field] != value:
                raise KernelError(
                    "CORPUS_IMMUTABLE_IDENTITY_INVALID",
                    f"{kind}.{field} differs at frozen identity",
                )
        return existing

    def corpus_source_lock(self, project_id: str, source_id: str) -> dict[str, Any]:
        source = self.corpus_record("source", project_id, source_id, lock=True)
        self.cursor.execute(
            "SELECT 1 FROM authority_corpus_retirement WHERE source_id=%s", [source_id]
        )
        source["retired"] = self.cursor.fetchone() is not None
        return source

    def corpus_latest(self, kind: str, project_id: str, source_id: str) -> str | None:
        if kind not in {"rights", "snapshot"}:
            raise ValueError("only revision chains have a latest identity")
        key = CORPUS_KEYS[kind]
        self.cursor.execute(
            sql.SQL("""
            SELECT {} FROM {} WHERE project_id=%s AND source_id=%s
            ORDER BY revision_number DESC LIMIT 1
            """).format(
                sql.Identifier(key),
                sql.Identifier("authority_corpus_" + kind),
            ),
            [project_id, source_id],
        )
        row = self.cursor.fetchone()
        return str(row[0]) if row else None

    def corpus_existing(self, kind: str, project_id: str, identity: str) -> bool:
        self.cursor.execute(
            sql.SQL("SELECT 1 FROM {} WHERE project_id=%s AND {}=%s").format(
                sql.Identifier("authority_corpus_" + kind),
                sql.Identifier(CORPUS_KEYS[kind]),
            ),
            [project_id, identity],
        )
        return self.cursor.fetchone() is not None

    def corpus_page(
        self,
        kind: str,
        project_id: str,
        *,
        parent_id: str = "",
        after: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("Corpus pages are bounded to 1..100 records")
        parent_keys = {
            "source": None,
            "rights": "source_id",
            "snapshot": "source_id",
            "book_identity": "source_id",
            "edition": "snapshot_id",
            "admission": "edition_id",
            "membership": "edition_id",
        }
        parent = parent_keys[kind]
        if parent and not parent_id:
            raise ValueError(f"{kind} query requires {parent}")
        params: list[Any] = [project_id, after]
        predicate = sql.SQL("")
        if parent:
            predicate = sql.SQL(" AND {}=%s").format(sql.Identifier(parent))
            params.append(parent_id)
        params.append(limit)
        self.cursor.execute(
            sql.SQL(
                "SELECT to_jsonb(r) FROM {} r WHERE project_id=%s AND {}>%s {} ORDER BY {} LIMIT %s"
            ).format(
                sql.Identifier("authority_corpus_" + kind),
                sql.Identifier(CORPUS_KEYS[kind]),
                predicate,
                sql.Identifier(CORPUS_KEYS[kind]),
            ),
            params,
        )
        return [dict(row[0]) for row in self.cursor.fetchall()]

    def corpus_output(
        self, project_id: str, operation_id: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT v.content, v.asset_version_id FROM authority_operation_output_asset o
            JOIN authority_asset_version v ON v.asset_version_id=o.asset_version_id
            JOIN authority_operation op ON op.operation_id=o.operation_id
            WHERE op.project_id=%s AND o.operation_id=%s AND o.output_key='source.corpus.record'
        """,
            [project_id, operation_id],
        )
        row = self.cursor.fetchone()
        return {**row[0], "asset_version_id": row[1]} if row else None

    def corpus_operation_status(
        self, project_id: str, operation_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT status FROM authority_operation
            WHERE project_id=%s AND operation_id=%s AND definition_name='source.corpus.commit'
        """,
            [project_id, operation_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CORPUS_OPERATION_NOT_FOUND", "Corpus Operation is not in this project"
            )
        return {
            "operation_id": operation_id,
            "status": row[0],
            "result": self.corpus_output(project_id, operation_id),
        }

    def corpus_import_status(
        self, project_id: str, import_job_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT to_jsonb(j), o.status, o.command_payload, o.operation_id,
                   o.definition_snapshot, o.trace_id
            FROM authority_source_import_job j
            JOIN authority_operation o ON o.operation_id=j.discovery_operation_id
            WHERE j.project_id=%s AND j.import_job_id=%s AND j.mode='FOUNDATION'
        """,
            [project_id, import_job_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CORPUS_IMPORT_NOT_FOUND",
                "Corpus foundation import is not in this project",
            )
        self.cursor.execute(
            """
            SELECT to_jsonb(a) FROM authority_attempt a WHERE operation_id=%s ORDER BY attempt_number LIMIT 10
        """,
            [row[3]],
        )
        return {
            **row[0],
            "operation_status": row[1],
            "frozen_input": row[2],
            "operation_id": row[3],
            "effective_status": row[0]["status"] if row[1] == "SUCCEEDED" else row[1],
            "definition_snapshot": row[4],
            "trace_id": row[5],
            "attempts": [dict(item[0]) for item in self.cursor.fetchall()],
            "result": self.corpus_output(project_id, row[3]),
        }
