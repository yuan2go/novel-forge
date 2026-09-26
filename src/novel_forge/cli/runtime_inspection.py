from __future__ import annotations

from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.migrations import LATEST_MIGRATION_ID


def add_runtime_inspection_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-runtime-inspect", help="inspect persistent identity and scoped ledgers without dispatch or reconciliation")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--expected-database", required=True)


def inspect_runtime(database_url: str, *, project_id: str, expected_database: str) -> dict[str, Any]:
    with AuthorityUnitOfWork(database_url) as uow:
        cur = uow.cursor
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute("SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port(), pg_postmaster_start_time(), oid FROM pg_database WHERE datname=current_database()")
        row = cur.fetchone()
        identity = dict(zip(("database", "role", "address", "port", "server_started_at", "database_oid"), row, strict=True))
        if row[0] != expected_database:
            raise KernelError("RUNTIME_DATABASE_IDENTITY_MISMATCH", "Connected database differs from the explicit expected identity")
        cur.execute("SELECT 1 FROM authority_project WHERE project_id=%s", [project_id])
        if cur.fetchone() is None:
            raise KernelError("RUNTIME_PROJECT_NOT_FOUND", "Project is absent from this ledger; inspection cannot bootstrap a replacement")
        cur.execute("SELECT migration_id FROM nf_schema_migrations ORDER BY migration_id")
        applied = [value[0] for value in cur.fetchall()]
        cur.execute("SELECT book_id FROM authority_book WHERE project_id=%s ORDER BY book_id", [project_id])
        books = [value[0] for value in cur.fetchall()]
        cur.execute("SELECT status,count(*) FROM authority_external_effect WHERE project_id=%s GROUP BY status ORDER BY status", [project_id])
        effects = dict(cur.fetchall())
        cur.execute("SELECT external_effect_id,status,effect_type,provider,model_id,manual_resolution_required FROM authority_external_effect WHERE project_id=%s AND status NOT IN ('SUCCEEDED','CANCELLED') ORDER BY external_effect_id LIMIT 101", [project_id])
        unresolved = [dict(zip(("external_effect_id", "status", "effect_type", "provider", "model_id", "manual_resolution_required"), row, strict=True)) for row in cur.fetchall()]
        cur.execute("SELECT status,accounting_basis,settled_cost_status,count(*),sum(actual_tokens),sum(reserved_amount),sum(settled_amount) FROM authority_budget_reservation WHERE project_id=%s GROUP BY 1,2,3 ORDER BY 1,2,3", [project_id])
        budgets = [dict(zip(("status", "accounting_basis", "cost_status", "count", "actual_tokens", "reserved_amount", "settled_amount"), row, strict=True)) for row in cur.fetchall()]
        cur.execute("SELECT budget_scope_id,owner_kind,owner_id,deadline_at,deadline_at<=NOW(),policy_snapshot->>'authorization_ref',policy_snapshot->>'provider_call_limit',policy_snapshot->>'token_limit' FROM authority_provider_budget_scope WHERE project_id=%s ORDER BY budget_scope_id", [project_id])
        scopes = [dict(zip(("budget_scope_id", "owner_kind", "owner_id", "deadline_at", "expired", "authorization_ref", "provider_call_limit", "token_limit"), row, strict=True)) for row in cur.fetchall()]
        cur.execute("SELECT book_id,state,accepted_through_chapter FROM authority_book_production WHERE project_id=%s ORDER BY book_run_id", [project_id])
        production = [dict(zip(("book_id", "state", "accepted_through_chapter"), row, strict=True)) for row in cur.fetchall()]
    return {"schema_version": "runtime-ledger-inspection.v1", "database_identity": identity, "project_id": project_id,
            "migration_head_expected": LATEST_MIGRATION_ID, "migration_head_present": LATEST_MIGRATION_ID in applied,
            "applied_migration_count": len(applied), "books": books, "book_production": production,
            "effect_counts": effects, "unresolved_effects": unresolved[:100], "unresolved_list_truncated": len(unresolved) > 100,
            "budget_reservations": budgets, "budget_scopes": scopes,
            "production_authorization": "NOT_ESTABLISHED_BY_INSPECTION", "provider_dispatches": 0,
            "recovery": "Use the existing owner-specific recovery and Effect reconciliation commands; inspection never resends or releases reservations."}


def run_runtime_inspection(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.query", args.project_id)
    return inspect_runtime(settings.database_url, project_id=args.project_id, expected_database=args.expected_database)
