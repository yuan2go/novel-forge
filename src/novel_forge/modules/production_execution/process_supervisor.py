"""Persistent, process-group-aware supervision for local Codex CLI workers.

The process receipt is execution evidence, not an Attempt authority.  Production
callers bind it to the existing Authority Attempt; legacy adapter callers may run
unbound, but those receipts are explicitly ineligible as production evidence.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Any, Mapping, Protocol

try:  # POSIX is the supported local CLI runtime; the fallback preserves importability.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

from .contracts import ExecutionRuntimeClass


CODEX_ENVIRONMENT_ALLOWLIST = (
    "PATH",
    "HOME",
    "CODEX_HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "SSL_CERT_FILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
)
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(encoded)


def _age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds())


class ProcessReceiptStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ORPHANED = "ORPHANED"
    CORRUPT_RESULT = "CORRUPT_RESULT"


class ResultIntegrity(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    MISSING = "MISSING"
    VALID = "VALID"
    CORRUPT = "CORRUPT"


@dataclass(frozen=True, slots=True)
class EnvironmentAllowlist:
    allowed_names: tuple[str, ...]

    @classmethod
    def codex_default(cls) -> EnvironmentAllowlist:
        return cls(CODEX_ENVIRONMENT_ALLOWLIST)

    def build(
        self,
        source: Mapping[str, str] | None = None,
        *,
        overrides: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        source_payload = os.environ if source is None else source
        override_payload = overrides or {}
        denied = sorted(set(override_payload) - set(self.allowed_names))
        if denied:
            raise ValueError(f"environment override is not allowlisted: {', '.join(denied)}")
        filtered = {
            name: str(source_payload[name])
            for name in self.allowed_names
            if name in source_payload and source_payload[name] is not None
        }
        for name, value in override_payload.items():
            if value is None:
                filtered.pop(name, None)
            else:
                filtered[name] = str(value)
        return filtered


@dataclass(frozen=True, slots=True)
class ProcessTimeout:
    timeout_seconds: float
    termination_grace_seconds: float = 2.0
    poll_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("process timeout must be positive")
        if self.termination_grace_seconds < 0:
            raise ValueError("termination grace must not be negative")
        if self.poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")


@dataclass(frozen=True, slots=True)
class ProcessGroup:
    pid: int
    pgid: int
    process_start_token: str

    def __post_init__(self) -> None:
        if self.pid <= 0 or self.pgid <= 0:
            raise ValueError("process group requires positive PID and PGID")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "pgid": self.pgid,
            "process_start_token": self.process_start_token,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProcessGroup:
        return cls(
            pid=int(payload.get("pid") or 0),
            pgid=int(payload.get("pgid") or 0),
            process_start_token=str(payload.get("process_start_token") or ""),
        )


@dataclass(frozen=True, slots=True)
class ProcessReceipt:
    receipt_id: str
    execution_id: str
    operation_id: str | None
    attempt_id: str | None
    fencing_token: int | None
    transport: ExecutionRuntimeClass
    status: ProcessReceiptStatus
    process_group: ProcessGroup
    execution_directory: str
    receipt_path: str
    stdout_path: str
    stderr_path: str
    result_path: str | None
    result_filename: str | None
    result_format: str | None
    result_integrity: ResultIntegrity
    request_digest: str
    command_sha256: str
    input_sha256: str
    environment_keys: tuple[str, ...]
    process_started_at: str
    supervisor_pid: int | None = None
    supervisor_process_start_token: str | None = None
    last_supervisor_heartbeat_at: str | None = None
    completed_at: str | None = None
    elapsed_ms: int = 0
    returncode: int | None = None
    termination_signal: str | None = None
    termination_reason: str | None = None
    failure_reason: str | None = None
    recovery_reason: str | None = None
    local_termination_only: bool = False
    provider_request_id: str | None = None
    receipt_version: str = "process-receipt.v1"

    def __post_init__(self) -> None:
        supplied = (self.operation_id is not None, self.attempt_id is not None, self.fencing_token is not None)
        if any(supplied) and not all(supplied):
            raise ValueError("process receipt Authority Attempt binding must be complete")
        if isinstance(self.fencing_token, bool):
            raise ValueError("process receipt fencing token must be an integer")
        if self.fencing_token is not None and self.fencing_token <= 0:
            raise ValueError("process receipt fencing token must be positive")
        if not self.receipt_id or not self.execution_id or not self.process_started_at:
            raise ValueError("process receipt identity is incomplete")
        if not _HEX_64.fullmatch(self.request_digest):
            raise ValueError("process receipt request digest must be SHA-256")
        if self.transport is not ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE:
            raise ValueError("process receipt transport must be LOCAL_CLI_REMOTE_INFERENCE")
        if self.provider_request_id is not None:
            raise ValueError("local process receipt cannot claim a provider request ID")

    @property
    def authority_bound(self) -> bool:
        return self.operation_id is not None and self.attempt_id is not None and self.fencing_token is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_version": self.receipt_version,
            "receipt_id": self.receipt_id,
            "execution_id": self.execution_id,
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "fencing_token": self.fencing_token,
            "authority_bound": self.authority_bound,
            "transport": self.transport.value,
            "status": self.status.value,
            "process_group": self.process_group.to_dict(),
            "execution_directory": self.execution_directory,
            "receipt_path": self.receipt_path,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "result_path": self.result_path,
            "result_filename": self.result_filename,
            "result_format": self.result_format,
            "result_integrity": self.result_integrity.value,
            "request_digest": self.request_digest,
            "command_sha256": self.command_sha256,
            "input_sha256": self.input_sha256,
            "environment_keys": list(self.environment_keys),
            "process_started_at": self.process_started_at,
            "supervisor_pid": self.supervisor_pid,
            "supervisor_process_start_token": self.supervisor_process_start_token,
            "last_supervisor_heartbeat_at": self.last_supervisor_heartbeat_at,
            "completed_at": self.completed_at,
            "elapsed_ms": self.elapsed_ms,
            "returncode": self.returncode,
            "termination_signal": self.termination_signal,
            "termination_reason": self.termination_reason,
            "failure_reason": self.failure_reason,
            "recovery_reason": self.recovery_reason,
            "local_termination_only": self.local_termination_only,
            "provider_request_id": None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProcessReceipt:
        return cls(
            receipt_version=str(payload.get("receipt_version") or "process-receipt.v1"),
            receipt_id=str(payload.get("receipt_id") or ""),
            execution_id=str(payload.get("execution_id") or ""),
            operation_id=str(payload["operation_id"]) if payload.get("operation_id") is not None else None,
            attempt_id=str(payload["attempt_id"]) if payload.get("attempt_id") is not None else None,
            fencing_token=int(payload["fencing_token"]) if payload.get("fencing_token") is not None else None,
            transport=ExecutionRuntimeClass(str(payload.get("transport") or "")),
            status=ProcessReceiptStatus(str(payload.get("status") or "")),
            process_group=ProcessGroup.from_dict(payload.get("process_group", {})),
            execution_directory=str(payload.get("execution_directory") or ""),
            receipt_path=str(payload.get("receipt_path") or ""),
            stdout_path=str(payload.get("stdout_path") or ""),
            stderr_path=str(payload.get("stderr_path") or ""),
            result_path=str(payload["result_path"]) if payload.get("result_path") else None,
            result_filename=str(payload["result_filename"]) if payload.get("result_filename") else None,
            result_format=str(payload["result_format"]) if payload.get("result_format") else None,
            result_integrity=ResultIntegrity(str(payload.get("result_integrity") or "NOT_REQUIRED")),
            request_digest=str(payload.get("request_digest") or ""),
            command_sha256=str(payload.get("command_sha256") or ""),
            input_sha256=str(payload.get("input_sha256") or ""),
            environment_keys=tuple(str(item) for item in payload.get("environment_keys", [])),
            process_started_at=str(payload.get("process_started_at") or ""),
            supervisor_pid=(
                int(payload["supervisor_pid"])
                if payload.get("supervisor_pid") is not None
                else None
            ),
            supervisor_process_start_token=(
                str(payload["supervisor_process_start_token"])
                if payload.get("supervisor_process_start_token")
                else None
            ),
            last_supervisor_heartbeat_at=(
                str(payload["last_supervisor_heartbeat_at"])
                if payload.get("last_supervisor_heartbeat_at")
                else None
            ),
            completed_at=str(payload["completed_at"]) if payload.get("completed_at") else None,
            elapsed_ms=int(payload.get("elapsed_ms") or 0),
            returncode=int(payload["returncode"]) if payload.get("returncode") is not None else None,
            termination_signal=str(payload["termination_signal"]) if payload.get("termination_signal") else None,
            termination_reason=str(payload["termination_reason"]) if payload.get("termination_reason") else None,
            failure_reason=str(payload["failure_reason"]) if payload.get("failure_reason") else None,
            recovery_reason=str(payload["recovery_reason"]) if payload.get("recovery_reason") else None,
            local_termination_only=bool(payload.get("local_termination_only", False)),
            provider_request_id=(
                str(payload["provider_request_id"])
                if payload.get("provider_request_id") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionDirectoryLayout:
    execution_id: str
    path: Path

    @property
    def metadata_path(self) -> Path:
        return self.path / "execution-metadata.json"

    @property
    def receipt_path(self) -> Path:
        return self.path / "process-receipt.json"

    @property
    def stdout_path(self) -> Path:
        return self.path / "stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.path / "stderr.log"

    @property
    def lock_path(self) -> Path:
        return self.path / ".execution.lock"

    def result_path(self, filename: str) -> Path:
        candidate = Path(filename)
        if not filename or candidate.name != filename or candidate.is_absolute():
            raise ValueError("result filename must be a single relative file name")
        return self.path / filename


class PersistentExecutionDirectory:
    """Stable filesystem storage for process output and crash recovery evidence."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def prepare(self, execution_id: str) -> ExecutionDirectoryLayout:
        if not str(execution_id).strip():
            raise ValueError("execution_id is required")
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", execution_id).strip("-._")[:48] or "execution"
        identity = _sha256_text(execution_id)[:16]
        path = (self.root / f"{slug}-{identity}").resolve()
        if path.parent != self.root:
            raise ValueError("execution directory escaped configured root")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        layout = ExecutionDirectoryLayout(execution_id=execution_id, path=path)
        with self.exclusive(layout):
            if layout.metadata_path.exists():
                metadata = self._read_json(layout.metadata_path)
                if metadata.get("execution_id") != execution_id:
                    raise ValueError("execution directory identity collision")
            else:
                self._atomic_json_write(
                    layout.metadata_path,
                    {"execution_id": execution_id, "request_digest": None, "created_at": _utc_now()},
                )
        return layout

    def bind_request(self, layout: ExecutionDirectoryLayout, request_digest: str) -> None:
        with self.exclusive(layout):
            self._bind_request_unlocked(layout, request_digest)

    def _bind_request_unlocked(self, layout: ExecutionDirectoryLayout, request_digest: str) -> None:
        if not _HEX_64.fullmatch(request_digest):
            raise ValueError("request digest must be SHA-256")
        metadata = self._read_json(layout.metadata_path)
        existing = metadata.get("request_digest")
        if existing and existing != request_digest:
            raise ValueError("execution request digest drift detected")
        if not existing:
            self._atomic_json_write(layout.metadata_path, {**metadata, "request_digest": request_digest})

    def read_receipt(self, execution_id: str) -> ProcessReceipt | None:
        layout = self.prepare(execution_id)
        with self.exclusive(layout):
            return self._read_receipt_unlocked(layout)

    def _read_receipt_unlocked(self, layout: ExecutionDirectoryLayout) -> ProcessReceipt | None:
        if not layout.receipt_path.exists():
            return None
        receipt = ProcessReceipt.from_dict(self._read_json(layout.receipt_path))
        metadata = self._read_json(layout.metadata_path)
        if metadata.get("request_digest") != receipt.request_digest:
            raise ValueError("process receipt request digest does not match execution metadata")
        self._validate_receipt_paths(layout, receipt)
        return receipt

    def write_receipt(self, receipt: ProcessReceipt) -> ExecutionDirectoryLayout:
        layout = self.prepare(receipt.execution_id)
        with self.exclusive(layout):
            self._bind_request_unlocked(layout, receipt.request_digest)
            self._write_receipt_unlocked(layout, receipt)
        return layout

    def _write_receipt_unlocked(
        self, layout: ExecutionDirectoryLayout, receipt: ProcessReceipt
    ) -> None:
        self._validate_receipt_paths(layout, receipt)
        self._atomic_json_write(layout.receipt_path, receipt.to_dict())

    @staticmethod
    def _validate_receipt_paths(
        layout: ExecutionDirectoryLayout, receipt: ProcessReceipt
    ) -> None:
        expected = {
            "execution_directory": str(layout.path),
            "receipt_path": str(layout.receipt_path),
            "stdout_path": str(layout.stdout_path),
            "stderr_path": str(layout.stderr_path),
        }
        for field_name, expected_path in expected.items():
            if getattr(receipt, field_name) != expected_path:
                raise ValueError(f"process receipt {field_name} escaped execution directory")
        expected_result = (
            str(layout.result_path(receipt.result_filename))
            if receipt.result_filename
            else None
        )
        if receipt.result_path != expected_result:
            raise ValueError("process receipt result_path escaped execution directory")

    @contextmanager
    def exclusive(self, layout: ExecutionDirectoryLayout):
        with layout.lock_path.open("a+", encoding="utf-8") as lock_handle:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def record_running_process(
        self,
        *,
        execution_id: str,
        pid: int,
        pgid: int,
        process_start_token: str,
        result_filename: str | None = None,
        result_format: str | None = "json",
        operation_id: str | None = None,
        attempt_id: str | None = None,
        fencing_token: int | None = None,
    ) -> ExecutionDirectoryLayout:
        """Import a running-process checkpoint for restart reconciliation."""

        layout = self.prepare(execution_id)
        request_digest = _canonical_hash({"execution_id": execution_id, "imported_running_process": True})
        result_path = str(layout.result_path(result_filename)) if result_filename else None
        receipt = ProcessReceipt(
            receipt_id=f"process-receipt:{request_digest[:24]}",
            execution_id=execution_id,
            operation_id=operation_id,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
            status=ProcessReceiptStatus.RUNNING,
            process_group=ProcessGroup(pid=pid, pgid=pgid, process_start_token=process_start_token),
            execution_directory=str(layout.path),
            receipt_path=str(layout.receipt_path),
            stdout_path=str(layout.stdout_path),
            stderr_path=str(layout.stderr_path),
            result_path=result_path,
            result_filename=result_filename,
            result_format=result_format if result_filename else None,
            result_integrity=ResultIntegrity.MISSING if result_filename else ResultIntegrity.NOT_REQUIRED,
            request_digest=request_digest,
            command_sha256=_sha256_text("imported-running-process"),
            input_sha256=_sha256_text(""),
            environment_keys=(),
            process_started_at=_utc_now(),
        )
        self.write_receipt(receipt)
        return layout

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object at {path}")
        return payload

    @staticmethod
    def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)


