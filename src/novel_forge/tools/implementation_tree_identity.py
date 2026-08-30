"""INVARIANT: Deterministic identity for files that can change Novel Forge runtime semantics.

The identity is intentionally independent from Git commit ids and from checked-in
or generated evidence documents.  CI binds the resulting digest to ``GITHUB_SHA``
inside a run artifact; the repository only stores the stable selection contract.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "implementation-tree-identity.v1"
ALGORITHM = "sha256-canonical-file-records-v1"

INCLUDED_PREFIXES = (
    "src",
    "tests",
    "scripts",
    "architecture/manifests",
    ".github/workflows",
)
ROOT_FILE_PATTERNS = (
    "compose*.yml",
    "compose*.yaml",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "Dockerfile",
    "Dockerfile.*",
    "Makefile",
    "pyproject.toml",
)
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
    }
)
EXCLUDED_FILE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "coverage.xml",
    "junit*.xml",
    "*.log",
)


def _is_excluded(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info") for part in relative.parts):
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def select_implementation_paths(repo_root: str | Path) -> list[Path]:
    root = Path(repo_root).resolve()
    selected: set[Path] = set()
    for prefix in INCLUDED_PREFIXES:
        base = root / prefix
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if (path.is_file() or path.is_symlink()) and not _is_excluded(path, root):
                selected.add(path)
    if root.is_dir():
        for path in root.iterdir():
            if not (path.is_file() or path.is_symlink()):
                continue
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in ROOT_FILE_PATTERNS):
                if not _is_excluded(path, root):
                    selected.add(path)
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix().encode("utf-8"))


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    if path.is_symlink():
        content = os.readlink(path).encode("utf-8")
        kind = "symlink"
    else:
        content = path.read_bytes()
        kind = "file"
    return {
        "path": relative,
        "kind": kind,
        "size": len(content),
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def build_implementation_tree_identity(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    records = [_file_record(root, path) for path in select_implementation_paths(root)]
    canonical = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "records": records,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "implementation_tree_sha": "sha256:" + hashlib.sha256(encoded).hexdigest(),
        "path_count": len(records),
        "paths": [record["path"] for record in records],
        "scope": {
            "included": [
                "src/**",
                "tests/**",
                "scripts/**",
                "architecture/manifests/**",
                ".github/workflows/**",
                *ROOT_FILE_PATTERNS,
            ],
            "excluded": [
                "docs/**",
                "generated test output",
                "timestamped reports",
                "CI run metadata",
                "build artifacts",
                "temporary files",
                *sorted(EXCLUDED_DIRECTORY_NAMES),
                *EXCLUDED_FILE_PATTERNS,
            ],
        },
        "records": records,
    }


__all__ = [
    "ALGORITHM",
    "EXCLUDED_DIRECTORY_NAMES",
    "EXCLUDED_FILE_PATTERNS",
    "INCLUDED_PREFIXES",
    "ROOT_FILE_PATTERNS",
    "SCHEMA_VERSION",
    "build_implementation_tree_identity",
    "select_implementation_paths",
]
