from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.modules.book_followup_authority.prose_coordinator import (
    BookProseReviewCoordinator,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


class ProseScope(BaseModel):
    project_id: str
    workspace_id: str
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)


class ProseStart(ProseScope):
    policy: dict[str, Any]
    evidence_ranges: list[dict[str, Any]] = Field(default_factory=list)


class ProseAdvance(ProseScope):
    expected_version: int = Field(ge=0)


class ProseDisposition(ProseAdvance):
    finding_digest: str
    decision: str
    rationale: str = Field(min_length=1)
    consumer_asset_version_id: str = ""


class ProseControl(ProseAdvance):
    paused: bool
    reason: str = Field(min_length=1)


class ProsePlanChange(ProseAdvance):
    finding_digest: str
    target_asset_version_id: str
    proposed_asset_version_id: str
    rationale: str = Field(min_length=1)


class ProseProviderSample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1)
    source_operation_id: str = Field(min_length=1)
    authorization_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    predecessor_operation_id: str = ""


def create_router(ctx: Any) -> APIRouter:
    router = APIRouter(
        prefix="/product/production/book-authority/runs/{book_run_id}/prose-reviews",
        tags=["book-prose-review"],
    )

    def coordinator() -> BookProseReviewCoordinator:
        return BookProseReviewCoordinator(ctx.services.book_production.followup)

    def execute(call: Any) -> Any:
        try:
            return call(build_trusted_principal_resolver().resolve_api_principal())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KernelError as exc:
            raise HTTPException(
                status_code=409, detail={"code": exc.code, "message": exc.message}
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/provider-samples", status_code=202)
    def provider_sample(book_run_id: str, request: ProseProviderSample, dry_run: bool = False) -> Any:
        from novel_forge.modules.book_followup_authority.prose_sampling import ProseReviewSampleCommand

        def sample(actor: Any) -> Any:
            app = ctx.services.book_production.followup
            command = ProseReviewSampleCommand(actor_id=actor.principal_id, **request.model_dump())
            prepared = app.prepare_prose_sample(command, principal=actor)
            if prepared["command_payload"]["book_run_id"] != book_run_id:
                raise KernelError("PROSE_SAMPLE_ORIGIN_INVALID", "sample source belongs to another Book run")
            return prepared if dry_run else app.admit_prose_sample(command, principal=actor)

        return execute(sample)

    @router.post("")
    def start(book_run_id: str, request: ProseStart) -> Any:
        return execute(
            lambda actor: coordinator().start(
                book_run_id=book_run_id, principal=actor, **request.model_dump()
            )
        )

    @router.get("")
    def list_runs(book_run_id: str, project_id: str, workspace_id: str) -> Any:
        def query(actor: Any) -> Any:
            actor.require("book.authority.query", project_id)
            with AuthorityUnitOfWork(coordinator().database_url) as uow:
                uow.cursor.execute(
                    "SELECT run_id,manifest_digest,exact_release_sha FROM authority_book_prose_review_run WHERE project_id=%s AND workspace_id=%s AND book_run_id=%s ORDER BY created_at DESC LIMIT 100",
                    [project_id, workspace_id, book_run_id],
                )
                return [
                    {
                        "run_id": row[0],
                        "manifest_digest": row[1],
                        "exact_release_sha": row[2],
                    }
                    for row in uow.cursor.fetchall()
                ]

        return execute(query)

    @router.get("/{run_id}")
    def report(
        book_run_id: str, run_id: str, project_id: str, workspace_id: str
    ) -> Any:
        return execute(
            lambda actor: coordinator().report(
                book_run_id=book_run_id,
                run_id=run_id,
                project_id=project_id,
                workspace_id=workspace_id,
                principal=actor,
            )
        )

    @router.post("/{run_id}/advance")
    def advance(book_run_id: str, run_id: str, request: ProseAdvance) -> Any:
        return execute(
            lambda actor: coordinator().advance(
                book_run_id=book_run_id,
                run_id=run_id,
                principal=actor,
                **request.model_dump(),
            )
        )

    @router.post("/{run_id}/findings/{lineage_id}/disposition")
    def disposition(
        book_run_id: str, run_id: str, lineage_id: str, request: ProseDisposition
    ) -> Any:
        return execute(
            lambda actor: coordinator().disposition(
                book_run_id=book_run_id,
                run_id=run_id,
                lineage_id=lineage_id,
                principal=actor,
                **request.model_dump(),
            )
        )

    @router.post("/{run_id}/control")
    def control(book_run_id: str, run_id: str, request: ProseControl) -> Any:
        return execute(
            lambda actor: coordinator().control(
                book_run_id=book_run_id,
                run_id=run_id,
                principal=actor,
                **request.model_dump(),
            )
        )

    @router.post("/{run_id}/findings/{lineage_id}/plan-change")
    def plan_change(
        book_run_id: str, run_id: str, lineage_id: str, request: ProsePlanChange
    ) -> Any:
        return execute(
            lambda actor: coordinator().propose_plan_change(
                plan_change=ctx.services.book_production.plan_change,
                book_run_id=book_run_id,
                run_id=run_id,
                lineage_id=lineage_id,
                principal=actor,
                **request.model_dump(),
            )
        )

    @router.post("/{run_id}/findings/{lineage_id}/impact-preview")
    def impact_preview(
        book_run_id: str, run_id: str, lineage_id: str, request: ProsePlanChange
    ) -> Any:
        return execute(
            lambda actor: coordinator().impact_preview(
                plan_change=ctx.services.book_production.plan_change,
                book_run_id=book_run_id,
                run_id=run_id,
                lineage_id=lineage_id,
                principal=actor,
                **request.model_dump(),
            )
        )

    return router
