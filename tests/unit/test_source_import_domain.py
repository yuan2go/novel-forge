from __future__ import annotations

import hashlib
import json

import pytest

from novel_forge.modules.source_import.domain import (
    RepositoryFile,
    SourceImportPolicy,
    binary_reason,
    chunk_normalized_text,
    diff_repository_manifests,
    manifest_hash,
    normalize_repository_url,
    normalize_source_bytes,
)


def _file(path: str, oid: str, *, eligibility: str = "ELIGIBLE") -> RepositoryFile:
    return RepositoryFile(
        path=path,
        mode="100644",
        object_type="blob",
        object_id=oid,
        size_bytes=10,
        eligibility=eligibility,
        block_reason="extension_policy" if eligibility == "BLOCKED" else "",
    )


def test_github_repository_url_is_canonical_and_rejects_credentials() -> None:
    assert (
        normalize_repository_url("https://github.com/Yuan2Go/Novel-Forge")
        == "https://github.com/yuan2go/novel-forge.git"
    )
    with pytest.raises(ValueError, match="credentials"):
        normalize_repository_url("https://token@github.com/yuan2go/novel-forge")
    with pytest.raises(ValueError, match="host"):
        normalize_repository_url("https://example.com/yuan2go/novel-forge")


def test_policy_blocks_submodule_symlink_extension_and_large_file() -> None:
    policy = SourceImportPolicy(max_file_bytes=1024, max_repository_bytes=2048)
    assert policy.path_decision("book/a.md", mode="100644", object_type="blob", size=8)[0] == "ELIGIBLE"
    assert policy.path_decision("book/a.py", mode="100644", object_type="blob", size=8) == ("BLOCKED", "extension_policy")
    assert policy.path_decision("book/a.md", mode="120000", object_type="blob", size=8) == ("BLOCKED", "symlink_policy")
    assert policy.path_decision("vendor", mode="160000", object_type="commit", size=-1) == ("BLOCKED", "submodule_policy")
    assert policy.path_decision("book/a.md", mode="100644", object_type="blob", size=1025) == ("BLOCKED", "file_size_policy")


def test_manifest_diff_handles_unchanged_modified_rename_removed_and_blocked() -> None:
    previous = (
        _file("same.md", "1" * 40),
        _file("modified.md", "2" * 40),
        _file("old-name.md", "3" * 40),
        _file("removed.md", "4" * 40),
    )
    current = (
        _file("same.md", "1" * 40),
        _file("modified.md", "5" * 40),
        _file("new-name.md", "3" * 40),
        _file("blocked.bin", "6" * 40, eligibility="BLOCKED"),
    )
    states = {item.path: item for item in diff_repository_manifests(previous, current)}
    assert states["same.md"].state == "UNCHANGED"
    assert states["modified.md"].state == "MODIFIED"
    assert states["new-name.md"].state == "RENAMED_SAME_CONTENT"
    assert states["new-name.md"].previous_path == "old-name.md"
    assert states["removed.md"].state == "REMOVED"
    assert states["blocked.bin"].state == "BLOCKED"


def test_manifest_diff_of_one_hundred_files_selects_only_three_changes() -> None:
    previous = tuple(
        _file(f"chapter-{index:03d}.md", f"{index:040x}")
        for index in range(100)
    )
    current = tuple(
        _file(
            f"chapter-{index:03d}.md",
            (f"{index + 1000:040x}" if index in {7, 41, 88} else f"{index:040x}"),
        )
        for index in range(100)
    )
    states = [item.state for item in diff_repository_manifests(previous, current)]
    assert states.count("UNCHANGED") == 97
    assert states.count("MODIFIED") == 3
    assert len(states) == 100


def test_normalization_supports_utf8_bom_gb18030_json_and_stable_chunks() -> None:
    bom = normalize_source_bytes("# 标题\r\n第一段。\r\n".encode("utf-8-sig"), path="book.md")
    gb = normalize_source_bytes("第一章\r\n中文内容。".encode("gb18030"), path="book.txt")
    structured = normalize_source_bytes(
        json.dumps({"z": 1, "a": "值"}, ensure_ascii=False).encode(),
        path="rules.json",
    )
    assert bom.encoding == "utf-8-sig"
    assert bom.text == "# 标题\n第一段。\n"
    assert gb.encoding == "gb18030"
    assert structured.text.startswith('{\n  "a": "值"')
    chunks = chunk_normalized_text(gb, max_chunk_bytes=256)
    assert b"".join(item.content for item in chunks) == gb.text.encode()
    assert chunks[0].normalized_byte_start == 0
    assert chunks[-1].normalized_byte_end == gb.byte_size


def test_binary_and_lfs_are_blocked_and_manifest_requires_exact_commit() -> None:
    assert binary_reason(b"a\x00b") == "binary_nul"
    assert binary_reason(b"version https://git-lfs.github.com/spec/v1\noid sha256:x\n") == "git_lfs_pointer"
    policy = SourceImportPolicy()
    row = _file("a.md", "a" * 40)
    digest = manifest_hash(
        repository_identity="git-repository:test",
        resolved_commit_sha="b" * 40,
        policy_hash=policy.policy_hash,
        files=(row,),
    )
    assert digest == "sha256:" + hashlib.sha256(
        json.dumps(
            {
                "repository_identity": "git-repository:test",
                "resolved_commit_sha": "b" * 40,
                "policy_hash": policy.policy_hash,
                "files": [
                    {
                        "path": "a.md",
                        "mode": "100644",
                        "object_type": "blob",
                        "object_id": "a" * 40,
                        "size_bytes": 10,
                        "eligibility": "ELIGIBLE",
                        "block_reason": "",
                        "content_hash": "",
                    }
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with pytest.raises(ValueError, match="exact commit"):
        manifest_hash(
            repository_identity="git-repository:test",
            resolved_commit_sha="main",
            policy_hash=policy.policy_hash,
            files=(row,),
        )
