"""INVARIANT: Bounded background renewal for an already-fenced Authority lease."""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import TracebackType

from novel_forge.modules.command_kernel.errors import KernelError


class LeaseHeartbeatGuard:

    def __init__(
        self,
        renew: Callable[[], object],
        *,
        lease_seconds: int,
        label: str,
        probe: Callable[[], object] | None = None,
        probe_on_exit: bool = True,
    ) -> None:
        if lease_seconds <= 0 or not label:
            raise ValueError("positive lease_seconds and label are required")
        self._renew = renew
        self._interval = max(0.05, min(float(lease_seconds) / 3.0, 10.0))
        self._label = label
        self._probe = probe
        self._probe_on_exit = probe_on_exit
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
        if exc is None:
            self._assert_background_healthy()
            if self._probe_on_exit and self._probe is not None:
                self._probe()
        return False

    def assert_healthy(self) -> None:

        self._assert_background_healthy()
        if self._probe is not None:
            self._probe()

    def _assert_background_healthy(self) -> None:
        if self._failure is not None:
            raise KernelError(
                "AUTHORITY_LEASE_HEARTBEAT_FAILED",
                f"{self._label} lease heartbeat failed: {self._failure}",
            ) from self._failure

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if self._probe is not None:
                    self._probe()
                self._renew()
            except Exception as exc:  # recorded and re-raised on the owning thread
                self._failure = exc
                self._stop.set()
                return


__all__ = ["LeaseHeartbeatGuard"]
