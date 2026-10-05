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

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, Response, UploadFile

from src import schemas
from src.agent import spec_extraction_agent
from src.auth import ratelimit
from src.auth.deps import Principal, optional_principal
from src.categories import load_category
from src.config import LIVE_PART_LOOKUP_LIMIT_PER_MIN, PC_CHECK_LIMIT_PER_MIN
from src.db import get_conn
from src.engine.owned_parts import preview_current_specs
from src.engine.spec_text import parse_spec_text
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import RateLimited, ServiceUnavailable, ValidationFailed
from src.services import (
    quote_apply, quote_chat_service, quote_comparison_service, quote_draft_service, quote_review_service, recommendation_service,
)


def _check_rate_limit(request: Request) -> None:
    """비로그인 호출 가능 + LLM 호출(추출·대화)이 끼는 엔드포인트 공통 한도(발견 사항)."""
    key = f"pc-check:{ratelimit.client_ip(request)}"
    if not ratelimit.allow(key, limit=PC_CHECK_LIMIT_PER_MIN, window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")

def _check_live_lookup_limit(request: Request) -> None:
    """실시간 검색 버튼 전용 한도 — PC_CHECK_LIMIT_PER_MIN 보다 엄격하다(검색 1회가 비용이 크다)."""
    key = f"live-part-lookup:{ratelimit.client_ip(request)}"
    if not ratelimit.allow(key, limit=LIVE_PART_LOOKUP_LIMIT_PER_MIN, window_seconds=60):
        raise RateLimited("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")


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


@router.get("/reviews/capabilities", response_model=schemas.QuoteCapabilitiesOut)
def quote_capabilities() -> schemas.QuoteCapabilitiesOut:
    """이미지 인식을 쓸 수 있는지와 서버 제한값(BE-01). 반드시 `/reviews/{list_id}` 보다 먼저 선언한다."""
    return schemas.QuoteCapabilitiesOut(**quote_draft_service.capabilities())


def _read_upload(upload: UploadFile) -> tuple[str, str | None, bytes]:
    from src.config import QUOTE_DRAFT_MAX_FILE_BYTES
    data = upload.file.read(QUOTE_DRAFT_MAX_FILE_BYTES + 1)      # 상한보다 크면 한 바이트만 더 읽고 거부 — 통째로 메모리에 올리지 않는다
    return upload.filename or "image", upload.content_type, data


@router.post("/review-drafts", response_model=schemas.QuoteDraftOut, status_code=201)
def create_quote_draft(
    request: Request, response: Response,
    images: list[UploadFile] = File(default=[]),
    images_bracket: list[UploadFile] = File(default=[], alias="images[]"),
    text: str | None = Form(default=None),
    question: str | None = Form(default=None),
    conditions: str | None = Form(default=None),
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteDraftOut:
    """여러 장의 견적 이미지(+텍스트)를 인식해 항목 초안으로 저장한다(BE-02). 파일 하나가 실패해도 나머지는 유지한다.
    이미지 원본은 저장하지 않는다. 기존 단일 이미지 API(`/pc/reviews`)는 그대로 둔다."""
    _check_rate_limit(request)
    try:
        parsed_conditions = schemas.QuoteConditionsIn.model_validate(json.loads(conditions)).model_dump() if conditions else None
    except (ValueError, TypeError) as exc:
        raise ValidationFailed("conditions는 올바른 JSON이어야 합니다.", field="conditions") from exc
    files = [_read_upload(f) for f in [*images, *images_bracket]]
    with get_conn() as conn:
        session, draft = quote_draft_service.create_draft(conn, principal, files, text, question, parsed_conditions)
    if session["browser_token"]:
        response.set_cookie("truefit_guest", session["browser_token"],
                            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    return schemas.QuoteDraftOut(**quote_draft_service.draft_out(session["list_id"], draft))


@router.get("/review-drafts/{draft_id}", response_model=schemas.QuoteDraftOut)
def get_quote_draft(draft_id: UUID, principal: Principal = Depends(optional_principal)) -> schemas.QuoteDraftOut:
    with get_conn() as conn:
        draft = quote_draft_service.get_draft(conn, draft_id, principal)
    return schemas.QuoteDraftOut(**quote_draft_service.draft_out(str(draft_id), draft))


@router.patch("/review-drafts/{draft_id}/items", response_model=schemas.QuoteDraftOut)
def patch_quote_draft_items(
    draft_id: UUID, body: schemas.QuoteDraftPatchIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteDraftOut:
    """항목 일괄 수정과 부품군별 분석 기준 선택(BE-04) — 한 트랜잭션, 버전이 다르면 409 STALE_REVIEW_VERSION."""
    with get_conn() as conn:
        draft = quote_draft_service.patch_items(
            conn, draft_id, principal, body.expected_version, [e.model_dump(exclude_unset=True) for e in body.items],
            body.selected_item_by_category)
    return schemas.QuoteDraftOut(**quote_draft_service.draft_out(str(draft_id), draft))


@router.post("/review-drafts/{draft_id}/items", response_model=schemas.QuoteDraftOut, status_code=201)
def add_quote_draft_item(
    draft_id: UUID, body: schemas.QuoteDraftItemAddIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteDraftOut:
    """모델이 못 읽은 부품을 사용자가 직접 추가한다 — 읽은 항목과 같은 방식으로 이름·코드·수량·가격을 나누고 카탈로그와 맞춘다."""
    with get_conn() as conn:
        draft = quote_draft_service.add_item(conn, draft_id, principal, body.expected_version, body.category, body.raw_text, body.source_id)
    return schemas.QuoteDraftOut(**quote_draft_service.draft_out(str(draft_id), draft))


@router.post("/review-drafts/{draft_id}/analysis", response_model=schemas.QuoteDraftAnalysisOut)
def analyze_quote_draft(
    draft_id: UUID, request: Request, body: schemas.QuoteDraftAnalysisIn | None = None,
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteDraftAnalysisOut:
    """분석 기준으로 고른 항목만 호환성·가격·균형·우리 추천 비교로 분석하고 같은 세션(list_id)에 저장한다(BE-07).
    `source_ids`를 주면 그 견적(이미지)의 항목만 — 서로 다른 견적을 올렸을 때 하나를 골라 분석한다."""
    _check_rate_limit(request)
    with get_conn() as conn:
        result = quote_draft_service.analyze_selected(conn, draft_id, principal, body.source_ids if body else None)
    return schemas.QuoteDraftAnalysisOut(**result)


@router.post("/review-drafts/{draft_id}/quote-comparisons", response_model=schemas.QuoteSavedComparisonOut, status_code=201)
def compare_draft_quotes(
    draft_id: UUID, body: schemas.QuoteQuoteComparisonIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteSavedComparisonOut:
    """한 초안에 올린 서로 다른 두 견적(A안·B안)을 제품 ID 기준으로 비교한다 — 저장 견적 비교와 같은 모양, 각 견적의 합계·호환 요약 포함."""
    with get_conn() as conn:
        result = quote_comparison_service.compare_quotes(conn, draft_id, principal, body.a_source_ids, body.b_source_ids)
    return schemas.QuoteSavedComparisonOut(**result)


@router.get("/review-drafts/{draft_id}/categories/{category}/comparison", response_model=schemas.QuoteDraftComparisonOut)
def compare_quote_draft_category(
    draft_id: UUID, category: str, baseline_item_id: str | None = Query(default=None),
    direction: Literal["cheaper", "better"] | None = Query(default=None),
    target_product_id: list[str] = Query(default=[], max_length=4),
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteDraftComparisonOut:
    """분석 전에 한 부품군의 인식 제품과 추천 제품을 나란히(BE-05). 조회만 한다."""
    with get_conn() as conn:
        result = quote_draft_service.comparison(conn, draft_id, principal, category, baseline_item_id, direction, target_product_id)
    return schemas.QuoteDraftComparisonOut(**result)


@router.post("/review-drafts/{draft_id}/replacements/preview", response_model=schemas.QuoteReplacementPreviewOut)
def preview_quote_draft_replacements(
    draft_id: UUID, body: schemas.QuoteReplacementsPreviewIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteReplacementPreviewOut:
    """여러 교체 후보를 한꺼번에 적용했을 때의 합계·호환 변화(BE-06). 조회만 한다."""
    with get_conn() as conn:
        result = quote_draft_service.replacement_preview(conn, draft_id, principal, [r.model_dump() for r in body.replacements])
    return schemas.QuoteReplacementPreviewOut(**result)


@router.post("/review-drafts/{draft_id}/replacements/apply", response_model=schemas.QuoteDraftOut)
def apply_quote_draft_replacements(
    draft_id: UUID, body: schemas.QuoteReplacementsApplyIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteDraftOut:
    """정확한 제품 ID로 초안의 항목을 교체한다(BE-06). 분석은 이어서 `/analysis`로 요청한다."""
    with get_conn() as conn:
        draft = quote_draft_service.replacement_apply(
            conn, draft_id, principal, body.expected_version, [r.model_dump() for r in body.replacements])
    return schemas.QuoteDraftOut(**quote_draft_service.draft_out(str(draft_id), draft))


@router.post("/review-drafts/{draft_id}/items/{item_id}/live-lookup", response_model=schemas.LiveSpecLookupOut)
def live_lookup_draft_item(
    draft_id: UUID, item_id: str, request: Request, principal: Principal = Depends(optional_principal),
) -> schemas.LiveSpecLookupOut:
    """초안의 항목 하나를 실시간 검색+검증한다 — 사용자가 버튼을 눌렀을 때만(같은 부품군에 제품이 여럿이라 항목 단위)."""
    _check_live_lookup_limit(request)
    with get_conn() as conn:
        result = quote_draft_service.live_lookup_item(conn, draft_id, principal, item_id)
    return schemas.LiveSpecLookupOut(**result)


@router.post("/reviews", response_model=schemas.QuoteReviewOut, status_code=201)
def create_quote_review(
    body: schemas.QuoteReviewIn, request: Request, response: Response,
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteReviewOut:
    """견적(텍스트·이미지·슬롯별 입력)을 분석해 새 세션에 저장한다 — 매칭 표와 호환 검사(CHK-04·CHK-09)."""
    _check_rate_limit(request)
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
    list_id: UUID, body: schemas.QuoteReviewIn, request: Request,
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteReviewOut:
    """인식 결과를 고친 견적으로 같은 세션의 분석을 다시 계산해 저장한다."""
    _check_rate_limit(request)
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


@router.post("/reviews/{list_id}/apply", response_model=schemas.QuoteApplyOut, status_code=201)
def apply_quote_alternative(
    list_id: UUID, body: schemas.QuoteApplyIn, response: Response, background_tasks: BackgroundTasks,
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteApplyOut:
    """비교 결과의 대안을 받아들여 새 계획을 만든다(CHK-08) — 고른 부품은 업그레이드 대상, 나머지는 견적 그대로 유지.
    업그레이드 추천(mode=upgrade)을 재사용한다. 필수 조건이 다 있으면 바로 추천을 시작한다."""
    with get_conn() as conn:
        result = quote_apply.apply_alternative(conn, list_id, principal, body.slots)
    if result["browser_token"]:
        response.set_cookie("truefit_guest", result["browser_token"],
                            httponly=True, samesite="lax", max_age=60 * 60 * 24 * 180)
    if result["run_id"]:
        background_tasks.add_task(recommendation_service.execute_recommendation,
                                  UUID(result["revision_id"]), UUID(result["run_id"]))
    return schemas.QuoteApplyOut(list_id=result["list_id"], slots=result["slots"], missing=result["missing"],
                                 run_id=result["run_id"])


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


@router.post("/reviews/{list_id}/parts/{slot}/live-lookup", response_model=schemas.LiveSpecLookupOut)
def live_lookup_quote_part(
    list_id: UUID, slot: str, request: Request, principal: Principal = Depends(optional_principal),
) -> schemas.LiveSpecLookupOut:
    """카탈로그에 "대응 안 됨"으로 뜬 부품을 사용자가 버튼으로 눌렀을 때만 실시간 검색+검증한다
    (docs/미보유부품_실시간스펙검색_설계.md §2 — 자동 실행 금지, PC_CHECK_LIMIT_PER_MIN보다
    엄격한 전용 한도를 쓴다). 캐시 히트면 검색·LLM 호출 없이 바로 응답한다."""
    _check_live_lookup_limit(request)
    with get_conn() as conn:
        result = quote_review_service.live_lookup_part(conn, list_id, principal, slot)
    return schemas.LiveSpecLookupOut(**result)


@router.post("/reviews/{list_id}/messages", response_model=schemas.QuoteChatOut)
def ask_about_quote_review(
    list_id: UUID, body: schemas.QuoteChatIn, request: Request,
    principal: Principal = Depends(optional_principal),
) -> schemas.QuoteChatOut:
    """저장된 비교 분석 결과를 근거로 되묻는다 — 답과 근거, 대안 조회(CHAT-04). 대화는 저장된다(CHAT-08)."""
    _check_rate_limit(request)
    context = body.context.model_dump() if body.context else None
    with get_conn() as conn:
        result = quote_chat_service.chat(conn, list_id, principal, body.text,
                                         client_message_id=body.client_message_id, context=context)
    return schemas.QuoteChatOut(**result)


@router.post("/reviews/{list_id}/saved-comparisons", response_model=schemas.QuoteSavedComparisonOut, status_code=201)
def create_saved_comparison(
    list_id: UUID, body: schemas.QuoteSavedComparisonIn, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteSavedComparisonOut:
    """받은 견적과 저장한 견적(확정 견적서)을 제품 ID 기준으로 비교한다(BE-09). 로그인한 소유자만 — 양쪽 소유권을 검증한다."""
    with get_conn() as conn:
        result = quote_comparison_service.create_comparison(conn, list_id, principal, body.saved_list_id, body.saved_revision_no)
    return schemas.QuoteSavedComparisonOut(**result)


@router.get("/reviews/{list_id}/saved-comparisons/{comparison_id}", response_model=schemas.QuoteSavedComparisonOut)
def get_saved_comparison(
    list_id: UUID, comparison_id: UUID, principal: Principal = Depends(optional_principal),
) -> schemas.QuoteSavedComparisonOut:
    with get_conn() as conn:
        result = quote_comparison_service.get_comparison(conn, list_id, principal, str(comparison_id))
    return schemas.QuoteSavedComparisonOut(**result)


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
