"""Static transitive module reachability for the PostgreSQL Authority plane."""
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


AUTHORITY_ENTRY_MODULES: dict[str, str] = {
    "api-app": "novel_forge.api.authority_app",
    "authority-dependencies": "novel_forge.api.authority_dependencies",
    "authority-cli": "novel_forge.cli",
    "chapter-worker": "novel_forge.workers.chapter_authority",
    "content-worker": "novel_forge.workers.content_authority",
    "source-worker": "novel_forge.workers.source_authority",
    "mkaos-worker": "novel_forge.workers.mkaos_authority",
    "book-worker": "novel_forge.workers.book_authority",
    "outbox-worker": "novel_forge.workers.outbox_authority",
    "maintenance-worker": "novel_forge.workers.runtime_groups",
    "worker-healthcheck": "novel_forge.workers.healthcheck",
    "provider-callback": "novel_forge.modules.provider_callback_authority.service",
    "external-effect-dispatch": "novel_forge.modules.command_kernel.external_effect_runtime",
    "provider-qualification-worker": "novel_forge.workers.d0_provider_qualification",
    "compose-probe": "scripts.verify_authority_compose",
}

GUARDED_COMPATIBILITY_BOUNDARIES = frozenset(
    {
        "novel_forge.cli.legacy",
        "novel_forge.model_adapters.guarded",
        "novel_forge.tools.authority_parity_manifest",
    }
)


@dataclass(frozen=True, slots=True)
class ImportGraph:
    modules: dict[str, str]
    edges: dict[str, tuple[str, ...]]
    entrypoints: dict[str, str]
    paths_by_file: dict[str, tuple[tuple[str, ...], ...]]


def build_authority_import_graph(repo_root: str | Path) -> ImportGraph:
    root = Path(repo_root).resolve()
    modules = _module_index(root)
    edges = {
        module: tuple(sorted(_dependencies(module, root / relative, modules)))
        for module, relative in modules.items()
    }
    entrypoints = {
        name: module
        for name, module in AUTHORITY_ENTRY_MODULES.items()
        if module in modules
    }
    paths: dict[str, list[tuple[str, ...]]] = {}
    for entry_name, entry_module in sorted(entrypoints.items()):
        for module, module_path in _shortest_paths(entry_module, edges).items():
            relative = modules[module]
            rendered = (f"entrypoint:{entry_name}", *module_path)
            paths.setdefault(relative, []).append(rendered)
    return ImportGraph(
        modules=modules,
        edges=edges,
        entrypoints=entrypoints,
        paths_by_file={
            path: tuple(sorted(values)) for path, values in sorted(paths.items())
        },
    )


def _module_index(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    source_root = root / "src"
    for candidate in sorted(source_root.rglob("*.py")):
        relative_source = candidate.relative_to(source_root)
        parts = list(relative_source.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        result[".".join(parts)] = candidate.relative_to(root).as_posix()
    for candidate in sorted((root / "scripts").rglob("*.py")):
        parts = list(candidate.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            result[".".join(parts)] = candidate.relative_to(root).as_posix()
    return result


def _dependencies(
    current_module: str, path: Path, known_modules: dict[str, str]
) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _add_known_prefix(alias.name, known_modules, dependencies)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(current_module, node.level, node.module)
            if base:
                _add_known_prefix(base, known_modules, dependencies)
                for alias in node.names:
                    _add_known_prefix(f"{base}.{alias.name}", known_modules, dependencies)
        elif isinstance(node, ast.Call) and _is_dynamic_import(node):
            if node.args and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str):
                    _add_known_prefix(value, known_modules, dependencies)
    dependencies.discard(current_module)
    return dependencies


def _resolve_from(current_module: str, level: int, module: str | None) -> str:
    if level == 0:
        return str(module or "")
    package = current_module.split(".")[:-1]
    trim = max(0, level - 1)
    if trim:
        package = package[:-trim]
    if module:
        package.extend(module.split("."))
    return ".".join(package)


def _is_dynamic_import(node: ast.Call) -> bool:
    function = node.func
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
        and function.attr == "import_module"
    ) or (isinstance(function, ast.Name) and function.id == "import_module")


def _add_known_prefix(
    module: str, known_modules: dict[str, str], dependencies: set[str]
) -> None:
    candidate = module
    while candidate:
        if candidate in known_modules:
            dependencies.add(candidate)
            return
        candidate = candidate.rpartition(".")[0]


def _shortest_paths(
    entry_module: str, edges: dict[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    paths = {entry_module: (entry_module,)}
    queue = deque([entry_module])
    while queue:
        current = queue.popleft()
        for dependency in edges.get(current, ()):
            if dependency in paths:
                continue
            paths[dependency] = (*paths[current], dependency)
            queue.append(dependency)
    return paths


def render_paths(paths: Iterable[tuple[str, ...]]) -> list[list[str]]:
    return [list(path) for path in paths]


def production_paths(paths: Iterable[tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        path
        for path in paths
        if not any(boundary in path for boundary in GUARDED_COMPATIBILITY_BOUNDARIES)
    )


__all__ = [
    "AUTHORITY_ENTRY_MODULES",
    "ImportGraph",
    "build_authority_import_graph",
    "production_paths",
    "render_paths",
]
