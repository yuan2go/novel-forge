from __future__ import annotations

import inspect
from types import SimpleNamespace

from novel_forge.api.routers.quality_qualification import create_router


def test_quality_qualification_router_exposes_operator_and_reviewer_safe_paths() -> (
    None
):
    context = SimpleNamespace(
        services=SimpleNamespace(
            quality_qualification_authority=object(),
        )
    )
    router = create_router(context)
    routes = {
        (route.path, method) for route in router.routes for method in route.methods
    }

    assert {
        ("/api/quality-qualification/campaigns", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}", "GET"),
        ("/api/quality-qualification/campaigns/{campaign_id}/freeze", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}/start", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}/resume", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}/subjects", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}/evidence", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}/evaluate", "POST"),
        ("/api/quality-qualification/campaigns/{campaign_id}/blind-packs", "GET"),
        ("/api/quality-qualification/blind-packs/{pack_id}", "GET"),
        ("/api/quality-qualification/blind-decisions", "POST"),
    } <= routes


def test_reviewer_pack_endpoint_never_accepts_or_returns_private_mapping() -> None:
    source = inspect.getsource(create_router)

    assert "private_mapping" not in source
    assert "reviewer_pack" in source
    assert "record_human_decision" in source
