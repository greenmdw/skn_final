"""FastAPI 앱 조립 — 라우터 include + 공통 에러 핸들러.

실행:  uvicorn src.api:app --reload   →   http://127.0.0.1:8000/docs

라우터:
  /auth/*     이메일+비밀번호 → JWT(httpOnly 쿠키 `truefit_session`)
  /session/*  S1~S3 대화·조건 수집 + [추천 실행]   (인증 불요)
  /lists/*    사이드바 목록(비로그인 가능) · S5-a 확정 · S5-b 리포트 · 알림(로그인 필수)
  /reviews/*  A7 리뷰 작성·게시                     (JWT 필수)
  /community/* 일반 커뮤니티 게시글·댓글·추천·조회   (읽기는 공개, 쓰기는 로그인)  /catalog/products 연결 제품 검색
  /peripherals/*  주변기기 제품 검색(공개 카탈로그)·견적 문장 해석 (인증 불요)
  /dev/*      시나리오 기반 파이프라인 (DB 미사용, 개발용)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from src.auth.origin import OriginCheckMiddleware
from src.config import (
    APP_NAME, IS_PRODUCTION, RECOMMEND_REAP_INTERVAL_SECONDS, RECOMMEND_STALE_SECONDS, RECOMMEND_STARTUP_STALE_SECONDS,
    WEB_DIST_DIR, assert_production_secret_safe,
)
from src.db import close_pool
from src.errors import TruefitError
from src.frontend_serving import mount_frontend
from src.routers import auth, community, dev, lists, me, pc_check, peripherals, reviews, session


log = logging.getLogger(__name__)


def _attach_recommendation_log_handler() -> None:
    """추천 시간 계측 로그(core_ready·post_done 등 INFO)가 `uvicorn src.api:app` 출력에 나오게 한다 — 앱에 로깅 설정이 없어
    INFO 가 버려졌다. 이 로거에만 INFO 핸들러를 붙이고 전역 설정(basicConfig 등)·다른 로거·propagate 는 그대로 둔다.
    이 로거나 상위(root)에 핸들러가 이미 있으면(다시 import 했거나 운영이 로깅을 따로 설정했으면) 붙이지 않는다 — 같은 메시지가 두 번 찍히지 않게."""
    logger = logging.getLogger("src.services.recommendation_service")
    if logger.hasHandlers():
        return
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


_attach_recommendation_log_handler()


def _reap(older_than_seconds: int) -> None:
    from src.services import recommendation_service

    try:
        recommendation_service.reap_stale_runs(older_than_seconds)
    except Exception:  # noqa: BLE001 — DB 가 없거나 막혀도 서버는 떠야 한다. 다음 주기에 다시 한다.
        log.warning("stale recommendation reap failed", exc_info=True)


async def _reap_periodically() -> None:
    while True:
        await asyncio.sleep(RECOMMEND_REAP_INTERVAL_SECONDS)
        await asyncio.to_thread(_reap, RECOMMEND_STALE_SECONDS)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    assert_production_secret_safe()
    await asyncio.to_thread(_reap, RECOMMEND_STARTUP_STALE_SECONDS)       # 재시작으로 끊긴 실행을 먼저 정리
    reaper = asyncio.create_task(_reap_periodically())
    yield
    reaper.cancel()
    close_pool()


app = FastAPI(title=f"{APP_NAME} API (skeleton)", lifespan=_lifespan)
# 응답 압축 — 추천 결과(GET /result)처럼 큰 JSON 응답의 전송량을 줄인다(리뷰 계산 snapshot 은 응답에서 이미 뺐고, 남은 결과도
# 수십 KB 다). 작은 응답(1KB 미만)은 압축하지 않는다.
# 압축은 브라우저가 Accept-Encoding 으로 받겠다고 할 때만 한다. 앞단 프록시도 압축한다면 운영에서 한쪽만 쓰도록 확인한다.
# 출처 검사보다 먼저 등록해 안쪽에 둔다 — 바깥에 두면 출처 검사가 응답을 조각으로 다시 흘려보내 크기(minimum_size)를 못 보고
# 작은 응답까지 압축했다.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(OriginCheckMiddleware)

app.include_router(auth.router)
app.include_router(session.router)
app.include_router(lists.router)
app.include_router(reviews.router)
app.include_router(pc_check.router)
app.include_router(peripherals.router)
app.include_router(community.router)
app.include_router(community.catalog_router)
app.include_router(me.router)
# /dev/* 는 DB 없이 파이프라인을 돌리는 개발용 진입점이라 운영(APP_ENV=production)에는 열지 않는다.
if not IS_PRODUCTION:
    app.include_router(dev.router)


@app.exception_handler(TruefitError)
def _truefit_error_handler(_req: Request, exc: TruefitError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_envelope(), headers=getattr(exc, "headers", None))


@app.exception_handler(PoolTimeout)
def _pool_timeout_handler(_req: Request, _exc: PoolTimeout) -> JSONResponse:
    """DB 연결을 기다리다 포기 — 서버 오류(500)가 아니라 "지금 몰려 있으니 잠시 뒤 다시"(503)로 알린다.
    풀 상태(크기·빈 연결·기다리는 요청)를 로그에 남긴다 — 풀이 정말 찼는지, 연결을 새로 여는 게 느린지 가르는 단서다."""
    from src.db import get_pool

    log.warning("db pool timeout: %s", get_pool().get_stats())
    return JSONResponse(
        status_code=503, headers={"Retry-After": "2"},
        content={"error": {"code": "service_busy", "message": "지금 요청이 몰려 있어요. 잠시 뒤 다시 시도해 주세요.", "field": None}},
    )


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
# web/dist 가 있으면 React 앱을 서빙하고, 없으면 API만 뜬다 (src/frontend_serving.py).
FRONTEND_SERVING = mount_frontend(app, web_dist=WEB_DIST_DIR)
