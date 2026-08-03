"""PostgreSQL AssetVersion projections for product-domain read surfaces."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext


ANALYSIS_TYPES = (
    "semantic_analysis", "evidence_span", "knowledge_abstraction_quality_benchmark",
    "knowledge_extraction_provider_quality_report", "semantic_conflict_review_report",
)
CONTEXT_TYPES = (
    "context_build_plan", "context_bundle", "input_manifest",
    "production_input_manifest", "knowledge_pack",
    "context_manifest_consistency_report", "quality_context_coverage_report",
)
FEEDBACK_TYPES = (
    "comment_cluster_report", "feedback_mutation_application_report",
    "feedback_plan_mutation_proposal", "platform_metric_snapshot",
    "reader_issue_set", "reader_outcome_report", "reader_state_transition",
)
PUBLISHING_TYPES = (
    "publish_gate_report", "release_package", "platform_upload_package",
    "platform_publish_receipt", "platform_review_status",
)
REVIEW_TYPES = (
    "review_issue", "review_report", "revision_plan", "revision_task",
    "chapter_quality_evidence", "quality_gate_report", "evaluation_gate",
)
MANUSCRIPT_TYPES = (
    "chapter_plan", "draft_chapter", "chapter_outcome", "review_report",
    "review_issue", "revision_plan", "revision_task", "context_bundle",
    "model_call_log", "agent_run", "execution_commit_manifest",
)
MKAOS_TYPES = (
    "source_document", "source_chunk", "knowledge_card_candidate", "knowledge_card",
    "rule_card_candidate", "rule_card", "template_card_candidate", "template_card",
    "knowledge_relation", "knowledge_graph_snapshot", "knowledge_pack",
    "knowledge_usage_binding", "knowledge_usage_event", "knowledge_quality_score",
    "knowledge_regression_case", "knowledge_governance_approval",
)
PLANNING_TYPES = (
    "topic_seed", "world_bible", "character_card", "relationship_state",
    "book_design", "book_plan", "volume_plan", "arc_plan",
    "chapter_group_plan", "chapter_plan", "ending_contract", "foreshadow_state",
    "power_state", "outline",
)
CREATIVE_LIBRARY_TYPES = (
    "platform_profile", "genre_market_profile", "quality_standard_profile",
    "style_profile", "continuity_bible",
)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    query = ctx.services.project_authority_query
    router = APIRouter(tags=["authority-assets"])

    def assets(
        types: tuple[str, ...], *, project_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        _authorize(project_id or "")
        return [
            _product_asset(row)
            for row in query.list_assets(
                project_id=project_id,
                asset_types=types,
                limit=limit,
            )
        ]

    @router.get("/assets")
    def all_assets(
        project_id: str | None = None,
        asset_type: str | None = Query(default=None, alias="type"),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        _authorize(project_id or "")
        return [
            _product_asset(row)
            for row in query.list_assets(
                project_id=project_id, asset_type=asset_type, limit=limit
            )
        ]

    @router.get("/product/analysis/reports")
    def analysis_reports(
        project_id: str | None = None,
        report_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        types = (report_type,) if report_type else ANALYSIS_TYPES
        return assets(types, project_id=project_id, limit=limit)

    @router.get("/product/context/assets")
    def context_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assets(CONTEXT_TYPES, project_id=project_id, limit=limit)

    @router.get("/product/feedback/assets")
    def feedback_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assets(FEEDBACK_TYPES, project_id=project_id, limit=limit)

    @router.get("/product/publishing/assets")
    def publishing_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assets(PUBLISHING_TYPES, project_id=project_id, limit=limit)

    @router.get("/product/review-issues")
    def review_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assets(REVIEW_TYPES, project_id=project_id, limit=limit)

    @router.get("/product/mkaos/assets")
    def mkaos_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assets(MKAOS_TYPES, project_id=project_id, limit=limit)

    @router.get("/product/planning/assets")
    def planning_assets(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return assets(PLANNING_TYPES, project_id=project_id, limit=limit)

    @router.get("/product/agents/runs")
    def agent_runs(
        project_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return [
            {
                **row,
                "agent_run_id": row["asset_id"],
                "agent_type": str((row["content"] or {}).get("agent_type") or ""),
                "operation": str((row["content"] or {}).get("operation") or ""),
                "model_provider": str((row["content"] or {}).get("model_provider") or ""),
                "model_name": str((row["content"] or {}).get("model_name") or ""),
                "token_used": int((row["content"] or {}).get("token_used") or 0),
                "token_budget": int((row["content"] or {}).get("token_budget") or 0),
                "evidence": dict((row["content"] or {}).get("evidence") or {}),
                "output_assets": list((row["content"] or {}).get("output_assets") or []),
            }
            for row in assets(("agent_run",), project_id=project_id, limit=limit)
        ]

    @router.get("/product/agents/events")
    def agent_events(
        project_id: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        _authorize(project_id)
        return [
            {
                "id": event["event_id"],
                "agent_run_id": event["aggregate_id"],
                "agent_run_asset_version_id": "",
                "event_type": event["event_type"],
                "status": str((event["payload"] or {}).get("status") or "recorded"),
                "message": str((event["payload"] or {}).get("message") or ""),
                "payload": event["payload"],
                "project_id": event["project_id"],
                "created_at": event["created_at"],
            }
            for event in ctx.services.task_authority_query.timeline(
                project_id=project_id, limit=limit
            )
            if "agent" in event["aggregate_type"].lower()
            or "agent" in event["event_type"].lower()
        ]

    @router.get("/product/runtime/trace-timeline")
    def runtime_trace_timeline(
        project_id: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        _authorize(project_id)
        events = ctx.services.task_authority_query.timeline(
            project_id=project_id, limit=limit
        )
        spans = [
            {
                "span_id": event["event_id"],
                "span_type": event["aggregate_type"],
                "name": event["event_type"],
                "status": str((event["payload"] or {}).get("status") or "recorded"),
                "started_at": event["created_at"],
                "finished_at": event["created_at"],
                "attributes": event["payload"],
                "correlation_id": event["correlation_id"],
                "causation_id": event["causation_id"],
            }
            for event in events
        ]
        return {
            "spans": spans,
            "summary": {"span_count": len(spans), "source": "state_event"},
            "authority": "postgresql",
        }

    @router.get("/product/runtime/cost-dashboard")
    def runtime_cost_dashboard(
        project_id: str | None = None,
    ) -> dict[str, Any]:
        rows = assets(
            ("cost_ledger", "model_call_log"), project_id=project_id, limit=500
        )
        ledger = [row for row in rows if row["type"] == "cost_ledger"]
        calls = [row for row in rows if row["type"] == "model_call_log"]
        total_cost = sum(
            float((row.get("content") or {}).get("cost") or 0) for row in ledger
        )
        return {
            "asset": {
                "content": {
                    "summary": {
                        "ledger_count": len(ledger),
                        "model_call_count": len(calls),
                        "total_cost": total_cost,
                        "average_quality_score": 0,
                        "cost_per_quality_point": 0,
                        "quality_basis": "not_calibrated",
                    },
                    "snapshots": {},
                    "recommendations": [],
                }
            },
            "authority": "postgresql",
        }

    @router.get("/product/libraries/creative")
    def creative_libraries(
        limit_per_library: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        rows = assets(
            CREATIVE_LIBRARY_TYPES, project_id=None,
            limit=min(1000, limit_per_library * len(CREATIVE_LIBRARY_TYPES)),
        )
        return [
            {
                "key": asset_type,
                "title": asset_type.replace("_", " ").title(),
                "asset_types": [asset_type],
                "assets": [row for row in rows if row["type"] == asset_type][
                    :limit_per_library
                ],
            }
            for asset_type in CREATIVE_LIBRARY_TYPES
        ]

    @router.get("/product/manuscript/workbench")
    def manuscript_workbench(
        project_id: str,
        draft_version_id: str = "",
        draft_path: str = "",
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        if draft_path and not draft_path.startswith("authority-output:"):
            raise HTTPException(
                status_code=422,
                detail="filesystem draft paths are not valid Authority identities",
            )
        selected_id = draft_version_id or draft_path
        rows = assets(MANUSCRIPT_TYPES, project_id=project_id, limit=limit)
        selected = next(
            (
                row for row in rows
                if row["asset_version_id"] == selected_id
                and row["type"] == "draft_chapter"
            ),
            next((row for row in rows if row["type"] == "draft_chapter"), None),
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[row["type"]].append(row)
        return {
            "project_id": project_id,
            "selected_draft_version_id": (
                selected["asset_version_id"] if selected else ""
            ),
            "selected_draft": selected,
            "chapters": _chapter_rows(grouped["draft_chapter"]),
            "versions": grouped["draft_chapter"],
            "generation_runs": grouped["model_call_log"],
            "context_bundles": grouped["context_bundle"],
            "context_sources": [],
            "reviews": grouped["review_report"] + grouped["review_issue"],
            "revision_plans": grouped["revision_plan"] + grouped["revision_task"],
            "editor_artifacts": grouped["execution_commit_manifest"],
            "agent_runs": grouped["agent_run"],
            "agent_events": [],
            "trace_summary": {
                "has_selected_draft": selected is not None,
                "context_source_count": 0,
                "generation_run_count": len(grouped["model_call_log"]),
                "review_count": len(grouped["review_report"] + grouped["review_issue"]),
                "editor_artifact_count": len(grouped["execution_commit_manifest"]),
                "agent_run_count": len(grouped["agent_run"]),
                "agent_statuses": {},
                "ready_for_review": bool(
                    selected and selected["lifecycle"] == "ACTIVE"
                    and selected["eligibility"] == "ELIGIBLE"
                ),
            },
            "authority": "postgresql",
        }

    return router


def _authorize(project_id: str) -> None:
    principal = build_trusted_principal_resolver().resolve_api_principal()
    if not project_id:
        if "*" not in principal.project_scope:
            raise HTTPException(
                status_code=403,
                detail="a project_id is required for a project-scoped Authority principal",
            )
        return
    try:
        principal.require("asset.authority.query", project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _product_asset(row: dict[str, Any]) -> dict[str, Any]:
    content = dict(row.get("content") or {})
    title = str(
        content.get("title") or content.get("name") or content.get("label")
        or row["type"].replace("_", " ").title()
    )
    return {
        **row,
        "path": f"authority://asset-version/{row['asset_version_id']}",
        "authority_ref": f"authority://asset-version/{row['asset_version_id']}",
        "id": row["asset_id"],
        "title": title,
        "status": row["lifecycle"],
        "asset_status": row["eligibility"],
        "risk_level": (
            "blocked" if row["governance"] != "CLEAR"
            or row["eligibility"] != "ELIGIBLE" else "clear"
        ),
        "summary": str(content.get("summary") or content.get("description") or ""),
        "tags": list(content.get("tags") or []),
        "source": "postgresql-authority",
    }


def _chapter_rows(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for draft in drafts:
        grouped[str((draft.get("content") or {}).get("chapter") or 0)].append(draft)
    rows: list[dict[str, Any]] = []
    for chapter, versions in grouped.items():
        latest = max(versions, key=lambda row: int(row.get("version_number") or 0))
        rows.append(
            {
                "chapter": int(chapter),
                "latest_draft_version_id": latest["asset_version_id"],
                "latest_title": latest["title"],
                "draft_count": len(versions),
                "review_count": 0,
                "latest_updated_at": latest["updated_at"],
                "status": latest["lifecycle"],
            }
        )
    return sorted(rows, key=lambda row: row["chapter"])


__all__ = ["create_router"]
