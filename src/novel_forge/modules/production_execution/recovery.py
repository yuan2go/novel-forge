from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.asset_commands import (
    AuthorityAssetWriteCommand,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.provider_control.contracts import (
    ProviderInvocationHandle,
    ProviderInvocationResult,
)
from novel_forge.storage.authority_asset_store import (
    AuthorityAssetDocument,
    AuthorityAssetQuery,
    AuthorityAssetWriter,
)

from .evidence import ExecutionRecord
from .contracts import (
    ExecutionCancellationResult,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
)
from .security import assert_no_inline_secrets
from .external_action_backend import ExternalActionInvocationResult
from .process_supervisor import ProcessReceipt


_EVIDENCE_KIND = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EVIDENCE_REF_PREFIX = "authority-asset-version:"


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: str, *, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _provider_result_to_dict(
    result: ProviderInvocationResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "outcome": result.outcome,
        "handle": asdict(result.handle) if result.handle is not None else None,
        "evidence": dict(result.evidence),
        "request_sent": result.request_sent,
    }


def _provider_result_from_dict(
    payload: Mapping[str, Any] | None,
) -> ProviderInvocationResult | None:
    if payload is None:
        return None
    handle_payload = payload.get("handle")
    handle = (
        ProviderInvocationHandle(
            **{
                name: handle_payload.get(name)
                for name in (
                    "provider_request_id",
                    "provider_correlation_id",
                    "accepted_at",
                    "completion_mode",
                    "query_supported",
                    "cancel_supported",
                    "callback_supported",
                    "idempotency_supported",
                )
            }
        )
        if isinstance(handle_payload, Mapping)
        else None
    )
    return ProviderInvocationResult(
        outcome=str(payload.get("outcome") or ""),
        handle=handle,
        evidence=dict(payload.get("evidence") or {}),
        request_sent=bool(payload.get("request_sent")),
    )


def _external_result_to_dict(
    result: ExternalActionInvocationResult | None,
) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "outcome": result.outcome,
        "external_request_id": result.external_request_id,
        "completion_mode": result.completion_mode,
        "evidence": dict(result.evidence),
        "request_sent": result.request_sent,
    }


def _external_result_from_dict(
    payload: Mapping[str, Any] | None,
) -> ExternalActionInvocationResult | None:
    if payload is None:
        return None
    return ExternalActionInvocationResult(
        outcome=str(payload.get("outcome") or ""),
        external_request_id=(
            str(payload["external_request_id"])
            if payload.get("external_request_id")
            else None
        ),
        completion_mode=str(payload.get("completion_mode") or "poll"),
        evidence=dict(payload.get("evidence") or {}),
        request_sent=bool(payload.get("request_sent")),
    )


def _record_to_dict(record: ExecutionRecord) -> dict[str, Any]:
    return {
        "request": record.request.to_dict(),
        "handle": record.handle.to_dict(),
        "started_at": record.started_at,
        "raw_evidence": dict(record.raw_evidence),
        "provider_result": _provider_result_to_dict(record.provider_result),
        "external_result": _external_result_to_dict(record.external_result),
        "process_receipt": (
            record.process_receipt.to_dict()
            if record.process_receipt is not None
            else None
        ),
        "result": record.result.to_dict() if record.result is not None else None,
        "callback_receipts": {
            message_id: {
                "payload_hash": identity[0],
                "outcome": identity[1],
            }
            for message_id, identity in sorted(record.callback_receipts.items())
        },
        "cancellation": (
            record.cancellation.to_dict()
            if record.cancellation is not None
            else None
        ),
    }


def _record_from_dict(payload: Mapping[str, Any]) -> ExecutionRecord:
    callbacks = {
        str(message_id): (
            str(identity.get("payload_hash") or ""),
            str(identity.get("outcome") or ""),
        )
        for message_id, identity in dict(
            payload.get("callback_receipts") or {}
        ).items()
        if isinstance(identity, Mapping)
    }
    process_payload = payload.get("process_receipt")
    result_payload = payload.get("result")
    cancellation_payload = payload.get("cancellation")
    return ExecutionRecord(
        request=ExecutionRequest.from_dict(dict(payload.get("request") or {})),
        handle=ExecutionHandle.from_dict(dict(payload.get("handle") or {})),
        started_at=str(payload.get("started_at") or ""),
        raw_evidence=dict(payload.get("raw_evidence") or {}),
        provider_result=_provider_result_from_dict(
            payload.get("provider_result")
            if isinstance(payload.get("provider_result"), Mapping)
            else None
        ),
        external_result=_external_result_from_dict(
            payload.get("external_result")
            if isinstance(payload.get("external_result"), Mapping)
            else None
        ),
        process_receipt=(
            ProcessReceipt.from_dict(process_payload)
            if isinstance(process_payload, Mapping)
            else None
        ),
        result=(
            ExecutionResult.from_dict(result_payload)
            if isinstance(result_payload, Mapping)
            else None
        ),
        callback_receipts=callbacks,
        cancellation=(
            ExecutionCancellationResult.from_dict(cancellation_payload)
            if isinstance(cancellation_payload, Mapping)
            else None
        ),
    )


