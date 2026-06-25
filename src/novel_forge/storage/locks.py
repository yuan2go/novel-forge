from __future__ import annotations

import shutil
import time
from pathlib import Path


class StorageLockTimeout(TimeoutError):
    """Raised when a local storage lock cannot be acquired in time."""


class StorageLock:
    def __init__(self, root: Path, name: str, timeout_seconds: float = 5.0, poll_seconds: float = 0.05) -> None:
        self.lock_path = root / "data" / ".locks" / f"{_safe_name(name)}.lock"
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def __enter__(self) -> StorageLock:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self.lock_path.mkdir()
                (self.lock_path / "created_at").write_text(str(time.time()), encoding="utf-8")
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise StorageLockTimeout(f"could not acquire storage lock: {self.lock_path}")
                time.sleep(self.poll_seconds)

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.lock_path, ignore_errors=True)


def _safe_name(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in name)[:120] or "storage"
