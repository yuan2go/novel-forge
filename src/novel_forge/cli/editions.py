from __future__ import annotations

import json
import os
from pathlib import Path

from novel_forge.modules.book_authority.edition_application import BookEditionApplication, EDITION_ACTIONS


def add_edition_parser(subparsers):
    parser = subparsers.add_parser("authority-edition", help="edit, validate, select and export exact Book manuscript editions")
    parser.add_argument("action", choices=sorted(EDITION_ACTIONS | {"query", "export", "start-validation"}))
    for field in ("project-id", "workspace-id", "book-run-id"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--revision-id", default="")
    parser.add_argument("--input-snapshot-id", default="")
    parser.add_argument("--payload-file", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--export-kind", choices=("FORMAL", "CANDIDATE"), default="FORMAL")


def run_edition_command(settings, args):
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    build_id, sha = authority_release_identity()
    principal = build_trusted_principal_resolver().resolve_api_principal()
    application = BookEditionApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
    scope = {key: getattr(args, key) for key in ("project_id", "workspace_id", "book_run_id")}
    if args.action == "start-validation":
        from novel_forge.api.authority_dependencies import (
            build_production_execution_composition, build_chapter_authority_application, build_book_authority_application,
        )
        if not args.revision_id:
            raise ValueError("Validation requires --revision-id")
        execution = build_production_execution_composition(settings)
        try:
            chapter = build_chapter_authority_application(settings, execution=execution)
            authority = build_book_authority_application(settings, execution=execution, chapter_application=chapter)
            return application.start_validation(authority=authority, **scope, revision_id=args.revision_id,
                input_snapshot_id=args.input_snapshot_id, principal=principal)
        finally:
            execution.close()
    if args.action in {"query", "export"}:
        if args.action == "query":
            return application.query(**scope, revision_id=args.revision_id, principal=principal)
        if not args.revision_id or not args.output:
            raise ValueError("Export requires --revision-id and a new --output path")
        result = application.export_manuscript(**scope, revision_id=args.revision_id, principal=principal,
                                             export_kind=getattr(args, "export_kind", "FORMAL"))
        manifest = result["revision"]["manifest"]
        text = ("\n\n".join(unit["title"] + "\n" + unit["text"] for unit in manifest["units"]) if args.format == "text"
                else json.dumps(result, ensure_ascii=False, indent=2, default=str))
        path = Path(args.output).expanduser().resolve()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        return {**result["export"], "output": str(path)}
    if not args.payload_file or not args.idempotency_key:
        raise ValueError("Edition mutations require --payload-file and --idempotency-key")
    data = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    return application.execute(**scope, action=args.action, data=data, idempotency_key=args.idempotency_key, principal=principal)
