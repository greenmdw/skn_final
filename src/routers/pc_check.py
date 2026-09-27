"""PC 견적 점검 — 세션 없이 쓰는 매칭 미리보기 (사양 텍스트/자유 문장/화면 캡처 → 화면 표).

`/pc/reviews` 는 같은 입력을 세션에 저장하는 비교 분석(호환 검사 · CHK-04, 결과 저장 · CHK-09)이다 —
아래 "아무것도 저장하지 않는다"는 `/pc/owned-parts/preview` 에만 해당한다.

CheckPage/ReviewPage는 카테고리·세션을 아직 만들지 않은 단계(파일/텍스트/이미지를 올려 "확인된
PC 구성" 표를 보는 시점)에서 이 API를 부른다. 판정은 owned_parts.preview_current_specs — 실제
업그레이드 추천 실행(session_service.handle_message → owned_for_conditions)과 같은 매칭
함수를 쓴다. 로그인·소유권 확인이 필요 없다(계산만 하고 아무것도 저장하지 않는다) — 이미지도
요청 처리 중에만 메모리에 있다가 버려진다.

`text`(자유 형식 견적 설명 전체)가 오면 슬롯별로 먼저 추출한다 — LLM 추출 에이전트가 있으면
그걸로, 없거나 실패하면 규칙 기반 파서로(session_service.attach_spec_file과 같은 fallback
원칙). `image_data_url`(화면 캡처)은 다르다 — 규칙으로 이미지를 읽을 방법이 없어서, 에이전트가
꺼져 있거나 실패하면 "확인 못 함"으로 조용히 넘기지 않고 503으로 알린다(호출자가 "빈 결과"와
"서버가 아예 못 봤다"를 구분할 수 있게). `current_specs`에 같은 슬롯이 이미 명시돼 있으면 그
값이 추출값을 덮지 않는다."""
from __future__ import annotations

import logging
import re

from uuid import UUID

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from src import schemas
from src.agent import spec_extraction_agent
from src.auth.deps import Principal, optional_principal
from src.categories import load_category
from src.db import get_conn
from src.engine.owned_parts import preview_current_specs
from src.engine.spec_text import parse_spec_text
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import ServiceUnavailable, ValidationFailed
from src.services import quote_chat_service, quote_review_service

log = logging.getLogger(__name__)
router = APIRouter(prefix="/pc", tags=["pc-check"])

_MAX_TEXT_CHARS = 20_000        # 견적 설명 정도의 길이면 충분하다 — 사진첩·문서 전체를 붙여넣는 걸 막는다
_MAX_IMAGE_DATA_URL_CHARS = 7_000_000   # base64는 원본의 약 4/3배 — 대략 5MB 이미지까지
_IMAGE_DATA_URL = re.compile(r"^data:image/(png|jpe?g|webp);base64,")


def _extract_current_specs_from_text(text: str) -> dict[str, str]:
    if spec_extraction_agent.available():
        try:
            extracted = spec_extraction_agent.extract(text)
            if extracted:
                return extracted
        except Exception as exc:  # noqa: BLE001 — 모델·네트워크 오류. 이번 요청만 규칙 경로로.
            log.warning("spec extraction agent (text) failed, falling back to rules: %s", exc)
    return parse_spec_text(text)


def _extract_current_specs_from_image(image_data_url: str) -> dict[str, str]:
    if not spec_extraction_agent.available():
        raise ServiceUnavailable(
            "이미지 인식은 지금 이 서버에서 켜져 있지 않습니다. 텍스트로 적어서 다시 시도해주세요.",
            code="image_extraction_unavailable")
    try:
        return spec_extraction_agent.extract_from_image(image_data_url)
    except Exception as exc:  # noqa: BLE001 — 이미지는 규칙 기반 대안이 없다: 조용히 빈 결과로
        # 넘기면 "사진에 부품이 없었다"와 "서버가 이미지를 못 봤다"가 구분이 안 된다.
        log.warning("spec extraction agent (image) failed: %s", exc)
        raise ServiceUnavailable("이미지를 확인하지 못했습니다. 잠시 후 다시 시도해주세요.",
                                 code="image_extraction_failed") from exc


def _resolve_current_specs(body: schemas.OwnedPartsPreviewIn) -> dict[str, str]:
    """요청(명시 슬롯 + 텍스트 또는 이미지) → 슬롯별 견적 텍스트. 미리보기와 견적 점검 저장이 같이 쓴다."""
    if body.text and len(body.text) > _MAX_TEXT_CHARS:
        raise ValidationFailed(f"텍스트가 너무 깁니다({_MAX_TEXT_CHARS:,}자 이하로 줄여주세요).", field="text")
    if body.image_data_url:
        if len(body.image_data_url) > _MAX_IMAGE_DATA_URL_CHARS:
            raise ValidationFailed("이미지가 너무 큽니다(5MB 이하로 올려주세요).", field="image_data_url")
        if not _IMAGE_DATA_URL.match(body.image_data_url):
            raise ValidationFailed("PNG·JPEG·WebP 이미지만 지원합니다.", field="image_data_url")

    current_specs = dict(body.current_specs)
    if body.image_data_url:
        for slot, value in _extract_current_specs_from_image(body.image_data_url).items():
            current_specs.setdefault(slot, value)
    elif body.text and body.text.strip():
        for slot, value in _extract_current_specs_from_text(body.text).items():
            current_specs.setdefault(slot, value)   # 명시적으로 넘긴 슬롯이 추출값보다 우선한다
    return current_specs


