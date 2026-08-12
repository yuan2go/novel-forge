from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from novel_forge.modules.source_import import GitRepositoryExternalEffectAdapter


def _git(path: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(path), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def test_git_adapter_pins_commit_discovers_policy_and_reads_blob(tmp_path: Path) -> None:
    repository = tmp_path / "fixture-repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Novel Forge Test")
    _git(repository, "config", "user.email", "test@novel-forge.invalid")
    (repository / "chapter.md").write_text("# 第一章\n内容。\n", encoding="utf-8")
    (repository / "binary.bin").write_bytes(b"a\x00b")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial")
    commit = _git(repository, "rev-parse", "HEAD")
    adapter = GitRepositoryExternalEffectAdapter(
        tmp_path / "cache",
        allow_file_repositories=True,
        allowed_file_roots=(tmp_path,),
    )

    result = adapter.execute(
        stable_idempotency_key="fixture:initial",
        capability="source.remote.fetch",
        request_payload={
            "repository_url": repository.as_uri(),
            "ref": "HEAD",
            "policy": {},
        },
    )

    assert result.outcome == "success"
    assert result.evidence["resolved_commit_sha"] == commit
    assert result.evidence["fixture_protocol_only"] is True
    rows = {row["path"]: row for row in result.evidence["files"]}
    assert rows["chapter.md"]["eligibility"] == "ELIGIBLE"
    assert rows["binary.bin"]["block_reason"] == "extension_policy"
    content = adapter.read_blob(
        str(result.evidence["repository_identity"]), rows["chapter.md"]["object_id"]
    )
    assert "第一章" in content.decode()
    assert hashlib.sha256(content).hexdigest()


def test_git_adapter_new_commit_manifest_changes_without_mutating_old_snapshot(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Novel Forge Test")
    _git(repository, "config", "user.email", "test@novel-forge.invalid")
    (repository / "a.txt").write_text("A\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "a")
    adapter = GitRepositoryExternalEffectAdapter(
        tmp_path / "cache",
        allow_file_repositories=True,
        allowed_file_roots=(tmp_path,),
    )
    first = adapter.execute(
        stable_idempotency_key="first",
        capability="source.remote.fetch",
        request_payload={"repository_url": repository.as_uri(), "ref": "HEAD", "policy": {}},
    )
    (repository / "a.txt").rename(repository / "renamed.txt")
    (repository / "b.txt").write_text("B\n", encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-m", "b")
    second = adapter.execute(
        stable_idempotency_key="second",
        capability="source.remote.fetch",
        request_payload={"repository_url": repository.as_uri(), "ref": "HEAD", "policy": {}},
    )
    assert first.evidence["resolved_commit_sha"] != second.evidence["resolved_commit_sha"]
    assert first.evidence["manifest_hash"] != second.evidence["manifest_hash"]
    assert {row["path"] for row in first.evidence["files"]} == {"a.txt"}
    assert {row["path"] for row in second.evidence["files"]} == {"b.txt", "renamed.txt"}
