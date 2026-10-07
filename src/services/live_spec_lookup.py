"""DB 미보유 부품·주변기기 실시간 스펙 검색 — docs/미보유부품_실시간스펙검색_설계.md.

검색 호출 → 검증(critique) → 임시 부품 저장소(catalog.live_spec_lookup_cache) 읽기/쓰기.
같은 부품은 가격·수량·상품코드가 달라도 같은 키(`normalize_lookup_key`)로 묶여 재검색하지 않는다(§9).
저장소는 카탈로그가 아니다 — 후보·가격 비교·합계에 연결되지 않는다.

`SupportedFields`의 필드명은 src/engine/owned_parts.py가 이미 쓰는 specs 키(`_SPEC_LABEL`)와
한 글자도 다르면 안 된다 — 다르면 호환성 검사 로직이 이 결과를 못 읽는다.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import APIConnectionError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from src.auth import ratelimit
from src.clients.llm_client import call_llm, call_web_search
from src.config import (
    LIVE_LOOKUP_GLOBAL_LIMIT_PER_MIN, LIVE_LOOKUP_MAX_CONCURRENCY, LIVE_PART_LOOKUP, LIVE_REFERENCE_PRICE,
    LIVE_REFERENCE_PRICE_TTL_DAYS, LIVE_SPEC_LOOKUP_FOUND_TTL_DAYS, LIVE_SPEC_LOOKUP_NOTFOUND_TTL_DAYS, LLM_PROVIDER,
    MOCK_MODE, OPENAI_API_KEY,
)
from src.engine.owned_parts import _is_model_token, _significant, _tokens
from src.engine.part_values import (
    canonical_board_form, canonical_case_forms, canonical_cooler_sockets, canonical_cooling_type, canonical_ddr,
    canonical_psu_form, canonical_socket,
)
from src.engine.prompts import LIVE_REFERENCE_PRICE_RULES, LIVE_SPEC_LOOKUP_SYSTEM
from src.engine.quote_price import MAX_PRICE, MIN_PRICE, strip_price
from src.engine.stage2_requirement import normalize_pc_slot
from src.errors import ServiceUnavailable
from src.repo.live_spec_lookup_repo import LiveSpecLookupRepo

log = logging.getLogger(__name__)


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


class _LiveSpecLookupResultWithPrice(LiveSpecLookupResult):
    """LIVE_REFERENCE_PRICE=1 일 때만 쓰는 출력 계약 — 참고가 한 칸이 더 있다(설계 §9.7)."""

    reference_price: int | None = None


@dataclass(frozen=True)
class LookupOutcome:
    """검색 결과 + 저장소 메타(신선도·검토 상태·참고가). 화면과 대화 에이전트가 필요한 만큼만 쓴다."""

    result: LiveSpecLookupResult
    fetched_at: datetime | None
    status: str                      # unreviewed | confirmed | rejected
    cached: bool
    reference_price: int | None = None
    reference_price_source_url: str | None = None
    reference_price_at: datetime | None = None


# 슬롯별로 의미 있는 필드(설계 §10.5-1). 스키마는 슬롯을 구분하지 않아 모델이 파워의 cooling_type 에 팬을,
# 메인보드의 capacity_gb 에 "최대 메모리"를 넣는 식으로 어긋난 값을 채웠다(2026-10-04 평가). 코드가 슬롯에
# 맞는 필드만 통과시킨다. 표에 없는 슬롯(또는 슬롯을 모르는 호출)은 거르지 않는다.
SLOT_FIELDS: dict[str, frozenset[str]] = {
    "CPU": frozenset({"socket", "mem_type"}),
    "GPU": frozenset({"interface"}),
    "RAM": frozenset({"mem_type", "speed_mts", "capacity_gb", "module_config", "height_mm"}),
    "메인보드": frozenset({"socket", "mem_type", "form_factor"}),
    "저장장치": frozenset({"capacity_gb", "interface", "form_factor"}),
    "파워": frozenset({"wattage_w", "form_factor", "module_config"}),
    "케이스": frozenset({"supports_form_factors"}),
    "쿨러": frozenset({"cooling_type", "radiator_mm", "height_mm", "socket"}),
}


def filter_fields_for_slot(slot: str | None, fields: dict) -> dict:
    """슬롯에 의미 없는 필드를 버린다. 슬롯을 모르거나 표에 없으면 그대로 돌려준다."""
    canonical = (normalize_pc_slot(slot) or slot) if slot else None
    allowed = SLOT_FIELDS.get(canonical) if canonical else None
    return dict(fields) if allowed is None else {k: v for k, v in fields.items() if k in allowed}


_RAM_KIT_A = re.compile(r"(\d{1,3})\s*GB?\s*[x×*]\s*(\d{1,2})\b", re.IGNORECASE)      # 16GB x 2
_RAM_KIT_B = re.compile(r"\b(\d{1,2})\s*[x×*]\s*(\d{1,3})\s*GB?\b", re.IGNORECASE)     # 2 x 16GB
_RAM_SINGLE = re.compile(r"단품|낱개|싱글|single|\b1\s*(?:개|pcs?|stick|module|x)\b", re.IGNORECASE)


def _ram_module_config(capacity, module_config) -> tuple[Any, str | None]:
    """검색이 준 RAM 구성 문장 → (총용량, "낱개GB × 개수"). 카탈로그와 같은 표기라 견적 수량 곱셈이 그대로 먹는다.
    키트("2 x 16GB")면 총용량도 낱개 × 개수로 맞추고, 단품이면 용량 × 1, 읽을 수 없는 문장은 구성만 버린다."""
    text = str(module_config or "")
    kit = _RAM_KIT_A.search(text)
    if kit:
        each, count = int(kit.group(1)), int(kit.group(2))
    else:
        kit = _RAM_KIT_B.search(text)
        each, count = (int(kit.group(2)), int(kit.group(1))) if kit else (None, None)
    if each:
        return each * count, f"{each}GB × {count}"
    if (_RAM_SINGLE.search(text) or not text.strip()) and isinstance(capacity, (int, float)) and capacity > 0:
        each = int(capacity) if float(capacity).is_integer() else capacity
        return capacity, f"{each}GB × 1"
    return capacity, None


def normalize_fields(slot: str | None, fields: dict) -> dict:
    """문장·제각각 표기인 값을 엔진이 읽는 표기로 맞추고, 하나로 정해지지 않는 값은 버린다(engine/part_values.py).

    메모리 규격(DDR)과 냉각 방식은 슬롯을 몰라도 맞추고, 소켓·폼팩터는 슬롯에 따라 뜻이 달라 슬롯을 알 때만 맞춘다
    (쿨러의 socket 은 지원 소켓 목록이라 카탈로그 표기로 다시 쓴다)."""
    canonical = (normalize_pc_slot(slot) or slot) if slot else None
    out = dict(fields)

    def put(key: str, value) -> None:
        if value:
            out[key] = value
        else:
            out.pop(key, None)

    if canonical == "RAM" and out.get("module_config") is not None:
        capacity, config = _ram_module_config(out.get("capacity_gb"), out["module_config"])
        put("module_config", config)
        if config and capacity is not None:
            out["capacity_gb"] = capacity
    if "mem_type" in out:
        put("mem_type", canonical_ddr(out["mem_type"]))
    if "cooling_type" in out:
        put("cooling_type", canonical_cooling_type(out["cooling_type"]))
    if "socket" in out and canonical in ("CPU", "메인보드"):
        put("socket", canonical_socket(out["socket"]))
    elif "socket" in out and canonical == "쿨러":
        put("socket", canonical_cooler_sockets(out["socket"]))      # 지원 소켓 목록 — 카탈로그 표기로
    if "form_factor" in out:
        if canonical == "메인보드":
            put("form_factor", canonical_board_form(out["form_factor"]))
        elif canonical == "파워":
            put("form_factor", canonical_psu_form(out["form_factor"]))
    if "supports_form_factors" in out:
        forms = canonical_case_forms(out["supports_form_factors"])
        put("supports_form_factors", " / ".join(forms) if forms else None)
    return out


def clean_fields(slot: str | None, fields: dict) -> dict:
    """슬롯에 의미 있는 필드만 남기고(filter_fields_for_slot) 그 값을 엔진 표기로 맞춘다(normalize_fields)."""
    return normalize_fields(slot, filter_fields_for_slot(slot, fields))


# ── 이름 확인(코드) ──────────────────────────────────────────────────────────────────────────
_UNIT_NUMBER = re.compile(r"^(\d+)(?:w|gb|tb|mm|hz|mhz|mts)$")
_MIN_IDENTITY_LEN = 3
_CAPACITY_SHORTHAND = re.compile(r"^\d{1,3}g$")      # "32G" — 쇼핑몰이 붙인 용량 표기. 제품 모델 번호가 아니다(5600G 같은 네 자리는 모델이다)


def _identity_tokens(name: str) -> set[str]:
    """질문한 제품을 가려내는 낱말 — 숫자가 든 모델 번호(RM1999x, 19900k, 9999). 짧은 것(i9·z1)과 DDR 세대·용량은 뺀다."""
    out: set[str] = set()
    for token in _significant(_tokens(name)):
        if not _is_model_token(token) or re.fullmatch(r"ddr[345]", token) or _CAPACITY_SHORTHAND.match(token):
            continue
        match = _UNIT_NUMBER.match(token)
        token = match.group(1) if match else token          # 850W → 850
        if len(token) >= _MIN_IDENTITY_LEN:
            out.add(token)
    return out


def snippet_mentions_the_product(name: str, snippet: str) -> bool:
    """검색 결과 글에 질문한 제품의 모델 번호가 모두 나오는가. 없는 제품은 검색해도 모델 번호가 나올 곳이 없다 — 일반
    페이지(예: 삼성 DRAM 소개)만 잡히면 LLM 이 그 글의 일반 값(DDR5)을 이 제품 값으로 옮기는 오탐이 있었다(F01).
    모델 번호로 쓸 낱말이 없으면(Dark Rock Pro 5 등) 판단하지 않고 통과시킨다."""
    need = _identity_tokens(name)
    if not need:
        return True
    have = set(_tokens(snippet))
    have |= {m.group(1) for t in have if (m := _UNIT_NUMBER.match(t))}
    return need <= have


def available() -> bool:
    """spec_extraction_agent.available()과 같은 패턴 — opt-in 플래그 꺼짐·MOCK_MODE·키 없음이면
    호출자(4단계 라우터)가 이걸 보고 기존처럼 조용히 건너뛴다."""
    return LIVE_PART_LOOKUP and not MOCK_MODE and LLM_PROVIDER == "openai" and bool(OPENAI_API_KEY)


# ── 조회 키 정규화 (설계 §9.3-1) ─────────────────────────────────────────────────────────────
_BRACKETS = re.compile(r"[\[\](){}（）]")
# "x2" "× 2" "*2" "2개" "수량 2" — 5800X3D 같은 모델명 속 X3 는 뒤에 D 가 붙어 \b 에서 걸러진다.
_QUANTITY = re.compile(r"(?<![\d.])(?:[x×*]\s*\d{1,2}(?:\s*ea)?\b|\d{1,2}\s*(?:개|ea)\b|수량\s*:?\s*\d{1,2}\b)", re.IGNORECASE)
# 쇼핑몰이 이름 앞에 붙이는 묶음 용량 표기("[DDR5 32G]" = 16GB 두 개의 합) — 제품 이름이 아니라 검색을 흐리고 모델 번호로 오인된다.
_BUNDLE_LABEL = re.compile(r"\[\s*(?:DDR[345]\s*)?\d{1,3}\s*(?:GB|G|TB)\s*\]", re.IGNORECASE)
_CHANNEL = re.compile(r"(?:듀얼|싱글|쿼드|트리플)\s*채널|(?:dual|single|quad)\s*channel", re.IGNORECASE)
_TRAILING_TIMES = re.compile(r"(?:^|\s)[x×*]\s*$", re.IGNORECASE)
# 추출 결과에 따라 이름 앞에 "메모리:" 같은 부품군 이름표가 붙기도 하고 안 붙기도 한다 — 같은 제품이 다른 키가 되지 않게 뗀다.
_LEADING_LABEL = re.compile(
    r"^\s*(?:cpu|프로세서|쿨러|cooler|메인보드|mainboard|메모리|ram|그래픽카드|그래픽|gpu|vga|ssd|저장장치|hdd|파워|psu|케이스|case)\s*[:：]\s*",
    re.IGNORECASE)
_PRODUCT_CODE = re.compile(r"(?<![\w-])\d{6,}(?![\w-])")          # 다나와 상품코드 등 6자리 이상 숫자만의 낱말
_SEPARATORS = re.compile(r"[\s\-–—:/|,·]+")


def _clean_name(part_text: str) -> str:
    """견적 원문에서 가격·수량·상품코드·괄호를 걷어 낸 부품 이름(대소문자는 그대로 — 검색 질의에 쓴다).

    용량(16GB)과 모델 토큰(5600 vs 5600X)은 남긴다 — 이걸 지우면 다른 제품이 같은 키로 합쳐진다."""
    text = _LEADING_LABEL.sub("", strip_price(part_text))
    text = _BUNDLE_LABEL.sub(" ", text)
    text = _BRACKETS.sub(" ", text)
    text = _CHANNEL.sub(" ", text)
    text = _QUANTITY.sub(" ", text)
    text = _PRODUCT_CODE.sub(" ", text)
    text = _TRAILING_TIMES.sub(" ", _SEPARATORS.sub(" ", text).strip())      # "…(16GB) x" 처럼 수량이 걷힌 뒤 남은 곱하기 기호
    return _SEPARATORS.sub(" ", text).strip()


def normalize_lookup_key(part_text: str) -> str:
    """저장소 조회 키 — 같은 제품이면 견적 가격·수량·상품코드·표기 차이와 무관하게 같은 값이 된다."""
    return _clean_name(part_text).lower()


def _search_query(name: str) -> str:
    return f"{name} 정식 스펙 현재 판매 가격" if LIVE_REFERENCE_PRICE else f"{name} 정식 스펙"


def _from_row(row: dict, slot: str | None = None) -> LiveSpecLookupResult:
    if row["status"] == "rejected":                  # 사람이 틀렸다고 한 값 — 못 찾음으로 취급
        return LiveSpecLookupResult(relevant=False)
    return LiveSpecLookupResult.model_validate({
        "relevant": row["relevant"], "supported_fields": clean_fields(slot, row["supported_fields"] or {}),
        "source_url": row["source_url"],
    })


def _valid_price(value: Any) -> int | None:
    """LLM 이 적은 금액이 가격으로 볼 수 있는 범위인지 코드가 확인한다(engine.quote_price 와 같은 범위)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if MIN_PRICE <= value <= MAX_PRICE else None