class AuthorityExecutionRecoveryStore:

    def __init__(self, database_url: str, *, project_id: str) -> None:
        if not database_url or not project_id:
            raise ValueError(
                "Authority execution recovery requires PostgreSQL and project_id"
            )
        self.database_url = database_url
        self.project_id = project_id
        self.query = AuthorityAssetQuery(database_url)
        self.writer = AuthorityAssetWriter(database_url)

    def put_record(self, record: ExecutionRecord) -> None:
        self._save_record(record)

    def save_record(self, record: ExecutionRecord) -> None:
        self._save_record(record)

    def get_record(self, execution_id: str) -> ExecutionRecord:
        existing = self._require_session(execution_id)
        record_payload = existing.content.get("record")
        if not isinstance(record_payload, Mapping):
            raise ValueError("execution recovery AssetVersion has no record contract")
        recovered = _record_from_dict(record_payload)
        if recovered.request.execution_id != execution_id:
            raise ValueError("execution recovery identity is corrupt")
        return recovered

    def find_record(self, execution_id: str) -> ExecutionRecord | None:
        try:
            return self.get_record(execution_id)
        except KernelError as exc:
            if exc.code == "AUTHORITY_ASSET_NOT_FOUND":
                return None
            raise

    def load_session(self, execution_id: str) -> ExecutionRecord:
        return self.get_record(execution_id)

    def put_request(self, request: ExecutionRequest) -> str:
        return self._put_evidence(
            "execution-request",
            request.execution_id,
            request.to_dict(),
            operation_id=request.operation_id,
            trace_id=request.trace_id,
            correlation_id=request.correlation_id,
        )

    def put_handle(self, handle: ExecutionHandle) -> str:
        record = self.get_record(handle.execution_id)
        return self._put_evidence(
            "execution-handle",
            handle.execution_id,
            handle.to_dict(),
            operation_id=record.request.operation_id,
            trace_id=record.request.trace_id,
            correlation_id=record.request.correlation_id,
        )

    def put_receipt(
        self,
        kind: str,
        execution_id: str,
        payload: Mapping[str, Any],
    ) -> str:
        if "receipt" not in kind:
            raise ValueError("receipt evidence kind must identify a receipt")
        return self.put_evidence(kind, execution_id, payload)

    def put_manifest(
        self,
        kind: str,
        execution_id: str,
        payload: Mapping[str, Any],
    ) -> str:
        if "manifest" not in kind:
            raise ValueError("manifest evidence kind must identify a manifest")
        return self.put_evidence(kind, execution_id, payload)

    def put_evidence(
        self,
        kind: str,
        execution_id: str,
        payload: Mapping[str, Any],
    ) -> str:
        record = self.get_record(execution_id)
        return self._put_evidence(
            kind,
            execution_id,
            payload,
            operation_id=record.request.operation_id,
            trace_id=record.request.trace_id,
            correlation_id=record.request.correlation_id,
        )

    def read_evidence(self, ref: str) -> dict[str, Any]:
        if not ref.startswith(_EVIDENCE_REF_PREFIX):
            raise ValueError("execution evidence ref is not Authority-backed")
        asset_version_id = ref.removeprefix(_EVIDENCE_REF_PREFIX)
        document = self.query.require(
            project_id=self.project_id,
            asset_version_id=asset_version_id,
        )
        if document.asset_type != "execution_evidence":
            raise ValueError("Authority AssetVersion is not execution evidence")
        payload = document.content.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("execution evidence AssetVersion has no payload")
        expected_hash = str(document.content.get("payload_hash") or "")
        actual_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        if expected_hash != actual_hash:
            raise ValueError("execution evidence payload hash is corrupt")
        return dict(payload)

    def _save_record(self, record: ExecutionRecord) -> None:
        request = record.request
        if request.project_id != self.project_id:
            raise ValueError("execution recovery cannot cross project boundaries")
        existing = self._find_session(request.execution_id)
        if existing is not None:
            stored_request_hash = str(
                existing.content.get("request_contract_hash") or ""
            )
            if stored_request_hash != request.contract_hash:
                raise ValueError("duplicate execution ID has a different request")
        record_payload = _record_to_dict(record)
        assert_no_inline_secrets(
            record_payload,
            label="Authority execution recovery record",
        )
        content = {
            "contract_version": "authority-execution-recovery.v1",
            "execution_id": request.execution_id,
            "request_contract_hash": request.contract_hash,
            "record_state_hash": hashlib.sha256(
                _canonical(record_payload).encode("utf-8")
            ).hexdigest(),
            "record": record_payload,
            "authority_status_owner": "authority_attempt",
            "external_outcome_owner": "authority_external_effect",
        }
        if existing is not None and existing.content == content:
            return
        logical_ref = self._session_ref(request.execution_id)
        self.writer.materialize_output(
            AuthorityAssetWriteCommand(
                operation_id=request.operation_id,
                project_id=self.project_id,
                asset_id=self._asset_id(logical_ref),
                asset_type="execution_recovery_session",
                schema_version="authority-execution-recovery.v1",
                logical_ref=logical_ref,
                category="production_execution_recovery",
                output_key=f"production_execution.recovery.{_digest(request.execution_id)}",
                role="execution_recovery_projection",
                content=content,
                qualification_policy="authority-execution-recovery-v1",
                trace_id=request.trace_id,
                correlation_id=request.correlation_id,
                expected_current_asset_version_id=(
                    existing.asset_version_id if existing is not None else None
                ),
                causation_id=request.external_effect_id,
            )
        )

    def _put_evidence(
        self,
        kind: str,
        execution_id: str,
        payload: Mapping[str, Any],
        *,
        operation_id: str,
        trace_id: str,
        correlation_id: str,
    ) -> str:
        if not _EVIDENCE_KIND.fullmatch(kind):
            raise ValueError("execution evidence kind is invalid")
        assert_no_inline_secrets(
            payload,
            label=f"Authority execution evidence {kind}",
        )
        frozen = json.loads(_canonical(payload))
        payload_hash = hashlib.sha256(
            _canonical(frozen).encode("utf-8")
        ).hexdigest()
        logical_ref = (
            "production_execution/recovery/evidence/"
            f"{_digest(execution_id)}/{kind}/{payload_hash}"
        )
        content = {
            "contract_version": "authority-execution-evidence.v1",
            "execution_id": execution_id,
            "kind": kind,
            "payload_hash": payload_hash,
            "payload": frozen,
        }
        try:
            existing = self.query.require(
                project_id=self.project_id,
                logical_ref=logical_ref,
            )
        except KernelError as exc:
            if exc.code != "AUTHORITY_ASSET_NOT_FOUND":
                raise
            existing = None
        if existing is not None:
            if existing.asset_type != "execution_evidence" or existing.content != content:
                raise ValueError("execution evidence hash identity is conflicted")
            return _EVIDENCE_REF_PREFIX + existing.asset_version_id
        command = AuthorityAssetWriteCommand(
            operation_id=operation_id,
            project_id=self.project_id,
            asset_id=self._asset_id(logical_ref),
            asset_type="execution_evidence",
            schema_version="authority-execution-evidence.v1",
            logical_ref=logical_ref,
            category="production_execution_evidence",
            output_key=(
                "production_execution.evidence."
                f"{kind}.{_digest(execution_id)}.{payload_hash[:12]}"
            ),
            role=kind,
            content=content,
            qualification_policy="authority-execution-evidence-v1",
            trace_id=trace_id,
            correlation_id=correlation_id,
        )
        try:
            document = self.writer.materialize_output(command)
        except KernelError as exc:
            if exc.code not in {
                "AUTHORITY_ASSET_LOCATOR_CONFLICT",
                "AUTHORITY_ASSET_VERSION_CONFLICT",
            }:
                raise
            document = self.query.require(
                project_id=self.project_id,
                logical_ref=logical_ref,
            )
            if (
                document.asset_type != "execution_evidence"
                or document.content != content
            ):
                raise
        return _EVIDENCE_REF_PREFIX + document.asset_version_id

    def _find_session(self, execution_id: str) -> AuthorityAssetDocument | None:
        try:
            return self._require_session(execution_id)
        except KernelError as exc:
            if exc.code == "AUTHORITY_ASSET_NOT_FOUND":
                return None
            raise

    def _require_session(self, execution_id: str) -> AuthorityAssetDocument:
        document = self.query.require(
            project_id=self.project_id,
            logical_ref=self._session_ref(execution_id),
        )
        if document.asset_type != "execution_recovery_session":
            raise ValueError("execution recovery locator has an unexpected asset type")
        return document

    @staticmethod
    def _session_ref(execution_id: str) -> str:
        return f"production_execution/recovery/sessions/{_digest(execution_id)}"

    def _asset_id(self, logical_ref: str) -> str:
        return "production-execution:" + _digest(
            f"{self.project_id}:{logical_ref}",
            length=32,
        )


__all__ = ["AuthorityExecutionRecoveryStore"]
