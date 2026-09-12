from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def add_creative_budget_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-creative-budget", help="configure/query cumulative Source, creation and repair allocations")
    parser.add_argument("action", choices=("configure", "query"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--authorization-evidence-file", type=Path)
    parser.add_argument("--idempotency-key", default="")


def run_creative_budget_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    from novel_forge.modules.command_kernel.creative_budget_runtime import configure_creative_budget, get_creative_budget
    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.query" if args.action == "query" else "book.authority.execute", args.project_id)
    if args.action == "query":
        return get_creative_budget(settings.database_url, args.project_id)
    if not all((args.policy_file, args.authorization_evidence_file, args.workspace_id, args.idempotency_key)):
        raise ValueError("configure requires an explicit policy, authorization evidence, workspace and stable idempotency key")
    policy = json.loads(args.policy_file.read_bytes())
    evidence_hash = "sha256:" + hashlib.sha256(args.authorization_evidence_file.read_bytes()).hexdigest()
    authorization = policy.get("authorization") or {}
    if authorization.get("evidence_hash") != evidence_hash:
        raise ValueError("authorization evidence bytes do not match the policy grant")
    if authorization.get("authorization_ref") != os.environ.get("NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF"):
        raise ValueError("the configured account route must refer to this exact operator authorization")
    build_id, sha = authority_release_identity()
    return configure_creative_budget(database_url=settings.database_url, policy=policy,
        project_id=args.project_id, workspace_id=args.workspace_id, principal=principal,
        application_build_id=build_id, commit_sha=sha, idempotency_key=args.idempotency_key,
        trace_id=f"trace:{uuid4()}", correlation_id=f"correlation:{uuid4()}")