def _outcome(row: dict, *, cached: bool, slot: str | None = None) -> LookupOutcome:
    price, price_at = row.get("reference_price"), row.get("reference_price_at")
    if not LIVE_REFERENCE_PRICE or row["status"] == "rejected" or price is None or price_at is None:
        price = price_at = None
    elif datetime.now(timezone.utc) - price_at > timedelta(days=LIVE_REFERENCE_PRICE_TTL_DAYS):
        price = price_at = None                      # 가격은 스펙보다 빨리 변한다 — 오래된 참고가는 내지 않는다
    return LookupOutcome(
        result=_from_row(row, slot), fetched_at=row["fetched_at"], status=row["status"], cached=cached,
        reference_price=price, reference_price_source_url=row.get("reference_price_source_url") if price else None,
        reference_price_at=price_at)


_SEARCH_SLOTS = threading.BoundedSemaphore(max(1, LIVE_LOOKUP_MAX_CONCURRENCY))
_SLOT_WAIT_SECONDS = 30.0
_RATE_LIMIT_RETRY_WAIT_SECONDS = 4.0     # 토큰 한도(429)에 걸리면 한 번만 잠깐 기다렸다 다시(테스트에서 0으로)


def _busy() -> ServiceUnavailable:
    return ServiceUnavailable("지금 검색 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요.", code="live_part_lookup_busy")


