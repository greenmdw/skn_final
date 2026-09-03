from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.integrations.odoo.client import OdooJson2Client
from app.integrations.odoo.config import OdooSettings
from app.integrations.odoo.schemas import OdooConnectionStatus
from app.integrations.odoo.service import OdooConnectionService
from app.integrations.odoo.transport import HttpResponse


@dataclass
class ScriptedTransport:
    responses: list[HttpResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        return self.responses.pop(0)


def json_response(status_code: int, payload: Any) -> HttpResponse:
    return HttpResponse(
        status_code=status_code,
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )


def configured_settings(**overrides: Any) -> OdooSettings:
    values: dict[str, Any] = {
        "base_url": "https://odoo.example.test",
        "database": "demo",
        "api_key": "top-secret-api-key",
        "expected_major_version": 19,
    }
    values.update(overrides)
    return OdooSettings(**values)


class OdooSettingsTests(unittest.TestCase):
    def test_missing_settings_are_reported_without_exposing_a_secret(self) -> None:
        settings = OdooSettings.from_env({})
        result = OdooConnectionService(settings, OdooJson2Client(settings)).check()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, OdooConnectionStatus.NOT_CONFIGURED)
        self.assertIn("ODOO_BASE_URL is not configured", result.configuration_errors)
        self.assertIn("ODOO_API_KEY is not configured", result.configuration_errors)

    def test_plain_http_requires_an_explicit_development_override(self) -> None:
        settings = configured_settings(base_url="http://odoo.local")
        self.assertIn(
            "ODOO_BASE_URL must use HTTPS unless ODOO_ALLOW_INSECURE_HTTP=true",
            settings.configuration_errors(),
        )

    def test_credentials_embedded_in_base_url_are_rejected_and_hidden(self) -> None:
        settings = configured_settings(base_url="https://user:password@odoo.local")
        result = OdooConnectionService(settings, OdooJson2Client(settings)).check()

        self.assertIn("ODOO_BASE_URL must not include credentials", result.configuration_errors)
        self.assertIsNone(result.base_url)
        self.assertNotIn("password", result.model_dump_json())


class OdooConnectionServiceTests(unittest.TestCase):
    def test_success_checks_version_and_authenticated_user_context(self) -> None:
        transport = ScriptedTransport(
            responses=[
                json_response(
                    200,
                    {"version": "19.0", "version_info": [19, 0, 0, "final", 0, ""]},
                ),
                json_response(200, {"uid": 7, "allowed_company_ids": [1, 3]}),
            ]
        )
        settings = configured_settings()
        client = OdooJson2Client(settings, transport)

        result = OdooConnectionService(settings, client).check()

        self.assertTrue(result.ok)
        self.assertEqual(result.status, OdooConnectionStatus.OK)
        self.assertEqual(result.server_version, "19.0")
        self.assertEqual(result.user_id, 7)
        self.assertEqual(result.allowed_company_ids, [1, 3])
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["url"], "https://odoo.example.test/web/version")
        self.assertEqual(
            transport.calls[1]["url"],
            "https://odoo.example.test/json/2/res.users/context_get",
        )
        self.assertEqual(
            transport.calls[1]["headers"]["Authorization"],
            "bearer top-secret-api-key",
        )
        self.assertEqual(transport.calls[1]["headers"]["X-Odoo-Database"], "demo")
        self.assertEqual(json.loads(transport.calls[1]["body"]), {})

    def test_version_mismatch_stops_before_using_the_api_key(self) -> None:
        transport = ScriptedTransport(
            responses=[
                json_response(
                    200,
                    {"version": "18.0", "version_info": [18, 0, 0, "final", 0, ""]},
                )
            ]
        )
        settings = configured_settings()

        result = OdooConnectionService(
            settings, OdooJson2Client(settings, transport)
        ).check()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, OdooConnectionStatus.VERSION_MISMATCH)
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn("Authorization", transport.calls[0]["headers"])

    def test_unauthorized_response_is_sanitized(self) -> None:
        transport = ScriptedTransport(
            responses=[
                json_response(
                    200,
                    {"version": "19.0", "version_info": [19, 0, 0, "final", 0, ""]},
                ),
                json_response(
                    401,
                    {
                        "name": "Unauthorized",
                        "message": "Invalid apikey",
                        "debug": "traceback containing top-secret-api-key",
                    },
                ),
            ]
        )
        settings = configured_settings()

        result = OdooConnectionService(
            settings, OdooJson2Client(settings, transport)
        ).check()
        serialized = result.model_dump_json()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, OdooConnectionStatus.AUTH_FAILED)
        self.assertNotIn("top-secret-api-key", serialized)
        self.assertNotIn("traceback", serialized)

    def test_invalid_version_payload_is_reported(self) -> None:
        transport = ScriptedTransport(responses=[json_response(200, {"version": "19.0"})])
        settings = configured_settings()

        result = OdooConnectionService(
            settings, OdooJson2Client(settings, transport)
        ).check()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, OdooConnectionStatus.INVALID_RESPONSE)


class OdooHealthEndpointTests(unittest.TestCase):
    def test_endpoint_stays_available_and_reports_missing_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {"ODOO_BASE_URL": "", "ODOO_DATABASE": "", "ODOO_API_KEY": ""},
            clear=False,
        ):
            response = TestClient(app).get("/api/integrations/odoo/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "NOT_CONFIGURED")
        self.assertNotIn("api_key", response.json())


if __name__ == "__main__":
    unittest.main()
