"""INVARIANT: implementation identity excludes Git ids and generated evidence so CI can bind stable content identity to a tested commit."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any


SCHEMA_VERSION = "implementation-tree-identity.v2"
ALGORITHM = "sha256-canonical-file-records-v1"

INCLUDED_PREFIXES = (
    "src",
    "tests",
    "scripts",
    "config",
    "skills",
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
    if any(
        part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info")
        for part in relative.parts
    ):
        return True
    return any(
        fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_FILE_PATTERNS
    )


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
            if any(
                fnmatch.fnmatch(path.name, pattern) for pattern in ROOT_FILE_PATTERNS
            ):
                if not _is_excluded(path, root):
                    selected.add(path)
    return sorted(
        selected, key=lambda path: path.relative_to(root).as_posix().encode("utf-8")
    )


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


def _build_identity(records: list[dict[str, Any]]) -> dict[str, Any]:
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
                "config/**",
                "skills/**",
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


def build_implementation_tree_identity(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    records = [_file_record(root, path) for path in select_implementation_paths(root)]
    return _build_identity(records)


def _select_git_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    if any(
        part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info")
        for part in path.parts
    ):
        return False
    if any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_FILE_PATTERNS):
        return False
    if any(relative == prefix or relative.startswith(prefix + "/") for prefix in INCLUDED_PREFIXES):
        return True
    return len(path.parts) == 1 and any(
        fnmatch.fnmatch(path.name, pattern) for pattern in ROOT_FILE_PATTERNS
    )


def build_git_implementation_tree_identity(
    repo_root: str | Path,
    commit_sha: str,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError("historical implementation identity requires a full Git SHA")
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--full-tree", commit_sha],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if tree.returncode != 0:
        raise ValueError("cannot read the observed Git implementation tree")
    selected: list[tuple[str, str, bytes]] = []
    for raw_entry in tree.stdout.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
            relative = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("observed Git tree contains an invalid entry") from exc
        if object_type != b"blob" or not _select_git_path(relative):
            continue
        kind = "symlink" if mode == b"120000" else "file"
        selected.append((relative, kind, object_id))
    selected.sort(key=lambda item: item[0].encode("utf-8"))

    object_ids = list(dict.fromkeys(item[2] for item in selected))
    blobs = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=b"".join(object_id + b"\n" for object_id in object_ids),
        check=False,
        capture_output=True,
        timeout=30,
    )
    if blobs.returncode != 0:
        raise ValueError("cannot read blobs from the observed Git implementation tree")
    content_by_id: dict[bytes, bytes] = {}
    offset = 0
    for requested_id in object_ids:
        header_end = blobs.stdout.find(b"\n", offset)
        if header_end < 0:
            raise ValueError("observed Git blob batch is truncated")
        header = blobs.stdout[offset:header_end].split(b" ")
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("observed Git object is not a blob")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise ValueError("observed Git blob size is invalid") from exc
        start = header_end + 1
        end = start + size
        if end >= len(blobs.stdout) or blobs.stdout[end : end + 1] != b"\n":
            raise ValueError("observed Git blob content is truncated")
        content_by_id[requested_id] = blobs.stdout[start:end]
        offset = end + 1
    if offset != len(blobs.stdout):
        raise ValueError("observed Git blob batch has trailing data")

    records = []
    for relative, kind, object_id in selected:
        content = content_by_id[object_id]
        records.append(
            {
                "path": relative,
                "kind": kind,
                "size": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return _build_identity(records)


__all__ = [
    "ALGORITHM",
    "EXCLUDED_DIRECTORY_NAMES",
    "EXCLUDED_FILE_PATTERNS",
    "INCLUDED_PREFIXES",
    "ROOT_FILE_PATTERNS",
    "SCHEMA_VERSION",
    "build_git_implementation_tree_identity",
    "build_implementation_tree_identity",
    "select_implementation_paths",
]
