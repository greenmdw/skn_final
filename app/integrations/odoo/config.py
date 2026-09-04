from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return -1.0


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return -1


class OdooSettings(BaseModel):
    """Environment-backed Odoo settings without leaking the API key."""

    model_config = ConfigDict(frozen=True)

    base_url: str = ""
    database: str | None = None
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 10.0
    verify_tls: bool = True
    allow_insecure_http: bool = False
    expected_major_version: int = 19
    user_agent: str = "skn-final/0.1.0"

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("database")
    @classmethod
    def normalize_database(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "OdooSettings":
        source = os.environ if environ is None else environ
        return cls(
            base_url=source.get("ODOO_BASE_URL", ""),
            database=source.get("ODOO_DATABASE"),
            api_key=SecretStr(source.get("ODOO_API_KEY", "")),
            connect_timeout_seconds=_parse_float(
                source.get("ODOO_CONNECT_TIMEOUT_SECONDS"), default=3.0
            ),
            read_timeout_seconds=_parse_float(
                source.get("ODOO_READ_TIMEOUT_SECONDS"), default=10.0
            ),
            verify_tls=_parse_bool(source.get("ODOO_VERIFY_TLS"), default=True),
            allow_insecure_http=_parse_bool(
                source.get("ODOO_ALLOW_INSECURE_HTTP"), default=False
            ),
            expected_major_version=_parse_int(
                source.get("ODOO_EXPECTED_MAJOR_VERSION"), default=19
            ),
            user_agent=source.get("ODOO_USER_AGENT", "skn-final/0.1.0"),
        )

    @property
    def api_key_value(self) -> str:
        return self.api_key.get_secret_value()

    def configuration_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.base_url:
            errors.append("ODOO_BASE_URL is not configured")
        else:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append("ODOO_BASE_URL must be an absolute HTTP(S) URL")
            elif parsed.username or parsed.password:
                errors.append("ODOO_BASE_URL must not include credentials")
            elif parsed.scheme != "https" and not self.allow_insecure_http:
                errors.append(
                    "ODOO_BASE_URL must use HTTPS unless ODOO_ALLOW_INSECURE_HTTP=true"
                )
        if not self.api_key_value:
            errors.append("ODOO_API_KEY is not configured")
        if self.connect_timeout_seconds <= 0:
            errors.append("ODOO_CONNECT_TIMEOUT_SECONDS must be greater than zero")
        if self.read_timeout_seconds <= 0:
            errors.append("ODOO_READ_TIMEOUT_SECONDS must be greater than zero")
        if self.expected_major_version <= 0:
            errors.append("ODOO_EXPECTED_MAJOR_VERSION must be greater than zero")
        return errors

    @property
    def public_base_url(self) -> str | None:
        if not self.base_url:
            return None
        parsed = urlparse(self.base_url)
        if parsed.username or parsed.password:
            return None
        return self.base_url
