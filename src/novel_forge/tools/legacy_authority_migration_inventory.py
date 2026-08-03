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


SCHEMA_VERSION = "legacy-authority-migration-inventory.v1"


def build_inventory(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    coverage = build_manifest(root)
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
        rows.append(
            {
                "inventory_id": _stable_id(domain, path, operation or aggregate),
                "business_domain": domain,
                "current_entrypoints": entrypoints,
                "current_authority_source": authorities,
                "current_write_points": writes,
                "current_read_points": reads,
                "target_authority_asset_type": _asset_type(domain, aggregate),
                "target_operation_definition": operation or f"{aggregate}.migration.required",
                "target_repository": repository or f"novel_forge.storage.{aggregate}_repository",
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
                "migration_status": "PLANNED",
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
    summary = {
        "inventory_rows": len(rows),
        "legacy_findings": sum(len(row["evidence"]) for row in rows),
        "business_domains": sorted({row["business_domain"] for row in rows}),
        "production_localstorage_goal": 0,
        "current_coverage_summary": coverage["summary"],
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
    return (
        finding.get("current_authority") in {"localstorage", "filesystem", "mixed"}
        or finding.get("usage_type") in {"fallback", "sync", "dual_write"}
        or "storage.local" in str(finding.get("dependency") or "")
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
                status=item["migration_status"],
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
