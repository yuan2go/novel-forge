from __future__ import annotations

from decimal import Decimal
from typing import Any

from novel_forge.modules.book_design_authority.application import BookDesignAuthorityCommand
from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
from novel_forge.modules.project_authority.application import ProjectAuthorityApplication, ProjectAuthorityCommand


def freeze_routes(routes: Any) -> dict[str, Any]:
    return {key: {
        "model_profile": route.model_profile.to_dict(),
        "route_policy": route.route_policy.to_dict(),
        "fallback_policy": route.fallback_policy.to_dict(),
        **{field: getattr(route, field) for field in (
            "backend_version", "auth_profile_ref", "prompt_version", "skill_version",
            "system_instruction_hash", "template_hash", "skill_content_hash", "prompt_compiler_version",
            "output_schema_ref", "model_context_limit", "token_accounting_method",
            "token_accounting_evidence_ref", "token_safety_margin", "token_framing_overhead",
        )},
    } for key, route in sorted(routes.items())}


def authorize_total(values: dict[str, str], amount: str, reference: str) -> str:
    if not amount or not reference.strip():
        raise ValueError("Explicit total USD authorization and its reference are required; credentials and daily caps are not authorization")
    total = Decimal(amount)
    if not total.is_finite() or total <= 0:
        raise ValueError("Authorized experiment total must be finite and positive")
    existing = values.get("NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP")
    if existing:
        cap = Decimal(existing)
        if not cap.is_finite() or cap <= 0:
            raise ValueError("Existing project total cap is invalid")
        total = min(total, cap)
    values["NOVEL_FORGE_PROJECT_TOTAL_PROVIDER_CAP"] = str(total)
    return str(total)


def prepare_pilot_book(*, composition: Any, principal: Any, project_id: str, workspace_id: str,
                       book_id: str, run_key: str, title: str, frozen: dict[str, Any], initialize: bool) -> dict[str, Any]:
    application = composition.formation.generation.book_design
    if initialize:
        if not workspace_id:
            raise ValueError("Initializing a pilot requires an explicit isolated workspace id")
        ProjectAuthorityApplication(application.database_url,
            application_build_id=application.application_build_id, commit_sha=application.commit_sha).execute(
            ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=project_id,
                workspace_id=workspace_id, actor_id=principal.principal_id, idempotency_key=f"{run_key}:project",
                trace_id=f"trace:{run_key}", correlation_id=run_key, payload={"title": title}), principal=principal)
        application.execute(BookDesignAuthorityCommand(definition_name="book.create", project_id=project_id,
            workspace_id=workspace_id, book_id=book_id, actor_id=principal.principal_id,
            service_identity="creation-pilot", idempotency_key=f"{run_key}:book",
            trace_id=f"trace:{run_key}", correlation_id=run_key,
            payload={"title": title, "production_profile": frozen["creation_policy"]["profiles"]["production_profile"]["content"],
                     "runtime_policy": {"creation_pilot": frozen}, "release_identity": frozen["implementation_identity"]}), principal=principal)
    book = BookDesignAuthorityQuery(application.database_url).require_book(project_id=project_id, book_id=book_id)
    if book["runtime_policy"].get("creation_pilot") != frozen:
        raise ValueError("Pilot brief, policy, run key, implementation or model configuration differs from the registered Book; use the original frozen configuration")
    return book
