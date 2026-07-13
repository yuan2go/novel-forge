from __future__ import annotations


class KernelError(RuntimeError):
    """Stable fail-closed Command Kernel error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
