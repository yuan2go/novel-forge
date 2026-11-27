from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import Any, BinaryIO, Iterator
from uuid import uuid4
import zipfile

from .contracts import IngestionBudget, IngestionFailure, safe_relative_path


BLOCK_BYTES = 64 * 1024


def file_identity(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(BLOCK_BYTES), b""):
            digest.update(block)
            size += len(block)
    return "sha256:" + digest.hexdigest(), size


def require_space(root: Path, budget: IngestionBudget, required: int = 0) -> None:
    if shutil.disk_usage(root).free < budget.min_free_disk_bytes + required:
        raise IngestionFailure("INSUFFICIENT_DISK_SPACE")


def checked_local(path: Path, roots: tuple[Path, ...]) -> Path:
    absolute = path.expanduser().absolute()
    root = next(
        (root for root in roots if absolute == root or root in absolute.parents), None
    )
    if root is None or ".." in absolute.parts:
        raise IngestionFailure("LOCAL_ROOT_NOT_ALLOWED")
    canonical_root = root.resolve(strict=True)
    candidate = canonical_root / absolute.relative_to(root)
    for parent in (candidate, *candidate.parents):
        if parent == canonical_root:
            break
        if parent.is_symlink():
            raise IngestionFailure("SYMLINK_FORBIDDEN", str(parent))
    if not candidate.exists():
        raise IngestionFailure("LOCAL_SOURCE_MISSING")
    return candidate


@contextmanager
def stable_local_file(
    path: Path, expected: dict[str, Any] | None = None
) -> Iterator[BinaryIO]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise IngestionFailure("NOT_REGULAR_FILE")
        identity = _stat_identity(before)
        if expected is not None and identity != expected:
            raise IngestionFailure("LOCAL_SOURCE_DRIFT", path.name)
        yield source
        if (
            _stat_identity(os.fstat(source.fileno())) != identity
            or _stat_identity(path.stat(follow_symlinks=False)) != identity
        ):
            raise IngestionFailure("LOCAL_SOURCE_CHANGED_DURING_READ", path.name)


def _stat_identity(value: os.stat_result) -> dict[str, Any]:
    return {
        "device": value.st_dev,
        "inode": value.st_ino,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def local_identity(path: Path) -> dict[str, Any]:
    return _stat_identity(path.stat(follow_symlinks=False))


def spool_bytes(
    source: BinaryIO,
    root: Path,
    budget: IngestionBudget,
    *,
    limit: int,
    expected_hash: str | None = None,
    expected_size: int | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    require_space(root, budget, expected_size or 0)
    temporary = root / (".partial-" + uuid4().hex)
    digest, size = hashlib.sha256(), 0
    try:
        with temporary.open("xb") as target:
            for block in iter(lambda: source.read(BLOCK_BYTES), b""):
                size += len(block)
                if size > limit:
                    raise IngestionFailure("BYTE_BUDGET_EXCEEDED")
                require_space(root, budget, len(block))
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        actual = "sha256:" + digest.hexdigest()
        if expected_hash and expected_hash != actual:
            raise IngestionFailure("CHECKSUM_MISMATCH")
        if expected_size is not None and size != expected_size:
            raise IngestionFailure("SIZE_MISMATCH")
        destination = root / digest.hexdigest()
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if file_identity(destination) != (actual, size):
                raise IngestionFailure("IMMUTABLE_CACHE_CONFLICT") from None
        return {"checksum": actual, "size_bytes": size, "cache_path": str(destination)}
    finally:
        temporary.unlink(missing_ok=True)


def atomic_receipt(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as target:
            json.dump(value, target, ensure_ascii=False, sort_keys=True)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def expand_container(
    path: Path, locator: str, root: Path, budget: IngestionBudget
) -> Iterator[dict[str, Any]]:
    seen: set[str] = set()
    expanded = 0

    def check(name: str, size: int, compressed: int) -> str:
        nonlocal expanded
        name = safe_relative_path(name)
        if name in seen:
            raise IngestionFailure("DUPLICATE_ARCHIVE_MEMBER", name)
        seen.add(name)
        expanded += size
        if (
            len(seen) > budget.max_files
            or size > budget.max_file_bytes
            or expanded > budget.max_expanded_bytes
        ):
            raise IngestionFailure("ARCHIVE_BUDGET_EXCEEDED")
        if size > max(1, compressed) * budget.max_archive_ratio:
            raise IngestionFailure("ARCHIVE_EXPANSION_RATIO")
        return name

    if locator.lower().endswith(".zip"):
        if path.stat().st_size > budget.memory_bytes // 16:
            raise IngestionFailure("ZIP_CENTRAL_DIRECTORY_MEMORY_LIMIT")
        with zipfile.ZipFile(path) as archive:
            for index, item in enumerate(archive.infolist(), 1):
                if index > budget.max_files * 2:
                    raise IngestionFailure("ARCHIVE_ENTRY_LIMIT")
                safe_relative_path(item.filename.rstrip("/"))
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or item.flag_bits & 1:
                    raise IngestionFailure("ARCHIVE_LINK_OR_ENCRYPTION_FORBIDDEN")
                if item.is_dir():
                    continue
                name = check(item.filename, item.file_size, item.compress_size)
                with archive.open(item) as content:
                    result = spool_bytes(
                        content,
                        root,
                        budget,
                        limit=item.file_size,
                        expected_size=item.file_size,
                    )
                yield {
                    **result,
                    "path": name,
                    "container_path": locator,
                    "offset_kind": "ARCHIVE_MEMBER",
                    "original_byte_offset": None,
                }
    else:
        with tarfile.open(path, mode="r|*") as archive:
            for index, item in enumerate(archive, 1):
                if index > budget.max_files * 2:
                    raise IngestionFailure("ARCHIVE_ENTRY_LIMIT")
                safe_relative_path(item.name.rstrip("/"))
                if item.isdir():
                    continue
                if not item.isfile() or item.issparse():
                    raise IngestionFailure("ARCHIVE_SPECIAL_FILE_FORBIDDEN")
                name = check(item.name, item.size, path.stat().st_size)
                if expanded > max(1, path.stat().st_size) * budget.max_archive_ratio:
                    raise IngestionFailure("ARCHIVE_EXPANSION_RATIO")
                content = archive.extractfile(item)
                if content is None:
                    raise IngestionFailure("ARCHIVE_MEMBER_UNREADABLE")
                with content:
                    result = spool_bytes(
                        content, root, budget, limit=item.size, expected_size=item.size
                    )
                yield {
                    **result,
                    "path": name,
                    "container_path": locator,
                    "offset_kind": "ARCHIVE_MEMBER",
                    "original_byte_offset": None,
                }


def spool_json(value: Any, root: Path, budget: IngestionBudget) -> dict[str, Any]:
    content = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return spool_bytes(io.BytesIO(content), root, budget, limit=budget.max_work_bytes)
