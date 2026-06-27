from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter

from novel_forge.api.routers import analysis, assets, audit, batch, drafts, handoffs, libraries, projects, reviews, system, tasks
from novel_forge.api.routers.context import ProductRouterContext


def product_routers(ctx: ProductRouterContext) -> Iterable[APIRouter]:
    return [
        projects.create_router(ctx),
        tasks.create_router(ctx),
        assets.create_router(ctx),
        libraries.create_router(ctx),
        analysis.create_router(ctx),
        handoffs.create_router(ctx),
        system.create_router(ctx),
        batch.create_router(ctx),
        drafts.create_router(ctx),
        reviews.create_router(ctx),
        audit.create_router(ctx),
    ]
