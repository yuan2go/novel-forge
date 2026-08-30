from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from typing import Mapping, Protocol, Sequence


class LocalCommandError(RuntimeError):

    def __init__(self, message: str, *, request_sent: bool) -> None:
        super().__init__(message)
        self.request_sent = request_sent


class LocalCommandExecutionPort(Protocol):
    def execute(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        environment: Mapping[str, str],
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class BoundedLocalCommandExecutionPort:

    allowed_executables: tuple[str, ...]
    maximum_output_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.allowed_executables or any(
            not executable or "/" in executable
            for executable in self.allowed_executables
        ):
            raise ValueError("local command executable allowlist is invalid")
        if self.maximum_output_bytes <= 0:
            raise ValueError("local command output limit must be positive")

    def execute(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: int,
        environment: Mapping[str, str],
    ) -> bytes:
        admitted = tuple(str(token) for token in command)
        if (
            not admitted
            or admitted[0] not in self.allowed_executables
            or any("\x00" in token for token in admitted)
        ):
            raise LocalCommandError(
                "local command is not admitted by execution policy",
                request_sent=False,
            )
        if timeout_seconds <= 0:
            raise LocalCommandError(
                "local command timeout must be positive",
                request_sent=False,
            )
        try:
            completed = subprocess.run(
                admitted,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                env={str(key): str(value) for key, value in environment.items()},
            )
        except OSError as exc:
            raise LocalCommandError(
                f"local command could not start: {type(exc).__name__}: {exc}",
                request_sent=False,
            ) from exc
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise LocalCommandError(
                f"local command failed: {type(exc).__name__}: {exc}",
                request_sent=True,
            ) from exc
        if len(completed.stdout) > self.maximum_output_bytes:
            raise LocalCommandError(
                "local command output exceeded execution policy",
                request_sent=True,
            )
        return bytes(completed.stdout)


def git_command_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:

    values = os.environ if source is None else source
    allowed = (
        "PATH",
        "HOME",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    )
    environment = {
        name: str(values[name])
        for name in allowed
        if values.get(name) is not None
    }
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "LC_ALL": "C",
        }
    )
    return environment


__all__ = [
    "BoundedLocalCommandExecutionPort",
    "LocalCommandError",
    "LocalCommandExecutionPort",
    "git_command_environment",
]
