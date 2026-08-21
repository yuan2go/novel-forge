from __future__ import annotations

from types import SimpleNamespace

from novel_forge.api.routers.agent_runtime import create_router


def test_agent_runtime_authority_routes_cover_control_and_query_surface() -> None:
    services = SimpleNamespace(
        agent_runtime_authority_application=SimpleNamespace(),
        agent_runtime_query=SimpleNamespace(),
    )
    router = create_router(
        SimpleNamespace(services=services, models={}, app_settings=SimpleNamespace())
    )
    routes = {
        (method, route.path)
        for route in router.routes
        for method in route.methods
    }

    assert ("POST", "/product/production/agent-runtime/agent-sessions") in routes
    assert (
        "GET",
        "/product/production/agent-runtime/agent-sessions/{agent_session_id}",
    ) in routes
    assert ("POST", "/product/production/agent-runtime/agent-runs") not in routes
    assert (
        "POST", "/product/production/agent-runtime/migration/agent-runs"
    ) in routes
    assert (
        "GET", "/product/production/agent-runtime/migration/agent-runs"
    ) in routes
    assert (
        "GET",
        "/product/production/agent-runtime/health/recovery",
    ) in routes
    assert (
        "POST",
        "/product/production/agent-runtime/migration/agent-runs/{agent_run_id}/cancel",
    ) in routes
    assert (
        "POST",
        "/product/production/agent-runtime/migration/agent-runs/{agent_run_id}/retry",
    ) in routes
    assert ("GET", "/product/production/agent-runtime/agents") in routes
    assert (
        "GET",
        "/product/production/agent-runtime/agents/{agent_id}/versions",
    ) in routes
    assert (
        "GET",
        "/product/production/agent-runtime/agent-collaborations/{session_id}",
    ) in routes