@dataclass(frozen=True, slots=True)
class ProcessLaunchRequest:
    execution_id: str
    command: tuple[str, ...]
    cwd: str
    input_text: str
    timeout: ProcessTimeout
    result_filename: str | None = None
    result_format: str | None = None
    environment_overrides: Mapping[str, str] | None = None
    operation_id: str | None = None
    attempt_id: str | None = None
    fencing_token: int | None = None

    def __post_init__(self) -> None:
        if not self.execution_id or not self.command or not self.cwd:
            raise ValueError("process launch request is incomplete")
        supplied = (self.operation_id is not None, self.attempt_id is not None, self.fencing_token is not None)
        if any(supplied) and not all(supplied):
            raise ValueError("process launch Authority Attempt binding must be complete")
        if isinstance(self.fencing_token, bool):
            raise ValueError("process launch fencing token must be an integer")
        if self.fencing_token is not None and self.fencing_token <= 0:
            raise ValueError("process launch fencing token must be positive")
        if self.result_filename:
            candidate = Path(self.result_filename)
            if candidate.name != self.result_filename or candidate.is_absolute():
                raise ValueError("result filename must be a single relative file name")
        elif self.result_format:
            raise ValueError("result format requires a result filename")

    @property
    def request_digest(self) -> str:
        return _canonical_hash(
            {
                "execution_id": self.execution_id,
                "operation_id": self.operation_id,
                "attempt_id": self.attempt_id,
                "fencing_token": self.fencing_token,
                "command": list(self.command),
                "cwd": str(Path(self.cwd).expanduser().resolve()),
                "input_sha256": _sha256_text(self.input_text),
                "result_filename": self.result_filename,
                "result_format": self.result_format,
                "timeout": {
                    "timeout_seconds": self.timeout.timeout_seconds,
                    "termination_grace_seconds": self.timeout.termination_grace_seconds,
                    "poll_interval_seconds": self.timeout.poll_interval_seconds,
                },
            }
        )


