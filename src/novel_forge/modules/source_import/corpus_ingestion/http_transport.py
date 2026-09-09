from __future__ import annotations

from contextlib import contextmanager
import http.client
import ipaddress
import json
import os
import socket
import ssl
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from .contracts import IngestionFailure


class CorpusHttpTransport:
    def __init__(self, *, token: str = "") -> None:
        self.token = token

    @staticmethod
    def _host_allowed(host: str) -> bool:
        return host in {"huggingface.co", "archive.org"} or any(
            host.endswith(suffix)
            for suffix in (".huggingface.co", ".hf.co", ".archive.org")
        )

    @contextmanager
    def open(
        self, url: str, *, timeout: int, method: str = "GET"
    ) -> Iterator[http.client.HTTPResponse]:
        current = url
        connection = None
        response = None
        try:
            for _ in range(6):
                parsed = urlsplit(current)
                host = parsed.hostname or ""
                if (
                    parsed.scheme != "https"
                    or not self._host_allowed(host)
                    or parsed.username
                    or parsed.password
                    or parsed.port not in {None, 443}
                ):
                    raise IngestionFailure("REMOTE_ORIGIN_FORBIDDEN")
                addresses = sorted(
                    {
                        row[4][0]
                        for row in socket.getaddrinfo(
                            host, 443, type=socket.SOCK_STREAM
                        )
                    }
                )
                if not addresses or any(
                    not ipaddress.ip_address(address).is_global for address in addresses
                ):
                    raise IngestionFailure(
                        "REMOTE_ADDRESS_FORBIDDEN",
                        json.dumps(
                            {
                                "host": host,
                                "stage": "DNS_ADMISSION",
                                "address_count": len(addresses),
                                "non_global_addresses": [
                                    a
                                    for a in addresses
                                    if not ipaddress.ip_address(a).is_global
                                ],
                                "proxy_environment_present": any(
                                    os.environ.get(k)
                                    for k in (
                                        "HTTPS_PROXY",
                                        "https_proxy",
                                        "ALL_PROXY",
                                        "all_proxy",
                                    )
                                ),
                                "recovery": "repair DNS/proxy routing; private-address admission remains forbidden",
                            },
                            sort_keys=True,
                        ),
                    )
                connection = http.client.HTTPSConnection(
                    host, timeout=timeout, context=ssl.create_default_context()
                )
                address = addresses[0]

                def connect(
                    _address: Any,
                    timeout: Any = timeout,
                    source_address: Any = None,
                    **_kwargs: Any,
                ) -> socket.socket:
                    return socket.create_connection(
                        (address, 443), timeout=timeout, source_address=source_address
                    )

                connection._create_connection = connect
                headers = {
                    "User-Agent": "NovelForge-Corpus/1",
                    "Accept-Encoding": "identity",
                }
                if self.token and host == "huggingface.co":
                    headers["Authorization"] = "Bearer " + self.token
                target = parsed.path or "/"
                if parsed.query:
                    target += "?" + parsed.query
                connection.request(method, target, headers=headers)
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise IngestionFailure("REDIRECT_WITHOUT_LOCATION")
                    current = urljoin(current, location)
                    response.close()
                    connection.close()
                    continue
                if response.status in {401, 403}:
                    raise IngestionFailure(
                        "REMOTE_ACCESS_NOT_AUTHORIZED", str(response.status)
                    )
                if response.status != 200:
                    raise IngestionFailure("REMOTE_HTTP_FAILURE", str(response.status))
                yield response
                return
            raise IngestionFailure("REDIRECT_LIMIT")
        except socket.gaierror as exc:
            raise IngestionFailure(
                "REMOTE_DNS_FAILURE",
                json.dumps(
                    {
                        "host": urlsplit(current).hostname,
                        "errno": exc.errno,
                        "stage": "DNS",
                    }
                ),
            ) from exc
        except ssl.SSLError as exc:
            raise IngestionFailure(
                "REMOTE_TLS_FAILURE",
                "certificate/TLS negotiation failed; verification remains required",
            ) from exc
        except TimeoutError as exc:
            raise IngestionFailure(
                "REMOTE_TIMEOUT", "bounded connection/read deadline exceeded"
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise IngestionFailure(
                "REMOTE_TRANSPORT_FAILURE", type(exc).__name__
            ) from exc
        finally:
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()

    def metadata(self, url: str, *, timeout: int) -> dict[str, Any]:
        with self.open(url, timeout=timeout) as response:
            data = response.read(4_000_001)
        if len(data) > 4_000_000:
            raise IngestionFailure("REMOTE_METADATA_LIMIT")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise IngestionFailure("REMOTE_METADATA_NOT_OBJECT")
        return value
