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
from scripts.creation_checkpoints import (
    decide_reading_review,
    reading_checkpoints,
    register_reading_review,
    require_reading_decision,
)


__all__ = ["authorize_execution", "authorize_total", "freeze_routes", "pilot_stop_cursor",
           "prepare_pilot_book", "verify_future_plan_change", "reading_checkpoint_gate",
           "decide_reading_review", "reading_checkpoints", "register_reading_review", "require_reading_decision"]


def reading_checkpoint_gate(*, composition: Any, book: dict, checkpoints: tuple[int, ...],
                            resume_after_checkpoint: int, decision_version_id: str, events: Any) -> str:
    cursor = book["accepted_through_chapter"]
    current_evidence = {}
    for boundary in checkpoints[:-1]:
        if boundary < cursor or boundary == cursor == resume_after_checkpoint:
            try:
                evidence = require_reading_decision(
                    composition=composition, book_run_id=book["book_run_id"], boundary=boundary,
                    decision_version_id=decision_version_id if boundary == resume_after_checkpoint else "",
                )
            except (KernelError, ValueError) as exc:
                if book["state"] != "PAUSED":
                    composition.authority.pause(book["book_run_id"], principal=composition.principal,
                                                reason="Accepted reading checkpoint requires resolved editorial evidence")
                events({"kind": "AUTHOR_READING_REVIEW_REQUIRED", "after_chapter": boundary, "reason": str(exc)})
                return "AUTHOR_READING_REVIEW_REQUIRED"
            if boundary == cursor:
                current_evidence = evidence
            events({"kind": "AUTHOR_READING_DECISION_VERIFIED", **evidence})
    if cursor not in checkpoints[:-1]:
        return ""
    group_id = composition.query.active_chapter_group_run_id(project_id=book["project_id"], book_run_id=book["book_run_id"])
    if group_id:
        group = composition.chapter_groups.require(group_id)
        if group.get("chapter_start", 1) > cursor:
            group = {"state": "COMPLETED"}
        elif group["chapter_end"] != cursor:
            if book["state"] != "PAUSED":
                composition.authority.pause(book["book_run_id"], principal=composition.principal,
                                            reason="Reading checkpoint crosses an incomplete ChapterGroup")
            events({"kind": "AUTHOR_READING_CHECKPOINT_GROUP_BLOCKED", "after_chapter": cursor, "group_run_id": group_id})
            return "AUTHOR_READING_CHECKPOINT_GROUP_BLOCKED"
        if group["state"] == "CHAPTER_RUNNING":
            group = composition.chapter_groups.reconcile_and_accept(group_id, principal=composition.principal)
        if group["state"] == "CLOSURE_PENDING":
            group = composition.chapter_groups.close(group_id, principal=composition.principal)
            events({"kind": "ACCEPTED_GROUP_CLOSED", "group_run_id": group_id})
        if group["state"] != "COMPLETED":
            return "WAITING_ACCEPTED_GROUP_CLOSURE"
    if resume_after_checkpoint != cursor:
        if book["state"] != "PAUSED":
            composition.authority.pause(book["book_run_id"], principal=composition.principal,
                                        reason=f"Frozen author reading checkpoint after chapter {cursor}")
        events({"kind": "AUTHOR_READING_CHECKPOINT_REQUIRED", "book_run_id": book["book_run_id"],
                "after_chapter": cursor, "independent_human_review": "NOT_REVIEWED"})
        return "AUTHOR_READING_CHECKPOINT_REQUIRED"
    current = composition.authority.require(book["book_run_id"])
    if current["state"] == "PAUSED":
        if current_evidence.get("paused_book_version") != current["version"]:
            events({"kind": "AUTHOR_READING_PAUSE_VERSION_CHANGED", "after_chapter": cursor,
                    "reason": "An earlier reading approval cannot release a subsequent operator pause"})
            return "AUTHOR_READING_PAUSE_VERSION_CHANGED"
        composition.authority.resume(book["book_run_id"], principal=composition.principal,
                                     expected_version=current["version"], reason=f"Native reading decision permits continuation after chapter {cursor}")
    return ""


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
    budget_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registered_frozen = frozen
    single_book = False
    if frozen.get("comparison_budget"):
        from scripts.creation_comparison import creation_resume_semantics
        registered_frozen = creation_resume_semantics(frozen, budget_binding)
        from novel_forge.modules.command_kernel.creative_budget_contract import SINGLE_BOOK_VERSIONS
        single_book = frozen["comparison_budget"].get("contract_version") in SINGLE_BOOK_VERSIONS
        authorization = budget_binding["authorization"]
        if not single_book:
            creation_caps = authorization["authorized_cumulative_caps"]["CREATION"]
            if creation_caps["calls"] <= 0 or creation_caps["tokens"] <= 0:
                raise ValueError("Pilot initialization or resume requires positive CREATION calls and tokens")
    application = composition.formation.generation.book_design
    if initialize:
        principal.require("book_design.authority.execute", project_id)
        if not workspace_id:
            raise ValueError(
                "Initializing a pilot requires an explicit isolated workspace id"
            )
        if single_book:
            try:
                BookDesignAuthorityQuery(application.database_url).require_book(project_id=project_id, book_id=book_id)
            except KernelError as exc:
                if exc.code != "BOOK_NOT_FOUND":
                    raise
                if not authorization["business_scope"]["design_allowed"]:
                    raise ValueError("Pilot initialization requires native design authorization") from exc
                design_caps = authorization["authorized_cumulative_caps"]["DESIGN"]
                if design_caps["calls"] <= 0 or design_caps["tokens"] <= 0:
                    raise ValueError("Pilot initialization requires positive DESIGN calls and tokens") from exc
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
            from novel_forge.modules.command_kernel.creative_budget_contract import PRODUCTION_BOOK_VERSION
            if frozen.get("comparison_budget", {}).get("contract_version") != PRODUCTION_BOOK_VERSION:
                raise ValueError("Pilot initialization requires the existing project's primary workspace")
            try:
                workspace = query.require_workspace(project_id=project_id, workspace_id=workspace_id)
            except KernelError as exc:
                if exc.code != "WORKSPACE_NOT_FOUND":
                    raise
                project_application = ProjectAuthorityApplication(
                    application.database_url, application_build_id=application.application_build_id,
                    commit_sha=application.commit_sha,
                )
                project_application.execute(ProjectAuthorityCommand(
                    definition_name="project_workspace.create", project_id=project_id,
                    workspace_id=project["workspace_id"], actor_id=principal.principal_id,
                    idempotency_key=f"{run_key}:workspace", trace_id=f"trace:{run_key}", correlation_id=run_key,
                    expected_version=project["version"], expected_current_asset_version_id=project["asset_version_id"],
                    payload={"workspace_id": workspace_id},
                ), principal=principal)
                workspace = query.require_workspace(project_id=project_id, workspace_id=workspace_id)
            if workspace["status"] != "ACTIVE":
                raise ValueError("Pilot initialization requires an ACTIVE workspace")
            if workspace["book_id"] and workspace["book_id"] != book_id:
                raise KernelError("BOOK_SCOPE_CONFLICT", "workspace is already bound to another book")
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
                    "runtime_policy": {"creation_pilot": registered_frozen},
                    "release_identity": frozen["implementation_identity"],
                },
            ),
            principal=principal,
        )
    book = BookDesignAuthorityQuery(application.database_url).require_book(
        project_id=project_id, book_id=book_id
    )
    if book["runtime_policy"].get("creation_pilot") != registered_frozen:
        raise ValueError(
            "Pilot brief, policy, run key, implementation or model configuration differs from the registered Book; use the original frozen configuration"
        )
    return book
