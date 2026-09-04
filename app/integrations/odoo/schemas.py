from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class OdooConnectionStatus(str, Enum):
    OK = "OK"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    UNREACHABLE = "UNREACHABLE"
    AUTH_FAILED = "AUTH_FAILED"
    FORBIDDEN = "FORBIDDEN"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    ODOO_ERROR = "ODOO_ERROR"


class OdooHealthResponse(BaseModel):
    ok: bool
    status: OdooConnectionStatus
    api: str = "json-2"
    base_url: str | None = None
    database: str | None = None
    server_version: str | None = None
    version_info: list[int | str] = Field(default_factory=list)
    user_id: int | None = None
    allowed_company_ids: list[int] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: int = 0
    message: str
    configuration_errors: list[str] = Field(default_factory=list)

    @property
    def http_status_code(self) -> int:
        if self.ok:
            return 200
        if self.status in {
            OdooConnectionStatus.NOT_CONFIGURED,
            OdooConnectionStatus.VERSION_MISMATCH,
            OdooConnectionStatus.UNREACHABLE,
        }:
            return 503
        return 502

