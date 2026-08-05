import inspect
from types import SimpleNamespace

from novel_forge.api.routers.capability_pack_authority import create_router
from novel_forge.cli import _run_capability_pack_command


def test_capability_pack_router_exposes_governed_lifecycle_and_queries() -> None:
    context = SimpleNamespace(
        services=SimpleNamespace(
            capability_pack_authority_application=object(),
            capability_pack_authority_query=object(),
        )
    )
    router = create_router(context)
    routes = {(route.path, method) for route in router.routes for method in route.methods}
    required = {
        ("/api/capability-packs/register", "POST"),
        ("/api/capability-packs/{pack_id}/{pack_version}/compile", "POST"),
        ("/api/capability-packs/compilations/{compilation_id}/approve", "POST"),
        ("/api/capability-packs/deployments", "POST"),
        ("/api/capability-packs/deployments/{deployment_id}/activate", "POST"),
        ("/api/capability-packs/deployments/{deployment_id}/rollback", "POST"),
        ("/api/capability-packs/deployments/{deployment_id}/drift", "GET"),
        ("/api/capability-packs/deployments/{deployment_id}/usage", "GET"),
        ("/api/capability-packs/usage", "GET"),
    }
    assert required <= routes


def test_capability_pack_cli_queries_require_authorized_project() -> None:
    source = inspect.getsource(_run_capability_pack_command)

    assert (
        'principal.require("capability_pack.authority.query", args.project_id)'
        in source
    )
