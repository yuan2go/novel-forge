from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from novel_forge.infrastructure.settings import IndustrialSettings


def main(argv: list[str] | None = None) -> int:
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql":
        print(
            "error: Authority CLI requires PostgreSQL storage authority",
            file=sys.stderr,
        )
        return 1
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
    trace = subparsers.add_parser("authority-knowledge-trace", help="trace one exact knowledge version through plans, requests and accepted prose")
    trace.add_argument("--project-id", required=True)
    trace.add_argument("--knowledge-card-asset-version-id", required=True)
    trace.add_argument("--book-id", default="")
    trace.add_argument("--limit", type=int, default=50)
    pack = subparsers.add_parser(
        "authority-capability-pack",
        help="manage PostgreSQL Capability Pack Authority lifecycle",
    )
    pack.add_argument(
        "action",
        choices=(
            "register", "validate", "compile", "approve", "deploy",
            "activate", "disable", "rollout-start", "rollout-pause",
            "rollout-resume", "rollout-complete", "rollback", "deprecate",
            "retire", "revoke", "list", "detail", "deployments",
            "deployment-detail", "rollout-detail", "drift", "usage",
        ),
    )
    pack.add_argument("--project-id", required=True)
    pack.add_argument("--workspace-id", default="")
    pack.add_argument("--pack-id", default="")
    pack.add_argument("--pack-version", default="")
    pack.add_argument("--compilation-id", default="")
    pack.add_argument("--deployment-id", default="")
    pack.add_argument("--rollout-id", default="")
    pack.add_argument("--expected-activation-version", type=int, default=0)
    pack.add_argument("--payload-file", default="")
    pack.add_argument("--idempotency-key", default="")
    pack.add_argument("--trace-id", default="")
    pack.add_argument("--correlation-id", default="")
    pack.add_argument("--environment", default="")
    pack.add_argument("--limit", type=int, default=100)
    from novel_forge.cli.craft import add_craft_parser
    add_craft_parser(subparsers)
    from novel_forge.cli.corpus import add_corpus_parser
    add_corpus_parser(subparsers)
    from novel_forge.cli.creative_budget import add_creative_budget_parser
    add_creative_budget_parser(subparsers)
    from novel_forge.cli.provider_routing import add_provider_routing_parser
    add_provider_routing_parser(subparsers)
    return parser


