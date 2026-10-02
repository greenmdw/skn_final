"""DB 미보유 부품·주변기기 실시간 스펙 검색 — docs/미보유부품_실시간스펙검색_설계.md.

3단계(이 파일의 현재 범위): 검색 호출 → 검증(critique) → 캐시 읽기/쓰기까지 — pc_check 연동은
4단계에서 이어서 추가한다(아직 없음, `lookup()`을 부르는 라우터 코드는 없다).

`SupportedFields`의 필드명은 src/engine/owned_parts.py가 이미 쓰는 specs 키(`_SPEC_LABEL`)와
한 글자도 다르면 안 된다 — 다르면 호환성 검사 로직이 이 결과를 못 읽는다.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.clients.llm_client import call_llm, call_web_search
from src.config import LIVE_PART_LOOKUP, LIVE_SPEC_LOOKUP_TTL_DAYS, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY
from src.engine.prompts import LIVE_SPEC_LOOKUP_SYSTEM
from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo


class SupportedFields(BaseModel):
    """스니펫에 실제로 적힌 값만 채운다(비어 있으면 null) — 지어낸 값 금지(프롬프트 규칙 2·3).

    extra="forbid" — 모델이 스키마 밖 필드(owned_parts.py가 모르는 키)를 지어내면 조용히
    버리지 않고 검증에서 걸린다."""

    model_config = ConfigDict(extra="forbid")

    socket: str | None = None
    mem_type: str | None = None
    wattage_w: int | None = None
    speed_mts: int | None = None
    capacity_gb: int | None = None
    module_config: str | None = None
    form_factor: str | None = None
    supports_form_factors: str | None = None
    cooling_type: str | None = None
    radiator_mm: int | None = None
    height_mm: int | None = None
    interface: str | None = None


class LiveSpecLookupResult(BaseModel):
    """live_spec_lookup_system()의 구조화 출력 계약.

    relevant=False 이거나 supported_fields가 전부 비어 있으면 호출자는 기존처럼
    "모름"으로 폴백한다(설계 문서 §3) — 이 모델 자체는 그 폴백 판단을 하지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    relevant: bool
    supported_fields: SupportedFields = Field(default_factory=SupportedFields)
    source_url: str | None = None

    def has_any_field(self) -> bool:
        return any(v is not None for v in self.supported_fields.model_dump().values())


def available() -> bool:
    """spec_extraction_agent.available()과 같은 패턴 — opt-in 플래그 꺼짐·MOCK_MODE·키 없음이면
    호출자(4단계 라우터)가 이걸 보고 기존처럼 조용히 건너뛴다."""
    return LIVE_PART_LOOKUP and not MOCK_MODE and LLM_PROVIDER == "openai" and bool(OPENAI_API_KEY)


def _query_text(brand: str, model: str) -> str:
    return f"{brand} {model} 정식 스펙"


def _from_row(row: dict) -> LiveSpecLookupResult:
    return LiveSpecLookupResult.model_validate({
        "relevant": row["relevant"], "supported_fields": row["supported_fields"], "source_url": row["source_url"],
    })


def lookup(conn, *, brand: str, model: str) -> LiveSpecLookupResult:
    """카탈로그에 없는 부품 하나를 실시간 검색+검증한다 — 캐시 히트면 검색·LLM 호출 없이 바로 반환.

    호출 전에 `available()`을 보는 건 호출자 몫이다(기존 에이전트들과 같은 계약) — 이 함수 자체는
    실패하면 예외를 그대로 올린다. relevant=False(검증 실패)도 그대로 캐싱한다(§4) — 같은 질의를
    또 비용 들여 재검색하지 않되, 호출자는 그 결과를 보고 "모름"으로 폴백해야 한다.
    """
    repo = LiveSpecLookupRepo(conn)
    query_text = _query_text(brand, model)

    cached = repo.get_fresh(query_text, ttl_days=LIVE_SPEC_LOOKUP_TTL_DAYS)
    if cached is not None:
        return _from_row(cached)

    search = call_web_search(query_text)
    prompt = (f"질문: {brand} {model}\n검색 스니펫:\n{search['text']}\n"
             f"스니펫 출처 URL: {search['source_url'] or '(없음)'}")
    raw = call_llm(prompt, system=LIVE_SPEC_LOOKUP_SYSTEM, output_schema=LiveSpecLookupResult.model_json_schema())
    result = LiveSpecLookupResult.model_validate(raw)

    row = repo.upsert(query_text=query_text, brand=brand, model=model, relevant=result.relevant,
                      supported_fields=result.supported_fields.model_dump(), source_url=result.source_url)
    return _from_row(row)
