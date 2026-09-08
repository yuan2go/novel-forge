from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from fnmatch import fnmatch
import fcntl
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from novel_forge.modules.command_kernel.external_effect_adapters import ProviderResult
from novel_forge.modules.source_authority.corpus import corpus_hash
from novel_forge.modules.source_import.domain import SourceImportPolicy
from novel_forge.modules.source_import.git_adapter import (
    GitRepositoryExternalEffectAdapter,
)

from .contracts import IngestionFailure, IngestionFile, IngestionManifest
from .http_transport import CorpusHttpTransport
from .safety import (
    atomic_receipt,
    checked_local,
    expand_container,
    file_identity,
    local_identity,
    spool_bytes,
    stable_local_file,
)


class CorpusAcquisitionAdapter:
    provider = "corpus_acquisition"
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
        "real_provider_validation_eligible": False,
        "contract_version": "provider-capability-v2",
    }

    def __init__(
        self,
        root: Path,
        *,
        local_roots: tuple[Path, ...],
        git_adapter: GitRepositoryExternalEffectAdapter,
        http: CorpusHttpTransport | None = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.local_roots = tuple(
            dict.fromkeys(
                candidate
                for path in local_roots
                for candidate in (
                    path.expanduser().absolute(),
                    path.expanduser().resolve(),
                )
            )
        )
        self.git = git_adapter
        self.http = http or CorpusHttpTransport()

    def _receipt_path(self, key: str) -> Path:
        return (
            self.root
            / "receipts"
            / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        )

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
                stable_idempotency_key,
                {"error": "unsupported_capability"},
            )
        manifest = IngestionManifest.model_validate(request_payload["manifest"])
        mode = str(request_payload["mode"])
        path = self._receipt_path(stable_idempotency_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            existing = self.query(
                stable_idempotency_key=stable_idempotency_key,
                capability=capability,
                request_payload=request_payload,
            )
            if existing.outcome != "not_found":
                return existing
            for attempt in range(manifest.budget.max_retries + 1):
                try:
                    selected, source_evidence = self._discover(manifest)
                    files = (
                        self._acquire(manifest, selected)
                        if mode == "IMPORT"
                        else selected
                    )
                    identity = corpus_hash(
                        {
                            "manifest": manifest.identity,
                            "source": source_evidence,
                            "files": [
                                {
                                    key: value
                                    for key, value in item.items()
                                    if key != "cache_path"
                                }
                                for item in files
                            ],
                        }
                    )
                    receipt = {
                        "schema_version": "corpus-acquisition-receipt.v1",
                        "manifest_hash": manifest.identity,
                        "mode": mode,
                        "acquisition_identity": identity,
                        "source": source_evidence,
                        "files": files,
                        "actual_bytes": sum(item.get("size_bytes", 0) for item in files)
                        if mode == "IMPORT"
                        else 0,
                        "file_count": len(files),
                        "acquired_at": datetime.now(timezone.utc).isoformat(),
                        "network_access": manifest.source.kind != "LOCAL",
                        "content_verified": mode == "IMPORT",
                        "analysis_called": False,
                        "provider_model_calls": 0,
                        "acquisition_attempt": attempt + 1,
                        "safe_retake": "FULL_VERIFIED_GET_AFTER_KNOWN_5XX_ONLY",
                    }
                    atomic_receipt(path, receipt)
                    return ProviderResult(
                        "success", "corpus:" + identity.removeprefix("sha256:"), receipt
                    )
                except (ValueError, OSError) as exc:
                    failure = {
                        "schema_version": "corpus-acquisition-failure.v1",
                        "manifest_hash": manifest.identity,
                        "mode": mode,
                        "error_code": getattr(exc, "reason", type(exc).__name__),
                        "error": str(exc)[:1000],
                        "content_verified": False,
                    }
                    atomic_receipt(
                        path.with_name(path.stem + f".attempt-{attempt}.failed.json"),
                        failure,
                    )
                    if (
                        getattr(exc, "reason", "") == "REMOTE_HTTP_FAILURE"
                        and str(exc).rsplit(": ", 1)[-1] in {"502", "503", "504"}
                        and attempt < manifest.budget.max_retries
                    ):
                        continue
                    return ProviderResult(
                        "final_failure", "corpus-failed:" + manifest.identity, failure
                    )

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        del capability
        path = self._receipt_path(stable_idempotency_key)
        if not path.exists():
            return ProviderResult(
                "not_found",
                stable_idempotency_key,
                {
                    "reason": "no_confirmed_acquisition_receipt",
                    "safe_retake_requires_new_effect": True,
                },
            )
        receipt = json.loads(path.read_text())
        expected = IngestionManifest.model_validate(request_payload["manifest"])
        if (
            receipt["manifest_hash"] != expected.identity
            or receipt["mode"] != request_payload["mode"]
        ):
            return ProviderResult(
                "final_failure",
                stable_idempotency_key,
                {"error": "frozen_acquisition_conflict"},
            )
        for item in receipt["files"]:
            if receipt["content_verified"] and file_identity(
                Path(item["cache_path"])
            ) != (item["checksum"], item["size_bytes"]):
                return ProviderResult(
                    "final_failure",
                    stable_idempotency_key,
                    {"error": "acquisition_cache_identity_conflict"},
                )
        return ProviderResult(
            "success",
            "corpus:" + receipt["acquisition_identity"].removeprefix("sha256:"),
            receipt,
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
            provider_request_id or stable_idempotency_key,
            {
                "cancelled": False,
                "reason": "verified acquisitions are immutable; cancelled operations cannot commit them",
            },
        )

    def _discover(
        self, manifest: IngestionManifest
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        source, budget = manifest.source, manifest.budget
        if source.kind == "LOCAL":
            base = checked_local(Path(source.location), self.local_roots)
            selected = []
            if source.files:
                paths = [
                    (
                        item,
                        checked_local(
                            base / item.path if base.is_dir() else base,
                            self.local_roots,
                        ),
                    )
                    for item in source.files
                ]
            elif base.is_file():
                paths = [(IngestionFile(path=base.name), base)]
            else:
                paths = []
                for scanned, path in enumerate(base.rglob("*"), 1):
                    if scanned > budget.max_files * 10:
                        raise IngestionFailure("DIRECTORY_SCAN_LIMIT")
                    relative = path.relative_to(base).as_posix()
                    if any(fnmatch(relative, pattern) for pattern in source.exclude):
                        continue
                    checked_local(path, self.local_roots)
                    if path.is_file() and any(
                        fnmatch(relative, pattern) for pattern in source.include
                    ):
                        paths.append((IngestionFile(path=relative), path))
                    if len(paths) > budget.max_files:
                        raise IngestionFailure("FILE_COUNT_LIMIT")
            for item, path in paths:
                size = path.stat().st_size
                if size > budget.max_file_bytes:
                    raise IngestionFailure("FILE_BYTE_LIMIT")
                selected.append(
                    {
                        **item.model_dump(mode="json"),
                        "local_path": str(path),
                        "size_bytes": item.size_bytes
                        if item.size_bytes is not None
                        else size,
                        "local_identity": local_identity(path),
                    }
                )
            evidence = {
                "kind": source.kind,
                "location": str(base),
                "directory_listing_identity": corpus_hash(
                    [
                        {k: v for k, v in row.items() if k != "local_path"}
                        for row in sorted(selected, key=lambda item: item["path"])
                    ]
                ),
            }
        elif source.kind == "GITHUB":
            policy = SourceImportPolicy(
                include_globs=tuple(item.path for item in source.files),
                extension_allowlist=tuple(
                    {
                        "." + item.path.rsplit(".", 1)[-1].lower()
                        for item in source.files
                    }
                ),
                max_files=budget.max_files,
                max_file_bytes=min(budget.max_file_bytes, 8_000_000),
                max_repository_bytes=budget.max_total_bytes,
                parser_profile="universal-corpus.v1",
                source_work_key="universal-source",
                corpus_registry_id="corpus-ingestion-manifest.v1",
                corpus_registry_hash=manifest.identity,
            )
            fetched = self.git.execute(
                stable_idempotency_key=manifest.identity,
                capability="source.remote.fetch",
                request_payload={
                    "repository_url": source.location,
                    "ref": source.revision,
                    "policy": asdict(policy),
                    "metadata_only": True,
                    "partial_fetch": True,
                },
            )
            if fetched.outcome != "success":
                raise IngestionFailure("GIT_ACQUISITION_FAILED")
            raw = fetched.evidence
            rows = {row["path"]: row for row in raw["files"]}
            selected = []
            for item in source.files:
                row = rows.get(item.path)
                if row is None or row["eligibility"] != "ELIGIBLE":
                    raise IngestionFailure(
                        "GIT_SELECTED_FILE_BLOCKED",
                        row["block_reason"] if row else item.path,
                    )
                if item.size_bytes is not None and item.size_bytes != row["size_bytes"]:
                    raise IngestionFailure("GIT_DECLARED_SIZE_CONFLICT")
                selected.append(
                    {
                        **item.model_dump(mode="json"),
                        "size_bytes": row["size_bytes"],
                        "git_object_id": row["object_id"],
                        "repository_identity": raw["repository_identity"],
                    }
                )
            evidence = {
                "kind": source.kind,
                "repository": source.location,
                "commit": raw["resolved_commit_sha"],
                "git_manifest_hash": raw["manifest_hash"],
                "large_file_limit": 8_000_000,
                "lfs_submodule_symlink": "REJECT",
            }
        elif source.kind == "HUGGING_FACE":
            url = f"https://huggingface.co/api/datasets/{quote(source.location, safe='/')}/revision/{source.revision}?blobs=true"
            metadata = self.http.metadata(url, timeout=budget.timeout_seconds)
            if metadata.get("sha") != source.revision:
                raise IngestionFailure("DATASET_REVISION_DRIFT")
            if source.config or source.split:
                configs = (metadata.get("cardData") or {}).get("configs") or []
                selected_config = next(
                    (
                        item
                        for item in configs
                        if item.get("config_name", "default")
                        == (source.config or "default")
                    ),
                    None,
                )
                if selected_config is None:
                    raise IngestionFailure("DATASET_CONFIG_MAPPING_UNVERIFIED")
                data_files = selected_config.get("data_files") or []
                patterns = []
                for item in data_files:
                    if isinstance(item, dict) and (
                        not source.split or item.get("split") == source.split
                    ):
                        paths = item.get("path", [])
                        patterns.extend([paths] if isinstance(paths, str) else paths)
                if not patterns or any(
                    not any(fnmatch(item.path, pattern) for pattern in patterns)
                    for item in source.files
                ):
                    raise IngestionFailure("DATASET_SPLIT_FILE_MISMATCH")
            rows = {row["rfilename"]: row for row in metadata.get("siblings", [])}
            selected = []
            for item in source.files:
                row = rows.get(item.path)
                if row is None:
                    raise IngestionFailure("DATASET_FILE_NOT_FOUND", item.path)
                lfs = row.get("lfs") or {}
                checksum = (
                    "sha256:" + lfs["sha256"] if lfs.get("sha256") else item.checksum
                )
                if item.checksum and checksum != item.checksum:
                    raise IngestionFailure("DATASET_DECLARED_CHECKSUM_CONFLICT")
                if item.size_bytes is not None and row.get("size") not in {
                    None,
                    item.size_bytes,
                }:
                    raise IngestionFailure("DATASET_DECLARED_SIZE_CONFLICT")
                selected.append(
                    {
                        **item.model_dump(mode="json"),
                        "checksum": checksum,
                        "size_bytes": row.get("size", item.size_bytes),
                        "git_blob_id": row.get("blobId"),
                        "download_url": f"https://huggingface.co/datasets/{quote(source.location, safe='/')}/resolve/{source.revision}/{quote(item.path, safe='/')}",
                    }
                )
            evidence = {
                "kind": source.kind,
                "dataset": source.location,
                "commit": source.revision,
                "config": source.config,
                "split": source.split,
                "metadata_hash": corpus_hash(metadata),
                "gated": metadata.get("gated", False),
                "dataset_license": (metadata.get("cardData") or {}).get("license"),
                "underlying_rights_inferred": False,
            }
        else:
            metadata = self.http.metadata(
                f"https://archive.org/metadata/{quote(source.location, safe='')}",
                timeout=budget.timeout_seconds,
            )
            rows = {row["name"]: row for row in metadata.get("files", [])}
            selected = []
            for item in source.files:
                row = rows.get(item.path)
                if row is None or row.get("private") in {True, "true"}:
                    raise IngestionFailure("ARCHIVE_FILE_UNAVAILABLE", item.path)
                if (
                    item.size_bytes is not None
                    and row.get("size") is not None
                    and item.size_bytes != int(row["size"])
                ):
                    raise IngestionFailure("ARCHIVE_DECLARED_SIZE_CONFLICT")
                selected.append(
                    {
                        **item.model_dump(mode="json"),
                        "size_bytes": int(row["size"])
                        if row.get("size")
                        else item.size_bytes,
                        "archive_md5": row.get("md5"),
                        "archive_sha1": row.get("sha1"),
                        "archive_mtime": row.get("mtime"),
                        "download_url": f"https://archive.org/download/{quote(source.location, safe='')}/{quote(item.path, safe='/')}",
                    }
                )
            evidence = {
                "kind": source.kind,
                "item": source.location,
                "file_metadata_hash": corpus_hash(
                    [
                        {
                            key: value
                            for key, value in row.items()
                            if key != "download_url"
                        }
                        for row in selected
                    ]
                ),
                "metadata": {
                    key: value
                    for key, value in metadata.get("metadata", {}).items()
                    if key
                    in {"identifier", "title", "licenseurl", "rights", "mediatype"}
                },
                "underlying_rights_inferred": False,
            }
        if (
            not selected
            or len(selected) > budget.max_files
            or sum(row.get("size_bytes") or 0 for row in selected)
            > budget.max_total_bytes
        ):
            raise IngestionFailure("ACQUISITION_SELECTION_BUDGET")
        return sorted(selected, key=lambda item: item["path"]), evidence

    def _acquire(
        self, manifest: IngestionManifest, selected: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        budget = manifest.budget
        files, total = [], 0
        for item in selected:
            remaining = min(budget.max_file_bytes, budget.max_total_bytes - total)
            args = {
                "root": self.root / "bytes",
                "budget": budget,
                "limit": remaining,
                "expected_hash": item.get("checksum"),
                "expected_size": item.get("size_bytes"),
            }
            if "local_path" in item:
                with stable_local_file(
                    Path(item["local_path"]), item["local_identity"]
                ) as source:
                    receipt = spool_bytes(source, **args)
            elif "git_object_id" in item:
                content = self.git.read_blob(
                    item["repository_identity"], item["git_object_id"]
                )
                if content.startswith(b"version https://git-lfs.github.com/spec/v1"):
                    raise IngestionFailure("GIT_LFS_UNSUPPORTED")
                receipt = spool_bytes(io.BytesIO(content), **args)
            else:
                with self.http.open(
                    item["download_url"], timeout=budget.timeout_seconds
                ) as source:
                    receipt = spool_bytes(source, **args)
                for algorithm in ("md5", "sha1"):
                    expected = item.get("archive_" + algorithm)
                    if expected:
                        digest = hashlib.new(algorithm)
                        with Path(receipt["cache_path"]).open("rb") as content:
                            for block in iter(lambda: content.read(65536), b""):
                                digest.update(block)
                        if digest.hexdigest() != expected:
                            raise IngestionFailure("ARCHIVE_METADATA_CONTENT_DRIFT")
            total += receipt["size_bytes"]
            kept = {
                key: value
                for key, value in item.items()
                if key not in {"download_url", "local_path"}
            }
            files.append({**kept, **receipt})
        if manifest.source.kind in {"LOCAL", "INTERNET_ARCHIVE"}:
            current, _ = self._discover(manifest)
            if corpus_hash(current) != corpus_hash(selected):
                raise IngestionFailure("SOURCE_CHANGED_DURING_ACQUISITION")
        return files

    def parse_files(
        self, receipt: dict[str, Any], manifest: IngestionManifest
    ) -> list[dict[str, Any]]:
        files = []
        expanded = 0
        for item in receipt["files"]:
            if item["path"].lower().endswith((".zip", ".tar", ".tar.gz", ".tgz")):
                for member in expand_container(
                    Path(item["cache_path"]),
                    item["path"],
                    self.root / "expanded",
                    manifest.budget,
                ):
                    expanded += member["size_bytes"]
                    if any(
                        fnmatch(member["path"], pattern)
                        for pattern in manifest.source.exclude
                    ) or not any(
                        fnmatch(member["path"], pattern)
                        for pattern in manifest.source.include
                    ):
                        if expanded > manifest.budget.max_expanded_bytes:
                            raise IngestionFailure("TOTAL_EXPANSION_LIMIT")
                        continue
                    files.append(
                        {
                            **member,
                            "archive_checksum": item["checksum"],
                            "parser": item.get("parser"),
                        }
                    )
                    if (
                        len(files) > manifest.budget.max_files
                        or expanded > manifest.budget.max_expanded_bytes
                    ):
                        raise IngestionFailure("TOTAL_EXPANSION_LIMIT")
            else:
                files.append(item)
        return files