def _call_guarded(fn, *args, **kwargs):
    """OpenAI 호출의 한도 초과(429)·연결 실패를 호출자가 다룰 수 있는 503 으로 바꾼다(설계 §10.5-2).
    한도 초과는 한 번 짧게 기다렸다 다시 시도한다 — 평가에서 웹 검색 1회가 약 1만 3천 토큰이라 분당 한도에
    쉽게 닿는 것이 확인됐다. 그 밖의 오류(스키마 검증 실패 등)는 숨기지 않고 그대로 올린다."""
    try:
        return fn(*args, **kwargs)
    except RateLimitError as first:
        time.sleep(_RATE_LIMIT_RETRY_WAIT_SECONDS)
        try:
            return fn(*args, **kwargs)
        except (RateLimitError, APIConnectionError) as exc:
            raise _busy() from first
    except APIConnectionError as exc:                # APITimeoutError 포함
        raise _busy() from exc


def lookup_with_meta(conn, part_text: str, *, slot: str | None = None, brand: str | None = None,
                     model: str | None = None) -> LookupOutcome:
    """카탈로그에 없는 부품 하나를 검색+검증한다 — 저장소에 쓸 만한 결과가 있으면 검색·LLM 호출 없이 바로 반환.

    part_text는 pc_check가 이미 들고 있는 "대응 안 됨" 슬롯의 원문 그대로다(가격·수량이 붙어 있어도
    된다 — 키와 검색 질의는 이름만 남겨 쓴다). brand/model은 저장소에 남기는 참고 메타데이터일 뿐이다.

    호출 전에 `available()`을 보는 건 호출자 몫이다(기존 에이전트들과 같은 계약) — 이 함수 자체는
    실패하면 예외를 그대로 올린다. relevant=False(검증 실패)도 저장한다(§4) — 같은 질의를 또 비용 들여
    재검색하지 않되, 호출자는 그 결과를 보고 "모름"으로 폴백해야 한다."""
    name = _clean_name(part_text)
    key = name.lower()
    if not key:                                      # 가격 같은 숫자만 남은 입력 — 검색할 이름이 없다
        return LookupOutcome(result=LiveSpecLookupResult(relevant=False), fetched_at=None,
                             status="unreviewed", cached=False)
    repo = LiveSpecLookupRepo(conn)

    cached = repo.get_fresh(key, found_ttl_days=LIVE_SPEC_LOOKUP_FOUND_TTL_DAYS,
                            notfound_ttl_days=LIVE_SPEC_LOOKUP_NOTFOUND_TTL_DAYS)
    if cached is not None:
        return _outcome(cached, cached=True, slot=slot)

    query = _search_query(name)
    # 저장소에 없어 OpenAI 를 불러야 하는 요청만 서비스 전체 상한을 거친다(설계 §10.5-2, config 주석 참고).
    if not ratelimit.allow("live-lookup-global", limit=LIVE_LOOKUP_GLOBAL_LIMIT_PER_MIN, window_seconds=60):
        raise _busy()
    if not _SEARCH_SLOTS.acquire(timeout=_SLOT_WAIT_SECONDS):
        raise _busy()
    try:
        return _search_and_verify(conn, repo, name, key, query, slot, brand, model)
    finally:
        _SEARCH_SLOTS.release()


