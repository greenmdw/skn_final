from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any

from .client import OdooJson2Client
from .config import OdooSettings
from .errors import OdooHttpError, OdooInvalidResponseError, OdooTransportError
from .schemas import OdooConnectionStatus, OdooHealthResponse


class OdooConnectionService:
    """Read-only Odoo connection probe used by the integration health endpoint."""

    def __init__(self, settings: OdooSettings, client: OdooJson2Client) -> None:
        self.settings = settings
        self.client = client

    def check(self) -> OdooHealthResponse:
        started = perf_counter()
        configuration_errors = self.settings.configuration_errors()
        if configuration_errors:
            return self._response(
                started,
                ok=False,
                status=OdooConnectionStatus.NOT_CONFIGURED,
                message="Odoo integration settings are incomplete or invalid",
                configuration_errors=configuration_errors,
            )

        try:
            version_payload = self.client.get_server_version()
            version, version_info = self._parse_version(version_payload)
            if not version_info or version_info[0] != self.settings.expected_major_version:
                return self._response(
                    started,
                    ok=False,
                    status=OdooConnectionStatus.VERSION_MISMATCH,
                    message=(
                        f"Expected Odoo {self.settings.expected_major_version}, "
                        f"but the server reported {version or 'an unknown version'}"
                    ),
                    server_version=version,
                    version_info=version_info,
                )

            context = self.client.call("res.users", "context_get")
            if not isinstance(context, Mapping):
                raise OdooInvalidResponseError(
                    "Odoo res.users/context_get returned an unexpected payload"
                )
            user_id = context.get("uid")
            allowed_company_ids = context.get("allowed_company_ids", [])
            if not isinstance(user_id, int):
                raise OdooInvalidResponseError("Odoo context did not include the current user id")
            if not isinstance(allowed_company_ids, list) or not all(
                isinstance(item, int) for item in allowed_company_ids
            ):
                raise OdooInvalidResponseError(
                    "Odoo context included invalid allowed_company_ids"
                )

            return self._response(
                started,
                ok=True,
                status=OdooConnectionStatus.OK,
                message="Connected to Odoo 19 JSON-2 successfully",
                server_version=version,
                version_info=version_info,
                user_id=user_id,
                allowed_company_ids=allowed_company_ids,
            )
        except OdooTransportError:
            return self._response(
                started,
                ok=False,
                status=OdooConnectionStatus.UNREACHABLE,
                message="The configured Odoo host could not be reached",
            )
        except OdooInvalidResponseError:
            return self._response(
                started,
                ok=False,
                status=OdooConnectionStatus.INVALID_RESPONSE,
                message="Odoo returned an unexpected response",
            )
        except OdooHttpError as exc:
            if exc.status_code == 401:
                status = OdooConnectionStatus.AUTH_FAILED
                message = "Odoo rejected the configured API key"
            elif exc.status_code == 403:
                status = OdooConnectionStatus.FORBIDDEN
                message = "The Odoo bot does not have permission for the connection probe"
            else:
                status = OdooConnectionStatus.ODOO_ERROR
                message = f"Odoo returned HTTP {exc.status_code}"
            return self._response(started, ok=False, status=status, message=message)

    def _response(
        self,
        started: float,
        *,
        ok: bool,
        status: OdooConnectionStatus,
        message: str,
        configuration_errors: list[str] | None = None,
        server_version: str | None = None,
        version_info: list[int | str] | None = None,
        user_id: int | None = None,
        allowed_company_ids: list[int] | None = None,
    ) -> OdooHealthResponse:
        return OdooHealthResponse(
            ok=ok,
            status=status,
            base_url=self.settings.public_base_url,
            database=self.settings.database,
            server_version=server_version,
            version_info=version_info or [],
            user_id=user_id,
            allowed_company_ids=allowed_company_ids or [],
            duration_ms=max(0, round((perf_counter() - started) * 1000)),
            message=message,
            configuration_errors=configuration_errors or [],
        )

    @staticmethod
    def _parse_version(payload: Any) -> tuple[str | None, list[int | str]]:
        if not isinstance(payload, Mapping):
            raise OdooInvalidResponseError("Odoo /web/version returned an unexpected payload")
        version = payload.get("version")
        version_info = payload.get("version_info")
        if version is not None and not isinstance(version, str):
            raise OdooInvalidResponseError("Odoo version was not a string")
        if not isinstance(version_info, list) or not all(
            isinstance(item, (int, str)) for item in version_info
        ):
            raise OdooInvalidResponseError("Odoo version_info was invalid")
        return version, version_info
