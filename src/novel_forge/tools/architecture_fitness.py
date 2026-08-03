"""Fast architecture fitness checks for the current production boundary."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
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


def build_report(repo_root: str | Path = ".") -> dict[str, Any]:
    root = Path(repo_root).resolve()
    policy = _load(root, "fitness-policy.yaml")
    entries = _load(root, "production-entry-manifest.yaml")
    violations: list[dict[str, str]] = []

    domain_paths: set[Path] = set()
    for pattern in policy.get("domain_globs", []):
        domain_paths.update(root.glob(str(pattern)))
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
            if attribute in {"write_text", "write_bytes", "write_json", "dump"}:
                violations.append(
                    {"rule": "production-local-write", "path": str(path.relative_to(root)), "detail": attribute}
                )

    for contract in policy.get("schema_contracts", []):
        path = root / str(contract["path"])
        token = str(contract["token"])
        if not path.is_file() or token not in path.read_text(encoding="utf-8"):
            violations.append(
                {"rule": "public-schema-version", "path": str(contract["path"]), "detail": token}
            )

    valid_classes = {"transaction_command", "durable_job", "saga", "external_effect"}
    entry_names: set[str] = set()
    for entry in entries.get("entries", []):
        name = str(entry.get("name") or "")
        source = root / str(entry.get("source") or "")
        classification = str(entry.get("classification") or "")
        definition = str(entry.get("operation_definition") or "")
        if not name or name in entry_names or not source.is_file() or classification not in valid_classes or not definition:
            violations.append(
                {"rule": "production-entry-classification", "path": str(source.relative_to(root)) if source.is_absolute() and source.is_relative_to(root) else str(source), "detail": name}
            )
        entry_names.add(name)

    subordinate = {
        kind: run_manifest(kind, root)
        for kind in ("migrations", "tests", "console-scripts")
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
