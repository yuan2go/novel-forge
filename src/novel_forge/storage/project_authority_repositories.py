from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError


BINDING_TARGET_TYPES = {
    "BOOK": frozenset({"book", "book_record", "book_design", "book_plan"}),
    "PLATFORM_PROFILE": frozenset({"platform_profile"}),
    "GENRE_MARKET_PROFILE": frozenset({"genre_market_profile"}),
    "QUALITY_STANDARD_PROFILE": frozenset({"quality_standard_profile"}),
    "STYLE_PROFILE": frozenset({"style_profile"}),
    "CONTINUITY_BIBLE": frozenset({"continuity_bible"}),
    "PRODUCTION_PROFILE": frozenset({"production_profile"}),
}


class ProjectAuthorityRepository:
    def __init__(self, cursor: Any) -> None:
        self.cursor = cursor

    def create(
        self,
        *,
        project: dict[str, Any],
        project_asset_version_id: str,
        workspace: dict[str, Any],
        workspace_asset_version_id: str,
        operation_id: str,
    ) -> None:
        self._require_asset_scope(
            project["project_id"], project_asset_version_id, "project_record"
        )
        self._require_asset_scope(
            project["project_id"], workspace_asset_version_id, "workspace_record"
        )
        self.cursor.execute("SET CONSTRAINTS authority_project_primary_workspace_fk DEFERRED")
        self.cursor.execute(
            """
            INSERT INTO authority_project (
                project_id, primary_workspace_id, title, series_title,
                book_number, status, stage, health, current_asset_version_id,
                created_by_operation_id, last_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                project["project_id"], project["workspace_id"], project["title"],
                project["series_title"], project.get("book_number"),
                project["status"], project["stage"], project["health"],
                project_asset_version_id, operation_id, operation_id,
            ],
        )
        self.create_workspace(workspace=workspace, workspace_asset_version_id=workspace_asset_version_id,
                              operation_id=operation_id)

    def require_new_workspace(self, workspace_id: str) -> None:
        self.cursor.execute("SELECT project_id FROM authority_workspace WHERE workspace_id=%s", [workspace_id])
        if self.cursor.fetchone() is not None:
            raise KernelError("WORKSPACE_SCOPE_CONFLICT", "workspace identity already exists and cannot be reassigned")

    def create_workspace(self, *, workspace: dict[str, Any], workspace_asset_version_id: str, operation_id: str) -> None:
        self._require_asset_scope(workspace["project_id"], workspace_asset_version_id, "workspace_record")
        self.cursor.execute(
            """
            INSERT INTO authority_workspace (
                workspace_id, project_id, book_id, status,
                current_asset_version_id, created_by_operation_id,
                last_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(workspace_id) DO NOTHING
            RETURNING workspace_id
            """,
            [
                workspace["workspace_id"], workspace["project_id"],
                workspace["book_id"], workspace["status"],
                workspace_asset_version_id, operation_id, operation_id,
            ],
        )
        if self.cursor.fetchone() is None:
            raise KernelError("WORKSPACE_SCOPE_CONFLICT", "workspace identity was created concurrently")

    def update(
        self,
        *,
        project: dict[str, Any],
        project_asset_version_id: str,
        operation_id: str,
        expected_version: int,
        expected_current_asset_version_id: str,
    ) -> int:
        self._require_asset_scope(
            project["project_id"], project_asset_version_id, "project_record"
        )
        self.cursor.execute(
            """
            UPDATE authority_project
            SET title = %s,
                series_title = %s,
                book_number = %s,
                status = %s,
                stage = %s,
                health = %s,
                current_asset_version_id = %s,
                last_operation_id = %s,
                version = version + 1,
                updated_at = NOW()
            WHERE project_id = %s
              AND version = %s
              AND current_asset_version_id = %s
            RETURNING version
            """,
            [
                project["title"], project["series_title"], project.get("book_number"),
                project["status"], project["stage"], project["health"],
                project_asset_version_id, operation_id, project["project_id"],
                expected_version, expected_current_asset_version_id,
            ],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "PROJECT_VERSION_CONFLICT",
                "project aggregate or current AssetVersion changed concurrently",
            )
        return int(row[0])

    def lock_project(self, project_id: str) -> dict[str, Any]:
        self.cursor.execute(
            """
            SELECT project.project_id, project.primary_workspace_id, project.version,
                   project.current_asset_version_id, version.content
            FROM authority_project AS project
            JOIN authority_asset_version AS version
              ON version.asset_version_id = project.current_asset_version_id
            WHERE project.project_id = %s
            FOR UPDATE OF project
            """,
            [project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("PROJECT_NOT_FOUND", "project does not exist")
        return {
            "project_id": row[0],
            "workspace_id": row[1],
            "version": int(row[2]),
            "asset_version_id": row[3],
            "content": row[4],
        }

    def current_binding_for_update(
        self, *, project_id: str, workspace_id: str, binding_type: str
    ) -> dict[str, Any] | None:
        self.cursor.execute(
            """
            SELECT binding.binding_id, binding.binding_asset_version_id,
                   binding.target_asset_version_id
            FROM authority_project_binding AS binding
            WHERE binding.project_id = %s
              AND binding.workspace_id = %s
              AND binding.binding_type = %s
              AND binding.active
            FOR UPDATE
            """,
            [project_id, workspace_id, binding_type],
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        return {
            "binding_id": row[0],
            "binding_asset_version_id": row[1],
            "target_asset_version_id": row[2],
        }

    def current_binding_decision_version(
        self, *, project_id: str, workspace_id: str, binding_type: str
    ) -> str:
        logical_ref = _binding_logical_ref(workspace_id, binding_type)
        self.cursor.execute(
            """
            SELECT locator.current_asset_version_id
            FROM authority_asset_locator AS locator
            JOIN authority_asset AS asset ON asset.asset_id = locator.asset_id
            WHERE locator.project_id = %s
              AND locator.logical_ref = %s
              AND asset.asset_type = 'project_binding_record'
            FOR UPDATE OF locator
            """,
            [project_id, logical_ref],
        )
        row = self.cursor.fetchone()
        return str(row[0]) if row else ""

    def require_binding_target(
        self, *, project_id: str, asset_version_id: str, binding_type: str
    ) -> dict[str, str]:
        allowed_types = BINDING_TARGET_TYPES.get(binding_type)
        if allowed_types is None:
            raise KernelError(
                "PROJECT_BINDING_TYPE_INVALID", f"unsupported binding type: {binding_type}"
            )
        self.cursor.execute(
            """
            SELECT asset.asset_id, asset.asset_type, version.lifecycle,
                   version.eligibility, version.governance
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
            WHERE version.asset_version_id = %s AND asset.project_id = %s
            FOR SHARE OF version, asset
            """,
            [asset_version_id, project_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError(
                "CROSS_PROJECT_REFERENCE",
                "binding target AssetVersion is missing or belongs to another project",
            )
        if row[1] not in allowed_types:
            raise KernelError(
                "PROJECT_BINDING_TARGET_TYPE_INVALID",
                f"{binding_type} cannot target Asset type {row[1]}",
            )
        if row[2:] != ("ACTIVE", "ELIGIBLE", "CLEAR"):
            raise KernelError(
                "PROJECT_BINDING_TARGET_INELIGIBLE",
                "binding target must be ACTIVE, ELIGIBLE, and governance CLEAR",
            )
        return {"asset_id": row[0], "asset_type": row[1]}

    def assign_binding(
        self,
        *,
        binding_id: str,
        binding_asset_version_id: str,
        project_id: str,
        workspace_id: str,
        binding_type: str,
        target_asset_version_id: str,
        operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_project_binding
            SET active = FALSE,
                superseded_by_operation_id = %s,
                superseded_at = NOW()
            WHERE project_id = %s
              AND workspace_id = %s
              AND binding_type = %s
              AND active
            """,
            [operation_id, project_id, workspace_id, binding_type],
        )
        self.cursor.execute(
            """
            INSERT INTO authority_project_binding (
                binding_id, project_id, workspace_id, binding_type,
                target_asset_version_id, binding_asset_version_id,
                created_by_operation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                binding_id, project_id, workspace_id, binding_type,
                target_asset_version_id, binding_asset_version_id, operation_id,
            ],
        )

    def remove_binding(
        self,
        *,
        project_id: str,
        workspace_id: str,
        binding_type: str,
        operation_id: str,
    ) -> None:
        self.cursor.execute(
            """
            UPDATE authority_project_binding
            SET active = FALSE,
                superseded_by_operation_id = %s,
                superseded_at = NOW()
            WHERE project_id = %s
              AND workspace_id = %s
              AND binding_type = %s
              AND active
            """,
            [operation_id, project_id, workspace_id, binding_type],
        )
        if self.cursor.rowcount != 1:
            raise KernelError(
                "PROJECT_BINDING_NOT_FOUND", "active Project binding does not exist"
            )

    def _require_asset_scope(
        self, project_id: str, asset_version_id: str, asset_type: str
    ) -> None:
        self.cursor.execute(
            """
            SELECT asset.project_id, asset.asset_type
            FROM authority_asset_version AS version
            JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
            WHERE version.asset_version_id = %s
            """,
            [asset_version_id],
        )
        row = self.cursor.fetchone()
        if row is None:
            raise KernelError("AUTHORITY_ASSET_NOT_FOUND", "project snapshot is missing")
        if row != (project_id, asset_type):
            raise KernelError(
                "CROSS_PROJECT_REFERENCE",
                "project projection snapshot belongs to a different project or type",
            )


def _binding_logical_ref(workspace_id: str, binding_type: str) -> str:
    return f"project-bindings/{workspace_id}/{binding_type.lower()}"


__all__ = [
    "BINDING_TARGET_TYPES",
    "ProjectAuthorityRepository",
    "_binding_logical_ref",
]
