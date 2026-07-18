"""Bounded background renewal for an already-fenced Authority lease."""
from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType

from novel_forge.modules.command_kernel.errors import KernelError


class LeaseHeartbeatGuard:
    """Renew a lease while a blocking handler/adapter owns its fencing token."""

    def __init__(
        self,
        renew: Callable[[], object],
        *,
        lease_seconds: int,
        label: str,
    ) -> None:
        if lease_seconds <= 0 or not label:
            raise ValueError("positive lease_seconds and label are required")
        self._renew = renew
        self._interval = max(0.05, min(float(lease_seconds) / 3.0, 10.0))
        self._label = label
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"authority-heartbeat:{label}",
            daemon=True,
        )

    def __enter__(self) -> "LeaseHeartbeatGuard":
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, traceback
        self._stop.set()
        self._thread.join(timeout=self._interval + 1.0)
        if exc is None and self._failure is not None:
            raise KernelError(
                "AUTHORITY_LEASE_HEARTBEAT_FAILED",
                f"{self._label} lease heartbeat failed: {self._failure}",
            ) from self._failure
        return False

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._renew()
            except Exception as exc:  # recorded and re-raised on the owning thread
                self._failure = exc
                self._stop.set()
                return


__all__ = ["LeaseHeartbeatGuard"]
