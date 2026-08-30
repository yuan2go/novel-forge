"""INVARIANT: integrity checks combine imports with Git tracking because an untracked module can work locally but fail from a clean checkout."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable

import yaml


DEFAULT_REQUIRED_IMPORTS = (
    "novel_forge",
    "novel_forge.modules.book_authority",
    "novel_forge.api.authority_app",
    "novel_forge.storage.migrations.versions",
)

@dataclass(frozen=True, slots=True)
class HeadIntegrityReport:
    tracked_file_count: int
    scanned_python_files: int
    missing_import_targets: tuple[str, ...]
    untracked_required_paths: tuple[str, ...]
    missing_exports: tuple[str, ...]
    missing_registry_targets: tuple[str, ...]
    failed_required_imports: tuple[str, ...]
    missing_test_collection: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.missing_import_targets,
                self.untracked_required_paths,
                self.missing_exports,
                self.missing_registry_targets,
                self.failed_required_imports,
                self.missing_test_collection,
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "tracked_file_count": self.tracked_file_count,
            "scanned_python_files": self.scanned_python_files,
            "missing_import_targets": list(self.missing_import_targets),
            "untracked_required_paths": list(self.untracked_required_paths),
            "missing_exports": list(self.missing_exports),
            "missing_registry_targets": list(self.missing_registry_targets),
            "failed_required_imports": list(self.failed_required_imports),
            "missing_test_collection": list(self.missing_test_collection),
        }


def build_head_integrity_report(
    repo_root: str | Path,
    *,
    tracked_paths: set[str] | None = None,
    required_imports: Iterable[str] = DEFAULT_REQUIRED_IMPORTS,
) -> HeadIntegrityReport:
    root = Path(repo_root).resolve()
    tracked = tracked_paths if tracked_paths is not None else _git_tracked_paths(root)
    source_root = root / "src"
    package_root = source_root / "novel_forge"
    python_files = tuple(sorted(package_root.rglob("*.py"))) if package_root.exists() else ()
    missing_imports: set[str] = set()
    untracked_dependencies: set[str] = set()
    missing_exports: set[str] = set()

    for path in python_files:
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except SyntaxError as exc:
            missing_imports.add(f"{relative}:syntax:{exc.lineno}")
            continue
        dependencies, unresolved = _internal_dependencies(path, tree, source_root)
        missing_imports.update(unresolved)
        if relative in tracked:
            untracked_dependencies.update(
                dependency.relative_to(root).as_posix()
                for dependency in dependencies
                if dependency.relative_to(root).as_posix() not in tracked
            )
        if path.name == "__init__.py":
            module_name = _module_name(path, source_root)
            missing_exports.update(
                f"{module_name}:{name}"
                for name in _missing_static_exports(tree)
            )

    registry_targets = _registry_target_failures(root, tracked)
    failed_imports = _required_import_failures(root, required_imports)
    missing_collection = _test_collection_failures(root)
    return HeadIntegrityReport(
        tracked_file_count=len(tracked),
        scanned_python_files=len(python_files),
        missing_import_targets=tuple(sorted(missing_imports)),
        untracked_required_paths=tuple(sorted(untracked_dependencies)),
        missing_exports=tuple(sorted(missing_exports)),
        missing_registry_targets=tuple(sorted(registry_targets)),
        failed_required_imports=tuple(sorted(failed_imports)),
        missing_test_collection=tuple(sorted(missing_collection)),
    )


def _git_tracked_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "HEAD_INTEGRITY_GIT_REQUIRED: repository tracking state is unavailable"
        )
    return {
        item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    }


def _internal_dependencies(
    path: Path,
    tree: ast.AST,
    source_root: Path,
) -> tuple[set[Path], set[str]]:
    dependencies: set[Path] = set()
    unresolved: set[str] = set()
    current_module = _module_name(path, source_root)
    current_package = (
        current_module
        if path.name == "__init__.py"
        else current_module.rpartition(".")[0]
    )
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(
                alias.name for alias in node.names if alias.name.startswith("novel_forge")
            )
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_import_module(
                current_package=current_package,
                module=node.module or "",
                level=node.level,
            )
            if not base.startswith("novel_forge"):
                continue
            modules.append(base)
            modules.extend(f"{base}.{alias.name}" for alias in node.names)
        else:
            continue
        found_for_statement = False
        for module in modules:
            target = _module_path(module, source_root)
            if target is not None:
                dependencies.add(target)
                found_for_statement = True
        if not found_for_statement and modules:
            unresolved.add(f"{path.relative_to(source_root)}:{modules[0]}")
    return dependencies, unresolved


def _absolute_import_module(
    *, current_package: str, module: str, level: int
) -> str:
    if level == 0:
        return module
    parts = current_package.split(".")
    trim = max(level - 1, 0)
    if trim:
        parts = parts[:-trim]
    return ".".join((*parts, *module.split("."))) if module else ".".join(parts)


def _module_path(module: str, source_root: Path) -> Path | None:
    if not module.startswith("novel_forge"):
        return None
    relative = Path(*module.split("."))
    file_target = source_root / relative.with_suffix(".py")
    if file_target.is_file():
        return file_target
    package_target = source_root / relative / "__init__.py"
    if package_target.is_file():
        return package_target
    return None


def _module_name(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _missing_static_exports(tree: ast.AST) -> set[str]:
    available: set[str] = set()
    exports: tuple[str, ...] | None = None
    dynamic_exports = False
    for node in getattr(tree, "body", ()):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            available.add(node.name)
            dynamic_exports = dynamic_exports or node.name == "__getattr__"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name != "*":
                    available.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    available.add(target.id)
            value = node.value
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in targets
            ):
                literal = _string_sequence(value)
                if literal is not None:
                    exports = literal
    if exports is None or dynamic_exports:
        return set()
    return set(exports) - available


def _string_sequence(node: ast.AST | None) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.append(item.value)
    return tuple(values)


def _registry_target_failures(root: Path, tracked: set[str]) -> set[str]:
    failures: set[str] = set()
    registry = (
        root
        / "src"
        / "novel_forge"
        / "storage"
        / "migrations"
        / "versions"
        / "__init__.py"
    )
    if registry.is_file():
        tree = ast.parse(registry.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is not None:
                continue
            for alias in node.names:
                if not alias.name.startswith("v"):
                    continue
                target = registry.parent / f"{alias.name}.py"
                relative = target.relative_to(root).as_posix()
                if not target.is_file():
                    failures.add(f"migration:missing:{relative}")
                elif relative not in tracked:
                    failures.add(f"migration:untracked:{relative}")
    for relative in (
        "src/novel_forge/api/routers/book_authority.py",
        "src/novel_forge/storage/book_authority_repositories.py",
    ):
        target = root / relative
        if not target.is_file():
            failures.add(f"required:missing:{relative}")
        elif relative not in tracked:
            failures.add(f"required:untracked:{relative}")
    return failures


def _required_import_failures(
    root: Path, required_imports: Iterable[str]
) -> set[str]:
    failures: set[str] = set()
    if not (root / "src").is_dir():
        return failures
    for module in required_imports:
        try:
            importlib.import_module(module)
        except (ImportError, AttributeError, RuntimeError, ValueError) as exc:
            failures.add(f"{module}:{type(exc).__name__}:{exc}")
    return failures


def _test_collection_failures(root: Path) -> set[str]:
    failures: set[str] = set()
    makefile = (root / "Makefile").read_text(encoding="utf-8") if (root / "Makefile").is_file() else ""
    workflow_path = root / ".github" / "workflows" / "core-os-ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8") if workflow_path.is_file() else ""
    qualification_runner_path = root / "scripts" / "run_p0_backend_qualification.py"
    qualification_runner = (
        qualification_runner_path.read_text(encoding="utf-8")
        if qualification_runner_path.is_file()
        else ""
    )
    runner_path = root / "scripts" / "run_authority_postgres_tests.py"
    runner = runner_path.read_text(encoding="utf-8") if runner_path.is_file() else ""
    if "head-integrity-check:" not in makefile:
        failures.add("Makefile:head-integrity-check")
    try:
        workflow_document = yaml.safe_load(workflow)
        jobs = workflow_document.get("jobs") if isinstance(workflow_document, dict) else None
        workflow_commands = "\n".join(
            str(step.get("run") or "")
            for job in (jobs or {}).values()
            if isinstance(job, dict)
            for step in job.get("steps", [])
            if isinstance(step, dict)
        )
    except (AttributeError, TypeError, yaml.YAMLError) as exc:
        workflow_commands = ""
        failures.add(f"core-os-ci:parse:{type(exc).__name__}")
    try:
        from novel_forge.tools.backend_qualification_contract import (
            QualificationContractError,
            load_qualification_manifest,
        )

        qualification = load_qualification_manifest(root)
    except (QualificationContractError, FileNotFoundError, ValueError) as exc:
        complete_collection_paths: set[str] = set()
        failures.add(
            "backend-qualification-manifest:"
            f"{type(exc).__name__}:{exc}"
        )
    else:
        complete_collection_paths = {
            path
            for contract in qualification.pytest_collections
            if contract.complete_collection and not contract.allow_skips
            for path in contract.paths
        }
        postgres_collections = tuple(
            contract
            for contract in qualification.pytest_collections
            if contract.classification == "POSTGRESQL_REQUIRED"
        )
        if len(postgres_collections) != 1:
            failures.add("postgres-collection:exactly-one-required")
        elif (
            postgres_collections[0].paths != ("tests/integration",)
            or not postgres_collections[0].complete_collection
            or postgres_collections[0].allow_skips
        ):
            failures.add("postgres-collection:complete-integration-required")
    make_match = re.search(
        r"(?m)^p0-backend-qualification:[^\n]*\n(?P<recipe>(?:\t[^\n]*\n?)+)",
        makefile,
    )
    common_entry = bool(
        "make p0-backend-qualification" in workflow_commands
        and make_match is not None
        and "scripts/run_p0_backend_qualification.py"
        in make_match.group("recipe")
        and "from novel_forge.tools.backend_qualification import main"
        in qualification_runner
    )
    for suite in ("tests/unit", "tests/integration", "tests/acceptance"):
        if suite in workflow_commands:
            continue
        if common_entry and suite in complete_collection_paths:
            continue
        failures.add(f"core-os-ci:{suite}")
    if "build_postgres_pytest_command" not in runner:
        failures.add("postgres-runner:canonical-complete-collection-entry")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    report = build_head_integrity_report(args.repo_root)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_REQUIRED_IMPORTS",
    "HeadIntegrityReport",
    "build_head_integrity_report",
    "main",
]
