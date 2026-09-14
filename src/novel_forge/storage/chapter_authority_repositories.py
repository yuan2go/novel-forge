"""COMPATIBILITY: this import path remains stable for shared fenced persistence."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from novel_forge.modules.command_kernel.errors import KernelError


class AuthorityHandlerRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def operation_execution(self, operation_id: str, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT operation_id, project_id, workspace_id, actor_id, status, definition_name,
                   definition_version, definition_snapshot, command_payload,
                   input_asset_snapshot, trace_id, correlation_id
            FROM authority_operation
            WHERE operation_id = %s AND project_id = %s
            """,
            [operation_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "OPERATION_NOT_FOUND", "authority operation does not exist"
            )
        fields = (
            "operation_id",
            "project_id",
            "workspace_id",
            "actor_id",
            "status",
            "definition_name",
            "definition_version",
            "definition_snapshot",
            "command_payload",
            "input_asset_snapshot",
            "trace_id",
            "correlation_id",
        )
        return dict(zip(fields, row, strict=True))

    def frozen_inputs(
        self,
        project_id: str,
        snapshots: list[dict[str, Any]],
        *,
        allow_approved_archival_migration: bool = False,
        evaluation_candidate_asset_version_id: str = "",
        story_design_candidate_asset_version_id: str = "",
        repair_candidate_asset_version_id: str = "",
        repair_result_asset_version_id: str = "",
        plan_change_candidate_asset_version_id: str = "",
        semantic_revalidation_target_asset_version_id: str = "",
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for snapshot in snapshots:
            asset_version_id = str(snapshot.get("asset_version_id") or "")
            content_hash = str(snapshot.get("content_hash") or "")
            self.cursor.execute(
                """
                SELECT version.asset_version_id, asset.asset_type,
                       version.content_hash, version.content, version.lifecycle,
                       version.eligibility, version.governance,
                       qualification.decision, qualification.policy_version
                FROM authority_asset_version AS version
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                LEFT JOIN LATERAL (
                    SELECT decision, policy_version
                    FROM authority_asset_qualification
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, qualification_id DESC
                    LIMIT 1
                ) AS qualification ON TRUE
                WHERE version.asset_version_id = %s
                  AND asset.project_id = %s
                  AND version.content_hash = %s
                """,
                [asset_version_id, project_id, content_hash],
            )
            row = self.cursor.fetchone()
            if row is None:
                raise KernelError(
                    "AUTHORITY_INPUT_SNAPSHOT_STALE",
                    f"frozen authority input is missing or changed: {asset_version_id}",
                )
            self.cursor.execute(
                """
                SELECT invalidation_id, reason
                FROM authority_artifact_invalidation
                WHERE project_id=%s AND target_asset_version_id=%s
                  AND status IN ('OPEN','REGENERATING')
                ORDER BY created_at DESC LIMIT 1
                """,
                [project_id, asset_version_id],
            )
            invalidation = self.cursor.fetchone()
            if (
                invalidation is not None
                and asset_version_id
                != semantic_revalidation_target_asset_version_id
            ):
                raise KernelError(
                    "AUTHORITY_INPUT_SEMANTICALLY_STALE",
                    "frozen authority input has unresolved semantic invalidation: "
                    f"{asset_version_id} ({invalidation[1]})",
                )
            production_eligible = (
                row[4] == "ACTIVE" and row[5] == "ELIGIBLE" and row[6] == "CLEAR"
            )
            approved_archival = (
                allow_approved_archival_migration
                and row[4] == "IMPORTED"
                and row[5] == "PENDING_EVALUATION"
                and row[6] == "CLEAR"
            )
            evaluation_candidate = (
                asset_version_id == evaluation_candidate_asset_version_id
                and row[1] in {"book_design", "planning_generation_candidate"}
                and row[4] == "CANDIDATE"
                and row[5] == "INELIGIBLE"
                and row[6] == "CLEAR"
            )
            story_design_candidate = (
                asset_version_id == story_design_candidate_asset_version_id
                and row[1] == "planning_generation_candidate"
                and row[4] == "CANDIDATE"
                and row[5] in {"INELIGIBLE", "ELIGIBLE"}
                and row[6] == "CLEAR"
            )
            repair_candidate = (
                asset_version_id == repair_candidate_asset_version_id
                and row[1] == "planning_generation_candidate"
                and row[4] == "CANDIDATE"
                and row[5] == "INELIGIBLE"
                and row[6] == "CLEAR"
            )
            repair_result = (
                asset_version_id == repair_result_asset_version_id
                and row[1] == "planning_generation_result_failure"
                and row[4] == "ACTIVE"
                and row[5] == "INELIGIBLE"
                and row[6] == "CLEAR"
            )
            plan_change_candidate = (
                asset_version_id == plan_change_candidate_asset_version_id
                and row[1] == "planning_generation_candidate"
                and row[4] == "CANDIDATE"
                and row[5] == "ELIGIBLE"
                and row[6] == "CLEAR"
            )
            if (
                not production_eligible
                and not approved_archival
                and not evaluation_candidate
                and not story_design_candidate
                and not repair_candidate
                and not repair_result
                and not plan_change_candidate
            ):
                raise KernelError(
                    "AUTHORITY_INPUT_NOT_ELIGIBLE",
                    f"frozen authority input is not active and eligible: {asset_version_id}",
                )
            allowed_qualification = (
                {None, "ELIGIBLE", "PENDING_EVALUATION"}
                if approved_archival
                else {None, "INELIGIBLE", "ELIGIBLE"}
                if (
                    evaluation_candidate
                    or story_design_candidate
                    or repair_candidate
                    or repair_result
                    or plan_change_candidate
                )
                else {None, "ELIGIBLE"}
            )
            if row[7] not in allowed_qualification:
                raise KernelError(
                    "AUTHORITY_INPUT_QUALIFICATION_REVOKED",
                    f"frozen authority input qualification is {row[7]}: {asset_version_id}",
                )
            self.cursor.execute(
                """
                SELECT blob.blob_id, reference.role, reference.ordinal,
                       reference.media_type, reference.content_hash,
                       blob.provider, blob.object_key, blob.expected_hash,
                       blob.expected_size, blob.actual_object_key, blob.actual_hash,
                       blob.actual_size, blob.receipt_provider, blob.status,
                       effect.external_effect_id, effect.capability, effect.status,
                       dispatch.dispatch_id, dispatch.generation, dispatch.status,
                       dispatch.evidence, receipt.receipt_id, receipt.status, receipt.payload
                FROM authority_asset_version_blob_reference AS reference
                JOIN authority_blob AS blob ON blob.blob_id = reference.blob_id
                LEFT JOIN authority_external_effect AS effect
                  ON effect.external_effect_id = blob.upload_effect_id
                 AND effect.project_id = blob.project_id
                LEFT JOIN LATERAL (
                    SELECT dispatch_id, generation, status, evidence
                    FROM authority_external_effect_dispatch
                    WHERE external_effect_id = effect.external_effect_id
                    ORDER BY generation DESC
                    LIMIT 1
                ) AS dispatch ON TRUE
                LEFT JOIN LATERAL (
                    SELECT receipt_id, status, payload
                    FROM authority_external_receipt
                    WHERE dispatch_id = dispatch.dispatch_id
                    ORDER BY received_at DESC, external_receipt_id DESC
                    LIMIT 1
                ) AS receipt ON TRUE
                WHERE reference.asset_version_id = %s
                  AND blob.project_id = %s
                ORDER BY reference.role, reference.ordinal
                """,
                [asset_version_id, project_id],
            )
            blobs = tuple(
                {
                    key: value
                    for key, value in zip(
                        (
                            "blob_id",
                            "role",
                            "ordinal",
                            "media_type",
                            "content_hash",
                            "provider",
                            "object_key",
                            "expected_hash",
                            "expected_size",
                            "actual_object_key",
                            "actual_hash",
                            "actual_size",
                            "receipt_provider",
                            "status",
                            "external_effect_id",
                            "capability",
                            "effect_status",
                            "dispatch_id",
                            "dispatch_generation",
                            "dispatch_status",
                            "dispatch_evidence",
                            "receipt_id",
                            "receipt_status",
                            "receipt_payload",
                        ),
                        blob_row,
                        strict=True,
                    )
                }
                for blob_row in self.cursor.fetchall()
            )
            resolved.append(
                {
                    "asset_version_id": row[0],
                    "asset_type": row[1],
                    "content_hash": row[2],
                    "content": row[3],
                    "lifecycle": row[4],
                    "eligibility": row[5],
                    "governance": row[6],
                    "qualification_decision": row[7] or "ELIGIBLE",
                    "qualification_policy_version": row[8] or "implicit-active-v1",
                    "blobs": blobs,
                }
            )
        return resolved

    def materialize_output(
        self,
        *,
        operation_id: str,
        project_id: str,
        asset_id: str,
        asset_version_id: str,
        qualification_id: str,
        asset_type: str,
        output_key: str,
        role: str,
        content: dict[str, Any],
        content_hash: str,
        qualification_policy: str,
        qualification_evidence: dict[str, Any],
        lifecycle: str = "ACTIVE",
        eligibility: str = "ELIGIBLE",
        governance: str = "CLEAR",
    ) -> bool:
        self.cursor.execute(
            """
            INSERT INTO authority_asset (asset_id, project_id, asset_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (asset_id) DO NOTHING
            """,
            [asset_id, project_id, asset_type],
        )
        self.cursor.execute(
            "SELECT project_id, asset_type FROM authority_asset WHERE asset_id = %s",
            [asset_id],
        )
        asset = self.cursor.fetchone()
        if asset != (project_id, asset_type):
            raise KernelError(
                "AUTHORITY_OUTPUT_REPLAY_CONFLICT",
                "stable authority Asset identity belongs to different content scope",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_version (
                asset_version_id, asset_id, version_number, lifecycle,
                eligibility, governance, content, content_hash, schema_version
            ) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_version_id) DO NOTHING
            RETURNING asset_version_id
            """,
            [
                asset_version_id,
                asset_id,
                lifecycle,
                eligibility,
                governance,
                Jsonb(content),
                content_hash,
                f"{asset_type.replace('_', '-')}.v1",
            ],
        )
        created = self.cursor.fetchone() is not None
        self.cursor.execute(
            """
            SELECT asset_id, content_hash, content, lifecycle, eligibility, governance
            FROM authority_asset_version WHERE asset_version_id = %s
            """,
            [asset_version_id],
        )
        version = self.cursor.fetchone()
        expected = (asset_id, content_hash, content, lifecycle, eligibility, governance)
        if version != expected:
            raise KernelError(
                "AUTHORITY_OUTPUT_REPLAY_CONFLICT",
                "stable authority AssetVersion identity has different content",
            )
        self.cursor.execute(
            """
            INSERT INTO authority_asset_qualification (
                qualification_id, asset_version_id, policy_version, decision, evidence
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (qualification_id) DO NOTHING
            """,
            [
                qualification_id,
                asset_version_id,
                qualification_policy,
                eligibility,
                Jsonb(qualification_evidence),
            ],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_operation_output_asset (
                operation_id, asset_id, asset_version_id,
                output_key, role, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (operation_id, output_key, role, asset_version_id) DO NOTHING
            """,
            [operation_id, asset_id, asset_version_id, output_key, role, content_hash],
        )
        return created


# COMPATIBILITY: retain the public name consumed by Chapter runtime callers.
ChapterAuthorityRepository = AuthorityHandlerRepository
