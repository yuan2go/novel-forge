from __future__ import annotations
from typing import Any
from psycopg.types.json import Jsonb
from novel_forge.modules.command_kernel.errors import KernelError


class SourceMarketRecords:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def definition(self, project: str, identity: str) -> dict:
        self.cursor.execute(
            "SELECT to_jsonb(d) FROM authority_source_market_definition d WHERE project_id=%s AND definition_id=%s",
            [project, identity],
        )
        row = self.cursor.fetchone()
        if not row:
            raise KernelError(
                "MARKET_DEFINITION_NOT_FOUND", "exact project definition required"
            )
        return row[0]

    def current(self, project: str, rank_key: str) -> dict | None:
        self.cursor.execute(
            """SELECT to_jsonb(d) FROM authority_source_market_definition d
            WHERE d.project_id=%s AND d.rank_key=%s AND NOT EXISTS (
                SELECT 1 FROM authority_source_market_definition n WHERE n.previous_definition_id=d.definition_id)
            LIMIT 1""",
            [project, rank_key],
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def definitions(
        self, project: str, after: str, limit: int, category: str = ""
    ) -> list[dict]:
        self.cursor.execute(
            """SELECT to_jsonb(d) FROM authority_source_market_definition d
            WHERE d.project_id=%s AND d.definition_id>%s AND (%s='' OR d.payload->'definition'->>'category'=%s)
            AND NOT EXISTS (SELECT 1 FROM authority_source_market_definition n WHERE n.previous_definition_id=d.definition_id)
            ORDER BY d.definition_id LIMIT %s""",
            [project, after, category, category, limit],
        )
        return [r[0] for r in self.cursor.fetchall()]

    def insert_definition(self, row: dict) -> None:
        self.cursor.execute(
            """INSERT INTO authority_source_market_definition
            (definition_id,project_id,source_id,rank_key,previous_definition_id,asset_version_id,payload,created_by_operation_id)
            VALUES (%(definition_id)s,%(project_id)s,%(source_id)s,%(rank_key)s,%(previous_definition_id)s,%(asset_version_id)s,%(payload)s,%(created_by_operation_id)s)
            ON CONFLICT(definition_id) DO NOTHING""",
            {**row, "payload": Jsonb(row["payload"])},
        )

    def platform(self, project: str, source: str) -> None:
        self.cursor.execute(
            """INSERT INTO authority_source_market_platform(project_id,platform,source_id)
            VALUES (%s,'qidian',%s) ON CONFLICT(project_id,platform) DO NOTHING""",
            [project, source],
        )
        self.cursor.execute(
            "SELECT source_id FROM authority_source_market_platform WHERE project_id=%s AND platform='qidian'",
            [project],
        )
        if self.cursor.fetchone()[0] != source:
            raise KernelError(
                "MARKET_PLATFORM_IDENTITY_CONFLICT",
                "Use the existing platform Source identity for every rank/category",
            )

    def insert_attempt(self, row: dict) -> None:
        self.cursor.execute(
            """INSERT INTO authority_source_market_attempt
            (attempt_record_id,project_id,definition_id,asset_version_id,status,observed_at,acquired_at,payload,created_by_operation_id)
            VALUES (%(attempt_record_id)s,%(project_id)s,%(definition_id)s,%(asset_version_id)s,%(status)s,%(observed_at)s,%(acquired_at)s,%(payload)s,%(created_by_operation_id)s)
            ON CONFLICT(attempt_record_id) DO NOTHING""",
            {**row, "payload": Jsonb(row["payload"])},
        )

    def attempts(
        self, project: str, definition: str, *, limit: int = 1, complete: bool = False
    ) -> list[dict]:
        self.cursor.execute(
            """SELECT to_jsonb(a) FROM authority_source_market_attempt a
            WHERE project_id=%s AND definition_id=%s AND (%s=false OR status='COMPLETE')
            ORDER BY observed_at DESC, acquired_at DESC, attempt_record_id DESC LIMIT %s""",
            [project, definition, complete, limit],
        )
        return [r[0] for r in self.cursor.fetchall()]

    def insert_metadata(self, row: dict) -> None:
        self.cursor.execute(
            """INSERT INTO authority_source_market_metadata
            (metadata_id,project_id,source_id,book_source_id,content_hash,payload,created_by_operation_id)
            VALUES (%(metadata_id)s,%(project_id)s,%(source_id)s,%(book_source_id)s,%(content_hash)s,%(payload)s,%(created_by_operation_id)s)
            ON CONFLICT(metadata_id) DO NOTHING""",
            {**row, "payload": Jsonb(row["payload"])},
        )

    def link(
        self,
        project: str,
        source: str,
        book: str,
        edition: str,
        evidence: str,
        operation: str,
    ) -> None:
        self.cursor.execute(
            """INSERT INTO authority_source_market_edition_link
            (project_id,source_id,book_source_id,edition_id,evidence_ref,created_by_operation_id)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(book_source_id,edition_id) DO NOTHING""",
            [project, source, book, edition, evidence, operation],
        )

    def work(self, project: str, book: str) -> dict:
        self.cursor.execute(
            """SELECT to_jsonb(m) FROM authority_source_market_metadata m
            WHERE project_id=%s AND book_source_id=%s ORDER BY created_at DESC,metadata_id DESC LIMIT 100""",
            [project, book],
        )
        metadata = [r[0] for r in self.cursor.fetchall()]
        self.cursor.execute(
            """SELECT l.edition_id,l.evidence_ref,e.title,e.locator,e.checksum,e.source_id
            FROM authority_source_market_edition_link l JOIN authority_corpus_edition e USING(project_id,edition_id)
            WHERE l.project_id=%s AND l.book_source_id=%s ORDER BY l.edition_id LIMIT 100""",
            [project, book],
        )
        editions = [
            dict(
                zip(
                    (
                        "edition_id",
                        "evidence_ref",
                        "title",
                        "locator",
                        "checksum",
                        "source_id",
                    ),
                    r,
                    strict=True,
                )
            )
            for r in self.cursor.fetchall()
        ]
        return {
            "metadata_versions": metadata,
            "editions": editions,
            "bounded": len(metadata) == 100 or len(editions) == 100,
        }
