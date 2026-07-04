from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.api.routers.runtime_request import normalize_product_api_runtime_request
from novel_forge.modules.editor import apply_editor_patch, create_draft_diff_report, create_editor_patch, list_editor_artifacts
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-editor"])
    EditorPatchRequest = models["EditorPatchRequest"]
    EditorPatchApplyRequest = models["EditorPatchApplyRequest"]
    DraftDiffReportRequest = models["DraftDiffReportRequest"]

    @router.get("/product/editor/artifacts")
    def editor_artifacts(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
        try:
            return list_editor_artifacts(LocalStorage(app_settings.root), project_id=project_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/editor/patch")
    def editor_patch_endpoint(request: EditorPatchRequest) -> dict[str, Any]:
        try:
            runtime_request = normalize_product_api_runtime_request(request, operation="editor.create_patch")
            return create_editor_patch(
                LocalStorage(app_settings.root),
                request.draft_path,
                instructions=request.instructions,
                operations=request.operations,
                workspace_path=request.workspace_path,
                environment=str(runtime_request["environment"]),
                os_envelope=runtime_request["envelope"] or None,
                source_policy=runtime_request["source_policy"],
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/editor/apply")
    def editor_apply_endpoint(request: EditorPatchApplyRequest) -> dict[str, Any]:
        try:
            runtime_request = normalize_product_api_runtime_request(request, operation="editor.apply_patch")
            return apply_editor_patch(
                LocalStorage(app_settings.root),
                request.patch_path,
                apply=request.apply,
                change_summary=request.change_summary,
                operation_ids=request.operation_ids,
                operation_indexes=request.operation_indexes,
                environment=str(runtime_request["environment"]),
                os_envelope=runtime_request["envelope"] or None,
                source_policy=runtime_request["source_policy"],
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/editor/diff-report")
    def editor_diff_endpoint(request: DraftDiffReportRequest) -> dict[str, Any]:
        try:
            return create_draft_diff_report(LocalStorage(app_settings.root), request.base_path, request.target_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
