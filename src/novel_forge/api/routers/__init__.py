from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter

from novel_forge.api.routers import (
    agents,
    analysis,
    assets,
    audit,
    batch,
    context_builder,
    continuity,
    drafts,
    editor,
    evaluation,
    feedback,
    handoffs,
    impact,
    libraries,
    manuscript,
    metrics,
    production_chain,
    projects,
    reviews,
    settings,
    system,
    tasks,
    workflow_nodes,
)
from novel_forge.api.routers.context import ProductRouterContext


def product_routers(ctx: ProductRouterContext) -> Iterable[APIRouter]:
    return [
        projects.create_router(ctx),
        tasks.create_router(ctx),
        workflow_nodes.create_router(ctx),
        agents.create_router(ctx),
        assets.create_router(ctx),
        libraries.create_router(ctx),
        manuscript.create_router(ctx),
        analysis.create_router(ctx),
        context_builder.create_router(ctx),
        continuity.create_router(ctx),
        editor.create_router(ctx),
        evaluation.create_router(ctx),
        feedback.create_router(ctx),
        metrics.create_router(ctx),
        settings.create_router(ctx),
        production_chain.create_router(ctx),
        handoffs.create_router(ctx),
        impact.create_router(ctx),
        system.create_router(ctx),
        batch.create_router(ctx),
        drafts.create_router(ctx),
        reviews.create_router(ctx),
        audit.create_router(ctx),
    ]
