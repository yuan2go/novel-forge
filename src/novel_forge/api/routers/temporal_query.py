"""Accepted-state temporal query routes for PostgreSQL Authority."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.api.routers.context import ProductRouterContext


class TemporalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    book_id: str = Field(min_length=1)
    query: Literal[
        "character_state_at",
        "character_knows_at",
        "character_believes_at",
        "character_arc_at",
        "conflict_at",
        "obligations_at",
        "state_at",
        "relationship_at",
        "world_state_at",
        "power_state_at",
        "plot_thread_at",
        "foreshadow_state_at",
        "pending_promises_at",
        "changes_between",
    ]
    chapter: int | None = Field(default=None, ge=1)
    chapter_from: int | None = Field(default=None, ge=0)
    chapter_to: int | None = Field(default=None, ge=1)
    character_id: str = ""
    fact_id: str = ""
    proposition_id: str = ""
    arc_id: str = ""
    conflict_id: str = ""
    obligation_type: Literal[
        "PROMISE", "FORESHADOWING", "MYSTERY", "CONFLICT", "OPEN_LOOP"
    ] | None = None
    unresolved_only: bool = False
    source_id: str = ""
    target_id: str = ""
    thread_id: str = ""

    @model_validator(mode="after")
    def validate_query_arguments(self) -> "TemporalQueryRequest":
        required = {
            "character_state_at": ("chapter", "character_id"),
            "character_knows_at": ("chapter", "character_id", "fact_id"),
            "character_believes_at": (
                "chapter",
                "character_id",
                "proposition_id",
            ),
            "character_arc_at": ("chapter", "character_id", "arc_id"),
            "conflict_at": ("chapter", "conflict_id"),
            "obligations_at": ("chapter",),
            "state_at": ("chapter",),
            "relationship_at": ("chapter", "source_id", "target_id"),
            "world_state_at": ("chapter",),
            "power_state_at": ("chapter", "character_id"),
            "plot_thread_at": ("chapter", "thread_id"),
            "foreshadow_state_at": ("chapter", "thread_id"),
            "pending_promises_at": ("chapter",),
            "changes_between": ("chapter_from", "chapter_to"),
        }[self.query]
        missing = [name for name in required if getattr(self, name) in (None, "")]
        if missing:
            raise ValueError(f"{self.query} requires {', '.join(missing)}")
        if (
            self.query == "changes_between"
            and self.chapter_from is not None
            and self.chapter_to is not None
            and self.chapter_to <= self.chapter_from
        ):
            raise ValueError("changes_between requires chapter_to > chapter_from")
        return self


def create_router(ctx: ProductRouterContext) -> APIRouter:
    router = APIRouter(
        prefix="/product/temporal-query",
        tags=["product-temporal-query"],
    )
    service = ctx.services.temporal_query_service

    @router.post("")
    def temporal_query(request: TemporalQueryRequest) -> dict[str, object]:
        try:
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("canon.authority.query", request.project_id)
            if request.query == "changes_between":
                return service.changes_between(
                    request.project_id,
                    request.book_id,
                    int(request.chapter_from),
                    int(request.chapter_to),
                )
            if request.query == "relationship_at":
                return service.relationship_at(
                    request.project_id,
                    request.book_id,
                    request.source_id,
                    request.target_id,
                    int(request.chapter),
                )
            if request.query == "character_knows_at":
                return service.character_knows_at(
                    request.project_id,
                    request.book_id,
                    request.character_id,
                    request.fact_id,
                    int(request.chapter),
                )
            if request.query == "character_believes_at":
                return service.character_believes_at(
                    request.project_id,
                    request.book_id,
                    request.character_id,
                    request.proposition_id,
                    int(request.chapter),
                )
            if request.query == "character_arc_at":
                return service.character_arc_at(
                    request.project_id,
                    request.book_id,
                    request.character_id,
                    request.arc_id,
                    int(request.chapter),
                )
            if request.query == "conflict_at":
                return service.conflict_at(
                    request.project_id,
                    request.book_id,
                    request.conflict_id,
                    int(request.chapter),
                )
            if request.query == "obligations_at":
                return service.obligations_at(
                    request.project_id,
                    request.book_id,
                    int(request.chapter),
                    obligation_types=(
                        (request.obligation_type,)
                        if request.obligation_type
                        else ()
                    ),
                    unresolved_only=request.unresolved_only,
                )
            if request.query in {"character_state_at", "power_state_at"}:
                method = getattr(service, request.query)
                return method(
                    request.project_id,
                    request.book_id,
                    request.character_id,
                    int(request.chapter),
                )
            if request.query in {"plot_thread_at", "foreshadow_state_at"}:
                method = getattr(service, request.query)
                return method(
                    request.project_id,
                    request.book_id,
                    request.thread_id,
                    int(request.chapter),
                )
            method = getattr(service, request.query)
            return method(request.project_id, request.book_id, int(request.chapter))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return router


__all__ = ["TemporalQueryRequest", "create_router"]
