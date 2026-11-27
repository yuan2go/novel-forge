from __future__ import annotations

import argparse
import json
from fnmatch import fnmatchcase
from pathlib import Path
import subprocess
import tomllib
from typing import Any, Iterable

from novel_forge.tools.authority_reachability import (
    build_authority_import_graph,
    production_paths,
)


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _module_for_path(graph: Any, relative: str) -> str:
    for module, path in graph.modules.items():
        if path == relative:
            return module
    return ""


def _reachable_modules(start: str, edges: dict[str, tuple[str, ...]]) -> set[str]:
    seen: set[str] = set()
    pending = [start]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(edges.get(current, ()))
    return seen


def _command_tokens(command: Any) -> tuple[str, ...]:
    if isinstance(command, str):
        return tuple(command.split())
    if isinstance(command, list):
        return tuple(str(item) for item in command)
    return ()


def _deployed_topology(
    root: Path, entrypoints: dict[str, str]
) -> tuple[set[str], set[str]]:
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
        raise ValueError("production reachability requires PyYAML") from exc
    compose = yaml.safe_load((root / "compose.yml").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    console_scripts = dict(pyproject.get("project", {}).get("scripts", {}))
    deployed_modules: set[str] = set()
    worker_operation_patterns: set[str] = set()
    for service in dict(compose.get("services") or {}).values():
        tokens = _command_tokens(service.get("command"))
        if not tokens:
            continue
        if "-m" in tokens:
            index = tokens.index("-m")
            if index + 1 < len(tokens):
                module = tokens[index + 1]
                if module == "novel_forge.cli" and "serve-api" in tokens:
                    module = "novel_forge.api.authority_app"
                deployed_modules.add(module)
        target = console_scripts.get(tokens[0])
        if target:
            deployed_modules.add(str(target).partition(":")[0])
        labels = dict(service.get("labels") or {})
        if str(labels.get("novel-forge.runtime-group") or "") != "api-callback":
            worker_operation_patterns.update(
                item.strip()
                for item in str(
                    labels.get("novel-forge.operation-definitions") or ""
                ).split(",")
                if item.strip()
            )
    return (
        {
            name
            for name, module in entrypoints.items()
            if module in deployed_modules
        },
        worker_operation_patterns,
    )


def _entrypoint_names(paths: Iterable[tuple[str, ...]]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        marker = path[0] if path else ""
        if marker.startswith("entrypoint:"):
            names.add(marker.removeprefix("entrypoint:"))
    return names


def build_production_reachability_manifest(
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    manifest = json.loads(
        (root / "architecture/manifests/production-entry-manifest.yaml").read_text(
            encoding="utf-8"
        )
    )
    graph = build_authority_import_graph(root)
    deployed_entrypoints, worker_operation_patterns = _deployed_topology(
        root, graph.entrypoints
    )
    proof_sha = _git_head(root)
    capabilities: list[dict[str, Any]] = []
    for entry in manifest.get("entries", []):
        source = str(entry.get("source") or "")
        application = str(entry.get("application_source") or "")
        source_path = root / source
        application_path = root / application
        source_routes = production_paths(graph.paths_by_file.get(source, ()))
        application_routes = production_paths(graph.paths_by_file.get(application, ()))
        source_route_names = _entrypoint_names(source_routes)
        application_route_names = _entrypoint_names(application_routes)
        composed_routes = source_route_names & application_route_names
        deployed_routes = composed_routes & deployed_entrypoints
        name = str(entry.get("name") or "")
        worker_backed = any(
            fnmatchcase(name, pattern) for pattern in worker_operation_patterns
        ) and str(entry.get("classification")) != "transaction_command"
        code_exists = source_path.is_file() and application_path.is_file()
        composed = bool(composed_routes)
        deployed = bool(deployed_routes or worker_backed)
        application_module = _module_for_path(graph, application)
        application_dependencies = (
            _reachable_modules(application_module, graph.edges)
            if application_module
            else set()
        )
        authority_backed = any(
            module == "novel_forge.storage.authority_uow"
            or module.startswith("novel_forge.modules.command_kernel")
            for module in application_dependencies
        )
        runtime_reachable = bool(
            code_exists and composed and deployed and authority_backed
        )
        proof_level = (
            "ARCHITECTURE_REACHABLE"
            if runtime_reachable
            else "COMPOSED_NOT_DEPLOYED"
            if composed
            else "CODE_EXISTS"
            if code_exists
            else "MISSING"
        )
        capabilities.append(
            {
                "name": name,
                "classification": str(entry.get("classification") or ""),
                "code_exists": code_exists,
                "composed": composed,
                "deployed": deployed,
                "runtime_reachable": runtime_reachable,
                "authority_backed": authority_backed,
                "worker_backed": worker_backed,
                "deployment_entrypoints": sorted(deployed_routes),
                "proof_level": proof_level,
                "proof_sha": proof_sha,
            }
        )
    return {
        "schema_version": "production-reachability-manifest.v1",
        "proof_boundary": (
            "static composition and Compose reachability; not runtime, Provider, "
            "long-form, or production proof"
        ),
        "proof_sha": proof_sha,
        "deployed_entrypoints": sorted(deployed_entrypoints),
        "capabilities": capabilities,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="derive the current-SHA production reachability manifest"
    )
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build_production_reachability_manifest(args.repo_root),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_production_reachability_manifest", "main"]
