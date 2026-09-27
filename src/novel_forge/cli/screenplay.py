from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from novel_forge.modules.book_followup_authority.screenplay_application import ScreenplayApplication


def add_screenplay_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-screenplay", help="prepare, generate, review, revise, accept and export exact-edition scene screenplays")
    parser.add_argument("action", choices=("prepare", "generate", "review", "revise", "accept", "update", "run", "status", "export"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--book-run-id", default="")
    parser.add_argument("--payload-file", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--source-asset-version-id", default="")
    parser.add_argument("--candidate-asset-version-id", default="")
    parser.add_argument("--review-asset-version-id", default="")
    parser.add_argument("--asset-version-id", default="")
    parser.add_argument("--operation-id", default="")
    parser.add_argument("--output", default="")


def run_screenplay_command(settings, args):
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver, build_production_execution_composition, build_book_followup_authority_application
    principal = build_trusted_principal_resolver().resolve_api_principal()
    build, sha = authority_release_identity()
    execution = None
    if args.action in {"generate", "review", "revise", "run"}:
        execution = build_production_execution_composition(settings)
        followup = build_book_followup_authority_application(settings, execution=execution)
    else:
        followup = None
    application = ScreenplayApplication(settings.database_url, application_build_id=build, commit_sha=sha, followup=followup)
    try:
        if args.action in {"prepare", "accept", "update"}:
            if not args.payload_file:
                raise ValueError("The command requires an exact --payload-file")
            return application.command(action=args.action, project_id=args.project_id, workspace_id=args.workspace_id,
                book_run_id=args.book_run_id, data=json.loads(Path(args.payload_file).read_text()),
                idempotency_key=args.idempotency_key, principal=principal)
        if args.action in {"generate", "review", "revise"}:
            return application.admit(stage={"generate": "screenplay_generate", "review": "screenplay_review", "revise": "screenplay_revision"}[args.action],
                project_id=args.project_id, workspace_id=args.workspace_id, source_asset_version_id=args.source_asset_version_id,
                candidate_asset_version_id=args.candidate_asset_version_id, review_asset_version_id=args.review_asset_version_id,
                idempotency_key=args.idempotency_key, principal=principal)
        if args.action == "run":
            return application.run(project_id=args.project_id, operation_id=args.operation_id, principal=principal)
        result = application.query(project_id=args.project_id, principal=principal, operation_id=args.operation_id, asset_version_id=args.asset_version_id)
        if args.action == "export":
            if not args.output or "text" not in result:
                raise ValueError("Export requires a candidate or accepted screenplay and an explicit --output")
            fd = os.open(Path(args.output).expanduser().resolve(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(result["text"])
            result["export_path"] = str(Path(args.output).expanduser().resolve())
        return result
    finally:
        if execution is not None:
            execution.close()
