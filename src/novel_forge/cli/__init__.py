"""CLI selector for PostgreSQL authority and isolated legacy development tools."""
from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4

from novel_forge.infrastructure.settings import IndustrialSettings


def main(argv: list[str] | None = None) -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql":
        if settings.environment == "production":
            print("error: production CLI requires PostgreSQL authority", file=sys.stderr)
            return 1
        from novel_forge.cli.legacy import main as legacy_main

        return legacy_main(argv)
    return _authority_main(argv, settings)


def _authority_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-forge",
        description="Novel Forge PostgreSQL Authority CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve-api", help="serve the authority-only API")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")

    migrate = subparsers.add_parser("authority-migrate", help="apply authority migrations")
    migrate.add_argument("--status", action="store_true")

    run = subparsers.add_parser("authority-chapter-run", help="run one authoritative chapter")
    run.add_argument("--project-id", required=True)
    run.add_argument("--workspace-id", required=True)
    run.add_argument("--actor-id", required=True)
    run.add_argument("--chapter", required=True, type=int)
    run.add_argument("--title", required=True)
    run.add_argument("--premise", required=True)
    run.add_argument("--trace-id", default="")
    run.add_argument("--correlation-id", default="")

    listing = subparsers.add_parser("authority-chapter-runs", help="list authoritative chapter runs")
    listing.add_argument("--project-id", required=True)
    listing.add_argument("--limit", type=int, default=100)

    detail = subparsers.add_parser("authority-chapter-detail", help="query one authoritative chapter run")
    detail.add_argument("--project-id", required=True)
    detail.add_argument("--root-operation-id", required=True)
    return parser


def _authority_main(argv: list[str] | None, settings: IndustrialSettings) -> int:
    parser = _authority_parser()
    args = parser.parse_args(argv)
    try:
        if not settings.database_url:
            raise RuntimeError("PostgreSQL database is required for authority CLI")
        if args.command == "serve-api":
            _serve_authority_api(settings, args.host, args.port, args.reload)
            return 0
        if args.command == "authority-migrate":
            from novel_forge.storage.migrations import get_migration_status, run_migrations

            result = (
                get_migration_status(settings.database_url)
                if args.status
                else run_migrations(settings.database_url)
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "authority-chapter-run":
            from novel_forge.api.authority_dependencies import (
                authority_release_identity,
                build_chapter_authority_application,
            )
            from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest

            application = build_chapter_authority_application(settings)
            build_id, commit_sha = authority_release_identity()
            result = application.run(
                SingleChapterRequest(
                    project_id=args.project_id,
                    workspace_id=args.workspace_id,
                    actor_id=args.actor_id,
                    chapter=args.chapter,
                    title=args.title,
                    premise=args.premise,
                    trace_id=args.trace_id or f"trace:{uuid4()}",
                    correlation_id=args.correlation_id or f"correlation:{uuid4()}",
                    application_build_id=build_id,
                    commit_sha=commit_sha,
                )
            )
            detail = application.query.require_run(
                project_id=args.project_id,
                root_operation_id=result.root_operation_id,
            )
            print(json.dumps(detail, ensure_ascii=False, indent=2))
            return 0
        from novel_forge.api.authority_dependencies import build_chapter_authority_query

        query = build_chapter_authority_query(settings)
        if args.command == "authority-chapter-runs":
            result = query.list_runs(project_id=args.project_id, limit=args.limit)
        else:
            result = query.require_run(
                project_id=args.project_id,
                root_operation_id=args.root_operation_id,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _serve_authority_api(
    settings: IndustrialSettings,
    host: str | None,
    port: int | None,
    reload: bool,
) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency boundary
        raise RuntimeError(
            "Authority API serving requires fastapi and uvicorn[standard]"
        ) from exc
    from novel_forge.api.app import create_app

    uvicorn.run(
        "novel_forge.api.app:app" if reload else create_app(settings),
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )


__all__ = ["main"]
