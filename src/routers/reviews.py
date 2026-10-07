"""/reviews/* — A7 부품/전체 PC 리뷰 작성·게시. JWT 필수.

리뷰 상세 조회(S5, 정제 전후 평점·요약 3건)는 /session 결과에 포함되거나 별도 GET.
작성 요청의 선택 필드 `telemetry`(schemas.ReviewTelemetry)는 폼 계측값 — 횟수·시간만 받고
`review_revision.usage_context.telemetry` 로 저장한다. 프론트는 붙여넣기·키 입력 이벤트를
세기만 하고 내용은 보내지 않는다.

조회 전용 공개 엔드포인트(리뷰 요약 `GET /summary/{product_key}`, 리뷰 검색 `GET /search`)는 인증 없이 둔다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from uuid import UUID

from src import schemas
from src.auth import ratelimit
from src.config import REVIEW_SEARCH_DEFAULT_LIMIT, REVIEW_SEARCH_LIMIT_PER_MIN
from src.errors import RateLimited
from src.services import review_search, review_service
from src.auth.deps import current_user

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _check_search_limit(request: Request) -> None:
    """리뷰 검색 전용 한도 — 로그인 없이 부를 수 있는데 요청마다 유료 embedding 호출이 하나 생긴다."""
    key = f"review-search:{ratelimit.client_ip(request)}"
    if not ratelimit.allow(key, limit=REVIEW_SEARCH_LIMIT_PER_MIN, window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")


@router.get("/search", response_model=schemas.ReviewSearchOut)
def search_reviews(
    request: Request,
    product_id: list[UUID] = Query(..., description="검색할 상품(catalog.product.id). 여러 개면 반복해서 준다"),
    q: str = Query(..., description="질문 — 예: 코일 소음 있나요"),
    limit: int = Query(REVIEW_SEARCH_DEFAULT_LIMIT, description="상품당 돌려줄 리뷰 수"),
) -> schemas.ReviewSearchOut:
    """상품별로 질문과 뜻이 가까운 실제 리뷰 — `?product_id=<uuid>&product_id=<uuid>&q=소음&limit=3`.

    상품마다 status(ok·no_match·no_reviews·not_indexed)와 coverage(실제 리뷰 수·검색 준비된 수)를 함께 낸다.
    similarity는 정렬용이지 추천 점수가 아니다. 카탈로그에 없는 상품은 404, embedding을 만들 수 없거나 저장된
    벡터가 지금 설정과 다르게 만들어졌으면 503(review_search_unavailable·review_index_mismatch).
    """
    _check_search_limit(request)
    return schemas.ReviewSearchOut(**review_search.search(product_ids=product_id, query=q, limit=limit))


@router.get("/pending")
def pending(user_id: UUID = Depends(current_user)) -> dict:
    """작성해야 할 리뷰 / 개봉 확인 / 내가 쓴 리뷰."""
    return review_service.list_pending_for_user(user_id)


@router.post("/part", status_code=status.HTTP_201_CREATED)
def write_part(body: schemas.PartReviewIn, user_id: UUID = Depends(current_user)) -> dict:
    return review_service.write_part_review(user_id, UUID(body.variant_id), rating=body.rating, title=body.title,
                                             body=body.body, axis_scores=body.axis_scores, telemetry=body.telemetry)


@router.post("/build")
def write_build(body: schemas.BuildReviewIn) -> dict:
    raise NotImplementedError


@router.post("/{review_id}/publish")
def publish(review_id: UUID, user_id: UUID = Depends(current_user)) -> dict:
    review_service.publish(review_id, user_id)
    return {"review_id": str(review_id), "status": "published"}


@router.get("/summary/{product_key}", response_model=schemas.ReviewSummaryOut)
def review_summary(product_key: str) -> schemas.ReviewSummaryOut:
    """S5 리뷰 상세 — 실측 관측(관계·행동 축)과 합성 데모 블록을 분리해 낸다.

    product_key 는 엔진 키(`amd-ryzen-5-5600`)·요약 키·ASIN 모두 받는다.
    읽기 전용 공개 데이터라 인증 없이 둔다 (auth 구현 후 optional_principal 로 소유 세션 연결).
    """
    return review_service.get_summary(product_key)