def _authority_main(argv: list[str] | None, settings: IndustrialSettings) -> int:
    parser = _authority_parser()
    args = parser.parse_args(argv)
    try:
        if not settings.database_url:
            raise RuntimeError("PostgreSQL database is required for authority CLI")
        if args.command == "authority-craft":
            from novel_forge.cli.craft import run_craft_command
            print(json.dumps(run_craft_command(settings, args), ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "authority-provider-routing":
            from novel_forge.cli.provider_routing import run_provider_routing_command

            print(json.dumps(run_provider_routing_command(settings, args), ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "authority-creative-budget":
            from novel_forge.cli.creative_budget import run_creative_budget_command
            print(json.dumps(run_creative_budget_command(settings, args), ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "corpus":
            from novel_forge.cli.corpus import run_corpus_command, format_corpus_report
            result = run_corpus_command(settings, args)
            print(format_corpus_report(result) if args.format == "text" else json.dumps(result, ensure_ascii=False, indent=2, default=str))
            if args.action == "run":
                return 0 if result["stop_reason"] == "COMPLETED" else 3 if result["stop_reason"] in {"PARTIAL", "BLOCKED", "FAILED", "CANCELLED"} else 2
            return 0
        if args.command == "serve-api":
            _serve_authority_api(settings, args.host, args.port, args.reload)
            return 0
        if args.command == "authority-knowledge-trace":
            from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
            from novel_forge.modules.mkaos_authority.trace import require_knowledge_trace
            principal = build_trusted_principal_resolver().resolve_api_principal()
            principal.require("mkaos.authority.query", args.project_id)
            result = require_knowledge_trace(
                settings.database_url, project_id=args.project_id,
                knowledge_card_asset_version_id=args.knowledge_card_asset_version_id,
                book_id=args.book_id, limit=args.limit,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
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
        if args.command == "authority-capability-pack":
            result = _run_capability_pack_command(settings, args)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return 0
        if args.command == "authority-chapter-run":
            from novel_forge.api.authority_dependencies import (
                authority_release_identity,
                build_chapter_authority_application,
                build_production_execution_composition,
            )
            from novel_forge.modules.chapter_authority.orchestrator import SingleChapterRequest

            production_execution = build_production_execution_composition(settings)
            application = build_chapter_authority_application(
                settings, execution=production_execution
            )
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
            production_execution.close()
            print(json.dumps(detail, ensure_ascii=False, indent=2))
            return 0
        from novel_forge.api.authority_dependencies import build_chapter_authority_query

        query = build_chapter_authority_query(settings)
        if args.command == "authority-chapter-runs":
            result = query.list_runs(project_id=args.project_id, limit=args.limit)
        elif args.command == "authority-chapter-detail":
            result = query.require_run(
                project_id=args.project_id,
                root_operation_id=args.root_operation_id,
            )
        else:
            raise RuntimeError(f"unsupported authority command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run_capability_pack_command(
    settings: IndustrialSettings, args: argparse.Namespace
) -> Any:
    from novel_forge.api.authority_dependencies import (
        build_capability_pack_authority_application,
        build_capability_pack_authority_query,
        build_trusted_principal_resolver,
    )
    from novel_forge.modules.capability_pack_authority.application import (
        CapabilityPackAuthorityCommand,
    )

    principal = build_trusted_principal_resolver().resolve_api_principal()
    query = build_capability_pack_authority_query(settings)
    if args.action == "list":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.list_versions(project_id=args.project_id, pack_id=args.pack_id)
    if args.action == "detail":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.version_detail(
            project_id=args.project_id,
            pack_id=args.pack_id,
            pack_version=args.pack_version,
        )
    if args.action == "deployments":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.list_deployments(
            pack_id=args.pack_id,
            project_id=args.project_id,
            environment=args.environment,
            limit=args.limit,
        )
    if args.action == "deployment-detail":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.deployment_detail(
            args.deployment_id, project_id=args.project_id
        )
    if args.action == "rollout-detail":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.rollout_detail(args.rollout_id, project_id=args.project_id)
    if args.action == "drift":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.drift_report(args.deployment_id, project_id=args.project_id)
    if args.action == "usage":
        principal.require("capability_pack.authority.query", args.project_id)
        return query.usage_metrics(args.deployment_id, project_id=args.project_id)

    actions = {
        "register": "capability_pack.manifest.register",
        "validate": "capability_pack.manifest.validate",
        "compile": "capability_pack.compile",
        "approve": "capability_pack.approval.decide",
        "deploy": "capability_pack.deployment.create",
        "activate": "capability_pack.deployment.activate",
        "disable": "capability_pack.deployment.disable",
        "rollout-start": "capability_pack.rollout.start",
        "rollout-pause": "capability_pack.rollout.pause",
        "rollout-resume": "capability_pack.rollout.resume",
        "rollout-complete": "capability_pack.rollout.complete",
        "rollback": "capability_pack.rollback",
        "deprecate": "capability_pack.deprecate",
        "retire": "capability_pack.retire",
        "revoke": "capability_pack.revoke",
    }
    payload: dict[str, Any] = {}
    if args.payload_file:
        loaded = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Capability Pack payload file must contain a JSON object")
        payload = loaded
    return build_capability_pack_authority_application(settings).execute(
        CapabilityPackAuthorityCommand(
            definition_name=actions[args.action],
            project_id=args.project_id,
            workspace_id=args.workspace_id,
            actor_id=principal.principal_id,
            pack_id=args.pack_id,
            pack_version=args.pack_version,
            compilation_id=args.compilation_id,
            deployment_id=args.deployment_id,
            rollout_id=args.rollout_id,
            expected_activation_version=args.expected_activation_version,
            idempotency_key=(
                args.idempotency_key
                or f"capability-pack:{args.action}:{uuid4()}"
            ),
            trace_id=args.trace_id or f"trace:capability-pack:{uuid4()}",
            correlation_id=(
                args.correlation_id or f"correlation:capability-pack:{uuid4()}"
            ),
            payload=payload,
        ),
        principal=principal,
    )


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
    from novel_forge.api.authority_app import create_authority_app

    uvicorn.run(
        "novel_forge.api.authority_app:create_authority_app_from_env" if reload
        else create_authority_app(settings),
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        factory=reload,
    )


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
