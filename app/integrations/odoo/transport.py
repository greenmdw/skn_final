from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import OdooTransportError


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    content_type: str | None = None


class OdooTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
        verify_tls: bool,
    ) -> HttpResponse: ...


class UrllibOdooTransport:
    """Dependency-free transport; replaceable by a pooled async client later."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: float,
        verify_tls: bool,
    ) -> HttpResponse:
        request = Request(url=url, data=body, headers=headers, method=method)
        context = ssl.create_default_context()
        if not verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        try:
            with urlopen(request, timeout=timeout_seconds, context=context) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=response.read(),
                    content_type=response.headers.get("Content-Type"),
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
                content_type=exc.headers.get("Content-Type") if exc.headers else None,
            )
        except (URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
            raise OdooTransportError("Unable to connect to the configured Odoo host") from exc