@dataclass(frozen=True, slots=True)
class SupervisedProcessResult:
    receipt: ProcessReceipt
    returncode: int | None
    stdout: str
    stderr: str
    duplicate_submission: bool = False


@dataclass(frozen=True, slots=True)
class ProcessRecoveryResult:
    receipt: ProcessReceipt
    result_recoverable: bool
    safe_to_signal: bool


class ProcessIdentityProbe(Protocol):
    def is_alive(self, pid: int) -> bool: ...

    def process_start_token(self, pid: int) -> str | None: ...


class PosixProcessIdentityProbe:
    def is_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def process_start_token(self, pid: int) -> str | None:
        ps_path = "/bin/ps" if Path("/bin/ps").exists() else "ps"
        try:
            completed = subprocess.run(
                [ps_path, "-o", "lstart=", "-p", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                env={"PATH": "/usr/bin:/bin", "LANG": "C"},
            )
        except Exception:
            return None
        value = completed.stdout.strip()
        return value or None


class CodexProcessSupervisor:
    def __init__(
        self,
        execution_directory: PersistentExecutionDirectory,
        *,
        environment_allowlist: EnvironmentAllowlist | None = None,
        identity_probe: ProcessIdentityProbe | None = None,
    ) -> None:
        self.execution_directory = execution_directory
        self.environment_allowlist = environment_allowlist or EnvironmentAllowlist.codex_default()
        self.identity_probe = identity_probe or PosixProcessIdentityProbe()

    def run(self, request: ProcessLaunchRequest, *, controller: Any | None = None) -> SupervisedProcessResult:
        layout = self.execution_directory.prepare(request.execution_id)
        existing: ProcessReceipt | None = None
        environment: dict[str, str] = {}
        process: subprocess.Popen[str] | None = None
        stdout_handle = None
        stderr_handle = None
        receipt: ProcessReceipt | None = None
        started_at = ""
        started_monotonic = 0.0
        with self.execution_directory.exclusive(layout):
            self.execution_directory._bind_request_unlocked(layout, request.request_digest)
            existing = self.execution_directory._read_receipt_unlocked(layout)
            if existing is None:
                environment = self.environment_allowlist.build(overrides=request.environment_overrides)
                started_at = _utc_now()
                started_monotonic = time.monotonic()
                stdout_handle = layout.stdout_path.open("w", encoding="utf-8")
                stderr_handle = layout.stderr_path.open("w", encoding="utf-8")
                try:
                    process = subprocess.Popen(
                        list(request.command),
                        stdin=subprocess.PIPE,
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        text=True,
                        cwd=str(Path(request.cwd).expanduser().resolve()),
                        env=environment,
                        start_new_session=True,
                    )
                except Exception:
                    stdout_handle.close()
                    stderr_handle.close()
                    raise

                pgid = os.getpgid(process.pid) if hasattr(os, "getpgid") else process.pid
                process_group = ProcessGroup(
                    pid=process.pid,
                    pgid=pgid,
                    process_start_token=self.identity_probe.process_start_token(process.pid) or "",
                )
                result_path = str(layout.result_path(request.result_filename)) if request.result_filename else None
                receipt = ProcessReceipt(
                    receipt_id=f"process-receipt:{request.request_digest[:24]}",
                    execution_id=request.execution_id,
                    operation_id=request.operation_id,
                    attempt_id=request.attempt_id,
                    fencing_token=request.fencing_token,
                    transport=ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
                    status=ProcessReceiptStatus.RUNNING,
                    process_group=process_group,
                    execution_directory=str(layout.path),
                    receipt_path=str(layout.receipt_path),
                    stdout_path=str(layout.stdout_path),
                    stderr_path=str(layout.stderr_path),
                    result_path=result_path,
                    result_filename=request.result_filename,
                    result_format=request.result_format,
                    result_integrity=ResultIntegrity.MISSING if request.result_filename else ResultIntegrity.NOT_REQUIRED,
                    request_digest=request.request_digest,
                    command_sha256=_canonical_hash({"command": list(request.command)}),
                    input_sha256=_sha256_text(request.input_text),
                    environment_keys=tuple(sorted(environment)),
                    process_started_at=started_at,
                    supervisor_pid=os.getpid(),
                    supervisor_process_start_token=(
                        self.identity_probe.process_start_token(os.getpid())
                    ),
                    last_supervisor_heartbeat_at=started_at,
                )
                self.execution_directory._write_receipt_unlocked(layout, receipt)
        if existing is not None:
            return self._await_existing(request)
        if process is None or receipt is None or stdout_handle is None or stderr_handle is None:
            raise RuntimeError("process launch reservation did not produce a running receipt")
        process_group = receipt.process_group

        control_failure: Exception | None = None
        termination_status: ProcessReceiptStatus | None = None
        termination_reason: str | None = None
        termination_signal: str | None = None
        last_heartbeat_monotonic = started_monotonic
        try:
            if process.stdin is not None:
                try:
                    process.stdin.write(request.input_text)
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            while process.poll() is None:
                elapsed = time.monotonic() - started_monotonic
                if elapsed >= request.timeout.timeout_seconds:
                    termination_status = ProcessReceiptStatus.TIMED_OUT
                    termination_reason = f"local process timed out after {request.timeout.timeout_seconds:g}s"
                    termination_signal = self._terminate_process_group(process, process_group, request.timeout)
                    break
                if controller is not None:
                    try:
                        controller.cancel_if_requested()
                        controller.observe_usage_delta(
                            {"elapsed_ms": int(elapsed * 1000), "usage_source": "process_poll"},
                            elapsed_ms=int(elapsed * 1000),
                        )
                    except Exception as exc:  # the provider controller owns the guard exception type
                        control_failure = exc
                        cancelled = str(getattr(controller, "status", "")) == "cancelled"
                        termination_status = ProcessReceiptStatus.CANCELLED if cancelled else ProcessReceiptStatus.FAILED
                        termination_reason = str(exc)
                        termination_signal = self._terminate_process_group(process, process_group, request.timeout)
                        break
                if time.monotonic() - last_heartbeat_monotonic >= 5.0:
                    receipt = replace(receipt, last_supervisor_heartbeat_at=_utc_now())
                    self.execution_directory.write_receipt(receipt)
                    last_heartbeat_monotonic = time.monotonic()
                time.sleep(request.timeout.poll_interval_seconds)
            returncode = process.wait(timeout=max(1.0, request.timeout.termination_grace_seconds + 1.0))
        finally:
            stdout_handle.close()
            stderr_handle.close()

        elapsed_ms = int((time.monotonic() - started_monotonic) * 1000)
        if termination_status is not None and termination_signal is None:
            termination_reason = f"{termination_reason or 'termination requested'}; process had already exited"
            termination_status = None
            control_failure = None
        status = termination_status or (
            ProcessReceiptStatus.SUCCEEDED if returncode == 0 else ProcessReceiptStatus.FAILED
        )
        integrity, integrity_failure = self._inspect_result(layout, request.result_filename, request.result_format)
        failure_reason = str(control_failure) if control_failure else None
        if status is ProcessReceiptStatus.FAILED and failure_reason is None and returncode != 0:
            failure_reason = f"local process exited with code {returncode}"
        if status is ProcessReceiptStatus.SUCCEEDED and integrity in {ResultIntegrity.MISSING, ResultIntegrity.CORRUPT}:
            status = ProcessReceiptStatus.CORRUPT_RESULT
            failure_reason = integrity_failure
        completed = replace(
            receipt,
            status=status,
            result_integrity=integrity,
            completed_at=_utc_now(),
            elapsed_ms=elapsed_ms,
            returncode=returncode,
            termination_signal=termination_signal,
            termination_reason=termination_reason,
            failure_reason=failure_reason,
            local_termination_only=termination_status in {
                ProcessReceiptStatus.CANCELLED,
                ProcessReceiptStatus.TIMED_OUT,
                ProcessReceiptStatus.FAILED,
            } and termination_signal is not None,
        )
        self.execution_directory.write_receipt(completed)
        return SupervisedProcessResult(
            receipt=completed,
            returncode=returncode,
            stdout=self._read_text(layout.stdout_path),
            stderr=self._read_text(layout.stderr_path),
        )

    def recover(self, execution_id: str) -> ProcessRecoveryResult:
        receipt = self.execution_directory.read_receipt(execution_id)
        if receipt is None:
            raise FileNotFoundError(f"no process receipt for {execution_id}")
        layout = self.execution_directory.prepare(execution_id)
        integrity, integrity_failure = self._inspect_result(
            layout, receipt.result_filename, receipt.result_format
        )
        if receipt.status is not ProcessReceiptStatus.RUNNING:
            if receipt.status is ProcessReceiptStatus.SUCCEEDED and integrity in {
                ResultIntegrity.MISSING,
                ResultIntegrity.CORRUPT,
            }:
                receipt = replace(
                    receipt,
                    status=ProcessReceiptStatus.CORRUPT_RESULT,
                    result_integrity=integrity,
                    failure_reason=integrity_failure,
                    recovery_reason="TERMINAL_RESULT_INTEGRITY_DRIFT",
                    completed_at=receipt.completed_at or _utc_now(),
                )
                self.execution_directory.write_receipt(receipt)
            return ProcessRecoveryResult(
                receipt=receipt,
                result_recoverable=integrity is ResultIntegrity.VALID,
                safe_to_signal=False,
            )

        pid = receipt.process_group.pid
        alive = self.identity_probe.is_alive(pid)
        current_start = self.identity_probe.process_start_token(pid) if alive else None
        recorded_start = receipt.process_group.process_start_token
        if alive and (not recorded_start or not current_start or current_start != recorded_start):
            recovered = replace(
                receipt,
                status=ProcessReceiptStatus.ORPHANED,
                result_integrity=integrity,
                recovery_reason="PID_REUSE_DETECTED" if recorded_start and current_start else "PROCESS_IDENTITY_UNVERIFIABLE",
                completed_at=_utc_now(),
            )
            self.execution_directory.write_receipt(recovered)
            return ProcessRecoveryResult(
                receipt=recovered,
                result_recoverable=integrity is ResultIntegrity.VALID,
                safe_to_signal=False,
            )
        if alive:
            return ProcessRecoveryResult(
                receipt=replace(receipt, result_integrity=integrity),
                result_recoverable=integrity is ResultIntegrity.VALID,
                safe_to_signal=True,
            )

        supervisor_alive = False
        if receipt.supervisor_pid is not None and receipt.supervisor_process_start_token:
            heartbeat_age = _age_seconds(receipt.last_supervisor_heartbeat_at)
            supervisor_alive = (
                heartbeat_age is not None
                and heartbeat_age <= 30.0
                and self.identity_probe.is_alive(receipt.supervisor_pid)
                and self.identity_probe.process_start_token(receipt.supervisor_pid)
                == receipt.supervisor_process_start_token
            )
        if supervisor_alive:
            return ProcessRecoveryResult(
                receipt=replace(receipt, result_integrity=integrity),
                result_recoverable=integrity is ResultIntegrity.VALID,
                safe_to_signal=False,
            )

        if integrity is ResultIntegrity.CORRUPT:
            status = ProcessReceiptStatus.CORRUPT_RESULT
            recovery_reason = "WORKER_CRASH_CORRUPT_RESULT"
        else:
            status = ProcessReceiptStatus.ORPHANED
            recovery_reason = (
                "WORKER_CRASH_RESULT_RECOVERABLE"
                if integrity is ResultIntegrity.VALID
                else "WORKER_CRASH_RESULT_MISSING"
            )
        recovered = replace(
            receipt,
            status=status,
            result_integrity=integrity,
            failure_reason=integrity_failure if integrity is ResultIntegrity.CORRUPT else receipt.failure_reason,
            recovery_reason=recovery_reason,
            completed_at=_utc_now(),
        )
        self.execution_directory.write_receipt(recovered)
        return ProcessRecoveryResult(
            receipt=recovered,
            result_recoverable=integrity is ResultIntegrity.VALID,
            safe_to_signal=False,
        )

    def _await_existing(self, request: ProcessLaunchRequest) -> SupervisedProcessResult:
        deadline = time.monotonic() + request.timeout.timeout_seconds
        recovery = self.recover(request.execution_id)
        while (
            recovery.receipt.status is ProcessReceiptStatus.RUNNING
            and time.monotonic() < deadline
        ):
            time.sleep(request.timeout.poll_interval_seconds)
            recovery = self.recover(request.execution_id)
        return SupervisedProcessResult(
            receipt=recovery.receipt,
            returncode=recovery.receipt.returncode,
            stdout=self._read_text(Path(recovery.receipt.stdout_path)),
            stderr=self._read_text(Path(recovery.receipt.stderr_path)),
            duplicate_submission=True,
        )

    def _terminate_process_group(
        self,
        process: subprocess.Popen[str],
        process_group: ProcessGroup,
        timeout: ProcessTimeout,
    ) -> str | None:
        if process.poll() is not None:
            return None
        current_start = self.identity_probe.process_start_token(process_group.pid)
        if (
            process_group.process_start_token
            and current_start
            and current_start != process_group.process_start_token
        ):
            return None
        last_signal: str | None = None
        if hasattr(os, "killpg"):
            try:
                os.killpg(process_group.pgid, signal.SIGTERM)
                last_signal = signal.Signals(signal.SIGTERM).name
            except ProcessLookupError:
                return last_signal
        else:  # pragma: no cover - exercised only on non-POSIX runtimes
            process.terminate()
            last_signal = signal.Signals(signal.SIGTERM).name
        deadline = time.monotonic() + timeout.termination_grace_seconds
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(min(timeout.poll_interval_seconds, max(0.001, deadline - time.monotonic())))
        if process.poll() is None:
            if hasattr(os, "killpg"):
                try:
                    os.killpg(process_group.pgid, signal.SIGKILL)
                    last_signal = signal.Signals(signal.SIGKILL).name
                except ProcessLookupError:
                    pass
            else:  # pragma: no cover - exercised only on non-POSIX runtimes
                process.kill()
                last_signal = signal.Signals(signal.SIGKILL).name
        return last_signal

    @staticmethod
    def _inspect_result(
        layout: ExecutionDirectoryLayout,
        result_filename: str | None,
        result_format: str | None,
    ) -> tuple[ResultIntegrity, str | None]:
        if not result_filename:
            return ResultIntegrity.NOT_REQUIRED, None
        result_path = layout.result_path(result_filename)
        if not result_path.exists():
            return ResultIntegrity.MISSING, "expected result file is missing"
        if result_format == "json":
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return ResultIntegrity.CORRUPT, f"result file is not valid JSON: {exc}"
            if not isinstance(payload, dict):
                return ResultIntegrity.CORRUPT, "result JSON must be an object"
        return ResultIntegrity.VALID, None

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
