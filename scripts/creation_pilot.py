from __future__ import annotations

from decimal import Decimal
from typing import Any

from novel_forge.modules.book_design_authority.application import (
    BookDesignAuthorityCommand,
)
from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
from novel_forge.modules.project_authority.application import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.project_authority.query import ProjectAuthorityQuery
from novel_forge.modules.command_kernel.errors import KernelError


def freeze_routes(routes: Any) -> dict[str, Any]:
    return {
        key: {
            "model_profile": route.model_profile.to_dict(),
            "route_policy": route.route_policy.to_dict(),
            "fallback_policy": route.fallback_policy.to_dict(),
            **{
                field: getattr(route, field)
                for field in (
                    "backend_version",
                    "auth_profile_ref",
                    "prompt_version",
                    "skill_version",
                    "system_instruction_hash",
                    "template_hash",
                    "skill_content_hash",
                    "prompt_compiler_version",
                    "output_schema_ref",
                    "model_context_limit",
                    "token_accounting_method",
                    "token_accounting_evidence_ref",
                    "token_safety_margin",
                    "token_framing_overhead",
                )
            },
        }
        for key, route in sorted(routes.items())
    }


def pilot_stop_cursor(policy: dict[str, Any], *, book_target: int) -> int:
    cursor = policy.get("pilot_stop_after_chapter", 0)
    if type(cursor) is not int or cursor < 0 or cursor >= book_target:
        raise ValueError("pilot_stop_after_chapter must be a nonnegative integer below the full Book target")
    intervention = (policy.get("future_plan_change") or {}).get("after_chapter", 0)
    if cursor and intervention >= cursor:
        raise ValueError("Future plan intervention must precede the frozen pilot stop cursor")
    return cursor


def verify_future_plan_change(*, composition: Any, book_run_id: str, proposal_id: str,
                              intervention: dict[str, Any]) -> dict[str, Any]:
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    book = composition.authority.require(book_run_id)
    proposal = composition.plan_change.require(proposal_id)
    boundary = intervention.get("after_chapter")
    if (type(boundary) is not int or boundary < 1
        or proposal["project_id"] != book["project_id"] or proposal["book_id"] != book["book_id"]
        or proposal["status"] != "ACTIVE" or proposal["source_type"] != "HUMAN_FEEDBACK"
        or book["accepted_through_chapter"] < boundary):
        raise ValueError("Continuation requires the owned ACTIVE future PlanChange at the frozen intervention")
    query = AuthorityAssetQuery(composition.authority.database_url)
    source = query.require(project_id=book["project_id"], asset_version_id=proposal["source_evidence_version_id"])
    changed = query.require(project_id=book["project_id"], asset_version_id=proposal["proposed_asset_version_id"])
    if (source.content.get("directive") != intervention.get("directive")
        or source.content.get("accepted_through_chapter") != boundary
        or source.content.get("book_id") != book["book_id"]
        or not changed.content.get("chapter_range")
        or changed.content["chapter_range"][0] <= boundary):
        raise ValueError("Future change must preserve accepted history and implement the frozen directive")
    resumed = composition.resume_after_plan_change(
        book_run_id=book_run_id, proposal_id=proposal_id, principal=composition.principal,
    )
    return {"proposal_id": proposal_id, "source_asset_version_id": source.asset_version_id,
            "proposed_asset_version_id": changed.asset_version_id,
            "after_chapter": boundary, "result": resumed}


def authorize_total(values: dict[str, str], amount: str, reference: str) -> str:
    if not amount or not reference.strip():
        raise ValueError(
            "Explicit total USD authorization and its reference are required; credentials and daily caps are not authorization"
        )
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


def authorize_execution(
    values: dict[str, str], amount: str, reference: str
) -> dict[str, Any]:
    """Bind a run to either a priced budget or the configured account grant."""

    accounting_basis = (
        str(values.get("NOVEL_FORGE_CODEX_ACCOUNTING_MODE") or "PRICED").strip().upper()
    )
    if accounting_basis == "PRICED":
        return {
            "accounting_basis": accounting_basis,
            "authorization_ref": reference,
            "authorized_total_usd": authorize_total(values, amount, reference),
            "monetary_cost_status": "ESTIMATED",
        }
    if accounting_basis != "ACCOUNT_ENTITLEMENT":
        raise ValueError("Unsupported Provider accounting basis")
    configured_reference = str(
        values.get("NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF") or ""
    ).strip()
    if amount.strip():
        raise ValueError(
            "Account-entitlement execution cannot declare a USD authorization"
        )
    if not reference.strip() or reference.strip() != configured_reference:
        raise ValueError(
            "Account-entitlement execution requires the exact configured authorization reference"
        )
    return {
        "accounting_basis": accounting_basis,
        "authorization_ref": configured_reference,
        "authorized_total_usd": None,
        "monetary_cost_status": "UNKNOWN",
    }


def prepare_pilot_book(
    *,
    composition: Any,
    principal: Any,
    project_id: str,
    workspace_id: str,
    book_id: str,
    run_key: str,
    title: str,
    frozen: dict[str, Any],
    initialize: bool,
) -> dict[str, Any]:
    application = composition.formation.generation.book_design
    if initialize:
        principal.require("book_design.authority.execute", project_id)
        if not workspace_id:
            raise ValueError(
                "Initializing a pilot requires an explicit isolated workspace id"
            )
        query = ProjectAuthorityQuery(application.database_url)
        try:
            project = query.require_project(project_id)
        except KernelError as exc:
            if exc.code != "PROJECT_NOT_FOUND":
                raise
            ProjectAuthorityApplication(
                application.database_url,
                application_build_id=application.application_build_id,
                commit_sha=application.commit_sha,
            ).execute(
                ProjectAuthorityCommand(
                    definition_name="project_lifecycle.create",
                    project_id=project_id,
                    workspace_id=workspace_id,
                    actor_id=principal.principal_id,
                    idempotency_key=f"{run_key}:project",
                    trace_id=f"trace:{run_key}",
                    correlation_id=run_key,
                    payload={"title": title},
                ),
                principal=principal,
            )
            project = query.require_project(project_id)
        if project["status"] != "ACTIVE":
            raise ValueError("Pilot initialization requires an ACTIVE project")
        if project["workspace_id"] != workspace_id:
            raise ValueError("Pilot initialization requires the existing project's primary workspace")
        application.execute(
            BookDesignAuthorityCommand(
                definition_name="book.create",
                project_id=project_id,
                workspace_id=workspace_id,
                book_id=book_id,
                actor_id=principal.principal_id,
                service_identity="creation-pilot",
                idempotency_key=f"{run_key}:book",
                trace_id=f"trace:{run_key}",
                correlation_id=run_key,
                payload={
                    "title": title,
                    "production_profile": frozen["creation_policy"]["profiles"][
                        "production_profile"
                    ]["content"],
                    "runtime_policy": {"creation_pilot": frozen},
                    "release_identity": frozen["implementation_identity"],
                },
            ),
            principal=principal,
        )
    book = BookDesignAuthorityQuery(application.database_url).require_book(
        project_id=project_id, book_id=book_id
    )
    if book["runtime_policy"].get("creation_pilot") != frozen:
        raise ValueError(
            "Pilot brief, policy, run key, implementation or model configuration differs from the registered Book; use the original frozen configuration"
        )
    return book
