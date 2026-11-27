from __future__ import annotations

from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class BookEditionRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def resolve_book_run(self, *, project_id: str, book_id: str, book_run_id: str = "") -> str:
        return self.accepted_scope(project_id=project_id, book_id=book_id, book_run_id=book_run_id)[0]

    def accepted_scope(self, *, project_id: str, book_id: str, book_run_id: str = "") -> tuple[str, tuple[str, ...] | None]:
        acceptance_ids = None
        if not book_run_id:
            self.cursor.execute("""SELECT event.content,asset.content,revision.manifest_digest
                FROM authority_book_edition_head head
                JOIN authority_book_edition_revision revision ON revision.revision_id=head.selected_revision_id
                JOIN authority_book_edition edition USING(edition_id)
                JOIN authority_asset_version asset ON asset.asset_version_id=revision.revision_id
                LEFT JOIN authority_book_edition_event event
                ON event.revision_id=head.selected_revision_id AND event.event_kind='VALIDATED'
                WHERE head.book_id=%s AND edition.project_id=%s
                ORDER BY event.created_at DESC,event.event_id DESC LIMIT 1""", [book_id,project_id])
            selected = self.cursor.fetchone()
            if selected:
                from novel_forge.modules.book_authority.editions import require_manifest
                proof, manifest, digest = selected
                require_manifest(manifest)
                if not proof or proof.get("manifest_digest") != digest or manifest["manifest_digest"] != digest:
                    raise KernelError("EDITION_ACCEPTANCE_SCOPE_INVALID", "Selected manuscript requires its exact immutable validation proof")
                book_run_id = str(proof.get("validation_book_run_id") or proof.get("source_book_run_id") or "")
                accepted = proof.get("accepted_units")
                if accepted is None and proof.get("kind") == "ORIGINAL_ACCEPTED_MANUSCRIPT":
                    accepted = manifest["sources"]
                acceptance_ids = tuple(str(item.get("acceptance_id") or "") for item in (accepted or []))
                if (not book_run_id or len(acceptance_ids) != len(manifest["units"])
                    or not all(acceptance_ids) or len(set(acceptance_ids)) != len(acceptance_ids)):
                    raise KernelError("EDITION_ACCEPTANCE_SCOPE_INVALID", "Selected manuscript must bind every accepted unit without extending its frozen boundary")
        self.cursor.execute("""SELECT book_run_id FROM authority_book_production
            WHERE project_id=%s AND book_id=%s AND (%s='' OR book_run_id=%s) ORDER BY book_run_id LIMIT 2""",
            [project_id,book_id,book_run_id,book_run_id])
        runs = self.cursor.fetchall()
        if len(runs) != 1:
            raise KernelError("EDITION_BOOK_RUN_REQUIRED", "Accepted facts require an exact run, a selected edition, or one unambiguous historical Book run")
        return str(runs[0][0]), acceptance_ids

    def book(self, *, project_id: str, workspace_id: str, book_run_id: str, for_update: bool = True) -> dict[str, Any]:
        self.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE project_id=%s AND workspace_id=%s AND book_run_id=%s" + (" FOR UPDATE" if for_update else ""),
                            [project_id, workspace_id, book_run_id])
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("EDITION_BOOK_SCOPE_INVALID", "Exact project, workspace and Book run are required")
        return dict(row[0])

    def revision(self, *, project_id: str, revision_id: str, book_id: str = "", for_update: bool = True) -> dict[str, Any]:
        self.cursor.execute("""SELECT to_jsonb(r),to_jsonb(e),v.content,v.content_hash FROM authority_book_edition_revision r
            JOIN authority_book_edition e USING(edition_id) JOIN authority_asset_version v ON v.asset_version_id=r.revision_id
            WHERE e.project_id=%s AND r.revision_id=%s AND (%s='' OR e.book_id=%s)""" + (" FOR UPDATE OF e" if for_update else ""),
            [project_id, revision_id, book_id, book_id])
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("EDITION_REVISION_NOT_FOUND", "Revision does not belong to the exact Book scope")
        return {**row[0], "edition": row[1], "manifest": row[2], "content_hash": row[3]}

    def events(self, revision_id: str) -> list[dict[str, Any]]:
        self.cursor.execute("SELECT to_jsonb(e) FROM authority_book_edition_event e WHERE revision_id=%s ORDER BY created_at,event_id", [revision_id])
        return [dict(row[0]) for row in self.cursor.fetchall()]

    def event(self, *, revision_id: str, kind: str, content: dict[str, Any], operation_id: str) -> None:
        self.cursor.execute("INSERT INTO authority_book_edition_event(event_id,revision_id,event_kind,content,created_by_operation_id) VALUES(%s,%s,%s,%s,%s)",
                            [str(uuid4()), revision_id, kind, Jsonb(content), operation_id])

    def head(self, book_id: str, *, for_update: bool = True) -> dict[str, Any]:
        self.cursor.execute("SELECT to_jsonb(h) FROM authority_book_edition_head h WHERE book_id=%s" + (" FOR UPDATE" if for_update else ""), [book_id])
        row = self.cursor.fetchone()
        return dict(row[0]) if row else {"book_id": book_id, "version": 0, "selected_revision_id": ""}

    def run_binding(self, book_run_id: str) -> dict[str, Any] | None:
        self.cursor.execute("SELECT to_jsonb(b) FROM authority_book_edition_run b WHERE book_run_id=%s", [book_run_id])
        row = self.cursor.fetchone()
        return dict(row[0]) if row else None

    def record_revision(self, *, revision_id: str, edition_id: str, revision_number: int,
                        predecessor_revision_id: str, base_revision_id: str, digest: str, operation_id: str) -> None:
        self.cursor.execute("""INSERT INTO authority_book_edition_revision(revision_id,edition_id,revision_number,
            predecessor_revision_id,base_revision_id,manifest_digest,created_by_operation_id)
            VALUES(%s,%s,%s,NULLIF(%s,''),NULLIF(%s,''),%s,%s)""",
            [revision_id, edition_id, revision_number, predecessor_revision_id, base_revision_id, digest, operation_id])

    def select(self, *, book_id: str, revision_id: str, expected_version: int, operation_id: str) -> int:
        self.cursor.execute("""INSERT INTO authority_book_edition_head(book_id,selected_revision_id,version,updated_by_operation_id)
            VALUES(%s,%s,1,%s) ON CONFLICT(book_id) DO UPDATE SET selected_revision_id=EXCLUDED.selected_revision_id,
            version=authority_book_edition_head.version+1,updated_by_operation_id=EXCLUDED.updated_by_operation_id
            WHERE authority_book_edition_head.version=%s RETURNING version""", [book_id, revision_id, operation_id, expected_version])
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("EDITION_SELECTION_CONFLICT", "The selected manuscript changed; reload without losing the candidate")
        return int(row[0])
