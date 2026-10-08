
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from typing import Any, Iterator

from novel_forge.modules.command_kernel.external_effect_adapters import (
    ExternalEffectAdapterError,
    ProviderResult,
)
from .public_catalog import CatalogCapture, digest, parse_page


def qidian_public_transport() -> Any:
    from novel_forge.modules.source_import.corpus_ingestion.http_transport import (
        CorpusHttpTransport,
    )

    class QidianPublicTransport(CorpusHttpTransport):
        @staticmethod
        def _host_allowed(host: str) -> bool:
            return host == "www.qidian.com"

    return QidianPublicTransport()


class PublicCatalogAdapter:
    provider = "public_catalog_http"
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
    maximum_page_bytes = 2_000_000

    def __init__(
        self, root: Path, *, offline_root: Path | None = None, transport: Any = None
    ) -> None:
        if not root.is_absolute():
            raise ValueError("public catalog requires an absolute durable receipt root")
        self.root = root.resolve()
        self.offline_root = offline_root.resolve() if offline_root else None
        self.transport = transport or qidian_public_transport()

    def execute(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        request_payload = self._business_payload(request_payload)
        if capability != "source.remote.fetch":
            raise ExternalEffectAdapterError(
                "unsupported catalog capability", request_sent=False
            )
        try:
            capture = CatalogCapture.model_validate(request_payload)
            with self._locked("effect:" + stable_idempotency_key):
                existing = self.query(
                    stable_idempotency_key=stable_idempotency_key,
                    capability=capability,
                    request_payload=request_payload,
                )
                if existing.outcome != "not_found":
                    return existing
                if capture.mode == "LIVE_HTTP" and capture.cache_ttl_seconds:
                    cached = self._cache(capture)
                    if cached:
                        return self._save_receipt(
                            stable_idempotency_key,
                            request_payload,
                            "success",
                            {**cached, "cache_reused": True},
                        )
                evidence = self._capture(capture, stable_idempotency_key)
                result = self._save_receipt(
                    stable_idempotency_key, request_payload, "success", evidence
                )
                if capture.mode == "LIVE_HTTP":
                    self._atomic(
                        self.root / "cache" / self._key(capture.url),
                        json.dumps(evidence, ensure_ascii=False).encode(),
                    )
                return result
        except ExternalEffectAdapterError:
            raise
        except ValueError as exc:
            code = str(exc).split(":")[0]
            evidence = {
                "error_code": code,
                "mode": request_payload.get("mode"),
                "url": request_payload.get("url"),
                "records_available": False,
            }
            return self._save_receipt(
                stable_idempotency_key, request_payload, "final_failure", evidence
            )
        except (OSError, TimeoutError) as exc:
            raise ExternalEffectAdapterError(
                f"catalog transport interrupted: {type(exc).__name__}",
                request_sent=True,
            ) from exc

    def query(
        self,
        *,
        stable_idempotency_key: str,
        capability: str,
        request_payload: dict[str, Any],
    ) -> ProviderResult:
        del capability
        request_payload = self._business_payload(request_payload)
        path = self.root / "receipts" / self._key(stable_idempotency_key)
        if not path.exists():
            return ProviderResult(
                "not_found",
                self._key(stable_idempotency_key),
                {"recovery": "NO_DURABLE_RECEIPT; do not assume an empty catalog"},
            )
        receipt = json.loads(path.read_bytes())
        if receipt["request_hash"] != self._request_hash(request_payload):
            raise ExternalEffectAdapterError(
                "catalog receipt request identity conflict", request_sent=False
            )
        for page in receipt["evidence"].get("pages", []):
            raw = self.root / "snapshots" / page["raw_snapshot_hash"].split(":")[1]
            if (
                not raw.exists()
                or digest(raw.read_bytes()) != page["raw_snapshot_hash"]
            ):
                raise ExternalEffectAdapterError(
                    "catalog receipt snapshot missing or corrupt", request_sent=False
                )
        return ProviderResult(
            receipt["outcome"], receipt["correlation_id"], receipt["evidence"]
        )

    def cancel(self, *, provider_request_id: str, **_kwargs: Any) -> ProviderResult:
        return ProviderResult(
            "final_failure",
            provider_request_id,
            {"error_code": "CATALOG_CANCEL_NOT_SUPPORTED"},
        )

    def _capture(self, capture: CatalogCapture, key: str) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        url: str | None = capture.url
        visited: set[str] = set()
        records: dict[str, dict[str, Any]] = {}
        for index in range(capture.max_pages):
            if url is None:
                break
            if url in visited:
                raise ValueError("PUBLIC_CATALOG_PAGINATION_LOOP")
            visited.add(url)
            if capture.mode == "OFFLINE_AUTHORIZED_SNAPSHOT":
                if index >= len(capture.offline_pages):
                    break
                page = capture.offline_pages[index]
                if page["url"] != url:
                    raise ValueError("OFFLINE_CATALOG_PAGINATION_IDENTITY_CONFLICT")
                path = Path(page["path"])
                if (
                    self.offline_root is None
                    or path.is_symlink()
                    or not path.resolve().is_relative_to(self.offline_root)
                ):
                    raise ValueError("OFFLINE_CATALOG_ROOT_FORBIDDEN")
                if path.stat().st_size > self.maximum_page_bytes:
                    raise ValueError("PUBLIC_CATALOG_PAGE_TOO_LARGE")
                raw = path.read_bytes()
                if digest(raw) != page["sha256"]:
                    raise ValueError("OFFLINE_CATALOG_HASH_CONFLICT")
                acquired_at = page["acquired_at"]
            else:
                with self._locked("qidian-host"):
                    gate = self.root / "rate-limit.json"
                    next_allowed = (
                        json.loads(gate.read_bytes())["next_allowed"]
                        if gate.exists()
                        else 0
                    )
                    delay = max(0, next_allowed - time.time())
                    if delay > capture.page_timeout_seconds:
                        raise ValueError("PUBLIC_CATALOG_RATE_LIMITED")
                    if delay:
                        time.sleep(delay)
                    self._atomic(
                        gate,
                        json.dumps(
                            {
                                "next_allowed": time.time()
                                + capture.minimum_interval_seconds
                            }
                        ).encode(),
                    )
                    with self.transport.open(
                        url, timeout=capture.page_timeout_seconds
                    ) as response:
                        raw = response.read(self.maximum_page_bytes + 1)
                        status = response.status
                        retry_after = response.getheader("Retry-After")
                        if status == 429 and retry_after and retry_after.isdigit():
                            self._atomic(
                                gate,
                                json.dumps(
                                    {
                                        "next_allowed": time.time()
                                        + min(3600, max(1, int(retry_after)))
                                    }
                                ).encode(),
                            )
                acquired_at = datetime.now(timezone.utc).isoformat()
                if len(raw) > self.maximum_page_bytes:
                    raise ValueError("PUBLIC_CATALOG_PAGE_TOO_LARGE")
                self._atomic(self.root / "snapshots" / digest(raw).split(":")[1], raw)
                if status != 200:
                    self._atomic(
                        self.root / "failures" / self._key(key),
                        json.dumps(
                            {
                                "url": url,
                                "http_status": status,
                                "acquired_at": acquired_at,
                                "raw_snapshot_hash": digest(raw),
                            }
                        ).encode(),
                    )
                    raise ValueError(
                        "PUBLIC_CATALOG_ACCESS_CHALLENGE"
                        if status == 202
                        else f"PUBLIC_CATALOG_HTTP_{status}"
                    )
            parsed = parse_page(raw, url, acquired_at)
            self._atomic(
                self.root / "snapshots" / parsed["raw_snapshot_hash"].split(":")[1], raw
            )
            for record in parsed["records"]:
                if (
                    record["work_id"] in records
                    and records[record["work_id"]] != record
                ):
                    raise ValueError("PUBLIC_CATALOG_PAGE_DUPLICATE_CONFLICT")
                records[record["work_id"]] = record
            pages.append({k: v for k, v in parsed.items() if k != "records"})
            url = parsed["next_url"]
        return {
            "schema_version": "public-catalog-snapshot.v1",
            "platform": capture.platform,
            "url": capture.url,
            "mode": capture.mode,
            "authorization_ref": capture.authorization_ref,
            "pages": pages,
            "records": list(records.values()),
            "ranking_period": pages[0]["ranking_period"],
            "parser_version": pages[0]["parser_version"],
            "acquired_at": pages[0]["acquired_at"],
            "data_time": None,
            "data_time_status": "NOT_PUBLISHED",
            "next_url": url,
            "snapshot_scope": capture.snapshot_scope,
            "complete": url is None and capture.snapshot_scope == "FULL_PAGE",
            "cache_reused": False,
            "generation_context_allowed": False,
        }

    def _cache(self, capture: CatalogCapture) -> dict[str, Any] | None:
        path = self.root / "cache" / self._key(capture.url)
        if not path.exists():
            return None
        data = json.loads(path.read_bytes())
        if (
            datetime.now(timezone.utc).timestamp()
            - datetime.fromisoformat(data["acquired_at"]).timestamp()
            > capture.cache_ttl_seconds
        ):
            return None
        if len(data["pages"]) > capture.max_pages or (
            len(data["pages"]) < capture.max_pages and not data["complete"]
        ):
            return None
        for page in data["pages"]:
            raw = self.root / "snapshots" / page["raw_snapshot_hash"].split(":")[1]
            if (
                not raw.exists()
                or digest(raw.read_bytes()) != page["raw_snapshot_hash"]
            ):
                return None
        return data

    def _save_receipt(
        self, key: str, payload: dict[str, Any], outcome: str, evidence: dict[str, Any]
    ) -> ProviderResult:
        identity = self._key(key)
        receipt = {
            "request_hash": self._request_hash(payload),
            "outcome": outcome,
            "correlation_id": identity,
            "evidence": evidence,
        }
        self._atomic(
            self.root / "receipts" / identity,
            json.dumps(receipt, ensure_ascii=False).encode(),
        )
        return ProviderResult(outcome, identity, evidence)

    @contextmanager
    def _locked(self, key: str) -> Iterator[None]:
        directory = self.root / "locks"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / self._key(key)).open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + f".{os.getpid()}.{uuid4().hex}.tmp")
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    @staticmethod
    def _key(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _business_payload(payload: dict[str, Any]) -> dict[str, Any]:
        host_fields = {
            "external_effect_id",
            "operation_id",
            "request_hash",
            "timeout_seconds",
            "provider_request_id",
            "trace_id",
            "correlation_id",
        }
        return {k: v for k, v in payload.items() if k not in host_fields}

    @staticmethod
    def _request_hash(payload: dict[str, Any]) -> str:
        return digest(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        )
