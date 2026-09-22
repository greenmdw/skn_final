"""PC 견적 점검 — 세션 없이 쓰는 매칭 미리보기 (사양 텍스트/자유 문장/화면 캡처 → 화면 표).

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

from fastapi import APIRouter

from src import schemas
from src.agent import spec_extraction_agent
from src.categories import load_category
from src.engine.owned_parts import preview_current_specs
from src.engine.spec_text import parse_spec_text
from src.engine.stage3_0_candidates import load_pc_catalog
from src.errors import ServiceUnavailable, ValidationFailed

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


@router.post("/owned-parts/preview", response_model=schemas.OwnedPartsPreviewOut)
def preview_owned_parts(body: schemas.OwnedPartsPreviewIn) -> schemas.OwnedPartsPreviewOut:
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

    by_slot = load_pc_catalog(lambda _msg: None)
    slot_structure = load_category("computer")["slot_structure"]
    rows = preview_current_specs(current_specs, by_slot, slot_structure)
    return schemas.OwnedPartsPreviewOut(rows=[schemas.OwnedPartsPreviewRow(**row) for row in rows])
