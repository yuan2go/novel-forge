import os
from pathlib import Path
import subprocess
from threading import Lock


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


_active_provider_invocations: set[str] = set()
_provider_invocation_lock = Lock()
_provider_process_probe = PosixProcessIdentityProbe()


def current_process_start_token() -> str | None:
    return _provider_process_probe.process_start_token(os.getpid())


def begin_provider_invocation(execution_id: str) -> None:
    with _provider_invocation_lock:
        if execution_id in _active_provider_invocations:
            raise ValueError("PROVIDER_INVOCATION_ALREADY_INFLIGHT")
        _active_provider_invocations.add(execution_id)


def finish_provider_invocation(execution_id: str) -> None:
    with _provider_invocation_lock:
        _active_provider_invocations.discard(execution_id)


def provider_invocation_inflight(record):
    process_id = (record.get("raw_evidence") or {}).get("invocation_process_id")
    execution_id = (record.get("request") or {}).get("execution_id")
    if process_id == os.getpid():
        with _provider_invocation_lock:
            return execution_id in _active_provider_invocations
    if type(process_id) is not int or (record.get("raw_evidence") or {}).get("invocation_finished"):
        return False
    if not _provider_process_probe.is_alive(process_id):
        return False
    expected_token = (record.get("raw_evidence") or {}).get("invocation_process_start_identity")
    current_token = _provider_process_probe.process_start_token(process_id)
    return not expected_token or not current_token or expected_token == current_token
