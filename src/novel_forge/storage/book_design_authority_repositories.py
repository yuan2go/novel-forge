from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from novel_forge.modules.book_design_authority.domain import (
    BOOK_DESIGN_SCHEMA_VERSION,
    EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignPayload,
    BookScope,
    evidence_hash,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.story_design_authority import required_qualification_profiles
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)


_PROGRESSIVE_BOOK_DESIGN_SCHEMAS = {
    BOOK_DESIGN_SCHEMA_VERSION,
    EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
}


class BookDesignAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create_book(
        self,
        *,
        scope: BookScope,
        book_asset_version_id: str,
        operation_id: str,
    ) -> None:
        self.cursor.execute(
            "SELECT project_id, book_id FROM authority_workspace WHERE workspace_id = %s FOR SHARE",
            [scope.workspace_id],
        )
        row = self.cursor.fetchone()
        if row is None or row[0] != scope.project_id:
            raise KernelError(
                "BOOK_SCOPE_CONFLICT", "workspace does not belong to project"
            )
        if row[1] and row[1] != scope.book_id:
            raise KernelError(
                "BOOK_SCOPE_CONFLICT", "workspace is already bound to another book"
            )
        self.cursor.execute(
            """
            INSERT INTO authority_book (
                book_id, project_id, workspace_id, principal_id, service_identity,
                book_scope, production_profile, runtime_policy, release_identity,
                status, current_book_asset_version_id, created_by_operation_id,
                last_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                      'DESIGN_PENDING', %s, %s, %s)
            """,
            [
                scope.book_id,
                scope.project_id,
                scope.workspace_id,
                scope.principal,
                scope.service_identity,
                Jsonb(
                    {
                        "project_id": scope.project_id,
                        "workspace_id": scope.workspace_id,
                        "book_id": scope.book_id,
                    }
                ),
                Jsonb(scope.production_profile),
                Jsonb(scope.runtime_policy),
                scope.release_identity,
                book_asset_version_id,
                operation_id,
                operation_id,
            ],
        )
        self.cursor.execute(
            "UPDATE authority_workspace SET book_id = %s, updated_at = NOW() WHERE workspace_id = %s AND project_id = %s",
            [scope.book_id, scope.workspace_id, scope.project_id],
        )

    def book_for_update(
        self, *, project_id: str, workspace_id: str, book_id: str
    ) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT book_id, project_id, workspace_id, version,
                   current_book_asset_version_id,
                   COALESCE(current_book_design_asset_version_id, ''), status
            FROM authority_book
            WHERE book_id = %s AND project_id = %s AND workspace_id = %s
            FOR UPDATE
            """,
            [book_id, project_id, workspace_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_NOT_FOUND", "Book authority root does not exist in scope"
            )
        return {
            "book_id": row[0],
            "project_id": row[1],
            "workspace_id": row[2],
            "version": int(row[3]),
            "book_asset_version_id": row[4],
            "current_design_asset_version_id": row[5],
            "status": row[6],
        }

    def propose(
        self,
        *,
        book: dict[str, Any],
        design: BookDesignPayload,
        operation_id: str,
        trace_id: str,
        checkpoint: Callable[[str], None],
    ) -> dict[str, str]:
        if design.schema_version == FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION:
            current_foundation = require_current_foundation_set(
                self.cursor,
                project_id=book["project_id"],
                book_id=book["book_id"],
            )
            if (
                design.foundation_set is None
                or design.foundation_set != current_foundation
            ):
                raise KernelError(
                    "BOOK_DESIGN_FOUNDATION_SET_STALE",
                    "BookDesign v5 must bind the exact current qualified Foundation Set",
                )
        asset_id = f"book-design:{book['book_id']}"
        self.cursor.execute(
            """
            INSERT INTO authority_asset (asset_id, project_id, asset_type)
            VALUES (%s, %s, 'book_design') ON CONFLICT (asset_id) DO NOTHING
            """,
            [asset_id, book["project_id"]],
        )
        self.cursor.execute(
            "SELECT project_id, asset_type FROM authority_asset WHERE asset_id = %s FOR UPDATE",
            [asset_id],
        )
        if self.cursor.fetchone() != (book["project_id"], "book_design"):
            raise KernelError(
                "BOOK_DESIGN_ASSET_CONFLICT", "BookDesign Asset identity has drifted"
            )
        self.cursor.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM authority_asset_version WHERE asset_id = %s",
            [asset_id],
        )
        version_number = int(self.cursor.fetchone()[0])
        asset_version_id = str(uuid4())
        content = design.to_dict()
        structurally_valid = True
        eligibility = (
            "ELIGIBLE"
            if design.schema_version not in _PROGRESSIVE_BOOK_DESIGN_SCHEMAS
            else "INELIGIBLE"
        )
        candidate_status = (
            "VALIDATED"
            if design.schema_version not in _PROGRESSIVE_BOOK_DESIGN_SCHEMAS
            else "EVALUATION_PENDING"
        )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version (
                asset_version_id, asset_id, version_number, lifecycle,
                eligibility, governance, content, content_hash, schema_version
            ) VALUES (%s, %s, %s, 'CANDIDATE', %s, 'CLEAR', %s, %s, %s)
            """,
            [
                asset_version_id,
                asset_id,
                version_number,
                eligibility,
                Jsonb(content),
                design.content_hash,
                design.schema_version,
            ],
        )
        checkpoint("after_asset_version_insert")
        if design.foundation_set is not None:
            for binding in design.foundation_set.bindings:
                self.cursor.execute(
                    """
                    INSERT INTO authority_asset_dependency (
                        dependency_id, project_id, book_id,
                        source_asset_version_id, target_asset_version_id,
                        dependency_type, created_by_operation_id
                    ) VALUES (%s,%s,%s,%s,%s,'REQUIRED',%s)
                    """,
                    [
                        str(uuid4()),
                        book["project_id"],
                        book["book_id"],
                        asset_version_id,
                        binding.asset_version_id,
                        operation_id,
                    ],
                )
        validation = {
            "schema_version": "book-design-validation.v3",
            "validator": "BookDesignPayload.from_mapping",
            "valid": structurally_valid,
            "trace_id": trace_id,
            "content_hash": design.content_hash,
            "semantic_evaluation_status": (
                "NOT_REQUIRED_LEGACY"
                if design.schema_version not in _PROGRESSIVE_BOOK_DESIGN_SCHEMAS
                else "EVALUATION_PENDING"
            ),
            "candidate_generation_does_not_evaluate_itself": True,
        }
        self.cursor.execute(
            """
            INSERT INTO authority_asset_qualification (
                qualification_id, asset_version_id, policy_version, decision, evidence
            ) VALUES (%s, %s, 'book-design-validator.v3', %s, %s)
            """,
            [str(uuid4()), asset_version_id, eligibility, Jsonb(validation)],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_book_design_candidate (
                candidate_id, project_id, workspace_id, book_id, asset_id,
                asset_version_id, schema_version, content_hash, status,
                created_by_operation_id, last_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                f"candidate:{asset_version_id}",
                book["project_id"],
                book["workspace_id"],
                book["book_id"],
                asset_id,
                asset_version_id,
                design.schema_version,
                design.content_hash,
                candidate_status,
                operation_id,
                operation_id,
            ],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_dependency (
                dependency_id, project_id, book_id, source_asset_version_id,
                target_asset_version_id, dependency_type, created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, 'REQUIRED', %s)
            """,
            [
                str(uuid4()),
                book["project_id"],
                book["book_id"],
                asset_version_id,
                book["book_asset_version_id"],
                operation_id,
            ],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_evidence (
                evidence_id, project_id, book_id, asset_version_id, evidence_type,
                schema_version, evidence, evidence_hash, created_by_operation_id
            ) VALUES (%s, %s, %s, %s, 'DOMAIN_VALIDATION',
                      'book-design-validation.v3', %s, %s, %s)
            """,
            [
                str(uuid4()),
                book["project_id"],
                book["book_id"],
                asset_version_id,
                Jsonb(validation),
                evidence_hash(validation),
                operation_id,
            ],
        )
        self._bind_output(
            operation_id=operation_id,
            asset_id=asset_id,
            asset_version_id=asset_version_id,
            output_key="book_design.candidate",
            role="candidate",
            content_hash=design.content_hash,
        )
        return {
            "asset_id": asset_id,
            "asset_version_id": asset_version_id,
            "content_hash": design.content_hash,
            "status": candidate_status,
        }

    def complete_semantic_evaluation(
        self,
        *,
        book: dict[str, Any],
        asset_version_id: str,
        generation_operation_id: str,
        evaluation_operation_id: str,
        passed: bool,
    ) -> dict[str, str]:
        candidate = self._candidate_for_update(book, asset_version_id)
        if candidate["schema_version"] not in _PROGRESSIVE_BOOK_DESIGN_SCHEMAS:
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_NOT_REQUIRED",
                "legacy BookDesign candidates do not enter the independent evaluation path",
            )
        if candidate["schema_version"] == FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION:
            self._require_v5_foundation(book, asset_version_id)
        target_status = "VALIDATED" if passed else "REJECTED"
        target_eligibility = "ELIGIBLE" if passed else "INELIGIBLE"
        if (
            candidate["status"] == target_status
            and candidate["last_operation_id"] == evaluation_operation_id
        ):
            return {
                "asset_version_id": asset_version_id,
                "status": target_status,
                "eligibility": target_eligibility,
            }
        if candidate["status"] != "EVALUATION_PENDING":
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_CONFLICT",
                "BookDesign candidate evaluation is already terminal",
            )
        if candidate["created_by_operation_id"] != generation_operation_id:
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_LINEAGE_INVALID",
                "BookDesign evaluation differs from candidate generation lineage",
            )
        self.cursor.execute(
            """
            UPDATE authority_book_design_candidate
            SET status=%s, last_operation_id=%s, updated_at=NOW()
            WHERE asset_version_id=%s AND status='EVALUATION_PENDING'
            """,
            [target_status, evaluation_operation_id, asset_version_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_CONFLICT",
                "BookDesign candidate changed during semantic evaluation",
            )
        self.cursor.execute(
            """
            UPDATE authority_asset_version
            SET eligibility=%s
            WHERE asset_version_id=%s AND lifecycle='CANDIDATE'
            """,
            [target_eligibility, asset_version_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_DESIGN_EVALUATION_CONFLICT",
                "BookDesign AssetVersion is no longer an activatable candidate",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_qualification(
                qualification_id, asset_version_id, policy_version,
                decision, evidence
            ) VALUES (%s, %s, 'independent-narrative-evaluation-v1', %s, %s)
            ON CONFLICT (qualification_id) DO NOTHING
            """,
            [
                evidence_hash(
                    {
                        "asset_version_id": asset_version_id,
                        "evaluation_operation_id": evaluation_operation_id,
                    }
                ),
                asset_version_id,
                target_eligibility,
                Jsonb(
                    {
                        "schema_version": "book-design-semantic-evaluation.v1",
                        "generation_operation_id": generation_operation_id,
                        "evaluation_operation_id": evaluation_operation_id,
                        "status": "PASS" if passed else "FAIL",
                        "trust_boundary": "INDEPENDENT",
                    }
                ),
            ],
        )
        return {
            "asset_version_id": asset_version_id,
            "status": target_status,
            "eligibility": target_eligibility,
        }

    def decide(
        self,
        *,
        book: dict[str, Any],
        asset_version_id: str,
        decision: str,
        reason: str,
        decided_by: str,
        operation_id: str,
    ) -> str:
        candidate = self._candidate_for_update(book, asset_version_id)
        if candidate["status"] != "VALIDATED":
            raise KernelError(
                "BOOK_DESIGN_DECISION_CONFLICT",
                "only a validated candidate can be decided",
            )
        if candidate["schema_version"] == FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION:
            self._require_v5_foundation(book, asset_version_id)
        if candidate["schema_version"] in _PROGRESSIVE_BOOK_DESIGN_SCHEMAS:
            self._require_progressive_qualification(book, asset_version_id)
        normalized = decision.strip().upper()
        if normalized not in {"APPROVE", "REJECT"}:
            raise KernelError(
                "BOOK_DESIGN_DECISION_INVALID", "decision must be APPROVE or REJECT"
            )
        decision_id = str(uuid4())
        self.cursor.execute(
            """
            INSERT INTO authority_asset_decision (
                decision_id, project_id, book_id, asset_version_id, decision,
                reason, decided_by, decided_by_operation_id, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                decision_id,
                book["project_id"],
                book["book_id"],
                asset_version_id,
                normalized,
                reason,
                decided_by,
                operation_id,
                Jsonb(
                    {
                        "schema_version": "asset-decision.v1",
                        "decision": normalized,
                        "reason": reason,
                    }
                ),
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_design_candidate
            SET status = %s, last_operation_id = %s, updated_at = NOW()
            WHERE asset_version_id = %s
            """,
            [
                "APPROVED" if normalized == "APPROVE" else "REJECTED",
                operation_id,
                asset_version_id,
            ],
        )
        return decision_id

    def activate(
        self,
        *,
        book: dict[str, Any],
        asset_version_id: str,
        reason: str,
        operation_id: str,
    ) -> dict[str, str]:
        candidate = self._candidate_for_update(book, asset_version_id)
        if candidate["status"] != "APPROVED":
            raise KernelError(
                "BOOK_DESIGN_ACTIVATION_CONFLICT",
                "only an approved candidate can activate",
            )
        if candidate["schema_version"] == FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION:
            self._require_v5_foundation(book, asset_version_id)
        self.cursor.execute(
            """
            SELECT decision_id FROM authority_asset_decision
            WHERE asset_version_id = %s AND decision = 'APPROVE'
            ORDER BY created_at DESC LIMIT 1
            """,
            [asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_DESIGN_APPROVAL_MISSING", "approval decision is missing"
            )
        decision_id = str(row[0])
        previous = str(book["current_design_asset_version_id"] or "")
        self.cursor.execute(
            """
            UPDATE authority_asset_activation SET retired_at = NOW()
            WHERE asset_id = %s AND book_id = %s AND retired_at IS NULL
            """,
            [candidate["asset_id"], book["book_id"]],
        )
        if previous:
            self.cursor.execute(
                "UPDATE authority_asset_version SET lifecycle = 'SUPERSEDED' WHERE asset_version_id = %s AND lifecycle = 'ACTIVE'",
                [previous],
            )
            if self.cursor.rowcount != 1:
                raise KernelError(
                    "BOOK_DESIGN_SUPERSESSION_CONFLICT",
                    "previous active version changed",
                )
            self.cursor.execute(
                "UPDATE authority_book_design_candidate SET status = 'SUPERSEDED', updated_at = NOW() WHERE asset_version_id = %s AND status = 'ACTIVE'",
                [previous],
            )
            self.cursor.execute(
                """
                INSERT INTO authority_asset_supersession (
                    supersession_id, project_id, book_id, previous_asset_version_id,
                    successor_asset_version_id, superseded_by_operation_id, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    str(uuid4()),
                    book["project_id"],
                    book["book_id"],
                    previous,
                    asset_version_id,
                    operation_id,
                    reason,
                ],
            )
        self.cursor.execute(
            "UPDATE authority_asset_version SET lifecycle = 'ACTIVE' WHERE asset_version_id = %s AND lifecycle = 'CANDIDATE'",
            [asset_version_id],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_DESIGN_ACTIVATION_CONFLICT", "candidate lifecycle changed"
            )
        logical_ref = f"books/{book['book_id']}/design"
        self.cursor.execute(
            """
            INSERT INTO authority_asset_locator (
                project_id, logical_ref, category, asset_id, current_asset_version_id
            ) VALUES (%s, %s, 'book-designs', %s, %s)
            ON CONFLICT (project_id, logical_ref) DO UPDATE SET
                current_asset_version_id = EXCLUDED.current_asset_version_id,
                updated_at = NOW()
            """,
            [book["project_id"], logical_ref, candidate["asset_id"], asset_version_id],
        )
        activation_id = str(uuid4())
        self.cursor.execute(
            """
            INSERT INTO authority_asset_activation (
                activation_id, project_id, book_id, asset_id, asset_version_id,
                decision_id, activated_by_operation_id, effective_from_chapter,
                activation_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s)
            """,
            [
                activation_id,
                book["project_id"],
                book["book_id"],
                candidate["asset_id"],
                asset_version_id,
                decision_id,
                operation_id,
                reason,
            ],
        )
        self.cursor.execute(
            """
            UPDATE authority_book_design_candidate
            SET status = 'ACTIVE', last_operation_id = %s, updated_at = NOW()
            WHERE asset_version_id = %s
            """,
            [operation_id, asset_version_id],
        )
        self.cursor.execute(
            """
            UPDATE authority_book
            SET current_book_design_asset_version_id = %s, status = 'DESIGN_ACTIVE',
                last_operation_id = %s, version = version + 1, updated_at = NOW()
            WHERE book_id = %s AND version = %s
            """,
            [asset_version_id, operation_id, book["book_id"], book["version"]],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "BOOK_VERSION_CONFLICT", "Book projection changed during activation"
            )
        self._bind_output(
            operation_id=operation_id,
            asset_id=candidate["asset_id"],
            asset_version_id=asset_version_id,
            output_key="book_design.active",
            role="active",
            content_hash=candidate["content_hash"],
        )
        return {"activation_id": activation_id, "previous_asset_version_id": previous}

    def _candidate_for_update(
        self, book: dict[str, Any], asset_version_id: str
    ) -> dict[str, str]:
        self.cursor.execute(
            """
            SELECT asset_id, asset_version_id, content_hash, status,
                   schema_version, created_by_operation_id, last_operation_id
            FROM authority_book_design_candidate
            WHERE project_id = %s AND workspace_id = %s AND book_id = %s
              AND asset_version_id = %s
            FOR UPDATE
            """,
            [
                book["project_id"],
                book["workspace_id"],
                book["book_id"],
                asset_version_id,
            ],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "BOOK_DESIGN_CANDIDATE_NOT_FOUND", "candidate is outside Book scope"
            )
        return {
            "asset_id": row[0],
            "asset_version_id": row[1],
            "content_hash": row[2],
            "status": row[3],
            "schema_version": row[4],
            "created_by_operation_id": row[5],
            "last_operation_id": row[6],
        }

    def _require_progressive_qualification(
        self, book: dict[str, Any], asset_version_id: str
    ) -> None:
        expected = {
            profile.layer.value: profile
            for profile in required_qualification_profiles("book_design.propose")
        }
        self.cursor.execute(
            """
            SELECT design_layer, profile_id, profile_version, profile_hash
            FROM authority_narrative_design_qualification
            WHERE project_id=%s AND book_id=%s AND asset_version_id=%s
              AND qualification_status='PASS'
              AND trust_boundary='INDEPENDENT'
              AND generation_operation_id=(
                  SELECT created_by_operation_id
                  FROM authority_book_design_candidate
                  WHERE asset_version_id=%s
              )
            ORDER BY design_layer
            """,
            [
                book["project_id"],
                book["book_id"],
                asset_version_id,
                asset_version_id,
            ],
        )
        rows = self.cursor.fetchall()
        actual = {str(row[0]): row for row in rows}
        if set(actual) != set(expected) or len(rows) != len(expected):
            raise KernelError(
                "BOOK_DESIGN_NARRATIVE_QUALIFICATION_REQUIRED",
                "BookDesign decision requires Story Intent and Foundation qualification",
            )
        for layer, profile in expected.items():
            if tuple(str(item) for item in actual[layer][1:4]) != (
                profile.profile_id,
                profile.profile_version,
                profile.profile_hash,
            ):
                raise KernelError(
                    "BOOK_DESIGN_NARRATIVE_QUALIFICATION_STALE",
                    "BookDesign qualification profile differs from current policy",
                )

    def _require_v5_foundation(
        self, book: dict[str, Any], asset_version_id: str
    ) -> None:
        self.cursor.execute(
            """
            SELECT content
            FROM authority_asset_version
            WHERE asset_version_id=%s
            """,
            [asset_version_id],
        )
        content_row = self.cursor.fetchone()
        if content_row is None:
            raise KernelError(
                "BOOK_DESIGN_CANDIDATE_NOT_FOUND", "BookDesign candidate disappeared"
            )
        design = BookDesignPayload.from_mapping(dict(content_row[0]))
        current_foundation = require_current_foundation_set(
            self.cursor,
            project_id=book["project_id"],
            book_id=book["book_id"],
        )
        if design.foundation_set is None or design.foundation_set != current_foundation:
            raise KernelError(
                "BOOK_DESIGN_FOUNDATION_SET_STALE",
                "Foundation Set changed after BookDesign qualification",
            )

    def _bind_output(
        self,
        *,
        operation_id: str,
        asset_id: str,
        asset_version_id: str,
        output_key: str,
        role: str,
        content_hash: str,
    ) -> None:
        self.cursor.execute(
            """
            INSERT INTO authority_operation_output_asset (
                operation_id, asset_id, asset_version_id, output_key, role, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [operation_id, asset_id, asset_version_id, output_key, role, content_hash],
        )


__all__ = ["BookDesignAuthorityRepository"]
