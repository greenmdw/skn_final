"""Odoo 19 JSON-2 integration skeleton."""

from .client import OdooJson2Client
from .config import OdooSettings
from .service import OdooConnectionService

__all__ = ["OdooConnectionService", "OdooJson2Client", "OdooSettings"]

