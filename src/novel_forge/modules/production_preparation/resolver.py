from __future__ import annotations

from dataclasses import replace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_quality_authority import (
    load_accepted_quality_observations,
)
from novel_forge.modules.production_preparation.contracts import ResolvedProductionAsset
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class PostgresProductionAssetResolver:
    """Read-only resolver for latest qualified Authority AssetVersions."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def resolve_latest(
        self, *, project_id: str, asset_type: str
    ) -> ResolvedProductionAsset | None:
        if asset_type in {"story_state_snapshot", "canon_snapshot"}:
            states = self._resolve_accepted_states(
                project_id=project_id, asset_type=asset_type, limit=1
            )
            return states[0] if states else None
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id, asset.asset_id, version.asset_version_id,
                       asset.asset_type, version.content_hash, version.content,
                       COALESCE(qualification.decision, 'ELIGIBLE'),
                       producer.operation_id, producer.definition_name, producer.status
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id = asset.asset_id
                LEFT JOIN LATERAL (
                    SELECT decision
                    FROM authority_asset_qualification
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC
                    LIMIT 1
                ) AS qualification ON TRUE
                LEFT JOIN LATERAL (
                    SELECT operation.operation_id, operation.definition_name, operation.status
                    FROM authority_operation_output_asset AS binding
                    JOIN authority_operation AS operation
                      ON operation.operation_id = binding.operation_id
                    WHERE binding.asset_version_id = version.asset_version_id
                    ORDER BY binding.created_at DESC, operation.updated_at DESC
                    LIMIT 1
                ) AS producer ON TRUE
                WHERE asset.project_id = %s AND asset.asset_type = %s
                  AND version.lifecycle = 'ACTIVE'
                  AND version.eligibility = 'ELIGIBLE'
                  AND version.governance = 'CLEAR'
                  AND COALESCE(qualification.decision, 'ELIGIBLE') = 'ELIGIBLE'
                ORDER BY version.created_at DESC, version.version_number DESC,
                         version.asset_version_id DESC
                LIMIT 1
                """,
                [project_id, asset_type],
            )
            row = uow.cursor.fetchone()
        if row is None:
            return None
        return self._asset(row, "latest eligible authority version")

    def resolve_all(
        self, *, project_id: str, asset_type: str, limit: int = 200
    ) -> tuple[ResolvedProductionAsset, ...]:
        if limit <= 0 or limit > 1000:
            raise ValueError("production asset selection limit is invalid")
        if asset_type in {"story_state_snapshot", "canon_snapshot"}:
            return self._resolve_accepted_states(
                project_id=project_id, asset_type=asset_type, limit=limit
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id, asset.asset_id, version.asset_version_id,
                       asset.asset_type, version.content_hash, version.content,
                       COALESCE(qualification.decision, 'ELIGIBLE'),
                       producer.operation_id, producer.definition_name, producer.status
                FROM authority_asset AS asset
                JOIN authority_asset_version AS version ON version.asset_id = asset.asset_id
                LEFT JOIN LATERAL (
                    SELECT decision FROM authority_asset_qualification
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC LIMIT 1
                ) AS qualification ON TRUE
                LEFT JOIN LATERAL (
                    SELECT operation.operation_id, operation.definition_name, operation.status
                    FROM authority_operation_output_asset AS binding
                    JOIN authority_operation AS operation
                      ON operation.operation_id = binding.operation_id
                    WHERE binding.asset_version_id = version.asset_version_id
                    ORDER BY binding.created_at DESC, operation.updated_at DESC
                    LIMIT 1
                ) AS producer ON TRUE
                WHERE asset.project_id = %s AND asset.asset_type = %s
                  AND version.lifecycle = 'ACTIVE'
                  AND version.eligibility = 'ELIGIBLE'
                  AND version.governance = 'CLEAR'
                  AND COALESCE(qualification.decision, 'ELIGIBLE') = 'ELIGIBLE'
                  AND NOT EXISTS (
                    SELECT 1 FROM authority_asset_version AS newer
                    WHERE newer.asset_id = version.asset_id
                      AND newer.version_number > version.version_number
                      AND newer.lifecycle = 'ACTIVE'
                  )
                ORDER BY
                    COALESCE((version.content->>'priority')::int, 0) DESC,
                    version.created_at DESC, version.version_number DESC,
                    version.asset_version_id DESC
                LIMIT %s
                """,
                [project_id, asset_type, limit],
            )
            rows = uow.cursor.fetchall()
        return tuple(self._asset(row, "eligible scoped authority collection") for row in rows)

    def resolve_accepted_for_boundary(
        self,
        *,
        project_id: str,
        book_id: str,
        asset_type: str,
        accepted_chapter: int,
    ) -> tuple[ResolvedProductionAsset, ...]:
        """Resolve the exact Book acceptance pointer required by continuation."""

        if (
            asset_type not in {"story_state_snapshot", "canon_snapshot"}
            or not project_id
            or not book_id
            or accepted_chapter <= 0
        ):
            raise ValueError("accepted Narrative State boundary is invalid")
        candidates = self._resolve_accepted_states(
            project_id=project_id,
            asset_type=asset_type,
            limit=2,
            book_id=book_id,
            accepted_chapter=accepted_chapter,
        )
        if len(candidates) > 1:
            raise KernelError(
                "PREPARATION_ACCEPTED_STATE_AMBIGUOUS",
                "Book acceptance resolved multiple Narrative State snapshots at one boundary",
            )
        return candidates

    def resolve_override(
        self, *, project_id: str, asset_version_id: str
    ) -> ResolvedProductionAsset:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id, asset.asset_id, version.asset_version_id,
                       asset.asset_type, version.content_hash, version.content,
                       COALESCE(qualification.decision, 'ELIGIBLE'),
                       producer.operation_id, producer.definition_name, producer.status,
                       version.lifecycle, version.eligibility, version.governance
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                LEFT JOIN LATERAL (
                    SELECT decision
                    FROM authority_asset_qualification
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC
                    LIMIT 1
                ) AS qualification ON TRUE
                LEFT JOIN LATERAL (
                    SELECT operation.operation_id, operation.definition_name, operation.status
                    FROM authority_operation_output_asset AS binding
                    JOIN authority_operation AS operation
                      ON operation.operation_id = binding.operation_id
                    WHERE binding.asset_version_id = version.asset_version_id
                    ORDER BY binding.created_at DESC, operation.updated_at DESC
                    LIMIT 1
                ) AS producer ON TRUE
                WHERE version.asset_version_id = %s
                """,
                [asset_version_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("PREPARATION_OVERRIDE_NOT_FOUND", "override AssetVersion is missing")
        if row[0] != project_id:
            raise KernelError(
                "PREPARATION_CROSS_PROJECT_INPUT",
                "override AssetVersion belongs to another project",
            )
        if tuple(row[10:13]) != ("ACTIVE", "ELIGIBLE", "CLEAR") or row[6] != "ELIGIBLE":
            raise KernelError(
                "PREPARATION_OVERRIDE_NOT_ELIGIBLE",
                "override AssetVersion is stale, revoked, or quarantined",
            )
        asset = self._asset(row[:10], "explicit audited AssetVersion override")
        accepted_scope = self._accepted_snapshot_scope(
            project_id=project_id,
            asset_version_id=asset_version_id,
        )
        if accepted_scope is not None:
            asset = self._bind_acceptance_scope(asset, *accepted_scope)
        else:
            initial_scope = self._initial_snapshot_scope(
                project_id=project_id,
                asset_version_id=asset_version_id,
            )
            if initial_scope is not None:
                asset = self._bind_initial_state_scope(asset, *initial_scope)
        return asset

    def _accepted_snapshot_scope(
        self, *, project_id: str, asset_version_id: str
    ) -> tuple[str, int, str] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT production.book_id, acceptance.chapter_number,
                       acceptance.acceptance_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_production AS production
                  ON production.book_run_id=acceptance.book_run_id
                 AND production.project_id=acceptance.project_id
                WHERE acceptance.project_id=%s
                  AND status='COMMITTED'
                  AND (
                    story_state_asset_version_id=%s
                    OR canon_snapshot_asset_version_id=%s
                  )
                ORDER BY acceptance.chapter_number DESC
                LIMIT 1
                """,
                [project_id, asset_version_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        return (
            (str(row[0]), int(row[1]), str(row[2]))
            if row is not None
            else None
        )

    def _initial_snapshot_scope(
        self, *, project_id: str, asset_version_id: str
    ) -> tuple[str, str] | None:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT snapshot.book_id, binding.binding_id
                FROM authority_book_production_input_snapshot AS snapshot
                JOIN authority_book_production_input_binding AS binding
                  ON binding.snapshot_id=snapshot.snapshot_id
                 AND binding.project_id=snapshot.project_id
                 AND binding.book_id=snapshot.book_id
                JOIN authority_book_production AS production
                  ON production.book_run_id=binding.book_run_id
                 AND production.project_id=binding.project_id
                 AND production.input_mode='RESOLVED_AUTHORITY_INPUT'
                WHERE snapshot.project_id=%s
                  AND (
                    snapshot.initial_story_state_version=%s
                    OR snapshot.initial_canon_snapshot_version=%s
                  )
                ORDER BY binding.created_at DESC
                LIMIT 1
                """,
                [project_id, asset_version_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    @staticmethod
    def _bind_acceptance_scope(
        asset: ResolvedProductionAsset,
        book_id: str,
        accepted_chapter: int,
        acceptance_id: str,
    ) -> ResolvedProductionAsset:
        content = dict(asset.content)
        declared = content.get("chapter", content.get("chapter_number"))
        if declared is not None and int(declared) != accepted_chapter:
            raise KernelError(
                "PREPARATION_ACCEPTANCE_CHAPTER_MISMATCH",
                "accepted snapshot chapter metadata conflicts with Book Authority",
            )
        content.update(
            {
                "chapter": accepted_chapter,
                "chapter_number": accepted_chapter,
                "accepted_through_chapter": accepted_chapter,
                "book_id": book_id,
                "acceptance_id": acceptance_id,
                "_authority_acceptance_bound": True,
            }
        )
        return replace(asset, content=content)

    @staticmethod
    def _bind_initial_state_scope(
        asset: ResolvedProductionAsset,
        book_id: str,
        binding_id: str,
    ) -> ResolvedProductionAsset:
        content = dict(asset.content)
        declared = content.get("chapter", content.get("chapter_number"))
        if declared is not None and int(declared) != 0:
            raise KernelError(
                "PREPARATION_INITIAL_STATE_CHAPTER_MISMATCH",
                "initial Narrative State must describe the pre-Chapter-1 boundary",
            )
        if content.get("initial_state_boundary") != "BOOK_PRODUCTION_INPUT_SNAPSHOT":
            raise KernelError(
                "PREPARATION_INITIAL_STATE_BOUNDARY_INVALID",
                "initial Narrative State is not governed as a Book input snapshot",
            )
        content.update(
            {
                "chapter": 0,
                "chapter_number": 0,
                "accepted_through_chapter": 0,
                "book_id": book_id,
                "book_input_binding_id": binding_id,
                "_authority_acceptance_bound": True,
            }
        )
        return replace(asset, content=content)

    def _resolve_accepted_states(
        self,
        *,
        project_id: str,
        asset_type: str,
        limit: int,
        book_id: str = "",
        accepted_chapter: int | None = None,
    ) -> tuple[ResolvedProductionAsset, ...]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT asset.project_id, asset.asset_id, version.asset_version_id,
                       asset.asset_type, version.content_hash, version.content,
                       COALESCE(qualification.decision, 'ELIGIBLE'),
                       acceptance_operation.operation_id,
                       acceptance_operation.definition_name,
                       acceptance_operation.status,
                       production.book_id, acceptance.chapter_number,
                       acceptance.acceptance_id
                FROM authority_book_chapter_acceptance AS acceptance
                JOIN authority_book_production AS production
                  ON production.book_run_id=acceptance.book_run_id
                 AND production.project_id=acceptance.project_id
                JOIN authority_operation AS acceptance_operation
                  ON acceptance_operation.operation_id=
                     acceptance.acceptance_operation_id
                 AND acceptance_operation.project_id=acceptance.project_id
                 AND acceptance_operation.status='SUCCEEDED'
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=CASE
                    WHEN %s='story_state_snapshot'
                    THEN acceptance.story_state_asset_version_id
                    ELSE acceptance.canon_snapshot_asset_version_id
                  END
                JOIN authority_asset AS asset
                  ON asset.asset_id=version.asset_id
                 AND asset.project_id=acceptance.project_id
                 AND asset.asset_type=%s
                LEFT JOIN LATERAL (
                    SELECT decision
                    FROM authority_asset_qualification
                    WHERE asset_version_id=version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC
                    LIMIT 1
                ) AS qualification ON TRUE
                WHERE acceptance.project_id=%s
                  AND acceptance.status='COMMITTED'
                  AND (%s='' OR production.book_id=%s)
                  AND (%s::integer IS NULL OR acceptance.chapter_number=%s)
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility='ELIGIBLE'
                  AND version.governance='CLEAR'
                  AND COALESCE(qualification.decision, 'ELIGIBLE')='ELIGIBLE'
                ORDER BY acceptance.chapter_number DESC,
                         acceptance.created_at DESC
                LIMIT %s
                """,
                [
                    asset_type,
                    asset_type,
                    project_id,
                    book_id,
                    book_id,
                    accepted_chapter,
                    accepted_chapter,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        resolved = tuple(
            self._bind_acceptance_scope(
                self._asset(row[:10], "committed Book acceptance state"),
                str(row[10]),
                int(row[11]),
                str(row[12]),
            )
            for row in rows
        )
        if asset_type != "story_state_snapshot":
            return resolved
        enriched: list[ResolvedProductionAsset] = []
        for asset in resolved:
            content = dict(asset.content)
            content["_accepted_quality_observations"] = (
                load_accepted_quality_observations(
                    self.database_url,
                    project_id=project_id,
                    book_id=str(content["book_id"]),
                    accepted_through_chapter=int(
                        content["accepted_through_chapter"]
                    ),
                )
            )
            enriched.append(replace(asset, content=content))
        return tuple(enriched)

    @staticmethod
    def _asset(row: tuple[object, ...], reason: str) -> ResolvedProductionAsset:
        content = dict(row[5] or {})
        if str(row[3]) == "typed_empty_state_snapshot":
            producer_operation_id = str(row[7] or "")
            producer_definition = str(row[8] or "")
            producer_status = str(row[9] or "")
            content.update(
                {
                    "_authority_producer_verified": (
                        producer_operation_id != ""
                        and producer_definition == "chapter.state.initialize_empty"
                        and producer_status == "SUCCEEDED"
                        and content.get("producer_operation_id") == producer_operation_id
                        and content.get("producer_definition") == producer_definition
                    ),
                    "_authority_producer_operation_id": producer_operation_id,
                    "_authority_producer_definition": producer_definition,
                    "_authority_producer_status": producer_status,
                }
            )
        return ResolvedProductionAsset(
            project_id=str(row[0]),
            asset_id=str(row[1]),
            asset_version_id=str(row[2]),
            asset_type=str(row[3]),
            content_hash=str(row[4]),
            content=content,
            qualification=str(row[6]),
            selected_reason=reason,
        )
