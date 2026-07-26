"""Backend-neutral execution evidence records and storage protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from novel_forge.modules.provider_control.contracts import ProviderInvocationResult

from .contracts import (
    ExecutionCancellationResult,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
)
from .process_supervisor import ProcessReceipt


@dataclass(slots=True)
class ExecutionRecord:
    request: ExecutionRequest
    handle: ExecutionHandle
    started_at: str
    raw_evidence: dict[str, Any]
    provider_result: ProviderInvocationResult | None = None
    external_result: Any | None = None
    process_receipt: ProcessReceipt | None = None
    result: ExecutionResult | None = None
    callback_receipts: dict[str, tuple[str, str]] = field(default_factory=dict)
    cancellation: ExecutionCancellationResult | None = None


class ExecutionRecordStore(Protocol):
    def put_record(self, record: ExecutionRecord) -> None: ...

    def save_record(self, record: ExecutionRecord) -> None: ...

    def get_record(self, execution_id: str) -> ExecutionRecord: ...

    def find_record(self, execution_id: str) -> ExecutionRecord | None: ...

    def put_evidence(
        self, kind: str, execution_id: str, payload: Mapping[str, Any]
    ) -> str: ...

    def read_evidence(self, ref: str) -> dict[str, Any]: ...


__all__ = ["ExecutionRecord", "ExecutionRecordStore"]
