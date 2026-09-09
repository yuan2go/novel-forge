from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.corpus import (
    CorpusPurpose,
    CorpusUse,
    RightsDeclaration,
    corpus_identity,
    corpus_use_admission,
)


from .corpus_processing_records import CorpusProcessingRecords


class CorpusIngestionRecords(CorpusProcessingRecords):
    cursor: Any

    def require_corpus_acquisition(
        self,
        project_id: str,
        *,
        source_id: str,
        workspace_id: str,
        source_kind: str,
        location: str,
        rights_id: str | None,
        declaration: RightsDeclaration,
        purpose: CorpusPurpose,
    ) -> None:
        self.corpus_authorization_lock(project_id)
        if self.corpus_existing("source", project_id, source_id):
            source = self.corpus_source_lock(project_id, source_id)
            if (
                source["retired"]
                or source["purpose"] != purpose.value
                or source["workspace_id"] != workspace_id
                or source["source_kind"].upper() != source_kind
                or source["external_identity"] != location
            ):
                raise KernelError(
                    "CORPUS_ACQUISITION_DENIED", "source retired or purpose changed"
                )
            current = self.corpus_latest("rights", project_id, source_id)
            if current:
                stored = self.corpus_record("rights", project_id, current)
                if (rights_id and rights_id != current) or stored[
                    "declaration"
                ] != declaration.model_dump(mode="json"):
                    raise KernelError(
                        "CORPUS_ACQUISITION_RIGHTS_STALE",
                        "freeze the exact current rights declaration",
                    )
                declaration = RightsDeclaration.model_validate(stored["declaration"])
        elif rights_id:
            raise KernelError(
                "CORPUS_REFERENCE_NOT_FOUND", "source does not exist in this project"
            )
        if (
            purpose not in declaration.allowed_purposes
            or purpose in declaration.denied_purposes
            or CorpusUse.LOCAL_PROCESSING not in declaration.allowed_uses
        ):
            raise KernelError(
                "CORPUS_ACQUISITION_DENIED",
                "explicit acquisition/processing purpose authorization is required",
            )

    def corpus_bind_content(self, row: dict[str, Any]) -> dict[str, Any]:
        row = {
            **row,
            "content_id": corpus_identity(
                "content", row["snapshot_id"], row["role"], row["path"], row["blob_id"]
            ),
        }
        self.cursor.execute(
            """
            INSERT INTO authority_corpus_content(content_id,project_id,snapshot_id,edition_id,blob_id,role,path,content_hash,byte_size,locator,acquisition_effect_id,created_by_operation_id)
            VALUES (%(content_id)s,%(project_id)s,%(snapshot_id)s,%(edition_id)s,%(blob_id)s,%(role)s,%(path)s,%(content_hash)s,%(byte_size)s,%(locator)s,%(acquisition_effect_id)s,%(created_by_operation_id)s)
            ON CONFLICT(content_id) DO NOTHING
        """,
            {**row, "locator": Jsonb(row["locator"])},
        )
        self.cursor.execute(
            "SELECT to_jsonb(c) FROM authority_corpus_content c WHERE content_id=%s",
            [row["content_id"]],
        )
        stored = dict(self.cursor.fetchone()[0])
        for key, value in row.items():
            if key != "created_by_operation_id" and stored[key] != value:
                raise KernelError("CORPUS_CONTENT_IDENTITY_CONFLICT", key)
        return stored

    def corpus_bind_bridge(self, row: dict[str, Any]) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_corpus_bridge(edition_id,project_id,source_document_id,source_transform_id,source_work_asset_version_id,rights_id,parser_hash,normalized_hash,policy_version,evidence,created_by_operation_id)
            VALUES (%(edition_id)s,%(project_id)s,%(source_document_id)s,%(source_transform_id)s,%(source_work_asset_version_id)s,%(rights_id)s,%(parser_hash)s,%(normalized_hash)s,%(policy_version)s,%(evidence)s,%(created_by_operation_id)s)
            ON CONFLICT(edition_id,source_work_asset_version_id) DO NOTHING
        """,
            {**row, "evidence": Jsonb(row["evidence"])},
        )
        self.cursor.execute(
            "SELECT to_jsonb(b) FROM authority_corpus_bridge b WHERE edition_id=%s AND source_work_asset_version_id=%s",
            [row["edition_id"], row["source_work_asset_version_id"]],
        )
        stored = self.cursor.fetchone()[0]
        if any(
            stored[key] != value
            for key, value in row.items()
            if key != "created_by_operation_id"
        ):
            raise KernelError(
                "CORPUS_BRIDGE_IDENTITY_CONFLICT", "frozen bridge differs"
            )

    def corpus_edition_uses(
        self,
        project_id: str,
        edition_ids: tuple[str, ...],
        use: CorpusUse,
        *,
        require_bridge: bool = True,
    ) -> dict[str, dict[str, Any]]:
        self.corpus_authorization_lock(project_id)
        result = {}
        for offset in range(0, len(edition_ids), 100):
            self.cursor.execute(
                """
                SELECT e.edition_id,s.purpose,r.declaration,b.external_work_id,
                    EXISTS(SELECT 1 FROM authority_corpus_retirement rt WHERE rt.source_id=s.source_id),
                    NOT EXISTS(SELECT 1 FROM authority_corpus_rights next WHERE next.previous_rights_id=r.rights_id),
                    bridge.edition_id,sn.snapshot_id,r.rights_id,s.source_id,bridge.evidence,
                    EXISTS(SELECT 1 FROM authority_corpus_membership m WHERE m.edition_id=e.edition_id AND m.purpose=s.purpose)
                FROM authority_corpus_edition e
                JOIN authority_corpus_snapshot sn ON sn.snapshot_id=e.snapshot_id AND sn.project_id=e.project_id
                JOIN authority_corpus_source s ON s.source_id=e.source_id
                JOIN authority_corpus_rights r ON r.rights_id=sn.rights_id
                JOIN authority_corpus_book_identity b ON b.book_source_id=e.book_source_id
                LEFT JOIN LATERAL (SELECT b.* FROM authority_corpus_bridge b
                    JOIN authority_source_work_version w ON w.asset_version_id=b.source_work_asset_version_id AND w.status='ACTIVE'
                    WHERE b.edition_id=e.edition_id AND b.project_id=e.project_id) bridge ON true
                WHERE e.project_id=%s AND e.edition_id=ANY(%s)
                ORDER BY e.edition_id
            """,
                [project_id, list(edition_ids[offset : offset + 100])],
            )
            for row in self.cursor.fetchall():
                decision = corpus_use_admission(
                    rights=RightsDeclaration.model_validate(row[2]),
                    source_purpose=CorpusPurpose(row[1]),
                    use=use,
                    external_work_id=str(row[3]),
                    retired=bool(row[4]),
                    rights_current=bool(row[5]),
                )
                reasons = (
                    list(decision["reasons"]) if decision["decision"] == "DENY" else []
                )
                if require_bridge and not row[6]:
                    reasons.append("CORPUS_BRIDGE_MISSING")
                if (
                    require_bridge
                    and row[10]
                    and row[10].get("completeness") == "REVIEW_REQUIRED"
                ):
                    reasons.append("CORPUS_STRUCTURE_REVIEW_REQUIRED")
                if not row[11]:
                    reasons.append("CORPUS_MEMBERSHIP_MISSING")
                result[str(row[0])] = {
                    **decision,
                    "decision": "DENY" if reasons else "ALLOW",
                    "reasons": reasons or decision["reasons"],
                    "snapshot_id": row[7],
                    "rights_id": row[8],
                    "source_id": row[9],
                    "declaration": row[2],
                    "external_work_id": row[3],
                }
        return result

    def require_corpus_edition_use(
        self,
        project_id: str,
        edition_id: str,
        use: CorpusUse,
        *,
        require_bridge: bool = True,
    ) -> dict[str, Any]:
        decisions = self.corpus_edition_uses(
            project_id, (edition_id,), use, require_bridge=require_bridge
        )
        decision = decisions.get(edition_id)
        if decision is None or decision["decision"] != "ALLOW":
            raise KernelError(
                "CORPUS_USE_DENIED",
                str(decision["reasons"] if decision else ["EDITION_SCOPE_MISSING"]),
            )
        return decision

    def corpus_document_denials(
        self, project_id: str, document_ids: tuple[str, ...], use: CorpusUse
    ) -> dict[str, str]:
        self.corpus_authorization_lock(project_id)
        denied: dict[str, str] = {}
        for offset in range(0, len(document_ids), 100):
            self.cursor.execute(
                """
                SELECT d.source_document_id,d.corpus_edition_id,
                    EXISTS(SELECT 1 FROM authority_corpus_content c WHERE c.project_id=d.project_id AND c.content_hash=d.source_content_hash),
                    EXISTS(
                        SELECT 1 FROM (
                            SELECT f.repository_snapshot_asset_version_id,f.path FROM authority_source_repository_file f WHERE f.source_document_id=d.source_document_id AND f.project_id=d.project_id
                            UNION SELECT w.repository_snapshot_asset_version_id,u.raw_file_path FROM authority_source_work_version w
                                JOIN authority_source_unit_version u ON u.source_work_asset_version_id=w.asset_version_id
                                WHERE w.source_document_id=d.source_document_id AND w.project_id=d.project_id
                        ) acquisition
                        JOIN authority_source_repository_snapshot rs ON rs.asset_version_id=acquisition.repository_snapshot_asset_version_id
                        JOIN authority_corpus_snapshot cs ON cs.project_id=d.project_id AND (
                            cs.repository_snapshot_asset_version_id=rs.asset_version_id OR
                            (cs.manifest->'metadata'->'source'->>'kind'='GITHUB' AND
                             cs.manifest->'metadata'->'source'->>'repository'=rs.repository_url AND
                             cs.manifest->'metadata'->'source'->>'commit'=rs.resolved_commit_sha AND
                             EXISTS(SELECT 1 FROM jsonb_array_elements(cs.manifest->'metadata'->'source'->'files') selected WHERE selected->>'path'=acquisition.path)))
                    )
                FROM authority_source_document d WHERE d.project_id=%s AND d.source_document_id=ANY(%s)
            """,
                [project_id, list(document_ids[offset : offset + 100])],
            )
            rows = self.cursor.fetchall()
            editions = tuple(str(row[1]) for row in rows if row[1])
            decisions = self.corpus_edition_uses(project_id, editions, use)
            for document, edition, tainted, bound in rows:
                if edition:
                    decision = decisions.get(str(edition))
                    if decision is None or decision["decision"] != "ALLOW":
                        denied[str(document)] = str(
                            decision["reasons"]
                            if decision
                            else ["CORPUS_BRIDGE_MISSING"]
                        )
                elif tainted or bound:
                    denied[str(document)] = "CORPUS_BRIDGE_MISSING"
        denied.update(self.corpus_unbridged_documents(project_id, document_ids))
        if use != CorpusUse.LOCAL_PROCESSING:
            denied.update(self.corpus_processing_denials(project_id, document_ids))
        return denied

    def require_corpus_documents(
        self, project_id: str, document_ids: tuple[str, ...], use: CorpusUse
    ) -> None:
        denied = self.corpus_document_denials(project_id, document_ids, use)
        if denied:
            raise KernelError("MKAOS_CORPUS_BRIDGE_REQUIRED", str(denied))

    def require_corpus_registration(
        self, project_id: str, blob: dict[str, Any], edition_id: str | None
    ) -> dict[str, Any] | None:
        self.corpus_authorization_lock(project_id)
        self.cursor.execute(
            """SELECT
                EXISTS(SELECT 1 FROM authority_corpus_content WHERE project_id=%s AND content_hash=%s),
                EXISTS(SELECT 1 FROM authority_corpus_content WHERE project_id=%s AND content_hash=%s AND edition_id=%s AND role='RAW_BUNDLE')""",
            [
                project_id,
                blob["actual_hash"],
                project_id,
                blob["actual_hash"],
                edition_id,
            ],
        )
        has_origin, owns_bundle = self.cursor.fetchone()
        if edition_id is None:
            if has_origin or str(blob.get("object_key", "")).startswith(
                f"source-import/{project_id}/corpus-"
            ):
                raise KernelError(
                    "CORPUS_DOCUMENT_LINEAGE_REQUIRED",
                    "Corpus bytes cannot enter legacy Source registration without an exact Edition",
                )
            return None
        if not owns_bundle:
            raise KernelError(
                "CORPUS_DOCUMENT_LINEAGE_REQUIRED",
                "Edition does not own the verified raw bundle",
            )
        return self.require_corpus_edition_use(
            project_id, edition_id, CorpusUse.LOCAL_PROCESSING, require_bridge=False
        )

    def corpus_content_page(
        self, project_id: str, snapshot_id: str, after: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("page limit must be 1..100")
        self.cursor.execute(
            "SELECT to_jsonb(c) FROM authority_corpus_content c WHERE project_id=%s AND snapshot_id=%s AND content_id>%s ORDER BY content_id LIMIT %s",
            [project_id, snapshot_id, after, limit],
        )
        return [dict(row[0]) for row in self.cursor.fetchall()]

    def require_corpus_execution_assets(
        self, project_id: str, identities: tuple[str, ...], use: CorpusUse
    ) -> None:
        self.corpus_authorization_lock(project_id)
        pending, visited, documents = set(identities), set(), set()
        for _depth in range(10):
            if not pending:
                break
            if len(pending | visited) > 4096:
                raise KernelError(
                    "CORPUS_LINEAGE_QUERY_BOUND", "split the consumption batch"
                )
            current, pending = sorted(pending - visited), set()
            visited.update(current)
            for start in range(0, len(current), 100):
                batch = current[start : start + 100]
                self.cursor.execute(
                    """
                    SELECT source_document_id FROM authority_source_document WHERE project_id=%s AND (asset_version_id=ANY(%s) OR source_document_id=ANY(%s))
                    UNION SELECT source_document_id FROM authority_source_chunk WHERE project_id=%s AND asset_version_id=ANY(%s)
                    UNION SELECT source_document_id FROM authority_source_transform WHERE project_id=%s AND asset_version_id=ANY(%s)
                    UNION SELECT source_document_id FROM authority_source_work_version WHERE project_id=%s AND asset_version_id=ANY(%s)
                """,
                    [
                        project_id,
                        batch,
                        batch,
                        project_id,
                        batch,
                        project_id,
                        batch,
                        project_id,
                        batch,
                    ],
                )
                resolved = {str(row[0]) for row in self.cursor.fetchall()}
                if _depth == 0 and use == CorpusUse.ABSTRACT_GENERATION and resolved:
                    raise KernelError(
                        "CORPUS_RAW_CONTENT_FORBIDDEN",
                        "Source documents, transforms, works and chunks are not generation knowledge",
                    )
                documents.update(resolved)
                self.cursor.execute(
                    """
                    SELECT input_asset_version_id FROM authority_source_deconstruction_observation_input WHERE project_id=%s AND observation_asset_version_id=ANY(%s)
                    UNION SELECT c.asset_version_id FROM authority_mkaos_evidence_span e JOIN authority_source_chunk c USING(source_chunk_id)
                        WHERE e.project_id=%s AND e.candidate_asset_version_id=ANY(%s)
                    UNION SELECT candidate_asset_version_id FROM authority_mkaos_knowledge_card WHERE project_id=%s AND asset_version_id=ANY(%s)
                    UNION SELECT i.knowledge_card_asset_version_id FROM authority_mkaos_knowledge_pack_item i
                        JOIN authority_mkaos_knowledge_pack p USING(knowledge_pack_id)
                        WHERE p.project_id=%s AND (p.asset_version_id=ANY(%s) OR p.knowledge_pack_id=ANY(%s))
                """,
                    [
                        project_id,
                        batch,
                        project_id,
                        batch,
                        project_id,
                        batch,
                        project_id,
                        batch,
                        batch,
                    ],
                )
                pending.update(
                    str(row[0])
                    for row in self.cursor.fetchall()
                    if str(row[0]) not in visited
                )
        if pending:
            raise KernelError(
                "CORPUS_LINEAGE_QUERY_BOUND", "source lineage exceeds supported depth"
            )
        self.require_corpus_documents(project_id, tuple(sorted(documents)), use)
