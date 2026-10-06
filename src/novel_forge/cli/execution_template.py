from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def add_execution_template_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-execution-template", help="bind a configured execution template to new Book work")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--template-file", type=Path, default=Path("config/execution_templates/creative_validation.json"))


def run_execution_template_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    from novel_forge.modules.authority_handler_runtime.policy_commands import configure_owned_policy
    from novel_forge.modules.production_execution.codex_model_catalog import parse_codex_model_catalog
    from novel_forge.modules.production_execution.execution_template import validate_templates
    from novel_forge.modules.production_execution.membership_identity import observe_membership_identity
    from novel_forge.modules.production_execution.routing_runtime import PostgresRoutingRegistry
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.execute", args.project_id)
    if os.environ.get("NOVEL_FORGE_RESOURCE_CONTROL_VERSION") != "billing-channel-resources.v1":
        raise ValueError("BILLING_CHANNEL_RESOURCE_CONFIGURATION_REQUIRED")
    identity = observe_membership_identity(os.environ.get("NOVEL_FORGE_CODEX_HOME", ""))
    if identity["account_ref"] != os.environ.get("NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF"):
        raise ValueError("CODEX_MEMBERSHIP_IDENTITY_DRIFT")
    authorization = os.environ.get("NOVEL_FORGE_CODEX_ACCOUNT_AUTHORIZATION_REF", "").strip()
    if not authorization:
        raise ValueError("CODEX_MEMBERSHIP_AUTHORIZATION_REQUIRED")
    models = parse_codex_model_catalog(os.environ.get("NOVEL_FORGE_CODEX_ROUTER_MODELS", ""))
    value = json.loads(args.template_file.read_text())
    value.update(book_id=args.book_id, member_authorization_ref=authorization,
        allowed_candidates=[f"codex-cli:{model['model']}:{model['reasoning']}" for model in models if model["role"] in {"PRIMARY", "REFERENCE"}])
    from novel_forge.modules.production_execution.execution_template import load_paid_configuration
    if value.get("deepseek") is not None:
        raise ValueError("PAID_TEMPLATE_MUST_INHERIT_CONFIGURED_AUTHORIZATION")
    paid, paid_unavailable = load_paid_configuration(os.environ)
    if paid is not None:
        value["deepseek"] = paid
        from novel_forge.modules.production_execution.routing_catalog import deepseek_candidates
        value["allowed_candidates"].extend(model.candidate_id for model in deepseek_candidates(available=True))
    validate_templates({"execution_templates": [value]})
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book WHERE project_id=%s AND book_id=%s", [args.project_id, args.book_id])
        if uow.cursor.fetchone() != (args.workspace_id,):
            raise ValueError("EXECUTION_TEMPLATE_BOOK_SCOPE_INVALID")
    prior = PostgresRoutingRegistry(settings.database_url).policy(args.project_id)
    content = dict(prior.get("policy") or {"task_overrides": [], "reason": "configured template for internal creative validation"})
    content.update(policy_version=args.policy_version, reason="native creation template; paid channel: " + (paid_unavailable or "AUTHORIZED_CONFIGURATION"), execution_templates=[
        item for item in content.get("execution_templates", []) if item["book_id"] != args.book_id] + [value])
    build_id, sha = authority_release_identity()
    return configure_owned_policy(database_url=settings.database_url, owner="PROVIDER_ROUTING", content=content,
        project_id=args.project_id, workspace_id=args.workspace_id, idempotency_key=args.idempotency_key,
        trace_id="trace:" + args.idempotency_key, correlation_id=args.book_id,
        application_build_id=build_id, commit_sha=sha, principal=principal)
