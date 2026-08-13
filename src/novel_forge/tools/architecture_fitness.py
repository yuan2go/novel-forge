"""Fast architecture fitness checks for the current production boundary."""
from __future__ import annotations

import argparse
import ast
import importlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from novel_forge.tools.architecture_manifest import run as run_manifest


def _load(root: Path, name: str) -> dict[str, Any]:
    path = root / "architecture/manifests" / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "architecture-manifest.v1":
        raise ValueError(f"unsupported architecture manifest: {path}")
    return payload


def _python_paths(root: Path, values: Iterable[str]) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for value in values:
        target = root / value
        if target.is_dir():
            paths.update(target.rglob("*.py"))
        elif target.is_file() and target.suffix == ".py":
            paths.add(target)
    return tuple(sorted(paths))


def _source_packages(root: Path) -> tuple[Path, ...]:
    """Count source-bearing packages, never stale bytecode-only directories."""
    return tuple(
        sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and any(path.rglob("*.py"))
        )
    )


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return tuple(values)


def _matches(module: str, forbidden: str) -> bool:
    return module == forbidden or module.startswith(forbidden + ".")


def _is_under(path: Path, roots: Iterable[Path]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _attribute_name(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _provider_direct_violations(
    root: Path,
    paths: Iterable[Path],
    allowlist: Iterable[Path],
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    allowed = tuple(allowlist)
    model_endpoint = re.compile(r"https?://[^\s'\"]*(openai|anthropic)[^\s'\"]*", re.I)
    model_cli = re.compile(r"\b(openai|anthropic|claude|codex)\b", re.I)
    for path in paths:
        if _is_under(path, allowed):
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for module in _imports(path):
            if _matches(module, "openai") or _matches(module, "anthropic"):
                violations.append(
                    {
                        "rule": "provider-direct-import",
                        "path": str(path.relative_to(root)),
                        "detail": module,
                    }
                )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _attribute_name(node.func)
                if name.endswith("responses.create") or name.endswith(
                    "chat.completions.create"
                ):
                    violations.append(
                        {
                            "rule": "provider-direct-call",
                            "path": str(path.relative_to(root)),
                            "detail": name,
                        }
                    )
                if name.startswith("subprocess.") and model_cli.search(
                    ast.get_source_segment(text, node) or ""
                ):
                    violations.append(
                        {
                            "rule": "provider-cli-call",
                            "path": str(path.relative_to(root)),
                            "detail": name,
                        }
                    )
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if model_endpoint.search(node.value):
                    violations.append(
                        {
                            "rule": "provider-direct-http-endpoint",
                            "path": str(path.relative_to(root)),
                            "detail": node.value[:160],
                        }
                    )
    return violations


def _repository_boundary_violations(
    root: Path, policy: dict[str, Any]
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for rule in policy.get("repository_boundary_rules", []):
        paths = _python_paths(root, rule.get("owner_roots", []))
        forbidden = tuple(str(value) for value in rule.get("forbidden_imports", []))
        for path in paths:
            for module in _imports(path):
                if any(_matches(module, denied) for denied in forbidden):
                    violations.append(
                        {
                            "rule": "cross-domain-repository-import",
                            "path": str(path.relative_to(root)),
                            "detail": module,
                        }
                    )
    return violations


def _migration_surface_violations(root: Path) -> list[dict[str, str]]:
    path = root / "architecture/manifests/migration-surface-manifest.yaml"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return [
            {
                "rule": "migration-surface-manifest",
                "path": str(path.relative_to(root)),
                "detail": str(exc),
            }
        ]
    violations: list[dict[str, str]] = []
    required = {
        "schema_version": "novel-forge.migration-surface.v1",
        "classification": "MIGRATION_ONLY",
        "runtime_registration": "FORBIDDEN",
        "production_import": "FORBIDDEN",
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            violations.append(
                {
                    "rule": "migration-surface-policy",
                    "path": str(path.relative_to(root)),
                    "detail": f"{key} must be {expected}",
                }
            )
    for relative in manifest.get("retained_paths", []):
        if not (root / str(relative)).exists():
            violations.append(
                {
                    "rule": "migration-surface-retained-path",
                    "path": str(relative),
                    "detail": "declared retained path is missing",
                }
            )
    for relative in manifest.get("retired_paths", []):
        if (root / str(relative)).exists():
            violations.append(
                {
                    "rule": "migration-surface-retired-path",
                    "path": str(relative),
                    "detail": "retired interactive runtime path still exists",
                }
            )

    from novel_forge.tools.authority_reachability import (
        build_authority_import_graph,
        production_paths as reachable_production_paths,
    )

    graph = build_authority_import_graph(root)
    for relative, paths in graph.paths_by_file.items():
        reached = reachable_production_paths(paths)
        if relative.startswith("src/novel_forge/modules/legacy_migration/") and reached:
            violations.append(
                {
                    "rule": "production-migration-import",
                    "path": relative,
                    "detail": " -> ".join(reached[0]),
                }
            )
    return violations


def _definition_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    module_name, separator, function_name = str(
        entry.get("definition_factory") or ""
    ).partition(":")
    if not separator:
        raise ValueError("definition_factory must use module:function syntax")
    factory = getattr(importlib.import_module(module_name), function_name)
    built = factory(application_build_id="architecture-fitness", commit_sha="0" * 40)
    definitions = (built,) if isinstance(built, dict) else tuple(built)
    for definition in definitions:
        if definition.get("name") == entry.get("name"):
            return definition
    raise ValueError(f"definition factory does not emit {entry.get('name')}")


def _classification_violations(
    root: Path, entries: list[dict[str, Any]]
) -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    expected_mode = {
        "transaction_command": "transactional",
        "durable_job": "worker",
        "saga": "saga",
        "external_effect": "external_effect",
    }
    for entry in entries:
        source = root / str(entry.get("source") or "")
        application = root / str(entry.get("application_source") or "")
        classification = str(entry.get("classification") or "")
        dispatch = str(entry.get("dispatch") or "")
        detail_path = str(application.relative_to(root)) if application.is_file() else str(application)
        try:
            definition = _definition_for_entry(entry)
        except (AttributeError, ImportError, TypeError, ValueError) as exc:
            violations.append(
                {
                    "rule": "operation-definition-resolution",
                    "path": detail_path,
                    "detail": str(exc),
                }
            )
            continue
        if definition.get("execution_mode") != expected_mode.get(classification):
            violations.append(
                {
                    "rule": "execution-mode-classification",
                    "path": detail_path,
                    "detail": f"{entry.get('name')}: {definition.get('execution_mode')} != {classification}",
                }
            )
        if (definition.get("policy") or {}).get(
            "execution_classification"
        ) != classification:
            violations.append(
                {
                    "rule": "execution-policy-classification",
                    "path": detail_path,
                    "detail": str(entry.get("name") or ""),
                }
            )
        if not source.is_file() or not application.is_file():
            violations.append(
                {
                    "rule": "production-entry-path",
                    "path": detail_path,
                    "detail": str(entry.get("name") or ""),
                }
            )
            continue
        source_text = source.read_text(encoding="utf-8")
        application_text = application.read_text(encoding="utf-8")
        api_call = str(entry.get("api_call") or "")
        if not api_call or api_call not in source_text:
            violations.append(
                {
                    "rule": "production-entry-dispatch",
                    "path": str(source.relative_to(root)),
                    "detail": f"{entry.get('name')}: missing {api_call}",
                }
            )
        if classification == "transaction_command":
            forbidden_tokens = (
                "command_kernel.attempt_runtime",
                "create_attempt(",
                "acquire_attempt_lease(",
                "submit_attempt_result(",
            )
            for token in forbidden_tokens:
                if token in application_text:
                    violations.append(
                        {
                            "rule": "transaction-command-attempt-semantics",
                            "path": str(application.relative_to(root)),
                            "detail": token,
                        }
                    )
        if classification == "durable_job" and dispatch != "worker_claim":
            violations.append(
                {
                    "rule": "durable-job-dispatch",
                    "path": detail_path,
                    "detail": dispatch,
                }
            )
        if classification == "external_effect" and not all(
            token in application_text for token in ("external_effect", "receipt")
        ):
            violations.append(
                {
                    "rule": "external-effect-receipt-boundary",
                    "path": detail_path,
                    "detail": str(entry.get("name") or ""),
                }
            )
    return violations


def build_report(repo_root: str | Path = ".") -> dict[str, Any]:
    root = Path(repo_root).resolve()
    policy = _load(root, "fitness-policy.yaml")
    entries = _load(root, "production-entry-manifest.yaml")
    violations: list[dict[str, str]] = []

    domain_root = root / str(policy["domain_package_root"])
    domain_packages = _source_packages(domain_root)
    domain_filenames = set(str(value) for value in policy["domain_layer_filenames"])
    domain_paths = {
        path
        for package in domain_packages
        for path in package.rglob("*.py")
        if path.name in domain_filenames
    }
    forbidden_domain = tuple(str(value) for value in policy["forbidden_domain_imports"])
    for path in sorted(domain_paths):
        for module in _imports(path):
            if any(_matches(module, denied) for denied in forbidden_domain):
                violations.append(
                    {"rule": "domain-import-boundary", "path": str(path.relative_to(root)), "detail": module}
                )

    production_paths = _python_paths(root, policy.get("production_roots", []))
    forbidden_production = tuple(
        str(value) for value in policy.get("forbidden_production_imports", [])
    )
    for path in production_paths:
        modules = _imports(path)
        for module in modules:
            if any(_matches(module, denied) for denied in forbidden_production):
                violations.append(
                    {"rule": "production-legacy-boundary", "path": str(path.relative_to(root)), "detail": module}
                )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            attribute = function.attr if isinstance(function, ast.Attribute) else ""
            if attribute in {"write_json", "write_asset", "write_asset_auto"}:
                violations.append(
                    {"rule": "production-local-write", "path": str(path.relative_to(root)), "detail": attribute}
                )

    provider_paths = _python_paths(root, policy.get("provider_scan_roots", []))
    provider_allowlist = tuple(
        root / str(value) for value in policy.get("provider_direct_call_allowlist", [])
    )
    violations.extend(
        _provider_direct_violations(root, provider_paths, provider_allowlist)
    )
    violations.extend(_repository_boundary_violations(root, policy))
    violations.extend(_migration_surface_violations(root))

    for contract in policy.get("schema_contracts", []):
        path = root / str(contract["path"])
        token = str(contract["token"])
        if not path.is_file() or token not in path.read_text(encoding="utf-8"):
            violations.append(
                {"rule": "public-schema-version", "path": str(contract["path"]), "detail": token}
            )

    valid_classes = {"transaction_command", "durable_job", "saga", "external_effect"}
    entry_names: set[str] = set()
    production_entries = list(entries.get("entries", []))
    for entry in production_entries:
        name = str(entry.get("name") or "")
        source = root / str(entry.get("source") or "")
        classification = str(entry.get("classification") or "")
        definition = str(entry.get("definition_factory") or "")
        if not name or name in entry_names or not source.is_file() or classification not in valid_classes or not definition:
            violations.append(
                {"rule": "production-entry-classification", "path": str(source.relative_to(root)) if source.is_absolute() and source.is_relative_to(root) else str(source), "detail": name}
            )
        entry_names.add(name)
    violations.extend(_classification_violations(root, production_entries))

    subordinate = {
        kind: run_manifest(kind, root)
        for kind in ("migrations", "tests", "console-scripts", "reachability")
    }
    for kind, report in subordinate.items():
        if report["status"] != "PASS":
            violations.append(
                {"rule": f"{kind}-manifest", "path": "architecture/manifests", "detail": str(report.get("error") or "failed")}
            )

    return {
        "status": "PASS" if not violations else "FAIL",
        "schema_version": "architecture-fitness-report.v1",
        "checked_domain_files": len(domain_paths),
        "checked_domain_packages": len(domain_packages),
        "checked_provider_files": len(provider_paths),
        "checked_production_files": len(production_paths),
        "classified_production_entries": len(entry_names),
        "subordinate_manifests": subordinate,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    report = build_report(args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_report", "main"]
