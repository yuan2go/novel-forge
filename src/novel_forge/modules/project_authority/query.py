from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class ProjectAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def list_projects(
        self, *, include_deleted: bool = False, limit: int = 500
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("project query limit must be between 1 and 1000")
        clauses = [] if include_deleted else ["project.status <> 'DELETED'"]
        where = "" if not clauses else "WHERE " + " AND ".join(clauses)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                _PROJECT_SELECT
                + f" {where} ORDER BY project.updated_at DESC, project.project_id LIMIT %s",
                [limit],
            )
            rows = uow.cursor.fetchall()
        return [_project_row(row) for row in rows]

    def require_project(self, project_id: str) -> dict[str, Any]:
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                _PROJECT_SELECT + " WHERE project.project_id = %s", [project_id]
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise KernelError("PROJECT_NOT_FOUND", "project does not exist")
        return _project_row(row)

    def list_assets(
        self,
        *,
        project_id: str | None,
        category: str | None = None,
        asset_type: str | None = None,
        asset_types: tuple[str, ...] = (),
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise ValueError("asset query limit must be between 1 and 1000")
        if project_id:
            self.require_project(project_id)
        clauses: list[str] = []
        params: list[Any] = []
        if project_id:
            clauses.append("asset.project_id = %s")
            params.append(project_id)
        if category:
            clauses.append("COALESCE(locator.category, asset.asset_type) = %s")
            params.append(category)
        if asset_type:
            clauses.append("asset.asset_type = %s")
            params.append(asset_type)
        if asset_types:
            clauses.append("asset.asset_type = ANY(%s)")
            params.append(list(asset_types))
        if keyword:
            clauses.append(
                "(COALESCE(locator.logical_ref, version.asset_version_id) ILIKE %s "
                "OR version.content::text ILIKE %s)"
            )
            term = f"%{keyword}%"
            params.extend([term, term])
        params.append(limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT COALESCE(locator.logical_ref, 'asset-versions/' || version.asset_version_id),
                       COALESCE(locator.category, asset.asset_type), asset.asset_id,
                       asset.project_id, asset.asset_type, version.asset_version_id,
                       version.version_number, version.lifecycle,
                       version.eligibility, version.governance,
                       version.content_hash, version.content, version.created_at,
                       output.operation_id
                FROM authority_asset AS asset
                JOIN LATERAL (
                    SELECT candidate.* FROM authority_asset_version AS candidate
                    WHERE candidate.asset_id = asset.asset_id
                    ORDER BY candidate.version_number DESC LIMIT 1
                ) AS version ON TRUE
                LEFT JOIN authority_asset_locator AS locator
                  ON locator.project_id = asset.project_id
                 AND locator.asset_id = asset.asset_id
                LEFT JOIN LATERAL (
                    SELECT operation_id
                    FROM authority_operation_output_asset
                    WHERE asset_version_id = version.asset_version_id
                    ORDER BY created_at DESC, operation_id DESC LIMIT 1
                ) AS output ON TRUE
                """
                + (" WHERE " + " AND ".join(clauses) if clauses else "")
                + " ORDER BY version.created_at DESC LIMIT %s",
                params,
            )
            rows = uow.cursor.fetchall()
        keys = (
            "logical_ref", "category", "asset_id", "project_id", "type", "asset_version_id",
            "version_number", "lifecycle", "eligibility", "governance",
            "content_hash", "content", "updated_at", "created_by_operation_id",
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            values = list(row)
            values[12] = str(values[12])
            values[13] = values[13] or ""
            item = dict(zip(keys, values, strict=True))
            content = dict(item.get("content") or {})
            item.update(
                {
                    "id": item["asset_id"],
                    "path": f"authority://asset-version/{item['asset_version_id']}",
                    "authority_ref": f"authority://asset-version/{item['asset_version_id']}",
                    "title": str(
                        content.get("title") or content.get("name")
                        or item["type"].replace("_", " ").title()
                    ),
                    "status": item["lifecycle"],
                    "asset_status": item["eligibility"],
                }
            )
            results.append(item)
        return results

    def list_bindings(self, *, project_id: str) -> list[dict[str, Any]]:
        project = self.require_project(project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT version.asset_version_id, version.version_number,
                       version.content_hash, version.content,
                       version.lifecycle, version.eligibility, version.governance,
                       binding.binding_id, binding.target_asset_version_id,
                       target_asset.asset_id, target_asset.asset_type,
                       target.lifecycle, target.eligibility, target.governance,
                       operation.operation_id, version.created_at
                FROM authority_asset_locator AS locator
                JOIN authority_asset AS asset ON asset.asset_id = locator.asset_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = locator.current_asset_version_id
                LEFT JOIN authority_project_binding AS binding
                  ON binding.binding_asset_version_id = version.asset_version_id
                 AND binding.active
                LEFT JOIN authority_asset_version AS target
                  ON target.asset_version_id = COALESCE(
                      binding.target_asset_version_id,
                      version.content->>'target_asset_version_id'
                  )
                LEFT JOIN authority_asset AS target_asset
                  ON target_asset.asset_id = target.asset_id
                LEFT JOIN authority_operation_output_asset AS operation
                  ON operation.asset_version_id = version.asset_version_id
                 AND operation.output_key = 'project.binding'
                 AND operation.role = 'primary_binding'
                WHERE locator.project_id = %s
                  AND locator.category = 'project-bindings'
                  AND asset.asset_type = 'project_binding_record'
                ORDER BY version.content->>'binding_type'
                """,
                [project_id],
            )
            rows = uow.cursor.fetchall()
        results = []
        for row in rows:
            content = dict(row[3] or {})
            results.append(
                {
                    "project_id": project_id,
                    "workspace_id": project["workspace_id"],
                    "binding_type": str(content.get("binding_type") or ""),
                    "status": str(content.get("status") or ""),
                    "active": row[7] is not None,
                    "binding_id": row[7] or "",
                    "binding_asset_version_id": row[0],
                    "binding_version_number": int(row[1]),
                    "binding_content_hash": row[2],
                    "binding_lifecycle": row[4],
                    "binding_eligibility": row[5],
                    "binding_governance": row[6],
                    "target_asset_version_id": row[8]
                    or str(content.get("target_asset_version_id") or ""),
                    "target_asset_id": row[9] or "",
                    "target_asset_type": row[10] or "",
                    "target_lifecycle": row[11] or "",
                    "target_eligibility": row[12] or "",
                    "target_governance": row[13] or "",
                    "created_by_operation_id": row[14] or "",
                    "updated_at": str(row[15]),
                    "authority_ref": f"authority://asset-version/{row[0]}",
                }
            )
        return results

    def operating_dashboard(self, *, limit: int = 20) -> dict[str, Any]:
        rows = self.list_projects(include_deleted=False, limit=limit)
        project_ids = [row["project_id"] for row in rows]
        metrics: dict[str, dict[str, Any]] = {}
        if project_ids:
            with AuthorityUnitOfWork(self.database_url) as uow:
                uow.cursor.execute(
                    """
                    SELECT project.project_id,
                           (SELECT COUNT(*) FROM authority_asset AS asset
                            WHERE asset.project_id=project.project_id
                              AND asset.asset_type IN ('draft_chapter','chapter_outcome')),
                           (SELECT COUNT(*) FROM authority_asset AS asset
                            WHERE asset.project_id=project.project_id
                              AND asset.asset_type='draft_chapter'),
                           (SELECT COUNT(*) FROM authority_asset AS asset
                            WHERE asset.project_id=project.project_id
                              AND asset.asset_type IN ('review_report','review_issue')),
                           (SELECT COUNT(*) FROM authority_project_binding AS binding
                            WHERE binding.project_id=project.project_id AND binding.active),
                           (SELECT COUNT(*) FROM authority_operation AS operation
                            WHERE operation.project_id=project.project_id
                              AND operation.status IN ('FAILED_FINAL','DEAD_LETTER')),
                           COALESCE((
                               SELECT ARRAY_AGG(binding.binding_type ORDER BY binding.binding_type)
                               FROM authority_project_binding AS binding
                               WHERE binding.project_id=project.project_id AND binding.active
                           ), ARRAY[]::text[])
                    FROM authority_project AS project
                    WHERE project.project_id = ANY(%s)
                    """,
                    [project_ids],
                )
                for row in uow.cursor.fetchall():
                    metrics[str(row[0])] = {
                        "chapter_count": int(row[1]),
                        "draft_count": int(row[2]),
                        "review_count": int(row[3]),
                        "profile_binding_count": int(row[4]),
                        "failed_task_count": int(row[5]),
                        "binding_types": list(row[6]),
                    }
        expected_binding_types = {
            "PLATFORM_PROFILE", "GENRE_MARKET_PROFILE",
            "QUALITY_STANDARD_PROFILE", "STYLE_PROFILE", "CONTINUITY_BIBLE",
        }
        expected_bindings = len(expected_binding_types)
        projects: list[dict[str, Any]] = []
        for row in rows:
            counts = metrics.get(row["project_id"], {})
            risk = {"BLOCKED": 100, "DEGRADED": 60, "UNKNOWN": 30}.get(
                row["health"], 0
            )
            binding_count = counts.get("profile_binding_count", 0)
            bottleneck_kind = "health" if row["health"] == "BLOCKED" else (
                "profile_binding" if binding_count < expected_bindings else "none"
            )
            bottleneck_label = (
                "Project blocked" if bottleneck_kind == "health" else
                "Authority profile bindings incomplete" if bottleneck_kind == "profile_binding"
                else "No blocking condition"
            )
            projects.append(
                {
                    **row,
                    **counts,
                    "profile_binding_total": expected_bindings,
                    "missing_profiles": sorted(
                        expected_binding_types - set(counts.get("binding_types", []))
                    ),
                    "open_issue_count": counts.get("review_count", 0),
                    "pending_handoff_count": 0,
                    "risk_score": risk,
                    "momentum_score": 0,
                    "investment_score": 0,
                    "score_basis": "not_behavior_calibrated",
                    "bottleneck": {
                        "severity": "blocking" if risk >= 100 else (
                            "warning" if bottleneck_kind != "none" else "clear"
                        ),
                        "kind": bottleneck_kind,
                        "label": bottleneck_label,
                        "suggestion": "resolve Authority gate evidence" if risk >= 100
                        else "bind qualified AssetVersions" if binding_count < expected_bindings
                        else "continue the current Authority plan",
                    },
                    "today_action": {
                        "action": "inspect",
                        "label": "Inspect Authority evidence",
                        "href": f"/projects?project_id={row['project_id']}",
                        "reason": bottleneck_label,
                    },
                    "today_priority_rank": risk,
                }
            )
        priorities = sorted(
            projects, key=lambda item: (-item["risk_score"], item["project_id"])
        )
        return {
            "authority": "postgresql",
            "projects": projects,
            "summary": {
                "project_count": len(projects),
                "active_project_count": sum(
                    row["status"] == "ACTIVE" for row in projects
                ),
                "high_risk_project_count": sum(
                    row["risk_score"] >= 60 for row in projects
                ),
                "blocked_project_count": sum(
                    row["health"] == "BLOCKED" for row in projects
                ),
                "average_investment_score": 0,
            },
            "today_priorities": [
                {
                    "project_id": row["project_id"],
                    "title": row["title"],
                    **row["today_action"],
                    "risk_score": row["risk_score"],
                    "investment_score": row["investment_score"],
                    "bottleneck": row["bottleneck"]["label"],
                }
                for row in priorities[:10]
                if row["bottleneck"]["kind"] != "none"
            ],
            "bottlenecks": [
                {
                    "project_id": row["project_id"],
                    "title": row["title"],
                    **row["bottleneck"],
                }
                for row in projects
                if row["bottleneck"]["kind"] != "none"
            ],
        }

    def scope_audit(self, *, project_id: str | None = None) -> dict[str, Any]:
        params: list[Any] = []
        clause = ""
        if project_id:
            clause = "WHERE project.project_id = %s"
            params.append(project_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                f"""
                SELECT project.project_id,
                       COUNT(*) FILTER (
                           WHERE asset.project_id <> project.project_id
                       ) AS cross_project_asset_refs,
                       COUNT(*) FILTER (
                           WHERE workspace.project_id <> project.project_id
                       ) AS cross_project_workspaces
                FROM authority_project AS project
                JOIN authority_workspace AS workspace
                  ON workspace.workspace_id = project.primary_workspace_id
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = project.current_asset_version_id
                JOIN authority_asset AS asset ON asset.asset_id = version.asset_id
                {clause}
                GROUP BY project.project_id
                ORDER BY project.project_id
                """,
                params,
            )
            rows = uow.cursor.fetchall()
        findings = [
            {
                "project_id": row[0],
                "cross_project_asset_refs": int(row[1]),
                "cross_project_workspaces": int(row[2]),
            }
            for row in rows
            if row[1] or row[2]
        ]
        return {
            "authority": "postgresql",
            "project_id": project_id or "",
            "status": "FAIL" if findings else "PASS",
            "findings": findings,
            "repair_applied": False,
        }


_PROJECT_SELECT = """
SELECT project.project_id, project.primary_workspace_id, project.title,
       project.series_title, project.book_number, project.status,
       project.stage, project.health, project.version,
       project.current_asset_version_id, version.content_hash,
       version.content, project.created_by_operation_id,
       project.last_operation_id, project.created_at, project.updated_at,
       (SELECT COUNT(*) FROM authority_asset AS asset
        WHERE asset.project_id = project.project_id) AS asset_count
FROM authority_project AS project
JOIN authority_asset_version AS version
  ON version.asset_version_id = project.current_asset_version_id
"""


def _project_row(row: tuple[Any, ...]) -> dict[str, Any]:
    keys = (
        "project_id", "workspace_id", "title", "series_title", "book_number",
        "status", "stage", "health", "version", "asset_version_id",
        "content_hash", "content", "created_by_operation_id",
        "last_operation_id", "created_at", "updated_at", "asset_count",
    )
    values = list(row)
    values[14] = str(values[14])
    values[15] = str(values[15])
    values[16] = int(values[16])
    item = dict(zip(keys, values, strict=True))
    item.update(
        {
            "id": item["project_id"],
            "path": f"authority://project/{item['project_id']}",
            "authority_ref": f"authority://project/{item['project_id']}",
            "project_config": dict((item.get("content") or {}).get("config") or {}),
        }
    )
    return item


__all__ = ["ProjectAuthorityQuery"]