def _review_out(list_id: str, review: dict) -> schemas.QuoteReviewOut:
    return schemas.QuoteReviewOut(
        list_id=list_id, version=review["version"], input=review["input"], parts=review["parts"],
        compat=review["compat"], prices=review.get("prices"), balance=review.get("balance"), compare=review.get("compare"),
        computed_at=review["computed_at"],
    )


@router.post("/reviews", response_model=schemas.QuoteReviewOut, status_code=201)
def create_quote_review(
    body: schemas.QuoteReviewIn, response: Response, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteReviewOut:
    """견적(텍스트·이미지·슬롯별 입력)을 분석해 새 세션에 저장한다 — 매칭 표와 호환 검사(CHK-04·CHK-09)."""
    current_specs = _resolve_current_specs(body)
    with get_conn() as conn:
        session, review = quote_review_service.create_review(
            conn, principal, current_specs, body.conditions.model_dump() if body.conditions else None)
    if session["browser_token"]:
        response.set_cookie("truefit_guest", session["browser_token"],
                            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return _review_out(session["list_id"], review)


@router.put("/reviews/{list_id}", response_model=schemas.QuoteReviewOut)
def update_quote_review(
    list_id: UUID, body: schemas.QuoteReviewIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteReviewOut:
    """인식 결과를 고친 견적으로 같은 세션의 분석을 다시 계산해 저장한다."""
    current_specs = _resolve_current_specs(body)
    with get_conn() as conn:
        review = quote_review_service.update_review(
            conn, list_id, principal, current_specs, body.conditions.model_dump() if body.conditions else None)
    return _review_out(str(list_id), review)


@router.get("/reviews/{list_id}", response_model=schemas.QuoteReviewOut)
def get_quote_review(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.QuoteReviewOut:
    with get_conn() as conn:
        review = quote_review_service.get_review(conn, list_id, principal)
    return _review_out(str(list_id), review)


@router.get("/reviews/{list_id}/parts/{slot}/compare", response_model=schemas.QuotePartCompareOut)
def compare_quote_part(
    list_id: UUID, slot: str, target: list[str] = Query(default_factory=list, max_length=4),
    direction: Literal["cheaper", "better"] | None = None, principal: Principal = Depends(optional_principal),
) -> schemas.QuotePartCompareOut:
    """견적 속 부품 하나를 같은 부품군의 다른 제품과 스펙·가격·리뷰로 나란히 비교한다(CHK-10). `target` 으로 비교할 제품을
    직접 고르고, 안 주면 `direction`(더 저렴한/더 좋은)에 맞는 후보를 고른다. 조회만 한다."""
    with get_conn() as conn:
        result = quote_review_service.compare_part(conn, list_id, principal, slot, target, direction)
    return schemas.QuotePartCompareOut(**result)


@router.post("/reviews/{list_id}/messages", response_model=schemas.QuoteChatOut)
def ask_about_quote_review(
    list_id: UUID, body: schemas.QuoteChatIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteChatOut:
    """저장된 비교 분석 결과를 근거로 되묻는다 — 답과 근거, 대안 조회(CHAT-04). 대화는 저장된다(CHAT-08)."""
    with get_conn() as conn:
        result = quote_chat_service.chat(conn, list_id, principal, body.text)
    return schemas.QuoteChatOut(**result)


@router.get("/reviews/{list_id}/messages", response_model=schemas.QuoteChatHistoryOut)
def quote_review_history(list_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.QuoteChatHistoryOut:
    """저장한 견적 점검을 다시 열 때 복원할 이전 대화."""
    with get_conn() as conn:
        return schemas.QuoteChatHistoryOut(messages=quote_chat_service.history(conn, list_id, principal))


@router.post("/owned-parts/preview", response_model=schemas.OwnedPartsPreviewOut)
def preview_owned_parts(body: schemas.OwnedPartsPreviewIn) -> schemas.OwnedPartsPreviewOut:
    current_specs = _resolve_current_specs(body)
    by_slot = load_pc_catalog(lambda _msg: None)
    slot_structure = load_category("computer")["slot_structure"]
    rows = preview_current_specs(current_specs, by_slot, slot_structure)
    return schemas.OwnedPartsPreviewOut(rows=[schemas.OwnedPartsPreviewRow(**row) for row in rows])
