"""주변기기 공개 API.

- `GET /peripherals/catalog/search` — 커뮤니티 글쓰기의 제품 선택용 검색(작업지시서 W-1). 로그인 없이 부를 수 있고
  공개 카탈로그 정보만 낸다. 가격이 없는 상품도 낸다 — 사용기를 쓸 수 있는 제품은 가격과 무관하다.
- `POST /peripherals/interpret` — 견적 문장 한 줄을 정해진 목록의 값으로 읽는다(견적 입력 설계 4장). 로그인 없이
  부를 수 있고, 언어 모델을 쓰므로 주소별 분당 요청 수를 제한한다.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request

from src import schemas
from src.auth import ratelimit
from src.db import get_conn
from src.engine.peripheral_rules import interpretation_settings
from src.errors import RateLimited
from src.repo import catalog_repo
from src.services import peripheral_interpret_service

router = APIRouter(prefix="/peripherals", tags=["peripherals"])


@router.get("/catalog/search", response_model=schemas.PeripheralCatalogSearchOut)
def search_catalog(
    kind: Literal["monitor", "keyboard", "mouse", "speaker"],
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=10, ge=1, le=30),
) -> schemas.PeripheralCatalogSearchOut:
    with get_conn() as conn:
        rows = catalog_repo.search_peripheral_products(conn, kind, q, limit)
    return schemas.PeripheralCatalogSearchOut(items=[schemas.PeripheralCatalogItemOut(**r) for r in rows])


@router.post("/interpret", response_model=schemas.PeripheralInterpretOut)
def interpret(body: schemas.PeripheralInterpretIn, request: Request) -> schemas.PeripheralInterpretOut:
    key = f"peripheral-interpret:{ratelimit.client_ip(request)}"
    if not ratelimit.allow(key, limit=interpretation_settings()["per_minute"], window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    return schemas.PeripheralInterpretOut(**peripheral_interpret_service.interpret(body.text, body.previous, body.kinds))
