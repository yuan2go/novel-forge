from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .process_supervisor import ExecutionDirectoryLayout, PersistentExecutionDirectory, ProcessReceipt


@dataclass(frozen=True)
class RetainedRejectedOutputProof:
    execution_id: str
    request_digest: str
    result_sha256: str
    byte_size: int
    raw_json: str

    def result(self) -> dict[str, Any]:
        return json.loads(self.raw_json)


def read_retained_rejected_output(*, request: Mapping[str, Any], process: Mapping[str, Any], metadata: Mapping[str, Any]) -> RetainedRejectedOutputProof:
    layout = ExecutionDirectoryLayout(
        request["execution_id"], Path(process["execution_directory"])
    )
    receipt = ProcessReceipt.from_dict(process)
    PersistentExecutionDirectory._validate_receipt_paths(layout, receipt)
    path = Path(process["result_path"])
    if (
        path.resolve(strict=True) != path
        or path.is_symlink()
        or layout.receipt_path.resolve(strict=True) != layout.receipt_path
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_PATH_INVALID",
            "Retained result and receipt must remain in their original native directory",
        )
    current = json.loads(layout.receipt_path.read_text())
    identity = json.loads(layout.metadata_path.read_text())
    if (
        current != process
        or identity.get("execution_id") != request["execution_id"]
        or identity.get("request_digest") != process.get("request_digest")
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_PROCESS_DRIFT",
            "The retained native process identity changed",
        )
    data = path.read_bytes()
    if (
        len(data) != metadata["byte_size"]
        or "sha256:" + hashlib.sha256(data).hexdigest() != metadata["result_sha256"]
    ):
        raise KernelError(
            "PLANNING_GATEWAY_RESULT_HASH_DRIFT", "The original rejected output changed"
        )
    raw = json.loads(data)
    if not isinstance(raw, dict):
        raise KernelError("PLANNING_GATEWAY_RESULT_EVIDENCE_INVALID", "Retained structured output must be a complete object")
    return RetainedRejectedOutputProof(request["execution_id"], process["request_digest"], metadata["result_sha256"], len(data), json.dumps(raw, sort_keys=True, ensure_ascii=False, allow_nan=False))
