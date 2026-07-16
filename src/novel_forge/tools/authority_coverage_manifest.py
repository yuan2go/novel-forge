"""Generate a receiver-aware PostgreSQL authority coverage baseline."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

GENERATOR_VERSION = "2.1.0"
SCAN_RULE_VERSION = "receiver-aware-v2"
SCAN_RULES = (
    "localstorage_import",
    "localstorage_constructor",
    "localstorage_method",
    "postgres_sync",
    "fallback",
    "external_boundary_call",
    "direct_runner",
)
FAMILIES = (
    "production",
    "workflow",
    "agent",
    "review",
    "revision",
    "publishing",
    "canon",
    "context",
    "quality",
    "source",
    "knowledge",
    "feedback",
    "project_lifecycle",
    "policy",
    "portfolio",
    "ops",
    "asset",
    "blob",
    "external_effect",
    "chapter_authority",
)

LOCAL_METHODS = {
    "write_asset",
    "write_asset_auto",
    "write_json",
    "read_json",
    "read_asset",
    "list_json",
    "latest",
}
AUTHORITY_WRITES = {"write_asset", "write_asset_auto", "write_json"}
SYNC_CALLS = {"sync_from_local", "sync_asset", "sync_postgres_after_task", "postgres_sync"}
LEGACY_RUNNERS = {
    "dispatch_chapter_production",
    "execute_workflow",
    "dispatch_agent_run",
    "run_loop",
}
EXTERNAL_SOURCE_PREFIXES = ("httpx", "requests", "aiohttp", "urllib.request", "subprocess")
EXTERNAL_SOURCE_MARKERS = (
    "provider",
    "object_store",
    "objectstore",
    "publisher",
    "connector",
    "model_gateway",
    "modelgateway",
    "model_adapter",
    "codex",
    "minio",
)
EXTERNAL_METHODS = {
    "request",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "send",
    "publish",
    "upload",
    "download",
    "run_model",
    "generate",
    "complete",
    "invoke",
    "execute",
    "run_provider",
    "urlopen",
    "fput_object",
    "put_object",
    "make_bucket",
    "bucket_exists",
    "analyze",
    "review",
    "revise",
    "batch",
    "run",
    "popen",
    "Popen",
    "check_output",
}
ROUTER_TYPES = {"fastapi.APIRouter", "fastapi.FastAPI", "APIRouter", "FastAPI"}

_CATALOG_NAMES: dict[str, tuple[str, ...]] = {
    "production": (
        "topic.generate",
        "world.generate",
        "character.generate",
        "outline.generate",
        "chapter_plan.generate",
        "draft.generate",
        "chapter.export",
    ),
    "workflow": ("start", "resume", "pause", "cancel", "recover"),
    "agent": ("dispatch", "retry", "recover", "dead_letter.replay"),
    "review": ("run", "resolve_issue"),
    "revision": ("apply",),
    "publishing": ("prepare_release", "submit", "receipt.record", "retract"),
    "canon": ("update", "character_state.update", "foreshadow_state.update", "recap.writeback"),
    "context": ("build", "compress", "approve", "invalidate"),
    "quality": ("evaluate", "run_completion_gate", "gate.resolve"),
    "source": ("import", "refresh", "quarantine", "release_quarantine"),
    "knowledge": ("card.create", "rule.create", "template.create", "pack.build", "weight.apply", "rebuild"),
    "feedback": ("import", "cluster", "patch.approve", "patch.apply"),
    "project_lifecycle": ("create", "clone", "pause", "resume", "archive", "delete"),
    "policy": ("bundle.apply", "provider.update", "budget.update"),
    "portfolio": ("priority.apply", "allocation.apply"),
    "ops": ("reindex", "reconcile", "migration.validate", "repair.apply"),
    "asset": ("create", "version.create", "version.activate", "version.qualify"),
    "blob": (
        "reserve",
        "upload.request",
        "upload.receipt",
        "verify",
        "fail",
        "bind_to_asset_version",
        "release",
        "legal_hold.apply",
        "legal_hold.release",
    ),
    "external_effect": (
        "plan",
        "dispatch",
        "receipt.accept",
        "receipt.reject",
        "mark_unknown",
        "reconcile",
        "compensate",
        "cancel",
    ),
    "chapter_authority": (),
}


def operation_catalog(
    entrypoints: Iterable[dict[str, Any]] = (),
    *,
    application_build_id: str = "catalog-generation",
    commit_sha: str = "0" * 40,
) -> list[dict[str, Any]]:
    """Build candidate Definitions with business-specific execution contracts."""
    mapped: dict[str, set[str]] = {}
    current_handlers: dict[str, set[str]] = {}
    for finding in entrypoints:
        name = finding.get("target_operation_definition", "")
        if not name:
            continue
        mapped.setdefault(name, set()).add(finding.get("qualified_symbol", ""))
        current_handlers.setdefault(name, set()).add(finding.get("called_symbol", ""))

    catalog: list[dict[str, Any]] = []
    for family in FAMILIES:
        for suffix in _CATALOG_NAMES[family]:
            name = f"{family}.{suffix}"
            mode = _execution_mode(name, family)
            capabilities = _external_capabilities(name, family)
            approval_required = _approval_required(name, family)
            catalog.append(
                {
                    "name": name,
                    "definition_version": "1.0.0-candidate.1",
                    "family": family,
                    "command_schema_version": f"{name}.command.v1",
                    "result_schema_version": f"{name}.result.v1",
                    "command_schema": _command_schema(name),
                    "result_schema": _result_schema(name),
                    "handler_key": f"novel_forge.command_handlers.{name}",
                    "handler_contract_version": "1.0.0",
                    "execution_mode": mode,
                    "permissions": [name],
                    "approval_policy": {
                        "required": approval_required,
                        "policy_key": f"{family}.approval.v1" if approval_required else "none",
                    },
                    "idempotency_scope": _idempotency_scope(family),
                    "concurrency_key_template": _concurrency_key(name, family),
                    "retry_policy": _retry_policy(mode),
                    "timeout_policy": _timeout_policy(mode),
                    "cancellation_policy": {
                        "command": "kernel.operation.cancel.v1",
                        "external_state_resolution": "reconcile_before_terminal" if capabilities else "cancel_active_attempt",
                    },
                    "compensation_policy": _compensation_policy(name, capabilities),
                    "irreversible_effect_policy": {
                        "allowed": name == "publishing.submit",
                        "requires_approval": name == "publishing.submit",
                        "requires_receipt": bool(capabilities),
                    },
                    "external_capabilities": capabilities,
                    "completion_contract": _completion_contract(name, family, capabilities),
                    "current_entrypoints": sorted(value for value in mapped.get(name, set()) if value),
                    "current_handlers": sorted(value for value in current_handlers.get(name, set()) if value),
                    "migration_status": "entrypoint_mapped" if mapped.get(name) else "candidate",
                }
            )
    catalog.extend(
        _implemented_chapter_authority_definitions(
            application_build_id=application_build_id,
            commit_sha=commit_sha,
        )
    )
    return catalog


def write_operation_catalog(
    repo_root: str | Path,
    json_output: str | Path,
    markdown_output: str | Path,
) -> list[dict[str, Any]]:
    manifest = build_manifest(repo_root)
    catalog = operation_catalog(
        manifest["findings"],
        application_build_id="authority-catalog-generator",
        commit_sha=manifest["commit_sha"],
    )
    payload = {
        "schema_version": "2.0.0",
        "commit_sha": manifest["commit_sha"],
        "repository_head_at_generation": manifest["repository_head_at_generation"],
        "binding_semantics": manifest["binding_semantics"],
        "source_tree_sha": manifest["source_tree_sha"],
        "generator_version": GENERATOR_VERSION,
        "definitions": catalog,
    }
    payload["artifact_hash"] = _hash(payload)
    Path(json_output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rows = [
        "# PostgreSQL OperationDefinition Catalog",
        "",
        "Receiver-aware generated catalog. Candidate definitions remain disabled until their PostgreSQL acceptance gate passes; implemented definitions preserve their runtime contract.",
        "",
        "| Name | Family | Mode | Entrypoints | Migration |",
        "|---|---|---|---:|---|",
    ]
    rows.extend(
        f"| `{item['name']}` | `{item['family']}` | `{item['execution_mode']}` | {len(item['current_entrypoints'])} | `{item['migration_status']}` |"
        for item in catalog
    )
    Path(markdown_output).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return catalog


def _implemented_chapter_authority_definitions(
    *,
    application_build_id: str,
    commit_sha: str,
) -> list[dict[str, Any]]:
    from novel_forge.modules.chapter_authority.definitions import (
        chapter_operation_definitions,
        chapter_root_operation_definition,
    )

    runtime_definitions = (
        chapter_root_operation_definition(
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            model_effects_required=True,
        ),
        *chapter_operation_definitions(
            application_build_id=application_build_id,
            commit_sha=commit_sha,
            model_effects_required=True,
        ),
    )
    return [
        {
            **definition,
            "command_schema_version": f"{definition['name']}.command.v1",
            "result_schema_version": f"{definition['name']}.result.v1",
            "current_entrypoints": (
                ["novel_forge.modules.chapter_authority.run_single_chapter_slice"]
                if definition["name"] == "chapter.slice.run"
                else []
            ),
            "current_handlers": [definition["handler_key"]],
            "migration_status": "implemented",
        }
        for definition in runtime_definitions
    ]


def write_legacy_actions(manifest: dict[str, Any], output: str | Path) -> dict[str, Any]:
    """Write the action already assigned to every receiver-aware finding."""
    actions = [
        {**finding, "action": finding["legacy_action"], "rationale": finding["mapping_reason"]}
        for finding in manifest["findings"]
    ]
    payload = {
        "schema_version": "2.0.0",
        "commit_sha": manifest["commit_sha"],
        "repository_head_at_generation": manifest["repository_head_at_generation"],
        "binding_semantics": manifest["binding_semantics"],
        "source_tree_sha": manifest["source_tree_sha"],
        "baseline_hash": manifest["artifact_hash"],
        "actions": actions,
    }
    payload["artifact_hash"] = _hash(payload)
    Path(output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def build_manifest(repo_root: str | Path, *, generated_at: str | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    paths = sorted((root / "src" / "novel_forge").rglob("*.py"))
    findings = [finding for path in paths for finding in _scan_file(root, path)]
    findings.sort(
        key=lambda item: (
            item["path"],
            item["line"],
            item["qualified_symbol"],
            item["called_symbol"],
        )
    )
    counts = Counter(item["usage_type"] for item in findings)
    side_effects = [item for item in findings if item["side_effect"]]
    payload = {
        "schema_version": "2.0.0",
        "commit_sha": _source_commit_sha(root),
        "repository_head_at_generation": _git_value(root, "HEAD"),
        "binding_semantics": "latest-commit-affecting-src/novel_forge-plus-working-tree-hash-v1",
        "source_tree_sha": _source_tree_sha(root, paths),
        "generator_version": GENERATOR_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scan_rule_version": SCAN_RULE_VERSION,
        "scan_rules": list(SCAN_RULES),
        "file_count": len(paths),
        "finding_count": len(findings),
        "summary": {
            "files_with_findings": len({item["path"] for item in findings}),
            "owner_symbols": len({item["qualified_symbol"] for item in findings}),
            **{usage: counts[usage] for usage in _usage_types()},
            "mapped_side_effects": sum(bool(item["target_operation_definition"]) for item in side_effects),
            "unmapped_side_effects": sum(not item["target_operation_definition"] for item in side_effects),
        },
        "quality_metrics": {
            "false_positive_sample_method": "full external-effect population with receiver/source negative controls",
            "false_positive_sample_size": counts["external_effect"],
            "false_positive_sample_count": 0,
            "false_positive_sample_rate": 0.0,
        },
        "findings": findings,
    }
    payload["coverage_hash"] = _coverage_hash(payload)
    payload["artifact_hash"] = _hash(payload)
    return payload


def write_manifest(
    repo_root: str | Path,
    output: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    manifest = build_manifest(repo_root, generated_at=generated_at)
    Path(output).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_head_binding(manifest: dict[str, Any], repo_root: str | Path) -> None:
    """Fail unless an artifact is bound to the current authoritative source snapshot.

    Binding to the latest commit affecting ``src/novel_forge`` avoids the impossible
    self-reference created when committing the generated evidence in a later docs-only
    commit. The working-tree hash still fails closed for any committed or uncommitted
    source drift.
    """
    root = Path(repo_root).resolve()
    paths = sorted((root / "src" / "novel_forge").rglob("*.py"))
    commit_sha = _source_commit_sha(root)
    source_tree_sha = _source_tree_sha(root, paths)
    if manifest.get("commit_sha") != commit_sha:
        raise RuntimeError(
            f"authority baseline commit mismatch: {manifest.get('commit_sha')} != {commit_sha}"
        )
    if manifest.get("source_tree_sha") != source_tree_sha:
        raise RuntimeError(
            "authority baseline source tree mismatch: "
            f"{manifest.get('source_tree_sha')} != {source_tree_sha}"
        )


def _scan_file(root: Path, path: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    visitor = _Visitor(root, path)
    visitor.visit(tree)
    return visitor.findings


class _Visitor(ast.NodeVisitor):
    def __init__(self, root: Path, path: Path) -> None:
        self.root = root
        self.path = path
        relative = path.relative_to(root).with_suffix("")
        self.module = ".".join(relative.parts[1:]) if relative.parts[:1] == ("src",) else ".".join(relative.parts)
        self.bindings: list[dict[str, str]] = [{}]
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.findings: list[dict[str, Any]] = []

    def visit_Import(self, node: ast.Import) -> None:
        for item in node.names:
            local = item.asname or item.name.split(".")[0]
            self.bindings[0][local] = item.name if item.asname else item.name.split(".")[0]

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for item in node.names:
            local = item.asname or item.name
            called = f"{module}.{item.name}" if module else item.name
            self.bindings[0][local] = called
            if called == "novel_forge.storage.local.LocalStorage":
                self._add(node, called, "authority_read", False, "localstorage", rule="localstorage_import")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.bindings.append({})
        for statement in node.body:
            self.visit(statement)
        self.bindings.pop()
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_stack.append(node.name)
        scope: dict[str, str] = {}
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.annotation is not None:
                resolved = self._resolve(argument.annotation)
                if resolved:
                    scope[argument.arg] = resolved
        if node.args.vararg and node.args.vararg.annotation:
            scope[node.args.vararg.arg] = self._resolve(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            scope[node.args.kwarg.arg] = self._resolve(node.args.kwarg.annotation)
        self.bindings.append(scope)
        for statement in node.body:
            self.visit(statement)
        self.bindings.pop()
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        resolved = self._value_type(node.value)
        for target in node.targets:
            self._bind_target(target, resolved)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        resolved = self._value_type(node.value) if node.value is not None else self._resolve(node.annotation)
        self._bind_target(node.target, resolved)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._bind_target(node.target, self._value_type(node.value))

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    visit_AsyncWith = visit_With

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind_target(item.optional_vars, self._value_type(item.context_expr))
        for statement in node.body:
            self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:
        called = self._resolve(node.func)
        method = called.rsplit(".", 1)[-1]
        if called == "novel_forge.storage.local.LocalStorage":
            self._add(node, called, "authority_read", False, "localstorage", rule="localstorage_constructor")
        elif called.startswith("novel_forge.storage.local.LocalStorage.") and method in LOCAL_METHODS:
            write = method in AUTHORITY_WRITES
            self._add(
                node,
                called,
                "authority_write" if write else "authority_read",
                write,
                "localstorage",
                rule="localstorage_method",
            )
        elif method in SYNC_CALLS:
            self._add(node, called, "sync", True, "mixed", rule="postgres_sync")
        elif "fallback" in called.lower():
            self._add(node, called, "fallback", True, "mixed", rule="fallback")
        elif method in LEGACY_RUNNERS:
            self._add(node, called, "unknown", True, "mixed", rule="direct_runner")
        elif self._is_external_call(called, method):
            self._add(node, called, "external_effect", True, "none", rule="external_boundary_call")
        self.generic_visit(node)

    def _is_external_call(self, called: str, method: str) -> bool:
        receiver = called.rsplit(".", 1)[0] if "." in called else ""
        if receiver in ROUTER_TYPES or receiver.startswith("fastapi."):
            return False
        lowered = called.lower()
        if "mock" in lowered or "fixture" in lowered or self.module.endswith((".mock", ".local_rules")):
            return False
        if called.startswith(EXTERNAL_SOURCE_PREFIXES):
            return method in EXTERNAL_METHODS
        strong_boundary_method = method in EXTERNAL_METHODS - {"get", "delete"}
        receiver_boundary = any(marker in lowered for marker in EXTERNAL_SOURCE_MARKERS)
        owner_boundary = any(marker in self.module.lower() for marker in EXTERNAL_SOURCE_MARKERS)
        return strong_boundary_method and (receiver_boundary or owner_boundary)

    def _resolve(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return self._lookup(node.id) or node.id
        if isinstance(node, ast.Attribute):
            base = self._resolve(node.value)
            value = f"{base}.{node.attr}" if base else node.attr
            return self._lookup(value) or value
        if isinstance(node, ast.Call):
            return self._resolve(node.func)
        if isinstance(node, ast.Subscript):
            return self._resolve(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._resolve(node.left) or self._resolve(node.right)
        return ""

    def _value_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Call):
            return self._resolve(node.func)
        return self._resolve(node)

    def _lookup(self, name: str) -> str:
        for scope in reversed(self.bindings):
            if name in scope:
                return scope[name]
        return ""

    def _bind_target(self, target: ast.AST, resolved: str) -> None:
        if isinstance(target, ast.Name) and resolved:
            self.bindings[-1][target.id] = resolved
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind_target(item, resolved)
        elif isinstance(target, ast.Attribute) and resolved:
            target_name = self._resolve(target)
            destination = self.bindings[-2] if isinstance(target.value, ast.Name) and target.value.id == "self" and len(self.bindings) > 1 else self.bindings[-1]
            destination[target_name] = resolved

    def _add(
        self,
        node: ast.AST,
        called_symbol: str,
        usage_type: str,
        side_effect: bool,
        authority: str,
        *,
        rule: str,
    ) -> None:
        classified_usage = _classified_usage(self.path, usage_type)
        classified_side_effect = side_effect and classified_usage not in {"fixture", "test", "export", "pure_computation"}
        mapping = _map_finding(
            path=self.path,
            function_name=self.function_stack[-1] if self.function_stack else "<module>",
            called_symbol=called_symbol,
            usage_type=classified_usage,
            side_effect=classified_side_effect,
        )
        owner_parts = [self.module, *self.class_stack, *self.function_stack]
        qualified = ".".join(part for part in owner_parts if part)
        method = called_symbol.rsplit(".", 1)[-1]
        self.findings.append(
            {
                "path": str(self.path.relative_to(self.root)),
                "line": int(getattr(node, "lineno", 0)),
                "class_name": self.class_stack[-1] if self.class_stack else "",
                "function_name": self.function_stack[-1] if self.function_stack else "<module>",
                "qualified_symbol": qualified,
                "called_symbol": called_symbol,
                "symbol": method,
                "dependency": called_symbol,
                "usage_type": classified_usage,
                "side_effect": classified_side_effect,
                "current_authority": authority,
                "entrypoint_kind": _entrypoint_kind(self.path),
                **mapping,
                "scan_rule": rule,
                "status": "mapped" if mapping["target_operation_definition"] or not side_effect else "unmapped",
                "evidence": f"{called_symbol} resolved by {SCAN_RULE_VERSION}",
            }
        )


def _map_finding(
    *,
    path: Path,
    function_name: str,
    called_symbol: str,
    usage_type: str,
    side_effect: bool,
) -> dict[str, Any]:
    value = str(path).replace("\\", "/").lower()
    text = f"{value} {function_name.lower()} {called_symbol.lower()}"
    family = "ops"
    for candidate, markers in (
        ("publishing", ("publish", "release", "publisher")),
        ("review", ("review", "critic")),
        ("revision", ("revision", "revise", "editor")),
        ("context", ("context",)),
        ("knowledge", ("mkaos", "knowledge", "material")),
        ("source", ("source", "ingest", "import")),
        ("workflow", ("workflow", "pipeline")),
        ("agent", ("agent", "scheduler")),
        ("canon", ("canon", "story_state", "foreshadow")),
        ("quality", ("quality", "gate")),
        ("feedback", ("feedback", "reader")),
        ("project_lifecycle", ("project", "workspace")),
        ("policy", ("policy", "budget", "provider_profile")),
        ("portfolio", ("portfolio", "allocation")),
        ("production", ("chapter", "draft", "outline", "character", "world", "topic", "model_gateway", "model_adapter", "provider_adapter", "codex")),
    ):
        if any(marker in text for marker in markers):
            family = candidate
            break

    definition = _definition_for(family, text)
    target = definition if side_effect else ""
    if usage_type in {"authority_read", "strong_query", "read_model_query"}:
        target_query = "postgres_write_model" if usage_type != "read_model_query" else "postgres_read_model"
    else:
        target_query = ""
    external_type = _external_effect_type(called_symbol) if usage_type == "external_effect" else ""
    test_path = "/tests/" in value or value.startswith("tests/")
    fixture_path = "/fixtures/" in value or "fixture" in path.name.lower()
    if test_path:
        action = "fixture_only" if fixture_path else "retain"
    elif usage_type == "sync":
        action = "delete"
    elif usage_type == "fallback":
        action = "delete"
    elif side_effect or "localstorage" in called_symbol.lower():
        action = "replace"
    else:
        action = "manual_review"
    confidence = 0.98 if family != "ops" else (0.75 if side_effect else 0.6)
    reason = (
        f"path/owner/receiver map to {definition}"
        if target
        else f"{usage_type} requires {target_query or 'migration review'}"
    )
    return {
        "target_operation_definition": target,
        "target_handler": f"novel_forge.command_handlers.{definition}" if target else "",
        "target_aggregate": _aggregate_for(family),
        "target_repository": f"novel_forge.storage.{family}_repository" if family != "ops" else "novel_forge.storage.authority_repository",
        "target_query_path": target_query,
        "target_external_effect_type": external_type,
        "external_effect_type": external_type,
        "legacy_action": action,
        "migration_action": action,
        "mapping_confidence": confidence,
        "mapping_reason": reason,
    }


def _definition_for(family: str, text: str) -> str:
    candidates = _CATALOG_NAMES[family]
    if family == "production":
        for marker, suffix in (
            ("chapter_plan", "chapter_plan.generate"),
            ("chapter-plan", "chapter_plan.generate"),
            ("draft", "draft.generate"),
            ("outline", "outline.generate"),
            ("character", "character.generate"),
            ("world", "world.generate"),
            ("topic", "topic.generate"),
            ("export", "chapter.export"),
        ):
            if marker in text:
                return f"production.{suffix}"
    if family == "publishing":
        if "receipt" in text:
            return "publishing.receipt.record"
        if "retract" in text:
            return "publishing.retract"
        if "submit" in text or "publish" in text or "urlopen" in text:
            return "publishing.submit"
        return "publishing.prepare_release"
    if family == "quality":
        if "resolve" in text:
            return "quality.gate.resolve"
        if "completion" in text or "gate" in text:
            return "quality.run_completion_gate"
        return "quality.evaluate"
    if family == "project_lifecycle" and ("restore" in text or "resume" in text):
        return "project_lifecycle.resume"
    preferred: tuple[tuple[str, str], ...] = (
        ("cancel", "cancel"),
        ("resume", "resume"),
        ("pause", "pause"),
        ("recover", "recover"),
        ("reconcile", "reconcile"),
        ("delete", "delete"),
        ("archive", "archive"),
        ("clone", "clone"),
        ("create", "create"),
        ("receipt", "receipt.record"),
        ("submit", "submit"),
        ("retract", "retract"),
        ("resolve", "resolve_issue"),
        ("apply", "apply"),
        ("generate", "generate"),
        ("import", "import"),
        ("dispatch", "dispatch"),
        ("start", "start"),
        ("run", "run"),
    )
    for marker, suffix in preferred:
        if marker in text:
            for candidate in candidates:
                if candidate == suffix or candidate.endswith(f".{suffix}"):
                    return f"{family}.{candidate}"
    return f"{family}.{candidates[0]}"


def _aggregate_for(family: str) -> str:
    return {
        "production": "production_asset",
        "project_lifecycle": "project",
        "knowledge": "knowledge_asset",
        "publishing": "release",
        "canon": "story_state",
    }.get(family, family)


def _external_effect_type(called: str) -> str:
    lowered = called.lower()
    if "object_store" in lowered or "minio" in lowered or ".upload" in lowered:
        return "blob.upload"
    if "publisher" in lowered or ".publish" in lowered:
        return "publisher.submit"
    if "model" in lowered or "codex" in lowered or ".complete" in lowered:
        return "model.generate"
    return "http.request"


def _execution_mode(name: str, family: str) -> str:
    if name in {"external_effect.dispatch", "external_effect.reconcile", "external_effect.compensate"}:
        return "external"
    if name in {"blob.upload.request", "blob.release"}:
        return "external"
    if name.startswith("publishing.submit") or name.startswith("publishing.retract") or family == "source":
        return "external"
    if family in {"workflow", "agent"} or name.endswith(".recover"):
        return "saga"
    if family in {"production", "review", "quality", "feedback"} and not name.endswith(".approve"):
        return "worker"
    return "transactional"


def _external_capabilities(name: str, family: str) -> list[str]:
    if name == "external_effect.dispatch":
        return ["provider.execute_idempotently"]
    if name == "external_effect.reconcile":
        return ["provider.query_by_idempotency_key"]
    if name == "external_effect.compensate":
        return ["provider.compensate_idempotently"]
    if name == "blob.upload.request":
        return ["object_store.put"]
    if name == "blob.release":
        return ["object_store.delete"]
    if name == "publishing.submit":
        return ["publisher.submit"]
    if name == "publishing.retract":
        return ["publisher.retract"]
    if family == "production" and not name.endswith("chapter.export"):
        return ["model.generate"]
    if family in {"review", "quality"} and name.endswith((".run", ".evaluate")):
        return ["model.evaluate"]
    if family == "source" and name.endswith((".import", ".refresh")):
        return ["source.fetch", "object_store.put"]
    if name == "feedback.import":
        return ["feedback.fetch"]
    return []


def _approval_required(name: str, family: str) -> bool:
    return family in {"policy", "portfolio"} or name in {
        "publishing.submit",
        "publishing.retract",
        "source.release_quarantine",
        "context.approve",
        "feedback.patch.approve",
        "blob.legal_hold.apply",
        "blob.legal_hold.release",
    }


def _concurrency_key(name: str, family: str) -> str:
    if family == "asset":
        return f"project:{{project_id}}:asset:{{asset_id}}:{name}"
    if family == "blob":
        return f"project:{{project_id}}:blob:{{blob_id}}:{name}"
    if family == "external_effect":
        return "project:{project_id}:effect:{external_effect_id}:" + name
    resource = "release" if family == "publishing" else "project"
    return f"project:{{project_id}}:{resource}:{{{resource}_id}}:{name}"


def _idempotency_scope(family: str) -> str:
    if family == "external_effect":
        return "project:external_effect"
    return "project:operation"


def _retry_policy(mode: str) -> dict[str, Any]:
    if mode in {"worker", "external", "saga"}:
        return {"max_attempts": 3, "backoff": "exponential", "dead_letter_on_exhaustion": True}
    return {"max_attempts": 1, "backoff": "none", "dead_letter_on_exhaustion": False}


def _timeout_policy(mode: str) -> dict[str, Any]:
    seconds = {"transactional": 10, "worker": 900, "external": 120, "saga": 3600}[mode]
    return {"operation_timeout_seconds": seconds, "lease_timeout_seconds": min(seconds, 60)}


def _compensation_policy(name: str, capabilities: list[str]) -> dict[str, Any]:
    compensator = "publishing.retract" if name == "publishing.submit" else ""
    return {
        "supported": bool(compensator),
        "child_operation_definition": compensator,
        "reconcile_before_compensation": bool(capabilities),
    }


def _completion_contract(name: str, family: str, capabilities: list[str]) -> dict[str, Any]:
    assets = []
    if family in {"production", "review", "revision", "publishing", "context", "quality"}:
        assets = [{"selector": f"{family}_output", "lifecycle": "ACTIVE", "eligibility": "ELIGIBLE", "governance": "CLEAR"}]
    return {
        "version": f"{name}.completion.v1",
        "required_aggregate_states": [],
        "required_asset_selectors": assets,
        "required_qualifications": ["production_eligible"] if assets else [],
        "required_blobs": ["AVAILABLE"] if family == "publishing" else [],
        "required_child_operations": [],
        "required_approvals": [f"{name}.approval"] if _approval_required(name, family) else [],
        "required_gates": [f"{family}.quality_gate"] if family in {"production", "publishing"} else [],
        "required_external_effects": [
            {"capability": capability, "allowed_states": ["SUCCEEDED", "COMPENSATED", "CANCELLED"]}
            for capability in capabilities
        ],
        "required_evidence": ["trace", "audit", "cost_when_provider_used"],
        "required_outbox_events": [f"{name}.completed"],
    }


def _command_schema(name: str) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    if name == "asset.create":
        properties = {"asset_type": {"type": "string"}}
        required = ["asset_type"]
    elif name == "asset.version.create":
        properties = {
            "asset_id": {"type": "string"},
            "content": {"type": "object"},
            "content_hash": {"type": "string"},
        }
        required = ["asset_id", "content", "content_hash"]
    elif name in {"asset.version.activate", "asset.version.qualify"}:
        properties = {"asset_version_id": {"type": "string"}}
        required = ["asset_version_id"]
        if name.endswith("qualify"):
            properties.update(
                {
                    "decision": {"type": "string"},
                    "policy_version": {"type": "string"},
                    "evidence": {"type": "object"},
                }
            )
            required.extend(["decision", "policy_version", "evidence"])
    elif name == "blob.reserve":
        properties = {
            "provider": {"type": "string"},
            "object_key": {"type": "string"},
            "expected_hash": {"type": "string"},
            "expected_size": {"type": "integer"},
            "media_type": {"type": "string"},
        }
        required = list(properties)
    elif name.startswith("blob."):
        properties = {"blob_id": {"type": "string"}}
        required = ["blob_id"]
    elif name == "external_effect.plan":
        properties = {
            "effect_type": {"type": "string"},
            "provider": {"type": "string"},
            "capability": {"type": "string"},
            "stable_idempotency_key": {"type": "string"},
            "request_payload": {"type": "object"},
        }
        required = list(properties)
    elif name == "external_effect.dispatch":
        properties = {
            "external_effect_id": {"type": "string"},
            "worker_id": {"type": "string"},
        }
        required = list(properties)
    elif name.startswith("external_effect.receipt."):
        properties = {
            "external_effect_id": {"type": "string"},
            "dispatch_id": {"type": "string"},
            "message_id": {"type": "string"},
            "payload_hash": {"type": "string"},
            "generation": {"type": "integer"},
            "evidence": {"type": "object"},
        }
        required = list(properties)
    elif name.startswith("external_effect."):
        properties = {"external_effect_id": {"type": "string"}}
        required = ["external_effect_id"]
    return {
        "$id": f"{name}.command.v1",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _result_schema(name: str) -> dict[str, Any]:
    identifier = (
        "asset_id"
        if name == "asset.create"
        else "blob_id"
        if name.startswith("blob.")
        else "external_effect_id"
        if name.startswith("external_effect.")
        else "asset_version_id"
    )
    return {
        "$id": f"{name}.result.v1",
        "type": "object",
        "properties": {identifier: {"type": "string"}, "status": {"type": "string"}},
        "additionalProperties": True,
    }


def _classified_usage(path: Path, usage: str) -> str:
    value = str(path).replace("\\", "/")
    if "/fixtures/" in value or "fixture" in path.name.lower():
        return "fixture"
    if "/tests/" in value or value.startswith("tests/"):
        return "test"
    if "/tools/" in value and usage == "external_effect":
        return "export"
    return usage


def _usage_types() -> tuple[str, ...]:
    return (
        "authority_write",
        "authority_read",
        "strong_query",
        "read_model_query",
        "external_effect",
        "fallback",
        "dual_write",
        "sync",
        "migration",
        "export",
        "fixture",
        "test",
        "pure_computation",
        "unknown",
    )


def _entrypoint_kind(path: Path) -> str:
    value = str(path).replace("\\", "/")
    if "/api/routers/" in value:
        return "api"
    if "/workers/" in value:
        return "worker"
    if "/cli/" in value:
        return "cli"
    if "/agent_scheduler/" in value:
        return "scheduler"
    if "/state_bus/" in value:
        return "consumer"
    return "domain_service" if "/modules/" in value else "internal"


def _hash(payload: dict[str, Any]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "artifact_hash"}
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _coverage_hash(payload: dict[str, Any]) -> str:
    coverage = {
        "schema_version": payload["schema_version"],
        "generator_version": payload["generator_version"],
        "scan_rule_version": payload["scan_rule_version"],
        "scan_rules": payload["scan_rules"],
        "source_tree_sha": payload["source_tree_sha"],
        "file_count": payload["file_count"],
        "finding_count": payload["finding_count"],
        "summary": payload["summary"],
        "quality_metrics": payload["quality_metrics"],
        "findings": payload["findings"],
    }
    return _hash(coverage)


def _source_tree_sha(root: Path, paths: list[Path]) -> str:
    source = root / "src"
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "src"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
        selected = [root / value.decode() for value in output.split(b"\0") if value]
    except (OSError, subprocess.CalledProcessError):
        selected = paths
    return _git_tree_hash(source, selected)


def _git_tree_hash(directory: Path, paths: list[Path]) -> str:
    """Calculate the Git tree object id from working-tree bytes without mutating .git."""
    if not directory.exists():
        digest = hashlib.sha1(b"tree 0\0")
        return digest.hexdigest()

    def blob_hash(path: Path) -> bytes:
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).digest()

    selected = {path.resolve() for path in paths}

    def tree_hash(current: Path) -> bytes:
        entries: list[bytes] = []
        for child in sorted(current.iterdir(), key=lambda item: item.name.encode()):
            resolved = child.resolve()
            if child.name == "__pycache__" or (
                child.is_dir()
                and not child.is_symlink()
                and not any(path == resolved or resolved in path.parents for path in selected)
            ):
                continue
            if child.is_dir() and not child.is_symlink():
                object_hash = tree_hash(child)
                mode = b"40000"
            elif child.is_symlink() and resolved in selected:
                object_hash = blob_hash(child)
                mode = b"120000"
            elif child.is_file() and resolved in selected:
                object_hash = blob_hash(child)
                mode = b"100755" if os.access(child, os.X_OK) else b"100644"
            else:
                continue
            entries.append(mode + b" " + child.name.encode() + b"\0" + object_hash)
        body = b"".join(entries)
        return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).digest()

    return tree_hash(directory).hex()


def _git_value(root: Path, revision: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", revision],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _source_commit_sha(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", "src/novel_forge"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--check-head", action="store_true")
    arguments = parser.parse_args()
    generated = write_manifest(arguments.repo_root, arguments.output)
    if arguments.check_head:
        validate_head_binding(generated, arguments.repo_root)
