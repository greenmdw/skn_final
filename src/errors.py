"""공통 에러 봉투 + 도메인 예외.

API 응답 에러 형식: {"error": {"code": str, "message": str, "field": str | null}}
FastAPI 예외 핸들러(src/api.py)가 아래 예외를 이 형식으로 변환한다.
"""
from __future__ import annotations


class TruefitError(Exception):
    """모든 도메인 예외의 베이스."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, field: str | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        if code is not None:
            self.code = code

    def to_envelope(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "field": self.field}}


class NotFound(TruefitError):
    code = "not_found"
    http_status = 404


class ValidationFailed(TruefitError):
    code = "validation_failed"
    http_status = 422


class Unauthorized(TruefitError):
    code = "unauthorized"
    http_status = 401


class Forbidden(TruefitError):
    code = "forbidden"
    http_status = 403


class Conflict(TruefitError):
    code = "conflict"
    http_status = 409


class RateLimited(TruefitError):
    code = "rate_limited"
    http_status = 429


class AccountLocked(TruefitError):
    code = "account_locked"
    http_status = 423


class FileTooLarge(TruefitError):
    code = "file_too_large"
    http_status = 413


class ServiceUnavailable(TruefitError):
    """이 요청을 처리할 방법이 지금 서버에 아예 없을 때(예: 이미지 인식에 필요한 LLM 연결이
    꺼져 있음) — 규칙 기반 fallback이 없어 "확인 못 함"으로 조용히 넘길 수 없는 경우에 쓴다."""

    code = "service_unavailable"
    http_status = 503
