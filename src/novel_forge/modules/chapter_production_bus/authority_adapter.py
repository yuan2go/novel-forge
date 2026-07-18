"""Compatibility command/query adapter for PostgreSQL Chapter Authority."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery


class ChapterAuthorityCommandPort(Protocol):
    def run(self, request: SingleChapterRequest) -> Any: ...


@dataclass(slots=True)
class ChapterProductionAuthorityAdapter:
    """Routes compatibility calls to Authority and returns rebuildable projections."""

    command_port: ChapterAuthorityCommandPort
    query: ChapterAuthorityQuery
    legacy_call_counts: dict[str, int] = field(default_factory=dict)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._count("submit")
        request = SingleChapterRequest(
            project_id=str(payload["project_id"]),
            workspace_id=str(payload["workspace_id"]),
            actor_id=str(payload["actor_id"]),
            chapter=int(payload["chapter"]),
            title=str(payload["title"]),
            premise=str(payload["premise"]),
            trace_id=str(payload["trace_id"]),
            correlation_id=str(payload["correlation_id"]),
            application_build_id=str(payload["application_build_id"]),
            commit_sha=str(payload["commit_sha"]),
            chapter_plan_asset_version_id=str(payload.get("chapter_plan_asset_version_id") or ""),
            chapter_plan_content_hash=str(payload.get("chapter_plan_content_hash") or ""),
            context_candidates=tuple(payload.get("context_candidates", ())),
            context_version_refs=dict(payload.get("context_version_refs", {})),
            context_token_budget=int(payload.get("context_token_budget", 6000)),
        )
        result = self.command_port.run(request)
        return self.project(
            self.query.require_run(
                project_id=request.project_id,
                root_operation_id=result.root_operation_id,
            )
        )

    def get(self, *, project_id: str, root_operation_id: str) -> dict[str, Any]:
        self._count("get")
        return self.project(
            self.query.require_run(
                project_id=project_id,
                root_operation_id=root_operation_id,
            )
        )

    def list(self, *, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._count("list")
        return [self._list_projection(row) for row in self.query.list_runs(project_id=project_id, limit=limit)]

    @staticmethod
    def project(authority_run: dict[str, Any]) -> dict[str, Any]:
        operations = authority_run.get("operations", [])
        outputs = authority_run.get("primary_outputs", [])
        by_operation = {item["operation_id"]: item for item in outputs}
        return {
            "type": "chapter_production_run_projection",
            "authoritative": False,
            "rebuildable": True,
            "project_id": authority_run["project_id"],
            "root_operation_id": authority_run["root_operation_id"],
            "status": authority_run["status"],
            "saga": dict(authority_run.get("saga", {})),
            "steps": [
                {
                    "operation_id": item["operation_id"],
                    "definition_name": item["definition_name"],
                    "status": item["status"],
                    "output": by_operation.get(item["operation_id"]),
                }
                for item in operations
                if item["operation_id"] != authority_run["root_operation_id"]
            ],
            "model_effects": list(authority_run.get("model_effects", [])),
            "projection_contract_version": "chapter-production-authority-projection-v1",
        }

    @staticmethod
    def _list_projection(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "type": "chapter_production_run_projection",
            "authoritative": False,
            "rebuildable": True,
        }

    def _count(self, action: str) -> None:
        self.legacy_call_counts[action] = self.legacy_call_counts.get(action, 0) + 1


__all__ = ["ChapterProductionAuthorityAdapter"]
