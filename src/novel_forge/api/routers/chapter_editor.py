from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class AuthorEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    chapter: int = Field(ge=1)
    base_asset_version_id: str = Field(min_length=1)
    base_asset_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    base_text_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1)
    action: Literal["save", "accept", "reject"]
    text: str | None = Field(default=None, max_length=200000)
    rights_basis: Literal["ORIGINAL_AUTHOR_INPUT", "AUTHORIZED_INPUT"] = "ORIGINAL_AUTHOR_INPUT"
    allowed_ranges: list[dict[str, int]] | None = None
    scene_artifacts: list[dict[str, Any]] | None = None
    scene_separators: list[str] | None = None
    edit_intent: Literal["PROSE_ONLY", "PLAN_STRUCTURE_CHANGE"] = "PROSE_ONLY"
    candidate_asset_version_id: str = ""
    rationale: str = ""
    source_review_run_id: str = ""
    source_lineage_id: str = ""


class AuthorBookReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    chapter_request_id: str = Field(min_length=1)
    expected_book_version: int = Field(ge=0)
    expected_root_operation_id: str = Field(min_length=1)
    candidate_asset_version_id: str = Field(min_length=1)
    decision_asset_version_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(prefix="/product/editor", tags=["chapter-author-editor"])

    def application():
        build_id, sha = authority_release_identity()
        return ChapterAuthorEditingApplication(ctx.services.chapter_query.database_url, application_build_id=build_id, commit_sha=sha)

    def execute(call):
        try:
            return call(build_trusted_principal_resolver().resolve_api_principal())
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except KernelError as error:
            raise HTTPException(status_code=409, detail={"code": error.code, "message": error.message}) from error
        except (ValueError, TypeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/drafts")
    def list_drafts(project_id: str = Query(min_length=1)):
        def read(principal):
            principal.require("chapter.authority.query", project_id)
            with AuthorityUnitOfWork(application().database_url) as uow:
                uow.cursor.execute(
                    """SELECT output.asset_version_id, asset.asset_type, version.content, version.content_hash,
                              root.workspace_id, root.command_payload, book.book_id
                       FROM authority_operation_output_asset output
                       JOIN authority_asset asset USING(asset_id)
                       JOIN authority_asset_version version USING(asset_version_id)
                       JOIN authority_operation op ON op.operation_id=output.operation_id
                       JOIN authority_operation root ON root.operation_id=op.root_operation_id
                       LEFT JOIN authority_book_chapter_request request ON request.chapter_root_operation_id=root.operation_id
                       LEFT JOIN authority_book_production book ON book.book_run_id=request.book_run_id
                       WHERE asset.project_id=%s AND asset.asset_type IN ('draft_chapter','draft_version','best_draft_candidate')
                       ORDER BY version.created_at DESC LIMIT 200""", [project_id])
                rows = uow.cursor.fetchall()
            return [{"project_id": project_id, "workspace_id": row[4],
                     "book_id": row[6] or row[5].get("book_id") or (row[5].get("preparation_report") or {}).get("book_id") or "",
                     "chapter": int(row[5].get("chapter") or 0), "asset_version_id": row[0], "asset_type": row[1],
                     "title": row[2].get("title") or f"第 {row[5].get('chapter')} 章", "content_hash": row[3]}
                    for row in rows]
        return execute(read)

    @router.get("/draft")
    def require_draft(project_id: str, workspace_id: str, book_id: str, chapter: int, base_asset_version_id: str):
        return execute(lambda principal: application().require(project_id=project_id, workspace_id=workspace_id,
                                                              book_id=book_id, chapter=chapter,
                                                              base_asset_version_id=base_asset_version_id, principal=principal))

    @router.post("/commands")
    def command(request: AuthorEditRequest):
        body = request.model_dump(exclude_none=True)
        action, key = body.pop("action"), body.pop("idempotency_key")
        return execute(lambda principal: application().execute(action=action, payload=body, idempotency_key=key, principal=principal))

    @router.post("/book-reviews", status_code=202)
    def book_review(request: AuthorBookReviewRequest):
        def submit(principal):
            from novel_forge.modules.book_authority.author_revision import replace_author_chapter
            authority = ctx.services.book_production.authority
            previous = authority.require_chapter_request(request.chapter_request_id)
            book = authority.require(previous["book_run_id"])
            if (book["project_id"],book["workspace_id"],book["book_id"]) != (request.project_id,request.workspace_id,request.book_id):
                raise KernelError("AUTHOR_BOOK_SCOPE_CONFLICT", "Book review request does not match its exact owner")
            result = replace_author_chapter(authority, principal=principal,
                **request.model_dump(exclude={"project_id","workspace_id","book_id"}))
            return {**result,"root_operation_id":result["chapter_root_operation_id"],"query_url":
                f"/product/production/chapter-authority/run?project_id={request.project_id}&root_operation_id={result['chapter_root_operation_id']}"}
        return execute(submit)

    return router
