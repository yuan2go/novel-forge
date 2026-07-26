"""Quarantined development-only HTTP transport.

Production domains must use ProductionExecutionGateway.  This transport exists
only while local-first compatibility callers are strangled and always checks the
controlled-environment boundary before opening a socket.
"""

from __future__ import annotations

from dataclasses import dataclass
import urllib.error
import urllib.request
from typing import Mapping

from novel_forge.modules.production_execution.security import (
    assert_legacy_execution_allowed,
)


@dataclass(frozen=True, slots=True)
class LegacyHttpResponse:
    status: int
    body: bytes


class LegacyHttpRequestError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, body: bytes = b"") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def development_only_http_request(
    *,
    component: str,
    url: str,
    method: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
    environment: str = "",
) -> LegacyHttpResponse:
    assert_legacy_execution_allowed(
        component=component,
        gateway_backed=False,
        environment=environment,
    )
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={str(key): str(value) for key, value in headers.items()},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout_seconds
        ) as response:
            return LegacyHttpResponse(
                status=int(response.status),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        response_body = exc.read()
        raise LegacyHttpRequestError(
            f"{component} returned HTTP {exc.code}",
            status=int(exc.code),
            body=response_body,
        ) from exc
    except urllib.error.URLError as exc:
        raise LegacyHttpRequestError(
            f"{component} request failed: {exc}"
        ) from exc


__all__ = [
    "LegacyHttpRequestError",
    "LegacyHttpResponse",
    "development_only_http_request",
]
