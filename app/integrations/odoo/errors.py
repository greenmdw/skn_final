from __future__ import annotations


class OdooError(Exception):
    """Base exception for the Odoo integration boundary."""


class OdooTransportError(OdooError):
    """The Odoo host could not be reached or the TLS connection failed."""


class OdooInvalidResponseError(OdooError):
    """Odoo returned a response that does not match the expected JSON shape."""


class OdooHttpError(OdooError):
    """An Odoo HTTP error with a sanitized message."""

    def __init__(self, status_code: int, error_type: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.status_code = status_code
        self.error_type = error_type
        self.safe_message = safe_message

