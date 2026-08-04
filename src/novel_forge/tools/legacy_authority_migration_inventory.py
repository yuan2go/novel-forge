"""Generate the executable Legacy-to-PostgreSQL Authority migration inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_forge.tools.authority_coverage_manifest import build_manifest
from novel_forge.tools.authority_reachability import (
    build_authority_import_graph,
    production_paths,
    render_paths,
)


SCHEMA_VERSION = "legacy-authority-migration-inventory.v3"

INVENTORY_STATUSES = frozenset(
    {
        "MIGRATED_NATIVE",
        "MIGRATED_READ_ONLY",
        "IMPORT_CANDIDATE_ONLY",
        "REBUILDABLE",
        "DEVELOPMENT_ONLY",
        "TEST_FIXTURE_ONLY",
        "EXPLICIT_COMPATIBILITY",
        "LEGACY_PRODUCTION_BLOCKER",
        "UNCLASSIFIED",
    }
)

# These are the only source files which may be entered by the default
# PostgreSQL backend process plane.  A Legacy finding in one of them is a
# blocker unless the exact file is an explicit selector/import boundary below.
PRODUCTION_AUTHORITY_FILES = frozenset(
    {
        "src/novel_forge/api/authority_app.py",
        "src/novel_forge/api/authority_dependencies.py",
        "src/novel_forge/workers/chapter_authority.py",
        "src/novel_forge/workers/content_authority.py",
        "src/novel_forge/workers/source_authority.py",
        "src/novel_forge/workers/mkaos_authority.py",
        "src/novel_forge/workers/runtime_groups.py",
    }
)

EXPLICIT_IMPORT_FILES = frozenset(
    {
        "src/novel_forge/modules/legacy_migration/application.py",
        "src/novel_forge/modules/legacy_migration/codecs.py",
        "src/novel_forge/modules/legacy_migration/definitions.py",
        "src/novel_forge/modules/legacy_migration/scanner.py",
        "src/novel_forge/modules/legacy_migration/service.py",
        "src/novel_forge/storage/legacy_object_sync.py",
        "src/novel_forge/storage/postgres.py",
    }
)

EXPLICIT_SELECTOR_FILES = frozenset(
    {
        "src/novel_forge/api/app.py",
        "src/novel_forge/api/legacy_app.py",
        "src/novel_forge/cli/legacy.py",
        "src/novel_forge/workers/celery_app.py",
        "src/novel_forge/workers/legacy_tasks.py",
        "src/novel_forge/workers/runtime.py",
        "src/novel_forge/workers/tasks.py",
    }
)


def build_inventory(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    coverage = build_manifest(root)
    import_graph = build_authority_import_graph(root)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for finding in coverage["findings"]:
        if not _is_legacy_finding(finding):
            continue
        domain = _business_domain(finding)
        operation = str(finding.get("target_operation_definition") or "")
        groups[(domain, str(finding["path"]), operation)].append(finding)

    rows = []
    for (domain, path, operation), findings in sorted(groups.items()):
        writes = sorted(
            {
                _point(item)
                for item in findings
                if item.get("side_effect")
                or item.get("usage_type")
                in {"authority_write", "dual_write", "fallback", "sync", "external_effect"}
            }
        )
        reads = sorted({_point(item) for item in findings if _point(item) not in writes})
        authorities = sorted(
            {str(item.get("current_authority") or "unknown") for item in findings}
        )
        usage = {str(item.get("usage_type") or "unknown") for item in findings}
        repository = _first(findings, "target_repository")
        aggregate = _first(findings, "target_aggregate") or _aggregate_for_domain(domain)
        entrypoints = sorted(
            {
                f"{item.get('entrypoint_kind', 'internal')}:{item.get('qualified_symbol', '')}"
                for item in findings
            }
        )
        all_paths = import_graph.paths_by_file.get(path, ())
        live_paths = production_paths(all_paths)
        classification = _classification(
            path, findings, usage, production_reachable=bool(live_paths)
        )
        symbols = sorted(
            {
                str(item.get("qualified_symbol") or item.get("symbol") or "<module>")
                for item in findings
            }
        )
        read_or_write = _read_or_write(reads=reads, writes=writes)
        target_asset_type = _asset_type(domain, aggregate)
        target_operation = operation or f"{aggregate}.migration.required"
        target_repository = repository or f"novel_forge.storage.{aggregate}_repository"
        rows.append(
            {
                "inventory_id": _stable_id(domain, path, operation or aggregate),
                "domain": domain,
                "file": path,
                "symbol": symbols,
                "entrypoint": entrypoints,
                "read_or_write": read_or_write,
                "current_authority": authorities,
                "target_authority": {
                    "kind": "postgresql",
                    "asset_type": target_asset_type,
                    "operation_definition": target_operation,
                    "repository": target_repository,
                },
                "production_reachable": classification[1],
                "allowed_runtime": _allowed_runtime(path, classification[0]),
                "reason": classification[2],
                "owner": _owner_for_domain(domain),
                "removal_condition": (
                    "PostgreSQL domain replacement is proven and the transitive "
                    "Authority entry graph no longer reaches this symbol"
                ),
                "transitive_paths": render_paths(all_paths),
                "production_transitive_paths": render_paths(live_paths),
                "migration_strategy": _migration_method(usage, path),
                "status": classification[0],
                "remaining_action": classification[2],
                "business_domain": domain,
                "current_entrypoints": entrypoints,
                "current_authority_source": authorities,
                "current_write_points": writes,
                "current_read_points": reads,
                "target_authority_asset_type": target_asset_type,
                "target_operation_definition": target_operation,
                "target_repository": target_repository,
                "transaction_boundary": (
                    "Command admission + fenced Attempt output + aggregate transition + "
                    "StateEvent/Audit/Outbox in one PostgreSQL transaction"
                ),
                "idempotency_key": f"project_id:{aggregate}:stable_business_identity:content_hash",
                "recovery_strategy": _recovery_strategy(usage),
                "migration_method": _migration_method(usage, path),
                "deletion_condition": (
                    "PostgreSQL command/query entrypoint is integration-proven; import reconciliation "
                    "passes; architecture guard reports no production reachability"
                ),
                "test_requirements": [
                    "unit: domain invariants/hash/idempotency/project scope",
                    "postgres: transaction rollback/concurrency/replay/stale fence/outbox",
                    "migration: duplicate/corrupt/missing-reference/cross-project/resume/reconcile",
                    "architecture: production LocalStorage/filesystem authority forbidden",
                ],
                "migration_status": classification[0],
                "evidence": [
                    {
                        "path": item["path"],
                        "line": item["line"],
                        "symbol": item.get("qualified_symbol") or item.get("symbol"),
                        "scan_rule": item.get("scan_rule"),
                        "usage_type": item.get("usage_type"),
                    }
                    for item in sorted(
                        findings,
                        key=lambda value: (value["path"], value["line"], value.get("symbol", "")),
                    )
                ],
            }
        )
    rows.extend(_runtime_configuration_findings(root))
    rows.extend(_web_excluded_findings(root))
    for row in rows:
        fallback_path = [f"declared:{row['file']}"]
        row.setdefault(
            "allowed_runtime", _allowed_runtime(row["file"], row["status"])
        )
        row.setdefault("reason", row["remaining_action"])
        row.setdefault("owner", _owner_for_domain(row["business_domain"]))
        row.setdefault("removal_condition", row["deletion_condition"])
        row.setdefault("transitive_paths", [fallback_path])
        row.setdefault(
            "production_transitive_paths",
            [fallback_path] if row["production_reachable"] else [],
        )
    rows.sort(key=lambda item: (item["file"], item["inventory_id"]))
    status_counts = {
        status: sum(1 for item in rows if item["status"] == status)
        for status in sorted(INVENTORY_STATUSES)
    }
    summary = {
        "inventory_rows": len(rows),
        "legacy_findings": sum(len(row["evidence"]) for row in rows),
        "business_domains": sorted({row["business_domain"] for row in rows}),
        "production_localstorage_goal": 0,
        "status_counts": status_counts,
        "legacy_production_blocker_count": status_counts["LEGACY_PRODUCTION_BLOCKER"],
        "unclassified_count": status_counts["UNCLASSIFIED"],
        "web_excluded_count": sum(
            1 for item in rows if str(item["file"]).startswith("web/")
        ),
        "current_coverage_summary": coverage["summary"],
        "reachability": {
            "entrypoint_count": len(import_graph.entrypoints),
            "module_count": len(import_graph.modules),
            "reachable_file_count": len(import_graph.paths_by_file),
            "entrypoints": import_graph.entrypoints,
            "guarded_compatibility_path_count": sum(
                len(paths) - len(production_paths(paths))
                for paths in import_graph.paths_by_file.values()
            ),
        },
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree_sha": coverage["source_tree_sha"],
        "coverage_hash": coverage["coverage_hash"],
        "summary": summary,
        "items": rows,
    }
    payload["artifact_hash"] = _hash(payload)
    return payload


def write_inventory(
    repo_root: str | Path, *, json_output: str | Path, markdown_output: str | Path
) -> dict[str, Any]:
    payload = build_inventory(repo_root)
    json_path = Path(json_output)
    markdown_path = Path(markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    return payload


def _is_legacy_finding(finding: dict[str, Any]) -> bool:
    dependency = str(finding.get("dependency") or "").lower()
    path = str(finding.get("path") or "").lower()
    legacy_fallback = finding.get("usage_type") == "fallback" and any(
        token in dependency or token in path
        for token in ("legacy", "localstorage", "storage.local", "postgres_fallback")
    )
    return (
        finding.get("current_authority") in {"localstorage", "filesystem"}
        or (
            finding.get("current_authority") == "mixed"
            and (finding.get("usage_type") != "fallback" or legacy_fallback)
        )
        or finding.get("usage_type") in {"sync", "dual_write"}
        or legacy_fallback
        or "storage.local" in dependency
    )


def _business_domain(finding: dict[str, Any]) -> str:
    text = " ".join(
        str(finding.get(key) or "")
        for key in ("path", "qualified_symbol", "target_aggregate", "target_operation_definition")
    ).lower()
    mapping = (
        ("project_workspace", ("project", "workspace", "portfolio")),
        ("source_governance", ("source", "ingest", "clean", "decomposition", "analysis")),
        ("mkaos", ("mkaos", "knowledge", "material", "training")),
        ("context_builder", ("context", "retrieval", "long_memory", "rag")),
        ("planning", ("topic", "world", "character", "outline", "plan", "story_design")),
        ("draft_review_revision", ("draft", "review", "revision", "editor", "manuscript")),
        ("publishing", ("publish", "release", "platform_submission")),
        ("feedback_reader", ("feedback", "reader", "retention", "outcome")),
        ("agent_workflow_task", ("agent", "workflow", "task", "runtime", "loop")),
        ("index_object_store", ("qdrant", "vector", "object_store", "minio", "index")),
    )
    for domain, tokens in mapping:
        if any(token in text for token in tokens):
            return domain
    return "cross_cutting_governance"


def _classification(
    path: str,
    findings: list[dict[str, Any]],
    usage: set[str],
    *,
    production_reachable: bool,
) -> tuple[str, bool, str]:
    if path.startswith("tests/"):
        return "TEST_FIXTURE_ONLY", False, "retain as a non-production fixture or test"
    if path.startswith("scripts/"):
        return "DEVELOPMENT_ONLY", False, "retain only as an explicit operator/development command"
    if path.startswith("web/"):
        return (
            "EXPLICIT_COMPATIBILITY",
            False,
            "backend Authority is out of Web implementation scope; the client must not enable Legacy writes",
        )
    if path in EXPLICIT_IMPORT_FILES:
        return (
            "IMPORT_CANDIDATE_ONLY",
            production_reachable,
            "retain only for frozen read-only import/export; never use as runtime read authority",
        )
    if path in EXPLICIT_SELECTOR_FILES:
        return (
            "EXPLICIT_COMPATIBILITY",
            False,
            "keep behind the explicit legacy command/profile and delete after parity",
        )
    if _is_rebuildable_path(path):
        return (
            "REBUILDABLE",
            False,
            "rebuild from PostgreSQL projections/object receipts; never import as authority",
        )
    if production_reachable:
        evidence = ", ".join(
            sorted({str(item.get("scan_rule") or "legacy") for item in findings})
        )
        return (
            "LEGACY_PRODUCTION_BLOCKER",
            True,
            f"remove or replace the production-reachable Legacy dependency ({evidence})",
        )
    if path.startswith("src/novel_forge/"):
        return (
            "EXPLICIT_COMPATIBILITY",
            False,
            "move entry behind the explicit legacy profile or replace with a native Authority operation",
        )
    return "UNCLASSIFIED", False, "classify this evidence before cutover"


def _allowed_runtime(path: str, status: str) -> list[str]:
    if status == "IMPORT_CANDIDATE_ONLY":
        return ["explicit-migration-cli"]
    if status == "TEST_FIXTURE_ONLY":
        return ["test"]
    if status == "DEVELOPMENT_ONLY" or path in EXPLICIT_SELECTOR_FILES:
        return ["development", "explicit-legacy-profile"]
    if status == "REBUILDABLE":
        return ["projection-rebuild"]
    if status == "LEGACY_PRODUCTION_BLOCKER":
        return []
    return ["compatibility-read-only"]


def _owner_for_domain(domain: str) -> str:
    return {
        "project_workspace": "Project Authority",
        "source_governance": "Source Authority",
        "mkaos": "MKAOS Authority",
        "planning": "Planning Authority",
        "agent_workflow_task": "Command Kernel",
    }.get(domain, "Authority Cutover")


def _is_authority_runtime_path(path: str) -> bool:
    prefixes = (
        "src/novel_forge/modules/book_authority/",
        "src/novel_forge/modules/book_design_authority/",
        "src/novel_forge/modules/chapter_authority/",
        "src/novel_forge/modules/command_kernel/",
        "src/novel_forge/modules/content_authority/",
        "src/novel_forge/modules/mkaos_authority/",
        "src/novel_forge/modules/project_authority/",
        "src/novel_forge/modules/source_authority/",
        "src/novel_forge/modules/task_authority/",
    )
    return path.startswith(prefixes)


def _is_rebuildable_path(path: str) -> bool:
    lowered = path.lower()
    return any(
        token in lowered
        for token in (
            "/cache/",
            "/index/",
            "projection_sync",
            "search_index",
            "vector_index",
        )
    )


def _read_or_write(*, reads: list[str], writes: list[str]) -> str:
    if reads and writes:
        return "READ_WRITE"
    if writes:
        return "WRITE"
    return "READ"


def _runtime_configuration_findings(root: Path) -> list[dict[str, Any]]:
    checks = (
        (
            "src/novel_forge/infrastructure/settings.py",
            'storage_authority: str = "legacy_local"',
            "IndustrialSettings.storage_authority",
            "default runtime selects Legacy LocalStorage",
        ),
        (
            "src/novel_forge/infrastructure/settings.py",
            '"postgresql" if environment == "production" else "legacy_local"',
            "IndustrialSettings.from_env",
            "standard development runtime selects Legacy LocalStorage",
        ),
        (
            "src/novel_forge/cli/__init__.py",
            'settings.storage_authority != "postgresql" and not authority_requested',
            "novel_forge.cli.main",
            "standard CLI falls through to the Legacy command surface",
        ),
    )
    findings: list[dict[str, Any]] = []
    for path, marker, symbol, reason in checks:
        candidate = root / path
        if not candidate.exists():
            continue
        source = candidate.read_text(encoding="utf-8")
        if marker not in source:
            continue
        line = source[: source.index(marker)].count("\n") + 1
        evidence = {
            "path": path,
            "line": line,
            "symbol": symbol,
            "scan_rule": "runtime_default",
            "usage_type": "fallback",
            "reason": reason,
        }
        findings.append(
            {
                "inventory_id": _stable_id("runtime_default", path, symbol),
                "domain": "runtime_governance",
                "file": path,
                "symbol": [symbol],
                "entrypoint": [f"runtime:{symbol}"],
                "read_or_write": "READ_WRITE",
                "current_authority": ["legacy_localstorage"],
                "target_authority": {
                    "kind": "postgresql",
                    "asset_type": "runtime_configuration",
                    "operation_definition": "runtime.authority.start",
                    "repository": "novel_forge.storage.database_runtime",
                },
                "production_reachable": True,
                "migration_strategy": "REPLACE_WITH_AUTHORITY",
                "status": "LEGACY_PRODUCTION_BLOCKER",
                "remaining_action": reason,
                "business_domain": "runtime_governance",
                "current_entrypoints": [f"runtime:{symbol}"],
                "current_authority_source": ["legacy_localstorage"],
                "current_write_points": [f"{path}:{line}:{symbol}"],
                "current_read_points": [],
                "target_authority_asset_type": "runtime_configuration",
                "target_operation_definition": "runtime.authority.start",
                "target_repository": "novel_forge.storage.database_runtime",
                "transaction_boundary": "startup validation before accepting work",
                "idempotency_key": "runtime_role:release_sha",
                "recovery_strategy": "fail closed; retry PostgreSQL startup without Legacy fallback",
                "migration_method": "REPLACE_WITH_AUTHORITY",
                "deletion_condition": "default startup is PostgreSQL Authority and architecture gate passes",
                "test_requirements": ["architecture: default runtime and Compose are PostgreSQL-only"],
                "migration_status": "LEGACY_PRODUCTION_BLOCKER",
                "evidence": [evidence],
            }
        )
    compose_path = root / "compose.yml"
    compose_source = (
        compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""
    )
    compose_failures = []
    if not compose_source:
        compose_failures.append("default compose.yml is missing")
    if "NOVEL_FORGE_STORAGE_AUTHORITY: postgresql" not in compose_source:
        compose_failures.append("default Compose does not select PostgreSQL authority")
    if "NOVEL_FORGE_LEGACY_WRITE_ENABLED: \"false\"" not in compose_source:
        compose_failures.append("default Compose does not disable Legacy writes")
    if "NOVEL_FORGE_SILENT_LEGACY_FALLBACK_ENABLED: \"false\"" not in compose_source:
        compose_failures.append("default Compose does not disable Legacy fallback")
    if "  web:\n" in compose_source or "  legacy-api:\n" in compose_source:
        compose_failures.append("default Compose contains a Web or Legacy service")
    for index, reason in enumerate(compose_failures, start=1):
        evidence = {
            "path": "compose.yml",
            "line": index,
            "symbol": "services",
            "scan_rule": "runtime_default",
            "usage_type": "fallback",
            "reason": reason,
        }
        findings.append(
            {
                "inventory_id": _stable_id("runtime_default", "compose.yml", reason),
                "domain": "runtime_governance",
                "file": "compose.yml",
                "symbol": ["services"],
                "entrypoint": ["runtime:compose"],
                "read_or_write": "READ_WRITE",
                "current_authority": ["legacy_localstorage"],
                "target_authority": {
                    "kind": "postgresql",
                    "asset_type": "runtime_configuration",
                    "operation_definition": "runtime.authority.start",
                    "repository": "novel_forge.storage.database_runtime",
                },
                "production_reachable": True,
                "migration_strategy": "REPLACE_WITH_AUTHORITY",
                "status": "LEGACY_PRODUCTION_BLOCKER",
                "remaining_action": reason,
                "business_domain": "runtime_governance",
                "current_entrypoints": ["runtime:compose"],
                "current_authority_source": ["legacy_localstorage"],
                "current_write_points": ["compose.yml:services"],
                "current_read_points": [],
                "target_authority_asset_type": "runtime_configuration",
                "target_operation_definition": "runtime.authority.start",
                "target_repository": "novel_forge.storage.database_runtime",
                "transaction_boundary": "startup validation before accepting work",
                "idempotency_key": "runtime_role:release_sha",
                "recovery_strategy": "fail closed; retry PostgreSQL startup without Legacy fallback",
                "migration_method": "REPLACE_WITH_AUTHORITY",
                "deletion_condition": "default Compose is PostgreSQL Authority-only",
                "test_requirements": ["architecture: default Compose is PostgreSQL-only"],
                "migration_status": "LEGACY_PRODUCTION_BLOCKER",
                "evidence": [evidence],
            }
        )
    return findings


def _web_excluded_findings(root: Path) -> list[dict[str, Any]]:
    """Record Legacy-labelled Web surfaces without treating them as backend authority.

    Web implementation is intentionally excluded from this convergence. Keeping each
    textual LocalStorage reference in the inventory prevents the exclusion from being
    mistaken for an Authority proof or from silently re-entering the backend runtime.
    """

    web_root = root / "web"
    if not web_root.exists():
        return []
    findings: list[dict[str, Any]] = []
    for candidate in sorted(web_root.rglob("*")):
        if {"node_modules", ".next", "coverage"} & set(candidate.parts):
            continue
        if not candidate.is_file() or candidate.suffix not in {
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
        }:
            continue
        relative = candidate.relative_to(root).as_posix()
        lines = candidate.read_text(encoding="utf-8").splitlines()
        evidence = [
            {
                "path": relative,
                "line": line_number,
                "symbol": "web_localstorage_reference",
                "scan_rule": "web_scope_exclusion",
                "usage_type": "read_only_label",
            }
            for line_number, line in enumerate(lines, start=1)
            if "localstorage" in line.lower()
        ]
        if not evidence:
            continue
        findings.append(
            {
                "inventory_id": _stable_id("web_excluded", relative, "localstorage"),
                "domain": "web_excluded",
                "file": relative,
                "symbol": ["web_localstorage_reference"],
                "entrypoint": ["web:excluded_from_backend_authority_acceptance"],
                "read_or_write": "READ",
                "current_authority": ["web_client_legacy_label"],
                "target_authority": {
                    "kind": "postgresql_projection_api",
                    "asset_type": "authority_projection",
                    "operation_definition": "web.authority.integration.pending",
                    "repository": "authority-api",
                },
                "production_reachable": False,
                "migration_strategy": "MAKE_READ_ONLY",
                "status": "EXPLICIT_COMPATIBILITY",
                "remaining_action": (
                    "Web is outside this backend acceptance; before production use, replace "
                    "or verify the surface against Authority API projections and keep Legacy "
                    "writes disabled"
                ),
                "business_domain": "web_excluded",
                "current_entrypoints": ["web:excluded_from_backend_authority_acceptance"],
                "current_authority_source": ["web_client_legacy_label"],
                "current_write_points": [],
                "current_read_points": [
                    f"{item['path']}:{item['line']}:{item['symbol']}" for item in evidence
                ],
                "target_authority_asset_type": "authority_projection",
                "target_operation_definition": "web.authority.integration.pending",
                "target_repository": "authority-api",
                "transaction_boundary": "none; Web excluded from backend runtime",
                "idempotency_key": "not_applicable_web_excluded",
                "recovery_strategy": "do not start Web in default Compose; fail closed on Legacy write",
                "migration_method": "MAKE_READ_ONLY",
                "deletion_condition": "Web integration has its own Authority API acceptance proof",
                "test_requirements": [
                    "architecture: default Compose contains no Web service",
                    "future Web acceptance: no Legacy write and Authority API projection only",
                ],
                "migration_status": "EXPLICIT_COMPATIBILITY",
                "evidence": evidence,
            }
        )
    return findings


def _aggregate_for_domain(domain: str) -> str:
    return {
        "project_workspace": "project_lifecycle",
        "source_governance": "source_governance",
        "mkaos": "knowledge",
        "context_builder": "context",
        "planning": "planning",
        "draft_review_revision": "content",
        "publishing": "publishing",
        "feedback_reader": "feedback",
        "agent_workflow_task": "agent",
        "index_object_store": "projection",
    }.get(domain, "policy")


def _asset_type(domain: str, aggregate: str) -> str:
    return {
        "project_workspace": "project_record/workspace_record/project_binding",
        "source_governance": "source_document/source_chunk/source_governance_decision",
        "mkaos": "knowledge_card/rule_card/template_card/knowledge_pack",
        "context_builder": "context_build_plan/context_bundle/context_evidence",
        "planning": "versioned_story_design/versioned_plan",
        "draft_review_revision": "draft/review_report/revision_plan/revised_draft",
        "publishing": "publish_gate/release_package/publishing_receipt",
        "feedback_reader": "feedback_import/reader_exposure/reader_outcome",
        "agent_workflow_task": "handoff/work_order/operation_projection",
        "index_object_store": "object_reference/index_rebuild_receipt",
    }.get(domain, f"{aggregate}_asset")


def _migration_method(usage: set[str], path: str) -> str:
    if "sync" in usage or "fallback" in usage:
        return "DEPRECATE_AFTER_AUTHORITY_REPLACEMENT"
    if any(token in path for token in ("index", "search", "qdrant", "vector")):
        return "REBUILD_FROM_POSTGRESQL_AND_OBJECT_STORE"
    return "FROZEN_SNAPSHOT_IMPORT_WITH_REVIEW_OR_QUARANTINE"


def _recovery_strategy(usage: set[str]) -> str:
    if "external_effect" in usage:
        return "ExternalEffect UNKNOWN -> reconciliation; stale fences rejected; manual gate"
    return "database-backed resume cursor; idempotent replay; conflict to quarantine"


def _point(item: dict[str, Any]) -> str:
    return f"{item['path']}:{item['line']}:{item.get('qualified_symbol') or item.get('symbol')}"


def _first(findings: list[dict[str, Any]], key: str) -> str:
    return next((str(item[key]) for item in findings if item.get(key)), "")


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:20]
    return f"legacy-migration:{digest}"


def _hash(payload: dict[str, Any]) -> str:
    canonical = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "artifact_hash"}
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Legacy Authority Migration Inventory",
        "",
        "> Generated from AST/code evidence. The JSON sibling is the machine-executable source.",
        "",
        f"- Rows: {payload['summary']['inventory_rows']}",
        f"- Findings: {payload['summary']['legacy_findings']}",
        f"- Artifact hash: `{payload['artifact_hash']}`",
        f"- Legacy production blockers: {payload['summary']['legacy_production_blocker_count']}",
        f"- Unclassified: {payload['summary']['unclassified_count']}",
        "",
        "| Domain | Entrypoint/file | Current authority | Target asset | Operation | Method | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in payload["items"]:
        lines.append(
            "| {business_domain} | `{path}` | {authority} | `{target}` | `{operation}` | {method} | {status} |".format(
                business_domain=item["business_domain"],
                path=item["evidence"][0]["path"],
                authority=", ".join(item["current_authority_source"]),
                target=item["target_authority_asset_type"],
                operation=item["target_operation_definition"],
                method=item["migration_method"],
                status=item["status"],
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args(argv)
    write_inventory(
        args.repo_root,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
