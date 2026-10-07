from __future__ import annotations

from pathlib import Path
from typing import Any


def add_creation_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-creation", help="start or continue native template-driven Book creation")
    parser.add_argument("action", choices=("start", "continue", "status", "choose", "recover", "cancel"))
    parser.add_argument("--project-id", default="")
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--book-id", default="")
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--formation-run-id", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--creation-policy-file", type=Path)
    parser.add_argument("--execution-template-file", type=Path, default=Path("config/execution_templates/author_first.json"))
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--maximum-ticks", type=int, default=100)
    parser.add_argument("--work-window-seconds", type=int, default=300)
    parser.add_argument("--yield-after-window", action="store_true")
    parser.add_argument("--foreground", action="store_true", help="drive a bounded local window as well as durable worker ownership")
    parser.add_argument("--creative-selection", choices=("AUTHOR_COMPARISON", "AUTO_COMPARISON", "FIRST_ADMITTED"), default="AUTO_COMPARISON")
    parser.add_argument("--candidate-number", type=int)
    parser.add_argument("--candidate-version", default="")
    parser.add_argument("--candidate-hash", default="")
    parser.add_argument("--reason", default="")
    successor = subparsers.add_parser("authority-opening-resource-successor", help="admit new resource semantics for unexecuted Opening work")
    successor.add_argument("--project-id", required=True)
    successor.add_argument("--opening-run-id", required=True)
    successor.add_argument("--expected-version", required=True, type=int)
    successor.add_argument("--idempotency-key", required=True)


def run_creation_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.modules.book_authority.creation_runtime import execute_creation_command
    if args.action == "start" and not all((args.project_id, args.workspace_id, args.book_id, args.idempotency_key)):
        from types import SimpleNamespace
        from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
        from novel_forge.modules.story_planning_runtime.domain import canonical_hash
        if not args.input_file:
            raise ValueError("Starting a work requires --input-file")
        principal = build_trusted_principal_resolver().resolve_api_principal()
        identity = canonical_hash({"version": "author-cli-work.v1", "actor_id": principal.principal_id,
            "project_id": args.project_id, "input_location": str(args.input_file.resolve()),
            "work_key": args.idempotency_key}).split(":")[-1]
        args = SimpleNamespace(**vars(args))
        args.project_id = args.project_id or "project:author:" + identity
        args.book_id = args.book_id or "book:author:" + identity
        args.workspace_id = args.workspace_id or "workspace:author:" + identity
        args.idempotency_key = args.idempotency_key or "author-start:" + identity
    if not args.project_id:
        raise ValueError("Continue or recover the exact Project returned when this work was started")
    result = execute_creation_command(settings, args)
    return {**result, "project_id": args.project_id, "book_id": result.get("book_id") or args.book_id}


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
