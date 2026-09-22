"""견적 점검: 자유 텍스트(업로드 파일·유튜브 견적 설명 등)에서 PC 부품 사양을 슬롯별로 뽑는다.

§D-3 "판정·수치는 코드, LLM은 서술" 과 같은 경계 — 여기서는 서술이 아니라 "추출"이지만 원칙은
같다: 텍스트에서 슬롯별 문구를 뽑을 뿐, 그 문구가 실제 어떤 카탈로그 제품인지·호환되는지는
판단하지 않는다. 판정은 owned_parts.resolve_owned_parts(=견적 점검 매칭 미리보기)가 한다.

conditions_agent와 같은 필요 조건(MOCK_MODE=0, OPENAI_API_KEY·LLM_MODEL)에
SPEC_EXTRACTION_AGENT=1까지 필요하다. `available()`이 False이거나 `extract()`가 예외를
올리면 호출자(session_service·pc_check 라우터)가 규칙 기반 파서(src.engine.spec_text)로
이번 요청만 처리한다 — call_llm과 같은 "구조화 출력 검증 실패 시 규칙 템플릿" 원칙이다.
"""
from __future__ import annotations

from pydantic import BaseModel

from src.clients.llm_client import call_llm, call_llm_vision
from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY, SPEC_EXTRACTION_AGENT
from src.engine.prompts import SPEC_EXTRACTION_IMAGE_SYSTEM, SPEC_EXTRACTION_SYSTEM

# 사용자가 붙여넣을 만한 견적 설명(유튜브 설명란 등)은 길 수 있다 — 토큰·비용 상한.
_MAX_INPUT_CHARS = 4000


class _SpecExtraction(BaseModel):
    """슬롯 이름을 그대로 필드명으로 쓴다 — computer의 slot_structure와 한 글자도 다르면 안 된다."""

    CPU: str | None = None
    GPU: str | None = None
    RAM: str | None = None
    메인보드: str | None = None
    저장장치: str | None = None
    파워: str | None = None
    케이스: str | None = None
    쿨러: str | None = None


# 이미지 전용 영문 스키마. 실측(2026-09-22): gpt-4o-mini에 비전 입력 + 한글 필드명을 같이 주면
# 구조화 출력이 깨진다(필드명이 제어문자로 뭉개짐) — 텍스트 입력에서는 안 생기는 문제다. 그래서
# 이미지만 영문 슬롯명으로 받고 여기서 한글 슬롯으로 옮긴다.
class _SpecExtractionImage(BaseModel):
    cpu: str | None = None
    gpu: str | None = None
    ram: str | None = None
    motherboard: str | None = None
    storage: str | None = None
    psu: str | None = None
    case_: str | None = None
    cooler: str | None = None


_IMAGE_SLOT_MAP = {"cpu": "CPU", "gpu": "GPU", "ram": "RAM", "motherboard": "메인보드",
                   "storage": "저장장치", "psu": "파워", "case_": "케이스", "cooler": "쿨러"}


def available() -> bool:
    return (not MOCK_MODE and SPEC_EXTRACTION_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


def _clean(draft: _SpecExtraction) -> dict[str, str]:
    return {slot: value.strip() for slot, value in draft.model_dump().items() if value and value.strip()}


def extract(text: str) -> dict[str, str]:
    """텍스트에서 슬롯별 사양 문구를 뽑는다. 값이 없거나 공백뿐인 슬롯은 결과에서 뺀다.

    호출 전에 `available()`을 보는 건 호출자 몫이다. 이 함수 자체는 실패하면 예외를 그대로
    올린다 — 규칙 경로로 바꿀지는 호출자가 정한다(conditions_agent.run_turn과 같은 계약)."""
    draft = _SpecExtraction.model_validate(
        call_llm(text[:_MAX_INPUT_CHARS], system=SPEC_EXTRACTION_SYSTEM, output_schema=_SpecExtraction.model_json_schema()))
    return _clean(draft)


def extract_from_image(image_data_url: str) -> dict[str, str]:
    """스크린샷 1장(견적·부품 목록이 찍힌 화면)에서 슬롯별 사양 문구를 뽑는다. 텍스트 추출과 같은
    판정 경계를 쓴다 — 다른 건 입력이 이미지라는 것과, 그래서 영문 스키마를 쓰고 한글 슬롯으로
    다시 옮긴다는 것뿐이다(위 _SpecExtractionImage 주석 참고).

    비전 호출은 가끔 답을 {"properties": {...}} 로 한 번 더 감싼다(관측된 동작, 텍스트 입력에서는
    안 그런다) — 스키마의 필드명이 최상위에 하나도 없으면 그 감싼 값을 대신 검증한다.

    텍스트 경로(extract)와 달리 규칙 기반 fallback이 없다 — 이미지에서 문구를 규칙으로 뽑을 방법이
    없다. `available()`이 False이거나 이 함수가 예외를 올리면, 호출자는 "확인 못 함"으로 알려야
    한다(조용히 빈 결과로 넘기면 "사진에 아무것도 없었다"와 "서버가 못 봤다"가 구분이 안 된다).
    이미지 원본은 호출이 끝나면 버려진다 — 저장하지 않는다."""
    raw = call_llm_vision(image_data_url, system=SPEC_EXTRACTION_IMAGE_SYSTEM,
                          output_schema=_SpecExtractionImage.model_json_schema())
    if isinstance(raw, dict) and not (set(raw) & set(_IMAGE_SLOT_MAP)) and isinstance(raw.get("properties"), dict):
        raw = raw["properties"]
    draft = _SpecExtractionImage.model_validate(raw)
    return {_IMAGE_SLOT_MAP[slot]: value.strip()
            for slot, value in draft.model_dump().items() if value and value.strip()}
