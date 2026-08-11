"""Pure identities, policies, normalization, chunking, and manifest diff rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fnmatch import fnmatch
import hashlib
import json
import math
import re
import unicodedata
from urllib.parse import unquote, urlsplit
from typing import Any, Iterable


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
_HEADING = re.compile(
    r"^(?:#{1,6}\s+|第[零一二三四五六七八九十百千万0-9]+[章节卷部回]\b)",
    re.IGNORECASE,
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceImportPolicy:
    policy_version: str = "source-import-policy.v1"
    include_globs: tuple[str, ...] = ("**/*", "*")
    exclude_globs: tuple[str, ...] = (
        ".git/**",
        "**/.git/**",
        "node_modules/**",
        "**/node_modules/**",
        "**/__pycache__/**",
    )
    extension_allowlist: tuple[str, ...] = (
        ".txt",
        ".text",
        ".md",
        ".markdown",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
    )
    max_file_bytes: int = 8_000_000
    max_repository_bytes: int = 500_000_000
    max_files: int = 20_000
    max_chunk_bytes: int = 12_000
    allow_symlinks: bool = False
    allow_submodules: bool = False
    allow_git_lfs: bool = False
    normalization_version: str = "source-normalization.v1"
    chunking_version: str = "source-structural-chunking.v1"
    analysis_profile: str = "writing_theory"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]+\.v[0-9]+", self.policy_version):
            raise ValueError("Source import policy_version is invalid")
        if not self.include_globs or not self.extension_allowlist:
            raise ValueError("Source import policy requires include and extension rules")
        if min(
            self.max_file_bytes,
            self.max_repository_bytes,
            self.max_files,
            self.max_chunk_bytes,
        ) <= 0:
            raise ValueError("Source import limits must be positive")
        if self.max_file_bytes > self.max_repository_bytes:
            raise ValueError("file limit cannot exceed repository limit")
        if self.allow_symlinks or self.allow_submodules or self.allow_git_lfs:
            raise ValueError(
                "symlink, submodule, and Git LFS import are not production-enabled"
            )
        object.__setattr__(
            self,
            "extension_allowlist",
            tuple(sorted({item.lower() for item in self.extension_allowlist})),
        )

    @property
    def policy_hash(self) -> str:
        return _canonical_hash(asdict(self))

    @property
    def chunking_policy_hash(self) -> str:
        return _canonical_hash(
            {
                "chunking_version": self.chunking_version,
                "max_chunk_bytes": self.max_chunk_bytes,
                "structure": "heading-paragraph-preserving",
                "token_estimator": "unicode-weighted-v1",
            }
        )

    def path_decision(self, path: str, *, mode: str, object_type: str, size: int) -> tuple[str, str]:
        normalized = path.replace("\\", "/").lstrip("/")
        if not normalized or ".." in normalized.split("/"):
            return "BLOCKED", "unsafe_path"
        if object_type == "commit" or mode == "160000":
            return (
                ("ELIGIBLE", "submodule_allowed")
                if self.allow_submodules
                else ("BLOCKED", "submodule_policy")
            )
        if mode == "120000":
            return (
                ("ELIGIBLE", "symlink_allowed")
                if self.allow_symlinks
                else ("BLOCKED", "symlink_policy")
            )
        if object_type != "blob":
            return "BLOCKED", "unsupported_git_object"
        if any(fnmatch(normalized, pattern) for pattern in self.exclude_globs):
            return "BLOCKED", "excluded_path"
        if not any(fnmatch(normalized, pattern) for pattern in self.include_globs):
            return "BLOCKED", "not_included"
        suffix = "." + normalized.rsplit(".", 1)[-1].lower() if "." in normalized.rsplit("/", 1)[-1] else ""
        if suffix not in self.extension_allowlist:
            return "BLOCKED", "extension_policy"
        if size < 0:
            return "BLOCKED", "unknown_size"
        if size > self.max_file_bytes:
            return "BLOCKED", "file_size_policy"
        return "ELIGIBLE", "eligible_text_candidate"


@dataclass(frozen=True, slots=True)
class RepositoryFile:
    path: str
    mode: str
    object_type: str
    object_id: str
    size_bytes: int
    eligibility: str
    block_reason: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.path or not self.mode or not self.object_type or not self.object_id:
            raise ValueError("repository file identity is incomplete")
        if self.eligibility not in {"ELIGIBLE", "BLOCKED"}:
            raise ValueError("repository file eligibility is invalid")
        if self.eligibility == "BLOCKED" and not self.block_reason:
            raise ValueError("blocked repository file requires a reason")
        if self.content_hash and not _SHA256.fullmatch(self.content_hash):
            raise ValueError("repository file content_hash is invalid")

    @property
    def identity(self) -> str:
        return _canonical_hash(
            {
                "path": self.path,
                "mode": self.mode,
                "object_type": self.object_type,
                "object_id": self.object_id,
                "size_bytes": self.size_bytes,
                "eligibility": self.eligibility,
                "block_reason": self.block_reason,
            }
        )


@dataclass(frozen=True, slots=True)
class ManifestDiffEntry:
    path: str
    state: str
    current_object_id: str = ""
    previous_path: str = ""
    previous_object_id: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.state not in {
            "UNCHANGED",
            "ADDED",
            "MODIFIED",
            "REMOVED",
            "RENAMED_SAME_CONTENT",
            "BLOCKED",
        }:
            raise ValueError("repository manifest diff state is invalid")


@dataclass(frozen=True, slots=True)
class NormalizedSource:
    text: str
    encoding: str
    media_type: str
    source_format: str
    normalization_version: str
    content_hash: str
    byte_size: int
    character_count: int
    structural_markers: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class NormalizedChunk:
    chunk_index: int
    content: bytes
    content_hash: str
    byte_size: int
    character_count: int
    token_count: int
    normalized_byte_start: int
    normalized_byte_end: int
    structural_label: str


def normalize_repository_url(value: str, *, allow_file: bool = False) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("repository URL cannot contain credentials, query, or fragment")
    if parsed.scheme == "https":
        if (parsed.hostname or "").lower() != "github.com":
            raise ValueError("GitHub repository host must be github.com")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2:
            raise ValueError("GitHub repository URL must contain owner and repository")
        owner, repository = parts
        repository = repository.removesuffix(".git")
        if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", item) for item in (owner, repository)):
            raise ValueError("GitHub repository owner or name is invalid")
        return f"https://github.com/{owner.lower()}/{repository.lower()}.git"
    if parsed.scheme == "file" and allow_file:
        path = unquote(parsed.path)
        if not path.startswith("/"):
            raise ValueError("file repository URL must be absolute")
        return "file://" + path.rstrip("/")
    raise ValueError("only governed GitHub repository URLs are supported")


def manifest_hash(
    *,
    repository_identity: str,
    resolved_commit_sha: str,
    policy_hash: str,
    files: Iterable[RepositoryFile],
) -> str:
    if not _COMMIT_SHA.fullmatch(resolved_commit_sha):
        raise ValueError("repository snapshot requires an exact commit SHA")
    if not _SHA256.fullmatch(policy_hash):
        raise ValueError("repository snapshot requires a policy hash")
    return _canonical_hash(
        {
            "repository_identity": repository_identity,
            "resolved_commit_sha": resolved_commit_sha,
            "policy_hash": policy_hash,
            "files": [asdict(item) for item in sorted(files, key=lambda row: row.path)],
        }
    )


def diff_repository_manifests(
    previous: Iterable[RepositoryFile], current: Iterable[RepositoryFile]
) -> tuple[ManifestDiffEntry, ...]:
    old = {item.path: item for item in previous}
    new = {item.path: item for item in current}
    removed = {path: item for path, item in old.items() if path not in new}
    removed_by_oid: dict[str, list[tuple[str, RepositoryFile]]] = {}
    for path, item in removed.items():
        removed_by_oid.setdefault(item.object_id, []).append((path, item))
    consumed_removed: set[str] = set()
    result: list[ManifestDiffEntry] = []
    for path, item in sorted(new.items()):
        prior = old.get(path)
        if item.eligibility == "BLOCKED":
            result.append(
                ManifestDiffEntry(
                    path,
                    "BLOCKED",
                    item.object_id,
                    previous_object_id=prior.object_id if prior else "",
                    reason=item.block_reason,
                )
            )
        elif prior and prior.object_id == item.object_id and prior.mode == item.mode:
            result.append(
                ManifestDiffEntry(path, "UNCHANGED", item.object_id, path, prior.object_id)
            )
        elif prior:
            result.append(
                ManifestDiffEntry(path, "MODIFIED", item.object_id, path, prior.object_id)
            )
        else:
            candidates = [row for row in removed_by_oid.get(item.object_id, []) if row[0] not in consumed_removed]
            if candidates:
                previous_path, previous_item = sorted(candidates, key=lambda row: row[0])[0]
                consumed_removed.add(previous_path)
                result.append(
                    ManifestDiffEntry(
                        path,
                        "RENAMED_SAME_CONTENT",
                        item.object_id,
                        previous_path,
                        previous_item.object_id,
                    )
                )
            else:
                result.append(ManifestDiffEntry(path, "ADDED", item.object_id))
    for path, item in sorted(removed.items()):
        if path not in consumed_removed:
            result.append(
                ManifestDiffEntry(
                    path,
                    "REMOVED",
                    previous_path=path,
                    previous_object_id=item.object_id,
                )
            )
    return tuple(result)


def binary_reason(data: bytes) -> str:
    if not data:
        return "empty_file"
    if data.startswith(_LFS_PREFIX):
        return "git_lfs_pointer"
    sample = data[:8192]
    if b"\x00" in sample:
        return "binary_nul"
    control = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    if control / len(sample) > 0.02:
        return "binary_control_ratio"
    return ""


def normalize_source_bytes(
    data: bytes,
    *,
    path: str,
    normalization_version: str = "source-normalization.v1",
) -> NormalizedSource:
    reason = binary_reason(data)
    if reason:
        raise ValueError(reason)
    text = ""
    encoding = ""
    for candidate in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = data.decode(candidate, errors="strict")
        except UnicodeDecodeError:
            continue
        encoding = candidate
        break
    if not encoding:
        raise ValueError("unsupported_text_encoding")
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
    source_format = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".json": "json",
        ".jsonl": "jsonl",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(suffix, "text")
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if source_format == "json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid_json_text") from exc
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    elif source_format == "jsonl":
        normalized_rows: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid_jsonl_text") from exc
            normalized_rows.append(
                json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
        text = "\n".join(normalized_rows)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n") + "\n"
    if not text.strip():
        raise ValueError("empty_normalized_text")
    encoded = text.encode("utf-8")
    markers = tuple(
        {"line": index, "label": line.lstrip("# ").strip()[:160]}
        for index, line in enumerate(text.splitlines(), start=1)
        if _HEADING.match(line.strip())
    )
    return NormalizedSource(
        text=text,
        encoding=encoding,
        media_type={"markdown": "text/markdown", "json": "application/json", "jsonl": "application/x-ndjson", "yaml": "application/yaml"}.get(source_format, "text/plain"),
        source_format=source_format,
        normalization_version=normalization_version,
        content_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
        byte_size=len(encoded),
        character_count=len(text),
        structural_markers=markers,
    )


def chunk_normalized_text(
    normalized: NormalizedSource, *, max_chunk_bytes: int
) -> tuple[NormalizedChunk, ...]:
    if max_chunk_bytes < 256:
        raise ValueError("max_chunk_bytes is too small")
    blocks = _structural_blocks(normalized.text)
    pieces: list[str] = []
    current = ""
    for block in blocks:
        if len((current + block).encode("utf-8")) <= max_chunk_bytes:
            current += block
            continue
        if current:
            pieces.append(current)
            current = ""
        for segment in _split_by_utf8_bytes(block, max_chunk_bytes):
            if len(segment.encode("utf-8")) == max_chunk_bytes:
                pieces.append(segment)
            elif not current:
                current = segment
            elif len((current + segment).encode("utf-8")) <= max_chunk_bytes:
                current += segment
            else:
                pieces.append(current)
                current = segment
    if current:
        pieces.append(current)
    if "".join(pieces) != normalized.text:
        raise RuntimeError("chunking changed normalized content")
    chunks: list[NormalizedChunk] = []
    offset = 0
    for index, piece in enumerate(pieces):
        content = piece.encode("utf-8")
        if not content:
            continue
        first_line = next((line.strip() for line in piece.splitlines() if line.strip()), "")
        label = first_line.lstrip("# ")[:160] if _HEADING.match(first_line) else f"segment-{index + 1}"
        chunks.append(
            NormalizedChunk(
                chunk_index=index,
                content=content,
                content_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                byte_size=len(content),
                character_count=len(piece),
                token_count=_estimate_tokens(piece),
                normalized_byte_start=offset,
                normalized_byte_end=offset + len(content),
                structural_label=label,
            )
        )
        offset += len(content)
    if not chunks or offset != normalized.byte_size:
        raise RuntimeError("chunk manifest does not cover normalized content")
    return tuple(chunks)


def _structural_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    blocks: list[str] = []
    current = ""
    for line in lines:
        stripped = line.strip()
        if current and _HEADING.match(stripped):
            blocks.append(current)
            current = ""
        current += line
        if not stripped:
            blocks.append(current)
            current = ""
    if current:
        blocks.append(current)
    return blocks


def _split_by_utf8_bytes(text: str, limit: int) -> list[str]:
    if len(text.encode("utf-8")) <= limit:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        low, high = start + 1, len(text)
        best = low
        while low <= high:
            middle = (low + high) // 2
            if len(text[start:middle].encode("utf-8")) <= limit:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        split = best
        window = text[start:best]
        boundary = max(window.rfind("\n"), window.rfind("。"), window.rfind("；"))
        if boundary >= max(1, len(window) // 2):
            split = start + boundary + 1
        pieces.append(text[start:split])
        start = split
    return pieces


def _estimate_tokens(text: str) -> int:
    cjk = sum("\u3400" <= character <= "\u9fff" for character in text)
    other = max(0, len(text) - cjk)
    return max(1, cjk + math.ceil(other / 4))


__all__ = [
    "ManifestDiffEntry",
    "NormalizedChunk",
    "NormalizedSource",
    "RepositoryFile",
    "SourceImportPolicy",
    "binary_reason",
    "chunk_normalized_text",
    "diff_repository_manifests",
    "manifest_hash",
    "normalize_repository_url",
    "normalize_source_bytes",
]
