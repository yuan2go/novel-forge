from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import Any


def add_creation_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-creation", help="start or continue native template-driven Book creation")
    parser.add_argument("action", choices=("start", "continue"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--book-id", default="")
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--formation-run-id", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--creation-policy-file", type=Path, default=Path("config/execution_templates/creation_inputs.json"))
    parser.add_argument("--execution-template-file", type=Path, default=Path("config/execution_templates/creative_validation.json"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--maximum-ticks", type=int, default=100)
    parser.add_argument("--work-window-seconds", type=int, default=300)
    parser.add_argument("--yield-after-window", action="store_true")
    successor = subparsers.add_parser("authority-opening-resource-successor", help="admit new resource semantics for unexecuted Opening work")
    successor.add_argument("--project-id", required=True)
    successor.add_argument("--opening-run-id", required=True)
    successor.add_argument("--expected-version", required=True, type=int)
    successor.add_argument("--idempotency-key", required=True)


def run_creation_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import (authority_release_identity, build_trusted_principal_resolver,
        build_content_authority_application, build_production_execution_composition,
        build_chapter_authority_application, build_book_production_composition)
    from novel_forge.modules.book_design_authority.formation_domain import StoryFormationInput, deterministic_story_formation_run_id
    from novel_forge.modules.book_design_authority.formation import StartStoryFormationCommand
    from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
    from novel_forge.modules.content_authority.application import ContentOperationRequest
    from novel_forge.modules.book_authority.creation_runtime import continue_creation
    from novel_forge.modules.production_execution.execution_template import selected_book_template
    from novel_forge.modules.capability_packs.validation_deployment import (
        install_chapter_validation_pack, install_longform_validation_pack, register_validation_runtime_definitions)
    from novel_forge.modules.capability_packs.longform_profiles import build_story_planning_pack_profile
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    if settings.environment != "validation" or args.maximum_ticks <= 0 or args.work_window_seconds <= 0:
        raise ValueError("Creative creation requires validation runtime and positive execution window")
    args = SimpleNamespace(**vars(args))
    if args.action == "start" and args.idempotency_key:
        args.idempotency_key = f"creation:{args.project_id}:{args.book_id}:{args.idempotency_key}"
    runtime_values = dict(os.environ)
    pack_scope = hashlib.sha256(args.project_id.encode()).hexdigest()[:24]
    runtime_values.setdefault("NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID", "chapter_generation_pack.creative." + pack_scope)
    runtime_values.setdefault("NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID", "story_planning_pack.creative." + pack_scope)
    settings = replace(settings, root=args.repository_root.resolve())
    resolver = build_trusted_principal_resolver()
    principal = resolver.resolve_api_principal()
    principal.require("book.authority.execute", args.project_id)
    build_id, sha = authority_release_identity()
    content = build_content_authority_application(settings)
    formation_id = args.formation_run_id
    existing_formation = None
    if args.action == "start":
        if not args.input_file or not all((args.workspace_id, args.book_id, args.idempotency_key)):
            raise ValueError("Start requires current work input, exact Book scope and stable idempotency key")
        inputs = json.loads(args.input_file.read_text())
        required = {"version", "brief", "title", "target_chapters", "language_contract"}
        if not required <= set(inputs) or set(inputs) - required - {"chapter_length"} or inputs["version"] != "creation-request.v1":
            raise ValueError("Creation input must declare current brief, title, scope and language")
        if (not isinstance(inputs["target_chapters"], int) or isinstance(inputs["target_chapters"], bool)
                or not 1 <= inputs["target_chapters"] <= 10000 or not isinstance(inputs["brief"], dict)
                or not isinstance(inputs["title"], str) or not inputs["title"].strip()
                or not isinstance(inputs["language_contract"], dict)
                or not isinstance(inputs["language_contract"].get("required_language"), str)
                or not inputs["language_contract"]["required_language"].strip()):
            raise ValueError("Creation requires a typed current work request")
        from novel_forge.modules.creative.domain import validate_creative_brief
        inputs["brief"] = validate_creative_brief(inputs["brief"])
        profiles = deepcopy(json.loads(args.creation_policy_file.read_text()))
        from novel_forge.modules.production_execution.codex_model_catalog import parse_codex_model_catalog
        catalog = parse_codex_model_catalog(os.environ.get("NOVEL_FORGE_CODEX_ROUTER_MODELS", ""))
        windows = [model["context_limit"] - model["output_limit"] for model in catalog if model["role"] == "PRIMARY"]
        if not windows or max(windows) <= 0:
            raise ValueError("CREATION_CONTEXT_WINDOW_REQUIRED")
        profile_content = profiles["profiles"]["production_profile"]["content"]
        profile_content.setdefault("chapter_context_policy", {"version": "book-chapter-context.v1",
            "draft_profile": "draft-context-profile-v4", "draft_token_budget": max(windows), "quality_token_budget": max(windows)})
        profile_content.setdefault("world_production_policy", {"version": "world-production-policy.v4",
            "max_provider_stages": 2, "context_token_budget": min(512000, max(windows))})
        profiles["profiles"]["production_profile"]["content"].update(
            target_chapter_count=inputs["target_chapters"], language_contract=inputs["language_contract"])
        if "chapter_length" in inputs:
            length = inputs["chapter_length"]
            if (not isinstance(length, dict) or set(length) != {"minimum", "maximum"}
                    or any(not isinstance(value, int) or isinstance(value, bool) for value in length.values())
                    or not 1 <= length["minimum"] <= length["maximum"] <= 100000):
                raise ValueError("CREATION_CHAPTER_LENGTH_INVALID")
            for fact in profiles["profiles"]["platform_profile"]["content"]["structured_facts"]:
                if fact["key"] == "platform_rules":
                    fact["value"]["chapter_length"] = dict(length)
            profiles["profiles"]["production_profile"]["content"]["chapter_length"] = dict(length)
        formation_id = deterministic_story_formation_run_id(project_id=args.project_id, book_id=args.book_id,
            stable_idempotency_key=args.idempotency_key)
        from novel_forge.modules.production_execution.execution_template import selected_template
        from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
        selected = selected_template(PostgresRoutingRegistry(settings.database_url).policy(args.project_id).get("policy", {}), args.book_id)
        if selected and selected["mode"] != "CREATIVE_VALIDATION":
            raise ValueError("CREATION_REQUIRES_EXPLICIT_VALIDATION_TEMPLATE")
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s AND formation_run_id<>%s", [args.project_id, args.book_id, formation_id])
            if uow.cursor.fetchone():
                raise ValueError("CREATION_ALREADY_ADMITTED_USE_ORIGINAL_FORMATION")
        ensure_creation_scope(settings, args, principal=principal, title=inputs["title"], build_id=build_id, sha=sha)
        from novel_forge.modules.command_kernel.errors import KernelError
        from novel_forge.modules.book_design_authority.application import BookDesignAuthorityApplication, BookDesignAuthorityCommand
        query = BookDesignAuthorityQuery(settings.database_url)
        try:
            book = query.require_book(project_id=args.project_id, book_id=args.book_id)
        except KernelError as error:
            if error.code != "BOOK_NOT_FOUND":
                raise
            native = BookDesignAuthorityApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
            native.execute(BookDesignAuthorityCommand(definition_name="book.create", project_id=args.project_id,
                workspace_id=args.workspace_id, book_id=args.book_id, actor_id=principal.principal_id,
                service_identity="native-creation", idempotency_key=args.idempotency_key + ":book",
                trace_id="trace:" + args.idempotency_key, correlation_id=formation_id,
                payload={"schema_version": "book-authority.v1", "title": inputs["title"],
                    "production_profile": profiles["profiles"]["production_profile"]["content"],
                    "runtime_policy": {"execution_mode": "CREATIVE_VALIDATION", "template_source": str(args.execution_template_file)},
                    "release_identity": sha}), principal=principal)
            book = query.require_book(project_id=args.project_id, book_id=args.book_id)
        if book["workspace_id"] != args.workspace_id:
            raise ValueError("Creation Book is outside the current workspace")
        brief = content.execute(ContentOperationRequest(definition_name="creative.brief.create", project_id=args.project_id,
            workspace_id=args.workspace_id, actor_id=principal.principal_id, trace_id="trace:" + args.idempotency_key,
            correlation_id=formation_id, idempotency_key=args.idempotency_key + ":brief", payload={"brief": inputs["brief"]}), principal=principal)
        frozen = StoryFormationInput(creative_brief_asset_version_id=brief.asset_version_id,
            creative_brief_content_hash=brief.content_hash, generation_policy={
                "contract_version": "formation-generation.v4", "approval_mode": "AUTO", "creative_candidates": 2,
                "target_chapters": inputs["target_chapters"], "title": inputs["title"], "creation_input_policy": profiles,
                "auto_authorization": {"contract_version": "formation-auto-authorization.v1", "policy_version": "formation-auto-policy.v1",
                    "authorization_ref": "creation:" + args.idempotency_key, "authorized_by_principal_id": principal.principal_id,
                    "project_id": args.project_id, "workspace_id": args.workspace_id, "book_id": args.book_id,
                    "formation_run_id": formation_id, "allowed_actions": ["book_design.candidate.activate",
                        "book_design.candidate.decide", "story_planning.candidate.activate", "story_planning.candidate.approve"]}})
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute("SELECT frozen_input_digest,expected_book_version FROM authority_story_formation_run WHERE formation_run_id=%s AND project_id=%s", [formation_id, args.project_id])
            existing_formation = uow.cursor.fetchone()
            if existing_formation and existing_formation[0] != frozen.digest:
                raise ValueError("CREATION_FROZEN_INPUT_DRIFT")
            admission = selected_book_template(uow.cursor, project_id=args.project_id, book_id=args.book_id, allow_literary_required=True)
        if admission is None:
            from novel_forge.cli.execution_template import run_execution_template_command
            run_execution_template_command(settings, SimpleNamespace(project_id=args.project_id,
                workspace_id=args.workspace_id, book_id=args.book_id, policy_version="creation:" + formation_id,
                idempotency_key=args.idempotency_key + ":execution-template", template_file=args.execution_template_file))
        repository_root = args.repository_root.resolve()
        hashes = register_validation_runtime_definitions(settings.database_url, application_build_id=build_id, commit_sha=sha)
        if existing_formation is None:
            install_chapter_validation_pack(settings.database_url, repository_root=repository_root,
            project_id=args.project_id, workspace_id=args.workspace_id, book_id=args.book_id,
            application_build_id=build_id, commit_sha=sha, compiler=principal, approver=principal, agent_admin=principal,
            pack_id_override=runtime_values["NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID"])
            profile = build_story_planning_pack_profile(repository_root, operation_definition_hash=hashes["planning"],
            pack_id=runtime_values["NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID"])
            install_longform_validation_pack(settings.database_url, profile=profile, pack_version="1.1.0", agent_generation=1,
            expected_activation_version=0, project_id=args.project_id, workspace_id=args.workspace_id, book_id=args.book_id,
            application_build_id=build_id, commit_sha=sha, compiler=principal, approver=principal, agent_admin=principal,
            agent_domain="story_planning", agent_scope_type="BOOK")
    elif not formation_id:
        raise ValueError("Continue requires the original Formation identity")
    execution = build_production_execution_composition(settings, env=runtime_values)
    try:
        chapter = build_chapter_authority_application(settings, execution=execution, env=runtime_values)
        composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=runtime_values)
        if args.action == "start":
            composition.formation.admit(StartStoryFormationCommand(project_id=args.project_id, workspace_id=args.workspace_id,
                book_id=args.book_id, actor_id=principal.principal_id, expected_book_version=existing_formation[1] if existing_formation else book["version"],
                stable_idempotency_key=args.idempotency_key, trace_id="trace:" + args.idempotency_key,
                correlation_id=formation_id, frozen_input=frozen), principal=principal)
        run = composition.formation.require(formation_id)
        if run["project_id"] != args.project_id:
            raise PermissionError("Formation is outside authorized project")
        progress, stagnant = None, 0
        while True:
            result = continue_creation(composition=composition, content=content, chapter=chapter, formation_run_id=formation_id,
                formation_worker=resolver.resolve_book_formation_worker_principal("creation-formation"),
                book_worker=resolver.resolve_worker_principal("creation-book"), maximum_ticks=args.maximum_ticks,
                deadline=monotonic() + args.work_window_seconds,
                creation_policy=json.loads(args.creation_policy_file.read_text()) if args.action == "continue" else None)
            if result["stop_reason"] != "YIELDED_CHECKPOINT" or args.yield_after_window:
                return {"formation_run_id": formation_id, **result}
            current = creation_progress(settings.database_url, project_id=args.project_id, formation_run_id=formation_id)
            stagnant = stagnant + 1 if current == progress else 0
            progress = current
            if stagnant >= 3:
                return {"formation_run_id": formation_id, **result, "stop_reason": "CREATION_NO_PROGRESS"}
    finally:
        execution.close()


def creation_progress(database_url: str, *, project_id: str, formation_run_id: str) -> tuple[Any, ...]:
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    with AuthorityUnitOfWork(database_url) as uow:
        uow.cursor.execute("""SELECT run.current_stage,run.lifecycle,
            (SELECT count(*) FROM authority_external_effect effect WHERE effect.project_id=run.project_id
                AND effect.request_payload #>> '{_production_execution,book_id}'=run.book_id AND effect.status='SUCCEEDED'),
            (SELECT count(*) FROM authority_book_opening_node_receipt receipt
                JOIN authority_book_opening_run opening USING(opening_run_id)
                WHERE opening.project_id=run.project_id AND opening.book_id=run.book_id),
            (SELECT COALESCE(max(accepted_through_chapter),0) FROM authority_book_production production
                WHERE production.project_id=run.project_id AND production.book_id=run.book_id)
            FROM authority_story_formation_run run WHERE run.formation_run_id=%s AND run.project_id=%s""",
            [formation_run_id, project_id])
        row = uow.cursor.fetchone()
    if row is None:
        raise ValueError("CREATION_CHECKPOINT_NOT_FOUND")
    return tuple(row)


def ensure_creation_scope(settings: Any, args: Any, *, principal: Any, title: str, build_id: str, sha: str) -> None:
    from novel_forge.modules.command_kernel.errors import KernelError
    from novel_forge.modules.project_authority.application import ProjectAuthorityApplication, ProjectAuthorityCommand
    from novel_forge.modules.project_authority.query import ProjectAuthorityQuery
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    application = ProjectAuthorityApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
    query = ProjectAuthorityQuery(settings.database_url)
    try:
        project = query.require_project(args.project_id)
    except KernelError as error:
        if error.code != "PROJECT_NOT_FOUND":
            raise
        application.execute(ProjectAuthorityCommand(definition_name="project_lifecycle.create", project_id=args.project_id,
            workspace_id=args.workspace_id, actor_id=principal.principal_id, idempotency_key=args.project_id + ":" + args.idempotency_key + ":project",
            trace_id="trace:" + args.idempotency_key, correlation_id=args.book_id, payload={"title": title}), principal=principal)
        project = query.require_project(args.project_id)
    if project["status"] != "ACTIVE":
        raise KernelError("PROJECT_LIFECYCLE_CONFLICT", "Creation requires an active authorized project")
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute("SELECT project_id,book_id,status FROM authority_workspace WHERE workspace_id=%s", [args.workspace_id])
        workspace = uow.cursor.fetchone()
    if workspace is None:
        application.execute(ProjectAuthorityCommand(definition_name="project_workspace.create", project_id=args.project_id,
            workspace_id=project["workspace_id"], actor_id=principal.principal_id, idempotency_key=args.idempotency_key + ":workspace",
            trace_id="trace:" + args.idempotency_key, correlation_id=args.book_id,
            expected_version=project["version"], expected_current_asset_version_id=project["asset_version_id"],
            payload={"workspace_id": args.workspace_id}), principal=principal)
    elif workspace[0] != args.project_id or workspace[1] not in (None, "", args.book_id) or workspace[2] != "ACTIVE":
        raise KernelError("CREATION_WORKSPACE_SCOPE_CONFLICT", args.workspace_id)


def run_opening_resource_successor_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver, build_production_execution_composition, build_chapter_authority_application, build_book_production_composition
    from novel_forge.modules.book_authority.resource_succession import adopt_resource_policy
    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.execute", args.project_id)
    execution = build_production_execution_composition(settings)
    try:
        chapter = build_chapter_authority_application(settings, execution=execution)
        composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter)
        run = composition.opening.require(args.opening_run_id)
        if run["project_id"] != args.project_id:
            raise PermissionError("Opening is outside current project")
        return adopt_resource_policy(composition.opening, opening_run_id=args.opening_run_id, principal=principal,
            expected_version=args.expected_version, idempotency_key=args.idempotency_key)
    finally:
        execution.close()