def _search_and_verify(conn, repo, name: str, key: str, query: str, slot, brand, model) -> LookupOutcome:
    search = _call_guarded(call_web_search, query)
    if not snippet_mentions_the_product(name, search["text"]):
        # 검색 글에 이 제품의 모델 번호가 없다 — LLM 검증을 부르지 않고 "못 찾음"으로 저장한다(비용도 아낀다).
        log.info("live lookup: %r — 검색 글에 모델 번호 %s 없음, 못 찾음 처리", name, sorted(_identity_tokens(name)))
        row = repo.upsert(lookup_key=key, query_text=query, brand=brand, model=model, relevant=False,
                          supported_fields={}, source_url=search.get("source_url"))
        return _outcome(row, cached=False, slot=slot)
    kind = f"부품 종류: {normalize_pc_slot(slot) or slot}\n" if slot else ""
    prompt = (f"질문: {name}\n{kind}검색 스니펫:\n{search['text']}\n"
              f"스니펫 출처 URL: {search['source_url'] or '(없음)'}")
    schema, system = LiveSpecLookupResult, LIVE_SPEC_LOOKUP_SYSTEM
    if LIVE_REFERENCE_PRICE:
        schema, system = _LiveSpecLookupResultWithPrice, LIVE_SPEC_LOOKUP_SYSTEM + "\n" + LIVE_REFERENCE_PRICE_RULES
    raw = _call_guarded(call_llm, prompt, system=system, output_schema=schema.model_json_schema())
    parsed = schema.model_validate(raw)

    price = _valid_price(getattr(parsed, "reference_price", None)) if parsed.relevant else None
    row = repo.upsert(lookup_key=key, query_text=query, brand=brand, model=model, relevant=parsed.relevant,
                      supported_fields=parsed.supported_fields.model_dump(), source_url=parsed.source_url,
                      reference_price=price, reference_price_source_url=parsed.source_url if price else None)
    return _outcome(row, cached=False, slot=slot)


