"""FastAPI 앱 조립 — 라우터 include + 공통 에러 핸들러.

실행:  uvicorn src.api:app --reload   →   http://127.0.0.1:8000/docs

라우터:
  /auth/*     이메일+비밀번호 → JWT(httpOnly 쿠키 `truefit_session`)
  /session/*  S1~S3 대화·조건 수집 + [추천 실행]   (인증 불요)
  /lists/*    사이드바 목록(비로그인 가능) · S5-a 확정 · S5-b 리포트 · 알림(로그인 필수)
  /reviews/*  A7 리뷰 작성·게시                     (JWT 필수)
  /dev/*      시나리오 기반 파이프라인 (DB 미사용, 개발용)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.auth.origin import OriginCheckMiddleware
from src.config import (
    APP_NAME, FRONTEND_DIR, FRONTEND_MODE, IS_PRODUCTION, WEB_DIST_DIR, assert_production_secret_safe,
)
from src.db import close_pool
from src.errors import TruefitError
from src.frontend_serving import mount_frontend
from src.routers import auth, dev, lists, pc_check, reviews, session


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    assert_production_secret_safe()
    yield
    close_pool()


app = FastAPI(title=f"{APP_NAME} API (skeleton)", lifespan=_lifespan)
app.add_middleware(OriginCheckMiddleware)

app.include_router(auth.router)
app.include_router(session.router)
app.include_router(lists.router)
app.include_router(reviews.router)
app.include_router(pc_check.router)
# /dev/* 는 DB 없이 파이프라인을 돌리는 개발용 진입점이라 운영(APP_ENV=production)에는 열지 않는다.
if not IS_PRODUCTION:
    app.include_router(dev.router)


@app.exception_handler(TruefitError)
def _truefit_error_handler(_req: Request, exc: TruefitError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_envelope())


@app.exception_handler(NotImplementedError)
def _not_impl_handler(_req: Request, exc: NotImplementedError) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": str(exc) or "미구현", "field": None}},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": APP_NAME}


# 프론트는 API 라우터를 모두 등록한 뒤 마지막에 붙인다 — API 경로가 정적 파일·SPA 폴백보다 우선한다.
# web/dist 가 있으면 새 React 앱, 없으면 옛 frontend/ (src/frontend_serving.py).
FRONTEND_SERVING = mount_frontend(app, web_dist=WEB_DIST_DIR, legacy_dir=FRONTEND_DIR, mode=FRONTEND_MODE)
