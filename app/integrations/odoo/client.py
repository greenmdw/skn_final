from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from .config import OdooSettings
from .errors import OdooHttpError, OdooInvalidResponseError
from .transport import OdooTransport, UrllibOdooTransport


_MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9_.]+$")
_METHOD_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


class OdooJson2Client:
    """Small JSON-2 client shared by future CRM, stock and purchase gateways."""

    def __init__(
        self,
        settings: OdooSettings,
        transport: OdooTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibOdooTransport()

    def get_server_version(self) -> dict[str, Any]:
        response = self.transport.request(
            method="GET",
            url=f"{self.settings.base_url}/web/version",
            headers={"Accept": "application/json", "User-Agent": self.settings.user_agent},
            body=None,
            timeout_seconds=self._timeout_seconds,
            verify_tls=self.settings.verify_tls,
        )
        return self._decode_response(response.status_code, response.body)

    def call(
        self,
        model: str,
        method: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        if not _MODEL_PATTERN.fullmatch(model):
            raise ValueError("Invalid Odoo model name")
        if not _METHOD_PATTERN.fullmatch(method):
            raise ValueError("Invalid Odoo method name")

        headers = {
            "Accept": "application/json",
            "Authorization": f"bearer {self.settings.api_key_value}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": self.settings.user_agent,
        }
        if self.settings.database:
            headers["X-Odoo-Database"] = self.settings.database

        response = self.transport.request(
            method="POST",
            url=f"{self.settings.base_url}/json/2/{model}/{method}",
            headers=headers,
            body=json.dumps(dict(parameters or {}), ensure_ascii=False).encode("utf-8"),
            timeout_seconds=self._timeout_seconds,
            verify_tls=self.settings.verify_tls,
        )
        return self._decode_response(response.status_code, response.body)

    @property
    def _timeout_seconds(self) -> float:
        # urllib exposes one request timeout. A pooled transport can split these later.
        return max(
            self.settings.connect_timeout_seconds,
            self.settings.read_timeout_seconds,
        )

    @staticmethod
    def _decode_response(status_code: int, body: bytes) -> Any:
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if status_code >= 400:
                raise OdooHttpError(
                    status_code,
                    "HTTP_ERROR",
                    f"Odoo returned HTTP {status_code}",
                ) from exc
            raise OdooInvalidResponseError("Odoo returned non-JSON data") from exc

        if status_code >= 400:
            error_type = "ODOO_ERROR"
            message = f"Odoo returned HTTP {status_code}"
            if isinstance(payload, dict):
                error_type = str(payload.get("name") or payload.get("type") or error_type)
                candidate = payload.get("message")
                if isinstance(candidate, str) and candidate.strip():
                    message = candidate.strip()
            # Never propagate Odoo's `debug` or traceback field.
            raise OdooHttpError(status_code, error_type, message)
        return payload