def lookup(conn, part_text: str, *, slot: str | None = None, brand: str | None = None,
           model: str | None = None) -> LiveSpecLookupResult:
    """`lookup_with_meta`의 결과만 — 신선도·참고가가 필요 없는 호출자(대화 에이전트)가 쓴다."""
    return lookup_with_meta(conn, part_text, slot=slot, brand=brand, model=model).result


def has_stored_value(conn, part_text: str, slot: str | None) -> bool:
    """이 부품의 실시간 검색 값이 저장소에 있고 쓸 만한가(만료 안, 사람이 거부하지 않음, 값이 하나라도 있음). 읽기만 한다."""
    key = normalize_lookup_key(part_text)
    if conn is None or not key:
        return False
    row = LiveSpecLookupRepo(conn).get_fresh(key, found_ttl_days=LIVE_SPEC_LOOKUP_FOUND_TTL_DAYS,
                                             notfound_ttl_days=LIVE_SPEC_LOOKUP_NOTFOUND_TTL_DAYS)
    if not row or not row["relevant"] or row["status"] == "rejected":
        return False
    return any(v is not None for v in clean_fields(slot, row["supported_fields"] or {}).values())


def cached_for_kept_parts(conn, owned: dict, current_specs: Any) -> None:
    """업그레이드 모드 확장(6단계) — 유지하는 부품(owned) 중 대응 실패(unverified)한 슬롯을, 사용자가 받은
    견적 점검에서 이미 눌러 둔 실시간 검색 결과(저장소, 만료 안)가 있으면 그 값으로 보강한다.

    새로 검색하지 않는다 — 저장소를 읽기만 한다. pc_check 버튼(명시적 사용자 행동)으로 이미 채워진 값이
    없으면 그대로 unverified로 남는다(설계 문서 §8 자동 실행 금지 원칙: 로그인 없는 추천 계산마다
    검색이 자동으로 돌면 비용·오남용 위험이 있다). 사람이 rejected 한 행은 쓰지 않는다.

    owned의 specs 키가 socket·mem_type 같은 호환성 축일 뿐 perf_tier(성능 등급)는 여기 없다 — 교체
    대상 부품의 성능 등급 하한(current_part_tiers)은 이 저장소로 메울 수 없다. 이건 호환성 보강이지
    성능 등급 추정이 아니다."""
    if conn is None or not isinstance(current_specs, dict) or not owned:
        return                             # DB 없이 도는 순수 계산(테스트·미리보기)은 저장소를 읽지 않는다
    from src.engine.owned_parts import merge_live_lookup
    from src.engine.stage2_requirement import normalize_pc_slot

    given = {(normalize_pc_slot(k) or str(k).strip()): v for k, v in current_specs.items()}
    repo = LiveSpecLookupRepo(conn)
    cached: dict[str, dict] = {}
    for slot, info in owned.items():
        if info.get("source") not in ("unverified", "text", "inferred"):
            continue                       # 카탈로그 대응(catalog)·가장 비슷한 제품(candidate)의 값은 그대로 둔다
        key = normalize_lookup_key(str(given.get(slot) or ""))
        if not key:
            continue
        row = repo.get_fresh(key, found_ttl_days=LIVE_SPEC_LOOKUP_FOUND_TTL_DAYS,
                             notfound_ttl_days=LIVE_SPEC_LOOKUP_NOTFOUND_TTL_DAYS)
        if row and row["status"] != "rejected":
            cached[slot] = {**row, "supported_fields": clean_fields(slot, row["supported_fields"] or {})}
    merge_live_lookup(owned, current_specs, cached)
