"""CONSTRAINT: manifest files use JSON syntax in .yaml files so standard-library JSON parsing and YAML-aware tooling validate the same bytes."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Any, Callable


MANIFEST_DIR = Path("architecture/manifests")


def _load(root: Path, name: str) -> dict[str, Any]:
    path = root / MANIFEST_DIR / name
    if not path.is_file():
        raise ValueError(f"manifest is missing: {path.relative_to(root)}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"manifest is not valid JSON-compatible YAML: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "architecture-manifest.v1":
        raise ValueError(f"unsupported manifest schema: {path}")
    return payload


def _tracked(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError("git tracking state is unavailable")
    return {part.decode("utf-8") for part in result.stdout.split(b"\0") if part}


def _callable_target(target: str) -> None:
    module_name, separator, attribute = target.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"invalid callable target: {target}")
    module = importlib.import_module(module_name)
    value = getattr(module, attribute)
    if not callable(value):
        raise ValueError(f"entrypoint target is not callable: {target}")


def check_modules(root: Path) -> dict[str, Any]:
    manifest = _load(root, "module-manifest.yaml")
    tracked = _tracked(root)
    checked: list[str] = []
    for item in manifest.get("modules", []):
        path = str(item["path"])
        if not (root / path).is_file():
            raise ValueError(f"module path does not exist: {path}")
        if path not in tracked:
            raise ValueError(f"required module is not tracked: {path}")
        importlib.import_module(str(item["import_path"]))
        checked.append(str(item["import_path"]))
    return {"kind": "modules", "checked": len(checked), "items": checked}


def check_migrations(root: Path) -> dict[str, Any]:
    manifest = _load(root, "migration-manifest.yaml")
    from novel_forge.storage.migrations.runner import MIGRATIONS, validate_migration_chain

    validate_migration_chain()
    registered = [migration.migration_id for migration in MIGRATIONS]
    expected = [str(value) for value in manifest.get("migration_ids", [])]
    if registered != expected:
        raise ValueError("migration manifest and registry differ")
    versions = root / "src/novel_forge/storage/migrations/versions"
    files = sorted(
        path.stem for path in versions.glob("v*.py") if path.name != "__init__.py"
    )
    expected_files = ["v" + migration_id for migration_id in expected]
    if files != expected_files:
        raise ValueError("migration registry and version files differ")
    head = str(manifest.get("head") or "")
    if not registered or registered[-1] != head:
        raise ValueError(f"migration head differs: expected {head!r}")
    if len({migration.down_revision for migration in MIGRATIONS[1:]}) != len(MIGRATIONS) - 1:
        raise ValueError("migration chain has multiple children for a revision")
    return {"kind": "migrations", "checked": len(registered), "head": head}


def check_workers(root: Path) -> dict[str, Any]:
    manifest = _load(root, "worker-manifest.yaml")
    tracked = _tracked(root)
    checked: list[str] = []
    names: set[str] = set()
    for item in manifest.get("workers", []):
        name = str(item["name"])
        if name in names:
            raise ValueError(f"duplicate worker manifest name: {name}")
        names.add(name)
        required = ("path", "entrypoint", "deployment_unit", "execution_class", "queue", "health")
        missing = [key for key in required if not str(item.get(key) or "").strip()]
        if missing:
            raise ValueError(f"worker {name} lacks fields: {', '.join(missing)}")
        path = str(item["path"])
        if not (root / path).is_file() or path not in tracked:
            raise ValueError(f"worker target is missing or untracked: {path}")
        _callable_target(str(item["entrypoint"]))
        checked.append(name)
    return {"kind": "workers", "checked": len(checked), "items": checked}


def check_tests(root: Path) -> dict[str, Any]:
    manifest = _load(root, "test-manifest.yaml")
    collections = list(manifest.get("collections", []))
    required_modules = [str(item) for item in manifest.get("required_modules", [])]
    collection_paths: list[str] = []
    for item in collections:
        relative = str(item["start_dir"])
        start = root / relative
        if not start.is_dir():
            raise ValueError(f"test directory does not exist: {start.relative_to(root)}")
        collection_paths.append(relative)
    for relative in required_modules:
        if not (root / relative).is_file():
            raise ValueError(f"required test module is missing: {relative}")

    discovery = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--disable-warnings",
            *collection_paths,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if discovery.returncode:
        detail = discovery.stderr.strip() or discovery.stdout.strip()
        raise ValueError(f"required pytest collection cannot be discovered: {detail}")
    node_ids = tuple(
        line.strip()
        for line in discovery.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )

    results: list[dict[str, Any]] = []
    for item in collections:
        prefix = str(item["start_dir"]).rstrip("/") + "/"
        count = sum(node_id.startswith(prefix) for node_id in node_ids)
        minimum = int(item.get("minimum_count", 1))
        if count < minimum:
            raise ValueError(
                f"required test collection {item['name']} found {count}; minimum is {minimum}"
            )
        results.append({"name": item["name"], "count": count})

    module_results: list[dict[str, Any]] = []
    for relative in required_modules:
        prefix = relative + "::"
        count = sum(node_id.startswith(prefix) for node_id in node_ids)
        if count < 1:
            raise ValueError(f"required test module collected zero tests: {relative}")
        module_results.append({"path": relative, "count": count})
    return {
        "kind": "tests",
        "checked": len(results),
        "collections": results,
        "module_collections": module_results,
    }


def check_console_scripts(root: Path) -> dict[str, Any]:
    manifest = _load(root, "console-script-manifest.yaml")
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    actual = dict(pyproject.get("project", {}).get("scripts", {}))
    expected = {
        str(item["name"]): str(item["target"])
        for item in manifest.get("console_scripts", [])
    }
    if actual != expected:
        raise ValueError("console script manifest and pyproject.toml differ")
    for target in expected.values():
        _callable_target(target)
    return {"kind": "console_scripts", "checked": len(expected), "items": sorted(expected)}


def check_reachability(root: Path) -> dict[str, Any]:
    from novel_forge.tools.production_reachability import (
        build_production_reachability_manifest,
    )

    manifest = build_production_reachability_manifest(root)
    capabilities = list(manifest["capabilities"])
    if not capabilities:
        raise ValueError("production reachability manifest has no capabilities")
    invalid = [
        item["name"]
        for item in capabilities
        if item["runtime_reachable"]
        and not all(
            item[field]
            for field in (
                "code_exists",
                "composed",
                "deployed",
                "authority_backed",
            )
        )
    ]
    if invalid:
        raise ValueError(
            "production reachability overclaims capabilities: " + ", ".join(invalid)
        )
    return {
        "kind": "reachability",
        "checked": len(capabilities),
        "runtime_reachable": sum(
            1 for item in capabilities if item["runtime_reachable"]
        ),
        "proof_sha": manifest["proof_sha"],
    }


CHECKERS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "modules": check_modules,
    "migrations": check_migrations,
    "workers": check_workers,
    "tests": check_tests,
    "console-scripts": check_console_scripts,
    "reachability": check_reachability,
}


def run(kind: str, repo_root: str | Path = ".") -> dict[str, Any]:
    root = Path(repo_root).resolve()
    checker = CHECKERS[kind]
    try:
        result = checker(root)
    except (ImportError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return {"status": "FAIL", "kind": kind, "error": str(exc)}
    return {"status": "PASS", **result}


def main(argv: list[str] | None = None, *, forced_kind: str | None = None) -> int:
    parser = argparse.ArgumentParser()
    if forced_kind is None:
        parser.add_argument("kind", choices=sorted(CHECKERS))
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    kind = forced_kind or args.kind
    report = run(kind, args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CHECKERS", "main", "run"]
