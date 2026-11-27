from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from novel_forge.cli.runtime_inspection import inspect_runtime
from novel_forge.modules.command_kernel.dispatch_control import change_dispatch_control, dispatch_control_status


def add_runtime_control_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-runtime", help="control project dispatch and inspect/export the persistent deployment")
    parser.add_argument("action", choices=("status", "pause", "resume", "export"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-version", type=int, default=0)
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--output", default="")


def run_runtime_control(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.query", args.project_id)
    # SECURITY: Verify the explicit persistent identity before any control mutation.
    ledger = inspect_runtime(settings.database_url, project_id=args.project_id, expected_database=args.expected_database)
    build_id, commit_sha = authority_release_identity()
    release = {"application_build_id": build_id, "commit_sha": commit_sha}
    if args.action in {"pause", "resume"}:
        control = change_dispatch_control(settings.database_url, project_id=args.project_id, principal=principal,
            state="PAUSED" if args.action == "pause" else "RUNNING", expected_version=args.expected_version,
            idempotency_key=args.idempotency_key, reason=args.reason, release_identity=release)
    else:
        control = dispatch_control_status(settings.database_url, project_id=args.project_id)
    result = {"schema_version": "runtime-operator-export.v1", "release_identity": release,
              "control": control, "ledger": ledger, "provider_dispatches": 0}
    if args.action == "export":
        if not args.output:
            raise ValueError("export requires an explicit --output file")
        output = Path(args.output).expanduser().resolve()
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
        result["export_path"] = str(output)
    return result
