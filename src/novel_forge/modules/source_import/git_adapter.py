from __future__ import annotations

import hashlib
from pathlib import Path
import re
from threading import Lock
import time
from typing import Any, Iterable

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from novel_forge.modules.production_execution.local_command import (
    BoundedLocalCommandExecutionPort,
    LocalCommandError,
    LocalCommandExecutionPort,
    git_command_environment,
)

from .domain import (
    RepositoryFile,
    SourceImportPolicy,
    binary_reason,
    manifest_hash,
    normalize_repository_url,
)


class GitRepositoryExternalEffectAdapter:
    provider = "git_repository"
    reconciliation_mode = "query"
    production_execution_gateway_backed = True
    capability_profile = {
        "provider": provider,
        "control_level": "V2_CONTROLLED",
        "supports_request_timeout": True,
        "supports_provider_idempotency": True,
        "supports_query": True,
        "supports_cancel": False,
        "supports_callback": False,
        "supports_usage_receipt": False,
        "supports_cost_receipt": False,
        "reconciliation_mode": "query",
        "real_provider_validation_eligible": True,
        "contract_version": "provider-capability-v2",
    }

    def __init__(
        self,
        cache_root: Path,
        *,
        allow_file_repositories: bool = False,
        allowed_file_roots: Iterable[Path] = (),
        timeout_seconds: int = 120,
        execution_port: LocalCommandExecutionPort | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Git adapter timeout must be positive")
        self.cache_root = cache_root.resolve()
        self.allow_file_repositories = allow_file_repositories
        self.allowed_file_roots = tuple(path.resolve() for path in allowed_file_roots)
        self.timeout_seconds = timeout_seconds
        self.execution_port = execution_port or BoundedLocalCommandExecutionPort(
            allowed_executables=("git",),
        )
        self._lock = Lock()

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        if capability != "source.remote.fetch":
            return ProviderResult(
                "final_failure",
                f"git:{stable_idempotency_key}",
                {"error": "unsupported_capability"},
            )
        try:
            result = self._discover(request_payload, fetch=True)
        except ExternalEffectAdapterError:
            raise
        except (OSError, ValueError, LocalCommandError) as exc:
            raise ExternalEffectAdapterError(
                f"Git discovery failed: {type(exc).__name__}: {exc}",
                request_sent=(
                    exc.request_sent if isinstance(exc, LocalCommandError) else False
                ),
            ) from exc
        return ProviderResult(
            "success",
            "git:" + hashlib.sha256(stable_idempotency_key.encode("utf-8")).hexdigest(),
            {**result, "stable_idempotency_key": stable_idempotency_key},
        )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        del capability
        try:
            result = self._discover(request_payload, fetch=False)
        except (OSError, ValueError, LocalCommandError):
            return ProviderResult(
                "not_found",
                f"git-query:{stable_idempotency_key}",
                {"repository_url": str(request_payload.get("repository_url") or "")},
            )
        return ProviderResult(
            "success",
            "git:" + hashlib.sha256(stable_idempotency_key.encode("utf-8")).hexdigest(),
            result,
        )

    def cancel(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
        provider_request_id: str,
    ) -> ProviderResult:
        del capability, request_payload
        return ProviderResult(
            "cancelled",
            provider_request_id or f"git-cancel:{stable_idempotency_key}",
            {"cancelled": False, "reason": "completed Git snapshots are immutable"},
        )

    def read_blob(self, repository_identity: str, object_id: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{40,64}", object_id):
            raise ValueError("Git object identity is invalid")
        mirror = self._mirror(repository_identity)
        return self._run(("git", "--git-dir", str(mirror), "cat-file", "blob", object_id), binary=True)

    def _discover(self, payload: dict[str, Any], *, fetch: bool) -> dict[str, Any]:
        raw_url = str(payload.get("repository_url") or "")
        repository_url = normalize_repository_url(
            raw_url, allow_file=self.allow_file_repositories
        )
        self._assert_file_repository_allowed(repository_url)
        requested_ref = str(payload.get("ref") or "HEAD").strip()
        if not requested_ref or requested_ref.startswith("-") or any(
            character in requested_ref for character in ("\x00", "\n", "\r", " ")
        ):
            raise ValueError("Git ref is invalid")
        policy = SourceImportPolicy(**dict(payload.get("policy") or {}))
        repository_identity = "git-repository:" + hashlib.sha256(
            repository_url.encode("utf-8")
        ).hexdigest()
        mirror = self._mirror(repository_identity)
        with self._lock:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            if not mirror.exists():
                self._run(("git", "init", "--bare", str(mirror)))
                self._run(("git", "--git-dir", str(mirror), "remote", "add", "origin", repository_url))
            else:
                self._run(("git", "--git-dir", str(mirror), "remote", "set-url", "origin", repository_url))
            if fetch:
                self._fetch_with_retry(
                    mirror=mirror,
                    requested_ref=requested_ref,
                    partial=bool(payload.get("partial_fetch", False)),
                )
                commitish = "FETCH_HEAD^{commit}"
            else:
                commitish = (
                    f"{requested_ref}^{{commit}}"
                    if re.fullmatch(r"[0-9a-f]{40}", requested_ref)
                    else "FETCH_HEAD^{commit}"
                )
            resolved = self._run(
                ("git", "--git-dir", str(mirror), "rev-parse", "--verify", commitish)
            ).decode("ascii").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}", resolved):
                raise ValueError("Git ref did not resolve to an exact commit")
            raw_tree = self._run(
                ("git", "--git-dir", str(mirror), "ls-tree", "-r", "-l", "-z", resolved),
                binary=True,
            )
        tree_files = self._parse_tree(raw_tree, policy)
        scoped_files = tuple(
            item
            for item in tree_files
            if item.block_reason not in {"not_included", "excluded_path"}
        )
        files = scoped_files if payload.get("metadata_only") else self._inspect_text_candidates(
            repository_identity,
            scoped_files,
            policy,
        )
        if len(files) > policy.max_files:
            raise ValueError("repository_file_count_policy")
        repository_bytes = sum(max(0, item.size_bytes) for item in files)
        if repository_bytes > policy.max_repository_bytes:
            raise ValueError("repository_size_policy")
        digest = manifest_hash(
            repository_identity=repository_identity,
            resolved_commit_sha=resolved,
            policy_hash=policy.policy_hash,
            files=files,
        )
        return {
            "schema_version": "source-repository-discovery.v1",
            "repository_identity": repository_identity,
            "repository_url": repository_url,
            "requested_ref": requested_ref,
            "resolved_commit_sha": resolved,
            "manifest_hash": digest,
            "import_policy_hash": policy.policy_hash,
            "file_count": len(files),
            "repository_bytes": repository_bytes,
            "files": [
                {
                    "path": item.path,
                    "mode": item.mode,
                    "object_type": item.object_type,
                    "object_id": item.object_id,
                    "size_bytes": item.size_bytes,
                    "eligibility": item.eligibility,
                    "block_reason": item.block_reason,
                    "content_hash": item.content_hash or None,
                }
                for item in files
            ],
            "tree_entry_count": len(tree_files),
            "excluded_tree_entry_count": len(tree_files) - len(scoped_files),
            "license_findings": [] if payload.get("metadata_only") else self._license_findings(
                repository_identity, tree_files
            ),
            "network_access_used": repository_url.startswith("https://"),
            "fixture_protocol_only": repository_url.startswith("file://"),
            "real_model_call": False,
            "production_verified": False,
        }

    def _inspect_text_candidates(
        self,
        repository_identity: str,
        files: tuple[RepositoryFile, ...],
        policy: SourceImportPolicy,
    ) -> tuple[RepositoryFile, ...]:
        inspected: list[RepositoryFile] = []
        for item in files:
            if item.eligibility != "ELIGIBLE":
                inspected.append(item)
                continue
            if item.object_type != "blob" or item.size_bytes > policy.max_file_bytes:
                inspected.append(
                    RepositoryFile(
                        path=item.path,
                        mode=item.mode,
                        object_type=item.object_type,
                        object_id=item.object_id,
                        size_bytes=item.size_bytes,
                        eligibility="BLOCKED",
                        block_reason="unsupported_git_object",
                    )
                )
                continue
            content = self.read_blob(repository_identity, item.object_id)
            reason = binary_reason(content)
            inspected.append(
                RepositoryFile(
                    path=item.path,
                    mode=item.mode,
                    object_type=item.object_type,
                    object_id=item.object_id,
                    size_bytes=item.size_bytes,
                    eligibility="BLOCKED" if reason else "ELIGIBLE",
                    block_reason=reason,
                    content_hash=(
                        "sha256:" + hashlib.sha256(content).hexdigest()
                        if not reason
                        else ""
                    ),
                )
            )
        return tuple(inspected)

    def _license_findings(
        self,
        repository_identity: str,
        files: tuple[RepositoryFile, ...],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for item in files:
            filename = item.path.rsplit("/", 1)[-1].lower()
            if not (
                filename.startswith("license")
                or filename.startswith("copying")
                or filename.startswith("notice")
            ):
                continue
            if item.object_type != "blob" or not 0 <= item.size_bytes <= 1_000_000:
                continue
            content = self.read_blob(repository_identity, item.object_id)
            lowered = content[:200_000].decode("utf-8", errors="ignore").lower()
            identifiers = []
            for marker, identity in (
                ("mit license", "MIT"),
                ("apache license", "Apache-2.0"),
                ("gnu general public license", "GPL"),
                ("creative commons", "Creative-Commons"),
            ):
                if marker in lowered:
                    identifiers.append(identity)
            findings.append(
                {
                    "path": item.path,
                    "object_id": item.object_id,
                    "content_hash": "sha256:" + hashlib.sha256(content).hexdigest(),
                    "detected_identifiers": identifiers,
                    "requires_human_rights_decision": not bool(identifiers),
                }
            )
        return findings

    def _fetch_with_retry(self, *, mirror: Path, requested_ref: str, partial: bool = False) -> None:
        command = (
            "git",
            "--git-dir",
            str(mirror),
            "fetch",
            "--force",
            "--prune",
            "--no-tags",
            *(("--depth=1", "--filter=blob:none") if partial else ()),
            "origin",
            requested_ref,
        )
        last_error: LocalCommandError | None = None
        for attempt in range(3):
            try:
                self._run(command)
                return
            except LocalCommandError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.1 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _parse_tree(self, raw: bytes, policy: SourceImportPolicy) -> tuple[RepositoryFile, ...]:
        files: list[RepositoryFile] = []
        for record in raw.split(b"\x00"):
            if not record:
                continue
            metadata, separator, raw_path = record.partition(b"\t")
            if not separator:
                raise ValueError("invalid_git_tree_record")
            parts = metadata.decode("ascii").split()
            if len(parts) != 4:
                raise ValueError("invalid_git_tree_metadata")
            mode, object_type, object_id, raw_size = parts
            path = raw_path.decode("utf-8", errors="strict")
            size = int(raw_size) if raw_size.isdigit() else -1
            eligibility, reason = policy.path_decision(
                path, mode=mode, object_type=object_type, size=size
            )
            files.append(
                RepositoryFile(
                    path=path,
                    mode=mode,
                    object_type=object_type,
                    object_id=object_id,
                    size_bytes=size,
                    eligibility=eligibility,
                    block_reason="" if eligibility == "ELIGIBLE" else reason,
                )
            )
        return tuple(sorted(files, key=lambda item: item.path))

    def _mirror(self, repository_identity: str) -> Path:
        token = repository_identity.rsplit(":", 1)[-1]
        if not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("repository identity is invalid")
        return self.cache_root / "repositories" / f"{token}.git"

    def _assert_file_repository_allowed(self, repository_url: str) -> None:
        if not repository_url.startswith("file://"):
            return
        path = Path(repository_url.removeprefix("file://")).resolve()
        if not self.allowed_file_roots or not any(
            path == root or root in path.parents for root in self.allowed_file_roots
        ):
            raise ValueError("file repository is outside configured fixture roots")

    def _run(self, command: tuple[str, ...], *, binary: bool = True) -> bytes:
        output = self.execution_port.execute(
            command,
            timeout_seconds=self.timeout_seconds,
            environment=git_command_environment(),
        )
        return output if binary else bytes(output)


__all__ = ["GitRepositoryExternalEffectAdapter"]
