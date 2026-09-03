from __future__ import annotations

from fastapi import APIRouter, Response

from .client import OdooJson2Client
from .config import OdooSettings
from .schemas import OdooHealthResponse
from .service import OdooConnectionService


router = APIRouter(prefix="/api/integrations/odoo", tags=["integrations"])


def build_connection_service() -> OdooConnectionService:
    settings = OdooSettings.from_env()
    client = OdooJson2Client(settings)
    return OdooConnectionService(settings, client)


@router.get("/health", response_model=OdooHealthResponse)
def odoo_health(response: Response) -> OdooHealthResponse:
    """Verify Odoo 19, bearer authentication, DB routing and current-user context."""

    result = build_connection_service().check()
    response.status_code = result.http_status_code
    return result

